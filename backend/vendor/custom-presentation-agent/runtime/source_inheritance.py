"""Resolve source placeholder paint before removing its demonstration words.

An empty inherited text placeholder can stop painting its fill in Impress.
Materialize only inherited source properties; never invent a replacement panel.
"""
from copy import deepcopy
from lxml import etree
from runtime.security import NS,xml,relationship_target
from app.presentation.parser.archive import relationship_part

def insert_property(props,child):
    # DrawingML CT_ShapeProperties has a strict child sequence. Impress accepts
    # some out-of-order nodes that PowerPoint can ask the user to repair.
    order={'xfrm':0,'prstGeom':1,'custGeom':1,'noFill':2,'solidFill':2,'gradFill':2,'blipFill':2,'pattFill':2,'grpFill':2,'ln':3,'effectLst':4,'effectDag':4,'scene3d':5,'sp3d':6,'extLst':9}
    rank=order.get(etree.QName(child).localname,8)
    for index,current in enumerate(props):
        if order.get(etree.QName(current).localname,8)>rank:props.insert(index,child);return
    props.append(child)


def materialize_placeholder_paint(parts):
    cache={}
    def root(name):
        if name not in cache:cache[name]=xml(parts[name])
        return cache[name]
    def parent(name,kind):
        relpart=relationship_part(name)
        if relpart not in parts:return None
        for rel in xml(parts[relpart]):
            if rel.get('Type','').endswith('/'+kind) and not rel.get('TargetMode'):
                target=relationship_target(relpart,rel.get('Target'))
                if target in parts:return target
    def placeholder(shape):return shape.find('p:nvSpPr/p:nvPr/p:ph',NS)
    def match(name,ph):
        for shape in root(name).findall('.//p:sp',NS):
            candidate=placeholder(shape)
            if candidate is not None and candidate.get('idx','0')==ph.get('idx','0') and candidate.get('type','obj')==ph.get('type','obj'):return shape
    fills=('noFill','solidFill','gradFill','blipFill','pattFill','grpFill')
    for name in list(parts):
        if not name.startswith('ppt/slides/') or not name.endswith('.xml'):continue
        layout=parent(name,'slideLayout')
        if not layout:continue
        master=parent(layout,'slideMaster');changed=False
        for shape in root(name).findall('.//p:sp',NS):
            ph=placeholder(shape)
            if ph is None:continue
            donors=[match(p,ph) for p in (layout,master) if p]
            props=shape.find('p:spPr',NS)
            if props is None:continue
            if not any(props.find('a:'+k,NS) is not None for k in fills):
                for donor in donors:
                    if donor is None:continue
                    source=donor.find('p:spPr',NS)
                    paint=next((source.find('a:'+k,NS) for k in fills if source is not None and source.find('a:'+k,NS) is not None),None)
                    if paint is not None:insert_property(props,deepcopy(paint));changed=True;break
            # Filled implicit rectangles are real source panels even after the
            # placeholder is emptied. Explicitly retain their native geometry.
            painted=any(props.find('a:'+k,NS) is not None for k in ('solidFill','gradFill','pattFill'))
            if painted:
                if props.find('a:xfrm',NS) is None:
                    transform=next((d.find('p:spPr/a:xfrm',NS) for d in donors if d is not None and d.find('p:spPr/a:xfrm',NS) is not None),None)
                    if transform is not None:props.insert(0,deepcopy(transform));changed=True
                if props.find('a:prstGeom',NS) is None and props.find('a:custGeom',NS) is None:
                    geometry=etree.Element('{%s}prstGeom'%NS['a'],prst='rect');etree.SubElement(geometry,'{%s}avLst'%NS['a']);insert_property(props,geometry);changed=True
                if props.find('a:ln',NS) is None:
                    line=etree.Element('{%s}ln'%NS['a']);etree.SubElement(line,'{%s}noFill'%NS['a']);insert_property(props,line);changed=True
        if changed:parts[name]=etree.tostring(root(name),xml_declaration=True,encoding='UTF-8',standalone=True)
