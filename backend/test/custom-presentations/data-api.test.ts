import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('data API stores project-owned receipts, invalidates plans and denies source substitution', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'nerpa-v3-api-'));
  process.env.DATA_DIR = join(folder, 'projects');
  const {app} = await import('../../src/server.js');
  const store = await import('../../src/store.js');
  const {resolveProjectData} = await import('../../src/custom-presentations/data/store.js');
  const {usesCustomEngine} = await import('../../src/custom-presentations/pipeline.js');
  const first = await store.createProject('custom.pptx'), second = await store.createProject('legacy.pptx');
  first.engineVersion = 'custom-v3'; first.plan = {slides: []}; first.contract = {revision: 0};
  first.result = {slides: 1}; await store.saveProject(first);
  assert.equal(usesCustomEngine(second), false);
  const server = app.listen(0, '127.0.0.1');
  await new Promise<void>(resolve => server.once('listening', resolve));
  const base = `http://127.0.0.1:${(server.address() as {port: number}).port}/api/projects`;
  try {
    const form = new FormData(); form.append('file', new Blob(['<rows><row year="2024" value="1"/><row year="2025" value="2"/></rows>']), 'факты.xml');
    const response = await fetch(`${base}/${first.id}/data`, {method: 'POST', body: form});
    assert.equal(response.status, 201);
    const {source, project} = await response.json() as any;
    assert.equal(source.fileName, 'факты.xml'); assert.equal(project.revision, 1);
    assert.equal(project.plan, undefined); assert.equal(project.contract, undefined); assert.equal(project.result, undefined);
    assert.deepEqual((await resolveProjectData(first.id, [source.id]))[0], source);
    await assert.rejects(resolveProjectData(second.id, [source.id]), (e: any) => e.code === 'data_not_found');
    const data = await fetch(`${base}/${first.id}/data`).then(r => r.json()) as any;
    assert.equal(data.sources.length, 1);
    await writeFile(join(store.projectDir(first.id), 'data-sources', source.id, 'source'), 'changed');
    await assert.rejects(resolveProjectData(first.id, [source.id]), (e: any) => e.code === 'data_source_changed');
    const traversal = await fetch(`${base}/${first.id}/data/not-a-uuid`, {method: 'DELETE'});
    assert.equal(traversal.status, 404);
    const removed = await fetch(`${base}/${first.id}/data/${source.id}`, {method: 'DELETE'});
    assert.equal(removed.status, 200);
    assert.equal((await store.getProject(first.id)).revision, 2);
    assert.deepEqual(await fetch(`${base}/${first.id}/data`).then(r => r.json()), {sources: []});
    const blocked = await fetch(`${base}/${first.id}/data`, {headers: {Origin: 'https://example.com'}});
    assert.equal(blocked.status, 403);
  } finally {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    await rm(folder, {recursive: true, force: true});
  }
});
