// The ONE validator for pi-subagents' structured-delegation `providerDiagnostics` snapshot (the
// shape as read at 0.81.0, `src/api/delegation.d.ts::SubagentDelegationProviderDiagnostics`).
// These are display-only facts: never termination, lock or spend evidence. The supplier's
// `lastError.message` text is dropped structurally — the decoded snapshot is built field by field
// and has no slot for it. Pi-free and import-free so the Pi-free delivery interfaces can name the
// progress sink.

export const PROVIDER_ERROR_KINDS = ["rate_limited", "transient_other", "unknown"] as const;
export type ProviderErrorKind = (typeof PROVIDER_ERROR_KINDS)[number];

export const PROVIDER_RETRY_PHASES = ["backoff", "in_flight"] as const;
export type ProviderRetryPhase = (typeof PROVIDER_RETRY_PHASES)[number];

/** Pi's live retry state: `backoff` while waiting `delayMs`, `in_flight` once the retry runs. */
export interface ProviderRetry {
  phase: ProviderRetryPhase;
  attempt: number;
  maxAttempts: number;
  delayMs: number;
  scheduledAt: number;
}

/**
 * The validated snapshot. A snapshot replaces the prior one (never merged as a delta);
 * `errorCount`/`lastError` persist for the child's life while `retry` clears when the retry
 * sequence ends.
 */
export interface ProviderDiagnostics {
  errorCount: number;
  lastError?: { kind: ProviderErrorKind; at: number };
  retry?: ProviderRetry;
}

/** One correlated update's display facts; an absent `diagnostics` key means unavailable. */
export interface DelegationProgress {
  diagnostics?: ProviderDiagnostics;
}

/** A display stream fed by the foreground transport — never part of any dispatch result. */
export type DelegationProgressSink = (progress: DelegationProgress) => void;

function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function safeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function member<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

/**
 * Decode a native `providerDiagnostics` value. Absent, or malformed ANYWHERE in the snapshot,
 * decodes to `undefined` (unavailable) — never a partial salvage and never an error. Unknown extra
 * keys at any level are ignored (the supplier's snapshot is additive-stable). The result is a
 * freshly constructed object; the input is never spread, retained or mutated.
 */
export function decodeProviderDiagnostics(value: unknown): ProviderDiagnostics | undefined {
  const snapshot = object(value);
  if (snapshot === null) return undefined;
  const { errorCount } = snapshot;
  if (!safeInteger(errorCount) || errorCount < 0) return undefined;

  let lastError: ProviderDiagnostics["lastError"];
  if (snapshot.lastError !== undefined) {
    const raw = object(snapshot.lastError);
    if (raw === null || !member(PROVIDER_ERROR_KINDS, raw.kind) || !finite(raw.at))
      return undefined;
    lastError = { kind: raw.kind, at: raw.at };
  }

  let retry: ProviderRetry | undefined;
  if (snapshot.retry !== undefined) {
    const raw = object(snapshot.retry);
    if (
      raw === null ||
      !member(PROVIDER_RETRY_PHASES, raw.phase) ||
      !safeInteger(raw.attempt) ||
      raw.attempt < 1 ||
      !safeInteger(raw.maxAttempts) ||
      raw.maxAttempts < raw.attempt ||
      !finite(raw.delayMs) ||
      raw.delayMs < 0 ||
      !finite(raw.scheduledAt)
    )
      return undefined;
    retry = {
      phase: raw.phase,
      attempt: raw.attempt,
      maxAttempts: raw.maxAttempts,
      delayMs: raw.delayMs,
      scheduledAt: raw.scheduledAt,
    };
  }

  return {
    errorCount,
    ...(lastError ? { lastError } : {}),
    ...(retry ? { retry } : {}),
  };
}
