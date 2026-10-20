import type {Project} from './domain.js';

/** The author receives only the facts for its selected slides. Global order
 * is a short title spine; neighbour briefs supply transitions, not geometry
 * or full documents for every repeated request. */
export function htmlAuthorContext(p:Project,indices:number[]){
  const slides=p.plan!.slides,selected=indices.map(index=>slides[index]!);
  const words=(text:string)=>new Set(text.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu)??[]);
  const keys=words(selected.map(slide=>slide.title+' '+slide.brief).join(' '));
  const relevance=(text:string)=>[...words(text)].reduce((n,word)=>n+(keys.has(word)?1:0),0);
  const evidence=(p.research?.evidence??[]).map(item=>({item,rank:relevance(item.text)})).filter(item=>item.rank>0).sort((a,b)=>b.rank-a.rank).slice(0,Math.max(2,indices.length*2)).map(item=>item.item);
  const source=p.brief?.sourceText??'';
  const chunks=source.split(/\n\s*\n|\n/).map((text,index)=>({text:text.trim(),index,rank:relevance(text)})).filter(item=>item.text&&item.text.length<=2500&&item.rank>0).sort((a,b)=>b.rank-a.rank);
  let length=0;const chosen=chunks.filter(item=>{if(length+item.text.length>3500)return false;length+=item.text.length;return true;}).sort((a,b)=>a.index-b.index);
  return {narrative:{topic:p.brief?.topic,opening:slides[0]?.title,conclusion:slides.at(-2)?.title,farewell:slides.at(-1)?.title,titles:slides.map((slide,index)=>({index,title:slide.title}))},
    sourceExcerpts:source.length<=1500?source:chosen.map(item=>item.text).join('\n'),evidence,
    dataInventory:(p.brief?.dataSources??[]).map(item=>({provenanceForNotes:{fileName:item.fileName},datasets:item.datasets.map(d=>({name:d.name,rows:d.rowCount,measures:d.views.filter(v=>v.purpose!=='context').map(v=>({title:v.title,definition:v.definition}))}))})),
    transitions:indices.map(index=>({index,previous:index>0?{title:slides[index-1]!.title,brief:slides[index-1]!.brief.slice(0,250)}:null,next:slides[index+1]?.title??null})),
    factPolicy:'Approved slide briefs and their bound data are authoritative. Excerpts and neighbouring titles provide context, not permission to add unrelated facts. Source template words/values are never evidence.'};
}
