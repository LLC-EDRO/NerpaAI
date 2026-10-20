"""Source-derived chart/table/image layouts preserve source furniture and data."""
import io
import unittest
from copy import deepcopy
from types import SimpleNamespace
from lxml import etree
from runtime.security import NS, xml, slide_order
from runtime.charts import chart_spec, fill_chart, validate_charts
from runtime.chart_builder import add_data_chart
from runtime.data_layouts import append_data_layouts, records, image_frame_ids, text_frame_ids, DATA_EXTENSION, DATA_NAMESPACE

STYLE = dict(font='DejaVu Sans', ink='#202020', accent='#0133A3', onAccent='#FFFFFF', surface='#EEEEEE', bodySize=18)
BOX = dict(x=40, y=125, w=880, h=360)

def roots():
    slide = xml(('<p:sld xmlns:p="%s" xmlns:a="%s" xmlns:r="%s"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sld>' % (NS['p'], NS['a'], NS['r'])).encode())
    return slide, etree.Element('{%s}Relationships' % NS['pr']), etree.Element('{%s}Types' % NS['ct'])

def source_fixture():
    slide, rels, types = roots()
    tree = slide.find('p:cSld/p:spTree', NS)
    # A title and body sample are independently replaceable; a native logo
    # above them remains byte-identical in every derivative.
    for identity, label in [(2, 'Title'), (3, 'Sample body'), (4, 'Brand')]:
        shape = etree.SubElement(tree, '{%s}sp' % NS['p'])
        nv = etree.SubElement(shape, '{%s}nvSpPr' % NS['p'])
        etree.SubElement(nv, '{%s}cNvPr' % NS['p'], id=str(identity), name=label)
        etree.SubElement(nv, '{%s}cNvSpPr' % NS['p'])
        etree.SubElement(nv, '{%s}nvPr' % NS['p'])
        props = etree.SubElement(shape, '{%s}spPr' % NS['p'])
        transform = etree.SubElement(props, '{%s}xfrm' % NS['a'])
        etree.SubElement(transform, '{%s}off' % NS['a'], x='508000', y='1016000')
        etree.SubElement(transform, '{%s}ext' % NS['a'], cx='4000000', cy='381000')
        body = etree.SubElement(shape, '{%s}txBody' % NS['p'])
        etree.SubElement(body, '{%s}bodyPr' % NS['a'])
        etree.SubElement(body, '{%s}lstStyle' % NS['a'])
        etree.SubElement(etree.SubElement(etree.SubElement(body, '{%s}p' % NS['a']), '{%s}r' % NS['a']), '{%s}t' % NS['a']).text = label
    parts = {'ppt/slides/slide1.xml': etree.tostring(slide), 'ppt/slides/_rels/slide1.xml.rels': etree.tostring(rels), '[Content_Types].xml': etree.tostring(types),
             'ppt/presentation.xml': ('<p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst><p:sldId id="256" r:id="slide1"/></p:sldIdLst></p:presentation>' % (NS['p'], NS['r'])).encode(),
             'ppt/_rels/presentation.xml.rels': ('<Relationships xmlns="%s"><Relationship Id="slide1" Type="%s/slide" Target="slides/slide1.xml"/></Relationships>' % (NS['pr'], NS['r'])).encode()}
    def item(identity, region):
        return dict(shape_id=identity, object_kind='shape', children=[], geometry={name+'_emu': round(region[key]*12700) for name, key in [('x', 'x'), ('y', 'y'), ('width', 'w'), ('height', 'h')]})
    heading = dict(key='s2', shapeId=2, role='header', text='Title', font='DejaVu Sans', size=24, color='#202020', x=40, y=80, w=360, h=32)
    body = dict(heading, key='s3', shapeId=3, role='body', text='Sample body', x=40, y=150, w=700, h=250, size=18)
    data = dict(width=960, height=540, styleProfile=dict(colors=['#0133A3', '#FFFFFF']), layouts=[dict(id='slide_1', index=0, part='ppt/slides/slide1.xml', usable=True, slots=[heading, body], charts=[])])
    model = dict(slides=[dict(slide_id='slide_1', objects=[item(2, heading), item(3, body), item(4, dict(x=40, y=15, w=880, h=45))])])
    analyzer = dict(slide_assignments=[dict(slide_id='slide_1', role_assignments=[dict(source_level='slide', source_open_xml_shape_id=4, role='logo')])])
    return parts, data, model, analyzer

class DataLayouts(unittest.TestCase):
    def test_source_parts_and_logo_survive_native_variants(self):
        parts, data, model, analyzer = source_fixture()
        original = deepcopy(parts)
        result, added = append_data_layouts(parts, data, model, analyzer)
        self.assertEqual(parts, original)
        self.assertEqual(result['ppt/slides/slide1.xml'], original['ppt/slides/slide1.xml'])
        self.assertEqual(len(added), 8)
        self.assertEqual(slide_order(result)[0], 'ppt/slides/slide1.xml')
        self.assertEqual(records(result), added)
        logo = xml(parts['ppt/slides/slide1.xml']).xpath('.//p:sp[p:nvSpPr/p:cNvPr/@id="4"]', namespaces=NS)[0]
        for derivative in added:
            root = xml(result[derivative['part']])
            self.assertEqual(etree.tostring(root.xpath('.//p:sp[p:nvSpPr/p:cNvPr/@id="4"]', namespaces=NS)[0]), etree.tostring(logo))
            self.assertFalse(root.xpath('.//p:cNvPr[@id="3"]', namespaces=NS))
            if derivative['kind'] == 'table':
                self.assertEqual(len(root.findall('.//a:tbl', NS)), 1)
            elif derivative['kind'] == 'image':
                identities = image_frame_ids(root)
                self.assertEqual(len(identities), 1)
                identity = next(iter(identities))
                pictures = root.xpath('.//p:pic[p:nvPicPr/p:cNvPr/@id=$id]', namespaces=NS, id=str(identity))
                self.assertEqual(len(pictures), 1)
                self.assertEqual(len(pictures[0].findall('p:blipFill/a:blip', NS)), 1)
                self.assertFalse(pictures[0].findall('.//p:ph', NS), 'standalone shape placeholders disappear in the actual renderer')
        duplicate, second = append_data_layouts(result, data, model, analyzer)
        self.assertIs(duplicate, result)
        self.assertEqual(second, [])

    def test_no_derivative_can_cover_protected_source_art(self):
        parts, data, model, analyzer = source_fixture()
        logo = model['slides'][0]['objects'][2]
        logo['geometry'] = dict(x_emu=0, y_emu=125*12700, width_emu=960*12700, height_emu=375*12700)
        result, added = append_data_layouts(parts, data, model, analyzer)
        self.assertIs(result, parts)
        self.assertEqual(added, [])

    def test_missing_source_objects_create_capabilities_without_overriding_existing_native_data(self):
        parts, data, model, analyzer = source_fixture()
        data['layouts'][0]['charts'] = [dict(key='existing')]
        result, added = append_data_layouts(parts, data, model, analyzer)
        self.assertNotIn('chart', [item['kind'] for item in added])
        self.assertIn('table', [item['kind'] for item in added])
        self.assertIn('image', [item['kind'] for item in added])

    def test_unusable_or_one_cell_source_objects_do_not_suppress_supported_new_layouts(self):
        parts, data, model, analyzer = source_fixture()
        data['layouts'].append(dict(data['layouts'][0], id='unavailable', usable=False, charts=[dict(key='unavailable')]))
        data['layouts'][0]['slots'].append(dict(data['layouts'][0]['slots'][1], key='s8_r0_c0', shapeId=8, cell=[0, 0]))
        _, added = append_data_layouts(parts, data, model, analyzer)
        self.assertIn('table', [item['kind'] for item in added])
        self.assertIn('chart', [item['kind'] for item in added])

    def test_malformed_uploaded_extension_is_ignored_without_crashing_or_disabling_data_objects(self):
        for attributes in [dict(kind='table', seriesCount='bad'), dict(kind='unknown'), dict(kind='chart', chartType='xy', seriesCount='6'), dict(kind='text', titleShapeId='2', bodyShapeId='2')]:
            with self.subTest(attributes=attributes):
                parts, data, model, analyzer = source_fixture()
                root = xml(parts['ppt/slides/slide1.xml'])
                extension = etree.SubElement(etree.SubElement(root, '{%s}extLst' % NS['p']), '{%s}ext' % NS['p'], uri=DATA_EXTENSION)
                etree.SubElement(extension, '{%s}dataLayout' % DATA_NAMESPACE, version='1', sourceLayoutId='slide_1', **attributes)
                parts['ppt/slides/slide1.xml'] = etree.tostring(root)
                self.assertEqual(records(parts), [])
                result, added = append_data_layouts(parts, data, model, analyzer)
                self.assertEqual(len(added), 8)
                self.assertEqual(records(result), added)

    def test_protected_recurring_header_is_never_selected_or_rewritten_as_content_title(self):
        parts, data, model, analyzer = source_fixture()
        analyzer['slide_assignments'][0]['role_assignments'].append(dict(source_level='slide', source_open_xml_shape_id=2, role='header'))
        result, added = append_data_layouts(parts, data, model, analyzer)
        self.assertEqual(added, [])
        self.assertIs(result, parts)

    def test_title_expansion_never_ignores_a_protected_horizontal_strip(self):
        parts, data, model, analyzer = source_fixture()
        model['slides'][0]['objects'][2]['geometry'] = dict(x_emu=500*12700, y_emu=85*12700, width_emu=420*12700, height_emu=4*12700)
        result, added = append_data_layouts(parts, data, model, analyzer)
        original = xml(parts['ppt/slides/slide1.xml']).find('.//p:sp/p:spPr/a:xfrm', NS)
        for derivative in added:
            title = xml(result[derivative['part']]).find('.//p:sp/p:spPr/a:xfrm', NS)
            if derivative['kind'] == 'text':
                self.assertGreaterEqual(int(title.find('a:off', NS).get('y'))/12700, 89)
            else:
                self.assertEqual(etree.tostring(title), etree.tostring(original))

    def test_compact_free_area_reduces_sample_table_rows_instead_of_rejecting_import(self):
        parts, data, model, analyzer = source_fixture()
        data.update(width=720, height=405)
        model['slides'][0]['objects'][2]['geometry'] = dict(x_emu=0, y_emu=270*12700, width_emu=720*12700, height_emu=100*12700)
        result, added = append_data_layouts(parts, data, model, analyzer)
        table = next(item for item in added if item['kind'] == 'table')
        rows = xml(result[table['part']]).findall('.//a:tbl/a:tr', NS)
        self.assertGreaterEqual(len(rows), 2)
        self.assertLess(len(rows), 4)

    def test_owned_text_canvas_has_separate_readable_native_title_and_body(self):
        parts, data, model, analyzer = source_fixture()
        result, added = append_data_layouts(parts, data, model, analyzer)
        text = next(item for item in added if item['kind'] == 'text')
        root = xml(result[text['part']])
        identities = text_frame_ids(root)
        self.assertEqual(identities, dict(title=text['titleShapeId'], body=text['bodyShapeId']))
        title = root.xpath('.//p:sp[p:nvSpPr/p:cNvPr/@id=$id]', namespaces=NS, id=str(identities['title']))[0]
        body = root.xpath('.//p:sp[p:nvSpPr/p:cNvPr/@id=$id]', namespaces=NS, id=str(identities['body']))[0]
        region = body.find('p:spPr/a:xfrm', NS)
        offset, extent = region.find('a:off', NS), region.find('a:ext', NS)
        title_region = title.find('p:spPr/a:xfrm', NS)
        title_offset, title_extent = title_region.find('a:off', NS), title_region.find('a:ext', NS)
        self.assertGreaterEqual(int(offset.get('y')), int(title_offset.get('y'))+int(title_extent.get('cy')))
        self.assertGreater(int(extent.get('cx')), data['width']*12700*.5)
        self.assertGreater(int(extent.get('cy')), data['height']*12700*.3)
        self.assertEqual(int(body.find('.//a:rPr', NS).get('sz')), 2400)
        self.assertEqual(int(title.find('.//a:rPr', NS).get('sz')), 3000)
        self.assertGreaterEqual(int(title_extent.get('cy'))/12700, 30*2.4, 'readable title reserves at least two native lines')
        self.assertEqual(title.find('p:txBody/a:bodyPr', NS).get('wrap'), 'square')
        self.assertFalse(body.findall('.//p:ph', NS), 'ordinary source-derived text must render without layout placeholder inheritance')
        self.assertEqual(text_frame_ids(root), identities)
        self.assertEqual(parts['ppt/slides/slide1.xml'], source_fixture()[0]['ppt/slides/slide1.xml'])

    def test_charts_are_editable_and_preserve_small_values_negative_xy_and_long_independent_series(self):
        for kind in ('bar', 'line', 'xy'):
            for count in (1, 2, 6):
                with self.subTest(kind=kind, series=count):
                    slide, rels, types = roots()
                    parts = {}
                    part = add_data_chart(slide.find('p:cSld/p:spTree', NS), 10, BOX, STYLE, parts, rels, types, kind+str(count), kind, count)
                    spec = chart_spec(SimpleNamespace(media_id=part, shape_id=10), parts)
                    self.assertEqual(spec['seriesCount'], count)
                    self.assertEqual(spec['dataKind'], 'xy' if kind == 'xy' else 'category')
                    self.assertTrue(any(name.endswith('.xlsx') for name in parts))
                    if kind == 'xy':
                        value = dict(kind='xy', title='Measured error', series=[dict(name='Series '+str(i), points=[dict(x=n-15+i*.1, y=(-1 if i % 2 else 1)*.004429+n*.000001) for n in range(31+i)]) for i in range(count)])
                    else:
                        value = dict(title='RMSE', categories=['A', 'B'], series=[dict(name='Series '+str(i), values=[.004429, .009559]) for i in range(count)])
                    validate_charts(dict(charts=[spec]), dict(charts={spec['key']: value}))
                    result = dict(parts)
                    fill_chart(spec, value, parts, result, slide, rels, 0, types)
                    output = xml(result['ppt/charts/nerpaChart1_10.xml'])
                    self.assertEqual(len(output.findall('.//c:ser', NS)), count)
                    self.assertFalse(output.findall('.//c:scaling/c:max', NS))
                    self.assertTrue(all(node.text == 'General' for node in output.findall('.//c:formatCode', NS)))
                    if kind == 'xy':
                        for i, series in enumerate(output.findall('.//c:ser', NS)):
                            self.assertEqual(len(series.findall('c:yVal/c:numRef/c:numCache/c:pt', NS)), 31+i)
                    else:
                        self.assertIn('0.004429', output.xpath('.//c:val//c:v/text()', namespaces=NS))
                        self.assertIn('0.009559', output.xpath('.//c:val//c:v/text()', namespaces=NS))

if __name__ == '__main__':
    unittest.main()
