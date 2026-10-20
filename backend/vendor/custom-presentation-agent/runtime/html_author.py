"""Model-authored HTML/CSS. The browser, rather than preset cards, owns layout.

Only presentation data bindings and inert markup are accepted. CSS lives in an
isolated shadow tree; the browser has no network or executable document content.
"""
import html
import json
import re
from lxml import html as lhtml, etree

TAGS=set('div section article header footer main aside h1 h2 h3 h4 h5 h6 p span strong em b i small sup sub ul ol li table thead tbody tr th td caption colgroup col figure figcaption img br hr'.split())
BAD_CSS=re.compile(r'@import|@font-face|url\s*\(|expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding|(?<![\w-])content\s*:',re.I)
COUNTER_CONTENT=re.compile(r'''(?<![\w-])content\s*:\s*counter\(\s*[a-zA-Z_][\w-]{0,40}(?:\s*,\s*(?:decimal|decimal-leading-zero|lower-alpha|upper-alpha|lower-roman|upper-roman))?\s*\)(?:\s*(?:\\?["'][.)\s:-]{0,4}\\?["']))?\s*(?=[;}])''',re.I)

def safe_css(value):
    if isinstance(value,str):
        value=re.sub(r'''([^{}]+?)::?before\s*\{([^{}]*?\bcontent\s*:\s*(?:attr\(\s*data-number\s*\)|["'][\d.)\s-]{1,6}["'])[^{}]*)\}''',
                     lambda m:m[1]+' > .nerpa-list-number{'+m[2]+'}',value,flags=re.I)
    # Empty pseudo-element content is decorative, not unbound copy. Disable
    # that decoration instead of discarding a slide's complete source layout.
    if isinstance(value,str):value=re.sub(r'(?<![\w-])content\s*:\s*(?:""|\'\')\s*;?', '', value,flags=re.I)
    # Structural ordinals are bound as real validated text below. A redundant
    # numeric/attr(data-number) pseudo-element must not discard a whole slide.
    # Arbitrary generated words and attr(data-text) remain prohibited.
    if isinstance(value,str):value=re.sub(r'''(?<![\w-])content\s*:\s*(?:attr\(\s*data-number\s*\)|["'][\d.)\s-]{1,6}["'])\s*;?''','',value,flags=re.I)
    # Unbound pseudo-element wording (often a duplicate metric) is not an
    # instruction to replace the whole slide with emergency copy. Remove the
    # literal declaration; all actual content still has required data bindings.
    # URL/import/expression checks continue to reject executable/remote CSS.
    if isinstance(value,str):value=re.sub(r'''(?<![\w-])content\s*:\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*;?''','',value,flags=re.I)
    # Structural list ordinals are not slide facts. Permit only a counter with
    # a standard numbering style and punctuation; arbitrary generated wording,
    # attr(), URLs and invented literal numbers remain prohibited.
    if not isinstance(value,str) or len(value)>24000 or BAD_CSS.search(COUNTER_CONTENT.sub('',value)) or '<' in value:raise ValueError('html_author_css')
    value=COUNTER_CONTENT.sub(lambda m:m[0].replace('\\"','"').replace("\\'","'"),value)
    return value

def author_scene(copy,layout,index,images):
    from runtime.html_deck import box,text_node
    texts=[];cells=[];bindings={};omitted=[];warnings=[]
    # The native adapter receives only photographs actually placed in HTML.
    # Previously an unused allocated image appeared in PPTX on top of text or
    # tables even though it was absent from the accepted browser/PDF layout.
    raw_html=copy['html'];requested=sorted({int(n) for n in re.findall(r'data-image\s*=\s*["\'](\d+)["\']',raw_html) if int(n)<len(images)})
    required=[i for i,image in enumerate(images) if image.get('source',{}).get('required') and i not in requested]
    for i in required:
        picture=images[i]
        raw_html+='<img data-image="%d" class="nerpa-required-source-figure" style="position:absolute;left:%spt;top:%spt;width:%spt;height:%spt;object-fit:contain">'%tuple([i]+[picture[k] for k in ('x','y','w','h')])
        warnings.append(dict(slide=index+1,reason='html_source_image_restored',message='Исходная иллюстрация возвращена в назначенную область; проверьте расположение пояснений.'))
    requested=sorted(set(requested)|set(required))
    mapping={old:new for new,old in enumerate(requested)}
    raw_html=re.sub(r'(data-image\s*=\s*["\'])(\d+)(["\'])',lambda m:m[1]+str(mapping.get(int(m[2]),len(requested)))+m[3],raw_html)
    copy=dict(copy,html=raw_html);images=[images[n] for n in requested]
    # Empty source positions may outnumber the new semantic items. Such empty
    # bindings disappear, while a typo or missing nonempty fact remains invalid.
    for field,keys,limit in [('paragraphs',[''],8),('cards',['title','body'],8),('steps',['title','body'],6),('metrics',['value','label'],8)]:
        for i in range(len(copy.get(field,[])),limit):
            omitted += [f'{field}.{i}'+('.'+key if key else '') for key in keys]
    def bind(path,key,value,bounds=None,bold=False):
        if value is None or not str(value).strip():omitted.append(path);return
        item=text_node(key,str(value),bounds or layout['body'],layout,bold)
        texts.append(item);bindings[path]=key
    reference=copy.get('sourceDesign') or {}
    # A source quote/question may consist of a single body frame and no
    # heading. Keep the semantic navigation title in notes in that case only.
    anchors=reference.get('textAnchors',[])
    body_only=reference.get('headingAbsent') or len(anchors)==1 and (reference.get('title') or {}).get('role') in ('body','label')
    title_binding=re.search(r'data-text\s*=\s*["\']title["\']',copy['html'])
    if body_only and not title_binding:
        omitted.append('title')
    else:bind('title','h_title',copy.get('title',''),layout['title'],True)
    source_subtitle=any(a.get('role') in ('subtitle','body') and a['shapeId']!=(reference.get('title') or {}).get('shapeId') for a in reference.get('textAnchors',[]))
    terminal=layout.get('design') and not layout['design']['content'] and not source_subtitle
    if terminal:
        omitted += [f'paragraphs.{i}' for i in range(len(copy.get('paragraphs',[])))]+['takeaway']
        for field in ('cards','steps','metrics'):
            for i,value in enumerate(copy.get(field,[])):
                omitted += [f'{field}.{i}.{key}' for key in value]
    if not terminal:
        for i,value in enumerate(copy.get('paragraphs',[])):bind(f'paragraphs.{i}',f'h_p_{i}',value)
        for i,value in enumerate(copy.get('cards',[])):
            bind(f'cards.{i}.title',f'h_card_{i}_title',value['title'],bold=True);bind(f'cards.{i}.body',f'h_card_{i}_body',value['body'])
        for i,value in enumerate(copy.get('steps',[])):
            bind(f'steps.{i}.title',f'h_step_{i}_title',value['title'],bold=True);bind(f'steps.{i}.body',f'h_step_{i}_body',value['body'])
        for i,value in enumerate(copy.get('metrics',[])):
            bind(f'metrics.{i}.value',f'h_metric_{i}',value['value'],bold=True);bind(f'metrics.{i}.label',f'h_metric_label_{i}',value['label'])
        bind('takeaway','h_takeaway',copy.get('takeaway',''))
    table=None if terminal else copy.get('table');chart=None if terminal else copy.get('chart')
    if table:
        for r,row in enumerate([table['headers'],*table['rows']]):
            for c,value in enumerate(row):
                item=text_node(f'h_cell_{r}_{c}',str(value),layout['body'],layout);item.update(cell=[r,c],bold=r==0);cells.append(item)
    # Pagination is presentation data too; it is never baked into source art.
    from runtime.page_numbers import PAGINATION
    for i,slot in enumerate(layout.get('pageNumbers',[])):
        match=PAGINATION.fullmatch(slot.get('text',''))
        if not match:continue
        item=text_node(f'h_page_{i}',str(index+1),box(slot),layout)
        item.update(font=slot.get('font') or layout['font'],size=slot.get('size',12),color=slot.get('color','#202020'),align=slot.get('align','center'))
        texts.append(item)
    scene=dict(version=1,index=index,sourceLayoutId=layout['id'],title=copy.get('title',''),texts=texts,cells=cells,
        table=dict(data=table,box=dict(layout['body'])) if table else None,chart=dict(data=chart,box=dict(layout['body'])) if chart else None,
        shapes=[],metricCards=[],images=images,notes=copy.get('notes',''),speech=copy.get('speech',''),sourceReferences=[*copy.get('sourceReferences',[]),*[dict(title=value,url='') for value in layout.get('attributions',[])]],
        designBounds=dict(title=layout['title'],content=[] if terminal else layout.get('columns') or [layout['body']],surfaces=(layout.get('design') or {}).get('surfaces',[]),safeSurfaces=layout.get('safeSourceSurfaces',[])),
        authored=dict(html=copy['html'],css=safe_css((copy.get('deckCss','')+'\n'+copy.get('css','')).strip()),bindings=bindings,omittedBindings=omitted))
    if copy.get('sourceDesign'):scene['sourceDesign']=copy['sourceDesign']
    if scene.get('chart'):
        from runtime.html_chart_export import chart_presentation
        from runtime.chart_builder import select_chart_style
        profile=select_chart_style(layout,chart['type'])
        scene['chart']['sourceStyle']=profile
        scene['chart']['presentation']=chart_presentation(copy.get('chartPresentation'),scene['authored']['css'],chart['type'],profile)
    # A model can intentionally remove an old ellipse without drawing a new
    # filled surface, but still call the edit "replace". Honour the removal
    # without throwing away this slide's authored layout or repeating the same
    # inconsistent edit in source-frame recovery. The native boundary verifies
    # which original shapes may actually be removed.
    surfaces={int(n) for n in re.findall(r'data-source-surface\s*=\s*["\'](\d+)["\']',copy['html'])}
    scene['sourceShapeEdits']=[dict(edit,action='remove') if edit.get('action')=='replace' and edit.get('shapeId') not in surfaces else dict(edit)
                               for edit in copy.get('sourceShapeEdits',[])]
    if scene['sourceShapeEdits']!=copy.get('sourceShapeEdits',[]):
        warnings.append(dict(slide=index+1,reason='html_source_shape_removed',message='Исходная фигура убрана: автор разместил содержание без заменяющей заливки.'))
    if body_only and not title_binding:scene['notes']='\n\n'.join(v for v in [copy.get('title',''),scene['notes']] if v)
    if copy.get('designDecision'):scene['designDecision']=copy['designDecision']
    if any(int(number)>=len(images) for number in re.findall(r'data-image\s*=\s*["\'](\d+)["\']',copy['html'])):
        scene['warnings']=[dict(slide=index+1,reason='html_photo_missing',message='Фото не найдено. Перестройте только исходную область фото/текста, не оставляя пустую колонку.')]
    if terminal:
        hidden=[*copy.get('paragraphs',[]),copy.get('takeaway','')]
        for field in ('cards','steps','metrics'):
            for item in copy.get(field,[]):hidden += [str(value) for value in item.values() if value]
        scene['notes']='\n\n'.join(value for value in [scene['notes'],*hidden] if value)
    if warnings:scene.setdefault('warnings',[]).extend(warnings)
    # Validate before handing the scene to the renderer; malformed code recovers
    # this slide locally instead of discarding authored content for the deck.
    author_fragment(scene,layout,lambda *_:'',validate=True)
    return scene

def author_fragment(scene,style,chart_renderer,validate=False):
    authored=scene['authored'];raw=authored['html']
    if not isinstance(raw,str) or not raw.strip() or len(raw)>24000:raise ValueError('html_author_markup')
    css=safe_css(authored.get('css',''));root=lhtml.fragment_fromstring(raw,create_parent='div')
    # Source row ordinals are structural design, not invented factual metrics.
    # Retain them as editable text when the author fills that original label.
    rows=style.get('sourceHtml',{}).get('numberedRows',[])
    ordinals={o['ordinal']:o for o in style.get('sourceHtml',{}).get('structuralOrdinals',[])}
    removed={e['shapeId'] for e in scene.get('sourceShapeEdits',[])}
    regions={r['shapeId']:r for r in style.get('sourceHtml',{}).get('textRegions',[])}
    for row in rows:
        identity=row['numberShapeId'];number=row['ordinal'];region=regions.get(identity)
        if identity in removed or not region or root.xpath('.//*[@data-number=$n]',n=str(number)) or root.xpath('.//*[@data-source-shape=$id and @data-text]',id=str(identity)):continue
        if not root.xpath('.//*[@data-source-shape=$id]',id=str(row['textShapeId'])):continue
        b=region['box']
        etree.SubElement(root,'span',{'data-number':str(number),'data-source-shape':str(identity),
            'style':'position:absolute;left:%spx;top:%spx;width:%spx;height:%spx;display:flex;align-items:center;justify-content:center;font-family:%s;font-size:%spx;color:%s'%tuple([b[k] for k in ('x','y','w','h')]+[json.dumps(region.get('font') or style['font']),region['size'],region.get('color') or style['ink']])})
    # A semantic pair sometimes arrives as one body-only paragraph. Restore its
    # existing heading INSIDE that same authored paragraph, preserving the
    # model's columns, frame and CSS instead of replacing the slide with cards.
    for path in authored['bindings']:
        if not re.fullmatch(r'cards\.\d+\.title',path) or root.xpath('.//*[@data-text=$key]',key=path):continue
        body_path=path.removesuffix('.title')+'.body';bodies=root.xpath('.//*[@data-text=$key]',key=body_path)
        if len(bodies)!=1 or bodies[0].tag not in ('p','div','span','li'):continue
        frame=bodies[0];frame.attrib.pop('data-text',None);source_id=frame.attrib.pop('data-source-shape',None)
        frame.text='';frame[:]=[]
        for binding in (path,body_path):
            item=etree.SubElement(frame,'span',{'data-text':binding,'style':'display:block;line-height:inherit'+(';font-weight:600' if binding==path else '')})
            if source_id:item.set('data-source-shape',source_id)
    # Recover an omitted visual marker only in a uniquely named empty frame
    # already authored by the model. Its CSS/geometry remain untouched.
    for kind,names in [('table',{'table','tab','table-frame'}),('chart',{'chart','plot','chart-frame'})]:
        if scene.get(kind) and not root.xpath('.//*[@data-visual="%s"]'%kind):
            frames=[el for el in root.iterdescendants() if el.tag=='div' and not len(el) and not (el.text or '').strip()
                    and not any(k.startswith('data-') for k in el.attrib)
                    and set(el.get('class','').split())&names]
            if len(frames)==1:frames[0].set('data-visual',kind)
    nodes={item['key']:item for item in scene['texts']+scene.get('cells',[])};used=set();visuals=set();photos=set()
    for element in list(root.iterdescendants()):
        if root not in element.iterancestors():continue
        if not isinstance(element.tag,str):element.getparent().remove(element);continue
        if element.tag.lower() not in TAGS:element.drop_tree();continue
        attrs=dict(element.attrib);element.attrib.clear()
        for key in ('class','id','role','aria-label','colspan','rowspan'):
            if key in attrs:element.set(key,attrs[key][:300])
        source_id=attrs.get('data-source-shape','')
        if source_id.isdigit() and any(a['shapeId']==int(source_id) for a in scene.get('sourceDesign',{}).get('textAnchors',[])):
            element.set('data-source-shape',source_id)
        if attrs.get('data-source-group') in {group['id'] for group in scene.get('sourceDesign',{}).get('sourceHtml',{}).get('textGroups',[])}:
            element.set('data-source-group',attrs['data-source-group'])
        if 'style' in attrs:element.set('style',safe_css(attrs['style']))
        surface=attrs.get('data-source-surface','')
        if surface.isdigit():
            original=next((s for s in scene.get('sourceDesign',{}).get('editableShapes',[]) if s['shapeId']==int(surface)),None)
            edited=any(e['shapeId']==int(surface) and e['action']=='replace' for e in scene.get('sourceShapeEdits',[]))
            if original and edited and re.fullmatch(r'#[0-9a-fA-F]{6}',original.get('fill','')):
                element.set('data-source-surface',surface)
                element.set('style',element.get('style','')+';--source-fill:'+original['fill']+'!important')
        reference=attrs.get('data-text')
        if not reference and attrs.get('data-number','').isdigit():
            number=int(attrs['data-number']);maximum=max(len([k for k in authored['bindings'] if re.fullmatch(r'cards\.\d+\.title',k)]),len([k for k in authored['bindings'] if re.fullmatch(r'steps\.\d+\.title',k)]),max((r['ordinal'] for r in rows),default=0),max(ordinals,default=0))
            if not 1<=number<=maximum:element.drop_tree();continue
            key=f'h_list_number_{number}'
            if key in used:raise ValueError('html_author_binding')
            if key not in nodes:
                from runtime.html_deck import text_node
                value=str(number).zfill(min(2,ordinals.get(number,{}).get('digits',1)))
                nodes[key]=text_node(key,value,dict(style['body']),style);scene['texts'].append(nodes[key])
            if source_id.isdigit() and int(source_id) in regions:nodes[key]['sourceShapeId']=int(source_id)
            if len(element):
                marker=etree.Element('span',{'data-key':key,'class':'nerpa-bound-text nerpa-list-number'})
                marker.text=nodes[key]['text'];element.insert(0,marker)
            else:
                element.text=nodes[key]['text'];element.set('data-key',key);element.set('class',(element.get('class','')+' nerpa-bound-text').strip())
            used.add(key)
        if reference:
            key=authored['bindings'].get(reference)
            if not key and reference in authored.get('omittedBindings',[]):element.drop_tree();continue
            if not key or key in used:raise ValueError('html_author_binding')
            element.clear(keep_tail=True);element.attrib.update({k:v for k,v in attrs.items() if k in ('class','id','role','aria-label')})
            if 'style' in attrs:element.set('style',safe_css(attrs['style']))
            element.set('class',(element.get('class','')+' nerpa-bound-text').strip());element.set('data-key',key);element.text=nodes[key]['text'];used.add(key)
            source_id=attrs.get('data-source-shape') or next((a.get('data-source-shape') for a in element.iterancestors() if a.get('data-source-shape')),'')
            if source_id.isdigit() and any(a['shapeId']==int(source_id) for a in scene.get('sourceDesign',{}).get('textAnchors',[])):
                # The source ID selects ONE layout host. Copying it onto each
                # child made a local padding/height CSS patch hit the parent
                # and every heading/paragraph again, producing new clipping.
                # Native ownership belongs in scene metadata; nested runs
                # inherit the host's font and retain their data-key identity.
                if attrs.get('data-source-shape'):element.set('data-source-shape',source_id)
                if attrs.get('data-source-role') in ('title','header','body','subtitle','label','metric','photo'):
                    element.set('data-source-role',attrs['data-source-role'])
                nodes[key]['sourceShapeId']=int(source_id)
            # A source-backed surface may be the text element itself. Clearing
            # placeholder content must retain its already validated fill and ID.
            if surface.isdigit() and original and edited and re.fullmatch(r'#[0-9a-fA-F]{6}',original.get('fill','')):
                element.set('data-source-surface',surface)
                element.set('style',element.get('style','')+';--source-fill:'+original['fill']+'!important')
        elif attrs.get('data-visual') in ('table','chart'):
            kind=attrs['data-visual']
            if not scene.get(kind):element.drop_tree();continue
            if kind in visuals:raise ValueError('html_author_visual')
            element.tag='div';element.text='';element[:]=[];element.set('data-visual',kind);visuals.add(kind)
            if kind=='chart':fragment=chart_renderer(scene['chart'],style)
            else:
                data=scene['table']['data'];fragment='<div class="authored-table">'
                for cell in scene['cells']:
                    fragment+='<div class="nerpa-bound-text authored-cell" data-key="%s">%s</div>'%(cell['key'],html.escape(cell['text']));used.add(cell['key'])
                fragment+='</div>';element.set('style',(element.get('style','')+';--table-cols:'+str(len(data['headers']))+';--table-rows:'+str(len(data['rows'])+1)))
            if fragment:
                for child in lhtml.fragments_fromstring(fragment):element.append(child)
        elif attrs.get('data-image','').isdigit():
            number=int(attrs['data-image'])
            if number>=len(scene['images']):element.drop_tree();continue
            if number in photos:raise ValueError('html_author_image')
            element.tag='img';element.text='';element[:]=[];element.set('data-image',str(number));photos.add(number)
            if scene['images'][number].get('fit')=='contain':element.set('style',element.get('style','')+';object-fit:contain')
            if scene['images'][number].get('source',{}).get('required'):
                element.set('style',element.get('style','')+';object-fit:contain!important;background-color:#FFFFFF!important')
        elif attrs.get('data-graphic') in ('bar','line'):
            element.tag='div';element.text='';element[:]=[];element.set('data-graphic',attrs['data-graphic'])
        elif element.tag=='img':element.drop_tree()
    # Literal copy cannot conceal sample text or invented numbers in the code.
    # All visible wording is supplied by the validated semantic content fields.
    for element in root.iter():
        if element.get('data-key') is None and not any(a.get('data-key') or a.get('data-visual') for a in element.iterancestors()):element.text=None
        element.tail=None
    for element in list(root.xpath('.//*[@data-key]')):
        item=nodes.get(element.get('data-key'))
        if not item or not item.get('manualStyle'):continue
        css_text='font-family:%s!important;font-size:%spt!important;color:%s!important;font-weight:%s!important;text-align:%s!important;line-height:%s;'%(json.dumps(item['font']),item['size'],item['color'],700 if item.get('bold') else 400,item.get('align','left'),item.get('lineHeight',1.16))
        if item.get('manualAlign'):element.set('data-manual-align',item['align'])
        if item.get('manualGeometry') and not item.get('cell'):
            element.getparent().remove(element);root.append(element)
            padding=item.get('htmlStyle',{})
            css_text+='padding:%s!important;position:absolute!important;left:%spt!important;top:%spt!important;width:%spt!important;height:%spt!important;'%(
                ' '.join(str(padding.get(key,0))+'pt' for key in ('paddingTop','paddingRight','paddingBottom','paddingLeft')),
                *[item[k] for k in ('x','y','w','h')])
        element.set('style',element.get('style','')+';'+css_text);element.set('data-manual-style','true')
    expected={key for key in nodes if not key.startswith('h_page_')}
    for edit in scene.get('sourceShapeEdits',[]):
        if edit['action']=='replace' and not root.xpath('.//*[@data-source-surface=$id]',id=str(edit['shapeId'])):
            raise ValueError('html_author_missing_source_surface:'+str(edit['shapeId']))
    missing=sorted(expected-used)+[kind for kind in ('table','chart') if scene.get(kind) and kind not in visuals]
    if used!=expected or missing:raise ValueError('html_author_missing_content:'+','.join(missing))
    markup=''.join(etree.tostring(child,encoding='unicode',method='html') for child in root)
    return markup,css

def source_font_css(scene):
    """Source typography is a design asset. CSS still owns geometry and fit."""
    reference=scene.get('sourceDesign') or {};rules=[]
    manual={item['key'] for item in scene['texts'] if item.get('manualStyle')}
    for selector,anchor in [('[data-key="h_title"]',reference.get('title') or {}),
                            *[('[data-source-shape="%s"]'%a['shapeId'],a) for a in reference.get('textAnchors',[])]]:
        if selector=='[data-key="h_title"]' and 'h_title' in manual:continue
        if selector.startswith('[data-source-shape=') and any(item.get('manualStyle') and item.get('sourceShapeId')==anchor.get('shapeId') for item in scene['texts']):continue
        if anchor.get('font'):rules.append('%s{font-family:%s!important}'%(selector,json.dumps(anchor['font'])))
    return ''.join(rules)

BASE_CSS='''
:host{display:block;width:100%;height:100%;position:relative;contain:paint;overflow:hidden}
*{box-sizing:border-box}h1,h2,h3,h4,p,figure,ul,ol{margin:0}:where(.nerpa-bound-text){white-space:pre-wrap;overflow-wrap:normal;line-height:1.16;min-width:0;min-height:0;max-width:100%;flex-shrink:0}
[data-visual]{min-width:0;min-height:0}[data-visual]>svg{display:block;width:100%;height:100%}
.authored-table{display:grid;width:100%;height:100%;grid-template-columns:repeat(var(--table-cols),minmax(0,1fr));grid-template-rows:repeat(var(--table-rows),minmax(0,1fr))}
.authored-cell{padding:5pt 6pt;border-bottom:.5pt solid currentColor;font-size:14pt}
img[data-image]{object-fit:cover;max-width:100%;max-height:100%}
'''

# Source artwork is already below the authored tree. Generated containers may
# arrange content, but cannot introduce the prose boxes/side stripes prohibited
# by the custom-deck design contract. SVG chart fills remain available.
STYLE_POLICY='*{background-color:transparent!important;background-image:none!important;box-shadow:none!important;border-left:none!important;border-right:none!important;border-inline-start:none!important;border-inline-end:none!important}[data-graphic]{background-color:var(--graphic-color,transparent)!important}[data-source-surface]{background-color:var(--source-fill,transparent)!important}'

def author_min_contrast(scene,item):
    # Preserve an intentional source foreground on its colored panel when it
    # remains legible. A marginal 4.5 threshold must not silently turn the
    # template's white-on-red copy black; vision still judges actual legibility.
    source=next((a for a in scene.get('sourceDesign',{}).get('textAnchors',[])
        if item.get('sourceShapeId') is not None and a.get('shapeId')==item['sourceShapeId'] and (a.get('color') or '').lower()==item.get('color','').lower()),None)
    return 3 if source or item['size']>=18 or item['size']>=14 and item.get('bold') else 4.5


def author_contrast_warnings(scene,background,width,height):
    """Send measured readability failures to the HTML editor, without repainting
    the user's artwork or putting a colored panel behind the text."""
    from PIL import Image
    from runtime.contrast import ratio
    warnings=[]
    with Image.open(background) as source:
        image=source.convert('RGB')
        from runtime.html_surfaces import busy_text_background
        reference=scene.get('sourceDesign')
        if reference is not None:
            reference['unsafeTextAnchors']=[dict(shapeId=anchor['shapeId'],box=anchor['box'],reason='busy-background')
                for anchor in reference.get('textAnchors',[]) if busy_text_background(image,
                    dict(anchor['box'],size=anchor.get('size',16)),width,height)]
        for item in scene['texts']+scene.get('cells',[]):
            if item['key'].startswith('h_page_') or not item.get('text','').strip():continue
            if busy_text_background(image,item,width,height):
                warnings.append(dict(slide=scene['index']+1,key=item['key'],reason='html_busy_background',message='Текст на пёстром фоне плохо читается. Перенесите его в одну из измеренных safeSurfaces исходного слайда, включая свободную исходную область фотографии. Сохраните заголовок; не добавляйте цветной блок.'))
            values=[]
            for row in range(3):
                for col in range(5):
                    x=(item['x']+item['w']*(col+.5)/5)*image.width/width
                    y=(item['y']+item['h']*(row+.5)/3)*image.height/height
                    if 0<=x<image.width and 0<=y<image.height:
                        pixel=image.getpixel((int(x),int(y)));values.append(ratio(item['color'],'#%02x%02x%02x'%pixel))
            minimum=author_min_contrast(scene,item)
            if values and sorted(values)[len(values)//2]<minimum:
                warnings.append(dict(slide=scene['index']+1,key=item['key'],reason='html_low_contrast',message='Повысьте контраст текста к фактическому фону средствами CSS, сохранив исходный дизайн.'))
    return warnings

def source_layout_warnings(scene,width,height):
    """Measured feedback for the model: conserve source anchors and diagrams.
    These findings request local code repair and never veto finished files."""
    reference=scene.get('sourceDesign') or {};warnings=[]
    items=[v for v in scene['texts'] if not v['key'].startswith('h_page_') and v.get('text','').strip() and not v.get('manualStyle')]
    def area(b):return max(0,b['w'])*max(0,b['h'])
    def overlap(a,b):return max(0,min(a['x']+a['w'],b['x']+b['w'])-max(a['x'],b['x']))*max(0,min(a['y']+a['h'],b['y']+b['h'])-max(a['y'],b['y']))
    def inside(a,b):
        px=max(5,b['w']*.12);py=max(5,b['h']*.12)
        return a['x']>=b['x']-px and a['y']>=b['y']-py and a['x']+a['w']<=b['x']+b['w']+px and a['y']+a['h']<=b['y']+b['h']+py
    def within_host(a,b):
        return a['x']>=b['x']-1.5 and a['y']>=b['y']-1.5 and a['x']+a['w']<=b['x']+b['w']+1.5 and a['y']+a['h']<=b['y']+b['h']+1.5
    def finding(item,reason,message):warnings.append(dict(slide=scene['index']+1,key=item['key'],reason=reason,message=message))
    removed={e['shapeId'] for e in scene.get('sourceShapeEdits',[])}
    for row in reference.get('sourceHtml',{}).get('iconRows',[]):
        if row['iconShapeId'] in removed:continue
        if not any(item.get('sourceShapeId')==row['textShapeId'] for item in items):
            finding(dict(key='source_row_'+str(row['textShapeId'])),'html_source_row_empty','У сохранённой иконки отсутствует свой текст. Заполните именно textShapeId '+str(row['textShapeId'])+' коротким самостоятельным подтверждённым пунктом; вводная строка не заменяет этот пункт. Сохраните иконку и все остальные полезные строки.')
    if reference.get('generationMode')=='style-stencils' and reference.get('compositionPolicy')!='source-first':
        # Content stencils replace sample diagram topology. Retained chrome and
        # actual source figures are still checked for overlap/readability.
        reference=dict(reference,textAnchors=[{key:value for key,value in a.items() if key!='container'} for a in reference.get('textAnchors',[]) if a.get('shapeId')==(reference.get('title') or {}).get('shapeId')],
                       dataFrames=[],editableShapes=[],sourceHtml=dict(reference.get('sourceHtml',{}),numberedRows=[]))
    rows=reference.get('sourceHtml',{}).get('numberedRows',[])
    if len(rows)>=3 and sum(r['textShapeId'] in removed for r in rows)>len(rows)*.5 and len([i for i in items if not i['key'].startswith(('h_title','h_list_number_'))])>=len(rows)*.6:
        finding(dict(key='source_structure'),'html_source_structure_removed','Удалена большая часть пригодной исходной схемы, хотя пояснения для её строк есть. Восстановите рамки и соединители, заполните каждую строку коротким тезисом; общие периоды и оговорки вынесите одной отдельной подписью к рисунку. Не заменяйте всю схему обычным списком.')
    for row in rows:
        if row['textShapeId'] in removed:continue
        bounds={k:v*.75 for k,v in row['box'].items()}
        if not any(item.get('sourceShapeId')==row['textShapeId'] or overlap(item,bounds)>=area(item)*.7 for item in items):
            finding(dict(key='source_row_'+str(row['textShapeId'])),'html_source_row_empty','В исходной схеме осталась пустая строка с линией/рамкой. Заполните её коротким подтверждённым тезисом либо явно уберите всю строку вместе с её рамкой и связанной линией; сохраняйте остальную схему.')
    for picture in scene.get('images',[]):
        if not picture.get('source',{}).get('required'):continue
        source=picture['source'];display=picture.get('contentBox',picture)
        if source.get('figureKind')=='chart' and source.get('labelCount',0)>=24 and (display['w']<width*.6 or display['h']<height*.5):
            aspect=display['w']/max(1,display['h']);minimum_w=max(width*.6,height*.5*aspect);minimum_h=minimum_w/aspect
            finding(dict(key='source_figure_'+str(picture.get('slotIndex',0))),'html_source_figure_too_small',
                'Плотная исходная диаграмма показана слишком мелко. При её пропорциях %.3f:1 нужен img минимум %.0f×%.0f CSS px, сохраняя object-fit:contain и все подписи. Большая ширина рамки при меньшей высоте оставляет сам рисунок маленьким. Перенесите пояснения в компактную боковую колонку; не уменьшайте график ради четырёх карточек.'%(aspect,minimum_w*4/3,minimum_h*4/3))
        for item in items:
            if any(overlap(line,picture)>max(1,area(line)*.02) for line in item.get('inkRects') or [item]):
                finding(item,'html_source_image_overlap','Текст перекрывает обязательную исходную иллюстрацию. Перестройте HTML внутри исходного блока фото/пояснений; сохраняйте сам рисунок целиком.')
    for frame in reference.get('dataFrames',[]):
        b=frame['box']
        if area(b)<width*height*.15 or scene.get('table') or scene.get('chart'):continue
        occupants=[i for i in items if i['key']!='h_title' and overlap(i,b)>max(1,area(i)*.3)]
        if not occupants and not any(overlap(p,b)>area(b)*.2 for p in scene.get('images',[])):
            finding(dict(key='source_visual_'+str(frame['shapeId'])),'html_source_visual_abandoned','Большая исходная область графика/таблицы оставлена пустой. При отсутствии новых числовых рядов постройте там связанную качественную схему из подтверждённых тезисов; сохраните отдельные подписи и соединители. Не переносите всю схему в обычный текстовый список сбоку и не возвращайте старые числовые данные.')
    for source in reference.get('textAnchors',[]):
        container=source.get('container')
        if not container or container.get('role')=='ordinal' or any(e['shapeId']==source['shapeId'] for e in scene.get('sourceShapeEdits',[])):continue
        bounds=container['box']
        assigned=[item for item in items if item.get('sourceShapeId')==source['shapeId']]
        occupants=[item for item in items if all(within_host(line,bounds) for line in (item.get('inkRects') or [item]))]
        if not occupants:
            finding(dict(key='source_'+str(source['shapeId'])),'html_source_container_empty',
                'Исходная заполненная фигура осталась пустой. Поместите соответствующее значение/подпись внутрь её innerBox, сохраняя цвет, центрирование и размер исходной фигуры; не размещайте весь текст снаружи.')
        for item in assigned:
            if any(not within_host(line,bounds) for line in (item.get('inkRects') or [item])):
                finding(item,'html_source_container_drift','Подпись вынесена за пределы собственной фигуры. Верните её внутрь innerBox; пояснение можно сократить или вынести рядом отдельным текстом.')
            elif container.get('innerBox') and any(not within_host(line,container['innerBox']) for line in (item.get('inkRects') or [item])):
                finding(item,'html_source_padding','Текст прижат к краю исходного блока. Разместите все строки внутри его padded innerBox с отступами со всех сторон и зазором у иконки; сократите повторяющееся пояснение, сохранив законченную мысль.')
    title=next((v for v in items if v['key']=='h_title'),None);anchor=(reference.get('title') or {}).get('box')
    if title and anchor and reference.get('headingAuthority')!='inferred' and 0<=anchor['x']<width and 0<=anchor['y']<height:
        if abs(title['x']-anchor['x'])>max(8,width*.015) or abs(title['y']-anchor['y'])>max(6,height*.02):
            finding(title,'html_source_title_drift','Верните заголовок к исходной привязке шаблона; корректируйте только размер и перенос внутри исходной области заголовка.')
        original=reference['title'];font=original.get('font','')
        if font and title.get('font','').strip('"\'').casefold()!=font.strip('"\'').casefold():
            finding(title,'html_source_typography_drift','Сохраните исходный шрифт заголовка шаблона.')
        if original.get('size',0)>=24 and title.get('size') and not original['size']*.7<=title['size']<=original['size']*1.2:
            finding(title,'html_source_typography_drift','Заголовок потерял исходный типографический масштаб. Сохраните иерархию шаблона, при необходимости сократите формулировку.')
    for item in items:
        anchors=reference.get('textAnchors',[])
        if item['key']!='h_title' and anchors and min(a['box']['y'] for a in anchors)>10 and any(line['y']<2 for line in item.get('inkRects',[])):
            finding(item,'html_native_bounds','Текст попал на верхний край вместо исходной строки шаблона. Проверьте фактические CSS-селекторы и верните группу к её исходной привязке.')
        ink=item.get('inkRects',[])
        if item['key']!='h_title' and len(ink)>1:
            def on_panel(line,panel):
                return line['x']>=panel['x']-3 and line['y']>=panel['y']-3 and line['x']+line['w']<=panel['x']+panel['w']+3 and line['y']+line['h']<=panel['y']+panel['h']+3
            for panel in reference.get('availableSurfaces',[]):
                fits=[on_panel(line,panel) for line in ink]
                if fits[0] and sum(fits)>=len(fits)*.6 and not all(fits):
                    finding(item,'html_native_bounds','Последние строки вышли за исходную светлую панель. Проверьте высоту всей группы/сетки, сократите повторяющееся пояснение или перенесите группу в другую свободную исходную область.')
                    break
        ink=item.get('inkRects') or [item]
        original_frame=any(all(inside(line,a['box']) for line in ink) for a in reference.get('textAnchors',[]))
        for artwork in reference.get('artwork',[]):
            if artwork.get('role')=='unknown' and any(inside(item,surface) for surface in reference.get('availableSurfaces',[])):
                continue  # Measured flat source panel, not a protected diagram.
            if artwork.get('role')=='container' and item['key'].startswith('h_list_number_') and inside(item,artwork['box']):
                continue  # Structural ordinal inside its original source badge.
            if artwork.get('role')=='icon' and any(overlap(line,artwork['box'])>2 for line in item.get('inkRects',[])):
                finding(item,'html_source_icon_overlap','Строки текста накладываются на исходную иконку. Сместите только соответствующие подписи к их исходным текстовым привязкам, оставив зазор у пиктограммы; не меняйте всю композицию.')
                break
            if overlap(item,artwork['box'])>max(8,area(item)*.08) and not original_frame:
                finding(item,'html_source_art_overlap','Текст перекрывает сохранённую графику шаблона. Используйте исходную область подписи или обтекание; не накладывайте произвольные колонки на схему.')
                break
    for kind in ('table','chart'):
        if not scene.get(kind):continue
        bounds=scene[kind]['box'];item=dict(bounds,key='h_'+kind)
        original_frame=any(inside(bounds,a['box']) for a in reference.get('dataFrames',[]))
        if not original_frame and any(overlap(bounds,a['box'])>max(8,area(bounds)*.08) for a in reference.get('artwork',[])):
            finding(item,'html_source_art_overlap','Новый график/таблица перекрывает сохранённую схему. Сохраните её исходный тип и размещайте подписи в исходных областях.')
    for i,left in enumerate(items):
        for right in items[i+1:]:
            if any(overlap(a,b)>max(3,min(area(a),area(b))*.1) for a in (left.get('inkRects') or [left]) for b in (right.get('inkRects') or [right])):
                finding(right,'html_text_overlap','Текстовые области пересекаются. Исправьте локальные отступы/размеры средствами HTML/CSS, сохранив композицию шаблона.')
    return warnings

def repair_author_contrast(scene,background,width,height,style):
    """Change only an unreadable foreground, choosing the nearest readable
    source color. Geometry, wording, artwork and manual edits stay intact."""
    from PIL import Image
    from runtime.contrast import ratio
    findings=author_contrast_warnings(scene,background,width,height)
    # A patterned surface needs a composition repair. Choosing black merely
    # because median contrast improves can make its labels look foreign and
    # does not solve the background defect.
    busy={w['key'] for w in findings if w['reason']=='html_busy_background'}
    failed={w['key'] for w in findings if w['reason']=='html_low_contrast'}-busy;repairs=[]
    palette=[style.get('ink'),style.get('titleColor'),style.get('accent'),*[a.get('color') for a in scene.get('sourceDesign',{}).get('textAnchors',[])]]
    palette=list(dict.fromkeys(c for c in palette if isinstance(c,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',c)))
    def rgb(c):return tuple(int(c[i:i+2],16) for i in (1,3,5))
    with Image.open(background) as source:
        image=source.convert('RGB')
        for item in scene['texts']+scene.get('cells',[]):
            if item['key'] not in failed or item.get('manualStyle'):continue
            pixels=[]
            for row in range(3):
                for col in range(5):
                    x=int((item['x']+item['w']*(col+.5)/5)*image.width/width);y=int((item['y']+item['h']*(row+.5)/3)*image.height/height)
                    if 0<=x<image.width and 0<=y<image.height:pixels.append('#%02x%02x%02x'%image.getpixel((x,y)))
            if not pixels:continue
            minimum=author_min_contrast(scene,item)
            def readable(c):
                values=sorted(ratio(c,p) for p in pixels);return values[len(values)//2]>=minimum
            candidates=[c for c in palette if readable(c)] or [c for c in ['#202020','#FFFFFF','#000000'] if readable(c)]
            if not candidates:continue
            original=item['color'];value=min(candidates,key=lambda c:sum((a-b)**2 for a,b in zip(rgb(c),rgb(original))))
            repairs.append(dict(key=item['key'],original=original,color=value));item['color']=value
    return repairs
