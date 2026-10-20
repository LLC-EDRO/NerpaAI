import {HttpError} from './errors.js';

type ImageRequest = {
  model: string; prompt: string; size: string; quality: 'low' | 'medium' | 'high';
  n: 1; output_format: 'png'; background?: 'transparent' | 'opaque';
};
type ImageInput = {
  apiKey: string; prompt: string; width: number; height: number;
  quality: ImageRequest['quality']; background?: ImageRequest['background'];
  signal: AbortSignal; fetcher?: typeof fetch;
  onRequest?: (body: ImageRequest) => Promise<void>;
};
export function imageRequestBody(input: Pick<ImageInput, 'prompt' | 'width' | 'height' | 'quality' | 'background'>): ImageRequest {
  return {model:'gpt-image-2',prompt:input.prompt,size:`${input.width}x${input.height}`,
    quality:input.quality,n:1,output_format:'png',...(input.background?{background:input.background}:{})};
}

/** This backend has a chat provider; image generation stays disabled. */
export async function requestImage(_input: ImageInput): Promise<{response: Response; body: ImageRequest; width: number; height: number}> {
  throw new HttpError(410, 'Генерация новых изображений отключена. Загрузите свой файл.', 'image_generation_disabled');
}
