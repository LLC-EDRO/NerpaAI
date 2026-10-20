import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import sharp from "sharp";
import {generateVisualAsset} from '../../src/custom-presentations/engine/editor-visual.js';

import {storeVisualAsset} from '../../src/custom-presentations/engine/visual-assets.js';

import {presentationImageSize} from '../../src/custom-presentations/engine/image-size.js';

import type {EditorVisualChoice as VisualChoice} from '../../src/custom-presentations/engine/editor-visual.js';

import {withEngineContext} from '../../src/custom-presentations/engine/runtime-context.js';


const choice: VisualChoice = {
  slideIndex: 0,
  slotIndex: 0,
  shapeId: 42,
  slot: {
    shapeId: 42,
    kind: "picture",
    box: { x: 350, y: 50, w: 300, h: 240 },
    aspectRatio: 1.25,
    sourceRole: "photo",
    protected: false,
    requiresOpaque: false,
    name: "test",
  },
  role: "content",
  kind: "illustration",
  description: "test picture",
  style: "blue",
  fieldKeys: [],
  background: "opaque",
  mode: "generate",
  quality: "medium",
  nonce: 0,
  instruction: "",
};
const dimensions = { width: 720, height: 405 };
const transparencyRejection={error:{message:'Transparent background is not supported for this model.',code:'invalid_value',param:'background',type:'image_generation_user_error'}};

test('native transparency fallback preserves slot canvas, receipts, provenance and paid-task cache',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'nerpa-native-fallback-'));
  try{
    const transparent={...choice,background:'transparent' as const};
    const size=presentationImageSize(choice.slot.box,dimensions);let calls=0;const captured:any[]=[];
    const input={folder,prompt:'Isolated blue solar panel',choice:transparent,dimensions,signal:AbortSignal.timeout(5000),fetcher:async(_url:unknown,init?:RequestInit)=>{
      calls++;const body=JSON.parse(String(init?.body));
      const journal=JSON.parse(await readFile(join(folder,'visual-tasks',(await readdir(join(folder,'visual-tasks')))[0]!),'utf8'));
      assert.equal(journal.model,body.model,'Actual request is recorded before it is sent');
      if(calls===1)return Response.json(transparencyRejection,{status:400});
      assert.equal(body.model,'gpt-image-1.5');
      const [width,height]=body.size.split('x').map(Number);
      const png=await sharp({create:{width,height,channels:4,background:{r:40,g:90,b:120,alpha:.5}}}).png().toBuffer();
      return Response.json({data:[{b64_json:png.toString('base64')}],usage:{output_tokens:100}});
    }};
    await withEngineContext({workspace:folder,env:{OPENAI_API_KEY:'native-fallback-success'},onImageGenerated:async info=>{captured.push(info);}},async()=>{
      const generated=await generateVisualAsset(input);
      const info=await sharp(await readFile(join(folder,'visual-assets',generated.asset))).metadata();
      assert.equal(info.width,size.width);assert.equal(info.height,size.height);assert.equal(info.hasAlpha,true);
      assert.deepEqual(await generateVisualAsset(input),generated);
    });
    assert.equal(calls,2);assert.equal(captured.length,2);assert.ok(captured.every(p=>p.model==='gpt-image-1.5'));
    const receipt=JSON.parse(await readFile(join(folder,'llm',(await readdir(join(folder,'llm')))[0]!),'utf8'));
    assert.equal(receipt.model,'gpt-image-1.5');assert.equal(receipt.background,'transparent');assert.equal(receipt.data,undefined);
  }finally{await rm(folder,{recursive:true,force:true});}
});

test('lost native fallback response is journaled uncertain and cannot be replayed',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'nerpa-native-uncertain-'));
  try{
    let calls=0;const input={folder,prompt:'Isolated solar panel',choice:{...choice,background:'transparent' as const},dimensions,signal:AbortSignal.timeout(5000),fetcher:async()=>{
      if(++calls===1)return Response.json(transparencyRejection,{status:400});throw Error('Connection lost');
    }};
    await withEngineContext({workspace:folder,env:{OPENAI_API_KEY:'native-fallback-uncertain'}},async()=>{
      await assert.rejects(generateVisualAsset(input),/Connection lost/);
      const journal=JSON.parse(await readFile(join(folder,'visual-tasks',(await readdir(join(folder,'visual-tasks')))[0]!),'utf8'));
      assert.equal(journal.state,'uncertain');
      await assert.rejects(generateVisualAsset(input),/Автоповтор отключён/);
    });assert.equal(calls,2);
  }finally{await rm(folder,{recursive:true,force:true});}
});

test('native fallback rejects opaque source before transparent padding is added',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'nerpa-native-alpha-'));
  try{
    let calls=0;await withEngineContext({workspace:folder,env:{OPENAI_API_KEY:'native-fallback-opaque'}},async()=>{
      await assert.rejects(generateVisualAsset({folder,prompt:'Isolated solar panel',choice:{...choice,background:'transparent'},dimensions,signal:AbortSignal.timeout(5000),fetcher:async(_url,init)=>{
        if(++calls===1)return Response.json(transparencyRejection,{status:400});
        const [width,height]=JSON.parse(String(init?.body)).size.split('x').map(Number);
        const png=await sharp({create:{width,height,channels:3,background:'#fff'}}).png().toBuffer();
        return Response.json({data:[{b64_json:png.toString('base64')}]});
      }}),/без прозрачного фона/);
    });assert.equal(calls,2);
  }finally{await rm(folder,{recursive:true,force:true});}
});
test("image canvas is bounded and valid for wide, tall and square native slots", () => {
  for (const [w, h] of [
    [300, 200],
    [200, 300],
    [100, 100],
    [500, 30],
  ]) {
    const s = presentationImageSize({ x: 0, y: 0, w, h }, dimensions);
    assert.equal(s.width % 16, 0);
    assert.equal(s.height % 16, 0);
    assert.ok(s.width * s.height >= 655360 && s.width * s.height <= 1280 * 720);
    assert.ok(Math.max(s.width / s.height, s.height / s.width) <= 3);
  }
});
test("normalize uploads; reject transparent text backdrops and fake image bytes", async () => {
  const folder = await mkdtemp(join(tmpdir(), "nerpa-img-"));
  try {
    const png = await sharp({
      create: {
        width: 32,
        height: 32,
        channels: 4,
        background: { r: 1, g: 2, b: 3, alpha: 0.5 },
      },
    })
      .png()
      .toBuffer();
    assert.match(
      await storeVisualAsset(folder, png, true),
      /^[a-f0-9]{64}\.png$/,
    );
    await assert.rejects(
      storeVisualAsset(folder, png, false, true),
      /непрозрачное/,
    );
    await assert.rejects(
      storeVisualAsset(folder, Buffer.from("not an image")),
      /PNG/,
    );
  } finally {
    await rm(folder, { recursive: true, force: true });
  }
});
test('explicit original PNG/JPEG storage preserves exact bytes and resolution after validation',async t=>{
  const folder=await mkdtemp(join(tmpdir(),'nerpa-original-image-'));t.after(()=>rm(folder,{recursive:true,force:true}));
  for(const format of ['png','jpeg'] as const){
    const source=sharp({create:{width:2304,height:48,channels:format==='png'?4:3,background:{r:15,g:30,b:45,alpha:format==='png'?.5:1}}});
    const input=await (format==='png'?source.png({compressionLevel:0}):source.jpeg({quality:83})).withMetadata({density:144}).toBuffer();
    const name=await storeVisualAsset(folder,input,false,false,undefined,{preserveOriginal:true});
    assert.ok(name.endsWith(format==='png'?'.png':'.jpg'));
    const stored=await readFile(join(folder,'visual-assets',name));assert.deepEqual(stored,input);
    assert.equal((await sharp(stored).metadata()).width,2304);
    const normalized=await storeVisualAsset(folder,input);
    assert.ok(normalized.endsWith('.png'));assert.equal((await sharp(await readFile(join(folder,'visual-assets',normalized))).metadata()).width,2048);
    assert.notDeepEqual(await readFile(join(folder,'visual-assets',normalized)),input);
    await assert.rejects(storeVisualAsset(folder,input,false,false,{width:128,height:128},{preserveOriginal:true}),{code:'visual_original_format'});
    if(format==='png')await assert.rejects(storeVisualAsset(folder,input,false,true,undefined,{preserveOriginal:true}),{code:'visual_backdrop_alpha'});
  }
  const webp=await sharp({create:{width:32,height:32,channels:3,background:'white'}}).webp().toBuffer();
  await assert.rejects(storeVisualAsset(folder,webp,false,false,undefined,{preserveOriginal:true}),{code:'visual_original_format'});
  await assert.rejects(storeVisualAsset(folder,Buffer.from('not a bitmap'),false,false,undefined,{preserveOriginal:true}),{code:'visual_format'});
});
test("paid generation is cached; ambiguous calls never auto-repeat; explicit nonce permits retry", async () => {
  const folder = await mkdtemp(join(tmpdir(), "nerpa-paid-"));
  const previous = process.env.OPENAI_API_KEY;
  process.env.OPENAI_API_KEY = "test";
  try {
    let calls = 0;
    const fetcher: any = async (_url: any, init: any) => {
      calls++;
      const body = JSON.parse(init.body);
      assert.equal(body.model, "gpt-image-2");
      assert.equal(body.n, 1);
      assert.equal(body.output_format, "png");
      assert.equal(body.response_format, undefined);
      const [width, height] = body.size.split("x").map(Number);
      const img = await sharp({
        create: { width, height, channels: 3, background: "#487af8" },
      })
        .png()
        .toBuffer();
      return new Response(
        JSON.stringify({
          data: [{ b64_json: img.toString("base64") }],
          usage: {
            input_tokens: 20,
            input_tokens_details: { text_tokens: 20, image_tokens: 0 },
            output_tokens: 500,
          },
        }),
        { headers: { "content-type": "application/json" } },
      );
    };
    const base = {
      folder,
      prompt: "test image",
      choice,
      dimensions,
      signal: new AbortController().signal,
      fetcher,
    };
    const [a, b] = await Promise.all([
      generateVisualAsset(base),
      generateVisualAsset(base),
    ]);
    assert.equal(a.asset, b.asset);
    assert.equal(calls, 1);
    const receipts = await readdir(join(folder, "llm"));
    assert.equal(receipts.length, 1);
    assert.ok(
      !(await readFile(join(folder, "llm", receipts[0]), "utf8")).includes(
        "b64_json",
      ),
    );
    let lost = 0;
    const broken = {
      ...base,
      prompt: "ambiguous",
      fetcher: (async () => {
        lost++;
        throw new Error("socket disconnected");
      }) as any,
    };
    await assert.rejects(generateVisualAsset(broken));
    await assert.rejects(generateVisualAsset(broken), /Автоповтор/);
    assert.equal(lost, 1);
    await generateVisualAsset({
      ...broken,
      choice: { ...choice, nonce: 1 },
      fetcher,
    });
    assert.equal(calls, 2);
  } finally {
    if (previous === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = previous;
    await rm(folder, { recursive: true, force: true });
  }
});
