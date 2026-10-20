import {createHash} from 'node:crypto';
import {copyFile, mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import type {Project} from '../domain.js';
import type {Project as EngineProject} from './engine/domain.js';
import {projectDir, saveProject, writeJson} from '../store.js';
import {HttpError} from '../errors.js';
import * as legacy from '../pipeline.js';
import * as engine from './engine/pipeline.js';
import {prepareHtmlTemplate, generateHtmlDeck} from './engine/html-pipeline.js';
import {withEngineContext} from './engine/runtime-context.js';
import {releaseFontSnapshot} from './engine/sandbox.js';
import {prepareVisualPlan as legacyVisualPlan} from '../visuals.js';
import {visualPreserveReason} from '../visual-types.js';

export const customEngine = 'custom-v3' as const;
export const usesCustomEngine = (p: Project) => p.engineVersion === customEngine;
const engineProject = (p: Project) => p as EngineProject;

/** Keep local project/model ownership in the host. The imported algorithms own
 * their JSON checkpoints and isolated HTML/PPTX processing only. */
export async function withCustomRuntime<T>(p: Project, signal: AbortSignal, work: () => Promise<T>) {
  const runtime = {
    workspace: projectDir(p.id),
    signal,
    locale: 'ru' as const,
    assertActive: async () => signal.throwIfAborted(),
    env: {PRESENTATION_SANDBOX_IMAGE: process.env.CUSTOM_PRESENTATION_SANDBOX_IMAGE || 'nerpa-free-pptx:3'},
  };
  try { return await withEngineContext(runtime, work); }
  finally { await releaseFontSnapshot(runtime); }
}

export async function analyzeSource(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacy.analyzeSource(p, signal);
  await withCustomRuntime(p, signal, async () => {
    await engine.analyzeSource(engineProject(p), signal);
    await prepareHtmlTemplate(engineProject(p), signal);
    await saveProject(p, 'Шаблон и HTML-профили разобраны. Можно создавать план.');
  });
}

export async function generatePlan(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacy.generatePlan(p, signal);
  await withCustomRuntime(p, signal, () => engine.generatePlan(engineProject(p), signal));
}

export function validatePlan(p: Project, raw: unknown) {
  return usesCustomEngine(p) ? engine.validatePlan(engineProject(p), raw) : legacy.validatePlan(p, raw);
}

export async function adaptPlan(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacy.adaptPlan(p, signal);
  signal.throwIfAborted();
  p.plan = validatePlan(p, p.plan);
  await writeJson(join(projectDir(p.id), `plan-r${p.revision}.json`), p.plan);
  p.status = 'plan_ready';
  await saveProject(p, 'Утверждённые макеты и данные плана проверены.');
}

/** Compatibility artifacts for the existing API: the selected source deck is
 * real PPTX; V3 generation itself uses the immutable source HTML profiles. */
export async function assembleAndDescribe(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacy.assembleAndDescribe(p, signal);
  await withCustomRuntime(p, signal, async () => {
    await adaptPlan(p, signal);
    await prepareHtmlTemplate(engineProject(p), signal);
    const folder = projectDir(p.id), assembled = join(folder, `assembled-r${p.revision}`);
    await mkdir(assembled, {recursive: true});
    p.status = 'assembling';
    await saveProject(p, 'Подготавливаем утверждённые макеты и HTML-контракт.');
    await engine.native('assemble', join(folder, 'source'), {
      layoutIds: p.plan!.slides.map(s => s.sourceLayoutId), output: assembled,
    }, signal);
    const slides = p.plan!.slides.map((slide, index) => {
      const layout = p.analysis.layouts.find((l: any) => l.id === slide.sourceLayoutId);
      return {index, originalSourceLayoutId: layout.id, assembledLayoutId: `selected-${index}`,
        native: structuredClone(layout), sourceHtml: layout.htmlSource};
    });
    await mkdir(join(assembled, 'previews'), {recursive: true});
    for (const slide of slides) {
      signal.throwIfAborted();
      // Adaptive HTML layouts can reuse an original part under a new ordinal.
      const sourceLayout = p.analysis.layouts.find((layout: any) => layout.part && layout.part === slide.native.part) || slide.native;
      await copyFile(join(folder, 'source/previews', `slide-${sourceLayout.index}.png`),
        join(assembled, 'previews', `slide-${slide.index}.png`));
    }
    p.contract = {
      version: 'nerpa-html-template/1', engine: customEngine, revision: p.revision,
      sourceSha256: p.analysis.sha256,
      assembledSha256: createHash('sha256').update(JSON.stringify([p.analysis.sha256, p.plan])).digest('hex'),
      dimensions: {width: p.analysis.width, height: p.analysis.height, unit: 'pt'},
      styleProfile: p.analysis.styleProfile, plan: p.plan, descriptionComplete: true, slides,
    };
    await writeJson(join(folder, `template-r${p.revision}.json`), p.contract);
    await prepareVisualPlan(p, signal);
    p.status = 'template_ready';
    await saveProject(p, 'HTML-контракт готов. Можно создавать презентацию.');
  });
}

export async function prepareVisualPlan(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacyVisualPlan(p, signal);
  signal.throwIfAborted();
  if (!p.contract) throw new HttpError(409, 'Сначала подготовьте макеты', 'no_contract');
  if (p.visuals?.revision === p.revision && p.visuals.assembledSha256 === p.contract.assembledSha256) return;
  p.visuals = {version: 1, detectionVersion: 2, revision: p.revision,
    assembledSha256: p.contract.assembledSha256, choices: []};
  p.contract.slides.forEach((slide: any, slideIndex: number) => {
    const slots = slide.native.imageSlots || slide.native.visualSlots || [];
    slots.forEach((slot: any, slotIndex: number) => {
      const requested = p.plan!.slides[slideIndex].images?.find(i => i.slotIndex === slotIndex);
      const choice = {slideIndex, slotIndex, shapeId: slot.shapeId, slot,
        role: slot.protected ? 'brand' as const : 'content' as const,
        kind: requested?.kind || 'photo' as const, description: requested?.description || p.plan!.slides[slideIndex].brief,
        style: '', fieldKeys: [], background: requested?.background || 'opaque' as const,
        mode: 'keep' as const, instruction: '', quality: 'medium' as const, nonce: 0};
      const preserveReason = visualPreserveReason(choice, p.contract.dimensions);
      p.visuals!.choices.push({...choice, ...(preserveReason ? {preserveReason} : {})});
    });
  });
  await saveProject(p);
}

export async function fillDeck(p: Project, signal: AbortSignal) {
  if (!usesCustomEngine(p)) return legacy.fillDeck(p, signal);
  if (!p.contract || p.contract.revision !== p.revision)
    throw new HttpError(409, 'Сначала подготовьте текущие макеты', 'no_contract');
  await withCustomRuntime(p, signal, async () => {
    p.plan = validatePlan(p, p.plan);
    const images = async () => {
      const slides: Record<number, any[]> = {}, files: Record<string, string> = {};
      for (const choice of p.visuals?.choices || []) {
        if (choice.mode !== 'upload' || !choice.asset || choice.preserveReason) continue;
        if (!/^[a-f0-9]{64}\.png$/.test(choice.asset)) throw new HttpError(400, 'Некорректное изображение', 'visual_asset');
        const key = choice.asset;
        files[key] = join(projectDir(p.id), 'visual-assets', key);
        (slides[choice.slideIndex] ||= []).push({image: key, shapeId: choice.shapeId,
          slotIndex: choice.slotIndex, box: choice.slot.box, fit: 'contain',
          kind: choice.kind, description: choice.description, background: choice.background});
      }
      return {slides, files, warnings: []};
    };
    const result = await generateHtmlDeck(engineProject(p), {addons: [], images});
    signal.throwIfAborted();
    await writeJson(join(projectDir(p.id), `filled-r${p.revision}.json`), result.slides);
    await writeJson(join(result.output, 'quality-warnings.json'), result.warnings);
    for (const choice of p.visuals?.choices || []) choice.applied = choice.mode === 'upload' && !!choice.asset && !choice.preserveReason;
    await saveProject(p);
  });
}

export const researchProject = legacy.researchProject;
