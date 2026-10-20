import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import sharp from 'sharp';
import {generateVisualAsset,imagePrompt} from '../../src/custom-presentations/engine/editor-visual.js';

import {storeVisualAsset} from '../../src/custom-presentations/engine/visual-assets.js';

import {type EditorVisualChoice as VisualChoice} from '../../src/custom-presentations/engine/editor-visual.js';

import {withEngineContext} from '../../src/custom-presentations/engine/runtime-context.js';


const dimensions={width:720,height:405};
function backdrop():VisualChoice{return {
  slideIndex:0,slotIndex:0,shapeId:42,
  slot:{shapeId:42,kind:'picture',box:{x:300,y:40,w:300,h:240},aspectRatio:1.25,sourceRole:'photo',protected:false,requiresOpaque:false},
  role:'photo_underlay',kind:'photo',description:'A quiet image under the slide text',style:'blue',fieldKeys:['title'],
  background:'transparent',mode:'generate',quality:'medium',nonce:0,instruction:'',
};}
async function folder(t:any){const path=await mkdtemp(join(tmpdir(),'nerpa-backdrop-'));t.after(()=>rm(path,{recursive:true,force:true}));return path;}
async function bitmap(alpha=1){return sharp({create:{width:160,height:80,channels:4,background:{r:30,g:80,b:120,alpha}}}).png().toBuffer();}

test('opaque canvas resizing keeps full opacity and rejects translucent original pixels',async t=>{
  const directory=await folder(t);
  const asset=await storeVisualAsset(directory,await bitmap(),false,true,{width:80,height:160});
  const output=await readFile(join(directory,'visual-assets',asset));
  const metadata=await sharp(output).metadata();
  assert.equal(metadata.width,80);assert.equal(metadata.height,160);
  assert.equal((await sharp(output).stats()).isOpaque,true);
  await assert.rejects(storeVisualAsset(directory,await bitmap(.5),false,true,{width:80,height:160}),error=>(error as any).code==='visual_backdrop_alpha');
});

test('legacy transparent backdrop settings send one opaque request and reuse the same paid identity',async t=>{
  const directory=await folder(t),choice=backdrop();let calls=0;
  await withEngineContext({workspace:directory,env:{OPENAI_API_KEY:'mock-backdrop-image'}},async()=>{
    const request={folder:directory,prompt:imagePrompt('Quiet ocean photograph',choice,{}),choice,dimensions,signal:AbortSignal.timeout(10000),
      fetcher:async(_url:unknown,init?:RequestInit)=>{
        calls++;const body=JSON.parse(String(init?.body));assert.equal(body.background,'opaque');
        const [width,height]=body.size.split('x').map(Number);
        const bytes=await sharp({create:{width,height,channels:3,background:'#1e5078'}}).png().toBuffer();
        return Response.json({data:[{b64_json:bytes.toString('base64')}]});
      }};
    const result=await generateVisualAsset(request);assert.equal(result.background,'opaque');
    assert.deepEqual(await generateVisualAsset(request),result);assert.equal(calls,1);
  });
});
