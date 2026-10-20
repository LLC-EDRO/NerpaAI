export function numbers(text: string) {
  const months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  const dates: string[] = [];
  text = text.replace(new RegExp(`(\\d{1,2})\\s+(${months.join('|')})\\s+(\\d{4})`, 'giu'),
    (_, day, month, year) => `${day}.${months.indexOf(month.toLowerCase())+1}.${year}`);
  text = text.replace(/\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b/g, (value, d, m, y) => {
    const date = new Date(Date.UTC(+y,+m-1,+d));
    if (date.getUTCFullYear()!==+y || date.getUTCMonth()!==+m-1 || date.getUTCDate()!==+d) return value;
    dates.push(`date:${y}-${String(+m).padStart(2,'0')}-${String(+d).padStart(2,'0')}`);
    return ' ';
  });
  // A run with several commas is a list, not pairs of decimal fractions.
  // A single decimal comma remains intact. Do not infer a magnitude from units.
  const normalized = text.replace(/\d+(?:,\d+){2,}/g, value => value.replace(/,/g, ';')).replace(
    /\b\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?\b/g,
    (value) => value.replace(/[ \u00a0\u202f]/g, ""),
  );
  return dates.concat([...normalized.matchAll(/[+−-]?\d+(?:[.,]\d+)?(?:[eE][+−-]?\d+)?(?:\s*\/\s*\d+)?/g)].map(m => {
    let value = m[0].replace(/\s/g, '').replace(',', '.').replace('−', '-');
    const before = normalized.slice(0, m.index);
    // A hyphen in an identifier or numeric range is not a negative sign.
    if (value.startsWith('-') && m[0][0] === '-' && /[\p{L}\d_]\s*$/u.test(before)) value = value.slice(1);
    return value.split('/').map(part => {
      const canonical = part.replace(/^\+/, '').replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
      return canonical === '-0' ? '0' : canonical;
    }).join('/');
  }));
}

export function planContentNumbers(text: string, evidenceIds: string[]) {
  const known = new Set(evidenceIds.map(id => id.toLowerCase()));
  return numbers(
    text
      // Named document labels are structural, even when step 1 is on slide 8.
      // Require a caption separator; leave quantities and inner facts intact.
      .replace(/(^|\n)(\s*(?:этап|шаг|пункт|слайд|иллюстрация|рисунок|таблица|раздел|глава|step|stage|slide|illustration|figure|table|section|chapter)\s+№?\s*)\d{1,3}(?=\s*[:—–.)-](?:\s|$))/giu, '$1$2')
      .replace(/\bevidence-\d+\b/gi, (id) => (known.has(id.toLowerCase()) ? "" : id)),
  );
}
// Evidence can spell small counts out; keep these separate from display values.
// Skip composite numerals instead of accidentally treating "двадцать один" as 1.

export function evidenceNumbers(text: string) {
  const small: Record<string, string> = {
    ноль: "0",
    нуля: "0",
    один: "1",
    одна: "1",
    одно: "1",
    одного: "1",
    одной: "1",
    одному: "1",
    одним: "1",
    одну: "1",
    два: "2",
    две: "2",
    двух: "2",
    двум: "2",
    двумя: "2",
    три: "3",
    трех: "3",
    трем: "3",
    тремя: "3",
    четыре: "4",
    четырех: "4",
    четырем: "4",
    четырьмя: "4",
    пять: "5",
    пяти: "5",
    шесть: "6",
    шести: "6",
    семь: "7",
    семи: "7",
    восемь: "8",
    восьми: "8",
    девять: "9",
    девяти: "9",
    десять: "10",
    десяти: "10",
  };
  const tokens =
    text
      .toLowerCase()
      .replace(/ё/g, "е")
      .match(/[\p{L}\d]+|[^\p{L}\d\s]+/gu) || [];
  const spelled = tokens.flatMap((word, i) => {
    const compound =
      /^(одно|двух|трех|четырех|пяти|шести|семи|восьми|девяти|десяти)(?:дневн|летн|годичн|месячн|недельн|часов|минутн|километров|процентн)\p{L}*$/u.exec(
        word,
      );
    const value = small[word] ?? (compound ? small[compound[1]] : undefined);
    if (value === undefined) return [];
    // Check numeral neighbours using complete known numeral words/stems, not nouns.
    const adjacent = [tokens[i - 1], tokens[i + 1]].filter(Boolean);
    if (
      adjacent.some((w) =>
        /^(?:\d+|один|одна|одно|одного|одной|два|две|двух|три|трех|четыре|пять|шесть|семь|восемь|девять|десять|\p{L}*надцать|двадцать|тридцать|сорок|пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто|сто|двести|триста|четыреста|пятьсот|шестьсот|семьсот|восемьсот|девятьсот|тысяч\p{L}*|миллион\p{L}*|миллиард\p{L}*)$/u.test(
          w,
        ),
      )
    )
      return [];
    return [value];
  });
  const fractions = [
    ...text
      .toLowerCase()
      .replace(/ё/g, "е")
      .matchAll(
        /(?<!\p{L})(?:(одна|одну|одной|две|двух|два|три|трех|\d+)\s+)?(половина|половину|половины|треть|трети|третьих|четверть|четверти|четвертых)(?!\p{L})/gu,
      ),
  ].map(
    (m) =>
      `${m[1] ? small[m[1]] || m[1] : "1"}/${m[2].startsWith("полов") ? 2 : m[2].startsWith("трет") ? 3 : 4}`,
  );
  const values = numbers(text);
  // A full date also supports displaying its year/day separately; a year alone
  // cannot support an invented full date.
  const dateParts = values.filter(v=>v.startsWith('date:')).flatMap(v=>{
    const [year,,day] = v.slice(5).split('-'); return [year,String(Number(day))];
  });
  return [...values, ...dateParts, ...spelled, ...fractions];
}
// A sample speaker signature is not a requirement for the new presentation.
// Apply this to saved contracts too, without touching native geometry or keys.
