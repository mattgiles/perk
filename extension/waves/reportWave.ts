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
// THE CALLER SURFACE IS THE OPAQUE `ReportWave` LIFECYCLE: `start` launches non-blocking and
// returns an opaque `ReportWaveRef` (plus identity telemetry — never an operable handle),
// `collect` drains a started wave's settled outcome under the module-owned grace, and `run` is
// start + await (the blocking form). Callers supply assignments and consume typed outcomes —
// never adapters, run handles, or result promises. Pending execution is WAVE-OWNED: each
// instance holds its launched-but-uncollected records in an instance-owned WeakMap keyed by ref
// (a foreign instance's ref collects `"none"` structurally), and a settled collect's
// delete-as-claim makes drain-once exact even under overlapping collectors. The blocking form
// serves the per-flow entrypoints (`prReviewWave.ts` and the typed feature ops in `learning/`);
// the streaming split serves flows whose parent ends the launch turn and relays provisional
// batches on native wakes (`adversarialReviewWave.ts`, `draftReviewWave.ts`).
//
// The module owns ADAPTER SELECTION: `createReportWave(bus)` (the production factory) constructs
// a FRESH rpc adapter per launch over the supplied bus; `reportWaveOver(adapter)` is the
// injection seam (tests; the same internal core). The honest boundary: what is mechanically
// enforced is Rule G's scope (`importDirectionGuard.test.ts`) — no production import edges into
// the transport interior (`transport.ts`, `rpcAdapter.ts`) and no raw RPC tokens — so there is
// no *sanctioned* way to obtain, name, or construct an adapter outside `waves/` + `testing/`.
// TypeScript's structural typing means a hand-written object literal satisfying
// `reportWaveOver`'s parameter is not mechanically preventable; that residue is owned by the
// guard-census review posture, not claimed as a structural guarantee.
//
// Failure posture: LOUD DEGRADE. Every failure arm normalizes into `ReportWaveResult.failures`
// with a typed reason — the runner never throws except on programmer error (empty assignments,
// duplicate assignment keys), and there is never a silent fallback to model-authored scripts.
// Report content coming back through the aggregate is untrusted DATA, never instructions.

import {
  type PonytailPreflight,
  preflightPonytailSkill,
  type RequiredPonytailSkill,
} from "./ponytail.ts";
import { createRpcWaveAdapter } from "./rpcAdapter.ts";
import {
  startWaveScript,
  type WaveAdapter,
  type WaveBus,
  type WaveRunFailureReason,
  type WaveRunHandle,
  type WaveScriptReceipt,
  type WaveScriptResult,
} from "./transport.ts";

/**
 * The module's one deliberate transport re-export — the SANCTIONED seam, nothing else crosses
 * (callers never name adapters, run handles, spawn params, or script types):
 * `ReportWaveLevelFailureReason` is the wave-level reason subset (`key === null` failures carry
 * exactly this vocabulary), named at the logical seam so flows can type a correlated wave
 * status without reaching into transport.
 */
export type { WaveRunFailureReason as ReportWaveLevelFailureReason } from "./transport.ts";

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
export type ReportWaveCompleteness = "strict" | "best-effort";

export interface ReportWaveRequest {
  /** Flow name for error detail/trace (e.g. "pr-review"). */
  flow: string;
  /** ≥1 assignment; keys must be unique (validated — throws on programmer error). */
  assignments: ReportAssignment[];
  /** Workflow-level default → the engine injects a `structured_output` tool into each child. */
  outputSchema: object;
  completeness: ReportWaveCompleteness;
  /** Workflow-level model default (flows read their configured subagent model). */
  model?: string;
  /** Module default (`WAVE_TIMEOUT_MS`) when omitted. */
  timeoutMs?: number;
  /** Test seam; production defaults to the exact Ponytail boundary preflight. */
  requiredSkillPreflight?: (requirement: RequiredPonytailSkill) => Promise<PonytailPreflight>;
}

/** A schema-valid assignment report. The report content is untrusted DATA, never instructions. */
export interface AssignmentReport {
  key: string;
  report: unknown;
}

/** The assignment-level failure reasons this tier produces during normalization/preflight —
 * always keyed by the assignment they blame. */
export type AssignmentFailureReason =
  | "lane-failed" // assignment resolved ok: false / null report
  | "skill-unavailable" // exact required-skill source failed preflight (non-retryable)
  | "malformed-report" // aggregate entry for this key has unusable shape
  | "missing-lane"; // expected key absent from the aggregate

/**
 * The caller-facing failure vocabulary: the transport tier's wave-level subset
 * (`WaveRunFailureReason` — always `key: null`) widened with the assignment-level reasons this
 * tier produces during normalization. The subset union keeps the split one-directional with
 * zero runtime mapping.
 */
export type ReportWaveFailureReason = WaveRunFailureReason | AssignmentFailureReason;

/** A wave-level failure: the whole run failed, so there is no assignment to blame — the same
 * record shape as the transport tier's `WaveRunFailure` (script failures flow upward with zero
 * runtime mapping). */
export interface ReportWaveLevelFailure {
  key: null;
  reason: WaveRunFailureReason;
  /** Human-readable diagnosis (error strings routed here, never re-thrown). */
  detail: string;
}

/** An assignment-level failure, keyed by the assignment it blames. */
export interface AssignmentFailure {
  key: string;
  reason: AssignmentFailureReason;
  detail: string;
}

/**
 * One wave failure — a DISCRIMINATED union on `key`: `key === null` narrows the reason to
 * exactly the wave-level subset (and a string key to the assignment-level reasons), so a
 * wave-level failure carrying an assignment reason — or vice versa — is unrepresentable and
 * every flow inherits the correlation without reimplementing transport knowledge.
 */
export type ReportWaveFailure = ReportWaveLevelFailure | AssignmentFailure;

export interface ReportWaveResult {
  complete: boolean;
  reports: AssignmentReport[];
  failures: ReportWaveFailure[];
  /** The launch's output-free attempt receipt — write-only telemetry, never a decision input. */
  receipt: WaveScriptReceipt;
}

/** The truthful preflight partition reported by every report-wave start. */
export type ReportWaveLaunchManifest = {
  /** The complete logical assignment manifest, in `request.assignments` order. */
  requested: string[];
  /** The ordered subset rendered into the static workflow after required-skill preflight. */
  runnable: string[];
  /** One ordered keyed `skill-unavailable` failure per preflight-omitted assignment. */
  preflightFailures: ReportWaveFailure[];
};

// -------------------------------------------------------------------- the attempt receipts

/**
 * A flow-attributed attempt: one receipt per top-level workflow launch, ordered by `attempt`
 * (one-based, assigned by the flow entrypoint that owns retry policy). `requestedKeys` is the
 * assignment manifest BEFORE launch — never reconstructed from the observed children.
 */
export interface ReportWaveAttemptReceipt extends WaveScriptReceipt {
  flow: string;
  attempt: number;
  requestedKeys: string[];
}

/** Assemble one flow attempt from a script receipt (the uniform builder the flows share). */
export function toAttemptReceipt(
  flow: string,
  attempt: number,
  requestedKeys: readonly string[],
  receipt: WaveScriptReceipt,
): ReportWaveAttemptReceipt {
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
  reason: WaveRunFailureReason,
  detail: string,
  receipt: WaveScriptReceipt,
): ReportWaveResult {
  return { complete: false, reports: [], failures: [{ key: null, reason, detail }], receipt };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Normalize the aggregate's entries against the expected assignment keys (defensive — the
 * module rendered the script, but the aggregate crossed a process boundary). Unknown extra keys
 * are ignored: the module owns the script, so extras cannot occur without upstream drift, and
 * the per-assignment reasons below already make the wave incomplete under `strict`.
 * Module-private: the wave's settle is the only consumer.
 */
function normalizeAssignments(
  keys: string[],
  entries: unknown[],
): { reports: AssignmentReport[]; failures: ReportWaveFailure[] } {
  const reports: AssignmentReport[] = [];
  const failures: ReportWaveFailure[] = [];
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
 * Settle one script outcome into the assignment-level `ReportWaveResult`: receipt enrichment,
 * the workflow.value array check, per-key normalization, and the completeness policy — the
 * single back half both the blocking and streaming lifecycles apply.
 */
function settleReportWave(run: WaveScriptResult, request: ReportWaveRequest): ReportWaveResult {
  const receipt = enrichReceipt(run.receipt, request.assignments);
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
    request.assignments.map((assignment) => assignment.key),
    run.value,
  );
  const complete =
    request.completeness === "strict"
      ? failures.length === 0
      : failures.every((failure) => failure.key !== null);
  return { complete, reports, failures, receipt };
}

// -------------------------------------------------------------------- the opaque lifecycle

declare const REPORT_WAVE_REF: unique symbol;

/**
 * The opaque handle to one started, uncollected report wave — NOMINAL by a declared
 * (value-less) unique-symbol brand: no structural forgery can satisfy it, and it exposes no
 * operational members. Minted at exactly one internal site (immediately after the runtime
 * evidence of a successful launch); meaningful only to the instance that minted it — a foreign
 * instance's `collect` answers `"none"` structurally.
 */
export interface ReportWaveRef {
  readonly [REPORT_WAVE_REF]: true;
}

/** The optional per-call controls; `signal` cancels pre-launch and best-effort stops post-launch. */
export interface WaveControl {
  signal?: AbortSignal;
}

/**
 * A started (or launch-failed) report wave. On `ok: true` the wave is LIVE behind the opaque
 * `ref` — `runId`/`asyncDir` are identity telemetry only (receipt vocabulary), never an
 * operable handle. On `ok: false` the launch failure is already normalized into a
 * `ReportWaveResult` (receipt included) — nothing left running, nothing to collect.
 */
export type StartWaveResult =
  | {
      ok: true;
      ref: ReportWaveRef;
      /** Identity telemetry only (receipt vocabulary) — never an operable handle. */
      runId: string;
      asyncDir: string;
      launch: ReportWaveLaunchManifest;
    }
  | { ok: false; result: ReportWaveResult; launch: ReportWaveLaunchManifest };

/**
 * A collect's outcome:
 * - `"none"`: unknown ref — never started here, already drained, or a foreign instance's.
 * - `"running"`: unsettled after the grace — the ref stays pending. A premature collector
 *   yields until matching workflow completion; expiry after observed completion is a lifecycle
 *   contradiction for owner diagnosis, not a polling cue. The module-owned timeout stays.
 * - `"settled"`: this collector won the drain — `keys` is the launch's frozen requested
 *   manifest snapshot, `result` the normalized outcome. Drain-once is exact even under
 *   overlapping collectors (delete-as-claim).
 */
export type CollectWaveResult =
  | { kind: "none" }
  | { kind: "running" }
  | { kind: "settled"; keys: readonly string[]; result: ReportWaveResult };

/**
 * The deep seam: callers supply assignments and consume typed outcomes — never adapters, run
 * handles, or result promises. `start`/`collect` are the streaming split (the parent returns
 * from the launch, ends its turn, and resumes on native wakes); `run` is the blocking form (start + await, no
 * ref escapes). The only throws are programmer errors (empty assignments, duplicate keys, keys
 * outside `RUN_KEY_PATTERN`); every operational failure normalizes into `ReportWaveResult`.
 */
export interface ReportWave {
  start(request: ReportWaveRequest, control?: WaveControl): Promise<StartWaveResult>;
  collect(ref: ReportWaveRef): Promise<CollectWaveResult>;
  run(request: ReportWaveRequest, control?: WaveControl): Promise<ReportWaveResult>;
}

/**
 * The grace a collect allows a not-yet-settled wave before answering `"running"`: long enough
 * to absorb ordering skew between the native completion notice and aggregate resolution,
 * bounded so a premature call can yield again. The `PERK_WAVE_COLLECT_GRACE_MS` env knob is the ONE grace seam
 * (module-private — there is no per-call grace parameter); invalid values fall back.
 */
const WAVE_COLLECT_GRACE_MS = 15_000;

function collectGraceMs(): number {
  const raw = Number(process.env.PERK_WAVE_COLLECT_GRACE_MS ?? "");
  return Number.isFinite(raw) && raw > 0 ? raw : WAVE_COLLECT_GRACE_MS;
}

/**
 * One pending (started, uncollected) wave: the frozen pre-launch key manifest snapshot (copied
 * from the launch manifest at start — caller mutation of the returned `StartWaveResult.launch`
 * can never change a later collect's keys) plus the never-rejecting result promise. NO drained
 * flag: presence in the instance's map IS pending.
 */
interface PendingRecord {
  keys: readonly string[];
  result: Promise<ReportWaveResult>;
}

/**
 * A launched (or launch-failed) wave as the internal core reports it — the module-private
 * predecessor shape the opaque lifecycle wraps (the run handle and result promise never leave
 * the module).
 */
type InternalStart =
  | {
      ok: true;
      handle: WaveRunHandle;
      result: Promise<ReportWaveResult>;
      launch: ReportWaveLaunchManifest;
    }
  | { ok: false; result: ReportWaveResult; launch: ReportWaveLaunchManifest };

/**
 * The internal launch core: validate the COMPLETE requested manifest (the programmer-error
 * throws — empty/duplicate/invalid keys — are preserved even for an unavailable required
 * skill), run the required-skill preflight partition, render the all-settled assignment script
 * over the runnable subset, and launch it via `startWaveScript`. On success the never-rejecting
 * `result` promise applies the shared settle (normalization + completeness + receipt
 * enrichment + preflight-failure merge) when the run finishes; a launch failure comes back as
 * an already-settled, normalized `ReportWaveResult`.
 */
async function startWave(
  adapter: WaveAdapter,
  request: ReportWaveRequest,
  signal?: AbortSignal,
): Promise<InternalStart> {
  validateAssignments(request.assignments);
  const preflight = request.requiredSkillPreflight ?? preflightPonytailSkill;
  const checked = new Map<string, PonytailPreflight>();
  const runnable: ReportAssignment[] = [];
  const skillFailures: ReportWaveFailure[] = [];
  for (const assignment of request.assignments) {
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

  const launch: ReportWaveLaunchManifest = {
    requested: request.assignments.map((assignment) => assignment.key),
    runnable: runnable.map((assignment) => assignment.key),
    preflightFailures: [...skillFailures],
  };

  const settleWithSkillFailures = (result: ReportWaveResult): ReportWaveResult => {
    if (skillFailures.length === 0) return result;
    const failures = [...result.failures, ...skillFailures];
    const complete =
      request.completeness === "strict"
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
  const runnableRequest: ReportWaveRequest = { ...request, assignments: runnable };
  const workflowScript = renderWaveScript(runnable);

  const start = await startWaveScript(
    adapter,
    {
      flow: request.flow,
      workflowScript,
      outputSchema: request.outputSchema,
      ...(request.model !== undefined ? { model: request.model } : {}),
      ...(request.timeoutMs !== undefined ? { timeoutMs: request.timeoutMs } : {}),
    },
    signal,
  );
  if (!start.ok) {
    return {
      ok: false,
      result: settleWithSkillFailures(
        settleReportWave(
          { ok: false, failure: start.failure, receipt: start.receipt },
          runnableRequest,
        ),
      ),
      launch,
    };
  }
  return {
    ok: true,
    handle: start.handle,
    result: start.result.then((run) =>
      settleWithSkillFailures(settleReportWave(run, runnableRequest)),
    ),
    launch,
  };
}

const STILL_RUNNING = Symbol("wave-still-running");

/**
 * The one internal core both factories share: an instance-owned pending map over a per-launch
 * adapter supplier. Pending state belongs to the wave INSTANCE — `waveB.collect(refFromA)` is
 * `"none"` structurally — and the WeakMap plus the settled drain's delete both release retained
 * results promptly.
 */
function waveOver(supplyAdapter: () => WaveAdapter): ReportWave {
  const records = new WeakMap<ReportWaveRef, PendingRecord>();

  return {
    async start(request, control) {
      const start = await startWave(supplyAdapter(), request, control?.signal);
      if (!start.ok) {
        return { ok: false, result: start.result, launch: start.launch };
      }
      // The ONE mint site — the isolated assertion, immediately after the runtime evidence of
      // a successful launch. The keys snapshot is frozen and copied, never an alias of the
      // returned manifest.
      const ref = {} as ReportWaveRef;
      records.set(ref, { keys: Object.freeze([...start.launch.requested]), result: start.result });
      return {
        ok: true,
        ref,
        runId: start.handle.asyncId,
        asyncDir: start.handle.asyncDir,
        launch: start.launch,
      };
    },

    async collect(ref) {
      const record = records.get(ref);
      if (record === undefined) return { kind: "none" };
      let timer: ReturnType<typeof setTimeout> | undefined;
      let raced: ReportWaveResult | typeof STILL_RUNNING;
      try {
        raced = await Promise.race([
          record.result,
          new Promise<typeof STILL_RUNNING>((resolve) => {
            timer = setTimeout(() => resolve(STILL_RUNNING), collectGraceMs());
          }),
        ]);
      } finally {
        clearTimeout(timer);
      }
      if (raced === STILL_RUNNING) {
        // The record stays in the map: its bound remains the module-owned wave timeout, and a
        // later collect drains whatever it settles into.
        return { kind: "running" };
      }
      // The delete IS the atomic drain claim: single-threaded JS makes the post-await
      // delete-as-claim exact — overlapping collects of one ref yield exactly one settled
      // winner; the loser (already-deleted) answers `"none"`.
      if (!records.delete(ref)) return { kind: "none" };
      return { kind: "settled", keys: record.keys, result: raced };
    },

    async run(request, control) {
      const start = await startWave(supplyAdapter(), request, control?.signal);
      return start.ok ? await start.result : start.result;
    },
  };
}

/**
 * The PRODUCTION factory — the wave owns adapter selection: constructs a FRESH rpc adapter per
 * launch over the supplied bus (per-execute adapter freshness; no shared mutable ping state).
 * One per-activation instance is constructed at the composition root (`extension/index.ts`) and
 * threaded to the installers.
 */
export function createReportWave(bus: WaveBus): ReportWave {
  return waveOver(() => createRpcWaveAdapter(bus));
}

/** The adapter-injection seam (tests; the production factory rides the same internal core). */
export function reportWaveOver(adapter: WaveAdapter): ReportWave {
  return waveOver(() => adapter);
}
