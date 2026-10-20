import { Worker } from "node:worker_threads";
import { HttpError } from "../../errors.js";
import { dataParserWorker } from "./parser-worker.js";
import type { ParsedDataTable } from "./analyze.js";

export const PRESENTATION_DATA_MAX_BYTES = 10 * 1024 * 1024;
export const PRESENTATION_DATA_EXTENSIONS =
  /\.(csv|tsv|xlsx|xls|xlsm|ods|json|jsonl|ndjson|xml|txt|md)$/i;
export async function parsePresentationData(
  bytes: unknown,
  encodedName: string,
  signal?: AbortSignal,
) {
  let name: string;
  try {
    name = decodeURIComponent(encodedName)
      .split(/[\\/]/)
      .at(-1)!
      .replace(/[\x00-\x1f\x7f]/g, "")
      .slice(0, 255);
  } catch {
    throw new HttpError(
      400,
      "Не удалось прочитать название файла данных.",
      "data_invalid_name",
    );
  }
  if (
    !Buffer.isBuffer(bytes) ||
    !bytes.length ||
    bytes.length > PRESENTATION_DATA_MAX_BYTES ||
    !PRESENTATION_DATA_EXTENSIONS.test(name)
  )
    throw new HttpError(
      400,
      "Загрузите CSV, TSV, Excel, ODS, JSON, XML или текстовую таблицу до 10 МБ.",
      "data_invalid_file",
    );
  signal?.throwIfAborted();
  const tables = await new Promise<ParsedDataTable[]>((resolve, reject) => {
    const worker = new Worker(dataParserWorker, {
      eval: true,
      execArgv: [],
      env: {},
      resourceLimits: { maxOldGenerationSizeMb: 192 },
      workerData: {
        bytes,
        name,
        extension: name.split(".").at(-1)!.toLowerCase(),
        xlsxModule: import.meta.resolve("xlsx"),
        zipModule: import.meta.resolve("jszip"),
        xmlModule: import.meta.resolve("fast-xml-parser"),
      },
    });
    let settled = false;
    const done = (error?: Error, value?: ParsedDataTable[]) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", aborted);
      void worker.terminate();
      error ? reject(error) : resolve(value!);
    };
    const aborted = () => done(signal?.reason ?? new Error("data_aborted"));
    const timer = setTimeout(
      () =>
        done(
          new HttpError(
            422,
            "Разбор данных занял слишком много времени. Разделите файл на несколько таблиц.",
            "data_timeout",
          ),
        ),
      15000,
    );
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) aborted();
    worker.once(
      "message",
      (result: { tables?: ParsedDataTable[]; error?: string }) => {
        if (result.tables) done(undefined, result.tables);
        else
          done(
            new HttpError(
              422,
              result.error === "data_too_large"
                ? "В одном файле поддерживаются до 12 таблиц, 10 000 строк и 40 колонок на таблицу, всего до 200 000 ячеек."
                : result.error === "data_no_table"
                  ? "Не найдена таблица. Вставьте строки с заголовками колонок, разделённые табуляцией, запятой, точкой с запятой или вертикальной чертой."
                  : "Не удалось разобрать данные. Проверьте формат, кавычки и структуру таблицы.",
              result.error ?? "data_invalid",
            ),
          );
      },
    );
    worker.once("error", () =>
      done(
        new HttpError(422, "Не удалось прочитать файл данных.", "data_invalid"),
      ),
    );
    worker.once("exit", () => {
      if (!settled)
        done(
          new HttpError(
            422,
            "Разбор данных прерван. Повторите загрузку.",
            "data_worker_failed",
          ),
        );
    });
  });
  return { fileName: name, tables };
}

