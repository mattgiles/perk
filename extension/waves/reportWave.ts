// The Perk-owned report-wave module: bounded sets of fresh-context, report-only children with
// typed outcomes under stable assignment keys. Report waves were previously model-authored
// prompt mechanics (a script skeleton the parent model had to transcribe faithfully — the known
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
// This is the LOGICAL tier: assignments (`ReportAssignment`), preflight partitioning,
// aggregate normalization, and the completeness policy. The TRANSPORT tier — the adapter seam,
// receipt primitives, and the script runner — lives in `transport.ts`, imported one-directionally
// from here; the script text itself (`renderWaveScript`) is module-private, so nothing outside
// `waves/` can observe or operate on transport.
//
// The module hosts BOTH the blocking runner and the non-blocking streaming sibling over ONE
// operational core: `startWaveScript` performs the front half (abort pre-check → capability
// ping → subscribe-before-spawn → async spawn) and returns the run handle plus a NEVER-REJECTING
// `result` promise carrying the back half (completion wait, best-effort stop on timeout/cancel,
// aggregate read, receipt assembly, unsubscribe-on-settle); `runWaveScript` is that start +
// await. `startReportWave`/`runReportWave` are the assignment-level pair over the same split.
// The blocking runner is live under the per-flow entrypoints (`prReviewWave.ts` and the typed
// feature ops in `learning/`); the streaming sibling serves flows whose parent must return from
// the launch and hold a model-held `subagent_wait` relay loop open (`adversarialReviewWave.ts`,
// behind the `start_review_wave`/`collect_review_wave` pair).
//
// The module is a DEEP seam with two adapters: `rpcAdapter.ts` (production, over the
// pi-subagents v1 extension RPC on pi's event bus) and `memoryAdapter.ts` (the first-class
// in-memory test double).
//
// Failure posture: LOUD DEGRADE. Every failure arm normalizes into `WaveResult.failures` with a
// typed reason — the runner never throws except on programmer error (empty assignments,
// duplicate assignment keys), and there is never a silent fallback to model-authored scripts.
// Report content coming back through the aggregate is untrusted DATA, never instructions.

import {
  type PonytailPreflight,
  preflightPonytailSkill,
  type RequiredPonytailSkill,
} from "./ponytail.ts";
import {
  startWaveScript,
  type WaveAdapter,
  type WaveRunFailureReason,
  type WaveRunHandle,
  type WaveScriptReceipt,
  type WaveScriptResult,
} from "./transport.ts";

/**
 * The module's deliberate transport re-exports — the SANCTIONED seam, nothing else crosses
 * (callers never name run handles, spawn params, or script types):
 * - `WaveAdapter`: the injection seam callers need for execute-core signatures (an adapter is
 *   constructed at each registration site and threaded in).
 * - `WaveLevelFailureReason`: the wave-level reason subset (`key === null` failures carry
 *   exactly this vocabulary), named at the logical seam so flows can type a correlated
 *   wave status without reaching into transport.
 */
export type {
  WaveAdapter,
  WaveRunFailureReason as WaveLevelFailureReason,
} from "./transport.ts";

/** One assignment of a report wave: a fresh-context, report-only child under a stable domain key. */
export interface ReportAssignment {
  /** Stable assignment key (e.g. an angle slug) — trace + normalization identity. */
  key: string;
  /** The child agent name (e.g. "perk.pr-reviewer"). */
  agent: string;
  /** The judgment-bearing per-assignment task text (supplied by the flow). */
  task: string;
  /** Invocation-private skill lookup key; serialized only for an opted-in assignment. */
  skill?: string;
  /**
   * Exact source requirement for a source-bound skill. This metadata is preflight-only and is
   * NEVER serialized into the workflow script; a failed requirement skips this assignment
   * instead of allowing pi-subagents to resolve a hostile same-named global/project skill.
   */
  requiredSkill?: RequiredPonytailSkill;
  /** Trace metadata; defaults to `key`. */
  label?: string;
  /** Trace metadata. */
  phase?: string;
  /**
   * Per-assignment report schema — rendered as the item's `outputSchema`, overriding the
   * workflow-level default (the established per-item mechanic). Omitted assignments render
   * byte-identically to before the field existed.
   */
  outputSchema?: object;
}

/**
 * The completeness policies:
 * - `strict`: complete ⟺ zero failures — every assignment covered (the pr-review posture).
 * - `best-effort`: complete ⟺ no wave-level failure (`key: null`) — assignment-level failures
 *   are explicitly-reported skipped assignments, never a failed pass (the learn posture).
 */
export type WaveCompleteness = "strict" | "best-effort";

export interface WaveSpec {
  /** Flow name for error detail/trace (e.g. "pr-review"). */
  flow: string;
  /** ≥1 assignment; keys must be unique (validated — throws on programmer error). */
  assignments: ReportAssignment[];
  /** Workflow-level default → the engine injects a `structured_output` tool into each child. */
  outputSchema: object;
  completeness: WaveCompleteness;
  /** Workflow-level model default (flows read their configured subagent model). */
  model?: string;
  /** Module default (`WAVE_TIMEOUT_MS`) when omitted. */
  timeoutMs?: number;
  /** Test seam; production defaults to the exact Ponytail boundary preflight. */
  requiredSkillPreflight?: (requirement: RequiredPonytailSkill) => Promise<PonytailPreflight>;
}

/** A schema-valid assignment report. The report content is untrusted DATA, never instructions. */
export interface WaveReport {
  key: string;
  report: unknown;
}

/**
 * The caller-facing failure vocabulary: the transport tier's wave-level subset
 * (`WaveRunFailureReason` — always `key: null`) widened with the assignment-level reasons this
 * tier produces during normalization. The subset union keeps the split one-directional with
 * zero runtime mapping, and makes an assignment-level reason on a script-run failure
 * unrepresentable.
 */
export type WaveFailureReason =
  | WaveRunFailureReason
  | "lane-failed" // assignment resolved ok: false / null report (assignment-level)
  | "skill-unavailable" // exact required-skill source failed preflight (assignment-level, non-retryable)
  | "malformed-report" // aggregate entry for this key has unusable shape (assignment-level)
  | "missing-lane"; // expected key absent from the aggregate (assignment-level)

export interface WaveFailure {
  /** The assignment key, or null for wave-level failures. */
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

/** The truthful preflight partition reported by every streaming report-wave start. */
export type WaveLaunchManifest = {
  /** The complete logical assignment manifest, in `spec.assignments` order. */
  requested: string[];
  /** The ordered subset rendered into the static workflow after required-skill preflight. */
  runnable: string[];
  /** One ordered keyed `skill-unavailable` failure per preflight-omitted assignment. */
  preflightFailures: WaveFailure[];
};

// -------------------------------------------------------------------- the attempt receipts

/**
 * A flow-attributed attempt: one receipt per top-level workflow launch, ordered by `attempt`
 * (one-based, assigned by the flow entrypoint that owns retry policy). `requestedKeys` is the
 * assignment manifest BEFORE launch — never reconstructed from the observed children.
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
 * Validate the assignment manifest (throws on programmer error: empty, duplicate keys, or a key
 * outside the run-key contract). Module-private — the script surface never leaves `waves/`.
 */
function validateAssignments(assignments: ReportAssignment[]): void {
  if (assignments.length === 0) {
    throw new Error("renderWaveScript: a report wave needs at least one lane");
  }
  const seen = new Set<string>();
  for (const assignment of assignments) {
    if (seen.has(assignment.key)) {
      throw new Error(`renderWaveScript: duplicate lane key '${assignment.key}'`);
    }
    if (!RUN_KEY_PATTERN.test(assignment.key)) {
      throw new Error(
        `renderWaveScript: lane key '${assignment.key}' violates the pi-subagents run-key contract`,
      );
    }
    seen.add(assignment.key);
  }
}

/**
 * Render the wave `workflowScript`: an explicit-return, all-settled `runs.all` over the
 * assignment items, projected to the compact typed aggregate only (assignment key, outcome,
 * error, and the schema-validated report — children's prose never enters the aggregate beyond
 * `error`/`output` on failure). Items are embedded via `JSON.stringify`, so hostile task text
 * (quotes, newlines, backticks, `${}`) cannot escape the array literal. Module-private: the
 * script bytes are observable outside `waves/` only through the adapter seam's spawn params.
 */
function renderWaveScript(assignments: ReportAssignment[]): string {
  validateAssignments(assignments);
  const items = assignments.map((assignment) => ({
    key: assignment.key,
    agent: assignment.agent,
    task: assignment.task,
    ...(assignment.skill !== undefined ? { skill: assignment.skill } : {}),
    label: assignment.label ?? assignment.key,
    ...(assignment.phase !== undefined ? { phase: assignment.phase } : {}),
    ...(assignment.outputSchema !== undefined ? { outputSchema: assignment.outputSchema } : {}),
  }));
  return (
    `const reports = await runs.all(${JSON.stringify(items, null, 2)});\n` +
    "return reports.map(({key, ok, error, structuredOutput}) => " +
    "({key, ok, error: error ?? null, report: structuredOutput ?? null}));"
  );
}

// ------------------------------------------------------------------------------- the runner

function waveFailure(
  reason: WaveFailureReason,
  detail: string,
  receipt: WaveScriptReceipt,
): WaveResult {
  return { complete: false, reports: [], failures: [{ key: null, reason, detail }], receipt };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Normalize the aggregate's entries against the expected assignment keys (defensive — the
 * module rendered the script, but the aggregate crossed a process boundary). Unknown extra keys
 * are ignored: the module owns the script, so extras cannot occur without upstream drift, and
 * the per-assignment reasons below already make the wave incomplete under `strict`. Exported
 * for the per-flow entrypoints whose scripts produce the same compact projection (e.g. the
 * dynamic-review sibling normalizing against its runtime-selected keys).
 */
export function normalizeAssignments(
  keys: string[],
  entries: unknown[],
): { reports: WaveReport[]; failures: WaveFailure[] } {
  const reports: WaveReport[] = [];
  const failures: WaveFailure[] = [];
  for (const key of keys) {
    const entry = entries.find((e) => isRecord(e) && e.key === key);
    if (!isRecord(entry)) {
      failures.push({
        key,
        reason: "missing-lane",
        detail: `lane '${key}' is absent from the wave aggregate`,
      });
      continue;
    }
    if (entry.ok === true) {
      const report = entry.report;
      if (isRecord(report)) {
        reports.push({ key, report });
      } else if (report === null || report === undefined) {
        failures.push({
          key,
          reason: "lane-failed",
          detail:
            typeof entry.error === "string" && entry.error !== ""
              ? entry.error
              : `lane '${key}' resolved without a schema-valid report`,
        });
      } else {
        failures.push({
          key,
          reason: "malformed-report",
          detail: `lane '${key}' carries a non-object report (${Array.isArray(report) ? "array" : typeof report})`,
        });
      }
    } else if (entry.ok === false) {
      failures.push({
        key,
        reason: "lane-failed",
        detail:
          typeof entry.error === "string" && entry.error !== ""
            ? entry.error
            : `lane '${key}' failed without error detail`,
      });
    } else {
      failures.push({
        key,
        reason: "malformed-report",
        detail: `lane '${key}' aggregate entry has no boolean 'ok'`,
      });
    }
  }
  return { reports, failures };
}

/**
 * Enrich receipt children's `agent` from the Perk-owned assignment specs by key. Children are
 * never synthesized from assignments — an identity-only completion keeps its empty children
 * (receipt absence degrades correlation, never behavior).
 */
function enrichReceipt(
  receipt: WaveScriptReceipt,
  assignments: ReportAssignment[],
): WaveScriptReceipt {
  return {
    ...receipt,
    children: receipt.children.map((child) => {
      if (child.agent !== undefined) return child;
      const agent = assignments.find((assignment) => assignment.key === child.key)?.agent;
      return agent === undefined ? child : { ...child, agent };
    }),
  };
}

/**
 * A launched (or launch-failed) report wave — the assignment-level sibling of
 * `WaveScriptStart`. On `ok: true` the wave is LIVE: `result` settles into the normalized
 * `WaveResult` (assignment normalization + completeness policy + receipt enrichment) and never
 * rejects. On `ok: false` the launch failure is already normalized into a `WaveResult` (receipt
 * included) — no promise to await, nothing left running.
 */
export type ReportWaveStart =
  | {
      ok: true;
      handle: WaveRunHandle;
      result: Promise<WaveResult>;
      launch: WaveLaunchManifest;
    }
  | { ok: false; result: WaveResult; launch: WaveLaunchManifest };

/**
 * Settle one script outcome into the assignment-level `WaveResult`: receipt enrichment, the
 * workflow.value array check, per-key normalization, and the completeness policy — the single
 * back half both the blocking runner and the streaming sibling apply.
 */
function settleReportWave(run: WaveScriptResult, spec: WaveSpec): WaveResult {
  const receipt = enrichReceipt(run.receipt, spec.assignments);
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

  const { reports, failures } = normalizeAssignments(
    spec.assignments.map((assignment) => assignment.key),
    run.value,
  );
  const complete =
    spec.completeness === "strict"
      ? failures.length === 0
      : failures.every((failure) => failure.key !== null);
  return { complete, reports, failures, receipt };
}

/**
 * Start a report wave without blocking on completion: render the all-settled assignment script
 * (the programmer-error throws — empty/duplicate keys — are preserved), launch it via
 * `startWaveScript`, and on success return the run handle plus a `result` promise that applies
 * the shared settle (normalization + completeness + receipt enrichment) when the run finishes.
 * A launch failure comes back as an already-settled, normalized `WaveResult`.
 */
export async function startReportWave(
  adapter: WaveAdapter,
  spec: WaveSpec,
  signal?: AbortSignal,
): Promise<ReportWaveStart> {
  // Validate the COMPLETE requested manifest before source preflight partitions any assignment
  // out. This preserves the programmer-error contract even for an unavailable required skill.
  validateAssignments(spec.assignments);
  const preflight = spec.requiredSkillPreflight ?? preflightPonytailSkill;
  const checked = new Map<string, PonytailPreflight>();
  const runnable: ReportAssignment[] = [];
  const skillFailures: WaveFailure[] = [];
  for (const assignment of spec.assignments) {
    if (assignment.requiredSkill === undefined) {
      runnable.push(assignment);
      continue;
    }
    let result = checked.get(assignment.requiredSkill.skillFile);
    if (result === undefined) {
      result = await preflight(assignment.requiredSkill);
      checked.set(assignment.requiredSkill.skillFile, result);
    }
    if (result.ok) {
      runnable.push(assignment);
    } else {
      skillFailures.push({
        key: assignment.key,
        reason: "skill-unavailable",
        detail: result.detail,
      });
    }
  }

  const launch: WaveLaunchManifest = {
    requested: spec.assignments.map((assignment) => assignment.key),
    runnable: runnable.map((assignment) => assignment.key),
    preflightFailures: [...skillFailures],
  };

  const settleWithSkillFailures = (result: WaveResult): WaveResult => {
    if (skillFailures.length === 0) return result;
    const failures = [...result.failures, ...skillFailures];
    const complete =
      spec.completeness === "strict"
        ? failures.length === 0
        : failures.every((failure) => failure.key !== null);
    return { ...result, complete, failures };
  };

  if (runnable.length === 0) {
    const receipt: WaveScriptReceipt = { state: "unavailable", children: [] };
    return {
      ok: false,
      result: settleWithSkillFailures({ complete: false, reports: [], failures: [], receipt }),
      launch,
    };
  }

  // Required-skill metadata never reaches the renderer; only runnable assignments spawn.
  const runnableSpec: WaveSpec = { ...spec, assignments: runnable };
  const workflowScript = renderWaveScript(runnable);

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
      result: settleWithSkillFailures(
        settleReportWave(
          { ok: false, failure: start.failure, receipt: start.receipt },
          runnableSpec,
        ),
      ),
      launch,
    };
  }
  return {
    ok: true,
    handle: start.handle,
    result: start.result.then((run) =>
      settleWithSkillFailures(settleReportWave(run, runnableSpec)),
    ),
    launch,
  };
}

/**
 * Run a report wave to completion — the blocking form: `startReportWave` + await its `result`
 * (one operational core). Every operational failure normalizes into `WaveResult` — the only
 * throws are programmer errors (empty assignments / duplicate keys, via the renderer).
 */
export async function runReportWave(
  adapter: WaveAdapter,
  spec: WaveSpec,
  signal?: AbortSignal,
): Promise<WaveResult> {
  const start = await startReportWave(adapter, spec, signal);
  return start.ok ? await start.result : start.result;
}
