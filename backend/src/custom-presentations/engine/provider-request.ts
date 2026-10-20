import { setTimeout as delay } from "node:timers/promises";
import { HttpError } from "./errors.js";
import {engineContext} from './runtime-context.js';

export type TransportDiagnostic = {
  type?: string;
  code?: string;
  phase: "connect" | "response";
};
const transportCodes = new Set([
  "ECONNRESET", "ECONNREFUSED", "ECONNABORTED", "ETIMEDOUT", "EPIPE", "ENOTFOUND", "EAI_AGAIN",
  "UND_ERR_SOCKET", "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_HEADERS_TIMEOUT", "UND_ERR_BODY_TIMEOUT",
  "UND_ERR_REQ_CONTENT_LENGTH_MISMATCH", "UND_ERR_RES_CONTENT_LENGTH_MISMATCH", "UND_ERR_INVALID_ARG",
  "ERR_TLS_CERT_ALTNAME_INVALID", "CERT_HAS_EXPIRED", "UNABLE_TO_VERIFY_LEAF_SIGNATURE", "DEPTH_ZERO_SELF_SIGNED_CERT",
]);
const transportErrorTypes = new Set([
  "TypeError", "Error", "AggregateError", "TimeoutError", "AbortError", "SyntaxError",
]);
/** Never retain error messages: network errors can contain URLs and secrets. */
export function transportDiagnostic(error: unknown, phase: TransportDiagnostic["phase"]): TransportDiagnostic {
  const result: TransportDiagnostic = { phase };
  const pending: unknown[] = [error], seen = new Set<unknown>();
  while (pending.length && seen.size < 12) {
    const value = pending.shift() as { name?: unknown; code?: unknown; cause?: unknown; errors?: unknown[] } | undefined;
    if (!value || typeof value !== "object" || seen.has(value)) continue;
    seen.add(value);
    if (!result.type && typeof value.name === "string" && transportErrorTypes.has(value.name)) result.type = value.name;
    if (!result.code && typeof value.code === "string" && transportCodes.has(value.code)) result.code = value.code;
    if (value.cause) pending.push(value.cause);
    if (Array.isArray(value.errors)) pending.push(...value.errors.slice(0, 4));
  }
  return result;
}

/** Delivery recovery is separate from content correction. Never retry a bad
 * key, exhausted quota, refusal or user cancellation as a transient outage. */
export async function providerJson(input: {
  url: string;
  init: RequestInit;
  signal?: AbortSignal;
  timeoutMs: number;
  prefix: "llm" | "search";
  model: string;
  stage?: string;
  fetcher?: typeof fetch;
  decode?: (response: Response) => Promise<any>;
  delayMs?: number;
  maxAttempts?: number;
  onRetry?: (event: {
    attempt: number;
    code: string;
    status?: number;
    waitMs: number;
  }) => Promise<void>;
  onFailure?: (event: {
    attempt: number;
    code: string;
    status?: number;
    transport?: TransportDiagnostic;
    exhausted: boolean;
  }) => Promise<void>;
}): Promise<any> {
  const cancellation = engineContext()?.signal;
  if (cancellation) input = {...input, signal: AbortSignal.any([cancellation, ...(input.signal ? [input.signal] : [])])};
  for (let attempt = 0; ; attempt++) {
    input.signal?.throwIfAborted();
    let status: number | undefined,
      waitMs = (input.delayMs ?? 1000) * 2 ** attempt;
    let failure: HttpError;
    let phase: TransportDiagnostic["phase"] = "connect";
    try {
      const request = () => (input.fetcher || fetch)(input.url, {
        ...input.init,
        signal: AbortSignal.any([
          AbortSignal.timeout(input.timeoutMs),
          ...(input.signal ? [input.signal] : []),
        ]),
      });
      const response = engineContext()?.observeApi
        ? await engineContext()!.observeApi!(input.stage??input.prefix,attempt+1,request)
        : await request();
      status = response.status;
      phase = "response";
      if (!response.ok) {
        const body = (await response.json().catch(() => undefined)) as any;
        const symbolic=(value:unknown)=>typeof value==='string'&&/^[a-zA-Z0-9_.-]{1,96}$/.test(value)?value:undefined;
        const quota = [body?.error?.code, body?.error?.type].some((v) =>
          ["insufficient_quota", "billing_hard_limit_reached"].includes(v),
        );
        failure = new HttpError(
          502,
          `Провайдер вернул HTTP ${status}.`,
          quota ? `${input.prefix}_quota_exhausted` : `${input.prefix}_http`,
          { status, model: input.model,...(symbolic(body?.error?.code)?{providerCode:symbolic(body.error.code)}:{}),
            ...(symbolic(body?.error?.param)?{parameter:symbolic(body.error.param)}:{}) },
        );
        if (quota || ![408, 409, 429, 500, 502, 503, 504].includes(status)){
          await input.onFailure?.({attempt:attempt+1,code:failure.code,status,exhausted:true});
          throw failure;
        }
        const retryAfter = response.headers.get("retry-after");
        if (retryAfter) {
          const seconds = Number(retryAfter);
          const requested = Number.isFinite(seconds)
            ? seconds * 1000
            : Date.parse(retryAfter) - Date.now();
          if (Number.isFinite(requested))
            waitMs = Math.min(30000, Math.max(waitMs, requested));
        }
      } else {
        const result = await (input.decode ? input.decode(response) : response.json());
        input.signal?.throwIfAborted();
        return result;
      }
    } catch (error) {
      input.signal?.throwIfAborted();
      if (error instanceof HttpError) throw error;
      failure = new HttpError(
        503,
        "Провайдер не завершил передачу ответа после автоматических повторов.",
        `${input.prefix}_transport`,
        { model: input.model, transport: transportDiagnostic(error, phase) },
      );
    }
    const transport = (failure!.details as { transport?: TransportDiagnostic } | undefined)?.transport;
    await input.onFailure?.({
      attempt: attempt + 1,
      code: failure!.code,
      status,
      ...(transport ? { transport } : {}),
      exhausted: attempt >= (input.maxAttempts??3)-1,
    });
    if (attempt >= (input.maxAttempts??3)-1) throw failure!;
    await input.onRetry?.({
      attempt: attempt + 1,
      code: failure!.code,
      status,
      waitMs,
    });
    await delay(waitMs, undefined, { signal: input.signal });
  }
}
