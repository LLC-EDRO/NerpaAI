import {createHash, randomUUID} from 'node:crypto';
import {readFile, writeFile, mkdir, readdir, rm} from 'node:fs/promises';
import {join, resolve, relative, isAbsolute} from 'node:path';
import {projectDir, readJson, writeJson} from '../../store.js';
import {HttpError} from '../../errors.js';
import {dataSourceSchema, type PresentationDataSource} from '../engine/data-contract.js';
import {parsePresentationData} from './parse.js';
import {analyzePresentationData} from './analyze.js';

function folder(project: string, source: string) {
  if (!/^[a-f0-9-]{36}$/.test(source)) throw new HttpError(404, 'Источник данных не найден', 'data_not_found');
  const root = resolve(projectDir(project), 'data-sources'), directory = resolve(root, source);
  const inside = relative(root, directory);
  if (!inside || inside.startsWith('..') || isAbsolute(inside)) throw new HttpError(404, 'Источник данных не найден', 'data_not_found');
  return directory;
}
let parsing = 0;
export async function uploadProjectData(project: string, bytes: Buffer, name: string, signal?: AbortSignal) {
  if (parsing >= 4) throw new HttpError(429, 'Дождитесь разбора предыдущих файлов', 'data_busy');
  parsing++;
  try {
    if ((await listProjectData(project)).length >= 6) throw new HttpError(400, 'Максимум 6 файлов данных на проект', 'data_source_limit');
    const parsed = await parsePresentationData(bytes, encodeURIComponent(name), signal);
    const id = randomUUID(), directory = folder(project, id);
    const receipt = analyzePresentationData(id, parsed.fileName, createHash('sha256').update(bytes).digest('hex'), parsed.tables);
    signal?.throwIfAborted();
    await mkdir(directory, {recursive: true, mode: 0o700});
    await writeFile(join(directory, 'source'), bytes, {mode: 0o600});
    await writeJson(join(directory, 'receipt.json'), receipt);
    return receipt;
  } finally { parsing--; }
}

export async function resolveProjectData(project: string, ids?: string[]): Promise<PresentationDataSource[]> {
  if (ids && (ids.length > 6 || new Set(ids).size !== ids.length))
    throw new HttpError(400, 'Выберите до 6 различных источников', 'data_source_limit');
  const values = ids || (await listProjectData(project)).map(s => s.id);
  return Promise.all(values.map(async id => {
    try {
      const directory = folder(project, id), receipt = dataSourceSchema.parse(await readJson(join(directory, 'receipt.json')));
      const digest = createHash('sha256').update(await readFile(join(directory, 'source'))).digest('hex');
      if (receipt.id !== id || receipt.sha256 !== digest) throw new HttpError(409, 'Исходные данные изменились. Загрузите файл повторно.', 'data_source_changed');
      return receipt;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') throw new HttpError(404, 'Источник данных не найден в этом проекте', 'data_not_found');
      throw error;
    }
  }));
}

export async function listProjectData(project: string): Promise<PresentationDataSource[]> {
  let ids: string[];
  try { ids = await readdir(join(projectDir(project), 'data-sources')); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error; }
  return Promise.all(ids.filter(id => /^[a-f0-9-]{36}$/.test(id)).sort().map(async id =>
    dataSourceSchema.parse(await readJson(join(folder(project, id), 'receipt.json')))));
}

export async function deleteProjectData(project: string, id: string) {
  // Both UUID components are checked before resolving/removing a source folder.
  const directory = folder(project, id);
  await rm(directory, {recursive: true, force: true});
}
