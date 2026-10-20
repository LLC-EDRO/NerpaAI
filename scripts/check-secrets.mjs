import {spawnSync} from 'node:child_process';
import {readFileSync, existsSync} from 'node:fs';
import {resolve, basename} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
function git(args, input) {
  const result = spawnSync('git', args, {cwd: root, input, maxBuffer: 128 * 1024 * 1024, windowsHide: true});
  if (result.error || result.status !== 0) throw new Error('Cannot inspect Git objects');
  return result.stdout;
}
const split = bytes => bytes.toString('utf8').split('\0').filter(Boolean);
const mode = process.argv[2] || '--worktree';
const findings = new Set();
const knownSecrets = new Set();
const secretName = /(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET|PROJECT_ID)$/i;
const placeholder = value => !value || value.length < 10 ||
  /^(?:test(?:[-_]|$)|fake(?:[-_]|$)|dummy(?:[-_]|$)|example(?:[-_]|$)|placeholder|changeme|your[_-]|<|\$|process\.|engineEnv\.|config\.|string$|undefined$|null$)/i.test(value) ||
  value.includes('${') || /^([x*])\1+$/i.test(value);

// Compare against actual local secrets without embedding or printing them.
for (const path of ['.env', '.env.local', 'backend/.env', 'backend/.env.inference.local']) {
  const file = resolve(root, path);
  if (!existsSync(file)) continue;
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([\w-]+)[ \t]*=[ \t]*(.*)$/.exec(line);
    if (!match || !secretName.test(match[1])) continue;
    const value = match[2].trim().replace(/^(['"])(.*)\1$/, '$2');
    if (!placeholder(value)) knownSecrets.add(value);
  }
}

function privatePath(path) {
  const normalized = path.replaceAll('\\', '/'), name = basename(normalized);
  if (/^\.env(?:\.|$)|\.env$|\.env\.(?:example|sample|template)$|^env\.(?:example|sample|template)$/i.test(name)) return true;
  return /(?:^|\/)(?:node_modules|dist|\.venv|venv|__pycache__|\.ssh|\.aws|secrets|work|outputs|backups?)\//i.test(normalized) ||
    /(?:^|\/)backend\/(?:data|fonts)\//i.test(normalized) ||
    /\.(?:pem|key|p12|pfx|log|pyc|tmp)$/i.test(name) ||
    /^(?:\.npmrc|\.pypirc|\.netrc|credentials\.json|service-account.*\.json)$/i.test(name);
}
function inspect(path, bytes, enforcePath = true) {
  if (enforcePath && privatePath(path)) findings.add(`${path}: private or generated file`);
  const text = bytes.toString('utf8');
  for (const secret of knownSecrets) if (text.includes(secret)) findings.add(`${path}: local credential`);
  if (bytes.includes(0) || bytes.length > 5 * 1024 * 1024) return;
  const report = (index, kind) => findings.add(`${path}:${text.slice(0, index).split('\n').length}: ${kind}`);
  for (const match of text.matchAll(/-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,})\b/g))
    report(match.index, 'private key or provider token');
  const syntheticTestKey = value => /(?:^|\/)test\//.test(path) && /^[a-z]+(?:-[a-z]+){1,10}$/.test(value);
  const assignments = /\b([\w-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|token))["']?[ \t]*[:=][ \t]*(["'`])([^"'`\r\n]*)\2/gi;
  for (const match of text.matchAll(assignments)) {
    const value = match[3];
    if (!placeholder(value) && !(syntheticTestKey(value) && /api[_-]?key$/i.test(match[1])) && /^[A-Za-z0-9_./+=~-]{12,}$/.test(value)) report(match.index, 'credential assignment');
  }
  for (const match of text.matchAll(/^[ \t]*(?:export[ \t]+)?([A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET))[ \t]*[:=][ \t]*([A-Za-z0-9_./+=~-]{12,})[ \t]*$/gm))
    if (!placeholder(match[2])) report(match.index, 'unquoted credential assignment');
  for (const match of text.matchAll(/\bBearer[ \t]+([A-Za-z0-9._~+/-]+=*)/g))
    if (!placeholder(match[1]) && !syntheticTestKey(match[1]) && match[1].length >= 16) report(match.index, 'literal bearer token');
  for (const match of text.matchAll(/(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|https?):\/\/([^\s/:]+):([^\s/@]+)@([^\s/'"]+)/g))
    if (!placeholder(match[2]) && !/(?:^|\.)(?:example|invalid|test)(?:[.:]|$)/i.test(match[3])) report(match.index, 'password in URL');
}

function inspectObjects(revisions) {
  const objects = new Map();
  for (const line of git(['rev-list', '--objects', ...revisions]).toString('utf8').trim().split('\n')) {
    const space = line.indexOf(' ');
    if (space > 0) objects.set(line.slice(0, space), line.slice(space + 1));
  }
  if (!objects.size) return;
  const batch = git(['cat-file', '--batch'], [...objects.keys()].join('\n') + '\n');
  let at = 0;
  while (at < batch.length) {
    const end = batch.indexOf(10, at);
    if (end < 0) throw new Error('Incomplete Git object stream');
    const [id, type, sizeText] = batch.subarray(at, end).toString('ascii').split(' '), size = Number(sizeText);
    if (!Number.isSafeInteger(size) || size < 0 || end + 1 + size >= batch.length) throw new Error('Invalid Git object stream');
    if (type === 'blob') inspect(objects.get(id) || id, batch.subarray(end + 1, end + 1 + size), false);
    at = end + size + 2;
  }
  inspect('commit messages', git(['log', '--format=%B', ...revisions]), false);
}

try {
  if (mode === '--staged') {
    for (const path of split(git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'])))
      inspect(path, git(['show', `:${path}`]));
  } else if (mode === '--history') {
    inspectObjects(['--all']);
  } else if (mode === '--push') {
    const lines = readFileSync(0, 'utf8').trim().split('\n').filter(Boolean);
    for (const line of lines) {
      const [, local, , remote] = line.trim().split(/\s+/);
      if (/^0+$/.test(local)) continue;
      if (!/^[a-f0-9]{40,64}$/.test(local) || !/^[a-f0-9]{40,64}$/.test(remote)) throw new Error('Invalid push reference');
      for (const path of split(git(['ls-tree', '-r', '--name-only', '-z', local])))
        if (privatePath(path)) findings.add(`${path}: private or generated file in pushed tree`);
      inspectObjects(/^0+$/.test(remote) ? [local] : [local, `^${remote}`]);
    }
  } else if (mode === '--worktree') {
    for (const path of new Set(split(git(['ls-files', '--cached', '--others', '--exclude-standard', '-z'])))) {
      const file = resolve(root, path);
      if (existsSync(file)) inspect(path, readFileSync(file));
    }
  } else throw new Error('Unsupported scan mode');
  if (findings.size) {
    console.error('Git operation blocked. Review these files; secret values are never printed:');
    for (const finding of findings) console.error(`- ${finding}`);
    process.exitCode = 1;
  } else console.log('Secret scan: no findings.');
} catch {
  console.error('Secret scan could not inspect Git safely; operation blocked.');
  process.exitCode = 1;
}
