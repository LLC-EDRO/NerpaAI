import hashlib
import io
import tempfile
import unittest
import zipfile
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from runtime.security import NS, xml, read_package
from runtime.embedded_objects import embedded_preview_records, protected_preview_shape_ids

class EmbeddedObjectTests(unittest.TestCase):
    part = 'ppt/slides/slide1.xml'
    rel_part = 'ppt/slides/_rels/slide1.xml.rels'
    payload_part = 'ppt/embeddings/oleObject1.bin'

    def fixture(self, alternate=True):
        picture = '''<p:pic><p:nvPicPr><p:cNvPr id="0" name="Fallback"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
          <p:blipFill><a:blip r:embed="image"/><a:srcRect l="1000"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
          <p:spPr><a:xfrm><a:off x="1" y="2"/><a:ext cx="3" cy="4"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'''
        obj = '<p:oleObj r:id="ole" progId="CorelDraw.Graphic.22"><p:embed/>' + picture + '</p:oleObj>'
        if alternate:
            obj = '<mc:AlternateContent><mc:Choice Requires="v"><p:oleObj r:id="ole" progId="CorelDraw.Graphic.22"><p:embed/></p:oleObj></mc:Choice><mc:Fallback>' + obj + '</mc:Fallback></mc:AlternateContent>'
        slide = f'''<p:sld xmlns:p="{NS['p']}" xmlns:a="{NS['a']}" xmlns:r="{NS['r']}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:v="urn:schemas-microsoft-com:vml">
          <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
          <p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="42" name="Brand artwork"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
          <p:xfrm rot="60000" flipH="1"><a:off x="127000" y="254000"/><a:ext cx="1270000" cy="635000"/></p:xfrm>
          <a:graphic><a:graphicData uri="{NS['p']}/ole">{obj}</a:graphicData></a:graphic></p:graphicFrame></p:spTree></p:cSld></p:sld>'''
        rels = f'''<Relationships xmlns="{NS['pr']}"><Relationship Id="ole" Type="{NS['r']}/oleObject" Target="../embeddings/oleObject1.bin"/>
          <Relationship Id="image" Type="{NS['r']}/image" Target="../media/image1.emf"/></Relationships>'''
        return {
            '[Content_Types].xml': f'''<Types xmlns="{NS['ct']}"><Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/{self.payload_part}" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/></Types>'''.encode(),
            'ppt/presentation.xml': f'<p:presentation xmlns:p="{NS["p"]}" xmlns:r="{NS["r"]}"><p:sldIdLst><p:sldId id="256" r:id="slide"/></p:sldIdLst></p:presentation>'.encode(),
            'ppt/_rels/presentation.xml.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="slide" Type="{NS["r"]}/slide" Target="slides/slide1.xml"/></Relationships>'.encode(),
            self.part: slide.encode(), self.rel_part: rels.encode(),
            self.payload_part: b'opaque payload: never opened or executed',
            'ppt/media/image1.emf': b'unchanged cached artwork',
        }

    def package(self, parts):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def change_xml(self, parts, name, change):
        root = xml(parts[name]);change(root)
        parts[name] = etree.tostring(root)

    def test_alternate_content_becomes_one_protected_picture_with_outer_identity_and_geometry(self):
        original = self.fixture()
        result = read_package(self.package(original))
        root = xml(result[self.part]);pictures = root.findall('.//p:pic', NS)
        self.assertEqual(len(pictures), 1)
        self.assertFalse(root.findall('.//p:graphicFrame', NS))
        self.assertFalse(root.findall('.//p:oleObj', NS))
        picture = pictures[0]
        identity = picture.find('p:nvPicPr/p:cNvPr', NS)
        self.assertEqual((identity.get('id'), identity.get('name')), ('42', 'Brand artwork'))
        transform = picture.find('p:spPr/a:xfrm', NS)
        self.assertEqual(dict(transform.attrib), dict(rot='60000', flipH='1'))
        self.assertEqual(dict(transform.find('a:off', NS).attrib), dict(x='127000', y='254000'))
        self.assertEqual(dict(transform.find('a:ext', NS).attrib), dict(cx='1270000', cy='635000'))
        self.assertEqual(picture.find('p:blipFill/a:srcRect', NS).get('l'), '1000')
        self.assertEqual(protected_preview_shape_ids(root), {42})
        self.assertEqual(embedded_preview_records(result), [dict(part=self.part, shapeId=42)])
        self.assertNotIn(self.payload_part, result)
        self.assertFalse(any(r.get('Type', '').endswith('/oleObject') for r in xml(result[self.rel_part])))
        self.assertFalse(any(n.get('PartName') == '/' + self.payload_part for n in xml(result['[Content_Types].xml'])))
        self.assertEqual(result['ppt/media/image1.emf'], original['ppt/media/image1.emf'])
        self.assertEqual(read_package(self.package(result)), result)

    def test_direct_cached_picture_is_supported_without_alternate_content(self):
        self.assertEqual(len(embedded_preview_records(read_package(self.package(self.fixture(False))))), 1)

    def test_private_prepared_copy_keeps_immutable_original_and_contains_no_payload(self):
        from runtime.fonts import prepare_font_copy, effective_source
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory);source = folder / 'source.pptx'
            source.write_bytes(self.package(self.fixture()));before = source.read_bytes()
            parts = read_package(before)
            prepared = prepare_font_copy(parts, folder, [])
            data = dict(sha256=hashlib.sha256(before).hexdigest(), preparedSha256=hashlib.sha256(prepared.read_bytes()).hexdigest())
            self.assertEqual(effective_source(source, folder, data), prepared)
            self.assertEqual(source.read_bytes(), before)
            with zipfile.ZipFile(prepared) as archive:
                self.assertNotIn(self.payload_part, archive.namelist())
                self.assertNotIn(b'oleObj', archive.read(self.part))

    def test_recovered_picture_is_preserved_in_explicit_visual_slots(self):
        from runtime.layout_metadata import visual_slots
        parts = read_package(self.package(self.fixture()))
        item = dict(shape_id=42, object_kind='picture', source_level='slide', source_part=self.part,
                    name='Brand artwork', geometry=dict(x_emu=127000, y_emu=254000, width_emu=1270000, height_emu=635000))
        slots = visual_slots([item], dict(part=self.part, slots=[]), {42: 'content'}, parts)
        self.assertEqual(len(slots), 1)
        self.assertTrue(slots[0]['protected'])
        self.assertEqual(slots[0]['sourceRole'], 'decoration')

    def item(self, identity, kind='picture', **changes):
        return dict(shape_id=identity, object_kind=kind, source_level='slide', source_part=self.part,
                    geometry=dict(x_emu=127000, y_emu=254000, width_emu=1270000, height_emu=635000), children=[]) | changes

    def test_missing_cached_picture_is_rejected(self):
        parts = self.fixture()
        def remove(root):
            for picture in root.findall('.//p:pic', NS):picture.getparent().remove(picture)
        self.change_xml(parts, self.part, remove)
        with self.assertRaisesRegex(ValueError, 'pptx_embedded_object_not_supported'):
            read_package(self.package(parts))

    def test_conflicting_cached_pictures_are_rejected(self):
        parts = self.fixture()
        def conflict(root):
            obj = root.find('.//p:oleObj', NS)
            picture = deepcopy(root.find('.//p:pic', NS));picture.find('p:blipFill/a:srcRect', NS).set('l', '5000')
            obj.append(picture)
        self.change_xml(parts, self.part, conflict)
        with self.assertRaisesRegex(ValueError, 'pptx_embedded_object_not_supported'):
            read_package(self.package(parts))

    def test_external_preview_and_external_ole_are_rejected_before_recovery(self):
        for relationship in ('image', 'ole'):
            with self.subTest(relationship=relationship):
                parts = self.fixture()
                def external(root):
                    rel = next(r for r in root if r.get('Id') == relationship)
                    rel.set('TargetMode', 'External');rel.set('Target', 'https://example.com/payload')
                self.change_xml(parts, self.rel_part, external)
                with self.assertRaisesRegex(ValueError, 'pptx_external_resource_not_supported'):
                    read_package(self.package(parts))

    def test_macro_and_activex_parts_are_still_rejected(self):
        for part in ('ppt/vbaProject.bin', 'ppt/activeX/activeX1.bin'):
            with self.subTest(part=part):
                parts = self.fixture();parts[part] = b'disallowed'
                with self.assertRaisesRegex(ValueError, 'pptx_active_content_not_supported'):
                    read_package(self.package(parts))

    def test_control_relationship_is_still_rejected(self):
        parts = self.fixture()
        def control(root):root[0].set('Type', NS['r'] + '/control')
        self.change_xml(parts, self.rel_part, control)
        with self.assertRaisesRegex(ValueError, 'pptx_active_content_not_supported'):
            read_package(self.package(parts))

    def test_unreferenced_binary_and_payload_still_referenced_elsewhere_are_rejected(self):
        parts = self.fixture();parts['ppt/embeddings/unowned.bin'] = b'unowned'
        with self.assertRaisesRegex(ValueError, 'pptx_embedded_object_not_supported'):
            read_package(self.package(parts))
        parts = self.fixture()
        self.change_xml(parts, self.rel_part, lambda root:etree.SubElement(root, '{%s}Relationship' % NS['pr'], Id='other', Type=NS['r'] + '/package', Target='../embeddings/oleObject1.bin'))
        with self.assertRaisesRegex(ValueError, 'pptx_embedded_object_not_supported'):
            read_package(self.package(parts))

    def test_broken_and_unsafe_relationships_are_not_hidden_by_recovery(self):
        for target, error in (('../media/missing.emf', 'pptx_broken_relationship'), ('../../../escape.bin', 'pptx_unsafe_relationship')):
            with self.subTest(target=target):
                parts = self.fixture()
                self.change_xml(parts, self.rel_part, lambda root:root[0].set('Target', target))
                with self.assertRaisesRegex(ValueError, error):read_package(self.package(parts))

    def test_chart_workbook_and_its_active_content_checks_remain_intact(self):
        parts = self.fixture()
        parts['ppt/embeddings/chart.xlsx'] = self.package({'xl/workbook.xml': b'<workbook/>'})
        self.assertIn('ppt/embeddings/chart.xlsx', read_package(self.package(parts)))
        parts['ppt/embeddings/chart.xlsx'] = self.package({'xl/vbaProject.bin': b'macro'})
        with self.assertRaisesRegex(ValueError, 'pptx_active_content_not_supported'):
            read_package(self.package(parts))

if __name__ == '__main__':
    unittest.main()
