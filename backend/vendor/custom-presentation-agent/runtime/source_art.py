"""Trusted DrawingML paint as separate SVG objects, retaining native identities.

Only source XML is read here. Unsupported paint stays in the source background
and is recorded explicitly; it never becomes permission to flatten the deck.
The native exporter keeps the original DrawingML, not these SVG approximations.
"""
from lxml import etree
from runtime.security import NS,xml

SVG='http://www.w3.org/2000/svg'
def tag(parent,name,**attrs):
    return etree.SubElement(parent,'{%s}%s'%(SVG,name),{k.replace('_','-'):str(v) for k,v in attrs.items()})

def identity(shape):
    item=shape.find('.//p:cNvPr',NS)
    return int(item.get('id')) if item is not None else None

def palette(parts):
    colors={'dk1':'000000','lt1':'FFFFFF','dk2':'202020','lt2':'EEEEEE'}
    for name,data in parts.items():
        if name.startswith('ppt/theme/theme') and name.endswith('.xml'):
            for item in xml(data).findall('.//a:clrScheme/*',NS):
                if len(item):colors[etree.QName(item).localname]=item[0].get('val') if etree.QName(item[0]).localname!='sysClr' else item[0].get('lastClr','000000')
            break
    for alias,key in [('bg1','lt1'),('bg2','lt2'),('tx1','dk1'),('tx2','dk2')]:colors[alias]=colors.get(key,'000000')
    return colors

def ink(fill,colors,fallback=None):
    if fill is None or not len(fill):return fallback
    c=fill[0];kind=etree.QName(c).localname
    value=c.get('val','000000') if kind=='srgbClr' else c.get('lastClr','000000') if kind=='sysClr' else colors.get(c.get('val'),'000000') if kind=='schemeClr' else None
    if not value or len(value)!=6:raise ValueError('source_paint_color')
    rgb=[int(value[i:i+2],16) for i in (0,2,4)];alpha=1
    for change in c:
        op=etree.QName(change).localname;v=float(change.get('val',100000))/100000
        if op=='alpha':alpha=v
        elif op in ('lumMod','shade'):rgb=[round(x*v) for x in rgb]
        elif op=='lumOff':rgb=[round(x+255*v) for x in rgb]
        elif op=='tint':rgb=[round(x+(255-x)*v) for x in rgb]
        elif op not in ('satMod',):raise ValueError('source_color_transform')
    return '#'+''.join('%02X'%max(0,min(255,x)) for x in rgb),alpha

def source_node(shape,colors):
    name=etree.QName(shape).localname
    if name=='grpSp':
        transform=shape.find('p:grpSpPr/a:xfrm',NS)
        if transform is None or transform.get('rot','0')!='0':raise ValueError('source_group_transform')
        off,ext,child,extent=[transform.find('a:'+k,NS) for k in ('off','ext','chOff','chExt')]
        if any(v is None for v in (off,ext,child,extent)):raise ValueError('source_group_geometry')
        sx=float(ext.get('cx'))/max(1,float(extent.get('cx')));sy=float(ext.get('cy'))/max(1,float(extent.get('cy')))
        result=etree.Element('{%s}g'%SVG,nsmap={None:SVG},transform='translate(%s %s) scale(%s %s) translate(%s %s)'%(float(off.get('x'))/12700,float(off.get('y'))/12700,sx,sy,-float(child.get('x'))/12700,-float(child.get('y'))/12700))
        result.set('data-source-object',str(identity(shape)))
        for item in shape:
            if etree.QName(item).localname in ('sp','cxnSp','grpSp'):
                piece=source_node(item,colors)
                if piece is not None:result.append(piece)
            elif etree.QName(item).localname not in ('nvGrpSpPr','grpSpPr','extLst'):raise ValueError('source_group_object')
        return result if len(result) else None
    if name not in ('sp','cxnSp'):return None
    props=shape.find('p:spPr',NS)
    if props is None:return None
    # Empty text-only frames have no paint; keep typography as HTML bindings.
    geom=props.find('a:prstGeom',NS);custom=props.find('a:custGeom',NS)
    if geom is None and custom is None and props.find('a:solidFill',NS) is None:return None
    t=props.find('a:xfrm',NS)
    if t is None:raise ValueError('source_inherited_geometry')
    off,ext=t.find('a:off',NS),t.find('a:ext',NS)
    if off is None or ext is None:raise ValueError('source_geometry')
    x,y,w,h=[float(v)/12700 for v in (off.get('x'),off.get('y'),ext.get('cx'),ext.get('cy'))]
    result=etree.Element('{%s}g'%SVG,{'data-source-object':str(identity(shape))},nsmap={None:SVG})
    transforms=['translate(%s %s)'%(x,y)]
    if float(t.get('rot','0')):transforms.append('rotate(%s %s %s)'%(float(t.get('rot'))/60000,w/2,h/2))
    fx,fy=t.get('flipH') in ('1','true'),t.get('flipV') in ('1','true')
    if fx or fy:transforms+=['translate(%s %s)'%(w if fx else 0,h if fy else 0),'scale(%s %s)'%(-1 if fx else 1,-1 if fy else 1)]
    result.set('transform',' '.join(transforms))
    if props.find('a:gradFill',NS) is not None or props.find('a:blipFill',NS) is not None or props.find('a:pattFill',NS) is not None or props.xpath('./a:effectLst/*|./a:effectDag',namespaces=NS):raise ValueError('source_complex_paint')
    fill=ink(props.find('a:solidFill',NS),colors)
    line=props.find('a:ln',NS)
    stroke=ink(line.find('a:solidFill',NS),colors) if line is not None and line.find('a:noFill',NS) is None else None
    line_ref=shape.find('p:style/a:lnRef',NS)
    if line is not None and line.find('a:noFill',NS) is None and line.find('a:solidFill',NS) is None and line_ref is not None and line_ref.get('idx','0')!='0':raise ValueError('source_theme_line')
    # A style matrix reference is explicit unsupported paint, not black-by-default.
    if shape.find('p:style',NS) is not None and not fill and line is None:raise ValueError('source_theme_style')
    attrs={'fill':fill[0] if fill else 'none','stroke':stroke[0] if stroke else 'none'}
    if fill:attrs['fill-opacity']=fill[1]
    if stroke:
        attrs.update({'stroke-opacity':stroke[1],'stroke-width':float(line.get('w','12700'))/12700,'stroke-linecap':'round' if line.get('cap')=='rnd' else 'butt','stroke-linejoin':'round'})
        dash=line.find('a:prstDash',NS)
        if dash is not None and dash.get('val')!='solid':attrs['stroke-dasharray']='4 3' if dash.get('val') in ('dash','sysDash') else '1 2'
        if any(marker.get('type','none')!='none' for marker in [*line.findall('a:headEnd',NS),*line.findall('a:tailEnd',NS)]):raise ValueError('source_arrow_marker')
    kind=geom.get('prst') if geom is not None else 'custom' if custom is not None else 'rect'
    if kind in ('rect','roundRect','round1Rect','round2SameRect'):
        element=tag(result,'rect',x=0,y=0,width=w,height=h)
        if kind!='rect':element.set('rx',str(min(w,h)*.1667))
    elif kind=='ellipse':element=tag(result,'ellipse',cx=w/2,cy=h/2,rx=w/2,ry=h/2)
    elif kind in ('line','straightConnector1'):element=tag(result,'line',x1=0,y1=0,x2=w,y2=h);attrs['fill']='none'
    elif kind in ('triangle','rtTriangle','diamond'):
        points={'triangle':[(w/2,0),(w,h),(0,h)],'rtTriangle':[(0,0),(w,h),(0,h)],'diamond':[(w/2,0),(w,h/2),(w/2,h),(0,h/2)]}[kind]
        element=tag(result,'polygon',points=' '.join('%s,%s'%p for p in points))
    elif kind=='custom':
        for path in custom.findall('a:pathLst/a:path',NS):
            pw,ph=float(path.get('w',w*12700)),float(path.get('h',h*12700));commands=[]
            def point(p):return '%s %s'%(float(p.get('x'))/pw*w,float(p.get('y'))/ph*h)
            for command in path:
                op=etree.QName(command).localname;pts=command.findall('a:pt',NS)
                if op in ('moveTo','lnTo'):commands.append(('M' if op=='moveTo' else 'L')+point(pts[0]))
                elif op in ('cubicBezTo','quadBezTo'):commands.append(('C' if op=='cubicBezTo' else 'Q')+' '.join(point(p) for p in pts))
                elif op=='close':commands.append('Z')
                else:raise ValueError('source_path_command')
            element=tag(result,'path',d=' '.join(commands))
            for k,v in attrs.items():element.set(k,str(v))
            if path.get('fill')=='none':element.set('fill','none')
        return result
    else:raise ValueError('source_preset_'+kind)
    for k,v in attrs.items():element.set(k,str(v))
    return result

def compile_source_art(root,layout,analysis,parts):
    objects=[];unsupported=[];tree=root.find('p:cSld/p:spTree',NS)
    if tree is None:return dict(objects=[],unsupported=[])
    colors=palette(parts)
    ordered=list(tree);geometry={item['shapeId']:item.get('box',{}) for item in layout.get('sourceObjects',[])}
    branding=set(layout.get('htmlPreserveShapeIds',[]))|{slot['shapeId'] for slot in layout.get('slots',[]) if slot.get('role') in ('brand','logo')}
    def branded(shape):return bool(branding.intersection(int(value) for value in shape.xpath('.//p:cNvPr/@id',namespaces=NS)))
    def bounds(shape):
        known=geometry.get(identity(shape))
        if known:return known
        transform=shape.find('p:spPr/a:xfrm',NS)
        if transform is None:return None
        off,ext=transform.find('a:off',NS),transform.find('a:ext',NS)
        return dict(x=float(off.get('x'))/12700,y=float(off.get('y'))/12700,w=float(ext.get('cx'))/12700,h=float(ext.get('cy'))/12700) if off is not None and ext is not None else None
    def overlaps(a,b):return a and b and min(a['x']+a['w'],b['x']+b['w'])>max(a['x'],b['x'])+1 and min(a['y']+a['h'],b['y']+b['h'])>max(a['y'],b['y'])+1
    def contains_picture(shape):return etree.QName(shape).localname=='pic' or shape.find('.//p:pic',NS) is not None
    for index,shape in enumerate(ordered):
        if etree.QName(shape).localname not in ('sp','cxnSp','grpSp'):continue
        if branded(shape):continue
        try:
            # A bitmap above a native header must stay above that header in
            # HTML too. Repainting the header over a logo retained in the
            # underlay made it disappear. Keep this paint with its picture in
            # the HTML underlay; the PPTX still retains both native objects.
            if any(contains_picture(later) and overlaps(bounds(shape),bounds(later)) for later in ordered[index+1:]):
                raise ValueError('source_paint_below_picture')
            if any(branded(later) and overlaps(bounds(shape),bounds(later)) for later in ordered[index+1:]):raise ValueError('source_paint_below_brand_text')
            piece=source_node(shape,colors)
            if piece is None:continue
            # Non-paint text boxes are not meaningful native art objects.
            if not piece.xpath('.//*[@fill!="none" or @stroke!="none"]'):continue
            objects.append(dict(shapeId=identity(shape),kind=etree.QName(shape).localname,svg=etree.tostring(piece,encoding='unicode'),editable=True))
        except (ValueError,TypeError,KeyError,ZeroDivisionError) as error:
            unsupported.append(dict(shapeId=identity(shape),feature=str(error),action='retained native; source background fallback for HTML'))
    return dict(objects=objects,unsupported=unsupported)

def source_art_markup(style,scene=None):
    art=style.get('sourceHtml',{}).get('nativeArt',{});removed={e['shapeId'] for e in (scene or {}).get('sourceShapeEdits',[])}
    objects=[]
    for item in art.get('objects',[]):
        if item['shapeId'] in removed:continue
        if not removed:objects.append(item['svg']);continue
        root=etree.fromstring(item['svg'].encode())
        for node in list(root.xpath('.//*[@data-source-object]')):
            if int(node.get('data-source-object')) in removed:node.getparent().remove(node)
        objects.append(etree.tostring(root,encoding='unicode'))
    if not objects:return ''
    return '<svg xmlns="%s" class="native-source-art" data-native-source-art="true" viewBox="0 0 %s %s" style="position:absolute;inset:0;width:100%%;height:100%%;pointer-events:none;overflow:visible">%s</svg>'%(SVG,style['canvasWidth'],style['canvasHeight'],''.join(objects))

def detach_source_art(root,art):
    ids={item['shapeId'] for item in art.get('objects',[])}
    tree=root.find('p:cSld/p:spTree',NS)
    if tree is not None:
        for shape in list(tree):
            if identity(shape) in ids:tree.remove(shape)

