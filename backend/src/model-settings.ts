import {AsyncLocalStorage} from 'node:async_hooks';
import {dirname, join} from 'node:path';
import {z} from 'zod';
import {dataRoot, writeJson} from './store.js';
import {HttpError} from './errors.js';
import {eligibleModel} from './model-policy.js';
import {inferenceConfiguration, inferenceConnection} from './inference-provider.js';

export type ModelSelection = {
  provider: 'inference'; baseUrl: string; textModel: string; visionModel: string;
};
export function defaultSelection(): ModelSelection {
  const config = inferenceConfiguration();
  return {provider: 'inference', baseUrl: config.baseUrl, textModel: config.model, visionModel: config.model};
}
const path = join(dirname(dataRoot), 'model-settings.json');
const context = new AsyncLocalStorage<ModelSelection>();
export const currentSelection = defaultSelection;
export const activeSelection = () => context.getStore() || currentSelection();
// Old projects may contain Ollama/OpenAI snapshots. Replace their connection
// too, without putting the API key into project JSON.
export const withModelSelection = <T>(_selection: ModelSelection, fn: () => T) => context.run(currentSelection(), fn);
export function publicModelSettings() {
  const config = inferenceConfiguration();
  return {...currentSelection(), keyConfigured: !!config.apiKey && !!config.projectId,
    projectId: config.projectId, imageModel: process.env.LOCAL_IMAGE_MODEL || 'FLUX.2-klein-4B'};
}
export async function loadModelSettings() {
  // The server environment is authoritative; old settings cannot redirect
  // the new API key or reactivate an earlier provider.
  await persistSelection();
}
export function connectionFor(_selection: ModelSelection) {
  return inferenceConnection();
}
async function persistSelection() {
  const model = eligibleModel({id: currentSelection().textModel});
  await writeJson(path, {...currentSelection(), approved: model ? [model] : []});
}
const inputSchema = z.object({
  provider: z.enum(['inference', 'ollama', 'openai']).optional(),
  baseUrl: z.string().optional(), textModel: z.string().optional(), visionModel: z.string().optional(),
});
function validateSelection(raw: unknown) {
  const supplied = inputSchema.parse(raw ?? {}), configured = currentSelection();
  // Accept previous settings forms while retaining this server's connection.
  if (supplied.provider && supplied.provider !== 'inference') return;
  if ((supplied.baseUrl && supplied.baseUrl.replace(/\/+$/, '') !== configured.baseUrl) ||
      (supplied.textModel && supplied.textModel !== configured.textModel) ||
      (supplied.visionModel && supplied.visionModel !== configured.visionModel))
    throw new HttpError(400, 'Подключение и модель задаются переменными INFERENCE_BASE_URL и INFERENCE_MODEL на backend', 'model_configuration');
}
export async function discoverModels(raw?: unknown, _fetcher?: typeof fetch) {
  validateSelection(raw);
  // One model was supplied for this API. No undocumented /models request.
  return [eligibleModel({id: currentSelection().textModel})!];
}
export async function saveModelSettings(raw: unknown) {
  validateSelection(raw);
  inferenceConnection();
  await persistSelection();
  return publicModelSettings();
}
