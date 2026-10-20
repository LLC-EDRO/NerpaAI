import test from "node:test";
import assert from "node:assert/strict";
import {providerJson} from '../../src/custom-presentations/engine/provider-request.js';




const response = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status });
const request = (fetcher: typeof fetch, signal?: AbortSignal) =>
  providerJson({
    url: "https://provider.invalid",
    init: {},
    timeoutMs: 1000,
    prefix: "llm",
    model: "test",
    delayMs: 0,
    fetcher,
    signal,
  });

test("delivery recovers from network, throttling and malformed response with a bounded budget", async () => {
  let calls = 0;
  assert.deepEqual(
    await request((async () => {
      calls++;
      if (calls === 1) throw new TypeError("network");
      if (calls === 2)
        return response(429, { error: { code: "rate_limit_exceeded" } });
      return response(200, { ok: true });
    }) as typeof fetch),
    { ok: true },
  );
  assert.equal(calls, 3);
  calls = 0;
  assert.deepEqual(
    await request((async () =>
      ++calls === 1
        ? new Response("broken json")
        : response(200, { ok: true })) as typeof fetch),
    { ok: true },
  );
  assert.equal(calls, 2);
});

test("credentials, quota and permanent errors do not retry; outages stop after three requests", async () => {
  for (const [status, code, expected] of [
    [401, "invalid_api_key", 1],
    [400, "invalid_request", 1],
    [429, "insufficient_quota", 1],
    [503, "unavailable", 3],
  ] as const) {
    let calls = 0;
    await assert.rejects(
      request((async () => {
        calls++;
        return response(status, { error: { code } });
      }) as typeof fetch),
      (e: any) => e.code === (code==='insufficient_quota'?'llm_quota_exhausted':'llm_http') && e.details.status === status,
    );
    assert.equal(calls, expected);
  }
});

test('exhausted delivery retains a safe nested transport cause and terminal diagnostics',async()=>{
  const events:any[]=[];let calls=0;
  await assert.rejects(providerJson({url:'https://provider.invalid',init:{},timeoutMs:1000,prefix:'llm',model:'test',delayMs:0,
    fetcher:(async()=>{calls++;throw new TypeError('private URL and token',{cause:Object.assign(new Error('private request'),{code:'ECONNRESET'})});}) as typeof fetch,
    onFailure:async event=>{events.push(event);},
  }),(e:any)=>{
    assert.equal(e.code,'llm_transport');assert.deepEqual(e.details.transport,{phase:'connect',type:'TypeError',code:'ECONNRESET'});
    assert.ok(!JSON.stringify(e.details).includes('private'));return true;
  });
  assert.equal(calls,3);assert.deepEqual(events.map(e=>e.exhausted),[false,false,true]);
  assert.ok(events.every(e=>e.transport.code==='ECONNRESET'));
});

test('a body interrupted after headers is distinguished from a connection failure',async()=>{
  const events:any[]=[];
  await assert.rejects(providerJson({url:'https://provider.invalid',init:{},timeoutMs:1000,prefix:'llm',model:'test',delayMs:0,
    fetcher:(async()=>({ok:true,status:200,json:async()=>{throw Object.assign(new Error('secret body'),{code:'UND_ERR_SOCKET'});}})) as any,
    onFailure:async event=>{events.push(event);},
  }),(e:any)=>e.details.transport.phase==='response'&&e.details.transport.code==='UND_ERR_SOCKET');
  assert.equal(events.at(-1).status,200);assert.equal(events.at(-1).exhausted,true);
});

test("cancellation interrupts delivery instead of launching another request", async () => {
  const c = new AbortController();
  let calls = 0;
  await assert.rejects(
    request(
      (async () => {
        calls++;
        c.abort();
        throw new TypeError("network");
      }) as typeof fetch,
      c.signal,
    ),
    (e: any) => e.name === "AbortError",
  );
  assert.equal(calls, 1);
});

