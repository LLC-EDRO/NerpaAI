import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp, rm, readFile, readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('V3 uses local Ollama, retains JSON repair and token receipts, and propagates cancellation', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'nerpa-v3-local-'));
  process.env.DATA_DIR = join(folder, 'projects');
  const calls: any[] = [];
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    calls.push({url: req.url, auth: req.headers.authorization, body: raw ? JSON.parse(raw) : undefined});
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/api/tags') return res.end(JSON.stringify({models: [{name: 'gemma4:12b'}]}));
    res.end(JSON.stringify({choices: [{finish_reason: 'stop', message: {content: '{"ok":true,}'}}],
      usage: {prompt_tokens: 12, completion_tokens: 6}}));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const {port} = server.address() as {port: number};
    const settings = await import('../../src/model-settings.js');
    const {llmJson} = await import('../../src/custom-presentations/engine/llm.js');
    const {withEngineContext} = await import('../../src/custom-presentations/engine/runtime-context.js');
    const {generationBudget} = await import('../../src/custom-presentations/engine/generation-budget.js');
    await settings.saveModelSettings({provider: 'ollama', baseUrl: `http://127.0.0.1:${port}`, textModel: 'gemma4:12b', visionModel: 'gemma4:12b'});
    const result = await llmJson({stage: 'html-author', folder, prompt: 'JSON', payload: {fact: 10}, schema: {type: 'object'}, validate: value => value});
    assert.deepEqual(result, {ok: true});
    const chat = calls.find(c => c.url === '/v1/chat/completions');
    assert.equal(chat.auth, undefined);
    assert.equal(chat.body.model, 'gemma4:12b');
    assert.equal(chat.body.stream, true);
    assert.equal(chat.body.response_format.type, 'json_schema');
    const receipts = await readdir(join(folder, 'llm'));
    const receipt = JSON.parse(await readFile(join(folder, 'llm', receipts[0]), 'utf8'));
    assert.equal(receipt.provider, 'ollama');
    assert.equal(receipt.usage.prompt_tokens, 12);
    const controller = new AbortController();
    await withEngineContext({workspace: folder, signal: controller.signal}, async () => {
      const signal = generationBudget().signal(); controller.abort();
      assert.equal(signal.aborted, true);
      await assert.rejects(llmJson({stage: 'html-author', folder, prompt: 'JSON', payload: {}, validate: v => v}), (e: any) => e.name === 'AbortError');
    });
    assert.equal(calls.filter(c => c.url === '/v1/chat/completions').length, 1);
  } finally {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    await rm(folder, {recursive: true, force: true});
  }
});
