"""Choose the final chart adapter AFTER HTML rendering, preserving evidence.

Image charts are clips of the actual accepted HTML PDF, not AI-painted data.
Bounded PNG bytes travel with the measured scene through repair/editor/final
export, so no host paths or new external downloads enter the sandbox protocol.
"""
import base64
import hashlib
import io
import re
from pathlib import Path
from PIL import Image
from lxml import etree

MAX_PICTURE_BYTES=256*1024


def chart_presentation(raw=None,css='',kind='line',profile=None):
    raw=raw if isinstance(raw,dict) else {}
    mode=raw.get('mode') if raw.get('mode') in ('auto','native','image') else 'auto'
    treatment=raw.get('treatment') if raw.get('treatment') in ('plain','gradient','soft-area') else 'plain'
    if treatment=='soft-area' and kind not in ('line','xy'):treatment='plain'
    reason=str(raw.get('reason','')).strip()[:240]
    profile=profile or {}
    source_treatment=profile.get('treatment','plain')
    if source_treatment!='plain':treatment=source_treatment
    if treatment=='soft-area' and kind not in ('line','xy'):treatment='plain'
    rich=bool(profile.get('fills') or profile.get('radial') or profile.get('bars') or profile.get('line',{}).get('curve')=='monotone' or profile.get('line',{}).get('areaOpacity',0)>0)
    custom=bool(re.search(r'(?:svg|polyline|data-chart-label|data-chart-value)[^{]*\{[^}]*(?:filter|opacity|fill|stroke|transform|mix-blend)',css,re.I))
    image=treatment!='plain' or rich or custom or mode=='image' and bool(reason)
    return dict(mode='image' if image else 'native',treatment=treatment,
                sourceLayoutId=profile.get('sourceLayoutId'),reason=('Source chart appearance: '+str(profile.get('sourceLayoutId','uploaded reference'))) if rich else reason if image and reason else 'HTML chart treatment requires a picture' if image else 'Standard editable chart')


def decorate_chart_svg(svg,item):
    treatment=item.get('presentation',{}).get('treatment','plain')
    root=etree.fromstring(svg.encode());ns='http://www.w3.org/2000/svg'
    from runtime.html_chart_theme import apply_source_fills
    if apply_source_fills(root,item.get('_style',{}),'source-fill-'+hashlib.sha256(svg.encode()).hexdigest()[:10]):return etree.tostring(root,encoding='unicode')
    if treatment=='plain':return svg
    if treatment=='gradient':
        defs=etree.Element('{%s}defs'%ns);root.insert(0,defs);gradients={}
        for node in root.xpath('.//*[@data-chart-value] | .//*[local-name()="polyline"]'):
            key='stroke' if etree.QName(node).localname=='polyline' else 'fill'
            ink=node.get(key,'')
            if not re.fullmatch(r'#[A-Fa-f0-9]{6}',ink):continue
            if ink not in gradients:
                identity='chart-gradient-'+hashlib.sha256(svg.encode()+ink.encode()).hexdigest()[:12];gradients[ink]=identity
                gradient=etree.SubElement(defs,'{%s}linearGradient'%ns,id=identity,x1='0',y1='0',x2='0',y2='1')
                etree.SubElement(gradient,'{%s}stop'%ns,offset='0',**{'stop-color':ink,'stop-opacity':'1'})
                etree.SubElement(gradient,'{%s}stop'%ns,offset='1',**{'stop-color':ink,'stop-opacity':'.45'})
            node.set(key,'url(#'+gradients[ink]+')')
    elif treatment=='soft-area':
        # All coordinates come from the verified SVG, never model prose.
        data=item['data'];values=[v for s in data['series'] for v in s['values']]
        from runtime.chart_numbers import value_domain
        low,high=value_domain(data)
        from runtime.html_charts import chart_layout
        style=item.get('_style',{});s=chart_layout(data,item['box'],style)
        baseline=s['bottom']-(max(low,min(high,0))-low)/(high-low)*(s['bottom']-s['top'])
        for line in root.xpath('.//*[local-name()="polyline"]'):
            points=line.get('points','').split()
            if not points:continue
            left=points[0].split(',')[0];right=points[-1].split(',')[0]
            area=etree.Element('{%s}polygon'%ns,points=' '.join(points)+f' {right},{baseline} {left},{baseline}',fill=line.get('stroke'),opacity='.16')
            root.insert(0,area)
    return etree.tostring(root,encoding='unicode')


def capture_chart_pictures(scenes,output,force=False):
    if not any(scene.get('chart') and (force or scene['chart'].get('presentation',{}).get('mode')=='image') for scene in scenes):return
    import pymupdf
    path=Path(output)/'html-preview.pdf'
    if not path.is_file():path=Path(output)/'presentation.pdf'
    if not path.is_file():return
    with pymupdf.open(path) as pdf:
        for index,scene in enumerate(scenes):
            chart=scene.get('chart')
            if not chart or not force and chart.get('presentation',{}).get('mode')!='image':continue
            page=pdf[index];bounds=chart['box'];clip=pymupdf.Rect(bounds['x'],bounds['y'],bounds['x']+bounds['w'],bounds['y']+bounds['h']) & page.rect
            if clip.is_empty:continue
            pixels=page.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=clip,alpha=False)
            bitmap=Image.frombytes('RGB',(pixels.width,pixels.height),pixels.samples)
            bitmap.thumbnail((1800,1200))
            stream=io.BytesIO();bitmap.save(stream,format='PNG',optimize=True);payload=stream.getvalue()
            for colours in (256,128,64):
                if len(payload)<=MAX_PICTURE_BYTES:break
                stream=io.BytesIO();bitmap.quantize(colors=colours).save(stream,format='PNG',optimize=True);payload=stream.getvalue()
                if len(payload)<=MAX_PICTURE_BYTES:break
            if payload is None or len(payload)>MAX_PICTURE_BYTES:continue
            chart['picture']=dict(encoding='png-base64',data=base64.b64encode(payload).decode(),width=bitmap.width,height=bitmap.height)


def chart_picture_bytes(chart):
    picture=chart.get('picture',{})
    if picture.get('encoding')!='png-base64' or not isinstance(picture.get('data'),str) or len(picture['data'])>MAX_PICTURE_BYTES*4//3+4:return None
    try:
        payload=base64.b64decode(picture['data'],validate=True)
        if len(payload)>MAX_PICTURE_BYTES or not payload.startswith(b'\x89PNG\r\n\x1a\n'):return None
        with Image.open(io.BytesIO(payload)) as image:
            if image.width>1800 or image.height>1200 or image.width*image.height>2160000:return None
            image.verify()
        return payload
    except (ValueError,OSError):return None
