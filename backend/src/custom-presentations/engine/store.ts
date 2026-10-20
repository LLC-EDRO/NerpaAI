import { engineContext } from "./runtime-context.js";
import { mkdir, readFile, writeFile, rename } from "node:fs/promises";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { HttpError } from "./errors.js";
import type { Project } from "./domain.js";
export const dataRoot = resolve(process.env.DATA_DIR || "data/projects");
export function projectDir(id: string) {
  if (!/^[a-f0-9-]{36}$/.test(id))
    throw new HttpError(404, "Проект не найден", "not_found");
  return engineContext()?.workspace ?? join(dataRoot, id);
}
export async function writeJson(path: string, value: unknown) {
  await engineContext()?.writeDocument?.(path, value);
  await writeLocalJson(path,value);
}
async function writeLocalJson(path:string,value:unknown) {
  await mkdir(resolve(path, ".."), { recursive: true, mode: 0o700 });
  const temp = path + "." + randomUUID() + ".tmp";
  // Match PostgreSQL source_text exactly, so verified mirrors avoid downloading
  // the same large JSON again in chunks on every read.
  await writeFile(temp, JSON.stringify(value), { mode: 0o600 });
  await rename(temp, path);
}
/** Diagnostic journals do not delay text/geometry processing. The host drains
 * their separately batched DB writes before completing or releasing a job. */
export async function writeDiagnostic(path:string,value:unknown) {
  const writer=engineContext()?.writeDiagnosticDocument;
  if(!writer)return writeJson(path,value);
  await writeLocalJson(path,value);
  writer(path,value);
}
export async function readJson(path: string) {
  const database = engineContext()?.readDocument;
  if(database){
    const saved=await database(path);
    if(saved!==undefined)return saved;
    throw Object.assign(new Error('Author document not found in PostgreSQL'),{code:'ENOENT'});
  }
  return JSON.parse(await readFile(path, "utf8"));
}
type PendingWrite = { project: Project; waiters: Array<{resolve:()=>void;reject:(error:unknown)=>void}> };
const projectWrites = new Map<string, PendingWrite>();
export async function saveProject(p: Project, message?: string) {
  p.updatedAt = new Date().toISOString();
  if (message) {
    p.message = message;
    p.events.push({ at: p.updatedAt, message });
    p.events = p.events.slice(-80);
  }
  const writeKey = projectDir(p.id);
  let pending = projectWrites.get(writeKey);
  if (!pending) {
    pending = {project:p,waiters:[]};
    projectWrites.set(writeKey,pending);
    const queue=pending;
    setTimeout(()=>{void (async()=>{
      while(queue.waiters.length){
        const batch=queue.waiters.splice(0);
        try {
          const snapshot=engineContext()?.checkpointSnapshot?.(queue.project) ?? structuredClone(queue.project);
          await engineContext()?.assertActive?.();
          await writeJson(join(writeKey,'project.json'),snapshot);
          await engineContext()?.onSave?.(snapshot);
          batch.forEach(w=>w.resolve());
        } catch(error){batch.forEach(w=>w.reject(error));}
      }
      projectWrites.delete(writeKey);
    })();},15);
  }
  pending.project=p;
  await new Promise<void>((resolve,reject)=>pending!.waiters.push({resolve,reject}));
  return p;
}
