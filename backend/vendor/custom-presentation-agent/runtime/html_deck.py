"""V3: source artwork -> measured HTML -> editable DrawingML.

Model-authored inert HTML/CSS is rendered with validated text/data bindings;
no uploaded HTML, scripts, paths or remote URLs are executed by the browser.
"""
import base64
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import tempfile
import time
import sys
import subprocess
import zipfile
import posixpath
from copy import deepcopy
from pathlib import Path
from lxml import etree
from PIL import Image, ImageStat
import pymupdf
from runtime.security import NS, xml, read_package, relationship_target
from runtime.fonts import effective_source
from runtime.assemble import assemble
from runtime.render import render
from runtime.drawingml import add_text, add_picture, add_shape, node
from runtime.package_cleanup import compact_package
from runtime.sample_furniture import clean_sample_furniture,ATTRIBUTION
from runtime.html_charts import chart_svg,apply_native_chart_density
from app.presentation.parser.archive import relationship_part

VERSION = 1
ARTWORK_VERSION = 16
LEGAL_MARK=re.compile(r'^(?:\s*\u00a9|\s*copyright\b|\s*all rights reserved\b)',re.I)
COLOR = re.compile(r'#[0-9a-fA-F]{6}\Z')

def color(value, fallback='#202020'):
    return value if isinstance(value, str) and COLOR.fullmatch(value) else fallback

def box(value):
    return {key: float(value.get(key, 0)) for key in ('x', 'y', 'w', 'h')}

def serialize(root):
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

def write_package(parts, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)

def editable_ids(layout):
    protected = {'brand', 'logo', 'footer', 'page_number', 'decoration'}
    return {slot['shapeId'] for slot in layout.get('slots', []) if slot.get('role') not in protected}-set(layout.get('htmlPreserveShapeIds',[]))

def sample_grid_ids(layout):
    """Repeated wide cell artwork is a data grid, not immutable branding."""
    if layout.get('htmlCompositionPolicy')=='source-first':return set()
    protected = {item.get('shapeId') for item in layout.get('reservedRegions', []) if item.get('role') in ('logo','brand','icon')}
    cells = [item for item in layout.get('sourceObjects', []) if item.get('canRemove') and item.get('shapeId') not in protected
             and item.get('kind') in ('picture','shape') and not item.get('hasText')
             and item['box']['w']>=70 and 8<=item['box']['h']<=65 and item['box']['w']/item['box']['h']>=3]
    if len(cells)>=9 and len({round(item['box']['x']/12) for item in cells})>=2 and len({round(item['box']['y']/12) for item in cells})>=3:
        return {item['shapeId'] for item in cells}
    return set()

def empty_content_frames(layout, width, height):
    protected = [item.get('box',item) for item in layout.get('reservedRegions', []) if item.get('role') in ('logo','brand','icon')]
    pictures = [item.get('box',item) for item in layout.get('imageSlots', [])]
    return [item for item in layout.get('sourceObjects', []) if item.get('kind')=='shape' and item.get('canRemove')
            and not item.get('hasText') and (item.get('line') or item.get('role')=='decorative' and item.get('fill'))
            and item['box']['w']>width*.5 and height*.12<item['box']['h']<height*.6
            and not any(intersection(item['box'],bounds)>1 for bounds in protected+pictures)
            and not any(slot.get('text','').strip() and intersection(item['box'],box(slot))>slot.get('w',0)*slot.get('h',0)*.5 for slot in layout.get('slots',[]))]

def empty_picture_ids(parts, layout):
    allowed={item['shapeId'] for item in layout.get('imageSlots',[]) if not item.get('protected') and not item.get('requiresOpaque') and not item.get('virtual')}
    relpart=relationship_part(layout['part']); relationships=xml(parts[relpart]) if relpart in parts else []
    targets={item.get('Id'):relationship_target(relpart,item.get('Target')) for item in relationships if not item.get('TargetMode')}
    source_root=xml(parts[layout['part']])
    result={int(shape.find('p:nvSpPr/p:cNvPr',NS).get('id')) for shape in source_root.findall('.//p:sp',NS)
            if shape.find('p:nvSpPr/p:nvPr/p:ph',NS) is not None and shape.find('p:nvSpPr/p:nvPr/p:ph',NS).get('type')=='pic'
            and shape.find('.//a:blip',NS) is None and shape.find('p:nvSpPr/p:cNvPr',NS) is not None}
    # Existing content photographs are sample material, not immutable design.
    # Background underlays and branding were excluded from `allowed` above.
    result.update(allowed)
    # A sample illustration can be assembled from several separate bitmaps
    # (device frame, screen and a small mark on that screen). Clear the whole
    # owned photo cluster, never leave its smaller old fragments behind.
    containers=[item.get('box') for item in layout.get('imageSlots',[]) if item['shapeId'] in allowed and item.get('box')]
    owned_groups={item.get('parentShapeId') for item in layout.get('sourceObjects',[]) if item['shapeId'] in allowed and item.get('parentShapeId') is not None}
    candidates=[item for item in layout.get('sourceObjects',[]) if item.get('kind')=='picture' and (item.get('canRemove') or item.get('parentShapeId') in owned_groups) and item.get('role') not in ('brand','logo','background','background_image','icon') and item.get('box')]
    size=xml(parts['ppt/presentation.xml']).find('p:sldSz',NS) if 'ppt/presentation.xml' in parts else None
    area_limit=float(size.get('cx'))*float(size.get('cy'))/12700**2*.8 if size is not None else float('inf')
    changed=True
    while changed:
        changed=False
        for item in candidates:
            b=item['box'];area=b['w']*b['h']
            if item['shapeId'] in result or not 0<area<area_limit:continue
            if any(intersection(b,c)>=min(area,c['w']*c['h'])*.98 for c in containers):
                result.add(item['shapeId']);containers.append(b);changed=True
    for picture in xml(parts[layout['part']]).findall('.//p:pic',NS):
        identity=picture.find('p:nvPicPr/p:cNvPr',NS);blip=picture.find('.//a:blip',NS)
        if identity is None or blip is None or int(identity.get('id')) not in allowed:continue
        target=targets.get(blip.get('{%s}embed'%NS['r']))
        if target not in parts:continue
        try:
            with Image.open(io.BytesIO(parts[target])) as image:
                # Flat sample tiles carry no photograph or diagram. Logos,
                # underlays and protected source artwork are excluded above.
                if max(ImageStat.Stat(image.convert('RGB').resize((32,32))).stddev)<2:
                    result.add(int(identity.get('id')))
        except (OSError,ValueError):pass
    return result

def metric_cards(layout, width, height):
    if layout.get('htmlRole') not in (None,'content') or layout.get('htmlNeutralContent'):return []
    numbers=[slot for slot in layout.get('slots',[]) if not slot.get('cell') and slot.get('y',0)>=height*.15
             and slot.get('size',0)>=height*.1 and len(slot.get('text',''))<=40 and re.search(r'\d',slot.get('text',''))]
    result=[]
    for number in numbers[:3]:
        containers=[item for item in layout.get('sourceObjects',[]) if item.get('kind')=='shape' and item.get('fill') and not item.get('hasText')
                    and item['box']['w']*item['box']['h']<width*height*.65 and intersection(item['box'],box(number))>=number['w']*number['h']*.9]
        container=min(containers,key=lambda item:item['box']['w']*item['box']['h'],default=None)
        bounds=container['box'] if container else box(number)
        labels=[slot for slot in layout.get('slots',[]) if slot is not number and slot.get('y',0)>number['y'] and
                abs(slot.get('x',0)-number['x'])<width*.08 and slot.get('y',0)<bounds['y']+bounds['h']+height*.12]
        label=min(labels,key=lambda slot:slot['y'],default=None)
        result.append(dict(number=number,label=label,box=bounds,shapeId=container['shapeId'] if container else None,
                           fill=color((container.get('fill') or {}).get('color')) if container else None))
    return result

def neutral_picture_surface(shape,bounds=None):
    props=shape.find('p:spPr',NS)
    if props is None:props=node(shape,'p:spPr')
    if bounds:
        transform=props.find('a:xfrm',NS)
        if transform is not None:props.remove(transform)
        transform=node(props,'a:xfrm');node(transform,'a:off',x=str(round(bounds['x']*12700)),y=str(round(bounds['y']*12700)))
        node(transform,'a:ext',cx=str(round(bounds['w']*12700)),cy=str(round(bounds['h']*12700)))
    if props.find('a:xfrm',NS) is None:return False
    for hint in shape.findall('.//p:ph',NS):hint.getparent().remove(hint)
    for body in shape.findall('p:txBody',NS):shape.remove(body)
    for fill in list(props):
        if etree.QName(fill).localname in ('noFill','solidFill','gradFill','blipFill','pattFill','grpFill'):props.remove(fill)
    if props.find('a:prstGeom',NS) is None:node(node(props,'a:prstGeom',prst='rect'),'a:avLst')
    node(node(props,'a:solidFill'),'a:srgbClr',val='FFFFFF')
    line=props.find('a:ln',NS)
    if line is not None:props.remove(line)
    node(node(props,'a:ln'),'a:noFill')
    return True

def clear_content(root, layout, width=0, height=0, empty_pictures=(), discarded_cards=()):
    """Retain original artwork/group topology, remove sample data and copy."""
    clean_sample_furniture(root)
    ids = editable_ids(layout)
    ids |= {slot['shapeId'] for slot in layout.get('slots',[]) if slot.get('role')=='page_number'} | set(layout.get('pageNumberShapeIds',[]))
    graphs = {chart['shapeId'] for chart in layout.get('charts', [])}
    grids = sample_grid_ids(layout) | set(empty_pictures) | set(discarded_cards) | set(layout.get('htmlRemoveShapeIds',[]))
    protected={item.get('shapeId') for item in layout.get('reservedRegions',[]) if item.get('role') in ('brand','logo','icon')}
    preserved_text={slot['shapeId'] for slot in layout.get('slots',[]) if slot.get('role') in ('brand','logo') or LEGAL_MARK.search(slot.get('text',''))}|set(layout.get('htmlPreserveShapeIds',[]))
    # Empty image placeholders are authoring controls, not source artwork.
    # Their default icon/hint is otherwise painted by LibreOffice into the PNG.
    grids |= {item['shapeId'] for item in layout.get('imageSlots',[]) if item.get('kind')=='placeholder' and not item.get('protected') and not item.get('virtual')}
    placeholders={item['shapeId'] for item in layout.get('imageSlots',[]) if item.get('kind')=='placeholder' and not item.get('protected') and not item.get('virtual')}
    # Original diagram segments and connectors are design, even where their
    # bounding boxes intersect former labels. Only explicitly reviewed IDs may
    # remove them; a generic panel/separator heuristic destroys radial schemes.
    for shape in list(root.xpath('.//p:sp | .//p:graphicFrame | .//p:pic | .//p:cxnSp | .//p:grpSp', namespaces=NS)):
        identity = shape.find('.//p:cNvPr', NS)
        if identity is None:
            continue
        identity = int(identity.get('id'))
        if identity in placeholders and shape.tag=='{%s}sp'%NS['p']:
            # Keep the original image frame as a neutral source surface when a
            # photograph is unavailable. Removing the whole frame exposed the
            # busy marble background under fallback text. Strip PowerPoint's
            # authoring control so no "click to add picture" icon can render.
            bounds=next((item.get('box') for item in layout.get('imageSlots',[]) if item['shapeId']==identity),None)
            if not neutral_picture_surface(shape,bounds):shape.getparent().remove(shape)
        elif identity in graphs or identity in grids or shape.tag!='{%s}grpSp'%NS['p'] and (shape.find('.//c:chart', NS) is not None or shape.find('.//a:tbl', NS) is not None):
            shape.getparent().remove(shape)
        elif shape.tag=='{%s}grpSp'%NS['p']:
            # Each child below is cleared independently. Clearing a group's
            # descendants here erased a protected wordmark before its child ID
            # could be checked against the branding whitelist.
            continue
        elif identity not in preserved_text and not LEGAL_MARK.search(''.join(shape.xpath('.//a:t/text()',namespaces=NS))):
            for field in shape.findall('.//a:fld',NS):field.getparent().remove(field)
            for text in shape.findall('.//a:t', NS):
                text.text = ''
            props=shape.find('p:spPr',NS)
            if props is not None and any(props.find('a:'+k,NS) is not None for k in ('solidFill','gradFill','pattFill')):
                # Once its words are gone, this is source artwork. Keeping an
                # empty placeholder hint makes Impress suppress even explicit
                # inherited panel geometry; retain it as an ordinary shape.
                for hint in shape.findall('p:nvSpPr/p:nvPr/p:ph',NS):hint.getparent().remove(hint)
            # Original fills/lines belong to the template, including source
            # text panels. Only former wording goes; generated prose remains
            # transparent and cannot introduce additional colored boxes.
    # Master/layout sample fields are cleared in owned clones below too.

def clear_inherited_samples(parts,analysis=None):
    from runtime.source_inheritance import materialize_placeholder_paint,insert_property
    materialize_placeholder_paint(parts)
    branding={slot.get('text','').strip() for layout in (analysis or {}).get('layouts',[]) for slot in layout.get('slots',[]) if slot.get('role') in ('brand','logo') or slot.get('shapeId') in layout.get('htmlPreserveShapeIds',[])}
    for name in list(parts):
        if name.startswith(('ppt/slideMasters/','ppt/slideLayouts/')) and name.endswith('.xml'):
            root=xml(parts[name]);clean_sample_furniture(root)
            for shape in list(root.findall('.//p:sp',NS)):
                # An inherited text placeholder may have a visible solid panel
                # with implicit rect geometry. Clearing its words must not make
                # LibreOffice drop the white panel and expose the colour below.
                props=shape.find('p:spPr',NS)
                if props is not None and props.find('a:xfrm',NS) is not None and props.find('a:solidFill',NS) is not None and props.find('a:prstGeom',NS) is None and props.find('a:custGeom',NS) is None:
                    geometry=etree.Element('{%s}prstGeom'%NS['a'],prst='rect');node(geometry,'a:avLst');insert_property(props,geometry)
                    if props.find('a:ln',NS) is None:
                        line=etree.Element('{%s}ln'%NS['a']);node(line,'a:noFill');insert_property(props,line)
                value=''.join(shape.xpath('./p:txBody//a:t/text()',namespaces=NS)).strip()
                if value not in branding and not LEGAL_MARK.search(value):
                    for field in shape.findall('p:txBody//a:fld',NS):field.getparent().remove(field)
                    for text in shape.findall('p:txBody//a:t',NS):text.text=''
                placeholder=shape.find('p:nvSpPr/p:nvPr/p:ph',NS)
                if placeholder is not None and placeholder.get('type')=='pic' and shape.find('.//a:blip',NS) is None:
                    # A layout's authoring control is not a real white panel.
                    # Local empty picture shapes are handled by clear_content;
                    # promoted inherited controls would leave ghost rectangles
                    # after their actual sample photograph was removed.
                    shape.getparent().remove(shape)
            parts[name]=serialize(root)

def intersection(a, b):
    return max(0, min(a['x']+a['w'], b['x']+b['w'])-max(a['x'], b['x'])) * max(0, min(a['y']+a['h'], b['y']+b['h'])-max(a['y'], b['y']))

def free_region(region, obstacles):
    """Largest remaining rectangle. Protected art is never a layout suggestion."""
    candidates = [region]
    for obstacle in obstacles:
        next_candidates = []
        for candidate in candidates:
            if intersection(candidate, obstacle) < 1:
                next_candidates.append(candidate)
                continue
            left, top = candidate['x'], candidate['y']
            right, bottom = left+candidate['w'], top+candidate['h']
            x, y = obstacle['x'], obstacle['y']
            for item in [dict(x=left, y=top, w=x-left-6, h=candidate['h']),
                         dict(x=x+obstacle['w']+6, y=top, w=right-x-obstacle['w']-6, h=candidate['h']),
                         dict(x=left, y=top, w=candidate['w'], h=y-top-6),
                         dict(x=left, y=y+obstacle['h']+6, w=candidate['w'], h=bottom-y-obstacle['h']-6)]:
                if item['w'] >= 45 and item['h'] >= 28:
                    next_candidates.append(item)
        candidates = sorted(next_candidates, key=lambda item: item['w']*item['h'], reverse=True)[:24]
    return max(candidates, key=lambda item: item['w']*item['h'], default=region)

def describe_layout(layout, analysis):
    width, height = analysis['width'], analysis['height']
    slots = [slot for slot in layout['slots'] if 'cell' not in slot and slot['shapeId'] in editable_ids(layout)]
    title = next((slot for slot in slots if slot['shapeId']==layout.get('htmlTitleShapeId')),
                 next((slot for slot in slots if slot.get('role') in ('title', 'header')), slots[0] if slots else {}))
    bodies = [slot for slot in slots if slot is not title]
    body = max(bodies, key=lambda slot: slot['w']*slot['h'], default=title)
    margin = max(18, width*.045)
    title_box = box(title) if title else dict(x=margin, y=height*.065, w=width-margin*2, h=height*.13)
    title_box.update(w=min(width-title_box['x']-margin/2, max(title_box['w'], width*.60)),
                     h=min(height*.20, max(title_box['h'], height*.12)))
    title_box['x'] = max(0, min(width-40, title_box['x']))
    title_box['y'] = max(0, min(height*.35, title_box['y']))
    title_box['w'] = max(35, min(width-title_box['x'], title_box['w']))
    removed = {slot['shapeId'] for slot in layout['slots'] if 'cell' in slot} | {item['shapeId'] for item in layout.get('charts', [])} | set(layout.get('htmlRemoveShapeIds',[]))
    protected = [box(item.get('box', item)) for item in layout.get('reservedRegions', [])
                 if item.get('role') not in ('chart', 'table') and item.get('shapeId') not in removed]
    grids = sample_grid_ids(layout)
    # Only verified source furniture reserves space. Old bullet markers and
    # sample icons must not shrink the entire content region into a column.
    pictures = [box(item.get('box', item)) for item in layout.get('imageSlots', []) if item.get('shapeId') not in grids|set(layout.get('emptyPictureIds',[]))|removed]
    region = dict(x=margin, y=max(height*.23, title_box['y']+title_box['h']+height*.035),
                  w=width-2*margin, h=height*.90-max(height*.23, title_box['y']+title_box['h']+height*.035))
    region['h'] = max(height*.2, region['h'])
    region = free_region(region, protected+pictures)
    adaptive_region = dict(region)
    # Preserve meaningful source columns and their contrast surfaces. Tiny
    # demonstrative frames are deliberately expanded to actual free space.
    columns = [box(item) for item in bodies if item['w'] >= width*.18 and item['h'] >= height*.20]
    if len(columns) >= 2 and all(intersection(a, b) < 1 for i, a in enumerate(columns) for b in columns[i+1:]):
        columns = sorted(columns, key=lambda item: (item['x'], item['y']))[:4]
    else:
        columns = []
    if body is not title and body.get('w', 0)*body.get('h', 0) >= width*height*.04 and body.get('w',0)>=width*.18 and body.get('h',0)>=height*.18 and not any(intersection(box(body), item)>1 for item in protected+pictures):
        region = box(body)
    for frame in empty_content_frames(layout,width,height):
        bounds=frame['box']
        if bounds['y']>=title_box['y']+title_box['h'] and abs(bounds['x']-region['x'])<width*.15:
            combined=dict(x=min(region['x'],bounds['x']),y=min(region['y'],bounds['y']),
                          w=max(region['x']+region['w'],bounds['x']+bounds['w'])-min(region['x'],bounds['x']),
                          h=max(region['y']+region['h'],bounds['y']+bounds['h'])-min(region['y'],bounds['y']))
            region=free_region(combined,protected+pictures)
    if columns:
        region = dict(x=min(c['x'] for c in columns),y=min(c['y'] for c in columns),
                      w=max(c['x']+c['w'] for c in columns)-min(c['x'] for c in columns),
                      h=max(c['y']+c['h'] for c in columns)-min(c['y'] for c in columns))
    if not bodies:
        # A table-only source has no paragraph frame. Its cell typography is a
        # better body reference than a white heading on a coloured title strip.
        body = next((slot for slot in layout['slots'] if slot.get('role')=='table_cell'), body)
    # A native chart has no paragraph slot. Its real frame anchors the content
    # panel; the heading strip must never become the body by default.
    data_body=max((item['box'] for item in layout.get('sourceObjects',[]) if item.get('kind') in ('chart','table') and item.get('box')),
                  key=lambda b:b['w']*b['h'],default=None) if not bodies else None
    if layout.get('htmlNeutralContent'):
        title_box=dict(x=margin,y=height*.16,w=width-2*margin,h=height*.14)
        region=dict(x=margin,y=height*.36,w=width-2*margin,h=height*.54)
        adaptive_region=dict(region);columns=[]
    elif layout.get('htmlRole') in ('cover','closing','section'):
        # Terminals often have a title and a very short subtitle in one panel.
        # A small subtitle is still intentional; expanding it to the full page
        # places copy on top of the cover artwork instead of its text surface.
        x=max(margin,min(width-margin-60,title.get('x',margin)))
        w=max(60,min(width-margin-x,title.get('w',width-2*margin)))
        y=max(height*.08,min(height*.52,title.get('y',height*.2)))
        h=max(height*.14,min(height*.24,title.get('h',height*.16)))
        title_box=dict(x=x,y=y,w=w,h=h)
        body_y=y+h+height*.035
        region=dict(x=x,y=body_y,w=w,h=max(30,height*.90-body_y))
        adaptive_region=dict(region);columns=[]
    design=design_geometry(layout.get('htmlDesign'),width,height) if not layout.get('htmlNeutralContent') else None
    if design and layout.get('htmlRole')=='content' and not design['content']:design=None
    if design:
        # Vision owns the panel boundaries. Free-space logic can subtract an
        # obstacle inside a panel, but can never expand across its edge.
        title_box=free_region(design['title'],protected+pictures)
        zones=[free_region(area,protected+pictures) for area in design['content']]
        region=dict(max(zones,key=lambda b:b['w']*b['h'],default=title_box))
        adaptive_region=dict(region);columns=zones if len(zones)>1 else []
    fonts = analysis.get('styleProfile', {}).get('fonts', [])
    font = body.get('font') or title.get('font') or (fonts[0] if fonts and isinstance(fonts[0], str) else 'Arial')
    palette = analysis.get('styleProfile', {}).get('colors', [])
    backgrounds=analysis.get('styleProfile',{}).get('backgrounds',[])
    contrast_panels=[item for item in layout.get('sourceObjects',[]) if item.get('kind')=='shape' and item.get('fill')
        and COLOR.fullmatch(str(item['fill'].get('color',''))) and item.get('box',{}).get('w',0)*item.get('box',{}).get('h',0)<width*height*.65
        and body.get('w',0)*body.get('h',0)>0 and intersection(item['box'],box(body))>=body['w']*body['h']*.8]
    source_surface=min(contrast_panels,key=lambda item:item['box']['w']*item['box']['h'],default=None)
    return dict(id=layout['id'], index=layout['index'], role=layout.get('htmlRole','content'), neutralContent=bool(layout.get('htmlNeutralContent')),
                neutralBackground=color(backgrounds[0],'#FFFFFF') if backgrounds else '#FFFFFF',background='html-background-%d.png' % layout['index'],
                title=title_box, body=region, adaptiveBody=adaptive_region, columns=columns, protected=protected,design=design,canvasWidth=width,canvasHeight=height,
                sourceTitle=box(title) if title else title_box,sourceBody=box(body) if body else region,
                sourceDataBody=data_body,
                sourceBodyAnchors=[box(slot) for slot in bodies],
                sourceSurface=source_surface['fill']['color'] if source_surface else None,
                font=font, headingFont=title.get('font') or font,
                size=max(20, min(28, body.get('size', height/22.5) if body.get('w',0)*body.get('h',0)>=width*height*.04 else height/22.5)),
                headingSize=max(24, min(height*.14, title.get('size', height/13.5))),
                ink=color(body.get('color')), titleColor=color(title.get('color')),
                chartStyle=dict(layout['htmlChartStyle'],sourceLayoutId=layout['id']) if layout.get('htmlChartStyle') else None,
                chartStyles=[dict(item['htmlChartStyle'],sourceLayoutId=item['id']) for item in analysis.get('layouts',[]) if item.get('htmlChartStyle') and not item.get('derivedMediaKind')],
                accent=next((color(item) for item in palette if COLOR.fullmatch(item) and
                             max(int(item[i:i+2],16) for i in (1,3,5))-min(int(item[i:i+2],16) for i in (1,3,5))>=25), '#286A78'),
                pictures=[item for item in layout.get('imageSlots',[]) if item.get('shapeId') not in removed], emptyPictureIds=layout.get('emptyPictureIds',[]), charts=layout.get('charts', []),removedShapeIds=layout.get('htmlRemoveShapeIds',[]),
                hadDataVisual=any(item.get('kind') in ('chart','table') for item in layout.get('sourceObjects',[])) or any('cell' in slot for slot in layout['slots']),
                metricCards=[card for card in metric_cards(layout,width,height) if not design or all(any(within(box(slot),area) for area in design['content']) for slot in (card['number'],card['label']) if slot)],
                tableStyle=next((slot for slot in layout.get('slots', []) if 'cell' in slot), None),
                pageNumbers=[dict(slot) for slot in layout.get('slots',[]) if slot.get('role')=='page_number' or slot.get('shapeId') in layout.get('pageNumberShapeIds',[])] or [dict(**item['box'],text=str(layout['index']+1),font=font,size=max(10,min(14,item['box']['h']*.65)),color=color(body.get('color')),align='center') for item in layout.get('sourceObjects',[]) if item.get('role')=='page_number' and item.get('hasText')],attributions=[slot.get('text','') for slot in layout.get('slots',[]) if ATTRIBUTION.search(slot.get('text','')) and not LEGAL_MARK.search(slot.get('text',''))])

def readable_ink(layout, background, width, height):
    """Repair inherited white-on-white copy using the actual source artwork."""
    def luminance(rgb):
        values = [v/255/12.92 if v/255 <= .04045 else ((v/255+.055)/1.055)**2.4 for v in rgb]
        return sum(a*b for a,b in zip(values,(.2126,.7152,.0722)))
    with Image.open(background) as image:
        image = image.convert('RGB')
        from runtime.html_surfaces import neutral_source_surfaces,busy_text_background
        layout['safeSourceSurfaces']=neutral_source_surfaces(image,width,height)
        layout['unsafeTextAnchors']=[]
        if layout.get('role')=='content' and layout['safeSourceSurfaces']:
            for region in layout.get('sourceHtml',{}).get('textRegions',[]):
                if region.get('role')=='title':continue
                bounds={k:v*.75 for k,v in region['box'].items()};size=region['size']*.75
                if busy_text_background(image,dict(bounds,size=size),width,height):
                    layout['unsafeTextAnchors'].append(dict(shapeId=region['shapeId'],role=region['role'],box=bounds,size=size,
                        reason='Original small text is on patterned artwork; a neutral source surface is available'))
        if layout.get('design'):
            precise=[];unresolved=[]
            def snap(bounds):
                # Vision identifies the intended panel; pixels refine its
                # approximate edge. This is a constraint, never a new layout.
                cx=min(image.width-1,max(0,round((bounds['x']+bounds['w']/2)*image.width/width)))
                cy=min(image.height-1,max(0,round((bounds['y']+bounds['h']/2)*image.height/height)))
                pixel=image.getpixel((cx,cy));same=lambda x,y:max(abs(a-b) for a,b in zip(image.getpixel((x,y)),pixel))<=8
                left=right=cx;top=bottom=cy
                while left>0 and same(left-1,cy):left-=1
                while right<image.width-1 and same(right+1,cy):right+=1
                while top>0 and same(cx,top-1):top-=1
                while bottom<image.height-1 and same(cx,bottom+1):bottom+=1
                pw=(right-left)*width/image.width;ph=(bottom-top)*height/image.height
                if pw<width*.16 or ph<height*.1:unresolved.append(bounds);return bounds
                inset=min(10,(right-left)//8,(bottom-top)//8)
                if not all(same(x,y) for x in (left+inset,right-inset) for y in (top+inset,bottom-inset)):unresolved.append(bounds);return bounds
                pad=min(12,pw*.035,ph*.08)
                plane=dict(x=left*width/image.width+pad,y=top*height/image.height+pad,w=pw-pad*2,h=ph-pad*2)
                if not any(all(abs(p[k]-plane[k])<1 for k in ('x','y','w','h')) for p in precise):precise.append(plane)
                x=max(bounds['x'],left*width/image.width+pad);y=max(bounds['y'],top*height/image.height+pad)
                r=min(bounds['x']+bounds['w'],right*width/image.width-pad);b=min(bounds['y']+bounds['h'],bottom*height/image.height-pad)
                return dict(x=x,y=y,w=r-x,h=b-y) if r-x>=35 and b-y>=15 else bounds
            design=layout['design']
            # Source text anchors disambiguate a model's approximate coordinates.
            # A title on a right-hand white panel cannot migrate onto left-hand
            # artwork even when the model returned an inaccurate X coordinate.
            for reference in [layout.get('sourceTitle'),layout.get('sourceDataBody'),layout.get('sourceBody'),*layout.get('sourceBodyAnchors',[])]:
                if reference:snap(reference)
            for reference in [design['title'],*design['content']]:snap(reference)
            def anchored(reference,fallback):
                if not reference:return fallback
                cx=reference['x']+reference['w']/2;cy=reference['y']+reference['h']/2
                candidates=[p for p in precise if p['x']<=cx<=p['x']+p['w'] and p['y']<=cy<=p['y']+p['h']]
                return min(candidates,key=lambda p:p['w']*p['h']) if candidates else fallback
            def verified(bounds):
                candidates=[p for p in precise if within(bounds,p)]
                return min(candidates,key=lambda p:p['w']*p['h']) if candidates else None
            terminal=layout.get('role') in ('cover','closing','section')
            title_plane=(None if terminal else verified(design['title'])) or anchored(layout.get('sourceTitle'),None)
            body_plane=(anchored(layout.get('sourceDataBody'),None) if not terminal else None) or (verified(max(design['content'],key=lambda b:b['w']*b['h'])) if design['content'] and not terminal else None) or anchored(layout.get('sourceBody'),None)
            if terminal and not title_plane:
                # A photographic master may contain a logo absent from slide
                # object metadata. Keep its known original hero placement.
                design['title']=dict(layout['sourceTitle'])
                if design['content']:
                    b=dict(layout['sourceBody']);b['h']=min(height-b['y']-12,max(b['h'],height*.12));design['content']=[b]
                zones=[design['title'],*design['content']]
                x=min(b['x'] for b in zones);y=min(b['y'] for b in zones)
                design['surfaces']=[dict(x=x,y=y,w=max(b['x']+b['w'] for b in zones)-x,h=max(b['y']+b['h'] for b in zones)-y)]
            if title_plane and not body_plane and not within(design['title'],title_plane):
                p=title_plane;source=layout['sourceTitle']
                design['title']=dict(x=p['x'],y=max(p['y'],min(source['y'],p['y']+p['h']*.3)),w=p['w'],h=min(p['h']*.7,max(height*.1,source['h'])))
            def same_plane(a,b):return a and b and all(abs(a[k]-b[k])<2 for k in ('x','y','w','h'))
            source_planes=[]
            for reference in layout.get('sourceBodyAnchors',[]):
                plane=anchored(reference,None)
                if plane and not same_plane(plane,title_plane) and not any(same_plane(plane,p) for p in source_planes):source_planes.append(dict(plane))
            if title_plane and len(source_planes)>1 and len(design['content'])>1:
                design['title']=snap(design['title'])
                if not within(design['title'],title_plane):
                    p=title_plane;design['title']=dict(x=p['x'],y=p['y'],w=p['w'],h=min(p['h'],max(height*.1,layout['sourceTitle']['h'])))
                design['content']=sorted(source_planes,key=lambda p:(p['x'],p['y']))
            elif title_plane and body_plane and (not within(design['title'],title_plane) or
                any(not verified(b) for b in design['content']) or
                layout.get('sourceDataBody') and len(design['content'])==1 and not within(design['content'][0],body_plane) or
                layout.get('role')=='content' and len(design['content'])==1 and design['content'][0]['w']<body_plane['w']*.70):
                if same_plane(title_plane,body_plane):
                    p=title_plane
                    if layout.get('role') in ('cover','closing','section'):
                        design['title']=dict(x=p['x'],y=p['y']+p['h']*.20,w=p['w'],h=p['h']*.43)
                        if design['content']:design['content']=[dict(x=p['x'],y=p['y']+p['h']*.72,w=p['w'],h=p['h']*.23)]
                    else:
                        th=min(p['h']*.22,max(height*.10,layout['sourceTitle']['h']))
                        design['title']=dict(x=p['x'],y=p['y'],w=p['w'],h=th)
                        design['content']=[dict(x=p['x'],y=p['y']+th+14,w=p['w'],h=max(20,p['h']-th-14))]
                else:
                    p=title_plane;source=layout['sourceTitle']
                    design['title']=dict(x=p['x'],y=max(p['y'],min(source['y'],p['y']+p['h']*.3)),w=p['w'],h=min(p['h']*.7,max(height*.1,source['h'])))
                    if design['content']:design['content']=[dict(body_plane)]
                design['content']=[free_region(b,[design['title']]) for b in design['content']]
                if layout.get('role')=='content' and body_plane['w']>width*.60 and body_plane['h']>height*.4:
                    design['variants']=list(dict.fromkeys(design['variants']+['cards','columns']))
            design['title']=snap(design['title']);design['content']=[snap(b) for b in design['content']]
            if terminal:
                # A one-word sample subtitle can be shorter than two real
                # introductory lines. Grow only downward inside its verified
                # original flat panel, never into the cover artwork.
                for b in design['content']:
                    plane=verified(b)
                    if plane:b['h']=max(b['h'],min(height*.16,plane['y']+plane['h']-b['y']))
            if precise:
                # An unresolved patterned area does not validate an entire
                # model canvas. Keep its intended zone, not a broad surface
                # that would permit moving white copy onto unrelated panels.
                design['surfaces']=precise+[dict(zone) for zone in [design['title'],*design['content']] if not any(within(zone,p) for p in precise)]
            layout['title']=free_region(design['title'],layout.get('protected',[]))
            if design['content']:
                zones=[free_region(b,layout.get('protected',[])) for b in design['content']]
                layout['body']=dict(max(zones,key=lambda b:b['w']*b['h']));layout['adaptiveBody']=dict(layout['body']);layout['columns']=zones if len(zones)>1 else []
        if not layout.get('design') and layout.get('role') in ('cover','closing','section'):
            bounds=layout['title'];cx=min(image.width-1,max(0,round((bounds['x']+bounds['w']/2)*image.width/width)))
            cy=min(image.height-1,max(0,round((bounds['y']+bounds['h']/2)*image.height/height)));pixel=image.getpixel((cx,cy))
            same=lambda x,y:max(abs(a-b) for a,b in zip(image.getpixel((x,y)),pixel))<=8
            left=right=cx;top=bottom=cy
            while left>0 and same(left-1,cy):left-=1
            while right<image.width-1 and same(right+1,cy):right+=1
            while top>0 and same(cx,top-1):top-=1
            while bottom<image.height-1 and same(cx,bottom+1):bottom+=1
            pw=(right-left)*width/image.width;ph=(bottom-top)*height/image.height
            if pw>width*.25 and ph>height*.3 and pw*ph<width*height*.88 and all(same(x,y) for x in (left+2,right-2) for y in (top+2,bottom-2)):
                pad=min(24,pw*.06);x=left*width/image.width+pad;y=top*height/image.height+pad
                w=pw-pad*2;h=ph-pad*2
                layout['title']=dict(x=x,y=y+h*.18,w=w,h=h*.42)
                layout['body']=dict(x=x,y=y+h*.65,w=w,h=h*.29)
                layout['adaptiveBody']=dict(layout['body']);layout['columns']=[]
        bounds=layout.get('adaptiveBody',layout['body'])
        body_pixels=[image.getpixel((min(image.width-1,max(0,round((bounds['x']+bounds['w']*(x+.5)/13)*image.width/width))),
                                    min(image.height-1,max(0,round((bounds['y']+bounds['h']*(y+.5)/9)*image.height/height))))) for x in range(13) for y in range(9)]
        layout['busyBody']=max(max(p[c] for p in body_pixels)-min(p[c] for p in body_pixels) for c in range(3))>65
        layout.pop('bodySurface',None);layout.pop('cardSurface',None)
        for bounds, key in [(layout['body'],'ink'), (layout['title'],'titleColor')]:
            samples = sorted(luminance(image.getpixel((min(image.width-1,max(0,round((bounds['x']+bounds['w']*(x+.5)/7)*image.width/width))),
                                                       min(image.height-1,max(0,round((bounds['y']+bounds['h']*(y+.5)/5)*image.height/height)))))) for x in range(7) for y in range(5))
            surface = samples[len(samples)//2]
            if key=='ink':
                centre=(max(0,min(image.width-1,round((bounds['x']+bounds['w']/2)*image.width/width))),max(0,min(image.height-1,round((bounds['y']+bounds['h']/2)*image.height/height))))
                layout['chartBackground']='#'+''.join('%02X'%value for value in image.getpixel(centre))
            ink = luminance(tuple(int(layout[key][i:i+2],16) for i in (1,3,5)))
            if (max(surface,ink)+.05)/(min(surface,ink)+.05)<(3 if key=='titleColor' else 4.5):
                layout[key] = '#FFFFFF' if (1.05/(surface+.05))>((surface+.05)/.0644) else '#202020'
        for marker in layout.get('pageNumbers',[]):
            x=min(image.width-1,max(0,round((marker['x']+marker['w']/2)*image.width/width)))
            y=min(image.height-1,max(0,round((marker['y']+marker['h']/2)*image.height/height)))
            background=luminance(image.getpixel((x,y)))
            ink=luminance(tuple(int(marker['color'][i:i+2],16) for i in (1,3,5)))
            if (max(background,ink)+.05)/(min(background,ink)+.05)<4.5:marker['color']='#202020' if background>.4 else '#FFFFFF'

def neutral_content_art(root, layout, style, width):
    """Learn a content composition from brand tokens if only terminals exist."""
    protected={item.get('shapeId') for item in layout.get('reservedRegions',[]) if item.get('role') in ('brand','logo','footer','page_number')}
    for shape in list(root.xpath('.//p:sp | .//p:pic | .//p:graphicFrame',namespaces=NS)):
        identity=shape.find('.//p:cNvPr',NS)
        if identity is not None and int(identity.get('id')) not in protected:shape.getparent().remove(shape)
    root.set('showMasterSp','0')
    slide=root.find('p:cSld',NS);background=slide.find('p:bg',NS)
    if background is not None:slide.remove(background)
    background=etree.Element('{%s}bg'%NS['p']);props=node(background,'p:bgPr')
    node(node(props,'a:solidFill'),'a:srgbClr',val=style.get('neutralBackground','#FFFFFF').lstrip('#'));slide.insert(0,background)
    tree=slide.find('p:spTree',NS)
    identity=max([int(item.get('id')) for item in root.findall('.//p:cNvPr',NS)]+[1])+1

def prepare_template(folder, soffice,reuse_artwork=False,profiles_only=False,selected_ids=()):
    analysis = json.loads((folder/'analysis.json').read_text())
    source_parts = None
    from runtime.html_source import compile_source_html, SOURCE_HTML_VERSION
    def source_dom(item, previous=None):
        nonlocal source_parts
        receipt=(previous or {}).get('sourceHtml',{})
        if receipt.get('version')==SOURCE_HTML_VERSION and receipt.get('sourceLayoutId')==item['id'] and receipt.get('headingSelection')==dict(reviewed='htmlTitleShapeId' in item,id=item.get('htmlTitleShapeId')) and (previous or {}).get('removedShapeIds',[])==item.get('htmlRemoveShapeIds',[]):
            return receipt
        if source_parts is None:
            source_parts=read_package(effective_source(folder/'source.pptx',folder,analysis).read_bytes(),generated=True)
            from runtime.source_inheritance import materialize_placeholder_paint
            materialize_placeholder_paint(source_parts)
        return compile_source_html(item,analysis,source_parts)
    cached=None
    if reuse_artwork:
        try:cached=json.loads((folder/'html-template.json').read_text())
        except (OSError,ValueError):pass
    selected=set(selected_ids)
    if cached and cached.get('artworkVersion')==ARTWORK_VERSION and cached.get('sourceSha256')==analysis['sha256'] and all(any(old['id']==item['id'] and (profiles_only and item['id'] not in selected or set(old.get('removedShapeIds',[]))==set(item.get('htmlRemoveShapeIds',[])) and (folder/('html-background-%d.png'%item['index'])).is_file() and (not old.get('nativeBackground') or (folder/old['nativeBackground']).is_file())) for old in cached['layouts']) for item in analysis['layouts']):
        old_by_id={item['id']:item for item in cached['layouts']};layouts=[]
        for item in analysis['layouts']:
            if profiles_only and item['id'] not in selected:
                layouts.append(old_by_id[item['id']]);continue
            original=dict(item,emptyPictureIds=old_by_id[item['id']].get('emptyPictureIds',[]))
            style=describe_layout(original,analysis);style['sourceHtml']=source_dom(item,old_by_id[item['id']]);style['nativeBackground']=old_by_id[item['id']].get('nativeBackground');readable_ink(style,folder/style['background'],analysis['width'],analysis['height']);layouts.append(style)
        # A compiler upgrade may turn formerly unsupported paint into SVG.
        # Its old bitmap underlay still contains that paint; detach it before
        # layering SVG, otherwise a local edit leaves the old shape underneath.
        if all(style.get('sourceHtml',{}).get('nativeArt')==old_by_id[style['id']].get('sourceHtml',{}).get('nativeArt') for style in layouts):
            result=dict(version=VERSION,artworkVersion=ARTWORK_VERSION,sourceSha256=analysis['sha256'],width=analysis['width'],height=analysis['height'],layouts=layouts)
            result['digest']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
            (folder/'html-template.json').write_text(json.dumps(result,ensure_ascii=False))
            return dict(result,profilesOnly=profiles_only)
    parts = read_package(effective_source(folder/'source.pptx', folder, analysis).read_bytes(), generated=True)
    from runtime.page_numbers import pagination_padding,pagination_shape_ids
    from runtime.source_art import detach_source_art
    from runtime.source_inheritance import materialize_placeholder_paint
    materialize_placeholder_paint(parts)
    source_parts=dict(parts)
    padding=pagination_padding([xml(source_parts[l['part']]) for l in analysis['layouts'] if not l.get('derivedMediaKind')],analysis['width'],analysis['height'])
    for item in analysis['layouts']:
        markers=pagination_shape_ids(xml(source_parts[item['part']]),analysis['width'],analysis['height'],item['index']+1,padding)
        item['pageNumberShapeIds']=sorted(set(item.get('pageNumberShapeIds',[]))|markers)
        for slot in item.get('slots',[]):
            if slot['shapeId'] in markers:slot['role']='page_number'
    (folder/'analysis.json').write_text(json.dumps(analysis,ensure_ascii=False))
    clear_inherited_samples(parts,analysis)
    for layout in analysis['layouts']:
        root = xml(parts[layout['part']])
        layout['emptyPictureIds']=sorted(empty_picture_ids(parts,layout))
        clear_content(root, layout, analysis['width'], analysis['height'], layout['emptyPictureIds'])
        parts[layout['part']] = serialize(root)
    old_by_id={item['id']:item for item in cached['layouts']} if cached else {}
    layouts = [old_by_id[layout['id']] if profiles_only and layout['id'] not in selected and layout['id'] in old_by_id else describe_layout(layout, analysis) for layout in analysis['layouts']]
    for item,style in zip(analysis['layouts'],layouts):
        if profiles_only and item['id'] not in selected and item['id'] in old_by_id:continue
        style['sourceHtml']=source_dom(item,old_by_id.get(item['id']))
        if style['sourceHtml'].get('nativeArt',{}).get('objects'):style['nativeBackground']='html-native-background-%d.png'%item['index']
    def reusable_background(style):
        old=old_by_id.get(style['id'])
        return bool(reuse_artwork and cached and cached.get('artworkVersion')==ARTWORK_VERSION and cached.get('sourceSha256')==analysis['sha256'] and old and
            set(old.get('removedShapeIds',[]))==set(style.get('removedShapeIds',[])) and old.get('neutralContent')==style.get('neutralContent') and
            old.get('sourceHtml',{}).get('nativeArt')==style.get('sourceHtml',{}).get('nativeArt') and
            (folder/style['background']).is_file() and (not style.get('nativeBackground') or (folder/style['nativeBackground']).is_file()))
    # Updating one sampled chart used to re-render every selected source page
    # twice. Keep unchanged immutable backgrounds and refresh just its pages.
    to_render=[layout for layout in layouts if (not profiles_only or layout['id'] in selected) and not reusable_background(layout)]
    for style in layouts:
        if reusable_background(style):readable_ink(style,folder/style['background'],analysis['width'],analysis['height'])
    # Render one deck per <=40 source pages. No LLM and no per-field converter.
    with tempfile.TemporaryDirectory(prefix='html-template-', dir=folder.parent) as temporary:
        work = Path(temporary)
        blank = work/'source.pptx'
        write_package(parts, blank)
        metadata = dict(analysis, sha256=hashlib.sha256(blank.read_bytes()).hexdigest())
        metadata.pop('preparedSha256', None)
        (work/'analysis.json').write_text(json.dumps(metadata))
        for start in range(0, len(to_render), 40):
            batch = to_render[start:start+40]
            assemble(blank, work, [item['id'] for item in batch], work/'selected.pptx')
            if any(item.get('neutralContent') for item in batch):
                selected_parts=read_package((work/'selected.pptx').read_bytes(),generated=True)
                by_id={item['id']:item for item in analysis['layouts']}
                for index,item in enumerate(batch):
                    if item.get('neutralContent'):
                        part='ppt/slides/labSlide%d.xml'%(index+1);root=xml(selected_parts[part])
                        neutral_content_art(root,by_id[item['id']],item,analysis['width']);selected_parts[part]=serialize(root)
                write_package(selected_parts,work/'selected.pptx')
            render(work/'selected.pptx', work/'rendered', soffice)
            for index, item in enumerate(batch):
                shutil.copyfile(work/'rendered'/('slide-%d.png' % index), folder/item['background'])
                readable_ink(item, folder/item['background'], analysis['width'], analysis['height'])
            if any(item.get('nativeBackground') for item in batch):
                native_parts=read_package((work/'selected.pptx').read_bytes(),generated=True)
                for index,item in enumerate(batch):
                    part='ppt/slides/labSlide%d.xml'%(index+1);root=xml(native_parts[part])
                    detach_source_art(root,item['sourceHtml'].get('nativeArt',{}));native_parts[part]=serialize(root)
                write_package(native_parts,work/'native-base.pptx')
                render(work/'native-base.pptx',work/'native-rendered',soffice)
                for index,item in enumerate(batch):
                    if item.get('nativeBackground'):shutil.copyfile(work/'native-rendered'/('slide-%d.png'%index),folder/item['nativeBackground'])
    result = dict(version=VERSION, artworkVersion=ARTWORK_VERSION, sourceSha256=analysis['sha256'], width=analysis['width'], height=analysis['height'], layouts=layouts)
    result['digest'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    (folder/'html-template.json').write_text(json.dumps(result, ensure_ascii=False))
    # A profiles-only request can still regenerate stale/missing artwork. The
    # sandbox must return those PNGs, not only the new cache receipt; otherwise
    # the host keeps the old background under a falsely current version.
    return dict(result,profilesOnly=profiles_only,refreshedArtwork=[name for item in to_render for name in [item['background'],item.get('nativeBackground')] if name])

def text_node(key, value, bounds, style, heading=False):
    return dict(key=key, text=value, **bounds, font=style['headingFont' if heading else 'font'],
                size=style['headingSize' if heading else 'size'], color=style['titleColor' if heading else 'ink'],
                bold=heading, align='left', verticalAlign='top')

def within(a,b):
    return a['x']>=b['x']-.1 and a['y']>=b['y']-.1 and a['x']+a['w']<=b['x']+b['w']+.1 and a['y']+a['h']<=b['y']+b['h']+.1

def design_geometry(raw,width,height):
    """Validate model output again at the renderer boundary; never execute it."""
    if not isinstance(raw,dict) or raw.get('canvas') not in ('panels','open'):return None
    def rect(value):
        if not isinstance(value,dict):return None
        if any(not isinstance(value.get(k),(int,float)) or isinstance(value[k],bool) or not math.isfinite(value[k]) for k in ('x','y','w','h')):return None
        x,y,w,h=[value[k] for k in ('x','y','w','h')]
        if x<0 or y<0 or w<20 or h<15 or x+w>1000 or y+h>1000:return None
        return dict(x=x*width/1000,y=y*height/1000,w=w*width/1000,h=h*height/1000)
    title=rect(raw.get('title'));content=raw.get('content')
    if not title or not isinstance(content,list) or len(content)>4:return None
    zones=[rect(b) for b in content]
    if not all(zones) or any(intersection(a,b)>1 for i,a in enumerate([title,*zones]) for b in [title,*zones][i+1:]):return None
    surfaces=[rect(b) for b in raw.get('surfaces',[])]
    if surfaces and (not all(surfaces) or any(not any(within(b,a) for a in surfaces) for b in [title,*zones])):return None
    return dict(canvas=raw['canvas'],title=title,content=zones,surfaces=surfaces,variants=[v for v in raw.get('variants',[]) if v in ('stack','cards','columns','split')])

def compose_slide(copy, layout, index, images):
    """Every new slide is HTML; malformed code recovers through HTML too."""
    from runtime.html_author import author_scene
    from runtime.html_source_recovery import recover_source_html
    if copy.get('html'):
        try:return author_scene(copy,layout,index,images)
        except (ValueError,etree.LxmlError) as error:
            detail=type(error).__name__
    else:detail='missing_html'
    scene=author_scene(recover_source_html(copy,layout,images),layout,index,images)
    scene['authored']['source']='source-frame-recovery'
    scene.setdefault('warnings',[]).append(dict(slide=index+1,reason='html_author_recovered',message='Код одного слайда восстановлен из его содержания.',detail=detail))
    return scene

def html_document(scenes, template, folder, images):
    e = html.escape
    width, height = template['width'], template['height']
    styles = '<style>@page{size:%spt %spt;margin:0}*{box-sizing:border-box}html,body{margin:0;padding:0}.slide{position:relative;width:%spt;height:%spt;overflow:hidden;break-after:page}.slide:last-child{break-after:auto}.copy{position:absolute;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.10;margin:0;padding:0}.background{position:absolute;inset:0;width:100%%;height:100%%}img.photo{position:absolute;object-fit:contain}td{padding:0}</style>' % (width, height, width, height)
    chunks = ['<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src data:">', styles, '</head><body>']
    by_id = {item['id']: item for item in template['layouts']}
    for index, scene in enumerate(scenes):
        layout = by_id[scene['sourceLayoutId']]
        variant=scene.get('sourceBackground','')
        background_file=variant if re.fullmatch(r'html-background-edit-[a-f0-9]{24}\.png',variant) else layout.get('nativeBackground') or layout['background']
        background = base64.b64encode((folder/background_file).read_bytes()).decode()
        chunks.append('<section class="slide" data-slide="%d"><img class="background" src="data:image/png;base64,%s">' % (index, background))
        from runtime.source_art import source_art_markup
        chunks.append(source_art_markup(layout,scene))
        if scene.get('authored'):
            from runtime.html_author import author_fragment,BASE_CSS,STYLE_POLICY,source_font_css
            markup,css=author_fragment(scene,layout,chart_svg)
            for number,picture in enumerate(scene.get('images',[])):
                payload=images.get(picture['image'])
                if payload:
                    mime='image/jpeg' if payload.startswith(b'\xff\xd8\xff') else 'image/png'
                    markup=markup.replace('data-image="%d"'%number,'data-image="%d" src="data:%s;base64,%s"'%(number,mime,base64.b64encode(payload).decode()))
            for item in scene['texts']:
                if item['key'].startswith('h_page_'):
                    markup+='<div class="nerpa-bound-text" data-key="%s" style="position:absolute;left:%spt;top:%spt;width:%spt;height:%spt;font-size:%spt;color:%s;text-align:%s">%s</div>'%(item['key'],item['x'],item['y'],item['w'],item['h'],item['size'],item['color'],item.get('align','center'),e(item['text']))
            defaults=':host{font-family:%s;font-size:%spt;color:%s}'%(json.dumps(layout['font']),layout['size'],layout['ink'])
            chunks.append('<div class="ai-host" style="position:absolute;inset:0;contain:paint"><template shadowrootmode="open" shadowrootserializable><style>'+BASE_CSS+defaults+css+STYLE_POLICY+source_font_css(scene)+'</style>'+markup+'</template></div></section>')
            continue
        raise ValueError('pptx_authored_html_required')
    chunks.append('</body></html>')
    return ''.join(chunks)

MEASURE = r"""() => [...document.querySelectorAll('.slide')].map(slide => {
  const result=[],origin=slide.getBoundingClientRect(),root=slide.querySelector('.ai-host')?.shadowRoot||slide;
  const canvas=document.createElement('canvas'),context=canvas.getContext('2d');
  const wordsFit=el=>{
    if(el.dataset.key?.startsWith('h_cell_'))return true;
    const words=(el.textContent.match(/\p{L}+/gu)||[]).filter(word=>word.length>=3&&word.length<=30);
    if(!words.length)return true;
    const style=getComputedStyle(el);context.font=style.font||`${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const available=el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
    return words.every(word=>context.measureText(word).width<=available+1);
  };
  const bounds=el=>{const b=el.getBoundingClientRect();return {x:(b.x-origin.x)*.75,y:(b.y-origin.y)*.75,w:b.width*.75,h:b.height*.75};};
  // Fit semantic groups together before measuring individual runs. Grid cards
  // and vertically centred prose can otherwise overflow their fixed surface
  // while every natural-height paragraph reports no own overflow.
  for(const region of root.querySelectorAll('.stencil .explanation,.source-composition [data-source-shape]:not([data-key])')){
    if(region.querySelector('[data-manual-style], [data-manual-geometry]'))continue;
    let size=parseFloat(getComputedStyle(region).fontSize);
    const fits=()=>{const frame=region.getBoundingClientRect(),cs=getComputedStyle(region);return [...region.querySelectorAll('[data-key]')].every(el=>{const b=el.getBoundingClientRect();return b.top>=frame.top+parseFloat(cs.paddingTop)-1&&b.bottom<=frame.bottom-parseFloat(cs.paddingBottom)+1&&b.left>=frame.left+parseFloat(cs.paddingLeft)-1&&b.right<=frame.right-parseFloat(cs.paddingRight)+1;});};
    while(size>21.4&&!fits()){size=Math.max(21.4,size-.7);region.style.fontSize=size+'px';}
  }
  for(const el of root.querySelectorAll('[data-key]')) {
    const alignment=el.dataset.manualAlign;
    if(['left','center','right'].includes(alignment)){
      const cs=getComputedStyle(el);
      if(cs.display.includes('flex')){
        const column=cs.flexDirection.startsWith('column'),reversed=(cs.direction==='rtl')!==(!column&&cs.flexDirection==='row-reverse');
        const value=alignment==='center'?'center':(alignment==='right')!==reversed?'flex-end':'flex-start';
        el.style.setProperty(column?'align-items':'justify-content',value,'important');
      }else if(cs.display.includes('grid')){
        el.style.setProperty('justify-items',alignment,'important');
        el.style.setProperty('justify-content',alignment,'important');
      }
    }
    const parent=el.parentElement;
    const singleFlex=parent&&getComputedStyle(parent).display==='flex'&&parent.querySelectorAll('[data-key]').length===1;
    const fitsParent=()=>{
      const frames=[];if(singleFlex)frames.push(parent);
      for(let ancestor=parent;ancestor&&ancestor!==root;ancestor=ancestor.parentElement){
        if(ancestor.hasAttribute('data-source-shape')||['hidden','clip'].includes(getComputedStyle(ancestor).overflow))frames.push(ancestor);
      }
      const b=el.getBoundingClientRect();return frames.every(frame=>{const p=frame.getBoundingClientRect(),s=getComputedStyle(frame);
        return b.top>=p.top+parseFloat(s.paddingTop)-1&&b.bottom<=p.bottom-parseFloat(s.paddingBottom)+1&&b.left>=p.left+parseFloat(s.paddingLeft)-1&&b.right<=p.right-parseFloat(s.paddingRight)+1;});
    };
    // Font ascent/descent can exceed a CSS line box, especially in imported
    // serif families. Resolve a natural heading line in the browser before
    // calling a two-pixel font-metric overhang a layout failure.
    if(root!==slide && el.dataset.key==='h_title' && el.firstChild?.nodeType===Node.TEXT_NODE && el.firstChild.length){
      const range=document.createRange();range.setStart(el.firstChild,0);range.setEnd(el.firstChild,String.fromCodePoint(el.firstChild.textContent.codePointAt(0)).length);
      const ink=range.getBoundingClientRect().height,line=parseFloat(getComputedStyle(el).lineHeight);
      if(ink>line+1)el.style.lineHeight=String((ink+1)/parseFloat(getComputedStyle(el).fontSize));
      // Imported PowerPoint headings often have a shorter frame than their
      // browser glyph metrics. Grow into a genuinely free header gap, bounded
      // by the next text/data/photo block; otherwise fit the type in place.
      const frame=el.getBoundingClientRect();
      const peers=[...root.querySelectorAll('[data-key]:not([data-key^="h_page_"]),[data-visual],img[data-image]')].filter(node=>node!==el&&!el.contains(node)).map(node=>node.getBoundingClientRect()).filter(b=>b.top>frame.top+1&&b.right>frame.left+1&&b.left<frame.right-1);
      const bottom=Math.min(origin.bottom-8,...peers.map(b=>b.top-8));
      const height=Math.min(el.scrollHeight,Math.max(0,bottom-frame.top),singleFlex?parent.clientHeight:Infinity);
      if(height>frame.height+1)el.style.height=height+'px';
    }
    const initial=parseFloat(getComputedStyle(el).fontSize)*.75, minimum=el.dataset.manualStyle?initial:Math.min(initial,root===slide||el.dataset.key?.startsWith('h_page_')?12:el.dataset.key==='h_title'?24:16);
    let size=initial;
    // Bounded local measurements replace repeated model rewrites.
    while(size>minimum && (el.scrollHeight>el.clientHeight+1 || el.scrollWidth>el.clientWidth+1 || !wordsFit(el) || !fitsParent())) {
      size=Math.max(minimum,size-0.5);el.style.fontSize=size+'pt';
    }
    const cs=getComputedStyle(el);const rgb=cs.color.match(/[\d.]+/g);
    result.push({key:el.dataset.key,size,font:cs.fontFamily.split(',')[0].replace(/[\"']/g,''),bold:Number(cs.fontWeight)>=600,color:rgb?'#'+rgb.slice(0,3).map(v=>Math.round(Number(v)).toString(16).padStart(2,'0')).join(''):'#202020',align:cs.textAlign==='center'?'center':(['right','end'].includes(cs.textAlign)?'right':'left'),lineHeight:(parseFloat(cs.lineHeight)||parseFloat(cs.fontSize)*1.16)/parseFloat(cs.fontSize),htmlStyle:{paddingTop:parseFloat(cs.paddingTop)*.75,paddingRight:parseFloat(cs.paddingRight)*.75,paddingBottom:parseFloat(cs.paddingBottom)*.75,paddingLeft:parseFloat(cs.paddingLeft)*.75},...bounds(el),overflow:el.scrollHeight>el.clientHeight+1||el.scrollWidth>el.clientWidth+1||!fitsParent()||el.getBoundingClientRect().right>origin.right+1||el.getBoundingClientRect().bottom>origin.bottom+1||el.getBoundingClientRect().left<origin.left-1||el.getBoundingClientRect().top<origin.top-1,
      measuredHeightPt:el.scrollHeight*.75,availableHeightPt:el.clientHeight*.75,inkRects:(()=>{
        const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),lines=[];let n;
        while(n=walker.nextNode()){const r=document.createRange();for(let i=0;i<n.textContent.length;){const c=String.fromCodePoint(n.textContent.codePointAt(i));r.setStart(n,i);r.setEnd(n,i+c.length);const b=r.getBoundingClientRect();i+=c.length;if(!c.trim()||!b.width||!b.height)continue;
          const x=(b.x-origin.x)*.75,y=(b.y-origin.y)*.75,w=b.width*.75,h=b.height*.75,last=lines.at(-1);
          if(last&&Math.abs(last.y-y)<1){last.w=Math.max(last.x+last.w,x+w)-Math.min(last.x,x);last.x=Math.min(last.x,x);last.h=Math.max(last.h,h);}else lines.push({x,y,w,h});
        }}return lines;
      })(),renderedText:(()=>{
        const node=el.firstChild;if(!node)return '';
        const value=node.textContent,range=document.createRange(),lines=[];let line='',top=null;
        for(let i=0;i<value.length;){const char=String.fromCodePoint(value.codePointAt(i));
          if(char==='\n'){lines.push(line);line='';top=null;i+=char.length;continue;}
          range.setStart(node,i);range.setEnd(node,i+char.length);const y=range.getBoundingClientRect().top;
          if(top!==null&&y>top+1){lines.push(line);line='';}line+=char;top=y;i+=char.length;
        }lines.push(line);return lines.join('\n');
      })()});
  }
  const cssShapes=[...root.querySelectorAll('[data-source-surface],[data-graphic],hr')].flatMap(el=>{
    const cs=getComputedStyle(el),paint=el.tagName==='HR'&&parseFloat(cs.borderTopWidth)>0?cs.borderTopColor:cs.backgroundColor,
      rgb=paint.match(/[\d.]+/g);if(!rgb||rgb.length>3&&Number(rgb[3])===0)return [];
    return [{...bounds(el),color:'#'+rgb.slice(0,3).map(v=>Math.round(Number(v)).toString(16).padStart(2,'0')).join(''),radius:(parseFloat(cs.borderRadius)||0)*.75}];
  });
  return {cssShapes,texts:result,shapes:[...root.querySelectorAll('[data-shape]')].map(el=>({index:Number(el.dataset.shape),...bounds(el)})),
    visuals:[...root.querySelectorAll('[data-visual]')].map(el=>({kind:el.dataset.visual,...bounds(el)})),images:[...root.querySelectorAll('img[data-image]')].map(el=>{
      const b=bounds(el),scale=getComputedStyle(el).objectFit==='contain'?Math.min(b.w/el.naturalWidth,b.h/el.naturalHeight):0;
      return {index:Number(el.dataset.image),...b,...(scale?{contentBox:{x:b.x+(b.w-el.naturalWidth*scale)/2,y:b.y+(b.h-el.naturalHeight*scale)/2,w:el.naturalWidth*scale,h:el.naturalHeight*scale}}:{})};})};
})"""

def browser_render(scenes, template, folder, output, images, deadline):
    by_id={layout['id']:layout for layout in template['layouts']}
    from runtime.html_brand_assets import restore_scene_brand_assets
    restore_scene_brand_assets(scenes,template,folder)
    from playwright.sync_api import sync_playwright
    from runtime.render import font_environment
    families = sorted({item['font'] for scene in scenes for item in [*scene['texts'], *scene.get('cells', [])]})
    config = output/'browser-config'; config.mkdir(exist_ok=True)
    env = font_environment(config, families)
    content = html_document(scenes, template, folder, images)
    warnings = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--no-zygote',
                  '--renderer-process-limit=2', '--num-raster-threads=2'], env=env,
            timeout=20000)
        try:
            page = browser.new_page(viewport=dict(width=math.ceil(template['width']*4/3), height=math.ceil(template['height']*4/3)), device_scale_factor=1)
            page.route('**/*', lambda route: route.abort())
            page.set_content(content, wait_until='load', timeout=20000)
            page.evaluate('async () => {await Promise.race([document.fonts.ready,new Promise(r=>setTimeout(r,5000))]);await Promise.all([...document.images].map(im=>im.decode().catch(()=>{})));}')
            measurements = page.evaluate(MEASURE)
            for index, measured in enumerate(measurements):
                by_key = {item['key']: item for item in [*scenes[index]['texts'], *scenes[index].get('cells', [])]}
                for item in measured['texts']:
                    by_key[item['key']].update({key:item[key] for key in ('x','y','w','h','size','lineHeight','font','bold','color','align')})
                    by_key[item['key']]['renderedText'] = item['renderedText']
                    by_key[item['key']]['inkRects'] = item.get('inkRects',[])
                    by_key[item['key']]['htmlStyle'] = item['htmlStyle']
                    lines=item.get('inkRects',[])
                    if lines:
                        x=min(line['x'] for line in lines);y=min(line['y'] for line in lines)
                        by_key[item['key']]['nativeTextBox']=dict(x=x,y=y,
                            w=max(line['x']+line['w'] for line in lines)-x,
                            h=max(line['y']+line['h'] for line in lines)-y)
                    if item['overflow']:
                        warnings.append(dict(slide=scenes[index]['index']+1, key=item['key'], reason='html_text_overflow', message='Проверьте вместимость текстового блока; полный текст сохранён для редактирования.'))
                    if item['size']<16 and len(by_key[item['key']].get('text',''))>=24 and re.match(r'^h_(?:p_|card_\d+_body|step_\d+_body|takeaway)',item['key']):
                        warnings.append(dict(slide=scenes[index]['index']+1,key=item['key'],reason='html_text_too_small',message='Основное пояснение стало слишком мелким. Сократите повторяющийся текст законченными фразами и используйте доступную внутреннюю область; основной текст должен оставаться читаемым, обычно не меньше 16 pt.'))
                for shape in measured['shapes']:scenes[index]['shapes'][shape['index']].update(box(shape))
                for visual in measured['visuals']:scenes[index][visual['kind']]['box']=box(visual)
                scenes[index]['cssShapes']=measured.get('cssShapes',[])
                for picture in measured.get('images',[]):
                    target=scenes[index]['images'][picture['index']];target.update(box(picture))
                    if picture.get('contentBox'):target['contentBox']=picture['contentBox']
                scenes[index]['htmlMeasured']=True
                warnings.extend(scenes[index].get('warnings',[]))
            # Print all artwork in one fresh document. Scrolling screenshot
            # captures of paint-contained shadow roots intermittently lose
            # logos or leave stale visibility masks on subsequent pages.
            page.evaluate("""()=>{for(const host of document.querySelectorAll('.ai-host')){
              const s=document.createElement('style');s.id='export-background';
              s.textContent='[data-key],[data-visual],img[data-image]{visibility:hidden!important}';host.shadowRoot.append(s)}}""")
            background_html=page.evaluate("()=>'<!doctype html><html>'+document.documentElement.getHTML({serializableShadowRoots:true})+'</html>'")
            page.evaluate("()=>{for(const host of document.querySelectorAll('.ai-host'))host.shadowRoot.getElementById('export-background')?.remove()}")
            artwork_page=browser.new_page(viewport=dict(width=math.ceil(template['width']*4/3),height=math.ceil(template['height']*4/3)))
            try:
                artwork_page.route('**/*',lambda route:route.abort())
                artwork_page.set_content(background_html,wait_until='load',timeout=20000)
                artwork_page.evaluate('async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode().catch(()=>{})));}')
                artwork_page.pdf(path=str(output/'authored-layers.pdf'),print_background=True,prefer_css_page_size=True)
            finally:artwork_page.close()
            rasterize_html_pdf(output/'authored-layers.pdf',output,len(scenes),'authored-background')
            (output/'authored-layers.pdf').unlink()
            # Keep CSS artwork separately so native text, photos and data remain editable.
            for index,scene in enumerate(scenes):
                if not scene.get('authored'):continue
                section=page.locator('body > section.slide[data-slide]').nth(index)
                filename=f'authored-background-{index}.png'
                scene['authoredBackground']=filename
                from runtime.html_author import author_contrast_warnings,source_layout_warnings,repair_author_contrast
                repaired=repair_author_contrast(scene,output/filename,template['width'],template['height'],by_id[scene['sourceLayoutId']])
                if repaired:
                    scene['contrastRepairs']=repaired
                    section.evaluate("(el,repairs)=>{const r=el.querySelector('.ai-host').shadowRoot;for(const repair of repairs){const target=[...r.querySelectorAll('[data-key]')].find(node=>node.dataset.key===repair.key);target?.style.setProperty('color',repair.color,'important')}}",repaired)
                warnings.extend(author_contrast_warnings(scene,output/filename,template['width'],template['height']))
                warnings.extend(source_layout_warnings(scene,template['width'],template['height']))
            # Persist the actual measured HTML before optional screenshots.
            final_html=page.evaluate("()=>'<!doctype html><html>'+document.documentElement.getHTML({serializableShadowRoots:true})+'</html>'")
            (output/'presentation.html').write_text(final_html)
            # Reset paint/visibility caches, retaining the exact serialized fit
            # and typography. The accepted PDF must show every decoded image.
            page.set_content(final_html,wait_until='load',timeout=20000)
            page.evaluate('async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode().catch(()=>{})));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}')
            # Keep a complete, vector-text HTML PDF even when the later native
            # converter exhausts its time budget. One print covers every page;
            # optional per-page screenshots must not determine PDF availability.
            page.pdf(path=str(output/'html-preview.pdf'),print_background=True,prefer_css_page_size=True)
            # The printed HTML is the canonical PDF. Chromium's offscreen
            # compositor can produce partially blank section screenshots after
            # printing despite correct DOM geometry. Rasterize that very PDF
            # for previews/vision so all formats show the same complete page.
            rasterize_html_pdf(output/'html-preview.pdf',output,len(scenes))
        finally:
            browser.close()
    from runtime.html_chart_export import capture_chart_pictures
    capture_chart_pictures(scenes,output)
    return warnings

def add_table(tree, identity, item, cells, style):
    from runtime.drawingml import geometry, solid
    frame = node(tree, 'p:graphicFrame')
    nv = node(frame, 'p:nvGraphicFramePr')
    node(nv, 'p:cNvPr', id=identity, name='Nerpa HTML editable table')
    node(nv, 'p:cNvGraphicFramePr'); node(nv, 'p:nvPr')
    geometry(frame, item['box'], 'p:xfrm')
    table = node(node(node(frame, 'a:graphic'), 'a:graphicData', uri='http://schemas.openxmlformats.org/drawingml/2006/table'), 'a:tbl')
    node(table, 'a:tblPr')
    rows = [item['data']['headers'], *item['data']['rows']]
    widths = [round(item['box']['w']*12700/len(rows[0]))]*len(rows[0])
    widths[-1] += round(item['box']['w']*12700)-sum(widths)
    grid = node(table, 'a:tblGrid')
    for width in widths:
        node(grid, 'a:gridCol', w=width)
    specs = {tuple(cell['cell']): cell for cell in cells}
    for r, row in enumerate(rows):
        tr = node(table, 'a:tr', h=round(item['box']['h']*12700/len(rows)))
        for c, value in enumerate(row):
            spec = specs[(r, c)]
            cell = node(tr, 'a:tc'); body = node(cell, 'a:txBody')
            node(body, 'a:bodyPr', wrap='square', anchor='t'); node(body, 'a:lstStyle')
            for line in spec.get('renderedText',value).split('\n'):
                paragraph = node(body, 'a:p'); props = node(paragraph, 'a:pPr', algn='l')
                node(node(props, 'a:lnSpc'), 'a:spcPts', val=round(spec['size']*100*spec.get('lineHeight',1.1)))
                node(node(props, 'a:spcBef'), 'a:spcPts', val=0);node(node(props, 'a:spcAft'), 'a:spcPts', val=0)
                run = node(paragraph, 'a:r'); rp = node(run, 'a:rPr', sz=round(spec['size']*100), b=int(spec['bold']))
                solid(rp, spec['color'])
                for tag in ('a:latin', 'a:ea', 'a:cs'):
                    node(rp, tag, typeface=spec['font'])
                node(run, 'a:t').text = line
            tc = node(cell, 'a:tcPr', marL=63500, marR=63500, marT=50800, marB=50800)
            node(tc, 'a:noFill')
            solid(node(tc, 'a:lnB', w=6350), style['accent'])

def add_notes(parts, part, rels, content_types, scene, index):
    text = scene.get('notes', '')
    chart=scene.get('chart')
    if chart and chart.get('exportedAs')=='image':
        data=chart['data'];rows=[data.get('title',''),'; '.join(['Category',*[s['name'] for s in data['series']]])]
        rows += ['; '.join([category,*[str(s['values'][i]) for s in data['series']]]) for i,category in enumerate(data['categories'])]
        text='\n\n'.join(value for value in [text,'Данные диаграммы (визуал сохранён изображением):\n'+'\n'.join(rows)] if value)
    refs = scene.get('sourceReferences', [])
    photos = [item.get('source') for item in scene.get('images', []) if item.get('source')]
    sources = [str(item.get('title', ''))+'\n'+str(item.get('url', '')) for item in [*refs, *photos]]
    text = '\n\n'.join([value for value in [text, *sources] if value])
    if not text:
        return
    master = next((name for name in parts if re.fullmatch(r'ppt/notesMasters/[^/]+\.xml', name)), None)
    if not master:
        master = 'ppt/notesMasters/nerpaHtmlNotes.xml'
        parts[master] = serialize(xml(('<p:notesMaster xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/></p:notesMaster>' % (NS['p'], NS['a'])).encode()))
        node(content_types, 'ct:Override', PartName='/'+master, ContentType='application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml')
        presentation = xml(parts['ppt/presentation.xml']); relationships = xml(parts['ppt/_rels/presentation.xml.rels'])
        node(relationships, 'pr:Relationship', Id='htmlNotesMaster', Type=NS['r']+'/notesMaster', Target='notesMasters/nerpaHtmlNotes.xml')
        listing = etree.Element('{%s}notesMasterIdLst' % NS['p'])
        node(listing, 'p:notesMasterId').set('{%s}id' % NS['r'], 'htmlNotesMaster')
        presentation.insert(1, listing)
        parts['ppt/presentation.xml'] = serialize(presentation); parts['ppt/_rels/presentation.xml.rels'] = serialize(relationships)
    note_part = 'ppt/notesSlides/nerpaHtml%d.xml' % index
    note = xml(('<p:notes xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t/></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>' % (NS['p'], NS['a'])).encode())
    note.find('.//a:t', NS).text = text; parts[note_part] = serialize(note)
    relationships = etree.Element('{%s}Relationships' % NS['pr'])
    for identity, kind, target in [('slide', 'slide', part), ('master', 'notesMaster', master)]:
        node(relationships, 'pr:Relationship', Id=identity, Type=NS['r']+'/'+kind, Target=posixpath.relpath(target, posixpath.dirname(note_part)))
    parts[relationship_part(note_part)] = serialize(relationships)
    node(rels, 'pr:Relationship', Id='htmlNotes', Type=NS['r']+'/notesSlide', Target=posixpath.relpath(note_part, posixpath.dirname(part)))
    node(content_types, 'ct:Override', PartName='/'+note_part, ContentType='application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml')

def add_measured_text(tree, identity, item):
    # CSS padding/flex alignment can place the text well inside its element.
    # Export the measured text origin, not the container's top-left corner.
    spec=dict(item,**item.get('nativeTextBox',{}),verticalAlign='top')
    add_text(tree,identity,spec,item.get('renderedText',item['text']))
    shape=tree[-1]
    # Browser line breaks are already measured with the actual fonts. Letting
    # PowerPoint/LibreOffice wrap them again splits even a one-word heading
    # when native glyph advances differ by a fraction of a point.
    shape.find('p:txBody/a:bodyPr',NS).set('wrap','none')
    for paragraph in shape.findall('p:txBody/a:p',NS):
        props=paragraph.find('a:pPr',NS)
        for inherited in props.findall('a:lnSpc',NS):props.remove(inherited)
        spacing=etree.Element('{%s}lnSpc'%NS['a']);node(spacing,'a:spcPts',val=round(item['size']*100*item.get('lineHeight',1.1)));props.insert(0,spacing)
        for position,name in [(1,'spcBef'),(2,'spcAft')]:
            spacing=etree.Element('{%s}%s'%(NS['a'],name));node(spacing,'a:spcPts',val=0);props.insert(position,spacing)

def add_html_picture(tree, identity, bounds, payload, parts, rels, content_types, index):
    old='ppt/media/nerpa-'+hashlib.sha256(payload).hexdigest()+'.png';existed=old in parts
    add_picture(tree,identity,bounds,payload,parts,rels,index)
    suffix='jpg' if payload.startswith(b'\xff\xd8\xff') else 'png'
    target=old[:-3]+suffix
    if old!=target:
        parts[target]=parts[old]
        if not existed:parts.pop(old)
    rid=tree[-1].find('p:blipFill/a:blip',NS).get('{%s}embed'%NS['r'])
    for relation in rels:
        if relation.get('Id')==rid:relation.set('Target','../media/'+posixpath.basename(target))
    if not any(item.get('Extension')==suffix for item in content_types):
        node(content_types,'ct:Default',Extension=suffix,ContentType='image/jpeg' if suffix=='jpg' else 'image/png')

def native_export(scenes, template, folder, output, images):
    analysis = json.loads((folder/'analysis.json').read_text())
    from runtime.page_numbers import renumber_pages,pagination_padding
    source_parts=read_package(effective_source(folder/'source.pptx',folder,analysis).read_bytes(),generated=True)
    source_layouts=[item for item in analysis['layouts'] if not item.get('derivedMediaKind')]
    page_padding=pagination_padding([xml(source_parts[item['part']]) for item in source_layouts],analysis['width'],analysis['height'])
    assemble(folder/'source.pptx', folder, [scene['sourceLayoutId'] for scene in scenes], output/'presentation.pptx')
    parts = read_package((output/'presentation.pptx').read_bytes(), generated=True)
    clear_inherited_samples(parts,analysis)
    originals = {item['id']: item for item in analysis['layouts']}
    styles = {item['id']: item for item in template['layouts']}
    content_types = xml(parts['[Content_Types].xml'])
    for index, scene in enumerate(scenes):
        part = 'ppt/slides/labSlide%d.xml' % (index+1)
        root = xml(parts[part]); original = deepcopy(root)
        style=styles[scene['sourceLayoutId']]
        used_card_ids={item.get('shapeId') for item in scene.get('metricCards',[])}
        discarded=[] if scene.get('authored') else [item['shapeId'] for item in style.get('metricCards',[]) if item.get('shapeId') and item['shapeId'] not in used_card_ids]
        from runtime.html_shape_edits import editable_shape_ids
        permitted=editable_shape_ids(originals[scene['sourceLayoutId']],analysis['width'],analysis['height'])
        discarded += [e['shapeId'] for e in scene.get('sourceShapeEdits',[]) if e.get('shapeId') in permitted]
        clear_content(root, originals[scene['sourceLayoutId']], analysis['width'], analysis['height'], style.get('emptyPictureIds',[]),discarded)
        if styles[scene['sourceLayoutId']].get('neutralContent'):
            neutral_content_art(root,originals[scene['sourceLayoutId']],styles[scene['sourceLayoutId']],analysis['width'])
        source_layout = originals[scene['sourceLayoutId']]
        renumber_pages(root, analysis['width'], analysis['height'], source_layout['index']+1, index+1, len(scenes),len(source_layouts),page_padding)
        # Source page labels were cleared above. The measured h_page binding
        # supplies the new ordinal once, with the same HTML geometry/style.
        tree = root.find('p:cSld/p:spTree', NS)
        relpart = relationship_part(part)
        rels = xml(parts[relpart])
        identity = max([int(item.get('id')) for item in root.findall('.//p:cNvPr', NS)]+[1])+1
        # The accepted browser background is a preview, never a replacement
        # for editable source DrawingML. Keep native panels/connectors/groups.
        for decoration in scene.get('cssShapes',[]):
            shape=add_shape(tree,identity,'Nerpa HTML surface',decoration,decoration['color']);identity+=1
            if decoration.get('radius',0)>0:shape.find('p:spPr/a:prstGeom',NS).set('prst','roundRect')
        for shape in scene.get('shapes',[]):
            add_shape(tree,identity,'Nerpa content card',shape,shape['color']);identity+=1
        for item in scene['texts']:
            add_measured_text(tree,identity,item); identity += 1
        if scene.get('table'):
            add_table(tree, identity, scene['table'], scene['cells'], styles[scene['sourceLayoutId']]); identity += 1
        if scene.get('chart'):
            from runtime.html_chart_export import chart_picture_bytes
            item=scene['chart'];item.pop('exportedAs',None)
            picture=chart_picture_bytes(item)
            if item.get('presentation',{}).get('mode')=='image' and picture:
                add_html_picture(tree,identity,item['box'],picture,parts,rels,content_types,index*100+identity)
                identity+=1;item['exportedAs']='image'
        if scene.get('chart') and scene['chart'].get('exportedAs')!='image':
            from runtime.chart_builder import add_data_chart,chart_presentation_style
            from runtime.charts import fill_chart
            item = scene['chart']; data = item['data']; style = styles[scene['sourceLayoutId']]
            chart_style = chart_presentation_style(style,data['type'],len(data['series']))
            source_spec = next((spec for spec in originals[scene['sourceLayoutId']].get('charts', []) if spec['seriesCount']==len(data['series']) and {'bar':'barChart','bar-horizontal':'barChart','line':'lineChart','xy':'scatterChart','pie':'pieChart','donut':'doughnutChart'}[data['type']] in spec['type']), None)
            if data['type']=='bar-horizontal':source_spec=None
            if source_spec:
                shapes = original.xpath('.//p:graphicFrame[p:nvGraphicFramePr/p:cNvPr/@id=$id]', namespaces=NS,id=str(source_spec['shapeId']))
                if shapes:
                    shape = deepcopy(shapes[0]); tree.append(shape)
                    shape.find('p:nvGraphicFramePr/p:cNvPr', NS).set('id', str(identity))
                    source_spec = dict(source_spec,shapeId=identity)
                    transform = shape.find('p:xfrm', NS)
                    transform.find('a:off', NS).set('x', str(round(item['box']['x']*12700)))
                    transform.find('a:off', NS).set('y', str(round(item['box']['y']*12700)))
                    transform.find('a:ext', NS).set('cx', str(round(item['box']['w']*12700)))
                    transform.find('a:ext', NS).set('cy', str(round(item['box']['h']*12700)))
                else:
                    source_spec = None
            if not source_spec:
                chart_part = add_data_chart(tree, identity, item['box'], chart_style, parts, rels, content_types, 'html-%d' % index, data['type'], len(data['series']))
            # Existing chart writer updates both chart caches and the embedded
            # workbook. Sample values are never left in the delivered chart.
            value = dict(title=data['title'], categories=data['categories'], series=data['series'])
            if data['type']=='xy':
                value = dict(kind='xy', title=data['title'], series=[dict(name=s['name'], points=[dict(x=float(x), y=y) for x, y in zip(data['categories'], s['values'])]) for s in data['series']])
            spec = source_spec or dict(part=chart_part, shapeId=identity, key='chart', type=data['type'],seriesCount=len(data['series']),dataKind='xy' if data['type']=='xy' else 'category')
            parts[part] = serialize(root); parts[relpart] = serialize(rels)
            try:
                fill_chart(spec, value, dict(parts), parts, root, rels, index+1, content_types)
                # fill_chart clones shared source charts. Follow the actual
                # slide relationship, not the original (now unused) part.
                reference=tree.xpath('./p:graphicFrame[p:nvGraphicFramePr/p:cNvPr/@id=$id]//c:chart',namespaces=NS,id=str(identity))[0]
                relation=next(r for r in rels if r.get('Id')==reference.get('{%s}id'%NS['r']))
                apply_native_chart_density(parts,relationship_target(relpart,relation.get('Target')),data,item['box'],chart_style,authored=not source_spec)
                item['exportedAs']='native'
            except Exception:
                for graph in tree.xpath('./p:graphicFrame[p:nvGraphicFramePr/p:cNvPr/@id=$id]',namespaces=NS,id=str(identity)):
                    tree.remove(graph)
                from runtime.html_chart_export import capture_chart_pictures,chart_picture_bytes
                capture_chart_pictures(scenes,output,force=True)
                picture=chart_picture_bytes(item)
                if picture:
                    add_html_picture(tree,identity,item['box'],picture,parts,rels,content_types,index*100+identity);item['exportedAs']='image'
                    item['presentation']=dict(item.get('presentation',{}),reason='Native chart adapter failed; retained verified HTML visual')
                    scene.setdefault('warnings',[]).append(dict(slide=index+1,reason='html_chart_visual_retained',message='Оформление графика сохранено изображением; точные данные доступны в заметках.'))
                else:
                    value_text = '\n'.join([data['title'], ', '.join(data['categories']), *[series['name']+': '+', '.join(map(str,series['values'])) for series in data['series']]])
                    add_text(tree,identity,text_node('h_chart_data',value_text,item['box'],style),value_text)
                    scene.setdefault('warnings',[]).append(dict(slide=index+1,reason='html_chart_data_recovered',message='Данные графика сохранены редактируемым текстом.'))
            identity += 1
        for item in scene.get('images', []):
            if item['image'] in images:
                if item.get('source',{}).get('required'):
                    add_shape(tree, identity, 'Original figure backdrop', item, '#FFFFFF');identity += 1
                bounds = box(item)
                if item.get('fit')!='cover':
                    with Image.open(io.BytesIO(images[item['image']])) as bitmap:
                        ratio = bitmap.width/bitmap.height
                    if bounds['w']/bounds['h']>ratio:
                        width = bounds['h']*ratio;bounds['x']+=(bounds['w']-width)/2;bounds['w']=width
                    else:
                        height = bounds['w']/ratio;bounds['y']+=(bounds['h']-height)/2;bounds['h']=height
                add_html_picture(tree, identity, bounds, images[item['image']], parts, rels, content_types, index*100+identity)
                identity += 1
        add_notes(parts, part, rels, content_types, scene, index)
        parts[part] = serialize(root); parts[relpart] = serialize(rels)
    parts['[Content_Types].xml'] = serialize(content_types)
    parts, cleanup = compact_package(parts)
    write_package(parts, output/'presentation.pptx')
    return cleanup

def deck_result(scenes,output,warnings,cleanup,started,html_only=False):
    from runtime.html_revision import seal_html_revision
    slides=[]
    for index,scene in enumerate(scenes):
        seal_html_revision(scene)
        all_texts=[*scene['texts'],*scene.get('cells',[])]
        slide=dict(title=scene['title'],notes=scene['notes'],speech=scene['speech'],native=dict(
            sourceSlideId=scene['sourceLayoutId'],mode='html',ordinal=index+1,fields={item['key']:item['text'] for item in all_texts},html=scene,
            htmlSlots=[{k:v for k,v in item.items() if k!='text'} for item in all_texts]))
        slides.append(slide)
    duration=round((time.monotonic()-started)*1000)
    (output/'html-scenes.json').write_text(json.dumps(dict(version=VERSION,slides=slides,warnings=warnings),ensure_ascii=False))
    (output/'render-quality.json').write_text(json.dumps(dict(version=VERSION,warnings=warnings,durationMs=duration),ensure_ascii=False))
    (output/'package-cleanup.json').write_text(json.dumps(cleanup))
    return dict(pptxWritten=not html_only,htmlOnly=html_only,pdfAvailable=(output/'presentation.pdf').is_file(),slides=slides,warnings=warnings,durationMs=duration)

def rasterize_html_pdf(pdf,output,count,prefix='slide'):
    # The long-lived importer has already opened source/edited PDFs with
    # different font and image subsets. Isolate final rasterization from that
    # state just as the independent native-preview rasterizer does. Otherwise
    # a PNG can omit a logo that is visibly present in its canonical PDF.
    subprocess.run([sys.executable,'-I','-c',
        "import sys,pymupdf;from pathlib import Path;d=pymupdf.open(sys.argv[1]);o=Path(sys.argv[2]);n=int(sys.argv[3]);p=sys.argv[4];assert len(d)==n,'pptx_preview_count_mismatch';[(page.get_pixmap(matrix=pymupdf.Matrix(1280/page.rect.width,1280/page.rect.width),alpha=False).save(o/(p+'-%d.png'%i))) for i,page in enumerate(d)]",
        str(pdf),str(output),str(count),prefix],check=True,timeout=20,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

def complete_html_previews(output,count):
    with pymupdf.open(output/'presentation.pdf') as pdf:
        if len(pdf)!=count:raise ValueError('pptx_preview_count_mismatch')
    if any(not (output/f'slide-{index}.png').is_file() for index in range(count)):
        rasterize_html_pdf(output/'presentation.pdf',output,count)

def removable_source_icons(layout,width,height):
    if layout.get('htmlRole')!='content':return set()
    protected={item.get('shapeId') for item in layout.get('reservedRegions',[]) if item.get('role') in ('brand','logo','chart','table')}
    protected|={item.get('shapeId') for item in layout.get('sourceObjects',[]) if item.get('hasText') or item.get('kind') in ('chart','table')}
    return {item['shapeId'] for item in layout.get('reservedRegions',[]) if item.get('role')=='icon' and
            type(item.get('shapeId')) is int and item['shapeId']>0 and item['shapeId'] not in protected and
            0<item.get('box',{}).get('w',0)<=width*.2 and 0<item.get('box',{}).get('h',0)<=height*.2}

def export_deck(folder, request):
    started = time.monotonic()
    deadline = started+max(20, min(100, request.get('remainingMs', 100000)/1000))
    output = Path(request['output']); output.mkdir(parents=True, exist_ok=True)
    template = json.loads((folder/'html-template.json').read_text())
    if template.get('version') != VERSION:
        raise ValueError('pptx_html_template_version')
    layouts = {item['id']: item for item in template['layouts']}
    # The compositor can evolve while the imported source artwork stays cached.
    # Re-measure style/roles for selected layouts using the authoritative source
    # geometry and existing clean background, without re-rendering the template.
    analysis=json.loads((folder/'analysis.json').read_text())
    originals={item['id']:item for item in analysis['layouts']}
    def refresh_style(identity):
        if identity not in layouts or identity not in originals:return
        original=dict(originals[identity],emptyPictureIds=layouts[identity].get('emptyPictureIds',[]))
        refreshed=describe_layout(original,analysis)
        for key in ('sourceHtml','nativeBackground'):
            if layouts[identity].get(key) is not None:refreshed[key]=layouts[identity][key]
        readable_ink(refreshed,folder/refreshed['background'],analysis['width'],analysis['height'])
        layouts[identity]=refreshed
    selected={slide.get('sourceLayoutId') or slide.get('native',{}).get('html',{}).get('sourceLayoutId') for slide in request['slides']}
    for identity in selected:refresh_style(identity)
    omitted={}
    for slide in request['slides']:
        saved=slide.get('native',{}).get('html',{})
        identity=slide.get('sourceLayoutId') or saved.get('sourceLayoutId')
        original=originals.get(identity)
        if not original:continue
        allowed=removable_source_icons(original,analysis['width'],analysis['height'])
        safe={value for value in slide.get('omitSourceIconIds',saved.get('omitSourceIconIds',[])) if type(value) is int and value in allowed}
        if safe:omitted.setdefault(identity,set()).update(safe)
    changed=[]
    for identity,ids in omitted.items():
        original=originals[identity];original['htmlRemoveShapeIds']=sorted(set(original.get('htmlRemoveShapeIds',[]))|ids)
        if set(layouts[identity].get('removedShapeIds',[]))!=set(original['htmlRemoveShapeIds']):changed.append(identity)
    if omitted:
        # This copy lives only in the job's sandbox, never in the user's
        # immutable template. The final native adapter sees the same omissions.
        (folder/'analysis.json').write_text(json.dumps(analysis,ensure_ascii=False))
    if changed and request.get('htmlPhase')!='final':
        template=prepare_template(folder,request['soffice'],True,True,changed)
        layouts={item['id']:item for item in template['layouts']}
    for identity in omitted:refresh_style(identity)
    template['layouts']=list(layouts.values())
    if not 1 <= len(request['slides']) <= 40:
        raise ValueError('pptx_html_slide_count')
    images = {name: Path(path).read_bytes() for name, path in request.get('images', {}).items()}
    scenes = []
    for index, slide in enumerate(request['slides']):
        saved = slide.get('native', {}).get('html')
        if saved:
            from runtime.html_revision import edited_html_scene
            scene = edited_html_scene(slide)
        else:
            layout = layouts.get(slide['sourceLayoutId'])
            if not layout:
                raise ValueError('pptx_html_layout_missing')
            placements = []
            for image in slide.get('images', []):
                bounds = image.get('box') or (layout['pictures'][0]['box'] if layout['pictures'] else layout['body'])
                placements.append(dict(image=image['image'],shapeId=image.get('shapeId',100000+len(placements)),slotIndex=image.get('slotIndex',len(placements)),source=image.get('source'),fit=image.get('fit','contain'), **box(bounds)))
            scene = compose_slide(dict(slide,deckSlideCount=len(request['slides']),omitSourceIconIds=sorted(omitted.get(slide['sourceLayoutId'],set()))), layout, index, placements)
        if scene['sourceLayoutId'] in omitted:scene['omitSourceIconIds']=sorted(omitted[scene['sourceLayoutId']])
        if scene.get('chart') and 'presentation' not in scene['chart']:
            from runtime.html_chart_export import chart_presentation
            scene['chart']['presentation']=chart_presentation(slide.get('chartPresentation'),scene.get('authored',{}).get('css',''),scene['chart']['data']['type'])
        scenes.append(scene)
    warnings = []
    if request.get('htmlPhase')=='final' and all(scene.get('htmlMeasured') for scene in scenes) and (folder/'html-proof.pdf').is_file():
        # Freeze the accepted browser layout. PowerPoint receives these exact
        # boxes, line breaks and styles; PDF remains the accepted HTML print.
        shutil.copyfile(folder/'html-proof.pdf',output/'presentation.pdf')
        shutil.copyfile(folder/'html-proof.html',output/'presentation.html')
        for index in range(len(scenes)):
            source=folder/f'html-proof-slide-{index}.png'
            if source.is_file():shutil.copyfile(source,output/f'slide-{index}.png')
        complete_html_previews(output,len(scenes))
        for index,scene in enumerate(scenes):
            artwork=folder/f'html-proof-background-{index}.png'
            if scene.get('authoredBackground') and artwork.is_file():shutil.copyfile(artwork,output/f'authored-background-{index}.png')
        cleanup=native_export(scenes,template,folder,output,images)
        return deck_result(scenes,output,warnings,cleanup,started)
    from runtime.html_shape_edits import render_edited_backgrounds
    render_edited_backgrounds(scenes,template,analysis,folder,request.get('soffice','/usr/bin/soffice'))
    try:
        # Preview only renders HTML. Reserving 35 seconds for a native export
        # that does not run in this phase made every <=35s preview start with
        # an already expired Chromium deadline after an author timeout.
        browser_deadline=min(deadline-(3 if request.get('htmlPhase')=='preview' else 35), started+40)
        if request.get('htmlPhase')=='preview' and request.get('repairBaseline') and request.get('repairSlides'):
            from runtime.html_partial_render import render_changed_pages
            scenes,partial_warnings=render_changed_pages(scenes,template,folder,output,images,browser_deadline,request['repairBaseline'],request['repairSlides'])
            warnings+=partial_warnings
        else:
            warnings += browser_render(scenes,template,folder,output,images,browser_deadline)
    except Exception as error:
        # A browser failure still gets a real editable PPTX from the same data.
        import traceback
        warnings.append(dict(reason='html_browser_unavailable', message='HTML-проверка не завершилась; сохранена редактируемая презентация.',
                             errorType=type(error).__name__, trace=[f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}' for frame in traceback.extract_tb(error.__traceback__)[-5:]]))
    if request.get('htmlPhase')=='preview' and (output/'html-preview.pdf').is_file():
        reverted=[]
        if request.get('repairBaseline'):
            from runtime.html_repair_acceptance import accept_repair
            scenes,warnings,reverted=accept_repair(scenes,warnings,request['repairBaseline'],request.get('repairSlides',[]),folder,output)
        shutil.copyfile(output/'html-preview.pdf',output/'presentation.pdf')
        complete_html_previews(output,len(scenes))
        return dict(deck_result(scenes,output,warnings,{},started,html_only=True),revertedSlides=reverted)
    cleanup = native_export(scenes, template, folder, output, images)
    warnings += [warning for scene in scenes for warning in scene.get('warnings',[])]
    # Final PowerPoint rendering is checked independently of the HTML preview.
    try:
        rendered = output/'native-preview'
        render(output/'presentation.pptx', rendered, request['soffice'], timeout=max(5,min(55,deadline-time.monotonic()-5)))
        # QA must see the actual final PDF. Source/converter operations can load
        # differently subsetted faces earlier in this worker; use a fresh font
        # rasterization context for the downloadable deck's previews.
        try:
            subprocess.run([sys.executable,'-I','-c',
                "import sys,pymupdf;from pathlib import Path;p=Path(sys.argv[1]);d=pymupdf.open(p/'presentation.pdf');[(page.get_pixmap(matrix=pymupdf.Matrix(1280/page.rect.width,1280/page.rect.width),alpha=False).save(p/('slide-%d.png'%i))) for i,page in enumerate(d)]",
                str(rendered)],check=True,timeout=max(3,min(15,deadline-time.monotonic()-2)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        except (subprocess.SubprocessError,OSError):
            warnings.append(dict(reason='html_native_preview_refresh_unavailable',message='PDF готов; дополнительное обновление превью не завершилось.'))
        with pymupdf.open(rendered/'presentation.pdf') as pdf:
            if len(pdf) != len(scenes):
                raise ValueError('pptx_preview_count_mismatch')
            for index, page in enumerate(pdf):
                for item in page.get_text('blocks'):
                    if item[0]<-1 or item[1]<-1 or item[2]>page.rect.width+1 or item[3]>page.rect.height+1:
                        warnings.append(dict(slide=index+1, reason='html_native_bounds', message='Проверьте текст у края слайда в PowerPoint.'))
        publish_format_previews(output,rendered,len(scenes))
    except Exception:
        warnings.append(dict(reason='html_native_preview_unavailable', message='PPTX сохранён; дополнительная проверка в PowerPoint не завершилась.'))
        previews = [output/('slide-%d.png' % index) for index in range(len(scenes))]
        html_pdf=output/'html-preview.pdf'
        if html_pdf.is_file():
            with pymupdf.open(html_pdf) as pdf:
                if len(pdf)!=len(scenes):raise ValueError('pptx_preview_count_mismatch')
                shutil.copyfile(html_pdf,output/'presentation.pdf')
            rasterize_html_pdf(html_pdf,output,len(scenes))
            warnings.append(dict(reason='html_pdf_preview_recovered',message='PDF собран из проверенного HTML; PPTX остаётся редактируемым.'))
        elif all(path.is_file() for path in previews):
            with pymupdf.open() as pdf:
                for path in previews:
                    page = pdf.new_page(width=template['width'], height=template['height'])
                    page.insert_image(page.rect, filename=str(path))
                pdf.save(output/'presentation.pdf')
            warnings.append(dict(reason='html_pdf_preview_recovered', message='PDF собран из HTML-превью; PPTX остаётся редактируемым.'))
    return deck_result(scenes,output,warnings,cleanup,started)


def publish_format_previews(output,rendered,count):
    """An independent native check must never replace the accepted HTML PDF.
    Editor/full exports obey the same contract as preview -> final jobs."""
    if (output/'html-preview.pdf').is_file():
        shutil.copyfile(output/'html-preview.pdf',output/'presentation.pdf')
        complete_html_previews(output,count)
    else:
        for path in rendered.glob('*'):
            if path.is_file():shutil.copyfile(path,output/path.name)
