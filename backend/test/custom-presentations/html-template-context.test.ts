import test from 'node:test';
import assert from 'node:assert/strict';
import {htmlTemplateContext,htmlReviewBatches,htmlReviewCoverage} from '../../src/custom-presentations/engine/html-template-context.js';
import {cssSourceDesign} from '../../src/custom-presentations/engine/html-model-geometry.js';
import {sourceHtmlDesign} from '../../src/custom-presentations/engine/html-source-design.js';
import {normalizeHtmlSourceBindings} from '../../src/custom-presentations/engine/html-bindings.js';

test('every slide is reviewed exactly once, including slides without technical warnings',()=>{
  for(const count of [1,3,5,15,28,40]){
    const batches=htmlReviewBatches(count);
    assert.deepEqual(batches.flat(),Array.from({length:count},(_,i)=>i));
    assert.ok(batches.every(batch=>batch.length<=5));
  }
  assert.throws(()=>htmlReviewCoverage([0,1],[{slide:1,verdict:'pass',reason:'Clear'}]));
  assert.throws(()=>htmlReviewCoverage([0,1],[{slide:1,verdict:'pass',reason:'Clear'},{slide:1,verdict:'pass',reason:'Duplicate'}]));
  assert.doesNotThrow(()=>htmlReviewCoverage([0],[{slide:1,verdict:'repair',reason:'Unreadable caption'}]));
});
test('design context is immutable across topics and changes with the source design',()=>{
  const source={sha256:'a',width:720,height:405,styleProfile:{fonts:['Inter'],colors:['#123456']}};
  const first=htmlTemplateContext({...source,brief:{topic:'A'}});
  assert.deepEqual(first.canvas,{width:960,height:540,units:'CSS px at 96dpi'});
  assert.deepEqual(first,htmlTemplateContext({...source,brief:{topic:'B'}}));
  assert.notEqual(first.digest,htmlTemplateContext({...source,sha256:'b'}).digest);
});
test('source DOM already uses CSS pixels and cannot be converted a second time',()=>{
  const sourceHtml={version:1,html:'<p style="left:96px"></p>',canvas:{width:960,height:540}};
  const css=cssSourceDesign({canvas:{width:720,height:405},sourceHtml,textAnchors:[],artwork:[],photoFrames:[],dataFrames:[]});
  assert.deepEqual(css.canvas,{width:960,height:540,units:'CSS px at 96dpi'});
  assert.deepEqual(css.sourceHtml,sourceHtml);
});
test('vision can identify a body-labelled banner instead of the parser card title',()=>{
 const slots=[{shapeId:1,role:'title',text:'Card',x:20,y:200,w:180,h:40,size:24},{shapeId:2,role:'body',text:'Banner',x:20,y:30,w:600,h:50,size:18}];
 const source=sourceHtmlDesign({width:720,height:405},{slots,htmlTitleShapeId:2});
 assert.equal(source.title?.shapeId,2);assert.equal(source.headingAuthority,'vision');
 const absent=sourceHtmlDesign({width:720,height:405},{slots,htmlTitleShapeId:null});
 assert.equal(absent.title,undefined);assert.equal(absent.headingAbsent,true);
});
test('copy capacity uses readable type and the actual padded icon-clear interior',()=>{
 const slots=[{shapeId:1,role:'title',text:'Заголовок',x:20,y:20,w:600,h:50,size:24},{shapeId:2,role:'body',text:'Пример',x:30,y:170,w:285,h:97,size:12}];
 const source=sourceHtmlDesign({width:960,height:540},{slots,htmlTitleShapeId:1,htmlSource:{textRegions:[{shapeId:2,box:{x:40,y:226.67,w:380,h:129.33},insets:[15.47,22.83,15.47,86.93],textStyles:{body:{size:16}}}]}});
 const caption=source.textAnchors.find(a=>a.shapeId===2)!;
 assert.ok(caption.maxWords<=10);assert.equal(caption.copyFit.lines,3);assert.ok(caption.copyFit.fontPx>=21.4);
 const tiny=sourceHtmlDesign({width:960,height:540},{slots:[{...slots[1],h:10}],htmlTitleShapeId:null});
 assert.equal(tiny.textAnchors[0]!.copyFit.requiresLocalReflow,true);
});
test('duplicate card bindings prefer the actual repeated row over the introductory aside',()=>{
 const slide:any={html:'<aside><h2 data-source-shape="1" data-text="cards.0.title"></h2></aside><article><h2 data-source-shape="2" data-text="cards.0.title"></h2></article>'};
 const source={sourceHtml:{textGroups:[{headingShapeId:1,role:'lead-or-aside'},{headingShapeId:2,role:'repeated-content'}]}};
 assert.equal(normalizeHtmlSourceBindings(slide,source),true);assert.equal((slide.html.match(/data-text=/g)??[]).length,1);
 assert.ok(slide.html.includes('data-source-shape="2"'));assert.equal(normalizeHtmlSourceBindings(slide,source),false);
 const ambiguous:any={html:'<p data-text="paragraphs.0"></p><p data-text="paragraphs.0"></p>'};
 assert.equal(normalizeHtmlSourceBindings(ambiguous,source),false);
});
test('simple source rows keep all card destinations instead of shifting data into an aside',()=>{
 const groups=[{id:'aside',role:'lead-or-aside',headingShapeId:1,bodyShapeId:2,box:{x:10,y:10,w:120,h:80}},
   ...[0,1].map(i=>({id:'row'+i,role:'repeated-content',headingShapeId:3+i*2,bodyShapeId:4+i*2,box:{x:300,y:100+i*120,w:350,h:100}}))];
 const slide:any={cards:[{title:'A',body:'Alpha'},{title:'B',body:'Beta'}],css:'source CSS',html:'<aside><h2 data-source-shape="1" data-text="cards.0.title"></h2><p data-source-shape="2" data-text="cards.0.body"></p></aside><article><h2 data-source-shape="3" data-text="cards.1.title"></h2><p data-source-shape="4" data-text="cards.1.body"></p></article><article><p data-source-shape="6" data-text="cards.1.body"></p></article>'};
 assert.equal(normalizeHtmlSourceBindings(slide,{sourceHtml:{textGroups:groups}}),true);
 assert.equal(slide.css,'source CSS');assert.equal((slide.html.match(/data-text=/g)??[]).length,4);
 assert.ok(slide.html.includes('data-source-shape="5" data-text="cards.1.title"'));
 assert.equal(normalizeHtmlSourceBindings(slide,{sourceHtml:{textGroups:groups}}),false);
});
