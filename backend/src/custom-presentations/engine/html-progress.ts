import type {Project} from './domain.js';
import {saveProject} from './store.js';
import type {HtmlAssessment} from './html-template-context.js';

export type HtmlSlideStage='writing'|'rendering'|'reviewing'|'repairing'|'ready'|'ready_with_warnings';
export interface HtmlGenerationProgress {
  phase:'writing'|'rendering'|'reviewing_visuals'|'repairing'|'saving';
  percent:number;total:number;written:number;rendered:number;reviewed:number;ready:number;
  slides:HtmlSlideStage[];
}

/** Counts completed work, including out-of-order batches. Publication counts
 * only after the owned preview and its live checkpoint have been saved. */
export function createHtmlProgress(project:Project,total:number){
  const written=new Set<number>(),reviewed=new Set<number>(),ready=new Set<number>();
  const state:HtmlGenerationProgress={phase:'writing',percent:12,total,written:0,rendered:0,reviewed:0,ready:0,
    slides:Array.from({length:total},()=>'writing')};
  project.htmlProgress=state;
  const save=async(phase:HtmlGenerationProgress['phase'],percent:number,message?:string)=>{
    state.phase=phase;state.percent=Math.max(state.percent,Math.min(97,Math.round(percent)));
    project.status=phase==='writing'?'filling':phase==='reviewing_visuals'?'reviewing_final_slides':phase==='repairing'?'repairing_html':'validating';
    project.progress={done:phase==='writing'?state.written:state.ready,total};
    await saveProject(project,message);
  };
  const reviewPercent=()=>65+18*state.reviewed/total+5*state.ready/total;
  return {
    state,
    start:()=>save('writing',12,'Создаём связное содержание и подготавливаем фотографии'),
    written:async(indices:number[])=>{
      for(const index of indices){written.add(index);if(state.slides[index]==='writing')state.slides[index]='rendering';}
      state.written=written.size;await save('writing',12+40*state.written/total);
    },
    rendering:()=>save('rendering',52,'Отрисовываем HTML и измеряем размещение элементов'),
    rendered:async()=>{
      state.rendered=total;state.slides=state.slides.map(stage=>stage==='ready'||stage==='ready_with_warnings'?stage:'reviewing');
      await save('reviewing_visuals',65,'Проверяем оформление и читаемость слайдов');
    },
    reviewed:async(assessments:HtmlAssessment[])=>{
      for(const assessment of assessments){const index=assessment.slide-1;reviewed.add(index);
        if(!ready.has(index))state.slides[index]=assessment.verdict==='repair'?'repairing':'reviewing';}
      state.reviewed=reviewed.size;await save('reviewing_visuals',reviewPercent());
    },
    repairing:async(indices:number[])=>{
      for(const index of indices)if(!ready.has(index))state.slides[index]='repairing';
      await save('repairing',reviewPercent(),'Исправляем найденные проблемы внутри исходного дизайна');
    },
    ready:async(index:number,withWarnings=false)=>{
      ready.add(index);state.ready=ready.size;state.slides[index]=withWarnings?'ready_with_warnings':'ready';
      await save(state.phase,reviewPercent());
    },
    exporting:()=>save('rendering',94,'Проверенные слайды готовы. Создаём PPTX и PDF'),
  };
}
