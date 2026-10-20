/** Provenance belongs to notes. A chart's visible caption explains the data
 * and its finding in ordinary language, without importing parser diagnostics. */
export const technicalDataCopy=(text:string)=>/(?:^|\n)\s*(?:Источник|Источники|Source|Период|Методика)\s*:|\.(?:csv|xlsx?|json|txt|docx?|pptx?|pdf)\b|(?:не\s+)?включен[оы]?\s+\d+\s+строк|пропуск(?:и|ов|ами|а|ах|ом)(?!\p{L})|замен[а-я\s]*нул[яеёь]|исходн[а-я]*\s+(?:файл|таблиц)|sourceRows|dataViewId|safeSurfaces|Рассчитано по исходным данным|(?:на\s+графике\s+)?показан[оы]?\s+\d+\s+из\s+\d+\s+наблюдени|https?:\/\//iu.test(text);

/** Check explicit fold comparisons against the chart actually being bound.
 * Other linguistic/factual claims remain part of the model's visual review. */
export function dataFoldComparisonMatches(text:string,series:Array<{values:number[]}>){
 const claims=[...text.matchAll(/(\d+(?:[.,]\d+)?)\s+раз(?:а|ов)?(?!\p{L})/giu)];
 if(!claims.length)return true;
 if(series.length!==1||!series[0]!.values.length)return false;
 const values=series[0]!.values;if(values.some(n=>!Number.isFinite(n)||n<=0))return false;
 const ratios=[Math.max(...values)/Math.min(...values),Math.max(values[0]!,values.at(-1)!)/Math.min(values[0]!,values.at(-1)!)];
 return claims.every(([,raw])=>{const digits=raw!.split(/[.,]/)[1]?.length??0,value=Number(raw!.replace(',','.'));return ratios.some(ratio=>Number(ratio.toFixed(digits))===value);});
}

export function correctEndpointDuration(title:string,views:Array<{chartType?:string;categories:string[]}>){
 if(!/рост|прирост|прибав|плюс|увелич|изменени|разниц/iu.test(title))return title;
 return title.replace(/за\s+(\d+)\s+(?:лет|года?)(?!\p{L})/giu,(claim,raw)=>{
  const spans=views.filter(view=>view.chartType==='line'&&view.categories.length===Number(raw)&&view.categories.every((value,i)=>/^\d{4}$/.test(value)&&Number(value)===Number(view.categories[0])+i));
  const endpoints=[...new Set(spans.map(view=>`${view.categories[0]}–${view.categories.at(-1)}`))];
  // Correct only the unambiguous off-by-one: observations != elapsed time.
  if(endpoints.length!==1)return claim;
  const years=Number(raw)-1,word=years%10===1&&years%100!==11?'год':[2,3,4].includes(years%10)&&![12,13,14].includes(years%100)?'года':'лет';
  return `за ${years} ${word}`;
 });
}

export function chartExplanation(paragraphs:string[],fallback:string){
  // A multi-sentence receipt is one technical block. Filtering its sentences
  // separately can leak detached fragments such as "Период: ..." back on slide.
  const candidates=paragraphs.filter(text=>!technicalDataCopy(text)).flatMap(text=>text.split(/(?<=[.!?])\s+(?=[А-ЯЁA-Z])/u)).map(text=>text.trim()).filter(text=>text&&!/^Визуализация:|^Показать\b|^Раскрыть\b/iu.test(text));
  const concise=(items:string[])=>{
    const result:string[]=[];let words=0,length=0;
    for(const item of items){const count=item.split(/\s+/u).length;if(words+count>42||length+item.length>360)break;result.push(item);words+=count;length+=item.length;if(result.length===3)break;}
    return result.join(' ');
  };
  return concise(candidates)||concise(fallback.split(/(?<=[.!?])\s+(?=[А-ЯЁA-Z])/u))||fallback;
}
