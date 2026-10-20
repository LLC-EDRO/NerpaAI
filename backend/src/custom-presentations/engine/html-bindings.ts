import {load} from 'cheerio';
import type {HtmlSlideCopy} from './html-domain.js';

/** Restore unambiguous source field assignments, preserving model CSS/copy.
 * Simple repeated rows own card bindings before an optional aside does;
 * ambiguous diagram topology still goes to the AI preflight. */
export function normalizeHtmlSourceBindings(slide:HtmlSlideCopy,source:any){
  if(!slide.html)return false;
  // Source composition has already fenced every path and owner and assigned
  // each nonempty field once. Do not second-guess these validated model
  // assignments with the legacy repeated-row ordering heuristic.
  if(/\bdata-source-composition-key=["'][a-f0-9]{64}["']/.test(slide.html))return false;
  const $=load(slide.html,null,false),byPath=new Map<string,any[]>();
  let changed=false;
  // Preserve authored captions/diagram labels as editable semantic text. Old
  // source words are absent from this DOM; copying these exact generated
  // strings into fields adds no claim and avoids silently emptying a diagram.
  const rows=source?.sourceHtml?.numberedRows??[];
  $('*').each((_,element)=>{
    const node=$(element);
    if(!('tagName' in element)||!/^(?:div|section|article|header|footer|main|aside|h[1-6]|p|span|strong|em|small|li|figure|figcaption)$/.test(element.tagName)||
      node.is('[data-text],[data-number],[data-visual]')||node.parents('[data-text],[data-number],[data-visual]').length)return;
    const textNodes=node.contents().toArray().filter((child:any)=>child.type==='text'&&child.data?.trim());
    for(const child of textNodes){
      const value=(child as any).data.trim();
      if(textNodes.length===1&&!node.children().length&&/^\d+$/.test(value)&&rows.some((r:any)=>r.ordinal===Number(value))){node.attr('data-number',value).empty();changed=true;continue;}
      let path:string;
      if(node.is('figcaption')&&!slide.takeaway){slide.takeaway=value;path='takeaway';}
      else{if(slide.paragraphs.length>=8)continue;path=`paragraphs.${slide.paragraphs.length}`;slide.paragraphs.push(value);}
      if(node.contents().length===1){node.attr('data-text',path).empty();}
      else $(child).replaceWith($('<span></span>').attr('data-text',path));
      changed=true;
    }
  });
  const groups=(source?.sourceHtml?.textGroups??[]).filter((g:any)=>g.role==='repeated-content');
  const aligned=(axis:'x'|'y')=>groups.length>1&&groups.every((g:any)=>Math.abs(g.box[axis]-groups[0].box[axis])<8);
  // A simple four-row icon list has four card destinations; the optional
  // sidebar is not row one. Restore source field assignment when the model
  // shifts all values by one row or duplicates its last value. Never impose
  // this ordering on radial diagrams, SWOT grids or unmatched cardinalities.
  if(groups.length===(slide.cards?.length??0)&&groups.every((g:any)=>g.box)&&(aligned('x')||aligned('y'))){
    const ordered=[...groups].sort((a:any,b:any)=>aligned('x')?a.box.y-b.box.y:a.box.x-b.box.x);
    const frames=ordered.map((g:any)=>({g,heading:$(`[data-source-shape="${g.headingShapeId}"]`),body:$(`[data-source-shape="${g.bodyShapeId}"]`)}));
    const groupByShape=new Map(ordered.flatMap((g:any)=>[[g.headingShapeId,g.id],[g.bodyShapeId,g.id]]));
    if(frames.every(({g,heading,body}:any)=>{
      if(heading.length>1||body.length>1||!heading.length&&!body.length)return false;
      if(heading.length&&body.length)return true;
      const parent=(heading.length?heading:body).parent();
      return !parent.attr('data-source-shape')&&parent.find('[data-source-shape]').toArray().every((el:any)=>{
        const owner=groupByShape.get(Number($(el).attr('data-source-shape')));return !owner||owner===g.id;
      });
    })){
      const ids=new Set<number>();
      frames.forEach(({g,heading,body}:any,i:number)=>{
        if(!heading.length){heading=$(`<h2 data-source-shape="${g.headingShapeId}"></h2>`);body.before(heading);changed=true;}
        if(!body.length){body=$(`<p data-source-shape="${g.bodyShapeId}"></p>`);heading.after(body);changed=true;}
        for(const [node,path,id] of [[heading,`cards.${i}.title`,g.headingShapeId],[body,`cards.${i}.body`,g.bodyShapeId]] as const){
          if(node.attr('data-text')!==path){node.attr('data-text',path);changed=true;}ids.add(id);
        }
      });
      $('[data-text^="cards."]').each((_,element)=>{
        const node=$(element),id=Number(node.attr('data-source-shape'));
        if(ids.has(id))return;
        if(id===source?.title?.shapeId&&source?.headingAuthority==='vision')node.attr('data-text','title');else node.remove();
        changed=true;
      });
    }
  }
  $('[data-text]').each((_,element)=>{const path=$(element).attr('data-text')!;byPath.set(path,[...(byPath.get(path)??[]),element]);});
  for(const [path,elements] of byPath){
    if(elements.length<2)continue;
    const score=(element:any)=>{
      const id=Number($(element).attr('data-source-shape'));
      if(path==='title')return id===source?.title?.shapeId?100:0;
      if(!/^(cards|steps|metrics)\./.test(path))return 0;
      const group=source?.sourceHtml?.textGroups?.find((g:any)=>g.headingShapeId===id||g.bodyShapeId===id);
      return group?.role==='repeated-content'?30:group?.role==='lead-or-aside'?-10:0;
    };
    const ranked=elements.map(element=>({element,score:score(element)})).sort((a,b)=>b.score-a.score);
    if(ranked[0]!.score<=ranked[1]!.score)continue;
    for(const item of ranked.slice(1))$(item.element).remove();changed=true;
  }
  if(changed)slide.html=$.html();
  return changed;
}
