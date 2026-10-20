import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {readFile,rm,readdir,copyFile,access} from 'node:fs/promises';
import sharp from 'sharp';
import type {Project} from './domain.js';
import {llmJson} from './llm.js';
import {native} from './pipeline.js';
import {engineContext,engineEnv} from './runtime-context.js';
import {writeJson,readJson,saveProject,projectDir} from './store.js';
import {htmlCopyPrompt,normalizeHtmlCopy,approvedHtmlCopy,htmlFarewellLayout,currentHtmlTemplate,htmlEngineVersion,htmlTemplateVersion,removableHtmlIcons,type HtmlWarning,type HtmlCopy} from './html-domain.js';
import {createGenerationLimiter,generationBudget,htmlRepairRenderMs,htmlInitialRenderMs} from './generation-budget.js';
import {uniqueWarnings} from './quality-warnings.js';
import {classifyHtmlRoles,enforceHtmlPlanRoles,htmlRoleVersion} from './html-layout-roles.js';
import {measuredHtmlDesign} from './html-design.js';
import {htmlVisualReviewSchema,htmlVisualReviewPrompt,htmlTargetedReviewPrompt,applyHtmlVisualRepairs,visibleHtmlReviewCopy,hasHtmlRepairAction} from './html-visual-review.js';
import {sourceHtmlDesign} from './html-source-design.js';
import {htmlAuthorBatches,normalizeHtmlBatch,missingHtmlBindings,missingHtmlLayoutStyles,acceptedHtmlRepair} from './html-author-batches.js';
import {htmlTemplateContext,sourceHtmlVersion,htmlReviewBatches,htmlReviewCoverage,type HtmlAssessment} from './html-template-context.js';
import {normalizeHtmlSourceBindings} from './html-bindings.js';
import {prepareStyleStencils,bindStyleData,stencilDataPreview} from './style-stencils.js';
import {dataViews,presentationDataPrompt} from './data-contract.js';
import {shapeModernizationAssessmentPrompt,sourceFidelityPrompt} from './html-design-policies.js';
import {htmlAuthorResponseSchema} from './html-author-schema.js';
import {clearDrawnSampleData} from './html-sample-data.js';
import {cssCanvas,cssSourceDesign,cssDesignBounds,cssText,cssMeasuredScene} from './html-model-geometry.js';
import {createHtmlProgress} from './html-progress.js';
import {htmlAuthorContext} from './html-author-context.js';
import {meaningReviewPrompt,sourceResetReviewPrompt} from './style-prompts.js';
import {learnChartStyles} from './chart-style-learning.js';
import {chartStyleVersion} from './chart-style.js';
import {verifySourceChartGradients} from './chart-gradient.js';

const textCapacity=createGenerationLimiter(Math.max(1,Math.min(32,Number(process.env.PRESENTATION_HTML_TEXT_CONCURRENCY)||4)));
const hash=(value:unknown)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function htmlGenerationIdentity(p:Project,references:any[],templateContext:any,addons:string[],locale:string|undefined){
  return hash({version:htmlEngineVersion,authorPolicy:hash(htmlCopyPrompt),templateContext:templateContext.digest,sourceHtml:references.map(r=>r.sourceHtml?.digest),plan:p.plan!.slides.map(({id,...slide})=>slide),source:p.brief,addons,locale});
}
const layoutFindings=new Set(['html_text_overflow','html_text_too_small','html_native_bounds','html_low_contrast','html_busy_background','html_source_icon_overlap','html_author_recovered',
  'html_duplicate_metric','html_source_title_drift','html_source_typography_drift','html_source_art_overlap','html_text_overlap','html_photo_missing',
  'html_source_container_empty','html_source_container_drift','html_source_padding','html_source_image_overlap','html_source_row_empty','html_source_structure_removed','html_source_visual_abandoned','html_source_figure_too_small']);
const criticalFindings=new Set(['html_text_overflow','html_text_too_small','html_native_bounds','html_low_contrast','html_busy_background','html_source_icon_overlap','html_author_recovered','html_text_overlap','html_source_container_empty','html_source_container_drift','html_source_padding','html_source_image_overlap','html_source_row_empty','html_source_structure_removed','html_source_visual_abandoned','html_source_figure_too_small']);
export async function prepareHtmlTemplate(p:Project,signal:AbortSignal){
  const current=currentHtmlTemplate(p.analysis);
  if(current&&!p.plan&&p.analysis.htmlRoleVersion===htmlRoleVersion&&(p.analysis as any).htmlChartStyleVersion===chartStyleVersion&&(p.analysis as any).htmlChartGradientVersion===chartStyleVersion&&p.analysis.layouts.every((layout:any)=>layout.htmlSource?.version===sourceHtmlVersion))return;
  if(!current||p.analysis.htmlRoleVersion!==htmlRoleVersion){await classifyHtmlRoles(p.analysis,join(projectDir(p.id),'source'),signal);delete (p.analysis as any).htmlChartGradientVersion;}
  if((p.analysis as any).htmlChartStyleVersion!==chartStyleVersion)await learnChartStyles(p.analysis,join(projectDir(p.id),'source'),signal);
  await verifySourceChartGradients(p.analysis,join(projectDir(p.id),'source'));
  // Role classification writes its reviewed removal IDs. Apply deterministic
  // sample-data removal afterwards, so the upload cache already contains it.
  // Otherwise generation unnecessarily re-rendered 15 backgrounds (~28s).
  clearDrawnSampleData(p.analysis);
  prepareStyleStencils(p.analysis);
  // The sandbox reads this authoritative mirror. Include enriched picture and
  // protected-art geometry before importing, rather than the raw parser file.
  await writeJson(join(projectDir(p.id),'source','analysis.json'),p.analysis);
  // A DOM compiler upgrade refreshes every stale profile without paying for
  // another vision classification or changing the immutable source artwork.
  const selected=p.plan?.slides.map(s=>s.sourceLayoutId)??p.analysis.layouts.filter((layout:any)=>layout.htmlSource?.version!==sourceHtmlVersion).map((layout:any)=>layout.id);
  // Upload analysis already owns these immutable profiles and backgrounds.
  // Starting another sandbox here consumed 21 seconds of the real author's
  // deadline even when the import receipt and artwork were current.
  let template:any;
  if(current)try{
    const saved=await readJson(join(projectDir(p.id),'source','html-template.json'));
    const required=selected.length?selected:p.analysis.layouts.map((l:any)=>l.id);
    if(saved.artworkVersion===16&&saved.sourceSha256===p.analysis.sha256&&required.every((id:string)=>saved.layouts?.some((l:any)=>l.id===id&&l.sourceHtml?.version===sourceHtmlVersion&&
      JSON.stringify([...(l.removedShapeIds??[])].sort())===JSON.stringify([...(p.analysis.layouts.find((v:any)=>v.id===id)?.htmlRemoveShapeIds??[])].sort())))){
      await Promise.all(saved.layouts.filter((l:any)=>selected.includes(l.id)).flatMap((l:any)=>[l.background,l.nativeBackground].filter(Boolean).map(name=>access(join(projectDir(p.id),'source',name)))));
      template=saved;
    }
  }catch{}
  template??=await native('html_template',join(projectDir(p.id),'source'),{reuseArtwork:true,profilesOnly:current,selectedLayoutIds:selected},signal);
  p.analysis.htmlTemplate={version:htmlTemplateVersion,sourceSha256:template.sourceSha256,digest:template.digest,layoutIds:template.layouts.map((layout:any)=>layout.id)};
  for(const layout of p.analysis.layouts){
    const imported=template.layouts.find((item:any)=>item.id===layout.id);
    if(imported){layout.pageNumberShapeIds=[...new Set([...(layout.pageNumberShapeIds??[]),...(imported.pageNumbers??[]).map((s:any)=>s.shapeId).filter(Number.isInteger)])];layout.slots.forEach((slot:any)=>{if(layout.pageNumberShapeIds.includes(slot.shapeId))slot.role='page_number';});layout.htmlTemplateLayout=true;layout.htmlBodyChars=Math.max(160,Math.min(1000,Math.round(imported.body.w*imported.body.h/160)));
      layout.htmlStyleInk=imported.ink;layout.htmlStyleHeadingInk=imported.titleColor;
      if(imported.sourceHtml)layout.htmlSource=imported.sourceHtml;
      if(imported.design){
        const rect=(b:any)=>({x:b.x/p.analysis.width*1000,y:b.y/p.analysis.height*1000,w:b.w/p.analysis.width*1000,h:b.h/p.analysis.height*1000});
        layout.htmlDesign={canvas:imported.design.canvas,title:rect(imported.design.title),content:imported.design.content.map(rect),
          surfaces:(imported.design.surfaces??[]).map(rect),variants:imported.design.variants};
      }
      if(imported.safeSourceSurfaces)layout.htmlSafeSurfaces=imported.safeSourceSurfaces;
      layout.htmlUnsafeTextAnchors=imported.unsafeTextAnchors??[];
      layout.htmlMetricCapacity=imported.metricCards?.length??0;
      layout.usable=true;layout.requiresRebuild=false;}
  }
  await writeJson(join(projectDir(p.id),'source','analysis.json'),p.analysis);
}

/** One coherent content request, concurrent photographs, two bounded renderers.
 * A review failure is a warning and can never revoke an already written deck. */
export async function generateHtmlDeck(p:Project,input:{startedAt?:number;addons:string[];
  photoSlots?:Record<number,number>;
  onSlideReady?:(index:number,slide:any,output:string)=>Promise<void>;
  images:(signal:AbortSignal)=>Promise<{slides:Record<number,any[]>;files:Record<string,string>;warnings:HtmlWarning[]}>;
}) {
  const budget=generationBudget(input.startedAt,Number(engineEnv.PRESENTATION_HTML_BUDGET_MS)||240000);
  // The latest complete API runs spent ~20–31s publishing after this engine.
  // Keep headroom for final export/publication, while leaving confirmation time.
  const deliveryReserveMs=40000;
  const folder=projectDir(p.id),output=join(folder,`output-r${p.revision}`);
  const writeSheet=async(thumbnails:Buffer[],path:string,labels?:number[])=>{
    const items=thumbnails.flatMap((input,index)=>[
      {input,left:index%3*384,top:Math.floor(index/3)*240},
      {input:Buffer.from(`<svg width="384" height="24"><rect width="384" height="24" fill="white"/><text x="10" y="18" font-family="Arial" font-size="16" fill="black">Slide ${labels?.[index]??index+1}</text></svg>`),left:index%3*384,top:Math.floor(index/3)*240+216},
    ]);
    await sharp({create:{width:1152,height:240*Math.ceil(thumbnails.length/3),channels:3,background:'#ffffff'}}).composite(items).png().toFile(path);
  };
  const warnings:HtmlWarning[]=enforceHtmlPlanRoles(p.analysis,p.plan!.slides,false);
  const progress=createHtmlProgress(p,p.plan!.slides.length);
  await progress.start();
  // Optional catalogue work must leave a real render/review/repair window.
  // Candidate metadata is shortlisted before the expensive pixel reviews.
  const imageSignal=budget.signal(110000,75000);
  const images=input.images(imageSignal).catch(async()=>{
    await engineContext()?.assertActive?.();
    warnings.push({reason:'html_photos_unavailable',message:'Часть фотографий не загрузилась; исходное оформление сохранено.'});
    return {slides:{},files:{},warnings:[]} as Awaited<ReturnType<typeof input.images>>;
  });
  const imported=currentHtmlTemplate(p.analysis)&&p.analysis.layouts.every((l:any)=>l.htmlSource?.version===sourceHtmlVersion);
  try{await prepareHtmlTemplate(p,budget.signal(125000,45000));}
  catch(error){
    await engineContext()?.assertActive?.();if(!imported)throw error;
    const available=await Promise.all(p.plan!.slides.map(async slide=>{try{await access(join(folder,'source',`html-background-${p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId).index}.png`));return true;}catch{return false;}}));
    if(available.some(value=>!value))throw error;
    warnings.push({reason:'html_profile_unavailable',message:'Дополнительное измерение макетов не завершилось; используется сохранённое оформление.'});
  }
  let copy:HtmlCopy,copyReused=false,authorTransportUnavailable=false;
  const authorTiles=await Promise.all(p.plan!.slides.map(slide=>{
    const layout=p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId);
    return sharp(join(folder,'source',`html-background-${layout.index}.png`)).resize({width:384,height:216,fit:'contain'}).png().toBuffer();
  }));
  let originalCount=0;
  const originals=await Promise.all(p.plan!.slides.map(async(slide,index)=>{
    const layout=p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId);
    try{const tile=await sharp(join(folder,'source','previews',`slide-${layout.index}.png`)).resize({width:384,height:216,fit:'contain'}).png().toBuffer();originalCount++;return tile;}
    catch{return authorTiles[index]!;}
  }));
  const references=p.plan!.slides.map(slide=>sourceHtmlDesign(p.analysis,p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId)));
  const templateContext=htmlTemplateContext(p.analysis);
  const identity=htmlGenerationIdentity(p,references,templateContext,input.addons,engineContext()?.locale);
  const authorReserveMs=deliveryReserveMs+55000;
  const recovery=approvedHtmlCopy(p,engineContext()?.locale||'ru');
  const authorBatch=async(indices:number[],label:string,signal:AbortSignal,timeoutMs=90000)=>{
    try{
    const sourceSheet=join(folder,`author-batch-${label}-originals.png`),cleanSheet=join(folder,`author-batch-${label}-backgrounds.png`);
    await writeSheet(indices.map(i=>originals[i]!),sourceSheet,indices.map(i=>i+1));
    await writeSheet(indices.map(i=>authorTiles[i]!),cleanSheet,indices.map(i=>i+1));
    const response=await textCapacity(()=>llmJson({folder,stage:`html-deck-copy-${label}`,signal,images:[sourceSheet,cleanSheet],
      prompt:htmlCopyPrompt+'\n'+presentationDataPrompt+'\nAuthor ONLY the approved global indices. Use the title spine and neighbours for transitions. Read each selected source concept and cleared DOM, then choose its local composition. COVER/CLOSING fills original source title/subtitle. Never return neighbouring slides.',
      reasoning:'low',maxAttempts:1,transportAttempts:2,maxTokens:Math.min(6500,Math.max(3000,1000+indices.length*800)),
      schema:htmlAuthorResponseSchema(indices),
      timeoutMs:Math.max(1,Math.min(timeoutMs,budget.remaining()-authorReserveMs)),
      referenceContext:templateContext,
      payload:{locale:engineContext()?.locale||'ru',topic:p.brief!.topic,addons:input.addons,canvas:cssCanvas(p.analysis),
        referenceImages:'Sheet 1: ORIGINAL style references. Sheet 2: cleaned chrome/backgrounds in the SAME order. Preserve useful source body shapes/fills and bind new text inside their original hosts; adapt only defective regions. Covers/closing retain unique composition.',
        ...htmlAuthorContext(p,indices),
        approved:indices.map(index=>{const slide=p.plan!.slides[index]!;return {index,title:slide.title,brief:slide.brief,layoutRole:p.analysis.layouts.find((layout:any)=>layout.id===slide.sourceLayoutId)?.htmlRole,
          visualPlan:slide.visualPlan,sourceDesign:cssSourceDesign(references[index],true),
          ...(slide.dataViewId&&dataViews(p.brief?.dataSources).some(view=>view.id===slide.dataViewId)?{dataView:stencilDataPreview(dataViews(p.brief?.dataSources).find(view=>view.id===slide.dataViewId)!)}:{}),
          availablePhotos:input.photoSlots?.[index]??0,requiredSourceImages:(slide.sourceImageIds??[]).map(id=>({id,...p.brief?.sourceDocument?.images.find(image=>image.id===id),observed:p.sourceFigureEvidence?.images.find(image=>image.id===id)})),
          closingKind:htmlFarewellLayout(p.analysis.layouts.find((layout:any)=>layout.id===slide.sourceLayoutId),p.analysis.height)?'farewell':'summary',
          textBudget:slide.dataViewId?'one audience-facing explanation below the chart, 20–35 words; no filenames or parser/missing-row diagnostics':'one message, usually 35–80 words; fit the actual body surface'}}),
        },
      validate:raw=>normalizeHtmlBatch(raw,p.plan!,indices,recovery),
    }),signal);
    return response;
  }catch(error){
    await engineContext()?.assertActive?.();
    await writeJson(join(folder,`html-copy-error-${label}.json`),{slides:indices.map(i=>i+1),name:(error as Error)?.name,code:(error as {code?:unknown})?.code??null,
      remainingMs:budget.remaining(),
      validation:(error as {details?:{validation?:unknown}})?.details?.validation??null,
      status:(error as {details?:{status?:unknown}})?.details?.status??null}).catch(()=>{});
    return {transportFailed:(error as {code?:string})?.code==='llm_transport',copy:{thesis:recovery.thesis,slides:indices.map(i=>recovery.slides[i]!)},warnings:indices.map(index=>({slide:index+1,reason:'html_approved_content_recovered',message:'Не удалось использовать ответ ИИ для этого слайда. Содержание восстановлено по отдельным полям исходного шаблона; проверьте формулировки.'}))};
  }
  };

  try{
    const saved=await readJson(join(folder,'html-copy.json'));
    if(saved.identity!==identity)throw Object.assign(new Error('changed'),{code:'ENOENT'});
    const normalized=normalizeHtmlBatch(saved.copy,p.plan!,p.plan!.slides.map((_,i)=>i),recovery);copy=normalized.copy;warnings.push(...normalized.warnings);
    copyReused=true;
    warnings.push(...(saved.warnings??[]));
  }catch(error){
    if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;
    // Authoring is essential; reviews are optional. Reserve the measured
    // preview/export/publication path, not an extra 50 seconds for reviews.
    const batches=await Promise.all(htmlAuthorBatches(p.plan!.slides.length).map(async(indices,batch)=>{
      const value=await authorBatch(indices,String(batch+1),budget.signal(authorReserveMs,90000));
      await progress.written(indices);return value;
    }));
    warnings.push(...batches.flatMap(batch=>batch.warnings));
    authorTransportUnavailable=batches.every(batch=>'transportFailed' in batch&&batch.transportFailed);
    copy={thesis:batches[0]?.copy.thesis??recovery.thesis,slides:batches.flatMap(batch=>batch.copy.slides)};
  }
  if(copyReused)await progress.written(copy.slides.map(slide=>slide.index));
  const missing=[...new Set(warnings.filter(w=>w.reason==='html_approved_content_recovered'&&w.slide).map(w=>w.slide!-1))];
  if(missing.length&&!authorTransportUnavailable&&budget.remaining()>authorReserveMs+15000){
    // Complete only missing/invalid members, never rerun their good neighbours.
    const completed=await Promise.all(htmlAuthorBatches(missing.length,2).map((indices,batch)=>authorBatch(indices.map(i=>missing[i]!),`missing-${batch+1}`,budget.signal(authorReserveMs,35000),35000)));
    for(const result of completed){
      const failed=new Set(result.warnings.filter(w=>w.reason==='html_approved_content_recovered').map(w=>w.slide));
      for(const slide of result.copy.slides)if(!failed.has(slide.index+1)){
        copy.slides[slide.index]=slide;
        for(let i=warnings.length-1;i>=0;i--)if(warnings[i]!.slide===slide.index+1&&warnings[i]!.reason==='html_approved_content_recovered')warnings.splice(i,1);
      }
      warnings.push(...result.warnings);
    }
  }
  await writeJson(join(folder,'html-copy.json'),{identity,copy,warnings});
  copy=bindStyleData(copy,p,references,input.photoSlots,warnings);
  const normalizedBindingSlides=copy.slides.filter(slide=>normalizeHtmlSourceBindings(slide,references[slide.index])).map(slide=>slide.index+1);
  const incomplete=copy.slides.filter(slide=>(missingHtmlBindings(slide,references[slide.index]).length||missingHtmlLayoutStyles(slide))&&!warnings.some(w=>w.slide===slide.index+1&&w.reason==='html_approved_content_recovered'));
  const preflightRepaired:number[]=[];
  if(incomplete.length&&budget.remaining()>deliveryReserveMs+50000){
    try{
      const sheet=join(folder,'author-incomplete-originals.png');
      await writeSheet(incomplete.map(slide=>originals[slide.index]!),sheet,incomplete.map(slide=>slide.index+1));
      const repair=await textCapacity(()=>llmJson({folder,stage:'html-binding-repair',images:[sheet],
        signal:budget.signal(deliveryReserveMs+25000,35000),timeoutMs:35000,maxAttempts:1,transportAttempts:2,maxTokens:Math.min(7000,2500+incomplete.length*1500),reasoning:'low',
        prompt:htmlVisualReviewPrompt+'\nThis is a code preflight, before rendering. Repair ALL supplied failedSlides. Keep every content field and its exact wording. Each binding must appear exactly once. Numbered lists use ol/li; never bind a heading twice for a number and a caption. If missingLayoutStyles is true, return a compact cssPatch positioning/styling the existing classes inside the exact source frames; do not repeat unchanged HTML or content. Otherwise return only the necessary complete compact HTML/CSS. Return repairs with code only. No new claims or copy edits.',
        payload:{canvas:cssCanvas(p.analysis),failedSlides:incomplete.map(slide=>({slide:slide.index+1,content:slide,sourceDesign:cssSourceDesign(references[slide.index],true),missingBindings:missingHtmlBindings(slide,references[slide.index]),missingLayoutStyles:missingHtmlLayoutStyles(slide)}))},
        validate:raw=>htmlVisualReviewSchema.parse(raw)}),budget.signal(deliveryReserveMs+25000,35000));
      const repaired=applyHtmlVisualRepairs(copy,repair,p.plan!.slides.map(slide=>p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId)?.htmlRole??'content'),p.brief!.sourceText);
      copy=bindStyleData(repaired.copy,p,references,input.photoSlots,warnings);preflightRepaired.push(...repaired.changed.map(i=>i+1));warnings.push(...repaired.warnings);
      await writeJson(join(folder,'html-copy.json'),{identity,copy,warnings});
    }catch{await engineContext()?.assertActive?.();}
  }
  const photos=await images;warnings.push(...photos.warnings);
  // The author knows the intended frames; composition must use the photographs
  // that actually arrived. A failed optional search cannot leave a blank column.
  const actualPhotoSlots=Object.fromEntries(Object.entries(photos.slides).map(([index,items])=>[index,items.length]));
  copy=bindStyleData(copy,p,references,actualPhotoSlots,warnings);
  const authorAndPhotoReadyMs=Date.now()-budget.startedAt;
  const allowedIcons=(id:string)=>removableHtmlIcons(p.analysis.layouts.find((l:any)=>l.id===id),p.analysis.width,p.analysis.height);
  const makeSlides=(value:HtmlCopy)=>value.slides.map((slide,index)=>({...slide,sourceDesign:references[index],deckCss:value.css??'',omitSourceIconIds:slide.omitSourceIconIds.filter(id=>allowedIcons(p.plan!.slides[index]!.sourceLayoutId).includes(id)),sourceLayoutId:p.plan!.slides[index]!.sourceLayoutId,sourceReferences:p.research?.sources??[],
    sourceShapeEdits:(slide.sourceShapeEdits??[]).filter(edit=>references[index]!.editableShapes.some((s:any)=>s.shapeId===edit.shapeId)),
    ...(htmlFarewellLayout(p.analysis.layouts.find((l:any)=>l.id===p.plan!.slides[index]!.sourceLayoutId),p.analysis.height)?{title:engineContext()?.locale==='en'?'Thank you':'Спасибо'}:{}),
    images:photos.slides[index]??[],notes:input.addons.includes('presentation_speaker_notes')?slide.notes:'',
    speech:input.addons.includes('presentation_speech_text')?slide.speech:''}));
  let slides=makeSlides(copy);
  await progress.rendering();
  await writeJson(join(folder,'source','analysis.json'),p.analysis);
  const exportMs=htmlInitialRenderMs(budget.remaining()-deliveryReserveMs);
  await rm(output,{recursive:true,force:true});
  const initialRenderAt=Date.now();
  let rendered=await native('html_export',join(folder,'source'),{htmlPhase:'preview',slides,images:photos.files,output,remainingMs:Math.max(20000,exportMs-5000)},AbortSignal.timeout(exportMs));
  for(const [index,slide] of rendered.slides.entries())if(slide.native?.html?.warnings?.some((w:any)=>w.reason==='html_shape_edit_unavailable'))copy.slides[index]!.sourceShapeEdits=slide.native.html.sourceShapeEdits??[];
  const initialRenderMs=Date.now()-initialRenderAt;
  warnings.push(...rendered.warnings);
  await progress.rendered();
  const publishedSlides=new Set<number>();
  const publishReady=async(indices:number[],withWarnings=false)=>{
    await Promise.all(indices.filter(index=>!publishedSlides.has(index)).map(async index=>{
      await engineContext()?.assertActive?.();
      await input.onSlideReady?.(index,rendered.slides[index],output);
      publishedSlides.add(index);await progress.ready(index,withWarnings);
    }));
  };
  const saveHtmlProof=async()=>{
    await copyFile(join(output,'presentation.pdf'),join(folder,'source','html-proof.pdf'));
    await copyFile(join(output,'presentation.html'),join(folder,'source','html-proof.html'));
    await Promise.all(rendered.slides.map(async(slide:any,index:number)=>{
      await copyFile(join(output,`slide-${index}.png`),join(folder,'source',`html-proof-slide-${index}.png`));
      if(slide.native.html.authoredBackground)await copyFile(join(output,`authored-background-${index}.png`),join(folder,'source',`html-proof-background-${index}.png`));
    }));
    return {slides:rendered.slides,warnings:rendered.warnings};
  };
  const repairedSlides:number[]=[];
  const visualAssessments:HtmlAssessment[]=[];
  const visualReviewFailures:number[]=[];
  const pendingVisualIssues:HtmlWarning[]=[];
  const suggestedRepairs=new Map<number,NonNullable<ReturnType<typeof htmlVisualReviewSchema.parse>['repairs']>[number]>();
  const contactSheet=async()=>{
    const previews=await Promise.all(rendered.slides.map((_:unknown,index:number)=>readFile(join(output,`slide-${index}.png`))));
    const thumbnails=await Promise.all(previews.map(bytes=>sharp(bytes).resize({width:384,height:216,fit:'contain'}).png().toBuffer()));
    const sheetPath=join(output,'review-contact-sheet.png');
    await writeSheet(thumbnails,sheetPath);
    return sheetPath;
  };
  // One whole-deck assessment can reject a bad slide for a bounded repair pass.
  // A broken repair must never revoke the already written presentation.
  const reviewAt=Date.now();
  if(budget.remaining()>deliveryReserveMs+12000&&engineEnv.PRESENTATION_HTML_VISION_REVIEW!=='off'){
    try{
      await saveProject(p,'ИИ проверяет оформление и читаемость каждого HTML-слайда');
      await contactSheet();
      const reviewDesigns=rendered.slides.map((s:any)=>{const layout=p.analysis.layouts.find((l:any)=>l.id===s.native.html.sourceLayoutId);return measuredHtmlDesign(s.native.html.designBounds,layout?.htmlDesign,p.analysis.width,p.analysis.height,layout?.htmlRole??'content');});
      const measuredIssues=uniqueWarnings(warnings);
      const visibleCopy=visibleHtmlReviewCopy(copy,rendered.slides);
      const reviews=await Promise.all(htmlReviewBatches(slides.length).map(async(indices,batch)=>{
        const reviewTargets=new Set(indices.map(index=>index+1));
        try{
        // Each slide has a readable source/result pair and its complete code.
        // A tiny contact sheet cannot establish caption legibility.
        const sourcePath=join(output,`review-originals-${batch}.png`);
        await writeSheet(indices.map(index=>originals[index]!),sourcePath,indices.map(i=>i+1));
        const resultImages=await Promise.all(indices.map(async index=>{
          const resultPath=join(output,`review-result-${index}.png`);
          await sharp(join(output,`slide-${index}.png`)).resize({width:1280,withoutEnlargement:true}).png().toFile(resultPath);
          return resultPath;
        }));
        const timeoutMs=Math.min(40000,budget.remaining()-deliveryReserveMs);
        const value=await textCapacity(()=>llmJson({folder:output,stage:`html-deck-review-${batch+1}`,images:[sourcePath,...resultImages],signal:budget.signal(deliveryReserveMs,timeoutMs),
        referenceContext:templateContext,maxAttempts:1,transportAttempts:1,maxTokens:3000,timeoutMs,reasoning:'low',
        prompt:'You are a senior presentation art director. Assess EVERY supplied rendered slide exactly once. The first image shows original source compositions for comparison; remaining images are full-size generated slides in supplied order. Return JSON {assessments:[{slide,verdict:"pass"|"repair",reason}],issues:[{slide,message,reason}],repairs:[]}. Inspect actual text legibility, clipping, collisions, contrast, meaning, explanatory hierarchy and fidelity to the source. Main explanations must be readable, including captions under large numbers. One main message per slide; facts retain units and qualifications. Judge meaningful use of space: intentional whitespace is valid, but a tiny dense text cluster in a large available panel or detached fragments are defective. Retain good original source composition; ask for local repair only when there is a concrete defect. Original source patterns, colored panels and icons are intentional design. No invented occupancy quota or new colored prose cards. Return short actionable defect reasons. Read the supplied local layoutCode and deduplicated styles as well as the image. When a concrete local fix is clear, return repairs:[{slide,reason,title?,html?,cssPatch?,paragraphs?,cards?,steps?,sourceShapeEdits?}] in this SAME response to avoid a second repair request. Every repaired slide has verdict repair. Keep exact data and each nonempty binding exactly once. For managed source-composition HTML, prefer copy-only repairs: return the complete paragraphs/cards/steps array and no HTML; the source compiler will bind the new fields to the real hosts. An empty icon row requires a NEW distinct point and text path: do not reuse an existing paragraph binding twice, and do not count the separate introduction as one icon row. For a padding problem shorten repetitive complete phrases BEFORE reducing font or consuming the icon area. Main explanations should normally remain at least 16 pt (21.4 CSS px). Do not include unchanged code. Otherwise return repairs:[]. An original logo-only closing with no visible text fields is intentional; do not add or demand hidden navigation copy. A pass requires inspecting the image, not counting geometric warnings.\n'+shapeModernizationAssessmentPrompt+'\n'+sourceFidelityPrompt+'\n'+meaningReviewPrompt+'\n'+sourceResetReviewPrompt,
        payload:{topic:p.brief!.topic,thesis:copy.thesis,storySpine:visibleCopy.map(s=>({slide:s.slide,title:s.title,idea:[...s.paragraphs,...s.cards.map((c:any)=>c.title),...s.steps.map((c:any)=>c.title),s.takeaway].filter(Boolean).join(' ').slice(0,220)})),finalContentSlide:p.plan!.slides.length-1,slides:visibleCopy.filter(s=>reviewTargets.has(s.slide)),
          styles:Object.fromEntries(indices.map(index=>[hash(copy.slides[index]?.css??'').slice(0,12),copy.slides[index]?.css??''])),
          canvas:cssCanvas(p.analysis),
          referenceImages:`Image 1: numbered ORIGINAL source compositions. Remaining full-resolution result images map to slides ${indices.map(i=>i+1).join(', ')} in that order.`,
          measuredIssues:measuredIssues.filter(w=>!w.slide||reviewTargets.has(w.slide)),editableSlides:[...reviewTargets],
          scenes:rendered.slides.flatMap((slide:any,index:number)=>reviewTargets.has(index+1)?[{slide:index+1,role:p.analysis.layouts.find((layout:any)=>layout.id===slide.native.html.sourceLayoutId)?.htmlRole,
            // Read local DOM and actual pixels together. Shared styles are
            // deduplicated above instead of repeated for every scene.
            design:reviewDesigns[index],sourceDesign:cssSourceDesign({...slide.native.html.sourceDesign??references[index],sourceHtml:undefined}),designDecision:copy.slides[index]?.designDecision,sourceShapeEdits:slide.native.html.sourceShapeEdits??[],
            layoutCode:{html:copy.slides[index]?.html,cssKey:hash(copy.slides[index]?.css??'').slice(0,12)},plannedVisual:p.plan!.slides[index]?.visualPlan,chartPresentation:copy.slides[index]?.chartPresentation,
            removableIcons:(p.analysis.layouts.find((l:any)=>l.id===slide.native.html.sourceLayoutId)?.reservedRegions??[]).filter((r:any)=>allowedIcons(slide.native.html.sourceLayoutId).includes(r.shapeId)).map((r:any)=>({shapeId:r.shapeId,box:cssText(r.box)})),
            actualPanels:cssDesignBounds(slide.native.html.designBounds),
            blocks:slide.native.html.texts.map(({key,x,y,w,h,size,inkRects,sourceShapeId,overflow}:any)=>cssText({key,x,y,w,h,size,inkRects,sourceShapeId,overflow})),surfaces:slide.native.html.shapes.map(cssText),images:slide.native.html.images.length,
            photoFrames:cssMeasuredScene(slide.native.html)?.images??[]}]:[])},
        validate:raw=>{const parsed=htmlVisualReviewSchema.parse(raw);htmlReviewCoverage(indices,parsed.assessments??[]);
          if(parsed.repairs.some(r=>!reviewTargets.has(r.slide))||parsed.issues.some(r=>!reviewTargets.has(r.slide))||parsed.css)throw new Error('html_review_scope');
          for(const repair of parsed.repairs){const assessment=parsed.assessments!.find(a=>a.slide===repair.slide)!;assessment.verdict='repair';}
          return parsed;},
      }),budget.signal(deliveryReserveMs,timeoutMs));
        visualAssessments.push(...value.assessments!);
        await progress.reviewed(value.assessments!);
        // Publish accepted slides while other review batches are still running.
        // A measured defect keeps its slide private until repair/confirmation.
        await publishReady(value.assessments!.filter(a=>a.verdict==='pass'&&
          !rendered.warnings.some((warning:HtmlWarning)=>warning.slide===a.slide&&criticalFindings.has(warning.reason))&&
          !value.issues.some(issue=>issue.slide===a.slide)).map(a=>a.slide-1));
        return value;
        }catch(error){await engineContext()?.assertActive?.();visualReviewFailures.push(...indices.map(i=>i+1));
          await writeJson(join(output,`html-review-error-${batch+1}.json`),{name:(error as Error)?.name,code:(error as {code?:unknown})?.code??null,
            message:(error as Error)?.message,status:(error as {details?:{status?:unknown}})?.details?.status??null,
            validation:(error as {details?:{validation?:unknown}})?.details?.validation??null,remainingMs:budget.remaining()}).catch(()=>{});
          return {issues:indices.map(i=>({slide:i+1,reason:'html_review_unavailable',message:'Визуальная проверка ИИ не завершилась; готовый слайд сохранён для редактирования.'})),repairs:[]};}
      }));
      const review={issues:reviews.flatMap(r=>r.issues),repairs:reviews.flatMap(r=>r.repairs)};
      for(const repair of review.repairs)if(hasHtmlRepairAction(repair))suggestedRepairs.set(repair.slide,repair);
      pendingVisualIssues.push(...review.issues.map(issue=>({slide:issue.slide,reason:issue.reason==='html_review_unavailable'?'html_review_unavailable':'html_visual_review',message:issue.message})));
    }catch(error){await engineContext()?.assertActive?.();await writeJson(join(output,'html-review-error.json'),{
      name:error instanceof Error?error.name:'Error',code:(error as {code?:unknown})?.code??null,
      status:(error as {details?:{status?:unknown}})?.details?.status??null,
    }).catch(()=>{});warnings.push({reason:'html_review_unavailable',message:'Дополнительная оценка оформления не завершилась. Файлы готовы для скачивания.'});}
  }
  const reviewMs=Date.now()-reviewAt;
  const repairAt=Date.now();
  const retryRepairs=new Set<number>();
  for(let pass=0;pass<2;pass++){
    const remainingIssues=[...rendered.warnings,...normalizeHtmlCopy(copy,p.plan!).warnings.filter(w=>w.reason==='html_duplicate_metric')];
    const overflowSlides=new Set<number>([...remainingIssues.filter((w:any)=>criticalFindings.has(w.reason)).map((w:any)=>w.slide),
      ...(pass===0?visualAssessments.filter(a=>a.verdict==='repair').map(a=>a.slide):retryRepairs)]);
    if(!overflowSlides.size||budget.remaining()<=deliveryReserveMs+28000||engineEnv.PRESENTATION_HTML_VISION_REVIEW==='off')break;
    try{
      await progress.repairing([...overflowSlides].map(number=>number-1));
      const batches=htmlReviewBatches(overflowSlides.size,2).map(indices=>indices.map(i=>[...overflowSlides][i]!));
      const responses=await Promise.all(batches.map(async(numbers,batch)=>{
        const proposed=pass===0?numbers.flatMap(number=>suggestedRepairs.has(number)?[suggestedRepairs.get(number)!]:[]):[];
        numbers=numbers.filter(number=>!proposed.some(repair=>repair.slide===number));
        if(!numbers.length)return {issues:[],repairs:proposed};
        // A concrete patch already returned with visual review needs only a
        // render. Do not discard it because another slide needs a new request.
        if(budget.remaining()<=deliveryReserveMs+45000)return {issues:[],repairs:proposed};
        const sourceSheet=join(output,`repair-originals-${batch}.png`);
        await writeSheet(numbers.map(n=>originals[n-1]!),sourceSheet,numbers);
        const timeoutMs=Math.min(35000,budget.remaining()-deliveryReserveMs-15000);
        try{const response=await textCapacity(()=>llmJson({folder:output,stage:`html-code-repair-${pass+1}-${batch+1}`,images:[sourceSheet,...numbers.map(n=>join(output,`slide-${n-1}.png`))],
          referenceContext:templateContext,signal:budget.signal(deliveryReserveMs+15000,timeoutMs),
          maxAttempts:1,transportAttempts:1,maxTokens:5000,timeoutMs,reasoning:'low',prompt:htmlTargetedReviewPrompt+'\nRepair ONLY supplied slides. Use complete per-slide HTML/CSS or a precise CSS patch. Return no root css. Prefer concise copy and a shared flow container for each related group; preserve header and logo; reflow the content stencil when needed. SourceHtml is a style reference; the body may be recomposed inside the existing safe surface.',
          payload:{canvas:cssCanvas(p.analysis),topic:p.brief!.topic,deckCss:copy.css,
            referenceImages:`Image 1: numbered source compositions. Remaining result images are slides ${numbers.join(', ')}.`,
            failedSlides:numbers.map(number=>({slide:number,sourceDesign:cssSourceDesign(references[number-1],true),sourceGroups:references[number-1]?.sourceHtml?.textGroups,content:copy.slides[number-1],scene:cssMeasuredScene(rendered.slides[number-1]?.native?.html,true),
              visualAssessment:visualAssessments.find(a=>a.slide===number),issues:remainingIssues.filter((w:any)=>w.slide===number)}))},
          validate:raw=>{const value=htmlVisualReviewSchema.parse(raw);if(value.css||value.repairs.some(r=>!numbers.includes(r.slide)))throw new Error('html_repair_scope');return value;}}),budget.signal(deliveryReserveMs+15000,timeoutMs));
          return {...response,repairs:[...proposed,...response.repairs]};
        }catch(error){await engineContext()?.assertActive?.();await writeJson(join(output,`html-code-repair-error-${batch+1}.json`),{slides:numbers,name:(error as Error)?.name,code:(error as {code?:unknown})?.code??null,remainingMs:budget.remaining()}).catch(()=>{});return {issues:[],repairs:proposed};}
      }));
      const review={issues:responses.flatMap(r=>r.issues),repairs:responses.flatMap(r=>r.repairs)};
      const roles=slides.map(slide=>p.analysis.layouts.find((l:any)=>l.id===slide.sourceLayoutId)?.htmlRole??'content');
      const repaired=applyHtmlVisualRepairs(copy,{...review,css:undefined,repairs:review.repairs.filter(repair=>overflowSlides.has(repair.slide))},roles,p.brief!.sourceText);
      repaired.copy=bindStyleData(repaired.copy,p,references,actualPhotoSlots,warnings);
      if(repaired.changed.length){
        const target=output+'-code-repair';await rm(target,{recursive:true,force:true});
        const nextSlides=makeSlides(repaired.copy);
        const baseline=await saveHtmlProof();
        const repairRenderMs=htmlRepairRenderMs(initialRenderMs,repaired.changed.length,slides.length,budget.remaining()-deliveryReserveMs);
        const fixed=await native('html_export',join(folder,'source'),{htmlPhase:'preview',slides:nextSlides,images:photos.files,output:target,remainingMs:Math.max(20000,repairRenderMs-5000),repairBaseline:baseline,repairSlides:repaired.changed.map(i=>i+1)},budget.signal(deliveryReserveMs,repairRenderMs));
        for(const file of await readdir(target,{withFileTypes:true}))if(file.isFile())await copyFile(join(target,file.name),join(output,file.name));
        const changed=new Set<number>(repaired.changed.map(i=>i+1).filter(n=>!fixed.revertedSlides?.includes(n)));
        retryRepairs.clear();for(const n of overflowSlides)if(!changed.has(n))retryRepairs.add(n);
        for(let i=warnings.length-1;i>=0;i--)if(changed.has(warnings[i]!.slide!)&&layoutFindings.has(warnings[i]!.reason))warnings.splice(i,1);
        warnings.push(...fixed.warnings,...repaired.warnings);copy=acceptedHtmlRepair(copy,repaired.copy,fixed.revertedSlides??[]);rendered=fixed;slides=makeSlides(copy);repairedSlides.push(...changed);
        await writeJson(join(folder,'html-copy.json'),{identity,copy,warnings:warnings.filter(w=>['html_table_as_text','html_chart_as_text','html_approved_content_recovered'].includes(w.reason))});
        await contactSheet();
      }
    }catch(error){await engineContext()?.assertActive?.();await writeJson(join(output,`html-code-repair-failed-${pass+1}.json`),{name:(error as Error)?.name,code:(error as {code?:unknown})?.code??null,remainingMs:budget.remaining(),initialRenderMs}).catch(()=>{});warnings.push({reason:'html_code_repair_unavailable',message:'Дополнительная проверка кода не завершилась; готовые файлы сохранены.'});break;}
  }
  const repairMs=Date.now()-repairAt;
  if(!repairedSlides.length)await contactSheet().catch(()=>{});
  const confirmedRepairs=new Set<number>();
  const confirmAt=Date.now();
  if(repairedSlides.length&&engineEnv.PRESENTATION_HTML_VISION_REVIEW!=='off'&&budget.remaining()>deliveryReserveMs+12000){
    await saveProject(p,'Повторно проверяем отрисованные исправления');
    const changed=[...new Set(repairedSlides)].sort((a,b)=>a-b);
    await Promise.all(htmlReviewBatches(changed.length,2).map(async(batch,batchNumber)=>{
      const indices=batch.map(i=>changed[i]!-1);
      try{
        const sourceSheet=join(output,`confirm-originals-${batchNumber}.png`);
        await writeSheet(indices.map(i=>originals[i]!),sourceSheet,indices.map(i=>i+1));
        const timeoutMs=Math.min(35000,budget.remaining()-deliveryReserveMs);
        const check=await textCapacity(()=>llmJson({folder:output,stage:`html-repair-confirm-${indices[0]!+1}`,
          images:[sourceSheet,...indices.map(i=>join(output,`slide-${i}.png`))],referenceContext:templateContext,
          signal:budget.signal(deliveryReserveMs,timeoutMs),timeoutMs,maxAttempts:1,transportAttempts:1,maxTokens:1600,reasoning:'low',
          prompt:'Inspect each repaired slide against its ORIGINAL design and the specific prior defect. Image 1 is the numbered original source contact sheet; following images are the repaired slides in supplied order. Return JSON {assessments:[{slide,verdict:"pass"|"repair",reason}]}, EVERY supplied slide exactly once, with concise reasons. This is final visual assessment, not code rewriting. Inspect boundaries, collisions, caption readability, hierarchy and correction of the named defect. Intentional source whitespace, asymmetrical heading anchors and stepped panel edges alone are not new defects. Former sample photos and wording are removed: when assignedPhotos is zero, using the existing neutral photo frame for locally reflowed supported text is ALLOWED. Do not demand unavailable photographs or literal reproduction of sample content. Preserve outer panels, branding and visual language; a still-empty large photo zone next to cramped unreadable text remains a defect. Do not approve from metrics alone.\n'+shapeModernizationAssessmentPrompt+'\n'+meaningReviewPrompt,
          payload:{slides:indices.map(i=>({slide:i+1,copy:visibleHtmlReviewCopy(copy,rendered.slides)[i],priorAssessment:visualAssessments.find(a=>a.slide===i+1),
            assignedPhotos:rendered.slides[i]?.native?.html?.images?.length??0,designDecision:copy.slides[i]?.designDecision,sourceShapeEdits:rendered.slides[i]?.native?.html?.sourceShapeEdits??[],
            sourceSurfaces:cssSourceDesign(references[i]).availableSurfaces,warnings:rendered.warnings.filter((w:any)=>w.slide===i+1)}))},
          validate:raw=>{const parsed=htmlVisualReviewSchema.pick({assessments:true}).parse(raw);return htmlReviewCoverage(indices,parsed.assessments??[]);}}),budget.signal(deliveryReserveMs,timeoutMs));
        for(const assessment of check)if(assessment.verdict==='pass')confirmedRepairs.add(assessment.slide);
        await publishReady(check.filter(assessment=>assessment.verdict==='pass'&&
          !rendered.warnings.some((warning:HtmlWarning)=>warning.slide===assessment.slide&&criticalFindings.has(warning.reason))).map(assessment=>assessment.slide-1));
      }catch{await engineContext()?.assertActive?.();}
    }));
  }
  const confirmationMs=Date.now()-confirmAt;
  const unreviewed=slides.map((_,i)=>i+1).filter(n=>!visualAssessments.some(a=>a.slide===n));
  for(const number of unreviewed)if(!warnings.some(w=>w.slide===number&&w.reason==='html_review_unavailable'))warnings.push({slide:number,reason:'html_review_unavailable',message:'Визуальная проверка ИИ не завершена. Готовый слайд доступен для редактирования.'});
  for(const number of new Set(repairedSlides))if(!confirmedRepairs.has(number))warnings.push({slide:number,reason:'html_repair_unconfirmed',message:'Исправленная HTML-вёрстка измерена; итоговая визуальная оценка ИИ не подтверждена.'});
  warnings.push(...pendingVisualIssues.filter(issue=>!confirmedRepairs.has(issue.slide!)));
  for(const assessment of visualAssessments)if(assessment.verdict==='repair'&&!confirmedRepairs.has(assessment.slide)&&!pendingVisualIssues.some(issue=>issue.slide===assessment.slide))warnings.push({slide:assessment.slide,reason:'html_visual_review',message:assessment.reason});
  // Optional AI checks can time out. Deliver the retained, measured HTML with
  // warnings after repair attempts finish; never turn that into a hard block.
  await publishReady(slides.map((_,index)=>index),true);
  await progress.exporting();
  const formatsAt=Date.now();
  if(rendered.htmlOnly){
    await saveProject(p,'HTML-вёрстка проверена. Создаём редактируемый PowerPoint по измеренным блокам');
    // Only the final accepted HTML is handed to the format adapter. Fixed
    // proof filenames remain within the isolated source workspace and never
    // become persistent template assets or arbitrary sandbox input paths.
    await saveHtmlProof();
    const finalOutput=output+'-final';await rm(finalOutput,{recursive:true,force:true});
    try{
      rendered=await native('html_export',join(folder,'source'),{htmlPhase:'final',slides:rendered.slides,images:photos.files,output:finalOutput,remainingMs:35000},AbortSignal.timeout(40000));
    }catch{
      await engineContext()?.assertActive?.();
      rendered=await native('html_export',join(folder,'source'),{slides:rendered.slides,images:photos.files,output:finalOutput,remainingMs:45000},AbortSignal.timeout(50000));
    }
    for(const file of await readdir(finalOutput,{withFileTypes:true}))if(file.isFile())await copyFile(join(finalOutput,file.name),join(output,file.name));
    warnings.push(...rendered.warnings);
  }
  const finalWarnings=uniqueWarnings([...warnings,...normalizeHtmlCopy(copy,p.plan!).warnings]);
  p.result={slides:slides.length,pdfAvailable:rendered.pdfAvailable,warnings:finalWarnings};
  p.status='complete';p.progress={done:slides.length,total:slides.length};
  await writeJson(join(output,'html-generation-report.json'),{version:htmlEngineVersion,startedAt:budget.startedAt,
    copySource:finalWarnings.some(w=>w.reason==='html_approved_content_recovered')?'approved-plan-recovery':'model',
    durationMs:Date.now()-budget.startedAt,budgetMs:240000,htmlFirst:true,measuredSlides:rendered.slides.filter((s:any)=>s.native.html.htmlMeasured).length,authoredSlides:rendered.slides.filter((s:any,i:number)=>s.native.html.authored&&s.native.html.authored.source!=='source-frame-recovery'&&!finalWarnings.some(w=>w.reason==='html_approved_content_recovered'&&(!w.slide||w.slide===i+1))).length,
    originalReferenceSlides:originalCount,sourceHtmlSlides:references.filter(r=>r.sourceHtml?.version===sourceHtmlVersion).length,templateContextDigest:templateContext.digest,
    visualReview:{assessments:visualAssessments.sort((a,b)=>a.slide-b.slide),unreviewed,failed:visualReviewFailures.sort((a,b)=>a-b),
      confirmedRepairs:[...confirmedRepairs].sort((a,b)=>a-b),unconfirmedRepairs:[...new Set(repairedSlides)].filter(n=>!confirmedRepairs.has(n))},
    stages:{authorAndPhotoReadyMs,initialRenderMs,reviewMs,repairMs,confirmationMs,formatsMs:Date.now()-formatsAt},
    designDecisions:copy.slides.map((s,index)=>({slide:index+1,sourceConcept:references[index].concept,...s.designDecision})),
    chartFormats:rendered.slides.flatMap((slide:any,index:number)=>slide.native.html.chart?[{slide:index+1,format:slide.native.html.chart.exportedAs??'native',presentation:slide.native.html.chart.presentation}]:[]),
    copyDigest:hash(copy),normalizedBindingSlides,preflightRepaired,repairedSlides,warnings:finalWarnings});
  await saveProject(p,finalWarnings.length?'Презентация готова. Замечания доступны рядом с результатом.':'Презентация готова для скачивания');
  return {slides:rendered.slides,output,warnings:finalWarnings,copyReused};
}
