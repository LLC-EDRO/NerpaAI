import tempfile,unittest
from pathlib import Path
import pymupdf
from runtime.html_repair_acceptance import accept_repair,repair_score

class HtmlRepairAcceptanceTest(unittest.TestCase):
    def pdf(self,path,labels):
        with pymupdf.open() as doc:
            for label in labels:doc.new_page(width=720,height=405).insert_text((40,80),label)
            doc.save(path)

    def test_a_regressing_slide_restores_its_html_pdf_preview_artwork_and_scene_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);out=folder/'output';out.mkdir()
            self.pdf(folder/'html-proof.pdf',['BASE ONE','BASE TWO']);self.pdf(out/'html-preview.pdf',['NEW ONE','BAD TWO'])
            document=lambda a,b:f'<html><body><section data-slide="0">{a}</section><section data-slide="1">{b}</section></body></html>'
            (folder/'html-proof.html').write_text(document('BASE ONE','BASE TWO'));(out/'presentation.html').write_text(document('NEW ONE','BAD TWO'))
            (folder/'html-proof-slide-1.png').write_bytes(b'base-preview');(folder/'html-proof-background-1.png').write_bytes(b'base-art')
            old=[dict(native=dict(html=dict(index=i,title=f'BASE {i}',authoredBackground=f'authored-background-{i}.png'))) for i in range(2)]
            scenes=[dict(index=i,title=f'NEW {i}') for i in range(2)]
            baseline=dict(slides=old,warnings=[]);warnings=[dict(slide=2,key='body',reason='html_text_overlap')]
            chosen,findings,reverted=accept_repair(scenes,warnings,baseline,[1,2],folder,out)
            self.assertEqual(reverted,[2]);self.assertEqual(chosen[0]['title'],'NEW 0');self.assertEqual(chosen[1]['title'],'BASE 1')
            self.assertNotIn('repairRejected',old[1]['native']['html'])
            self.assertIn('BASE TWO',(out/'presentation.html').read_text());self.assertNotIn('BAD TWO',(out/'presentation.html').read_text())
            self.assertEqual((out/'slide-1.png').read_bytes(),b'base-preview');self.assertEqual((out/'authored-background-1.png').read_bytes(),b'base-art')
            with pymupdf.open(out/'html-preview.pdf') as pdf:
                self.assertEqual(len(pdf),2);self.assertIn('NEW ONE',pdf[0].get_text());self.assertIn('BASE TWO',pdf[1].get_text())
            self.assertEqual([w['reason'] for w in findings],['html_visual_repair_reverted'])

    def test_duplicate_findings_do_not_bias_candidate_acceptance(self):
        warning=dict(slide=1,key='body',reason='html_text_overflow')
        self.assertEqual(repair_score([warning,warning],1),5)
        scenes=[dict(index=0)];baseline=dict(slides=[dict(native=dict(html=dict(index=0)))],warnings=[warning])
        self.assertEqual(accept_repair(scenes,[],baseline,[1],Path('/unused'),Path('/unused'))[2],[])
