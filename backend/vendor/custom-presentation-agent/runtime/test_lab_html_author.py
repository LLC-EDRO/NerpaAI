import json,shutil,tempfile,time,unittest
from pathlib import Path
from PIL import Image
from runtime.html_deck import describe_layout,compose_slide,html_document,browser_render
from runtime.html_author import author_fragment,safe_css,author_contrast_warnings,source_layout_warnings,repair_author_contrast

class HtmlAuthorTest(unittest.TestCase):
    def test_missing_code_preserves_every_fact_in_identified_html_recovery(self):
        copy=self.copy();copy.pop('html',None);copy['paragraphs']=['RMSE = 0,004429; только учебная выборка.','Период 2023–2026, единица — кг.']
        scene=compose_slide(copy,self.style(),0,[])
        self.assertEqual(scene['authored']['source'],'source-frame-recovery')
        self.assertEqual(scene['warnings'][0]['reason'],'html_author_recovered')
        self.assertNotIn('flow',scene)
        self.assertEqual([item['text'] for item in scene['texts'] if item['key'].startswith('h_p_')],copy['paragraphs'])
        self.assertTrue(all('data-text="paragraphs.%d"'%i in scene['authored']['html'] for i in range(2)))

    def test_replacement_without_new_surface_keeps_authored_content_and_removes_original(self):
        copy=self.copy();copy.update(sourceShapeEdits=[dict(shapeId=12,action='replace')],
            sourceDesign=dict(textAnchors=[],editableShapes=[dict(shapeId=12,fill='#001F82')]))
        scene=compose_slide(copy,self.style(),0,[])
        self.assertEqual(scene['sourceShapeEdits'],[dict(shapeId=12,action='remove')])
        self.assertNotEqual(scene['authored'].get('source'),'source-frame-recovery')
        self.assertEqual(scene['warnings'][0]['reason'],'html_source_shape_removed')

    def test_replacement_surface_on_bound_text_retains_validated_original_fill(self):
        copy=self.copy();copy.update(paragraphs=['Explanation'],sourceShapeEdits=[dict(shapeId=12,action='replace')],
            sourceDesign=dict(textAnchors=[dict(shapeId=12)],editableShapes=[dict(shapeId=12,fill='#001F82')]),
            html='<main><h1 data-text="title"></h1><p data-source-shape="12" data-source-surface="12" data-text="paragraphs.0"></p></main>')
        scene=compose_slide(copy,self.style(),0,[]);markup,_=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('data-source-surface="12"',markup)
        self.assertIn('--source-fill:#001F82!important',markup)
        self.assertNotEqual(scene['authored'].get('source'),'source-frame-recovery')

    def test_empty_retained_host_is_a_repair_but_explicit_shape_modernization_is_allowed(self):
        host=dict(shapeId=12,box=dict(x=40,y=90,w=280,h=120),container=dict(role='content',box=dict(x=40,y=90,w=280,h=120)))
        item=dict(key='h_p_0',text='A detached label',x=40,y=240,w=280,h=30,sourceShapeId=12)
        scene=dict(index=0,texts=[item],sourceDesign=dict(textAnchors=[host]))
        self.assertEqual({w['reason'] for w in source_layout_warnings(scene,720,405)}, {'html_source_container_empty','html_source_container_drift'})
        scene['sourceShapeEdits']=[dict(shapeId=12,action='replace')]
        self.assertFalse(source_layout_warnings(scene,720,405))
        scene['sourceShapeEdits']=[];item['y']=120
        self.assertFalse(source_layout_warnings(scene,720,405))

    def test_card_edge_tolerance_cannot_hide_padding_loss_or_partial_overflow(self):
        outer=dict(x=40,y=90,w=280,h=120);inner=dict(x=58,y=108,w=244,h=84)
        host=dict(shapeId=12,box=outer,container=dict(role='content',box=outer,innerBox=inner))
        item=dict(key='h_p_0',text='Complete explanation',x=42,y=111,w=220,h=40,sourceShapeId=12,inkRects=[dict(x=42,y=111,w=220,h=24)])
        scene=dict(index=0,texts=[item],sourceDesign=dict(textAnchors=[host]))
        self.assertIn('html_source_padding',{w['reason'] for w in source_layout_warnings(scene,720,405)})
        item['inkRects']=[dict(x=60,y=111,w=220,h=24)];self.assertFalse(source_layout_warnings(scene,720,405))
        item['inkRects']=[dict(x=60,y=111,w=265,h=24)]
        self.assertIn('html_source_container_drift',{w['reason'] for w in source_layout_warnings(scene,720,405)})

    def test_source_backed_replacement_uses_original_fill_and_inherits_text_identity(self):
        copy=self.copy();copy.update(paragraphs=['Supported explanation'],sourceShapeEdits=[dict(shapeId=12,action='replace')],
            sourceDesign=dict(textAnchors=[dict(shapeId=12)],editableShapes=[dict(shapeId=12,fill='#001F82')]),
            html='<main><h1 data-text="title"></h1><section data-source-shape="12" data-source-surface="12"><p data-text="paragraphs.0"></p></section></main>',
            css='section{border-radius:14px;color:white}')
        scene=compose_slide(copy,self.style(),0,[]);markup,_=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('--source-fill:#001F82!important',markup)
        self.assertEqual(next(t for t in scene['texts'] if t['key']=='h_p_0')['sourceShapeId'],12)
        scene['authored']['html']=scene['authored']['html'].replace('data-source-surface="12"','')
        with self.assertRaisesRegex(ValueError,'missing_source_surface'):author_fragment(scene,self.style(),lambda *_:'')
    def test_source_host_selector_is_unique_while_nested_bindings_keep_native_ownership(self):
        from lxml import html
        copy=self.copy();copy.update(paragraphs=['Complete explanation.'],sourceDesign=dict(textAnchors=[dict(shapeId=12)]),
            html='<main><h1 data-text="title"></h1><section data-source-shape="12"><p data-text="paragraphs.0"></p></section></main>',
            css='[data-source-shape="12"]{padding:20px;height:120px;width:320px}')
        scene=compose_slide(copy,self.style(),0,[]);markup,_=author_fragment(scene,self.style(),lambda *_:'');root=html.fromstring(markup)
        self.assertEqual(len(root.xpath('.//*[@data-source-shape="12"]')),1,'CSS patch must style the host only')
        self.assertEqual(next(t for t in scene['texts'] if t['key']=='h_p_0')['sourceShapeId'],12)
    def test_trusted_structural_badges_keep_editable_zero_padded_numbers(self):
        copy=self.copy();copy['html']+='<span data-number="1" data-source-shape="12"></span>'
        style=self.style();style['sourceHtml']=dict(structuralOrdinals=[dict(shapeId=12,ordinal=1,digits=2),dict(shapeId=13,ordinal=2,digits=2),dict(shapeId=14,ordinal=3,digits=2)],textRegions=[dict(shapeId=12)])
        scene=compose_slide(copy,style,0,[]);markup,_=author_fragment(scene,style,lambda *_:'')
        self.assertEqual(next(t for t in scene['texts'] if t['key']=='h_list_number_1')['text'],'01');self.assertIn('01</span>',markup)
    def test_direct_source_binding_retains_its_role_selector_for_local_css_repairs(self):
        from lxml import html
        copy=self.copy();copy.update(paragraphs=['Complete explanation.'],sourceDesign=dict(textAnchors=[dict(shapeId=12)]),
            html='<main><h1 data-text="title"></h1><p data-source-shape="12" data-source-role="label" data-text="paragraphs.0"></p></main>',css='[data-source-role="label"]{padding:20px;font-size:22px}')
        scene=compose_slide(copy,self.style(),0,[]);markup,_=author_fragment(scene,self.style(),lambda *_:'');root=html.fromstring(markup)
        self.assertEqual(len(root.xpath('.//*[@data-key="h_p_0" and @data-source-role="label"]')),1)
    def test_readable_original_white_on_red_is_not_repainted_black(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'red.png';Image.new('RGB',(400,160),'#EA2905').save(path)
            item=dict(key='h_card_0_body',text='Краткое пояснение',x=20,y=20,w=320,h=80,size=14,color='#FFFFFF',sourceShapeId=35)
            scene=dict(index=0,texts=[item],sourceDesign=dict(textAnchors=[dict(shapeId=35,color='#FFFFFF',box=dict(x=20,y=20,w=320,h=80),size=14)]))
            self.assertFalse(repair_author_contrast(scene,path,400,160,{}));self.assertEqual(item['color'],'#FFFFFF')
            # Source identity does not excuse genuinely invisible white-on-white.
            Image.new('RGB',(400,160),'white').save(path)
            self.assertTrue(repair_author_contrast(scene,path,400,160,{}));self.assertNotEqual(item['color'],'#FFFFFF')
    def test_flex_cover_copy_wraps_inside_its_existing_panel(self):
        if not shutil.which('chromium'):self.skipTest('Chromium required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'out';out.mkdir();style=self.style();style['background']='art.png'
            Image.new('RGB',(720,405),'white').save(root/'art.png')
            copy=self.copy();copy.update(paragraphs=['Прогнозы Банка России и Минэкономразвития'],html='<main><div class="heading"><h1 data-text="title"></h1></div><div class="caption"><p data-text="paragraphs.0"></p></div></main>',
                title='Как Россия переживёт экономический кризис 2026 года',css='main{position:relative;width:100%;height:100%}.heading,.caption{position:absolute;left:350pt;width:300pt;display:flex;align-items:center;justify-content:flex-end;text-align:right}.heading{top:100pt;height:130pt}.heading h1{font-size:48pt}.caption{top:250pt;height:65pt}.caption p{font-size:20pt}')
            scene=compose_slide(copy,style,0,[])
            browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            for item in scene['texts']:
                self.assertGreaterEqual(item['x'],349);self.assertLessEqual(item['x']+item['w'],651)
            title=next(item for item in scene['texts'] if item['key']=='h_title');caption=next(item for item in scene['texts'] if item['key']=='h_p_0')
            self.assertLessEqual(title['y']+title['h'],caption['y']+1)
    def test_multislide_previews_match_complete_html_pdf_including_lower_rows(self):
        if not shutil.which('chromium'):self.skipTest('Chromium required')
        import pymupdf
        from PIL import ImageChops
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'out';out.mkdir();style=self.style();style['background']='art.png'
            Image.new('RGB',(720,405),'white').save(root/'art.png')
            copy=self.copy();copy.update(paragraphs=['Верхняя строка','Нижняя строка'],
                html='<main><h1 data-text="title"></h1><p class="top" data-text="paragraphs.0"></p><p class="bottom" data-text="paragraphs.1"></p></main>',
                css='main{position:relative;width:100%;height:100%;color:#123456}h1{position:absolute;top:30pt;left:40pt;font-size:28pt}.top{position:absolute;top:110pt;left:40pt;font-size:22pt}.bottom{position:absolute;top:330pt;left:40pt;font-size:22pt}')
            scenes=[compose_slide(copy,style,i,[]) for i in range(4)]
            browser_render(scenes,dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            with pymupdf.open(out/'html-preview.pdf') as pdf:
                self.assertEqual(len(pdf),4)
                for i,page in enumerate(pdf):
                    pix=page.get_pixmap(matrix=pymupdf.Matrix(1280/page.rect.width,1280/page.rect.width),alpha=False)
                    expected=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    actual=Image.open(out/f'slide-{i}.png').convert('RGB')
                    self.assertIsNone(ImageChops.difference(actual,expected).getbbox())
                    self.assertLess(min(actual.crop((40,580,850,670)).convert('L').getdata()),150,'Lower row must be visibly painted')
    def test_numbered_group_keeps_its_bound_heading_and_explanation(self):
        copy=self.copy();copy.update(paragraphs=[],cards=[dict(title='Проверка',body='Подтверждённое пояснение')],
            html='<main><h1 data-text="title"></h1><ol><li class="row" data-number="1"><h2 data-text="cards.0.title"></h2><p data-text="cards.0.body"></p></li></ol></main>',
            css='.row:before{content:attr(data-number);position:absolute;left:-30px}')
        scene=compose_slide(copy,self.style(),0,[]);markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('Подтверждённое пояснение',markup);self.assertIn('Проверка',markup)
        self.assertIn('nerpa-list-number',markup);self.assertIn('.row > .nerpa-list-number',css)
        self.assertNotIn('content:',css)
    def test_last_line_leaving_a_source_panel_is_reported_even_when_its_leaf_box_fits(self):
        lines=[dict(x=40,y=y,w=200,h=18) for y in [50,75,100,125]]
        scene=dict(index=0,texts=[dict(key='h_card_0_body',text='Four lines',x=40,y=50,w=200,h=100,inkRects=lines)],
            sourceDesign=dict(textAnchors=[],availableSurfaces=[dict(x=20,y=20,w=400,h=100)]))
        self.assertEqual(source_layout_warnings(scene,960,540)[0]['reason'],'html_native_bounds')
        scene['sourceDesign']['availableSurfaces'][0]['h']=150
        self.assertFalse(source_layout_warnings(scene,960,540))
    def test_reviewer_knows_that_an_original_patterned_text_frame_is_already_bad(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'art.png';image=Image.new('RGB',(400,160),'white');draw=ImageDraw.Draw(image)
            for x in range(0,200,32):draw.rectangle((x,0,x+16,160),fill='#FA4808')
            image.save(path)
            scene=dict(index=0,texts=[],sourceDesign=dict(textAnchors=[dict(shapeId=7,box=dict(x=0,y=0,w=180,h=120),size=16),
                dict(shapeId=8,box=dict(x=220,y=20,w=160,h=100),size=16)]))
            self.assertFalse(author_contrast_warnings(scene,path,400,160))
            self.assertEqual([a['shapeId'] for a in scene['sourceDesign']['unsafeTextAnchors']],[7])
    def test_empty_textbox_height_does_not_create_a_false_label_collision(self):
        scene=dict(index=0,texts=[dict(key='h_card_0_title',text='Heading',x=40,y=60,w=300,h=100,
            inkRects=[dict(x=40,y=60,w=100,h=20)]),dict(key='h_card_0_body',text='Explanation',x=40,y=100,w=300,h=80,
            inkRects=[dict(x=40,y=100,w=200,h=20)])],sourceDesign={})
        self.assertFalse(source_layout_warnings(scene,960,540))
        scene['texts'][1]['inkRects'][0]['y']=70
        self.assertEqual(source_layout_warnings(scene,960,540)[0]['reason'],'html_text_overlap')
    def test_flat_source_panel_and_its_number_badge_are_valid_text_hosts(self):
        scene=dict(index=0,texts=[dict(key='h_card_0_body',text='Explanation',x=40,y=60,w=300,h=60),
            dict(key='h_list_number_1',text='1',x=450,y=80,w=60,h=40)],sourceDesign=dict(textAnchors=[],
            availableSurfaces=[dict(x=20,y=20,w=380,h=180)],artwork=[dict(role='unknown',box=dict(x=0,y=0,w=700,h=230)),
                dict(role='container',box=dict(x=445,y=75,w=70,h=70))]))
        # The number overlaps the broad panel too, which is not in a measured
        # safe region; place the panel under only the actual prose surface.
        scene['sourceDesign']['artwork'][0]['box']['w']=400
        self.assertFalse(source_layout_warnings(scene,960,540))
    def test_unpositioned_first_repeated_group_is_reported_at_canvas_edge(self):
        item=dict(key='h_card_0_title',text='First agenda row',x=150,y=0,w=400,h=24,inkRects=[dict(x=150,y=0,w=200,h=20)])
        scene=dict(index=0,texts=[item],sourceDesign=dict(textAnchors=[dict(box=dict(x=150,y=200,w=400,h=80))]))
        self.assertEqual(source_layout_warnings(scene,960,540)[0]['reason'],'html_native_bounds')
        item.update(y=200,inkRects=[dict(x=150,y=200,w=200,h=20)])
        self.assertFalse(source_layout_warnings(scene,960,540))
    def test_css_structural_counters_keep_numbered_source_rows_without_unbound_copy(self):
        css='li:before{content:counter(item,decimal-leading-zero) \\".\\";position:absolute}'
        self.assertIn('content:counter(item,decimal-leading-zero) ".";',safe_css(css))
        for value in ['li:before{content:counter(item) "9000"}', 'p:before{content:attr(data-text)}']:
            with self.assertRaises(ValueError):safe_css(value)
        self.assertNotIn('unverified copy',safe_css('p:before{content:"unverified copy"}'))
    def test_empty_pseudo_content_disables_only_decoration_and_keeps_authored_columns(self):
        copy=self.copy();copy['css']+=".columns:before{content:'';border-top:2pt solid red}"
        scene=compose_slide(copy,self.style(),0,[])
        self.assertIn('authored',scene);markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertNotIn('content:',css);self.assertIn('grid-template-columns',css)
        self.assertNotIn('unbound sample data',safe_css('p:before{content:"unbound sample data"}'))

    def test_structural_numbers_are_validated_ordinals_and_headings_stay_single(self):
        copy=self.copy();copy.update(paragraphs=[],cards=[dict(title='Условие',body='Подтверждённое объяснение')],
            html='<main><h1 data-text="title"></h1><span class="num" data-number="1"></span><h2 data-text="cards.0.title"></h2><p data-text="cards.0.body"></p></main>')
        scene=compose_slide(copy,self.style(),0,[]);self.assertIn('authored',scene)
        for _ in range(2):markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertEqual(markup.count('Условие'),1);self.assertIn('>1</span>',markup)
        self.assertEqual(len([t for t in scene['texts'] if t['key']=='h_list_number_1']),1)

    def style(self):
        return describe_layout(dict(id='source',index=0,htmlRole='content',slots=[
            dict(shapeId=1,role='title',text='Old title',x=40,y=30,w=640,h=60,font='Arial',size=30,color='#163743'),
            dict(shapeId=2,role='body',text='Old body',x=40,y=120,w=640,h=240,font='Arial',size=22,color='#163743')]),dict(width=720,height=405))
    def copy(self):
        return dict(title='Точный заголовок',paragraphs=['Первый тезис','Второй тезис'],cards=[],steps=[],metrics=[],takeaway='',
            html='<main class="layout"><h1 data-text="title"></h1><div class="columns"><p data-text="paragraphs.0"></p><p data-text="paragraphs.1"></p></div></main>',
            css='.layout{height:100%;padding:30pt 40pt;display:grid;grid-template-rows:65pt 1fr;gap:25pt}.columns{display:grid;grid-template-columns:1fr 1fr;gap:35pt}h1{font-size:30pt}p{font-size:22pt}')
    def test_model_code_owns_composition_without_generated_boxes_or_stripes(self):
        self.assertIn('justify-content',safe_css('main{display:flex;justify-content:center;align-content:start}'))
        scene=compose_slide(self.copy(),self.style(),0,[])
        self.assertIn('authored',scene);self.assertEqual(scene['shapes'],[]);self.assertNotIn('flow',scene)
        markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('Точный заголовок',markup);self.assertIn('grid-template-columns',css);self.assertNotIn('Old body',markup)
    def test_unbound_copy_and_active_content_cannot_enter_the_rendered_slide(self):
        copy=self.copy();copy['html']='<script>danger()</script><p>OLD MATERIAL 999</p>'+copy['html']
        scene=compose_slide(copy,self.style(),0,[]);markup,_=author_fragment(scene,self.style(),lambda *_:'')
        self.assertNotIn('script',markup);self.assertNotIn('danger',markup);self.assertNotIn('999',markup)
        for css in ['@import "https://example.com";','p{background:url(file:///secret)}','p{behavior:evil}']:
            with self.assertRaises(ValueError):safe_css(css)
    def test_bad_code_recovers_only_its_slide_and_never_discards_the_content(self):
        copy=self.copy();copy['html']='<h1 data-text="title"></h1>'
        scene=compose_slide(copy,self.style(),0,[])
        self.assertEqual(scene['authored']['source'],'source-frame-recovery');self.assertEqual(scene['warnings'][0]['reason'],'html_author_recovered')
        self.assertNotIn('flow',scene)
        self.assertIn('Первый тезис',' '.join(t['text'] for t in scene['texts']));self.assertEqual(scene['shapes'],[])
    def test_bad_css_recovers_two_source_fields_without_a_page_wide_preset(self):
        copy=self.copy();copy.update(paragraphs=[],cards=[dict(title='Первое',body='Первое объяснение'),dict(title='Второе',body='Второе объяснение')],css='@import "bad";',sourceDesign=dict(
            title=dict(shapeId=1,box=dict(x=40,y=30,w=640,h=60),size=30),textAnchors=[dict(shapeId=1,role='title',box=dict(x=40,y=30,w=640,h=60)),
            dict(shapeId=2,role='body',box=dict(x=60,y=150,w=200,h=160)),dict(shapeId=3,role='body',box=dict(x=420,y=150,w=200,h=160))]))
        scene=compose_slide(copy,self.style(),0,[])
        self.assertEqual(scene['authored']['source'],'source-frame-recovery');markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('left:60pt',css);self.assertIn('left:420pt',css);self.assertNotIn('flow',scene)
        self.assertIn('Первое объяснение',markup);self.assertIn('Второе объяснение',markup)
    def test_unbound_photographs_cannot_appear_only_in_the_native_export(self):
        photo=lambda value:dict(image=value,x=40,y=120,w=250,h=150)
        copy=self.copy();scene=compose_slide(copy,self.style(),0,[photo('unused')]);self.assertFalse(scene['images'])
        copy['html']+='<img data-image="1">';scene=compose_slide(copy,self.style(),0,[photo('unused'),photo('visible')])
        self.assertEqual([p['image'] for p in scene['images']],['visible']);self.assertIn('data-image="0"',scene['authored']['html'])
    def test_missing_semantic_heading_stays_inside_the_authored_body_frame(self):
        copy=self.copy();copy.update(paragraphs=[],cards=[dict(title='Known heading',body='Exact explanation')],html='<main class="columns"><h1 data-text="title"></h1><p class="original" data-text="cards.0.body"></p></main>')
        scene=compose_slide(copy,self.style(),0,[]);self.assertIn('authored',scene)
        markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('class="original"',markup);self.assertIn('Known heading',markup);self.assertIn('Exact explanation',markup)
        self.assertIn('grid-template-columns',css);self.assertEqual(scene['shapes'],[])
    def test_title_only_design_keeps_model_code_and_moves_subtitle_to_notes(self):
        style=self.style();style['design']=dict(canvas='panels',title=style['title'],content=[],variants=['stack'])
        scene=compose_slide(self.copy(),style,0,[])
        self.assertIn('authored',scene);markup,_=author_fragment(scene,style,lambda *_:'')
        self.assertIn('Точный заголовок',markup);self.assertNotIn('Первый тезис',markup)
        self.assertIn('Первый тезис',scene['notes'])
    def test_optional_empty_binding_does_not_discard_authored_composition(self):
        copy=self.copy();copy['html']+='<p data-text="takeaway"></p>'
        copy['html']+='<article><h2 data-text="cards.3.title"></h2><p data-text="cards.3.body"></p></article><div data-visual="chart"></div>'
        scene=compose_slide(copy,self.style(),0,[])
        self.assertIn('authored',scene)
        markup,_=author_fragment(scene,self.style(),lambda *_:'');self.assertNotIn('data-visual',markup)
        copy['html']+='<p data-text="unknown.0"></p>'
        self.assertEqual(compose_slide(copy,self.style(),0,[])['authored']['source'],'source-frame-recovery')
    def test_unique_model_table_frame_keeps_its_geometry_when_marker_is_omitted(self):
        copy=self.copy();copy['table']=dict(headers=['A','B'],rows=[['1','2']])
        copy['html']+='<div class="tab"></div>';copy['css']+='.tab{position:absolute;left:50pt;top:210pt;width:600pt;height:130pt}'
        scene=compose_slide(copy,self.style(),0,[])
        self.assertIn('authored',scene);markup,css=author_fragment(scene,self.style(),lambda *_:'')
        self.assertIn('data-visual="table"',markup);self.assertIn('left:50pt',css)
        copy['html']+='<div class="tab"></div>'
        self.assertEqual(compose_slide(copy,self.style(),0,[])['authored']['source'],'source-frame-recovery','ambiguous model frames are replaced only inside source fields')
    def test_readability_uses_real_artwork_and_preserves_the_model_code(self):
        with tempfile.TemporaryDirectory() as directory:
            background=Path(directory)/'art.png';Image.new('RGB',(720,405),'#85bad3').save(background)
            scene=compose_slide(self.copy(),self.style(),0,[])
            for item in scene['texts']:item['color']='#258865'
            warnings=author_contrast_warnings(scene,background,720,405)
            self.assertTrue(warnings);self.assertEqual(warnings[0]['reason'],'html_low_contrast');self.assertIn('authored',scene)
            for item in scene['texts']:item['color']='#101b20'
            self.assertFalse(author_contrast_warnings(scene,background,720,405))
    def test_unreadable_foreground_uses_a_readable_source_color_without_moving_or_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            background=Path(directory)/'white.png';Image.new('RGB',(720,405),'white').save(background)
            style=self.style();scene=compose_slide(self.copy(),style,0,[]);before=[(item['text'],item['x'],item['y'],item['w'],item['h']) for item in scene['texts']]
            for item in scene['texts']:item['color']='#FFFFFF'
            repaired=repair_author_contrast(scene,background,720,405,style)
            self.assertTrue(repaired);self.assertFalse(author_contrast_warnings(scene,background,720,405))
            self.assertEqual(before,[(item['text'],item['x'],item['y'],item['w'],item['h']) for item in scene['texts']])
            scene['texts'][0].update(color='#FFFFFF',manualStyle=True)
            self.assertNotIn(scene['texts'][0]['key'],[r['key'] for r in repair_author_contrast(scene,background,720,405,style)])
    def test_source_single_body_quote_does_not_gain_an_unrelated_visible_heading(self):
        copy=self.copy();copy['html']='<main><p data-text="paragraphs.0"></p><p data-text="paragraphs.1"></p></main>'
        copy['sourceDesign']=dict(title=dict(shapeId=8,role='body'),textAnchors=[dict(shapeId=8,role='body')])
        scene=compose_slide(copy,self.style(),0,[]);self.assertIn('authored',scene)
        self.assertNotIn('h_title',[item['key'] for item in scene['texts']]);self.assertIn(copy['title'],scene['notes'])
        self.assertEqual([t['text'] for t in scene['texts']],copy['paragraphs'])
    def test_farewell_cannot_move_its_left_title_onto_the_retained_symbol(self):
        scene=dict(index=0,texts=[dict(key='h_title',text='Thanks',x=400,y=180,w=200,h=60)],sourceDesign=dict(
            title=dict(box=dict(x=60,y=80,w=250,h=80)),textAnchors=[dict(box=dict(x=60,y=80,w=250,h=80))],
            artwork=[dict(shapeId=9,box=dict(x=380,y=80,w=300,h=250))]))
        self.assertEqual({w['reason'] for w in source_layout_warnings(scene,720,405)},{'html_source_title_drift','html_source_art_overlap'})
        scene['texts'][0].update(x=60,y=80)
        self.assertFalse(source_layout_warnings(scene,720,405))
    def test_radial_labels_may_use_source_frames_but_generic_rows_over_the_ring_are_flagged(self):
        scene=dict(index=0,texts=[dict(key='h_card_0_body',text='Bound label',x=290,y=210,w=100,h=55)],sourceDesign=dict(
            textAnchors=[dict(box=dict(x=280,y=200,w=120,h=80))],artwork=[dict(shapeId=4,box=dict(x=260,y=160,w=190,h=180))]))
        self.assertFalse(source_layout_warnings(scene,720,405))
        scene['texts'][0].update(x=100,y=180,w=500,h=90)
        self.assertEqual(source_layout_warnings(scene,720,405)[0]['reason'],'html_source_art_overlap')
    def test_icon_clearance_uses_actual_text_lines_instead_of_empty_textbox_space(self):
        scene=dict(index=0,texts=[dict(key='h_card_0_body',text='Exact explanation',x=80,y=150,w=400,h=100,
            inkRects=[dict(x=80,y=150,w=120,h=20)])],sourceDesign=dict(textAnchors=[dict(box=dict(x=80,y=150,w=400,h=100))],
            artwork=[dict(shapeId=40,role='icon',box=dict(x=420,y=150,w=30,h=30))]))
        self.assertFalse(source_layout_warnings(scene,720,405))
        scene['texts'][0]['inkRects']=[dict(x=80,y=150,w=370,h=20)]
        self.assertEqual(source_layout_warnings(scene,720,405)[0]['reason'],'html_source_icon_overlap')
    @unittest.skipUnless(shutil.which('chromium'),'real Chromium required')
    def test_browser_measures_model_grid_and_saves_reopenable_shadow_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);out=root/'out';out.mkdir();style=self.style();Image.new('RGB',(1280,720),'white').save(root/style['background'])
            copy=self.copy();copy['html']=copy['html'].replace('class="layout"','class="slide layout"')
            copy['css']+=' .columns p{background:red;border-left:4pt solid green}'
            copy['sourceDesign']=dict(title=dict(shapeId=1,role='title',font='Arial'),textAnchors=[])
            copy['css']+=' h1{font-family:Georgia}'
            copy['html']+='<div data-graphic="bar" style="position:absolute;left:40pt;bottom:10pt;width:100pt;height:4pt;--graphic-color:#169EAA"></div>'
            scene=compose_slide(copy,style,0,[])
            warnings=browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            self.assertFalse(warnings,warnings);self.assertTrue(scene['htmlMeasured']);self.assertTrue((out/'authored-background-0.png').is_file())
            texts={n['key']:n for n in scene['texts']};self.assertGreater(texts['h_p_1']['x'],texts['h_p_0']['x']+texts['h_p_0']['w'])
            document=(out/'presentation.html').read_text();self.assertIn('shadowrootmode',document);self.assertIn('Точный заголовок',document)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox']);page=browser.new_page();page.set_content(document)
                self.assertEqual(page.locator('[data-key="h_title"]').inner_text(),'Точный заголовок')
                self.assertEqual(page.locator('[data-key="h_title"]').evaluate('el=>getComputedStyle(el).fontFamily'),'Arial')
                self.assertEqual(page.locator('[data-key="h_p_0"]').evaluate('el=>getComputedStyle(el).borderLeftWidth'),'0px')
                self.assertEqual(page.locator('[data-key="h_p_0"]').evaluate('el=>getComputedStyle(el).backgroundColor'),'rgba(0, 0, 0, 0)')
                self.assertEqual(page.locator('[data-graphic="bar"]').evaluate('el=>getComputedStyle(el).backgroundColor'),'rgb(22, 158, 170)')
                browser.close()
            self.assertEqual(len(list(out.glob('slide-*.png'))),1)
            item=next(n for n in scene['texts'] if n['key']=='h_p_0')
            item.update(text='Edited exact text',x=60,y=140,w=230,h=60,manualStyle=True,manualGeometry=True)
            browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            self.assertAlmostEqual(item['x'],60,delta=.1);self.assertAlmostEqual(item['y'],140,delta=.1)
            self.assertIn('Edited exact text',(out/'presentation.html').read_text())

    @unittest.skipUnless(shutil.which('chromium'),'real Chromium required')
    def test_model_copy_wrapper_does_not_position_every_bound_paragraph_on_top_of_itself(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);out=root/'out';out.mkdir();style=self.style();Image.new('RGB',(1280,720),'white').save(root/style['background'])
            copy=self.copy();copy['html']='<main class="layout"><h1 data-text="title"></h1><div class="copy"><p data-text="paragraphs.0"></p><p data-text="paragraphs.1"></p></div></main>'
            copy['css']='.layout{width:100%;height:100%}h1{position:absolute;left:40pt;top:30pt;font-size:30pt}.copy{position:absolute;left:90pt;top:120pt;width:550pt;display:flex;flex-direction:column;gap:20pt}p{font-size:22pt}'
            scene=compose_slide(copy,style,0,[]);warnings=browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            self.assertFalse(warnings,warnings);items={item['key']:item for item in scene['texts']}
            self.assertAlmostEqual(items['h_title']['x'],40,delta=.1)
            self.assertGreater(items['h_p_1']['y'],items['h_p_0']['y']+items['h_p_0']['h'])

    @unittest.skipUnless(shutil.which('chromium'),'real Chromium required')
    def test_fixed_source_heading_frame_fits_type_instead_of_growing_into_the_subtitle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);out=root/'out';out.mkdir();style=self.style();Image.new('RGB',(1280,720),'white').save(root/style['background'])
            copy=self.copy();copy['css']='.layout{width:100%;height:100%}h1{position:absolute;left:40pt;top:30pt;width:640pt;height:70pt;font-size:64pt;line-height:.9}.columns{position:absolute;left:40pt;top:110pt;width:640pt;height:200pt;display:grid;grid-template-columns:1fr 1fr;gap:20pt}p{font-size:22pt}'
            scene=compose_slide(copy,style,0,[]);warnings=browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            self.assertFalse(warnings,warnings);items={item['key']:item for item in scene['texts']}
            self.assertLess(items['h_title']['size'],64);self.assertLessEqual(items['h_title']['h'],74.1)
            self.assertLessEqual(items['h_title']['y']+items['h_title']['h'],items['h_p_0']['y'])

    @unittest.skipUnless(shutil.which('chromium'),'real Chromium required')
    def test_heading_line_box_follows_font_metrics_before_shrinking_the_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'out';out.mkdir();style=self.style();Image.new('RGB',(1280,720),'white').save(root/style['background'])
            copy=self.copy();copy['css']+='.layout{display:flex;flex-direction:column}h1{line-height:.5}'
            scene=compose_slide(copy,style,0,[])
            warnings=browser_render([scene],dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+60)
            self.assertFalse(warnings,warnings)
            title=next(item for item in scene['texts'] if item['key']=='h_title')
            self.assertEqual(title['size'],30);self.assertGreater(title['lineHeight'],1)

if __name__=='__main__':unittest.main()
