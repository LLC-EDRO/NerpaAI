"""Clone native charts and update editable data without replacing their design."""
import io
import math
import posixpath
import re
import zipfile
from decimal import Decimal, DecimalException, localcontext
from lxml import etree
from runtime.security import NS,xml,relationship_target
from app.presentation.parser.archive import relationship_part
from runtime.chart_workbook import ChartWorkbook

NS['c']='http://schemas.openxmlformats.org/drawingml/2006/chart'
MAX_SERIES=6
MAX_POINTS=500
CATEGORY_KINDS={'barChart','lineChart','areaChart','pieChart','doughnutChart','radarChart'}
NUMBER_LABEL=re.compile(r'^(\s*)([+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?)(\s*(?:%|[A-Za-zА-Яа-яЁё°/²³]+)?\s*)$')

def finite_number(value):
    try:return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:return False

def label_decimal(text):
    if not isinstance(text,str) or len(text)>512:return None
    try:
        number=Decimal(text.strip().replace(',','.'))
        if not number.is_finite():return None
        represented=float(number)
        return number if math.isfinite(represented) and (represented!=0 or number==0) else None
    except (DecimalException,ValueError,OverflowError):return None

def cache_number(parent,index):
    if parent is None:return None
    nodes=parent.xpath('.//c:pt[@idx=$index]/c:v/text()',namespaces=NS,index=str(index))
    return label_decimal(nodes[0]) if len(nodes)==1 else None

def label_binding(plot,series,label,index,match):
    """Bind a literal only to an exact original value at its own data index."""
    number=label_decimal(match.group(2))
    if number is None:raise ValueError('pptx_chart_labels_unsupported')
    xy=etree.QName(plot).localname=='scatterChart'
    x=cache_number(series.find('c:xVal' if xy else 'c:cat',NS),index)
    y=cache_number(series.find('c:yVal' if xy else 'c:val',NS),index)
    choices=[]
    if etree.QName(plot).localname in ('pieChart','doughnutChart') and '%' in match.group(3):
        values=[label_decimal(text) for text in series.xpath('./c:val//c:pt/c:v/text()',namespaces=NS)]
        if y is not None and values and all(value is not None and value>=0 for value in values):
            try:
                with localcontext() as context:
                    context.prec=64
                    total=sum(values,Decimal(0))
                    if total and y*100/total==number:choices.append('percent')
            except DecimalException:raise ValueError('pptx_chart_labels_unsupported')
    else:
        if x is not None and x==number:choices.append('x' if xy else 'category')
        if y is not None and y==number:choices.append('y')
    if len(choices)>1:
        owners=(label,series.find('c:dLbls',NS),plot.find('c:dLbls',NS))
        def enabled(flag):
            for owner in owners:
                node=owner.find('c:'+flag,NS) if owner is not None else None
                if node is not None:return node.get('val') in ('1','true')
            return False
        shown={'x':enabled('showCatName'),'category':enabled('showCatName'),'y':enabled('showVal'),'percent':enabled('showPercent')}
        choices=[choice for choice in choices if shown[choice]]
    if len(choices)!=1:raise ValueError('pptx_chart_labels_unsupported')
    return choices[0]

def custom_labels(root):
    if root.xpath('.//*[local-name()="datalabelsRange" or local-name()="dataLabelsRange"]'):
        raise ValueError('pptx_chart_labels_unsupported')
    plans=[]
    for plot in root.xpath('./c:chart/c:plotArea/*[c:ser]',namespaces=NS):
        series=plot.findall('c:ser',NS)
        for i,s in enumerate(series):
            labels=s.findall('c:dLbls/c:dLbl',NS)
            if i==0:
                group=plot.findall('c:dLbls/c:dLbl',NS)
                if len(series)>1 and any(label.find('c:tx',NS) is not None for label in group):raise ValueError('pptx_chart_labels_unsupported')
                labels+=group
            for label in labels:
                tx=label.find('c:tx',NS)
                if tx is None:continue
                rich=tx.find('c:rich',NS)
                text=''.join(rich.xpath('.//a:t/text()',namespaces=NS)) if rich is not None else ''.join(tx.xpath('./c:strRef/c:strCache/c:pt/c:v/text()',namespaces=NS))
                match=NUMBER_LABEL.fullmatch(text)
                identity=label.find('c:idx',NS)
                try:index=int(identity.get('val')) if identity is not None else -1
                except (ValueError,TypeError):index=-1
                if match is None or index<0:raise ValueError('pptx_chart_labels_unsupported')
                binding=label_binding(plot,s,label,index,match)
                plans.append((s,label,index,text,match,binding))
    return plans

def cache_data(parent):
    if parent is None:raise ValueError('pptx_chart_data_unsupported')
    for path in ('c:numRef/c:numCache','c:strRef/c:strCache','c:numLit','c:strLit','c:multiLvlStrRef/c:multiLvlStrCache'):
        cache=parent.find(path,NS)
        if cache is not None:
            levels=cache.findall('c:lvl',NS)
            if len(levels)>1:raise ValueError('pptx_chart_data_unsupported')
            count_node=cache.find('c:ptCount',NS)
            points=(levels[0] if levels else cache).findall('c:pt',NS)
            try:
                indices=[int(point.get('idx')) for point in points]
                count=int(count_node.get('val')) if count_node is not None else len(points)
            except (TypeError,ValueError):raise ValueError('pptx_chart_data_unsupported')
            if not 1<=count<=MAX_POINTS:raise ValueError('pptx_chart_point_limit')
            if len(set(indices))!=len(indices) or any(index<0 or index>=count for index in indices):raise ValueError('pptx_chart_data_unsupported')
            if not points or any(point.find('c:v',NS) is None for point in points):raise ValueError('pptx_chart_data_unsupported')
            return cache,count
    raise ValueError('pptx_chart_data_unsupported')

def source_workbook(root,part,parts):
    external=root.find('c:externalData',NS)
    if external is None:return None
    relname=relationship_part(part)
    rels=xml(parts[relname]) if relname in parts else None
    rid=external.get('{%s}id'%NS['r'])
    rel=next((r for r in rels if r.get('Id')==rid),None) if rels is not None else None
    if rel is None or rel.get('TargetMode')=='External' or not rel.get('Type','').endswith('/package'):
        raise ValueError('pptx_chart_workbook_reference_unsupported')
    target=relationship_target(relname,rel.get('Target',''))
    if not target.endswith('.xlsx') or target not in parts:raise ValueError('pptx_chart_workbook_reference_unsupported')
    try:return ChartWorkbook(parts[target])
    except (KeyError,zipfile.BadZipFile):raise ValueError('pptx_chart_workbook_reference_unsupported')

def axis_contract(root,series):
    axes=[];by_id={};axis_kinds={};series_axes=[]
    for axis in root.xpath('./c:chart/c:plotArea/c:catAx|./c:chart/c:plotArea/c:valAx|./c:chart/c:plotArea/c:dateAx',namespaces=NS):
        identity=axis.find('c:axId',NS)
        if identity is None or identity.get('val') in by_id:raise ValueError('pptx_chart_axis_unsupported')
        scaling=axis.find('c:scaling',NS)
        log=scaling.find('c:logBase',NS) if scaling is not None else None
        meta=dict(id=identity.get('val'),dimension='y' if etree.QName(axis).localname=='valAx' else 'x',scale='log' if log is not None else 'linear')
        try:
            if log is not None:
                base=float(log.get('val'))
                if etree.QName(axis).localname!='valAx' or not math.isfinite(base) or not 2<=base<=1000:raise ValueError()
                meta['logBase']=base
            for name in ('min','max'):
                bound=scaling.find('c:'+name,NS) if scaling is not None else None
                if bound is not None:
                    number=float(bound.get('val'))
                    if not math.isfinite(number) or log is not None and number<=0:raise ValueError()
                    meta[name]=number
            if 'min' in meta and 'max' in meta and meta['min']>=meta['max']:raise ValueError()
        except (TypeError,ValueError):raise ValueError('pptx_chart_scale_unsupported')
        axes.append(meta);by_id[meta['id']]=meta;axis_kinds[meta['id']]=etree.QName(axis).localname
    for s in series:
        ids=[node.get('val') for node in s.getparent().findall('c:axId',NS)]
        binding={}
        if ids:
            if len(ids)!=2 or len(set(ids))!=2 or any(identity not in by_id for identity in ids):raise ValueError('pptx_chart_axis_unsupported')
            if etree.QName(s.getparent()).localname!='scatterChart':
                categories=[identity for identity in ids if axis_kinds[identity] in ('catAx','dateAx')]
                values=[identity for identity in ids if axis_kinds[identity]=='valAx']
                if len(categories)!=1 or len(values)!=1:raise ValueError('pptx_chart_axis_unsupported')
                ids=categories+values
            binding=dict(xAxisId=ids[0],yAxisId=ids[1])
            for dimension,identity in zip(('x','y'),ids):
                by_id[identity]['dimension']=dimension
        elif etree.QName(s.getparent()).localname=='scatterChart':raise ValueError('pptx_chart_axis_unsupported')
        series_axes.append(binding)
    return axes,series_axes

def chart_spec(item,parts):
    part=item.media_id
    if not part or part not in parts: raise ValueError('pptx_chart_part_missing')
    root=xml(parts[part]);series=root.xpath('.//c:plotArea/*/c:ser',namespaces=NS)
    kinds={etree.QName(s.getparent()).localname for s in series}
    xy=kinds=={'scatterChart'}
    if not kinds or not (xy or kinds.issubset(CATEGORY_KINDS)): raise ValueError('pptx_chart_type_unsupported')
    if not 1<=len(series)<=MAX_SERIES: raise ValueError('pptx_chart_series_limit')
    book=source_workbook(root,part,parts)
    counts=[]
    for s in series:
        cat=s.find('c:xVal' if xy else 'c:cat',NS);val=s.find('c:yVal' if xy else 'c:val',NS)
        if val is None or not (val.find('c:numRef',NS) is not None or val.find('c:numLit',NS) is not None):raise ValueError('pptx_chart_data_unsupported')
        if xy and (cat is None or not (cat.find('c:numRef',NS) is not None or cat.find('c:numLit',NS) is not None)):raise ValueError('pptx_chart_data_unsupported')
        _,count=cache_data(val);_,category_count=cache_data(cat)
        if count!=category_count:raise ValueError('pptx_chart_data_unsupported')
        counts.append(count)
        if book is not None:
            for parent,length in ((cat,count),(val,count),(s.find('c:tx',NS),1)):
                if parent is None:continue
                for ref in parent.findall('*/c:f',NS):book.binding(ref.text,length,allow_formula=True)
    if not xy and len(set(counts))!=1: raise ValueError('pptx_chart_categories_mismatch')
    if book is not None:
        for ref in root.findall('c:chart/c:title/c:tx/c:strRef/c:f',NS):book.binding(ref.text,1,allow_formula=True)
    axes,series_axes=axis_contract(root,series)
    for _,label,_,_,_,_ in custom_labels(root):
        if book is not None:
            for ref in label.findall('c:tx/c:strRef/c:f',NS):book.binding(ref.text,1,allow_formula=True)
        elif label.find('c:tx/c:strRef',NS) is not None:raise ValueError('pptx_chart_labels_unsupported')
    return dict(key=f'chart{item.shape_id}',shapeId=item.shape_id,part=part,type='/'.join(sorted(kinds)),dataKind='xy' if xy else 'category',seriesCount=len(series),pointCount=max(counts),seriesPointCounts=counts,axes=axes,seriesAxes=series_axes,hasTitle=root.find('c:chart/c:title',NS) is not None)

def validate_charts(layout,native):
    expected={c['key']:c for c in layout.get('charts',[])}
    values=native.get('charts',{})
    if not isinstance(values,dict) or set(values)!=set(expected): raise ValueError('pptx_chart_keys_mismatch')
    for key,spec in expected.items():
        value=values[key]
        if not isinstance(value,dict):raise ValueError('pptx_chart_values_invalid')
        if not isinstance(value.get('title',''),str) or len(value.get('title',''))>80: raise ValueError('pptx_chart_title_invalid')
        xy=spec.get('dataKind')=='xy'
        if xy and (value.get('kind')!='xy' or 'categories' in value) or not xy and value.get('kind') not in (None,'category'):raise ValueError('pptx_chart_kind_mismatch')
        categories=value.get('categories',[])
        if not xy and (not isinstance(categories,list) or not 1<=len(categories)<=MAX_POINTS or any(not isinstance(t,str) or not t.strip() or len(t)>30 for t in categories)): raise ValueError('pptx_chart_categories_invalid')
        if not isinstance(value.get('series'),list) or len(value['series'])!=spec['seriesCount']: raise ValueError('pptx_chart_series_invalid')
        axes={axis['id']:axis for axis in spec.get('axes',[])}
        for i,s in enumerate(value['series']):
            if not isinstance(s,dict) or not isinstance(s.get('name'),str) or not s['name'].strip() or len(s['name'])>40: raise ValueError('pptx_chart_values_invalid')
            numbers=s.get('points' if xy else 'values')
            if not isinstance(numbers,list) or not 1<=len(numbers)<=MAX_POINTS or not xy and len(numbers)!=len(categories):raise ValueError('pptx_chart_values_invalid')
            if xy:
                if 'values' in s or any(not isinstance(p,dict) or set(p)!={'x','y'} for p in numbers):raise ValueError('pptx_chart_values_invalid')
                xs=[p['x'] for p in numbers];ys=[p['y'] for p in numbers]
            else:
                if 'points' in s:raise ValueError('pptx_chart_values_invalid')
                xs=numeric_categories(categories);ys=numbers
            if any(not finite_number(n) for n in (xs or [])+ys): raise ValueError('pptx_chart_values_invalid')
            binding=spec.get('seriesAxes',[{}]*spec['seriesCount'])[i]
            for name,coords in (('x',xs),('y',ys)):
                axis=axes.get(binding.get(name+'AxisId'))
                if axis and axis['scale']=='log' and (coords is None or any(n<=0 for n in coords)):raise ValueError('pptx_chart_log_value_invalid')
            if any(k in spec['type'] for k in ('pieChart','doughnutChart')) and (any(n<0 for n in ys) or not any(ys)): raise ValueError('pptx_chart_values_invalid')

def numeric_categories(labels):
    try:
        result=[float(label.replace(',','.')) for label in labels]
        return result if all(math.isfinite(v) for v in result) else None
    except (ValueError,TypeError,AttributeError):return None

def prepare_chart_render(root):
    """Use a shared sparse cache extent in the converter's temporary copy only.

    LibreOffice 7.4 drops an earlier shorter logarithmic XY series when the
    later series has more points. A common cache extent retains omitted trailing
    positions: no numeric points, formulas, workbook data, order or style change.
    The exported chart must retain its actual independent series counts.
    """
    logarithmic={axis.find('c:axId',NS).get('val') for axis in root.findall('c:chart/c:plotArea/c:valAx',NS)
                 if axis.find('c:axId',NS) is not None and axis.find('c:scaling/c:logBase',NS) is not None}
    changed=False
    for plot in root.findall('c:chart/c:plotArea/c:scatterChart',NS):
        if not logarithmic.intersection(node.get('val') for node in plot.findall('c:axId',NS)):continue
        entries=[]
        try:
            for series in plot.findall('c:ser',NS):
                x,count=cache_data(series.find('c:xVal',NS));y,ycount=cache_data(series.find('c:yVal',NS))
                if count!=ycount:raise ValueError('pptx_chart_data_unsupported')
                entries.append((x,y,count))
        except ValueError:continue  # Unsupported source objects stay untouched.
        maximum=max((entry[2] for entry in entries),default=0)
        for x,y,count in entries:
            if count==maximum:continue
            for cache in (x,y):
                counter=cache.find('c:ptCount',NS)
                if counter is None:
                    counter=etree.Element('{%s}ptCount'%NS['c']);cache.insert(1 if cache.find('c:formatCode',NS) is not None else 0,counter)
                counter.set('val',str(maximum))
            changed=True
    return changed

def workbook(data, categories=None):
    # A fresh data-only XLSX: no original formulas, external links, macros, or stale values.
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet=etree.Element('{%s}worksheet'%ns,nsmap={None:ns});rows=etree.SubElement(sheet,'{%s}sheetData'%ns)
    if data.get('kind')=='xy':
        values=[[label for s in data['series'] for label in (s['name']+' X',s['name'])]]
        for i in range(max(len(s['points']) for s in data['series'])):
            values.append([number for s in data['series'] for number in ((s['points'][i]['x'],s['points'][i]['y']) if i<len(s['points']) else (None,None))])
    else:
        values=[[data.get('title') or 'Category']+[s['name'] for s in data['series']]]+[[label]+[s['values'][i] for s in data['series']] for i,label in enumerate(categories if categories is not None else data['categories'])]
    for i,row in enumerate(values,1):
        r=etree.SubElement(rows,'{%s}row'%ns,r=str(i))
        for j,value in enumerate(row):
            if value is None:continue
            cell=etree.SubElement(r,'{%s}c'%ns,r=chr(65+j)+str(i))
            if isinstance(value,str):
                cell.set('t','inlineStr');etree.SubElement(etree.SubElement(cell,'{%s}is'%ns),'{%s}t'%ns).text=value
            else: etree.SubElement(cell,'{%s}v'%ns).text=str(value)
    parts={
      '[Content_Types].xml':f'<Types xmlns="{NS["ct"]}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
      '_rels/.rels':f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="book" Type="{NS["r"]}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
      'xl/workbook.xml':f'<workbook xmlns="{ns}" xmlns:r="{NS["r"]}"><sheets><sheet name="Data" sheetId="1" r:id="sheet"/></sheets></workbook>',
      'xl/_rels/workbook.xml.rels':f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="sheet" Type="{NS["r"]}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
      'xl/worksheets/sheet1.xml':etree.tostring(sheet,xml_declaration=True,encoding='UTF-8')}
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in parts.items(): z.writestr(name,value)
    return result.getvalue()

def normalize_chart(root, palette=(), background=None):
    """Repair supported native charts without rasterizing or changing data."""
    from runtime.contrast import ratio
    def insert_before(parent,child,names):
        parent.insert(next((i for i,n in enumerate(parent) if etree.QName(n).localname in names),len(parent)),child)
    # Mixed-sign horizontal bars cross the category axis: nextTo puts labels
    # directly on the negative bars. Move category labels outside the plot.
    for plot in root.xpath('.//c:plotArea/c:areaChart',namespaces=NS):
        grouping=plot.find('c:grouping',NS)
        series=plot.findall('c:ser',NS)
        if len(series)<2 or grouping is not None and grouping.get('val') in ('stacked','percentStacked'):continue
        for series_node in series:
            # Preserve colors, series order and editable data; only opaque fills
            # acquire a shared translucency. Existing explicit alpha wins.
            for color in series_node.xpath('./c:spPr/a:solidFill/*',namespaces=NS):
                if not color.xpath('./a:alpha|./a:alphaMod|./a:alphaOff',namespaces=NS):
                    etree.SubElement(color,'{%s}alpha'%NS['a'],val='55000')
    for plot in root.xpath('.//c:plotArea/c:barChart[c:barDir[@val="bar"]]',namespaces=NS):
        values=[float(v.text) for v in plot.xpath('./c:ser/c:val//c:pt/c:v',namespaces=NS)]
        if values and min(values)<0<max(values):
            ids={n.get('val') for n in plot.findall('c:axId',NS)}
            for axis in root.xpath('.//c:catAx',namespaces=NS):
                axis_id=axis.find('c:axId',NS)
                if axis_id is None or axis_id.get('val') not in ids:continue
                labels=axis.find('c:tickLblPos',NS)
                if labels is None:
                    labels=etree.Element('{%s}tickLblPos'%NS['c']);insert_before(axis,labels,{'spPr','txPr','crossAx','crosses','crossesAt','auto','lblAlgn','lblOffset','tickLblSkip','tickMarkSkip','noMultiLvlLbl','extLst'})
                labels.set('val','low')
    for plot in root.xpath('.//c:plotArea/c:doughnutChart|.//c:plotArea/c:pieChart|.//c:plotArea/c:barChart',namespaces=NS):
        kind=etree.QName(plot).localname;pie=kind in ('pieChart','doughnutChart')
        if kind=='doughnutChart' and plot.find('c:holeSize',NS) is None:
            insert_before(plot,etree.Element('{%s}holeSize'%NS['c'],val='50'),{'extLst'})
        series=plot.findall('c:ser',NS)
        count=max((len(s.xpath('./c:val//c:pt',namespaces=NS)) for s in series),default=0)
        if pie:
            vary=plot.find('c:varyColors',NS)
            if vary is None:vary=etree.Element('{%s}varyColors'%NS['c']);plot.insert(0,vary)
            vary.set('val','1')
            colors=[c for c in dict.fromkeys(palette) if isinstance(c,str) and len(c)==7 and c.startswith('#') and ratio(c,background or '#FFFFFF')>=2.5]
            for series_node in series:
                # Explicit data-point colors prevent viewers treating all slices
                # as the series' solid fill. Existing per-point styling wins.
                if len(colors)>=count and count>1 and not series_node.findall('c:dPt',NS):
                    for i in range(count):
                        point=etree.Element('{%s}dPt'%NS['c']);etree.SubElement(point,'{%s}idx'%NS['c'],val=str(i))
                        props=etree.SubElement(point,'{%s}spPr'%NS['c']);fill=etree.SubElement(props,'{%s}solidFill'%NS['a'])
                        etree.SubElement(fill,'{%s}srgbClr'%NS['a'],val=colors[i][1:])
                        insert_before(series_node,point,{'dLbls','cat','val','extLst'})
        if not count or count>8 or len(series)>3:continue
        labels=plot.find('c:dLbls',NS)
        if labels is None:
            labels=etree.Element('{%s}dLbls'%NS['c'])
            insert_before(plot,labels,{'firstSliceAng','holeSize','gapWidth','overlap','serLines','axId','extLst'})
        enabled=labels.xpath('./c:showVal[@val="1"]|./c:showCatName[@val="1"]|./c:showPercent[@val="1"]',namespaces=NS)
        if not enabled and not labels.findall('c:dLbl',NS):
            for child in list(labels):
                if etree.QName(child).localname.startswith('show') or etree.QName(child).localname in ('delete','dLblPos'):labels.remove(child)
            # LibreOffice may keep doughnut labels inside even with outEnd.
            # Choose an explicit inside placement and contrasting per-slice
            # text instead; all viewers then use the same design intent.
            insert_before(labels,etree.Element('{%s}dLblPos'%NS['c'],val='ctr' if pie else 'outEnd'),{'separator','showLeaderLines','leaderLines','extLst'})
            category_labels=pie and root.find('c:chart/c:legend',NS) is None
            for name,on in [('showLegendKey',False),('showVal',not pie),('showCatName',category_labels),('showSerName',False),('showPercent',pie),('showBubbleSize',False)]:
                insert_before(labels,etree.Element('{%s}%s'%(NS['c'],name),val='1' if on else '0'),{'separator','showLeaderLines','leaderLines','extLst'})
            if pie and len(series)==1:
                for point in series[0].findall('c:dPt',NS):
                    index=point.find('c:idx',NS);color=point.find('c:spPr/a:solidFill/a:srgbClr',NS)
                    if index is None or color is None:continue
                    slice_background='#'+color.get('val','')
                    if len(slice_background)!=7:continue
                    foreground=max(('#000000','#FFFFFF'),key=lambda c:ratio(c,slice_background))
                    label=etree.Element('{%s}dLbl'%NS['c']);etree.SubElement(label,'{%s}idx'%NS['c'],val=index.get('val'))
                    tx=etree.SubElement(label,'{%s}txPr'%NS['c']);etree.SubElement(tx,'{%s}bodyPr'%NS['a']);etree.SubElement(tx,'{%s}lstStyle'%NS['a'])
                    p=etree.SubElement(tx,'{%s}p'%NS['a']);pp=etree.SubElement(p,'{%s}pPr'%NS['a']);rp=etree.SubElement(pp,'{%s}defRPr'%NS['a'])
                    fill=etree.SubElement(rp,'{%s}solidFill'%NS['a']);etree.SubElement(fill,'{%s}srgbClr'%NS['a'],val=foreground[1:])
                    etree.SubElement(p,'{%s}endParaRPr'%NS['a'])
                    etree.SubElement(label,'{%s}dLblPos'%NS['c'],val='ctr')
                    # Some viewers do not inherit the group's display flags
                    # for a individually styled label. Explicitly repeat them.
                    for name,on in [('showLegendKey',False),('showVal',False),('showCatName',category_labels),('showSerName',False),('showPercent',True),('showBubbleSize',False)]:
                        etree.SubElement(label,'{%s}%s'%(NS['c'],name),val='1' if on else '0')
                    labels.insert(len(labels.findall('c:dLbl',NS)),label)
    from runtime.chart_contrast import repair_chart_contrast
    repair_chart_contrast(root,palette,background)

def fill_chart(spec,value,parts,result,slide_root,slide_rels,slide_index,content_types,palette=(),background=None):
    validate_charts({'charts':[spec]},{'charts':{spec['key']:value}})
    root=xml(parts[spec['part']]);part=f'ppt/charts/nerpaChart{slide_index+1}_{spec["shapeId"]}.xml'
    book_data=source_workbook(root,spec['part'],parts)
    labels=custom_labels(root)
    xy=spec.get('dataKind')=='xy'
    numeric=bool(root.xpath('.//c:ser/c:cat/c:numRef|.//c:ser/c:cat/c:numLit',namespaces=NS))
    categories=numeric_categories(value['categories']) if numeric and not xy else None
    # Preserve explicit scales when new data fits. Clear only clipping bounds;
    # base, direction, crossing, ticks and number formats stay source-owned.
    bound_values={}
    for i,s in enumerate(value['series']):
        binding=spec.get('seriesAxes',[{}]*spec['seriesCount'])[i]
        for dimension,coords in (('x',[p['x'] for p in s['points']] if xy else categories),('y',[p['y'] for p in s['points']] if xy else s['values'])):
            identity=binding.get(dimension+'AxisId')
            if identity and coords is not None:bound_values.setdefault(identity,[]).extend(coords)
    for axis in root.xpath('.//c:valAx',namespaces=NS):
        identity=axis.find('c:axId',NS);scaling=axis.find('c:scaling',NS)
        coords=bound_values.get(identity.get('val')) if identity is not None else None
        if not coords or scaling is None:continue
        for name,clipped in (('min',lambda bound:min(coords)<bound),('max',lambda bound:max(coords)>bound)):
            node=scaling.find('c:'+name,NS)
            if node is not None and clipped(float(node.get('val'))):scaling.remove(node)
    def data_ref(parent,kind,formula,values):
        if book_data is not None:
            # Ref formulas and other cache properties remain in their original
            # position. Literal caches are edited in place as well.
            cache,count=cache_data(parent)
            ref=next((child for child in parent if etree.QName(child).localname.endswith('Ref')),None)
            if ref is not None:
                f=ref.find('c:f',NS)
                if f is None:raise ValueError('pptx_chart_workbook_reference_unsupported')
                book_data.update(f,values)
            # A numeric category range can legitimately become text labels.
            cache_kind=etree.QName(cache).localname
            if kind=='str' and cache_kind in ('numCache','numLit'):
                cache.tag='{%s}%s'%(NS['c'],'strCache' if cache_kind=='numCache' else 'strLit')
                for code in cache.findall('c:formatCode',NS):cache.remove(code)
                if ref is not None:ref.tag='{%s}strRef'%NS['c']
            level=cache.find('c:lvl',NS)
            target=level if level is not None else cache
            for point in target.findall('c:pt',NS):target.remove(point)
            counter=cache.find('c:ptCount',NS)
            if counter is None:
                counter=etree.Element('{%s}ptCount'%NS['c']);cache.insert(1 if cache.find('c:formatCode',NS) is not None else 0,counter)
            counter.set('val',str(len(values)))
            for i,v in enumerate(values):
                point=etree.Element('{%s}pt'%NS['c'],idx=str(i));etree.SubElement(point,'{%s}v'%NS['c']).text=str(v)
                target.insert(next((j for j,n in enumerate(target) if etree.QName(n).localname=='extLst'),len(target)),point)
            return
        code=parent.find('.//c:formatCode',NS)
        format_code=code.text if code is not None else 'General'
        for node in list(parent): parent.remove(node)
        ref=etree.SubElement(parent,'{%s}%sRef'%(NS['c'],kind));etree.SubElement(ref,'{%s}f'%NS['c']).text=formula
        cache=etree.SubElement(ref,'{%s}%sCache'%(NS['c'],kind))
        if kind=='num': etree.SubElement(cache,'{%s}formatCode'%NS['c']).text=format_code
        etree.SubElement(cache,'{%s}ptCount'%NS['c'],val=str(len(values)))
        for i,v in enumerate(values): etree.SubElement(etree.SubElement(cache,'{%s}pt'%NS['c'],idx=str(i)),'{%s}v'%NS['c']).text=str(v)
    for i,s in enumerate(root.xpath('.//c:plotArea/*/c:ser',namespaces=NS)):
        tx=s.find('c:tx',NS)
        if tx is None: tx=etree.Element('{%s}tx'%NS['c']);s.insert(2,tx)
        col=chr(66+i*2) if xy else chr(66+i)
        name=value['series'][i]['name']
        if book_data is not None and tx.find('c:strRef',NS) is None:
            literal=tx.find('c:v',NS)
            if literal is None:literal=etree.SubElement(tx,'{%s}v'%NS['c'])
            literal.text=name
        else:data_ref(tx,'str',f"Data!${col}$1",[name])
        if xy:
            points=value['series'][i]['points'];end=len(points)+1;xcol=chr(65+i*2)
            data_ref(s.find('c:xVal',NS),'num',f'Data!${xcol}$2:${xcol}${end}',[p['x'] for p in points])
            data_ref(s.find('c:yVal',NS),'num',f'Data!${col}$2:${col}${end}',[p['y'] for p in points])
        else:
            end=len(value['categories'])+1
            data_ref(s.find('c:cat',NS),'num' if categories is not None else 'str',f'Data!$A$2:$A${end}',categories if categories is not None else value['categories'])
            data_ref(s.find('c:val',NS),'num',f'Data!${col}$2:${col}${end}',value['series'][i]['values'])
        for point in s.findall('c:dPt',NS):
            idx=point.find('c:idx',NS)
            if idx is not None and int(idx.get('val'))>=end-1:s.remove(point)
    ordered_series=root.xpath('.//c:plotArea/*/c:ser',namespaces=NS)
    for s,label,index,text,match,binding in labels:
        data=value['series'][ordered_series.index(s)]
        values=([p[binding] for p in data['points']] if xy else value['categories'] if binding=='category' else data['values'])
        if index>=len(values):label.getparent().remove(label);continue
        number=values[index]
        if binding=='percent':
            try:
                with localcontext() as context:
                    context.prec=64
                    number=Decimal(str(number))*100/sum((Decimal(str(v)) for v in values),Decimal(0))
            except DecimalException:raise ValueError('pptx_chart_labels_unsupported')
        replacement=str(number)
        if ',' in match.group(2):replacement=replacement.replace('.',',')
        tx=label.find('c:tx',NS)
        rich=tx.find('c:rich',NS)
        if rich is not None:
            start,end=match.span(2);offset=0;inserted=False
            for node in rich.xpath('.//a:t',namespaces=NS):
                current=node.text or '';next_offset=offset+len(current)
                if next_offset>start and offset<end:
                    left=current[:max(0,start-offset)];right=current[max(0,end-offset):]
                    node.text=left+('' if inserted else replacement)+right;inserted=True
                offset=next_offset
        else:
            rendered=text[:match.start(2)]+replacement+text[match.end(2):]
            data_ref(tx,'str','Data!$A$1',[rendered])
    title=root.find('c:chart/c:title',NS)
    if title is not None:
        tx=title.find('c:tx',NS)
        if tx is not None:
            rich=tx.find('c:rich',NS)
            if rich is not None and rich.xpath('.//a:t',namespaces=NS):
                for i,t in enumerate(rich.xpath('.//a:t',namespaces=NS)): t.text=value.get('title','') if i==0 else ''
            elif book_data is not None and tx.find('c:v',NS) is not None:tx.find('c:v',NS).text=value.get('title','')
            else: data_ref(tx,'str',"Data!$A$1",[value.get('title','')])
    relname=relationship_part(spec['part']);rels=xml(parts[relname]) if relname in parts else etree.Element('{%s}Relationships'%NS['pr'])
    old_external=root.find('c:externalData',NS)
    old_rid=old_external.get('{%s}id'%NS['r']) if old_external is not None else None
    for r in list(rels):
        if r.get('Type','').endswith('/package') and r.get('Id')==old_rid: rels.remove(r)
        elif r.get('TargetMode')!='External':
            target=r.get('Target','')
            absolute=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(spec['part']),target))
            r.set('Target',posixpath.relpath(absolute,posixpath.dirname(part)))
    book=f'ppt/embeddings/nerpaChart{slide_index+1}_{spec["shapeId"]}.xlsx'
    rid='nerpaData'
    while any(r.get('Id')==rid for r in rels):rid+='x'
    etree.SubElement(rels,'{%s}Relationship'%NS['pr'],Id=rid,Type=NS['r']+'/package',Target=posixpath.relpath(book,posixpath.dirname(part)))
    external=root.find('c:externalData',NS)
    if external is None: external=etree.SubElement(root,'{%s}externalData'%NS['c'])
    external.set('{%s}id'%NS['r'],rid)
    auto=external.find('c:autoUpdate',NS)
    if auto is None:auto=etree.SubElement(external,'{%s}autoUpdate'%NS['c'])
    if auto.get('val') is None:auto.set('val','0')
    # Chart style/color/media relationships were rebased to the cloned part.
    result[part]=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
    result[relationship_part(part)]=etree.tostring(rels,xml_declaration=True,encoding='UTF-8')
    result[book]=book_data.serialize() if book_data is not None else workbook(value,categories)
    etree.SubElement(content_types,'{%s}Override'%NS['ct'],PartName='/'+part,ContentType='application/vnd.openxmlformats-officedocument.drawingml.chart+xml')
    if not any(n.get('Extension')=='xlsx' for n in content_types):etree.SubElement(content_types,'{%s}Default'%NS['ct'],Extension='xlsx',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    chart_rid='nerpaChart'+str(spec['shapeId'])
    while any(r.get('Id')==chart_rid for r in slide_rels):chart_rid+='x'
    etree.SubElement(slide_rels,'{%s}Relationship'%NS['pr'],Id=chart_rid,Type=NS['r']+'/chart',Target=posixpath.relpath(part,'ppt/slides'))
    node=slide_root.xpath('.//p:cNvPr[@id=$id]',namespaces=NS,id=str(spec['shapeId']))[0].getparent().getparent()
    node.find('.//c:chart',NS).set('{%s}id'%NS['r'],chart_rid)
