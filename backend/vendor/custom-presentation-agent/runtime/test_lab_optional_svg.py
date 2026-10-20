"""Optional SVG recovery never weakens archive or relationship validation."""
import io
import os
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from lxml import etree
from runtime.security import NS, xml, read_package, relationship_target
from runtime.optional_svg import normalize_optional_svg, optional_svg_recoveries, SVG_EXTENSION, SVG_NAMESPACE

def pack(parts):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            # Repacking the same fixture must not differ at a two-second DOS
            # timestamp boundary while testing source immutability.
            entry=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
            archive.writestr(entry,data,compress_type=zipfile.ZIP_DEFLATED)
    return result.getvalue()

def fixture(count=1, target='NULL', image_format='PNG'):
    bitmap = io.BytesIO()
    Image.new('RGB', (24, 16), '#0133A3').save(bitmap, format=image_format)
    suffix, mime = ('png', 'image/png') if image_format == 'PNG' else ('jpg', 'image/jpeg')
    root = xml(('<p:sld xmlns:p="%s" xmlns:a="%s" xmlns:r="%s"><p:cSld><p:spTree/></p:cSld></p:sld>' % (NS['p'], NS['a'], NS['r'])).encode())
    rels = etree.Element('{%s}Relationships' % NS['pr'])
    etree.SubElement(rels, '{%s}Relationship' % NS['pr'], Id='primary', Type=NS['r']+'/image', Target='../media/primary.'+suffix)
    for i in range(count):
        picture = etree.SubElement(root.find('p:cSld/p:spTree', NS), '{%s}pic' % NS['p'])
        blip = etree.SubElement(etree.SubElement(picture, '{%s}blipFill' % NS['p']), '{%s}blip' % NS['a'])
        blip.set('{%s}embed' % NS['r'], 'primary')
        extension = etree.SubElement(etree.SubElement(blip, '{%s}extLst' % NS['a']), '{%s}ext' % NS['a'], uri=SVG_EXTENSION)
        svg = etree.SubElement(extension, '{%s}svgBlip' % SVG_NAMESPACE)
        svg.set('{%s}embed' % NS['r'], 'svg'+str(i))
        etree.SubElement(rels, '{%s}Relationship' % NS['pr'], Id='svg'+str(i), Type=NS['r']+'/image', Target=target)
    parts = {'ppt/slides/slide1.xml': etree.tostring(root), 'ppt/slides/_rels/slide1.xml.rels': etree.tostring(rels),
             'ppt/media/primary.'+suffix: bitmap.getvalue(),
             '[Content_Types].xml': ('<Types xmlns="%s"><Default Extension="%s" ContentType="%s"/></Types>' % (NS['ct'], suffix, mime)).encode(),
             'ppt/presentation.xml': ('<p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst><p:sldId id="256" r:id="slide1"/></p:sldIdLst></p:presentation>' % (NS['p'], NS['r'])).encode(),
             'ppt/_rels/presentation.xml.rels': ('<Relationships xmlns="%s"><Relationship Id="slide1" Type="%s/slide" Target="slides/slide1.xml"/></Relationships>' % (NS['pr'], NS['r'])).encode()}
    return parts

class OptionalSvg(unittest.TestCase):
    def assert_unrecoverable(self, parts, reason='pptx_broken_relationship'):
        original = deepcopy(parts)
        self.assertEqual(normalize_optional_svg(parts), original)
        self.assertEqual(parts, original)
        with self.assertRaisesRegex(ValueError, '^'+reason+'$'):
            read_package(pack(parts))

    def test_missing_optional_svg_uses_intact_png_or_jpeg_and_is_idempotent(self):
        for image_format in ('PNG', 'JPEG'):
            for target in ('NULL', '../media/missing.svg'):
                with self.subTest(format=image_format, target=target):
                    parts = fixture(target=target, image_format=image_format)
                    original = deepcopy(parts)
                    result = read_package(pack(parts))
                    self.assertEqual(parts, original)
                    self.assertEqual(len(optional_svg_recoveries(result)), 1)
                    self.assertEqual(result['ppt/media/primary.'+('png' if image_format == 'PNG' else 'jpg')], original['ppt/media/primary.'+('png' if image_format == 'PNG' else 'jpg')])
                    self.assertFalse(xml(result['ppt/slides/slide1.xml']).findall('.//{%s}svgBlip' % SVG_NAMESPACE))
                    self.assertEqual(normalize_optional_svg(result), result)
                    self.assertEqual(read_package(pack(result)), result)

    def test_83_missing_svg_hints_recover_without_changing_any_primary_media(self):
        parts = fixture(83)
        payload = pack(parts)
        result = read_package(payload)
        self.assertEqual(len(optional_svg_recoveries(result)), 83)
        self.assertEqual(result['ppt/media/primary.png'], parts['ppt/media/primary.png'])
        self.assertEqual(payload, pack(parts), 'the original upload is immutable')
        for name, data in result.items():
            if name.endswith('.rels'):
                self.assertTrue(all(relationship_target(name, r.get('Target', '')) in result for r in xml(data)))

    def test_existing_svg_metadata_is_preserved(self):
        parts = fixture(target='../media/vector.svg')
        parts['ppt/media/vector.svg'] = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
        self.assertEqual(normalize_optional_svg(parts), parts)
        self.assertEqual(optional_svg_recoveries(read_package(pack(parts))), [])

    def test_missing_primary_invalid_raster_wrong_mime_and_excessive_pixels_are_not_repaired(self):
        for variant in ('missing', 'invalid', 'mime', 'pixels'):
            with self.subTest(variant=variant):
                parts = fixture()
                if variant == 'missing':
                    del parts['ppt/media/primary.png']
                elif variant == 'invalid':
                    parts['ppt/media/primary.png'] = b'not an image'
                elif variant == 'mime':
                    parts['[Content_Types].xml'] = parts['[Content_Types].xml'].replace(b'image/png', b'image/svg+xml')
                if variant == 'pixels':
                    with patch('runtime.optional_svg.MAX_RASTER_PIXELS', 10):
                        self.assert_unrecoverable(parts)
                else:
                    self.assert_unrecoverable(parts)

    def test_noncanonical_or_ambiguous_svg_references_are_not_repaired(self):
        for variant in ('extension', 'extra-child', 'shared-consumer', 'unknown-reference'):
            with self.subTest(variant=variant):
                parts = fixture()
                root = xml(parts['ppt/slides/slide1.xml'])
                extension = root.find('.//a:ext', NS)
                if variant == 'extension':
                    extension.set('uri', '{UNKNOWN}')
                elif variant == 'extra-child':
                    etree.SubElement(extension, 'unknown')
                else:
                    other = etree.SubElement(root, 'unknown')
                    other.set('{%s}%s' % (NS['r'], 'embed' if variant == 'shared-consumer' else 'unexpected'), 'svg0')
                parts['ppt/slides/slide1.xml'] = etree.tostring(root)
                self.assert_unrecoverable(parts)

    def test_all_raw_relationships_are_validated_before_optional_metadata_normalization(self):
        cases = [('external', 'pptx_external_resource_not_supported'), ('unsafe', 'pptx_unsafe_relationship'),
                 ('duplicate', 'pptx_invalid_relationship'), ('active', 'pptx_active_content_not_supported')]
        for variant, reason in cases:
            with self.subTest(variant=variant):
                parts = fixture()
                relations = xml(parts['ppt/slides/_rels/slide1.xml.rels'])
                if variant == 'external':
                    relations[1].set('TargetMode', 'External')
                    relations[1].set('Target', 'https://example.org/image.svg')
                elif variant == 'unsafe':
                    relations[1].set('Target', '../../../../outside.svg')
                elif variant == 'duplicate':
                    relations[1].set('Id', 'primary')
                else:
                    etree.SubElement(relations, '{%s}Relationship' % NS['pr'], Id='active', Type=NS['r']+'/control', Target='../media/primary.png')
                parts['ppt/slides/_rels/slide1.xml.rels'] = etree.tostring(relations)
                original = pack(parts)
                with patch('runtime.optional_svg.normalize_optional_svg', side_effect=AssertionError('normalization ran before raw security checks')):
                    with self.assertRaisesRegex(ValueError, '^'+reason+'$'):
                        read_package(original)
                self.assertEqual(pack(parts), original)

    @unittest.skipUnless(os.environ.get('NERPA_PPTX_OPTIONAL_SVG_FIXTURE'), 'set a local owned fixture to verify the supplied source archive')
    def test_supplied_source_fixture_retains_all_media_bytes(self):
        source = Path(os.environ['NERPA_PPTX_OPTIONAL_SVG_FIXTURE'])
        payload = source.read_bytes()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            media = {name: archive.read(name) for name in archive.namelist() if name.startswith('ppt/media/') and not name.endswith('/')}
        result = read_package(payload)
        self.assertEqual(len(optional_svg_recoveries(result)), 83)
        self.assertEqual({name: result[name] for name in media}, media)
        self.assertEqual(source.read_bytes(), payload)

if __name__ == '__main__':
    unittest.main()
