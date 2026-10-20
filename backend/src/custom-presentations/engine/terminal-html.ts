import type {HtmlSlideCopy} from './html-domain.js';

/** A closing logo-only composition has no subtitle destination. Keep extra
 * detail in notes instead of inventing a body over the institution's logo.
 * Real title/subtitle frames retain their native geometry and typography. */
export function realizeTerminalHtml(slide:HtmlSlideCopy,source:any):HtmlSlideCopy{
  if(!source.sourceHtml||!source.styleSystem||!['cover','closing','section'].includes(source.role))return slide;
  const title=source.title?{...source.title,box:{...source.title.box}}:undefined;
  const frames=(source.textAnchors??[]).filter((anchor:any)=>anchor.shapeId!==title?.shapeId&&['body','subtitle'].includes(anchor.role)&&anchor.box.w>40&&anchor.box.h>10);
  if(source.role==='cover'&&title){
    const column=frames.find((f:any)=>Math.abs(f.box.x-title.box.x)<15&&f.box.w<title.box.w*.7);
    if(column)title.box.w=Math.min(title.box.w,column.box.w);
  }
  let notes=[slide.notes,...(!frames.length?slide.paragraphs:[]),slide.takeaway,...slide.cards.flatMap(card=>[card.title,card.body])].filter(Boolean).join('\n');
  if(source.role==='closing'&&!title&&!frames.length)return {...slide,paragraphs:[],cards:[],steps:[],metrics:[],chart:null,table:null,takeaway:'',notes:[slide.title,notes].filter(Boolean).join('\n'),html:'<main></main>',css:''};
  // Terminal titles have real source frames. A model-supplied full-width
  // heading must not spill over the cover illustration or farewell logo.
  if(!title)return slide;
  const safe=(value:string)=>String(value??'Arial').replace(/["'<>\\]/g,'');
  const style=(frame:any)=>`position:absolute;left:${frame.box.x}pt;top:${frame.box.y}pt;width:${frame.box.w}pt;height:${frame.box.h}pt;font-family:"${safe(frame.font)}";font-size:${frame.size??18}pt;color:${frame.shapeId===title.shapeId?source.styleSystem.headingInk??frame.color:source.styleSystem.ink??frame.color};text-align:${frame.align??'left'};line-height:1.12;`;
  let paragraphs=frames.length?slide.paragraphs:[];
  if(source.role==='closing'){
    const capacity=frames.reduce((sum:any,f:any)=>sum+Math.floor(f.box.w/((f.size??18)*.55))*Math.max(1,Math.floor(f.box.h/((f.size??18)*1.12))),0);
    if(paragraphs.join(' ').length>capacity*.85){notes=[notes,...paragraphs].filter(Boolean).join('\n');paragraphs=[];}
  }
  const sections=frames.slice(0,Math.min(frames.length,paragraphs.length)).map((frame:any,index:number,selected:any[])=>{
    const indices=paragraphs.map((_,i)=>i).filter(i=>Math.min(selected.length-1,Math.floor(i*selected.length/paragraphs.length))===index);
    return `<section class="terminal-body" style='${style(frame)}display:flex;flex-direction:column;justify-content:center;gap:8pt'>${indices.map(i=>`<p data-text="paragraphs.${i}"></p>`).join('')}</section>`;
  }).join('');
  return {...slide,paragraphs,cards:[],steps:[],metrics:[],table:null,chart:null,takeaway:'',notes,
    html:`<main><h1 data-text="title" style='${style(title)}font-weight:700'></h1>${sections}</main>`,
    css:'main{position:relative;width:100%;height:100%}h1,.terminal-body p{margin:0}.terminal-body p{position:static!important;flex:0 1 auto;min-height:0}'};
}
