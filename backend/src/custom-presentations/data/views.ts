import type { PresentationDataView } from "../engine/data-contract.js";

type Column = {
  name: string;
  type: "number" | "date" | "text";
  unit: string;
  missing: number;
};
const names: Record<string, string> = {
  year: "Год",
  species: "Вид",
  island: "Остров",
  sex: "Пол",
  economy_name: "Страна",
  economy_code: "Код страны",
  population_people: "Население",
  gdp_per_capita_constant_2015_usd: "ВВП на человека, в ценах 2015 года",
  internet_users_pct: "Пользователи интернета",
  electricity_access_pct: "Доступ к электричеству",
  observed_birds_n: "Число наблюдавшихся птиц",
  bill_length_mm: "Длина клюва",
  bill_depth_mm: "Высота клюва",
  flipper_length_mm: "Длина ласты",
  body_mass_g: "Масса тела",
  co2_mean_ppm: "Среднегодовая концентрация CO₂",
  annual_mean_uncertainty_ppm: "Неопределённость годового среднего",
};
export const dataFieldLabel = (name: string) =>
  names[name.toLowerCase()] ?? name.replace(/_/g, " ");
export const dataFieldDefinition = (name: string) =>
  /gdp.*per.capita|ввп.*(?:душу|человека|жителя)/iu.test(name)
    ? "ВВП на человека — объём произведённого экономического продукта в расчёте на жителя. Это не личный, средний заработанный или располагаемый доход человека. Сохраняйте указанный вид цен и валюту."
    : /observed_birds_n|число наблюдавшихся/iu.test(name)
      ? "Количество птиц в наблюдаемой выборке, а не оценка численности вида в природе."
      : undefined;
export function dataFieldUnit(name: string) {
  if (/_pct$/i.test(name)) return "%";
  if (/_ppm$/i.test(name)) return "ppm";
  if (/_mm$/i.test(name)) return "мм";
  if (/_kg$/i.test(name)) return "кг";
  if (/_g$/i.test(name)) return "г";
  if (/_people$/i.test(name)) return "чел.";
  if (/usd$/i.test(name)) return "USD";
  return "";
}
const identifier = (name: string) =>
  /(?:^id$|(?:^|_)(?:code|id|latitude|longitude)(?:_|$)|код|широта|долгота)/i.test(
    name,
  );
const context = (name: string) =>
  /uncertainty|погрешност|неопредел[её]нност|standard.?error/i.test(name);
const ordered = (label: string) =>
  /^\d{1,2}[./]\d{1,2}[./]\d{4}$/.test(label)
    ? label
        .split(/[./]/)
        .reverse()
        .map((s) => s.padStart(2, "0"))
        .join("-")
    : label;

/** Detect the observational grain before choosing marks. Repeated individual
 * measurements are a group comparison, not a time series with duplicate years.
 * Computed means are explicit, auditable and never replace missing values. */
export function buildDataViews(
  tableId: string,
  sourceLabel: string,
  rows: string[][],
  columns: Column[],
  number: (raw: string) => number | null,
): PresentationDataView[] {
  const views: PresentationDataView[] = [];
  const dates = columns
    .map((column, index) => ({ ...column, index }))
    .filter((c) => c.type === "date");
  const time = dates.find(
    (c) => new Set(rows.map((row) => row[c.index])).size > 1,
  );
  const dimensions = columns
    .map((column, index) => ({ ...column, index }))
    .filter(
      (c) =>
        c.type === "text" &&
        !identifier(c.name) &&
        rows.filter((row) => row[c.index]).length >=
          Math.max(2, rows.length * 0.25),
    );
  const ranked = [...dimensions].sort(
    (a, b) =>
      Number(
        /name|назван|species|вид|страна|регион|region|category|категор/i.test(
          b.name,
        ),
      ) -
      Number(
        /name|назван|species|вид|страна|регион|region|category|категор/i.test(
          a.name,
        ),
      ),
  );
  const primary = ranked[0];
  const numericX =
    !time &&
    columns[0]?.type === "number" &&
    /^(?:x|t|ось\s*x|координата\s*x|time|время)(?:\s|[,([\]]|$)/iu.test(
      columns[0]!.name,
    );
  const measures = columns
    .map((column, index) => ({ ...column, index }))
    .filter(
      (c) =>
        c.type === "number" &&
        !identifier(c.name) &&
        !(
          (numericX || (!primary && !time && columns.length > 1)) &&
          c.index === 0
        ),
    );
  for (const column of measures.slice(0, 12)) {
    const label = dataFieldLabel(column.name),
      unit = column.unit || dataFieldUnit(column.name);
    const clean = rows
      .map((row, index) => ({
        row,
        index,
        value: number(row[column.index] ?? ""),
      }))
      .filter(
        (p): p is { row: string[]; index: number; value: number } =>
          p.value !== null &&
          (!time || !!p.row[time.index]) &&
          (!numericX || number(p.row[0] ?? "") !== null) &&
          !/^(?:итого|всего|total|grand total)$/i.test(
            primary ? (p.row[primary.index] ?? "") : "",
          ),
      );
    if (!clean.length) continue;
    const missing = rows.length - clean.length,
      period = dates
        .flatMap((c) => rows.map((row) => row[c.index]!))
        .filter(Boolean)
        .sort();
    const periodLabel = period.length
      ? `Период: ${period[0]}${period[0] !== period.at(-1) ? "–" + period.at(-1) : ""}.`
      : "";
    const qualification = [
      `${sourceLabel}. ${label}${unit ? ` (${unit})` : ""}.`,
      periodLabel,
      missing
        ? `Не включено ${missing} строк с пропусками или итогами; пропуски не заменялись нулём.`
        : "",
    ]
      .filter(Boolean)
      .join(" ");
    const add = (suffix: string, partial: Partial<PresentationDataView>) =>
      views.push({
        id: `${tableId}:v${column.index}${suffix}`,
        title: label,
        kind: "chart",
        chartType: "bar",
        unit,
        categoryLabel: "",
        categories: [],
        series: [],
        caption: qualification.slice(0, 1200),
        observations: clean.length,
        missing,
        sourceRows: [],
        purpose: context(column.name) ? "context" : "evidence",
        definition: dataFieldDefinition(column.name),
        ...partial,
      });
    const keys = primary
      ? [...new Set(rows.map((row) => row[primary.index]).filter(Boolean))]
      : [];
    const uniqueTime =
      time && new Set(rows.map((row) => row[time.index])).size === rows.length;
    const panel =
      !uniqueTime &&
      time &&
      primary &&
      keys.length <= 6 &&
      rows.every((row) => row[primary.index]) &&
      new Set(
        rows.map((row) =>
          JSON.stringify([row[time.index], row[primary.index]]),
        ),
      ).size === rows.length;
    if (uniqueTime || panel) {
      const groups = panel ? keys : [""];
      const grouped = groups.map((group) =>
        clean
          .filter((p) => !panel || p.row[primary!.index] === group)
          .sort((a, b) =>
            ordered(a.row[time!.index]!).localeCompare(
              ordered(b.row[time!.index]!),
            ),
          ),
      );
      // Preserve incomplete panels separately. No interpolation or zero filling.
      const aligned = grouped.every(
        (group) =>
          JSON.stringify(group.map((p) => p.row[time!.index])) ===
          JSON.stringify(grouped[0]?.map((p) => p.row[time!.index])),
      );
      const sets = aligned
        ? [{ name: "", groups }]
        : groups.map((name) => ({ name, groups: [name] }));
      for (const set of sets) {
        const samples = set.groups.map(
            (group) => grouped[groups.indexOf(group)]!,
          ),
          first = samples[0];
        if (!first?.length) continue;
        const indices = sampleIndices(
            first.map((p) => p.value),
            36,
          ),
          selection =
            indices.length < first.length
              ? ` Показаны ${indices.length} из ${first.length} наблюдений, включая крайние значения; весь ряд сохранён в источнике.`
              : "";
        add(set.name ? `:g${groups.indexOf(set.name)}` : "", {
          title: label + (set.name ? ` — ${set.name}` : ""),
          kind: first.length > 1 ? "chart" : "metrics",
          chartType: "line",
          categoryLabel: dataFieldLabel(time!.name),
          categories: indices.map((i) => first[i]!.row[time!.index]!),
          series: set.groups.map((group, i) => ({
            name: group || label,
            values: indices.map((n) => samples[i]![n]!.value),
          })),
          sourceRows: indices.map((i) => first[i]!.index + 1),
          caption: (qualification + selection).slice(0, 1200),
        });
      }
      continue;
    }
    // Small, named groups with repeated observations support an explicit mean.
    // A table with no group dimension never silently aggregates duplicate years.
    if (
      primary &&
      keys.length >= 2 &&
      keys.length <= 12 &&
      rows.every((row) => row[primary.index]) &&
      clean.length > keys.length &&
      rows.length >= keys.length * 2
    ) {
      const groups = keys
        .map((key) => ({
          key,
          points: clean.filter((p) => p.row[primary.index] === key),
        }))
        .filter((g) => g.points.length);
      if (groups.length < 2) continue;
      add(":mean", {
        title: `${label}: среднее по ${dataFieldLabel(primary.name).toLowerCase()}`,
        chartType: "bar-horizontal",
        categoryLabel: dataFieldLabel(primary.name),
        categories: groups.map((g) => g.key!.slice(0, 180)),
        series: [
          {
            name: `Среднее: ${label}`,
            values: groups.map(
              (g) =>
                g.points.reduce((n, p) => n + p.value, 0) / g.points.length,
            ),
          },
        ],
        aggregation: {
          method: "mean",
          groupBy: dataFieldLabel(primary.name),
          sampleSizes: groups.map((g) => g.points.length),
        },
        caption: (
          qualification +
          ` Среднее арифметическое по группам; n: ${groups.map((g) => `${g.key} — ${g.points.length}`).join(", ")}. Различия описывают выборку, а не причинный эффект.`
        ).slice(0, 1200),
      });
      continue;
    }
    const category = numericX ? 0 : (primary?.index ?? time?.index ?? 0);
    let points = clean
      .filter((p) => !numericX || number(p.row[category]!) !== null)
      .map((p) => ({
        ...p,
        label: numericX
          ? String(number(p.row[category]!))
          : p.row[category] || String(p.index + 1),
      }));
    const total = points.length;
    if (!total) continue;
    if (total > 24)
      points = [...points]
        .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
        .slice(0, 12);
    const unique = new Set(points.map((p) => p.label)).size === points.length;
    const share =
      unique &&
      total <= 6 &&
      !missing &&
      /доля|структура|состав|share|composition/i.test(column.name) &&
      unit === "%" &&
      points.every((p) => p.value >= 0) &&
      Math.abs(points.reduce((sum, p) => sum + p.value, 0) - 100) < 0.11;
    add("", {
      kind: points.length === 1 ? "metrics" : "chart",
      chartType: numericX
        ? "xy"
        : share
          ? "donut"
          : points.some((p) => p.label.length > 18)
            ? "bar-horizontal"
            : "bar",
      categoryLabel: dataFieldLabel(columns[category]!.name),
      categories: points.map((p) => p.label.slice(0, 180)),
      series: [{ name: label, values: points.map((p) => p.value) }],
      sourceRows: points.map((p) => p.index + 1),
      caption: (
        qualification +
        (total > points.length
          ? ` Показаны ${points.length} наибольших по модулю значений из ${total}; полная таблица сохранена в источнике.`
          : "") +
        (!unique
          ? " Повторяющиеся категории — отдельные наблюдения; значения не суммировались."
          : "")
      ).slice(0, 1200),
    });
  }
  return views.slice(0, 12);
}
function sampleIndices(values: number[], limit: number) {
  if (values.length <= limit) return values.map((_, i) => i);
  const min = values.indexOf(Math.min(...values)),
    max = values.indexOf(Math.max(...values)),
    indices = new Set([0, values.length - 1, min, max]);
  for (let i = 0; i < limit - 4; i++)
    indices.add(Math.round((i * (values.length - 1)) / (limit - 5)));
  return [...indices].sort((a, b) => a - b);
}
