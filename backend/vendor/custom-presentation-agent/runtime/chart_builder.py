"""Create editable, data-only charts for source-derived PPTX layouts.

The generated sample values describe layout capacity only. The normal native
chart contract replaces them using independently verified presentation facts.
"""
import hashlib
import re
from lxml import etree
from runtime.security import NS
from runtime.charts import workbook

def node(parent, tag, **attrs):
    prefix, name = tag.split(':')
    return etree.SubElement(parent, '{%s}%s' % (NS[prefix], name), {k: str(v) for k, v in attrs.items()})

def solid(parent, color):
    node(node(parent, 'a:solidFill'), 'a:srgbClr', val=color.lstrip('#'))

def chart_font(parent, style, size=14):
    text = node(parent, 'c:txPr')
    node(text, 'a:bodyPr')
    node(text, 'a:lstStyle')
    paragraph = node(text, 'a:p')
    props = node(node(paragraph, 'a:pPr'), 'a:defRPr', sz=round(size * 100))
    solid(props, style['ink'])
    for tag in ('a:latin', 'a:ea', 'a:cs'):
        node(props, tag, typeface=style['font'])
    node(paragraph, 'a:endParaRPr', lang='ru-RU')

def data_reference(parent, kind, formula, values):
    reference = node(parent, 'c:' + kind + 'Ref')
    node(reference, 'c:f').text = formula
    cache = node(reference, 'c:' + kind + 'Cache')
    if kind == 'num':
        node(cache, 'c:formatCode').text = 'General'
    node(cache, 'c:ptCount', val=len(values))
    for index, value in enumerate(values):
        node(node(cache, 'c:pt', idx=index), 'c:v').text = str(value)

def select_chart_style(style,kind=None):
    local=style.get('chartStyle') or {}
    library=[local,*style.get('chartStyles',[])]
    library=[p for p in library if p]
    def family(value):
        return 'radial' if value in ('pie','donut') else 'bar' if value in ('bar','bar-horizontal') else 'line'
    def score(p):
        return (100 if p.get('type')==kind else 70 if family(p.get('type'))==family(kind) else 0)+(10 if p==local else 0)+p.get('confidence',0)
    return max(library,key=score,default={}) if kind else local


def chart_presentation_style(style,kind=None,series_count=1):
    """One chart-only theme drives SVG and native OOXML, including a style
    learned from an image. Its sample pixels are never a numeric data source.
    """
    result=dict(style)
    profile=select_chart_style(style,kind)
    result['chartStyle']=profile
    palette=[value for value in profile.get('palette',[]) if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)]
    if palette:result.update(accent=palette[0],seriesColors=palette)
    if profile.get('font'):result['font']=profile['font']
    if re.fullmatch(r'#[0-9a-fA-F]{6}',str(profile.get('ink',''))):result['ink']=profile['ink']
    # White labels INSIDE a source bar are not white axis labels on a white
    # chart surface. Keep the source hue when readable, otherwise ordinary ink.
    background=style.get('chartBackground') or style.get('sourceSurface')
    if background:
        from runtime.contrast import ratio
        if ratio(result['ink'],background)<4.5:result['ink']=style['ink']
    for key in ('grid','legend','axes','showValues','markers','lineWidth','holeSize','fills','bars','line','radial','axisLine','gridOpacity','legendMarker'):
        if key in profile:result[key]=profile[key]
    if kind in ('bar','bar-horizontal') and profile.get('type') in ('bar','bar-horizontal') and kind!=profile['type'] and result.get('fills'):
        # A long-category ranking may require horizontal bars. Rotate the
        # source fade with the bar axis, keeping the vivid end at the value.
        turn=90 if kind=='bar-horizontal' else -90
        result['fills']=[dict(fill,angle=(fill.get('angle',90)+turn)%360) for fill in result['fills']]
    # A source ring has no axes. Reusing its colors for a new time series
    # must not accidentally hide the quantitative scale of that new graph.
    if kind in ('line','xy') and profile.get('type') and profile.get('type') not in ('line','xy'):
        result.update(axes=True,axisLine='baseline',grid='horizontal')
        # Transferring visual language does not transfer a pie's percentage
        # labels or turn a time series into a composition.
        result.pop('radial',None)
        # A bar can fade almost into its background; a thin quantitative line
        # cannot. Transfer its source hues with sufficient line contrast.
        if result.get('fills'):
            inks=[contrasting_series_color(value,style) for value in palette]
            result['fills']=[dict(angle=0,stops=[dict(offset=0,color=inks[i]),dict(offset=1,color=inks[(i+1)%len(inks)])]) for i in range(len(inks))]
    if kind in ('pie','donut') and profile:
        # Blank template rings often have no real category labels. Preserve
        # their appearance, but never deliver an unexplained multicolour ring.
        if result.get('legend')=='none':result.update(legend='right',showValues=True)
    if kind in ('line','xy'):
        result['lineWidth']=max(2.4,result.get('lineWidth',2.4))
    if kind in ('bar','bar-horizontal','line','xy') and series_count>1 and result.get('legend')=='none':
        # An unlabelled sample ring is a colour/style reference, never
        # permission to hide the identities of new quantitative series.
        result['legend']='bottom'
    result.setdefault('surface','#DADADA')
    return result

def series_colors(style, count):
    palette = list(dict.fromkeys([*style.get('seriesColors', []), style['accent']]))
    # Different lightnesses of the source accent are deterministic and retain
    # the uploaded theme without introducing unrelated hard-coded branding.
    for ratio in (.30, .55, .72, .15, .43):
        accent = style['accent'].lstrip('#')
        palette.append('#' + ''.join('%02X' % round(int(accent[i:i+2], 16) * (1-ratio) + 255 * ratio) for i in (0, 2, 4)))
    if style.get('chartStyle',{}).get('type') in ('pie','donut') and style.get('radial'):return palette[:count]
    return [contrasting_series_color(value,style) for value in palette[:count]]

def contrasting_series_color(value,style):
    from runtime.contrast import ratio,luminance
    background=style.get('chartBackground') or style.get('sourceSurface')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(background or '')) or ratio(value,background)>=3:return value
    target=0 if luminance(background)>.4 else 255
    rgb=[int(value[i:i+2],16) for i in (1,3,5)]
    for step in range(1,11):
        amount=step/10;candidate='#'+''.join('%02X'%round(v*(1-amount)+target*amount) for v in rgb)
        if ratio(candidate,background)>=3:return candidate
    return candidate

def add_data_chart(tree, shape_id, box, style, result, rels, content_types, key, kind='bar', series_count=1):
    """Append a native chart and embedded XLSX, returning its part name.

    Source templates with existing charts continue to use their original
    objects. These newly owned layouts support 1..6 rows without weakening
    the original-chart series/axis preservation rules.
    """
    if kind not in ('bar', 'bar-horizontal', 'line', 'xy', 'pie', 'donut') or not 1 <= series_count <= 6:
        raise ValueError('pptx_data_chart_invalid')
    circular=kind in ('pie','donut')
    bars=kind in ('bar','bar-horizontal')
    if circular and series_count!=1:raise ValueError('pptx_data_chart_invalid')
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    part = 'ppt/charts/nerpaData' + digest + '.xml'
    book = 'ppt/embeddings/nerpaData' + digest + '.xlsx'
    data = dict(title='Показатель', categories=['A', 'B', 'C'], series=[dict(name='Ряд %d' % (i+1), values=[1+i, 2+i, 3+i]) for i in range(series_count)])
    if kind == 'xy':
        data = dict(kind='xy', title='Показатель', series=[dict(name='Ряд %d' % (i+1), points=[dict(x=x, y=x*x+i) for x in (-1, 0, 1)]) for i in range(series_count)])
    root = etree.Element('{%s}chartSpace' % NS['c'], nsmap={p: NS[p] for p in ('c', 'a', 'r')})
    node(root, 'c:lang', val='ru-RU')
    chart = node(root, 'c:chart')
    node(chart, 'c:autoTitleDeleted', val=1)
    plot = node(chart, 'c:plotArea')
    node(plot, 'c:layout')
    graph = node(plot, 'c:' + {'bar': 'barChart', 'bar-horizontal':'barChart', 'line': 'lineChart', 'xy': 'scatterChart', 'pie':'pieChart','donut':'doughnutChart'}[kind])
    if bars:
        node(graph, 'c:barDir', val='bar' if kind=='bar-horizontal' else 'col')
        node(graph, 'c:grouping', val='clustered')
    elif kind == 'line':
        node(graph, 'c:grouping', val='standard')
    elif kind=='xy':
        node(graph, 'c:scatterStyle', val='lineMarker')
    node(graph, 'c:varyColors', val=1 if circular else 0)
    colors = series_colors(style, series_count)
    for index, series in enumerate(data['series']):
        s = node(graph, 'c:ser')
        node(s, 'c:idx', val=index)
        node(s, 'c:order', val=index)
        name_col = chr(66 + index*2) if kind == 'xy' else chr(66 + index)
        data_reference(node(s, 'c:tx'), 'str', 'Data!$%s$1' % name_col, [series['name']])
        shape = node(s, 'c:spPr')
        if bars:
            solid(shape, colors[index])
            node(node(shape, 'a:ln'), 'a:noFill')
        elif not circular:
            solid(node(shape, 'a:ln', w=round(style.get('lineWidth',2)*12700)), colors[index])
            marker = node(s, 'c:marker')
            node(marker, 'c:symbol', val='circle' if style.get('markers',True) else 'none')
            node(marker, 'c:size', val=5)
            solid(node(marker, 'c:spPr'), colors[index])
        if kind == 'xy':
            xcol = chr(65 + index*2)
            data_reference(node(s, 'c:xVal'), 'num', 'Data!$%s$2:$%s$4' % (xcol, xcol), [p['x'] for p in series['points']])
            data_reference(node(s, 'c:yVal'), 'num', 'Data!$%s$2:$%s$4' % (name_col, name_col), [p['y'] for p in series['points']])
        else:
            data_reference(node(s, 'c:cat'), 'str', 'Data!$A$2:$A$4', data['categories'])
            data_reference(node(s, 'c:val'), 'num', 'Data!$%s$2:$%s$4' % (name_col, name_col), series['values'])
        if kind in ('line','xy'):
            node(s, 'c:smooth', val=0)
    if bars or circular or kind in ('line','xy'):
        labels = node(graph, 'c:dLbls')
        node(labels, 'c:numFmt', formatCode='General', sourceLinked=0)
        chart_font(labels, style, 12)
        node(labels, 'c:dLblPos', val='bestFit' if circular else 'outEnd' if bars else 't')
        for name in ('showLegendKey', 'showVal', 'showCatName', 'showSerName', 'showPercent', 'showBubbleSize'):
            node(labels, 'c:' + name, val=1 if name == 'showVal' and style.get('showValues',True) else 0)
        if bars:node(graph, 'c:gapWidth', val=100)
    if not circular:
        node(graph, 'c:axId', val=100)
        node(graph, 'c:axId', val=200)
        for axis_kind, identity, position, cross in [('valAx' if kind == 'xy' else 'catAx', 100, 'l' if kind=='bar-horizontal' else 'b', 200), ('valAx', 200, 'b' if kind=='bar-horizontal' else 'l', 100)]:
            axis = node(plot, 'c:' + axis_kind)
            node(axis, 'c:axId', val=identity)
            scaling = node(axis, 'c:scaling')
            node(scaling, 'c:orientation', val='maxMin' if kind=='bar-horizontal' and axis_kind=='catAx' else 'minMax')
            # Numeric scales remain automatic: tiny errors and negative XY values
            # must never inherit a forced upper bound of one or a positive floor.
            node(axis, 'c:delete', val=0 if style.get('axes',True) else 1)
            node(axis, 'c:axPos', val=position)
            direction='vertical' if position in ('b','t') else 'horizontal'
            if identity == 200 and style.get('grid','both') in ('both',direction):
                grid = node(axis, 'c:majorGridlines')
                solid(node(node(grid, 'c:spPr'), 'a:ln'), style.get('surface', '#EEEEEE'))
            node(axis, 'c:numFmt', formatCode='General', sourceLinked=0)
            node(axis, 'c:majorTickMark', val='none')
            node(axis, 'c:minorTickMark', val='none')
            node(axis, 'c:tickLblPos', val='nextTo')
            node(node(node(axis, 'c:spPr'), 'a:ln'), 'a:noFill')
            chart_font(axis, style, 12)
            node(axis, 'c:crossAx', val=cross)
            node(axis, 'c:crosses', val='max' if kind=='bar-horizontal' and axis_kind=='valAx' else 'autoZero')
            if axis_kind == 'catAx':
                node(axis, 'c:auto', val=1)
                node(axis, 'c:lblAlgn', val='ctr')
                node(axis, 'c:lblOffset', val=100)
            else:
                node(axis, 'c:crossBetween', val='midCat' if kind == 'xy' else 'between')
    elif kind=='donut':
        node(graph,'c:holeSize',val=round(style.get('holeSize',58)))
    if (series_count > 1 or circular) and style.get('legend')!='none':
        legend = node(chart, 'c:legend')
        node(legend, 'c:legendPos', val={'top':'t','right':'r'}.get(style.get('legend'),'b'))
        node(legend, 'c:overlay', val=0)
        chart_font(legend, style, 12)
    node(chart, 'c:plotVisOnly', val=1)
    node(chart, 'c:dispBlanksAs', val='gap')
    node(node(root, 'c:spPr'), 'a:noFill')
    chart_font(root, style, 12)
    external = node(root, 'c:externalData')
    external.set('{%s}id' % NS['r'], 'data')
    node(external, 'c:autoUpdate', val=0)
    result[part] = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
    book_rels = etree.Element('{%s}Relationships' % NS['pr'])
    node(book_rels, 'pr:Relationship', Id='data', Type=NS['r']+'/package', Target='../embeddings/'+book.rsplit('/', 1)[-1])
    result['ppt/charts/_rels/'+part.rsplit('/', 1)[-1]+'.rels'] = etree.tostring(book_rels, xml_declaration=True, encoding='UTF-8')
    result[book] = workbook(data)
    node(content_types, 'ct:Override', PartName='/'+part, ContentType='application/vnd.openxmlformats-officedocument.drawingml.chart+xml')
    if not any(n.get('Extension') == 'xlsx' for n in content_types):
        node(content_types, 'ct:Default', Extension='xlsx', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    rid = 'nerpaDataChart'+digest
    node(rels, 'pr:Relationship', Id=rid, Type=NS['r']+'/chart', Target='../charts/'+part.rsplit('/', 1)[-1])
    frame = node(tree, 'p:graphicFrame')
    nv = node(frame, 'p:nvGraphicFramePr')
    node(nv, 'p:cNvPr', id=shape_id, name='Редактируемый график')
    node(nv, 'p:cNvGraphicFramePr')
    node(nv, 'p:nvPr')
    transform = node(frame, 'p:xfrm')
    node(transform, 'a:off', x=round(box['x']*12700), y=round(box['y']*12700))
    node(transform, 'a:ext', cx=round(box['w']*12700), cy=round(box['h']*12700))
    graphic = node(node(frame, 'a:graphic'), 'a:graphicData', uri=NS['c'])
    node(graphic, 'c:chart').set('{%s}id' % NS['r'], rid)
    return part
