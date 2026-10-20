/** Some templates draw charts as rectangles instead of native c:chart data.
 * Recognize only a repeated bar series with a shared baseline AND numeric axis
 * labels. Rings, timelines, icon columns and ordinary panels do not qualify. */
export function drawnSampleChart(layout:any,width:number,height:number){
 const objects:any[]=layout.sourceObjects??[];
 const bars=objects.filter(o=>o.kind==='shape'&&!o.hasText&&o.box&&o.fill?.color&&
   o.box.w>2&&o.box.w<width*.045&&o.box.h>height*.08&&o.box.h>o.box.w*2);
 for(const candidate of bars){
   const aligned=bars.filter(o=>Math.abs(o.box.y+o.box.h-candidate.box.y-candidate.box.h)<height*.012);
   if(aligned.length<6||new Set(aligned.map(o=>Math.round(o.box.h/(height*.04)))).size<3)continue;
   const left=Math.min(...aligned.map(o=>o.box.x)),right=Math.max(...aligned.map(o=>o.box.x+o.box.w));
   const top=Math.min(...aligned.map(o=>o.box.y)),bottom=Math.max(...aligned.map(o=>o.box.y+o.box.h));
   const axis=(layout.slots??[]).filter((s:any)=>/^\d+(?:[.,]\d+)?%?$/.test(String(s.text??'').trim())&&s.x<left&&s.x+s.w>left-width*.15&&s.y>=top-height*.15&&s.y<=bottom+height*.03);
   if(axis.length<3||right-left<width*.2)continue;
   const x=Math.max(0,Math.min(left-width*.04,...axis.map((s:any)=>s.x))),y=Math.max(0,Math.min(top-height*.04,...axis.map((s:any)=>s.y)));
   const box={x,y,w:Math.min(width,right+width*.04)-x,h:Math.min(height,bottom+height*.18)-y};
   const contained=(o:any)=>o.box&&o.box.x>=x-1&&o.box.y>=y-1&&o.box.x+o.box.w<=x+box.w+1&&o.box.y+o.box.h<=y+box.h+1;
   const shapeIds=objects.filter(o=>contained(o)&&!['brand','logo','background','background_image'].includes(o.role)&&
     ['shape','connector','group'].includes(o.kind)&&(!o.hasText||['label','footer'].includes(o.role))).map(o=>o.shapeId);
   return {box,shapeIds};
 }
}
export function clearDrawnSampleData(analysis:any){
 for(const layout of analysis.layouts??[]){
   const profile=layout.htmlChartStyle,objects:any[]=layout.sourceObjects??[];
   if(['raster','slide-preview'].includes(profile?.sourceKind)&&profile.type==='bar'&&profile.confidence>=.7){
     // A chart can be exported as many separate overlapping picture bars.
     // Vision may name just one series; retain the style but clear every bar
     // sharing its verified baseline, rather than repairing old data at render.
     const narrow=objects.filter(o=>o.kind==='picture'&&o.box&&!['brand','logo','icon','background','background_image'].includes(o.role)&&o.box.w<analysis.width*.1&&o.box.h>analysis.height*.08&&o.box.h>o.box.w*1.5);
     const reviewed=new Set([...(profile.sourceShapeIds??[]),...(layout.htmlRemoveShapeIds??[])]);
     const seeds=narrow.filter(o=>reviewed.has(o.shapeId));
     if(seeds.length>=3){
       const baseline=seeds[0].box.y+seeds[0].box.h;
       const aligned=narrow.filter(o=>Math.abs(o.box.y+o.box.h-baseline)<analysis.height*.012);
       const left=Math.min(...seeds.map(o=>o.box.x)),right=Math.max(...seeds.map(o=>o.box.x+o.box.w));
       if(seeds.every(o=>Math.abs(o.box.y+o.box.h-baseline)<analysis.height*.012)&&right-left>analysis.width*.2){
         const component=[...seeds];
         for(let changed=true;changed;){
           changed=false;
           for(const item of aligned)if(!component.includes(item)&&component.some(peer=>Math.max(0,Math.max(item.box.x,peer.box.x)-Math.min(item.box.x+item.box.w,peer.box.x+peer.box.w))<=analysis.width*.04)){
             component.push(item);changed=true;
           }
         }
         const ids=component.map(o=>o.shapeId);
         if(profile.sourceKind==='raster')profile.sourceShapeIds=[...new Set([...(profile.sourceShapeIds??[]),...ids])];
         layout.htmlSampleDataShapeIds=[...new Set([...(layout.htmlSampleDataShapeIds??[]),...ids])];
         layout.htmlRemoveShapeIds=[...new Set([...(layout.htmlRemoveShapeIds??[]),...ids])];
       }
     }
   }
   const data=drawnSampleChart(layout,analysis.width,analysis.height);if(!data)continue;
   layout.htmlSampleDataFrames=[{kind:'chart',type:'bar',box:data.box}];
   layout.htmlSampleDataShapeIds=data.shapeIds;
   layout.htmlRemoveShapeIds=[...new Set([...(layout.htmlRemoveShapeIds??[]),...data.shapeIds])];
 }
}
