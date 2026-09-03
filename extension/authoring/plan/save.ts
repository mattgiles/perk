// The plan save feature: the narrow exterior `PlanBackend` port (one production adapter — the
// `perk plan save` cold door in pi/v1 — plus one deterministic fake in the tests: the port
// admission rule), the `savePlan` operation, and the shared APPROVED-review → save orchestration
// `planApprovalSave` (the exported name contracts.md §8.23 pins — the `gistApprovalSave`
// mirror).
//
// Identity-less saves stay legal and fully specified: `session.runId === null` ⇒ the backend
// sees `runId: null` (the adapter omits `--run-id`), pointer capture no-ops in the adapter, and
// the LINKAGE + CLAIM ops still run — workflow-state appends are branch-backed and
// identity-independent (today's behavior, preserved). Backend saves are not abortable
// mid-flight (today's behavior — stated, not changed).

import type {
  PlanRef,
  WorkflowChangeResult,
  WorkflowSession,
} from "../../session/workflowSession.ts";
import { resumePlanDraft } from "./draft.ts";
import { type PlanSource, resolvePlanSource } from "./source.ts";

/** The atomic objective node→plan commit surfaced by `perk plan save`. */
export interface ObjectiveNodeLink {
  linked: boolean;
  node: string | null;
  status: string | null;
  error: string | null;
}

/** The backend save facts (`ref.pr_id` is the opaque string issue id — contracts §8.21). */
export type PlanBackendSaveResult =
  | {
      status: "saved";
      ref: PlanRef;
      existed: boolean | null;
      updated: boolean;
      cached: boolean;
      nodeLink: ObjectiveNodeLink | null;
    }
  | { status: "failed"; message: string; errorType: string };

/**
 * The narrow exterior port the save operation writes through. `runId: null` means the caller
 * has no session identity — the backend omits its run linkage (an identity-less save keeps
 * working).
 */
export interface PlanBackend {
  save(req: {
    plan: string;
    title?: string;
    runId: string | null;
    objectiveId?: string;
    nodeId?: string;
    consumedLearn?: string[];
  }): Promise<PlanBackendSaveResult>;
}

/**
 * The save outcome. The saved arm carries the backend facts PLUS the resolution facts
 * (`source`/`paramMismatch` ride through for the adapter's message assembly) and the two
 * workflow-state results — the session seam's own `WorkflowChangeResult` values passed through
 * VERBATIM (lossless by construction; `null` means not attempted: `linkage` when the save
 * failed before it, `claimClear` when there was no matching claim / no node link). The
 * production adapter's rendering ignores both fields (byte-stable output); they exist so the
 * feature outcome is honest and the direct feature tests can pin every arm — the seam's type,
 * not new API surface.
 */
export type SavePlanOutcome =
  | {
      status: "saved";
      ref: PlanRef;
      existed: boolean | null;
      updated: boolean;
      cached: boolean;
      nodeLink: ObjectiveNodeLink | null;
      source: PlanSource | null;
      paramMismatch: boolean;
      linkage: WorkflowChangeResult | null;
      claimClear: WorkflowChangeResult | null;
    }
  | { status: "failed"; message: string; errorType: string };

/** The dependency bag the save operation runs over (the adapter composes production values). */
export interface PlanSaveDeps {
  session: WorkflowSession;
  backend: PlanBackend;
  /** Best-effort LLM title (null ⇒ the cold door's `derive_title` fallback takes over). */
  generateTitle(plan: string): Promise<string | null>;
  /** Best-effort planning-pointer capture (contracts §8.35; no-ops on absent identity). */
  capturePlanningPointer(): void;
}

/**
 * The single save operation every plan-save surface calls. Ordering preserved exactly: validate
 * the non-blank plan → resolve the title (explicit wins; else `generateTitle`; null ⇒ the cold
 * door derives) → warm node-claim recovery (BOTH link params absent ⇒ fill both from
 * `session.nodeClaim()`; any explicit value — even one — wins outright, never mixed) →
 * `backend.save` → `capturePlanningPointer()` (best-effort thunk) → link the live session
 * (`apply({kind:"link-plan-ref"})` — append iff the ref differs) → on a node-linked save whose
 * FULL claim identity matches (resolved objective + linked node), clear the claim
 * (`apply({kind:"clear-node-claim"})` — an unrelated claim is never clobbered). Never throws.
 */
export async function savePlan(
  input: {
    plan: string;
    title?: string;
    objectiveId?: string;
    nodeId?: string;
    consumedLearn?: string[];
    /** The resolved plan source — surfaced in the adapter's message when non-param. */
    source?: PlanSource;
    /** A differing explicit param was ignored in favor of the artifact (visibly flagged). */
    paramMismatch?: boolean;
  },
  deps: PlanSaveDeps,
): Promise<SavePlanOutcome> {
  const plan = input.plan.trim();
  if (!plan) {
    return {
      status: "failed",
      message: "no plan markdown to save (propose a plan first)",
      errorType: "invalid_input",
    };
  }

  // Forward an explicit title (previously accepted but DROPPED), else best-effort generate one
  // via the session model. On any failure the cold door's `derive_title` fallback takes over.
  const explicit = input.title?.trim();
  const title =
    explicit && explicit.length > 0 ? explicit : ((await deps.generateTitle(plan)) ?? undefined);

  // Warm node-link recovery. When BOTH link params are absent (an approval-triggered save
  // carries no model params), fill both-or-neither from the rebuilt `objective_node_claim`. Any
  // explicit value (even one) wins outright — a half-specified link is the caller's, never
  // mixed with the claim. Fail-open: a malformed/missing claim never blocks a save
  // (`nodeClaim()` returns null). Mirrors the cold `_link_from_handoff`.
  let objectiveId = input.objectiveId;
  let nodeId = input.nodeId;
  if (objectiveId === undefined && nodeId === undefined) {
    const claim = deps.session.nodeClaim();
    if (claim !== null) {
      objectiveId = claim.objective;
      nodeId = claim.node;
    }
  }

  const saved = await deps.backend.save({
    plan,
    ...(title !== undefined ? { title } : {}),
    runId: deps.session.runId,
    ...(objectiveId !== undefined ? { objectiveId } : {}),
    ...(nodeId !== undefined ? { nodeId } : {}),
    ...(input.consumedLearn !== undefined ? { consumedLearn: input.consumedLearn } : {}),
  });
  if (saved.status === "failed") return saved;

  // Capture the planning session pointer (contracts.md §8.35): best-effort + non-fatal (the
  // carrier warns + no-ops on absent identity; a successful save must stand).
  deps.capturePlanningPointer();

  // Link the live session: the seam appends iff the rebuilt ref differs, with a strict
  // read-back — verbatim into the outcome (the adapter's rendering ignores it; the append
  // helper's report() stays the loudness channel).
  const linkage = deps.session.apply({ kind: "link-plan-ref", ref: saved.ref });

  // A successful node-linked save clears the matching claim (best-effort — failure only risks
  // a stale claim silently linking a later, unrelated save; surfaced via the seam's loud
  // report()). The FULL claim identity must match — the resolved objective AND the linked node
  // — so a save linked to objective B node 1.1 never clears objective A's standing 1.1 claim.
  let claimClear: WorkflowChangeResult | null = null;
  if (saved.nodeLink?.linked === true) {
    const linkedNode = saved.nodeLink.node ?? nodeId ?? null;
    const claim = deps.session.nodeClaim();
    if (
      linkedNode !== null &&
      claim !== null &&
      claim.node === linkedNode &&
      claim.objective === objectiveId
    ) {
      claimClear = deps.session.apply({
        kind: "clear-node-claim",
        claim: { objective: claim.objective, node: linkedNode },
      });
    }
  }

  return {
    status: "saved",
    ref: saved.ref,
    existed: saved.existed,
    updated: saved.updated,
    cached: saved.cached,
    nodeLink: saved.nodeLink,
    source: input.source ?? null,
    paramMismatch: input.paramMismatch ?? false,
    linkage,
    claimClear,
  };
}

/** The structural gate slice the approval→save flow releases (the adapter builds it over ToolGating). */
export interface PlanGate {
  isActive(): boolean;
  exit(): void;
}

/** The approval→save orchestration outcome (the plan `GistApprovalSaveOutcome` mirror). */
export type PlanApprovalSaveOutcome =
  | { status: "no-plan" }
  | { status: "saved"; result: Extract<SavePlanOutcome, { status: "saved" }>; gateExited: boolean }
  | {
      status: "save-failed";
      result: Extract<SavePlanOutcome, { status: "failed" }>;
      gateExited: false;
    };

/** The approval→save dependency bag: the save deps + the gate + the save-mode transcript tier. */
export interface PlanApprovalSaveDeps extends PlanSaveDeps {
  gate: PlanGate;
  /** The transcript-scrape thunk (save-mode last resort); omit where the tier cannot apply. */
  transcript?: () => string | null;
}

/**
 * The shared APPROVED-review → save orchestration (an APPROVED `plan_review` outcome and the
 * manual `/plan-save` failsafe both run THIS — contracts §8.23 pins the name). Flow:
 * artifact-first resolution (`resolvePlanSource` — `reviewedPlan` is the explicit fallback, the
 * transcript scrape last) → `savePlan` (warm node-claim recovery happens inside) → gate exit
 * ONLY on a verified successful save while read-only (the D1a pattern: snapshot
 * `gate.isActive()` BEFORE the save; a failed save leaves the gate ON). No resolvable plan
 * source → `no-plan` (nothing saved, the gate untouched); callers render their own fallback.
 */
export async function planApprovalSave(
  deps: PlanApprovalSaveDeps,
  opts: { reviewedPlan?: string; title?: string } = {},
): Promise<PlanApprovalSaveOutcome> {
  const src = resolvePlanSource(
    {
      draft: resumePlanDraft(deps.session),
      ...(opts.reviewedPlan !== undefined ? { explicit: opts.reviewedPlan } : {}),
      ...(deps.transcript !== undefined ? { transcript: deps.transcript } : {}),
    },
    "save",
  );
  if (src === null) return { status: "no-plan" };
  // D1a: snapshot the gate BEFORE the save; on success, exit it so save marks the read-only →
  // read-write boundary in one gesture. A failed save leaves the gate on.
  const wasReadOnly = deps.gate.isActive();
  const result = await savePlan(
    {
      plan: src.plan,
      source: src.source,
      paramMismatch: src.paramMismatch,
      ...(opts.title !== undefined ? { title: opts.title } : {}),
    },
    deps,
  );
  if (result.status === "failed") return { status: "save-failed", result, gateExited: false };
  let gateExited = false;
  if (wasReadOnly) {
    deps.gate.exit();
    gateExited = true;
  }
  return { status: "saved", result, gateExited };
}
