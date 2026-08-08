// The Perk-owned report-wave module: bounded sets of fresh-context, report-only children with
// typed outcomes under stable lane keys. Report waves were previously model-authored prompt
// mechanics (a script skeleton the parent model had to transcribe faithfully — the known
// prompt-drift risk); this module makes the mechanics CODE. It renders the complete, tested
// `workflowScript`, launches it through a `WaveAdapter` (async-only, `mission: false`), blocks on
// the run's async-complete event with a module-owned timeout, reads the durable `status.json`
// `workflow.value` aggregate, and normalizes `{complete, reports[], failures[]}` under a
// flow-specific completeness policy.
//
// The module is a DEEP seam with two adapters: `rpcAdapter.ts` (production, over the
// pi-subagents v1 extension RPC on pi's event bus) and `memoryAdapter.ts` (the first-class
// in-memory test double). It is deliberately dormant — no flow calls it and no model-facing tool
// exists — until the flow migrations wire their per-flow `WaveSpec`-building entrypoints over
// `runReportWave`.
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

/** An async-complete notification; at least one identifier is present on real payloads. */
export interface WaveCompletion {
  asyncId?: string;
  asyncDir?: string;
}

/** The full spawn params the runner fixes: async-only, ephemeral, fresh-context by definition. */
export interface WaveSpawnParams {
  workflowScript: string;
  async: true;
  /** Waves are ephemeral by explicit decision — never mission-attached. */
  mission: false;
  /** A report wave is by definition fresh-context. */
  context: "fresh";
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
 * Render the wave `workflowScript`: an explicit-return, all-settled `runs.all` over the lane
 * items, projected to the compact typed aggregate only (lane key, outcome, error, and the
 * schema-validated report — children's prose never enters the aggregate beyond `error`/`output`
 * on failure). Lane items are embedded via `JSON.stringify`, so hostile task text (quotes,
 * newlines, backticks, `${}`) cannot escape the array literal. Throws on programmer error:
 * empty lanes or duplicate lane keys.
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
    seen.add(lane.key);
  }
  const items = lanes.map((lane) => ({
    key: lane.key,
    agent: lane.agent,
    task: lane.task,
    label: lane.label ?? lane.key,
    ...(lane.phase !== undefined ? { phase: lane.phase } : {}),
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

function waveFailure(reason: WaveFailureReason, detail: string): WaveResult {
  return { complete: false, reports: [], failures: [{ key: null, reason, detail }] };
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
export type WaveScriptResult = { ok: true; value: unknown } | { ok: false; failure: WaveFailure };

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
 * Run one module-rendered workflowScript through the adapter: capability ping →
 * subscribe-before-spawn (the completion-before-reply buffer) → async spawn → block on the
 * async-complete event (module-owned timeout, abortable) → best-effort stop on timeout/cancel →
 * read the durable aggregate → the `state !== "complete"` / unreadable arms. Returns the raw
 * `workflow.value` on success — the shared operational core under `runReportWave` and the
 * dynamic-review sibling; per-flow value normalization stays with the caller.
 */
export async function runWaveScript(
  adapter: WaveAdapter,
  spec: WaveScriptSpec,
  signal?: AbortSignal,
): Promise<WaveScriptResult> {
  const scriptFailure = (reason: WaveFailureReason, detail: string): WaveScriptResult => ({
    ok: false,
    failure: { key: null, reason, detail },
  });

  if (signal?.aborted === true) {
    return scriptFailure("cancelled", `wave '${spec.flow}' was cancelled before launch`);
  }

  // 1. Capability check — the loud-degrade arm: the result explicitly names the wave
  //    unavailable; callers surface it, never silently fall back to model-authored scripts.
  let ping: WavePing | null;
  try {
    ping = await adapter.ping();
  } catch (error) {
    return scriptFailure("unavailable", `subagent RPC ping failed: ${errorDetail(error)}`);
  }
  if (ping === null) {
    return scriptFailure(
      "unavailable",
      "pi-subagents did not advertise the report-wave capabilities (ping failed or incomplete)",
    );
  }

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

  try {
    // 3. Spawn: async-only, ephemeral, fresh-context — the module fixes those; the flow's spec
    //    supplies the judgment-bearing pieces (lanes, schema, model, policy).
    const timeoutMs = spec.timeoutMs ?? waveTimeoutMs();
    try {
      handle = await adapter.spawn({
        workflowScript: spec.workflowScript,
        async: true,
        mission: false,
        context: "fresh",
        outputSchema: spec.outputSchema,
        ...(spec.model !== undefined ? { model: spec.model } : {}),
        timeoutMs,
      });
    } catch (error) {
      return scriptFailure("spawn-failed", `wave spawn failed: ${errorDetail(error)}`);
    }

    // 4. Block on completion with the module-owned timeout; honor the caller's AbortSignal.
    const outcome = await new Promise<"complete" | "timeout" | "cancelled">((resolve) => {
      if (buffered.some(matchesHandle)) {
        resolve("complete");
        return;
      }
      const settle = (value: "complete" | "timeout" | "cancelled"): void => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
        notifyMatch = null;
        resolve(value);
      };
      const timer = setTimeout(() => settle("timeout"), timeoutMs);
      const onAbort = (): void => settle("cancelled");
      notifyMatch = () => settle("complete");
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted === true) settle("cancelled");
    });
    if (outcome !== "complete") {
      // Best-effort stop — adapters never throw here by contract, but a broken adapter's error
      // is still swallowed into the detail rather than re-thrown.
      let stopNote = "";
      try {
        await adapter.stop(handle);
      } catch (error) {
        stopNote = ` (stop failed: ${errorDetail(error)})`;
      }
      return outcome === "timeout"
        ? scriptFailure("timeout", `wave '${spec.flow}' timed out after ${timeoutMs}ms${stopNote}`)
        : scriptFailure("cancelled", `wave '${spec.flow}' was cancelled${stopNote}`);
    }

    // 5. Read the durable aggregate; surface the terminal-state arms.
    let aggregate: { state: string; error?: string; value: unknown };
    try {
      aggregate = await adapter.readAggregate(handle);
    } catch (error) {
      return scriptFailure(
        "aggregate-unreadable",
        `wave aggregate unreadable: ${errorDetail(error)}`,
      );
    }
    if (aggregate.state !== "complete") {
      const detail = aggregate.error !== undefined ? `: ${aggregate.error}` : "";
      return scriptFailure("run-failed", `wave run ended '${aggregate.state}'${detail}`);
    }
    return { ok: true, value: aggregate.value };
  } finally {
    unsubscribe();
  }
}

/**
 * Run a report wave: render the all-settled lane script, run it through `runWaveScript`, then
 * normalize per lane key and apply the completeness policy. Every operational failure normalizes
 * into `WaveResult` — the only throws are programmer errors (empty lanes / duplicate keys, via
 * `renderWaveScript`).
 */
export async function runReportWave(
  adapter: WaveAdapter,
  spec: WaveSpec,
  signal?: AbortSignal,
): Promise<WaveResult> {
  // Programmer-error validation first (throws): the script render is spec-only.
  const workflowScript = renderWaveScript(spec.lanes);

  const run = await runWaveScript(
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
  if (!run.ok) {
    return { complete: false, reports: [], failures: [run.failure] };
  }
  if (!Array.isArray(run.value)) {
    return waveFailure(
      "aggregate-unreadable",
      "wave aggregate carries no workflow.value array (the script's explicit return is missing)",
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
  return { complete, reports, failures };
}
