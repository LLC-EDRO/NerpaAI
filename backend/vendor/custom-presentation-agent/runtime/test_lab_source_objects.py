"""Native compiler object addresses include non-text paint without permissions drift."""
import copy
import unittest
from lxml import etree
from runtime.security import NS, xml
from runtime.layout_metadata import source_objects
from runtime.test_lab_data_layouts import source_fixture
from runtime.embedded_objects import PREVIEW_EXTENSION

class SourceObjects(unittest.TestCase):
    def fixture(self):
        parts, data, model, analyzer = source_fixture()
        root = xml(parts['ppt/slides/slide1.xml'])
        items = model['slides'][0]['objects']
        return root, items, {4:'logo'}

    def append(self, root, items, identity, kind='shape', parent=None, fill=None, line=None, text=None):
        tree = parent if parent is not None else root.find('p:cSld/p:spTree', NS)
        tags = {'shape':('sp','nvSpPr'), 'group':('grpSp','nvGrpSpPr'), 'picture':('pic','nvPicPr')}
        tag, nvtag = tags[kind]
        shape = etree.SubElement(tree, '{%s}%s' % (NS['p'], tag))
        nv = etree.SubElement(shape, '{%s}%s' % (NS['p'], nvtag))
        etree.SubElement(nv, '{%s}cNvPr' % NS['p'], id=str(identity), name='Native object')
        props = etree.SubElement(shape, '{%s}%s' % (NS['p'], 'grpSpPr' if kind == 'group' else 'spPr'))
        if kind == 'shape':
            etree.SubElement(props, '{%s}prstGeom' % NS['a'], prst='rect')
            if fill:
                etree.SubElement(etree.SubElement(props, '{%s}solidFill' % NS['a']), '{%s}srgbClr' % NS['a'], val=fill.lstrip('#'))
            else:etree.SubElement(props, '{%s}noFill' % NS['a'])
            etree.SubElement(props, '{%s}ln' % NS['a'])
        if text is not None:
            body = etree.SubElement(shape, '{%s}txBody' % NS['p'])
            etree.SubElement(body, '{%s}bodyPr' % NS['a'])
            etree.SubElement(etree.SubElement(etree.SubElement(body, '{%s}p' % NS['a']), '{%s}r' % NS['a']), '{%s}t' % NS['a']).text = text
        item = dict(shape_id=identity, object_kind=kind, source_level='slide', fill=dict(color=fill) if fill else None,
                    line=line, geometry=dict(x_emu=40*12700, y_emu=150*12700, width_emu=300*12700, height_emu=200*12700), children=[])
        items.append(item)
        return shape, item

    def test_non_text_cards_and_empty_frames_have_stable_addresses_and_editability(self):
        root, items, roles = self.fixture()
        self.append(root, items, 5, fill='#F1F7FF')
        self.append(root, items, 24)
        before = etree.tostring(root); original = copy.deepcopy(items)
        result = source_objects(root, items, roles, 960, 540)
        by_id = {entry['shapeId']:entry for entry in result}
        self.assertEqual(by_id[5]['fill'], {'color':'#F1F7FF'})
        self.assertFalse(by_id[5]['hasText']); self.assertTrue(by_id[5]['canRemove'])
        self.assertTrue(by_id[24]['canRemove']); self.assertIsNone(by_id[24]['fill'])
        self.assertFalse(by_id[24]['frameEditable'])
        self.assertEqual(by_id[24]['box'], dict(x=40,y=150,w=300,h=200))
        self.assertTrue(by_id[2]['hasText']); self.assertTrue(by_id[2]['frameEditable'])
        self.assertFalse(by_id[4]['canRemove']); self.assertFalse(by_id[4]['frameEditable'])
        self.assertEqual([entry['zOrder'] for entry in result], list(range(5)))
        self.assertEqual(etree.tostring(root), before); self.assertEqual(items, original)

    def test_protected_group_ancestors_descendants_and_static_previews_cannot_be_removed(self):
        root, items, roles = self.fixture()
        group, group_item = self.append(root, items, 10, 'group')
        _, child = self.append(root, group_item['children'], 11, parent=group, text='Brand child')
        child['parent_group_path'] = 'slide_1_obj_10'
        roles[10] = 'brand'
        _, second = self.append(root, items, 20, 'group')
        second_shape = root.xpath('.//p:grpSp[p:nvGrpSpPr/p:cNvPr/@id="20"]',namespaces=NS)[0]
        self.append(root, second['children'], 21, parent=second_shape, text='Logo child')
        roles[21] = 'logo'
        picture, _ = self.append(root, items, 30, 'picture')
        nv = picture.find('p:nvPicPr/p:cNvPr', NS)
        etree.SubElement(etree.SubElement(nv, '{%s}extLst' % NS['a']), '{%s}ext' % NS['a'], uri=PREVIEW_EXTENSION)
        result = {entry['shapeId']:entry for entry in source_objects(root, items, roles, 960, 540)}
        for identity in (4,10,11,20,21,30):
            self.assertFalse(result[identity]['canRemove'], identity)
            self.assertFalse(result[identity]['frameEditable'], identity)
        self.assertEqual(result[11]['parentShapeId'], 10)
        self.assertEqual(result[11]['groupPath'], 'slide_1_obj_10')
        self.assertFalse(result[11]['topLevel'])

    def test_inherited_ids_never_become_local_and_top_level_objects_get_bounded_priority(self):
        root, items, roles = self.fixture()
        items.insert(0, dict(shape_id=2, source_level='master', object_kind='shape', geometry={}))
        group, group_item = self.append(root, items, 10, 'group')
        for identity in range(100,110):self.append(root, group_item['children'], identity, parent=group, text='Child')
        self.append(root, items, 24)
        selected = source_objects(root, items, roles, 960, 540, limit=5)
        self.assertEqual({entry['shapeId'] for entry in selected}, {2,3,4,10,24})
        self.assertEqual(len([entry for entry in selected if entry['shapeId']==2]), 1)
        all_entries = {entry['shapeId']:entry for entry in source_objects(root, items, roles, 960, 540)}
        self.assertTrue(all_entries[10]['canRemove'])
        for identity in range(100,110):self.assertFalse(all_entries[identity]['canRemove'])

if __name__ == '__main__':unittest.main()
