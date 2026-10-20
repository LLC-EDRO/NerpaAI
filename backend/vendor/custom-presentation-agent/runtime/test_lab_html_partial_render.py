import copy
import hashlib
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pymupdf
from runtime.html_deck import describe_layout,compose_slide,browser_render
from runtime.html_partial_render import render_changed_pages


class HtmlPartialRenderTest(unittest.TestCase):
    def test_only_changed_page_renders_and_unchanged_scenes_and_pixels_stay_exact(self):
        if not shutil.which('chromium'):self.skipTest('Chromium required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);baseline=root/'baseline';baseline.mkdir();out=root/'changed';out.mkdir()
            Image.new('RGB',(720,405),'white').save(root/'art.png')
            layout=describe_layout(dict(id='source',index=0,htmlRole='content',slots=[dict(shapeId=1,role='title',text='Original',x=30,y=30,w=660,h=50,font='Arial',size=28,color='#123456')]),dict(width=720,height=405))
            layout['background']='art.png';template=dict(width=720,height=405,layouts=[layout])
            def slide(title):return dict(title=title,paragraphs=[],cards=[],metrics=[],steps=[],table=None,chart=None,takeaway='',html='<main><h1 data-text="title"></h1></main>',css='h1{position:absolute;left:30pt;top:30pt;font-size:28pt}')
            scenes=[compose_slide(slide('До '+str(i)),layout,i,[]) for i in range(3)]
            warnings=browser_render(scenes,template,root,baseline,{},time.monotonic()+60)
            shutil.copyfile(baseline/'html-preview.pdf',root/'html-proof.pdf');shutil.copyfile(baseline/'presentation.html',root/'html-proof.html')
            for i in range(3):
                shutil.copyfile(baseline/f'slide-{i}.png',root/f'html-proof-slide-{i}.png')
                shutil.copyfile(baseline/f'authored-background-{i}.png',root/f'html-proof-background-{i}.png')
            receipt=dict(slides=[dict(native=dict(html=copy.deepcopy(s))) for s in scenes],warnings=warnings)
            proposed=[compose_slide(slide('После '+str(i)),layout,i,[]) for i in range(3)]
            counts=[]
            def render(selected,*args):counts.append(len(selected));return browser_render(selected,*args)
            with patch('runtime.html_deck.browser_render',side_effect=render):
                result,_=render_changed_pages(proposed,template,root,out,{},time.monotonic()+60,receipt,[2])
            self.assertEqual(counts,[1]);self.assertEqual(result[0],receipt['slides'][0]['native']['html']);self.assertEqual(result[2],receipt['slides'][2]['native']['html'])
            self.assertEqual(result[1]['texts'][0]['text'],'После 1')
            for i in (0,2):self.assertEqual(hashlib.sha256((out/f'slide-{i}.png').read_bytes()).digest(),hashlib.sha256((baseline/f'slide-{i}.png').read_bytes()).digest())
            with pymupdf.open(out/'html-preview.pdf') as pdf:
                self.assertEqual(len(pdf),3);self.assertIn('После 1',pdf[1].get_text());self.assertIn('До 0',pdf[0].get_text())
            # A subset render keeps global slide identity in every finding.
            # Otherwise a repaired eighth page could blame the first page.
            overflow=root/'overflow';overflow.mkdir()
            tiny=compose_slide(slide('Очень длинный заголовок'),layout,7,[])
            tiny['authored']['css']+='\nh1{width:10px!important;height:1px!important}'
            findings=browser_render([tiny],template,root,overflow,{},time.monotonic()+60)
            overflows=[item for item in findings if item['reason']=='html_text_overflow']
            self.assertTrue(overflows);self.assertEqual({item['slide'] for item in overflows},{8})


if __name__=='__main__':unittest.main()
