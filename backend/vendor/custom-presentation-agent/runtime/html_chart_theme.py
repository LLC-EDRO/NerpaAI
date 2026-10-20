"""Source-derived SVG grammar. Only geometry changes, never observations."""
import math
from lxml import etree


def monotone_path(points):
    """Shape-preserving cubic interpolation through every verified point.
    Tangents vanish at extrema and are limited to prevent invented overshoot.
    """
    if not points:return ''
    if len(points)<3:return 'M '+' L '.join('%s,%s'%p for p in points)
    slopes=[(b[1]-a[1])/(b[0]-a[0]) for a,b in zip(points,points[1:])]
    tangents=[slopes[0],*[(a+b)/2 if a*b>0 else 0 for a,b in zip(slopes,slopes[1:])],slopes[-1]]
    for i,slope in enumerate(slopes):
        if not slope:tangents[i]=tangents[i+1]=0;continue
        a,b=tangents[i]/slope,tangents[i+1]/slope
        scale=3/math.sqrt(a*a+b*b) if a*a+b*b>9 else 1
        tangents[i]=scale*a*slope;tangents[i+1]=scale*b*slope
    path='M %s,%s'%points[0]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        step=(b[0]-a[0])/3
        path+=' C %s,%s %s,%s %s,%s'%(a[0]+step,a[1]+tangents[i]*step,b[0]-step,b[1]-tangents[i+1]*step,*b)
    return path


def apply_source_fills(root,style,identity):
    ns='http://www.w3.org/2000/svg';fills=style.get('fills') or []
    if not fills:return False
    defs=etree.Element('{%s}defs'%ns);root.insert(0,defs)
    for index,fill in enumerate(fills):
        angle=math.radians(fill.get('angle',90));dx,dy=math.cos(angle)/2,math.sin(angle)/2
        gradient=etree.SubElement(defs,'{%s}linearGradient'%ns,id='%s-%d'%(identity,index),x1=str(.5-dx),y1=str(.5-dy),x2=str(.5+dx),y2=str(.5+dy))
        for stop in sorted(fill['stops'],key=lambda s:s['offset']):
            etree.SubElement(gradient,'{%s}stop'%ns,offset=str(stop['offset']),**{'stop-color':stop['color'],'stop-opacity':str(stop.get('opacity',1))})
    for node in root.xpath('.//*[@data-chart-value] | .//*[@data-chart-line] | .//*[@data-chart-area]'):
        index=int(node.get('data-chart-series','0'))%len(fills)
        # A highlighted/muted bar treatment owns its explicit muted colour.
        if node.get('data-chart-muted')=='true':continue
        key='stroke' if node.get('data-chart-line') else 'fill'
        node.set(key,'url(#%s-%d)'%(identity,index))
    return True
