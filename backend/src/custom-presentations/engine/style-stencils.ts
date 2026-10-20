import type {HtmlCopy,HtmlSlideCopy} from './html-domain.js';
import type {Project} from './domain.js';
import {dataViews,dataChartChoices,type PresentationDataView} from './data-contract.js';
import type {HtmlWarning} from './html-domain.js';
import {realizeTerminalHtml} from './terminal-html.js';
import {chartExplanation,technicalDataCopy,dataFoldComparisonMatches,correctEndpointDuration} from './data-explanation.js';
import {realizeSourceComposition} from './source-composition.js';

export const styleStencilVersion=8;
export const styleStencilIds=['editorial','columns','comparison','figure-right','figure-left','process','metrics','chart-insight','chart-right','chart-wide','table-insight','table-right','table-wide','statement'] as const;
export type StyleStencilId=typeof styleStencilIds[number];
const protectedRoles=new Set(['brand','logo','icon','background','background_image','footer','page_number','title','header']);
const intersect=(a:any,b:any)=>{const x=Math.max(a.x,b.x),y=Math.max(a.y,b.y);return {x,y,w:Math.max(0,Math.min(a.x+a.w,b.x+b.w)-x),h:Math.max(0,Math.min(a.y+a.h,b.y+b.h)-y)};};
/** Retained paint includes white ornaments: a flat colour is not permission
 * to write over a native object. Subtract its bounds before placing HTML. */
function clearSurface(base:any,obstacles:any[],minWidth:number,minHeight:number){
  let candidates=[base];
  for(const obstacle of obstacles){
    candidates=candidates.flatMap(rect=>{
      const hit=intersect(rect,obstacle);if(hit.w<1||hit.h<1)return [rect];
      return [{x:rect.x,y:rect.y,w:hit.x-rect.x-4,h:rect.h},
        {x:hit.x+hit.w+4,y:rect.y,w:rect.x+rect.w-hit.x-hit.w-4,h:rect.h},
        {x:rect.x,y:rect.y,w:rect.w,h:hit.y-rect.y-4},
        {x:rect.x,y:hit.y+hit.h+4,w:rect.w,h:rect.y+rect.h-hit.y-hit.h-4}]
        .filter(b=>b.w>=minWidth&&b.h>=minHeight);
    }).sort((a,b)=>b.w*b.h-a.w*a.h).slice(0,16);
    if(!candidates.length)return base;
  }
  return candidates[0]??base;
}

/** Clear sample data/photographs; preserve the useful native body design.
 * Text is emptied separately by the DOM compiler. Explicit local model edits
 * remain fenced to owned shapes and cannot delete protected branding. */
export function prepareStyleStencils(analysis:any){
  const {height:h}=analysis;
  for(const layout of analysis.layouts??[]){
    layout.htmlGenerationMode='style-stencils';
    if(layout.htmlRole!=='content'){
      // Template authoring placeholders are not real contact/brand content.
      const samples=(layout.slots??[]).filter((s:any)=>/^(?:QR[- ]?code|имя\s+(?:спикера|фамилия)|speaker name|name surname)(?:[\s,\n]|$)/iu.test(String(s.text??'').trim()));
      const ids=new Set<number>(samples.map((s:any)=>s.shapeId));
      for(const sample of samples)for(const o of layout.sourceObjects??[]){const b=o.box;if(!b||o.hasText||!o.fill?.color||['brand','logo','background','background_image'].includes(o.role)||layout.htmlPreserveShapeIds?.includes(o.shapeId))continue;
        if(b.w*b.h<analysis.width*h*.025&&Math.abs(b.y-sample.y)<8&&b.x+b.w<=sample.x&&sample.x-b.x-b.w<30)ids.add(o.shapeId);}
      layout.htmlRemoveShapeIds=[...new Set([...(layout.htmlRemoveShapeIds??[]),...ids])];continue;
    }
    const objects:any[]=layout.sourceObjects??[],byId=new Map(objects.map(object=>[object.shapeId,object]));
    const protectedIds=new Set<number>([layout.htmlTitleShapeId,...(layout.htmlPreserveShapeIds??[]),...(layout.htmlChromeShapeIds??[]),
      ...(layout.reservedRegions??[]).filter((region:any)=>['brand','logo','icon','footer','page_number'].includes(region.role)).map((region:any)=>region.shapeId),
      ...objects.filter(object=>protectedRoles.has(object.role)&&(!['title','header'].includes(object.role)||object.box?.y<h*.2)).map(object=>object.shapeId)].filter(Number.isInteger));
    // Protect every ancestor of a logo/wordmark, not merely its child ID.
    for(const id of [...protectedIds]){let object=byId.get(id),seen=new Set<number>();while(object?.parentShapeId&&!seen.has(object.parentShapeId)){seen.add(object.parentShapeId);protectedIds.add(object.parentShapeId);object=byId.get(object.parentShapeId);}}
    const charts=new Set(layout.htmlChartStyle?.sourceShapeIds??[]);
    // Undo the obsolete blanket cleanup in cached V3 imports. Emptying words
    // never grants permission to delete the shape that carries their design.
    const oldStencilRemoval=new Set(layout.htmlStyleRemoveShapeIds??[]);
    layout.htmlRemoveShapeIds=(layout.htmlRemoveShapeIds??[]).filter((id:number)=>!oldStencilRemoval.has(id)&&!protectedIds.has(id));
    layout.htmlCompositionPolicy='source-first';
    const removed=objects.filter(object=>{
      const b=object.box;if(!b||protectedIds.has(object.shapeId)||object.hidden)return false;
      if(['chart','table'].includes(object.kind))return true;
      if(charts.has(object.shapeId))return true;
      // A source chart may be a single bitmap that the native photo policy
      // deliberately excludes from imageSlots. Its data is still sample
      // content: never leave it behind the new bound plot.
      if(layout.htmlConcept?.kind==='chart'&&object.kind==='picture'&&!['icon','logo','brand','background','background_image','decoration'].includes(object.role)&&
        b.y>=h*.13&&b.w*b.h>=analysis.width*h*.06)return true;
      // Only replace sample photographs. Fills, rounded panels, connectors,
      // badges, group topology and their empty text hosts remain editable.
      return object.kind==='picture'&&(layout.imageSlots??[]).some((slot:any)=>slot.shapeId===object.shapeId&&!slot.protected&&!slot.requiresOpaque);
    }).map(object=>object.shapeId);
    layout.htmlStyleRemoveShapeIds=removed;
    layout.htmlRemoveShapeIds=[...new Set([...(layout.htmlRemoveShapeIds??[]),...(layout.htmlSampleDataShapeIds??[]),...removed])];
    if(charts.size){layout.imageSlots=(layout.imageSlots??[]).filter((slot:any)=>!charts.has(slot.shapeId));layout.imageSlotCount=layout.imageSlots.length;}
    layout.htmlStencilVersion=styleStencilVersion;
  }
}

export function sourceStyleSystem(analysis:any,layout:any,source:any){
  const w=analysis.width,h=analysis.height,px=(n:number)=>Math.round(n*4/3*10)/10;
  const furniture=new Set(['brand','logo','footer','page_number','decoration']);
  const reasonable=(slot:any)=>slot&&!furniture.has(slot.role)&&slot.y>=0&&slot.y<h*.42&&slot.y+slot.h<h*.6&&slot.w>w*.22;
  const candidates=(layout.slots??[]).filter(reasonable).filter((slot:any)=>!layout.htmlPreserveShapeIds?.includes(slot.shapeId));
  const heading=(layout.slots??[]).find((slot:any)=>slot.shapeId===source.title?.shapeId);
  const local=reasonable(heading)?heading:candidates.sort((a:any,b:any)=>(['title','header'].includes(b.role)?100:0)+(b.size??0)-(['title','header'].includes(a.role)?100:0)-(a.size??0)||a.y-b.y)[0];
  const title=reasonable(source.title?.box)&&source.title?.box.y<h*.42?{...source.title.box}:local?{x:local.x,y:local.y,w:local.w,h:local.h}:{x:w*.055,y:h*.13,w:w*.86,h:h*.10};
  title.h=Math.max(h*.075,Math.min(h*.14,title.h));title.w=Math.max(title.w,w*.72);title.w=Math.min(title.w,w*.945-title.x);
  const brands=[...(layout.reservedRegions??[]),...(layout.sourceObjects??[])].filter((item:any)=>['brand','logo'].includes(item.role)).map((item:any)=>item.box).filter(Boolean);
  for(const brand of brands)if(brand.x>title.x+w*.3&&intersect(brand,title).h>1)title.w=Math.min(title.w,brand.x-title.x-w*.025);
  let bodyTop=Math.min(h*.58,Math.max(h*.2,title.y+title.h+h*.035));
  const base={x:w*.055,y:bodyTop,w:w*.89,h:Math.max(0,h*.91-bodyTop)};
  const surfaces=(source.availableSurfaces?.length?source.availableSurfaces:(layout.htmlDesign?.surfaces??[]).map((rect:any)=>({x:rect.x*w/1000,y:rect.y*h/1000,w:rect.w*w/1000,h:rect.h*h/1000})));
  let free=surfaces.map((surface:any)=>intersect(surface,base)).filter((rect:any)=>rect.w>w*.25&&rect.h>h*.16);
  let body=free.sort((a:any,b:any)=>b.w*b.h-a.w*a.h)[0]??base;
  const clearedRasterChart=(layout.htmlChartStyle?.sourceShapeIds??[]).some((id:number)=>layout.htmlRemoveShapeIds?.includes(id));
  if(clearedRasterChart||['chart','table'].includes(layout.htmlConcept?.kind)&&(layout.sourceObjects??[]).some((o:any)=>['chart','table'].includes(o.kind)&&layout.htmlRemoveShapeIds?.includes(o.shapeId)))body=base;
  if(body.h<h*.30&&surfaces.length){
    // A tall empty top margin must not force an entire explanation into a
    // shallow strip. Move the heading within the same flat source surface.
    const surface=surfaces.filter((b:any)=>b.w>w*.6&&b.h>h*.35).sort((a:any,b:any)=>b.w*b.h-a.w*a.h)[0];
    if(surface&&surface.y<title.y){title.y=Math.max(surface.y+h*.025,h*.065);bodyTop=title.y+title.h+h*.035;
      const expanded=intersect(surface,{...base,y:bodyTop,h:h*.91-bodyTop});if(expanded.h>body.h)body=expanded;}
  }
  const obstacles=(source.artwork??[]).filter((item:any)=>item.box&&item.shapeId!==source.title?.shapeId&&item.box.w*item.box.h<areaOf(w,h)*.7).map((item:any)=>item.box);
  body=clearSurface(body,obstacles,w*.26,h*.18);
  const safeTitle=clearSurface(title,obstacles,w*.26,h*.05);Object.assign(title,safeTitle);
  // The first run may be a tiny red sample annotation. Learn ordinary body
  // ink from the dominant text area, preserving that template's typography.
  const bodySlot=(layout.slots??[]).filter((slot:any)=>!['title','header','brand','logo','footer','page_number','decoration'].includes(slot.role)&&slot.color)
    .sort((a:any,b:any)=>(b.w*b.h)*(b.size??16)-(a.w*a.h)*(a.size??16))[0];
  const palette=analysis.styleProfile?.colors??[];
  const rect=(b:any)=>Object.fromEntries(['x','y','w','h'].map(key=>[key,px(b[key])]));
  return {version:styleStencilVersion,mode:'style-stencils',canvas:{width:px(w),height:px(h)},title:rect(title),body:rect(body),
    font:bodySlot?.font??heading?.font??analysis.styleProfile?.fonts?.[0]??'Arial',
    headingFont:local?.font??heading?.font??bodySlot?.font??'Arial',headingSize:px(Math.max(22,Math.min(38,local?.size??heading?.size??30))),
    ink:layout.htmlStyleInk??bodySlot?.color??heading?.color??'#202020',headingInk:layout.htmlStyleHeadingInk??heading?.color??bodySlot?.color??'#202020',
    accent:palette.find((color:string)=>{if(!/^#[a-f0-9]{6}$/i.test(color))return false;const rgb=color.slice(1).match(/../g)!.map(value=>parseInt(value,16));return Math.max(...rgb)-Math.min(...rgb)>=25;})??bodySlot?.color??'#3159B6',
    chartStyle:layout.htmlChartStyle,
    stencils:styleStencilIds,
    preserved:'source shapes, fills, connectors, text hosts, background, logos, header, footer, palette and fonts',
    composition:'fill suitable original body hosts first; locally adapt only defective or incompatible frames'};
}
const areaOf=(w:number,h:number)=>w*h;

/** Tested flow primitives use the uploaded theme and measured content surface.
 * The model selects a stencil and writes the argument; it can refine CSS or
 * provide bespoke inert HTML when a meaningful diagram needs it. */
export function realizeStyleStencil(slide:HtmlSlideCopy,source:any,photoCount=0):HtmlSlideCopy{
  if(source.role!=='content'||!source.styleSystem)return realizeTerminalHtml(slide,source);
  const preserved=realizeSourceComposition(slide,source,photoCount);
  if(preserved)return preserved;
  if(!photoCount&&/data-image\s*=/.test(slide.html??''))slide={...slide,html:'',css:'',stencilId:undefined};
  if(slide.chart){
    const original=[...slide.paragraphs,slide.takeaway].filter(Boolean).join(' ');
    const description=chartExplanation([...slide.paragraphs,slide.takeaway],dataViewExplanation({title:slide.chart.title,chartType:slide.chart.type,categories:slide.chart.categories,series:slide.chart.series,unit:''} as PresentationDataView));
    const marker='Полное пояснение графика:';
    const notes=description===original||slide.notes.includes(marker)?slide.notes:[slide.notes,marker,original].filter(Boolean).join('\n');
    slide={...slide,paragraphs:[description],takeaway:'',notes};
  }
  const style=source.styleSystem,title=style.title;
  // Chart source captions can be long. Inherited footer logos are sometimes
  // baked into a master and absent from slide-level object IDs.
  const body=slide.chart?{...style.body,h:Math.min(style.body.h,style.canvas.height*.86-style.body.y)}:style.body;
  let chosen=styleStencilIds.includes(slide.stencilId as StyleStencilId)?slide.stencilId as StyleStencilId:
    slide.chart?'chart-insight':slide.table?'table-insight':photoCount?'figure-right':slide.metrics.length?'metrics':slide.steps.length?'process':slide.cards.length>1?'columns':slide.paragraphs.length===1&&slide.paragraphs[0]!.length<180?'statement':'editorial';
  const concept=source.concept;
  if(slide.chart)chosen='chart-wide';
  else if(slide.table&&(!slide.stencilId||!['table-insight','table-right','table-wide'].includes(chosen)))chosen=concept?.visualSide==='right'?'table-right':slide.table.headers.length>4?'table-wide':'table-insight';
  else if(photoCount&&(!slide.stencilId||!['figure-left','figure-right'].includes(chosen)))chosen=concept?.visualSide==='left'?'figure-left':'figure-right';
  if(!photoCount&&['figure-left','figure-right'].includes(chosen))chosen=slide.cards.length>1?'columns':'editorial';
  if(chosen==='statement'&&(slide.paragraphs.length!==1||slide.paragraphs[0]!.length>220))chosen='editorial';
  const p=slide.paragraphs.map((_,i)=>`<p data-text="paragraphs.${i}"></p>`).join('');
  const pairs=(field:'cards'|'steps')=>slide[field].map((_,i)=>`<article><h2 data-text="${field}.${i}.title"></h2><p data-text="${field}.${i}.body"></p></article>`).join('');
  const metrics=slide.metrics.map((_,i)=>`<article><strong class="value" data-text="metrics.${i}.value"></strong><p data-text="metrics.${i}.label"></p></article>`).join('');
  const visuals=[slide.chart?'<div class="data-plot" data-visual="chart"></div>':'',slide.table?'<div class="data-plot" data-visual="table"></div>':''].join('');
  const image=photoCount?`<div class="figures">${Array.from({length:photoCount},(_,index)=>`<img class="figure" data-image="${index}">`).join('')}</div>`:'';
  const prose=p+(slide.cards.length?`<div class="groups">${pairs('cards')}</div>`:'')+(slide.steps.length?`<div class="steps">${pairs('steps')}</div>`:'')+(slide.metrics.length?`<div class="metrics">${metrics}</div>`:'');
  const content=visuals?`<div class="visual">${visuals}</div><aside class="explanation">${prose}</aside>`:image?`<div class="explanation">${prose}</div>${image}`:`<div class="explanation">${prose}</div>`;
  const caption=slide.takeaway?'<footer data-text="takeaway"></footer>':'';
  const html=`<main class="stencil ${chosen}"><h1 data-text="title"></h1><section class="body">${content}${caption}</section></main>`;
  const characters=[...slide.paragraphs,...slide.cards.flatMap(c=>[c.title,c.body]),...slide.steps.flatMap(c=>[c.title,c.body])].join(' ').length;
  const small=Math.max(20,Math.min(30,style.canvas.height*(characters>650?.036:.042)));
  const font=String(style.font).replace(/["'<>\\]/g,''),headingFont=String(style.headingFont).replace(/["'<>\\]/g,'');
  const n=(value:number)=>Math.round(value*10)/10;
  const css=`.stencil{position:relative;width:100%;height:100%;font-family:"${font}";color:${style.ink};font-size:${small}px;line-height:1.24}.stencil *{box-sizing:border-box;min-width:0}.stencil h1{position:absolute;left:${title.x}px;top:${title.y}px;width:${title.w}px;height:${title.h}px;margin:0;font-family:"${headingFont}";font-size:${style.headingSize}px;line-height:1.1;color:${style.headingInk};font-weight:700}.stencil .body{position:absolute;left:${body.x}px;top:${body.y}px;width:${body.w}px;height:${body.h}px;display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr) auto;column-gap:${n(style.canvas.width*.028)}px;row-gap:16px}.stencil p,.stencil h2{margin:0}.stencil h2{font-size:1.12em;line-height:1.16;font-weight:700;margin-bottom:10px}.stencil .explanation{display:flex;flex-direction:column;justify-content:center;gap:18px;min-height:0}.stencil .groups,.stencil .steps,.stencil .metrics{display:grid;grid-template-columns:repeat(${Math.max(1,Math.min(3,slide.cards.length||slide.steps.length||slide.metrics.length))},minmax(0,1fr));gap:24px;align-items:start}.stencil .value{font-size:2.5em;line-height:1.06;font-weight:700;color:${style.accent};display:block;margin-bottom:12px}.stencil .visual,.stencil .data-plot{width:100%;height:100%;min-height:0}.stencil .figures{display:grid;grid-template-rows:repeat(${Math.max(1,photoCount)},minmax(0,1fr));gap:16px;min-height:0}.stencil .figure{width:100%;height:100%;object-fit:contain;min-height:0}.stencil footer{grid-column:1/-1;font-size:${Math.max(13,small*.65)}px;line-height:1.25;margin:0;align-self:end}.stencil.chart-insight .body,.stencil.table-insight .body{grid-template-columns:minmax(0,3fr) minmax(0,1.15fr)}.stencil.chart-insight .explanation,.stencil.table-insight .explanation{font-size:${small*.9}px}.stencil.figure-right .body,.stencil.figure-left .body{grid-template-columns:minmax(0,1fr) minmax(0,1.15fr)}.stencil.figure-left .figures{grid-column:1;grid-row:1}.stencil.figure-left .explanation{grid-column:2;grid-row:1}.stencil.statement .explanation>p{font-size:1.55em;line-height:1.22;max-width:95%}.stencil.editorial .explanation{max-width:94%}.stencil.process .steps{counter-reset:step}.stencil.process .steps article{display:flex;flex-direction:column;gap:8px}.stencil.metrics .metrics{align-items:center}.stencil .authored-table{width:100%;font-size:${Math.max(14,small*.8)}px;border-collapse:collapse}.stencil .authored-cell{padding:10px 9px;border-bottom:1px solid currentColor}`;
  // Meaningful model-authored diagrams remain possible; an empty HTML field
  // explicitly opts into a reusable stencil and avoids repeated code tokens.
  const variantsCss=`.stencil.chart-right .body,.stencil.table-right .body{grid-template-columns:minmax(0,1.15fr) minmax(0,3fr)}.stencil.chart-right .visual,.stencil.table-right .visual{grid-column:2;grid-row:1}.stencil.chart-right .explanation,.stencil.table-right .explanation{grid-column:1;grid-row:1;font-size:${small*.9}px}.stencil.chart-wide .body,.stencil.table-wide .body{grid-template-rows:minmax(0,1fr) auto auto}.stencil.chart-wide .explanation,.stencil.table-wide .explanation{display:flex;flex-direction:row;gap:24px;font-size:${small*.9}px}.stencil.chart-wide .explanation>p,.stencil.table-wide .explanation>p{flex:1}.stencil.chart-wide .body{grid-template-columns:minmax(0,1fr)}.stencil.chart-wide .visual{grid-column:1;grid-row:1}.stencil.chart-wide .explanation{grid-column:1;grid-row:2;display:block;font-size:${small*.94}px;line-height:1.24}.stencil.chart-wide .explanation p{max-width:100%}`;
  const managed=!!slide.chart||!slide.html?.trim()||/class=["'][^"']*\bstencil\b/.test(slide.html);
  // Recompute managed grids after copy/repair changes. Stale CSS and arbitrary
  // top/left patches cannot override the measured header and body boundaries.
  // Genuine bespoke diagrams with their own markup remain model-authored.
  return {...slide,stencilId:chosen,...(managed?{html,css:[css,variantsCss].join('\n')}:{})};
}

export function bindStyleData(copy:HtmlCopy,p:Project,references:any[],photoSlots:Record<number,number>={},warnings:HtmlWarning[]=[]){
  const views=dataViews(p.brief?.dataSources),known=new Map(views.map(view=>[view.id,view]));
  return {...copy,slides:copy.slides.map((slide,index)=>{
    slide={...slide,title:correctEndpointDuration(slide.title,views)};
    const id=p.plan?.slides[index]?.dataViewId,view=id?known.get(id):undefined;
    let result=slide;
    const allocated=p.plan?.slides.some(item=>item.dataViewId);
    if(!view&&slide.chart&&views.length&&allocated){
      result={...slide,title:p.plan!.slides[index]!.title,chart:null,stencilId:undefined,html:'',css:'',
        notes:[slide.notes,`Дополнительный график сохранён как данные в заметках: ${JSON.stringify(slide.chart)}`].filter(Boolean).join('\n')};
      warnings.push({slide:index+1,reason:'html_data_scope',message:'Повторная диаграмма убрана: данные уже представлены на выбранных слайдах.'});
    }else if(!view&&slide.chart&&views.length){
      const proof=verifyDataChart(slide.chart,views);
      if(proof===null){
        const available=views.filter(view=>view.kind==='chart').slice(0,6);
        if(available.length){result={...slide,title:'Что подтверждают исходные данные',paragraphs:['В таблице приведены первое и последнее наблюдения каждого показателя. Для дополнительного расчётного показателя требуется уточнить исходные данные и метод расчёта.'],
          chart:null,table:{headers:['Показатель','Первое наблюдение','Последнее наблюдение'],rows:available.map(view=>[view.title,
            `${view.categories[0]}: ${view.series[0]!.values[0]}`,`${view.categories.at(-1)}: ${view.series[0]!.values.at(-1)}`])},
          takeaway:[...new Set(available.map(view=>view.caption))].join(' '),stencilId:'table-insight',html:'',css:'',cards:[],steps:[],metrics:[]};
          warnings.push({slide:index+1,reason:'html_data_chart_reconciled',message:'Неподтверждённый график заменён сводкой исходных данных. Проверьте метод расчёта дополнительного показателя.'});}
      }else if(proof){result={...slide,takeaway:technicalDataCopy(slide.takeaway)?'':slide.takeaway,notes:slide.notes.includes(proof)?slide.notes:[slide.notes,proof].filter(Boolean).join('\n')};}
    }
    if(view){
      const proposed=p.plan?.slides[index]?.visualPlan?.chartType;
      const chart=view.kind==='chart'?{type:proposed&&dataChartChoices(view).includes(proposed)?proposed:view.chartType!,title:(view.title+(view.unit&&!view.title.includes(view.unit)?` · ${view.unit}`:'')).slice(0,200),categories:view.categories,series:view.series}:null;
      const metric=view.kind==='metrics'&&view.series[0]?{value:String(view.series[0].values[0])+(view.unit?' '+view.unit:''),label:view.categories[0]??view.title}:undefined;
      const repeatedRows=view.table?.rows.filter(row=>row.every(value=>slide.paragraphs.join(' ').includes(String(value)))).length??0;
      const fallback=!slide.paragraphs.length||repeatedRows>=3||slide.paragraphs.some(paragraph=>/^(?:Показать|Раскрыть|Рассмотреть|Визуализация:)/i.test(paragraph));
      const originalDescription=chartExplanation(fallback?[]:slide.paragraphs,dataViewExplanation(view));
      const description=dataFoldComparisonMatches(originalDescription,view.series)?originalDescription:dataViewExplanation(view);
      const title=dataFoldComparisonMatches(slide.title,view.series)?slide.title:view.title;
      const marker=`Данные и методика (${view.id}):`;
      const notes=slide.notes.includes(marker)?slide.notes:[slide.notes,marker,view.caption,(view as any).sourceNotes,
        'Полное авторское пояснение: '+[...slide.paragraphs,slide.takeaway].filter(Boolean).join('\n')].filter(Boolean).join('\n');
      result={...slide,title,paragraphs:[description],chart,table:view.kind==='table'?view.table??null:null,metrics:metric?[metric]:[],takeaway:'',notes,
        // Source numbers are bound once. The author writes meaning in one
        // short explanation, not a second transcription of the spreadsheet.
        cards:[],steps:[],stencilId:view.kind==='chart'&&['chart-insight','chart-right','chart-wide'].includes(slide.stencilId??'')||view.kind==='table'&&['table-insight','table-right','table-wide'].includes(slide.stencilId??'')?slide.stencilId:view.kind==='chart'||view.kind==='table'?undefined:'metrics'};
      if(slide.html?.trim()&&(!new RegExp(`data-visual=["']${view.kind}["']`).test(slide.html)&&view.kind!=='metrics'||!slide.html.includes('takeaway')))result={...result,html:'',css:''};
    }
    return realizeStyleStencil(result,references[index],photoSlots[index]??0);
  })};
}

/** A model may juxtapose verified series, subtract compatible units, or
 * explicitly propose a ratio. Every paired observation is verified locally;
 * rounding is disclosed instead of silently treating it as measured data. */
export function verifyDataChart(chart:NonNullable<HtmlSlideCopy['chart']>,views:PresentationDataView[]):string|null{
  const compatible=views.filter(view=>view.kind==='chart'&&view.categories.length===chart.categories.length&&view.categories.every((value,index)=>value===chart.categories[index])).slice(0,40);
  const units=new Set<string>(),calculations:string[]=[];
  for(const series of chart.series){
    const direct=compatible.find(view=>view.series.some(source=>source.values.every((value,index)=>value===series.values[index])));
    if(direct){units.add(direct.unit);continue;}
    let calculation:string|undefined;
    for(const left of compatible)for(const right of compatible)if(left.id!==right.id&&left.series[0]&&right.series[0]){
      if(left.unit===right.unit&&left.series[0].values.every((value,index)=>Math.abs(value-right.series[0]!.values[index]-series.values[index]!)<1e-9)){
        calculation=`Рассчитано по исходным данным: ${left.title} − ${right.title}.`;units.add(left.unit);break;
      }
      if(chart.categories.length<2||!/(?:÷|\/|делени|отношени|средн.*чек|на сотрудник|на одного|\bper\b|\baverage\b|\bratio\b)/i.test(chart.title+' '+series.name)||right.series[0].values.some(value=>value===0))continue;
      const ratios=left.series[0].values.map((value,index)=>value/right.series[0]!.values[index]!);
      const digits=Array.from({length:7},(_,i)=>i).find(digits=>ratios.every((value,index)=>Number.isFinite(value)&&Math.abs(Number(value.toFixed(digits))-series.values[index]!)<1e-9));
      if(digits!==undefined){calculation=`Рассчитано по исходным данным: ${left.title} ÷ ${right.title}; округление до ${digits} знаков после запятой.`;units.add(left.unit+' / '+right.unit);break;}
    }
    if(!calculation)return null;calculations.push(calculation);
  }
  return units.size>1?null:[...new Set(calculations)].join(' ');
}

export function dataViewExplanation(view:PresentationDataView){
  const format=(value:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value),u=view.unit?' '+view.unit:'';
  if(view.table){
    const {headers,rows}=view.table;
    // A caption explains the comparison; repeating the entire table as a
    // second paragraph caused an unreadable narrow column beside it.
    const column=headers.length-1;
    const numeric=rows.map(row=>({label:String(row[0]),value:Number(String(row[column]??'').replace(/[\s\u00a0\u202f]/g,'').replace(',','.'))}))
      .filter(row=>Number.isFinite(row.value)&&row.label);
    if(numeric.length>=2){
      const max=numeric.reduce((a,b)=>a.value>b.value?a:b),min=numeric.reduce((a,b)=>a.value<b.value?a:b);
      if(/изменени|прирост/iu.test(headers[column]??''))return `Изменение различается по периодам. Наибольшее — ${max.label}: ${format(max.value)}${u}. Это изменение за весь указанный интервал, а не за один год.`;
      if(max.value!==min.value)return `Сравнение по показателю «${headers[column]}»: наибольшее значение — ${max.label} (${format(max.value)}${u}), наименьшее — ${min.label} (${format(min.value)}${u}).`;
      return `По показателю «${headers[column]}» у представленных категорий одинаковое значение: ${format(max.value)}${u}.`;
    }
    return `${view.title}. Таблица сопоставляет ${headers.join(' и ').toLocaleLowerCase('ru-RU')}; категории представлены в строках.`;
  }
  if(!view.series.length)return `${view.title}: ${view.observations} записей из исходной таблицы.`;
  return view.series.map(series=>{
    const values=series.values,max=Math.max(...values),min=Math.min(...values);
    if(values.length===1)return `${series.name}: ${format(values[0]!)}${u}.`;
    if(view.chartType==='line')return `${series.name}: ${view.categories[0]} — ${format(values[0]!)}${u}; ${view.categories.at(-1)} — ${format(values.at(-1)!)}${u}. Изменение между концами периода: ${format(values.at(-1)!-values[0]!)}${u}.`;
    return min===max?`${series.name}: во всех показанных наблюдениях ${format(max)}${u}.`:
      `${series.name}: максимум — ${view.categories[values.indexOf(max)]}, ${format(max)}${u}; минимум — ${view.categories[values.indexOf(min)]}, ${format(min)}${u}.`;
  }).join(' ');
}
export function stencilDataPreview(view:PresentationDataView & {sourceNotes?:string}){return {id:view.id,title:view.title,kind:view.kind,chartType:view.chartType,chartChoices:dataChartChoices(view),unit:view.unit,definition:view.definition,provenanceForNotes:{caption:view.caption,sourceNotes:view.sourceNotes,aggregation:view.aggregation},observedSummary:dataViewExplanation(view),values:'bound by the server; do not transcribe numeric series'};}
