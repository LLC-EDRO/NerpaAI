import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
const privateRoot=await mkdtemp(join(tmpdir(),'nerpa-v3-plan-host-'));
process.env.DATA_DIR=join(privateRoot,'projects');
after(()=>rm(privateRoot,{recursive:true,force:true}));
const {recoverPlanProposal}=await import('../../src/custom-presentations/engine/plan-recovery.js');
const {generatePlan,validatePlan,uploadedPlanningContext}=await import('../../src/custom-presentations/engine/pipeline.js');
import {withEngineContext} from '../../src/custom-presentations/engine/runtime-context.js';
import {sourceRecoveryVersion} from '../../src/custom-presentations/engine/template-version.js';
import type {Project,Outline,Layout} from '../../src/custom-presentations/engine/domain.js';

const layout=(id:string,role='content',frames=0):Layout=>({id,index:0,name:id,usable:true,warnings:[],slots:[],charts:[],htmlRole:role,htmlTemplateLayout:true,
  imageSlots:Array.from({length:frames},(_,i)=>({shapeId:i+1,sourceRole:'content',protected:false,requiresOpaque:false}))});
const policy={photos:{max:0},tables:{min:1 as const,target:1,max:2},charts:{min:1 as const,target:1,max:2},interiorSlides:2};
function fixture(){
 const p:Project={id:'test',name:'test',createdAt:'',updatedAt:'',revision:1,status:'planning',busy:false,message:'',events:[],
  brief:{topic:'Временные ряды',sourceText:'Ирландия и Европа, температурные ряды.',count:4,webSearch:false,sourceDocument:{version:1,images:[{id:'image-1',name:'Graph'},{id:'image-2',name:'Heatmap'}],warnings:[]}},
  analysis:{layouts:[layout('cover','cover'),layout('text'),layout('photo','content',1),layout('thanks','closing'),layout('logo','content',2),layout('hero','cover',4)]}};
 p.analysis.layouts[4].imageSlots.forEach((s:any)=>{s.protected=true;s.sourceRole='logo';});
 const plan:Outline={slides:[{sourceLayoutId:'cover',title:'Доклад',brief:'Тема'},
  {sourceLayoutId:'text',title:'Ирландия и Европа',brief:'Проверенные исходные ряды.',sourceImageIds:['image-1']},
  {sourceLayoutId:'text',title:'Тепловая карта',brief:'Дни недели и месяцы.',sourceImageIds:['image-2']},
  {sourceLayoutId:'thanks',title:'Выводы',brief:'Итоги'}]};
 return {p,plan};
}
test('both incompatible figure layouts are repaired locally without changing a word or losing an original',()=>{
 const {p,plan}=fixture(),before=structuredClone(plan);
 const result=recoverPlanProposal(p,plan);
 assert.equal(result.warnings.length,2);
 assert.deepEqual(result.plan.slides.map(s=>s.sourceLayoutId),['cover','photo','photo','thanks']);
 assert.deepEqual(validatePlan(p,result.plan,policy),result.plan);
 for(let i=0;i<4;i++)assert.deepEqual({...result.plan.slides[i],sourceLayoutId:before.slides[i]!.sourceLayoutId},before.slides[i]);
 assert.deepEqual(plan,before,'input proposal and approved layouts stay immutable');
 assert.deepEqual(recoverPlanProposal(p,result.plan).plan,result.plan,'recovery is idempotent');
});
test('validator reports all incompatible slides in one repair round and preserves strict source ownership',()=>{
 const {p,plan}=fixture();
 assert.throws(()=>validatePlan(p,plan,policy),(e:any)=>e.code==='plan_source_image_capacity'&&e.details.issues.length===2&&e.details.issues[1].path[1]===2);
 plan.slides[1]!.sourceImageIds=['unknown-source'];
 assert.throws(()=>validatePlan(p,recoverPlanProposal(p,plan).plan,policy),(e:any)=>e.code==='source_image_invalid');
});
test('protected artwork, covers and capacity shortages cannot be passed off as document frames',()=>{
 const {p,plan}=fixture();p.analysis.layouts=p.analysis.layouts.filter((l:Layout)=>l.id!=='photo');
 assert.equal(recoverPlanProposal(p,plan).warnings.length,0);
 assert.throws(()=>validatePlan(p,recoverPlanProposal(p,plan).plan,policy),(e:any)=>e.code==='plan_source_image_capacity');
 const context=uploadedPlanningContext(p);
 assert.deepEqual(context.sourceImageLayoutIds,[]);
 assert.ok(context.layouts.every(l=>l.safeSourceImageSlotCount===0));
});
test('already compatible figure layouts and unrelated text/table choices retain their source identity',()=>{
 const {p,plan}=fixture();plan.slides[1]!.sourceLayoutId='photo';delete plan.slides[2]!.sourceImageIds;
 const result=recoverPlanProposal(p,plan);
 assert.deepEqual(result.plan,plan);assert.equal(result.warnings.length,0);
 assert.deepEqual(uploadedPlanningContext(p).sourceImageLayoutIds,['photo']);
});
test('a small automatic count shortfall is repaired without another model call or changes to original figures',()=>{
 const {p,plan}=fixture();p.brief!.count=5;const before=structuredClone(plan);
 const result=recoverPlanProposal(p,plan);assert.equal(result.plan.slides.length,5);
 assert.deepEqual(result.plan.slides.filter(s=>s.sourceImageIds).map(s=>s.sourceImageIds),[['image-1'],['image-2']]);
 assert.equal(result.plan.slides.at(-1)!.sourceLayoutId,'thanks');assert.deepEqual(plan,before);
 assert.equal(result.warnings.filter(w=>w.reason==='plan_count_repaired').length,1);
 assert.deepEqual(recoverPlanProposal(p,result.plan).plan,result.plan);
});
test('a durable candidate completes the same outline after a restart without another provider call; changed source invalidates it',async t=>{
 const folder=await mkdtemp(join(tmpdir(),'nerpa-plan-cache-'));t.after(()=>rm(folder,{recursive:true,force:true}));
 const {p,plan}=fixture();p.id=randomUUID();p.analysis.recoveryVersion=sourceRecoveryVersion;
 p.brief!.sourceDocument!.images=[];plan.slides.forEach(s=>delete s.sourceImageIds);
 const documents=new Map<string,unknown>();let calls=0;
 t.mock.method(globalThis,'fetch',async(url:any)=>{if(String(url).endsWith('/api/tags'))return Response.json({models:[{name:'gemma4:12b'}]});calls++;return Response.json({choices:[{finish_reason:'stop',message:{content:JSON.stringify(plan)}}]});});
 const {saveModelSettings}=await import('../../src/model-settings.js');
 await withEngineContext({workspace:folder},()=>saveModelSettings({provider:'ollama',baseUrl:'http://127.0.0.1:11434',textModel:'gemma4:12b',visionModel:'gemma4:12b'}));
 await withEngineContext({workspace:folder,
  writeDocument:async(path,value)=>{documents.set(path,structuredClone(value));},readDocument:async path=>documents.get(path)},async()=>{
  const first=structuredClone(p);await generatePlan(first,new AbortController().signal);assert.equal(calls,1);assert.equal(first.plan!.slides.length,4);
  const resumed=structuredClone(p);await generatePlan(resumed,new AbortController().signal);assert.equal(calls,1);assert.equal(resumed.plan!.slides.length,4);
  const changed=structuredClone(p);changed.brief!.sourceText+=' Additional original material.';
  await generatePlan(changed,new AbortController().signal);assert.equal(calls,2);
 });
});
