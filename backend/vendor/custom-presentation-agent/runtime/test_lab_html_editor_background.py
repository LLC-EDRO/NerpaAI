import tempfile,time,unittest,shutil
from pathlib import Path
from lxml import html
import pymupdf
from PIL import Image
from runtime.html_editor_background import html_editor_background
from runtime.html_revision import edited_html_scene
from runtime.html_deck import compose_slide,browser_render
from runtime.html_author import author_fragment
from runtime import test_lab_html_author as author_tests


@unittest.skipUnless(shutil.which('chromium'),'Chromium required')
class HtmlEditorBackgroundTest(unittest.TestCase):
    def test_manual_alignment_moves_text_inside_original_flex_and_grid_frames_in_pdf_and_pptx(self):
        from runtime.html_deck import add_measured_text
        from runtime.security import NS
        from lxml import etree
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);style=author_tests.HtmlAuthorTest().style();style['background']='art.png'
            Image.new('RGB',(720,405),'white').save(root/'art.png');scenes=[]
            for mode in ('flex-row','flex-column','grid'):
                for align in ('left','center','right'):
                    copy=author_tests.HtmlAuthorTest().copy();copy.update(paragraphs=['Aligned text\nShort'],
                        html='<main><h1 data-text="title"></h1><p data-text="paragraphs.0"></p></main>',
                        css='main{position:relative;width:100%%;height:100%%}h1{position:absolute;left:30pt;top:20pt;font-size:24pt}p{position:absolute;left:60pt;top:120pt;width:500pt;height:130pt;padding:8pt 12pt;margin:0;font-size:22pt;display:%s;flex-direction:%s;align-items:center;justify-content:center;justify-items:center;text-align:center}'%('grid' if mode=='grid' else 'flex','column' if mode=='flex-column' else 'row'))
                    original=compose_slide(copy,style,len(scenes),[])
                    slide=dict(native=dict(html=original,fields={item['key']:item['text'] for item in original['texts']}),textStyles={'native.fields.h_p_0':dict(align=align)})
                    scenes.append(edited_html_scene(slide))
            out=root/'output';out.mkdir();browser_render(scenes,dict(width=720,height=405,layouts=[style]),root,out,{},time.monotonic()+90)
            with pymupdf.open(out/'html-preview.pdf') as pdf:
                self.assertEqual(len(pdf),9)
                for index,scene in enumerate(scenes):
                    item=next(t for t in scene['texts'] if t['key']=='h_p_0');align=('left','center','right')[index%3]
                    self.assertEqual(item['align'],align)
                    self.assertAlmostEqual(item['x'],60,delta=.02);self.assertAlmostEqual(item['w'],500,delta=.02)
                    self.assertTrue(item['inkRects']);ink=item['inkRects'][0]
                    if align=='left':self.assertAlmostEqual(ink['x'],72,delta=1,msg='page '+str(index))
                    elif align=='right':self.assertAlmostEqual(ink['x']+ink['w'],548,delta=1,msg='page '+str(index))
                    else:self.assertAlmostEqual(ink['x']+ink['w']/2,310,delta=1,msg='page '+str(index))
                    self.assertIn('Aligned text',pdf[index].get_text())
                    tree=etree.Element('{%s}spTree'%NS['p']);add_measured_text(tree,index+1,item)
                    for paragraph in tree.findall('p:sp/p:txBody/a:p',NS):
                        self.assertEqual(paragraph.find('a:pPr',NS).get('algn'),{'left':'l','center':'ctr','right':'r'}[align])

    def test_exact_binding_hides_shadowed_text_keeps_surface_and_other_page_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'previews').mkdir();source=root/'previews/presentation.html'
            source.write_text('''<!doctype html><html><head><style>
              @page{size:720pt 405pt;margin:0}body{margin:0}.slide{width:720pt;height:405pt;break-after:page}
              .slide:last-child{break-after:auto}
            </style></head><body><section data-slide="0" class="slide"><div class="ai-host"><template shadowrootmode="open" shadowrootserializable>
            <style>*{box-sizing:border-box}main{width:720pt;height:405pt;background:#fff}
              p{margin:0;width:300pt;height:80pt;padding:8pt 12pt;font:24pt/1.2 'Liberation Sans';color:#fff;background:#1248ab;text-shadow:1px 1px #000}
              div{font:20pt 'Liberation Sans'}</style><main><p data-key="h_p_0">Same repeated copy</p>
              <div data-key="h_p_1">Same repeated copy</div></main></template></div></section>
            <section data-slide="1" class="slide">OTHER PAGE MUST NOT APPEAR</section></body></html>''')
            before=source.read_bytes();output=root/'output'
            result=html_editor_background(root,dict(output=str(output),page=0,width=720,height=405,
                fields=[dict(path='native.fields.h_p_0',font='Liberation Sans')]))
            self.assertEqual(source.read_bytes(),before)
            appearance=result['appearances']['native.fields.h_p_0']
            self.assertEqual(appearance['size'],24);self.assertEqual(appearance['color'],'#ffffff')
            self.assertEqual(appearance['htmlStyle']['paddingLeft'],12)
            self.assertAlmostEqual(appearance['htmlStyle']['paddingTop'],8,places=3)
            with pymupdf.open(output/'editor.pdf') as pdf:
                self.assertEqual(len(pdf),1)
                self.assertNotIn('OTHER PAGE',pdf[0].get_text())
            image=Image.open(output/'slide-0.png').convert('RGB')
            self.assertEqual(image.crop((5,5,520,135)).getextrema(),((18,18),(72,72),(171,171)),
                'Selected text and its shadow disappear; the original filled surface stays intact')
            self.assertTrue(result['fonts'])
            for font in result['fonts']:self.assertTrue((output/font['key']).is_file())
            for page in (-1,2,True):
                with self.assertRaisesRegex(ValueError,'page_invalid'):
                    html_editor_background(root,dict(output=str(output),page=page,fields=[]))
            with self.assertRaisesRegex(ValueError,'field_invalid'):
                html_editor_background(root,dict(output=str(output),page=0,fields=[dict(path='../secret')]))

    def test_manual_typography_stays_in_original_grid_and_moving_preserves_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);style=author_tests.HtmlAuthorTest().style();style['background']='art.png'
            Image.new('RGB',(720,405),'white').save(root/'art.png')
            copy=author_tests.HtmlAuthorTest().copy();copy.update(paragraphs=['Concise explanation'],
                html='<main><h1 data-text="title"></h1><div class="grid"><p data-text="paragraphs.0"></p></div></main>',
                css='main{position:relative;width:100%;height:100%}h1{position:absolute;left:30pt;top:20pt;font-size:28pt}.grid{position:absolute;left:60pt;top:120pt;display:grid;width:500pt;height:130pt}p{margin:0;padding:8pt 12pt;font-size:18pt;line-height:1.2}')
            scene=compose_slide(copy,style,0,[]);template=dict(width=720,height=405,layouts=[style])
            out=root/'initial';out.mkdir();browser_render([scene],template,root,out,{},time.monotonic()+60)
            field=next(t for t in scene['texts'] if t['key']=='h_p_0');before=dict(field)
            slide=dict(native=dict(html=scene,fields={t['key']:t['text'] for t in scene['texts']}),textStyles={'native.fields.h_p_0':dict(size=24,bold=True)})
            edited=edited_html_scene(slide)
            markup,_=author_fragment(edited,style,lambda *_:'')
            element=html.fragment_fromstring(markup,create_parent=True).xpath('.//*[@data-key="h_p_0"]')[0]
            self.assertEqual(element.getparent().get('class'),'grid')
            self.assertNotIn('position:absolute',element.get('style',''))
            revised=root/'revised';revised.mkdir();browser_render([edited],template,root,revised,{},time.monotonic()+60)
            field=next(t for t in edited['texts'] if t['key']=='h_p_0')
            self.assertEqual(field['size'],24)
            for key in ('x','y','w','h','htmlStyle'):self.assertEqual(field[key],before[key],key)
            slide['native']['html']=edited
            slide['textStyles']['native.fields.h_p_0'].update(x=35,y=285,w=500,h=90)
            moved=edited_html_scene(slide);out=root/'moved';out.mkdir()
            browser_render([moved],template,root,out,{},time.monotonic()+60)
            field=next(t for t in moved['texts'] if t['key']=='h_p_0')
            for key,value in dict(x=35,y=285,w=500,h=90,size=24).items():self.assertAlmostEqual(field[key],value,delta=.02)
            self.assertEqual(field['htmlStyle'],before['htmlStyle'])


if __name__=='__main__':unittest.main()
