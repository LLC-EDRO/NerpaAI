import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from runtime.html_deck import describe_layout,export_deck

def source(index=0,design=None):
    return dict(id=f'source{index}',index=index,htmlRole='content',slots=[
        dict(shapeId=1,role='title',text='Заголовок',x=40,y=25,w=630,h=55,size=30,font='Arial',color='#163743'),
        dict(shapeId=2,role='body',text='Текст',x=500,y=130,w=150,h=160,size=22,font='Arial',color='#163743')],htmlDesign=design)

class HtmlExportTest(unittest.TestCase):

    def test_neural_icon_repair_refreshes_only_affected_artwork_and_reaches_final_adapter(self):
        import pymupdf
        from runtime.html_deck import removable_source_icons
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);original=source()
            original['reservedRegions']=[dict(shapeId=9,role='icon',box=dict(x=350,y=130,w=35,h=35)),dict(shapeId=10,role='logo',box=dict(x=50,y=10,w=30,h=30))]
            original['htmlDesign']=dict(canvas='panels',title=dict(x=50,y=50,w=900,h=130),content=[dict(x=50,y=250,w=900,h=650)],surfaces=[dict(x=20,y=20,w=960,h=960)],variants=['cards'])
            analysis=dict(width=720,height=405,sha256='a'*64,layouts=[original]);style=describe_layout(original,analysis)
            (folder/'analysis.json').write_text(json.dumps(analysis));(folder/'html-template.json').write_text(json.dumps(dict(version=1,width=720,height=405,layouts=[style])))
            Image.new('RGB',(960,540),'white').save(folder/style['background'])
            self.assertEqual(removable_source_icons(original,720,405),{9})
            refreshed=[]
            def refresh(source,soffice,reuse,profiles,selected):
                refreshed.extend(selected)
                return dict(version=1,width=720,height=405,layouts=[dict(style,removedShapeIds=[9])])
            def browser(scenes,template,source,target,images,deadline):
                self.assertGreater(scenes[0]['designBounds']['content'][0]['w'],600)
                for scene in scenes:scene['htmlMeasured']=True
                (target/'presentation.html').write_text('<html>Accepted repair</html>')
                with pymupdf.open() as pdf:pdf.new_page(width=720,height=405);pdf.save(target/'html-preview.pdf')
                return []
            with patch('runtime.html_deck.prepare_template',refresh),patch('runtime.html_deck.browser_render',browser):
                preview=export_deck(folder,dict(htmlPhase='preview',soffice='unused',output=str(folder/'preview'),slides=[dict(sourceLayoutId='source0',title='Title',paragraphs=['Text'],omitSourceIconIds=[9,10])],remainingMs=30000))
            self.assertEqual(refreshed,['source0']);self.assertEqual(preview['slides'][0]['native']['html']['omitSourceIconIds'],[9])
            import shutil
            for a,b in [('presentation.pdf','html-proof.pdf'),('presentation.html','html-proof.html'),('slide-0.png','html-proof-slide-0.png')]:shutil.copyfile(folder/'preview'/a,folder/b)
            # A fresh final sandbox starts from the immutable source metadata.
            (folder/'analysis.json').write_text(json.dumps(analysis))
            def native(scenes,template,source,target,images):
                changed=json.loads((source/'analysis.json').read_text())['layouts'][0]
                self.assertEqual(changed['htmlRemoveShapeIds'],[9]);return {}
            with patch('runtime.html_deck.native_export',native),patch('runtime.html_deck.prepare_template',side_effect=AssertionError('Artwork re-rendered after HTML acceptance')):
                export_deck(folder,dict(htmlPhase='final',output=str(folder/'final'),slides=preview['slides'],remainingMs=30000))


    def test_preview_does_not_call_powerpoint_and_final_does_not_relayout_html(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);layout=describe_layout(source(),dict(width=720,height=405))
            (folder/'analysis.json').write_text(json.dumps(dict(width=720,height=405,layouts=[source()])))
            (folder/'html-template.json').write_text(json.dumps(dict(version=1,width=720,height=405,layouts=[layout])))
            Image.new('RGB',(960,540),'white').save(folder/layout['background'])
            def browser(scenes,template,source,target,images,deadline):
                for scene in scenes:scene['htmlMeasured']=True
                (target/'presentation.html').write_text('<html>Accepted CSS layout</html>')
                with pymupdf.open() as pdf:pdf.new_page(width=720,height=405);pdf.save(target/'html-preview.pdf')
                return []
            with patch('runtime.html_deck.browser_render',browser),patch('runtime.html_deck.native_export',side_effect=AssertionError('PPTX before HTML review')):
                preview=export_deck(folder,dict(htmlPhase='preview',output=str(folder/'preview'),slides=[dict(sourceLayoutId='source0',title='Title',paragraphs=['Text'])],remainingMs=30000))
            self.assertTrue(preview['htmlOnly']);self.assertFalse(preview['pptxWritten'])
            import shutil
            for a,b in [('presentation.pdf','html-proof.pdf'),('presentation.html','html-proof.html'),('slide-0.png','html-proof-slide-0.png')]:shutil.copyfile(folder/'preview'/a,folder/b)
            def native(scenes,template,source,target,images):
                (target/'presentation.pptx').write_bytes(b'editable-native');return {}
            with patch('runtime.html_deck.browser_render',side_effect=AssertionError('HTML laid out again after acceptance')),patch('runtime.html_deck.native_export',native),patch('runtime.html_deck.render',side_effect=AssertionError('PDF replaced after acceptance')):
                final=export_deck(folder,dict(htmlPhase='final',output=str(folder/'final'),slides=preview['slides'],remainingMs=30000))
            self.assertTrue(final['pptxWritten']);self.assertEqual((folder/'preview/presentation.pdf').read_bytes(),(folder/'final/presentation.pdf').read_bytes())

