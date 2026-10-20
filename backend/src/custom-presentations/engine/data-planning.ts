import type {Project,Outline} from './domain.js';
import {dataViews,dataChartChoices} from './data-contract.js';

type View=ReturnType<typeof dataViews>[number];
/** File names and IDs are provenance, not new statistical evidence. */
export const dataViewFingerprint=(view:View)=>JSON.stringify([view.kind,view.unit,view.categoryLabel,view.categories,view.series,view.table,view.aggregation]);
const words=(text:string)=>new Set(text.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu)??[]);
export function planDataAllocation(p:Pick<Project,'brief'>){
  const all=dataViews(p.brief?.dataSources),seen=new Set<string>();
  const distinct=all.filter(view=>{const key=dataViewFingerprint(view);if(seen.has(key))return false;seen.add(key);return true;});
  const evidence=distinct.filter(view=>view.purpose!=='context');
  // A source registry may legitimately contribute a useful descriptive table
  // alongside a numeric chart, rather than an invented second statistic.
  const views=evidence.length>=2?evidence:[...evidence,...distinct.filter(view=>view.purpose==='context'&&view.kind==='table')];
  const topic=words(p.brief?.topic??'');
  const score=(view:View)=>{
    const relevance=[...words(view.title+' '+view.datasetName)].filter(word=>topic.has(word)).length;
    const values=view.series.flatMap(series=>series.values),range=values.length?Math.max(...values)-Math.min(...values):0;
    const contrast=values.length?range/Math.max(1,...values.map(Math.abs)):0;
    return relevance*4+(view.kind==='chart'?4:0)+(view.series.length>1?2:0)+(view.aggregation?2:0)+contrast-
      (view.series.length&&view.series.every(s=>new Set(s.values).size===1)?5:0);
  };
  const ranked=[...views].sort((a,b)=>score(b)-score(a));
  const count=p.brief?.count??15;
  const maxEvidenceSlides=Math.min(views.length,Math.max(1,Math.min(4,Math.floor((count-2)*.3),Math.max(2,p.brief?.dataSources?.length??0))));
  const recommended:View[]=[];
  // Cover independent sources before adding another variable from one file.
  for(const source of p.brief?.dataSources??[]){const view=ranked.find(view=>view.id.startsWith(source.id+':'));if(view&&recommended.length<maxEvidenceSlides)recommended.push(view);}
  for(const view of ranked)if(recommended.length<maxEvidenceSlides&&!recommended.includes(view))recommended.push(view);
  return {minEvidenceSlides:Math.min(maxEvidenceSlides,(p.brief?.dataSources?.length??0)>=2?2:1),maxEvidenceSlides,recommendedViewIds:recommended.map(view=>view.id),availableViewIds:views.map(view=>view.id),
    policy:'With two attached data sources use at least two meaningful visuals (chart or table), normally two in a 15-slide deck. Duplicate observations are never counted twice: use a distinct supported aspect or a derived interval table. Evidence is a chapter, followed by interpretation, application and a supported answer; do not fill the story with more variables.'};
}

/** Keep the model's argument; bind only a bounded, distinct evidence chapter.
 * Unselected optional views never overwrite narrative titles or create warnings. */
export function attachPlannedData(p:Project,plan:Outline){
  const all=dataViews(p.brief?.dataSources),known=new Map(all.map(view=>[view.id,view]));
  if(!all.length)return {plan,warnings:[]};
  const allocation=planDataAllocation(p),result=structuredClone(plan),used=new Set<string>(),valid=new Set(allocation.availableViewIds);
  const eligible=result.slides.map((slide,index)=>({slide,index})).filter(({slide,index})=>index>0&&index<result.slides.length-1&&
    p.analysis?.layouts?.find((layout:any)=>layout.id===slide.sourceLayoutId)?.htmlRole==='content');
  const eligibleIndices=new Set(eligible.map(({index})=>index));
  result.slides.forEach((slide,index)=>{if(!eligibleIndices.has(index))delete slide.dataViewId;});
  const selected:typeof eligible=[];
  for(const item of eligible){
    const id=item.slide.dataViewId,view=id?known.get(id):undefined,key=view?dataViewFingerprint(view):'';
    if(view&&valid.has(id!)&&!used.has(key)&&selected.length<allocation.maxEvidenceSlides){used.add(key);selected.push(item);continue;}
    if(id){
      delete item.slide.dataViewId;
      // Defensive recovery of an overlong statistical catalogue. Keep this
      // local and bounded; the author develops these tasks from actual sources.
      const stages=[['Как читать результаты','Объяснить, какие объекты и показатели сопоставимы, какие различия нельзя интерпретировать как причинность.'],
        ['Что следует из наблюдений','Связать уже показанные данные с центральным вопросом; объяснить значение результата без повторения чисел и графиков.'],
        ['Границы выводов','Объяснить ограничения источников, пропуски и условия применимости выводов по теме.'],
        ['Практический следующий шаг','Предложить проверяемое действие по теме на основе уже изложенных результатов, не выдумывая эффект или прогноз.']];
      const stage=stages[Math.min(3,Math.floor((item.index-1)*4/Math.max(1,result.slides.length-2)))]!;
      item.slide.title=stage[0]!;item.slide.brief=`${stage[1]} Тема: ${p.brief?.topic??''}.`;
      item.slide.visualPlan={kind:'text',description:'Содержательное объяснение: 2–3 смысловые группы без повторного графика.'};
    }
  }
  // Recover only genuinely omitted evidence, in the middle of the argument.
  // Never replace opening/context, final answer or an assigned document figure.
  for(const id of allocation.recommendedViewIds){
    const view=known.get(id)!,key=dataViewFingerprint(view);if(used.has(key)||selected.length>=allocation.maxEvidenceSlides)continue;
    const start=result.slides.length>=8?Math.max(2,Math.floor(result.slides.length*.25)):1,end=result.slides.length>=8?result.slides.length-3:result.slides.length-1;
    const target=eligible.filter(item=>!item.slide.dataViewId&&!item.slide.sourceImageIds?.length&&item.index>=start&&item.index<end)
      .sort((a,b)=>Math.abs(a.index-result.slides.length*(.35+selected.length*.2))-Math.abs(b.index-result.slides.length*(.35+selected.length*.2)))[0];
    if(!target)continue;target.slide.dataViewId=id;target.slide.title=view.title;selected.push(target);used.add(key);
  }
  for(const {slide} of selected){
    const view=known.get(slide.dataViewId!)!,proposed=slide.visualPlan?.chartType;
    if(view.id.endsWith(':interval-changes'))slide.title=view.title;
    const chartType=proposed&&dataChartChoices(view).includes(proposed)?proposed:view.chartType;
    slide.visualPlan={kind:view.kind,chartType,description:`${view.title}. ${view.categoryLabel}${view.unit?` · ${view.unit}`:''}. ${view.caption}`.slice(0,600)};
    // Keep the approved finding and task. Exact values travel in the bound
    // data contract, not as an enormous duplicate paragraph in the brief.
    slide.brief=`${slide.brief??''}\nДанные: ${view.title}. Источник: ${view.fileName}. ${view.caption} Дать конкретное объяснение результата и связать его с предыдущим и следующим слайдом.`.slice(0,2000);
    slide.images=[];
  }
  for(const {slide} of eligible)if(!slide.dataViewId&&slide.visualPlan?.kind==='chart'){
    slide.visualPlan={kind:'diagram',description:'Качественное сопоставление и объяснение уже показанных результатов, без дополнительного количественного графика.'};
    slide.brief=slide.brief.replace(/\nВизуализация:[^]*$/u,'');
  }
  return {plan:result,warnings:[]};
}
