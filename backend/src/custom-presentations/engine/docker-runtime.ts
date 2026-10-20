import { execFile } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, win32 } from 'node:path';
import { promisify } from 'node:util';

export type DockerFailureReason = 'binary_missing' | 'daemon_unavailable' | 'image_missing'
  | 'probe_timeout' | 'windows_engine' | 'permission_denied' | 'probe_failed';

const messages: Record<DockerFailureReason, string> = {
  binary_missing: 'Docker executable is unavailable.',
  daemon_unavailable: 'Docker daemon is unavailable.',
  image_missing: 'The configured Docker image is unavailable.',
  probe_timeout: 'Docker image inspection timed out.',
  windows_engine: 'Docker is not using a compatible Linux engine.',
  permission_denied: 'Access to Docker was denied.',
  probe_failed: 'Docker image inspection failed.',
};

/** Deliberately excludes the original command, stderr, private paths and daemon URL. */
export class DockerRuntimeError extends Error {
  readonly name = 'DockerRuntimeError';
  constructor(readonly reason: DockerFailureReason) { super(messages[reason]); }
}

export const classifiedDockerError = (reason: DockerFailureReason) => new DockerRuntimeError(reason);

function boundedText(value: unknown) {
  return (typeof value === 'string' ? value : Buffer.isBuffer(value) ? value.toString('utf8') : '').slice(0, 16_384);
}

/** Safe classification can also be used for a bounded stderr from `docker run`. */
export function classifyDockerFailure(error: unknown): DockerFailureReason | null {
  if (error == null) return null;
  if (error instanceof DockerRuntimeError) return error.reason;
  const detail = typeof error === 'object' ? error as {
    code?: unknown; message?: unknown; stderr?: unknown; killed?: unknown; signal?: unknown;
  } : {};
  const code = boundedText(detail.code);
  const text = [boundedText(detail.stderr), boundedText(detail.message), boundedText(error)].join('\n');
  if (code === 'ENOENT') return 'binary_missing';
  if (/no such image|no such object:\s*(?:image\s+)?|image[^\r\n]*(?:not found|does not exist)|reference[^\r\n]*does not exist/i.test(text)) return 'image_missing';
  if (code === 'EACCES' || code === 'EPERM' || /access (?:is )?denied|permission denied|operation not permitted/i.test(text)) return 'permission_denied';
  if (/image operating system ["']?linux["']? cannot be used|linux containers? (?:are |is )?not supported|unsupported (?:os|operating system)[^\r\n]*windows|unknown server OS:\s*windows|windows containers? mode/i.test(text)) return 'windows_engine';
  if (code === 'ETIMEDOUT' || code === 'ERR_CHILD_PROCESS_TIMEOUT' || detail.killed === true || /\b(?:timed out|timeout exceeded|context deadline exceeded)\b/i.test(text)) return 'probe_timeout';
  if (/cannot connect to (?:the )?docker daemon|is (?:the )?docker daemon running|error during connect|connection (?:refused|reset)|daemon (?:is )?(?:unavailable|starting)|server is shutting down|service unavailable|unexpected EOF/i.test(text)
    || /(?:docker[^\r\n]*pipe|pipe[^\r\n]*docker)[^\r\n]*(?:cannot find|not found|does not exist)/i.test(text)) return 'daemon_unavailable';
  return 'probe_failed';
}

export interface DockerBinaryOptions {
  env?: NodeJS.ProcessEnv;
  platform?: NodeJS.Platform;
  exists?: (path: string) => boolean;
}

/** Match the first case-insensitive key passed by Node's Windows child-process environment. */
function environmentValue(env: NodeJS.ProcessEnv, name: string, platform: NodeJS.Platform) {
  if (platform !== 'win32') return env[name];
  const normalized = name.toUpperCase();
  const key = Object.keys(env).sort().find(key => key.toUpperCase() === normalized);
  return key === undefined ? undefined : env[key];
}

/** Avoid an extensionless `docker` earlier on Windows PATH shadowing Docker Desktop. */
export function resolveDockerBinary(options: DockerBinaryOptions = {}) {
  const env = options.env ?? process.env, platform = options.platform ?? process.platform;
  const override = environmentValue(env, 'PRESENTATION_DOCKER_BIN', platform)?.trim();
  if (override) return override;
  if (platform !== 'win32') return 'docker';
  const programFiles = environmentValue(env, 'ProgramW6432', platform) || environmentValue(env, 'ProgramFiles', platform);
  if (programFiles) {
    const official = win32.join(programFiles, 'Docker', 'Docker', 'resources', 'bin', 'docker.exe');
    if ((options.exists ?? existsSync)(official)) return official;
  }
  return 'docker.exe';
}

export interface DockerProbeOptions extends DockerBinaryOptions {
  image: string;
  binary?: string;
  /** Injectable stat identity, never the contents of Docker's credential-bearing config. */
  contextKey?: string;
}

export type DockerProbeExec = (binary: string, args: string[], options: {
  timeout: number; maxBuffer: number; env: NodeJS.ProcessEnv; windowsHide: boolean;
}) => Promise<{ stdout: string | Buffer }>;

export interface DockerProbeDependencies {
  exec?: DockerProbeExec;
  now?: () => number;
  wait?: (ms: number) => Promise<void>;
  timeoutMs?: number;
  cacheMs?: number;
}

const dockerEnvironmentKeys = [
  'DOCKER_CONTEXT', 'DOCKER_HOST', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH',
  'DOCKER_API_VERSION', 'DOCKER_TLS', 'PATH', 'PATHEXT',
] as const;

function desktopContextIdentity(env: NodeJS.ProcessEnv, platform: NodeJS.Platform) {
  const path = platform === 'win32' ? win32 : { join };
  const home = environmentValue(env, platform === 'win32' ? 'USERPROFILE' : 'HOME', platform) || homedir();
  const file = path.join(environmentValue(env, 'DOCKER_CONFIG', platform) || path.join(home, '.docker'), 'config.json');
  try {
    const info = statSync(file);
    return JSON.stringify([file, info.mtimeMs, info.size]);
  } catch (error) {
    return JSON.stringify([file, (error as NodeJS.ErrnoException).code || 'unavailable']);
  }
}

const nativeExec = promisify(execFile);

function listsExactImage(stdout: string | Buffer, image: string) {
  // A reference filter can match more than one row. Verify the exact reference,
  // not merely the presence of any image, and never use a listed ID for execution.
  const target = image.includes('@') || image.split('/').at(-1)!.includes(':') ? image : image + ':latest';
  try {
    return boundedText(stdout).split(/\r?\n/).filter(line => line.trim()).some(line => {
      const row: unknown = JSON.parse(line);
      if (!row || typeof row !== 'object') return false;
      const { Repository, Tag, Digest, ID } = row as Record<string, unknown>;
      if (typeof ID !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(ID)) return false;
      if (/^sha256:[a-f0-9]{64}$/.test(image)) return ID === image;
      if (typeof Repository !== 'string') return false;
      return (typeof Tag === 'string' && Tag !== '<none>' && `${Repository}:${Tag}` === target)
        || (typeof Digest === 'string' && /^sha256:[a-f0-9]{64}$/.test(Digest) && `${Repository}@${Digest}` === target);
    });
  } catch { return false; }
}

/** Positive cache and single-flight belong to one probe instance; failures are never cached. */
export function createDockerImageProbe(dependencies: DockerProbeDependencies = {}) {
  const execute: DockerProbeExec = dependencies.exec ?? (async (binary, args, options) => nativeExec(binary, args, options));
  const now = dependencies.now ?? Date.now;
  const wait = dependencies.wait ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const timeout = Math.min(10_000, Math.max(1, dependencies.timeoutMs ?? 5_000));
  const cacheMs = Math.max(0, Math.min(30_000, dependencies.cacheMs ?? 30_000));
  const cache = new Map<string, { id: string; expires: number }>();
  const pending = new Map<string, Promise<string>>();

  return function probe(options: DockerProbeOptions): Promise<string> {
    const env = { ...(options.env ?? process.env) }, platform = options.platform ?? process.platform;
    const binary = options.binary ?? resolveDockerBinary({ env, platform, exists: options.exists });
    const image = options.image.trim();
    if (!image || /^-/.test(image) || /[\s\x00-\x1f\x7f]/.test(image)) return Promise.reject(classifiedDockerError('probe_failed'));
    const key = JSON.stringify([binary, platform, image,
      ...dockerEnvironmentKeys.map(name => environmentValue(env, name, platform) ?? null),
      options.contextKey ?? desktopContextIdentity(env, platform)]);
    const saved = cache.get(key);
    if (saved && saved.expires > now()) return Promise.resolve(saved.id);
    if (saved) cache.delete(key);
    const existing = pending.get(key);
    if (existing) return existing;
    const run = async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const { stdout } = await execute(binary, ['image', 'inspect', '--format', '{{.Id}}', image], {
            timeout, maxBuffer: 4096, env, windowsHide: true,
          });
          const id = boundedText(stdout).trim();
          if (!/^sha256:[a-f0-9]{64}$/.test(id)) throw classifiedDockerError('probe_failed');
          cache.set(key, { id, expires: now() + cacheMs });
          // Context switches must not leave an unbounded set of private environment keys in memory.
          for (const [oldKey, value] of cache) if (value.expires <= now()) cache.delete(oldKey);
          while (cache.size > 64) cache.delete(cache.keys().next().value!);
          return id;
        } catch (error) {
          const reason = classifyDockerFailure(error) ?? 'probe_failed';
          if (attempt === 0 && platform === 'win32' && reason === 'image_missing') {
            // Docker Desktop Resource Saver can serve a stale 404 for inspect
            // without waking the VM. A filtered list reaches the live engine;
            // only proof of this exact reference permits one fresh inspection.
            try {
              const { stdout } = await execute(binary, ['image', 'ls', '--no-trunc', '--digests',
                '--filter', `reference=${image}`, '--format', '{{json .}}'], {
                timeout, maxBuffer: 4096, env, windowsHide: true,
              });
              if (listsExactImage(stdout, image)) continue;
            } catch (listError) {
              throw classifiedDockerError(classifyDockerFailure(listError) ?? 'probe_failed');
            }
          }
          if (attempt === 0 && (reason === 'daemon_unavailable' || reason === 'probe_timeout')) {
            await wait(150);
            continue;
          }
          throw classifiedDockerError(reason);
        }
      }
      throw classifiedDockerError('probe_failed');
    };
    // Starting through a microtask also handles a synchronously throwing injected executor.
    const result = Promise.resolve().then(run).finally(() => pending.delete(key));
    pending.set(key, result);
    return result;
  };
}

/** Inspect a prebuilt image only. Building, pulling and selecting fallback images belong elsewhere. */
export const probeResolvedImage = createDockerImageProbe();
