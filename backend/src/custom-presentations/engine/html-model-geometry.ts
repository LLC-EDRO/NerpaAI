/** The browser is 96dpi, PowerPoint geometry is 72pt/in. Keep the model in
 * ordinary CSS pixels throughout; native points are an export boundary only. */
const px=(value:number)=>Math.round(value*4/3*10)/10;
export const cssCanvas=(analysis:{width:number;height:number})=>({width:px(analysis.width),height:px(analysis.height),units:'CSS px at 96dpi'});
const rect=(b:any)=>b?{...b,x:px(b.x),y:px(b.y),w:px(b.w),h:px(b.h)}:b;
export function cssSourceDesign(source:any,compact=false){
 const anchor=(a:any)=>({...a,box:rect(a.box),...(a.size?{size:px(a.size)}:{}),
   ...(a.container?{container:{...a.container,box:rect(a.container.box),innerBox:rect(a.container.innerBox)}}:{})});
  const result={...source,coordinateSpace:'CSS pixels at 96dpi; all boxes and font sizes below use px',canvas:cssCanvas(source.canvas),
   ...(source.title?{title:anchor(source.title)}:{}),textAnchors:source.textAnchors.map(anchor),
   artwork:source.artwork.map(anchor),photoFrames:source.photoFrames.map(anchor),dataFrames:source.dataFrames.map(anchor),
   editableShapes:(source.editableShapes??[]).map(anchor),
   ...(source.unsafeTextAnchors?{unsafeTextAnchors:source.unsafeTextAnchors.map(anchor)}:{}),
   ...(source.density?{density:{...source.density,minBodyFont:typeof source.density.minBodyFont==='number'?px(source.density.minBodyFont):null}}:{}),
   availableSurfaces:(source.availableSurfaces??[]).map(rect)};
  if(compact&&result.sourceHtml){
    const {canvas,coordinateSpace,contract,textRegions,nativeArt,...receipt}=result.sourceHtml;
    // DOM inline styles + textAnchors already carry geometry and typography.
    // Keep paragraph metadata, grouping and the exact DOM without sending a
    // third full copy of the same frame definitions.
    result.sourceHtml={...receipt,...(nativeArt?{nativeArt:{objects:nativeArt.objects?.map(({shapeId,kind,editable}:any)=>({shapeId,kind,editable})),unsupported:nativeArt.unsupported}}:{}),paragraphStyles:(textRegions??[]).map((r:any)=>({shapeId:r.shapeId,paragraphs:r.paragraphs??[],...(r.textStyles?{textStyles:r.textStyles}:{}),...(r.textBox?{textBox:r.textBox}:{} )}))};
    if(source.generationMode==='style-stencils'&&source.role==='content'&&source.compositionPolicy!=='source-first'){
      // This is ONE selected, already cleared source DOM, not the entire deck.
      // It grounds the model's local concept and typography. Large native
      // artwork stays referenced by IDs rather than duplicated SVG paths.
      result.sourceHtml={version:receipt.version,digest:receipt.digest,html:receipt.html,nativeArt:result.sourceHtml.nativeArt,unsupported:receipt.unsupported};
      result.textAnchors=result.textAnchors.filter((anchor:any)=>anchor.shapeId===source.title?.shapeId);
    }
  }
  return result;
}
export function cssDesignBounds(bounds:any){
 if(!bounds)return bounds;
 return {...bounds,title:rect(bounds.title),content:bounds.content?.map(rect),surfaces:bounds.surfaces?.map(rect),safeSurfaces:bounds.safeSurfaces?.map(rect)};
}
export const cssText=(item:any)=>({...rect(item),...(item.size?{size:px(item.size)}:{}),...(item.inkRects?{inkRects:item.inkRects.map(rect)}:{})});
export function cssMeasuredScene(scene:any,compact=false){
 const text=(item:any)=>compact?cssText(Object.fromEntries(['key','x','y','w','h','size','font','color','bold','align','lineHeight','sourceShapeId','inkRects','overflow'].filter(k=>item[k]!==undefined).map(k=>[k,item[k]]))):cssText(item);
 return scene?{texts:scene.texts?.map(text),cells:scene.cells?.map(text),table:scene.table?{...(compact?{}:scene.table),box:rect(scene.table.box)}:null,
   chart:scene.chart?{...(compact?{}:scene.chart),box:rect(scene.chart.box)}:null,images:scene.images?.map((i:any)=>({...rect(i),...(i.contentBox?{contentBox:rect(i.contentBox)}:{})})),designBounds:cssDesignBounds(scene.designBounds)}:undefined;
}
