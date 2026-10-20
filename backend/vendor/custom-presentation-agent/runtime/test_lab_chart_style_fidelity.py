import unittest
from copy import deepcopy
from runtime.chart_builder import chart_presentation_style,select_chart_style
from runtime.html_charts import chart_svg
from runtime.html_chart_export import chart_presentation
from runtime.html_chart_theme import monotone_path
from runtime.security import xml


class ChartStyleFidelityTest(unittest.TestCase):
    def style(self):
        return dict(font='Arial',ink='#202020',accent='#0078FF',chartBackground='#FFFFFF')

    def chart(self,kind='bar'):
        return dict(box=dict(w=650,h=320),data=dict(type=kind,title='Наблюдения',categories=['А','Б','В'],series=[dict(name='Измерение',values=[10,40,50])]))

    def test_matching_family_beats_first_ring_and_incompatible_local_profile(self):
        ring=dict(type='donut',palette=['#00CCCC'],axes=False,confidence=.99)
        bars=dict(type='bar',palette=['#0078FF'],axes=True,confidence=.9)
        style=dict(self.style(),chartStyle=ring,chartStyles=[ring,bars])
        self.assertEqual(select_chart_style(style,'bar'),bars)
        self.assertTrue(chart_presentation_style(style,'line')['axes'])

    def test_exact_gradient_stops_and_rounded_bars_survive_even_native_request(self):
        profile=dict(type='bar',palette=['#0879E8'],treatment='gradient',confidence=.9,
            fills=[dict(angle=90,stops=[dict(offset=0,color='#0879E8'),dict(offset=1,color='#041139')])],
            bars=dict(radius=7,widthRatio=.8,overlap=0,valuePosition='inside',highlight='none'))
        item=self.chart();before=deepcopy(item['data'])
        item['presentation']=chart_presentation(dict(mode='native',treatment='plain'),kind='bar',profile=profile)
        self.assertEqual(item['presentation']['mode'],'image')
        root=xml(chart_svg(item,dict(self.style(),chartStyle=profile)).encode())
        self.assertEqual(root.xpath('.//*[local-name()="stop"]/@stop-color'),['#0879E8','#041139'])
        self.assertEqual(root.xpath('.//*[@data-chart-value]/@rx'),['7']*3)
        self.assertEqual([float(v) for v in root.xpath('.//*[@data-chart-value]/@data-chart-value')],[10,40,50])
        self.assertEqual(item['data'],before)

    def test_rings_are_transparent_paths_with_source_geometry_and_calculated_labels(self):
        profile=dict(type='donut',palette=['#0078FF','#00C8D8','#CCE5F9'],holeSize=66,legend='bottom',
            radial=dict(startAngle=-90,gap=1,stroke='#DDE6F3',strokeWidth=.4,center='total',labels='percent'))
        item=self.chart('donut');root=xml(chart_svg(item,dict(self.style(),chartStyle=profile)).encode())
        self.assertEqual(len(root.xpath('.//*[local-name()="path" and @data-chart-value]')),3)
        self.assertEqual(root.xpath('.//*[@data-chart-value]/@fill-rule'),['evenodd']*3)
        self.assertIn('100',root.xpath('.//*[local-name()="text"]/text()'))
        self.assertIn('40%',root.xpath('.//*[local-name()="text"]/text()'))
        self.assertEqual(chart_presentation(profile=profile,kind='donut')['mode'],'image')

    def test_monotone_curves_pass_through_observations_and_do_not_replace_marks(self):
        profile=dict(type='line',palette=['#0078FF'],line=dict(curve='monotone',areaOpacity=.12),markers=False)
        item=self.chart('line');root=xml(chart_svg(item,dict(self.style(),chartStyle=profile)).encode())
        self.assertTrue(root.xpath('.//*[@data-chart-line and contains(@d," C ")]'))
        self.assertEqual([float(v) for v in root.xpath('.//*[@data-chart-value]/@data-chart-value')],[10,40,50])
        self.assertTrue(root.xpath('.//*[@data-chart-area]'))
        self.assertEqual(monotone_path([(0,0),(1,1)]),'M 0,0 L 1,1')

    def test_white_inside_labels_cannot_make_white_axes_on_white_surface(self):
        style=chart_presentation_style(dict(self.style(),chartStyle=dict(type='bar',ink='#FFFFFF',axes=False)),'line')
        self.assertEqual(style['ink'],'#202020');self.assertTrue(style['axes'])

    def test_source_ring_without_sample_labels_still_explains_new_categories(self):
        style=chart_presentation_style(dict(self.style(),chartStyle=dict(type='donut',legend='none')),'donut')
        self.assertEqual(style['legend'],'right');self.assertTrue(style['showValues'])

    def test_multiple_time_series_keep_their_names_when_the_source_ring_has_no_legend(self):
        profile=dict(type='donut',legend='none',palette=['#0077FF','#00AA66','#CC6600'])
        item=self.chart('line');item['data']['series']=[dict(name=name,values=[10,40,50]) for name in ('Adelie','Chinstrap','Gentoo')]
        root=xml(chart_svg(item,dict(self.style(),chartStyle=profile)).encode())
        self.assertEqual(root.xpath('.//*[@data-chart-label="legend"]/text()'),['Adelie','Chinstrap','Gentoo'])
        self.assertEqual(chart_presentation_style(dict(self.style(),chartStyle=profile),'line',3)['legend'],'bottom')

    def test_last_year_cannot_overlap_the_previous_tick(self):
        item=self.chart('line');item['data'].update(categories=[str(year) for year in range(2000,2026)],series=[dict(name='CO2',values=list(range(26)))])
        root=xml(chart_svg(item,self.style()).encode());labels=root.xpath('.//*[@data-chart-label="category"]')
        self.assertEqual(labels[-1].text,'2025')
        self.assertGreater(float(labels[-1].get('x'))-float(labels[-2].get('x')),40)

    def test_long_value_on_short_bar_moves_outside_instead_of_over_category(self):
        item=self.chart('bar-horizontal');item['data'].update(categories=['Индия','Нигерия'],series=[dict(name='Население',values=[1430000000,223150000])])
        profile=dict(type='bar-horizontal',bars=dict(radius=0,widthRatio=.8,overlap=0,valuePosition='inside',highlight='none'))
        root=xml(chart_svg(item,dict(self.style(),chartStyle=profile)).encode())
        mark=root.xpath('.//*[@data-chart-value="223150000"]')[0]
        label=root.xpath('.//*[local-name()="text" and text()="223,15 млн"]')[0]
        self.assertEqual(label.get('text-anchor'),'start')
        self.assertGreater(float(label.get('x')),float(mark.get('x'))+float(mark.get('width')))
