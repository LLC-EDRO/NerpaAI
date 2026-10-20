import type {Layout,Slot} from './domain.js';

const furniture=new Set(['brand','logo','decoration','footer','page_number','icon']);
const headingRoles=new Set(['header','title']);
function capacity(slot:Slot){
  const measured=slot.textFit?.targetChars;
  return Math.max(0,Math.min(Number.isFinite(slot.maxChars)?slot.maxChars:0,Number.isFinite(measured)?measured:Infinity));
}
/** Explicit template instructions are not narrative copy. Native fields remain editable. */
export function templateInstruction(text:string){
  const value=text.trim().replace(/\s+/g,' ');
  return /\b(?:insert|replace|enter|type|add|paste)\b.{0,70}\b(?:text|title|heading|content|image|photo|here)\b/i.test(value)||
    /(?:^|[.!?:]\s*)(?:вставьте|разместите|добавьте|введите|укажите|напишите|замените|поместите|впишите)\s.{0,70}(?:текст|заголов|назван|изображ|фото|содержан)/iu.test(value)||
    /(?:здесь|в\s+этом\s+поле)\s+(?:размещается|должен\s+быть|вставляется|будет)\s+(?:основной\s+)?(?:текст|заголов|содержан)/iu.test(value);
}
export function narrativeLayoutCapabilities(layout:Pick<Layout,'slots'|'charts'>&Record<string,any>){
  if(layout.htmlTemplateLayout){const terminal=['cover','closing','section'].includes(layout.htmlRole);
    return {hasHeading:true,bodyChars:layout.htmlBodyChars??650,instructionOnly:false,sectionOnly:terminal,
      automaticContentEligible:!terminal,automaticSectionEligible:layout.htmlRole==='section'};}
  const text=(layout.slots||[]).filter(slot=>!slot.cell&&!furniture.has(slot.role));
  const headings=text.filter(slot=>headingRoles.has(slot.role)&&capacity(slot)>=8);
  const bodies=text.filter(slot=>!headingRoles.has(slot.role));
  const bodyChars=bodies.reduce((sum,slot)=>sum+capacity(slot),0);
  const data=(layout.charts||[]).length>0||(layout.slots||[]).some(slot=>!!slot.cell)||(layout.imageSlots||[]).length>0;
  // A native chart's actual title is also visible content. Column headings of
  // a table label properties and do not replace the slide's overall heading.
  const hasChartHeading=(layout.charts||[]).some(chart=>chart.hasTitle===true);
  const hasHeading=headings.length>0||hasChartHeading;
  // Ordinary title+body placeholders are a real composition, even if their
  // sample text tells the template user what to type into each native field.
  const instructionOnly=!hasHeading&&text.length>0&&text.every(slot=>templateInstruction(slot.text||''));
  const sectionOnly=hasHeading&&!data&&bodies.length===0;
  return {hasHeading,bodyChars,instructionOnly,sectionOnly,
    automaticContentEligible:hasHeading&&!instructionOnly&&(bodyChars>=80||data),
    automaticSectionEligible:sectionOnly,
    ...(layout.derivedMediaKind==='text'?{preferredTextLayout:true}:{})};
}
