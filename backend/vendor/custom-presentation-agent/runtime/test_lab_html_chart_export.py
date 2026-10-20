import base64
import io
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from PIL import Image
from runtime.html_chart_export import chart_presentation,capture_chart_pictures,chart_picture_bytes,MAX_PICTURE_BYTES
from runtime.html_charts import chart_svg
from runtime.security import xml


class HtmlChartExportTest(unittest.TestCase):
    def chart(self):
        return dict(data=dict(type='line',title='Measured series',categories=['2024','2025','2026'],series=[dict(name='EUR',values=[-12.5,0,120.25])]),box=dict(x=40,y=80,w=620,h=270))

    def test_standard_charts_remain_native_and_image_choice_requires_a_visual_reason(self):
        self.assertEqual(chart_presentation()['mode'],'native')
        self.assertEqual(chart_presentation(dict(mode='image',reason=''))['mode'],'native')
        self.assertEqual(chart_presentation(dict(mode='image',reason='Custom visual labels'))['mode'],'image')
        self.assertEqual(chart_presentation(dict(mode='auto',treatment='gradient'))['mode'],'image')
        self.assertEqual(chart_presentation(dict(mode='native',treatment='soft-area'),kind='bar')['treatment'],'plain')
        self.assertEqual(chart_presentation(css='.plot svg polyline{filter:drop-shadow(1px 1px 2px red)}')['mode'],'image')

    def test_special_html_treatments_never_change_verified_series_or_categories(self):
        chart=self.chart();before=deepcopy(chart['data'])
        for treatment in ('gradient','soft-area'):
            with self.subTest(treatment=treatment):
                root=xml(chart_svg(dict(chart,presentation=dict(treatment=treatment)),dict(font='Arial',ink='#222222',accent='#224499')).encode())
                self.assertEqual([float(n.get('data-chart-value')) for n in root.xpath('.//*[@data-chart-value]')],[-12.5,0,120.25])
                if treatment=='gradient':self.assertTrue(root.xpath('.//*[local-name()="linearGradient"]'))
                else:self.assertTrue(root.xpath('.//*[local-name()="polygon" and @opacity=".16"]'))
        self.assertEqual(chart['data'],before)

    def test_picture_is_a_bounded_crop_of_the_actual_accepted_pdf_and_data_survive(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            with pymupdf.open() as pdf:
                page=pdf.new_page(width=720,height=405);page.draw_rect(pymupdf.Rect(40,80,660,350),color=(0,0,.5),fill=(.9,.95,1));page.insert_text((80,120),'Exact HTML values: -12.5 / 0 / 120.25');pdf.save(output/'html-preview.pdf')
            scene=dict(chart=dict(self.chart(),presentation=dict(mode='image',reason='Specific visual')),index=0)
            before=deepcopy(scene['chart']['data']);capture_chart_pictures([scene],output)
            payload=chart_picture_bytes(scene['chart']);self.assertIsNotNone(payload);self.assertLessEqual(len(payload),MAX_PICTURE_BYTES)
            with Image.open(io.BytesIO(payload)) as image:self.assertEqual(image.size,(1240,540))
            self.assertEqual(scene['chart']['data'],before)
            native=dict(chart=self.chart());capture_chart_pictures([native],output);self.assertNotIn('picture',native['chart'])

    def test_untrusted_picture_fields_cannot_load_paths_or_unbounded_images(self):
        for value in [dict(encoding='file',data='/etc/passwd'),dict(encoding='png-base64',data='a'*(MAX_PICTURE_BYTES*2)),dict(encoding='png-base64',data=base64.b64encode(b'not a PNG').decode())]:
            self.assertIsNone(chart_picture_bytes(dict(picture=value)))

    def test_authored_chart_policy_survives_scene_construction_and_editor_revision(self):
        from runtime.test_lab_html_author import HtmlAuthorTest
        from runtime.html_deck import compose_slide
        from runtime.html_revision import edited_html_scene
        fixture=HtmlAuthorTest();copy=fixture.copy();copy.update(chart=self.chart()['data'],chartPresentation=dict(mode='auto',treatment='gradient',reason='Source chart gradient'),
            html='<main><h1 data-text="title"></h1><div data-visual="chart"></div><p data-text="paragraphs.0"></p></main>')
        scene=compose_slide(copy,fixture.style(),0,[])
        self.assertEqual(scene['chart']['presentation']['mode'],'image')
        edited=edited_html_scene(dict(native=dict(html=scene,fields={})))
        self.assertEqual(edited['chart'],scene['chart'])
