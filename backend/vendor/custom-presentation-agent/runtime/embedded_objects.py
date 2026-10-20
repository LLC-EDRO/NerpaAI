"""Keep an embedded object's cached artwork, never its executable payload.

Only a complete internal DrawingML picture can replace an OLE graphic frame.
The immutable upload is not rewritten; callers serialize these validated parts
to the existing private prepared copy before parsing or rendering it.
"""
import posixpath
from copy import deepcopy
from lxml import etree
from runtime.security import NS, xml, relationship_target

PREVIEW_EXTENSION = '{C92DFD91-CC73-4D49-9554-C9EE5E07475A}'
PREVIEW_NS = 'https://nerpa.ai/presentation/static-object-preview/1'
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.emf', '.wmf')

def _unsupported():
    raise ValueError('pptx_embedded_object_not_supported')

def _rels_name(part):
    return posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')

def _serialize(root):
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

def protected_preview_shape_ids(root):
    result = set()
    for picture in root.findall('.//p:pic', NS):
        identity = picture.find('p:nvPicPr/p:cNvPr', NS)
        if identity is not None and identity.find('a:extLst/a:ext[@uri="%s"]' % PREVIEW_EXTENSION, NS) is not None:
            try:
                result.add(int(identity.get('id')))
            except (TypeError, ValueError):
                _unsupported()
    return result

def embedded_preview_records(parts):
    return [dict(part=name, shapeId=identity)
            for name, data in parts.items() if name.startswith('ppt/') and name.endswith('.xml')
            for identity in sorted(protected_preview_shape_ids(xml(data)))]

def normalize_embedded_objects(parts):
    """Consume only OLE relationships with a verified, self-contained preview.

    AlternateContent may contain the same object twice: the VML choice and the
    DrawingML fallback. Replace their enclosing graphicFrame once, preserving
    its identity, transform, ordering and the cached picture's crop/effects.
    All unrelated package security checks remain the caller's responsibility.
    """
    result = dict(parts)
    consumed = set()
    for part, data in parts.items():
        if not part.startswith('ppt/') or not part.endswith('.xml'):
            continue
        root = xml(data)
        all_ole = root.findall('.//p:oleObj', NS)
        if not all_ole:
            continue
        rel_part = _rels_name(part)
        if rel_part not in parts:
            _unsupported()
        rel_root = xml(parts[rel_part])
        relationships = {rel.get('Id'): rel for rel in rel_root}
        handled = set()
        removed_ids = set()
        for frame in list(root.findall('.//p:graphicFrame', NS)):
            objects = frame.findall('.//p:oleObj', NS)
            if not objects:
                continue
            identities = {obj.get('{%s}id' % NS['r']) for obj in objects}
            if len(identities) != 1 or None in identities:
                _unsupported()
            rid = next(iter(identities))
            rel = relationships.get(rid)
            if rel is None or not rel.get('Type', '').endswith('/oleObject') or rel.get('TargetMode') == 'External':
                _unsupported()
            target = relationship_target(rel_part, rel.get('Target', ''))
            if not target.startswith('ppt/embeddings/') or target not in parts:
                _unsupported()
            if any(obj.find('p:embed', NS) is None or obj.find('p:link', NS) is not None for obj in objects):
                _unsupported()
            pictures = [picture for obj in objects for picture in obj.findall('p:pic', NS)]
            if not pictures or len({etree.tostring(p, method='c14n') for p in pictures}) != 1:
                _unsupported()
            picture = deepcopy(pictures[0])
            # A preview can reference internal image parts only. No hyperlinks,
            # linked images, media objects or OLE relationships survive it.
            for node in picture.iter():
                for key, value in node.attrib.items():
                    if not key.startswith('{%s}' % NS['r']):
                        continue
                    image_rel = relationships.get(value)
                    if key != '{%s}embed' % NS['r'] or image_rel is None or image_rel.get('TargetMode') == 'External' or not image_rel.get('Type', '').endswith('/image'):
                        _unsupported()
                    image = relationship_target(rel_part, image_rel.get('Target', ''))
                    if not image.startswith('ppt/media/') or image not in parts or not image.lower().endswith(IMAGE_EXTENSIONS):
                        _unsupported()
            if len(picture.findall('p:blipFill/a:blip', NS)) != 1:
                _unsupported()
            blip = picture.find('p:blipFill/a:blip', NS)
            if not blip.get('{%s}embed' % NS['r']):
                _unsupported()
            identity = frame.find('p:nvGraphicFramePr/p:cNvPr', NS)
            transform = frame.find('p:xfrm', NS)
            properties = picture.find('p:spPr', NS)
            nonvisual = picture.find('p:nvPicPr', NS)
            if identity is None or not (identity.get('id') or '').isdigit() or transform is None or properties is None or nonvisual is None:
                _unsupported()
            if transform.find('a:off', NS) is None or transform.find('a:ext', NS) is None:
                _unsupported()
            # The fallback often uses id=0. The outer frame owns the actual
            # slide identity; discard action-bearing nonvisual children.
            safe_identity = etree.Element('{%s}cNvPr' % NS['p'])
            for key in ('id', 'name', 'descr', 'title', 'hidden'):
                if identity.get(key) is not None:
                    safe_identity.set(key, identity.get(key))
            extension = etree.SubElement(etree.SubElement(safe_identity, '{%s}extLst' % NS['a']), '{%s}ext' % NS['a'], uri=PREVIEW_EXTENSION)
            etree.SubElement(extension, '{%s}staticPreview' % PREVIEW_NS)
            for child in list(nonvisual):
                nonvisual.remove(child)
            nonvisual.extend([safe_identity, etree.Element('{%s}cNvPicPr' % NS['p']), etree.Element('{%s}nvPr' % NS['p'])])
            old_transform = properties.find('a:xfrm', NS)
            if old_transform is not None:
                properties.remove(old_transform)
            safe_transform = deepcopy(transform)
            safe_transform.tag = '{%s}xfrm' % NS['a']
            properties.insert(0, safe_transform)
            frame.getparent().replace(frame, picture)
            handled.update(objects)
            removed_ids.add(rid)
            consumed.add(target)
        if set(all_ole) != handled:
            _unsupported()
        for rel in list(rel_root):
            if rel.get('Id') in removed_ids:
                rel_root.remove(rel)
        result[part] = _serialize(root)
        result[rel_part] = _serialize(rel_root)
    if not consumed:
        return result
    # Never remove a payload still referenced by another object. A shared OLE
    # payload is fine only when every owner has been replaced by its preview.
    for name, data in result.items():
        if name.endswith('.rels'):
            for rel in xml(data):
                if rel.get('TargetMode') != 'External' and relationship_target(name, rel.get('Target', '')) in consumed:
                    _unsupported()
    for target in consumed:
        result.pop(target)
    types = xml(result['[Content_Types].xml'])
    for node in list(types):
        if node.tag == '{%s}Override' % NS['ct'] and node.get('PartName', '').lstrip('/') in consumed:
            types.remove(node)
    result['[Content_Types].xml'] = _serialize(types)
    return result
