// The session identity lifecycle (contracts.md §8.2/§8.3) as a named, Pi-free session
// operation: decide what `session_start` should do (claim / fork / adopt / mint / keep) and
// perform the workflow-state establishment for the decided arm — the ONE combined claim entry
// with establish-before-consume, the derived fork/adopt identities, the warm mint, and the
// deliberate keep-arm non-write (reload-generation reconstruction IS the LWW rebuild; no
// version backfill).
//
// Pi-free by construction (importDirectionGuard Rule D): effects arrive through two narrow
// injection points — `SessionStateStore` (the workflow-state slice: rebuild + plain append +
// the strict verified append) and `SessionIdentityPorts` (handoff read/consume, run-scratch
// isolation, the run-id mint, the §8.3 version stamp). `index.ts` binds the production values
// and renders the outcome's per-arm problems/warnings with today's exact report scopes; the
// strict appends keep reporting through `appendWorkflowStateClassified`'s own loudness channel
// (the report slice rides `SessionArtifactCtx`, re-exported via `substrate/sessionData.ts` —
// this module never imports `surfaces/`).
//
// ONE handoff authority: every handoff/run-id read — the claim arm's, `decideClaim`'s
// env-child probe, `resolveRunStage`'s stage lookup, and `deriveForkRunId`'s sibling scan —
// flows through the injected reads (`SessionIdentityReads`, the read slice of
// `SessionIdentityPorts`), so the lifecycle is genuinely independent of the cache backing and
// the fakes never touch disk. The decision logic is byte-identical to its
// `substrate/workflowState.ts` ancestry.

import type { Handoff } from "../substrate/cache.ts";
import type { SessionArtifactCtx } from "../substrate/sessionData.ts";
import {
  type AppendWorkflowStateOpts,
  appendWorkflowStateClassified,
  branchOf,
  type ClassifiedAppend,
  type EntrySink,
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
 * `stage`; `fork`, `adopt`, and `none` carry no launched stage (an adopted env-child must never
 * impersonate the launched stage; LWW restores fork/none state instead). The stage gates whether
 * `session_start` reconciles `cache.plan-ref` into `active_plan_ref`.
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
