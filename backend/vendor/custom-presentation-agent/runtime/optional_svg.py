"""Recover missing optional Office SVG previews using their intact raster.

No relationship URI policy is relaxed. The caller first validates every raw
relationship. Only a canonical SVG extension with one missing internal image
relationship and a fully decoded PNG/JPEG primary image may be removed.
"""
import io
import posixpath
import warnings
from PIL import Image
from lxml import etree
from runtime.security import NS, xml, relationship_target

SVG_NAMESPACE = 'http://schemas.microsoft.com/office/drawing/2016/SVG/main'
SVG_EXTENSION = '{96DAC541-7B7A-43D3-8B79-37D633B846F1}'
RECOVERY_EXTENSION = '{A9635179-0E73-4BDB-BE80-D94A110F2184}'
RECOVERY_NAMESPACE = 'https://nerpa.ai/presentation/svg-fallback-recovery/1'
MAX_RASTER_BYTES = 40*1024*1024
MAX_RASTER_PIXELS = 40_000_000

def owner_part(relationship_part):
    if relationship_part == '_rels/.rels':
        return None
    return posixpath.join(posixpath.dirname(posixpath.dirname(relationship_part)), posixpath.basename(relationship_part)[:-5])

def raster_format(parts, part, content_types, cache):
    if part in cache:
        return cache[part]
    data = parts.get(part)
    suffix = part.rsplit('.', 1)[-1].lower()
    defaults = [item.get('ContentType') for item in content_types if item.tag == '{%s}Default' % NS['ct'] and item.get('Extension', '').lower() == suffix]
    overrides = [item.get('ContentType') for item in content_types if item.tag == '{%s}Override' % NS['ct'] and item.get('PartName') == '/'+part]
    mime = overrides[0] if len(overrides) == 1 else defaults[0] if not overrides and len(defaults) == 1 else None
    expected = 'PNG' if mime == 'image/png' and suffix == 'png' else 'JPEG' if mime == 'image/jpeg' and suffix in ('jpg', 'jpeg') else None
    valid = False
    if expected and data and len(data) <= MAX_RASTER_BYTES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format == expected and 0 < image.width*image.height <= MAX_RASTER_PIXELS:
                        image.load()
                        valid = True
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            pass
    cache[part] = valid
    return valid

def optional_svg_recoveries(parts):
    result = {}
    for part, data in parts.items():
        if not part.startswith('ppt/') or not part.endswith('.xml'):
            continue
        for extension in xml(data).findall('.//a:ext[@uri="%s"]' % RECOVERY_EXTENSION, NS):
            marker = extension.find('{%s}missingSvgFallback' % RECOVERY_NAMESPACE)
            if marker is None:
                continue
            record = dict(part=marker.get('sourcePart', part), relationshipId=marker.get('relationshipId'), target=marker.get('target'), primaryTarget=marker.get('primaryTarget'))
            if all(isinstance(value, str) and value for value in record.values()):
                result[(record['part'], record['relationshipId'])] = record
    return list(result.values())

def normalize_optional_svg(parts):
    result = dict(parts)
    content_types = xml(parts['[Content_Types].xml'])
    raster_cache = {}
    for name, data in parts.items():
        if not name.endswith('.rels'):
            continue
        owner = owner_part(name)
        if owner not in parts or not owner.startswith('ppt/') or not owner.endswith('.xml'):
            continue
        relationships = xml(data)
        by_id = {relationship.get('Id'): relationship for relationship in relationships}
        root = xml(parts[owner])
        plans = []
        for relation in relationships:
            if relation.get('Type') != NS['r']+'/image' or relation.get('TargetMode') == 'External':
                continue
            target = relationship_target(name, relation.get('Target', ''))
            if target in parts:
                continue
            identity = relation.get('Id')
            # Include every relationship-namespace attribute, not merely the
            # common embed/id/link spellings; unknown consumers remain errors.
            uses = [element for element in root.iter() if any(key.startswith('{%s}' % NS['r']) and value == identity for key, value in element.attrib.items())]
            if len(uses) != 1:
                continue
            svg = uses[0]
            extension = svg.getparent()
            collection = extension.getparent() if extension is not None else None
            primary = collection.getparent() if collection is not None else None
            if (svg.tag != '{%s}svgBlip' % SVG_NAMESPACE or len(svg) or dict(svg.attrib) != {'{%s}embed' % NS['r']: identity} or extension is None or collection is None or primary is None or
                extension.tag != '{%s}ext' % NS['a'] or extension.get('uri') != SVG_EXTENSION or len(extension) != 1 or
                collection.tag != '{%s}extLst' % NS['a'] or primary.tag != '{%s}blip' % NS['a'] or primary.get('{%s}link' % NS['r'])):
                continue
            raster = by_id.get(primary.get('{%s}embed' % NS['r']))
            if raster is None or raster.get('Type') != NS['r']+'/image' or raster.get('TargetMode') == 'External':
                continue
            primary_target = relationship_target(name, raster.get('Target', ''))
            if not raster_format(parts, primary_target, content_types, raster_cache):
                continue
            plans.append((relation, extension, primary, primary_target))
        for relation, extension, primary, primary_target in plans:
            extension.getparent().remove(extension)
            relationships.remove(relation)
            collection = primary.find('a:extLst', NS)
            if collection is None:
                collection = etree.SubElement(primary, '{%s}extLst' % NS['a'])
            marker_extension = etree.SubElement(collection, '{%s}ext' % NS['a'], uri=RECOVERY_EXTENSION)
            etree.SubElement(marker_extension, '{%s}missingSvgFallback' % RECOVERY_NAMESPACE, sourcePart=owner,
                             relationshipId=relation.get('Id'), target=relation.get('Target'), primaryTarget=primary_target)
        if plans:
            result[owner] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            result[name] = etree.tostring(relationships, xml_declaration=True, encoding='UTF-8', standalone=True)
    return result
