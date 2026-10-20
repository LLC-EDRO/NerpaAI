import {z} from 'zod';
import {dataChartKinds} from './data-contract.js';

export const chartStyleVersion=3;
const hex=z.string().regex(/^#[a-f0-9]{6}$/i);
const chartStyleSchema=z.object({
  sourceKind:z.enum(['raster','native','slide-preview']),sourceShapeIds:z.array(z.number().int().positive()).max(8),
  sourceRegion:z.object({x:z.number().min(0).max(1000),y:z.number().min(0).max(1000),w:z.number().positive().max(1000),h:z.number().positive().max(1000)}).optional(),
  type:z.enum(dataChartKinds),palette:z.array(z.string().regex(/^#[a-f0-9]{6}$/i)).min(1).max(8),
  font:z.string().trim().min(1).max(100).optional(),ink:z.string().regex(/^#[a-f0-9]{6}$/i).optional(),
  grid:z.enum(['none','horizontal','vertical','both']).default('horizontal'),
  legend:z.enum(['none','top','bottom','right']).default('bottom'),
  axes:z.boolean().default(true),showValues:z.boolean().default(true),markers:z.boolean().default(true),
  lineWidth:z.number().min(1).max(6).default(2),holeSize:z.number().min(30).max(80).default(58),
  treatment:z.enum(['plain','gradient','soft-area']).default('plain'),
  fills:z.array(z.object({angle:z.number().min(0).max(360),stops:z.array(z.object({offset:z.number().min(0).max(1),color:hex,opacity:z.number().min(0).max(1).optional()})).min(2).max(5)})).max(8).optional(),
  bars:z.object({radius:z.number().min(0).max(24),widthRatio:z.number().min(.2).max(1),overlap:z.number().min(0).max(.8),valuePosition:z.enum(['inside','outside']),highlight:z.enum(['none','max','last']),mutedColor:hex.optional()}).optional(),
  line:z.object({curve:z.enum(['straight','monotone']),areaOpacity:z.number().min(0).max(.5)}).optional(),
  radial:z.object({startAngle:z.number().min(-360).max(360),gap:z.number().min(0).max(6),stroke:hex.optional(),strokeWidth:z.number().min(0).max(3),center:z.enum(['none','total','largest-percent']),labels:z.enum(['none','value','percent'])}).optional(),
  axisLine:z.enum(['none','baseline','both']).optional(),gridOpacity:z.number().min(0).max(.4).optional(),
  legendMarker:z.enum(['line','circle','square']).optional(),
  confidence:z.number().min(0).max(1),
});
export type SourceChartStyle=z.infer<typeof chartStyleSchema>;

/** Vision describes appearance, never hidden observations. Its shape IDs must
 * refer to real charts/pictures on this slide, away from persistent branding. */
export function readSourceChartStyle(raw:unknown,layout:any,canvas?:{width:number;height:number}):SourceChartStyle|undefined{
  const parsed=chartStyleSchema.safeParse(raw);if(!parsed.success||parsed.data.confidence<.65)return;
  const style=parsed.data,protectedIds=new Set([...(layout.htmlChromeShapeIds??[]),...(layout.reservedRegions??[]).filter((item:any)=>['logo','brand','background','footer','page_number'].includes(item.role)).map((item:any)=>item.shapeId)]);
  const ids=style.sourceShapeIds.filter(id=>!protectedIds.has(id)&&(layout.sourceObjects??[]).some((object:any)=>object.shapeId===id&&
    object.kind===(style.sourceKind==='raster'?'picture':'chart')&&!['logo','brand','background','background_image'].includes(object.role)&&
    !(style.sourceKind==='raster'&&canvas&&object.box?.w*object.box?.h>canvas.width*canvas.height*.72)));
  // Whole-slide/inherited raster art can teach STYLE, but must never become a
  // removal ID. Its bounded chart crop is reference-only, not numeric evidence.
  const r=style.sourceRegion;
  const referenceOnly=style.sourceKind==='slide-preview'&&r&&r.x+r.w<=1000&&r.y+r.h<=1000&&r.w*r.h<=650000;
  if(!ids.length&&!referenceOnly)return;
  return {...style,sourceShapeIds:ids,...(style.font?{font:style.font.split(',')[0]!.replace(/["']/g,'').trim()}:{}),palette:[...new Set(style.palette.map(color=>color.toUpperCase()))]};
}

const family=(type:string)=>['pie','donut'].includes(type)?'radial':['bar','bar-horizontal'].includes(type)?'bar':'line';
/** Prefer the selected slide's own grammar when compatible, otherwise a real
 * example of that family. Never borrow a ring's axis rules for a time series. */
export function selectChartStyle(styles:Array<SourceChartStyle&{sourceLayoutId?:string}>,kind:string,localId?:string){
  return [...styles].sort((a,b)=>{
    const score=(s:SourceChartStyle&{sourceLayoutId?:string})=>(s.type===kind?100:family(s.type)===family(kind)?70:0)+(s.sourceLayoutId===localId?10:0)+s.confidence;
    return score(b)-score(a);
  })[0];
}
export function chartStyleLibrary(analysis:any){
  return (analysis.layouts??[]).filter((l:any)=>!l.derivedMediaKind&&l.htmlChartStyle).map((l:any)=>({...l.htmlChartStyle,sourceLayoutId:l.id}));
}

/** Some providers place one optional chart description at the JSON root.
 * Recover it only when its native IDs identify exactly ONE supplied slide. */
export function layoutChartStyle(raw:any,item:any,source:any,batch:any[],canvas:{width:number;height:number}){
  const local=readSourceChartStyle(item.chartStyle,source,canvas);if(local)return local;
  if(!raw.chartStyle)return;
  const matches=batch.flatMap(layout=>{const style=readSourceChartStyle(raw.chartStyle,layout,canvas);return style?[{id:layout.id,style}]:[];});
  return matches.length===1&&matches[0]!.id===source.id?matches[0]!.style:undefined;
}

export const chartStyleVisionPrompt=`Inside EACH layouts item, also return its own chartStyle:null OR a style description for one actual statistical chart visible in THAT slide, including a chart embedded as a picture. Never put chartStyle, chromeShapeIds or contentShapeIds at the JSON root: {sourceKind:"raster"|"native",sourceShapeIds:[EXACT supplied chart/picture IDs],type:"bar"|"bar-horizontal"|"line"|"pie"|"donut"|"xy",palette:["#RRGGBB"],ink:"#RRGGBB",font,grid:"none"|"horizontal"|"vertical"|"both",legend:"none"|"top"|"bottom"|"right",axes:boolean,showValues:boolean,markers:boolean,lineWidth:1..6,holeSize:30..80,treatment:"plain"|"gradient"|"soft-area",confidence:0..1}. Capture series/slice colours in their order, typography and visible axis/grid/legend treatment. Do not classify photos, logos, radial process diagrams or decorative backgrounds as charts. Never delete a whole-slide bitmap including branding; use a bounded slide-preview style reference instead. This is a STYLE reference: do not infer, digitize or invent sample values from bar heights, blurry labels or pixels. Exact observations for the new chart must come from the user's supplied data or independently readable evidence. Appearance fidelity comes first: rebuild new exact data in HTML/SVG and export its verified picture when a native chart would change the design. Never reuse the old sample bitmap or numbers. Also describe these OPTIONAL visual grammar fields when visible, with numeric values in source slide points: fills:[{angle:0..360 (0=left-to-right,90=top-to-bottom),stops:[{offset:0..1,color:"#RRGGBB",opacity:0..1}]}] in series/slice order, bars:{radius:0..24,widthRatio:0.2..1,overlap:0..0.8,valuePosition:"inside"|"outside",highlight:"none"|"max"|"last",mutedColor:"#RRGGBB"}, line:{curve:"straight"|"monotone",areaOpacity:0..0.5}, radial:{startAngle:-360..360,gap:0..6,stroke:"#RRGGBB",strokeWidth:0..3,center:"none"|"total"|"largest-percent",labels:"none"|"value"|"percent"}, axisLine:"none"|"baseline"|"both",gridOpacity:0..0.4,legendMarker:"line"|"circle"|"square". Match the actual gradient stops (including dark fades), rounded bars, highlight/muted bars, ring thickness, segment labels, and minimal axes. Smooth source curves use monotone interpolation through exact observations, never fabricated points. A full-slide/inherited image may be a STYLE-only reference: sourceKind:"slide-preview",sourceShapeIds:[],sourceRegion:{x,y,w,h} around its chart in 0..1000 coordinates, excluding branding. This never permits deleting the full slide image. It is not a data source. Do not output prose or copy sample values.`;
