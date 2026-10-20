import unittest
from lxml import etree
from runtime.security import NS,xml
from runtime.source_art import compile_source_art,detach_source_art,source_art_markup
from runtime.html_deck import clear_inherited_samples,empty_picture_ids
from runtime.page_numbers import pagination_shape_ids

class SourceArtTest(unittest.TestCase):
    def shape(self,identity=7,geom='rect',fill='FFFFFF',text='OLD SAMPLE'):
        return f'<p:sp><p:nvSpPr><p:cNvPr id="{identity}"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="127000" y="254000"/><a:ext cx="2540000" cy="1270000"/></a:xfrm><a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln w="12700"><a:solidFill><a:srgbClr val="246569"/></a:solidFill></a:ln></p:spPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    def root(self,content):return xml(f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree>{content}</p:spTree></p:cSld></p:sld>'.encode())
    def test_native_panels_and_lines_are_separate_svg_nodes_without_old_copy(self):
        root=self.root(self.shape()+self.shape(8,'line',text=''))
        art=compile_source_art(root,{},dict(width=720,height=405),{})
        self.assertEqual([o['shapeId'] for o in art['objects']],[7,8]);self.assertFalse(art['unsupported'])
        markup=source_art_markup(dict(canvasWidth=720,canvasHeight=405,sourceHtml=dict(nativeArt=art)))
        self.assertIn('data-source-object="7"',markup);self.assertIn('<line',markup);self.assertNotIn('ns0:',markup);self.assertNotIn('OLD SAMPLE',markup)
        detach_source_art(root,art);self.assertFalse(root.xpath('.//p:sp',namespaces=NS))
    def test_explicit_none_arrow_ends_are_an_ordinary_editable_border(self):
        root=self.root(self.shape());line=root.find('.//a:ln',NS)
        for end in ('headEnd','tailEnd'):etree.SubElement(line,'{%s}%s'%(NS['a'],end),type='none')
        art=compile_source_art(root,{},dict(width=720,height=405),{})
        self.assertEqual([s['shapeId'] for s in art['objects']],[7]);self.assertFalse(art['unsupported'])
        line.find('a:tailEnd',NS).set('type','triangle')
        self.assertEqual(compile_source_art(root,{},dict(width=720,height=405),{})['unsupported'][0]['feature'],'source_arrow_marker')
    def test_native_header_cannot_be_repainted_over_a_later_logo_in_the_html_underlay(self):
        root=self.root(self.shape(7,fill='001F82',text='')+'<p:pic><p:nvPicPr><p:cNvPr id="8"/></p:nvPicPr><p:spPr><a:xfrm><a:off x="1270000" y="254000"/><a:ext cx="1270000" cy="508000"/></a:xfrm></p:spPr></p:pic>')
        art=compile_source_art(root,{},dict(width=720,height=405),{})
        self.assertFalse(art['objects']);self.assertEqual(art['unsupported'][0]['feature'],'source_paint_below_picture')
        detach_source_art(root,art)
        self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['7','8'],'HTML underlay retains original paint order; PowerPoint keeps both native objects')
    def test_native_card_stays_below_an_icon_inside_a_later_group(self):
        root=self.root(self.shape(7,fill='212121',text='')+'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="9"/></p:nvGrpSpPr><p:grpSpPr/><p:pic><p:nvPicPr><p:cNvPr id="8"/></p:nvPicPr></p:pic></p:grpSp>')
        layout=dict(sourceObjects=[dict(shapeId=9,box=dict(x=40,y=30,w=50,h=50))])
        art=compile_source_art(root,layout,dict(width=720,height=405),{})
        self.assertNotIn(7,[item['shapeId'] for item in art['objects']])
        self.assertIn('source_paint_below_picture',[item['feature'] for item in art['unsupported']])
        detach_source_art(root,art);self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['7','9','8'])
    def test_static_brand_words_are_not_detached_with_paint_or_covered_by_repainted_header(self):
        root=self.root(self.shape(7,fill='001F82',text='')+self.shape(8,text='NOVA LAB'))
        art=compile_source_art(root,dict(htmlPreserveShapeIds=[8]),dict(width=720,height=405),{})
        self.assertFalse(art['objects']);detach_source_art(root,art)
        self.assertIn('NOVA LAB',root.xpath('.//a:t/text()',namespaces=NS))
    def test_group_cleanup_keeps_a_protected_wordmark_but_removes_neighbouring_sample_words(self):
        from runtime.html_deck import clear_content
        root=self.root('<p:grpSp><p:nvGrpSpPr><p:cNvPr id="100"/></p:nvGrpSpPr><p:grpSpPr/>'+self.shape(7,text='NOVA LAB')+self.shape(8,text='OLD SAMPLE')+'</p:grpSp>')
        clear_content(root,dict(slots=[dict(shapeId=7,role='brand'),dict(shapeId=8,role='body')]))
        words=root.xpath('.//a:t/text()',namespaces=NS)
        self.assertIn('NOVA LAB',words);self.assertNotIn('OLD SAMPLE',words)
    def test_unsupported_geometry_keeps_native_object_and_reports_the_html_limitation(self):
        root=self.root(self.shape(9,'cloud'))
        art=compile_source_art(root,{},dict(width=720,height=405),{})
        self.assertFalse(art['objects']);self.assertEqual(art['unsupported'][0]['shapeId'],9)
        detach_source_art(root,art);self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['9'])
    def test_local_source_edit_also_removes_a_nested_svg_shape_without_dropping_its_peers(self):
        art=dict(objects=[dict(shapeId=16,svg=f'<g xmlns="http://www.w3.org/2000/svg" data-source-object="16"><g data-source-object="17"><rect width="4" height="4"/></g><g data-source-object="18"><rect width="5" height="5"/></g></g>')])
        markup=source_art_markup(dict(canvasWidth=720,canvasHeight=405,sourceHtml=dict(nativeArt=art)),dict(sourceShapeEdits=[dict(shapeId=17,action='remove')]))
        self.assertNotIn('data-source-object="17"',markup);self.assertIn('data-source-object="18"',markup)
    def test_clearing_words_preserves_an_inherited_white_panel_with_implicit_rectangle_geometry(self):
        root=self.root(self.shape());props=root.find('.//p:sp/p:spPr',NS);props.remove(props.find('a:prstGeom',NS))
        parts={'ppt/slideLayouts/slideLayout1.xml':etree.tostring(root)};clear_inherited_samples(parts)
        actual=xml(parts['ppt/slideLayouts/slideLayout1.xml'])
        self.assertIsNotNone(actual.find('.//p:sp/p:spPr/a:prstGeom',NS));self.assertFalse(actual.xpath('.//a:t/text()',namespaces=NS))
    def test_stroke_color_never_becomes_a_transparent_shape_fill(self):
        from app.presentation.parser.colors import resolve_solid_fill,resolve_line
        root=self.root(self.shape());props=root.find('.//p:sp/p:spPr',NS);props.remove(props.find('a:solidFill',NS))
        self.assertIsNone(resolve_solid_fill(props,{}).value);self.assertEqual(resolve_line(props,{})[0].value,'#246569')
    def test_inherited_paint_is_materialized_on_the_actual_slide_placeholder(self):
        from runtime.source_inheritance import materialize_placeholder_paint
        layout=self.root(self.shape());shape=layout.find('.//p:sp',NS);props=shape.find('p:spPr',NS);props.remove(props.find('a:prstGeom',NS))
        ph=etree.SubElement(etree.SubElement(shape.find('p:nvSpPr',NS),'{%s}nvPr'%NS['p']),'{%s}ph'%NS['p'],type='body',idx='22')
        slide=self.root(self.shape());local=slide.find('.//p:sp',NS);local.remove(local.find('p:spPr',NS));etree.SubElement(local,'{%s}spPr'%NS['p'])
        etree.SubElement(etree.SubElement(local.find('p:nvSpPr',NS),'{%s}nvPr'%NS['p']),'{%s}ph'%NS['p'],type='body',idx='22')
        parts={'ppt/slides/slide1.xml':etree.tostring(slide),'ppt/slideLayouts/slideLayout1.xml':etree.tostring(layout),'ppt/slides/_rels/slide1.xml.rels':b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>'}
        materialize_placeholder_paint(parts);actual=xml(parts['ppt/slides/slide1.xml'])
        self.assertIsNotNone(actual.find('.//p:sp/p:spPr/a:solidFill',NS));self.assertIsNotNone(actual.find('.//p:sp/p:spPr/a:prstGeom',NS));self.assertIsNotNone(actual.find('.//p:sp/p:spPr/a:xfrm',NS))
        self.assertEqual([etree.QName(n).localname for n in actual.find('.//p:sp/p:spPr',NS)],['xfrm','prstGeom','solidFill','ln'])
    def test_empty_pagination_fields_cannot_regenerate_an_old_number_in_the_background(self):
        from runtime.html_deck import clear_content
        root=self.root(self.shape(text='6'));body=root.find('.//p:txBody/a:p',NS)
        field=etree.SubElement(body,'{%s}fld'%NS['a'],type='slidenum');etree.SubElement(field,'{%s}t'%NS['a']).text='6'
        clear_content(root,dict(slots=[dict(shapeId=7,role='page_number')]))
        self.assertFalse(root.findall('.//a:fld',NS));self.assertFalse([v for v in root.xpath('.//a:t/text()',namespaces=NS) if v])
    def test_cleared_filled_placeholder_remains_visible_native_art(self):
        from runtime.html_deck import clear_content
        root=self.root(self.shape());shape=root.find('.//p:sp',NS)
        etree.SubElement(etree.SubElement(shape.find('p:nvSpPr',NS),'{%s}nvPr'%NS['p']),'{%s}ph'%NS['p'],type='body',idx='22')
        clear_content(root,dict(slots=[]))
        self.assertIsNone(shape.find('p:nvSpPr/p:nvPr/p:ph',NS));self.assertIsNotNone(shape.find('p:spPr/a:solidFill',NS))
    def test_only_layout_authoring_picture_controls_are_removed_not_real_white_panels(self):
        root=self.root(self.shape()+self.shape(8));shape=root.find('.//p:sp',NS)
        etree.SubElement(etree.SubElement(shape.find('p:nvSpPr',NS),'{%s}nvPr'%NS['p']),'{%s}ph'%NS['p'],type='pic',idx='4')
        parts={'ppt/slideLayouts/slideLayout1.xml':etree.tostring(root)};clear_inherited_samples(parts)
        self.assertEqual(xml(parts['ppt/slideLayouts/slideLayout1.xml']).xpath('.//p:cNvPr/@id',namespaces=NS),['8'])
    def test_split_old_mockup_removes_frame_screen_and_sample_mark_but_never_institution_branding(self):
        root=self.root('');layout=dict(part='ppt/slides/slide1.xml',imageSlots=[dict(shapeId=18,box=dict(x=60,y=40,w=50,h=30))],
          sourceObjects=[dict(shapeId=17,kind='picture',canRemove=True,role='photo',box=dict(x=50,y=20,w=90,h=70)),
                         dict(shapeId=19,kind='picture',canRemove=True,role='photo',box=dict(x=70,y=50,w=20,h=10)),
                         dict(shapeId=20,kind='picture',canRemove=True,role='logo',box=dict(x=70,y=50,w=20,h=10))])
        self.assertEqual(empty_picture_ids({layout['part']:etree.tostring(root)},layout),{17,18,19})
    def test_an_ordinary_small_footer_number_is_detected_even_when_analyzer_called_it_footer(self):
        root=self.root(self.shape(text='6'));shape=root.find('.//p:sp',NS)
        shape.find('p:spPr/a:xfrm/a:off',NS).set('y',str(490*12700))
        run=shape.find('p:txBody/a:p/a:r',NS);etree.SubElement(run,'{%s}rPr'%NS['a'],sz='1000')
        self.assertEqual(pagination_shape_ids(root,960,540,6),{7})
    def test_original_document_image_cannot_disappear_when_the_model_omits_its_html_marker(self):
        from runtime.html_author import author_scene
        style=dict(id='test',font='Arial',size=18,headingFont='Arial',headingSize=24,titleColor='#202020',ink='#202020',title=dict(x=20,y=20,w=600,h=50),body=dict(x=20,y=100,w=600,h=250),pictures=[])
        copy=dict(title='Graph',html='<main><h1 data-text="title"></h1></main>',css='',paragraphs=[],cards=[],steps=[],metrics=[],takeaway='')
        images=[dict(image='original.png',x=350,y=120,w=250,h=180,source=dict(kind='source-document',required=True)),dict(image='optional.png',x=40,y=120,w=200,h=150)]
        result=author_scene(copy,style,0,images)
        self.assertEqual([image['image'] for image in result['images']],['original.png'])
        self.assertIn('data-image="0"',result['authored']['html'])
        self.assertIn('html_source_image_restored',[w['reason'] for w in result['warnings']])
        from runtime.html_author import author_fragment
        markup,_=author_fragment(result,style,lambda *_:'')
        self.assertIn('background-color:#FFFFFF!important',markup)
    def test_dense_original_plot_is_measured_by_visible_content_not_its_large_letterbox(self):
        from runtime.html_author import source_layout_warnings
        scene=dict(index=0,texts=[],images=[dict(x=0,y=100,w=900,h=200,contentBox=dict(x=300,y=100,w=300,h=200),source=dict(required=True,figureKind='chart',labelCount=40))],sourceDesign={})
        self.assertIn('html_source_figure_too_small',[w['reason'] for w in source_layout_warnings(scene,960,540)])
        scene['images'][0]['contentBox'].update(w=720,h=430)
        self.assertNotIn('html_source_figure_too_small',[w['reason'] for w in source_layout_warnings(scene,960,540)])
    def test_moving_a_source_visuals_explanation_into_only_the_left_column_is_a_regression(self):
        from runtime.html_author import source_layout_warnings
        from runtime.html_repair_acceptance import repair_score
        texts=[dict(key='h_p_'+str(i),text='Supported fact',x=40,y=110+i*35,w=250,h=25,size=16) for i in range(4)]
        scene=dict(index=0,texts=texts,sourceDesign=dict(dataFrames=[dict(shapeId=12,kind='chart',box=dict(x=400,y=100,w=280,h=240))]))
        issues=source_layout_warnings(scene,720,405)
        self.assertIn('html_source_visual_abandoned',[w['reason'] for w in issues]);self.assertGreater(repair_score(issues,1),20)
        texts[-1].update(x=420,y=160,w=200)
        self.assertNotIn('html_source_visual_abandoned',[w['reason'] for w in source_layout_warnings(scene,720,405)])
    def test_a_repair_cannot_remove_most_of_a_usable_numbered_diagram_to_fit_its_prose(self):
        from runtime.html_author import source_layout_warnings
        rows=[dict(numberShapeId=i*2,textShapeId=i*2+1,ordinal=i+1,box=dict(x=10,y=80+i*40,w=300,h=30)) for i in range(5)]
        scene=dict(index=0,texts=[dict(key='h_p_'+str(i),text='Fact',x=30,y=90+i*40,w=200,h=20,size=16) for i in range(5)],
            sourceDesign=dict(sourceHtml=dict(numberedRows=rows)),sourceShapeEdits=[dict(shapeId=r['textShapeId'],action='remove') for r in rows])
        self.assertIn('html_source_structure_removed',[w['reason'] for w in source_layout_warnings(scene,720,405)])

if __name__=='__main__':unittest.main()
