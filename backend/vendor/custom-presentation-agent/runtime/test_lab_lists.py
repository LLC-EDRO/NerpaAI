import unittest
import pymupdf
from runtime.text_frames import number_label, NUMBER_SCHEMES, TemplateParagraph, TemplateTextFrame, TemplateTextFitter
from app.text.replacement import replacement_paragraph_sources

class NativeListsTest(unittest.TestCase):
    def test_mixed_heading_and_list_skip_old_blank_spacers_without_losing_first_number(self):
        self.assertEqual(replacement_paragraph_sources([True,False,True,True],['Заголовок','Первый','Второй']),[0,2,3])
        self.assertEqual(replacement_paragraph_sources([True,False,True,True],['Заголовок','','Первый','Второй']),[0,1,2,3])
        self.assertEqual(replacement_paragraph_sources([True,False,True],['Заголовок','Первый','Второй']),[0,2,2])

if __name__ == '__main__':
    unittest.main()
