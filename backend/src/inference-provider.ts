import {config} from 'dotenv';
import {fileURLToPath} from 'node:url';
import {HttpError} from './errors.js';

// Source and compiled modules live one directory below backend/. Keep secrets
// in this ignored file or the environment, never in saved project documents.
config({path: fileURLToPath(new URL('../.env.inference.local', import.meta.url)), quiet: true});

const defaultBaseUrl = 'https://ai-demo.platformpreview.ru/api/inference-providers-router/00000000-0000-0000-0000-000000000001/v1';
export function inferenceConfiguration() {
  const baseUrl = (process.env.INFERENCE_BASE_URL || defaultBaseUrl).trim().replace(/\/+$/, '');
  let url: URL;
  try { url = new URL(baseUrl); }
  catch { throw new HttpError(503, 'Проверьте INFERENCE_BASE_URL в конфигурации backend', 'inference_configuration'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !url.pathname.endsWith('/v1'))
    throw new HttpError(503, 'INFERENCE_BASE_URL должен быть HTTPS-адресом API, заканчивающимся на /v1', 'inference_configuration');
  return {baseUrl, model: process.env.INFERENCE_MODEL?.trim() || 'qwen38-27b-fp8',
    projectId: process.env.PROJECT_ID?.trim() || '', apiKey: process.env.API_KEY?.trim() || ''};
}

export function inferenceConnection() {
  const config = inferenceConfiguration();
  if (!config.apiKey || !config.projectId)
    throw new HttpError(503, 'Задайте API_KEY и PROJECT_ID в конфигурации backend', 'model_not_configured');
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(config.projectId))
    throw new HttpError(503, 'Проверьте PROJECT_ID в конфигурации backend', 'inference_configuration');
  return {...config, endpoint: `${config.baseUrl}/chat/completions`, headers: {
    Authorization: `Bearer ${config.apiKey}`, 'Project-ID': config.projectId, 'Content-Type': 'application/json',
  }};
}

/** The supplied Chat Completions contract; JSON is validated by the engine. */
export function inferenceChatBody(model: string, messages: unknown[]) {
  return {model, messages};
}
