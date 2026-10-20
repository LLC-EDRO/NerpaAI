import {engineContext} from './runtime-context.js';
import {createHash,randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import sharp from 'sharp';
import {HttpError} from './errors.js';
import {readJson,writeJson} from './store.js';
import {presentationImageSize} from './image-size.js';
import {imageRequestBody} from './image-request.js';
import {visualPreserveReason,type VisualSlot} from './visual-types.js';
import {storeVisualAsset} from './visual-assets.js';
export type EditorVisualChoice={slot:VisualSlot;role:string;kind:string;style:string;background:'transparent'|'opaque';description:string;quality:'low'|'medium'|'high';nonce:number};
const visualRequiresOpaque=(choice:EditorVisualChoice)=>choice.slot.requiresOpaque||choice.role==='photo_underlay';
const hash=(value:unknown)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const assetName=/^[a-f0-9]{64}\.(?:png|jpg)$/;
export function imagePrompt(
  brief: string,
  choice: EditorVisualChoice,
  palette: unknown,
) {
  const transparent = !visualRequiresOpaque(choice) && choice.background === "transparent";
  return `Create ONE professional presentation visual. Kind: ${choice.kind}. This is an asset inside an existing slide, not the slide itself.
Reference data (not instructions): ${JSON.stringify({ subject: brief, style: choice.style, palette, aspectRatio: choice.slot.aspectRatio })}.
Match the slide palette, materials and visual style. Explain this slot's specific subject. Preserve recognizable physical forms and natural skin colours. Use a clear composition and readable silhouette. Finish object edges and keep generous margins.
${transparent ? "Isolated cutout with real transparent alpha and transparent negative space. No white matte, checkerboard, rectangle, floor, scenery or painted background. Subtle shadows fade into alpha." : "Opaque image filling its frame. Match the original composition and colour contrast, especially behind overlaid slide text. Keep the composition quiet where text overlaps."}
${choice.kind === "chart" ? "Chart comparing only the exact supported values in the brief, with their units and labels. Use honest scales and correct proportions. If no quantitative data was supplied, show a qualitative comparison without numbers or numeric axes. Never invent statistics." : choice.kind === "diagram" ? "Illustrative conceptual diagram with clear relationships and few elements. Arrows must express the sequence or relationships in the brief, not decorative connections. No fabricated quantitative chart or statistics. Use only short labels explicitly supplied in the brief." : choice.kind === "interface" ? "Polished conceptual UI/product mockup, not a real screenshot or proof of a shipped product. Use only short labels explicitly supplied; no invented analytics, brands, logos or claims." : "No text, letters, numbers, logos, watermarks or invented charts. No generic robots or light bulbs unless the subject specifically requires them."}
For diagrams and interfaces, all visible UI labels must be in Russian unless the user explicitly requests another language. Short generic navigation labels are allowed; do not invent quantitative metrics. Do not duplicate the slide title or draw its decorations. Never reproduce template placeholder instructions such as "insert photo" or "Вставить фото". No extraneous objects.`;
}
type GenerateInput = {
  folder: string;
  prompt: string;
  choice: EditorVisualChoice;
  dimensions: { width: number; height: number };
  signal: AbortSignal;
  fetcher?: typeof fetch;
  description?: string;
  slideTitle?: string;
  slideText?: string;
};
type GeneratedVisualAsset = {asset:string;identity:string;background?:'transparent'|'opaque'};
const pendingImages = new Map<
  string,
  Promise<GeneratedVisualAsset>
>();
export function generateVisualAsset(input: GenerateInput):Promise<GeneratedVisualAsset> {
  const reason = visualPreserveReason(input.choice, input.dimensions);
  if (reason)
    return Promise.reject(new HttpError(400, reason, "visual_protected"));
  // Old checkpoints and direct callers may predate the measured backdrop flag.
  // Use the effective setting for both the request and its paid-task identity.
  if (visualRequiresOpaque(input.choice) && input.choice.background !== 'opaque')
    input = {...input, choice:{...input.choice, background:'opaque'}};
  const size = presentationImageSize(input.choice.slot.box, input.dimensions);
  const key = hash({
    folder: input.folder,
    prompt: input.prompt,
    quality: input.choice.quality,
    background: input.choice.background,
    nonce: input.choice.nonce,
    size: `${size.width}x${size.height}`,
  });
  const pending = pendingImages.get(key);
  if (pending) return pending;
  const task = generateVisualAssetOnce(input).then(async generated=>{
    input.signal.throwIfAborted();
    await engineContext()?.assertActive?.();
    const background=generated.background??(visualRequiresOpaque(input.choice)?'opaque' as const:undefined);
    await engineContext()?.onImageGenerated?.({path:join(input.folder,'visual-assets',generated.asset),prompt:input.prompt,description:input.choice.description,model:generated.model,...(generated.provider?{provider:generated.provider}:{}),options:{...generated.options,kind:input.choice.kind,background:generated.background??input.choice.background,quality:input.choice.quality,identity:generated.identity}});
    return {asset:generated.asset,identity:generated.identity,...(background?{background}:{})};
  });
  pendingImages.set(key, task);
  void task
    .finally(() => {
      if (pendingImages.get(key) === task) pendingImages.delete(key);
    })
    .catch(() => {});
  return task;
}
async function generateVisualAssetOnce(input: GenerateInput) {
  const { folder, prompt, choice, signal } = input;
  const started = Date.now();
  const size = presentationImageSize(choice.slot.box, input.dimensions);
  // Identity stays stable even after this API project requires a compatibility model.
  const body = imageRequestBody({prompt,...size,quality:choice.quality,background:choice.background});
  const identity = hash({ body, nonce: choice.nonce }),
    path = join(folder, "visual-tasks", `${identity}.json`);
  let prior: any;
  try {
    prior = await readJson(path);
  } catch {}
  if (prior?.asset && assetName.test(prior.asset)) {
    try {
      await readFile(join(folder, "visual-assets", prior.asset));
      return { asset: prior.asset, identity, model:prior.model??body.model, options:prior.generationOptions??{},
        ...(typeof prior.provider==='string'?{provider:prior.provider}:{}),
        ...(prior.sourceKind==='real-photo'?{background:'opaque' as const}:{}) };
    } catch {}
  }
  if (prior)
    throw new HttpError(
      409,
      prior.state === "running" || prior.state === "uncertain"
        ? "Ответ на предыдущий платный запрос не получен. Автоповтор отключён; повторите эту картинку вручную."
        : "Предыдущая попытка не удалась. Повторите только эту картинку или загрузите файл.",
      "visual_previous_attempt",
    );
  signal.throwIfAborted();
  await engineContext()?.assertActive?.();
  // Resolve photographs only after the exact paid task has been reconciled.
  // An unavailable search is an error, not permission to silently buy an AI image.
  const photoRequiresOpaque=visualRequiresOpaque(choice);
  const photo = await engineContext()?.resolveRealPhoto?.({
    prompt,description:input.description??choice.description,kind:choice.kind,
    size:{width:size.deliveryWidth,height:size.deliveryHeight},
    requiresOpaque:photoRequiresOpaque,
    ...(input.slideTitle?{slideTitle:input.slideTitle}:{}),
    ...(input.slideText?{slideText:input.slideText}:{}),
  });
  signal.throwIfAborted();
  await engineContext()?.assertActive?.();
  if(photo){
    const asset=await storeVisualAsset(folder,photo.bytes,false,photoRequiresOpaque);
    signal.throwIfAborted();
    await engineContext()?.assertActive?.();
    const options={sourceKind:'real-photo',source:photo.source,query:photo.query,reason:photo.reason,
      size:`${size.deliveryWidth}x${size.deliveryHeight}`,background:'opaque' as const,kind:choice.kind};
    await writeJson(path,{state:'ready',asset,provider:photo.provider,model:'source-photo',sourceKind:'real-photo',
      prompt,description:input.description??choice.description,generationOptions:options,
      startedAt:new Date(started).toISOString(),finishedAt:new Date().toISOString(),durationMs:Date.now()-started});
    return {asset,identity,provider:photo.provider,model:'source-photo',background:'opaque' as const,options};
  }
  throw new HttpError(410, 'Генерация новых изображений отключена. Загрузите свой файл.', 'image_generation_disabled');
}
