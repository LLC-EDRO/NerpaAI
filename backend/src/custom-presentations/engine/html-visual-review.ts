import {styleReviewPrompt,sourceResetReviewPrompt} from './style-prompts.js';
import {sourceFidelityPrompt,slideFamilyPrompt} from './html-design-policies.js';
import {z} from 'zod';
import {htmlCardSchema,sourceShapeEditSchema,type HtmlCopy,type HtmlWarning} from './html-domain.js';
import {normalizeHtmlNumbers} from './html-code-normalization.js';

// Keep valid, expensive assessments/patches when a provider appends a prose
// string or an empty placeholder to a diagnostic array. Coverage and slide
// scope remain strict; an unscoped string never becomes an invented finding.
const scopedObjects=(value:unknown)=>Array.isArray(value)?value.filter(item=>item&&typeof item==='object'&&!Array.isArray(item)&&Number.isInteger(item.slide)):value;
const repairObjects=(value:unknown)=>Array.isArray(value)?value.filter(item=>item&&typeof item==='object'&&!Array.isArray(item)&&Number.isInteger(item.slide)&&typeof item.reason==='string'):value;
export const htmlVisualReviewSchema=z.object({
  assessments:z.array(z.object({slide:z.number().int().min(1).max(40),verdict:z.enum(['pass','repair']),reason:z.string().min(1).max(500)})).max(40).optional(),
  css:z.string().max(24000).optional(),
  issues:z.preprocess(scopedObjects,z.array(z.object({slide:z.number().int().min(1).max(40),message:z.string().max(900),reason:z.string().optional()})).max(30).default([])),
  repairs:z.preprocess(repairObjects,z.array(z.object({slide:z.number().int().min(1).max(40),reason:z.string().max(600),
    resetToSource:z.boolean().optional(),
    html:z.string().max(24000).optional(),css:z.string().max(24000).optional(),cssPatch:z.string().max(3000).optional(),
    sourceShapeEdits:z.array(sourceShapeEditSchema).max(16).optional(),
    sourceBindings:z.array(z.object({shapeId:z.number().int().positive(),paths:z.array(z.string().regex(/^(?:title|takeaway|paragraphs\.\d+|(?:cards|steps)\.\d+\.(?:title|body)|metrics\.\d+\.(?:value|label))$/)).max(20)}).strict()).max(32).optional(),
    title:z.string().trim().max(200).optional(),paragraphs:z.array(z.string().max(600)).max(8).optional(),
    metrics:z.array(z.object({value:z.string().max(80),label:z.string().max(280)}).strict()).max(8).optional(),
    cards:z.array(htmlCardSchema).max(8).optional(),steps:z.array(htmlCardSchema).max(6).optional(),takeaway:z.string().max(280).optional(),
})).max(8).default([])),
});
export type HtmlVisualReview=z.infer<typeof htmlVisualReviewSchema>;
/** A diagnosis without an actual patch still needs the targeted code request. */
export function hasHtmlRepairAction(repair:HtmlVisualReview['repairs'][number]){
  return Object.entries(repair).some(([key,value])=>!['slide','reason'].includes(key)&&!(key==='resetToSource'&&value!==true)&&value!==undefined&&
    (value===null||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length>0));
}
const numbers=(text:string):string[]=>(text.match(/(?<!\d)[+−-]?\d+(?:[.,]\d+)?/g)??[]).map(value=>value.replace('−','-').replace(',','.').replace(/^\+/,''));
// Array separators are syntax, not decimal commas. Read scalar leaves so
// [42,56,70,88] cannot become evidence for the unrelated number 42.56.
function evidenceNumbers(value:unknown):string[]{
  if(typeof value==='string'||typeof value==='number')return numbers(String(value));
  if(Array.isArray(value))return value.flatMap(evidenceNumbers);
  return value&&typeof value==='object'?Object.values(value).flatMap(evidenceNumbers):[];
}

/** A copy edit and its bindings form one transaction. A reviewer must not
 * remove bindings for protected data that its response cannot change. */
function hasRequiredBindings(slide:HtmlCopy['slides'][number],titleRequired=true){
  if(!slide.html)return true;
  const used=[...slide.html.matchAll(/\bdata-text\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/g)].map(m=>m[1]??m[2]??m[3]);
  const required=titleRequired?['title']:[];
  {
    slide.paragraphs.forEach((value,i)=>{if(value)required.push(`paragraphs.${i}`);});
    for(const field of ['cards','steps','metrics'] as const)slide[field].forEach((item,i)=>{
      for(const [key,value] of Object.entries(item))if(value)required.push(`${field}.${i}.${key}`);
    });
    if(slide.takeaway)required.push('takeaway');
    for(const kind of ['table','chart'] as const)if(slide[kind]&&!new RegExp(`data-visual\\s*=\\s*["']?${kind}\\b`).test(slide.html))return false;
  }
  return required.every(key=>used.filter(value=>value===key).length===1);
}

/** Review the visible terminal, not copy intentionally moved into its notes. */
export function visibleHtmlReviewCopy(copy:HtmlCopy,rendered:any[]){
  return copy.slides.map(({index,notes,speech,html,css,designDecision,...content},ordinal)=>{
    const scene=rendered[ordinal]?.native?.html;
    return {slide:ordinal+1,...content,title:Array.isArray(scene?.texts)&&!scene.texts.some((text:any)=>text.key==='h_title')?'':scene?.title??content.title,
      ...(scene?.designBounds?.content?.length===0?{paragraphs:[],cards:[],steps:[],metrics:[],table:null,chart:null,takeaway:''}:{})};
  });
}

/** A reviewer can repair layout/copy, never silently replace source data. */
export function applyHtmlVisualRepairs(copy:HtmlCopy,review:HtmlVisualReview,roles:string[],source:string){
  const next=structuredClone(copy),changed:number[]=[],warnings:HtmlWarning[]=[];
  const sharedChanged=review.css!==undefined&&review.css!==copy.css;
  if(sharedChanged)next.css=review.css;
  const evidence=new Set([...numbers(source),...evidenceNumbers(copy.slides.map(({title,paragraphs,cards,steps,metrics,table,chart,takeaway,notes,speech})=>
    ({title,paragraphs,cards,steps,metrics,table,chart,takeaway,notes,speech})))]);
  for(const repair of review.repairs){
    const index=repair.slide-1,slide=next.slides[index];
    if(!slide||changed.includes(index))continue;
    const before=structuredClone(slide);
    if(repair.steps&&repair.steps.length!==slide.steps.length&&!(repair.resetToSource&&slide.steps.length===0)){
      warnings.push({slide:repair.slide,reason:'html_repair_data_rejected',message:'Число этапов утверждённой схемы сохранено; проверка может уточнить их подписи.'});continue;
    }
    if(repair.metrics&&(repair.metrics.length!==slide.metrics.length||repair.metrics.some((metric,i)=>metric.value!==slide.metrics[i]!.value))){
      warnings.push({slide:repair.slide,reason:'html_repair_data_rejected',message:'Числа и единицы показателей сохранены: проверка может менять только их пояснения.'});continue;
    }
    const commit=()=>{
      if(repair.sourceBindings===undefined&&slide.sourceBindings){
        // A shortened copy must not retain dead layout pointers and trigger
        // paid re-authoring when the valid result is resumed later.
        slide.sourceBindings=slide.sourceBindings.map(binding=>({...binding,paths:binding.paths.filter(path=>{
          const value=path.split('.').reduce<any>((owner,key)=>owner?.[key],slide);
          return typeof value==='string'&&!!value.trim();
        })})).filter(binding=>binding.paths.length);
      }
      // Source-managed HTML is rebound immediately after this transaction.
      // A reviewer may split one paragraph into two genuine source rows
      // without rewriting the whole DOM. Check bespoke replacement HTML
      // strictly, but do not reject the new field against the OLD managed DOM.
      const rebindSource=repair.resetToSource===true&&roles[index]==='content'&&!slide.html?.trim()||repair.html===undefined&&/\bdata-source-composition-key=/.test(before.html??'')&&
        (repair.paragraphs!==undefined||repair.cards!==undefined||repair.steps!==undefined);
      if(!rebindSource&&!hasRequiredBindings(slide,!before.html||/data-text\s*=\s*["']title["']/.test(before.html))){
        next.slides[index]=before;
        warnings.push({slide:repair.slide,reason:'html_repair_binding_rejected',message:'Исправление пропустило существующее содержание; сохранена предыдущая вёрстка слайда.'});return;
      }
      changed.push(index);
    };
    let layoutChanged=false;
    if(repair.resetToSource&&roles[index]==='content'){
      slide.html='';slide.css='';slide.stencilId='source-layout';slide.sourceBindings=[];
      slide.sourceShapeEdits=[];slide.omitSourceIconIds=[];layoutChanged=true;
    }
    if(repair.sourceShapeEdits!==undefined){slide.sourceShapeEdits=repair.sourceShapeEdits;layoutChanged=true;}
    if(repair.sourceBindings!==undefined){slide.sourceBindings=repair.sourceBindings;layoutChanged=true;}
    if(repair.html!==undefined){slide.html=normalizeHtmlNumbers(repair.html);layoutChanged=true;}
    if(repair.css!==undefined){slide.css=repair.css;layoutChanged=true;}
    if(repair.cssPatch?.trim()){slide.css=[slide.css,repair.cssPatch].filter(Boolean).join('\n');layoutChanged=true;}
    const copyChange=repair.title!==undefined||repair.paragraphs!==undefined||repair.cards!==undefined||repair.steps!==undefined||repair.metrics!==undefined||repair.takeaway!==undefined;
    const closing=roles[index]==='closing';
    const cover=roles[index]==='cover'||roles[index]==='section';
    if(!copyChange||roles[index]!=='content'&&!closing&&!cover){if(layoutChanged)commit();continue;}
    if(closing&&(repair.title!==undefined||repair.cards?.length)){if(layoutChanged)commit();continue;}
    if(cover&&repair.cards?.length){if(layoutChanged)commit();continue;}
    const dataObject=!!(slide.table||slide.chart||slide.metrics.length||slide.steps.length);
    if(dataObject&&repair.cards?.length){if(layoutChanged)commit();continue;}
    if(numbers(JSON.stringify(repair.cards??[])+' '+JSON.stringify(repair.steps??[])+' '+JSON.stringify(repair.metrics??[])+' '+(repair.paragraphs??[]).join(' ')+(repair.title??'')+(repair.takeaway??'')).some(n=>!evidence.has(n))){
      if(layoutChanged)commit();
      warnings.push({slide:repair.slide,reason:'html_repair_data_rejected',message:'Неподтверждённые числа из предложения проверки отклонены; исходные данные сохранены.'});continue;
    }
    // Recomposition into cards replaces duplicated prose. If a numeric fact
    // was omitted, retain that original paragraph rather than silently lose it.
    const paragraphs=repair.paragraphs??(repair.cards?.length?slide.paragraphs.filter(p=>numbers(p).some(n=>!numbers(JSON.stringify(repair.cards)).includes(n))):undefined);
    Object.assign(slide,{...(repair.title?{title:repair.title}:{}),...(paragraphs?{paragraphs}:{}),
      ...(repair.cards?{cards:repair.cards}:{}),...(repair.steps?{steps:repair.steps}:{}),...(repair.takeaway!==undefined?{takeaway:repair.takeaway}:{})});commit();
    if(cover&&(repair.title||repair.paragraphs))slide.notes=[before.notes,...(repair.title&&repair.title!==before.title?[before.title]:[]),...(repair.paragraphs?before.paragraphs:[])].filter(Boolean).join('\n');
    if(repair.metrics&&changed.includes(index))slide.metrics=repair.metrics;
  }
  return {copy:next,changed:sharedChanged?next.slides.map((_,index)=>index):changed,warnings};
}

export const htmlVisualReviewPrompt=styleReviewPrompt+'\n'+sourceFidelityPrompt+'\n'+slideFamilyPrompt+'\n'+sourceResetReviewPrompt;
export const htmlTargetedReviewPrompt=htmlVisualReviewPrompt+`
Repair ONLY failedSlides with measured problems. Header/logo/background style remains stable, while the body can reflow using a suitable stencil inside actual safe surfaces. Prioritize html_text_overlap, html_text_overflow, html_busy_background, missing assigned figures and html_author_recovered. Keep every source data value and its meaningful unit/scope. Keep technical source captions, filenames, method and missing-row details in notes. The visible text is one short explanation below a large chart: what is shown, the main result, and its meaning. Do not replace a chart with a photo. Shorten repetitive explanatory prose together with its bindings when it is the cause of overflow. Use a shared grid/flex flow with minmax(0,1fr), min-width:0 and an explicit total height instead of guessing overlapping Y positions. sourceDesign.styleSystem supplies the new body surface; old sample text anchors and diagram topology are references. Preserve the real original terminal composition. Return concise cssPatch or complete local HTML/CSS plus any necessary copy shortening. Never add arbitrary colored prose boxes or a side stripe. Never change statistics, silently omit a field or make important explanation microscopic.`;
