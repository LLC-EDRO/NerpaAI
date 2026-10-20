import unittest
from runtime.html_shape_edits import editable_shape_ids,render_edited_backgrounds

class ShapeEditTest(unittest.TestCase):
    def test_only_unbranded_content_furniture_can_be_modernized(self):
        def shape(identity,y,role='body',kind='shape'):
            return dict(shapeId=identity,kind=kind,canRemove=True,fill=dict(color='#001F82'),role=role,box=dict(x=80,y=y,w=200,h=60))
        layout=dict(htmlRole='content',htmlTitleShapeId=8,slots=[dict(shapeId=8,y=0,h=70)],htmlPreserveShapeIds=[13],
            sourceObjects=[shape(2,140),shape(3,0),shape(4,140,'logo'),shape(8,140),shape(12,140,'body','chart'),shape(13,140),shape(14,140)],
            reservedRegions=[dict(shapeId=14,role='brand')])
        self.assertEqual(editable_shape_ids(layout,960,540),{2})
        layout['htmlRole']='cover';self.assertFalse(editable_shape_ids(layout,960,540))

    def test_detached_native_paint_is_edited_in_svg_without_converting_the_background_again(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        original=dict(id='slide',htmlRole='content',sourceObjects=[dict(shapeId=2,kind='shape',canRemove=True,fill=dict(color='#0077FF'),role='body',box=dict(x=80,y=140,w=200,h=60))])
        art=dict(objects=[dict(shapeId=2,svg='<g xmlns="http://www.w3.org/2000/svg" data-source-object="2"><rect width="100" height="100"/></g>')])
        scene=dict(sourceLayoutId='slide',sourceShapeEdits=[dict(shapeId=2,action='remove')],sourceDesign=dict(artwork=[dict(shapeId=2)]))
        template=dict(layouts=[dict(id='slide',nativeBackground='html-native-background-0.png',sourceHtml=dict(nativeArt=art))])
        with TemporaryDirectory() as folder:
            render_edited_backgrounds([scene],template,dict(width=960,height=540,sha256='test',layouts=[original]),Path(folder),'/nonexistent/soffice')
        self.assertNotIn('sourceBackground',scene);self.assertEqual(scene['sourceDesign']['artwork'],[])
        self.assertEqual(scene['sourceShapeEdits'],[dict(shapeId=2,action='remove')])

    def test_optional_background_timeout_restores_design_and_keeps_the_slide_deliverable(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import subprocess
        from runtime.security import NS
        original=dict(id='slide',htmlRole='content',slots=[],sourceObjects=[dict(shapeId=2,kind='shape',canRemove=True,fill=dict(color='#0077FF'),role='body',box=dict(x=80,y=140,w=200,h=60))])
        design=dict(artwork=[dict(shapeId=2),dict(shapeId=99,role='logo')])
        scene=dict(index=4,sourceLayoutId='slide',sourceShapeEdits=[dict(shapeId=2,action='remove')],sourceDesign=design)
        template=dict(layouts=[dict(id='slide',sourceHtml=dict(nativeArt=dict(objects=[])))])
        parts={'ppt/slides/labSlide1.xml':f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:spTree/></p:cSld></p:sld>'.encode()}
        with TemporaryDirectory() as folder:
            with patch('runtime.assemble.assemble',lambda _a,_b,_c,target:target.write_bytes(b'fixture')),patch('runtime.html_shape_edits.read_package',return_value=parts),patch('runtime.render.render',side_effect=subprocess.TimeoutExpired('soffice',15)):
                render_edited_backgrounds([scene],template,dict(width=960,height=540,sha256='test',layouts=[original]),Path(folder),'/soffice')
        self.assertEqual(scene['sourceShapeEdits'],[]);self.assertNotIn('sourceBackground',scene)
        self.assertEqual(scene['sourceDesign'],design);self.assertEqual(scene['warnings'][0]['slide'],5)
        self.assertEqual(scene['warnings'][0]['reason'],'html_shape_edit_unavailable')

if __name__=='__main__':unittest.main()
