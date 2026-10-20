/** A standalone sample statistic is a value region, never a content headline.
 * Keep a plain calendar year eligible as a genuine section heading. */
export function standaloneSourceStatistic(value:unknown){
  const text=String(value??'').trim();
  if(/^(?:19|20)\d{2}$/.test(text))return false;
  return /^(?:[$€£₽]\s*)?[+−-]?\d[\d\s.,'’\u202f\u00a0]*(?:\s*(?:%|‰|кг|kg|тонн?|т|млн|тыс|млрд|million|billion|thousand))?$/iu.test(text);
}
