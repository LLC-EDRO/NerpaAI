import io,tempfile,unittest
from pathlib import Path
from PIL import Image
from runtime.html_brand_assets import composite_brand_assets
from runtime.security import NS

class BrandAssetsTest(unittest.TestCase):
    def test_original_brand_bitmap_is_restored_without_copying_sample_text_or_other_pictures(self):
        picture=lambda identity,rid:f'<p:pic><p:nvPicPr><p:cNvPr id="{identity}"/></p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/></p:blipFill></p:pic>'
        slide=f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree>{picture(7,"rId1")}{picture(8,"rId2")}</p:spTree></p:cSld></p:sld>'
        image=io.BytesIO();Image.new('RGBA',(20,10),'white').save(image,format='PNG')
        parts={'ppt/slides/slide1.xml':slide.encode(),'ppt/slides/_rels/slide1.xml.rels':f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="rId1" Target="../media/logo.png"/><Relationship Id="rId2" Target="../media/logo.png"/></Relationships>'.encode(),'ppt/media/logo.png':image.getvalue()}
        layout=dict(part='ppt/slides/slide1.xml',sourceObjects=[dict(shapeId=7,kind='picture',role='logo',box=dict(x=70,y=5,w=20,h=10)),dict(shapeId=8,kind='picture',role='content',box=dict(x=10,y=30,w=20,h=10))])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'background.png';Image.new('RGB',(100,60),'#001F82').save(path)
            self.assertEqual(composite_brand_assets(path,layout,parts,100,60),1)
            result=Image.open(path);self.assertEqual(result.getpixel((75,8)),(255,255,255));self.assertEqual(result.getpixel((15,33)),(0,31,130))

if __name__=='__main__':unittest.main()
