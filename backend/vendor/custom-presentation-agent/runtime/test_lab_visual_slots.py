import unittest
from runtime.layout_metadata import visual_slots,has_text
from runtime.security import NS
class VisualSlots(unittest.TestCase):
    def test_empty_picture_placeholder_and_placeholder_with_text(self):
        part='ppt/slides/any.xml'
        parts={part:f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:sp><p:nvSpPr><p:cNvPr id="917"/><p:cNvSpPr/><p:nvPr><p:ph type="pic"/></p:nvPr></p:nvSpPr></p:sp></p:sld>'.encode()}
        item=dict(shape_id=917,object_kind='shape',placeholder_type='pic',source_part=part,
                  geometry=dict(x_emu=0,y_emu=0,width_emu=100*12700,height_emu=80*12700))
        self.assertFalse(has_text(item))
        slots=visual_slots([item],dict(part=part,slots=[]),{},parts)
        self.assertEqual(len(slots),1)
        self.assertEqual(slots[0]['kind'],'placeholder')
        item['rich_text']={'paragraphs':[{'runs':[{'text':'Actual text'}]}]}
        self.assertTrue(has_text(item))
        self.assertEqual(visual_slots([item],dict(part=part,slots=[]),{},parts),[])
    def setUp(self):
        self.slot=dict(shapeId=42,kind='picture',box=dict(x=10,y=10,w=100,h=80),aspectRatio=1.25,protected=False,requiresOpaque=False)
        self.slide=dict(native=dict(mode='source'),visualSlotsVersion=1,images=[dict(shapeId=42,slotIndex=0,image='generated.png',background='transparent')])
