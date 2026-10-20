import { buildDataViews, dataFieldUnit } from "./views.js";
import {
  dataSourceSchema,
  type PresentationDataSource,
} from "../engine/data-contract.js";

export interface ParsedDataTable {
  name: string;
  rows: string[][];
  sourceNotes?: string;
}
export const presentationDataAnalysisVersion = 3;
const missing = (value: string) =>
  !value.trim() ||
  /^(?:n\/?a|null|none|nan|нет данных|н\/д|[—–-])$/i.test(value.trim());
const year = (value: string) => /^(?:19|20)\d{2}$/.test(value);
const date = (value: string) =>
  year(value) ||
  /^\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?$|^\d{1,2}[./]\d{1,2}[./]\d{4}$/.test(
    value,
  );
const unitPattern =
  /(?:млрд|млн|тыс)\.?\s*(?:руб\.?|USD|EUR|RUB|₽|€|\$|чел\.?|шт\.?)|(?:руб\.?|USD|EUR|RUB|₽|€|\$|£|кг|тонн|кВт[·⋅]?ч|км|чел\.?|шт\.?|%)(?!\p{L})/iu;
function cellUnit(raw: string) {
  return (
    raw.trim().match(new RegExp(`(?:${unitPattern.source})$`, "iu"))?.[0] ??
    raw.trim().match(/^(?:[$€£₽]|USD|EUR|RUB)(?!\p{L})/iu)?.[0] ??
    ""
  );
}
const canonicalUnit = (value: string) =>
  value
    .toLowerCase()
    .replace(/[.\s]/g, "")
    .replace(/руб|rub|₽/g, "rub")
    .replace(/usd|\$/g, "usd")
    .replace(/eur|€/g, "eur");
/** Decimal commas and grouped spaces are numeric notation, never a reason to
 * turn missing cells into zeros or evaluate spreadsheet expressions. */
export function dataNumber(raw: string): number | null {
  if (missing(raw)) return null;
  let value = raw.trim();
  const suffix = cellUnit(value);
  if (suffix)
    value = value.startsWith(suffix)
      ? value.slice(suffix.length)
      : value.slice(0, -suffix.length);
  value = value
    .trim()
    .replace(/[\u00a0\u202f\s]/g, "")
    .replace(/[−–]/g, "-");
  if (/^\(.*\)$/.test(value)) value = "-" + value.slice(1, -1);
  value = value
    .replace(/^(?:[$€£₽]|USD|EUR|RUB)/i, "")
    .replace(/(?:%|[$€£₽]|руб\.?|USD|EUR|RUB)$/i, "");
  if (value.includes(",") && value.includes("."))
    value =
      value.lastIndexOf(",") > value.lastIndexOf(".")
        ? value.replace(/\./g, "").replace(",", ".")
        : value.replace(/,/g, "");
  else if (value.includes(",")) value = value.replace(",", ".");
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function unit(name: string, values: string[]) {
  const explicit = name
    .match(/\(([^()]{1,40})\)|\[([^\[\]]{1,40})\]/)
    ?.slice(1)
    .find(Boolean);
  if (explicit) return explicit;
  return (
    name.match(unitPattern)?.[0] ?? values.map(cellUnit).find(Boolean) ?? ""
  );
}

export function analyzePresentationData(
  id: string,
  fileName: string,
  sha256: string,
  tables: ParsedDataTable[],
): PresentationDataSource {
  const warnings: string[] = [];
  const datasets = tables.map((table, tableIndex) => {
    const sourceLabel =
      table.name === fileName ? fileName : `${fileName} · ${table.name}`;
    let matrix = table.rows
      .filter((row) => row.some((value) => !missing(value)))
      .map((row) => row.map((value) => value.trim()));
    // A workbook title above a real header is not a one-column data table.
    const start = matrix.findIndex(
      (row, index) =>
        row.filter((value) => !missing(value)).length >= 2 &&
        !!matrix[index + 1],
    );
    matrix = matrix.slice(Math.max(0, start));
    const width = Math.min(40, Math.max(...matrix.map((row) => row.length))),
      rawHeaders = matrix[0] ?? [];
    const firstHasData = rawHeaders.some(
      (value, index) =>
        dataNumber(value) !== null &&
        dataNumber(matrix[1]?.[index] ?? "") !== null,
    );
    const hasHeader =
      !firstHasData &&
      rawHeaders.some((value) => dataNumber(value) === null && !missing(value));
    const headers = Array.from({ length: width }, (_, i) => {
      const name = hasHeader ? rawHeaders[i] : "";
      return (name || `Колонка ${i + 1}`).slice(0, 160);
    });
    const unique = new Map<string, number>();
    headers.forEach((name, index) => {
      const n = (unique.get(name) ?? 0) + 1;
      unique.set(name, n);
      if (n > 1) headers[index] = `${name} (${n})`.slice(0, 160);
    });
    const rows = (hasHeader ? matrix.slice(1) : matrix).map((row) =>
      Array.from({ length: width }, (_, i) => row[i] ?? ""),
    );
    const columns = headers.map((name, column) => {
      const values = rows.map((row) => row[column]!),
        present = values.filter((value) => !missing(value));
      const temporal =
        /(?:год|дата|период|месяц|квартал|year|date|month|quarter)/i.test(
          name,
        ) &&
        present.length > 0 &&
        present.every(date);
      const identifier =
        /(?:^id$|код|индекс|номер|почт|phone|zip|code)/i.test(name) ||
        present.some((value) => /^0\d{2,}$/.test(value));
      const declaredUnit = unit(name, []),
        units = new Set(
          present.map(cellUnit).filter(Boolean).map(canonicalUnit),
        );
      const mixedUnits =
        units.size > 1 ||
        (!!declaredUnit &&
          [...units].some((value) => value !== canonicalUnit(declaredUnit)));
      const type = temporal
        ? "date"
        : !identifier &&
            !mixedUnits &&
            present.length &&
            present.filter((value) => dataNumber(value) !== null).length >=
              Math.ceil(present.length * 0.9)
          ? "number"
          : "text";
      if (mixedUnits)
        warnings.push(
          `${table.name}: «${name}» содержит разные единицы; значения сохранены в таблице без смешивания масштабов.`,
        );
      return {
        name,
        type: type as "number" | "date" | "text",
        unit:
          type === "number" ? unit(name, present) || dataFieldUnit(name) : "",
        missing: values.filter(missing).length,
      };
    });
    const tableId = `${id}:t${tableIndex + 1}`,
      views = buildDataViews(tableId, sourceLabel, rows, columns, dataNumber);
    if (!views.length) {
      views.push({
        id: `${tableId}:table`,
        title: table.name.slice(0, 200),
        kind: "table",
        unit: "",
        categoryLabel: "",
        categories: [],
        series: [],
        table: {
          headers: headers.slice(0, 4),
          rows: rows
            .slice(0, 8)
            .map((row) => row.slice(0, 4).map((value) => value.slice(0, 240))),
        },
        caption:
          `${sourceLabel}. ${rows.length} записей${rows.length > 8 || width > 4 ? ". Показан фрагмент: первые 8 строк и 4 колонки; весь исходник сохранён" : ""}.`.slice(
            0,
            1200,
          ),
        observations: rows.length,
        missing: 0,
        sourceRows: [],
      });
    }
    if (columns.filter((c) => c.type === "number").length > 12)
      warnings.push(
        `${table.name}: предложены первые 12 визуализаций; остальные показатели остаются в исходном файле.`,
      );
    if (columns.some((column) => column.type === "number" && column.missing))
      warnings.push(
        `${table.name}: есть пропуски; графики показывают только имеющиеся значения.`,
      );
    return {
      id: tableId,
      name: table.name.slice(0, 180),
      rowCount: rows.length,
      columns,
      views,
      ...(table.sourceNotes ? { notes: table.sourceNotes } : {}),
    };
  });
  return dataSourceSchema.parse({
    version: 1,
    analysisVersion: presentationDataAnalysisVersion,
    id,
    fileName,
    sha256,
    datasets,
    warnings: [...new Set(warnings)].slice(0, 30),
  });
}
