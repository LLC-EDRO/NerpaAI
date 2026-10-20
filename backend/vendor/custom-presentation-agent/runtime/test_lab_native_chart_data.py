"""Native chart data regression tests, including real editable PPTX packages."""
import io
import math
import unittest
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from lxml import etree
from runtime.security import NS, xml
from runtime.charts import chart_spec, fill_chart, validate_charts, prepare_chart_render
from runtime.chart_workbook import ChartWorkbook, S, SHEET_NS, parse_reference, column_name

try:
    from pptx import Presentation
    from pptx.chart.data import XyChartData, CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
except ImportError:
    Presentation = None

def pack(parts):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in parts.items():archive.writestr(name,data)
    return output.getvalue()

def unpack(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:return {name:archive.read(name) for name in archive.namelist()}

@unittest.skipUnless(Presentation is not None,'python-pptx is required only for real PPTX regression fixtures')
class NativeChartData(unittest.TestCase):
    def fixture(self,kind='xy',counts=(31,27)):
        prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
        if kind=='xy':
            data=XyChartData()
            for i,count in enumerate(counts):
                s=data.add_series(f'Series {i+1}')
                for n in range(count):s.add_data_point(n-count/2+i*.25,n*n/8-count)
            chart_kind=XL_CHART_TYPE.XY_SCATTER_LINES
        else:
            data=CategoryChartData();data.categories=[f'Category {n}' for n in range(counts[0])]
            for i in range(len(counts)):data.add_series(f'Series {i+1}',[n+i+.004429 for n in range(counts[0])])
            chart_kind=XL_CHART_TYPE.PIE if kind=='pie' else XL_CHART_TYPE.COLUMN_CLUSTERED if kind=='bar' else XL_CHART_TYPE.LINE
        shape=slide.shapes.add_chart(chart_kind, Inches(1), Inches(1), Inches(8), Inches(5),data)
        chart=shape.chart;chart.has_title=True;chart.chart_title.text_frame.text='Original chart'
        output=io.BytesIO();prs.save(output);parts=unpack(output.getvalue())
        part='ppt/charts/chart1.xml';root=xml(parts[part])
        for s in root.findall('.//c:ser',NS):
            props=etree.SubElement(s,'{%s}spPr'%NS['c']);line=etree.SubElement(props,'{%s}ln'%NS['a'],w='25400')
            fill=etree.SubElement(line,'{%s}solidFill'%NS['a']);etree.SubElement(fill,'{%s}srgbClr'%NS['a'],val='123ABC')
            for code in s.findall('.//c:numCache/c:formatCode',NS):code.text='0.000000'
        parts[part]=etree.tostring(root)
        bookname=next(name for name in parts if name.endswith('.xlsx'))
        wb=unpack(parts[bookname]);sheet=xml(wb['xl/worksheets/sheet1.xml'])
        row=etree.SubElement(sheet.find('s:sheetData',S),'{%s}row'%SHEET_NS,r='99')
        cell=etree.SubElement(row,'{%s}c'%SHEET_NS,r='Z99',t='inlineStr')
        etree.SubElement(etree.SubElement(cell,'{%s}is'%SHEET_NS),'{%s}t'%SHEET_NS).text='Unrelated source cell'
        row=etree.SubElement(sheet.find('s:sheetData',S),'{%s}row'%SHEET_NS,r='100')
        cell=etree.SubElement(row,'{%s}c'%SHEET_NS,r='Z100')
        etree.SubElement(cell,'{%s}f'%SHEET_NS).text='2+3';etree.SubElement(cell,'{%s}v'%SHEET_NS).text='5'
        sheet.find('s:sheetData/s:row[@r="2"]/s:c[@r="B2"]',S).set('s','0')
        wb['xl/worksheets/sheet1.xml']=etree.tostring(sheet)
        parts[bookname]=pack(wb)
        return parts,SimpleNamespace(media_id=part,shape_id=shape.shape_id)

    def value(self,spec,counts=None):
        counts=counts or spec['seriesPointCounts']
        if spec['dataKind']=='xy':
            return dict(kind='xy',title='New chart',series=[dict(name=f'New series {i}',points=[dict(x=(n+1)*(-1 if i==0 else 1)+i/4,y=n/7-i-.004429) for n in range(count)]) for i,count in enumerate(counts)])
        return dict(title='New chart',categories=[f'New category {n}' for n in range(counts[0])],series=[dict(name=f'New series {i}',values=[n/7-i-.004429 for n in range(counts[0])]) for i in range(spec['seriesCount'])])

    def filled(self,parts,item,value):
        spec=chart_spec(item,parts)
        slide=xml(parts['ppt/slides/slide1.xml']);rels=xml(parts['ppt/slides/_rels/slide1.xml.rels']);types=xml(parts['[Content_Types].xml']);result=dict(parts)
        fill_chart(spec,value,parts,result,slide,rels,0,types)
        result['ppt/slides/slide1.xml']=etree.tostring(slide);result['ppt/slides/_rels/slide1.xml.rels']=etree.tostring(rels);result['[Content_Types].xml']=etree.tostring(types)
        part=f'ppt/charts/nerpaChart1_{item.shape_id}.xml'
        return result,xml(result[part]),result[f'ppt/embeddings/nerpaChart1_{item.shape_id}.xlsx']

    def assert_cached_and_book(self,root,book,value):
        workbook=ChartWorkbook(book)
        series=root.findall('.//c:ser',NS)
        for s,data in zip(series,value['series']):
            entries=(('xVal',[p['x'] for p in data['points']]),('yVal',[p['y'] for p in data['points']])) if value.get('kind')=='xy' else (('val',data['values']),)
            for tag,numbers in entries:
                parent=s.find('c:'+tag,NS)
                self.assertEqual([float(v) for v in parent.xpath('.//c:pt/c:v/text()',namespaces=NS)],numbers)
                self.assertEqual(parent.find('.//c:ptCount',NS).get('val'),str(len(numbers)))
                ref=parent.find('c:numRef/c:f',NS)
                entry,coords=workbook.binding(ref.text,len(numbers))
                actual=[float(workbook.cell(entry[2],*coord,create=False).find('s:v',S).text) for coord in coords]
                self.assertEqual(actual,numbers)

    def source_data(self,parts,item,entries):
        """Keep the native source cache and workbook consistent in a fixture."""
        root=xml(parts[item.media_id]);series=root.find('.//c:ser',NS)
        bookname=next(name for name in parts if name.endswith('.xlsx'));book=ChartWorkbook(parts[bookname])
        for tag,values in entries.items():
            parent=series.find('c:'+tag,NS)
            for node,value in zip(parent.xpath('.//c:pt/c:v',namespaces=NS),values):node.text=str(value)
            book.update(parent.find('.//c:f',NS),values)
        parts[item.media_id]=etree.tostring(root);parts[bookname]=book.serialize()

    def rich_label(self,root,text,index=0,flags=None):
        series=root.find('.//c:ser',NS)
        labels=series.find('c:dLbls',NS)
        if labels is None:labels=etree.SubElement(series,'{%s}dLbls'%NS['c'])
        label=etree.SubElement(labels,'{%s}dLbl'%NS['c']);etree.SubElement(label,'{%s}idx'%NS['c'],val=str(index))
        rich=etree.SubElement(etree.SubElement(label,'{%s}tx'%NS['c']),'{%s}rich'%NS['c'])
        etree.SubElement(rich,'{%s}bodyPr'%NS['a']);etree.SubElement(rich,'{%s}lstStyle'%NS['a'])
        run=etree.SubElement(etree.SubElement(rich,'{%s}p'%NS['a']),'{%s}r'%NS['a'])
        etree.SubElement(run,'{%s}rPr'%NS['a'],sz='2200',b='1');etree.SubElement(run,'{%s}t'%NS['a']).text=text
        for name,on in (flags or {}).items():etree.SubElement(label,'{%s}%s'%(NS['c'],name),val='1' if on else '0')
        return label

    def test_scatter_independent_x_and_counts_native_roundtrip_preserves_style_and_workbook(self):
        parts,item=self.fixture();original=deepcopy(parts);spec=chart_spec(item,parts)
        self.assertEqual(spec['dataKind'],'xy');self.assertEqual(spec['seriesPointCounts'],[31,27])
        self.assertEqual([a['dimension'] for a in spec['axes']],['x','y'])
        value=self.value(spec);validate_charts({'charts':[spec]},{'charts':{spec['key']:value}})
        result,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
        source=xml(parts[item.media_id])
        self.assertEqual(root.xpath('.//c:scatterStyle/@val',namespaces=NS),source.xpath('.//c:scatterStyle/@val',namespaces=NS))
        self.assertEqual(root.xpath('.//c:ser/c:spPr/a:ln/@w',namespaces=NS),['25400','25400'])
        self.assertEqual(root.xpath('.//c:ser/c:spPr/a:ln/a:solidFill/a:srgbClr/@val',namespaces=NS),['123ABC','123ABC'])
        self.assertEqual(root.xpath('.//c:numCache/c:formatCode/text()',namespaces=NS),['0.000000']*4)
        original_book=unpack(next(data for name,data in parts.items() if name.endswith('.xlsx')));updated=unpack(book)
        self.assertEqual(updated['xl/styles.xml'],original_book['xl/styles.xml'])
        sheet=xml(updated['xl/worksheets/sheet1.xml'])
        self.assertEqual(sheet.find('s:sheetData/s:row[@r="2"]/s:c[@r="B2"]',S).get('s'),'0')
        self.assertEqual(sheet.find('s:sheetData/s:row[@r="99"]/s:c[@r="Z99"]/s:is/s:t',S).text,'Unrelated source cell')
        self.assertEqual(sheet.find('s:sheetData/s:row[@r="100"]/s:c[@r="Z100"]/s:f',S).text,'2+3')
        read=Presentation(io.BytesIO(pack(result))).slides[0].shapes[0].chart
        self.assertEqual([len(s.points) for s in read.series],[31,27])
        self.assertEqual(list(read.series[0].iter_values()),[p['y'] for p in value['series'][0]['points']])
        self.assertEqual(parts,original)

    def test_changed_point_counts_create_managed_sheet_without_overwriting_original_cells(self):
        for kind,counts in [('xy',(25,29)),('bar',(25,25)),('line',(29,29))]:
            parts,item=self.fixture(kind,(3,3));spec=chart_spec(item,parts);value=self.value(spec,counts)
            _,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
            original=unpack(next(data for name,data in parts.items() if name.endswith('.xlsx')));updated=unpack(book)
            before=xml(original['xl/worksheets/sheet1.xml']);after=xml(updated['xl/worksheets/sheet1.xml'])
            source_chart=xml(parts[item.media_id])
            names={column_name(col)+str(row) for formula in source_chart.xpath('.//c:ser/c:tx/c:strRef/c:f/text()',namespaces=NS) for col,row in parse_reference(formula)[1]}
            for row in before.findall('s:sheetData/s:row',S):
                for cell in row.findall('s:c',S):
                    if cell.get('r') in names:continue  # Names are intentionally updated.
                    current=after.find(f's:sheetData/s:row[@r="{row.get("r")}"]/s:c[@r="{cell.get("r")}"]',S)
                    self.assertEqual(etree.tostring(current),etree.tostring(cell))
            self.assertEqual(updated['xl/styles.xml'],original['xl/styles.xml'])
            self.assertIn("'Nerpa Data'",''.join(root.xpath('.//c:xVal//c:f/text()|.//c:yVal//c:f/text()|.//c:val//c:f/text()',namespaces=NS)))
            self.assertEqual(len(ChartWorkbook(book).sheets),2)

    def test_log_axes_keep_base_direction_units_and_nonclipping_bounds(self):
        parts,item=self.fixture();root=xml(parts[item.media_id])
        for axis in root.findall('.//c:valAx',NS):
            scaling=axis.find('c:scaling',NS);scaling.insert(0,etree.Element('{%s}logBase'%NS['c'],val='10'))
            scaling.find('c:orientation',NS).set('val','maxMin')
            etree.SubElement(scaling,'{%s}min'%NS['c'],val='.01');etree.SubElement(scaling,'{%s}max'%NS['c'],val='1000')
            etree.SubElement(axis,'{%s}majorUnit'%NS['c'],val='10')
        parts[item.media_id]=etree.tostring(root);spec=chart_spec(item,parts);value=self.value(spec)
        for s in value['series']:
            for point in s['points']:point['x']=abs(point['x'])+.1;point['y']=abs(point['y'])+.1
        _,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
        self.assertEqual(root.xpath('.//c:logBase/@val',namespaces=NS),['10','10'])
        self.assertEqual(root.xpath('.//c:orientation/@val',namespaces=NS),['maxMin','maxMin'])
        self.assertEqual(root.xpath('.//c:scaling/c:min/@val',namespaces=NS),['.01','.01'])
        self.assertEqual(root.xpath('.//c:scaling/c:max/@val',namespaces=NS),['1000','1000'])
        self.assertEqual(root.xpath('.//c:majorUnit/@val',namespaces=NS),['10','10'])
        for invalid in (0,-1,math.inf,True):
            bad=deepcopy(value);bad['series'][0]['points'][0]['x']=invalid
            with self.assertRaises(ValueError):validate_charts({'charts':[spec]},{'charts':{spec['key']:bad}})
        value['series'][0]['points'][0]['x']=2000
        _,root,_=self.filled(parts,item,value)
        self.assertEqual(root.xpath('.//c:scaling/c:max/@val',namespaces=NS),['1000'])
        self.assertEqual(root.xpath('.//c:logBase/@val',namespaces=NS),['10','10'])

    def test_shared_x_reference_can_become_independent_without_corrupting_other_series(self):
        parts,item=self.fixture(counts=(3,3));root=xml(parts[item.media_id]);series=root.findall('.//c:ser',NS)
        series[1].find('c:xVal/c:numRef/c:f',NS).text=series[0].find('c:xVal/c:numRef/c:f',NS).text
        parts[item.media_id]=etree.tostring(root);spec=chart_spec(item,parts);value=self.value(spec)
        _,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
        self.assertNotEqual(*root.xpath('.//c:xVal/c:numRef/c:f/text()',namespaces=NS))

    def test_extreme_finite_coordinates_are_not_capped_rounded_or_turned_into_zero(self):
        parts,item=self.fixture(counts=(3,3));spec=chart_spec(item,parts);value=self.value(spec)
        coordinates=[dict(x=1e300,y=-1e300),dict(x=5e-324,y=5e-324),dict(x=-1e20,y=1e20)]
        value['series'][0]['points']=coordinates
        _,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
        self.assertEqual(root.xpath('.//c:ser[1]/c:xVal//c:pt/c:v/text()',namespaces=NS),['1e+300','5e-324','-1e+20'])
        bad=deepcopy(value);bad['series'][0]['points'][0]['x']=10**500
        with self.assertRaisesRegex(ValueError,'pptx_chart_values_invalid'):validate_charts({'charts':[spec]},{'charts':{spec['key']:bad}})

    def test_category_log_axis_and_large_source_series_are_supported(self):
        parts,item=self.fixture('bar',(31,31));root=xml(parts[item.media_id]);axis=root.find('.//c:valAx',NS)
        axis.find('c:scaling',NS).insert(0,etree.Element('{%s}logBase'%NS['c'],val='2'))
        parts[item.media_id]=etree.tostring(root);spec=chart_spec(item,parts)
        self.assertEqual(spec['pointCount'],31);self.assertEqual(spec['dataKind'],'category')
        value=self.value(spec)
        for s in value['series']:s['values']=[i+.1 for i in range(31)]
        _,root,book=self.filled(parts,item,value);self.assert_cached_and_book(root,book,value)
        self.assertEqual(root.xpath('.//c:logBase/@val',namespaces=NS),['2'])
        value['series'][0]['values'][0]=0
        with self.assertRaisesRegex(ValueError,'pptx_chart_log_value_invalid'):validate_charts({'charts':[spec]},{'charts':{spec['key']:value}})

    def test_category_axes_bind_by_type_when_source_axis_id_order_is_reversed(self):
        parts,item=self.fixture('bar',(3,));source=xml(parts[item.media_id]);plot=source.find('.//c:barChart',NS)
        original_ids=[node.get('val') for node in plot.findall('c:axId',NS)]
        ids=plot.findall('c:axId',NS);ids[0].set('val',original_ids[1]);ids[1].set('val',original_ids[0])
        axis=source.find('.//c:valAx',NS);scaling=axis.find('c:scaling',NS)
        scaling.insert(0,etree.Element('{%s}logBase'%NS['c'],val='10'))
        etree.SubElement(scaling,'{%s}min'%NS['c'],val='1');etree.SubElement(scaling,'{%s}max'%NS['c'],val='10')
        parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts);spec=chart_spec(item,parts)
        self.assertEqual(spec['seriesAxes'],[dict(xAxisId=original_ids[0],yAxisId=original_ids[1])])
        value=dict(title='New',categories=['A','B','C'],series=[dict(name='New',values=[2,4,8])])
        _,updated,_=self.filled(parts,item,value)
        self.assertEqual(updated.xpath('.//c:barChart/c:axId/@val',namespaces=NS),original_ids[::-1])
        self.assertEqual(updated.xpath('.//c:valAx/c:scaling/c:min/@val',namespaces=NS),['1'])
        self.assertEqual(updated.xpath('.//c:valAx/c:scaling/c:max/@val',namespaces=NS),['10'])
        value['categories']=['100','200','300'];value['series'][0]['values']=[.5,4,8]
        _,updated,_=self.filled(parts,item,value)
        self.assertEqual(updated.xpath('.//c:valAx/c:scaling/c:min/@val',namespaces=NS),[])
        self.assertEqual(updated.xpath('.//c:valAx/c:scaling/c:max/@val',namespaces=NS),['10'])
        value['series'][0]['values'][0]=0
        with self.assertRaisesRegex(ValueError,'pptx_chart_log_value_invalid'):validate_charts({'charts':[spec]},{'charts':{spec['key']:value}})
        self.assertEqual(parts,snapshot)

    def test_limits_and_unsupported_originals_fail_without_mutating_source(self):
        parts,item=self.fixture(counts=(3,3));original=deepcopy(parts);spec=chart_spec(item,parts)
        for counts in ((501,3),(0,3)):
            value=self.value(spec,counts)
            with self.assertRaises(ValueError):validate_charts({'charts':[spec]},{'charts':{spec['key']:value}})
        for mutate in (
            lambda root:root.find('.//c:scatterChart',NS).__setattr__('tag','{%s}bubbleChart'%NS['c']),
            lambda root:root.find('.//c:xVal/c:numRef/c:f',NS).__setattr__('text','NamedRange'),
            lambda root:etree.SubElement(root.find('.//c:valAx/c:scaling',NS),'{%s}logBase'%NS['c'],val='1'),
        ):
            changed=deepcopy(parts);root=xml(changed[item.media_id]);mutate(root);changed[item.media_id]=etree.tostring(root);snapshot=deepcopy(changed)
            with self.assertRaises(ValueError):chart_spec(item,changed)
            self.assertEqual(changed,snapshot)
        wb_name=next(name for name in parts if name.endswith('.xlsx'));changed=deepcopy(parts);wb=unpack(changed[wb_name]);sheet=xml(wb['xl/worksheets/sheet1.xml'])
        cell=sheet.find('s:sheetData/s:row[@r="2"]/s:c[@r="B2"]',S);etree.SubElement(cell,'{%s}f'%SHEET_NS).text='A2*A2'
        wb['xl/worksheets/sheet1.xml']=etree.tostring(sheet);changed[wb_name]=pack(wb)
        computed_spec=chart_spec(item,changed);value=self.value(computed_spec)
        _,root,book=self.filled(changed,item,value);self.assert_cached_and_book(root,book,value)
        sheet=xml(unpack(book)['xl/worksheets/sheet1.xml'])
        self.assertEqual(sheet.find('s:sheetData/s:row[@r="2"]/s:c[@r="B2"]/s:f',S).text,'A2*A2')
        self.assertIn("'Nerpa Data'",root.find('.//c:yVal/c:numRef/c:f',NS).text)
        self.assertEqual(parts,original)

    def test_numeric_custom_labels_refresh_exact_value_and_preserve_rich_formatting(self):
        parts,item=self.fixture('bar',(3,3));root=xml(parts[item.media_id]);series=root.find('.//c:ser',NS)
        labels=etree.SubElement(series,'{%s}dLbls'%NS['c']);label=etree.SubElement(labels,'{%s}dLbl'%NS['c']);etree.SubElement(label,'{%s}idx'%NS['c'],val='0')
        rich=etree.SubElement(etree.SubElement(label,'{%s}tx'%NS['c']),'{%s}rich'%NS['c']);etree.SubElement(rich,'{%s}bodyPr'%NS['a']);etree.SubElement(rich,'{%s}lstStyle'%NS['a'])
        paragraph=etree.SubElement(rich,'{%s}p'%NS['a']);run=etree.SubElement(paragraph,'{%s}r'%NS['a']);props=etree.SubElement(run,'{%s}rPr'%NS['a'],sz='2200',b='1');etree.SubElement(run,'{%s}t'%NS['a']).text='0.004429 ms'
        parts[item.media_id]=etree.tostring(root);spec=chart_spec(item,parts);value=self.value(spec);value['series'][0]['values'][0]=.009559
        _,root,_=self.filled(parts,item,value)
        self.assertEqual(root.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),['0.009559 ms'])
        self.assertEqual(root.xpath('.//c:dLbl/c:tx/c:rich//a:rPr/@sz',namespaces=NS),['2200'])
        self.assertEqual(root.xpath('.//c:dLbl/c:tx/c:rich//a:rPr/@b',namespaces=NS),['1'])

    def test_scatter_rich_labels_follow_original_x_or_y_at_their_own_index(self):
        for original,expected in [('1 s','2 s'),('5 ms','6 ms')]:
            with self.subTest(original=original):
                parts,item=self.fixture(counts=(1,));self.source_data(parts,item,{'xVal':[1],'yVal':[5]})
                source=xml(parts[item.media_id]);self.rich_label(source,original)
                parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts)
                spec=chart_spec(item,parts);value=dict(kind='xy',title='New',series=[dict(name='New',points=[dict(x=2,y=6)])])
                _,updated,book=self.filled(parts,item,value);self.assert_cached_and_book(updated,book,value)
                self.assertEqual(updated.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),[expected])
                self.assertEqual(updated.xpath('.//c:dLbl//a:rPr/@sz',namespaces=NS),['2200'])
                self.assertEqual(parts,snapshot)

    def test_numeric_category_label_tracks_category_rather_than_y(self):
        parts,item=self.fixture('bar',(1,));self.source_data(parts,item,{'cat':['2024'],'val':[5]})
        source=xml(parts[item.media_id]);self.rich_label(source,'2024')
        parts[item.media_id]=etree.tostring(source)
        value=dict(title='New',categories=['2025'],series=[dict(name='New',values=[6])])
        _,updated,book=self.filled(parts,item,value);self.assert_cached_and_book(updated,book,value)
        self.assertEqual(updated.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),['2025'])

    def test_pie_percentage_label_tracks_share_rather_than_raw_value(self):
        parts,item=self.fixture('pie',(3,));self.source_data(parts,item,{'val':[2,3,5]})
        source=xml(parts[item.media_id]);self.rich_label(source,'20%')
        parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts)
        value=dict(title='New',categories=['A','B','C'],series=[dict(name='New',values=[3,3,4])])
        _,updated,book=self.filled(parts,item,value);self.assert_cached_and_book(updated,book,value)
        self.assertEqual(updated.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),['30%'])
        self.assertEqual(parts,snapshot)

    def test_pie_percentage_with_extreme_or_malformed_source_number_is_view_only(self):
        for number in ('1e9999999','1e-9999999','NaN','sNaN','Infinity'):
            with self.subTest(number=number):
                parts,item=self.fixture('pie',(3,));source=xml(parts[item.media_id])
                source.find('.//c:ser/c:val//c:pt/c:v',NS).text=number
                self.rich_label(source,'20%');parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts)
                with self.assertRaisesRegex(ValueError,'pptx_chart_labels_unsupported'):chart_spec(item,parts)
                self.assertEqual(parts,snapshot)

    def test_equal_x_and_y_require_an_unambiguous_explicit_label_display_flag(self):
        for flags,expected in [({'showCatName':True,'showVal':False},'2'),({'showCatName':False,'showVal':True},'6')]:
            with self.subTest(flags=flags):
                parts,item=self.fixture(counts=(1,));self.source_data(parts,item,{'xVal':[1],'yVal':[1]})
                source=xml(parts[item.media_id]);self.rich_label(source,'1',flags=flags)
                parts[item.media_id]=etree.tostring(source)
                value=dict(kind='xy',title='New',series=[dict(name='New',points=[dict(x=2,y=6)])])
                _,updated,_=self.filled(parts,item,value)
                self.assertEqual(updated.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),[expected])

    def test_unbound_ambiguous_rounded_or_wrong_index_numeric_labels_are_view_only(self):
        cases=[('xy',{'xVal':[1],'yVal':[1]},'1',None),
               ('xy',{'xVal':[1],'yVal':[1]},'1',{'showCatName':True,'showVal':True}),
               ('xy',{'xVal':[1],'yVal':[5]},'2024 s',None),
               ('xy',{'xVal':[1,2],'yVal':[5,6]},'2 s',None),
               ('bar',{'val':[.004429]},'0.0044 ms',None),
               ('pie',{'val':[2,3,5]},'2%',None)]
        for kind,entries,text,flags in cases:
            with self.subTest(kind=kind,text=text,flags=flags):
                count=len(next(iter(entries.values())));parts,item=self.fixture(kind,(count,))
                self.source_data(parts,item,entries);source=xml(parts[item.media_id]);self.rich_label(source,text,flags=flags)
                parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts)
                with self.assertRaisesRegex(ValueError,'pptx_chart_labels_unsupported'):chart_spec(item,parts)
                self.assertEqual(parts,snapshot)

    def test_unsupported_numeric_annotation_does_not_write_a_partial_output(self):
        parts,item=self.fixture(counts=(1,));self.source_data(parts,item,{'xVal':[1],'yVal':[5]})
        spec=chart_spec(item,parts);source=xml(parts[item.media_id]);self.rich_label(source,'2024 s')
        parts[item.media_id]=etree.tostring(source);snapshot=deepcopy(parts);result=dict(parts)
        slide=xml(parts['ppt/slides/slide1.xml']);rels=xml(parts['ppt/slides/_rels/slide1.xml.rels']);types=xml(parts['[Content_Types].xml'])
        before=[etree.tostring(node) for node in (slide,rels,types)]
        with self.assertRaisesRegex(ValueError,'pptx_chart_labels_unsupported'):
            fill_chart(spec,self.value(spec),parts,result,slide,rels,0,types)
        self.assertEqual(parts,snapshot);self.assertEqual(result,snapshot)
        self.assertEqual([etree.tostring(node) for node in (slide,rels,types)],before)

    def test_decimal_comma_literal_keeps_source_precision_and_comma_style(self):
        parts,item=self.fixture('bar',(1,));source=xml(parts[item.media_id]);self.rich_label(source,'0,004429 ms')
        parts[item.media_id]=etree.tostring(source)
        value=dict(title='New',categories=['A'],series=[dict(name='New',values=[.009559])])
        _,updated,_=self.filled(parts,item,value)
        self.assertEqual(updated.xpath('.//c:dLbl/c:tx/c:rich//a:t/text()',namespaces=NS),['0,009559 ms'])

    def test_custom_named_labels_are_preserved_as_unsupported_rather_than_silently_stale(self):
        parts,item=self.fixture('bar',(3,3));root=xml(parts[item.media_id]);series=root.find('.//c:ser',NS)
        labels=etree.SubElement(series,'{%s}dLbls'%NS['c']);label=etree.SubElement(labels,'{%s}dLbl'%NS['c']);etree.SubElement(label,'{%s}idx'%NS['c'],val='0')
        rich=etree.SubElement(etree.SubElement(label,'{%s}tx'%NS['c']),'{%s}rich'%NS['c']);paragraph=etree.SubElement(rich,'{%s}p'%NS['a']);run=etree.SubElement(paragraph,'{%s}r'%NS['a']);etree.SubElement(run,'{%s}t'%NS['a']).text='Unbound original annotation'
        parts[item.media_id]=etree.tostring(root);before=deepcopy(parts)
        with self.assertRaisesRegex(ValueError,'pptx_chart_labels_unsupported'):chart_spec(item,parts)
        self.assertEqual(parts,before)

    def test_log_renderer_sparse_extent_keeps_all_real_points_order_and_export_immutable(self):
        parts,item=self.fixture(counts=(25,29));source=xml(parts[item.media_id])
        source.find('.//c:valAx/c:scaling',NS).insert(0,etree.Element('{%s}logBase'%NS['c'],val='10'))
        original=etree.tostring(source);rendered=deepcopy(source)
        points_before=rendered.xpath('.//c:pt',namespaces=NS)
        points_before=[etree.tostring(point) for point in points_before]
        formulas=rendered.xpath('.//c:f/text()',namespaces=NS)
        series_order=rendered.xpath('.//c:ser/c:idx/@val|.//c:ser/c:order/@val',namespaces=NS)
        self.assertTrue(prepare_chart_render(rendered))
        self.assertFalse(prepare_chart_render(rendered))
        self.assertEqual(rendered.xpath('.//c:xVal//c:ptCount/@val|.//c:yVal//c:ptCount/@val',namespaces=NS),['29']*4)
        self.assertEqual([etree.tostring(point) for point in rendered.xpath('.//c:pt',namespaces=NS)],points_before)
        self.assertEqual(rendered.xpath('.//c:f/text()',namespaces=NS),formulas)
        self.assertEqual(rendered.xpath('.//c:ser/c:idx/@val|.//c:ser/c:order/@val',namespaces=NS),series_order)
        self.assertEqual(etree.tostring(source),original)
        linear=xml(parts[item.media_id]);before=etree.tostring(linear)
        self.assertFalse(prepare_chart_render(linear));self.assertEqual(etree.tostring(linear),before)

class WorkbookReferenceSafety(unittest.TestCase):
    def test_quoted_sheet_names_and_vertical_or_horizontal_ranges(self):
        self.assertEqual(parse_reference("'A''s sheet'!$AA$10:$AC$10"),("A's sheet",[(27,10),(28,10),(29,10)]))
        self.assertEqual(parse_reference('Data!B2:B4'),('Data',[(2,2),(2,3),(2,4)]))
        for value in ('[external.xlsx]Sheet!A1:A2','Name','Sheet!A1:B2','Sheet!XFE1','Sheet!A0','Sheet!A1:A501'):
            with self.assertRaises(ValueError):parse_reference(value)

if __name__=='__main__':unittest.main()
