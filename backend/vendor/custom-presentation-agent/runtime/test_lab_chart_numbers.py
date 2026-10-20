import unittest
from runtime.chart_numbers import number_label,value_domain
from runtime.html_charts import chart_svg,apply_native_chart_density
from runtime.security import xml,NS
from runtime.test_lab_style_data_charts import StyleDataChartsTest

class ChartReadabilityTest(unittest.TestCase):
    def test_formatted_labels_do_not_expose_float_noise_or_scientific_notation(self):
        self.assertEqual(number_label(61869.082498576),'61,87 тыс.')
        self.assertEqual(number_label(1_420_000_000),'1,42 млрд')
        self.assertEqual(number_label(.12),'0,12')
        self.assertEqual(number_label(0),'0')
        self.assertEqual(number_label(-12.345),'-12,35')

    def test_time_series_uses_local_labelled_scale_but_bars_keep_zero(self):
        data=dict(type='line',title='Концентрация CO₂, ppm',categories=['2000','2025'],series=[dict(name='CO₂',values=[369.71,427.35])])
        low,high=value_domain(data)
        self.assertGreater(low,300);self.assertLess(low,369.71);self.assertGreater(high,427.35)
        style=dict(font='Arial',ink='#222222',accent='#3159B6')
        svg=chart_svg(dict(data=data,box=dict(w=600,h=300)),style)
        self.assertIn('369,71',svg);self.assertIn('427,35',svg)
        root=xml(svg.encode());points=root.xpath('.//*[local-name()="circle"]')
        self.assertGreater(abs(float(points[0].get('cy'))-float(points[1].get('cy'))),100)
        parts,part,_=StyleDataChartsTest().native(data,style)
        apply_native_chart_density(parts,part,data,dict(w=600,h=300),style,authored=True)
        root=xml(parts[part]);scaling=root.find('.//c:valAx/c:scaling',NS)
        self.assertAlmostEqual(float(scaling.find('c:min',NS).get('val')),low)
        self.assertAlmostEqual(float(scaling.find('c:max',NS).get('val')),high)
        self.assertEqual(value_domain(dict(data,type='bar'))[0],0)

    def test_editable_horizontal_chart_keeps_html_category_order_and_display_precision(self):
        data=dict(type='bar-horizontal',title='ВВП',categories=['A','B'],series=[dict(name='USD',values=[61869.082498576,2229.71])])
        style=dict(font='Arial',ink='#222222',accent='#3159B6')
        parts,part,_=StyleDataChartsTest().native(data,style)
        apply_native_chart_density(parts,part,data,dict(w=600,h=300),style,authored=True)
        root=xml(parts[part])
        self.assertEqual(root.find('.//c:catAx/c:scaling/c:orientation',NS).get('val'),'maxMin')
        self.assertEqual(root.find('.//c:dLbls/c:numFmt',NS).get('formatCode'),'0.##," тыс."')
        self.assertEqual(root.xpath('.//c:ser/c:val/c:numRef/c:numCache/c:pt/c:v/text()',namespaces=NS),['61869.082498576','2229.71'])
