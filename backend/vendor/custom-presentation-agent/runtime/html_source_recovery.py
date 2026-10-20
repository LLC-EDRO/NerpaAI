"""Source-frame HTML for one malformed authored slide; no preset recomposition."""
def recover_source_html(copy,layout,images=()):
    reference=copy.get('sourceDesign') or {};title=reference.get('title') or {}
    anchors=[a for a in reference.get('textAnchors',[]) if a.get('shapeId')!=title.get('shapeId') and a.get('role') not in ('label','footer','brand','logo','page_number') and a.get('characters',10)>4]
    frames=[]
    for anchor in sorted(anchors,key=lambda a:(a['box']['y'],a['box']['x'])):
        b=anchor['box'];previous=next((p for p in frames if abs(p['x']-b['x'])<8 and abs(p['w']-b['w'])<16 and b['y']>=p['y'] and b['y']-p['y']-p['h']<25),None)
        if previous:previous['h']=max(previous['h'],b['y']+b['h']-previous['y'])
        else:frames.append(dict(b))
    groups=[]
    for i,value in enumerate(copy.get('paragraphs',[])):
        if value:groups.append([(f'paragraphs.{i}','p')])
    for field,first,last in [('cards','title','body'),('steps','title','body'),('metrics','value','label')]:
        for i,value in enumerate(copy.get(field,[])):
            groups.append([(f'{field}.{i}.{key}','h2' if key==first else 'p') for key in (first,last) if value.get(key)])
    if copy.get('takeaway'):groups.append([('takeaway','p')])
    visual=next((k for k in ('table','chart') if copy.get(k)),None)
    visual_box=None
    if visual:
        visual_box=next((f['box'] for f in reference.get('dataFrames',[]) if f.get('kind')==visual),None)
        visual_box=visual_box or next((f['box'] for f in reference.get('photoFrames',[])),None) or dict(layout['body'])
        def overlaps(b):return min(b['x']+b['w'],visual_box['x']+visual_box['w'])>max(b['x'],visual_box['x']) and min(b['y']+b['h'],visual_box['y']+visual_box['h'])>max(b['y'],visual_box['y'])
        frames=[b for b in frames if not overlaps(b)]
    def image_overlap(b):return any(min(b['x']+b['w'],p['x']+p['w'])>max(b['x'],p['x']) and min(b['y']+b['h'],p['y']+p['h'])>max(b['y'],p['y']) for p in images)
    frames=[b for b in frames if not image_overlap(b)]
    if not frames:frames=[dict(layout['body'])]
    # Keep all data bindings even when fewer source groups than new points.
    # They flow within the corresponding original field, not across the page.
    assigned=[[] for _ in frames]
    for i,group in enumerate(groups):assigned[min(len(frames)-1,i*len(frames)//max(1,len(groups)))].extend(group)
    t=title.get('box') or layout['title']
    css='main{position:relative;width:100%%;height:100%%}h1,h2,p{margin:0;min-width:0;min-height:0}h1{position:absolute;left:%spt;top:%spt;width:%spt;height:%spt;font-size:%spt;line-height:1.1}'%tuple([t[k] for k in ('x','y','w','h')]+[title.get('size') or layout['headingSize']])
    markup='<main><h1 data-text="title"></h1>'
    for i,(b,fields) in enumerate(zip(frames,assigned)):
        if not fields:continue
        markup+='<section class="source-recovery-%d">'%i+''.join('<%s data-text="%s"></%s>'%(tag,path,tag) for path,tag in fields)+'</section>'
        css+='.source-recovery-%d{position:absolute;left:%spt;top:%spt;width:%spt;height:%spt;display:flex;flex-direction:column;gap:6pt;font-size:16pt;line-height:1.2}.source-recovery-%d h2{font-size:18pt;flex:0 0 auto}.source-recovery-%d p{flex:1 1 0}'%tuple([i]+[b[k] for k in ('x','y','w','h')]+[i,i])
    if visual:
        markup+='<div class="source-recovered-visual" data-visual="%s"></div>'%visual
        css+='.source-recovered-visual{position:absolute;left:%spt;top:%spt;width:%spt;height:%spt}'%tuple(visual_box[k] for k in ('x','y','w','h'))
    for i,picture in enumerate(images):
        markup+='<img class="source-recovered-photo-%d" data-image="%d">'%(i,i)
        css+='.source-recovered-photo-%d{position:absolute;left:%spt;top:%spt;width:%spt;height:%spt;object-fit:cover}'%tuple([i]+[picture[k] for k in ('x','y','w','h')])
    return dict(copy,html=markup+'</main>',css=css,deckCss='')
