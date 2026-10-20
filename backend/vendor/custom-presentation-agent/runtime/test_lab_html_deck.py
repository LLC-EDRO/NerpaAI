import tempfile
import unittest
from pathlib import Path
from runtime.html_deck import clear_content, describe_layout, compose_slide, html_document, readable_ink, sample_grid_ids, add_measured_text, empty_picture_ids, neutral_content_art, chart_svg, add_html_picture
from runtime.security import NS, xml
from lxml import etree
from runtime.html_source import SOURCE_HTML_VERSION

class HtmlDeckTest(unittest.TestCase):
    def test_virtual_html_photo_host_retains_its_original_fill_in_native_export(self):
        source=self.layout();source['imageSlots']=[dict(shapeId=17,kind='placeholder',virtual=True,protected=False)]
        root=xml(f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="17"/></p:nvSpPr><p:spPr><a:solidFill><a:srgbClr val="0077FF"/></a:solidFill></p:spPr><p:txBody><a:p><a:r><a:t>Sample photo</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'.encode())
        clear_content(root,source,720,405)
        self.assertEqual(root.xpath('//a:srgbClr/@val',namespaces=NS),['0077FF']);self.assertEqual(root.xpath('//p:cNvPr/@id',namespaces=NS),['17']);self.assertFalse(''.join(root.xpath('//a:t/text()',namespaces=NS)))
    def test_final_preview_rasterization_matches_canonical_pdf_and_replaces_stale_image(self):
        import pymupdf
        from PIL import Image,ImageChops
        from runtime.html_deck import rasterize_html_pdf
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'canonical.pdf'
            with pymupdf.open() as pdf:
                page=pdf.new_page(width=720,height=405)
                page.draw_rect(pymupdf.Rect(610,20,690,80),fill=(0,0,.5))
                page.insert_text((40,120),'Canonical text')
                pdf.save(path)
            Image.new('RGB',(1280,720),'white').save(root/'slide-0.png')
            rasterize_html_pdf(path,root,1)
            with pymupdf.open(path) as pdf:
                pix=pdf[0].get_pixmap(matrix=pymupdf.Matrix(1280/720,1280/720),alpha=False)
                expected=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            self.assertIsNone(ImageChops.difference(Image.open(root/'slide-0.png').convert('RGB'),expected).getbbox())

    def test_independent_native_check_cannot_replace_the_accepted_html_pdf(self):
        import pymupdf
        from runtime.html_deck import publish_format_previews
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);native=root/'native';native.mkdir()
            for path,text in [(root/'html-preview.pdf','Canonical HTML'),(native/'presentation.pdf','Independent PowerPoint')]:
                with pymupdf.open() as pdf:
                    pdf.new_page().insert_text((30,40),text);pdf.save(path)
            publish_format_previews(root,native,1)
            self.assertEqual((root/'presentation.pdf').read_bytes(),(root/'html-preview.pdf').read_bytes())
            with pymupdf.open(root/'presentation.pdf')as pdf:self.assertIn('Canonical HTML',pdf[0].get_text())

    def test_similarly_luminous_saturated_artwork_is_not_a_readable_prose_surface(self):
        from PIL import Image,ImageDraw
        from runtime.html_surfaces import busy_text_background
        image=Image.new('RGB',(400,160),'#FA4808');draw=ImageDraw.Draw(image)
        for x in range(0,400,32):draw.rectangle((x,0,x+16,160),fill='#B36A18')
        item=dict(x=0,y=0,w=400,h=160,size=16)
        self.assertTrue(busy_text_background(image,item,400,160))
        self.assertFalse(busy_text_background(Image.new('RGB',(400,160),'#FA4808'),item,400,160))
    def test_measured_neutral_surfaces_do_not_bridge_a_patterned_gap_in_an_l_shape(self):
        from PIL import Image,ImageDraw
        from runtime.html_surfaces import neutral_source_surfaces,busy_text_background
        image=Image.new('RGB',(960,540),'#D72205');draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,950,220),fill='white');draw.rectangle((560,220,920,500),fill='white')
        surfaces=neutral_source_surfaces(image,960,540)
        self.assertTrue(surfaces);self.assertTrue(any(b['x']<30 and b['w']>850 and b['h']>170 for b in surfaces))
        self.assertTrue(all(b['y']+b['h']<225 or b['x']>=555 for b in surfaces))
        self.assertFalse(busy_text_background(image,dict(x=20,y=30,w=300,h=100,size=16),960,540))
        for x in range(0,500,40):draw.rectangle((x,300,x+20,450),fill='#80DEFF')
        self.assertTrue(busy_text_background(image,dict(x=20,y=310,w=400,h=110,size=16),960,540))
    def test_short_preview_budget_does_not_reserve_a_native_export_that_is_not_run(self):
        import json,time
        from unittest.mock import patch
        from PIL import Image
        from runtime.html_deck import export_deck,VERSION
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);output=folder/'output';source=self.layout();source.update(id='source',index=0,htmlRole='content')
            (folder/'analysis.json').write_text(json.dumps(dict(width=720,height=405,layouts=[source])))
            (folder/'html-template.json').write_text(json.dumps(dict(version=VERSION,width=720,height=405,layouts=[describe_layout(source,dict(width=720,height=405))])))
            Image.new('RGB',(720,405),'white').save(folder/'html-background-0.png')
            def browser(scenes,template,folder,out,images,deadline):
                self.assertGreater(deadline-time.monotonic(),15)
                (out/'html-preview.pdf').write_bytes(b'fixture');return []
            with patch('runtime.html_deck.browser_render',side_effect=browser),patch('runtime.html_deck.complete_html_previews'),patch('runtime.html_deck.deck_result',return_value=dict(ok=True)),patch('runtime.html_deck.native_export') as native:
                self.assertEqual(export_deck(folder,dict(output=str(output),htmlPhase='preview',remainingMs=20000,slides=[dict(sourceLayoutId='source',title='Title',paragraphs=['Point'])],images={},soffice='none')),dict(ok=True,revertedSlides=[]))
                native.assert_not_called()

    def test_explicit_sample_data_removal_includes_grouped_axes_and_keeps_design(self):
        source=self.layout();source['htmlRemoveShapeIds']=[20]
        root=xml(f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree><p:grpSp><p:nvGrpSpPr><p:cNvPr id="20"/></p:nvGrpSpPr><p:cxnSp><p:nvCxnSpPr><p:cNvPr id="21"/></p:nvCxnSpPr></p:cxnSp></p:grpSp><p:sp><p:nvSpPr><p:cNvPr id="30"/></p:nvSpPr></p:sp></p:spTree></p:cSld></p:sld>'.encode())
        clear_content(root,source,720,405)
        self.assertEqual(root.xpath('//p:cNvPr/@id',namespaces=NS),['30'])

    def test_html_pagination_uses_output_order_and_keeps_source_style(self):
        source=self.layout()
        source['slots'].append(dict(shapeId=90,role='page_number',x=680,y=375,w=25,h=18,text='23',font='Arial',size=12,color='#123456',align='center'))
        style=describe_layout(source,dict(width=720,height=405))
        scene=compose_slide(dict(title='Итог',paragraphs=['Текст'],deckSlideCount=15),style,4,[])
        number=next(item for item in scene['texts'] if item['key']=='h_page_0')
        self.assertEqual(number['text'],'5');self.assertEqual(number['color'],'#123456');self.assertEqual(number['x'],680)
        root=xml(f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="90"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>23</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'.encode())
        clear_content(root,source,720,405)
        self.assertFalse(''.join(root.xpath('//a:t/text()',namespaces=NS)))

    def test_independent_white_panels_remain_artwork_and_keep_the_gap_empty(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='content'
        source['slots'][0].update(x=45,y=25,w=630,h=35)
        source['slots'][1].update(x=55,y=160,w=30,h=18,text='Текст')
        source['slots'].append(dict(shapeId=12,role='body',x=440,y=170,w=40,h=18,text='Описание',font='Arial',size=12,color='#163743'))
        source['sourceObjects']=[dict(shapeId=20+i,kind='shape',canRemove=True,hasText=False,fill=dict(color='#FFFFFF'),box=dict(x=x,y=120,w=250,h=230)) for i,x in enumerate([30,440])]
        source['htmlDesign']=dict(canvas='panels',title=dict(x=60,y=50,w=580,h=75),content=[dict(x=60,y=205,w=229,h=365),dict(x=396,y=205,w=229,h=365)],surfaces=[dict(x=35,y=25,w=620,h=115),dict(x=35,y=179,w=261,h=420),dict(x=380,y=179,w=261,h=420)],variants=['columns'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'islands.png';picture=Image.new('RGB',(720,405),'#102C37');draw=ImageDraw.Draw(picture)
            for b in [(30,15,690,82),(30,120,280,350),(440,120,690,350)]:draw.rectangle(b,fill='white')
            picture.save(path);readable_ink(style,path,720,405)
        self.assertEqual(len(style['columns']),2)
        self.assertLess(style['columns'][0]['x']+style['columns'][0]['w'],280)
        self.assertGreater(style['columns'][1]['x'],440)

    def test_cover_subtitle_can_grow_inside_its_original_white_panel(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='cover'
        source['slots'][0].update(x=330,y=100,w=330,h=70)
        source['slots'][1].update(x=330,y=220,w=330,h=15)
        source['htmlDesign']=dict(canvas='panels',title=dict(x=460,y=250,w=450,h=160),content=[dict(x=460,y=550,w=450,h=35)],surfaces=[dict(x=430,y=100,w=500,h=800)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cover.png';picture=Image.new('RGB',(720,405),'#102C37')
            ImageDraw.Draw(picture).rectangle((310,40,680,365),fill='white');picture.save(path)
            readable_ink(style,path,720,405)
        self.assertGreater(style['body']['h'],60)
        self.assertGreaterEqual(style['body']['x'],310)
        self.assertLess(style['body']['y']+style['body']['h'],365)

    def test_chart_only_body_cannot_be_mistaken_for_the_header_strip(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['slots']=source['slots'][:1];source['htmlRole']='content'
        source['slots'][0].update(x=45,y=24,w=630,h=35)
        source['sourceObjects']=[dict(shapeId=40,kind='chart',box=dict(x=60,y=160,w=600,h=180))]
        source['htmlDesign']=dict(canvas='panels',title=dict(x=60,y=60,w=880,h=60),content=[dict(x=60,y=130,w=880,h=50)],surfaces=[dict(x=40,y=40,w=920,h=170)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'data-panels.png';picture=Image.new('RGB',(720,405),'#102C37');draw=ImageDraw.Draw(picture)
            draw.rectangle((30,15,690,82),fill='white');draw.rectangle((30,115,690,360),fill='white');picture.save(path)
            readable_ink(style,path,720,405)
        self.assertGreater(style['body']['y'],115);self.assertGreater(style['body']['h'],200)
        scene=compose_slide(dict(title='Сравнение',paragraphs=[],table=dict(headers=['Участок','Объекты'],rows=[['Север','20'],['Центр','30'],['Юг','40']])),style,0,[])
        self.assertGreater(scene['table']['box']['y'],115)
        self.assertGreater(scene['table']['box']['h'],200)


    def test_patterned_zone_cannot_validate_a_repair_across_the_whole_canvas(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='content'
        source['slots'][0].update(x=430,y=50,w=230,h=60)
        source['slots'][1].update(x=40,y=190,w=280,h=160)
        source['htmlDesign']=dict(canvas='panels',title=dict(x=600,y=100,w=330,h=150),content=[dict(x=50,y=450,w=420,h=400)],
            surfaces=[dict(x=20,y=20,w=960,h=960)],variants=['columns','cards'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'pattern.png';picture=Image.new('RGB',(720,405),'#102C37');draw=ImageDraw.Draw(picture)
            for x in range(0,720,25):draw.rectangle((x,0,x+8,405),fill='orange')
            draw.rectangle((400,20,700,150),fill='white');picture.save(path);readable_ink(style,path,720,405)
        self.assertTrue(all(p['w']<400 for p in style['design']['surfaces']))
        scene=compose_slide(dict(title='Роли команды',composition='columns',paragraphs=[],cards=[dict(title='Участники',body='Проверяют данные')],
            placement=dict(title=dict(x=30,y=75,w=940,h=100),content=[dict(x=30,y=200,w=940,h=650)])),style,0,[])
        self.assertGreater(scene['texts'][0]['x'],400)
        self.assertFalse(scene['shapes'],'No generated boxes or accent stripes behind source-style text')

    def test_photographic_cover_keeps_original_hero_away_from_master_branding(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='cover';source['slots'][0].update(x=194,y=108,w=338,h=63)
        source['slots'][1].update(x=194,y=173,w=338,h=23)
        source['htmlDesign']=dict(canvas='open',title=dict(x=50,y=50,w=900,h=140),content=[dict(x=50,y=220,w=900,h=300)],surfaces=[dict(x=0,y=0,w=1000,h=1000)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'photo.png';picture=Image.new('RGB',(720,405),'blue');draw=ImageDraw.Draw(picture)
            for x in range(0,720,20):draw.rectangle((x,0,x+8,405),fill='orange')
            picture.save(path);readable_ink(style,path,720,405)
        scene=compose_slide(dict(title='Тема пилота',paragraphs=['Краткое пояснение']),style,0,[])
        self.assertAlmostEqual(scene['texts'][0]['y'],108);self.assertAlmostEqual(scene['texts'][0]['x'],194)

    def test_source_anchor_keeps_cover_inside_right_panel_despite_bad_model_coordinates(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='cover'
        source['slots'][0].update(x=410,y=100,w=280,h=120)
        source['slots'][1].update(x=410,y=250,w=280,h=25)
        source['htmlDesign']=dict(canvas='panels',surfaces=[dict(x=130,y=20,w=180,h=940)],
            title=dict(x=145,y=350,w=150,h=300),content=[dict(x=140,y=690,w=160,h=180)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'panel.png';picture=Image.new('RGB',(720,405),'blue')
            ImageDraw.Draw(picture).rectangle((400,20,700,380),fill='white');picture.save(path);readable_ink(style,path,720,405)
        scene=compose_slide(dict(title='Проверка пилота',paragraphs=['Краткое пояснение']),style,0,[])
        for item in scene['texts']:
            self.assertGreaterEqual(item['x'],400);self.assertLessEqual(item['x']+item['w'],700)

    def test_tiny_sample_column_can_grow_within_the_verified_white_panel(self):
        from PIL import Image
        source=self.layout();source['htmlRole']='content';source['htmlDesign']=dict(canvas='panels',
            surfaces=[dict(x=50,y=50,w=900,h=900)],title=dict(x=560,y=80,w=370,h=130),
            content=[dict(x=560,y=270,w=370,h=620)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'panel.png';Image.new('RGB',(720,405),'white').save(path);readable_ink(style,path,720,405)
        self.assertGreater(style['body']['w'],650);self.assertIn('columns',style['design']['variants'])

    def test_cached_artwork_refresh_does_not_parse_or_render_powerpoint_again(self):
        import json
        from PIL import Image
        from unittest.mock import patch
        from runtime.html_deck import prepare_template, ARTWORK_VERSION
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);layout=self.layout();analysis=dict(width=720,height=405,sha256='a'*64,layouts=[layout])
            style=describe_layout(layout,analysis)
            style['sourceHtml']=dict(version=SOURCE_HTML_VERSION,sourceLayoutId=layout['id'],headingSelection=dict(reviewed=False,id=None))
            (folder/'analysis.json').write_text(json.dumps(analysis))
            (folder/'html-template.json').write_text(json.dumps(dict(version=1,artworkVersion=ARTWORK_VERSION,sourceSha256=analysis['sha256'],layouts=[style])))
            Image.new('RGB',(720,405),'white').save(folder/style['background'])
            with patch('runtime.html_deck.read_package',side_effect=AssertionError('Source parsed again')),patch('runtime.html_deck.render',side_effect=AssertionError('Artwork rendered again')):
                result=prepare_template(folder,'unused',True)
            self.assertEqual(len(result['layouts']),1);self.assertEqual(len(result['digest']),64)

    def test_selected_profiles_do_not_require_unselected_background_downloads(self):
        import json
        from PIL import Image
        from unittest.mock import patch
        from runtime.html_deck import prepare_template, ARTWORK_VERSION
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);first=self.layout();second=dict(self.layout(),id='other',index=1)
            analysis=dict(width=720,height=405,sha256='a'*64,layouts=[first,second]);styles=[describe_layout(l,analysis) for l in analysis['layouts']]
            for item,style in zip(analysis['layouts'],styles):style['sourceHtml']=dict(version=SOURCE_HTML_VERSION,sourceLayoutId=item['id'],headingSelection=dict(reviewed=False,id=None))
            (folder/'analysis.json').write_text(json.dumps(analysis));(folder/'html-template.json').write_text(json.dumps(dict(version=1,artworkVersion=ARTWORK_VERSION,sourceSha256=analysis['sha256'],layouts=styles)))
            Image.new('RGB',(720,405),'white').save(folder/styles[0]['background'])
            with patch('runtime.html_deck.read_package',side_effect=AssertionError('Unselected source re-imported')):
                result=prepare_template(folder,'unused',True,True,[first['id']])
            self.assertTrue(result['profilesOnly']);self.assertEqual(len(result['layouts']),2)

    def test_actual_white_panel_edge_constrains_an_imprecise_vision_rectangle(self):
        from PIL import Image,ImageDraw
        source=self.layout();source['htmlRole']='closing';source['htmlDesign']=dict(canvas='panels',
            surfaces=[dict(x=0,y=0,w=750,h=1000),dict(x=750,y=0,w=250,h=1000)],
            title=dict(x=25,y=10,w=720,h=130),content=[dict(x=65,y=250,w=620,h=500)],variants=['stack'])
        style=describe_layout(source,dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'panel.png';picture=Image.new('RGB',(960,540),'#1242BD')
            ImageDraw.Draw(picture).rectangle((0,86,480,540),fill='white');picture.save(path)
            readable_ink(style,path,720,405)
        scene=compose_slide(dict(title='Итоги',paragraphs=['Результат и следующий шаг']),style,0,[])
        body=scene['texts'][1]
        self.assertLessEqual(body['x']+body['w'],360)
        self.assertEqual(style['ink'],'#173F45')


    def test_title_only_farewell_cannot_grow_copy_over_its_artwork(self):
        source=self.layout();source['htmlRole']='closing';source['htmlDesign']=dict(canvas='panels',
            title=dict(x=300,y=400,w=400,h=200),content=[],variants=['stack'])
        scene=compose_slide(dict(title='Спасибо',paragraphs=['Согласовать следующий шаг']),describe_layout(source,dict(width=720,height=405)),0,[])
        self.assertEqual(len(scene['texts']),1);self.assertEqual(scene['texts'][0]['text'],'Спасибо')
        self.assertIn('Согласовать следующий шаг',scene['notes'])

    def test_vision_panel_overrides_canvas_expansion_for_title_cards_and_intro(self):
        source=self.layout();source['htmlRole']='content'
        source['htmlDesign']=dict(canvas='panels',title=dict(x=550,y=100,w=400,h=150),
            content=[dict(x=550,y=300,w=400,h=600)],variants=['cards','columns','stack'])
        style=describe_layout(source,dict(width=720,height=405))
        scene=compose_slide(dict(title='Заголовок',paragraphs=['Вводное объяснение'],composition='cards',
            cards=[dict(title='Риск',body='Неполные данные'),dict(title='Мера',body='Проверить источник')]),style,0,[])
        for item in scene['texts']+scene['shapes']:
            self.assertGreaterEqual(item['x'],396)
            self.assertLessEqual(item['x']+item['w'],684.1)
            self.assertLessEqual(item['y']+item['h'],364.6)
        self.assertLessEqual(scene['texts'][0]['y']+scene['texts'][0]['h'],101.3)

    def test_vision_disconnected_panels_never_use_the_patterned_gap(self):
        source=self.layout();source['htmlDesign']=dict(canvas='panels',title=dict(x=50,y=50,w=900,h=150),
            content=[dict(x=50,y=250,w=300,h=650),dict(x=650,y=250,w=300,h=650)],variants=['columns'])
        style=describe_layout(source,dict(width=720,height=405))
        scene=compose_slide(dict(title='Факторы',composition='columns',paragraphs=['Короткая вводная'],
            cards=[dict(title='А',body='Причина'),dict(title='Б',body='Следствие'),dict(title='В',body='Проверка')]),style,0,[])
        for item in scene['texts'][1:]:
            self.assertTrue(item['x']+item['w']<=252.1 or item['x']>=468)
        self.assertFalse(scene['shapes'])
        intro=next(item for item in scene['texts'] if item['key']=='h_p_0')
        from runtime.html_deck import intersection
        self.assertIn('data-text="paragraphs.0"',scene['authored']['html'])
        self.assertTrue(all('data-text="cards.%d.body"'%i in scene['authored']['html'] for i in range(3)))
        # Final positions come from browser CSS measurement, not placeholder frames.



    def test_pdf_survives_native_timeout_even_without_optional_screenshots(self):
        import json
        import pymupdf
        from unittest.mock import patch
        from runtime.html_deck import export_deck
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);output=folder/'output';style=describe_layout(self.layout(),dict(width=720,height=405))
            (folder/'html-template.json').write_text(json.dumps(dict(version=1,width=720,height=405,layouts=[style])))
            (folder/'analysis.json').write_text(json.dumps(dict(width=720,height=405,layouts=[self.layout()])))
            from PIL import Image
            Image.new('RGB',(720,405),'white').save(folder/style['background'])
            def browser(scenes,template,source,target,images,deadline):
                with pymupdf.open() as pdf:
                    pdf.new_page(width=720,height=405).insert_text((40,80),'Measured HTML content')
                    pdf.save(target/'html-preview.pdf')
                return []
            def native(scenes,template,source,target,images):
                (target/'presentation.pptx').write_bytes(b'editable-native-fixture');return {}
            with patch('runtime.html_deck.browser_render',browser),patch('runtime.html_deck.native_export',native),patch('runtime.html_deck.render',side_effect=TimeoutError):
                result=export_deck(folder,dict(output=str(output),slides=[dict(sourceLayoutId='source',title='Title',paragraphs=['Body'])],soffice='fixture',remainingMs=20000))
            self.assertTrue(result['pdfAvailable']);self.assertTrue((output/'slide-0.png').is_file())
            with pymupdf.open(output/'presentation.pdf') as pdf:self.assertIn('Measured HTML content',pdf[0].get_text())

    def test_busy_brand_art_gets_a_solid_content_surface(self):
        from PIL import Image, ImageDraw
        style=describe_layout(self.layout(),dict(width=720,height=405))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'busy.png';picture=Image.new('RGB',(720,405),'blue');draw=ImageDraw.Draw(picture)
            for x in range(0,720,40):draw.rectangle((x,0,x+20,405),fill='red')
            picture.save(path);readable_ink(style,path,720,405)
        scene=compose_slide(dict(title='Проверка',paragraphs=['Первый тезис','Второй тезис']),style,0,[])
        self.assertFalse(scene['shapes'],'Patterned artwork does not authorize colored prose boxes')

    def test_terminal_text_stays_inside_the_original_flat_panel(self):
        from PIL import Image, ImageDraw
        source=self.layout();source['htmlRole']='cover'
        source['slots'][0].update(x=410,y=100,w=280,h=120,color='#EA2905')
        source['slots'][1].update(x=410,y=230,w=280,h=25)
        style=describe_layout(source,dict(width=720,height=405))
        self.assertGreater(style['body']['x'],400)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'panel.png';picture=Image.new('RGB',(720,405),'blue')
            ImageDraw.Draw(picture).rectangle((400,20,700,380),fill='white');picture.save(path)
            readable_ink(style,path,720,405)
        for key in ('title','body'):
            bounds=style[key];self.assertGreater(bounds['x'],400);self.assertLess(bounds['x']+bounds['w'],700)
            self.assertGreater(bounds['y'],20);self.assertLess(bounds['y']+bounds['h'],380)
        self.assertGreater(style['body']['y'],style['title']['y']+style['title']['h'])
        self.assertEqual(style['titleColor'],'#EA2905')

    def test_explicit_company_date_example_is_cleared_but_real_branding_survives(self):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="17"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>COMPANY NAME / 00. 00. 20XX</a:t></a:r></a:p></p:txBody></p:sp>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="18"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>© Nerpa 2026</a:t></a:r></a:p></p:txBody></p:sp>'
                  '</p:spTree></p:sld>').encode())
        clear_content(root,dict(slots=[]))
        self.assertEqual([value for value in root.xpath('.//a:t/text()',namespaces=NS) if value],['© Nerpa 2026'])

    def test_measured_native_lines_are_not_wrapped_again_by_the_viewer(self):
        from runtime.html_deck import add_measured_text
        tree=etree.Element('{%s}spTree'%NS['p'])
        spec=dict(key='h_title',text='Вывод',renderedText='Вывод',x=10,y=0,w=114.3,h=30,size=32,font='Montserrat',color='#FFFFFF',bold=True,align='left',lineHeight=1.1)
        add_measured_text(tree,10,spec)
        self.assertEqual(tree.find('.//a:bodyPr',NS).get('wrap'),'none')
        self.assertEqual(tree.xpath('.//a:t/text()',namespaces=NS),['Вывод'])
        spec['nativeTextBox']=dict(x=18,y=20,w=120,h=40)
        add_measured_text(tree,11,spec)
        self.assertEqual(tree[-1].find('p:spPr/a:xfrm/a:off',NS).get('y'),str(20*12700))
        self.assertEqual(spec['y'],0,'Native export must not rewrite the HTML editor frame')

    def test_empty_picture_control_is_not_retained_as_a_hint_image(self):
        part='ppt/slides/slide1.xml'
        parts={part:('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
                    '<p:sp><p:nvSpPr><p:cNvPr id="12"/><p:nvPr><p:ph type="pic"/></p:nvPr></p:nvSpPr></p:sp>'
                    '</p:spTree></p:sld>').encode()}
        source=dict(self.layout(),part=part)
        empty=empty_picture_ids(parts,source);self.assertEqual(empty,{12})
        root=xml(parts[part]);clear_content(root,source,720,405,empty)
        self.assertFalse(root.findall('.//p:sp',NS))

    def test_registered_picture_placeholder_keeps_its_original_clean_surface(self):
        source=self.layout();source['imageSlots']=[dict(shapeId=12,kind='placeholder',protected=False,box=dict(x=40,y=100,w=250,h=180))]
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="12"/><p:nvPr><p:ph type="pic"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:p><a:r><a:t>Click to add picture</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:sld>').encode())
        clear_content(root,source,720,405,{12})
        self.assertFalse(root.findall('.//p:ph',NS));self.assertFalse(root.findall('.//a:t',NS))
        self.assertEqual(root.xpath('.//a:solidFill/a:srgbClr/@val',namespaces=NS),['FFFFFF'])
        self.assertEqual(root.xpath('.//a:xfrm/a:ext/@cx',namespaces=NS),[str(250*12700)])

    def test_unmapped_old_copy_is_removed_while_original_surface_is_preserved(self):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
            '<p:sp><p:nvSpPr><p:cNvPr id="17"/></p:nvSpPr><p:spPr><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></p:spPr><p:txBody><a:p><a:r><a:t>Old example and license instructions</a:t></a:r></a:p></p:txBody></p:sp>'
            '</p:spTree></p:sld>').encode())
        clear_content(root,dict(slots=[]))
        self.assertFalse([t for t in root.xpath('.//a:t/text()',namespaces=NS) if t])
        self.assertEqual(len(root.findall('.//p:spPr/a:solidFill',NS)),1)

    def test_radial_nodes_and_segments_survive_clearing_their_sample_labels(self):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
            '<p:sp><p:nvSpPr><p:cNvPr id="17"/></p:nvSpPr><p:spPr><a:solidFill><a:srgbClr val="10E7D9"/></a:solidFill><a:prstGeom prst="ellipse"/></p:spPr><p:txBody><a:p><a:r><a:t>OLD 99</a:t></a:r></a:p></p:txBody></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="18"/></p:nvSpPr><p:spPr><a:solidFill><a:srgbClr val="1781A1"/></a:solidFill><a:prstGeom prst="pie"/></p:spPr></p:sp>'
            '</p:spTree></p:sld>').encode())
        source=self.layout();source['htmlRole']='content'
        source['sourceObjects']=[dict(shapeId=18,kind='shape',hasText=False,canRemove=True,fill=dict(color='#1781A1'),box=dict(x=30,y=120,w=250,h=230))]
        clear_content(root,source,720,405)
        self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['17','18'])
        self.assertEqual(len(root.findall('.//p:spPr/a:solidFill',NS)),2)
        self.assertNotIn('OLD',''.join(root.xpath('.//a:t/text()',namespaces=NS)))

    def test_explicit_local_repair_removes_only_reviewed_sample_shapes(self):
        source=self.layout();source['htmlRole']='content'
        source['slots'][1].update(x=80,y=160,w=230,h=90,text='Example')
        source['sourceObjects']=[dict(shapeId=31,kind='shape',hasText=False,canRemove=True,fill=dict(color='#0077FF'),box=dict(x=60,y=140,w=280,h=130))]
        source['htmlRemoveShapeIds']=[31,43]
        source['reservedRegions']=[dict(shapeId=43,role='icon',box=dict(x=300,y=160,w=20,h=20)),
                                   dict(shapeId=44,role='logo',box=dict(x=600,y=20,w=50,h=30))]
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="31"/></p:nvSpPr></p:sp>'
                  '<p:pic><p:nvPicPr><p:cNvPr id="43"/></p:nvPicPr></p:pic>'
                  '<p:pic><p:nvPicPr><p:cNvPr id="44"/></p:nvPicPr></p:pic>'
                  '</p:spTree></p:sld>').encode())
        clear_content(root,source,720,405)
        self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['44'])
        style=describe_layout(source,dict(width=720,height=405))
        self.assertEqual(len(style['protected']),1)


    def test_cover_is_not_rebuilt_as_a_content_card_grid(self):
        layout=describe_layout(dict(self.layout(),htmlRole='cover'),dict(width=720,height=405))
        scene=compose_slide(dict(title='Тема',paragraphs=['Автор','Организация'],cards=[dict(title='Лишняя карточка',body='Текст')]),layout,0,[])
        self.assertEqual(scene['shapes'],[])

    def test_original_jpeg_bytes_keep_matching_package_type(self):
        import io
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(80,40),'blue').save(stream,format='JPEG');payload=stream.getvalue()
        tree=xml(('<p:spTree xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"/>').encode())
        rels=xml(('<Relationships xmlns="'+NS['pr']+'"/>').encode());types=xml(('<Types xmlns="'+NS['ct']+'"/>').encode());parts={}
        add_html_picture(tree,2,dict(x=10,y=10,w=100,h=50),payload,parts,rels,types,0)
        self.assertTrue(next(iter(parts)).endswith('.jpg'));self.assertEqual(next(iter(parts.values())),payload)
        self.assertEqual(types[0].get('ContentType'),'image/jpeg');self.assertTrue(rels[0].get('Target').endswith('.jpg'))

    def test_html_scatter_preserves_numeric_x_spacing(self):
        svg=chart_svg(dict(data=dict(type='xy',categories=['1','3','9'],series=[dict(values=[10,20,30])]),box=dict(w=400,h=200)),dict(ink='#202020',accent='#0077FF'))
        tree=xml(svg.encode());points=tree.find('{http://www.w3.org/2000/svg}polyline').get('points').split()
        xs=[float(point.split(',')[0]) for point in points]
        self.assertAlmostEqual((xs[1]-xs[0])/(xs[2]-xs[0]),.25)


    def test_terminal_only_recovery_builds_new_content_art_without_hero(self):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:cSld><p:spTree>'
                  '<p:pic><p:nvPicPr><p:cNvPr id="8"/></p:nvPicPr></p:pic>'
                  '<p:pic><p:nvPicPr><p:cNvPr id="9"/></p:nvPicPr></p:pic>'
                  '</p:spTree></p:cSld></p:sld>').encode())
        neutral_content_art(root,dict(reservedRegions=[dict(shapeId=9,role='logo')]),dict(accent='#0077FF'),720)
        self.assertEqual(root.get('showMasterSp'),'0')
        self.assertNotIn('8',root.xpath('.//p:cNvPr/@id',namespaces=NS))
        self.assertIn('9',root.xpath('.//p:cNvPr/@id',namespaces=NS))
        self.assertEqual(root.find('p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr',NS).get('val'),'FFFFFF')

    def test_text_branding_survives_sample_removal_and_neutral_content_keeps_source_background(self):
        source=self.layout();source['htmlPreserveShapeIds']=[2]
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:cSld><p:spTree>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="1"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Sample title</a:t></a:r></a:p></p:txBody></p:sp>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="2"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Brand</a:t></a:r></a:p></p:txBody></p:sp>'
                  '</p:spTree></p:cSld></p:sld>').encode())
        clear_content(root,source)
        self.assertEqual([v for v in root.xpath('.//a:t/text()',namespaces=NS) if v],['Brand'])
        layout=describe_layout(source,dict(width=720,height=405,styleProfile=dict(backgrounds=['#102C37'])))
        neutral_content_art(root,dict(reservedRegions=[dict(shapeId=2,role='brand')]),layout,720)
        self.assertIn('Brand',root.xpath('.//a:t/text()',namespaces=NS))
        self.assertEqual(root.find('p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr',NS).get('val'),'102C37')

    def test_measured_line_breaks_survive_native_export_without_inherited_spacing(self):
        tree=xml(('<p:spTree xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"/>').encode())
        item=dict(key='body',text='First second',renderedText='First\nsecond',x=20,y=30,w=200,h=80,
                  font='Arial',size=20,color='#202020',bold=False,align='left')
        add_measured_text(tree,2,item)
        self.assertEqual(tree.xpath('.//a:t/text()',namespaces=NS),['First','second'])
        self.assertEqual(tree.xpath('.//a:spcAft/a:spcPts/@val',namespaces=NS),['0','0'])
        self.assertEqual(tree.xpath('.//a:lnSpc/a:spcPts/@val',namespaces=NS),['2200','2200'])
        self.assertEqual(item['text'],'First second')

    def test_only_explicitly_removed_separators_are_erased(self):
        root=xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:spTree>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="8"/></p:nvSpPr></p:sp>'
                  '<p:sp><p:nvSpPr><p:cNvPr id="9"/></p:nvSpPr></p:sp>'
                  '</p:spTree></p:sld>').encode())
        source=self.layout();source['sourceObjects']=[dict(shapeId=i,canRemove=True,role='decorative',hasText=False,box=dict(x=50,y=200,w=200,h=2)) for i in (8,9)]
        source['reservedRegions']=[dict(shapeId=9,role='brand')]
        source['htmlRemoveShapeIds']=[8]
        clear_content(root,source,720,405)
        self.assertEqual(root.xpath('.//p:cNvPr/@id',namespaces=NS),['9'])

    def test_uniform_picture_recovery_excludes_protected_branding(self):
        import io
        from PIL import Image
        bitmap=io.BytesIO();Image.new('RGB',(40,30),'green').save(bitmap,format='PNG')
        part='ppt/slides/source.xml'
        root=('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'" xmlns:r="'+NS['r']+'"><p:pic><p:nvPicPr><p:cNvPr id="8"/></p:nvPicPr><p:blipFill><a:blip r:embed="image"/></p:blipFill></p:pic></p:sld>').encode()
        parts={part:root,'ppt/slides/_rels/source.xml.rels':('<Relationships xmlns="'+NS['pr']+'"><Relationship Id="image" Target="../media/tile.png"/></Relationships>').encode(),'ppt/media/tile.png':bitmap.getvalue()}
        source=dict(part=part,imageSlots=[dict(shapeId=8)])
        self.assertEqual(empty_picture_ids(parts,source),{8})
        source['imageSlots'][0]['protected']=True
        self.assertEqual(empty_picture_ids(parts,source),set())

    def layout(self):
        return dict(id='source', index=0, slots=[
            dict(shapeId=1, role='title', x=35, y=25, w=650, h=45, size=30, font='Arial', color='#173F45'),
            dict(shapeId=2, role='body', x=35, y=150, w=30, h=12, size=18, font='Arial', color='#173F45')])

    def test_tiny_sample_frame_expands_but_keeps_original_typography(self):
        layout = describe_layout(self.layout(), dict(width=720, height=405))
        self.assertGreater(layout['body']['w'], 500)
        self.assertGreater(layout['body']['h'], 150)
        self.assertEqual(layout['font'], 'Arial')
        self.assertEqual(layout['ink'], '#173F45')
        self.assertGreaterEqual(layout['size'], 20)

    def test_removed_sample_chart_does_not_block_new_content(self):
        source = self.layout()
        source['reservedRegions'] = [dict(shapeId=90, role='chart', box=dict(x=80, y=100, w=600, h=250))]
        layout = describe_layout(source, dict(width=720, height=405))
        self.assertEqual(layout['protected'], [])
        self.assertGreater(layout['body']['w'], 600)

    def test_sample_bullet_does_not_reserve_a_whole_content_column(self):
        source=self.layout();source['sourceObjects']=[dict(shapeId=22,kind='shape',hasText=False,box=dict(x=200,y=110,w=12,h=12))]
        layout=describe_layout(source,dict(width=720,height=405))
        self.assertGreater(layout['adaptiveBody']['w'],600)

    def test_meaningful_source_column_is_not_expanded_over_side_artwork(self):
        source = self.layout(); source['slots'][1].update(x=60,y=120,w=265,h=210)
        layout = describe_layout(source, dict(width=720,height=405))
        self.assertEqual(layout['body'],dict(x=60,y=120,w=265,h=210))

    def test_chart_space_is_reclaimed_by_authored_css_instead_of_a_second_compositor(self):
        source=self.layout();source['slots'][1].update(x=490,y=120,w=190,h=210)
        source['sourceObjects']=[dict(shapeId=8,kind='chart',box=dict(x=40,y=100,w=420,h=240))]
        layout=describe_layout(source,dict(width=720,height=405))
        scene=compose_slide(dict(title='Риски',paragraphs=['Объяснение без фиктивной диаграммы'],
            html='<main><h1 data-text="title"></h1><p data-text="paragraphs.0"></p></main>',
            css='main{position:relative;width:100%;height:100%}h1{position:absolute;left:40pt;top:25pt;width:630pt;height:55pt;margin:0}p{position:absolute;left:40pt;top:120pt;width:640pt;height:210pt;margin:0;font-size:22pt}'),layout,0,[])
        from runtime.html_deck import browser_render
        from PIL import Image
        import time
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'out';output.mkdir();Image.new('RGB',(720,405),'white').save(root/layout['background'])
            browser_render([scene],dict(width=720,height=405,layouts=[layout]),root,output,{},time.monotonic()+30)
        self.assertNotIn('flow',scene);self.assertTrue(scene['htmlMeasured'])
        self.assertGreater(next(item['w'] for item in scene['texts'] if item['key']=='h_p_0'),600)

    def test_contrast_recovery_uses_actual_background_and_brand_accent(self):
        from PIL import Image
        source=self.layout();source['slots'][1]['color']='#FFFFFF'
        layout=describe_layout(source,dict(width=720,height=405,styleProfile=dict(colors=['#FAFCFF','#8F8F8F','#0077FF'])))
        with tempfile.TemporaryDirectory() as path:
            background=Path(path)/'background.png';Image.new('RGB',(720,405),'white').save(background)
            readable_ink(layout,background,720,405)
        self.assertEqual(layout['ink'],'#202020');self.assertEqual(layout['accent'],'#0077FF')

    def test_repeated_sample_cell_art_is_not_frozen_into_background(self):
        objects=[dict(shapeId=10+r*3+c,kind='picture',canRemove=True,hasText=False,
                      box=dict(x=20+c*210,y=100+r*35,w=200,h=30)) for r in range(4) for c in range(3)]
        source=self.layout();source['sourceObjects']=objects
        source['reservedRegions']=[dict(shapeId=10,role='logo',box=objects[0]['box'])]
        self.assertNotIn(10,sample_grid_ids(source));self.assertEqual(len(sample_grid_ids(source)),11)

    def test_protected_picture_is_outside_expanded_content(self):
        source = self.layout()
        source['imageSlots'] = [dict(box=dict(x=400, y=110, w=280, h=240))]
        layout = describe_layout(source, dict(width=720, height=405))
        self.assertLessEqual(layout['body']['x']+layout['body']['w'], 400)

    def test_sample_data_is_removed_even_if_chart_type_is_unsupported(self):
        root = xml(('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'" xmlns:c="'+NS['c']+'">'
                    '<p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Text</a:t></a:r></a:p></p:txBody></p:sp>'
                    '<p:sp><p:nvSpPr><p:cNvPr id="3"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Brand</a:t></a:r></a:p></p:txBody></p:sp>'
                    '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="99"/></p:nvGraphicFramePr><a:graphic><a:graphicData><c:chart/></a:graphicData></a:graphic></p:graphicFrame>'
                    '</p:spTree></p:sld>').encode())
        source = self.layout(); source['slots'].append(dict(shapeId=3, role='brand'))
        clear_content(root, source)
        self.assertEqual(root.xpath('count(.//c:chart)', namespaces=NS), 0)
        self.assertEqual([text for text in root.xpath('.//a:t/text()', namespaces=NS) if text], ['Brand'])

    def test_html_escapes_content_and_table_values_are_individually_editable(self):
        layout = describe_layout(self.layout(), dict(width=720, height=405))
        scene = compose_slide(dict(title='<script>throw 1</script>', paragraphs=[],
                                   table=dict(headers=['Area', 'Count'], rows=[['North', '20']])), layout, 0, [])
        self.assertEqual(len(scene['cells']), 4)
        self.assertEqual(scene['cells'][-1]['cell'], [1, 1])
        with tempfile.TemporaryDirectory() as path:
            from PIL import Image
            Image.new('RGB', (720, 405), 'white').save(Path(path)/layout['background'])
            document = html_document([scene], dict(width=720, height=405, layouts=[layout]), Path(path), {})
        self.assertNotIn('<script>', document)
        self.assertIn('&lt;script&gt;', document)
        self.assertIn('20', document)
