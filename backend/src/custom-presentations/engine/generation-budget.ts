import {AsyncResource} from 'node:async_hooks';
import {engineContext} from './runtime-context.js';

/** Shared process limit, in addition to each deployment's bounded job queue. */
export function createGenerationLimiter(limit:number){
  let active=0;
  const queue:Array<()=>void>=[];
  return async function run<T>(work:()=>Promise<T>,signal?:AbortSignal):Promise<T>{
    signal?.throwIfAborted();
    let start!:()=>void;
    await new Promise<void>((resolve,reject)=>{
      const abort=()=>{const index=queue.indexOf(start);if(index>=0){queue.splice(index,1);reject(signal?.reason);}};
      start=AsyncResource.bind(()=>{signal?.removeEventListener('abort',abort);active++;resolve();});
      signal?.addEventListener('abort',abort,{once:true});
      if(active<limit)start();else queue.push(start);
      if(signal?.aborted)abort();
    });
    try{signal?.throwIfAborted();return await work();}
    finally{active--;queue.shift()?.();}
  };
}

export function generationBudget(startedAt=Date.now(),limitMs=240000,now=Date.now){
  const deadline=startedAt+Math.max(30000,Math.min(240000,limitMs));
  return {startedAt,deadline,remaining:()=>Math.max(0,deadline-now()),
    signal:(reserveMs=0,capMs=240000)=>AbortSignal.any([
      AbortSignal.timeout(Math.max(1,Math.min(capMs,deadline-now()-reserveMs))),
      ...(engineContext()?.signal ? [engineContext()!.signal!] : []),
    ])};
}

/** A complex deck cannot repair twelve pages inside a hardcoded 30s render
 * when its measured first render took 40–55s. Keep the publication reserve. */
export function htmlRepairRenderMs(initialMs:number,changed:number,total:number,availableMs:number){
 const estimate=initialMs*Math.min(1,.25+.9*changed/Math.max(1,total))+12000;
 return Math.max(1,Math.floor(Math.min(availableMs,65000,Math.max(30000,estimate))));
}

/** Complex uploaded artwork is slower when several decks render together.
 * A per-render 50–75s cap cancelled otherwise viable work before the global
 * deadline. Borrow only available time, retaining the publication reserve. */
export function htmlInitialRenderMs(availableMs:number){
 return Math.max(1,Math.floor(Math.min(105000,availableMs)));
}
