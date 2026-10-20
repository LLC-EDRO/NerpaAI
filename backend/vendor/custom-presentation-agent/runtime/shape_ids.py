"""Repair unreferenced duplicate DrawingML shape IDs in an effective copy.

Some exporters reuse the last background shape's ID for a native table. The
parser then loses the table's physical identity. Never guess the target of an
existing animation/connector reference, or rewrite compatibility alternatives.
"""
from collections import Counter
from lxml import etree
from runtime.security import NS,xml

def recover_shape_ids(parts):
    result=dict(parts);repairs=[]
    for part,data in parts.items():
        if not part.startswith(('ppt/slides/','ppt/slideLayouts/','ppt/slideMasters/')) or not part.endswith('.xml'):continue
        root=xml(data)
        nodes=[n for n in root.findall('.//p:cNvPr',NS) if not any(etree.QName(p).localname=='AlternateContent' for p in n.iterancestors())]
        counts=Counter(n.get('id') for n in nodes);duplicates={v for v,n in counts.items() if v is not None and n>1}
        if not duplicates:continue
        references={value for n in root.iter() for key,value in n.attrib.items()
                    if etree.QName(key).localname.lower() in ('spid','shapeid') or
                    (n.tag in ('{%s}stCxn'%NS['a'],'{%s}endCxn'%NS['a']) and key=='id')}
        seen=set();identity=max([int(n.get('id')) for n in root.findall('.//p:cNvPr',NS) if n.get('id','').isdigit()]+[0]);changed=False
        for n in nodes:
            old=n.get('id')
            if old in seen and old not in references:
                identity+=1;n.set('id',str(identity));changed=True
                repairs.append(dict(part=part,originalId=old,recoveredId=str(identity)))
            seen.add(old)
        if changed:result[part]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    return result,repairs
