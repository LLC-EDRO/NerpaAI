"""The editor changes inputs of the same HTML revision, then remeasures it."""
import copy
import hashlib
import json


def edited_html_scene(slide):
    scene=copy.deepcopy(slide['native']['html'])
    fields=slide['native'].get('fields',{})
    for item in [*scene['texts'],*scene.get('cells',[])]:
        item['text']=fields.get(item['key'],item['text'])
        manual=slide.get('textStyles',{}).get('native.fields.'+item['key'],{})
        item['manualStyle']=bool(manual)
        item['manualGeometry']=any(key in manual for key in ('x','y','w','h'))
        item['manualAlign']='align' in manual
        for key in ('x','y','w','h','size','font','color','bold','align'):
            if key in manual:item[key]=manual[key]
    scene['title']=next((item['text'] for item in scene['texts'] if item['key']=='h_title'),scene['title'])
    scene['notes']=slide.get('notes',scene['notes']);scene['speech']=slide.get('speech',scene['speech'])
    if scene.get('table'):
        cells={tuple(item['cell']):item['text'] for item in scene['cells']}
        for r,row in enumerate([scene['table']['data']['headers'],*scene['table']['data']['rows']]):
            for c in range(len(row)):row[c]=cells[(r,c)]
    # Replacements must reach the HTML image binding as well as the file map.
    # Otherwise a saved scene references the former image and loses the photo.
    for image in scene.get('images',[]):
        replacement=next((value for value in slide.get('images',[]) if image.get('shapeId') is not None and value.get('shapeId')==image.get('shapeId') or
                          value.get('slotIndex') is not None and value.get('slotIndex')==image.get('slotIndex')),None)
        if replacement:
            image['image']=replacement['image']
            if replacement.get('fit') in ('cover','contain'):image['fit']=replacement['fit']
    return scene


def seal_html_revision(scene):
    fields=('key','text','x','y','w','h','size','font','color','bold','align','lineHeight','cell')
    # Browser CSS serialization can change line-height by a few millionths on
    # an unchanged page. Quantize measured typography/geometry only; semantic
    # chart/table values and the actual saved scene retain their exact values.
    measured={'x','y','w','h','size','lineHeight'}
    def stable(item,key):
        value=item[key]
        return round(float(value),4) if key in measured and isinstance(value,(float,int)) else value
    content=dict(sourceLayoutId=scene['sourceLayoutId'],authored=scene.get('authored'),sourceShapeEdits=scene.get('sourceShapeEdits',[]),
        text=[{key:stable(item,key) for key in fields if key in item} for item in [*scene['texts'],*scene.get('cells',[])]],
        table=scene.get('table'),chart=scene.get('chart'),images=scene.get('images',[]),notes=scene.get('notes',''),speech=scene.get('speech',''))
    digest=hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    previous=scene.get('htmlRevision',{})
    if previous.get('digest')==digest:return previous
    revision=dict(version=1,digest=digest,sourceLayoutId=scene['sourceLayoutId'])
    if previous.get('digest'):revision['parentDigest']=previous['digest']
    scene['htmlRevision']=revision
    return revision
