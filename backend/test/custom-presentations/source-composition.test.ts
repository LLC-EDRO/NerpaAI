import test from 'node:test';
import assert from 'node:assert/strict';
import {load} from 'cheerio';
import {realizeSourceComposition} from '../../src/custom-presentations/engine/source-composition.js';
import {prepareStyleStencils} from '../../src/custom-presentations/engine/style-stencils.js';
import {normalizeHtmlSourceBindings} from '../../src/custom-presentations/engine/html-bindings.js';
import {missingHtmlBindings} from '../../src/custom-presentations/engine/html-author-batches.js';

const slide=(extra:any={})=>({index:0,title:'Сравнение подходов',paragraphs:[],cards:[{title:'Первый подход',body:'Содержательное объяснение.'},{title:'Второй подход',body:'Другой смысловой шаг.'}],steps:[],metrics:[],chart:null,table:null,takeaway:'',notes:'',speech:'',omitSourceIconIds:[],sourceShapeEdits:[],...extra});
const region=(shapeId:number,x:number)=>({shapeId,role:shapeId===1?'title':'body',box:{x,y:shapeId===1?20:150,w:shapeId===1?800:340,h:shapeId===1?60:240},size:shapeId===1?44:24,color:'#FFFFFF',container:shapeId===1?undefined:{innerBox:{x:x+12,y:162,w:316,h:216}}});
const source=()=>({role:'content',title:{shapeId:1},photoFrames:[],dataFrames:[],sourceHtml:{textRegions:[region(1,40),region(2,40),region(3,420)],html:'<section class="source-slide"><div data-source-native-layer="true"></div><div data-source-shape="1" style="position:absolute;left:40px;top:20px;width:800px;height:60px;color:#FFFFFF;font-size:44px"><p></p></div><div data-source-shape="2" style="position:absolute;left:40px;top:150px;width:340px;height:240px;color:#FFFFFF"><p></p></div><div data-source-shape="3" style="position:absolute;left:420px;top:150px;width:340px;height:240px;color:#FFFFFF"><p></p></div></section>'}});

test('new semantic pairs fill their real source hosts, retaining frame geometry and typography',()=>{
 const result=realizeSourceComposition(slide({sourceBindings:[{shapeId:2,paths:['cards.1.title','cards.1.body']},{shapeId:3,paths:['cards.0.title','cards.0.body']}]}),source(),0)!;
 const $=load(result.html!);assert.equal(result.stencilId,'source-layout');
 assert.equal($('[data-source-shape="2"] [data-text="cards.1.body"]').length,1);
 assert.equal($('[data-source-shape="3"]').css('left'),'420px');
 assert.equal($('[data-source-shape="1"]').css('font-size'),'44px');assert.equal($('[data-text="title"]').css('font-size'),'inherit');
 assert.equal($('[data-source-native-layer]').length,0,'native paint is not duplicated');
 assert.equal($('[data-text]').length,5);assert.doesNotMatch(result.html!,/Содержательное|Второй подход/,'wording must be bound, never executed as markup');
});
test('unknown shape IDs and duplicated bindings cannot steal text from another source host',()=>{
 const input=slide({sourceBindings:[{shapeId:999,paths:['cards.0.title']},{shapeId:2,paths:['cards.0.title','cards.0.title','notes','cards.999.body']}]}),before=structuredClone(input);
 const result=realizeSourceComposition(input,source(),0)!,$=load(result.html!);
 assert.equal($('[data-text="cards.0.title"]').length,1);assert.equal($('[data-text]').length,5);assert.equal($('[data-source-shape="999"]').length,0);assert.deepEqual(input,before);
});
test('short native captions retain their model-selected host instead of spilling into the final field',()=>{
 const s:any=source();s.sourceHtml.textRegions[1]={...region(2,40),container:undefined,box:{x:40,y:160,w:130,h:15.71}};
 const input=slide({cards:[],paragraphs:['Короткая подпись.','Отдельное пояснение.'],sourceBindings:[{shapeId:2,paths:['paragraphs.0']},{shapeId:3,paths:['paragraphs.1']}]});
 const $=load(realizeSourceComposition(input,s,0)!.html!);
 assert.equal($('[data-source-shape="2"]').attr('data-text'),'paragraphs.0');assert.equal($('[data-source-shape="3"]').attr('data-text'),'paragraphs.1');
});
test('separate heading and description reflow within their existing panel, preserving its artwork and icon',()=>{
 const s:any=source();s.sourceHtml.textRegions=[region(1,40),{...region(2,60),container:undefined,box:{x:60,y:180,w:180,h:17.33}}, {...region(3,60),container:undefined,box:{x:60,y:204,w:180,h:44.96}}];
 s.sourceHtml.textGroups=[{id:'native-pair',headingShapeId:2,bodyShapeId:3,box:{x:60,y:180,w:180,h:68.96}}];
 s.editableShapes=[{shapeId:30,kind:'shape',role:'container',hasText:false,box:{x:30,y:100,w:165,h:230}}];
 const before=structuredClone(s),result=realizeSourceComposition(slide({cards:[{title:'Два слова',body:'Законченное описание смысла этого этапа.'}],sourceBindings:[{shapeId:2,paths:['cards.0.title']},{shapeId:3,paths:['cards.0.body']}]}),s,0)!,$=load(result.html!);
 const flow=$('[data-source-flow="native-pair"]');assert.equal(flow.length,1);assert.ok(parseFloat(flow.css('height')!)>200);
 assert.equal(flow.find('[data-source-shape="2"]').css('height'),'auto');assert.equal(flow.find('[data-source-shape="3"]').css('position'),'relative');
 assert.deepEqual(s,before);assert.deepEqual(missingHtmlBindings(result,s),[]);
});
test('a shallow lead-in and its tall native column share flow without moving the source title',()=>{
 const s:any=source();s.sourceHtml.textRegions=[region(1,40),{...region(2,600),container:undefined,box:{x:600,y:120,w:400,h:25.83}}, {...region(3,600),container:undefined,box:{x:600,y:155.5,w:400,h:390}}];
 const input=slide({cards:[],paragraphs:['Законченное вводное объяснение, которому нужны две строки.','Основное пояснение.'],sourceBindings:[{shapeId:2,paths:['paragraphs.0']},{shapeId:3,paths:['paragraphs.1']}]});
 const result=realizeSourceComposition(input,s,0)!,$=load(result.html!);assert.equal($('[data-source-flow="column-2"]').length,1);
 assert.equal($('[data-source-shape="1"]').css('left'),'40px');assert.equal($('[data-source-shape="2"]').css('height'),'auto');assert.deepEqual(missingHtmlBindings(result,s),[]);
});
test('a measured local CSS repair survives data rebinding and bespoke model HTML is authoritative',()=>{
 const s=source(),first=realizeSourceComposition(slide(),s,0)!;
 const repaired={...first,css:first.css+' [data-source-shape="2"]{font-size:22px}'};
 assert.deepEqual(realizeSourceComposition(repaired,s,0),repaired);
 assert.equal(realizeSourceComposition(slide({stencilId:'source-layout',html:'<main style="display:grid"><p data-text="title"></p></main>'}),s,0),undefined);
});
test('a source-hosted composition passes the older row normalizer without duplicating or rearranging semantic pairs',()=>{
 const s:any=source();s.sourceHtml.textGroups=[{role:'repeated-content',headingShapeId:2,bodyShapeId:3,box:{x:40,y:150,w:340,h:240}}];
 const result=realizeSourceComposition(slide({cards:[{title:'Одна мысль',body:'Одно объяснение'}]}),s,0)!,before=structuredClone(result);
 assert.deepEqual(missingHtmlBindings(result,s),[]);assert.equal(normalizeHtmlSourceBindings(result,s),false);assert.deepEqual(result,before);
 assert.deepEqual(missingHtmlBindings(result,s),[]);
});
test('refreshing a prior blanket-cleanup import restores body paint but still replaces old raster charts',()=>{
 const l:any={htmlRole:'content',htmlTitleShapeId:1,htmlStyleRemoveShapeIds:[2,3,8],htmlRemoveShapeIds:[2,3,8],htmlChartStyle:{sourceShapeIds:[8]},
 sourceObjects:[{shapeId:1,role:'title',box:{y:20}},{shapeId:2,kind:'shape',hasText:true,fill:{color:'#0077FF'},box:{y:150}},{shapeId:3,kind:'connector',box:{y:160}},{shapeId:8,kind:'picture',box:{y:160}}]};
 prepareStyleStencils({width:960,height:540,layouts:[l]});assert.deepEqual(l.htmlRemoveShapeIds,[8]);assert.equal(l.htmlCompositionPolicy,'source-first');
});
test('a chart picture excluded from photo slots is cleared even when style learning was unavailable',()=>{
 const l:any={htmlRole:'content',htmlConcept:{kind:'chart'},htmlTitleShapeId:1,imageSlots:[],sourceObjects:[{shapeId:1,kind:'shape',role:'title',box:{x:30,y:20,w:800,h:60}},{shapeId:750,kind:'picture',role:'photo',box:{x:0,y:112,w:960,h:360}}]};
 prepareStyleStencils({width:960,height:540,layouts:[l]});assert.deepEqual(l.htmlRemoveShapeIds,[750]);
});
test('cached classification cannot erase original icons or their containing group',()=>{
 const l:any={htmlRole:'content',htmlTitleShapeId:1,htmlRemoveShapeIds:[7,8],htmlStyleRemoveShapeIds:[],reservedRegions:[{shapeId:8,role:'icon'}],sourceObjects:[{shapeId:7,kind:'group',box:{y:150}},{shapeId:8,parentShapeId:7,kind:'picture',role:'icon',box:{y:150}}]};
 prepareStyleStencils({width:960,height:540,layouts:[l]});assert.deepEqual(l.htmlRemoveShapeIds,[]);assert.deepEqual(l.htmlStyleRemoveShapeIds,[]);
});
test('a copy shortening retains its measured CSS patch while rebinding every remaining field',()=>{
 const s=source(),before=realizeSourceComposition(slide(),s,0)!;
 const changed={...before,cards:[{title:'Короткий тезис',body:'Законченное объяснение.'}],css:before.css+' [data-source-shape="2"]{justify-content:center}'};
 const result=realizeSourceComposition(changed,s,0)!;
 assert.match(result.css!,/justify-content:center/);assert.deepEqual(missingHtmlBindings(result,s),[]);
});
test('card descriptions use the native caption and safe expanded interior, keeping the original card fill and icon clear',()=>{
 const s:any=source();s.sourceHtml.textRegions[1].textBox={x:40,y:150,w:340,h:65};s.sourceHtml.textRegions[2].textBox={x:52,y:280,w:316,h:150};
 s.sourceHtml.textRegions[2].textStyles={heading:{color:'#0077FF'},body:{color:'#FFFFFF'}};
 s.sourceHtml.textGroups=[{origin:'native-container',role:'repeated-content',headingShapeId:2,bodyShapeId:3,box:{x:40,y:150,w:340,h:300}}];
 const input=slide({cards:[{title:'Смысл сравнения',body:'Короткое объяснение результата.'}],sourceBindings:[{shapeId:2,paths:['cards.0.title','cards.0.body']}]});
 const result=realizeSourceComposition(input,s,0)!,$=load(result.html!);
 assert.equal($('[data-source-shape="2"]').attr('data-text'),'cards.0.title');assert.equal($('[data-source-shape="2"]').css('height'),'65px');
 assert.equal($('[data-source-shape="3"]').attr('data-text'),'cards.0.body');assert.equal($('[data-source-shape="3"]').css('top'),'280px');assert.equal($('[data-source-shape="3"]').css('color'),'#FFFFFF');
});
test('source data objects are bound in their actual frame and charts without a frame use the chart composer',()=>{
 const s:any=source();s.dataFrames=[{kind:'chart',box:{x:40,y:100,w:500,h:200}}];
 const data=slide({cards:[],paragraphs:['Рост заметен на всём периоде.'],chart:{type:'line',title:'Ряд',categories:['2020','2025'],series:[{name:'Ряд',values:[1,2]}]}});
 const result=realizeSourceComposition(data,s,0)!,$=load(result.html!);assert.equal($('[data-visual="chart"]').length,1);
 assert.equal(realizeSourceComposition(data,source(),0),undefined);
});
test('a single result reuses the full source column rather than a small agenda ordinal',()=>{
 const s:any=source();s.sourceHtml.canvas={width:1280,height:720};
 s.sourceHtml.textRegions=[{...region(1,40),box:{x:40,y:60,w:400,h:160}},
  ...[180,290,400].map((y,i)=>({...region(i+2,640),container:undefined,box:{x:640,y,w:540,h:65}}))];
 const result=realizeSourceComposition(slide({cards:[],metrics:[{value:'+57,64 ppm',label:'Изменение концентрации за период'}],paragraphs:['Рост между первым и последним наблюдениями.']}),s,0)!;
 const $=load(result.html!);assert.ok(parseFloat($('[data-text="metrics.0.value"]').css('font-size')!)>=40);
 assert.equal($('[data-text="metrics.0.value"]').parent().css('left'),'640px');assert.equal($('[data-text]').length,4);
});
test('a timeline conclusion uses its available caption row, keeping it away from a last narrow column',()=>{
 const s:any=source();s.sourceHtml.canvas={width:1280,height:720};
 const regions=[region(1,40),...Array.from({length:4},(_,i)=>({...region(2+i,40+i*290),container:undefined,box:{x:40+i*290,y:270,w:230,h:60}})),...Array.from({length:4},(_,i)=>({...region(6+i,40+i*290),container:undefined,box:{x:40+i*290,y:390,w:230,h:60}}))];
 s.sourceHtml.textRegions=regions;s.sourceHtml.html='<section class="source-slide">'+regions.map(r=>`<div data-source-shape="${r.shapeId}"></div>`).join('')+'</section>';
 const input=slide({cards:[],steps:Array.from({length:4},(_,i)=>({title:'Этап '+i,body:''})),takeaway:'Полный вывод по результату, а затем следующий шаг.',sourceBindings:Array.from({length:4},(_,i)=>({shapeId:2+i,paths:[`steps.${i}.title`]}))});
 const result=realizeSourceComposition(input,s,0)!,$=load(result.html!);assert.equal($('[data-text="takeaway"]').css('width'),'1100px');assert.deepEqual(missingHtmlBindings(result,s),[]);
});

test('original structural badges survive clearing without stealing prose or repeating metric ordinals',()=>{
 const s:any=source();
 const badges=Array.from({length:3},(_,i)=>({...region(10+i,40+i*260),container:undefined,box:{x:40+i*260,y:150,w:45,h:40}}));
 s.sourceHtml.structuralOrdinals=badges.map((r,i)=>({shapeId:r.shapeId,ordinal:i+1,digits:2}));
 s.sourceHtml.textRegions.push(...badges);s.sourceHtml.html=s.sourceHtml.html.replace('</section>',badges.map(r=>`<div data-source-shape="${r.shapeId}"></div>`).join('')+'</section>');
 const plain=load(realizeSourceComposition(slide(),s,0)!.html!);
 assert.equal(plain('[data-number]').length,3);assert.equal(plain('[data-text="cards.0.body"]').length,1);
 const result=realizeSourceComposition(slide({cards:[],metrics:[{value:'01',label:'Первая тема'},{value:'02',label:'Вторая тема'},{value:'03',label:'Третья тема'}],sourceBindings:badges.map((r,i)=>({shapeId:r.shapeId,paths:[`metrics.${i}.value`]}))}),s,0)!;
 const $=load(result.html!);assert.equal($('[data-number]').length,0);
 for(let i=0;i<3;i++)assert.equal($(`[data-source-shape="${10+i}"]`).attr('data-text'),`metrics.${i}.value`);
 assert.deepEqual(missingHtmlBindings(result,s),[]);
});
