import type {Outline} from './domain.js';
import {normalizeHtmlCopy,type HtmlCopy,type HtmlSlideCopy,type HtmlWarning} from './html-domain.js';

/** Bounded output per request. Authors share a title spine; local source
 * geometry, evidence and slide code are partitioned. */
export function htmlAuthorBatches(count:number,size=5){
  if(!Number.isInteger(count)||count<0||count>40||!Number.isInteger(size)||size<1||size>5)throw Error('html_author_batch_size');
  return Array.from({length:Math.ceil(count/size)},(_,i)=>Array.from({length:Math.min(size,count-i*size)},(_,n)=>i*size+n));
}
export function normalizeHtmlBatch(raw:unknown,plan:Outline,indices:number[],recovery?:HtmlCopy){
  const value=raw as any;
  if(!Array.isArray(value?.slides))throw Error('html_copy_batch_identity');
  // Providers occasionally append prose strings to slides. They are not slide
  // objects and must not discard valid, expensive authored neighbours.
  const candidates=value.slides.filter((s:any)=>s&&typeof s==='object'&&!Array.isArray(s));
  if(!candidates.length||candidates.length>indices.length||
    candidates.some((slide:any)=>!indices.includes(slide.index))||new Set(candidates.map((s:any)=>s.index)).size!==candidates.length)throw Error('html_copy_batch_identity');
  const warnings:HtmlWarning[]=[];
  const slides=indices.map(index=>{
    try{
      if(!candidates.some((s:any)=>s.index===index))throw Error('html_copy_batch_missing');
      const normalized=normalizeHtmlCopy({thesis:value.thesis,css:value.css,slides:[{...candidates.find((s:any)=>s.index===index),index:0}]},{slides:[plan.slides[index]!]});
      warnings.push(...normalized.warnings.map(w=>({...w,...(w.slide?{slide:index+1}:{})})));
      const slide=normalized.copy.slides[0]!;
      // A reference is not the copy itself. Empty arrays with apparently
      // plausible sourceBindings used to pass preflight and erase whole text
      // panels. Recover only this member; good neighbouring slides survive.
      const missing=(slide.sourceBindings??[]).flatMap(binding=>binding.paths).filter(path=>{
        const value=path.split('.').reduce<unknown>((owner,key)=>owner&&typeof owner==='object'?(owner as Record<string,unknown>)[key]:undefined,slide);
        return typeof value!=='string'||!value.trim();
      });
      if(missing.length)throw Error('html_copy_unresolved_source_bindings:'+missing.join(','));
      return {...slide,index,css:[normalized.copy.css,slide.css].filter(Boolean).join('\n')};
    }catch(error){
      if(!recovery)throw error;
      warnings.push({slide:index+1,reason:'html_approved_content_recovered',message:'Данные одного слайда восстановлены по утверждённому описанию; остальные слайды сохранены из ответа ИИ.'});
      return recovery.slides[index]!;
    }
  });
  // Shared CSS belongs to this batch. Inline it into its isolated slide styles
  // so another batch's class names can never change these slides.
  return {copy:{thesis:typeof value.thesis==='string'?value.thesis:recovery?.thesis??'',slides},warnings};
}
/** Cheap content preflight before spending a Chromium render on incomplete
 * markup. Geometry and visual quality are still assessed from real pixels. */
export function missingHtmlBindings(slide:HtmlSlideCopy,source?:any){
 const used=[...(slide.html??'').matchAll(/\bdata-text\s*=\s*(?:"([^"]+)"|'([^']+)')/g)].map(m=>m[1]??m[2]);
 const bodyOnly=(source?.headingAbsent||source?.textAnchors?.length===1&&['body','label'].includes(source.title?.role))&&!used.includes('title');
 const required=[...(bodyOnly?[]:['title']),...slide.paragraphs.map((p,i)=>p?`paragraphs.${i}`:'')];
 for(const field of ['cards','steps','metrics'] as const)slide[field].forEach((item,i)=>Object.entries(item).forEach(([key,value])=>{if(value)required.push(`${field}.${i}.${key}`);}));
 if(slide.takeaway)required.push('takeaway');
 return [...required.filter(Boolean).filter(key=>used.filter(path=>path===key).length!==1),
   ...(['table','chart'] as const).filter(kind=>slide[kind]&&!new RegExp(`data-visual\\s*=\\s*["']${kind}["']`).test(slide.html??''))];
}
/** A reset alone is not the CSS for a custom class-based composition. Source
 * DOM with real inline geometry remains valid; no preset layout is injected. */
export function missingHtmlLayoutStyles(slide:HtmlSlideCopy){
 if(!slide.html)return false;
 if(/^\s*<main>\s*<\/main>\s*$/.test(slide.html))return false;
 const inline=[...slide.html.matchAll(/\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')/g)].map(m=>m[1]??m[2]);
 return !/(?:^|[;{])\s*(?:position|display|grid(?:-[\w-]+)?|flex(?:-[\w-]+)?|font-size|line-height|left|top|width|height)\s*:/i.test([slide.css??'',...inline].join(';'));
}
/** A rejected visual proposal must roll its code and content back together. */
export function acceptedHtmlRepair(before:ReturnType<typeof normalizeHtmlCopy>['copy'],next:ReturnType<typeof normalizeHtmlCopy>['copy'],reverted:number[]){
 if(!reverted.length)return next;
 const rejected=new Set(reverted);
 return {...next,css:undefined,slides:next.slides.map((_,index)=>{
   const owner=rejected.has(index+1)?before:next,slide=owner.slides[index]!;
   return {...slide,css:[owner.css,slide.css].filter(Boolean).join('\n')};
 })};
}
