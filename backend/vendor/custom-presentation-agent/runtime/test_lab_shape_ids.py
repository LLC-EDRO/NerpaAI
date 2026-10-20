import unittest
from runtime.security import NS,xml
from runtime.shape_ids import recover_shape_ids

class ShapeIdentityRecoveryTest(unittest.TestCase):
    def source(self,extra=''):
        part='ppt/slides/slide1.xml'
        value=('<p:sld xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"><p:cSld><p:spTree>'
               '<p:sp><p:nvSpPr><p:cNvPr id="5" name="Background"/></p:nvSpPr></p:sp>'
               '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="Table"/></p:nvGraphicFramePr></p:graphicFrame>'
               '<p:sp><p:nvSpPr><p:cNvPr id="6" name="Other"/></p:nvSpPr></p:sp>'
               '</p:spTree></p:cSld>'+extra+'</p:sld>').encode()
        return part,{part:value,'ppt/media/keep.png':b'unchanged'}

    def test_recovers_table_identity_without_modifying_original_or_other_ids(self):
        part,parts=self.source();before=dict(parts);result,repairs=recover_shape_ids(parts)
        self.assertEqual(parts,before)
        self.assertEqual(xml(result[part]).xpath('.//p:cNvPr/@id',namespaces=NS),['5','7','6'])
        self.assertEqual(result['ppt/media/keep.png'],parts['ppt/media/keep.png'])
        self.assertEqual(repairs,[dict(part=part,originalId='5',recoveredId='7')])
        self.assertEqual(recover_shape_ids(result),(result,[]))

    def test_does_not_guess_ambiguous_animation_or_connector_target(self):
        for reference in ['<p:spTgt spid="5"/>','<a:stCxn id="5" idx="0"/>','<p:bldP spid="5"/>']:
            _,parts=self.source(reference)
            self.assertEqual(recover_shape_ids(parts),(parts,[]))
