// The report-wave TRANSPORT tier: the adapter seam, the receipt primitives, and the script
// runner — everything that knows a wave is realized as one detached pi-subagents
// `workflowScript` run. The logical tier (`reportWave.ts`: assignments, normalization,
// completeness policy) sits strictly above this module; nothing here imports back into it, so
// the dependency is one-directional by construction (type-only edges count).
//
// `startWaveScript` performs the front half (abort pre-check → capability ping →
// subscribe-before-spawn → async spawn) and returns the run handle plus a NEVER-REJECTING
// `result` promise carrying the back half (completion wait under the module-owned timeout,
// best-effort stop on timeout/cancel, aggregate read, receipt assembly,
// unsubscribe-on-settle); `runWaveScript` is that start + await.
//
// The failure vocabulary here is the WAVE-LEVEL subset only (`WaveRunFailureReason`): the six
// reasons a script run itself can produce, always `key: null`. The logical tier widens it with
// the assignment-level reasons — `WaveRunFailure` is structurally assignable to the caller-facing
// `WaveFailure`, so script failures flow upward with zero runtime mapping, and an
// assignment-level reason on a script-run failure is unrepresentable.
//
// Failure posture: LOUD DEGRADE. Every operational arm normalizes into a typed failure — the
// runner never throws, and there is never a silent fallback to model-authored scripts.

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
 * One child's identity/artifact trail from the completion payload — OUTPUT-FREE by invariant:
 * reports, summaries, and structured output never enter a receipt (they stay in the durable
 * `status.json.workflow.value`, the sole report authority).
 */
export interface WaveChildReceipt {
  /** The Perk assignment key (mapped FROM the upstream row's overloaded `agent` field). */
  key: string;
  /** The child agent name, enriched from the Perk-owned assignment spec where known. */
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
 * each child's `agent` unset (enrichment happens against Perk-owned assignment specs).
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
 * and injects a fenced `acceptance-report` completion instruction into each child — a COMPETING
 * completion contract observed steering children into invalid `structured_output` attempts.
 * `{level: "none"}` is the sanctioned disable shape (pi-subagents `explicitAcceptanceCanDisable`);
 * `formatAcceptancePrompt` emits nothing at level none, so no contract block reaches a child.
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
   * delivers it onto every child, suppressing the auto-inferred acceptance contract. */
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

// -------------------------------------------------------------- the wave-level failure tier

/**
 * The wave-level failure vocabulary: exactly the six reasons the script runner can produce.
 * The logical tier's `WaveFailureReason` is the superset union over this plus the
 * assignment-level reasons — the reason literals are shared bytes.
 */
export type WaveRunFailureReason =
  | "unavailable" // ping failed / capabilities missing
  | "spawn-failed" // RPC spawn rejected or no run handle
  | "timeout" // module-owned timeout expired (best-effort stop issued)
  | "cancelled" // AbortSignal fired (best-effort stop issued)
  | "run-failed" // terminal status.json state ≠ "complete"
  | "aggregate-unreadable"; // status.json missing/corrupt/no workflow.value array

/**
 * A wave-level failure: always `key: null` (there is no assignment to blame — the whole run
 * failed). Structurally assignable to the logical tier's `WaveFailure`, so script failures are
 * absorbed upward with zero runtime mapping.
 */
export interface WaveRunFailure {
  key: null;
  reason: WaveRunFailureReason;
  /** Human-readable diagnosis (error strings routed here, never re-thrown). */
  detail: string;
}

// ------------------------------------------------------------------------- the script runner

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

/** The judgment-bearing pieces a script run needs (the assignment-free slice of `WaveSpec`). */
export interface WaveScriptSpec {
  /** Flow name for error detail/trace (e.g. "pr-review"). */
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
  | { ok: false; failure: WaveRunFailure; receipt: WaveScriptReceipt };

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
  | { ok: false; failure: WaveRunFailure; receipt: WaveScriptReceipt };

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
    reason: WaveRunFailureReason,
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
  //    supplies the judgment-bearing pieces (script, schema, model, policy).
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
    reason: WaveRunFailureReason,
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
      // per-child identity/artifact trail; an identity-only completion yields empty children).
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
