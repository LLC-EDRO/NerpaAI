import sharp from 'sharp';
import {join} from 'node:path';
import {chartStyleVersion,type SourceChartStyle} from './chart-style.js';

export async function verifySourceChartGradients(analysis:any,folder:string){
  if(analysis.htmlChartGradientVersion===chartStyleVersion)return;
  for(const source of analysis.layouts.filter((l:any)=>!l.derivedMediaKind&&l.htmlChartStyle)){
    source.htmlChartStyle=await verifyBarGradient(source.htmlChartStyle,join(folder,'previews',`slide-${source.index}.png`)).catch(()=>source.htmlChartStyle);
  }
  for(const layout of analysis.layouts.filter((l:any)=>l.derivedSourceLayoutId)){
    const source=analysis.layouts.find((l:any)=>l.id===layout.derivedSourceLayoutId);
    if(source?.htmlChartStyle)layout.htmlChartStyle=source.htmlChartStyle;
  }
  analysis.htmlChartGradientVersion=chartStyleVersion;
}

/** Vision occasionally reverses stop order. Verify only an unambiguous
 * vertical bar fade against long coloured runs in the actual source pixels.
 * Never read heights as values, and abstain on photos/short/ambiguous runs. */
export async function verifyBarGradient(style:SourceChartStyle,path:string):Promise<SourceChartStyle>{
  if(style.type!=='bar'||!style.fills?.length||style.fills.some(fill=>Math.abs(Math.sin(fill.angle*Math.PI/180))<.95))return style;
  const {data,info}=await sharp(path).resize({width:700,withoutEnlargement:true}).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const pixel=(x:number,y:number)=>[0,1,2].map(c=>data[(y*info.width+x)*info.channels+c]!);
  const region=style.sourceRegion??{x:0,y:180,w:1000,h:700};
  const x0=Math.max(0,Math.floor(region.x*info.width/1000)),x1=Math.min(info.width,Math.ceil((region.x+region.w)*info.width/1000));
  const y0=Math.max(0,Math.floor(region.y*info.height/1000)),y1=Math.min(info.height,Math.ceil((region.y+region.h)*info.height/1000));
  const rgb=(hex:string)=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  const chroma=(p:number[])=>{const low=Math.min(...p);return p.map(v=>v-low);};
  const palette=style.palette.map(rgb).map(chroma).filter(p=>Math.max(...p)>40);
  const colored=(p:number[])=>{const c=chroma(p),norm=Math.hypot(...c);return norm>18&&palette.some(q=>c.reduce((sum,v,i)=>sum+v*q[i]!,0)/norm/Math.hypot(...q)>.97);};
  const differences:number[]=[];let backgroundSamples:number[]=[];
  for(let x=x0;x<x1;x+=3){
    let start=-1;
    for(let y=y0;y<=y1;y++){
      const yes=y<y1&&colored(pixel(x,y));
      if(yes&&start<0)start=y;
      if(!yes&&start>=0){
        const length=y-start;
        if(length>info.height*.08){
          const a=pixel(x,start+Math.floor(length*.2)),b=pixel(x,start+Math.floor(length*.8));
          differences.push(a.reduce((s,v)=>s+v,0)-b.reduce((s,v)=>s+v,0));
          backgroundSamples.push(...pixel(Math.max(0,x-2),Math.min(info.height-1,y+2)));
        }start=-1;
      }
    }
  }
  if(differences.length<8)return style;
  differences.sort((a,b)=>a-b);backgroundSamples.sort((a,b)=>a-b);
  const actual=differences[Math.floor(differences.length/2)]!,background=backgroundSamples[Math.floor(backgroundSamples.length/2)]!;
  const expected=style.fills.map(fill=>{
    const ends=[fill.stops[0]!,fill.stops.at(-1)!].map(stop=>rgb(stop.color).reduce((sum,v)=>sum+v*(stop.opacity??1)+background*(1-(stop.opacity??1)),0));
    return (ends[0]!-ends[1]!)*Math.sign(Math.sin(fill.angle*Math.PI/180));
  });
  const direction=expected.reduce((a,b)=>a+b,0)/expected.length;
  if(Math.abs(actual)<35||Math.abs(direction)<35||actual*direction>=0)return style;
  return {...style,fills:style.fills.map(fill=>({...fill,angle:(fill.angle+180)%360}))};
}
