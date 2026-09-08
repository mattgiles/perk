// The session identity lifecycle (contracts.md §8.2/§8.3) as named, Pi-free session
// operations: decide what `session_start` should do (claim / fork / adopt / mint / keep) and
// perform the workflow-state establishment for the decided arm — the ONE combined claim entry
// with establish-before-consume, the derived fork/adopt identities, the warm mint, and the
// deliberate keep-arm non-write (reload-generation reconstruction IS the LWW rebuild; no
// version backfill) — then the two-phase startup facts around the gate: `sessionStartToolScope`
// (pure; the mode/stage slice the gate syncs from BEFORE any fallible read) and
// `resolveSessionStartFacts` (post-gate; the lazy launched-stage linkage reconciliation plus the
// implementation-capture and feedback-receiver inputs), with `sessionTreeFacts` as the
// navigation twin over the already-rebuilt selected-branch state.
//
// Pi-free by construction (importDirectionGuard Rule D): effects arrive through narrow
// injection points — `SessionStateStore` (the workflow-state slice: rebuild + plain append +
// the strict verified append), `SessionIdentityPorts` (handoff read/consume, run-scratch
// isolation, the run-id mint, the §8.3 version stamp), and `SessionStartFactReads` (the handoff
// + checkout plan-ref reads the post-gate facts may touch). `index.ts` binds the production
// values, orders the Pi effects, and renders the outcome's per-arm problems/warnings with today's
// exact report scopes; the strict appends keep reporting through
// `appendWorkflowStateClassified`'s own loudness channel (the report slice rides
// `SessionArtifactCtx`, re-exported via `substrate/sessionData.ts` — this module never imports
// `surfaces/`, `pi/`, or the feedback receiver).
//
// ONE handoff authority: every handoff/run-id read — the claim arm's, `decideClaim`'s
// env-child probe, `resolveRunStage`'s stage lookup, and `deriveForkRunId`'s sibling scan —
// flows through the injected reads (`SessionIdentityReads`, the read slice of
// `SessionIdentityPorts`), so the lifecycle is genuinely independent of the cache backing and
// the fakes never touch disk. The decision logic is byte-identical to its
// `substrate/workflowState.ts` ancestry.

import type { Handoff, PlanRef } from "../substrate/cache.ts";
import { type Registry, stageConsumesPlanRef } from "../substrate/registry.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type AppendWorkflowStateOpts,
  appendWorkflowStateClassified,
  branchOf,
  type ClassifiedAppend,
  type EntrySink,
  planRefsEqual,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "../substrate/workflowState.ts";

/**
 * The exterior reads the lifecycle's decision tier needs — the read slice of
 * `SessionIdentityPorts` (production bound to `substrate/cache.ts` by `index.ts`; the test
 * suites bind fakes).
 */
export interface SessionIdentityReads {
  /** The cold-launch handoff blob for `runId`, or null (missing/unreadable). */
  readHandoff(runId: string): Handoff | null;
  /** The existing run ids under `scratch/runs/` (the fork/adopt sibling-derivation scan). */
  listRunIds(): string[];
}

/**
 * Derive a fork-child run_id: `<parent>.<n>` where `n` is the max existing sibling + 1
 * (over the `scratch/runs/` scan), else 1.
 */
export function deriveForkRunId(parentRunId: string, runIds: Iterable<string>): string {
  const prefix = `${parentRunId}.`;
  let max = 0;
  for (const id of runIds) {
    if (!id.startsWith(prefix)) continue;
    const segment = id.slice(prefix.length).split(".")[0] ?? "";
    const n = Number.parseInt(segment, 10);
    if (Number.isInteger(n) && n > max) max = n;
  }
  return `${parentRunId}.${max + 1}`;
}

export type ClaimDecision =
  | { action: "keep"; source: "session"; state: WorkflowState }
  | {
      action: "fork";
      source: "fork";
      childRunId: string;
      parentRunId: string;
      state: WorkflowState;
    }
  | { action: "claim"; source: "env"; runId: string }
  | {
      action: "adopt";
      source: "env-child";
      childRunId: string;
      parentRunId: string;
      /** Inherited from the parent's handoff so read-only gating survives into the child. */
      mode?: string;
    }
  | { action: "none"; source: "none"; state: WorkflowState };

/**
 * The registry stage id the launched run is acting on, read from its handoff blob, or null.
 * Only `claim` (cold) and `keep` (reload) sessions have a settled run whose handoff records a
 * `stage` — a kept session re-reads its run's handoff on every reload, so a consuming stage's
 * checkout binding is re-read there too; `fork`, `adopt`, and `none` carry no launched stage (an
 * adopted env-child must never impersonate the launched stage; LWW restores fork/none state
 * instead). The stage gates whether `session_start` reconciles `cache.plan-ref` into
 * `active_plan_ref`.
 */
export function resolveRunStage(
  decision: ClaimDecision,
  reads: Pick<SessionIdentityReads, "readHandoff">,
): string | null {
  const runId =
    decision.action === "claim"
      ? decision.runId
      : decision.action === "keep"
        ? decision.state.run_id
        : null;
  if (runId === undefined || runId === null) return null;
  const stage = reads.readHandoff(runId)?.stage;
  return typeof stage === "string" && stage !== "" ? stage : null;
}

/**
 * Decide what `session_start` should do, from the rebuilt state + the current session handle
 * + the launch env. Reload vs fork is distinguished by the `run_id ↔ pi_session_id` mapping
 * (NOT `event.reason`, which is "startup" for a headless `pi --fork`): if the branch already
 * carries a `run_id` whose recorded `pi_session_id` differs from the current session, the id
 * was inherited across a fork → derive a child; if it matches (or is absent), it's a reload.
 * An env-inherited run id whose handoff was already CONSUMED by a different session is a
 * spawned child, not the launched session → `adopt` (derive a sibling id, inherit `mode`).
 */
export function decideClaim(args: {
  state: WorkflowState;
  currentSessionId: string | null;
  envRunId: string | null;
  reads: SessionIdentityReads;
}): ClaimDecision {
  const { state, currentSessionId, envRunId, reads } = args;
  if (state.run_id !== undefined) {
    if (state.pi_session_id === undefined || state.pi_session_id === currentSessionId) {
      return { action: "keep", source: "session", state };
    }
    const childRunId = deriveForkRunId(state.run_id, reads.listRunIds());
    return { action: "fork", source: "fork", childRunId, parentRunId: state.run_id, state };
  }
  if (envRunId !== null && envRunId !== "") {
    // Env-child detection (contracts §8.2): subagent children are spawned as separate `pi`
    // processes with the parent's env, so they arrive here carrying the parent's PERK_RUN_ID.
    // A handoff already consumed by a DIFFERENT (or unrecorded) session belongs to someone else:
    // adopt a derived `<run_id>.<n>` child identity instead of re-claiming — never re-consume the
    // handoff, never capture pointers, never impersonate the launched stage. The parent's `mode`
    // is inherited so read-only gating survives into exploration children. Everything else —
    // absent/corrupt/mismatched handoff (the loud unclaimed error), unconsumed (the normal cold
    // claim), or consumed by THIS session (idempotent re-claim after lost branch state) — stays
    // the claim arm.
    const handoff = reads.readHandoff(envRunId);
    if (
      handoff !== null &&
      handoff.run_id === envRunId &&
      handoff.consumed === true &&
      handoff.pi_session_id !== currentSessionId
    ) {
      return {
        action: "adopt",
        source: "env-child",
        childRunId: deriveForkRunId(envRunId, reads.listRunIds()),
        parentRunId: envRunId,
        mode: handoff.mode,
      };
    }
    return { action: "claim", source: "env", runId: envRunId };
  }
  return { action: "none", source: "none", state };
}

// --------------------------------------------------------------- the identity establishment

/**
 * The narrow workflow-state store port: the LWW rebuild, the plain (honest-tier, no read-back)
 * append the fork/adopt arms use, and the strict verified append. ONE port serves both the
 * identity lifecycle (which verifies `run_id`) and the session engine
 * (`session/workflowSession.ts`, which verifies each change's own field) — hence the generic
 * verified append.
 */
export interface SessionStateStore {
  rebuild(): WorkflowState;
  append(data: WorkflowState): void;
  appendVerified<K extends keyof WorkflowState>(opts: AppendWorkflowStateOpts<K>): ClassifiedAppend;
}

/**
 * The production `SessionStateStore` over the live branch: `EntrySink` appends,
 * `rebuildWorkflowState` over the branch, and `appendWorkflowStateClassified` for the strict
 * tier (its report() path stays the loudness channel for read-back failures).
 */
export function branchSessionStateStore(
  sink: EntrySink,
  source: SessionArtifactCtx,
): SessionStateStore {
  return {
    rebuild: () => rebuildWorkflowState(branchOf(source)),
    append: (data) => sink.appendEntry(WORKFLOW_STATE_TYPE, data),
    appendVerified: (opts) => appendWorkflowStateClassified(sink, source, opts),
  };
}

/** The exterior effects the lifecycle needs — production bound in `index.ts`, fakes in tests. */
export interface SessionIdentityPorts extends SessionIdentityReads {
  /** Mark the handoff consumed (establish-before-consume: called only after a verified claim). */
  markHandoffConsumed(runId: string, opts: { piSessionId?: string }): void;
  /** Isolate the derived child's run scratch root (a throw is tolerated — warned, not fatal). */
  ensureRunScratch(runId: string): void;
  /** Mint a fresh run_id for the warm identity-less arm. */
  mintRunId(): string;
  /**
   * The §8.3 exact-vintage stamp recorded by every identity-establishing arm
   * (claim/fork/adopt/mint); undefined (the perkVersion() failure sentinel) drops the key on
   * serialize and leaves the session on the timestamp-estimate arm.
   */
  versionStamp: string | undefined;
}

/** Which lifecycle arm settled (the failed claim/mint arms both read `unclaimed`). */
export type SessionIdentityArm = "claimed" | "kept" | "forked" | "adopted" | "minted" | "unclaimed";

/**
 * What `session_start` consumes downstream: the settled arm, the resolved state the byte-
 * identical derivations run over (`scopeStage`, `implStage`, the sentinel source —
 * `arm === "minted" ? "mint" : decision.source`), the decision itself, and the per-arm
 * problems/warnings the caller renders with today's exact report scopes ("workflow-state
 * linkage error" `{alsoLog: true}`; "run scratch" warnings).
 *
 * A discriminated union on `arm`, correlating each settled arm with exactly the decision that
 * can produce it: an impossible pair (e.g. `forked` carrying a claim decision) does not
 * compile, and narrowing on `arm` proves the decision's fields. `unclaimed` is the shared
 * failure arm of the two strict-append paths — a failed cold claim (`action: "claim"`) or a
 * failed mint (`action: "none"`); the correlated decision says which.
 */
export type EstablishIdentityOutcome = {
  resolved: WorkflowState;
  /** Caller-rendered with scope "workflow-state linkage error" (`{alsoLog: true}`). */
  problems: string[];
  /** Caller-rendered with scope "run scratch" (`{alsoLog: true}`). */
  warnings: string[];
} & (
  | { arm: "claimed"; decision: Extract<ClaimDecision, { action: "claim" }> }
  | { arm: "kept"; decision: Extract<ClaimDecision, { action: "keep" }> }
  | { arm: "forked"; decision: Extract<ClaimDecision, { action: "fork" }> }
  | { arm: "adopted"; decision: Extract<ClaimDecision, { action: "adopt" }> }
  | { arm: "minted"; decision: Extract<ClaimDecision, { action: "none" }> }
  | { arm: "unclaimed"; decision: Extract<ClaimDecision, { action: "claim" | "none" }> }
);

/** Reflect a captured restriction without participating in identity or handoff authority. */
export function reflectSessionReadOnlyFloor(
  store: SessionStateStore,
  outcome: EstablishIdentityOutcome,
): { outcome: EstablishIdentityOutcome; unexpectedFailure: boolean } {
  if (outcome.arm === "unclaimed" || outcome.resolved.mode === "read-only") {
    return { outcome, unexpectedFailure: false };
  }
  let appended: ClassifiedAppend;
  try {
    appended = store.appendVerified({
      data: { mode: "read-only" },
      field: "mode",
      expected: "read-only",
      scope: "child restriction",
      failure:
        "could not persist child read-only restriction; in-memory restriction remains active",
    });
  } catch {
    // The Pi edge reports this escaped-contract failure once and continues startup with the floor.
    return { outcome, unexpectedFailure: true };
  }
  return {
    outcome:
      appended.status === "applied"
        ? { ...outcome, resolved: { ...outcome.resolved, mode: "read-only" } }
        : outcome,
    unexpectedFailure: false,
  };
}

/** The refinement stage id (registry vocabulary; the admission check keys on it). */
const REFINE_STAGE_ID = "objective-refine";

/** The top-level handoff keys the plan-graph doors use as planning-link / plan-ref inputs. */
const PLANNING_LINK_KEYS = [
  "objective_id",
  "node_id",
  "adopt_from",
  "supersedes",
  "gist_scope",
  "consumed_learn",
] as const;

/**
 * Which planning-link / plan-ref input (if any) an `objective-refine` handoff carries at the
 * top level — `null` for every non-refinement handoff and for a clean refinement one. A key is
 * "carried" when present and not null/undefined (an empty `consumed_learn` list is clean).
 */
export function refinementHandoffContamination(handoff: Handoff): string | null {
  if (handoff.stage !== REFINE_STAGE_ID) return null;
  const carried = PLANNING_LINK_KEYS.filter((key) => {
    const value = handoff[key];
    if (value === undefined || value === null) return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  });
  return carried.length === 0 ? null : carried.join(", ");
}

/**
 * Establish the session's run identity — the four `session_start` arms as one named operation:
 *
 * - **claim** (cold): read the handoff via the port (missing/mismatched ⇒ `unclaimed` with the
 *   loud problem; never falls through to mint) → build the ONE combined entry (`run_id`,
 *   `pi_session_id`, `mode`, the `perk_version` stamp, `stage`, and the `objective_node_claim`
 *   carrier when the handoff's `objective_id`/`node_id` are both non-blank strings) → ONE
 *   strict append verified on `run_id` → only on verified success, consume the handoff
 *   (establish-before-consume: a failed read-back ⇒ `unclaimed`, NOT consumed).
 * - **fork** / **adopt**: isolate the derived child's scratch (a throw is a warning; identity
 *   still settles) → the derived-identity append — plain appends (honest tier, no read-back).
 *   Fork inherits the parent's `mode` and NO `stage` (LWW carries the parent's); adopt takes
 *   `mode` from the handoff and never impersonates stage or claim (and never re-consumes).
 * - **mint** (`none`): mint a run_id → strict append verified on `run_id`; a failed read-back
 *   leaves the session unidentified (`unclaimed` — re-mints next `session_start`).
 * - **keep** (reload): NO append — reload-generation reconstruction IS the LWW rebuild, and the
 *   deliberate no-version-backfill non-write is preserved.
 */
export function establishSessionIdentity(
  store: SessionStateStore,
  ports: SessionIdentityPorts,
  input: { currentSessionId: string | null; envRunId: string | null },
): EstablishIdentityOutcome {
  const problems: string[] = [];
  const warnings: string[] = [];
  const currentSessionId = input.currentSessionId;
  const decision = decideClaim({
    state: store.rebuild(),
    currentSessionId,
    envRunId: input.envRunId,
    reads: ports,
  });
  const stamp = ports.versionStamp;

  if (decision.action === "claim") {
    // Cold claim — establish before consume (strict).
    const handoff = ports.readHandoff(decision.runId);
    if (handoff === null || handoff.run_id !== decision.runId) {
      problems.push(`handoff missing or mismatched for run ${decision.runId}`);
      return { arm: "unclaimed", resolved: {}, decision, problems, warnings };
    }
    // Refinement admission (contracts.md §8.67): the isolated `objective-refine` stage must
    // never arrive carrying a planning link or plan-ref input — those top-level keys are what
    // the claim arm below (and the plan-save recovery paths) read as a planning claim /
    // adoption. A contaminated refinement handoff is REFUSED before any claim is recorded and
    // is NOT consumed (the door that wrote it is the defect; nothing here rebinds or clears).
    // Ordinary objective-plan handoffs (which legitimately carry objective_id/node_id) are
    // untouched.
    const contamination = refinementHandoffContamination(handoff);
    if (contamination !== null) {
      problems.push(
        `refusing the objective-refine handoff for run ${decision.runId}: it carries ${contamination} (a planning link/plan-ref input a refinement session never accepts)`,
      );
      return { arm: "unclaimed", resolved: {}, decision, problems, warnings };
    }
    // The objective-plan cold door's handoff_extra carries the node link
    // (objective_id/node_id): persist it as the objective_node_claim so the implement-here
    // exits are structurally suppressed in COLD objective-plan sessions too (the warm
    // `objective_node` tool records the claim; a cold factory session never calls it — the
    // door marked the node before launch). Blank/absent ids persist nothing; the claim
    // clears on a successful node-linked save exactly as the warm-recorded one does.
    const handoffObjective = handoff.objective_id;
    const handoffNode = handoff.node_id;
    const nodeClaim =
      typeof handoffObjective === "string" &&
      handoffObjective.trim() !== "" &&
      typeof handoffNode === "string" &&
      handoffNode.trim() !== ""
        ? { objective: handoffObjective, node: handoffNode }
        : undefined;
    const data: WorkflowState = {
      run_id: decision.runId,
      pi_session_id: currentSessionId ?? undefined,
      mode: handoff.mode,
      perk_version: stamp,
      // Record the launched stage so the interior can tell e.g. objective-author from plan
      // (both are read-only) and inject the right authoring context.
      stage: handoff.stage,
      ...(nodeClaim !== undefined ? { objective_node_claim: nodeClaim } : {}),
    };
    const appended = store.appendVerified({
      data,
      field: "run_id",
      expected: decision.runId,
      scope: "workflow-state linkage error",
      failure: `read-back failed for run ${decision.runId}`,
    });
    if (appended.status !== "applied") {
      // do NOT consume — the strict-append seam already reported the failure loudly.
      return { arm: "unclaimed", resolved: {}, decision, problems, warnings };
    }
    ports.markHandoffConsumed(decision.runId, { piSessionId: currentSessionId ?? undefined });
    return { arm: "claimed", resolved: data, decision, problems, warnings };
  }

  if (decision.action === "fork" || decision.action === "adopt") {
    // Inherited/adopted run identity → isolate the child's scratch. A static redirect or
    // filesystem failure is loud but does not prevent the derived workflow identity from
    // settling; later eligible turns retry through the agent-scratch resolver. The adopt arm
    // mirrors fork minus everything that belongs to the launched session (contracts §8.2):
    // never re-consume the handoff, no `stage` (no stage impersonation), no claim.
    try {
      ports.ensureRunScratch(decision.childRunId);
    } catch (error) {
      const kind = decision.action === "fork" ? "fork" : "adopted";
      warnings.push(
        `could not create ${kind} run root for ${decision.childRunId}: ${String(error)}`,
      );
    }
    const data: WorkflowState = {
      run_id: decision.childRunId,
      pi_session_id: currentSessionId ?? undefined,
      predecessor: decision.parentRunId,
      mode: decision.action === "fork" ? decision.state.mode : decision.mode,
      perk_version: stamp,
    };
    store.append(data);
    if (decision.action === "fork") {
      return { arm: "forked", resolved: data, decision, problems, warnings };
    }
    return { arm: "adopted", resolved: data, decision, problems, warnings };
  }

  if (decision.action === "none") {
    // A warm session with no identity mints its own run_id so per-run state (the session data
    // dir) can key off it. No disk artifacts — dirs are the accessor's job; provenance is
    // recorded separately. A failed cold claim above never falls here (claim stays a loud
    // unclaimed error).
    const runId = ports.mintRunId();
    const data: WorkflowState = {
      run_id: runId,
      pi_session_id: currentSessionId ?? undefined,
      perk_version: stamp,
    };
    const appended = store.appendVerified({
      data,
      field: "run_id",
      expected: runId,
      scope: "workflow-state linkage error",
      failure: `read-back failed for minted run ${runId}`,
    });
    if (appended.status === "applied") {
      return {
        arm: "minted",
        resolved: { ...decision.state, ...data },
        decision,
        problems,
        warnings,
      };
    }
    // Loud-but-non-fatal (the seam reported): the session stays unidentified and re-mints on
    // the next session_start.
    return { arm: "unclaimed", resolved: decision.state, decision, problems, warnings };
  }

  // keep (reload): NO append — reload-generation reconstruction IS the LWW rebuild; the
  // deliberate no-version-backfill non-write is preserved (§8.3: an LWW backfill would
  // mis-stamp an old session with today's version).
  return { arm: "kept", resolved: decision.state, decision, problems, warnings };
}

// ------------------------------------------------------------- the two-phase startup facts

/**
 * PHASE 1 (before the gate) — the tool-scope slice `gating.syncFromState` consumes, derived
 * PURELY from the established identity: no store, handoff, registry, or checkout read can sit
 * between identity establishment and gate synchronization (a read failure must never leave the
 * gate unsynced). Mode is exactly the resolved mode (after optional floor reflection). The scope
 * stage is the workflow-state `stage` key (§8.40): claim → the handoff-recorded stage just
 * appended; keep/none → the branch-LWW stage; fork INHERITS the parent's stage (a forked
 * implement session is an implement session); adopt NEVER impersonates (a subagent child's
 * fresh branch carries no stage, so `session_tree` agrees). A failed claim leaves `resolved`
 * empty → no stage → unscoped (stage scoping is fail-open). No stage validation or
 * normalization — an unknown stage id passes through as-is.
 */
export function sessionStartToolScope(
  identity: EstablishIdentityOutcome,
): Pick<WorkflowState, "mode" | "stage"> {
  const { resolved, decision } = identity;
  const stage =
    decision.action === "adopt"
      ? undefined
      : (resolved.stage ?? (decision.action === "fork" ? decision.state.stage : undefined));
  return { mode: resolved.mode, stage };
}

/**
 * The exterior reads the post-gate facts may touch — the handoff (the launched-stage authority
 * for claim/keep) and the checkout `cache.plan-ref` (read ONLY on the consuming arm). Production
 * binds both cwd-bound in `index.ts`; the suites bind recording fakes.
 */
export interface SessionStartFactReads extends Pick<SessionIdentityReads, "readHandoff"> {
  /** The worktree's `cache.plan-ref` selector, or null (missing/unreadable). */
  readPlanRef(): PlanRef | null;
}

/**
 * The receiver-shaped feedback inputs both startup and navigation derive. Deliberately a local,
 * inferred structural shape (no shared vocabulary with `hunkFeedback/receiver.ts`): the
 * `index.ts` call site adds Pi's run `mode` and the receiver's own `ReceiverSyncArgs` accepts
 * the result structurally. Eligibility stays receiver-owned (its fresh checkout read included).
 */
interface SessionFeedbackFacts {
  stage: string | null;
  adopted: boolean;
  runId: string | null;
  piSessionId: string | null;
  activePlanRef: PlanRef | null;
}

/**
 * PHASE 2 (after the gate and the claimed-only refinement import) — the lazy linkage
 * reconciliation plus the derived capture/feedback inputs. `resolved` is the same
 * `WorkflowState`-shaped diagnostic startup always produced (the T3 sentinel's material) —
 * lifecycle-local, not a feature-facing snapshot.
 */
export interface SessionStartFacts {
  resolved: WorkflowState;
  /** Present only for an identified implement session (launched or fork-inherited stage). */
  implementationCapture: { runId: string; parentSessionId: string | null } | null;
  feedback: SessionFeedbackFacts;
}

/**
 * The post-gate startup facts. Operation order (each step's port is the only one it touches):
 *
 * 1. Rebuild the live linked `active_plan_ref` ONCE (the store), before any handoff read.
 * 2. Resolve the launched stage through the handoff reader — claim/keep only (`resolveRunStage`);
 *    fork/adopt/none never read a stage handoff here.
 * 3. Registry admission: only a non-null launched stage can consume the checkout ref
 *    (`stageConsumesPlanRef`); a null registry stays PERMISSIVE when a stage is present (to
 *    preserve implement linkage); an unknown stage in an available registry does not consume.
 * 4. On the consuming arm ONLY, read the checkout `cache.plan-ref`: same `(provider, pr_id)`
 *    keeps the existing linked object without appending; a different ref performs ONE strict
 *    verified append (`active_plan_ref`, `planRefsEqual`, the "workflow-state linkage error"
 *    scope) and folds the new ref in ONLY on `applied` — a rejected/unverified append leaves
 *    `resolved` exactly as it arrived (a kept session keeps its LWW ref; a fresh claim keeps
 *    none — never flattened, never rebuilt again to manufacture a fallback); no cached ref
 *    preserves a non-null linked ref. A non-consuming (or absent) launched stage preserves a
 *    non-null linked ref WITHOUT reading the checkout — the root selector must not leak in.
 * 5. The implementation stage is the launched stage, with only a fork falling back to its
 *    parent's LWW stage; `implementationCapture` exists only for a truthy run id on
 *    `stage === "implement"` (parent provenance comes only from the fork decision).
 * 6. `feedback` carries the implementation stage, the decision's adoption, the resolved
 *    run/ref, and startup's CURRENT Pi session handle (never an inherited branch handle).
 *
 * A throwing store/read propagates to the caller (Pi's hook error boundary) — unreadability is
 * never turned into confirmed absence, and no later effect runs from guessed facts.
 */
export function resolveSessionStartFacts(
  store: SessionStateStore,
  reads: SessionStartFactReads,
  input: {
    identity: EstablishIdentityOutcome;
    /** The already-loaded registry (null when it failed to load) — never a loader. */
    registry: Registry | null;
    currentSessionId: string | null;
  },
): SessionStartFacts {
  const { identity, registry, currentSessionId } = input;
  const decision = identity.decision;
  let resolved: WorkflowState = identity.resolved;

  const linked = store.rebuild().active_plan_ref ?? null;
  const launchedStage = resolveRunStage(decision, reads);
  const consumesPlanRef =
    launchedStage !== null && (registry === null || stageConsumesPlanRef(registry, launchedStage));
  if (consumesPlanRef) {
    const cachedRef = reads.readPlanRef();
    if (cachedRef !== null) {
      if (planRefsEqual(linked, cachedRef)) {
        resolved = { ...resolved, active_plan_ref: linked };
      } else {
        const appended = store.appendVerified({
          data: { active_plan_ref: cachedRef },
          field: "active_plan_ref",
          expected: cachedRef,
          scope: "workflow-state linkage error",
          failure: `plan-ref read-back failed for ${cachedRef.provider}:${cachedRef.pr_id}`,
          equals: planRefsEqual,
        });
        if (appended.status === "applied") resolved = { ...resolved, active_plan_ref: cachedRef };
      }
    } else if (linked !== null) {
      resolved = { ...resolved, active_plan_ref: linked };
    }
  } else if (linked !== null) {
    resolved = { ...resolved, active_plan_ref: linked };
  }

  const implementationStage =
    launchedStage ?? (decision.action === "fork" ? (decision.state.stage ?? null) : null);
  const implementationCapture =
    resolved.run_id && implementationStage === "implement"
      ? {
          runId: resolved.run_id,
          parentSessionId:
            decision.action === "fork" ? (decision.state.pi_session_id ?? null) : null,
        }
      : null;

  return {
    resolved,
    implementationCapture,
    feedback: {
      stage: implementationStage,
      adopted: decision.action === "adopt",
      runId: resolved.run_id ?? null,
      piSessionId: currentSessionId,
      activePlanRef: resolved.active_plan_ref ?? null,
    },
  };
}

/**
 * The navigation twin (`session_tree`), PURE over the ONE already-rebuilt selected-branch state:
 * tool scope is the branch's per-field-LWW mode/stage (the §8.40 key); feedback uses the
 * branch's stage/run/ref AND ITS OWN recorded session id (not startup's current-handle
 * override) with `adopted: false` — an env-adopted child's fresh branch carries no stage, so the
 * stage gate alone keeps it receiver-ineligible. No handoff/checkout read, claim, linkage, or
 * implementation capture happens on navigation (a deliberate asymmetry with startup).
 */
export function sessionTreeFacts(state: WorkflowState): {
  toolScope: Pick<WorkflowState, "mode" | "stage">;
  feedback: SessionFeedbackFacts;
} {
  return {
    toolScope: { mode: state.mode, stage: state.stage },
    feedback: {
      stage: state.stage ?? null,
      adopted: false,
      runId: state.run_id ?? null,
      piSessionId: state.pi_session_id ?? null,
      activePlanRef: state.active_plan_ref ?? null,
    },
  };
}
