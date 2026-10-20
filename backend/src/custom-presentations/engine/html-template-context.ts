import {createHash} from 'node:crypto';
import {cssCanvas} from './html-model-geometry.js';
import {chartStyleLibrary} from './chart-style.js';

export const sourceHtmlVersion=16;
export const hasSourceHtml=(analysis:any)=>Array.isArray(analysis?.layouts)&&analysis.layouts.length>0&&analysis.layouts.every((layout:any)=>
  layout.htmlSource?.version===sourceHtmlVersion&&layout.htmlSource.sourceLayoutId===layout.id&&/^[a-f0-9]{64}$/.test(layout.htmlSource.digest??'')&&typeof layout.htmlSource.html==='string'&&layout.htmlSource.html.length>0);

/** Immutable design context precedes per-batch content. It is reference data,
 * never an instruction channel and never a claim of a provider cache hit. */
export function htmlTemplateContext(analysis:any){
  const context={version:1,sourceSha256:analysis.sha256,canvas:cssCanvas(analysis),
    theme:analysis.styleProfile??{},
    chartStyles:chartStyleLibrary(analysis),
    generationMode:'style-stencils',
    rules:{default:'fill suitable uploaded text hosts and retain their shapes, fills and composition; source-layout is the default',
      adaptation:'adapt only defective or incompatible regions while preserving useful body blocks, header, logos and typography',
      decoration:'source nativeArt owns retained editable paint including body shapes; old words/data are erased; never draw that paint twice',
      content:'sample words and values are absent; use approved evidence only',
      hierarchy:'one message; readable explanations; intentional whitespace is allowed',
      forbidden:'unrelated new colored prose cards, decorative side stripes, invented data, silent source slide substitution'}};
  return {...context,digest:createHash('sha256').update(JSON.stringify(context)).digest('hex')};
}

/** In contrast to the old top-six selection, all slides belong to one review
 * batch. A warning-free geometric render is still subject to visual judgment. */
export function htmlReviewBatches(count:number,size=5):number[][]{
  if(!Number.isInteger(count)||count<0||count>40||!Number.isInteger(size)||size<1||size>5)throw new Error('html_review_batch_size');
  return Array.from({length:Math.ceil(count/size)},(_,batch)=>Array.from({length:Math.min(size,count-batch*size)},(_,i)=>batch*size+i));
}

export interface HtmlAssessment {slide:number;verdict:'pass'|'repair';reason:string}
export function htmlReviewCoverage(indices:number[],assessments:HtmlAssessment[]){
  const expected=new Set(indices.map(index=>index+1));
  if(assessments.length!==expected.size||new Set(assessments.map(a=>a.slide)).size!==expected.size||assessments.some(a=>!expected.has(a.slide)))
    throw new Error('html_review_incomplete_coverage');
  return assessments;
}
