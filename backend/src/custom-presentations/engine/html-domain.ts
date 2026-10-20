import {styleAuthorPrompt} from './style-prompts.js';
import {sourceFidelityPrompt,slideFamilyPrompt} from './html-design-policies.js';
import {z} from 'zod';
import type {Outline, Project} from './domain.js';
import {recoveryPoints,recoveryHtml} from './html-recovery.js';
import {normalizeHtmlNumbers} from './html-code-normalization.js';
import {dataChartKinds} from './data-contract.js';

export const htmlEngineVersion=41;
// Import receipts are versioned independently of the copy/scene format.
export const htmlTemplateVersion=30;
export const chartPresentationSchema=z.object({mode:z.enum(['auto','native','image']),treatment:z.enum(['plain','gradient','soft-area']),reason:z.string().trim().max(240)}).strict();
export const htmlCardSchema=z.object({title:z.string().trim().max(160),body:z.string().trim().max(600)}).strict();
export const sourceShapeEditSchema=z.object({shapeId:z.number().int().positive(),action:z.enum(['remove','replace'])}).strict();
const text=z.string().trim().max(1800);
// Some providers wrap a paragraph in {text}; this is lossless content, not a
// reason to discard that slide. Other object shapes still fail validation.
const paragraph=z.preprocess(value=>value&&typeof value==='object'&&!Array.isArray(value)&&
  Object.keys(value).length===1&&typeof (value as {text?:unknown}).text==='string'?(value as {text:string}).text:value,text);
const cell=z.preprocess(value=>typeof value==='number'&&Number.isFinite(value)?String(value):value,text);
const optionalCopy=z.preprocess(value=>value??'',text);
// A registry schema can legitimately show column names before records exist.
// Do not replace a complete authored deck because that one table has no rows.
// Source calendars/Gantt grids legitimately need one label plus many weeks.
const table=z.object({headers:z.array(cell).min(1).max(24),rows:z.array(z.array(cell).min(1).max(24)).max(24)}).strict();
const chart=z.object({type:z.enum(dataChartKinds),title:text,categories:z.array(cell).min(2).max(36),
  series:z.array(z.object({name:text,values:z.array(z.number().finite()).min(2).max(36)}).strict()).min(1).max(6)}).strict();
export const htmlCopySchema=z.object({thesis:text,css:z.string().max(24000).optional(),slides:z.array(z.object({
  index:z.number().int().min(0).max(39),html:z.string().max(24000).optional(),css:z.string().max(24000).optional(),title:text,paragraphs:z.array(paragraph).max(8),
  stencilId:z.string().max(60).optional(),
  sourceBindings:z.array(z.object({shapeId:z.number().int().positive(),paths:z.array(z.string().regex(/^(?:title|takeaway|paragraphs\.\d+|(?:cards|steps)\.\d+\.(?:title|body)|metrics\.\d+\.(?:value|label))$/)).max(20)}).strict()).max(32).optional(),
  designDecision:z.object({mode:z.enum(['preserve','adapt','repair']),family:z.enum(['cover','text','photo','table','chart','radial','timeline','metrics','closing']),reasons:z.array(z.string().max(180)).max(6).default([])}).optional().catch(undefined),
  table:table.nullable(),chart:chart.nullable(),
  chartPresentation:chartPresentationSchema.nullable().optional(),
  steps:z.array(z.object({title:text,body:text}).strict()).max(6),
  cards:z.array(htmlCardSchema).max(8).default([]),
  omitSourceIconIds:z.array(z.number().int().positive()).max(16).default([]),
  sourceShapeEdits:z.array(sourceShapeEditSchema).max(16).default([]),
  metrics:z.array(z.object({value:z.preprocess(value=>typeof value==='number'&&Number.isFinite(value)?String(value):value,z.string().max(80)),label:z.string().max(280)}).strict()).max(8).default([]),
  takeaway:optionalCopy,notes:z.preprocess(value=>value??'',z.string().max(64000)),speech:z.preprocess(value=>value??'',z.string().max(4500)),
}).strict()).min(1).max(40)}).strict();
export type HtmlCopy=z.infer<typeof htmlCopySchema>;
export type HtmlSlideCopy=HtmlCopy['slides'][number];
export interface HtmlWarning {slide?:number;reason:string;message:string;suggestedSourceLayoutId?:string}

export const narrativePolicy=`Построй единое последовательное объяснение темы. Определи центральный вопрос доклада и ответ, к которому ведут материалы. Начало вводит предмет и проблему, основная часть объясняет причины, подход и подтверждения, завершение отвечает на исходный вопрос и формулирует результат или следующий шаг. Для учебного, научного и обзорного доклада адаптируй эту логику к жанру: не придумывай бизнес-проблему или состоявшееся внедрение. Каждый слайд раскрывает один шаг рассуждения и использует термины в одном значении. Заголовок и содержание следующего слайда должны продолжать предыдущую мысль, без случайного переключения предмета. Не повторяй вводную на каждом слайде. Завершение обязательно содержит содержательный итог. Если последний макет — прощание, сохрани его назначение: итог раскрой на предыдущем содержательном слайде, а в прощании оставь короткое завершение и следующий шаг. Без отдельного прощального макета итог располагается на последнем слайде. Следуй утверждённому порядку и количеству слайдов. Сохраняй точные данные, единицы, периоды, оговорки и различие между фактом, гипотезой и рекомендацией.`;

export const htmlCopyPrompt=narrativePolicy+'\n'+styleAuthorPrompt+'\n'+sourceFidelityPrompt+'\n'+slideFamilyPrompt;

/** Validate data, never reject a usable whole deck for a local chart/cell issue. */
export function normalizeHtmlCopy(raw:unknown,plan:Outline):{copy:HtmlCopy;warnings:HtmlWarning[]} {
  const value=htmlCopySchema.parse(raw),warnings:HtmlWarning[]=[];
  const byIndex=new Map(value.slides.map(slide=>[slide.index,slide]));
  if(byIndex.size!==value.slides.length||value.slides.length!==plan.slides.length||plan.slides.some((_,i)=>!byIndex.has(i)))
    throw new Error('html_copy_slide_identity');
  const slides=plan.slides.map((_,index)=>{
    const slide=structuredClone(byIndex.get(index)!);
    if(slide.html)slide.html=normalizeHtmlNumbers(slide.html);
    if(slide.metrics.some(metric=>metric.value.trim()===slide.title.trim()))warnings.push({slide:index+1,reason:'html_duplicate_metric',message:'Заголовок дублирует крупное значение метрики. Раскройте в заголовке смысл показателя и оставьте число в метрике.'});
    if(slide.table&&(slide.table.headers.length<2||slide.table.rows.some(row=>row.length!==slide.table!.headers.length))){
      const rows=slide.table.rows.map(row=>row.map((cell,i)=>`${slide.table!.headers[i]??''}: ${cell}`).join('; '));
      slide.paragraphs.push(...rows);slide.table=null;
      warnings.push({slide:index+1,reason:'html_table_as_text',message:'Несогласованные строки таблицы сохранены как редактируемый текст.'});
    }
    if(slide.chart&&(slide.chart.series.some(series=>series.values.length!==slide.chart!.categories.length)||
      slide.chart.type==='xy'&&slide.chart.categories.some(x=>!Number.isFinite(Number(x))))){
      slide.paragraphs.push(slide.chart.series.map(series=>series.name+': '+series.values.join(', ')).join('\n'));slide.chart=null;
      warnings.push({slide:index+1,reason:'html_chart_as_text',message:'Данные диаграммы сохранены текстом: проверьте соответствие подписей и значений.'});
    }
    if(slide.chart&&['pie','donut'].includes(slide.chart.type)&&(slide.chart.series.length!==1||slide.chart.categories.length>6||
      slide.chart.series[0]!.values.some(value=>value<0)||!slide.chart.series[0]!.values.some(value=>value>0))){
      slide.chart.type='bar';
      warnings.push({slide:index+1,reason:'html_chart_kind_repaired',message:'Для этих значений выбрана столбчатая диаграмма; данные сохранены без изменений.'});
    }
    return slide;
  });
  return {copy:{...value,slides},warnings};
}

/** Provider outages preserve approved content; no fabricated measurements. */
export function htmlFarewellLayout(layout:any,height=540):boolean{
  return !!layout?.slots?.some((slot:any)=>(layout.htmlRole==='closing'||['title','header'].includes(slot.role)||Number(slot.size)>=height*.06)&&
    /^(?:спасибо|благодар|thank\s*you|thanks\b|до встречи|questions\b|контакты)/iu.test(String(slot.text??'').trim()));
}
export function approvedHtmlCopy(p:Project,locale:'ru'|'en'='ru'):HtmlCopy {
  return {thesis:p.brief?.topic??p.name,slides:p.plan!.slides.map((slide,index)=>{
    const layout=p.analysis?.layouts?.find((layout:any)=>layout.id===slide.sourceLayoutId);
    return recoveryHtml({index,title:htmlFarewellLayout(layout,p.analysis?.height)?(locale==='en'?'Thank you':'Спасибо'):slide.title,
      paragraphs:recoveryPoints(slide.brief),table:null,chart:null,steps:[],cards:[],omitSourceIconIds:[],sourceShapeEdits:[],metrics:[],takeaway:'',notes:'',speech:''},p.analysis,layout);
  })};
}

/** Only small sample pictograms can be removed by a visual repair. */
export function removableHtmlIcons(layout:any,width:number,height:number):number[]{
  if(layout?.htmlRole!=='content')return [];
  const protectedIds=new Set([...(layout.sourceObjects??[]).filter((o:any)=>o.hasText||['chart','table'].includes(o.kind)),...(layout.reservedRegions??[]).filter((r:any)=>['brand','logo','chart','table'].includes(r.role))].map((r:any)=>r.shapeId));
  return [...new Set<number>((layout.reservedRegions??[]).filter((r:any)=>r.role==='icon'&&Number.isInteger(r.shapeId)&&
    r.box?.w>0&&r.box?.h>0&&r.box.w<=width*.2&&r.box.h<=height*.2&&!protectedIds.has(r.shapeId)).map((r:any)=>r.shapeId))];
}

export const currentHtmlTemplate=(analysis:any)=>analysis?.htmlTemplate?.version===htmlTemplateVersion&&
  !(analysis.htmlRoleIncomplete&&Date.now()>=analysis.htmlRoleRetryAfter)&&
  analysis.htmlTemplate.sourceSha256===analysis.sha256&&/^[a-f0-9]{64}$/.test(analysis.htmlTemplate.digest??'')&&
  Array.isArray(analysis.htmlTemplate.layoutIds)&&analysis.htmlTemplate.layoutIds.length>0&&
  analysis.htmlTemplate.layoutIds.every((id:string)=>analysis.layouts?.some((layout:any)=>layout.id===id));
