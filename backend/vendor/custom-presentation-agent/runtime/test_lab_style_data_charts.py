import io
import unittest
import zipfile
from copy import deepcopy
from runtime.security import NS,xml
from runtime.chart_builder import add_data_chart,chart_presentation_style
from runtime.charts import fill_chart
from runtime.html_charts import chart_svg,apply_native_chart_density


class StyleDataChartsTest(unittest.TestCase):
    def test_raster_style_drives_svg_and_editable_native_chart_without_using_picture_as_data(self):
        base=dict(font='Arial',ink='#202020',accent='#00AAAA',chartStyle=dict(sourceKind='raster',sourceShapeIds=[8],palette=['#C25538','#D69E42'],grid='none',legend='none',axes=False,showValues=False,markers=False,lineWidth=3))
        before=deepcopy(base);style=chart_presentation_style(base)
        data=dict(type='line',title='Проверенные данные',categories=['2024','2025'],series=[dict(name='Ряд',values=[-12.5,0])])
        svg=xml(chart_svg(dict(data=data,box=dict(w=600,h=300)),base).encode())
        self.assertEqual(base,before)
        self.assertTrue(svg.xpath('.//*[local-name()="polyline" and @stroke="#C25538" and @stroke-width="3"]'))
        self.assertFalse(svg.xpath('.//*[@data-chart-label="axis" or @data-chart-label="value" or @data-chart-label="legend"]'))
        parts,part,root=self.native(data,style)
        self.assertEqual(root.find('.//c:ser/c:spPr/a:ln/a:solidFill/a:srgbClr',NS).get('val'),'C25538')
        self.assertEqual(root.find('.//c:ser/c:marker/c:symbol',NS).get('val'),'none')
        self.assertEqual(root.find('.//c:valAx/c:delete',NS).get('val'),'1')
        self.assertFalse(root.findall('.//c:majorGridlines',NS))
        self.assertFalse(root.findall('.//c:legend',NS))
        self.assertFalse(root.xpath('.//c:dLbls/c:showVal[@val="1"]',namespaces=NS))
        self.assertTrue(any(name.endswith('.xlsx') for name in parts))

    def native(self,data,style):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:cSld><p:spTree/></p:cSld></p:sld>').encode())
        tree=root.find('p:cSld/p:spTree',NS);rels=xml(('<Relationships xmlns="'+NS['pr']+'"/>').encode());types=xml(('<Types xmlns="'+NS['ct']+'"/>').encode());parts={}
        bounds=dict(x=20,y=100,w=600,h=300)
        part=add_data_chart(tree,1,bounds,style,parts,rels,types,'editable-'+data['type'],data['type'],len(data['series']))
        spec=dict(part=part,shapeId=1,key='chart',type={'bar':'barChart','bar-horizontal':'barChart','line':'lineChart','pie':'pieChart','donut':'doughnutChart'}[data['type']],seriesCount=len(data['series']),dataKind='category')
        fill_chart(spec,dict(title=data['title'],categories=data['categories'],series=data['series']),dict(parts),parts,root,rels,1,types)
        reference=tree.find('.//c:chart',NS);rid=reference.get('{%s}id'%NS['r']);relation=next(item for item in rels if item.get('Id')==rid)
        part='ppt/charts/'+relation.get('Target').rsplit('/',1)[-1]
        apply_native_chart_density(parts,part,data,bounds,style,authored=True)
        return parts,part,xml(parts[part])

    def test_every_chart_kind_preserves_exact_series_cache_and_embedded_workbook(self):
        style=dict(font='Arial',ink='#202020',accent='#3159B6',seriesColors=['#3159B6','#F5A623'])
        for kind in ('bar','bar-horizontal','line','pie','donut'):
            values=[0,40,60] if kind in ('pie','donut') else [-12.5,0,120.25]
            data=dict(type=kind,title='Точные значения',categories=['А','Б','В'],series=[dict(name='Показатель',values=values)])
            with self.subTest(kind=kind):
                svg=xml(chart_svg(dict(data=data,box=dict(w=600,h=300)),style).encode())
                self.assertEqual([float(node.get('data-chart-value')) for node in svg.xpath('.//*[@data-chart-value]')],values)
                parts,part,root=self.native(data,style)
                self.assertEqual([float(value) for value in root.xpath('.//c:ser/c:val//c:pt/c:v/text()',namespaces=NS)],values)
                self.assertEqual(root.xpath('.//c:title//a:t/text()',namespaces=NS),[data['title']])
                self.assertTrue(root.xpath('.//c:dLbls/c:showVal[@val="1"]',namespaces=NS))
                if kind=='line':self.assertEqual(root.find('.//c:dLbls/c:dLblPos',NS).get('val'),'t')
                books=[value for name,value in parts.items() if name.endswith('.xlsx')]
                self.assertTrue(books)
                with zipfile.ZipFile(io.BytesIO(books[-1])) as book:
                    sheet=xml(book.read('xl/worksheets/sheet1.xml'))
                    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                    actual=[float(value) for value in sheet.xpath('//s:row[@r>1]/s:c[starts-with(@r,"B")]/s:v/text()',namespaces=ns)]
                    self.assertEqual(actual,values)
                if kind=='bar-horizontal':self.assertEqual(root.find('.//c:barChart/c:barDir',NS).get('val'),'bar')
                if kind in ('pie','donut'):self.assertEqual(len(root.findall('.//c:dPt',NS)),3)

    def test_faint_source_gray_is_readable_in_both_svg_and_native_chart(self):
        from runtime.contrast import ratio
        from runtime.chart_builder import series_colors
        style=dict(font='Arial',ink='#222222',accent='#BFBFBF',chartBackground='#FFFFFF',seriesColors=['#BFBFBF'])
        data=dict(type='line',title='Data',categories=['2024','2025'],series=[dict(name='EUR',values=[12,18])])
        colour=series_colors(style,1)[0];self.assertGreaterEqual(ratio(colour,'#FFFFFF'),3)
        svg=chart_svg(dict(data=data,box=dict(w=600,h=300)),style);self.assertIn('stroke="'+colour+'"',svg)
        parts,part,root=self.native(data,style)
        self.assertEqual(root.find('.//c:ser/c:spPr/a:ln/a:solidFill/a:srgbClr',NS).get('val'),colour[1:])

    def test_reusing_ring_style_for_line_restores_a_quantitative_scale(self):
        style=dict(font='Arial',ink='#222222',accent='#3159B6',chartStyle=dict(type='donut',axes=False,grid='none'))
        self.assertTrue(chart_presentation_style(style,'line')['axes'])
        self.assertFalse(chart_presentation_style(style,'donut')['axes'])
