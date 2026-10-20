import json
import unittest
from lxml import etree, html
from runtime.html_source import compile_source_html


class SourceHtmlTest(unittest.TestCase):
    def fixture(self):
        layout=dict(id='source-1',part='ppt/slides/slide1.xml',slots=[dict(shapeId=7,role='title',x=72,y=36,w=300,h=60,font='Inter',size=24,color='#123456',align='center',text='OLD TITLE')],sourceObjects=[],imageSlots=[])
        parts={layout['part']:b'''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="7"/></p:nvSpPr><p:txBody><a:bodyPr lIns="12700" tIns="25400"/><a:p><a:pPr algn="ctr"><a:buChar char="-"/></a:pPr><a:r><a:t>OLD TITLE</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''}
        return layout,dict(width=720,height=405),parts

    def test_source_dom_is_empty_has_stable_ids_and_css_units(self):
        layout,analysis,parts=self.fixture();result=compile_source_html(layout,analysis,parts)
        root=html.fromstring(result['html']);self.assertEqual(root.text_content(),'')
        self.assertNotIn('OLD TITLE',json.dumps(result))
        self.assertEqual(result['textRegions'][0]['box'],dict(x=96,y=48,w=400,h=80))
        self.assertEqual(result['textRegions'][0]['insets'],[2.67,9.6,4.8,1.33])
        self.assertIn('left:96.0px',result['html']);self.assertIn('data-source-shape="7"',result['html'])
        self.assertEqual(result['textRegions'][0]['paragraphs'][0]['bullet'],'-')
        self.assertEqual(result['digest'],compile_source_html(layout,analysis,parts)['digest'])

    def test_protected_and_removed_words_never_become_fillable_frames(self):
        for key in ('htmlRemoveShapeIds','htmlPreserveShapeIds'):
            layout,analysis,parts=self.fixture();layout[key]=[7]
            result=compile_source_html(layout,analysis,parts);self.assertEqual(result['textRegions'],[])
            self.assertNotIn('data-source-shape="7"',result['html'])

    def test_filled_ellipse_exposes_inside_text_relationship_without_copying_its_words(self):
        layout,analysis,parts=self.fixture();slot=layout['slots'][0]
        slot.update(role='body',text='OLD OVAL LABEL',verticalAlign='center',color='#FFFFFF')
        layout['sourceObjects']=[dict(shapeId=7,fill=dict(color='#001F82'))]
        root=etree.fromstring(parts[layout['part']]);shape=root[0][0][0]
        ns='{http://schemas.openxmlformats.org/drawingml/2006/main}'
        props=etree.SubElement(shape,'{http://schemas.openxmlformats.org/presentationml/2006/main}spPr');etree.SubElement(props,ns+'prstGeom',prst='ellipse')
        etree.SubElement(etree.SubElement(props,ns+'solidFill'),ns+'srgbClr',val='001F82')
        parts[layout['part']]=etree.tostring(root)
        result=compile_source_html(layout,analysis,parts);host=result['textRegions'][0]['container']
        self.assertEqual(host['textPlacement'],'inside');self.assertEqual(host['geometry'],'ellipse');self.assertEqual(host['fill'],'#001F82')
        self.assertGreater(host['innerBox']['x'],host['box']['x']);self.assertLess(host['innerBox']['w'],host['box']['w'])
        self.assertNotIn('OLD OVAL LABEL',json.dumps(result))

    def test_mixed_metric_and_prose_keep_their_distinct_native_styles(self):
        layout,analysis,parts=self.fixture();slot=layout['slots'][0];slot.update(role='body',size=60,color='#0077FF')
        root=etree.fromstring(parts[layout['part']]);ns='{http://schemas.openxmlformats.org/drawingml/2006/main}'
        paragraph=root.find('.//'+ns+'p');run=paragraph.find(ns+'r');props=etree.SubElement(run,ns+'rPr',sz='6000',b='1');etree.SubElement(etree.SubElement(props,ns+'solidFill'),ns+'srgbClr',val='0077FF')
        ordinary=etree.SubElement(paragraph,ns+'r');props=etree.SubElement(ordinary,ns+'rPr',sz='1800');etree.SubElement(etree.SubElement(props,ns+'solidFill'),ns+'srgbClr',val='FFFFFF');etree.SubElement(ordinary,ns+'t').text='OLD PROSE'
        parts[layout['part']]=etree.tostring(root);result=compile_source_html(layout,analysis,parts)
        styles=result['textRegions'][0]['textStyles'];self.assertEqual(styles['heading']['color'],'#0077FF');self.assertEqual(styles['body']['color'],'#FFFFFF');self.assertEqual(styles['body']['size'],24)
        self.assertNotIn('OLD PROSE',json.dumps(result))

    def test_zero_inset_rounded_host_gets_four_safe_margins_without_losing_icon_offset(self):
        layout,analysis,parts=self.fixture();layout['slots'][0].update(role='body',w=300,h=100,verticalAlign='center')
        root=etree.fromstring(parts[layout['part']]);shape=root[0][0][0];a='{http://schemas.openxmlformats.org/drawingml/2006/main}';p='{http://schemas.openxmlformats.org/presentationml/2006/main}'
        body=shape.find(p+'txBody/'+a+'bodyPr');body.attrib.update(dict(lIns='825500',rIns='0',tIns='0',bIns='0'))
        props=etree.SubElement(shape,p+'spPr');etree.SubElement(props,a+'prstGeom',prst='roundRect');etree.SubElement(etree.SubElement(props,a+'solidFill'),a+'srgbClr',val='212121')
        parts[layout['part']]=etree.tostring(root);result=compile_source_html(layout,analysis,parts);region=result['textRegions'][0]
        self.assertGreater(region['insets'][3],80,'source icon offset is retained')
        self.assertTrue(all(v>0 for v in region['insets']));self.assertLess(region['container']['innerBox']['w'],region['box']['w']-80)
        self.assertIn('justify-content:center',result['html'])

    def test_owned_illustration_text_shape_exposes_a_photo_frame_without_a_bitmap(self):
        layout,analysis,parts=self.fixture();layout.update(htmlRole='content',htmlConcept=dict(kind='figure'));layout['slots'][0].update(role='body',text='Illustration',x=220,y=90,w=420,h=220)
        result=compile_source_html(layout,analysis,parts);self.assertEqual(result['textRegions'][0]['role'],'photo');self.assertEqual(result['photoFrames'][0]['shapeId'],7);self.assertTrue(result['photoFrames'][0]['virtual'])
        layout['htmlRole']='closing';self.assertEqual(compile_source_html(layout,analysis,parts)['photoFrames'],[])

    def test_filled_heading_and_nested_caption_keep_separate_safe_text_areas(self):
        from copy import deepcopy
        layout,analysis,parts=self.fixture();layout['slots'][0].update(role='body',x=40,y=100,w=300,h=220,text='OLD HEADING')
        root=etree.fromstring(parts[layout['part']]);shape=root[0][0][0];a='{http://schemas.openxmlformats.org/drawingml/2006/main}';p='{http://schemas.openxmlformats.org/presentationml/2006/main}'
        props=etree.SubElement(shape,p+'spPr');etree.SubElement(props,a+'prstGeom',prst='roundRect');etree.SubElement(etree.SubElement(props,a+'solidFill'),a+'srgbClr',val='212121')
        caption=deepcopy(shape);caption.find('.//'+p+'cNvPr').set('id','8');caption.remove(caption.find(p+'spPr'));root[0][0].append(caption)
        layout['slots'].append(dict(shapeId=8,role='label',x=55,y=240,w=270,h=20,font='Inter',size=14,color='#FFFFFF',text='OLD CAPTION'))
        layout['sourceObjects']=[dict(shapeId=9,kind='picture',box=dict(x=55,y=210,w=20,h=20))];parts[layout['part']]=etree.tostring(root)
        result=compile_source_html(layout,analysis,parts);heading,body=result['textRegions'];group=result['textGroups'][0]
        self.assertEqual(group['origin'],'native-container');self.assertLessEqual(heading['textBox']['y']+heading['textBox']['h'],280)
        self.assertGreater(body['textBox']['h'],body['box']['h']);self.assertLessEqual(body['textBox']['y']+body['textBox']['h'],heading['box']['y']+heading['box']['h'])
        self.assertNotIn('OLD CAPTION',json.dumps(result))

    def test_short_filled_label_and_separate_label_caption_are_paired_without_merging_repeated_rows(self):
        layout,analysis,parts=self.fixture();layout['slots'][0].update(role='label',x=40,y=100,w=140,h=31,size=14,text='Note')
        root=etree.fromstring(parts[layout['part']]);shape=root[0][0][0];a='{http://schemas.openxmlformats.org/drawingml/2006/main}';p='{http://schemas.openxmlformats.org/presentationml/2006/main}'
        props=etree.SubElement(shape,p+'spPr');etree.SubElement(props,a+'prstGeom',prst='roundRect');etree.SubElement(etree.SubElement(props,a+'solidFill'),a+'srgbClr',val='000000')
        layout['slots'].append(dict(shapeId=8,role='label',x=40,y=145,w=500,h=31,font='Inter',size=14,color='#FFFFFF'))
        parts[layout['part']]=etree.tostring(root);result=compile_source_html(layout,analysis,parts)
        self.assertEqual([(g['headingShapeId'],g['bodyShapeId']) for g in result['textGroups']],[(7,8)])

    def test_original_icon_rows_keep_exact_caption_ids_for_empty_row_detection(self):
        layout,analysis,parts=self.fixture();layout['slots'][0].update(role='label',x=100,y=120,w=300,h=45)
        layout['reservedRegions']=[dict(shapeId=99,role='icon',box=dict(x=60,y=130,w=20,h=20))]
        result=compile_source_html(layout,analysis,parts);self.assertEqual(result['iconRows'][0]['textShapeId'],7);self.assertEqual(result['iconRows'][0]['iconShapeId'],99)

    def test_only_a_complete_small_number_run_is_structural_not_sample_statistics(self):
        layout,analysis,parts=self.fixture();base=dict(layout['slots'][0],role='label',y=120,w=25,h=25,size=16)
        layout['slots']=[dict(base,shapeId=7+i,x=40+i*80,text=str(i+1).zfill(2)) for i in range(3)]
        result=compile_source_html(layout,analysis,parts)
        self.assertEqual([o['ordinal'] for o in result['structuralOrdinals']],[1,2,3]);self.assertEqual(result['structuralOrdinals'][0]['digits'],2)
        layout['slots'][2]['text']='25';self.assertEqual(compile_source_html(layout,analysis,parts)['structuralOrdinals'],[])

    def test_table_grid_and_styles_survive_without_old_cell_values(self):
        layout,analysis,parts=self.fixture()
        root=etree.fromstring(parts[layout['part']]);tree=root[0][0]
        shape=etree.fromstring(b'''<p:graphicFrame xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:nvGraphicFramePr><p:cNvPr id="9"/></p:nvGraphicFramePr><a:graphic><a:graphicData><a:tbl><a:tblGrid><a:gridCol w="1270000"/><a:gridCol w="2540000"/></a:tblGrid><a:tr h="254000"><a:tc><a:txBody><a:p><a:r><a:t>OLD CELL</a:t></a:r></a:p></a:txBody><a:tcPr><a:solidFill><a:srgbClr val="ABCDEF"/></a:solidFill></a:tcPr></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>''')
        tree.append(shape);parts[layout['part']]=etree.tostring(root)
        layout['sourceObjects']=[dict(shapeId=9,kind='table',box=dict(x=40,y=80,w=300,h=200))]
        result=compile_source_html(layout,analysis,parts);frame=result['dataFrames'][0]
        self.assertEqual(frame['columnWidths'],[133.33,266.67]);self.assertEqual(frame['rowHeights'],[26.67])
        self.assertEqual(frame['cellStyles'],[[dict(fill='#ABCDEF')]])
        self.assertNotIn('OLD CELL',json.dumps(result));self.assertIn('data-visual="table"',result['html'])

    def test_source_font_is_escaped_and_unsupported_rotation_is_explicit(self):
        layout,analysis,parts=self.fixture();layout['slots'][0]['font']='x" onload="bad'
        root=etree.fromstring(parts[layout['part']]);shape=root[0][0][0]
        ns='{http://schemas.openxmlformats.org/drawingml/2006/main}'
        props=etree.SubElement(shape,'{http://schemas.openxmlformats.org/presentationml/2006/main}spPr')
        etree.SubElement(props,ns+'xfrm',rot='5400000');parts[layout['part']]=etree.tostring(root)
        result=compile_source_html(layout,analysis,parts)
        self.assertFalse(html.fromstring(result['html']).xpath('//*[@onload]'))
        self.assertEqual(result['unsupported'][0]['feature'],'rotated_text')

    def test_repeated_rows_are_distinct_from_the_introductory_aside(self):
        layout,analysis,parts=self.fixture()
        for i,(x,y,w) in enumerate([(30,180,180),(300,60,350),(300,170,350),(300,280,350),(300,390,350)]):
            for offset,role,top in [(0,'label',y),(1,'body',y+25)]:
                layout['slots'].append(dict(shapeId=20+i*2+offset,role=role,x=x,y=top,w=w,h=20,font='Inter',size=14,color='#123456'))
        result=compile_source_html(layout,analysis,parts)
        self.assertEqual(len(result['textGroups']),5)
        self.assertEqual(result['textGroups'][0]['role'],'lead-or-aside')
        for group in result['textGroups'][1:]:
            self.assertEqual(group['role'],'repeated-content');self.assertEqual(len(group['peerGroupIds']),3)

    def test_a_heading_free_large_statistic_is_a_metric_frame_not_a_new_headline(self):
        layout,analysis,parts=self.fixture();layout['htmlTitleShapeId']=None
        layout['slots'][0].update(text='89,526,124',size=96)
        result=compile_source_html(layout,analysis,parts)
        self.assertEqual(result['textRegions'][0]['role'],'metric');self.assertNotIn('89,526,124',result['html'])

    def test_original_patterned_body_is_flagged_before_model_authoring(self):
        import tempfile
        from pathlib import Path
        from PIL import Image,ImageDraw
        from runtime.html_deck import describe_layout,readable_ink
        layout,analysis,parts=self.fixture();layout.update(index=0,htmlRole='content')
        layout['slots'].append(dict(shapeId=8,role='body',text='Old sample body',x=40,y=150,w=200,h=100,font='Inter',size=14,color='#FFFFFF'))
        style=describe_layout(layout,analysis);style['sourceHtml']=compile_source_html(layout,analysis,parts)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'art.png';image=Image.new('RGB',(720,405),'white');draw=ImageDraw.Draw(image)
            for x in range(0,300,24):draw.rectangle((x,0,x+11,405),fill='#F05A24');draw.rectangle((x+12,0,x+23,405),fill='#258FC0')
            image.save(path);readable_ink(style,path,720,405)
        self.assertTrue(style['safeSourceSurfaces']);self.assertIn(8,[a['shapeId'] for a in style['unsafeTextAnchors']])


if __name__=='__main__':unittest.main()
