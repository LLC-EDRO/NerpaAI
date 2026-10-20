import {z} from 'zod';

// Vision coordinates use the same 0..1000 canvas at any source aspect ratio.
// The model chooses the design; these checks only enforce its spatial contract.
export const htmlRectSchema=z.object({x:z.number().finite().min(0),y:z.number().finite().min(0),
  w:z.number().finite().min(20),h:z.number().finite().min(15)}).strict()
  .refine(b=>b.x+b.w<=1000&&b.y+b.h<=1000,'outside_slide');
export const htmlCompositionSchema=z.enum(['auto','stack','cards','columns','split']);
export const htmlDesignSchema=z.object({canvas:z.enum(['panels','open']),title:htmlRectSchema,
  surfaces:z.array(htmlRectSchema).min(1).max(4).optional(),
  content:z.array(htmlRectSchema).max(4),variants:z.array(htmlCompositionSchema.exclude(['auto'])).min(1).max(4)}).strict()
  .refine(d=>d.content.every(b=>!overlaps(b,d.title))&&d.content.every((b,i)=>d.content.slice(i+1).every(a=>!overlaps(a,b))),'overlapping_zones')
  .refine(d=>!d.surfaces||[d.title,...d.content].every(b=>d.surfaces!.some(a=>insideHtmlRect(b,a))),'outside_panel');
export type HtmlDesign=z.infer<typeof htmlDesignSchema>;
/** Use the measured renderer's grounded panels for review, not stale model bounds. */
export function measuredHtmlDesign(bounds:any,base:HtmlDesign|undefined,width:number,height:number,role:string):HtmlDesign|undefined{
  if(!bounds||!base)return base;
  const rect=(b:any)=>({x:b.x/width*1000,y:b.y/height*1000,w:b.w/width*1000,h:b.h/height*1000});
  return readHtmlDesign({...base,title:rect(bounds.title),content:bounds.content.map(rect),
    ...(bounds.surfaces?.length?{surfaces:bounds.surfaces.map(rect)}:{})},role);
}
type Rect=z.infer<typeof htmlRectSchema>;
const overlaps=(a:Rect,b:Rect)=>Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)+1&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y)+1;
/** A model may let the top edge of a body zone touch a title. Subtract that
 * overlap inside its proposed panel; never manufacture a larger content area. */
export function readHtmlDesign(raw:unknown,role:string):HtmlDesign|undefined{
  if(!raw||typeof raw!=='object')return;
  const value=structuredClone(raw) as any;
  if(Array.isArray(value.content)&&htmlRectSchema.safeParse(value.title).success){
    value.content=value.content.map((area:unknown)=>{
      const parsed=htmlRectSchema.safeParse(area);if(!parsed.success||!overlaps(parsed.data,value.title))return area;
      const b=parsed.data,t=value.title,bottom=b.y+b.h;
      if(b.y>=t.y&&b.y<t.y+t.h&&bottom>t.y+t.h+60){const y=t.y+t.h+8;return {...b,y,h:bottom-y};}
      return area;
    });
  }
  const result=htmlDesignSchema.safeParse(value);
  return result.success&&(role!=='content'||result.data.content.length)?result.data:undefined;
}
export const insideHtmlRect=(a:Rect,b:Rect)=>a.x>=b.x-.1&&a.y>=b.y-.1&&a.x+a.w<=b.x+b.w+.1&&a.y+a.h<=b.y+b.h+.1;
export const htmlDesignVisionPrompt=`Read the ORIGINAL slide and extract its reusable visual style. Identify 1–4 LARGE actual safe flat/white content surfaces, independently of old tiny sample text boxes. Keep separate white panels separate, exclude patterned borders, logos and protected header artwork. Identify the real original heading anchor and rough photo/text arrangement. On CONTENT slides preserve suitable original panels, filled text hosts, columns and diagram relationships. Identify their actual reusable content regions. Local repair may enlarge a defective tiny frame; do not flatten every source composition into one generic body. Keep header/logo/background style and make the body surface generous enough for readable new copy or data. On COVER/CLOSING/SECTION preserve the actual unique title/subtitle/hero composition; content:[] is valid for a title-only terminal. Do not turn an actual cover into a content slide. Return design:{canvas:"panels"|"open",surfaces:[{x,y,w,h}],title:{x,y,w,h},content:[{x,y,w,h}],variants:["stack"|"columns"|"split"|"cards"]}. Every rectangle is normalized to 0..1000 over the original slide and lies inside a real safe surface. Header and body do not overlap. Return geometry for every supplied layout.`;
