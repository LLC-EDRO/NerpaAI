"""Composite protected source bitmaps directly, independent of converter caches.

Some converters omit a repeated SVG's fallback image on individual pages. A
source logo is immutable data: retain its actual picture bytes, crop and bounds
instead of asking a model to redraw it or cropping old sample text from a page.
"""
import io
from pathlib import Path
from PIL import Image,ImageOps
from runtime.security import NS,xml,read_package,relationship_target
from app.presentation.parser.archive import relationship_part


def composite_brand_assets(path,layout,parts,width,height):
    ids={s['shapeId'] for s in layout.get('sourceObjects',[]) if s.get('kind')=='picture' and s.get('role') in ('brand','logo')}
    ids|={r['shapeId'] for r in layout.get('reservedRegions',[]) if r.get('role') in ('brand','logo')}
    if not ids:return 0
    source=xml(parts[layout['part']]);relpart=relationship_part(layout['part'])
    relations={r.get('Id'):r for r in xml(parts[relpart])} if relpart in parts else {}
    objects={s['shapeId']:s for s in layout.get('sourceObjects',[])}
    result=Image.open(path).convert('RGBA');restored=0
    for picture in source.findall('.//p:pic',NS):
        identity=picture.find('p:nvPicPr/p:cNvPr',NS)
        if identity is None or int(identity.get('id')) not in ids:continue
        obj=objects.get(int(identity.get('id')),{});b=obj.get('box')
        if not b or b['w']<=0 or b['h']<=0 or b['w']*b['h']>width*height*.25:continue
        blip=picture.find('p:blipFill/a:blip',NS)
        rel=relations.get(blip.get('{%s}embed'%NS['r'])) if blip is not None else None
        if rel is None or rel.get('TargetMode')=='External':continue
        target=relationship_target(relpart,rel.get('Target'))
        if target not in parts:continue
        try:
            asset=Image.open(io.BytesIO(parts[target])).convert('RGBA')
        except (OSError,ValueError):continue  # Unsupported vectors stay native.
        crop=picture.find('p:blipFill/a:srcRect',NS)
        if crop is not None:
            l,t,r,bottom=[float(crop.get(k,'0'))/100000 for k in ('l','t','r','b')]
            asset=asset.crop((round(asset.width*l),round(asset.height*t),round(asset.width*(1-r)),round(asset.height*(1-bottom))))
        transform=picture.find('p:spPr/a:xfrm',NS)
        if transform is not None:
            if int(transform.get('rot','0')):continue
            if transform.get('flipH') in ('1','true'):asset=ImageOps.mirror(asset)
            if transform.get('flipV') in ('1','true'):asset=ImageOps.flip(asset)
        x,y,w,h=[round(b[k]*(result.width/width if k in ('x','w') else result.height/height)) for k in ('x','y','w','h')]
        if w<1 or h<1:continue
        result.alpha_composite(asset.resize((w,h),Image.Resampling.LANCZOS),(x,y));restored+=1
    if restored:result.convert('RGB').save(path)
    return restored


def restore_scene_brand_assets(scenes,template,folder):
    import json
    from runtime.fonts import effective_source
    if not (folder/'analysis.json').is_file() or not (folder/'source.pptx').is_file():return
    analysis=json.loads((folder/'analysis.json').read_text())
    parts=read_package(effective_source(folder/'source.pptx',folder,analysis).read_bytes(),generated=True)
    originals={s['id']:s for s in analysis['layouts']};styles={s['id']:s for s in template['layouts']};done={}
    for scene in scenes:
        name=scene.get('sourceBackground') or styles[scene['sourceLayoutId']]['background']
        # Both names are server-produced; never follow arbitrary scene paths.
        import re
        if not re.fullmatch(r'html-background-(?:\d{1,3}|edit-[a-f0-9]{24})\.png',name):continue
        key=(scene['sourceLayoutId'],name)
        if key not in done:done[key]=composite_brand_assets(folder/name,originals[scene['sourceLayoutId']],parts,analysis['width'],analysis['height'])
        scene['protectedBrandAssets']=done[key]
