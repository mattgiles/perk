// The once-counted usage ledger — one SDK-free fold over Pi's usage records, shared by the
// headless worker's `RunOutcome` (`worker/stageExecution.ts`) and `/perk-selfcheck`'s census.
//
// Structural shapes only (no `@earendil-works/*` import): the worker's adapter stays its only
// SDK-bearing module, and selfcheck reads the same arithmetic over branch entries.
//
// The once-rule: every usage record is counted exactly once, at the boundary where Pi records it —
// an assistant message's `usage`, a tool result's `usage` (onto which Pi has already folded every
// nested call: a codemode script's `models.*` aggregate, a nested `ctx.executeTool` roll-up — so
// nested tool events are never summed), a `compaction` / `branch_summary` entry's `usage`, and a
// `usage` entry. That is the set Pi's own `getSessionStats()` sums; perk owns its fold because
// Pi's `usage-totals` helper is not a public export.
//
// Summed fields: `input`, `output`, `cacheRead`, `cacheWrite` and `cost.total`. `reasoning` and
// `cacheWrite1h` are NEVER added — pi-ai normalizes them as subsets of `output` / `cacheWrite`, so
// adding them would double-count. Cost is Pi's recorded `cost.total`: a model with no price table
// records 0, which is a recorded zero — never "unavailable". "Unavailable" means no record exists
// (`records === 0`), which callers render distinctly from a zero.
//
// Image and classifier calls have no counter here: Pi records them only as token-shaped `Usage`
// folded onto their tool result when the provider reports it; perk manufactures no non-token
// metric and no token equivalent.

/** The slice of a Pi `Usage` the ledger reads (every field optional — narrowed at runtime). */
export interface UsageRecord {
  input?: number;
  output?: number;
  cacheRead?: number;
  cacheWrite?: number;
  /** A subset of `output` — never summed. */
  reasoning?: number;
  /** A subset of `cacheWrite` — never summed. */
  cacheWrite1h?: number;
  cost?: { total?: number };
}

/** The ledger's running totals; `records` counts the usage records folded in. */
export interface UsageTotals {
  records: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  cost: number;
}

export function emptyUsageTotals(): UsageTotals {
  return { records: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A finite number clamped at 0; anything else is 0. */
function counted(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
}

/**
 * Fold one usage value into `totals`. A non-object (absent, `null`, a primitive, an array) is not
 * a record and changes nothing; an object counts ONE record, each summed field clamped at 0 (a
 * non-finite or non-numeric field reads 0).
 */
export function addUsageRecord(totals: UsageTotals, usage: unknown): void {
  if (!isObject(usage)) return;
  totals.records += 1;
  totals.input += counted(usage.input);
  totals.output += counted(usage.output);
  totals.cacheRead += counted(usage.cacheRead);
  totals.cacheWrite += counted(usage.cacheWrite);
  totals.cost += isObject(usage.cost) ? counted(usage.cost.total) : 0;
}

/** Fold already-counted totals into `target` (records included). */
export function mergeUsageTotals(target: UsageTotals, source: UsageTotals): void {
  target.records += source.records;
  target.input += source.input;
  target.output += source.output;
  target.cacheRead += source.cacheRead;
  target.cacheWrite += source.cacheWrite;
  target.cost += source.cost;
}

/** Fresh-work tokens: `input + output` — the sum the worker's budget counts. */
export function freshTokens(totals: UsageTotals): number {
  return totals.input + totals.output;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** An assistant message's requested physical identity, `provider/model`; `null` when absent. */
function requestedKey(message: unknown): string | null {
  if (!isObject(message)) return null;
  const { provider, model } = message;
  return nonEmptyString(provider) && nonEmptyString(model) ? `${provider}/${model}` : null;
}

/**
 * The ONE formatter for a dispatched identity: `provider/model` as recorded on an assistant
 * message, plus `→responseModel` only when the provider reported a different id. `null` when the
 * message names no provider or model.
 */
export function physicalKey(message: unknown): string | null {
  const requested = requestedKey(message);
  if (requested === null || !isObject(message)) return null;
  const { model, responseModel } = message;
  return nonEmptyString(responseModel) && responseModel !== model
    ? `${requested}→${responseModel}`
    : requested;
}

/**
 * Whether an assistant message is a successful response: its `stopReason` is neither `error` nor
 * `aborted` (Pi's own latest-response rule — a failed routing leaves the selected identity on its
 * error message, so an error never counts as dispatch).
 */
export function isSuccessfulResponse(message: unknown): boolean {
  if (!isObject(message)) return false;
  return message.stopReason !== "error" && message.stopReason !== "aborted";
}

/** A USD amount at four decimals: `$0.0123`. */
export function formatUsd(cost: number): string {
  return `$${cost.toFixed(4)}`;
}

/** Where a branch's usage records came from (each count is records, not entries). */
export interface UsageSources {
  assistant: number;
  toolResult: number;
  compaction: number;
  branchSummary: number;
  usageEntry: number;
}

/** Fold `usage` and credit `source` when it counted a record. */
function addFrom(
  totals: UsageTotals,
  sources: UsageSources,
  source: keyof UsageSources,
  usage: unknown,
): void {
  const before = totals.records;
  addUsageRecord(totals, usage);
  if (totals.records > before) sources[source] += 1;
}

/**
 * One pass over session entries, each owned record once: an assistant or tool-result message's
 * `usage`, a `compaction` / `branch_summary` entry's `usage`, a `usage` entry's `usage`. Nothing
 * else is read — never `custom` / `custom_message` data, never nested tool events.
 */
export function branchUsageCensus(entries: readonly unknown[]): {
  totals: UsageTotals;
  bySource: UsageSources;
} {
  const totals = emptyUsageTotals();
  const bySource: UsageSources = {
    assistant: 0,
    toolResult: 0,
    compaction: 0,
    branchSummary: 0,
    usageEntry: 0,
  };
  for (const entry of entries) {
    if (!isObject(entry)) continue;
    if (entry.type === "message") {
      const message = entry.message;
      if (!isObject(message)) continue;
      if (message.role === "assistant") addFrom(totals, bySource, "assistant", message.usage);
      else if (message.role === "toolResult") {
        addFrom(totals, bySource, "toolResult", message.usage);
      }
    } else if (entry.type === "compaction") {
      addFrom(totals, bySource, "compaction", entry.usage);
    } else if (entry.type === "branch_summary") {
      addFrom(totals, bySource, "branchSummary", entry.usage);
    } else if (entry.type === "usage") {
      addFrom(totals, bySource, "usageEntry", entry.usage);
    }
  }
  return { totals, bySource };
}

/** The dispatch census of a branch's assistant messages. */
export interface ModelCensus {
  /** `physicalKey` of the latest successful response; `null` when none is recorded. */
  dispatched: string | null;
  /**
   * The same response's requested physical identity (`provider/model`, no `→responseModel`
   * suffix) — what a selection compares against.
   */
  requested: string | null;
  /** Successful responses grouped by `physicalKey`, first-seen order. */
  responses: { model: string; count: number }[];
  /** Assistant messages that ended `error` / `aborted` (never in `responses`). */
  errors: number;
  aborted: number;
}

/**
 * Census the branch's assistant messages: successful responses by physical identity (a successful
 * message naming no provider/model is skipped), plus the error/aborted counts.
 */
export function branchModelCensus(entries: readonly unknown[]): ModelCensus {
  const counts = new Map<string, number>();
  let dispatched: string | null = null;
  let requested: string | null = null;
  let errors = 0;
  let aborted = 0;
  for (const entry of entries) {
    if (!isObject(entry) || entry.type !== "message") continue;
    const message = entry.message;
    if (!isObject(message) || message.role !== "assistant") continue;
    if (message.stopReason === "error") errors += 1;
    else if (message.stopReason === "aborted") aborted += 1;
    else {
      const key = physicalKey(message);
      if (key === null) continue;
      counts.set(key, (counts.get(key) ?? 0) + 1);
      dispatched = key;
      requested = requestedKey(message);
    }
  }
  return {
    dispatched,
    requested,
    responses: [...counts].map(([model, count]) => ({ model, count })),
    errors,
    aborted,
  };
}
