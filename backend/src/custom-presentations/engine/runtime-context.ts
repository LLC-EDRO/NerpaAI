import { AsyncLocalStorage } from 'node:async_hooks';
import type { Project } from './domain.js';

/** Computed by the host; the separately compiled engine does not own allowances. */
export interface EngineMediaPolicy {
  photos: {max:number};
  tables: {min:1;target:number;max:number};
  charts: {min:1;target:number;max:number};
  interiorSlides:number;
}

/** Host integration for HTML authoring and isolated source import/export. */
export interface EngineRuntime {
  workspace: string;
  signal?: AbortSignal;
  observeApi?: <T>(stage:string,attempt:number|undefined,work:()=>Promise<T>)=>Promise<T>;
  locale?: 'ru' | 'en';
  instructions?: string;
  maxGeneratedImages?: number;
  mediaPolicy?: EngineMediaPolicy;
  mediaPlanningPrompt?: string;
  env?: Record<string, string | undefined>;
  assertActive?: () => Promise<void>;
  onSave?: (project: Project) => Promise<void>;
  checkpointSnapshot?: (project: Project) => Project;
  writeDiagnosticDocument?: (path:string,value:unknown)=>void;
  flushDiagnostics?: ()=>Promise<void>;
  writeDocument?: (path: string, value: unknown) => Promise<void>;
  readDocument?: (path: string) => Promise<unknown | undefined>;
  saveNativeDocuments?: (directory: string, files: string[]) => Promise<void>;
  /** Read only a current source-document image through the host's owner scope. */
  readSourceImage?: (assetId:string) => Promise<Buffer>;
  resolveRealPhoto?: (input:{prompt:string;description:string;kind:string;searchQuery?:string;size:{width:number;height:number};slideTitle?:string;slideText?:string;requiresOpaque?:boolean;signal?:AbortSignal})=>Promise<{bytes:Buffer;provider:string;source:Record<string,unknown>;query:string;reason:string}|undefined>;
  onImageGenerated?: (input:{path:string;prompt:string;description:string;model:string;provider?:string;options:Record<string,unknown>})=>Promise<void>;
}
const contexts = new AsyncLocalStorage<EngineRuntime>();
export const engineContext = () => contexts.getStore();
export const withEngineContext = <T>(runtime: EngineRuntime, work: () => Promise<T>) => contexts.run(runtime, work);
// Per-invocation configuration prevents changing models of unrelated products.
export const engineEnv = new Proxy(process.env, {
  get(target, key: string) {
    const overrides = contexts.getStore()?.env;
    return overrides && Object.hasOwn(overrides, key) ? overrides[key] : target[key];
  },
});
