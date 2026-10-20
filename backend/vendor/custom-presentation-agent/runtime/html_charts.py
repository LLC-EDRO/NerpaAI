"""Readable HTML chart labels; data remains complete in the editable chart."""
import html,math,textwrap
from lxml import etree
from runtime.chart_builder import series_colors,chart_presentation_style
from runtime.security import NS,xml
from runtime.chart_numbers import number_label,value_domain


def chart_layout(data,bounds,style):
    width,height=bounds['w'],bounds['h'];count=len(data['categories']);series=len(data['series'])
    legend_mode=style.get('legend','top')
    legend_cols=1 if legend_mode=='right' else max(1,min(series,int(max(1,width-58)//155)))
    legend_rows=math.ceil(series/legend_cols) if series>1 and legend_mode!='none' else 0
    top=32+(26 if data.get('title') else 0)+(legend_rows*23 if legend_mode=='top' else 0)
    bottom=max(top+30,height-76-(legend_rows*23 if legend_mode=='bottom' else 0));left=76;right=max(left+20,width-25-(min(150,width*.23) if legend_mode=='right' and legend_rows else 0))
    label_width=max(64,min(14,max(len(str(s)) for s in data['categories']))*6+12)
    step=max(1,math.ceil(count*label_width/max(1,right-left)))
    return dict(width=width,height=height,left=left,right=right,top=top,bottom=bottom,step=step,
                showValues=style.get('showValues',True) and count*series<=18 and (right-left)/max(1,count*series)>=28,
                colors=series_colors(style,series),labelWidth=label_width,legendCols=legend_cols,legendRows=legend_rows,legendMode=legend_mode)


def chart_svg(item,style):
    style=chart_presentation_style(style,item['data']['type'],len(item['data']['series']))
    item=dict(item,_style=style)
    if item['data']['type'] in ('pie','donut','bar-horizontal'):
        from runtime.html_data_charts import data_chart_svg
        from runtime.html_chart_export import decorate_chart_svg
        return decorate_chart_svg(data_chart_svg(item,style),item)
    data=item['data'];s=chart_layout(data,item['box'],style);e=html.escape
    low,high=value_domain(data)
    y=lambda value:s['bottom']-(value-low)/(high-low)*(s['bottom']-s['top'])
    count=len(data['categories']);series_count=len(data['series'])
    if data['type']=='xy':
        xs=[float(v) for v in data['categories']];xmin=min(xs);xmax=max(xs)
        if xmin==xmax:xmax=xmin+1
        x=lambda index:s['left']+(xs[index]-xmin)/(xmax-xmin)*(s['right']-s['left'])
    else:x=lambda index:s['left']+(index+.5)*(s['right']-s['left'])/count
    nodes=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" style="width:100%%;height:100%%" font-family="%s">'%(s['width'],s['height'],e(style.get('font','Arial'),quote=True))]
    def text(kind,xp,yp,value,anchor='start',size=14,full=None):
        return '<text data-chart-label="%s" x="%s" y="%s" font-size="%s" text-anchor="%s" fill="%s">%s%s</text>'%(kind,xp,yp,size,anchor,style['ink'],e(str(value)),('<title>'+e(str(full))+'</title>') if full is not None else '')
    if data.get('title'):
        limit=max(8,int((s['right']-s['left'])/6.5));title=data['title']
        nodes.append(text('title',s['left'],18,title if len(title)<=limit else title[:limit-1]+'…',size=16,full=title))
    for si,series in enumerate(data['series']):
        if series_count<2 or style.get('legend')=='none':break
        row,col=divmod(si,s['legendCols']);yp=(s['bottom']+55 if s['legendMode']=='bottom' else 20+(22 if data.get('title') else 0))+row*18;xp=(s['right']+16 if s['legendMode']=='right' else s['left'])+col*(s['right']-s['left'])/s['legendCols']
        nodes.append(('<circle cx="%s" cy="%s" r="4" fill="%s"/>'%(xp+4,yp-4,s['colors'][si])) if style.get('legendMarker')=='circle' else '<rect x="%s" y="%s" width="10" height="3" fill="%s"/>'%(xp,yp-6,s['colors'][si]))
        name=series.get('name','');limit=max(5,int((s['right']-s['left'])/s['legendCols']/6)-4)
        nodes.append(text('legend',xp+16,yp,name if len(name)<=limit else name[:limit-1]+'…',full=name))
    for i in range(5):
        value=low+(high-low)*i/4;yp=y(value)
        if style.get('grid','horizontal') in ('horizontal','both'):nodes.append('<path d="M %s %s H %s" fill="none" stroke="%s" opacity="%s"/>'%(s['left'],yp,s['right'],style['ink'],style.get('gridOpacity',.18)))
        if style.get('axes',True):nodes.append(text('axis',s['left']-7,yp+4,number_label(value),'end'))
    if style.get('axes',True) and style.get('axisLine','both')!='none':
        path='M %s %s H %s'%(s['left'],y(max(low,min(high,0))),s['right'])
        if style.get('axisLine','both')=='both':path+=' M %s %s V %s'%(s['left'],s['top'],s['bottom'])
        nodes.append('<path d="%s" fill="none" stroke="%s" opacity=".55"/>'%(path,style['ink']))
    for i,label in enumerate(data['categories']):
        if i%s['step'] and i!=count-1:continue
        if i not in (0,count-1) and (count-1-i)*(s['right']-s['left'])/count<s['labelWidth']+12:continue
        # Display at most three short lines; the full category remains in the
        # SVG title and the unchanged chart data/embedded workbook.
        lines=textwrap.wrap(str(label),width=14,break_long_words=True,break_on_hyphens=False) or ['']
        if len(lines)>3:lines=lines[:3];lines[-1]=lines[-1][:-1]+'…'
        xp=max(s['left']+38,min(s['right']-38,x(i)))
        if style.get('grid') in ('vertical','both'):nodes.append('<path d="M %s %s V %s" fill="none" stroke="%s" opacity="%s"/>'%(xp,s['top'],s['bottom'],style['ink'],style.get('gridOpacity',.18)))
        for row,line in enumerate(lines):nodes.append(text('category',xp,s['bottom']+20+row*16,line,'middle',full=label))
    for si,series in enumerate(data['series']):
        points=[];ink=s['colors'][si];bars=style.get('bars',{})
        for i,value in enumerate(series['values']):
            xp=x(i)+(si-(series_count-1)/2)*(s['right']-s['left'])/count/(series_count+1)*(1-bars.get('overlap',0)) if data['type']=='bar' else x(i)
            title=e('%s — %s: %s'%(series.get('name',''),data['categories'][i],value))
            if data['type']=='bar':
                bw=(s['right']-s['left'])/count/(series_count+1)*bars.get('widthRatio',.78)
                muted=bars.get('highlight') in ('max','last') and i!=(series['values'].index(max(series['values'])) if bars.get('highlight')=='max' else count-1)
                bar_ink=bars.get('mutedColor',ink) if muted else ink
                nodes.append('<rect data-chart-series="%s" data-chart-muted="%s" rx="%s" data-chart-value="%s" x="%s" y="%s" width="%s" height="%s" fill="%s"><title>%s</title></rect>'%(si,str(muted).lower(),bars.get('radius',0),value,xp-bw/2,min(y(0),y(value)),bw,max(.2,abs(y(value)-y(0))),bar_ink,title))
            else:
                points.append((x(i),y(value)))
                nodes.append('<circle data-chart-series="%s" data-chart-value="%s" cx="%s" cy="%s" r="%s" fill="%s"><title>%s</title></circle>'%(si,value,x(i),y(value),3.2 if style.get('markers',True) and (count<=12 or i in (0,count-1)) else 0,ink,title))
            if s['showValues'] or style.get('showValues',True) and data['type']=='line' and series_count==1 and i in (0,count-1):
                inside=data['type']=='bar' and bars.get('valuePosition')=='inside' and abs(y(value)-y(0))>22
                label=text('value',xp,y(value)+(16 if value>=0 else -7) if inside else y(value)+(14 if value<0 else -9),number_label(value),'middle',size=12)
                if inside:
                    from runtime.contrast import luminance
                    label=label.replace('fill="'+style['ink']+'"','fill="'+('#FFFFFF' if luminance(ink)<.45 else '#101010')+'"')
                nodes.append(label)
        if points:
            from runtime.html_chart_theme import monotone_path
            curve=style.get('line',{}).get('curve')=='monotone'
            path=monotone_path(points)
            if style.get('line',{}).get('areaOpacity',0)>0:
                area=path+' L %s,%s L %s,%s Z'%(points[-1][0],s['bottom'],points[0][0],s['bottom'])
                nodes.append('<path data-chart-area="true" data-chart-series="%s" d="%s" fill="%s" opacity="%s"/>'%(si,area,ink,style['line']['areaOpacity']))
            attrs='data-chart-line="true" data-chart-series="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"'%(si,ink,style.get('lineWidth',3))
            nodes.append('<path d="%s" %s/>'%(path,attrs) if curve else '<polyline points="%s" %s/>'%(' '.join('%s,%s'%p for p in points),attrs))
    nodes.append('</svg>')
    from runtime.html_chart_export import decorate_chart_svg
    return decorate_chart_svg(''.join(nodes),dict(item,_style=style))


def apply_native_chart_density(parts,part,data,bounds,style,authored=False):
    """The final format adapter follows the HTML's label density, not vice versa.
    Native chart caches and the embedded workbook are never modified here.
    """
    root=xml(parts[part]);s=chart_layout(data,bounds,style)
    # Existing source line/bar colors remain their own hue, but must be
    # visible against the measured HTML surface in both final formats.
    from runtime.chart_builder import contrasting_series_color
    for colour in root.xpath('.//c:ser/c:spPr//a:srgbClr | .//c:ser/c:marker/c:spPr//a:srgbClr',namespaces=NS):
        colour.set('val',contrasting_series_color('#'+colour.get('val'),style).lstrip('#'))
    if authored:
        # Newly authored HTML charts own their title and numeric scale. Do not
        # let PowerPoint/LibreOffice silently hide the title or invent a
        # different axis range. Existing uploaded native charts keep theirs.
        from runtime.chart_builder import node,solid
        chart=root.find('c:chart',NS);deleted=chart.find('c:autoTitleDeleted',NS)
        if deleted is not None:deleted.set('val','0' if data.get('title') else '1')
        if data.get('title') and chart.find('c:title',NS) is None:
            title=etree.Element('{%s}title'%NS['c']);chart.insert(0,title)
            rich=node(node(title,'c:tx'),'c:rich');node(rich,'a:bodyPr');node(rich,'a:lstStyle')
            p=node(rich,'a:p');run=node(p,'a:r');props=node(run,'a:rPr',sz=1200)
            solid(props,style['ink']);node(props,'a:latin',typeface=style['font']);node(run,'a:t').text=data['title']
            node(title,'c:overlay',val=0)
    if data['type'] in ('pie','donut'):
        from runtime.chart_builder import node,solid
        palette=series_colors(style,len(data['categories']))
        for series in root.findall('.//c:ser',NS):
            for old in series.findall('c:dPt',NS):series.remove(old)
            position=next((i for i,n in enumerate(series) if etree.QName(n).localname in ('dLbls','cat','val','extLst')),len(series))
            for index,ink in enumerate(palette):
                point=etree.Element('{%s}dPt'%NS['c']);node(point,'c:idx',val=index);solid(node(point,'c:spPr'),ink);series.insert(position+index,point)
        parts[part]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        return
    if authored:
        low,high=value_domain(data)
        magnitude=max(abs(v) for series in data['series'] for v in series['values'])
        number_format='0.##'+(',,," млрд"' if magnitude>=1e9 else ',," млн"' if magnitude>=1e6 else '," тыс."' if magnitude>=1e4 else '')
        for labels in root.findall('.//c:dLbls',NS):
            fmt=labels.find('c:numFmt',NS)
            if fmt is None:
                fmt=etree.Element('{%s}numFmt'%NS['c']);labels.insert(len(labels.findall('c:dLbl',NS)),fmt)
            fmt.set('formatCode',number_format);fmt.set('sourceLinked','0')
        for axis in root.findall('.//c:valAx',NS):
            if data['type']=='xy' and axis.find('c:axPos',NS).get('val')=='b':continue
            scaling=axis.find('c:scaling',NS)
            fmt=axis.find('c:numFmt',NS)
            if fmt is not None:fmt.set('formatCode',number_format);fmt.set('sourceLinked','0')
            for name,value in [('max',high),('min',low)]:
                for old in scaling.findall('c:'+name,NS):scaling.remove(old)
                node(scaling,'c:'+name,val=value)
            for old in axis.findall('c:majorUnit',NS):axis.remove(old)
            unit=etree.Element('{%s}majorUnit'%NS['c'],val=str((high-low)/4))
            axis.insert(next((i for i,n in enumerate(axis) if etree.QName(n).localname in ('minorUnit','dispUnits','extLst')),len(axis)),unit)
    if not s['showValues']:
        for labels in root.findall('.//c:dLbls',NS):
            for label in [labels,*labels.findall('c:dLbl',NS)]:
                for name in ('showVal','showCatName','showSerName','showPercent'):
                    for value in label.findall('c:'+name,NS):value.set('val','0')
    for axis in root.findall('.//c:catAx',NS):
        if s['step']>1:
            # A mixed-sign column chart crosses the category axis at zero.
            # Keep long labels below all bars, including in LibreOffice which
            # may automatically rotate labels instead of honoring tickLblSkip.
            position=axis.find('c:tickLblPos',NS)
            if position is None:
                position=etree.Element('{%s}tickLblPos'%NS['c']);axis.insert(next((i for i,n in enumerate(axis) if etree.QName(n).localname in ('spPr','txPr','crossAx','crosses','crossesAt','auto','lblAlgn','lblOffset','tickLblSkip','tickMarkSkip','noMultiLvlLbl','extLst')),len(axis)),position)
            position.set('val','low')
        skip=axis.find('c:tickLblSkip',NS)
        if skip is None:
            skip=etree.Element('{%s}tickLblSkip'%NS['c'])
            before=next((i for i,n in enumerate(axis) if etree.QName(n).localname in ('tickMarkSkip','noMultiLvlLbl','extLst')),len(axis));axis.insert(before,skip)
        skip.set('val',str(s['step']))
    parts[part]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
