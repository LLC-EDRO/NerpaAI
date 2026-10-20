"""DrawingML primitives used by HTML export and source import."""
import hashlib
import io
from lxml import etree
from PIL import Image
from runtime.security import NS

def node(parent, element, **attrs):
    prefix,tag=element.split(':')
    return etree.SubElement(parent,'{%s}%s'%(NS[prefix],tag),{k:str(v) for k,v in attrs.items()})

def geometry(parent, box, tag='a:xfrm'):
    x=node(parent,tag)
    node(x,'a:off',x=round(box['x']*12700),y=round(box['y']*12700))
    node(x,'a:ext',cx=round(box['w']*12700),cy=round(box['h']*12700))

def solid(parent, color):
    node(node(parent,'a:solidFill'),'a:srgbClr',val=color.lstrip('#'))

def add_shape(tree, shape_id, name, box, color=None):
    shape=node(tree,'p:sp');nv=node(shape,'p:nvSpPr');node(nv,'p:cNvPr',id=shape_id,name=name)
    node(nv,'p:cNvSpPr');node(nv,'p:nvPr');props=node(shape,'p:spPr');geometry(props,box)
    node(node(props,'a:prstGeom',prst='rect'),'a:avLst')
    solid(props,color) if color else node(props,'a:noFill')
    node(node(props,'a:ln'),'a:noFill')
    return shape

def add_text(tree, shape_id, spec, value):
    shape=add_shape(tree,shape_id,'Nerpa '+spec['key'],spec)
    body=node(shape,'p:txBody');bp=node(body,'a:bodyPr',wrap='square',lIns=0,rIns=0,tIns=0,bIns=0,anchor={'top':'t','center':'ctr','bottom':'b'}.get(spec.get('verticalAlign'),'ctr' if spec['key']=='a_title' else 't'))
    node(bp,'a:noAutofit');node(body,'a:lstStyle')
    for line in value.split('\n'):
        p=node(body,'a:p');pp=node(p,'a:pPr',algn={'left':'l','center':'ctr','right':'r'}[spec['align']],marL=0,indent=0)
        node(node(pp,'a:lnSpc'),'a:spcPct',val=110000);node(pp,'a:buNone')
        run=node(p,'a:r');r=node(run,'a:rPr',lang='ru-RU',sz=round(spec['size']*100),b=int(spec['bold']))
        solid(r,spec['color'])
        for tag in ('a:latin','a:ea','a:cs'):node(r,tag,typeface=spec['font'])
        node(run,'a:t').text=line

def add_picture(tree,shape_id,box,payload,result,rels,index):
    name='ppt/media/nerpa-'+hashlib.sha256(payload).hexdigest()+'.png';result[name]=payload
    rid='nerpaAdaptiveImage'+str(index)
    node(rels,'pr:Relationship',Id=rid,Type=NS['r']+'/image',Target='../media/'+name.split('/')[-1])
    pic=node(tree,'p:pic');nv=node(pic,'p:nvPicPr');node(nv,'p:cNvPr',id=shape_id,name='Nerpa generated illustration')
    node(node(nv,'p:cNvPicPr'),'a:picLocks',noChangeAspect=1);node(nv,'p:nvPr')
    fill=node(pic,'p:blipFill');blip=node(fill,'a:blip');blip.set('{%s}embed'%NS['r'],rid)
    with Image.open(io.BytesIO(payload)) as im: ratio=im.width/im.height
    target=box['w']/box['h'];horizontal=round(max(0,(1-target/ratio)*50000));vertical=round(max(0,(1-ratio/target)*50000))
    node(fill,'a:srcRect',l=horizontal,r=horizontal,t=vertical,b=vertical)
    node(node(fill,'a:stretch'),'a:fillRect');props=node(pic,'p:spPr');geometry(props,box);node(node(props,'a:prstGeom',prst='rect'),'a:avLst')

def serialize(root):
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
