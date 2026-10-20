import tempfile
import unittest
from pathlib import Path
import pymupdf
from PIL import Image
from runtime.pdf_preview import pdf_preview


class PdfPreviewTest(unittest.TestCase):
    def test_gallery_preview_rasterizes_the_requested_page_without_changing_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'previews').mkdir();source=folder/'previews/presentation.pdf'
            with pymupdf.open() as pdf:
                for ink in [(1,0,0),(0,0,1)]:
                    page=pdf.new_page(width=720,height=405);page.draw_rect(page.rect,color=ink,fill=ink)
                pdf.save(source)
            before=source.read_bytes();output=folder/'out'
            self.assertEqual(pdf_preview(folder,dict(output=str(output),page=1)),dict(page=1))
            with Image.open(output/'slide-0.png') as image:
                self.assertEqual(image.size,(1280,720));self.assertEqual(image.getpixel((640,360)),(0,0,255))
            self.assertEqual(source.read_bytes(),before)
            for page in [-1,2,True]:
                with self.assertRaisesRegex(ValueError,'pptx_preview_page_invalid'):pdf_preview(folder,dict(output=str(output),page=page))
