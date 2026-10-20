import unittest
from types import SimpleNamespace as O
from runtime.security import NS,xml
from runtime.typography import inherited_vertical_alignment

class AlignmentTest(unittest.TestCase):
    def test_inherited_center_and_explicit_override(self):
        self.assertEqual(inherited_vertical_alignment({'text_frame':{'style_layers':[{'body_attributes':{'anchor':'ctr'}},{'body_attributes':{}}]}}),'center')
        self.assertEqual(inherited_vertical_alignment(O(text_frame=O(style_layers=[O(body_attributes={'anchor':'ctr'}),O(body_attributes={'anchor':'b'})]))),'bottom')
