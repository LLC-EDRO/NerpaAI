"""Source-backed HTML shape modernization, isolated to each output slide.

Remove the selected native decoration before drawing its replacement in CSS.
Never mask old artwork with white rectangles and never mutate shared layouts:
two output slides using one source can make different design decisions.
"""
import hashlib
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from copy import deepcopy
from runtime.security import NS, read_package, xml


def editable_shape_ids(layout, width, height):
    if layout.get('htmlRole') != 'content':
        return set()
    title = next((s for s in layout.get('slots',[]) if s['shapeId']==layout.get('htmlTitleShapeId')),None)
    protected=set(layout.get('htmlPreserveShapeIds',[])) | {r.get('shapeId') for r in layout.get('reservedRegions',[]) if r.get('role') in ('brand','logo','chart','table')}
    return {s['shapeId'] for s in layout.get('sourceObjects',[]) if s.get('kind') in ('shape','picture','connector','line') and s.get('canRemove') and
        ((s.get('fill') or {}).get('color') or (s.get('line') or {}).get('color') or s.get('kind') in ('picture','connector','line')) and s.get('box') and s['shapeId'] not in protected and
        s['shapeId']!=layout.get('htmlTitleShapeId') and s.get('role') not in ('brand','logo','footer','page_number','title','header') and
        s['box']['y']>=max(height*.12,title['y']+title['h']-2 if title else 0) and s['box']['w']*s['box']['h']<width*height*.4}


def render_edited_backgrounds(scenes, template, analysis, folder, soffice):
    from runtime.html_deck import clear_content, clear_inherited_samples, neutral_content_art, metric_cards, write_package
    from runtime.assemble import assemble
    from runtime.render import render
    originals={item['id']:item for item in analysis['layouts']}
    styles={item['id']:item for item in template['layouts']}
    original_designs={id(scene):deepcopy(scene.get('sourceDesign')) for scene in scenes}
    variants={}
    for scene in scenes:
        original=originals[scene['sourceLayoutId']]
        allowed=editable_shape_ids(original,analysis['width'],analysis['height'])
        edits={e['shapeId']:e['action'] for e in scene.get('sourceShapeEdits',[]) if type(e.get('shapeId')) is int and e['shapeId'] in allowed and e.get('action') in ('remove','replace')}
        scene['sourceShapeEdits']=[dict(shapeId=k,action=v) for k,v in sorted(edits.items())]
        if not edits:
            scene.pop('sourceBackground',None)
            continue
        # Native paint already detached from this underlay is drawn by SVG.
        # Its edited IDs are filtered in source_art_markup, so another
        # LibreOffice background conversion would be identical work.
        art=styles[original['id']].get('sourceHtml',{}).get('nativeArt',{})
        painted=set()
        from lxml import etree
        for item in art.get('objects',[]):
            painted.add(item['shapeId'])
            painted.update(int(value) for value in etree.fromstring(item['svg'].encode()).xpath('.//*[@data-source-object]/@data-source-object'))
        svg_only=bool(styles[original['id']].get('nativeBackground')) and set(edits)<=painted
        digest=hashlib.sha256(json.dumps([2,analysis['sha256'],scene['sourceLayoutId'],sorted(edits),original.get('htmlRemoveShapeIds',[]),styles[original['id']].get('sourceHtml',{}).get('digest')],sort_keys=True).encode()).hexdigest()[:24]
        target='html-background-edit-'+digest+'.png'
        scene['sourceBackground']=target
        if svg_only:
            scene.pop('sourceBackground',None)
        elif not (folder/target).is_file():
            variants[target]=(original,set(edits))
        # Quality review must not treat intentionally removed source furniture
        # as a protected obstacle, or demand labels inside a removed ellipse.
        if scene.get('sourceDesign'):
            scene['sourceDesign']=deepcopy(scene['sourceDesign'])
            scene['sourceDesign']['artwork']=[a for a in scene['sourceDesign'].get('artwork',[]) if a['shapeId'] not in edits]
    if not variants:
        return
    with tempfile.TemporaryDirectory(prefix='html-shapes-',dir=folder.parent) as temporary:
        work=Path(temporary)
        assemble(folder/'source.pptx',folder,[v[0]['id'] for v in variants.values()],work/'selected.pptx')
        parts=read_package((work/'selected.pptx').read_bytes(),generated=True)
        clear_inherited_samples(parts,analysis)
        for i,(original,ids) in enumerate(variants.values()):
            part='ppt/slides/labSlide%d.xml'%(i+1);root=xml(parts[part]);style=styles[original['id']]
            clear_content(root,original,analysis['width'],analysis['height'],style.get('emptyPictureIds',[]),
                ids)
            from runtime.source_art import detach_source_art
            detach_source_art(root,style.get('sourceHtml',{}).get('nativeArt',{}))
            if style.get('neutralContent'):
                neutral_content_art(root,original,style,analysis['width'])
            from lxml import etree
            parts[part]=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        write_package(parts,work/'edited.pptx')
        try:
            render(work/'edited.pptx',work/'rendered',soffice,timeout=15)
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            # Optional local modernization cannot revoke the whole deck.
            # Restore its actual native design, then let the normal HTML
            # reviewer fit the content to that retained design.
            for scene in scenes:
                if scene.get('sourceBackground') not in variants:continue
                scene.pop('sourceBackground',None);scene['sourceShapeEdits']=[]
                if original_designs[id(scene)] is not None:scene['sourceDesign']=original_designs[id(scene)]
                scene.setdefault('warnings',[]).append(dict(slide=scene.get('index',0)+1,reason='html_shape_edit_unavailable',message='Локальное изменение фигуры не завершилось; сохранено исходное оформление для проверки и редактирования.'))
            return
        for i,target in enumerate(variants):
            shutil.copyfile(work/'rendered'/('slide-%d.png'%i),folder/target)
