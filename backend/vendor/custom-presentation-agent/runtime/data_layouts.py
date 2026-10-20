"""Append source-derived native data layouts without editing the upload.

Only measured source content may be replaced. Unknown artwork, cached embedded
previews, branding, footer furniture and inherited source objects reserve space.
New native data objects then use the ordinary parse/plan/evidence/fill pipeline.
"""
import hashlib
import posixpath
import math
import re
import io
from PIL import Image
from lxml import etree
from runtime.security import NS, xml, slide_order
from runtime.geometry import box, inside, intersection
from runtime.background import source_background
from runtime.embedded_objects import protected_preview_shape_ids
from runtime.layout_metadata import objects
from runtime.chart_builder import add_data_chart, node, solid
from app.presentation.parser.archive import relationship_part
from app.presentation.parser.ids import slide_id_from_part

DATA_EXTENSION = '{768E6A07-4A3C-48F3-846A-C75D9367E016}'
DATA_NAMESPACE = 'https://nerpa.ai/presentation/data-layout/1'
DATA_LAYOUT_VERSION = 1
PROTECTED_ROLES = {'logo', 'header', 'footer', 'page_number', 'background', 'background_image', 'icon', 'decoration', 'decorative', 'decorative_image'}

def image_frame_ids(root):
    """Recognize only the server-owned picture of an image derivative."""
    result = set()
    for extension in root.findall('p:extLst/p:ext[@uri="%s"]' % DATA_EXTENSION, NS):
        item = extension.find('{%s}dataLayout' % DATA_NAMESPACE)
        if item is None or item.get('version') != str(DATA_LAYOUT_VERSION) or item.get('kind') != 'image':
            continue
        identity = item.get('frameShapeId', '')
        if not identity.isdigit():
            continue
        pictures = root.xpath('./p:cSld/p:spTree/p:pic[p:nvPicPr/p:cNvPr/@id=$id]', namespaces=NS, id=identity)
        if len(pictures) == 1 and len(pictures[0].findall('p:blipFill/a:blip', NS)) == 1:
            result.add(int(identity))
    return result

def text_frame_ids(root):
    """Return validated native title/body identities of an owned text canvas."""
    for extension in root.findall('p:extLst/p:ext[@uri="%s"]' % DATA_EXTENSION, NS):
        item = extension.find('{%s}dataLayout' % DATA_NAMESPACE)
        if item is None or item.get('version') != str(DATA_LAYOUT_VERSION) or item.get('kind') != 'text':
            continue
        identities = {role: item.get(role+'ShapeId', '') for role in ('title', 'body')}
        if any(not identity.isdigit() for identity in identities.values()) or len(set(identities.values())) != 2:
            continue
        if all(len(root.xpath('./p:cSld/p:spTree/p:sp[p:nvSpPr/p:cNvPr/@id=$id]/p:txBody', namespaces=NS, id=identity)) == 1 for identity in identities.values()):
            return {role: int(identity) for role, identity in identities.items()}
    return {}

def add_body_text(tree, shape_id, region, style):
    """Create a normal visible text box, without an unresolved placeholder."""
    shape = node(tree, 'p:sp')
    nv = node(shape, 'p:nvSpPr')
    node(nv, 'p:cNvPr', id=shape_id, name='Основное содержание')
    node(nv, 'p:cNvSpPr')
    node(nv, 'p:nvPr')
    properties = node(shape, 'p:spPr')
    transform = node(properties, 'a:xfrm')
    node(transform, 'a:off', x=round(region['x']*12700), y=round(region['y']*12700))
    node(transform, 'a:ext', cx=round(region['w']*12700), cy=round(region['h']*12700))
    node(node(properties, 'a:prstGeom', prst='rect'), 'a:avLst')
    node(properties, 'a:noFill')
    node(node(properties, 'a:ln'), 'a:noFill')
    body = node(shape, 'p:txBody')
    node(node(body, 'a:bodyPr', wrap='square', lIns=0, rIns=0, tIns=0, bIns=0, anchor='t'), 'a:noAutofit')
    node(body, 'a:lstStyle')
    paragraph = node(body, 'a:p')
    paragraph_style = node(paragraph, 'a:pPr', algn='l', marL=0, indent=0)
    node(node(paragraph_style, 'a:lnSpc'), 'a:spcPct', val=120000)
    node(paragraph_style, 'a:buNone')
    run = node(paragraph, 'a:r')
    # Large enough for a talk, with all capacity determined again by the native
    # text fitter. The model cannot shrink type or grow this measured region.
    size = style.get('textBodySize', max(18, style['bodySize']))
    properties = node(run, 'a:rPr', lang='ru-RU', sz=round(size*100), b=0)
    solid(properties, style['ink'])
    for tag in ('a:latin', 'a:ea', 'a:cs'):
        node(properties, tag, typeface=style['font'])
    node(run, 'a:t').text = 'Основные положения материала'
    node(paragraph, 'a:endParaRPr', lang='ru-RU', sz=round(size*100))
    return shape

def records(parts):
    result = []
    ordered = slide_order(parts)
    known_ids = {slide_id_from_part(part) for part in ordered}
    for part in ordered:
        root = xml(parts[part])
        extension = root.find('p:extLst/p:ext[@uri="%s"]' % DATA_EXTENSION, NS)
        item = extension.find('{%s}dataLayout' % DATA_NAMESPACE) if extension is not None else None
        if item is not None:
            kind, chart_type = item.get('kind'), item.get('chartType')
            count = item.get('seriesCount', '0')
            if item.get('version') != str(DATA_LAYOUT_VERSION) or kind not in ('table', 'chart', 'image', 'text') or item.get('sourceLayoutId') not in known_ids or not re.fullmatch(r'[0-6]', count):
                continue
            if kind == 'chart':
                if chart_type not in ('bar', 'line', 'xy') or int(count) < 1 or not root.findall('.//c:chart', NS):
                    continue
            elif chart_type is not None or count != '0':
                continue
            elif kind == 'table' and not root.findall('.//a:tbl', NS):
                continue
            elif kind == 'image' and not image_frame_ids(root) and not root.findall('.//p:ph[@type="pic"]', NS):
                continue
            elif kind == 'text' and not text_frame_ids(root):
                continue
            result.append(dict(part=part, kind=kind, sourceLayoutId=item.get('sourceLayoutId'), chartType=chart_type, seriesCount=int(count),
                               **({role+'ShapeId': identity for role, identity in text_frame_ids(root).items()} if kind == 'text' else {})))
    return result

def free_rect(bounds, obstacles, padding=8):
    """Find an exact axis-aligned region split at measured object edges."""
    candidates = [bounds]
    for raw in obstacles:
        obstacle = dict(x=raw['x']-padding, y=raw['y']-padding, w=raw['w']+2*padding, h=raw['h']+2*padding)
        remaining = []
        for candidate in candidates:
            if intersection(candidate, obstacle) < .01:
                remaining.append(candidate)
                continue
            left, top = candidate['x'], candidate['y']
            right, bottom = left+candidate['w'], top+candidate['h']
            for x, y, w, h in [(left, top, obstacle['x']-left, candidate['h']),
                                (obstacle['x']+obstacle['w'], top, right-obstacle['x']-obstacle['w'], candidate['h']),
                                (left, top, candidate['w'], obstacle['y']-top),
                                (left, obstacle['y']+obstacle['h'], candidate['w'], bottom-obstacle['y']-obstacle['h'])]:
                region = dict(x=x, y=y, w=w, h=h)
                if w > 0 and h > 0 and inside(region, candidate):
                    remaining.append(region)
        candidates = sorted(remaining, key=lambda region: region['w']*region['h'], reverse=True)[:80]
    return max(candidates, key=lambda region: region['w']*region['h'], default=None)

def contrast(a, b):
    def luminance(color):
        channels = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
        linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
        return sum(value*weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    x, y = sorted([luminance(a), luminance(b)])
    return (y+.05)/(x+.05)

def candidate(parts, data, layout, slide, assignments):
    if not layout.get('usable') or layout.get('derivedMediaKind') or not layout.get('slots'):
        return None
    width, height = data['width'], data['height']
    root = xml(parts[layout['part']])
    tree = root.find('p:cSld/p:spTree', NS)
    items = list(objects(slide['objects']))
    by_id = {item.get('shape_id'): item for item in items}
    local_roles = {item['source_open_xml_shape_id']: item['role'] for item in assignments if item['source_level'] == 'slide'}
    static_previews = protected_preview_shape_ids(root)
    protected_ids = set(static_previews)
    for item in items:
        if local_roles.get(item.get('shape_id')) in PROTECTED_ROLES:
            protected_ids.add(item.get('shape_id'))
            protected_ids.update(child.get('shape_id') for child in objects(item.get('children', [])))
    text = [slot for slot in layout['slots'] if not slot.get('cell') and slot['shapeId'] not in protected_ids and slot['y']+slot['h'] <= height*.32]
    heading = max(text, key=lambda slot: (local_roles.get(slot['shapeId'], slot.get('role')) in ('title', 'section_title'), slot['size'], -slot['y']), default=None)
    if not heading:
        return None
    title_shapes = tree.xpath('./p:sp[p:nvSpPr/p:cNvPr/@id=$id]', namespaces=NS, id=str(heading['shapeId']))
    # A grouped heading needs inverse transforms. Preserve that source layout
    # rather than silently moving or flattening its group.
    if len(title_shapes) != 1:
        return None
    removable = set()
    protected = []
    for item in items:
        identity = item.get('shape_id')
        if item.get('hidden') or identity is None:
            continue
        region = box(item)
        if region['w'] <= 0 or region['h'] <= 0:
            continue
        full_background = region['w']*region['h'] >= width*height*.85 and item.get('object_kind') == 'picture'
        role = local_roles.get(identity)
        if identity == heading['shapeId'] or full_background:
            continue
        if identity in protected_ids:
            protected.append(region)
            continue
        # Only source text/native data or explicitly identified content photos
        # are replaceable. Decorative and unknown vectors reserve their space.
        source_slot = any(slot['shapeId'] == identity for slot in layout['slots'])
        content_photo = item.get('object_kind') == 'picture' and role == 'photo'
        native_data = item.get('object_kind') in ('table', 'chart')
        below_heading = region['y'] >= heading['y']+heading['h']-2
        if below_heading and (source_slot or content_photo or native_data):
            removable.add(identity)
        elif item.get('object_kind') != 'group':
            protected.append(region)
    # Inherited objects are never removed. Full-page background pictures remain
    # behind data; all smaller inherited objects remain collision obstacles.
    for assignment in assignments:
        if assignment['source_level'] == 'slide':
            continue
        region = box({'geometry': assignment.get('source_geometry') or {}})
        if region['w'] > 0 and region['h'] > 0 and region['w']*region['h'] < width*height*.85:
            protected.append(region)
    margin = max(width*.04, min(heading['x'], width*.09))
    top = max(height*.20, heading['y']+heading['h']+height*.045)
    bounds = dict(x=margin, y=top, w=width-margin*2, h=height*.92-top)
    area = free_rect(bounds, protected, max(8, width*.01))
    if not area or area['w'] < width*.50 or area['h'] < height*.30 or area['w']*area['h'] < width*height*.20:
        return None
    background = source_background(parts, layout['part'])
    # A photograph/gradient cannot establish contrast for an added chart/table.
    if not background or any(item.get('object_kind') == 'picture' and box(item)['w']*box(item)['h'] >= width*height*.85 for item in items):
        return None
    palette = [value for value in data.get('styleProfile', {}).get('colors', []) if isinstance(value, str) and len(value) == 7 and value.startswith('#')]
    ink = heading.get('color', '#202020')
    if contrast(ink, background) < 4.5:
        ink = max(['#000000', '#FFFFFF', *palette], key=lambda value: contrast(value, background))
    accent = next((value for value in palette if contrast(value, background) >= 3 and max(int(value[i:i+2], 16) for i in (1, 3, 5))-min(int(value[i:i+2], 16) for i in (1, 3, 5)) > 35), ink)
    surface = '#' + ''.join('%02X' % round(int(accent[i:i+2], 16)*.09+int(background[i:i+2], 16)*.91) for i in (1, 3, 5))
    style = dict(font=heading['font'], ink=ink, accent=accent, onAccent=max(['#000000', '#FFFFFF'], key=lambda color: contrast(color, accent)), surface=surface, bodySize=min(20, max(14, heading['size']*.85)), seriesColors=[color for color in palette if contrast(color, background) >= 3])
    title_region = free_rect(dict(x=heading['x'], y=heading['y'], w=width-margin-heading['x'], h=heading['h']), protected, 3)
    if title_region and (abs(title_region['y']-heading['y']) > .1 or abs(title_region['h']-heading['h']) > .1):
        title_region = None
    return dict(layout=layout, heading=heading, body=area, title=title_region, remove=removable, style=style, protected=protected)

def readable_text_geometry(option, data):
    """Reserve two title lines and readable body text in measured free space."""
    heading, body = option['heading'], option['body']
    top = min(heading['y'], body['y'])
    bounds = dict(x=body['x'], y=top, w=body['w'], h=body['y']+body['h']-top)
    canvas = free_rect(bounds, option['protected'], max(8, data['width']*.01))
    if not canvas:
        return None
    # Relative to the native slide canvas, not a specific uploaded template.
    title_size = max(16, min(90, data['height']/18))
    body_size = max(12, min(72, data['height']/22.5))
    title_height = title_size*2.6
    gap = max(8, data['height']*.03)
    body_top = canvas['y']+title_height+gap
    body_height = canvas['y']+canvas['h']-body_top
    if canvas['w'] < title_size*10 or body_height < body_size*1.2*4:
        return None
    return dict(title=dict(x=canvas['x'],y=canvas['y'],w=canvas['w'],h=title_height),
                body=dict(x=canvas['x'],y=body_top,w=canvas['w'],h=body_height),titleSize=title_size,bodySize=body_size)

def apply_text_title_geometry(title, proposal, heading):
    region = proposal['title']
    transform = title.find('p:spPr/a:xfrm', NS)
    if transform is None:
        return False
    off, extent = transform.find('a:off', NS), transform.find('a:ext', NS)
    if off is None or extent is None:
        return False
    for key in ('x', 'y'):
        off.set(key, str(round(region[key]*12700)))
    for key, dimension in (('cx', 'w'), ('cy', 'h')):
        extent.set(key, str(round(region[dimension]*12700)))
    body = title.find('p:txBody', NS)
    properties = body.find('a:bodyPr', NS)
    if properties is None:
        properties = etree.Element('{%s}bodyPr' % NS['a'])
        body.insert(0, properties)
    for name, value in dict(wrap='square',anchor='t',lIns=0,rIns=0,tIns=0,bIns=0).items():
        properties.set(name, str(value))
    for child in list(properties):
        if etree.QName(child).localname in ('spAutoFit','normAutofit','noAutofit'):
            properties.remove(child)
    node(properties, 'a:noAutofit')
    for paragraph in body.findall('a:p', NS):
        paragraph_style = paragraph.find('a:pPr', NS)
        if paragraph_style is None:
            paragraph_style = etree.Element('{%s}pPr' % NS['a'])
            paragraph.insert(0, paragraph_style)
        for line in paragraph_style.findall('a:lnSpc', NS):
            paragraph_style.remove(line)
        spacing = etree.Element('{%s}lnSpc' % NS['a'])
        node(spacing, 'a:spcPct', val=110000)
        paragraph_style.insert(0, spacing)
        for run in paragraph.findall('a:r', NS):
            run_properties = run.find('a:rPr', NS)
            if run_properties is None:
                run_properties = etree.Element('{%s}rPr' % NS['a'])
                run.insert(0, run_properties)
            run_properties.set('sz', str(round(proposal['titleSize']*100)))
            run_properties.set('b', str(int(bool(heading.get('bold')))))
        for end in paragraph.findall('a:endParaRPr', NS):
            end.set('sz', str(round(proposal['titleSize']*100)))
    return True

def append_data_layouts(parts, data, model, analyzer):
    """Return (prepared parts, derivative records), or the untouched parts.

    Original slide parts and order stay byte-identical. Stable part identities
    and an explicit package marker make re-analysis idempotent.
    """
    existing_kinds = {item['kind'] for item in records(parts)}
    usable = [layout for layout in data['layouts'] if layout.get('usable') and not layout.get('requiresRebuild')]
    def regular_table(layout):
        for identity in {slot['shapeId'] for slot in layout['slots'] if slot.get('cell') is not None}:
            cells = [slot for slot in layout['slots'] if slot['shapeId'] == identity and slot.get('cell') is not None]
            rows, columns = max(cell['cell'][0] for cell in cells)+1, max(cell['cell'][1] for cell in cells)+1
            if rows < 2 or not 2 <= columns <= 8 or len(cells) != rows*columns:
                continue
            by_cell = {tuple(cell['cell']): cell for cell in cells}
            if all((r, c) in by_cell and by_cell[r, c]['key'] == 's%d_r%d_c%d' % (identity, r, c) and
                   abs(by_cell[r, c]['x']-by_cell[0, c]['x']) <= .1 and abs(by_cell[r, c]['w']-by_cell[0, c]['w']) <= .1 and
                   abs(by_cell[r, c]['y']-by_cell[r, 0]['y']) <= .1 and abs(by_cell[r, c]['h']-by_cell[r, 0]['h']) <= .1
                   for r in range(rows) for c in range(columns)):
                return True
        return False
    missing_tables = 'table' not in existing_kinds and not any(regular_table(layout) for layout in usable)
    missing_charts = 'chart' not in existing_kinds and not any(layout.get('charts') for layout in usable)
    usable_ids = {layout['id'] for layout in usable}
    missing_image_frame = 'image' not in existing_kinds and not any(item.get('placeholder_type') == 'pic' for slide in model['slides'] if slide['slide_id'] in usable_ids for item in objects(slide['objects']))
    missing_text = 'text' not in existing_kinds
    if not missing_tables and not missing_charts and not missing_image_frame and not missing_text:
        return parts, []
    slides = {slide['slide_id']: slide for slide in model['slides']}
    assignments = {item['slide_id']: item.get('role_assignments', []) for item in analyzer.get('slide_assignments', [])}
    available = [option for layout in data['layouts'] if layout.get('usable') and layout['id'] in slides and (option := candidate(parts, data, layout, slides[layout['id']], assignments.get(layout['id'], [])))]
    if not available:
        return parts, []
    chosen = max(available, key=lambda option: (option['body']['w']*option['body']['h'], -option['layout']['index']))
    text_geometry = readable_text_geometry(chosen, data) if missing_text else None
    size = chosen['style']['bodySize']
    table_columns = min(4, math.floor(chosen['body']['w']/(size*2+12)))
    table_data_rows = min(3, math.floor(chosen['body']['h']/(size*1.35+8))-1)
    can_add_table = missing_tables and table_columns >= 2 and table_data_rows >= 1
    variants = ([('text', None, 0)] if text_geometry else []) + ([('table', None, 0)] if can_add_table else []) + ([('chart', kind, count) for kind, count in [('bar', 1), ('line', 1), ('line', 2), ('xy', 1), ('xy', 2)]] if missing_charts else []) + ([('image', None, 0)] if missing_image_frame else [])
    variants = variants[:max(0, 100-len(data['layouts']))]
    if not variants:
        return parts, []
    result = dict(parts)
    presentation = xml(parts['ppt/presentation.xml'])
    presentation_rels = xml(parts['ppt/_rels/presentation.xml.rels'])
    types = xml(parts['[Content_Types].xml'])
    listing = presentation.find('p:sldIdLst', NS)
    next_id = max([int(item.get('id')) for item in listing]+[255])+1
    source_layout = chosen['layout']
    added = []
    for offset, (kind, chart_type, series_count) in enumerate(variants):
        key = '%s:%d:%s:%s:%d' % (source_layout['part'], DATA_LAYOUT_VERSION, kind, chart_type or '', series_count)
        token = hashlib.sha256(key.encode()).hexdigest()[:16]
        part = 'ppt/slides/nerpaData'+token+'.xml'
        root = xml(parts[source_layout['part']])
        tree = root.find('p:cSld/p:spTree', NS)
        for identity in chosen['remove']:
            for identity_node in tree.xpath('.//p:cNvPr[@id=$id]', namespaces=NS, id=str(identity)):
                shape = identity_node.getparent().getparent()
                if shape.getparent() is not None:
                    shape.getparent().remove(shape)
        for timing in root.findall('p:timing', NS):
            root.remove(timing)
        root.attrib.pop('show', None)
        title = tree.xpath('./p:sp[p:nvSpPr/p:cNvPr/@id=$id]', namespaces=NS, id=str(chosen['heading']['shapeId']))[0]
        if chosen['title']:
            transform = title.find('p:spPr/a:xfrm', NS)
            if transform is not None:
                off, extent = transform.find('a:off', NS), transform.find('a:ext', NS)
                if off is not None and extent is not None:
                    off.set('x', str(round(chosen['title']['x']*12700)))
                    extent.set('cx', str(round(chosen['title']['w']*12700)))
        title_nodes = title.findall('.//a:t', NS)
        for index, text in enumerate(title_nodes):
            text.text = {'text': 'Основные положения', 'table': 'Таблица сравнения', 'chart': 'График по данным', 'image': 'Иллюстрация из материала'}[kind] if index == 0 else ''
        if kind == 'text' and not apply_text_title_geometry(title,text_geometry,chosen['heading']):
            continue
        relationship_name = relationship_part(source_layout['part'])
        relationships = xml(parts[relationship_name]) if relationship_name in parts else etree.Element('{%s}Relationships' % NS['pr'])
        for relation in list(relationships):
            if relation.get('Type', '').endswith(('/notesSlide', '/comments', '/commentAuthors', '/slide')):
                relationships.remove(relation)
        # Removed body hyperlinks must not leave references to other slides.
        for link in root.xpath('.//*[@r:id]', namespaces=NS):
            if not any(relation.get('Id') == link.get('{%s}id' % NS['r']) for relation in relationships):
                link.getparent().remove(link)
        shape_id = max([int(item.get('id')) for item in root.findall('.//p:cNvPr', NS)]+[1])+1
        if kind == 'text':
            add_body_text(tree, shape_id, text_geometry['body'], {**chosen['style'],'textBodySize':text_geometry['bodySize']})
        elif kind == 'table':
            from runtime.table_builder import add_data_table
            add_data_table(tree, shape_id, chosen['body'], chosen['style'], columns=table_columns, data_rows=table_data_rows)
        elif kind == 'chart':
            add_data_chart(tree, shape_id, chosen['body'], chosen['style'], result, relationships, types, key, chart_type, series_count)
        else:
            # A standalone p:sp with p:ph type=pic is not a real picture in
            # LibreOffice when its referenced source layout owns no matching
            # placeholder. Start with an ordinary picture instead: the normal
            # replacement path updates its native blip in every renderer.
            bitmap = io.BytesIO()
            Image.new('RGBA', (1, 1), (0, 0, 0, 0)).save(bitmap, format='PNG')
            payload = bitmap.getvalue()
            media = 'ppt/media/nerpaDataFrame-'+hashlib.sha256(payload).hexdigest()+'.png'
            while media in result and result[media] != payload:
                media = media[:-4]+'x.png'
            result[media] = payload
            if not any(item.get('Extension') == 'png' for item in types):
                node(types, 'ct:Default', Extension='png', ContentType='image/png')
            image_rid = 'nerpaDataImage'+token
            node(relationships, 'pr:Relationship', Id=image_rid, Type=NS['r']+'/image', Target='../media/'+media.rsplit('/', 1)[-1])
            shape = node(tree, 'p:pic')
            nv = node(shape, 'p:nvPicPr')
            node(nv, 'p:cNvPr', id=shape_id, name='Иллюстрация из материала')
            node(node(nv, 'p:cNvPicPr'), 'a:picLocks', noChangeAspect=1)
            node(nv, 'p:nvPr')
            fill = node(shape, 'p:blipFill')
            node(fill, 'a:blip').set('{%s}embed' % NS['r'], image_rid)
            node(node(fill, 'a:stretch'), 'a:fillRect')
            properties = node(shape, 'p:spPr')
            transform = node(properties, 'a:xfrm')
            region = chosen['body']
            node(transform, 'a:off', x=round(region['x']*12700), y=round(region['y']*12700))
            node(transform, 'a:ext', cx=round(region['w']*12700), cy=round(region['h']*12700))
            node(node(properties, 'a:prstGeom', prst='rect'), 'a:avLst')
            node(properties, 'a:noFill')
            node(node(properties, 'a:ln'), 'a:noFill')
        extension_list = root.find('p:extLst', NS)
        if extension_list is None:
            extension_list = node(root, 'p:extLst')
        for previous in extension_list.findall('p:ext[@uri="%s"]' % DATA_EXTENSION, NS):
            extension_list.remove(previous)
        extension = node(extension_list, 'p:ext', uri=DATA_EXTENSION)
        metadata = etree.SubElement(extension, '{%s}dataLayout' % DATA_NAMESPACE, kind=kind, sourceLayoutId=source_layout['id'], version=str(DATA_LAYOUT_VERSION))
        if chart_type:
            metadata.set('chartType', chart_type)
            metadata.set('seriesCount', str(series_count))
        if kind == 'image':
            metadata.set('frameShapeId', str(shape_id))
        if kind == 'text':
            metadata.set('titleShapeId', str(chosen['heading']['shapeId']))
            metadata.set('bodyShapeId', str(shape_id))
        result[part] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
        result[relationship_part(part)] = etree.tostring(relationships, xml_declaration=True, encoding='UTF-8')
        rid = 'nerpaData'+token
        node(presentation_rels, 'pr:Relationship', Id=rid, Type=NS['r']+'/slide', Target=posixpath.relpath(part, 'ppt'))
        item = node(listing, 'p:sldId', id=next_id+offset)
        item.set('{%s}id' % NS['r'], rid)
        node(types, 'ct:Override', PartName='/'+part, ContentType='application/vnd.openxmlformats-officedocument.presentationml.slide+xml')
        added.append(dict(part=part, kind=kind, sourceLayoutId=source_layout['id'], chartType=chart_type, seriesCount=series_count,
                          **(dict(titleShapeId=chosen['heading']['shapeId'],bodyShapeId=shape_id) if kind == 'text' else {})))
    result['ppt/presentation.xml'] = etree.tostring(presentation, xml_declaration=True, encoding='UTF-8')
    result['ppt/_rels/presentation.xml.rels'] = etree.tostring(presentation_rels, xml_declaration=True, encoding='UTF-8')
    result['[Content_Types].xml'] = etree.tostring(types, xml_declaration=True, encoding='UTF-8')
    return result, added
