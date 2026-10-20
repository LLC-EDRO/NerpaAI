export type QualityWarning = { slide?: number; key?: string; reason: string; message: string };

export function uniqueWarnings(warnings: QualityWarning[]) {
  return [...new Map(warnings.map(w => [JSON.stringify([w.slide,w.key,w.reason,w.message]),w])).values()];
}
