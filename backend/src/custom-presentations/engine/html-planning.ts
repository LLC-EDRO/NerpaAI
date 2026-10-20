import type {Outline} from './domain.js';

export const htmlPlanningFormat=`HTML VISUAL PLAN — обязательное дополнение к формату ответа выше.
Для КАЖДОГО слайда добавь visualPlan:{kind:"text"|"chart"|"table"|"diagram"|"metrics",chartType?:"bar"|"bar-horizontal"|"line"|"pie"|"donut"|"xy",description:"что увидит зритель"}. При attachedData добавляй dataViewId из точных ID нужной визуализации. Это решение дизайнера ДО утверждения, не новый запрос модели. Для обложки достаточно kind:text. Не оставляй визуализацию подразумеваемой только перечислением цифр.
Если в одном содержательном слайде есть хотя бы два сопоставимых подтверждённых наблюдения в одной единице за один период, планируй chart и указывай категории, единицу и период в description; разовую величину покажи metrics. Для динамики нужна упорядоченная серия. Разные валюты, определения и популяции не сравнивай одной шкалой: предложи table с оговорками. Нельзя выдумывать данные ради диаграммы. Для качественных связей выбирай diagram или table. Поле images предназначено только для фотографий/внешних иллюстраций; HTML-график не расходует их квоту. Выбирай исходный макет с подходящей свободной панелью, даже если в нём нет нативного образца графика. Это уточнение имеет приоритет над общими ограничениями о наличии нативного объекта.`;

/** Show the model's concrete visual decision in the existing editable plan UI.
 * Only newly generated plans call this; approved plans are never rewritten. */
export function describeHtmlPlanVisuals(plan:Outline):Outline{
 const labels={chart:'Диаграмма',table:'Таблица',diagram:'Схема',metrics:'Крупные показатели',text:'Текст'};
 return {slides:plan.slides.map(slide=>({...slide,brief:slide.visualPlan&&slide.visualPlan.kind!=='text'
  ?`${slide.brief}\nВизуализация: ${labels[slide.visualPlan.kind]} — ${slide.visualPlan.description}`.slice(0,2000):slide.brief}))};
}
