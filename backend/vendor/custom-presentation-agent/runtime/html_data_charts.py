"""Data-first charts in the source palette; every mark retains its value."""
import html
import math
from runtime.chart_builder import series_colors
from runtime.chart_numbers import number_label


def _label(x,y,value,ink,anchor='start',size=15):
    return '<text x="%s" y="%s" font-size="%s" text-anchor="%s" fill="%s">%s</text>'%(x,y,size,anchor,ink,html.escape(str(value)))


def data_chart_svg(item,style):
    data=item['data'];width=item['box']['w'];height=item['box']['h'];ink=style['ink']
    nodes=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" font-family="%s">'%(width,height,html.escape(style.get('font','Arial'),quote=True))]
    if data['type'] in ('pie','donut'):
        values=data['series'][0]['values'];total=sum(values)
        if len(data['series'])!=1 or not total>0 or any(value<0 for value in values) or len(values)>6:raise ValueError('html_pie_data_invalid')
        colors=series_colors(style,len(values));radial=style.get('radial',{})
        legend=style.get('legend','right');side=legend=='right';below=legend in ('top','bottom')
        cx=width*(.32 if side else .5);cy=height*(.45 if below else .53)
        radius=min(width*(.27 if side else .42),height*(.32 if below else .40))
        inner=radius*style.get('holeSize',58)/100 if data['type']=='donut' else 0
        start=math.radians(radial.get('startAngle',-90));gap=math.radians(radial.get('gap',0))
        for index,value in enumerate(values):
            angle=value/total*math.tau;end=start+angle;mid=start+angle/2
            title=html.escape('%s: %s'%(data['categories'][index],value))
            if value==0:nodes.append('<g data-chart-value="0"><title>%s</title></g>'%title)
            if value>0:
                actual_gap=min(gap,angle*.2);a=start+actual_gap/2;b=end-actual_gap/2
                if angle>=math.tau-.00001 and not gap:
                    # Two half arcs support a true full ring without a painted centre.
                    outer='M %s %s A %s %s 0 1 1 %s %s A %s %s 0 1 1 %s %s'%(cx,cy-radius,radius,radius,cx,cy+radius,radius,radius,cx,cy-radius)
                    hole=' M %s %s A %s %s 0 1 0 %s %s A %s %s 0 1 0 %s %s'%(cx,cy-inner,inner,inner,cx,cy+inner,inner,inner,cx,cy-inner) if inner else ''
                    path=outer+hole+' Z'
                else:
                    x1,y1=cx+radius*math.cos(a),cy+radius*math.sin(a);x2,y2=cx+radius*math.cos(b),cy+radius*math.sin(b)
                    path='M %s %s A %s %s 0 %s 1 %s %s'%(x1,y1,radius,radius,1 if b-a>math.pi else 0,x2,y2)
                    if inner:
                        ix2,iy2=cx+inner*math.cos(b),cy+inner*math.sin(b);ix1,iy1=cx+inner*math.cos(a),cy+inner*math.sin(a)
                        path+=' L %s %s A %s %s 0 %s 0 %s %s Z'%(ix2,iy2,inner,inner,1 if b-a>math.pi else 0,ix1,iy1)
                    else:path+=' L %s %s Z'%(cx,cy)
                nodes.append('<path data-chart-series="%s" data-chart-value="%s" d="%s" fill="%s" fill-rule="evenodd" stroke="%s" stroke-width="%s"><title>%s</title></path>'%(index,value,path,colors[index],radial.get('stroke','none'),radial.get('strokeWidth',0),title))
                label_mode=radial.get('labels','none')
                if label_mode!='none' and angle>=.20:
                    from runtime.contrast import luminance
                    label=number_label(value) if label_mode=='value' else number_label(round(value/total*100,1))+'%'
                    distance=(inner+radius)/2
                    nodes.append(_label(cx+distance*math.cos(mid),cy+distance*math.sin(mid)+4,label,'#FFFFFF' if luminance(colors[index])<.45 else '#111111','middle',14))
            start=end
            if legend=='none':continue
            if side:
                x=width*.65;y=cy-(len(values)-1)*18+index*36
            else:
                cols=min(3,len(values));col=index%cols;row=index//cols
                x=12+col*width/cols;y=(height-45 if legend=='bottom' else 40)+row*23
            nodes.append('<rect x="%s" y="%s" width="10" height="10" rx="2" fill="%s"/>'%(x,y-9,colors[index]))
            label=data['categories'][index];limit=max(8,int((width*.30 if side else width/min(3,len(values))-25)/6.5))
            nodes.append(_label(x+18,y,label if len(label)<=limit else label[:limit-1]+'…',ink,size=12))
            if side and style.get('showValues',True):nodes.append(_label(width*.97,y,number_label(value),ink,'end',12))
        center=radial.get('center','none')
        if inner and center!='none':
            label=number_label(total) if center=='total' else number_label(max(values)/total*100)+'%'
            nodes.append(_label(cx,cy+8,label,ink,'middle',min(34,inner*.5)))
    else:
        count=len(data['categories']);series_count=len(data['series']);values=[value for series in data['series'] for value in series['values']]
        low=min(0,min(values));high=max(0,max(values));high=high if high>low else low+1
        left=width*.32;right=width*.84;top=36;bottom=height-35;row=(bottom-top)/max(1,count)
        x=lambda value:left+(value-low)/(high-low)*(right-left)
        colors=series_colors(style,series_count);bars=style.get('bars',{})
        for tick in range(5):
            value=low+(high-low)*tick/4;xp=x(value)
            if style.get('grid','vertical') in ('vertical','both'):nodes.append('<path d="M %s %s V %s" fill="none" stroke="%s" opacity=".16"/>'%(xp,top,bottom,ink))
            if style.get('axes',True):nodes.append(_label(xp,bottom+24,number_label(value),ink,'middle',13))
        for i,category in enumerate(data['categories']):
            center=top+row*(i+.5);limit=max(8,int((left-10)/6.5));label=str(category)
            nodes.append(_label(left-10,center+4,label if len(label)<=limit else label[:limit-1]+'…',ink,'end',14))
            for si,series in enumerate(data['series']):
                value=series['values'][i];bar_height=min(30,row*bars.get('widthRatio',.65)/max(1,series_count));y=center+(si-(series_count-1)/2)*(bar_height+2)
                nodes.append('<rect data-chart-series="%s" data-chart-value="%s" x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s"><title>%s</title></rect>'%(si,value,min(x(0),x(value)),y-bar_height/2,max(.2,abs(x(value)-x(0))),bar_height,bars.get('radius',3),colors[si],html.escape('%s: %s'%(category,value))))
                if series_count==1 and style.get('showValues',True):
                    label=number_label(value)
                    inside=bars.get('valuePosition')=='inside' and abs(x(value)-x(0))>len(label)*8+14
                    from runtime.contrast import luminance
                    label_ink=('#FFFFFF' if luminance(colors[si])<.45 else '#111111') if inside else ink
                    nodes.append(_label(x(value)+((-7 if value>=0 else 7) if inside else (-5 if value<0 else 5)),y+4,label,label_ink,('end' if value>=0 else 'start') if inside else ('end' if value<0 else 'start'),14))
    if data.get('title'):nodes.append(_label(8,20,data['title'],ink,size=16))
    nodes.append('</svg>');return ''.join(nodes)
