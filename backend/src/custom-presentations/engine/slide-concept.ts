import {z} from 'zod';
import {isTemplateUtilityLayout} from './template-catalog.js';

export const contentKinds=['editorial','figure','chart','table','metrics','process','comparison'] as const;
const sides=['left','right','center','full','none'] as const;
const schema=z.object({kind:z.enum(contentKinds),visualSide:z.enum(sides),textSide:z.enum(sides),
  structure:z.enum(['split','columns','stack','full']),confidence:z.number().min(0).max(1)});
export type SlideConcept=z.infer<typeof schema>&{origin:'vision'|'native'};
const furniture=new Set(['logo','brand','background','background_image','footer','page_number','icon','decoration']);
const side=(box:any,width:number):typeof sides[number]=>!box?'none':box.w>width*.72?'full':box.x+box.w/2<width*.44?'left':box.x+box.w/2>width*.56?'right':'center';

/** One cached semantic classification per source slide. Native fallback never
 * guesses that an arbitrary photograph is a quantitative plot. */
export function sourceSlideConcept(layout:any,canvas:{width:number;height:number},raw:unknown=layout.htmlConcept):SlideConcept{
  const parsed=schema.safeParse(raw);
  if(parsed.success&&parsed.data.confidence>=.65)return {...parsed.data,origin:(raw as any)?.origin==='native'?'native':'vision'};
  const objects=(layout.sourceObjects??[]).filter((o:any)=>o.box&&!furniture.has(o.role)&&!o.hidden);
  const chart=objects.find((o:any)=>o.kind==='chart'||layout.htmlChartStyle?.sourceShapeIds.includes(o.shapeId));
  const table=objects.find((o:any)=>o.kind==='table');
  const photo=objects.filter((o:any)=>o.kind==='picture'&&o.box.w*o.box.h>canvas.width*canvas.height*.06).sort((a:any,b:any)=>b.box.w*b.box.h-a.box.w*a.box.h)[0];
  const body=(layout.slots??[]).filter((s:any)=>!furniture.has(s.role)&&!['title','header'].includes(s.role)&&s.y>canvas.height*.15);
  const metric=body.some((s:any)=>Number(s.size)>=canvas.height*.08&&/\d/.test(s.text??''));
  const kind=chart?'chart':table||layout.slots?.some((s:any)=>s.cell)?'table':photo?'figure':metric?'metrics':'editorial';
  const visualSide=side((chart??table??photo)?.box,canvas.width),textSide=visualSide==='left'?'right':visualSide==='right'?'left':'full';
  return {kind,visualSide,textSide,structure:['left','right'].includes(visualSide)?'split':'full',confidence:.5,origin:'native'};
}

/** Select by meaning before approval; never reshuffle a user's approved plan.
 * Variety is a tie-breaker, not a reason to use a cover or distort statistics. */
export function matchPlanConcepts(analysis:any,slides:any[]){
  const imported=new Set(analysis.htmlTemplate?.layoutIds??analysis.layouts.map((l:any)=>l.id));
  const candidates=(analysis.layouts??[]).filter((l:any)=>l.usable&&imported.has(l.id)&&l.htmlRole==='content'&&!l.derivedMediaKind&&!isTemplateUtilityLayout(l));
  if(!candidates.length)return;
  const used=new Map<string,number>();
  for(const [index,slide] of slides.entries()){
    const current=analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId);
    if(index===0||current?.htmlRole!=='content')continue;
    const requested=slide.sourceImageIds?.length||slide.images?.length?'figure':slide.visualPlan?.kind==='diagram'?'process':slide.visualPlan?.kind==='text'?'editorial':slide.visualPlan?.kind??'editorial';
    const hasFigure=(slide.sourceImageIds?.length??0)+(slide.images?.length??0);
    let pool=candidates.filter((l:any)=>!hasFigure||(l.imageSlots??[]).filter((s:any)=>!s.protected&&!s.requiresOpaque&&!furniture.has(s.sourceRole)).length>=hasFigure);
    if(!hasFigure){
      // Some templates bake numbered diagrams into an inherited full-slide
      // image. Their transparent slide text boxes are not editable artwork.
      // Compose that concept on a clear theme surface instead of overpainting
      // immutable sample numbers. Real native diagrams remain eligible.
      const clean=pool.filter((l:any)=>!l.htmlSource||!['process','comparison'].includes(sourceSlideConcept(l,analysis).kind)||
        (l.sourceObjects??[]).some((o:any)=>!furniture.has(o.role)&&(['chart','table','picture','connector','line'].includes(o.kind)||o.fill?.color)));
      if(clean.length)pool=clean;
    }
    const score=(l:any)=>{const concept=sourceSlideConcept(l,analysis);return (concept.kind===requested?12:requested==='chart'&&['table','metrics'].includes(concept.kind)?4:0)+
      // The planner has seen the actual source design. Keep its compatible
      // choice, including filled comparison/process hosts for semantic copy,
      // instead of always preferring a large empty prose plane.
      (l.id===current?.id&&(concept.kind===requested||requested==='editorial'&&['editorial','comparison','process'].includes(concept.kind))?14:l.id===current?.id?2:0)-Math.min(3,used.get(l.id)??0)*1.3-(slides[index-1]?.sourceLayoutId===l.id?2:0);};
    const selected=[...pool].sort((a,b)=>score(b)-score(a)||a.index-b.index)[0];
    if(selected)slide.sourceLayoutId=selected.id;
    used.set(slide.sourceLayoutId,(used.get(slide.sourceLayoutId)??0)+1);
  }
}

export const slideConceptVisionPrompt=`Also return concept:{kind:"editorial"|"figure"|"chart"|"table"|"metrics"|"process"|"comparison",visualSide:"left"|"right"|"center"|"full"|"none",textSide:"left"|"right"|"center"|"full"|"none",structure:"split"|"columns"|"stack"|"full",confidence:0..1} inside EACH layout item. Classify the CONTENT's actual purpose and rough visual/text balance, separately from cover/closing/section role. A picture of a statistical chart is chart, not a photograph. A radial process is process, not a pie chart. Header logos and edge decorations do not count as content pictures. This semantic type survives removal of old sample words and furniture and guides the new local composition. Do not turn covers or closing slides into content.`;
