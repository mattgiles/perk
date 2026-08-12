// The Perk-owned report-wave module: bounded sets of fresh-context, report-only children with
// typed outcomes under stable lane keys. Report waves were previously model-authored prompt
// mechanics (a script skeleton the parent model had to transcribe faithfully — the known
// prompt-drift risk); this module makes the mechanics CODE. It renders the complete, tested
// `workflowScript`, launches it through a `WaveAdapter` (async-only, `mission: false`), waits on
// the run's async-complete event with a module-owned timeout, reads the durable `status.json`
// `workflow.value` aggregate, and normalizes `{complete, reports[], failures[]}` under a
// flow-specific completeness policy. Each launch additionally records an OUTPUT-FREE
// `WaveScriptReceipt` (run handle + per-child identity/artifact trail from the completion
// payload) — write-only telemetry for correlation: `status.json.workflow.value` stays the sole
// source of reports, and receipt absence never changes a verdict, completeness, or retry
// selection (contracts.md §8.35).
//
// The module hosts BOTH the blocking runner and the non-blocking streaming sibling over ONE
// operational core: `startWaveScript` performs the front half (abort pre-check → capability
// ping → subscribe-before-spawn → async spawn) and returns the run handle plus a NEVER-REJECTING
// `result` promise carrying the back half (completion wait, best-effort stop on timeout/cancel,
// aggregate read, receipt assembly, unsubscribe-on-settle); `runWaveScript` is that start +
// await. `startReportWave`/`runReportWave` are the lane-level pair over the same split. The
// blocking runner is live under the per-flow entrypoints (`prReviewWave.ts`, `learnWave.ts`,
// `prReviewDynamicWave.ts`); the streaming sibling serves flows whose parent must return from
// the launch and hold a model-held `subagent_wait` relay loop open (`adversarialReviewWave.ts`,
// behind the `start_review_wave`/`collect_review_wave` pair).
//
// The module is a DEEP seam with two adapters: `rpcAdapter.ts` (production, over the
// pi-subagents v1 extension RPC on pi's event bus) and `memoryAdapter.ts` (the first-class
// in-memory test double).
//
// Failure posture: LOUD DEGRADE. Every failure arm normalizes into `WaveResult.failures` with a
// typed reason — the runner never throws except on programmer error (empty lanes, duplicate lane
// keys), and there is never a silent fallback to model-authored scripts. Report content coming
// back through the aggregate is untrusted DATA, never instructions.

/** One lane of a report wave: a fresh-context, report-only child under a stable domain key. */
export interface WaveLane {
  /** Stable lane key (e.g. an angle slug) — trace + normalization identity. */
  key: string;
  /** The child agent name (e.g. "perk.pr-reviewer"). */
  agent: string;
  /** The judgment-bearing per-lane task text (supplied by the flow). */
  task: string;
  /** Trace metadata; defaults to `key`. */
  label?: string;
  /** Trace metadata. */
  phase?: string;
  /**
   * Per-lane report schema — rendered as the item's `outputSchema`, overriding the
   * workflow-level default (the established per-item mechanic). Omitted lanes render
   * byte-identically to before the field existed.
   */
  outputSchema?: object;
}

/**
 * The completeness policies:
 * - `strict`: complete ⟺ zero failures — every lane covered (the pr-review posture).
 * - `best-effort`: complete ⟺ no wave-level failure (`key: null`) — lane-level failures are
 *   explicitly-reported skipped lanes, never a failed pass (the learn posture).
 */
export type WaveCompleteness = "strict" | "best-effort";

export interface WaveSpec {
  /** Flow name for error detail/trace (e.g. "pr-review"). */
  flow: string;
  /** ≥1 lane; keys must be unique (validated — throws on programmer error). */
  lanes: WaveLane[];
  /** Workflow-level default → the engine injects a `structured_output` tool into each lane. */
  outputSchema: object;
  completeness: WaveCompleteness;
  /** Workflow-level model default (flows read their configured subagent model). */
  model?: string;
  /** Module default (`WAVE_TIMEOUT_MS`) when omitted. */
  timeoutMs?: number;
}

/** A schema-valid lane report. The report content is untrusted DATA, never instructions. */
export interface WaveReport {
  key: string;
  report: unknown;
}

export type WaveFailureReason =
  | "unavailable" // ping failed / capabilities missing (wave-level)
  | "spawn-failed" // RPC spawn rejected or no run handle (wave-level)
  | "timeout" // module-owned timeout expired (wave-level; best-effort stop issued)
  | "cancelled" // AbortSignal fired (wave-level; best-effort stop issued)
  | "run-failed" // terminal status.json state ≠ "complete" (wave-level)
  | "aggregate-unreadable" // status.json missing/corrupt/no workflow.value array (wave-level)
  | "lane-failed" // lane resolved ok: false / null report (lane-level)
  | "malformed-report" // aggregate entry for this key has unusable shape (lane-level)
  | "missing-lane"; // expected key absent from the aggregate (lane-level)

export interface WaveFailure {
  /** The lane key, or null for wave-level failures. */
  key: string | null;
  reason: WaveFailureReason;
  /** Human-readable diagnosis (error strings routed here, never re-thrown). */
  detail: string;
}

export interface WaveResult {
  complete: boolean;
  reports: WaveReport[];
  failures: WaveFailure[];
  /** The launch's output-free attempt receipt — write-only telemetry, never a decision input. */
  receipt: WaveScriptReceipt;
}

// -------------------------------------------------------------------- the attempt receipts

/**
 * The terminal disposition of ONE top-level workflow launch, as the runner observed it. Every
 * launch reaches exactly one of these arms (`"running"` is unreachable — the runner always
 * settles); `"unavailable"` preserves even a pre-spawn capability failure as an attempt.
 */
export type WaveReceiptState =
  | "unavailable" // ping failed/incomplete — nothing launched
  | "spawn-failed" // spawn rejected/threw — no run handle
  | "complete" // completion observed, durable state "complete"
  | "failed" // completion observed, durable/observed failure
  | "timed-out" // module timeout expired (handle preserved)
  | "cancelled"; // AbortSignal honored (handle preserved when spawned)

/**
 * One child lane's identity/artifact trail from the completion payload — OUTPUT-FREE by
 * invariant: reports, summaries, and structured output never enter a receipt (they stay in the
 * durable `status.json.workflow.value`, the sole report authority).
 */
export interface WaveChildReceipt {
  /** The Perk lane key (mapped FROM the upstream row's overloaded `agent` field). */
  key: string;
  /** The child agent name, enriched from the Perk-owned lane spec where known. */
  agent?: string;
  /** The child's opaque run id — never parsed or synthesized from paths. */
  runId?: string;
  success?: boolean;
  outputState?: "present" | "absent" | "unknown";
  /** String path fields only; output-free. */
  artifactPaths?: Record<string, string>;
}

/** One script launch's receipt: the run handle (where known) + the observed children. */
export interface WaveScriptReceipt {
  /** The top-level async run id (the spawn handle's asyncId). */
  runId?: string;
  asyncDir?: string;
  state: WaveReceiptState;
  children: WaveChildReceipt[];
}

/**
 * A flow-attributed attempt: one receipt per top-level workflow launch, ordered by `attempt`
 * (one-based, assigned by the flow entrypoint that owns retry policy). `requestedKeys` is the
 * lane manifest BEFORE launch — never reconstructed from the observed children.
 */
export interface WaveAttemptReceipt extends WaveScriptReceipt {
  flow: string;
  attempt: number;
  requestedKeys: string[];
}

/** Assemble one flow attempt from a script receipt (the uniform builder the flows share). */
export function toAttemptReceipt(
  flow: string,
  attempt: number,
  requestedKeys: string[],
  receipt: WaveScriptReceipt,
): WaveAttemptReceipt {
  return { flow, attempt, requestedKeys: [...requestedKeys], ...receipt };
}

// ------------------------------------------------------------------------- the adapter seam

/** The minimal pi event-bus surface an adapter needs (mirrors pi's EventBus, whose `on` returns an unsubscribe function). */
export interface WaveBus {
  emit(channel: string, data: unknown): void;
  on(channel: string, handler: (data: unknown) => void): () => void;
}

/** A successful capability ping; `asyncCompleteEvent` is the ADVERTISED async-complete channel. */
export interface WavePing {
  asyncCompleteEvent: string;
}

/** The detached async run a spawn launched. */
export interface WaveRunHandle {
  asyncId: string;
  asyncDir: string;
}

/**
 * An async-complete notification; at least one identifier is present on real payloads. The
 * observability fields are optional — an identity-only completion stays valid (receipt absence
 * degrades correlation, never behavior). The adapter normalizes them output-free and leaves
 * each child's `agent` unset (enrichment happens against Perk-owned lane specs).
 */
export interface WaveCompletion {
  asyncId?: string;
  asyncDir?: string;
  /** The run's raw terminal state string, when the payload carries one. */
  state?: string;
  success?: boolean;
  children?: WaveChildReceipt[];
}

/**
 * The explicit acceptance-disable every wave spawn carries. Without it, pi-subagents
 * auto-infers a generic acceptance contract for reviewer/analyst-named or read-only children
 * and injects a fenced `acceptance-report` completion instruction into each lane — a COMPETING
 * completion contract observed steering children into invalid `structured_output` attempts.
 * `{level: "none"}` is the sanctioned disable shape (pi-subagents `explicitAcceptanceCanDisable`);
 * `formatAcceptancePrompt` emits nothing at level none, so no contract block reaches a lane.
 * Deliberately module-wide with no opt-out: every report-wave child's sole completion contract
 * is the engine-validated `structured_output` report.
 */
export const WAVE_ACCEPTANCE = {
  level: "none",
  reason: "perk report-wave lanes complete via the engine-validated structured_output report",
} as const;

/** The full spawn params the runner fixes: async-only, ephemeral, fresh-context by definition. */
export interface WaveSpawnParams {
  workflowScript: string;
  async: true;
  /** Waves are ephemeral by explicit decision — never mission-attached. */
  mission: false;
  /** A report wave is by definition fresh-context. */
  context: "fresh";
  /** The fixed acceptance disable (`WAVE_ACCEPTANCE`) — pi-subagents' workflow-defaults spread
   * delivers it onto every lane child, suppressing the auto-inferred acceptance contract. */
  acceptance: { level: "none"; reason: string };
  outputSchema: object;
  model?: string;
  /** Orphan insurance: the run enforces the same deadline even if the parent session dies. */
  timeoutMs: number;
}

export interface WaveAdapter {
  /** Capability-checked ping; null ⇒ unavailable (loud degrade upstream). Must be called first. */
  ping(): Promise<WavePing | null>;
  /** Launch the async workflowScript run; throws ⇒ spawn-failed. */
  spawn(params: WaveSpawnParams): Promise<WaveRunHandle>;
  /** Subscribe to run completions (any run — the runner matches the handle); returns unsubscribe. */
  onComplete(handler: (completion: WaveCompletion) => void): () => void;
  /** Best-effort stop of a live run (timeout/cancel path); never throws. */
  stop(handle: WaveRunHandle): Promise<void>;
  /** Read the run's durable aggregate; throws ⇒ aggregate-unreadable. */
  readAggregate(handle: WaveRunHandle): Promise<{ state: string; error?: string; value: unknown }>;
}

// ---------------------------------------------------------------------------- the renderer

/**
 * pi-subagents' scripted-workflow run-key contract for `runs.all` item keys: start
 * alphanumeric, then letters/digits/`.`/`_`/`-`, ≤128 chars total. Mirrored here because the
 * upstream pattern is enforced only inside the live workflow worker — an invalid key fails the
 * WHOLE wave at dispatch (`run-failed`), a path no offline adapter exercises — so the renderer
 * rejects it up front as a programmer error.
 */
export const RUN_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/**
 * Render the wave `workflowScript`: an explicit-return, all-settled `runs.all` over the lane
 * items, projected to the compact typed aggregate only (lane key, outcome, error, and the
 * schema-validated report — children's prose never enters the aggregate beyond `error`/`output`
 * on failure). Lane items are embedded via `JSON.stringify`, so hostile task text (quotes,
 * newlines, backticks, `${}`) cannot escape the array literal. Throws on programmer error:
 * empty lanes, duplicate lane keys, or a lane key outside the run-key contract.
 */
export function renderWaveScript(lanes: WaveLane[]): string {
  if (lanes.length === 0) {
    throw new Error("renderWaveScript: a report wave needs at least one lane");
  }
  const seen = new Set<string>();
  for (const lane of lanes) {
    if (seen.has(lane.key)) {
      throw new Error(`renderWaveScript: duplicate lane key '${lane.key}'`);
    }
    if (!RUN_KEY_PATTERN.test(lane.key)) {
      throw new Error(
        `renderWaveScript: lane key '${lane.key}' violates the pi-subagents run-key contract`,
      );
    }
    seen.add(lane.key);
  }
  const items = lanes.map((lane) => ({
    key: lane.key,
    agent: lane.agent,
    task: lane.task,
    label: lane.label ?? lane.key,
    ...(lane.phase !== undefined ? { phase: lane.phase } : {}),
    ...(lane.outputSchema !== undefined ? { outputSchema: lane.outputSchema } : {}),
  }));
  return (
    `const reports = await runs.all(${JSON.stringify(items, null, 2)});\n` +
    "return reports.map(({key, ok, error, structuredOutput}) => " +
    "({key, ok, error: error ?? null, report: structuredOutput ?? null}));"
  );
}

// ------------------------------------------------------------------------------- the runner

/**
 * The module-owned wave timeout default: a deliberate tightening vs the 30-minute foreground
 * default the prompt-mechanics wave rode. Per-flow `spec.timeoutMs` overrides; the default is
 * overridable for tests via PERK_WAVE_TIMEOUT_MS.
 */
export const WAVE_TIMEOUT_MS = 15 * 60_000;

function waveTimeoutMs(): number {
  const raw = Number(process.env.PERK_WAVE_TIMEOUT_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : WAVE_TIMEOUT_MS;
}

function waveFailure(
  reason: WaveFailureReason,
  detail: string,
  receipt: WaveScriptReceipt,
): WaveResult {
  return { complete: false, reports: [], failures: [{ key: null, reason, detail }], receipt };
}

/** The judgment-bearing pieces a script run needs (the lane-free slice of `WaveSpec`). */
export interface WaveScriptSpec {
  /** Flow name for error detail/trace (e.g. "pr-review-dynamic"). */
  flow: string;
  /** The complete, module-rendered workflowScript (never model-authored). */
  workflowScript: string;
  /** Workflow-level default → the engine injects a `structured_output` tool into each child. */
  outputSchema: object;
  /** Workflow-level model default (per-item `model` fields in the script override it). */
  model?: string;
  /** Module default (`WAVE_TIMEOUT_MS`) when omitted. */
  timeoutMs?: number;
}

/** A script run's outcome: the raw `workflow.value` on success, one wave-level failure otherwise. */
export type WaveScriptResult =
  | { ok: true; value: unknown; receipt: WaveScriptReceipt }
  | { ok: false; failure: WaveFailure; receipt: WaveScriptReceipt };

/**
 * A launched (or launch-refused) script run. On `ok: true` the run is LIVE: `handle` is the
 * detached async run, and `result` settles when the back half finishes (completion wait under
 * the module-owned timeout, AbortSignal honor, best-effort stop on timeout/cancel, the durable
 * aggregate read, receipt assembly, unsubscribe-on-settle). `result` NEVER rejects — every arm
 * normalizes into `WaveScriptResult`, so an uncollected wave can never become an unhandled
 * rejection. Pre-spawn failures (aborted-before-launch, ping fail/null, spawn throw) take the
 * `ok: false` arm with the same failure/receipt values the blocking runner reports, and the
 * completion subscription is released immediately.
 */
export type WaveScriptStart =
  | { ok: true; handle: WaveRunHandle; result: Promise<WaveScriptResult> }
  | { ok: false; failure: WaveFailure; receipt: WaveScriptReceipt };

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Normalize the aggregate's entries against the expected lane keys (defensive — the module
 * rendered the script, but the aggregate crossed a process boundary). Unknown extra keys are
 * ignored: the module owns the script, so extras cannot occur without upstream drift, and the
 * per-lane reasons below already make the wave incomplete under `strict`. Exported for the
 * per-flow entrypoints whose scripts produce the same compact lane projection (e.g. the
 * dynamic-review sibling normalizing against its runtime-selected keys).
 */
export function normalizeLanes(
  keys: string[],
  entries: unknown[],
): { reports: WaveReport[]; failures: WaveFailure[] } {
  const reports: WaveReport[] = [];
  const failures: WaveFailure[] = [];
  for (const key of keys) {
    const lane = { key };
    const entry = entries.find((e) => isRecord(e) && e.key === lane.key);
    if (!isRecord(entry)) {
      failures.push({
        key: lane.key,
        reason: "missing-lane",
        detail: `lane '${lane.key}' is absent from the wave aggregate`,
      });
      continue;
    }
    if (entry.ok === true) {
      const report = entry.report;
      if (isRecord(report)) {
        reports.push({ key: lane.key, report });
      } else if (report === null || report === undefined) {
        failures.push({
          key: lane.key,
          reason: "lane-failed",
          detail:
            typeof entry.error === "string" && entry.error !== ""
              ? entry.error
              : `lane '${lane.key}' resolved without a schema-valid report`,
        });
      } else {
        failures.push({
          key: lane.key,
          reason: "malformed-report",
          detail: `lane '${lane.key}' carries a non-object report (${Array.isArray(report) ? "array" : typeof report})`,
        });
      }
    } else if (entry.ok === false) {
      failures.push({
        key: lane.key,
        reason: "lane-failed",
        detail:
          typeof entry.error === "string" && entry.error !== ""
            ? entry.error
            : `lane '${lane.key}' failed without error detail`,
      });
    } else {
      failures.push({
        key: lane.key,
        reason: "malformed-report",
        detail: `lane '${lane.key}' aggregate entry has no boolean 'ok'`,
      });
    }
  }
  return { reports, failures };
}

/**
 * Start one module-rendered workflowScript through the adapter — the non-blocking front half:
 * capability ping → subscribe-before-spawn (the completion-before-reply buffer) → async spawn.
 * On success the back half (block on the async-complete event under the module-owned timeout,
 * abortable → best-effort stop on timeout/cancel → read the durable aggregate → the
 * `state !== "complete"` / unreadable arms) runs behind the returned `result` promise, which
 * never rejects. The shared operational core under every runner; per-flow value normalization
 * stays with the caller.
 */
export async function startWaveScript(
  adapter: WaveAdapter,
  spec: WaveScriptSpec,
  signal?: AbortSignal,
): Promise<WaveScriptStart> {
  // The receipt is assembled in EVERY terminal arm — write-only telemetry: nothing below reads
  // it back into the ok/failure decision.
  const receiptOf = (
    state: WaveReceiptState,
    spawned: WaveRunHandle | null,
    completion?: WaveCompletion,
  ): WaveScriptReceipt => ({
    ...(spawned !== null ? { runId: spawned.asyncId, asyncDir: spawned.asyncDir } : {}),
    state,
    children: completion?.children ?? [],
  });
  const startFailure = (
    reason: WaveFailureReason,
    detail: string,
    receipt: WaveScriptReceipt,
  ): WaveScriptStart => ({
    ok: false,
    failure: { key: null, reason, detail },
    receipt,
  });

  // Read through a closure so TS's readonly-property narrowing never staples the first
  // check's `false` onto the post-await re-check (the signal CAN flip during an await).
  const aborted = (): boolean => signal?.aborted === true;
  const cancelledBeforeLaunch = (): WaveScriptStart =>
    startFailure(
      "cancelled",
      `wave '${spec.flow}' was cancelled before launch`,
      receiptOf("cancelled", null),
    );

  if (aborted()) return cancelledBeforeLaunch();

  // 1. Capability check — the loud-degrade arm: the result explicitly names the wave
  //    unavailable; callers surface it, never silently fall back to model-authored scripts.
  let ping: WavePing | null;
  try {
    ping = await adapter.ping();
  } catch (error) {
    return startFailure(
      "unavailable",
      `subagent RPC ping failed: ${errorDetail(error)}`,
      receiptOf("unavailable", null),
    );
  }
  if (ping === null) {
    return startFailure(
      "unavailable",
      "pi-subagents did not advertise the report-wave capabilities (ping failed or incomplete)",
      receiptOf("unavailable", null),
    );
  }

  // An abort can arrive WHILE the ping await is pending — re-check before subscribe/spawn so a
  // cancelled wave never launches (the pre-launch check alone leaves this window open).
  if (aborted()) return cancelledBeforeLaunch();

  // 2. Subscribe BEFORE spawn: a completion can arrive before the spawn reply resolves (the
  //    completion-before-reply race) — every completion is buffered and re-checked once the
  //    handle is known.
  let handle: WaveRunHandle | null = null;
  let notifyMatch: (() => void) | null = null;
  const buffered: WaveCompletion[] = [];
  const matchesHandle = (completion: WaveCompletion): boolean =>
    handle !== null &&
    ((completion.asyncDir !== undefined && completion.asyncDir === handle.asyncDir) ||
      (completion.asyncId !== undefined && completion.asyncId === handle.asyncId));
  const unsubscribe = adapter.onComplete((completion) => {
    buffered.push(completion);
    if (matchesHandle(completion) && notifyMatch !== null) notifyMatch();
  });

  // 3. Spawn: async-only, ephemeral, fresh-context — the module fixes those; the flow's spec
  //    supplies the judgment-bearing pieces (lanes, schema, model, policy).
  const timeoutMs = spec.timeoutMs ?? waveTimeoutMs();
  try {
    handle = await adapter.spawn({
      workflowScript: spec.workflowScript,
      async: true,
      mission: false,
      context: "fresh",
      acceptance: WAVE_ACCEPTANCE,
      outputSchema: spec.outputSchema,
      ...(spec.model !== undefined ? { model: spec.model } : {}),
      timeoutMs,
    });
  } catch (error) {
    unsubscribe();
    return startFailure(
      "spawn-failed",
      `wave spawn failed: ${errorDetail(error)}`,
      receiptOf("spawn-failed", null),
    );
  }
  const spawned = handle;

  const scriptFailure = (
    reason: WaveFailureReason,
    detail: string,
    receipt: WaveScriptReceipt,
  ): WaveScriptResult => ({
    ok: false,
    failure: { key: null, reason, detail },
    receipt,
  });

  // The back half: every arm below RETURNS a normalized `WaveScriptResult` (never throws), so
  // `result` never rejects; the subscription is released exactly when it settles.
  const settle = async (): Promise<WaveScriptResult> => {
    try {
      // 4. Block on completion with the module-owned timeout; honor the caller's AbortSignal.
      const outcome = await new Promise<"complete" | "timeout" | "cancelled">((resolve) => {
        if (buffered.some(matchesHandle)) {
          resolve("complete");
          return;
        }
        const settleOutcome = (value: "complete" | "timeout" | "cancelled"): void => {
          clearTimeout(timer);
          signal?.removeEventListener("abort", onAbort);
          notifyMatch = null;
          resolve(value);
        };
        const timer = setTimeout(() => settleOutcome("timeout"), timeoutMs);
        const onAbort = (): void => settleOutcome("cancelled");
        notifyMatch = () => settleOutcome("complete");
        signal?.addEventListener("abort", onAbort, { once: true });
        if (signal?.aborted === true) settleOutcome("cancelled");
      });
      if (outcome !== "complete") {
        // Best-effort stop — adapters never throw here by contract, but a broken adapter's error
        // is still swallowed into the detail rather than re-thrown.
        let stopNote = "";
        try {
          await adapter.stop(spawned);
        } catch (error) {
          stopNote = ` (stop failed: ${errorDetail(error)})`;
        }
        return outcome === "timeout"
          ? scriptFailure(
              "timeout",
              `wave '${spec.flow}' timed out after ${timeoutMs}ms${stopNote}`,
              receiptOf("timed-out", spawned),
            )
          : scriptFailure(
              "cancelled",
              `wave '${spec.flow}' was cancelled${stopNote}`,
              receiptOf("cancelled", spawned),
            );
      }

      // The MATCHED completion (retained for the receipt — its normalized children are the
      // child-lane identity/artifact trail; an identity-only completion yields empty children).
      const matched = buffered.find(matchesHandle);

      // 5. Read the durable aggregate; surface the terminal-state arms.
      let aggregate: { state: string; error?: string; value: unknown };
      try {
        aggregate = await adapter.readAggregate(spawned);
      } catch (error) {
        // Aggregate-unreadable: the completion identity is retained — the receipt state derives
        // from the OBSERVED completion (a correlation label, not a verdict; the authoritative
        // failure reason stays in the wave failure).
        return scriptFailure(
          "aggregate-unreadable",
          `wave aggregate unreadable: ${errorDetail(error)}`,
          receiptOf(matched?.success === false ? "failed" : "complete", spawned, matched),
        );
      }
      if (aggregate.state !== "complete") {
        const detail = aggregate.error !== undefined ? `: ${aggregate.error}` : "";
        return scriptFailure(
          "run-failed",
          `wave run ended '${aggregate.state}'${detail}`,
          receiptOf("failed", spawned, matched),
        );
      }
      return { ok: true, value: aggregate.value, receipt: receiptOf("complete", spawned, matched) };
    } finally {
      unsubscribe();
    }
  };
  return { ok: true, handle: spawned, result: settle() };
}

/**
 * Run one module-rendered workflowScript to completion — the blocking form: `startWaveScript` +
 * await its `result` (one operational core, behavior identical to the historical blocking
 * runner).
 */
export async function runWaveScript(
  adapter: WaveAdapter,
  spec: WaveScriptSpec,
  signal?: AbortSignal,
): Promise<WaveScriptResult> {
  const start = await startWaveScript(adapter, spec, signal);
  if (!start.ok) return { ok: false, failure: start.failure, receipt: start.receipt };
  return await start.result;
}

/**
 * Enrich receipt children's `agent` from the Perk-owned lane specs by key. Children are never
 * synthesized from lanes — an identity-only completion keeps its empty children (receipt absence
 * degrades correlation, never behavior).
 */
function enrichReceipt(receipt: WaveScriptReceipt, lanes: WaveLane[]): WaveScriptReceipt {
  return {
    ...receipt,
    children: receipt.children.map((child) => {
      if (child.agent !== undefined) return child;
      const agent = lanes.find((lane) => lane.key === child.key)?.agent;
      return agent === undefined ? child : { ...child, agent };
    }),
  };
}

/**
 * A launched (or launch-failed) report wave — the lane-level sibling of `WaveScriptStart`. On
 * `ok: true` the wave is LIVE: `result` settles into the normalized `WaveResult` (lane
 * normalization + completeness policy + receipt enrichment) and never rejects. On `ok: false`
 * the launch failure is already normalized into a `WaveResult` (receipt included) — no promise
 * to await, nothing left running.
 */
export type ReportWaveStart =
  | { ok: true; handle: WaveRunHandle; result: Promise<WaveResult> }
  | { ok: false; result: WaveResult };

/**
 * Settle one script outcome into the lane-level `WaveResult`: receipt enrichment, the
 * workflow.value array check, per-lane-key normalization, and the completeness policy — the
 * single back half both the blocking runner and the streaming sibling apply.
 */
function settleReportWave(run: WaveScriptResult, spec: WaveSpec): WaveResult {
  const receipt = enrichReceipt(run.receipt, spec.lanes);
  if (!run.ok) {
    return { complete: false, reports: [], failures: [run.failure], receipt };
  }
  if (!Array.isArray(run.value)) {
    return waveFailure(
      "aggregate-unreadable",
      "wave aggregate carries no workflow.value array (the script's explicit return is missing)",
      receipt,
    );
  }

  const { reports, failures } = normalizeLanes(
    spec.lanes.map((lane) => lane.key),
    run.value,
  );
  const complete =
    spec.completeness === "strict"
      ? failures.length === 0
      : failures.every((failure) => failure.key !== null);
  return { complete, reports, failures, receipt };
}

/**
 * Start a report wave without blocking on completion: render the all-settled lane script (the
 * programmer-error throws — empty lanes / duplicate keys — are preserved), launch it via
 * `startWaveScript`, and on success return the run handle plus a `result` promise that applies
 * the shared settle (normalization + completeness + receipt enrichment) when the run finishes.
 * A launch failure comes back as an already-settled, normalized `WaveResult`.
 */
export async function startReportWave(
  adapter: WaveAdapter,
  spec: WaveSpec,
  signal?: AbortSignal,
): Promise<ReportWaveStart> {
  // Programmer-error validation first (throws): the script render is spec-only.
  const workflowScript = renderWaveScript(spec.lanes);

  const start = await startWaveScript(
    adapter,
    {
      flow: spec.flow,
      workflowScript,
      outputSchema: spec.outputSchema,
      ...(spec.model !== undefined ? { model: spec.model } : {}),
      ...(spec.timeoutMs !== undefined ? { timeoutMs: spec.timeoutMs } : {}),
    },
    signal,
  );
  if (!start.ok) {
    return {
      ok: false,
      result: settleReportWave({ ok: false, failure: start.failure, receipt: start.receipt }, spec),
    };
  }
  return {
    ok: true,
    handle: start.handle,
    result: start.result.then((run) => settleReportWave(run, spec)),
  };
}

/**
 * Run a report wave to completion — the blocking form: `startReportWave` + await its `result`
 * (one operational core). Every operational failure normalizes into `WaveResult` — the only
 * throws are programmer errors (empty lanes / duplicate keys, via `renderWaveScript`).
 */
export async function runReportWave(
  adapter: WaveAdapter,
  spec: WaveSpec,
  signal?: AbortSignal,
): Promise<WaveResult> {
  const start = await startReportWave(adapter, spec, signal);
  return start.ok ? await start.result : start.result;
}
