"""Real native table parse/resize/fill/assembly without models or converters."""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from app.presentation.parser import PresentationParser
from runtime.security import NS, xml, read_package
from runtime.table_builder import add_data_table
from runtime.tables import table_slots

STYLE = dict(font='DejaVu Sans', bodySize=18, ink='#202020', accent='#0133A3', onAccent='#FFFFFF', surface='#FFFFFF')
BOX = dict(x=42.125, y=144.25, w=803.333, h=300.125)

def slide_root():
    return xml(f'''<p:sld xmlns:p="{NS['p']}" xmlns:a="{NS['a']}" xmlns:r="{NS['r']}"><p:cSld><p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
      <p:sp><p:nvSpPr><p:cNvPr id="4" name="Existing brand"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="254000" cy="254000"/></a:xfrm><a:solidFill><a:srgbClr val="0133A3"/></a:solidFill></p:spPr></p:sp>
      </p:spTree></p:cSld></p:sld>'''.encode())

def package(source, root):
    parts = {
        '[Content_Types].xml': f'''<Types xmlns="{NS['ct']}"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
          <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
          <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
          <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
          <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/></Types>'''.encode(),
        '_rels/.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="presentation" Type="{NS["r"]}/officeDocument" Target="ppt/presentation.xml"/></Relationships>'.encode(),
        'ppt/presentation.xml': f'<p:presentation xmlns:p="{NS["p"]}" xmlns:r="{NS["r"]}"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="master"/></p:sldMasterIdLst><p:sldIdLst><p:sldId id="256" r:id="slide"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'.encode(),
        'ppt/_rels/presentation.xml.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="slide" Type="{NS["r"]}/slide" Target="slides/slide1.xml"/><Relationship Id="master" Type="{NS["r"]}/slideMaster" Target="slideMasters/slideMaster1.xml"/></Relationships>'.encode(),
        'ppt/slides/slide1.xml': etree.tostring(root),
        'ppt/slides/_rels/slide1.xml.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="layout" Type="{NS["r"]}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>'.encode(),
        'ppt/slideMasters/slideMaster1.xml': f'<p:sldMaster xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="layout"/></p:sldLayoutIdLst></p:sldMaster>'.encode(),
        'ppt/slideMasters/_rels/slideMaster1.xml.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="layout" Type="{NS["r"]}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>'.encode(),
        'ppt/slideLayouts/slideLayout1.xml': f'<p:sldLayout xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}" type="blank"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'.encode(),
        'ppt/slideLayouts/_rels/slideLayout1.xml.rels': f'<Relationships xmlns="{NS["pr"]}"><Relationship Id="master" Type="{NS["r"]}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>'.encode(),
    }
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)

class DataTableBuilder(unittest.TestCase):
    def build(self, columns=4, data_rows=3, **kwargs):
        root = slide_root()
        table = add_data_table(root.find('p:cSld/p:spTree', NS), 50, kwargs.get('box', BOX), kwargs.get('style', STYLE), columns, data_rows)
        return root, table

    def test_native_grid_exact_geometry_and_template_style(self):
        before = slide_root().find('.//p:sp', NS)
        root, table = self.build()
        self.assertEqual(etree.tostring(root.find('.//p:sp', NS)), etree.tostring(before))
        # This URI identifies a table to PowerPoint/LibreOffice; the parser can
        # still extract a:tbl from an unrecognized graphicData payload.
        self.assertEqual(table.getparent().get('uri'), 'http://schemas.openxmlformats.org/drawingml/2006/table')
        self.assertEqual(len(table.findall('a:tr', NS)), 4)
        self.assertTrue(all(len(row.findall('a:tc', NS)) == 4 for row in table.findall('a:tr', NS)))
        self.assertEqual(sum(int(column.get('w')) for column in table.findall('a:tblGrid/a:gridCol', NS)), round(BOX['w'] * 12700))
        self.assertEqual(sum(int(row.get('h')) for row in table.findall('a:tr', NS)), round(BOX['h'] * 12700))
        self.assertEqual({p.get('typeface') for p in table.findall('.//a:latin', NS)}, {'DejaVu Sans'})
        rows = table.findall('a:tr', NS)
        self.assertEqual({p.get('val') for p in rows[0].findall('.//a:rPr/a:solidFill/a:srgbClr', NS)}, {'FFFFFF'})
        self.assertEqual({p.get('val') for p in rows[1].findall('.//a:rPr/a:solidFill/a:srgbClr', NS)}, {'202020'})
        self.assertFalse(root.findall('.//p:pic', NS))
        self.assertTrue(all(not any(character.isdigit() for character in (text.text or '')) for text in table.findall('.//a:t', NS)), 'capacity labels cannot become apparent statistical evidence')

    def test_invalid_identity_grid_style_and_unreadable_capacity_are_rejected_without_mutation(self):
        root = slide_root(); tree = root.find('p:cSld/p:spTree', NS); before = etree.tostring(root)
        variations = [
            dict(shape_id=4), dict(shape_id=True), dict(columns=1), dict(columns=9), dict(data_rows=0), dict(data_rows=10),
            dict(box={**BOX, 'w': float('nan')}), dict(box={**BOX, 'x': -1}), dict(box={**BOX, 'h': 1}),
            dict(style={**STYLE, 'accent': 'url(unsafe)'}), dict(style={**STYLE, 'font': ''}), dict(style={**STYLE, 'bodySize': 0}),
        ]
        for variation in variations:
            values = dict(tree=tree, shape_id=50, box=BOX, style=STYLE, columns=4, data_rows=3)
            values.update(variation)
            with self.subTest(variation=variation), self.assertRaises(ValueError):
                add_data_table(**values)
            self.assertEqual(etree.tostring(root), before)


if __name__ == '__main__':
    unittest.main()
