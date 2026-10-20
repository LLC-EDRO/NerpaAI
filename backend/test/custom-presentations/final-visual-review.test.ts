import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import sharp from 'sharp';
import type {infer as Infer} from 'zod';
import {reviewFinalSlides,finalVisualReviewSchema,finalVisualReviewSummary,finalVisualReviewPolicyVersion,type FinalVisualReviewState} from '../../src/custom-presentations/engine/final-visual-review.js';


type Options=Parameters<typeof reviewFinalSlides>[0];
type Request=Parameters<Options['review']>[0];
type Assessment=Infer<typeof finalVisualReviewSchema>;
const digest=(value:Buffer|string)=>createHash('sha256').update(value).digest('hex');
const assessment=():Assessment=>({clarity:{status:'ok',summary:'All text is readable.'},illustrations:{status:'ok',summary:'The image supports the slide.'},composition:{status:'ok',summary:'Objects fit the page.'},issues:[]});
async function fixture(){
  const slides=[{index:0,id:'cover',context:{purpose:'cover'}},{index:1,id:'body',context:{purpose:'body'}},{index:2,id:'last',context:{purpose:'conclusion'}}];
  const images=await Promise.all(slides.map((slide,index)=>sharp(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="'+['#ffffff','#f0f5ff','#fff5f0'][index]+'"/><text x="64" y="180" font-size="40">'+slide.id+'</text></svg>')).png().toBuffer()));
  const calls:Request[]=[],previews:number[]=[],saved:FinalVisualReviewState[]=[];
  const options:Options={artifactDigest:digest('exact exported PDF'),artifactKind:'builtin-pdf',context:{topic:'Experiment',instructions:'Read all slides'},slides,
    preview:async(index)=>{previews.push(index);return Buffer.from(images[index]!);},
    review:async(request)=>{calls.push(request);return {value:assessment(),provider:'isolated-fixture',model:'prepared-assessment'};},
    save:async(state)=>{saved.push(structuredClone(state));},
  };
  return {options,images,calls,previews,saved};
}

test('every actual final PNG is reviewed including fitting cover/body/last, with complete identity and unchanged bytes',async()=>{
  const f=await fixture(),before=f.images.map(digest),progress:Array<[number,number]>=[];
  const state=await reviewFinalSlides({...f.options,onProgress:async(done,total)=>{progress.push([done,total]);}});
  assert.equal(state.status,'complete');assert.equal(state.reviews.length,3);
  assert.deepEqual(f.calls.map(request=>[request.index,request.id]),[[0,'cover'],[1,'body'],[2,'last']]);
  for(const request of f.calls){
    assert.ok(Buffer.isBuffer(request.png));assert.deepEqual(request.png,f.images[request.index]);assert.equal(request.imageHash,digest(request.png));
    assert.deepEqual(request.context,f.options.slides[request.index]!.context);assert.deepEqual(request.deckContext,f.options.context);assert.ok(request.prompt.length>20);
  }
  assert.deepEqual(f.images.map(digest),before);assert.deepEqual(progress.at(-1),[3,3]);assert.equal(f.saved.at(-1)?.status,'complete');
  const summary=finalVisualReviewSummary(state);assert.equal(summary.status,'complete');assert.equal(summary.reviewedSlides,3);
  assert.equal(summary.totalSlides,3);assert.equal(summary.artifactDigest,f.options.artifactDigest);assert.deepEqual(summary.issues,[]);
});

test('all three analysis dimensions are mandatory and their status must agree with concrete findings',()=>{
  assert.ok(finalVisualReviewSchema.safeParse(assessment()).success);
  const missing:any=assessment();delete missing.illustrations;assert.ok(!finalVisualReviewSchema.safeParse(missing).success);
  const contradicted=assessment();contradicted.issues.push({category:'clarity',severity:'critical',message:'Unreadable title',suggestion:'Make title readable'});
  assert.ok(!finalVisualReviewSchema.safeParse(contradicted).success);
  const omitted=assessment();omitted.composition.status='issue';assert.ok(!finalVisualReviewSchema.safeParse(omitted).success);
});

test('native critical/warning findings preserve severity and actual slide ordinal without altering the export',async()=>{
  const f=await fixture(),before=f.images.map(digest);
  const state=await reviewFinalSlides({...f.options,artifactKind:'uploaded-pptx',review:async(request)=>{
    const value=assessment();if(request.index===1){value.clarity.status='issue';value.composition.status='issue';value.issues=[
      {category:'clarity',severity:'warning',message:'Small caption',suggestion:'Increase caption size'},
      {category:'composition',severity:'critical',message:'Legend overlaps data',suggestion:'Move the legend'},
    ];}return {value,provider:'isolated-fixture',model:'prepared-assessment'};
  }});
  assert.equal(state.status,'complete');assert.deepEqual(f.images.map(digest),before);
  const summary=finalVisualReviewSummary(state);assert.equal(summary.reviewedSlides,3);assert.deepEqual(summary.issues.map(issue=>issue.slide),[2,2]);
  assert.deepEqual(summary.issues.map(issue=>issue.severity),['warning','critical']);assert.ok(summary.issues.every(issue=>issue.message&&issue.suggestion&&issue.reason));
});

test('partial provider failure stays running; exact resume skips accepted rows after checking their actual current PNG',async()=>{
  const f=await fixture(),failure=new Error('isolated provider offline');let calls=0;
  await assert.rejects(reviewFinalSlides({...f.options,review:async()=>{if(++calls===2)throw failure;return {value:assessment(),provider:'fixture',model:'prepared'};}}),error=>error===failure);
  const partial=f.saved.at(-1)!;assert.equal(partial.status,'running');assert.equal(partial.reviews.length,1);assert.ok(!f.saved.some(state=>state.status==='complete'));
  f.calls.length=0;f.previews.length=0;
  const state=await reviewFinalSlides({...f.options,state:partial});assert.equal(state.status,'complete');
  assert.deepEqual(f.calls.map(request=>request.index),[1,2]);assert.deepEqual(f.previews,[0,1,2]);
});

test('complete exact-artifact resume avoids provider calls while verifying all current image bytes',async()=>{
  const f=await fixture(),state=await reviewFinalSlides(f.options),progress:Array<[number,number]>=[];f.calls.length=0;f.previews.length=0;
  const resumed=await reviewFinalSlides({...f.options,state:structuredClone(state),onProgress:async(done,total)=>{progress.push([done,total]);}});assert.equal(resumed.status,'complete');
  assert.equal(f.calls.length,0);assert.deepEqual(f.previews,[0,1,2]);assert.deepEqual(progress,[[1,3],[2,3],[3,3]]);
});

test('artifact digest/kind and deck context changes invalidate every cached assessment',async()=>{
  const f=await fixture(),state=await reviewFinalSlides(f.options);
  const variants:Array<Partial<Options>>=[{artifactDigest:digest('new export bytes')},{artifactKind:'uploaded-pptx'},{context:{topic:'Changed evidence'}}];
  for(const variant of variants){f.calls.length=0;const result=await reviewFinalSlides({...f.options,...variant,state});assert.equal(result.status,'complete');assert.deepEqual(f.calls.map(request=>request.index),[0,1,2]);}
});

test('a changed final PNG invalidates precisely that row despite unchanged artifact ID and text context',async()=>{
  const f=await fixture(),state=await reviewFinalSlides(f.options),replacement=await sharp({create:{width:640,height:360,channels:3,background:'#5a77d3'}}).png().toBuffer();
  f.images[1]=replacement;f.calls.length=0;
  const result=await reviewFinalSlides({...f.options,state});assert.equal(result.status,'complete');assert.deepEqual(f.calls.map(request=>request.index),[1]);
  assert.equal(result.reviews.find(row=>row.index===1)!.imageHash,digest(replacement));
});

test('slide identity/order and per-slide context changes never reuse stale full-deck receipts',async()=>{
  const f=await fixture(),state=await reviewFinalSlides(f.options);
  const variants=[f.options.slides.map((slide,index)=>({...slide,id:index===1?'replaced-body':slide.id})),
    [...f.options.slides].reverse().map((slide,index)=>({...slide,index})),
    f.options.slides.map((slide,index)=>({...slide,context:index===1?{purpose:'comparison'}:slide.context}))];
  for(const slides of variants){f.calls.length=0;const result=await reviewFinalSlides({...f.options,slides,state});assert.equal(result.status,'complete');assert.deepEqual(f.calls.map(request=>request.index),[0,1,2]);}
});

test('malformed, duplicate and out-of-range cached coverage is ignored rather than certified',async()=>{
  const f=await fixture(),state=await reviewFinalSlides(f.options);
  const invalid=[{...state,policyVersion:999},{...state,reviews:[state.reviews[0],state.reviews[0],state.reviews[2]]},
    {...state,reviews:state.reviews.map((row,index)=>index===1?{...row,index:99}:row)},
    {...state,reviews:state.reviews.map((row,index)=>index===1?{...row,value:{clarity:{status:'ok',summary:'No other areas'}}}:row)},
    {...state,reviews:state.reviews.map((row,index)=>index===1?{...row,id:'cover'}:row)}];
  for(const cached of invalid){f.calls.length=0;const result=await reviewFinalSlides({...f.options,state:cached});assert.equal(result.status,'complete');assert.deepEqual(f.calls.map(request=>request.index),[0,1,2]);}
  assert.throws(()=>finalVisualReviewSummary(invalid[1]));assert.throws(()=>finalVisualReviewSummary(invalid[2]));assert.throws(()=>finalVisualReviewSummary(invalid[4]));
});

test('a previous policy receipt remains readable for delivered decks but cannot skip review under current slide scope',async()=>{
  const f=await fixture(),current=await reviewFinalSlides(f.options);
  for(const policyVersion of [1,2]){
    const previous={...current,policyVersion};
    assert.equal(finalVisualReviewSummary(previous).status,'complete');
    f.calls.length=0;
    const updated=await reviewFinalSlides({...f.options,state:previous});
    assert.equal(updated.policyVersion,finalVisualReviewPolicyVersion);
    assert.deepEqual(f.calls.map(request=>request.index),[0,1,2]);
    assert.match(f.calls[0]!.prompt,/не требуй все эти элементы на каждом слайде/);
  }
});

test('invalid assessment or provider failure never saves a complete receipt',async()=>{
  for(const mode of ['invalid','provider']){const f=await fixture();await assert.rejects(reviewFinalSlides({...f.options,review:async()=>{if(mode==='provider')throw Error('offline');return {value:{issues:[]},provider:'fixture',model:'invalid'};}}));assert.ok(!f.saved.some(state=>state.status==='complete'));}
});

test('missing, empty, corrupt or undersized PNG never reaches the model or complete coverage',async()=>{
  const tiny=await sharp({create:{width:32,height:18,channels:3,background:'#ffffff'}}).png().toBuffer();
  for(const mode of ['missing','empty','corrupt','undersized']){const f=await fixture();await assert.rejects(reviewFinalSlides({...f.options,preview:async()=>{if(mode==='missing')throw Error('No final image');return mode==='empty'?Buffer.alloc(0):mode==='undersized'?tiny:Buffer.from('stale filename is not PNG bytes');}}));assert.equal(f.calls.length,0);assert.ok(!f.saved.some(state=>state.status==='complete'));}
});

test('cancellation before or after a provider response cannot publish completed coverage',async()=>{
  for(const stage of ['before','after']){const f=await fixture();let stopped=stage==='before';await assert.rejects(reviewFinalSlides({...f.options,assertActive:async()=>{if(stopped)throw Error('cancelled fixture');},review:async(request)=>{f.calls.push(request);stopped=true;return {value:assessment(),provider:'fixture',model:'prepared'};}}),/cancelled fixture/);assert.ok(!f.saved.some(state=>state.status==='complete'));if(stage==='before')assert.equal(f.calls.length,0);}
});

test('durable save failure propagates instead of returning successful review',async()=>{
  const f=await fixture();await assert.rejects(reviewFinalSlides({...f.options,save:async()=>{throw Error('isolated durable storage offline');}}),/isolated durable storage offline/);
});

test('callback PNG mutation cannot certify different bytes from its server-owned image hash',async()=>{
  const f=await fixture();await assert.rejects(reviewFinalSlides({...f.options,review:async(request)=>{
    const end=request.png.length-1;request.png[end]=(request.png[end]??0)^1;return {value:assessment(),provider:'fixture',model:'mutating-callback'};
  }}),/final_visual_image_changed/);assert.ok(!f.saved.some(state=>state.status==='complete'));
});

test('callback extras cannot overwrite the server-owned slide identity and image hash',async()=>{
  const f=await fixture(),state=await reviewFinalSlides({...f.options,review:async()=>({value:assessment(),provider:'fixture',model:'prepared',index:99,id:'other-slide',imageHash:digest('other image')})});
  assert.deepEqual(state.reviews.map(row=>[row.index,row.id]),[[0,'cover'],[1,'body'],[2,'last']]);assert.deepEqual(state.reviews.map(row=>row.imageHash),f.images.map(digest));
});

test('duplicate IDs, invalid index coverage and empty manifests reject before model work',async()=>{
  for(const slides of [[{index:0,id:'same'},{index:1,id:'same'}],[{index:0,id:'a'},{index:2,id:'b'}],[{index:0,id:'a'},{index:-1,id:'b'}],[]]){const f=await fixture();await assert.rejects(reviewFinalSlides({...f.options,slides}));assert.equal(f.calls.length,0);assert.ok(!f.saved.some(state=>state.status==='complete'));}
});

test('cancellation during PNG rendering stops before any provider work',async()=>{
  const f=await fixture();let stopped=false;
  await assert.rejects(reviewFinalSlides({...f.options,assertActive:async()=>{if(stopped)throw Error('cancelled during preview');},
    preview:async(index)=>{stopped=true;return f.images[index]!;}}),/cancelled during preview/);
  assert.equal(f.calls.length,0);assert.ok(!f.saved.some(state=>state.status==='complete'));
});

test('original and callback context mutation cannot alter the hashed request or later slides',async()=>{
  const f=await fixture(),baseline=await reviewFinalSlides(f.options),expectedDeck=structuredClone(f.options.context),expectedSlides=structuredClone(f.options.slides);
  const requests:Request[]=[];
  const state=await reviewFinalSlides({...f.options,preview:async(index)=>{
    if(index===0){(f.options.context as {topic:string}).topic='Changed during preview';f.options.slides[1]!.context={purpose:'Wrong later body'};}
    return f.images[index]!;
  },review:async(request)=>{
    requests.push(structuredClone(request));assert.deepEqual(request.deckContext,expectedDeck);assert.deepEqual(request.context,expectedSlides[request.index]!.context);
    (request.deckContext as {topic:string}).topic='Changed by callback';(request.context as {purpose:string}).purpose='Changed by callback';
    return {value:assessment(),provider:'fixture',model:'prepared'};
  }});
  assert.equal(state.deckDigest,baseline.deckDigest);assert.equal(requests.length,3);
  assert.deepEqual(requests[1]!.context,{purpose:'body'});assert.deepEqual(requests[2]!.context,{purpose:'conclusion'});
});

test('final artifact verification runs before completed coverage can be saved',async()=>{
  const f=await fixture();let verified=false;
  const state=await reviewFinalSlides({...f.options,verify:async()=>{assert.equal(f.saved.at(-1)?.status,'running');verified=true;},
    save:async(value)=>{if(value.status==='complete')assert.equal(verified,true);f.saved.push(structuredClone(value));}});
  assert.equal(state.status,'complete');
  const failed=await fixture();await assert.rejects(reviewFinalSlides({...failed.options,verify:async()=>{throw Error('export changed after review');}}),/export changed after review/);
  assert.equal(failed.saved.at(-1)?.status,'running');assert.ok(!failed.saved.some(value=>value.status==='complete'));
});

test('temporary first-preview failure retains paid cached rows so retry does not repeat completed reviews',async()=>{
  const f=await fixture(),complete=await reviewFinalSlides(f.options);f.calls.length=0;f.saved.length=0;
  await assert.rejects(reviewFinalSlides({...f.options,state:complete,preview:async()=>{throw Error('temporary bitmap unavailable');}}),/temporary bitmap unavailable/);
  const cached=f.saved.at(-1)!;assert.equal(cached.status,'running');assert.deepEqual(cached.reviews,complete.reviews);
  assert.equal(f.calls.length,0);
  const resumed=await reviewFinalSlides({...f.options,state:cached});assert.equal(resumed.status,'complete');assert.equal(f.calls.length,0);
});
