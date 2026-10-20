import {load} from 'cheerio';
import {createHash} from 'node:crypto';
import type {HtmlSlideCopy} from './html-domain.js';

const paths=(slide:HtmlSlideCopy)=>{
 const entries:Array<[string,string]>=[
  ['title',slide.title],...slide.paragraphs.map((value,i)=>[`paragraphs.${i}`,value] as [string,string]),
  ...(['cards','steps','metrics'] as const).flatMap(field=>slide[field].flatMap((item,i)=>Object.entries(item).map(([key,value])=>[`${field}.${i}.${key}`,value] as [string,string]))),
  ['takeaway',slide.takeaway],
 ];return new Map(entries.filter(([,value])=>!!value));
};

/** Bind semantic copy into the uploaded, already cleared DOM. Native paint is
 * rendered separately once, and remains editable in the PowerPoint export.
 * No literal source words, sample values or arbitrary model IDs can survive. */
export function realizeSourceComposition(slide:HtmlSlideCopy,source:any,photoCount:number):HtmlSlideCopy|undefined{
  if(!source.sourceHtml?.html||source.role!=='content')return;
  const generated=/\bdata-source-composition-key=/.test(slide.html??'');
  const managed=!slide.html?.trim()||generated;
  if(!managed)return;
  const signature=createHash('sha256').update(JSON.stringify([5,source.sourceHtml.digest,slide.title,slide.paragraphs,slide.cards,slide.steps,slide.metrics,slide.takeaway,slide.chart,slide.table,slide.sourceBindings,photoCount])).digest('hex');
  if(generated&&slide.html!.includes(`data-source-composition-key="${signature}"`))return slide;
  const regions:any[]=source.sourceHtml.textRegions??[];
  const ordinals:any[]=source.sourceHtml.structuralOrdinals??[];
  const title=regions.find(r=>r.shapeId===source.title?.shapeId);
  // Native captions can be 15.7px high. Dropping them as "too small" silently
  // discarded the model's correct binding and piled its copy into the last
  // remaining field. Keep the host; repair its typography/flow instead.
  const body=regions.filter(r=>r!==title&&!ordinals.some(o=>o.shapeId===r.shapeId)&&!['title','header','photo','brand','logo','footer','page_number','decoration'].includes(r.role)&&r.container?.role!=='ordinal'&&r.box.w>=30&&r.box.h>=6);
  if(!title||!body.length)return;
  // A quantitative plot needs its own source data frame. If the source has
  // no such frame, the existing chart composer uses the cleared chart plane.
  const kind=slide.chart?'chart':slide.table?'table':undefined;
  const dataFrame=kind?(source.dataFrames??[]).find((frame:any)=>frame.kind===kind):undefined;
  if(kind&&!dataFrame)return;
  const values=paths(slide),assignments=new Map<number,string[]>(),used=new Set<string>(),localBoxes=new Map<number,any>();
  // A single confirmed result cannot be squeezed into an agenda's tiny
  // ordinal. Reuse its existing unfilled text column as one metric group;
  // source title, art and filled panels are left in place.
  if(slide.metrics.length===1&&!slide.cards.length&&!slide.steps.length&&!kind&&!photoCount&&!body.some(r=>r.container)){
    const canvas=source.sourceHtml.canvas??source.styleSystem?.canvas;
    const candidates=body.filter(r=>r.box.w>=(canvas?.width??1280)*.2),seed=[...candidates].sort((a,b)=>b.box.w-a.box.w)[0];
    const column=seed?candidates.filter(r=>Math.abs(r.box.x-seed.box.x)<seed.box.w*.2):[];
    if(column.length>=2){
      const b={x:Math.min(...column.map(r=>r.box.x)),y:Math.min(...column.map(r=>r.box.y)),w:0,h:0};
      b.w=Math.max(...column.map(r=>r.box.x+r.box.w))-b.x;b.h=Math.max(...column.map(r=>r.box.y+r.box.h))-b.y;
      const t=title.box,overlap=Math.min(b.x+b.w,t.x+t.w)>Math.max(b.x,t.x)&&Math.min(b.y+b.h,t.y+t.h)>Math.max(b.y,t.y);
      if(b.h>=(canvas?.height??720)*.25&&!overlap){
        const $=load(source.sourceHtml.html,null,false);$('[data-source-native-layer]').remove();
        for(const region of regions){const node=$(`[data-source-shape="${region.shapeId}"]`).first();if(region!==title)node.remove();else node.empty().attr('data-text','title').css('font-weight','700');}
        $('.source-slide').addClass('source-composition').attr('data-source-composition-key',signature);
        const host=$('<article></article>').attr('data-source-shape',String(seed.shapeId)).css({position:'absolute',left:b.x+'px',top:b.y+'px',width:b.w+'px',height:b.h+'px',display:'flex','flex-direction':'column','justify-content':'center',gap:'24px','font-family':String(seed.font??'Arial'),'font-size':'26px',color:seed.textStyles?.body?.color??seed.color??'#FFFFFF'});
        const value=slide.metrics[0]!.value,size=Math.max(40,Math.min(96,b.h*.28,b.w/Math.max(1,value.length*.58)));
        host.append($('<strong></strong>').attr('data-text','metrics.0.value').css({'font-size':size+'px','line-height':'1.05',color:source.styleSystem?.accent??seed.color??'#0077FF'}));
        for(const key of [...values.keys()].filter(key=>!['title','metrics.0.value'].includes(key)))host.append($('<p></p>').attr('data-text',key).css({margin:'0','line-height':'1.2'}));
        $('.source-slide').append(host);return {...slide,stencilId:'source-layout',html:$.html(),css:'.source-composition{position:relative;width:100%;height:100%}.source-composition *{box-sizing:border-box;min-width:0}'};
      }
    }
  }
  const assign=(id:number,keys:string[])=>{
    if(!regions.some(r=>r.shapeId===id))return;
    const valid=[...new Set(keys)].filter(key=>values.has(key)&&!used.has(key));
    if(!valid.length)return;assignments.set(id,[...(assignments.get(id)??[]),...valid]);valid.forEach(key=>used.add(key));
  };
  assign(title.shapeId,['title']);
  for(const binding of slide.sourceBindings??[]){
    const ordinal=ordinals.find(o=>o.shapeId===binding.shapeId);
    if(ordinal){
      // Some authors express agenda entries as metrics. Only an exact
      // matching ordinal may occupy the small badge; its prose stays outside.
      assign(binding.shapeId,binding.paths.filter(path=>/^metrics\.\d+\.value$/.test(path)&&/^0?\d{1,2}$/.test(values.get(path)??'')&&Number(values.get(path))===ordinal.ordinal));
      continue;
    }
    if(binding.shapeId===title.shapeId||!body.some(r=>r.shapeId===binding.shapeId))continue;
    const group=(source.sourceHtml.textGroups??[]).find((g:any)=>g.origin==='native-container'&&g.headingShapeId===binding.shapeId);
    for(const path of binding.paths)assign(group&&/\.(?:body|label)$/.test(path)?group.bodyShapeId:binding.shapeId,[path]);
  }
  const groups=(source.sourceHtml.textGroups??[]).filter((g:any)=>body.some(r=>r.shapeId===g.headingShapeId)&&body.some(r=>r.shapeId===g.bodyShapeId))
    .sort((a:any,b:any)=>Math.abs(a.box.y-b.box.y)<12?a.box.x-b.box.x:a.box.y-b.box.y);
  for(const field of ['cards','steps','metrics'] as const){
    slide[field].forEach((_,i)=>{
      const head=`${field}.${i}.${field==='metrics'?'value':'title'}`,body=`${field}.${i}.${field==='metrics'?'label':'body'}`;
      const group=groups.find((g:any)=>assignments.get(g.headingShapeId)?.includes(head)||assignments.get(g.bodyShapeId)?.includes(body))??groups.find((g:any)=>!assignments.has(g.headingShapeId)&&!assignments.has(g.bodyShapeId));if(!group)return;
      assign(group.headingShapeId,[`${field}.${i}.${field==='metrics'?'value':'title'}`]);
      assign(group.bodyShapeId,[`${field}.${i}.${field==='metrics'?'label':'body'}`]);
    });
  }
  // Source bodies often contain whole cards (heading + explanation) rather
  // than separate text shapes. Keep each semantic pair together in its host.
  const bundles:string[][]=[];
  for(const field of ['cards','steps','metrics'] as const)slide[field].forEach((_,i)=>bundles.push(Object.keys(slide[field][i]!).map(key=>`${field}.${i}.${key}`).filter(key=>!used.has(key))));
  slide.paragraphs.forEach((_,i)=>{if(!used.has(`paragraphs.${i}`))bundles.push([`paragraphs.${i}`]);});
  if(slide.takeaway&&!used.has('takeaway'))bundles.push(['takeaway']);
  const ordered=[...body].sort((a,b)=>Math.abs(a.box.y-b.box.y)<12?a.box.x-b.box.x:a.box.y-b.box.y);
  const free=ordered.filter(r=>!assignments.has(r.shapeId));
  // A timeline has a caption for every node. When only one concluding thought
  // remains, use that actual caption row as one explanation, rather than
  // squeezing it under the last pill or leaving it in a tiny corner.
  if(slide.steps.length>=3&&slide.takeaway&&!used.has('takeaway')&&free.length>=3&&
    free.every(r=>!r.container)&&Math.max(...free.map(r=>r.box.y))-Math.min(...free.map(r=>r.box.y))<12){
    const first=free[0]!,b={x:Math.min(...free.map(r=>r.box.x)),y:Math.min(...free.map(r=>r.box.y)),w:0,h:0};
    b.w=Math.max(...free.map(r=>r.box.x+r.box.w))-b.x;
    const height=source.sourceHtml.canvas?.height??720;
    b.h=Math.min(120,height*.82-b.y);if(b.h>=40){localBoxes.set(first.shapeId,b);assign(first.shapeId,['takeaway']);}
  }
  for(const [index,bundle] of bundles.filter(b=>b.length).entries()){
    const region=free[Math.min(index,free.length-1)]??ordered.at(-1);if(region)assign(region.shapeId,bundle);
  }
  if([...values.keys()].some(key=>!used.has(key)))return;
  const $=load(source.sourceHtml.html,null,false);
  $('[data-source-native-layer]').remove();
  $('.source-slide').addClass('source-composition').attr('data-source-composition-key',signature);
  // Quantitative objects are replaced by exact bound data, never by sample
  // SVG/series. Only the matching original frame receives the new plot.
  $('[data-visual]').each((_,node)=>{$(node).parent().remove();});
  for(const region of regions){
    const frame=$(`[data-source-shape="${region.shapeId}"]`).first();
    if(!frame.length)continue;frame.empty();
    const keys=assignments.get(region.shapeId)??[];
    const ordinal=ordinals.find(o=>o.shapeId===region.shapeId);
    if(ordinal){frame.attr(keys.length?'data-text':'data-number',keys[0]??String(ordinal.ordinal));continue;}
    if(!keys.length){frame.remove();continue;}
    const box=localBoxes.get(region.shapeId)??region.textBox;
    if(box)frame.css({left:box.x+'px',top:box.y+'px',width:box.w+'px',height:box.h+'px'});
    frame.css('gap','8px');
    // Increase short copy within its original host; long prose stays close to
    // the template's readable size. The measured HTML fitter verifies the fit.
    const count=keys.reduce((n,key)=>n+(values.get(key)?.length??0),0),insets=region.insets??[0,0,0,0],bounds=box??region.box;
    const inner={w:Math.max(1,bounds.w-insets[1]-insets[3]),h:Math.max(1,bounds.h-insets[0]-insets[2])};
    const fit=Math.sqrt(inner.w*inner.h/Math.max(1,count)*1.35);
    const size=region===title?region.size:Math.max(22,Math.min(36,(region.size??24)*1.25,fit*.85));
    if(region!==title)frame.css('font-size',`${Math.round(size*10)/10}px`);
    // A single semantic field binds to the real source frame itself. Nesting
    // another binding under that same host would make the older row-repair
    // normalizer repeat it on both the parent and its child.
    const textStyle=(key:string)=>region.textStyles?.[/\.(?:title|value)$/.test(key)?'heading':'body'];
    if(keys.length===1&&region!==title){
      const native=textStyle(keys[0]!);if(native?.color)frame.css('color',native.color);
      if(native?.bold!==undefined||/\.(?:title|value)$/.test(keys[0]!))frame.css('font-weight',native?.bold||/\.(?:title|value)$/.test(keys[0]!)?'700':'400');
      if(/metrics\.\d+\.value$/.test(keys[0]!)&&native?.size)frame.css('font-size',Math.min(native.size,Math.max(32,fit))+'px');
      frame.attr('data-text',keys[0]!);continue;
    }
    for(const key of keys){
      const strong=/\.(?:title|value)$/.test(key),tag=key==='title'?'h1':strong?'strong':'p';
      const native=textStyle(key);
      frame.append($(`<${tag}></${tag}>`).attr('data-text',key).css({margin:'0',display:'block','font-size':/metrics\.\d+\.value$/.test(key)&&native?.size?Math.min(native.size,Math.max(32,fit))+'px':'inherit','line-height':key==='title'?'1.1':'1.2',...(native?.color?{color:native.color}:{}),...(strong||key==='title'?{'font-weight':'700'}:{})}));
    }
  }
  // Separate native title/caption shapes inside one existing panel must flow
  // together. Increasing both fonts in their old fixed-height boxes caused
  // clipping and collisions even when most of the original panel was empty.
  // Only borrow verified space inside a real, unmodified native container.
  const paired=new Set<number>();
  const flow=(head:any,caption:any,bounds:any,groupId:string)=>{
    const heading=$(`[data-source-shape="${head.shapeId}"]`).first(),description=$(`[data-source-shape="${caption.shapeId}"]`).first();
    if(!heading.length||!description.length||bounds.h<70||bounds.w<60)return;
    const parent=$('<div></div>').attr('data-source-flow',groupId).css({position:'absolute',left:bounds.x+'px',top:bounds.y+'px',width:bounds.w+'px',height:bounds.h+'px',display:'flex','flex-direction':'column',gap:'12px'});
    heading.css({position:'relative',left:'auto',top:'auto',width:'100%',height:'auto',padding:'0',flex:'0 0 auto','font-size':'22px','line-height':'1.2'});
    description.css({position:'relative',left:'auto',top:'auto',width:'100%',height:'auto',padding:'0',flex:'1 1 auto','min-height':'0','font-size':'22px','line-height':'1.2'});
    parent.append(heading,description);$('.source-slide').append(parent);paired.add(head.shapeId);paired.add(caption.shapeId);
  };
  for(const group of groups){
    if(group.origin==='native-container')continue;
    const head=regions.find(r=>r.shapeId===group.headingShapeId),caption=regions.find(r=>r.shapeId===group.bodyShapeId);
    if(!head||!caption||!assignments.has(head.shapeId)||!assignments.has(caption.shapeId))continue;
    const containers=(source.editableShapes??[]).filter((shape:any)=>shape.kind==='shape'&&shape.role==='container'&&!shape.hasText&&shape.box)
      .map((shape:any)=>({x:shape.box.x*4/3,y:shape.box.y*4/3,w:shape.box.w*4/3,h:shape.box.h*4/3}))
      .filter((b:any)=>b.x<=head.box.x+1&&b.y<=head.box.y+1&&b.x+b.w>=Math.max(head.box.x+head.box.w,caption.box.x+caption.box.w)-1&&b.y+b.h>=caption.box.y+caption.box.h-1)
      .sort((a:any,b:any)=>a.w*a.h-b.w*b.h);
    const panel=containers[0];if(!panel)continue;
    const pad=Math.min(20,panel.w*.06),x=Math.max(head.box.x,caption.box.x,panel.x+pad),y=Math.max(head.box.y,panel.y+pad);
    let bottom=panel.y+panel.h-pad;
    for(const frame of (source.photoFrames??[]).slice(0,photoCount)){
      const b=frame.box;if(b&&b.x*4/3<x+panel.w&&(b.x+b.w)*4/3>x&&b.y*4/3>y)bottom=Math.min(bottom,b.y*4/3-12);
    }
    flow(head,caption,{x,y,w:Math.min(panel.x+panel.w-pad,Math.max(head.box.x+head.box.w,caption.box.x+caption.box.w))-x,h:bottom-y},String(group.id??head.shapeId));
  }
  // A shallow lead-in followed by a tall prose field in the same native
  // column is another real source pair, even when its role was simply body.
  // Redistribute only their combined rectangle, never the title/art/photo.
  for(const head of ordered){
    if(paired.has(head.shapeId)||head.container||head.textBox||head.box.h>Math.max(36,head.size*2)||!assignments.has(head.shapeId))continue;
    const caption=ordered.find(r=>r!==head&&!paired.has(r.shapeId)&&!r.container&&!r.textBox&&assignments.has(r.shapeId)&&Math.abs(r.box.x-head.box.x)<3&&Math.abs(r.box.w-head.box.w)<3&&r.box.h>=100&&r.box.y>=head.box.y+head.box.h-1&&r.box.y-head.box.y-head.box.h<=24);
    if(caption)flow(head,caption,{x:head.box.x,y:head.box.y,w:head.box.w,h:caption.box.y+caption.box.h-head.box.y},'column-'+head.shapeId);
  }
  const frameStyle=(b:any)=>`position:absolute;left:${b.x*4/3}px;top:${b.y*4/3}px;width:${b.w*4/3}px;height:${b.h*4/3}px`;
  if(dataFrame) $('.source-slide').append($('<div></div>').attr('style',frameStyle(dataFrame.box)).append($('<div></div>').attr('data-visual',kind!).attr('style','width:100%;height:100%')));
  for(const [index,frame] of (source.photoFrames??[]).slice(0,photoCount).entries()){
    $(`[data-source-shape="${frame.shapeId}"]`).remove();
    $('.source-slide').append($('<img>').attr('data-image',String(index)).attr('style',frameStyle(frame.box)+';object-fit:contain'));
  }
  if(photoCount>(source.photoFrames?.length??0))return;
  return {...slide,stencilId:'source-layout',html:$.html(),css:generated&&slide.css?slide.css:'.source-composition{position:relative;width:100%;height:100%}.source-composition *{box-sizing:border-box;min-width:0}'};
}
