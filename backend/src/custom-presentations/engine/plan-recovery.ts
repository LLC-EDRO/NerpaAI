import {planSchema,type Layout,type Project,type Outline} from './domain.js';
import {automaticTemplateLayouts} from './template-catalog.js';
import {narrativeLayoutCapabilities} from './narrative-layouts.js';
import {enforceHtmlPlanRoles} from './html-layout-roles.js';

const protectedRoles=new Set(['icon','logo','brand','background','background_image','decoration','footer','page_number']);
export function sourceImageFrames(layout:Layout|undefined){
  return (layout?.imageSlots??[]).filter((slot:any)=>!slot.protected&&!slot.requiresOpaque&&!protectedRoles.has(slot.sourceRole));
}

/** Fresh proposals only: retain every word and original figure, change just an
 * incompatible donor to a measured content composition of the SAME template.
 * Approved/manual layouts never enter this function. */
export function recoverPlanProposal(p:Project,raw:unknown){
  const plan:Outline=planSchema.parse(raw);
  const warnings:ReturnType<typeof enforceHtmlPlanRoles>=[];
  const layouts=automaticTemplateLayouts<Layout>(p.analysis).filter(layout=>layout.usable&&narrativeLayoutCapabilities(layout).automaticContentEligible);
  const count=p.brief?.count??plan.slides.length;
  // A readable 14-slide answer must not fail a paid 15-slide request. Recover
  // small count errors before spending another full planning call. New slides
  // are authoring tasks, never invented observations or copies of sample text.
  if(plan.slides.length>=2&&count-plan.slides.length>0&&count-plan.slides.length<=2&&layouts.length){
    const donor=layouts.find(layout=>!sourceImageFrames(layout).length)??layouts[0]!;
    const additions=[
      {title:'Как использовать результаты',brief:'Свяжи уже показанный результат с исходным вопросом доклада. Объясни одно содержательное применение или практическое значение в рамках темы. Не повторяй числовые значения, не обсуждай файлы и парсинг; не выдавай возможное применение за выполненное внедрение.'},
      {title:'Дальнейшая проверка',brief:'Сформулируй один проверяемый следующий шаг из представленных выводов: что именно стоит наблюдать, сравнить или проверить дальше и зачем. Сохрани предмет доклада, не вводи новые измерения, числа, прогнозы или вымышленные результаты.'},
    ];
    const missing=count-plan.slides.length;
    plan.slides.splice(Math.max(1,plan.slides.length-2),0,...additions.slice(0,missing).map(slide=>({...slide,sourceLayoutId:donor.id,
      images:[],visualPlan:{kind:'text' as const,description:'Содержательное объяснение в стилистике шаблона; 2–3 короткие смысловые группы.'}})));
    warnings.push({slide:Math.max(2,plan.slides.length-2),reason:'plan_count_repaired',message:'Недостающий шаг рассказа добавлен в план; исходные данные и остальные слайды сохранены.'});
  }
  if(plan.slides.length-count>0&&plan.slides.length-count<=2){
    for(let i=1;plan.slides.length>count&&i<plan.slides.length-2;i++){
      const a=plan.slides[i]!,b=plan.slides[i+1]!;
      if([a,b].some(s=>s.dataViewId||s.sourceImageIds?.length||s.images?.length||s.visualPlan&&s.visualPlan.kind!=='text'))continue;
      const combined=a.brief+'\n'+b.title+': '+b.brief;if(combined.length>2000)continue;
      a.brief=combined;plan.slides.splice(i+1,1);i--;
    }
  }
  warnings.push(...enforceHtmlPlanRoles(p.analysis,plan.slides));
  const known=new Set(p.brief?.sourceDocument?.images.map(image=>image.id)??[]);
  plan.slides.forEach((slide,index)=>{
    if(!slide.sourceImageIds?.length||index===0||index===plan.slides.length-1||slide.sourceImageIds.some(id=>!known.has(id)))return;
    const count=new Set(slide.sourceImageIds).size;
    const current=layouts.find(layout=>layout.id===slide.sourceLayoutId);
    if(current&&sourceImageFrames(current).length>=count)return;
    const candidates=layouts.filter(layout=>sourceImageFrames(layout).length>=count);
    const score=(layout:Layout)=>
      (layout.htmlDesign?.canvas===current?.htmlDesign?.canvas?20:0)-
      (sourceImageFrames(layout).length-count)*2+
      (layout.id!==plan.slides[index-1]?.sourceLayoutId?1:0);
    const replacement=candidates.sort((a,b)=>score(b)-score(a)||a.index-b.index)[0];
    if(!replacement)return; // Precise validation/AI repair handles real capacity shortages.
    slide.sourceLayoutId=replacement.id;
    warnings.push({slide:index+1,reason:'plan_source_layout_repaired',message:'Для исходной иллюстрации автоматически выбран подходящий содержательный макет из вашего шаблона.'});
  });
  return {plan,warnings};
}
