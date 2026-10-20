import {layoutEditability,preferEditableLayouts,sourceMediaRequirements} from './layout-selection.js';
import {automaticTemplateLayouts} from './template-catalog.js';
import {prepareSourceFigureEvidence,sourceFigureFacts} from './source-figure-evidence.js';
import {narrativeLayoutCapabilities} from './narrative-layouts.js';
import {sourceRecoveryVersion} from './template-version.js';
import {planQualityWarnings} from './plan-quality.js';
import {narrativePolicy} from './html-domain.js';
import {htmlPlanningFormat,describeHtmlPlanVisuals} from './html-planning.js';
import {presentationDataContext,presentationDataPrompt,dataViews} from './data-contract.js';
import {attachPlannedData,planDataAllocation} from './data-planning.js';
import {stylePlanningPrompt} from './style-prompts.js';
import {sourceSlideConcept,matchPlanConcepts} from './slide-concept.js';
import {enforceHtmlPlanRoles} from './html-layout-roles.js';
import {engineContext,type EngineMediaPolicy} from './runtime-context.js';
import {validateResearchCoverage} from './research-coverage.js';
import {createNativePool} from './native-pool.js';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {runNativeSandbox} from './sandbox.js';
import {HttpError} from './errors.js';
import {retryTransient} from './retry.js';
import {projectDir,readJson,writeJson,writeDiagnostic,saveProject} from './store.js';
import {llmJson} from './llm.js';
import {recoverPlanProposal,sourceImageFrames} from './plan-recovery.js';
import {researchStamp,researchText,searchResearch,researchContext,numericEvidenceCount,mergeResearch,reusableResearch} from './research.js';
import {planSchema,type Outline,type Project,type Layout} from './domain.js';
const nativePool=createNativePool(Math.max(1,Math.min(4,Math.floor(Number(process.env.PPTX_CONCURRENCY)||4))));
export async function native(
  action: string,
  folder: string,
  extra: Record<string, unknown> = {},
  signal?: AbortSignal
) {
  return retryTransient(
    async () => {
      const started = Date.now();
      let executionStarted = started;
      const documents:Array<{directory:string;files:string[]}>=[];
      const process = async () => {
        signal?.throwIfAborted();
        executionStarted = Date.now();
        return runNativeSandbox({ action, folder, ...extra }, 240000,
          (directory,files)=>documents.push({directory,files}),undefined,{signal});
      };
      const result: any = await nativePool(process);
      const persistedAt=Date.now();
      // Release CPU/render capacity before waiting for the remote database.
      // The caller still receives no success until every document is durable.
      for(const document of documents)await engineContext()?.saveNativeDocuments?.(document.directory,document.files);
      await writeDiagnostic(
        join(folder, "performance", `${Date.now()}-${randomUUID()}.json`),
        {
          action,
          ...(result.error?{error:result.error,errorType:result.errorType,trace:result.trace}:{}),
          ...(action==='html_export'?{htmlPhase:extra.htmlPhase??'full'}:{}),
          durationMs: Date.now() - started,
          queueMs: executionStarted - started,
          executionMs: Date.now() - executionStarted,
          nativeProcessMs:persistedAt-executionStarted,
          persistenceMs:Date.now()-persistedAt,
          slideCount: Array.isArray(extra.slides)
            ? extra.slides.length
            : undefined,
        },
      );
      if (result.error) {
        const code =
          result.errorType === "TimeoutExpired" ? "pptx_timeout" : result.error;
        throw new HttpError(422, "Обработчик PPTX: " + code, code, {
          trace: result.trace,
          issues: result.issues,
        });
      }
      return result;
    },
    {
      signal,
      ...(action.startsWith('html_')?{attempts:1}:{}),
      retryable: (error) =>
        error instanceof HttpError &&
        ["pptx_timeout", "pptx_runtime_failed", "pptx_render_failed"].includes(
          error.code,
        ),
      onRetry: () =>
        writeJson(
          join(folder, "recovery", `${Date.now()}-${randomUUID()}.json`),
          {
            action,
            reason: "transient_native_failure",
            automaticRetry: true,
          },
        ),
    },
  );
}

async function ensureSourceRecovery(p: Project, signal: AbortSignal) {
  if (p.analysis?.recoveryVersion === sourceRecoveryVersion) return;
  const folder = join(projectDir(p.id), "source");
  const sha = createHash("sha256")
    .update(await readFile(join(folder, "source.pptx")))
    .digest("hex");
  if (p.analysis?.sha256 && p.analysis.sha256 !== sha)
    throw new HttpError(
      409,
      "Исходный PPTX изменился. Нельзя применить к нему сохранённый план.",
      "pptx_source_changed",
    );
  await checkpoint(
    p,
    "analyzing_source",
    "Проверяем старый разбор шаблона с обновлённым восстановлением",
  );
  p.analysis = await native("analyze", folder, {}, signal);
  const metadata=await native('layout_metadata',folder,{},signal);
  p.analysis.layouts=p.analysis.layouts.map((layout:Layout)=>({...layout,...metadata[layout.id],usable:layout.usable,warnings:layout.warnings}));
  await saveProject(p, "Разбор шаблона обновлён автоматически");
  return true;
}
async function checkpoint(
  p: Project,
  status: string,
  message: string,
  done?: number,
  total?: number,
) {
  p.status = status;
  p.progress = done === undefined ? undefined : { done, total: total! };
  await saveProject(p, message);
}
export async function analyzeSource(p: Project, signal: AbortSignal) {
  await checkpoint(
    p,
    "analyzing_source",
    "Читаем объекты PPTX и создаём изображения исходных слайдов",
  );
  p.analysis = await native(
    "analyze",
    join(projectDir(p.id), "source"),
    {},
    signal,
  );
  signal.throwIfAborted();
  await checkpoint(
    p,
    "ready",
    `Шаблон разобран. Доступно макетов: ${p.analysis.layouts.filter((l: Layout) => l.usable).length} из ${p.analysis.layouts.length}`,
  );
}
export function validatePlan(p: Project, raw: unknown,mediaPolicy?:EngineMediaPolicy) {
  const plan = planSchema.parse(raw);
  enforceHtmlPlanRoles(p.analysis,plan.slides);
  const ids = plan.slides.map((s) => s.id).filter(Boolean);
  if (new Set(ids).size !== ids.length)
    throw new HttpError(
      422,
      "Слайды должны иметь уникальные идентификаторы",
      "plan_duplicate_id",
    );
  if (plan.slides.length !== p.brief!.count)
    throw new HttpError(
      422,
      "Количество слайдов не совпадает с заданием",
      "plan_count",
    );
  for (const slide of plan.slides) {
    if(slide.sourceImageIds?.some(id=>!p.brief?.sourceDocument?.images.some(image=>image.id===id)))
      throw new HttpError(422,'Выбрано неизвестное изображение исходного документа','source_image_invalid');
    if (
      !(mediaPolicy?automaticTemplateLayouts<Layout>(p.analysis):p.analysis.layouts).some(
        (l: Layout) => l.id === slide.sourceLayoutId && l.usable,
      )
    )
      throw new HttpError(
        422,
        "Выбран недоступный макет",
        "layout_unavailable",
      );
  }
  // This policy is supplied only for fresh automatic proposals. Never trim an
  // approved plan, original source figures, or already purchased placements.
  if(mediaPolicy)validatePlanMedia(p,plan,mediaPolicy);
  return plan;
}
export function validatePlanMedia(p:Project,plan:Outline,mediaPolicy:EngineMediaPolicy){
    const issues:Array<{path:(string|number)[];code:string;message:string;details?:unknown}>=[];
    const reject=(error:HttpError,index:number,field:string)=>issues.push({path:['slides',index,field],code:error.code,message:error.message,details:error.details});
    plan.slides.slice(1,-1).forEach((slide,index)=>{
      const layout=p.analysis.layouts.find((candidate:Layout)=>candidate.id===slide.sourceLayoutId&&candidate.usable);
      if(!layout)return;
      const capability=narrativeLayoutCapabilities(layout);
      if(!capability.automaticContentEligible&&!capability.automaticSectionEligible)
        reject(new HttpError(422,`Слайд ${index+2}: у выбранного макета нет отдельного читаемого заголовка и вместительной области содержания. Выберите подготовленный текстовый, табличный, графический или иллюстрационный макет; служебное поле не заменяет содержательный слайд.`,
          'plan_narrative_layout_required',{slide:index+2,sourceLayoutId:layout.id,narrativeCapabilities:capability}),index+1,'sourceLayoutId');
    });
    plan.slides.forEach((slide,index)=>{
      if(!slide.sourceImageIds?.length)return;
      const layout=p.analysis.layouts.find((candidate:Layout)=>candidate.id===slide.sourceLayoutId&&candidate.usable);
      const safe=sourceImageFrames(layout);
      if(index===0||index===plan.slides.length-1||new Set(slide.sourceImageIds).size>safe.length)
        reject(new HttpError(422,
          `Слайд ${index+1}: исходные изображения назначены в макет без достаточного числа безопасных содержательных рамок. Выберите внутренний макет с imageSlots или перенесите эти sourceImageIds на подходящий внутренний слайд. Фон, логотип и область под текстом не являются рамками для документа.`,
          'plan_source_image_capacity',{slide:index+1,sourceLayoutId:slide.sourceLayoutId,frames:safe.length}),index,'sourceImageIds');
    });
    if(issues.length){const first=issues[0]!;throw new HttpError(422,first.message,first.code,{...(first.details as object),issues});}
    const photos=plan.slides.reduce((total,slide,index)=>{
      const layout=p.analysis.layouts.find((candidate:Layout)=>candidate.id===slide.sourceLayoutId&&candidate.usable&&candidate.narrative!==false);
      const frames=layout?.imageSlots||[];
      const sourceIds=new Set((slide.sourceImageIds||[]).filter(id=>p.brief?.sourceDocument?.images.some(image=>image.id===id)));
      const originals=index>0&&index<plan.slides.length-1?Math.min(sourceIds.size,frames.length):0;
      return total+(slide.images||[]).filter(image=>{
        if(image.kind!=='photo'&&image.kind!=='illustration')return false;
        const sourceFrame=image.slotIndex<originals?frames[image.slotIndex]:undefined;
        return !sourceFrame||sourceFrame.protected||['icon','logo','decoration','footer','page_number'].includes(sourceFrame.sourceRole);
      }).length;
    },0);
    if(photos>mediaPolicy.photos.max)throw new HttpError(422,
      `Предложено слишком много новых фотографий или тематических иллюстраций: ${photos}; максимум ${mediaPolicy.photos.max}. Выберите самые содержательные изображения, остальные слайды раскройте текстом, схемами или подтверждёнными таблицами и графиками. Не нужно заполнять весь лимит.`,
      'plan_photo_budget',{photos,max:mediaPolicy.photos.max});
    const requirements=sourceMediaRequirements(automaticTemplateLayouts<Layout>(p.analysis),p.brief?.sourceDocument,Math.min(mediaPolicy.interiorSlides,Math.max(0,plan.slides.length-2)));
    const interior=plan.slides.slice(1,-1);
    for(const kind of ['tables','charts'] as const){
      const required=requirements[kind];
      if(required.min&&!interior.some(slide=>required.compatibleLayoutIds.includes(slide.sourceLayoutId)))throw new HttpError(422,
        kind==='tables'
          ? 'В исходном документе есть содержательная таблица и в шаблоне есть совместимый редактируемый объект. Добавьте хотя бы одну нативную таблицу на внутренний слайд по этим данным; качественные свойства тоже подходят.'
          : 'В исходном документе есть связанный числовой ряд и в шаблоне есть совместимая нативная диаграмма. Добавьте хотя бы один редактируемый график на внутренний слайд, используя подтверждённые значения.',
        kind==='tables'?'plan_native_table_required':'plan_native_chart_required',required);
    }
}
export async function researchProject(p: Project, signal: AbortSignal, force = false) {
  try {
    await researchProjectStrict(p,signal,force);
    delete p.researchWarning;
  } catch (error) {
    signal.throwIfAborted();
    p.researchWarning = 'Поиск или проверка источников не завершились. Использованы доступные материалы; проверьте факты и ссылки.';
    await saveProject(p,p.researchWarning);
  }
}
async function researchProjectStrict(
  p: Project,
  signal: AbortSignal,
  force = false,
) {
  if (!p.brief?.webSearch) return;
  const requirements = (p.plan?.slides || []).flatMap((slide,index) => {
    const layout=p.analysis?.layouts.find((candidate:Layout)=>candidate.id===slide.sourceLayoutId);
    const capacity=layout?.htmlMetricCapacity??0;
    return capacity>0?[{slide:index+1,topic:slide.title,intent:slide.brief,group:'metrics',maxChars:80}]:[];
  });
  const minNumericFacts = requirements.length
    ? Math.min(8, requirements.length)
    : /статист|метрик|цифр|показател/i.test(
          p.brief.sourceText + " " + p.brief.topic,
        )
      ? 3
      : 0;
  const context = researchContext(p.plan, requirements);
  if (!force && reusableResearch(p.research, p.brief, context)) return;
  // A changed layout fingerprint alone does not justify repeating web search.
  // Ask which evidence is actually missing; retain all original cited facts.
  let searchPlan = p.plan,
    searchRequirements = requirements;
  if (
    !force &&
    p.plan &&
    p.research?.stamp === researchStamp(p.brief) &&
    p.research.evidence.length
  ) {
    const numericSlides = new Set<number>(
      requirements.map((r: any) => r.slide),
    );
    const coverage = await llmJson({
      stage: "research-coverage",
      folder: projectDir(p.id),
      signal,
      prompt: `Проверь достаточность УЖЕ НАЙДЕННЫХ источников для каждого слайда. Не заполняй слайды. План задаёт тему, не обязательный перенос всех фактов. Для вводных слайдов, определений, выводов и явно обозначенных рекомендаций допустимы устойчивые знания без источника. Для фактических кейсов, актуальных утверждений и метрик нужны релевантные evidenceIds; проверяй субъект, единицу, период и охват. Для каждой числовой карточки должны находиться разные подходящие факты, не один факт для всех карточек. Если данных хватает, missing=""; иначе missing — конкретный вопрос для дополнительного поиска. Не ищи заново уже подтверждённое, но не объявляй отсутствующие факты найденными. Ответ {slides:[{slide:1,evidenceIds:["evidence-1"],missing:""}]}, каждый слайд ровно один раз.`,
      payload: {
        topic: p.brief.topic,
        userSource: p.brief.sourceText,
        slides: p.plan.slides.map((s, i) => ({
          slide: i + 1,
          title: s.title,
          brief: s.brief,
        })),
        requirements,
        evidence: p.research.evidence,
      },
      validate: (raw) =>
        validateResearchCoverage(
          raw,
          p.plan!.slides.length,
          numericSlides,
          p.research!.evidence,
        ),
    });
    await writeJson(
      join(projectDir(p.id), `research-coverage-${context}.json`),
      { context, coverage },
    );
    const missing = coverage.filter((row) => row.missing);
    if (!missing.length) {
      p.research.contextStamp = context;
      await writeJson(join(projectDir(p.id), "research.json"), p.research);
      await saveProject(
        p,
        "Проверено покрытие слайдов: найденных источников достаточно, повторный поиск не нужен",
      );
      return;
    }
    searchPlan = {
      slides: missing.map((row) => ({
        ...p.plan!.slides[row.slide - 1],
        brief: row.missing,
      })),
    };
    searchRequirements = requirements.filter((r: any) =>
      missing.some((row) => row.slide === r.slide),
    );
  }
  await checkpoint(
    p,
    "researching",
    "Ищем факты и статистику в интернете, сохраняем источники",
  );
  const found = await searchResearch(
    p.brief,
    projectDir(p.id),
    signal,
    fetch,
    searchPlan,
    searchRequirements,
    minNumericFacts,
    p.research,
  );
  p.research = mergeResearch(p.research, found);
  p.research.contextStamp = context;
  p.research.coverage = {
    targetNumericFacts: minNumericFacts,
    foundNumericFacts: numericEvidenceCount(p.research),
    sufficient: numericEvidenceCount(p.research) >= minNumericFacts,
  };
  delete p.result;
  await writeJson(join(projectDir(p.id), "research.json"), p.research);
  await checkpoint(
    p,
    p.plan ? "plan_ready" : "ready",
    p.research.evidence.length
      ? `Найдено фактов: ${p.research.evidence.length}. ${p.research.coverage.sufficient ? "Источники доступны для проверки." : "Подбираем содержание по найденным данным; каждую метрику проверим при заполнении."}`
      : "Поиск завершён без фактов с подтверждёнными ссылками. Будут использованы ваши материалы.",
  );
}
export function projectFacts(p: Project) {
  const found =
    p.brief?.webSearch && p.research?.stamp === researchStamp(p.brief)
      ? researchText(p.research)
      : "";
  const figures=sourceFigureFacts(p).map(fact=>fact.text).join('\n');
  return `${p.brief!.topic}\n${p.brief!.sourceText}${p.brief?.dataSources?.length?'\nДанные пользователя:\n'+JSON.stringify(dataViews(p.brief.dataSources)):''}${found ? "\nФакты из веб-поиска с источниками:\n" + found : ""}${figures?'\nИсходные иллюстрации, проверенные по изображению. При противоречии подписи документа для описания назначенного рисунка используй наблюдения ниже, не меняя сам рисунок:\n'+figures:''}`;
}
/** Offer only capabilities measured in the uploaded PPTX. Missing objects do
 * not justify inventing a native chart/table or forcing a fabricated dataset. */
export function uploadedPlanningContext(p:Project){
  const usable=preferEditableLayouts(automaticTemplateLayouts<Layout>(p.analysis).filter((layout:Layout)=>layout.usable));
  return {
    topic:p.brief!.topic,count:p.brief!.count,maxGeneratedImages:engineContext()?.maxGeneratedImages??3,
    ...(engineContext()?.mediaPolicy?{mediaPolicy:engineContext()!.mediaPolicy,
      mediaRequirements:sourceMediaRequirements(usable,p.brief?.sourceDocument,Math.min(engineContext()!.mediaPolicy!.interiorSlides,Math.max(0,p.brief!.count-2)))}:{}),
    mediaCapabilities:{
      editableTableLayouts:usable.filter(layout=>{const c=layoutEditability(layout);return narrativeLayoutCapabilities(layout).automaticContentEligible&&c.nativeTables+c.recoveredEditableTables>0;}).map(layout=>layout.id),
      nativeChartLayouts:usable.filter(layout=>narrativeLayoutCapabilities(layout).automaticContentEligible&&layoutEditability(layout).nativeCharts>0).map(layout=>layout.id),
    },
    htmlDataCapabilities:{
      types:['bar','bar-horizontal','line','pie','donut','xy','table','qualitative-diagram'],
      layouts:usable.filter(layout=>layout.htmlTemplateLayout&&layout.htmlRole==='content'&&
        (layout.htmlDesign?.content??[]).some((b:any)=>b.w>=380&&b.h>=220)).map(layout=>layout.id),
      policy:'HTML can build editable charts/tables inside the existing source content panel even without a native data object. Prefer a meaningful chart for comparable confirmed observations, with units, period and source; use a table for different units/definitions. Never compare incompatible currencies or populations on one axis. Decide the visual before approval and include it explicitly in brief. Source sample statistics are not evidence.',
    },
    userSource:p.brief!.sourceText,
    attachedData:presentationDataContext(p.brief?.dataSources,planDataAllocation(p).recommendedViewIds),
    dataAllocation:planDataAllocation(p),
    sourceImageLayoutIds:usable.filter(layout=>narrativeLayoutCapabilities(layout).automaticContentEligible&&sourceImageFrames(layout).length>0).map(layout=>layout.id),
    webPhotoPolicy:{priority:'web',max:engineContext()?.mediaPolicy?.photos.max??3,
      layouts:usable.filter(layout=>layout.htmlRole==='content'&&sourceImageFrames(layout).length>0).map(layout=>({id:layout.id,
        slots:(layout.imageSlots??[]).flatMap((slot:any,slotIndex:number)=>!slot.protected&&!slot.requiresOpaque&&!['icon','logo','brand','background','background_image','decoration','footer','page_number'].includes(slot.sourceRole)?[{slotIndex,aspectRatio:slot.aspectRatio}]:[])})),
      instruction:'Prefer 2–5 useful real photographs on distinct narrative slides for a 15-slide deck when safe photo layouts exist. Preserve a good source text-plus-picture concept. Plan exact English searchQuery together with the slide so no extra query-model call is needed. The photograph must explain this particular slide, not repeat a generic topic image. Never assign photos to quantitative charts, tables, covers or closing slides.'},
    sourceImagePlacementRule:'sourceImageIds can be assigned only to an INTERIOR layout from sourceImageLayoutIds with safeSourceImageSlotCount >= the number of distinct sourceImageIds. visualSlots alone do not guarantee a safe original-image frame. Keep the observed figure subject, facts and original image; choose a compatible source layout before writing the plan.',
    ...(p.sourceFigureEvidence?{sourceFigureEvidence:p.sourceFigureEvidence.images.map(({id,kind,description,visibleLabels,captionConflict,conflictReason,safeTitle,safeCaption})=>({id,kind,description,visibleLabels,captionConflict,conflictReason,safeTitle,safeCaption})),
      sourceFigureInstruction:'These observations come from the actual original image pixels before planning. For each assigned sourceImageId use its observed subject and labels. When captionConflict=true, do not copy the contradictory document caption into the approved title or brief; use safeTitle/safeCaption or an equally accurate neutral description. Preserve the original image. Do not invent numerical series or infer unlabelled units/locations.'}:{}),
    ...(p.brief?.sourceDocument?{sourceDocument:p.brief.sourceDocument,sourceImageInstruction:'Assign relevant ORIGINAL source images via sourceImageIds: exact IDs from sourceDocument, only on interior slides with compatible visualSlots. Prefer originals for experiments/screenshots instead of generated substitutes. Unused images remain in the source gallery. Preserve table rows, columns and source chart values. Current userSource is authoritative after edits. For actual figure details use sourceFigureEvidence: when captionConflict=true the document caption does not describe that bitmap. Do not infer unseen image details.'}:{}),
    researchEvidence:p.brief!.webSearch?p.research?.evidence||[]:[],
    sourceStyle:p.analysis.styleProfile?{fonts:p.analysis.styleProfile.fonts?.slice(0,6),colors:p.analysis.styleProfile.colors?.slice(0,10)}:undefined,
    layouts:usable.map((layout:Layout)=>layout.htmlGenerationMode==='style-stencils'?{
      id:layout.id,name:layout.name,templateRole:layout.htmlRole,concept:sourceSlideConcept(layout,p.analysis),
      allowedPositions:layout.htmlRole==='cover'?['first']:layout.htmlRole==='closing'?['last']:layout.htmlRole==='section'?['section-divider']:['interior','summary'],
      safeSourceImageSlotCount:narrativeLayoutCapabilities(layout).automaticContentEligible?sourceImageFrames(layout).length:0,
      htmlComposition:{mode:'source-first',design:layout.htmlDesign,bodyChars:layout.htmlBodyChars,textHosts:layout.slots.filter((s:any)=>!s.cell&&!['brand','logo','footer','page_number'].includes(s.role)).slice(0,20).map((s:any)=>({shapeId:s.shapeId,role:s.role,size:s.size,box:{x:s.x,y:s.y,w:s.w,h:s.h}})),filledBlocks:(layout.sourceObjects??[]).filter((o:any)=>o.fill?.color&&!['brand','logo','background'].includes(o.role)).length},
      ...(layout.htmlChartStyle?{chartStyle:{type:layout.htmlChartStyle.type,palette:layout.htmlChartStyle.palette}}:{}),
      visualSlots:(layout.imageSlots??[]).filter((slot:any)=>!slot.protected).map((slot:any,slotIndex:number)=>({slotIndex,aspectRatio:slot.aspectRatio,box:slot.box})),
    }:({
      id:layout.id,name:layout.name,editability:layoutEditability(layout),narrativeCapabilities:narrativeLayoutCapabilities(layout),charts:layout.charts,
      safeSourceImageSlotCount:narrativeLayoutCapabilities(layout).automaticContentEligible?sourceImageFrames(layout).length:0,
      ...(layout.htmlTemplateLayout?{htmlComposition:{adaptive:true,bodyChars:layout.htmlBodyChars,design:layout.htmlDesign,instruction:'Recompose within vision-approved source panels. Tiny sample frames may grow inside those panels, never across artwork. Choose by meaning, panel capacity and source design.'}}:{}),
      ...(layout.htmlRole?{templateRole:layout.htmlRole,allowedPositions:layout.htmlRole==='cover'?['first']:layout.htmlRole==='closing'?['last']:layout.htmlRole==='section'?['section-divider']:['interior','summary']}:{}),
      ...(layout.derivedMediaKind?{derivedMediaKind:layout.derivedMediaKind,derivedSourceLayoutId:layout.derivedSourceLayoutId}:{}),
      tables:[...new Set(layout.slots.filter(slot=>slot.cell).map(slot=>slot.shapeId))].map(shapeId=>({shapeId,cells:layout.slots.filter(slot=>slot.shapeId===shapeId).length})),
      requiresRepair:!!layout.requiresRebuild,
      compositionFamily:layout.slots.map(slot=>[slot.cell?'cell':slot.role,Math.round(slot.x/40),Math.round(slot.y/40),Math.round(slot.w/40),Math.round(slot.h/40)]),
      visualSlots:(layout.imageSlots||layout.visualSlots||[]).filter((slot:any)=>!slot.protected&&!['icon','logo','decoration','footer','page_number'].includes(slot.sourceRole))
        .map((slot:any,slotIndex:number)=>({slotIndex,requiresOpaque:!!slot.requiresOpaque,aspectRatio:slot.aspectRatio})),
      fields:layout.slots.map(slot=>({key:slot.key,text:slot.text.slice(0,120),role:slot.role,maxChars:Math.min(slot.maxChars,slot.textFit?.targetChars??Infinity),fontSize:slot.size})),
    })),
  };
}
export async function generatePlan(p: Project, signal: AbortSignal) {
  const refreshed=await ensureSourceRecovery(p, signal);
  // Recovery replaces native geometry. Reapply the cached visual style after
  // that replacement so old drafts cannot lose content roles or data slots.
  if(refreshed)await (await import('./html-pipeline.js')).prepareHtmlTemplate(p,signal);
  await prepareSourceFigureEvidence(p, signal);
  await researchProject(p, signal);
  const facts = projectFacts(p);
  await checkpoint(
    p,
    "planning",
    "Модель составляет план и предлагает исходные макеты",
  );
  let recoveredWarnings:Project['planWarnings']=[];
  const request = {
    stage: "plan",
    folder: projectDir(p.id),
    signal:AbortSignal.any([signal,AbortSignal.timeout(90_000)]),
    timeoutMs:45_000,transportAttempts:1,
    maxTokens:Math.min(14_000,2_000+p.brief!.count*700),
    alternateModelOnLastAttempt:true,
    prompt:stylePlanningPrompt+'\n'+presentationDataPrompt+'\n'+htmlPlanningFormat+'\n'+(engineContext()?.mediaPlanningPrompt??''),
    payload: {...uploadedPlanningContext(p),narrativePolicy,dataPolicy:presentationDataPrompt,
      htmlStatisticsInstruction:'Если htmlDataCapabilities.layouts не пуст, ограничение выбора только нативных объектов относится к старому нативному режиму. HTML позволяет построить редактируемый график или таблицу в исходной свободной панели. Анализируй подтверждённые числа ДО утверждения плана: для сопоставимых значений предложи столбчатый график, для динамики — линию; для разной природы/валют/охвата — таблицу или независимые метрики. В brief явно укажи тип визуализации, категории, единицу, период и какие подтверждённые факты используются. Для числовой темы стремись к 1–2 осмысленным визуализациям, если данные позволяют. Не выбирай количественный график только ради квоты. Не превращай график в фото и не расходуй квоту фотографий на HTML-диаграмму.'},
    validate: (value:unknown) => {
      const recovered=recoverPlanProposal(p,value);
      const parsed=validatePlan(p,recovered.plan,engineContext()?.mediaPolicy);
      if(p.analysis.htmlTemplate&&parsed.slides.some(slide=>!slide.visualPlan))throw new Error('html_plan_visual_missing');
      recoveredWarnings=recovered.warnings;
      return p.analysis.htmlTemplate?describeHtmlPlanVisuals(parsed):parsed;
    },
  };
  const candidatePath=join(projectDir(p.id),'plan-candidate.json');
  const identity=createHash('sha256').update(JSON.stringify([2,request.prompt,request.payload,engineContext()?.locale,engineContext()?.instructions])).digest('hex');
  let plan:Outline|undefined;
  let cached:any;
  try{cached=await readJson(candidatePath);}catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT'&&!(error instanceof SyntaxError))throw error;}
  if(cached?.identity===identity){try{plan=request.validate(cached.candidate);}catch{/* The model will repair this exact rejected proposal below. */}}
  plan??=await llmJson({...request,...(cached?.identity===identity?{initialCandidate:cached.candidate}:{}),onCandidate:async candidate=>{
    if(JSON.stringify(candidate).length<=200_000)await writeJson(candidatePath,{identity,candidate});
  }});
  const dataPlan=attachPlannedData(p,plan);plan=dataPlan.plan;
  matchPlanConcepts(p.analysis,plan.slides);
  p.planWarnings = [...recoveredWarnings,...dataPlan.warnings,...planQualityWarnings(plan, facts, (p.research?.evidence || []).map(e => e.id), engineContext()?.locale)];

  p.revision++;
  p.plan = { slides: plan.slides.map((s) => ({ ...s, id: randomUUID() })) };
  delete p.result;
  await writeJson(join(projectDir(p.id), `plan-r${p.revision}.json`), p.plan);
  await checkpoint(
    p,
    "plan_ready",
    "Проверьте план и выберите макет для каждого слайда",
  );
}
