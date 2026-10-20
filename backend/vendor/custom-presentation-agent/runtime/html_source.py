"""Compile editable source frames, not a replacement layout or sample copy.

Static artwork stays in the cleaned background. This DOM supplies the actual
text/photo/data frames to the HTML author. Native units cross this boundary
once (72pt -> 96dpi CSS). The receipt states unsupported source features.
"""
import hashlib
import html
import json
import re
from lxml import etree
from runtime.security import NS

SOURCE_HTML_VERSION = 16


def px(value):
    return round(float(value)*4/3, 2)


def compile_source_html(layout, analysis, parts):
    root = etree.fromstring(parts[layout['part']])
    shapes = {}
    for shape in root.xpath('.//p:sp | .//p:graphicFrame | .//p:pic', namespaces=NS):
        identity = shape.find('.//p:cNvPr', NS)
        if identity is not None:
            shapes[int(identity.get('id'))] = shape
    from runtime.source_art import palette,ink
    colors=palette(parts)
    object_paints=[]
    for identity,shape in shapes.items():
        fill=ink(shape.find('p:spPr/a:solidFill',NS),colors)
        object_paints.append(dict(shapeId=identity,fill=fill[0] if fill and fill[1]>.01 else None))
    removed = set(layout.get('htmlRemoveShapeIds', []))
    protected = set(layout.get('htmlPreserveShapeIds', []))
    regions, chunks, unsupported, photo_frames = [], [], [], []
    def frame(identity, role, bounds, extra=''):
        return '<div data-source-shape="%s" data-source-role="%s" style="position:absolute;left:%spx;top:%spx;width:%spx;height:%spx;%s">' % (
            identity, html.escape(role, quote=True), *(px(bounds[k]) for k in ('x','y','w','h')), extra)
    for slot in layout.get('slots', []):
        identity = slot['shapeId']
        if identity in removed|protected or slot.get('cell') is not None or slot.get('role') in ('brand','logo','page_number','decoration','footer'):
            continue
        shape = shapes.get(identity)
        body = shape.find('p:txBody/a:bodyPr', NS) if shape is not None else None
        inset = [px(float(body.get(key, default))/12700) if body is not None else px(float(default)/12700)
                 for key, default in [('tIns','45720'),('rIns','91440'),('bIns','45720'),('lIns','91440')]]
        paragraphs = []
        for paragraph in shape.findall('p:txBody/a:p', NS) if shape is not None else []:
            props = paragraph.find('a:pPr', NS)
            spec = {}
            if props is not None:
                spec = {key:props.get(key) for key in ('algn','lvl','marL','indent') if props.get(key) is not None}
                bullet = props.find('a:buChar', NS)
                if bullet is not None:spec['bullet'] = bullet.get('char')
                if props.find('a:buAutoNum', NS) is not None:spec['numbered'] = True
                for tag in ('lnSpc','spcBef','spcAft'):
                    spacing = props.find('a:'+tag, NS)
                    if spacing is not None and len(spacing):spec[tag] = {etree.QName(spacing[0]).localname:spacing[0].get('val')}
            paragraphs.append(spec)
        bounds = {key:px(slot[key]) for key in ('x','y','w','h')}
        source_role='title' if identity==layout.get('htmlTitleShapeId') else 'label' if isinstance(layout.get('htmlTitleShapeId'),int) and slot.get('role') in ('title','header') else slot.get('role','body')
        if layout.get('htmlTitleShapeId') is None and 'htmlTitleShapeId' in layout and source_role in ('title','header'):
            source_role='metric' if slot.get('size',0)>=32 and len(slot.get('text',''))<60 and any(c.isdigit() for c in slot.get('text','')) else 'label'
        region = dict(shapeId=identity, role=source_role, box=bounds,
                      font=slot.get('font'), size=px(slot.get('size',18)), color=slot.get('color'),
                      align=slot.get('align','left'), bold=bool(slot.get('bold')), insets=inset, paragraphs=paragraphs)
        # One source text shape can mix a large accent metric/heading and
        # ordinary white/dark prose. Keep that typography grammar, without
        # exposing any sample words or asking the author to copy them.
        styles=[]
        for paragraph in shape.findall('p:txBody/a:p',NS) if shape is not None else []:
            for run in paragraph.findall('a:r',NS):
                wording=run.find('a:t',NS);props=run.find('a:rPr',NS)
                if wording is None or not (wording.text or '').strip():continue
                paint=ink(props.find('a:solidFill',NS),colors) if props is not None else None
                styles.append(dict(color=paint[0] if paint else region['color'],size=px(float(props.get('sz'))/100) if props is not None and props.get('sz') else region['size'],bold=props.get('b')=='1' if props is not None and props.get('b') is not None else region['bold'],weight=len(wording.text or '')))
        if styles:
            ordinary=[s for s in styles[1:] if s['size']<=styles[0]['size'] and not s['bold']] or styles[1:] or styles
            prose=[s for s in ordinary if s['size']>=12] or ordinary
            body_size=min(s['size'] for s in prose)
            body_style=max((s for s in prose if s['size']<=body_size+.1),key=lambda s:s['weight'])
            region['textStyles']=dict(heading={k:v for k,v in styles[0].items() if k!='weight'},body={k:v for k,v in body_style.items() if k!='weight'})
        # A text-bearing ellipse/pill is a content host, not an obstacle. Its
        # paint remains in the cleaned artwork; only the old wording is erased.
        # Expose the relationship explicitly so authors do not move its labels
        # to the nearest white surface and abandon the original filled shape.
        obj = next((item for item in layout.get('sourceObjects',[]) if item.get('shapeId')==identity),{})
        geom = shape.find('p:spPr/a:prstGeom',NS) if shape is not None else None
        fill = next((p['fill'] for p in object_paints if p['shapeId']==identity),None)
        if fill and geom is not None:
            kind = geom.get('prst','rect')
            pad = list(inset)
            if source_role not in ('title','header','photo'):
                # Some valid PPTX hosts intentionally have zero text insets.
                # New, longer copy still needs an interior: keep generous
                # source/icon offsets, but never use a rounded border as the
                # text baseline. Small pills receive proportional padding.
                horizontal=min(24,bounds['w']*.06)
                vertical=min(20,bounds['h']*.12)
                pad=[max(pad[0],vertical),max(pad[1],horizontal),
                     max(pad[2],vertical),max(pad[3],horizontal)]
            if kind == 'ellipse':
                pad = [max(pad[0],bounds['h']*.147),max(pad[1],bounds['w']*.147),
                       max(pad[2],bounds['h']*.147),max(pad[3],bounds['w']*.147)]
            inner = dict(x=round(bounds['x']+pad[3],2),y=round(bounds['y']+pad[0],2),
                         w=round(max(1,bounds['w']-pad[1]-pad[3]),2),h=round(max(1,bounds['h']-pad[0]-pad[2]),2))
            ordinal = str(slot.get('text','')).strip().isdigit() and len(str(slot.get('text','')).strip())<=2 and slot['w']*slot['h']<analysis['width']*analysis['height']*.02
            region['container'] = dict(shapeId=identity,geometry=kind,fill=fill,box=bounds,innerBox=inner,
                textPlacement='inside',verticalAlign=slot.get('verticalAlign','center'),role='ordinal' if ordinal else 'content')
            inset = [round(v,2) for v in pad]
            region['insets']=inset
        transform = shape.find('p:spPr/a:xfrm', NS) if shape is not None else None
        if transform is not None and int(transform.get('rot','0')):
            unsupported.append(dict(shapeId=identity,feature='rotated_text',action='verify against original image'))
        if body is not None and body.get('vert','horz') != 'horz':
            unsupported.append(dict(shapeId=identity,feature='vertical_text',action='verify against original image'))
        regions.append(region)
        align = slot.get('align','left')
        align = align if align in ('left','center','right','justify') else 'left'
        vertical = {'center':'center','middle':'center','bottom':'flex-end'}.get(slot.get('verticalAlign'),'flex-start')
        font = html.escape(json.dumps(slot.get('font') or 'Arial'), quote=True)
        color = slot.get('color','#172B34')
        # Font/color came from the parser, but source strings are still data.
        if not isinstance(color,str) or len(color)!=7 or any(c not in '#0123456789abcdefABCDEF' for c in color):color='#172B34'
        style = 'box-sizing:border-box;display:flex;flex-direction:column;justify-content:%s;padding:%s;font-family:%s;font-size:%spx;font-weight:%s;color:%s;text-align:%s;' % (
            vertical,' '.join(str(value)+'px' for value in inset),font,region['size'],700 if region['bold'] else 400,color,align)
        chunks.append(frame(identity,region['role'],slot,style)+'<p style="margin:0;white-space:pre-wrap;line-height:1.1" data-source-shape="%s"></p></div>'%identity)
        if layout.get('htmlRole')=='content' and region['role'] not in ('title','header','brand','logo') and layout.get('htmlConcept',{}).get('kind')=='figure' and re.fullmatch(r'(?:иллюстрация|изображение|фото(?:графия)?|картинка|illustration|image|picture|photo)(?:\s*\d+)?',str(slot.get('text','')).strip(),re.I) and bounds['w']*bounds['h']>=px(analysis['width'])*px(analysis['height'])*.08:
            region['role']='photo'
            photo_frames.append(dict(shapeId=identity,kind='placeholder',box={k:slot[k] for k in ('x','y','w','h')},fit='cover',virtual=True,sourceRole='photo',protected=False,requiresOpaque=False,aspectRatio=slot['w']/max(1,slot['h'])))
    # Flat arrays made authors confuse an aside with a repeated content row.
    groups=[];paired=set()
    # Filled cards often use the whole card as the heading shape and a tiny
    # separate sample caption inside it. These are one semantic pair. Grow the
    # caption only inside its own existing card; keep the heading above icons.
    def contained(a,b):return a['x']>=b['x']-1 and a['y']>=b['y']-1 and a['x']+a['w']<=b['x']+b['w']+1 and a['y']+a['h']<=b['y']+b['h']+1
    for heading in regions:
        container=heading.get('container')
        if not container or container.get('role')=='ordinal' or heading['role'] in ('title','photo'):continue
        h=heading['box'];children=[r for r in regions if r is not heading and r['role'] not in ('title','photo') and contained(r['box'],h) and r['box']['y']>=h['y']+h['h']*.25 and r['box']['w']>=h['w']*.45]
        if len(children)!=1:continue
        body=children[0];b=body['box'];top=b['y']
        for obj in layout.get('sourceObjects',[]):
            if obj.get('shapeId') in (heading['shapeId'],body['shapeId']) or obj.get('kind') not in ('picture','shape'):continue
            bounds={k:px(obj['box'][k]) for k in ('x','y','w','h')} if obj.get('box') else None
            if bounds and contained(bounds,h) and bounds['y']>h['y']+heading['size']*1.2:top=min(top,bounds['y'])
        heading['role']='label';heading['textBox']=dict(h,h=round(max(heading['size']*1.3,top-h['y']-10),2))
        inner=container['innerBox']
        # The caption's own zero-inset shape is not the enclosing card. Grow
        # only into the card's padded interior, not to its right/bottom edge.
        x=max(b['x'],inner['x']);y=max(b['y'],inner['y'])
        body['role']='body';body['textBox']=dict(x=x,y=y,
            w=round(max(1,min(b['x']+b['w'],inner['x']+inner['w'])-x),2),
            h=round(max(1,inner['y']+inner['h']-y),2))
        body['container']=dict(container,innerBox=body['textBox'])
        groups.append(dict(id='host-'+str(heading['shapeId']),headingShapeId=heading['shapeId'],bodyShapeId=body['shapeId'],box=h,origin='native-container'))
        paired.add(body['shapeId'])
    for heading in (r for r in regions if r['role'] in ('label','header') and not any(g['headingShapeId']==r['shapeId'] for g in groups)):
        h=heading['box']
        def prose_candidate(r):
            if r['role'] in ('body','subtitle'):return True
            # Parser labels also include captions. A short filled badge above
            # an unfilled caption, or a centred timeline pill above a wider
            # left-aligned explanation, forms a pair. Equal repeated list rows
            # must never be mistaken for a heading+body relationship.
            return r['role']=='label' and not r.get('container') and (
                heading.get('container') and h['h']<=heading['size']*3.5 or
                heading.get('align')=='center' and r.get('align')!='center')
        candidates=[r for r in regions if r is not heading and prose_candidate(r) and r['shapeId'] not in paired
                    and (abs(r['box']['x']-h['x'])<max(8,h['w']*.08) or abs(r['box']['x']+r['box']['w']/2-h['x']-h['w']/2)<max(8,h['w']*.08))
                    and h['y']+h['h']*.5<=r['box']['y']<=h['y']+h['h']+max(20,heading['size']*2.5)]
        body=min(candidates,key=lambda r:r['box']['y'],default=None)
        if not body:continue
        paired.add(body['shapeId']);b=body['box']
        groups.append(dict(id='group-'+str(heading['shapeId']),headingShapeId=heading['shapeId'],bodyShapeId=body['shapeId'],
            box=dict(x=min(h['x'],b['x']),y=h['y'],w=max(h['w'],b['w']),h=max(h['y']+h['h'],b['y']+b['h'])-h['y'])))
    for group in groups:
        peers=[other for other in groups if abs(other['box']['w']-group['box']['w'])<=group['box']['w']*.12]
        group['role']='repeated-content' if len(peers)>=2 else 'lead-or-aside'
        group['peerGroupIds']=[other['id'] for other in peers if other is not group]
    numbered_rows=[]
    for ordinal in (r for r in regions if str(next((s.get('text','') for s in layout.get('slots',[]) if s['shapeId']==r['shapeId']), '')).strip().isdigit()):
        source=next(s for s in layout['slots'] if s['shapeId']==ordinal['shapeId'])
        if int(source['text'].strip())>20 or ordinal['box']['w']>px(analysis['width'])*.09:continue
        b=ordinal['box'];labels=[r for r in regions if r['shapeId']!=ordinal['shapeId'] and abs(r['box']['y']-b['y'])<4 and r['box']['x']>=b['x']+b['w']-3]
        label=min(labels,key=lambda r:r['box']['x'],default=None)
        if not label:continue
        connectors=[o['shapeId'] for o in layout.get('sourceObjects',[]) if o.get('kind') in ('connector','line') and o.get('box') and abs(px(o['box']['y'])-(b['y']+b['h']/2))<max(6,b['h']*.3)]
        numbered_rows.append(dict(numberShapeId=ordinal['shapeId'],textShapeId=label['shapeId'],connectedShapeIds=connectors,ordinal=int(source['text'].strip()),box=dict(x=b['x'],y=b['y'],w=label['box']['x']+label['box']['w']-b['x'],h=max(b['h'],label['box']['h']))))
    # Complete small 01..N runs are structural ordinals, not sample metrics.
    # Preserve their identity after clearing sample wording; empty badges were
    # previously retained while their numbers silently disappeared.
    ordinal_candidates=[]
    for r in regions:
        slot=next((s for s in layout.get('slots',[]) if s['shapeId']==r['shapeId']),{})
        value=str(slot.get('text','')).strip()
        if re.fullmatch(r'0?[1-9]|1[0-2]',value) and r['box']['w']<=px(analysis['width'])*.12 and r['box']['h']<=px(analysis['height'])*.12:
            ordinal_candidates.append(dict(shapeId=r['shapeId'],ordinal=int(value),digits=len(value)))
    structural_ordinals=ordinal_candidates if 3<=len(ordinal_candidates)<=12 and sorted(o['ordinal'] for o in ordinal_candidates)==list(range(1,len(ordinal_candidates)+1)) else []
    icon_rows=[]
    for icon in layout.get('reservedRegions',[]):
        if icon.get('role')!='icon' or not icon.get('box') or icon.get('shapeId') in removed:continue
        b={k:px(icon['box'][k]) for k in ('x','y','w','h')}
        candidates=[r for r in regions if r['role'] not in ('title','header','photo') and not r.get('container')
            and 4<=r['box']['x']-b['x']-b['w']<=px(analysis['width'])*.12
            and abs(r['box']['y']+r['box']['h']/2-b['y']-b['h']/2)<=max(b['h'],r['box']['h']*.5)]
        caption=min(candidates,key=lambda r:r['box']['x']-b['x']+abs(r['box']['y']+r['box']['h']/2-b['y']-b['h']/2)*2,default=None)
        if caption:icon_rows.append(dict(iconShapeId=icon['shapeId'],textShapeId=caption['shapeId'],box=caption['box']))
    for index,region in enumerate(regions):
        if not region.get('textBox'):continue
        for key,css in [('x','left'),('y','top'),('w','width'),('h','height')]:
            chunks[index]=re.sub(r'\b'+css+r':[-\d.]+px;',css+':'+str(region['textBox'][key])+'px;',chunks[index],count=1)
        chunks[index]=re.sub(r'data-source-role="[^"]+"','data-source-role="'+region['role']+'"',chunks[index],count=1)
    chunk_by_id={region['shapeId']:chunk for region,chunk in zip(regions,chunks)}
    grouped_ids={identity for group in groups for identity in (group['headingShapeId'],group['bodyShapeId'])}
    chunks=[chunk for region,chunk in zip(regions,chunks) if region['shapeId'] not in grouped_ids]+[
        '<div class="source-group" data-source-group="%s" style="display:contents">%s%s</div>'%(
            group['id'],chunk_by_id[group['headingShapeId']],chunk_by_id[group['bodyShapeId']]) for group in groups]
    data_frames = []
    for item in layout.get('sourceObjects', []):
        if item.get('kind') not in ('table','chart') or not item.get('box'):continue
        # Removed sample data retains a replaceable FRAME, never its values.
        identity,kind = item['shapeId'],item['kind']
        spec = dict(shapeId=identity,kind=kind,box={key:px(item['box'][key]) for key in ('x','y','w','h')})
        shape = shapes.get(identity)
        if kind == 'table' and shape is not None:
            table = shape.find('.//a:tbl',NS)
            if table is not None:
                spec['columnWidths'] = [px(float(col.get('w'))/12700) for col in table.findall('a:tblGrid/a:gridCol',NS)]
                spec['rowHeights'] = [px(float(row.get('h'))/12700) for row in table.findall('a:tr',NS)]
                spec['cellStyles'] = []
                for row in table.findall('a:tr',NS):
                    styles=[]
                    for cell in row.findall('a:tc',NS):
                        fill=cell.find('a:tcPr/a:solidFill/a:srgbClr',NS)
                        styles.append(dict(fill='#'+fill.get('val')) if fill is not None else {})
                    spec['cellStyles'].append(styles)
                table_style = table.find('a:tblPr/a:tableStyleId',NS)
                if table_style is not None:spec['tableStyleId']=table_style.text
        if kind == 'chart':
            # Parser metadata is style/type only: never send sample series.
            chart = next((c for c in layout.get('charts',[]) if c.get('shapeId')==identity),{})
            spec['type']=chart.get('type',chart.get('kind','unknown'))
            unsupported.append(dict(shapeId=identity,feature='chart_theme_details',action='use original image to verify axes and legend'))
        data_frames.append(spec)
        chunks.append(frame(identity,kind,item['box'])+'<div data-visual="%s" style="width:100%%;height:100%%"></div></div>'%kind)
    for item in layout.get('imageSlots', []):
        if item.get('protected') or item.get('requiresOpaque') or not item.get('box'):continue
        identity=item['shapeId']
        chunks.append(frame(identity,'photo',item['box'])+'</div>')
    from copy import deepcopy
    from runtime.html_deck import clear_content,empty_picture_ids
    from runtime.source_art import compile_source_art
    clean=deepcopy(root)
    clear_content(clean,layout,analysis['width'],analysis['height'],empty_picture_ids(parts,layout))
    native_art=compile_source_art(clean,layout,analysis,parts)
    unsupported.extend(native_art['unsupported'])
    markup='<section class="source-slide" style="position:relative;width:100%;height:100%"><div data-source-native-layer="true"></div>'+''.join(chunks)+'</section>'
    result=dict(version=SOURCE_HTML_VERSION,nativeArt=native_art,objectPaints=object_paints,numberedRows=numbered_rows,structuralOrdinals=structural_ordinals,iconRows=icon_rows,coordinateSpace='CSS pixels at 96dpi',sourceLayoutId=layout['id'],
                headingSelection=dict(reviewed='htmlTitleShapeId' in layout,id=layout.get('htmlTitleShapeId')),
                canvas=dict(width=px(analysis['width']),height=px(analysis['height'])),html=markup,
                textRegions=regions,textGroups=groups,photoFrames=photo_frames,dataFrames=data_frames,unsupported=unsupported,
                contract='Static decoration is supplied by cleaned background. Empty source regions contain no sample wording or values. Bind new semantic fields inside these frames. A textRegions.container is an existing filled text host: keep its new labels inside innerBox, never above/below the emptied shape. Preserve good frames and locally adapt defective ones.')
    result['digest']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result
