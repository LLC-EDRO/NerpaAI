import copy
import unittest
from runtime.html_revision import edited_html_scene,seal_html_revision


class HtmlRevisionTest(unittest.TestCase):
    def fixture(self):
        scene=dict(sourceLayoutId='source',title='Before',notes='',speech='',texts=[dict(key='h_title',text='Before',x=10,y=10,w=200,h=40,size=30,font='Inter',color='#123456',bold=True,align='left')],cells=[],
                   authored=dict(html='<h1 data-text="title"></h1>',css='h1{margin:0}',bindings=dict(title='h_title')),
                   images=[dict(image='old.png',shapeId=7,slotIndex=0,x=300,y=100,w=200,h=150)])
        seal_html_revision(scene)
        return dict(native=dict(html=scene,fields=dict(h_title='Before')),images=[dict(image='old.png',shapeId=7,slotIndex=0)])

    def test_text_style_and_photo_edits_update_one_revision_without_mutating_previous(self):
        slide=self.fixture();before=copy.deepcopy(slide);old=slide['native']['html']['htmlRevision']['digest']
        slide['native']['fields']['h_title']='After';slide['textStyles']={'native.fields.h_title':dict(size=36,w=240)}
        slide['images'][0]['image']='new.png'
        scene=edited_html_scene(slide);revision=seal_html_revision(scene)
        self.assertEqual(scene['title'],'After');self.assertEqual(scene['texts'][0]['size'],36)
        self.assertEqual(scene['images'][0]['image'],'new.png');self.assertEqual(scene['authored'],before['native']['html']['authored'])
        self.assertNotEqual(revision['digest'],old);self.assertEqual(revision['parentDigest'],old)
        self.assertEqual(seal_html_revision(scene),revision);self.assertEqual(slide['native']['html'],before['native']['html'])

    def test_reopening_unchanged_inputs_keeps_exact_revision(self):
        slide=self.fixture();scene=edited_html_scene(slide)
        self.assertEqual(seal_html_revision(scene),slide['native']['html']['htmlRevision'])

    def test_browser_measurement_noise_keeps_revision_but_real_style_and_data_changes_do_not(self):
        scene=self.fixture()['native']['html'];scene['texts'][0]['lineHeight']=1.1599961428640309
        original=seal_html_revision(scene)
        scene['texts'][0]['lineHeight']=1.1600014999973216
        self.assertEqual(seal_html_revision(scene),original)
        scene['texts'][0]['size']+=.01
        self.assertNotEqual(seal_html_revision(scene)['digest'],original['digest'])
        # Scientific values are not geometry and must never be rounded away.
        scene['chart']=dict(data=dict(series=[dict(values=[.0000001,.0000002])]))
        before=seal_html_revision(scene)['digest'];scene['chart']['data']['series'][0]['values'][0]=.00000011
        self.assertNotEqual(seal_html_revision(scene)['digest'],before)


if __name__=='__main__':unittest.main()
