import type {Layout} from './domain.js';

/** Vendor instructions/credits describe template use, not an audience slide.
 * Manual source selection remains available outside automatic planning. */
export function isTemplateUtilityLayout(layout:any){
  const heading=(layout.slots??[]).filter((slot:any)=>['title','header'].includes(slot.role)).map((slot:any)=>String(slot.text??'').trim()).join(' ');
  const text=(layout.slots??[]).map((slot:any)=>String(slot.text??'')).join(' ');
  return /^(?:instructions? for use|how to use (?:this |the )?template|credits|инструкци[яи] по использованию(?: шаблона)?|благодарности авторам шаблона)$/iu.test(heading)||
    /you are (?:not )?allowed to[\s\S]{0,1200}(?:templates?|presentations?)/iu.test(text)&&/personal|commercial|redistribut|resell|copyright/iu.test(text);
}

/** Only layouts covered by the current HTML design receipt enter planning. */
export function automaticTemplateLayouts<T extends {id:string}=Layout>(analysis:{layouts:T[];htmlTemplate?:{layoutIds:string[]}}|undefined):T[] {
  const layouts=analysis?.layouts??[];
  if(!analysis?.htmlTemplate)return layouts;
  const ids=new Set(analysis.htmlTemplate.layoutIds);
  const covered=layouts.filter(layout=>ids.has(layout.id)&&!isTemplateUtilityLayout(layout));
  const original=covered.filter(layout=>!(layout as any).derivedMediaKind);
  // Generic native data derivatives were useful to the old filler. HTML can
  // adapt the actual source frames without replacing them with those layouts.
  if(original.some(layout=>(layout as any).htmlRole==='content'))return original;
  return covered;
}
