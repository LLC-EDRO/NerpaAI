import unittest
from types import SimpleNamespace as O
from runtime.analysis import restore_native_order

class NativeSourceOrder(unittest.TestCase):
    def test_all_parser_foreign_keys_keep_their_identity_and_get_presentation_indices(self):
        child=O(slide_id='second',slide_index=0)
        nested={'slide_id':'first','slide_index':1}
        model=O(slides=[O(slide_id='second',source_part='slide10.xml',slide_index=0,child=child),O(slide_id='first',source_part='slide2.xml',slide_index=1)],records=[nested])
        restore_native_order(model,['slide2.xml','slide10.xml'])
        self.assertEqual([s.slide_id for s in model.slides],['first','second'])
        self.assertEqual([s.slide_index for s in model.slides],[0,1])
        self.assertEqual(child.slide_index,1);self.assertEqual(nested['slide_index'],0)
