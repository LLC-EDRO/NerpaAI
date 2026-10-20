"""Bounded editable ring/pie repair. AI binds labels; geometry follows values.

Candidates require percentage labels and a single near-circular group of
closed curved sectors. Arbitrary art, logos and unsupported graphs are never
reinterpreted merely because they contain several coloured shapes.
"""
import math,re
from lxml import etree
from runtime.security import NS

def percentages(text):
    return [float(v.replace(',','.')) for v in re.findall(r'(?<![\d.,])([0-9]{1,3}(?:[.,][0-9]+)?)\s*%',text)]

def candidates(root,slots):
    labels=[dict(key=s['key'],text=s.get('text','')) for s in slots if len(percentages(s.get('text','')))==1]
    if not 2<=len(labels)<=12 or abs(sum(percentages(s['text'])[0] for s in labels)-100)>2:return []
    result=[]
    for group in root.findall('.//p:grpSp',NS):
        shapes=group.findall('p:sp',NS)
        if len(shapes)!=len(labels) or group.findall('p:grpSp',NS) or group.findall('p:pic',NS):continue
        transform=group.find('p:grpSpPr/a:xfrm',NS)
        extent=transform.find('a:chExt',NS) if transform is not None else None
        if extent is None:continue
        w,h=int(extent.get('cx',0)),int(extent.get('cy',0))
        if not w or not h or not .8<w/h<1.25:continue
        members=[]
        for shape in shapes:
            paths=shape.findall('p:spPr/a:custGeom/a:pathLst/a:path',NS)
            if (len(paths)!=1 or shape.find('p:spPr/a:solidFill',NS) is None
                or any((t.text or '').strip() for t in shape.findall('.//a:t',NS))):break
            path=paths[0]
            if any(path.find('a:'+tag,NS) is None for tag in ('close','lnTo','cubicBezTo')):break
            identity=shape.find('p:nvSpPr/p:cNvPr',NS)
            color=shape.find('p:spPr/a:solidFill/a:srgbClr',NS)
            if color is None:break
            members.append(dict(shapeId=int(identity.get('id')),color='#'+color.get('val') if color is not None else None))
        if len(members)==len(shapes):
            result.append(dict(groupId=int(group.find('p:nvGrpSpPr/p:cNvPr',NS).get('id')),sectors=members,sourceLabels=labels))
    # Several candidate groups sharing one label set are ambiguous. Do not
    # guess associations or reshape arbitrary decoration.
    return result if len(result)==1 else []
