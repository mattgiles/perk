// The ready + handoff transition feature (the ready half of the delivery pair), Pi-free.
//
// One entry point — `readyChange` — owns the transition's ordering, verification, and the
// session-transition decision: the exterior effect first (the Python cold door marks the PR
// ready, appends the SHA-bound journal stamp, and converges idempotent re-stamps — mutations
// canonical), then classification and the continuation decision computed wholly before any
// surface activity. The warm plane never re-derives staleness or idempotency — that is why the
// outcome union has NO warm `stale` arm: a cascade-staled stamp is repaired Python-side by
// re-running ready.
//
// Correlated facts are structure, not independent optionals: the `ReadyFacts` union makes a
// continuation cohort without the worker's stacked routing fact (or vice versa) unrepresentable,
// and each outcome arm is constrained to its matching facts variant — a `completed` with stacked
// facts, a `stamped` without a cohort, or a drive on an unverified stamp cannot compile.
//
// The port is action-specific (never a generic handoff manager): `MarkReady` has exactly ONE
// production adapter — the `perk pr ready --json` cold-door composition in
// `pi/v1/delivery/ready.ts`. The gate read is an injected capability (`sessionReadOnly`), not a
// ToolGating import — the feature stays Pi-free.

// The drive's strict evidence vocabulary (contracts.md §8.66), local on purpose: this is
// exact-evidence validation at the continuation boundary, NOT the lenient render vocabulary
// other stack surfaces use. Both diff-range endpoints must be the full 40-hex lowercase
// object id; ids must be marker-safe segments.
const READY_EVIDENCE_ID_RE = /^[A-Za-z0-9._-]{1,64}$/;
const READY_FULL_SHA_RE = /^[0-9a-f]{40}$/;

/** The readied PR's identity facts (strict on the wire — a malformed `pr` fails the decode). */
export interface ReadyPr {
  number: number;
  url: string;
}

/** The stacked handoff cohort — decoded all-or-nothing (advisory detail, never half-rendered).
 * Deliberately facts-only: the worker envelope's `reconcile_notice`/`reconcile_retry` are cold
 * presentation strings — the warm surface derives its own retry gesture from `plan`, so missing
 * presentation data can never suppress an otherwise valid continuation. */
export interface ReadyHandoff {
  objective: string;
  node: string;
  stamped_head: string;
  stamp_advanced: boolean;
  plan: string;
  parent_checkpoint: string;
}

/** An incremental ready: the review gate opened. `stacked` is false OR absent (an old worker) —
 * the absence is preserved for the wire (the details rebuild passes it through). */
interface IncrementalReadyFacts {
  route: "incremental";
  pr: ReadyPr;
  was_draft?: boolean;
  stacked?: false;
}

/** A stacked stamp whose continuation cohort failed to decode (dropped whole) — the worker's
 * own success already proved the mechanics, but the recording facts are unverifiable (a
 * mixed-version envelope). */
interface StackedUnverifiedReadyFacts {
  route: "stacked_unverified";
  pr: ReadyPr;
  was_draft?: boolean;
}

/** A stacked stamp with the full continuation cohort. */
interface StackedReadyFacts {
  route: "stacked";
  pr: ReadyPr;
  was_draft?: boolean;
  handoff: ReadyHandoff;
}

/** The discriminated ready facts — the wire's correlations become structure: a cohort without
 * the stacked routing fact (or a dropped cohort masquerading as incremental) is unrepresentable. */
export type ReadyFacts = IncrementalReadyFacts | StackedUnverifiedReadyFacts | StackedReadyFacts;

/** One external mark-ready attempt: the verified facts, or the adapter's soft failure. */
export type MarkReadyAttempt =
  | { ok: true; facts: ReadyFacts }
  | { ok: false; message: string; errorType: string };

/** The mark-ready port — ONE production adapter (the cold-door composition in the installer). */
export type MarkReady = () => Promise<MarkReadyAttempt>;

export interface ReadyDeps {
  markReady: MarkReady;
  /** The gate read, injected as a capability. Read ONLY on the stamped-with-cohort path — the
   * negative arms (`failed`, `completed`, `stamp_facts_unverified`) never touch it. */
  sessionReadOnly: () => boolean;
}

/**
 * The validated drive evidence — NOMINAL and mint-only (the WorkerModelSelection precedent):
 * the `#private` field makes structural forgery impossible, the constructor is unreachable
 * outside this module, and `readyChange` mints it from the SAME facts value the `stamped` arm
 * carries, only after the strict evidence vocabulary passed. Every field is a validated
 * primitive SNAPSHOTTED at mint time — the evidence never aliases the caller-reachable handoff
 * object, so post-validation mutation of `facts.handoff` cannot reach the drive render. The
 * drive template interpolates exclusively from this type, so an unvalidated (or
 * facts-divergent) drive is unrepresentable.
 */
class ReadyDriveEvidence {
  // The ONE `#private` field supplies the nominal guarantee; the getter below reads it.
  readonly #objective: string;
  readonly node: string;
  readonly plan: string;
  readonly stamped_head: string;
  readonly parent_checkpoint: string;
  /** The verified PR number (integer-checked with the evidence). */
  readonly pr: number;

  constructor(handoff: ReadyHandoff, pr: number) {
    this.#objective = handoff.objective;
    this.node = handoff.node;
    this.plan = handoff.plan;
    this.stamped_head = handoff.stamped_head;
    this.parent_checkpoint = handoff.parent_checkpoint;
    this.pr = pr;
  }

  get objective(): string {
    return this.#objective;
  }
}

export type { ReadyDriveEvidence };

/**
 * The continuation decision for a stamped-with-cohort ready, in the pinned arm order: the gate
 * check comes BEFORE evidence validation. `retryPlan` carries the safe-interpolation policy —
 * the id vocabulary applied to `handoff.plan`; `null` ⇒ the adapter renders the `<plan>`
 * placeholder.
 */
export type ReadyContinuation =
  | { kind: "refused_read_only"; retryPlan: string | null }
  | { kind: "evidence_invalid"; retryPlan: string | null }
  | { kind: "drive"; evidence: ReadyDriveEvidence };

/** The honest outcome vocabulary — each arm constrained to its matching facts variant. */
export type ReadyOutcome =
  /** Exterior failure — no continuation activity, the gate is never read. */
  | { kind: "failed"; message: string; errorType: string }
  /** The effect is verified; nothing to continue. */
  | { kind: "completed"; facts: IncrementalReadyFacts }
  /** The effect stands; the recording facts are unverifiable (a mixed-version envelope). */
  | { kind: "stamp_facts_unverified"; facts: StackedUnverifiedReadyFacts }
  /** The effect stands with a verified cohort; the continuation decision rides along. */
  | { kind: "stamped"; facts: StackedReadyFacts; continuation: ReadyContinuation };

/** Decide the continuation for a stamped cohort: gate first (pinned order), then the strict
 * evidence vocabulary, then mint the drive evidence from the SAME facts the arm carries. */
function decideContinuation(facts: StackedReadyFacts, deps: ReadyDeps): ReadyContinuation {
  const handoff = facts.handoff;
  const retryPlan = READY_EVIDENCE_ID_RE.test(handoff.plan) ? handoff.plan : null;
  if (deps.sessionReadOnly()) return { kind: "refused_read_only", retryPlan };
  const idsValid =
    READY_EVIDENCE_ID_RE.test(handoff.objective) &&
    READY_EVIDENCE_ID_RE.test(handoff.node) &&
    READY_EVIDENCE_ID_RE.test(handoff.plan);
  const shasValid =
    READY_FULL_SHA_RE.test(handoff.stamped_head) &&
    READY_FULL_SHA_RE.test(handoff.parent_checkpoint);
  if (!idsValid || !shasValid || !Number.isInteger(facts.pr.number)) {
    return { kind: "evidence_invalid", retryPlan };
  }
  return { kind: "drive", evidence: new ReadyDriveEvidence(handoff, facts.pr.number) };
}

/**
 * The one ready operation: the exterior effect first, then the exhaustive classification over
 * the facts route, then — on the stamped-with-cohort path ONLY — the continuation decision.
 * A failed attempt returns as-is with no continuation activity; `completed` and
 * `stamp_facts_unverified` likewise never read the gate (no recording exists to guard on this
 * path, and no horizontal completion is performed — WorkflowSession stays untouched).
 */
export async function readyChange(deps: ReadyDeps): Promise<ReadyOutcome> {
  const attempt = await deps.markReady();
  if (!attempt.ok) {
    return { kind: "failed", message: attempt.message, errorType: attempt.errorType };
  }
  const facts = attempt.facts;
  switch (facts.route) {
    case "incremental":
      return { kind: "completed", facts };
    case "stacked_unverified":
      return { kind: "stamp_facts_unverified", facts };
    case "stacked":
      return { kind: "stamped", facts, continuation: decideContinuation(facts, deps) };
  }
  // Exhaustive over the route (no default arm): a new facts variant fails to compile here.
  const exhaustive: never = facts;
  throw new Error(`unreachable ready facts route: ${JSON.stringify(exhaustive)}`);
}
