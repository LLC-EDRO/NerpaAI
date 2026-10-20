import test from 'node:test';
import assert from 'node:assert/strict';
import {htmlDesignSchema,readHtmlDesign,measuredHtmlDesign} from '../../src/custom-presentations/engine/html-design.js';
import {normalizeHtmlCopy} from '../../src/custom-presentations/engine/html-domain.js';
import {htmlVisualReviewSchema,applyHtmlVisualRepairs} from '../../src/custom-presentations/engine/html-visual-review.js';

const design=htmlDesignSchema.parse({canvas:'panels',title:{x:540,y:100,w:400,h:170},
  content:[{x:540,y:300,w:400,h:580}],variants:['stack','cards','columns']});
const plan={slides:[{sourceLayoutId:'source',title:'Риски',brief:'Неполные данные'}]};
const copy=()=>normalizeHtmlCopy({thesis:'Проверить данные',slides:[{index:0,title:'Риски',paragraphs:['Неполные данные'],cards:[],metrics:[],steps:[],table:null,chart:null}]},plan).copy;

test('a prose diagnostic or empty repair cannot discard valid scoped visual assessments',()=>{
 const value=htmlVisualReviewSchema.parse({assessments:[{slide:1,verdict:'repair',reason:'Тесное пояснение'}],issues:['Unscoped prose',{slide:1,message:'Проверить отступ'}],repairs:[{},'prose',{slide:1,reason:'Уточнить отступ',cssPatch:'p{padding:20px}'}]});
 assert.equal(value.assessments?.length,1);assert.deepEqual(value.issues,[{slide:1,message:'Проверить отступ'}]);assert.equal(value.repairs.length,1);
 assert.equal(htmlVisualReviewSchema.safeParse({assessments:[{slide:0,verdict:'pass',reason:'Invalid owner'}]}).success,false);
});

test('a metric caption can be shortened and enlarged without changing its exact value or unit',()=>{
 const original=copy();original.slides[0]!.paragraphs=[];original.slides[0]!.metrics=[{value:'250 кг',label:'Планируемая масса материала для учебного пилота'}];
 original.slides[0]!.html='<h1 data-text="title"></h1><strong data-text="metrics.0.value"></strong><p data-text="metrics.0.label"></p>';
 const review=htmlVisualReviewSchema.parse({issues:[],repairs:[{slide:1,reason:'Мелкая подпись',metrics:[{value:'250 кг',label:'Масса материала — план пилота'}],cssPatch:'p{font-size:24px}'}]});
 const fixed=applyHtmlVisualRepairs(original,review,['content'],'');
 assert.deepEqual(fixed.changed,[0]);assert.equal(fixed.copy.slides[0]!.metrics[0]!.label,'Масса материала — план пилота');
 const unsafe=htmlVisualReviewSchema.parse({issues:[],repairs:[{slide:1,reason:'Подмена',metrics:[{value:'500 кг',label:'Масса материала'}],cssPatch:'p{font-size:24px}'}]});
 const rejected=applyHtmlVisualRepairs(original,unsafe,['content'],'');assert.deepEqual(rejected.changed,[]);assert.deepEqual(rejected.copy,original);
});

test('vision zones reject canvas overflow, title collisions and overlapping panels',()=>{
  assert.equal(htmlDesignSchema.safeParse({...design,title:{x:900,y:0,w:200,h:100}}).success,false);
  assert.equal(htmlDesignSchema.safeParse({...design,content:[design.title]}).success,false);
  assert.equal(htmlDesignSchema.safeParse({...design,content:[design.content[0],design.content[0]]}).success,false);
});
test('title-only terminals and small model edge overlaps do not discard a valid visual analysis',()=>{
  assert.ok(readHtmlDesign({...design,content:[]},'closing'));
  assert.equal(readHtmlDesign({...design,content:[]},'content'),undefined);
  const adjusted=readHtmlDesign({...design,content:[{x:540,y:250,w:400,h:630}]},'content')!;
  assert.equal(adjusted.content[0]!.y,278);assert.equal(adjusted.content[0]!.y+adjusted.content[0]!.h,880);
});
test('review uses measured panels instead of an old overly broad vision surface',()=>{
  const broad=htmlDesignSchema.parse({...design,surfaces:[{x:20,y:20,w:960,h:960}]});
  const grounded=measuredHtmlDesign({...design,surfaces:[{x:540,y:60,w:400,h:900}]},broad,1000,1000,'content');
  assert.ok(grounded);
  assert.deepEqual(grounded!.surfaces,[{x:540,y:60,w:400,h:900}]);
});
test('visual repair uses actual CSS rather than a second coordinate controller',()=>{
 const original=copy();original.slides[0]!.html='<h1 data-text="title"></h1><p data-text="paragraphs.0"></p>';
 const review=htmlVisualReviewSchema.parse({issues:[],repairs:[{slide:1,reason:'Readable local reflow',cssPatch:'p{max-width:680px;font-size:24px}'}]});
 const fixed=applyHtmlVisualRepairs(original,review,['content'],'');
 assert.deepEqual(fixed.changed,[0]);assert.equal(fixed.copy.slides[0]!.title,original.slides[0]!.title);
 assert.deepEqual(fixed.copy.slides[0]!.paragraphs,original.slides[0]!.paragraphs);assert.match(fixed.copy.slides[0]!.css!,/max-width:680px/);
});
test('a source-managed repair may split content into an additional real row before automatic rebinding',()=>{
 const original=copy();original.slides[0]!.html='<section data-source-composition-key="known"><h1 data-text="title"></h1><p data-text="paragraphs.0"></p></section>';
 const review=htmlVisualReviewSchema.parse({issues:[],repairs:[{slide:1,reason:'Заполнить отдельную исходную строку',paragraphs:['Первый самостоятельный тезис.','Второй самостоятельный тезис.']}]});
 const fixed=applyHtmlVisualRepairs(original,review,['content'],'');assert.deepEqual(fixed.changed,[0]);assert.equal(fixed.copy.slides[0]!.paragraphs.length,2);
 const bespoke=structuredClone(original);bespoke.slides[0]!.html=bespoke.slides[0]!.html!.replace('data-source-composition-key="known"','');
 assert.deepEqual(applyHtmlVisualRepairs(bespoke,review,['content'],'').changed,[],'bespoke HTML still requires every new field');
});
test('meaning repair uses individual chart values and never treats JSON separators as decimal commas',()=>{
 const original=copy();original.slides[0]!.chart={type:'line',title:'Заказы (тыс.)',categories:['2023','2024','2025','2026'],series:[{name:'Заказы',values:[42,56,70,88]}]};
 for(const [title,accepted] of [['Заказы выросли с 42 до 88 тыс. за 2023–2026 годы',true],['Заказы достигли 42,56 тыс.',false],['Заказы снизились до -42 тыс.',false]] as const){
  const review=htmlVisualReviewSchema.parse({issues:[],repairs:[{slide:1,reason:'Уточнить вывод',title}]});
  const fixed=applyHtmlVisualRepairs(original,review,['content'],'');
  assert.equal(fixed.changed.length>0,accepted,title);assert.deepEqual(fixed.copy.slides[0]!.chart,original.slides[0]!.chart);
 }
});
