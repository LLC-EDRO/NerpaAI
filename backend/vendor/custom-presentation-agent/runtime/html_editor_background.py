"""Hide exact HTML bindings for editing; no PDF glyph search or PPTX converter.

The source is the immutable HTML already accepted by the slide renderer.
Other text, photographs, chart marks and source-backed fills stay untouched.
"""
from pathlib import Path
from lxml import html,etree
from playwright.sync_api import sync_playwright
from runtime.render import font_environment
from runtime.editor_typography import editor_font
from runtime.html_deck import rasterize_html_pdf


def html_editor_background(folder,request):
    output=Path(request['output']);output.mkdir(parents=True,exist_ok=True)
    document=html.document_fromstring((Path(folder)/'previews/presentation.html').read_text())
    sections=document.xpath('//body/section[@data-slide]')
    page=request['page']
    if type(page) is not int or not 0<=page<len(sections):raise ValueError('pptx_editor_page_invalid')
    for index,section in enumerate(sections):
        if index!=page:section.getparent().remove(section)
    fields=request['fields'];keys={f['path']:f['path'].removeprefix('native.fields.') for f in fields}
    if any(not path.startswith('native.fields.') or not key or len(key)>100 for path,key in keys.items()):
        raise ValueError('pptx_editor_field_invalid')
    config=output/'browser-config';config.mkdir(exist_ok=True)
    env=font_environment(config,sorted({f.get('font','Arial') for f in fields}))
    content='<!doctype html>\n'+etree.tostring(document,encoding='unicode',method='html')
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--renderer-process-limit=1'],env=env,timeout=12000)
        try:
            tab=browser.new_page(viewport=dict(width=round(request['width']*4/3),height=round(request['height']*4/3)))
            tab.route('**/*',lambda route:route.abort())
            tab.set_content(content,wait_until='load',timeout=12000)
            tab.evaluate('async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})))}')
            appearances=tab.evaluate('''keys=>{
              const slide=document.querySelector('body>section[data-slide]'),root=slide.querySelector('.ai-host')?.shadowRoot||slide;
              const result={};
              for(const [path,key] of Object.entries(keys)){
                const nodes=[...root.querySelectorAll('[data-key]')].filter(e=>e.dataset.key===key);
                if(nodes.length!==1)throw Error('editor_binding_missing');
                const el=nodes[0],s=getComputedStyle(el),size=parseFloat(s.fontSize)*.75;
                const rgb=s.color.match(/[\\d.]+/g)||['0','0','0'];
                result[path]={font:s.fontFamily.split(',')[0].replace(/["']/g,''),size,
                  bold:Number(s.fontWeight)>=600,color:'#'+rgb.slice(0,3).map(v=>Math.round(Number(v)).toString(16).padStart(2,'0')).join(''),
                  lineHeight:(parseFloat(s.lineHeight)||parseFloat(s.fontSize)*1.16)/parseFloat(s.fontSize),
                  baselineTop:size*.9,baselineBottom:size*.18,insetX:0,verticalAlign:'top',
                  htmlStyle:{paddingLeft:parseFloat(s.paddingLeft)*.75,paddingRight:parseFloat(s.paddingRight)*.75,
                    paddingTop:parseFloat(s.paddingTop)*.75,paddingBottom:parseFloat(s.paddingBottom)*.75,
                    display:s.display.includes('flex')?'flex':s.display.includes('grid')?'grid':'block',flexDirection:s.flexDirection,direction:s.direction,justifyItems:s.justifyItems,
                    justifyContent:s.justifyContent,alignItems:s.alignItems,letterSpacing:s.letterSpacing==='normal'?0:parseFloat(s.letterSpacing)*.75,
                    whiteSpace:s.whiteSpace,overflowWrap:s.overflowWrap,textAlign:s.textAlign}};
                // Preserve the element's background, dimensions and layout.
                // Hiding the element itself would erase a source-backed fill.
                el.style.setProperty('color','transparent','important');
                el.style.setProperty('-webkit-text-fill-color','transparent','important');
                el.style.setProperty('text-shadow','none','important');
              }
              return result;
            }''',keys)
            tab.pdf(path=str(output/'editor.pdf'),print_background=True,prefer_css_page_size=True)
        finally:browser.close()
    rasterize_html_pdf(output/'editor.pdf',output,1)
    fonts={}
    for appearance in appearances.values():
        appearance['font']=editor_font(appearance['font'],output,fonts)
    return dict(paths=list(keys),appearances=appearances,fonts=list(fonts.values()))
