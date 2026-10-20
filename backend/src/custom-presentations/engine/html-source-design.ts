import {standaloneSourceStatistic} from './html-source-statistics.js';
import {sourceStyleSystem} from './style-stencils.js';
import {sourceSlideConcept} from './slide-concept.js';
/** Original native geometry is the composition reference, not a new layout kit.
 * All coordinates are points in the source canvas, including grouped labels. */
export function sourceHtmlDesign(analysis:any,layout:any){
  // Refreshed native receipts also repair older parser metadata that confused
  // a shape's border color with its transparent fill.
  const paints=new Map<number,string|null>((layout.htmlSource?.objectPaints??[]).map((p:any)=>[p.shapeId,p.fill]));
  const sourceObjects=(layout.sourceObjects??[]).map((s:any)=>paints.has(s.shapeId)?{...s,fill:paints.get(s.shapeId)?{color:paints.get(s.shapeId)}:null}:s);
  const width=analysis.width,height=analysis.height,area=width*height;
  const round=(value:number)=>Math.round(value*10)/10;
  const box=(value:any)=>({x:round(value.x),y:round(value.y),w:round(value.w),h:round(value.h)});
  const photoIds=new Set((layout.htmlSource?.photoFrames??[]).map((r:any)=>r.shapeId));
  const content=(layout.slots??[]).filter((s:any)=>!s.cell&&!photoIds.has(s.shapeId)&&!layout.htmlRemoveShapeIds?.includes(s.shapeId)&&!layout.htmlPreserveShapeIds?.includes(s.shapeId)&&!['brand','logo','page_number'].includes(s.role)&&
    (s.role!=='footer'||s.y<height*.94)&&s.w>0&&s.h>0);
  const main=content.filter((s:any)=>s.role!=='footer');
  const titles=main.filter((s:any)=>['title','header'].includes(s.role));
  const candidate=main.find((s:any)=>s.shapeId===layout.htmlTitleShapeId)??[...(titles.length?titles:main)].sort((a:any,b:any)=>(b.size??0)-(a.size??0))[0];
  const headingAbsent=layout.htmlTitleShapeId===null||layout.htmlRole==='content'&&standaloneSourceStatistic(candidate?.text);
  const title=headingAbsent?undefined:candidate;
  const anchors=content.map((s:any)=>{
    const region=layout.htmlSource?.textRegions?.find((r:any)=>r.shapeId===s.shapeId),container=region?.container;
    const nativeBox=(b:any)=>Object.fromEntries(['x','y','w','h'].map(k=>[k,round(b[k]*.75)]));
    const frame=region?.textBox??region?.box??{w:s.w*4/3,h:s.h*4/3};
    const readableFontPx=Math.max(21.4,region?.textStyles?.body?.size??(s.size??18)*4/3);
    const innerWidth=Math.max(1,frame.w-(region?.insets?.[1]??0)-(region?.insets?.[3]??0));
    const innerHeight=Math.max(1,frame.h-(region?.insets?.[0]??0)-(region?.insets?.[2]??0));
    // The source may use a 9–12pt sample caption, while generation deliberately
    // keeps explanations readable at >=16pt. Area/native-font estimates gave
    // the model permission for 30 words where only about nine actually fit.
    const lines=Math.floor(innerHeight/(readableFontPx*1.3)),characters=Math.floor(innerWidth/(readableFontPx*.56))*lines;
    return {shapeId:s.shapeId,role:headingAbsent&&['title','header'].includes(s.role)?standaloneSourceStatistic(s.text)?'metric':'label':region?.role??s.role,box:region?.textBox?nativeBox(region.textBox):box(s),font:s.font,size:s.size,
      color:s.color,bold:!!s.bold,align:s.align??'left',verticalAlign:s.verticalAlign??'top',characters:String(s.text??'').length,
      maxWords:Math.max(1,Math.floor(characters/7)),copyFit:{fontPx:round(readableFontPx),lines,characters,requiresLocalReflow:lines<1},
      ...(container?{container:{...container,box:nativeBox(container.box),innerBox:nativeBox(container.innerBox)}}:{})};
  });
  const replacedPhotos=new Set((layout.imageSlots??[]).filter((s:any)=>!s.protected&&!s.requiresOpaque).map((s:any)=>s.shapeId));
  const removed=new Set(layout.htmlRemoveShapeIds??[]),nativePaint=new Set([...(layout.htmlSource?.nativeArt?.objects??[]),...(layout.htmlSource?.nativeArt?.unsupported??[])].map((s:any)=>s.shapeId));
  const painted=(s:any,seen=new Set<number>()):boolean=>{
    if(replacedPhotos.has(s.shapeId)||removed.has(s.shapeId)||seen.has(s.shapeId)||['chart','table'].includes(s.kind))return false;
    if(s.kind==='group'){const next=new Set([...seen,s.shapeId]),children=sourceObjects.filter((c:any)=>c.parentShapeId===s.shapeId);return children.length?children.some((c:any)=>painted(c,next)):nativePaint.has(s.shapeId)||!layout.htmlSource;}
    return s.kind==='picture'||s.role==='icon'||!!s.fill?.color||!!s.line?.color||nativePaint.has(s.shapeId)||!layout.htmlSource&&!('fill' in s)&&!('line' in s);
  };
  const textSurface=(s:any)=>{
    const rgb=String(s.fill?.color??'').match(/^#([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i)?.slice(1).map((v:string)=>parseInt(v,16));
    return s.kind==='shape'&&rgb&&(Math.min(...rgb)>220&&Math.max(...rgb)-Math.min(...rgb)<20||s.box.w/s.box.h>=1.6)&&s.box.w*s.box.h>area*.035&&
      content.some((a:any)=>a.x>=s.box.x&&a.y>=s.box.y&&a.x+a.w<=s.box.x+s.box.w+1&&a.y+a.h<=s.box.y+s.box.h+1);
  };
  const artwork=sourceObjects.filter((s:any)=>!s.hidden&&!s.hasText&&s.box&&painted(s)&&
    !textSurface(s)&&
    !['background','background_image','page_number'].includes(s.role)&&(s.role==='icon'||s.box.w*s.box.h>=area*.005)&&
    !(s.box.w>=width*.9&&s.box.h>=height*.9)&&!layout.htmlRemoveShapeIds?.includes(s.shapeId))
    .map((s:any)=>({shapeId:s.shapeId,kind:s.kind,role:s.role,box:box(s.box)}));
  for(const r of layout.reservedRegions??[])if(['brand','logo'].includes(r.role)&&!artwork.some((a:any)=>a.shapeId===r.shapeId))
    artwork.push({shapeId:r.shapeId,kind:r.role,role:r.role,box:box(r.box)});
  const photos=(layout.imageSlots??[]).filter((s:any)=>s.box&&!s.protected&&!['brand','logo','background','background_image'].includes(s.sourceRole))
    .map((s:any)=>({shapeId:s.shapeId,box:box(s.box),fit:s.fit??'cover'}));
  const frames=sourceObjects.filter((s:any)=>['chart','table'].includes(s.kind)&&s.box)
    .map((s:any)=>({shapeId:s.shapeId,kind:s.kind,box:box(s.box)}));
  frames.push(...(layout.htmlSampleDataFrames??[]).map((s:any)=>({shapeId:s.shapeId,kind:s.kind,type:s.type,sampleDataRemoved:true,box:box(s.box)})));
  const body=anchors.filter((s:any)=>s.shapeId!==title?.shapeId);
  const protectedIds=new Set([...(layout.htmlPreserveShapeIds??[]),...(layout.reservedRegions??[]).filter((s:any)=>['brand','logo','chart','table'].includes(s.role)).map((s:any)=>s.shapeId)]);
  const editableShapes=layout.htmlRole==='content'?sourceObjects.filter((s:any)=>['shape','picture','connector','line'].includes(s.kind)&&s.canRemove&&(s.fill?.color||s.line?.color||['picture','connector','line'].includes(s.kind))&&s.box&&
    s.shapeId!==title?.shapeId&&!removed.has(s.shapeId)&&!protectedIds.has(s.shapeId)&&!['brand','logo','footer','page_number','title','header'].includes(s.role)&&
    s.box.y>=Math.max(height*.12,title?title.y+title.h-2:0)&&s.box.w*s.box.h<area*.4)
    .map((s:any)=>({shapeId:s.shapeId,kind:s.kind,box:box(s.box),fill:s.fill?.color,role:s.role,hasText:!!s.hasText,allowedActions:s.kind==='picture'?['remove']:['remove','replace']})):[];
  const inkArea=content.reduce((sum:number,s:any)=>sum+Math.min(s.w*s.h,String(s.text??'').length*(s.size??18)**2*.48),0);
  const result={coordinateSpace:'source canvas points',canvas:{width,height},role:layout.htmlRole??'content',concept:sourceSlideConcept(layout,analysis),headingAbsent,
    headingAuthority:headingAbsent?'absent':Number.isInteger(layout.htmlTitleShapeId)?'vision':'inferred',
    ...(title?{title:{shapeId:title.shapeId,role:Number.isInteger(layout.htmlTitleShapeId)?'title':title.role,box:box(title),font:title.font,size:title.size,color:title.color,align:title.align??'left'}}:{}),
    textAnchors:anchors,artwork,photoFrames:photos,dataFrames:frames,editableShapes,
    ...(layout.htmlSource?{sourceHtml:layout.htmlSource}:{}),
    unsafeTextAnchors:layout.htmlUnsafeTextAnchors??[],
    availableSurfaces:layout.htmlSafeSurfaces??[],
    density:{textInkFraction:Math.round(1000*Math.min(1,inkArea/area))/1000,
      bodyBoxesFraction:Math.round(1000*Math.min(1,body.reduce((sum:number,s:any)=>sum+s.box.w*s.box.h,0)/area))/1000,
      minBodyFont:body.length?Math.min(...body.map((s:any)=>s.size??18)):null},
  };
  if(layout.htmlGenerationMode!=='style-stencils')return result;
  const styleSystem=sourceStyleSystem(analysis,layout,result);
  if(result.role!=='content')return {...result,generationMode:'style-stencils',styleSystem};
  if(layout.htmlCompositionPolicy==='source-first')return {...result,generationMode:'style-stencils',compositionPolicy:'source-first',styleSystem};
  return {...result,generationMode:'style-stencils',styleSystem,headingAbsent:false,headingAuthority:'style',
    title:{shapeId:title?.shapeId??0,role:'title',box:Object.fromEntries(Object.entries(styleSystem.title).map(([key,value])=>[key,(value as number)*.75])) as {x:number;y:number;w:number;h:number},font:styleSystem.headingFont,size:styleSystem.headingSize*.75,color:styleSystem.headingInk,align:'left'}};
}
