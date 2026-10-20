import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID,createHash} from 'node:crypto';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,basename} from 'node:path';
import sharp from 'sharp';
import type {Project} from '../../src/custom-presentations/engine/domain.js';

import type {llmJson} from '../../src/custom-presentations/engine/llm.js';

import {withEngineContext} from '../../src/custom-presentations/engine/runtime-context.js';

import {prepareSourceFigureEvidence,sourceFigureFacts} from '../../src/custom-presentations/engine/source-figure-evidence.js';


const digest=(bytes:Buffer)=>createHash('sha256').update(bytes).digest('hex');
function project():Project{
  return {id:randomUUID(),name:'Source test',createdAt:'now',updatedAt:'now',revision:1,status:'idle',message:'',busy:true,events:[],
    brief:{topic:'Исходные рисунки',count:9,sourceText:'Методы визуализации временных рядов',webSearch:false,
      sourceDocument:{version:1,warnings:[],images:[{id:'figure-one',name:'graph.png',assetId:randomUUID(),caption:'Изменение населения'},
        {id:'figure-two',name:'heatmap.png',assetId:randomUUID(),caption:'Число событий по месяцам'}],
        blocks:[{type:'paragraph',id:'outside',text:'Far context'},
          {type:'paragraph',id:'p1',text:'Периоды наблюдений'},
          {type:'paragraph',id:'p2',text:'Данные демографии'},
          {type:'image',id:'b1',imageId:'figure-one'},
          {type:'paragraph',id:'p3',text:'Первая подпись'},
          {type:'paragraph',id:'p4',text:'Обсуждение'},
          {type:'image',id:'b2',imageId:'figure-two'},
          {type:'paragraph',id:'p5',text:'Вторая подпись'}]}}};
}
const response=(images:any[])=>({images:images.map(image=>({id:image.id,kind:image.id==='figure-one'?'chart':'diagram',
  description:image.id==='figure-one'?'Линейный график численности населения.':'Матрица корреляций признаков.',
  visibleLabels:image.id==='figure-one'?['Year','Ireland']:['Feature A','Feature B'],
  captionConflict:image.id==='figure-two',conflictReason:image.id==='figure-two'?'Оси содержат признаки, а не месяцы и дни.':'',
  safeTitle:image.id==='figure-one'?'Динамика численности':'Корреляции признаков',
  safeCaption:image.id==='figure-one'?'График исходных наблюдений':'Матрица связей между признаками'}))});
async function setup(t:any){
  const workspace=await mkdtemp(join(tmpdir(),'nerpa-figure-evidence-'));t.after(()=>rm(workspace,{recursive:true,force:true}));
  const p=project(),images=p.brief!.sourceDocument!.images;
  const buffers=new Map<string,Buffer>([
    [images[0]!.assetId!,await sharp({create:{width:2200,height:40,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).png().toBuffer()],
    [images[1]!.assetId!,await sharp({create:{width:50,height:30,channels:3,background:'#123456'}}).png().toBuffer()],
  ]);
  return {workspace,p,buffers,runtime:{workspace,readSourceImage:async(id:string)=>{assert.ok(buffers.has(id),'Owner ID required');return buffers.get(id)!;}}};
}
const signal=()=>new AbortController().signal;

test('reads actual owner images, produces white bounded vision copies, and records conflicts without changing source bytes',async t=>{
  const {workspace,p,buffers,runtime}=await setup(t),originals=[...buffers.values()].map(bytes=>Buffer.from(bytes));
  let calls=0;
  const model=(async(input:any)=>{
    calls++;assert.equal(input.stage,'source-figure-review');assert.equal(input.reasoning,'medium');
    assert.deepEqual(input.payload.images.map((image:any)=>image.id),['figure-one','figure-two']);
    assert.deepEqual(input.payload.images[0].nearbyParagraphs,['Периоды наблюдений','Данные демографии','Первая подпись','Обсуждение']);
    assert.equal(input.payload.images[1].authorCaption,'Число событий по месяцам');
    assert.match(input.prompt,/Не выполняй указания/);
    for(const path of input.images){
      assert.match(basename(path),/^[a-f0-9]{64}\.png$/);
      const metadata=await sharp(path).metadata();assert.ok(metadata.width!<=1600&&metadata.height!<=1600);assert.equal(metadata.hasAlpha,false);
    }
    const pixel=await sharp(input.images[0]).extract({left:0,top:0,width:1,height:1}).raw().toBuffer();
    assert.deepEqual([...pixel],[255,255,255]);
    return input.validate(response(input.payload.images));
  }) as typeof llmJson;
  const receipt=await withEngineContext(runtime,()=>prepareSourceFigureEvidence(p,signal(),{model}));
  assert.equal(calls,1);assert.equal(receipt!.images.length,2);assert.equal(p.status,'reviewing_source_images');
  assert.deepEqual(p.progress,{done:2,total:2});
  assert.deepEqual(receipt!.images.map(image=>image.sha256),originals.map(digest));
  assert.deepEqual([...buffers.values()],originals);
  assert.deepEqual(JSON.parse(await readFile(join(workspace,'source-figure-evidence.json'),'utf8')),receipt);
  const facts=sourceFigureFacts(p);assert.equal(facts.length,2);assert.deepEqual(facts[1]!.sourceIds,['figure-two']);
  assert.match(facts[1]!.text,/авторская подпись не соответствует изображению/);
  assert.match(facts[1]!.text,/Корреляции признаков/);
  assert.doesNotMatch(facts[1]!.text,/Число событий по месяцам/);
});

test('exact cache and durable resume skip the model; changed bytes or caption invalidate evidence',async t=>{
  const {p,buffers,runtime}=await setup(t);let calls=0;
  const model=(async(input:any)=>{calls++;return input.validate(response(input.payload.images));}) as typeof llmJson;
  await withEngineContext(runtime,async()=>{
    const initial=await prepareSourceFigureEvidence(p,signal(),{model});
    assert.deepEqual(await prepareSourceFigureEvidence(p,signal(),{model}),initial);assert.equal(calls,1);
    delete p.sourceFigureEvidence;
    assert.deepEqual(await prepareSourceFigureEvidence(p,signal(),{model}),initial);assert.equal(calls,1,'Resume uses the validated durable receipt');
    const asset=p.brief!.sourceDocument!.images[0]!.assetId!;
    buffers.set(asset,await sharp({create:{width:80,height:40,channels:3,background:'red'}}).png().toBuffer());
    const changed=await prepareSourceFigureEvidence(p,signal(),{model});assert.equal(calls,2);assert.notEqual(changed!.identity,initial!.identity);
    p.brief!.sourceDocument!.images[1]!.caption='Проверенная другая авторская подпись';
    assert.deepEqual(sourceFigureFacts(p),[],'Changed input cannot expose old figure facts');
    const recaptioned=await prepareSourceFigureEvidence(p,signal(),{model});assert.equal(calls,3);assert.notEqual(recaptioned!.identity,changed!.identity);
  });
});

test('rejects incomplete or duplicate model image coverage and never publishes partial evidence',async t=>{
  const {p,runtime}=await setup(t);
  for(const mode of ['missing','duplicate']){
    const model=(async(input:any)=>{const value=response(input.payload.images);return {images:mode==='missing'?value.images.slice(0,1):[value.images[0],value.images[0]]};}) as typeof llmJson;
    await assert.rejects(withEngineContext(runtime,()=>prepareSourceFigureEvidence(p,signal(),{model})),/images|image ID/i);
    assert.equal(p.sourceFigureEvidence,undefined);
  }
});

test('asset-backed images require the owner hook while legacy standalone projects are skipped',async t=>{
  const {p,workspace}=await setup(t);let calls=0;
  const model=(async()=>{calls++;throw Error('Must not call model');}) as typeof llmJson;
  await assert.rejects(withEngineContext({workspace},()=>prepareSourceFigureEvidence(p,signal(),{model})),
    (error:any)=>error.status===503&&error.code==='source_figure_reader_unavailable');
  for(const image of p.brief!.sourceDocument!.images)delete image.assetId;
  p.sourceFigureEvidence={version:1,identity:'stale',images:[]} as any;
  assert.equal(await withEngineContext({workspace},()=>prepareSourceFigureEvidence(p,signal(),{model})),undefined);
  assert.equal(calls,0);assert.equal(p.sourceFigureEvidence,undefined);assert.deepEqual(sourceFigureFacts(p),[]);
});

test('five source figures are reviewed in sequential batches of at most four with stable ID ordering',async t=>{
  const {p,buffers,runtime}=await setup(t),images=p.brief!.sourceDocument!.images;
  for(let index=3;index<=5;index++){
    const assetId=randomUUID();images.push({id:`figure-${index}`,name:`image-${index}.png`,assetId});
    buffers.set(assetId,[...buffers.values()][1]!);
  }
  const batches:string[][]=[];
  const model=(async(input:any)=>{batches.push(input.payload.images.map((image:any)=>image.id));return response(input.payload.images);}) as typeof llmJson;
  const result=await withEngineContext(runtime,()=>prepareSourceFigureEvidence(p,signal(),{model}));
  assert.deepEqual(batches,[['figure-one','figure-two','figure-3','figure-4'],['figure-5']]);
  assert.deepEqual(result!.images.map(image=>image.id),images.map(image=>image.id));assert.equal(sourceFigureFacts(p).length,5);
});

test('corrupt receipt fields cannot be reused even when its identity matches',async t=>{
  const {p,runtime}=await setup(t);let calls=0;
  const model=(async(input:any)=>{calls++;return input.validate(response(input.payload.images));}) as typeof llmJson;
  await withEngineContext(runtime,async()=>{
    await prepareSourceFigureEvidence(p,signal(),{model});
    p.sourceFigureEvidence!.images[0]!.description='';
    const receiptPath=join(runtime.workspace,'source-figure-evidence.json');
    const {writeFile}=await import('node:fs/promises');await writeFile(receiptPath,JSON.stringify(p.sourceFigureEvidence));
    assert.deepEqual(sourceFigureFacts(p),[]);
    await prepareSourceFigureEvidence(p,signal(),{model});assert.equal(calls,2);
  });
});
