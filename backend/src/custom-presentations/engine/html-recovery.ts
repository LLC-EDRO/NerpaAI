import type {HtmlSlideCopy} from './html-domain.js';
import {sourceHtmlDesign} from './html-source-design.js';
import {realizeStyleStencil} from './style-stencils.js';

/** Last-resort copy is still audience-facing. A plan is an assignment, and its
 * stage directions must never be pasted into a finished slide. */
export function recoveryPoints(brief:string):string[]{
  const value=brief.replace(/\n(?:Визуализация|Данные):[^]*$/u,'').trim().replace(/^(?:три части доклада|сравнение ключевых параметров|утвержд[её]нные параметры|ответ на вопрос доклада)\s*:\s*/iu,'');
  if(/^(?:титул\s*:|короткое завершение доклада|тема доклада и подзаголовок)/iu.test(value))return [];
  // Decimal commas and commas inside parenthesized lists stay intact.
  const sentences=value.split(/;\s*|(?<!долл)(?<!млн)(?<!трлн)\.\s+(?=[А-ЯЁA-Z])/u).map(s=>s.trim()).filter(Boolean);
  if(sentences.length>1)return boundedPoints(sentences);
  let depth=0,start=0;const parts:string[]=[];
  for(let i=0;i<value.length;i++){
    if(value[i]==='(')depth++;else if(value[i]===')')depth=Math.max(0,depth-1);
    if(!depth&&value[i]===','&&!/\d/.test(value[i-1]??'')&&!/\d/.test(value[i+1]??'')){parts.push(value.slice(start,i).trim());start=i+1;}
  }
  parts.push(value.slice(start).trim());
  // Only explicit enumerations should become comma-separated points.
  return boundedPoints(/^(?:три части доклада|первое\b)/iu.test(brief)?parts.filter(Boolean):sentences);
}
const boundedPoints=(points:string[])=>points.length<=8?points:[...points.slice(0,7),points.slice(7).join('; ')];

type Frame={x:number;y:number;w:number;h:number;shapeId:number;size:number};
/** Reuse actual source text groups, including multiple rows at the same X.
 * This emergency path cannot substitute a full-width preset for those fields. */
export function recoveryHtml(slide:HtmlSlideCopy,analysis:any,layout:any):HtmlSlideCopy{
  if(!layout?.slots?.length||!analysis?.width||!analysis?.height)return slide;
  const source=sourceHtmlDesign(analysis,layout),title=source.title;
  if(source.role==='content'&&'styleSystem' in source)return realizeStyleStencil({...slide,html:'',css:''},source);
  if(!title)return slide;
  const area=analysis.width*analysis.height;
  const fields=(layout.slots as any[]).filter(s=>s.shapeId!==title.shapeId&&!s.cell&&
    !['brand','logo','footer','page_number','decoration','label'].includes(s.role)&&s.w*s.h>area*.002&&s.w>40&&s.h>10);
  const frames:Frame[]=[];
  for(const s of fields.sort((a,b)=>a.y-b.y||a.x-b.x)){
    const previous=frames.find(f=>Math.abs(f.x-s.x)<8&&Math.abs(f.w-s.w)<16&&s.y>=f.y&&s.y-f.y-f.h<25);
    if(previous){previous.h=Math.max(previous.h,s.y+s.h-previous.y);previous.size=Math.max(previous.size,s.size??16);}
    else frames.push({x:s.x,y:s.y,w:s.w,h:s.h,shapeId:s.shapeId,size:s.size??16});
  }
  const terminal=['cover','closing','section'].includes(layout.htmlRole);
  // A title-only farewell has no visible subtitle. Preserve any meaningful
  // planned detail in notes instead of adding prose over its decoration.
  const points=terminal&&!frames.length?[]:slide.paragraphs;
  const slots:Frame[]=frames.length?frames:source.textAnchors.filter((s:any)=>s.shapeId!==title.shapeId).map((s:any)=>({...s.box,shapeId:s.shapeId,size:s.size??16}));
  if(points.length&&!slots.length)return {...slide,paragraphs:[],notes:[slide.notes,...points].filter(Boolean).join('\n'),html:'<main><h1 data-text="title"></h1></main>',css:titleCss(title)};
  const chosen=slots.slice(0,Math.min(slots.length,points.length));
  const assigned=chosen.map((frame,i)=>({frame,indices:points.map((_,n)=>n).filter(n=>Math.min(chosen.length-1,Math.floor(n*chosen.length/points.length))===i)}));
  const html='<main><h1 data-text="title"></h1>'+assigned.map(({frame,indices},i)=>`<section class="source-field-${i}" data-source-shape="${frame.shapeId}">${indices.map(n=>`<p data-text="paragraphs.${n}"></p>`).join('')}</section>`).join('')+'</main>';
  const css=titleCss(title)+assigned.map(({frame},i)=>`.source-field-${i}{position:absolute;left:${frame.x}pt;top:${frame.y}pt;width:${frame.w}pt;height:${frame.h}pt;display:flex;flex-direction:column;gap:8pt;overflow:hidden;font-size:${Math.max(16,Math.min(24,frame.size))}pt;line-height:1.2}`).join('')+'p{margin:0;min-height:0;flex:1 1 0}';
  return {...slide,paragraphs:points,html,css,...(!points.length&&slide.paragraphs.length?{notes:[slide.notes,...slide.paragraphs].filter(Boolean).join('\n')}:{})};
}
const titleCss=(title:any)=>`main{position:relative;width:100%;height:100%}h1{position:absolute;left:${title.box.x}pt;top:${title.box.y}pt;width:${title.box.w}pt;height:${title.box.h}pt;font-size:${title.size??32}pt;line-height:1.1;margin:0;font-weight:700;flex-shrink:0}`;
