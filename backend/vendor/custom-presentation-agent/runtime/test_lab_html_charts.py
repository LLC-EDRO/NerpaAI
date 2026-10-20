import unittest
from copy import deepcopy
from runtime.html_charts import chart_svg,apply_native_chart_density
from runtime.html_deck import describe_layout,compose_slide
from runtime.security import xml,NS
from runtime.chart_builder import add_data_chart

class HtmlChartDensityTest(unittest.TestCase):
    def test_authored_chart_keeps_html_title_and_scale_without_changing_data(self):
        tree=xml(('<p:spTree xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"/>').encode())
        rels=xml(('<Relationships xmlns="'+NS['pr']+'"/>').encode());types=xml(('<Types xmlns="'+NS['ct']+'"/>').encode());parts={}
        style=dict(font='Arial',ink='#202020',accent='#286A78');bounds=dict(x=20,y=100,w=600,h=300)
        part=add_data_chart(tree,1,bounds,style,parts,rels,types,'title-scale','bar',1)
        before=deepcopy(parts);data=dict(type='bar',title='Confirmed units and period',categories=['A','B'],series=[dict(name='Values',values=[68.82,14.16])])
        apply_native_chart_density(parts,part,data,bounds,style,authored=True);after=xml(parts[part])
        self.assertEqual(after.xpath('.//c:title//a:t/text()',namespaces=NS),[data['title']])
        self.assertEqual(after.find('.//c:autoTitleDeleted',NS).get('val'),'0')
        self.assertEqual(float(after.find('.//c:valAx/c:scaling/c:max',NS).get('val')),68.82)
        self.assertEqual(float(after.find('.//c:valAx/c:majorUnit',NS).get('val')),68.82/4)
        self.assertEqual(xml(before[part]).xpath('.//c:pt/c:v/text()',namespaces=NS),after.xpath('.//c:pt/c:v/text()',namespaces=NS))
        self.assertEqual({k:v for k,v in parts.items() if k.endswith('.xlsx')},{k:v for k,v in before.items() if k.endswith('.xlsx')})

    def test_dense_chart_keeps_every_point_and_full_labels_without_overlapping_value_text(self):
        data=dict(type='bar',title='Плановые значения',categories=['Длинное название '+str(i) for i in range(24)],series=[dict(name='Метод '+str(s),values=list(range(s,24+s))) for s in range(6)])
        before=deepcopy(data);svg=xml(chart_svg(dict(data=data,box=dict(w=800,h=320)),dict(font='Arial',ink='#202020',accent='#286A78')).encode())
        self.assertEqual(data,before)
        self.assertEqual(len(svg.xpath('.//*[@data-chart-value]')),144)
        self.assertEqual(len(svg.xpath('.//*[@data-chart-label="legend"]')),6)
        self.assertFalse(svg.xpath('.//*[@data-chart-label="value"]'))
        for category in data['categories']:self.assertTrue(any(category in value for value in svg.xpath('.//*[local-name()="title"]/text()')))
        self.assertNotIn('Times',str(svg.attrib))

    def test_native_density_preserves_chart_cache_and_embedded_workbook(self):
        tree=xml(('<p:spTree xmlns:p="'+NS['p']+'" xmlns:a="'+NS['a']+'"/>').encode())
        rels=xml(('<Relationships xmlns="'+NS['pr']+'"/>').encode());types=xml(('<Types xmlns="'+NS['ct']+'"/>').encode());parts={}
        style=dict(font='Arial',ink='#202020',accent='#286A78');bounds=dict(x=20,y=100,w=600,h=300)
        part=add_data_chart(tree,1,bounds,style,parts,rels,types,'density','bar',6)
        before=xml(parts[part]).xpath('.//c:pt/c:v/text()',namespaces=NS)
        books={name:value for name,value in parts.items() if name.endswith('.xlsx')}
        data=dict(type='bar',categories=['Участок '+str(i) for i in range(24)],series=[dict(name=str(s),values=list(range(24))) for s in range(6)])
        apply_native_chart_density(parts,part,data,bounds,style)
        after=xml(parts[part]);self.assertEqual(before,after.xpath('.//c:pt/c:v/text()',namespaces=NS))
        self.assertEqual(books,{name:value for name,value in parts.items() if name.endswith('.xlsx')})
        self.assertEqual(after.find('.//c:dLbls/c:showVal',NS).get('val'),'0')
        self.assertGreater(int(after.find('.//c:catAx/c:tickLblSkip',NS).get('val')),1)
        self.assertEqual(after.find('.//c:catAx/c:tickLblPos',NS).get('val'),'low')
