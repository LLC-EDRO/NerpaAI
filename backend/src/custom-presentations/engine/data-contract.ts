import {z} from 'zod';

export const dataChartKinds=['bar','bar-horizontal','line','pie','donut','xy'] as const;
export const dataViewSchema=z.object({
  id:z.string().min(1).max(100),title:z.string().max(200),kind:z.enum(['chart','metrics','table']),
  chartType:z.enum(dataChartKinds).optional(),unit:z.string().max(80),categoryLabel:z.string().max(120),
  categories:z.array(z.string().max(180)).max(36),
  series:z.array(z.object({name:z.string().max(160),values:z.array(z.number().finite()).max(36)}).strict()).max(6),
  table:z.object({headers:z.array(z.string().max(160)).max(8),rows:z.array(z.array(z.string().max(240)).max(8)).max(12)}).optional(),
  caption:z.string().max(1200),observations:z.number().int().nonnegative(),missing:z.number().int().nonnegative(),
  sourceRows:z.array(z.number().int().nonnegative()).max(36),
  purpose:z.enum(['evidence','context']).optional(),
  definition:z.string().max(600).optional(),
  aggregation:z.object({method:z.literal('mean'),groupBy:z.string().max(160),sampleSizes:z.array(z.number().int().positive()).max(36)}).strict().optional(),
}).strict().superRefine((view,ctx)=>{
  if(view.kind==='chart'&&(!view.chartType||view.categories.length<2||!view.series.length||view.series.some(series=>series.values.length!==view.categories.length)))ctx.addIssue({code:'custom',message:'Inconsistent data chart'});
});
export const dataSourceSchema=z.object({
  version:z.literal(1),analysisVersion:z.number().int().positive().optional(),id:z.string().uuid(),fileName:z.string().min(1).max(255),sha256:z.string().regex(/^[a-f0-9]{64}$/),
  datasets:z.array(z.object({id:z.string().max(100),name:z.string().max(180),rowCount:z.number().int().nonnegative(),
    columns:z.array(z.object({name:z.string().max(160),type:z.enum(['number','date','text']),unit:z.string().max(80),missing:z.number().int().nonnegative()}).strict()).max(40),
    views:z.array(dataViewSchema).max(12),notes:z.string().max(4000).optional(),
  }).strict()).min(1).max(12),warnings:z.array(z.string().max(600)).max(30),
}).strict();
export type PresentationDataSource=z.infer<typeof dataSourceSchema>;
export type PresentationDataView=z.infer<typeof dataViewSchema>;
/** Change the presentation, never the observations or their interpretation. */
export function dataChartChoices(view:PresentationDataView):typeof dataChartKinds[number][]{
  if(view.kind!=='chart')return [];
  if(view.chartType==='xy')return ['xy'];
  if(view.chartType==='pie'||view.chartType==='donut')return ['pie','donut','bar','bar-horizontal'];
  const time=/год|месяц|дата|период|year|month|date|period/i.test(view.categoryLabel)||view.categories.every(label=>/^\d{4}(?:[-./]\d{1,2})?(?:[-./]\d{1,2})?$/.test(label));
  return time?['line','bar','bar-horizontal']:['bar','bar-horizontal'];
}
export function dataViews(sources:PresentationDataSource[]|undefined){
  const all=(sources??[]).flatMap(source=>source.datasets.flatMap(dataset=>dataset.views.map(view=>({...view,fileName:source.fileName,datasetName:dataset.name,sourceNotes:dataset.notes}))));
  if((sources?.length??0)<2)return all;
  const evidence=all.filter(view=>view.purpose!=='context');
  const unique=new Set(evidence.map(view=>JSON.stringify([view.kind,view.unit,view.categoryLabel,view.categories,view.series,view.table,view.aggregation])));
  // Two formats of the same time series are still ONE set of observations.
  // A complementary interval table reveals the changes behind its trend,
  // without creating another sample or another near-identical chart.
  const base=evidence.find(view=>view.kind==='chart'&&view.series.length===1);
  if(unique.size!==1||!base||base.categories.length<2)return all;
  if(base.chartType!=='line'||!base.categories.every(v=>/^\d{4}$/.test(v))){
    const series=base.series[0]!,minimum=Math.min(...series.values),baseline=base.categories[series.values.indexOf(minimum)]!;
    const format=(value:number)=>String(Number(value.toFixed(10))).replace('.',',');
    const sizes=base.aggregation?.sampleSizes;
    const rows=base.categories.slice(0,8).map((category,i)=>[category,format(series.values[i]!),sizes?String(sizes[i]):format(series.values[i]!-minimum)]);
    all.push({...base,id:`${sources!.at(-1)!.id}:comparison-detail`,kind:'table',chartType:undefined,title:(sizes?'Состав сравнений: ':'Различия между категориями: ')+base.title.slice(0,150),categories:[],series:[],
      table:{headers:[base.categoryLabel||'Категория',`${series.name}${base.unit?`, ${base.unit}`:''}`.slice(0,160),sizes?'Число измерений':`Разница с «${baseline.slice(0,70)}»${base.unit?`, ${base.unit}`:''}`.slice(0,160)],rows},
      caption:(sizes?'Средние и фактические размеры групп. ':'Разницы рассчитаны с категорией минимального значения в тех же единицах. ')+`Это те же наблюдения, не дополнительная выборка. ${base.caption}`.slice(0,900),purpose:'evidence'});
    return all;
  }
  const indices=[0,...Array.from({length:Math.min(5,base.categories.length-1)},(_,i)=>Math.round((i+1)*(base.categories.length-1)/Math.min(5,base.categories.length-1)))];
  const series=base.series[0]!,format=(value:number)=>String(Number(value.toFixed(10))).replace('.',',');
  const rows=indices.slice(1).map((to,i)=>{const from=indices[i]!;return [`${base.categories[from]}–${base.categories[to]}`,format(series.values[to]!-series.values[from]!)];});
  all.push({...base,id:`${sources!.at(-1)!.id}:interval-changes`,kind:'table',chartType:undefined,title:`Изменение по периодам: ${base.title}`.slice(0,200),
    categories:[],series:[],table:{headers:['Период',`Изменение${base.unit?`, ${base.unit}`:''}`],rows},
    caption:`Рассчитано как разность опубликованных значений на концах каждого интервала. Наблюдения те же, что на графике; повторный подсчёт выборки не выполняется. ${base.caption}`.slice(0,1200),sourceRows:indices.map(i=>base.sourceRows[i]??i),purpose:'evidence'});
  return all;
}
/** Stable, bounded facts shared by the planner and the author. No original
 * spreadsheet is sent repeatedly and no model is asked to transcribe numbers. */
export function presentationDataContext(sources:PresentationDataSource[]|undefined,recommendedIds:string[]=[]){
  const groups=(sources??[]).map(source=>dataViews([source])),all=groups.flat(),recommended=new Set(recommendedIds);
  const selected=all.filter(view=>recommended.has(view.id));
  const limit=recommendedIds.length?Math.min(8,Math.max(4,recommendedIds.length*2)):40;
  for(let i=0;selected.length<limit&&groups.some(group=>i<group.length);i++)for(const group of groups){const view=group[i];if(view&&selected.length<limit&&!recommended.has(view.id))selected.push(view);}
  const noted=new Set<string>();
  return selected.map(view=>{const sourceId=view.id.split(':')[0]!,sourceNotes=noted.has(sourceId)?undefined:view.sourceNotes;noted.add(sourceId);return {id:view.id,title:view.title,kind:view.kind,chartType:view.chartType,chartChoices:dataChartChoices(view),unit:view.unit,
    categoryLabel:view.categoryLabel,datasetName:view.datasetName,observations:view.observations,
    provenanceForNotes:{fileName:view.fileName,missing:view.missing,sourceNotes,caption:view.caption},
    categories:view.categories.slice(0,8),series:view.series.map(series=>({name:series.name,values:series.values.slice(0,8),
      ...(series.values.length?{min:Math.min(...series.values),max:Math.max(...series.values),first:series.values[0],last:series.values.at(-1)}:{})})),
    ...(view.table?{table:view.table}:{}),purpose:view.purpose??'evidence',definition:view.definition,aggregation:view.aggregation};});
}
export const presentationDataPrompt=`USER DATA CONTRACT: attachedData is an inventory of OPTIONAL evidence views, not a list of required slides. First interpret the subject, populations, units, dates and relationships. Follow dataAllocation: select only its recommended evidence IDs within maxEvidenceSlides, typically TWO evidence slides in a 15-slide talk with two files. Related series belong on ONE comparison chart; duplicate files do not require duplicate slides. A context/constant uncertainty field is a qualification, not another chart. The other slides develop the question, context, method, interpretation, implications, supported solution and final answer. Never build a country-by-country or variable-by-variable catalogue. Do not repeat the same numbers or chart elsewhere, including unbound charts/metric cards. One statistical slide needs a readable visual AND a short explanation of its specific finding. Prefer supplied observations to web statistics. Reference the exact view.id using dataViewId. Different measures, units, periods and populations remain separate. Use line charts for ordered time, bars for comparable categories, and pie/donut only for genuine parts of a whole. Preserve source attribution, missing-data notices and sampling/aggregation details in notes. Visible chart text is one short audience-facing explanation below the plot: what it shows, its key result and meaning. Do not display filenames, parser diagnostics or a methodology dump. Keep meaningful units and the scope needed for an honest interpretation. The renderer binds exact observations or explicitly computed group means; never invent or recompute values in model code. Display rounding changes labels only. Conclusions must be supported; correlation is not causation. Build one narrative from the question to an answer and a feasible next step. Unused optional views remain in the source files; they are not missing presentation content.`;
