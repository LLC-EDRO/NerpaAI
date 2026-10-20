import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, win32 } from 'node:path';
import {classifyDockerFailure,createDockerImageProbe,DockerRuntimeError,resolveDockerBinary,type DockerFailureReason,type DockerProbeExec} from '../../src/custom-presentations/engine/docker-runtime.js';


const id = 'sha256:' + 'a'.repeat(64);
const options = { image: 'nerpa-pptx-sandbox:2', env: {}, contextKey: 'fixture', platform: 'linux' as const };

test('Windows selects the installed Docker Desktop executable rather than an extensionless PATH entry', () => {
  const expected = win32.join('C:\\Program Files', 'Docker', 'Docker', 'resources', 'bin', 'docker.exe');
  const inspected: string[] = [];
  assert.equal(resolveDockerBinary({ platform: 'win32', env: { ProgramFiles: 'C:\\Program Files' }, exists: path => {
    inspected.push(path); return path === expected;
  } }), expected);
  assert.deepEqual(inspected, [expected]);
  assert.equal(resolveDockerBinary({ platform: 'win32', env: {}, exists: () => false }), 'docker.exe');
  assert.equal(resolveDockerBinary({ platform: 'win32', env: { ProgramFiles: 'C:\\Other' }, exists: () => false }), 'docker.exe');
});

test('an explicit Docker binary is honored and Unix retains its docker default', () => {
  assert.equal(resolveDockerBinary({ platform: 'win32', env: { PRESENTATION_DOCKER_BIN: 'D:\\Tools\\custom.exe' }, exists: () => { throw Error('must not inspect'); } }), 'D:\\Tools\\custom.exe');
  assert.equal(resolveDockerBinary({ platform: 'linux', env: {} }), 'docker');
  assert.equal(resolveDockerBinary({ platform: 'darwin', env: {} }), 'docker');
});

test('24 concurrent probes inspect once and return the verified immutable image ID', async () => {
  let calls = 0, release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const probe = createDockerImageProbe({ exec: async (binary, args, settings) => {
    calls++;
    assert.equal(binary, 'docker');
    assert.deepEqual(args, ['image', 'inspect', '--format', '{{.Id}}', options.image]);
    assert.equal(settings.timeout, 5_000); assert.equal(settings.maxBuffer, 4096); assert.equal(settings.windowsHide, true);
    await gate;
    return { stdout: id + '\n' };
  } });
  const pending = Array.from({ length: 24 }, () => probe({ ...options, platform: 'linux' }));
  await Promise.resolve(); assert.equal(calls, 1);
  release();
  assert.deepEqual(await Promise.all(pending), Array(24).fill(id));
  assert.equal(await probe({ ...options, platform: 'linux' }), id);
  assert.equal(calls, 1);
});

test('positive cache expires and failures are evicted rather than poisoning the namespace', async () => {
  let time = 100, calls = 0;
  const probe = createDockerImageProbe({ now: () => time, cacheMs: 30, exec: async () => {
    calls++; if (calls === 2) throw Object.assign(Error('No such image'), { code: 1 });
    return { stdout: id };
  } });
  assert.equal(await probe(options), id);
  time += 29; assert.equal(await probe(options), id); assert.equal(calls, 1);
  time++; await assert.rejects(probe(options), (error: unknown) => error instanceof DockerRuntimeError && error.reason === 'image_missing');
  assert.equal(await probe(options), id); assert.equal(calls, 3);
});

test('binary, image and effective Docker context/environment changes have separate cache namespaces', async () => {
  let calls = 0;
  const probe = createDockerImageProbe({ exec: async () => { calls++; return { stdout: id }; } });
  await probe(options);
  const variants = [
    { binary: 'other-docker' }, { image: 'other:2' }, { contextKey: 'new-context-file' },
    ...['DOCKER_CONTEXT', 'DOCKER_HOST', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'DOCKER_API_VERSION', 'DOCKER_TLS', 'PATH', 'PATHEXT'].map(key => ({ env: { [key]: 'different' } })),
  ];
  for (const variant of variants) await probe({ ...options, ...variant });
  assert.equal(calls, variants.length + 1);
  await probe(options); assert.equal(calls, variants.length + 1);
});

test('Docker Desktop context file stat changes invalidate cache without reading its credential contents', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'nerpa-docker-context-'));
  try {
    const file = join(folder, 'config.json'); let calls = 0;
    const probe = createDockerImageProbe({ exec: async () => { calls++; return { stdout: id }; } });
    const input = { image: options.image, platform: process.platform, env: { DOCKER_CONFIG: folder } };
    await writeFile(file, '{"currentContext":"one"}');
    await probe(input); await probe(input); assert.equal(calls, 1);
    await writeFile(file, '{"currentContext":"different-context"}');
    await probe(input); assert.equal(calls, 2);
  } finally { await rm(folder, { recursive: true, force: true }); }
});

test('missing image and missing executable never retry, build, pull or expose raw diagnostics', async () => {
  for (const [error, reason] of [
    [Object.assign(Error('spawn C:\\private\\tools\\docker.exe ENOENT'), { code: 'ENOENT' }), 'binary_missing'],
    [Object.assign(Error('No such image: registry.private/token:secret'), { code: 1 }), 'image_missing'],
  ] as const) {
    let calls = 0, waits = 0;
    const probe = createDockerImageProbe({ exec: async (_binary, args) => {
      calls++; assert.equal(args[0], 'image'); assert.equal(args[1], 'inspect'); throw error;
    }, wait: async () => { waits++; } });
    await assert.rejects(probe(options), (result: unknown) => {
      assert.ok(result instanceof DockerRuntimeError); assert.equal(result.reason, reason);
      assert.doesNotMatch(result.message + JSON.stringify(result), /private|secret|token|tools/i);
      assert.equal('cause' in result, false); return true;
    });
    assert.equal(calls, 1); assert.equal(waits, 0);
  }
});

test('daemon startup and inspection timeouts retry once within a bounded probe', async () => {
  for (const error of [Error('Cannot connect to the Docker daemon. Is the docker daemon running?'), Object.assign(Error('timeout'), { code: 'ETIMEDOUT' })]) {
    let calls = 0; const waits: number[] = [];
    const probe = createDockerImageProbe({ exec: async () => {
      if (++calls === 1) throw error; return { stdout: id };
    }, wait: async ms => { waits.push(ms); } });
    assert.equal(await probe(options), id); assert.equal(calls, 2); assert.deepEqual(waits, [150]);
  }
});

test('a persistently unavailable daemon stops after two inspections and may recover on a later request', async () => {
  let calls = 0, unavailable = true;
  const probe = createDockerImageProbe({ exec: async () => {
    calls++; if (unavailable) throw Error('error during connect: connection refused'); return { stdout: id };
  }, wait: async () => {} });
  await assert.rejects(probe(options), (error: unknown) => error instanceof DockerRuntimeError && error.reason === 'daemon_unavailable');
  assert.equal(calls, 2);
  unavailable = false; assert.equal(await probe(options), id); assert.equal(calls, 3);
});

test('permissions, Windows engine mode and malformed inspection results are not blindly retried', async () => {
  const cases: Array<{ execute: DockerProbeExec; reason: DockerFailureReason }> = [
    { execute: async () => { throw Object.assign(Error('private endpoint denied'), { stderr: 'Access is denied.' }); }, reason: 'permission_denied' },
    { execute: async () => { throw Error('image operating system "linux" cannot be used on this platform'); }, reason: 'windows_engine' },
    { execute: async () => ({ stdout: 'sha256:invalid' }), reason: 'probe_failed' },
    { execute: async () => { throw Error('unrecognized private failure'); }, reason: 'probe_failed' },
  ];
  for (const item of cases) {
    let calls = 0;
    const probe = createDockerImageProbe({ exec: async (...args) => { calls++; return item.execute(...args); }, wait: async () => { assert.fail('must not retry'); } });
    await assert.rejects(probe(options), (error: unknown) => error instanceof DockerRuntimeError && error.reason === item.reason);
    assert.equal(calls, 1);
  }
});

test('classifies bounded native-run stderr and handles an absent error without diagnostic leakage', () => {
  assert.equal(classifyDockerFailure(null), null);
  assert.equal(classifyDockerFailure(undefined), null);
  assert.equal(classifyDockerFailure({ code: 125, stderr: Buffer.from('No such image: private') }), 'image_missing');
  assert.equal(classifyDockerFailure({ code: 125, stderr: 'open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.' }), 'daemon_unavailable');
  assert.equal(classifyDockerFailure({ code: 125, stderr: 'permission denied while trying to connect to Docker' }), 'permission_denied');
  assert.equal(classifyDockerFailure({ killed: true, signal: 'SIGTERM' }), 'probe_timeout');
  assert.equal(classifyDockerFailure({ stderr: 'x509: certificate signed by unknown authority' }), 'probe_failed');
});

test('invalid configured images fail before invoking Docker and surrounding whitespace is normalized', async () => {
  let calls = 0;
  const probe = createDockerImageProbe({ exec: async (_binary, args) => { calls++; assert.equal(args.at(-1), options.image); return { stdout: id }; } });
  for (const image of ['', '  ', 'bad image:2', '--help', 'bad\nimage']) await assert.rejects(probe({ ...options, image }));
  assert.equal(calls, 0);
  assert.equal(await probe({ ...options, image: '  ' + options.image + '  ' }), id); assert.equal(calls, 1);
});

test('Windows stale Resource Saver 404 wakes only through an exact filtered list before one authoritative inspection', async () => {
  const calls: string[][] = [], env = { DOCKER_CONTEXT: 'explicit-desktop', DOCKER_HOST: 'private-endpoint' };
  const probe = createDockerImageProbe({ exec: async (binary, args, settings) => {
    assert.equal(binary, 'D:\\Tools\\docker.exe'); assert.deepEqual(settings.env, env);
    assert.equal(settings.timeout, 5_000); assert.equal(settings.maxBuffer, 4096);
    calls.push(args);
    if (calls.length === 1) throw Error('No such image: nerpa-pptx-sandbox:2');
    if (args[1] === 'ls') return { stdout: JSON.stringify({ Repository: 'nerpa-pptx-sandbox', Tag: '2', Digest: id, ID: id }) + '\n' };
    return { stdout: id };
  }, wait: async () => { assert.fail('recovery does not poll or sleep'); } });
  const input = { ...options, platform: 'win32' as const, binary: 'D:\\Tools\\docker.exe', env };
  assert.deepEqual(await Promise.all(Array.from({ length: 24 }, () => probe(input))), Array(24).fill(id));
  assert.deepEqual(calls, [
    ['image', 'inspect', '--format', '{{.Id}}', options.image],
    ['image', 'ls', '--no-trunc', '--digests', '--filter', `reference=${options.image}`, '--format', '{{json .}}'],
    ['image', 'inspect', '--format', '{{.Id}}', options.image],
  ]);
  assert.equal(await probe(input), id); assert.equal(calls.length, 3);
});

test('Windows does not retry a genuinely missing, mismatched or unverified image', async () => {
  for (const stdout of [
    '', 'invalid-json',
    JSON.stringify({ Repository: 'nerpa-pptx-sandbox', Tag: '3', ID: id }),
    JSON.stringify({ Repository: 'another-image', Tag: '2', ID: id }),
    JSON.stringify({ Repository: 'nerpa-pptx-sandbox', Tag: '2', ID: 'truncated-id' }),
    JSON.stringify({ Repository: 'docker.io/library/nerpa-pptx-sandbox', Tag: '2', ID: id }),
  ]) {
    const calls: string[][] = [];
    const probe = createDockerImageProbe({ exec: async (_binary, args) => {
      calls.push(args); if (args[1] === 'inspect') throw Error('No such image'); return { stdout };
    } });
    await assert.rejects(probe({ ...options, platform: 'win32' }), (error: unknown) => error instanceof DockerRuntimeError && error.reason === 'image_missing');
    assert.deepEqual(calls.map(args => args[1]), ['inspect', 'ls']);
  }
});

test('Windows Resource Saver recovery still stops if the exact reference remains unavailable after waking', async () => {
  const calls: string[][] = [];
  const probe = createDockerImageProbe({ exec: async (_binary, args) => {
    calls.push(args);
    if (args[1] === 'inspect') throw Error('No such image');
    return { stdout: JSON.stringify({ Repository: 'nerpa-pptx-sandbox', Tag: '2', ID: id }) };
  } });
  await assert.rejects(probe({ ...options, platform: 'win32' }), (error: unknown) => error instanceof DockerRuntimeError && error.reason === 'image_missing');
  assert.deepEqual(calls.map(args => args[1]), ['inspect', 'ls', 'inspect']);
});

test('Windows Resource Saver list failures retain safe classification and never retry the list', async () => {
  for (const [failure, reason] of [
    [Object.assign(Error('private endpoint timeout'), { code: 'ETIMEDOUT' }), 'probe_timeout'],
    [Object.assign(Error('Access is denied at private endpoint'), { code: 'EACCES' }), 'permission_denied'],
  ] as const) {
    const calls: string[][] = [];
    const probe = createDockerImageProbe({ exec: async (_binary, args) => {
      calls.push(args); if (args[1] === 'inspect') throw Error('No such image'); throw failure;
    } });
    await assert.rejects(probe({ ...options, platform: 'win32' }), (error: unknown) => {
      assert.ok(error instanceof DockerRuntimeError); assert.equal(error.reason, reason);
      assert.doesNotMatch(error.message, /private|endpoint/); return true;
    });
    assert.deepEqual(calls.map(args => args[1]), ['inspect', 'ls']);
  }
});

test('exact filtered-list proof supports implicit latest and configured digest references without selecting another row', async () => {
  for (const image of ['registry.example:5000/private/pptx', `registry.example:5000/private/pptx@${id}`]) {
    const calls: string[][] = [];
    const probe = createDockerImageProbe({ exec: async (_binary, args) => {
      calls.push(args);
      if (calls.length === 1) throw Error('No such image');
      if (args[1] === 'ls') {
        assert.equal(args[5], `reference=${image}`);
        return { stdout: JSON.stringify({ Repository: 'registry.example:5000/private/pptx', Tag: 'latest', Digest: id, ID: id }) };
      }
      assert.equal(args.at(-1), image); return { stdout: id };
    } });
    assert.equal(await probe({ ...options, image, platform: 'win32' }), id);
    assert.deepEqual(calls.map(args => args[1]), ['inspect', 'ls', 'inspect']);
  }
});

test('Linux missing-image probes never invoke the Windows Desktop wake path', async () => {
  const calls: string[][] = [];
  const probe = createDockerImageProbe({ exec: async (_binary, args) => { calls.push(args); throw Error('No such image'); } });
  await assert.rejects(probe(options), (error: unknown) => error instanceof DockerRuntimeError && error.reason === 'image_missing');
  assert.deepEqual(calls.map(args => args[1]), ['inspect']);
});

test('Windows binary selection honors mixed-case environment names and Node duplicate-key precedence', () => {
  assert.equal(resolveDockerBinary({ platform: 'win32', env: { presentation_docker_bin: String.raw`  D:\Tools\custom.exe  ` }, exists: () => { throw Error('must not inspect'); } }), String.raw`D:\Tools\custom.exe`);
  for (const name of ['pRoGrAmW6432', 'programfiles']) {
    const expected = win32.join(String.raw`D:\Applications`, 'Docker', 'Docker', 'resources', 'bin', 'docker.exe');
    assert.equal(resolveDockerBinary({ platform: 'win32', env: { [name]: String.raw`D:\Applications` }, exists: path => path === expected }), expected);
  }
  const expected = win32.join(String.raw`C:\First`, 'Docker', 'Docker', 'resources', 'bin', 'docker.exe');
  assert.equal(resolveDockerBinary({ platform: 'win32', env: { ProgramFiles: String.raw`C:\Second`, PROGRAMFILES: String.raw`C:\First` }, exists: path => path === expected }), expected);
  assert.equal(resolveDockerBinary({ platform: 'linux', env: { presentation_docker_bin: '/ignored' } }), 'docker');
});

test('Windows case-insensitive Docker environment values isolate the cache without rewriting the child environment', async () => {
  const alternate = 'sha256:' + 'b'.repeat(64);
  for (const name of ['DOCKER_CONTEXT', 'DOCKER_HOST', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'DOCKER_API_VERSION', 'DOCKER_TLS', 'PATH', 'PATHEXT']) {
    const firstEnv = { [name.toLowerCase()]: 'first' }, secondEnv = { [name.toLowerCase()]: 'second' };
    const received: NodeJS.ProcessEnv[] = [];
    const probe = createDockerImageProbe({ exec: async (_binary, _args, settings) => {
      received.push(settings.env);
      return { stdout: settings.env[name.toLowerCase()] === 'first' ? id : alternate };
    } });
    const input = { ...options, platform: 'win32' as const, binary: 'fixture.exe' };
    assert.equal(await probe({ ...input, env: firstEnv }), id, name);
    assert.equal(await probe({ ...input, env: secondEnv }), alternate, name);
    assert.equal(await probe({ ...input, env: { [name]: 'first' } }), id, name);
    assert.deepEqual(received, [firstEnv, secondEnv], name);
  }
});

test('Windows cache keys use the first lexicographic duplicate environment key like execFile', async () => {
  let calls = 0;
  const probe = createDockerImageProbe({ exec: async (_binary, _args, settings) => {
    calls++;
    assert.equal(settings.env.DOCKER_HOST, calls === 1 ? 'first' : 'second');
    assert.equal(settings.env.docker_host, calls === 1 ? 'ignored-one' : 'ignored-three');
    return { stdout: id };
  } });
  const input = { ...options, platform: 'win32' as const, binary: 'fixture.exe' };
  await probe({ ...input, env: { docker_host: 'ignored-one', DOCKER_HOST: 'first' } });
  await probe({ ...input, env: { docker_host: 'ignored-two', DOCKER_HOST: 'first' } });
  assert.equal(calls, 1);
  await probe({ ...input, env: { docker_host: 'ignored-three', DOCKER_HOST: 'second' } });
  assert.equal(calls, 2);
});

test('Windows mixed-case config and home names retain context-file stat invalidation', { skip: process.platform !== 'win32' }, async () => {
  for (const name of ['dOcKeR_cOnFiG', 'uSeRpRoFiLe']) {
    const folder = await mkdtemp(join(tmpdir(), 'nerpa-docker-case-'));
    try {
      const configFolder = name === 'uSeRpRoFiLe' ? join(folder, '.docker') : folder;
      await mkdir(configFolder, { recursive: true });
      const file = join(configFolder, 'config.json'); let calls = 0;
      const probe = createDockerImageProbe({ exec: async () => { calls++; return { stdout: id }; } });
      const input = { image: options.image, binary: 'fixture.exe', platform: 'win32' as const, env: { [name]: folder } };
      await writeFile(file, '{"currentContext":"one"}');
      await probe(input); await probe(input); assert.equal(calls, 1, name);
      await writeFile(file, '{"currentContext":"different-context"}');
      await probe(input); assert.equal(calls, 2, name);
    } finally { await rm(folder, { recursive: true, force: true }); }
  }
});
