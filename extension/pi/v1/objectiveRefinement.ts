// The v1 Pi installer for the objective-node refinement feature (contracts.md §8.67):
// `installObjectiveRefinementBindings` owns every refinement registration — the ONE model-facing
// `objective_refinement_draft` tool, the warm `/objective-refine` entry, the human failsafe
// `/objective-refinement-save`, and the refinement context hook pair; `runRefinementReviewV1` is
// the `plan_review` refinement arm the stage dispatcher routes to; `importRefinementContextOnClaim`
// is the cold claim's one-time context import. The feature logic lives in
// `authoring/refinement/`; this module decodes at the tool/command boundary, builds the
// cold-door backend / worker / gate adapters, constructs the warm-door Result envelopes, and
// places the feature-owned prose units in Pi fields.
//
// Isolation posture: a refinement session never creates a plan, claims a node, links a plan-ref,
// changes node/objective state or provisions a checkout. There is NO `objective_refinement_save`
// tool — the two persistence paths are the APPROVED `plan_review` arm and the human command,
// both through the shared save seam over the `perk objective refinement-save` worker.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  importColdRefinementContext,
  importRefinementContext,
  REFINE_STAGE,
  REFINEMENT_CONTEXT_ARTIFACT,
  type RefinementContextRead,
  validateContextTransfer,
} from "../../authoring/refinement/context.ts";
import {
  REFINEMENT_DRAFT_ARTIFACT,
  renderRefinementDraft,
  resumeRefinementDraft,
  reviseRefinementDraft,
} from "../../authoring/refinement/draft.ts";
import {
  REFINEMENT_CONTEXT_TYPE,
  REFINEMENT_DRAFT_TOOL_GUIDELINES,
  REFINEMENT_MARKER,
  refinementContextContent,
  refinementGuidance,
  refinementStageRefusal,
} from "../../authoring/refinement/prose.ts";
import {
  completeRefinementReview,
  type RefinementDraftReviewer,
  type RefinementReviewOutcome,
  type ReviewRefinementResult,
} from "../../authoring/refinement/review.ts";
import {
  type RefinementBackend,
  type RefinementBackendSaveResult,
  refinementApprovalSave,
  reviewedPairOf,
} from "../../authoring/refinement/save.ts";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import {
  captureDraftReviewBinding,
  changedTargetComponents,
  targetDriftDetail,
} from "../../session/draftReviewBinding.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import {
  type Handoff,
  handoffPath,
  isSafeRunId,
  readHandoff,
  runScratchDir,
} from "../../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  runColdDoor,
  stringField,
  stringListField,
} from "../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { loadPerkConfig } from "../../substrate/config.ts";
import { failFor, ok, type Result } from "../../substrate/result.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { paramsOf, stringParam } from "../../substrate/toolParams.ts";
import {
  type BranchEntry,
  branchOf,
  rebuildWorkflowState,
  type WorkflowState,
} from "../../substrate/workflowState.ts";
import { report } from "../../surfaces/report.ts";
import { installInjectedContext } from "./contextInjection.ts";
import {
  captureDraftReviewRefusal,
  type DraftReviewConfirmedFacts,
  type DraftReviewRuntime,
  type DraftReviewStop,
  draftReviewCompletionResult,
  draftReviewMutationRefusal,
  draftReviewMutationValue,
  draftReviewRefusalResult,
  type RegisteredDraftReviewBridge,
} from "./draftReviewActivation.ts";
import type { DraftReviewCapability } from "./draftReviewDecisions.ts";
import {
  boundRefinementSaveDeps,
  mutationRefinementSaveDeps,
  type RefinementSaveDiagnostics,
} from "./draftReviewEffects.ts";
import { hasDirectEditsHeading } from "./providers/plannotator.ts";
import { isPlannotatorPlanSelected } from "./providers/selection.ts";
import {
  approvedSubjectSaveResult,
  type ReviewOutcome,
  type ReviewSubject,
  runFirstPartyReview,
  skipResult,
  subjectReviewOutcomeResult,
  type ToolResult,
  verdictsFor,
} from "./review.ts";

const SCOPE_REFINE = "objective-refine";
const SCOPE_SAVE = "objective-refinement-save";

// ------------------------------------------------------------------- the tool-boundary decode

/** Decode the `objective_refinement_draft` params: exactly `{ markdown: string }` (strict). */
export function decodeRefinementDraftParams(params: unknown): { markdown: string } | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const markdown = stringParam(p, "markdown");
  if (markdown === null || markdown === undefined) return null;
  return { markdown };
}

// ----------------------------------------------------------------- the command-args decode

export type RefineCommandArgs =
  | { ok: true; objective: string | null; node: string | null }
  | { ok: false; problem: string };

/**
 * Parse `/objective-refine [objective] [--node ID | --node=ID]`: at most one positional (an
 * opaque objective id, `#` tolerated), at most one `--node` with a nonblank value, nothing else.
 * Every extra/duplicate/missing-value shape refuses (never a silent default). Pure.
 */
export function parseRefineCommandArgs(args: string): RefineCommandArgs {
  const tokens = args
    .trim()
    .split(/\s+/)
    .filter((t) => t.length > 0);
  let objective: string | null = null;
  let node: string | null = null;
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i] as string;
    if (token === "--node" || token.startsWith("--node=")) {
      if (node !== null) return { ok: false, problem: "--node may be given at most once" };
      const value = token === "--node" ? tokens[++i] : token.slice("--node=".length);
      if (value === undefined || value.trim() === "" || value.startsWith("--"))
        return { ok: false, problem: "--node needs a node id (e.g. --node 2.3)" };
      node = value;
      continue;
    }
    if (token.startsWith("-")) return { ok: false, problem: `unknown option ${token}` };
    if (objective !== null) return { ok: false, problem: `unexpected extra argument ${token}` };
    const id = token.replace(/^#/, "");
    if (id === "") return { ok: false, problem: "the objective id must not be blank" };
    objective = id;
  }
  return { ok: true, objective, node };
}

// ------------------------------------------------------------------- the warm admission

/** The plan-graph stages a launch handoff marks a session as plan-bearing with. */
const PLAN_BEARING_STAGES: readonly string[] = [
  "plan",
  "objective-plan",
  "save",
  "implement",
  "submit",
  "address",
  "land",
  "learn",
];

export type WarmRefinementAdmission =
  | { ok: true; runId: string; activeObjective: string | null; alreadyRefining: boolean }
  | { ok: false; code: "bad_state" | "bound_session"; problem: string };

function isNonblankString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

/**
 * Decide whether an existing session may enter refinement (contracts.md §8.67's warm
 * admission), read STRICTLY over the rebuilt state + the run's launch handoff:
 *  - an unsafe/missing run identity, a malformed claim / plan-ref / stage, or an unreadable
 *    handoff → `bad_state` (never treated as absence);
 *  - a sound active plan-ref, a planning claim, or a plan-bearing launch handoff (a plan-graph
 *    stage, a planning link or an adoption source) → `bound_session` — nothing is cleared,
 *    suspended or restored;
 *  - otherwise admitted; `alreadyRefining` marks an explicit re-entry (a new grounding pass).
 * The cached root plan-ref selector is never consulted. Pure.
 */
export function decideWarmRefinementAdmission(
  state: WorkflowState,
  handoff:
    | { status: "absent" }
    | { status: "present"; handoff: Handoff }
    | { status: "unreadable" },
): WarmRefinementAdmission {
  const bad = (problem: string): WarmRefinementAdmission => ({
    ok: false,
    code: "bad_state",
    problem,
  });
  const bound = (problem: string): WarmRefinementAdmission => ({
    ok: false,
    code: "bound_session",
    problem,
  });
  const runId = state.run_id;
  if (typeof runId !== "string" || !isSafeRunId(runId)) return bad("no safe session run identity");
  const claim = state.objective_node_claim;
  if (claim !== undefined && claim !== null) {
    if (
      typeof claim !== "object" ||
      Array.isArray(claim) ||
      !isNonblankString((claim as { objective?: unknown }).objective) ||
      !isNonblankString((claim as { node?: unknown }).node)
    )
      return bad("the session's objective_node_claim is malformed");
    return bound(
      `this session carries a planning claim (objective ${(claim as { objective: string }).objective} node ${(claim as { node: string }).node})`,
    );
  }
  const ref = state.active_plan_ref;
  if (ref !== undefined && ref !== null) {
    if (
      typeof ref !== "object" ||
      Array.isArray(ref) ||
      !isNonblankString((ref as { provider?: unknown }).provider) ||
      !isNonblankString((ref as { pr_id?: unknown }).pr_id)
    )
      return bad("the session's active_plan_ref is malformed");
    return bound(
      `this session is bound to plan ${(ref as { provider: string }).provider}:${(ref as { pr_id: string }).pr_id}`,
    );
  }
  const stage = state.stage;
  if (stage !== undefined && stage !== null && typeof stage !== "string")
    return bad("the session's stage is malformed");
  if (handoff.status === "unreadable") return bad("the run's launch handoff is unreadable");
  if (handoff.status === "present") {
    const h = handoff.handoff;
    if (h.run_id !== runId) return bad("the run's launch handoff names another run");
    if (isNonblankString(h.objective_id) || isNonblankString(h.node_id))
      return bound("this session was launched with a planning link");
    if (isNonblankString(h.adopt_from))
      return bound("this session was launched as a plan adoption");
    if (typeof h.stage === "string" && PLAN_BEARING_STAGES.includes(h.stage))
      return bound(`this session was launched as a ${h.stage} session`);
  }
  if (typeof stage === "string" && PLAN_BEARING_STAGES.includes(stage))
    return bound(`this session is a ${stage} session`);
  const activeObjective = state.active_objective;
  return {
    ok: true,
    runId,
    activeObjective: isNonblankString(activeObjective) ? activeObjective : null,
    alreadyRefining: stage === REFINE_STAGE,
  };
}

/** Read the run's handoff strictly: ENOENT is `absent`; any other failure is `unreadable`. */
function readHandoffStrict(
  cwd: string,
  runId: string,
): { status: "absent" } | { status: "present"; handoff: Handoff } | { status: "unreadable" } {
  let raw: string;
  try {
    raw = readFileSync(handoffPath(cwd, runId), "utf8");
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT")
      return { status: "absent" };
    return { status: "unreadable" };
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
      return { status: "unreadable" };
    const h = parsed as Record<string, unknown>;
    if (typeof h.run_id !== "string") return { status: "unreadable" };
    return { status: "present", handoff: h as unknown as Handoff };
  } catch {
    return { status: "unreadable" };
  }
}

// ---------------------------------------------------------------- the cold-door adapters

/** The decoded `perk objective refine-context --json` envelope slice. */
interface RefineContextPayload {
  contextJson: string;
  contextDigest: string;
}

function decodeRefineContext(payload: ColdJson): RefineContextPayload | null {
  const contextJson = stringField(payload, "context_json");
  const contextDigest = stringField(payload, "context_digest");
  if (contextJson === undefined || contextDigest === undefined) return null;
  return { contextJson, contextDigest };
}

/**
 * The warm context worker: `perk objective refine-context <objective> [--node ID] --run-id RID
 * --json` — the context is a JSON STRING inside the envelope (never re-encoded here).
 */
async function fetchRefinementContext(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  req: { objective: string; node: string | null; runId: string },
): Promise<
  | { ok: true; contextJson: string; contextDigest: string }
  | { ok: false; message: string; errorType: string }
> {
  const args = ["objective", "refine-context", req.objective];
  if (req.node !== null) args.push("--node", req.node);
  args.push("--run-id", req.runId, "--json");
  const r = await runColdDoor<RefineContextPayload>(pi, ctx, args, {
    label: "perk objective refine-context",
    decode: decodeRefineContext,
  });
  if (!r.ok) return { ok: false, message: r.message, errorType: r.errorType };
  return { ok: true, contextJson: r.data.contextJson, contextDigest: r.data.contextDigest };
}

/** The decoded `perk objective refinement-save --json` success payload. */
interface RefinementSavePayload {
  commentId: string;
  carrierUrl: string;
  carrierIdentifier: string;
  objectiveId: string;
  objectiveRunId: string;
  nodeId: string;
  bodyDigest: string;
  savedAt: string;
  authoredAt: string;
}

function decodeRefinementSave(payload: ColdJson): RefinementSavePayload | null {
  const fields = [
    "comment_id",
    "carrier_url",
    "carrier_identifier",
    "objective_id",
    "objective_run_id",
    "node_id",
    "body_digest",
    "saved_at",
    "authored_at",
  ] as const;
  const values: Record<string, string> = {};
  for (const key of fields) {
    const value = stringField(payload, key);
    if (value === undefined) return null;
    values[key] = value;
  }
  return {
    commentId: values.comment_id as string,
    carrierUrl: values.carrier_url as string,
    carrierIdentifier: values.carrier_identifier as string,
    objectiveId: values.objective_id as string,
    objectiveRunId: values.objective_run_id as string,
    nodeId: values.node_id as string,
    bodyDigest: values.body_digest as string,
    savedAt: values.saved_at as string,
    authoredAt: values.authored_at as string,
  };
}

/**
 * The production `RefinementBackend` over the Python worker (`perk objective refinement-save
 * --run-id RID --json` via the shared cold-door client; the EXACT draft bytes ride the
 * run-scratch `--draft-file` channel). The worker reads the bound context from the run's
 * session data itself — no caller-supplied context path, target or expectation. Failures keep
 * the worker's typed diagnostics (`write_attempted`, `comment_ids`) beside the message.
 */
export function coldDoorRefinementBackend(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
): RefinementBackend {
  return {
    async save(req) {
      const r = await runColdDoor<RefinementSavePayload>(
        pi,
        ctx,
        ["objective", "refinement-save", "--run-id", req.runId, "--json"],
        {
          label: "perk objective refinement-save",
          decode: decodeRefinementSave,
          stdin: {
            flag: "--draft-file",
            content: req.draftRaw,
            filename: REFINEMENT_DRAFT_ARTIFACT,
          },
        },
      );
      if (!r.ok) {
        const attempted =
          r.payload === undefined ? undefined : booleanField(r.payload, "write_attempted");
        return {
          status: "failed",
          message: r.message,
          errorType: r.errorType,
          writeAttempted: attempted ?? null,
          commentIds: r.payload === undefined ? [] : stringListField(r.payload, "comment_ids"),
        };
      }
      const d = r.data;
      return {
        status: "saved",
        commentId: d.commentId,
        carrierUrl: d.carrierUrl,
        carrierIdentifier: d.carrierIdentifier,
        objectiveId: d.objectiveId,
        objectiveRunId: d.objectiveRunId,
        nodeId: d.nodeId,
        bodyDigest: d.bodyDigest,
        savedAt: d.savedAt,
        authoredAt: d.authoredAt,
      };
    },
  };
}

// ------------------------------------------------------------------------- result envelopes

/** The ok-arm fields of a verified refinement save (the structured `details` surface). */
export interface RefinementSaveOk {
  refinement: {
    comment_id: string;
    carrier_url: string;
    carrier_identifier: string;
    objective_id: string;
    objective_run_id: string;
    node_id: string;
    body_digest: string;
    saved_at: string;
    authored_at: string;
  };
  advisory: true;
}

export type RefinementSaveResult = Result<
  RefinementSaveOk,
  { write_attempted: boolean | null; comment_ids: string[] }
>;

/**
 * Render a backend save outcome as the warm-door Result envelope — the ONE result-construction
 * site for every refinement save surface (review arm + human command). A verified save says
 * ADVISORY content — not an executable plan — was saved and terminates; a failure reports
 * through `failFor` with the worker's diagnostics retained (never "nothing saved", never a
 * blind-retry prescription).
 */
export function refinementSaveResultOf(
  ctx: ExtensionContext,
  save: RefinementBackendSaveResult,
): RefinementSaveResult {
  if (save.status === "failed") {
    return failFor<{ write_attempted: boolean | null; comment_ids: string[] }>(ctx, SCOPE_SAVE)(
      save.message,
      save.errorType,
      {
        write_attempted: save.writeAttempted,
        comment_ids: save.commentIds,
      },
    );
  }
  return ok(
    `Saved refinement for objective ${save.objectiveId} node ${save.nodeId} → comment ` +
      `${save.commentId} on ${save.carrierIdentifier} (${save.carrierUrl}); body digest ` +
      `${save.bodyDigest}; saved at ${save.savedAt}.\n` +
      "ADVISORY content — not an executable plan — was saved: no plan was created, no node was " +
      "claimed, and no node/objective state changed.",
    {
      refinement: {
        comment_id: save.commentId,
        carrier_url: save.carrierUrl,
        carrier_identifier: save.carrierIdentifier,
        objective_id: save.objectiveId,
        objective_run_id: save.objectiveRunId,
        node_id: save.nodeId,
        body_digest: save.bodyDigest,
        saved_at: save.savedAt,
        authored_at: save.authoredAt,
      },
      advisory: true,
    },
    { terminate: true },
  );
}

// ------------------------------------------------------------------------- adapter plumbing

function openSession(pi: ExtensionAPI, ctx: ExtensionContext): WorkflowSession {
  return openBranchWorkflowSession(pi, ctx);
}

function gateFor(gating: ToolGating, ctx: ExtensionContext): ApprovalGate {
  return { isActive: () => gating.isActive(), exit: () => gating.exit(ctx) };
}

/** Whether the branch is a refinement session (stage match; the gate is checked separately). */
export function isRefinementSession(branch: readonly BranchEntry[]): boolean {
  return rebuildWorkflowState(branch).stage === REFINE_STAGE;
}

function inRefinementStage(ctx: ExtensionContext): boolean {
  try {
    return isRefinementSession(branchOf(ctx));
  } catch {
    return false;
  }
}

/**
 * The cold claim's one-time context import (called from `session_start` right after a
 * successful claim): reads the consumed handoff back for its namespaced block, then imports the
 * fixed run-scratch transfer. A refusal is reported loudly; the session stays gated and no
 * draft can be written until a grounding pass supplies a valid context. Never throws.
 */
export function importRefinementContextOnClaim(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  claim: { runId: string; stage: string | undefined },
): void {
  if (claim.stage !== REFINE_STAGE) return;
  try {
    const handoff = readHandoff(ctx.cwd, claim.runId);
    if (handoff === null) {
      report(
        ctx,
        SCOPE_REFINE,
        "error",
        "context import refused — the run's handoff is unreadable",
        {
          alsoLog: true,
        },
      );
      return;
    }
    const transferPath = join(runScratchDir(ctx.cwd, claim.runId), REFINEMENT_CONTEXT_ARTIFACT);
    const imported = importColdRefinementContext(
      openSession(pi, ctx),
      { runId: claim.runId, stage: claim.stage, handoff },
      {
        readTransfer() {
          try {
            // Fatal decoding: malformed UTF-8 is a refusal, never a silent U+FFFD substitution.
            return new TextDecoder("utf-8", { fatal: true }).decode(readFileSync(transferPath));
          } catch (error) {
            if (
              typeof error === "object" &&
              error !== null &&
              "code" in error &&
              error.code === "ENOENT"
            )
              return null;
            throw error;
          }
        },
      },
    );
    if (imported.status === "refused") {
      report(ctx, SCOPE_REFINE, "error", `context import refused — ${imported.problem}`, {
        alsoLog: true,
      });
    }
  } catch (error) {
    report(ctx, SCOPE_REFINE, "error", `context import failed — ${String(error)}`, {
      alsoLog: true,
    });
  }
}

// ------------------------------------------------------------------------------ the installer

/**
 * Install every refinement Pi binding: the refinement context hook pair, the
 * `objective_refinement_draft` tool, the warm `/objective-refine` entry and the human
 * `/objective-refinement-save` failsafe. Inert outside refinement sessions; never throws.
 */
export function installObjectiveRefinementBindings(
  pi: ExtensionAPI,
  gating: ToolGating,
  reviews: DraftReviewRuntime,
): void {
  const isRefining = (branch: readonly BranchEntry[]) =>
    gating.isActive() && isRefinementSession(branch);
  installInjectedContext(pi, {
    customType: REFINEMENT_CONTEXT_TYPE,
    flavors: {
      [REFINEMENT_MARKER]: (ctx) => refinementContextContent(loadPerkConfig(ctx.cwd).planAuthoring),
    },
    select: (_ctx, branch) => (isRefining(branch) ? REFINEMENT_MARKER : null),
    live: (_ctx, branch) => isRefining(branch),
  });

  pi.registerTool({
    name: "objective_refinement_draft",
    label: "Refinement draft",
    description:
      "Write (or overwrite) the working objective-node refinement — the advisory Markdown — to " +
      "the session data dir, bound to this session's grounding context. The only sanctioned " +
      "write surface in a refinement session. NOT a save: an APPROVED plan_review, or the " +
      "human's /objective-refinement-save, persists the node's refinement comment.",
    promptSnippet:
      "Persist the working refinement Markdown to the session data dir (full rewrite, context-bound)",
    promptGuidelines: REFINEMENT_DRAFT_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["markdown"],
      properties: {
        markdown: {
          type: "string",
          description:
            "The full refinement Markdown: what the node must deliver, the prerequisites that " +
            "do not exist yet, the code seams as observed at capture time, the risks, and the " +
            "assumptions a later real plan must re-verify.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const fail = failFor(ctx, "objective-refinement-draft", "objective_refinement_draft");
      const decoded = decodeRefinementDraftParams(params);
      if (decoded === null)
        return fail("objective_refinement_draft needs { markdown: string }", "bad_input");
      // Independent of tool visibility: the draft writer only exists inside a refinement session.
      if (!inRefinementStage(ctx))
        return fail(
          "objective_refinement_draft is only available in an objective-refine session " +
            "(enter one with perk objective refine <objective> or /objective-refine)",
          "wrong_stage",
        );
      const mutation = reviews.mutate(
        ctx,
        "source-changed",
        (session) => reviseRefinementDraft(decoded, session),
        { draft: { subject: "refinement" } },
      );
      if (!mutation.ok) return draftReviewMutationRefusal(mutation);
      const revised = mutation.value;
      switch (revised.status) {
        case "revised":
        case "unchanged": {
          const c = revised.context.context;
          return ok(
            `Refinement draft written → ${revised.receipt.path} (${revised.receipt.digest}); ` +
              `bound to objective ${c.objective.id} node ${c.target.identity.node_id} ` +
              `(context ${revised.context.digest})`,
            {
              name: REFINEMENT_DRAFT_ARTIFACT,
              path: revised.receipt.path,
              digest: revised.receipt.digest,
              bytes: revised.bytes,
              run_id: revised.receipt.runId,
              context_digest: revised.context.digest,
              objective_id: c.objective.id,
              node_id: c.target.identity.node_id,
              unchanged: revised.status === "unchanged",
            },
          );
        }
        case "rejected":
          return fail(
            revised.problem,
            revised.reason === "blank_markdown"
              ? "invalid_input"
              : revised.reason === "no_identity"
                ? "no_run_id"
                : revised.reason === "no_context"
                  ? "refinement_context_missing"
                  : revised.reason === "context_refused"
                    ? "refinement_context_invalid"
                    : "write_failed",
          );
        case "unverified":
          return fail(revised.problem, "write_failed");
      }
    },
  });

  registerPerkCommand(pi, "objective-refine", {
    description:
      "Enter an objective-node refinement pass in this session: [objective] [--node ID] " +
      "(else the active objective; the first refinable future node). Read-only; Linear only.",
    handler: async (args, ctx) => {
      const warn = (message: string) => report(ctx, SCOPE_REFINE, "warning", message);
      const parsed = parseRefineCommandArgs(args ?? "");
      if (!parsed.ok) {
        warn(`${parsed.problem}. Usage: /objective-refine [objective] [--node ID]`);
        return;
      }
      if (!ctx.isIdle()) {
        warn("the model is running — wait for the turn to finish, then re-run /objective-refine");
        return;
      }
      const state = rebuildWorkflowState(branchOf(ctx));
      const runIdForHandoff = typeof state.run_id === "string" ? state.run_id : "";
      const admission = decideWarmRefinementAdmission(
        state,
        runIdForHandoff && isSafeRunId(runIdForHandoff)
          ? readHandoffStrict(ctx.cwd, runIdForHandoff)
          : { status: "absent" },
      );
      const objectiveHint = parsed.objective ?? "<objective>";
      if (!admission.ok) {
        warn(
          `${admission.problem} — refusing (${admission.code}). Start a fresh session with ` +
            `\`perk objective refine ${objectiveHint}${parsed.node ? ` --node ${parsed.node}` : ""}\`.`,
        );
        return;
      }
      const objective = parsed.objective ?? admission.activeObjective;
      if (objective === null) {
        warn(
          "no objective given and none active (objective_required). Use " +
            "`/objective-refine <objective> [--node ID]`.",
        );
        return;
      }
      report(
        ctx,
        SCOPE_REFINE,
        "info",
        `${objective}${parsed.node ? ` node ${parsed.node}` : ""}${admission.alreadyRefining ? " (new grounding pass)" : ""}`,
      );
      const fetched = await fetchRefinementContext(pi, ctx, {
        objective,
        node: parsed.node,
        runId: admission.runId,
      });
      if (!fetched.ok) {
        report(ctx, SCOPE_REFINE, "error", `${fetched.message} (${fetched.errorType})`, {
          alsoLog: true,
        });
        return;
      }
      const validated = validateContextTransfer(fetched.contextJson, {
        runId: admission.runId,
        expectedDigest: fetched.contextDigest,
      });
      if (!validated.ok) {
        report(
          ctx,
          SCOPE_REFINE,
          "error",
          `the prepared context is invalid — ${validated.problem} (refinement_context_invalid)`,
          { alsoLog: true },
        );
        return;
      }
      // Under #2256's mutation boundary: recheck the same run/admission against LIVE state,
      // persist the exact raw context, then the stage-only entry. Outstanding review eligibility
      // is invalidated by the boundary itself (a new grounding pass is a target change).
      type Entered =
        | { status: "entered" | "unchanged"; path: string; read: RefinementContextRead }
        | { status: "refused"; problem: string };
      const mutation = reviews.mutate(ctx, "target-changed", (session): Entered => {
        const live = rebuildWorkflowState(branchOf(ctx));
        const runId = typeof live.run_id === "string" ? live.run_id : "";
        const again = decideWarmRefinementAdmission(
          live,
          runId && isSafeRunId(runId) ? readHandoffStrict(ctx.cwd, runId) : { status: "absent" },
        );
        if (!again.ok) return { status: "refused", problem: `${again.problem} (${again.code})` };
        if (again.runId !== admission.runId)
          return { status: "refused", problem: "the session identity changed (bad_state)" };
        const imported = importRefinementContext(session, validated.read);
        if (imported.status === "rejected" || imported.status === "unverified")
          return {
            status: "refused",
            problem: `could not persist the context (${imported.problem})`,
          };
        const staged = session.apply({ kind: "enter-refinement-stage" });
        if (staged.status === "rejected" || staged.status === "unverified")
          return {
            status: "refused",
            problem:
              `the context was persisted but the stage entry failed (${staged.problem}) — the ` +
              "session is not in refinement; re-run /objective-refine",
          };
        return {
          status:
            imported.status === "unchanged" && staged.status === "unchanged"
              ? "unchanged"
              : "entered",
          path: imported.receipt.path,
          read: imported.read,
        };
      });
      if (!mutation.ok) {
        warn(draftReviewMutationRefusal(mutation).content[0]?.text ?? "Draft review stopped");
        return;
      }
      const entered = mutation.value;
      if (entered.status === "refused") {
        report(ctx, SCOPE_REFINE, "error", entered.problem, { alsoLog: true });
        return;
      }
      // Enter/re-scope the gate for the refinement stage (its own allowlist + mode flavor), then
      // drive the shared flow guidance. Failed setup above never reaches this point.
      if (!gating.isActive()) gating.enter(ctx);
      gating.syncFromState("read-only", REFINE_STAGE);
      const c = entered.read.context;
      report(
        ctx,
        SCOPE_REFINE,
        "info",
        `${entered.status === "unchanged" ? "context unchanged" : "context prepared"} for objective ` +
          `${c.objective.id} node ${c.target.identity.node_id} (${c.target.status}` +
          `${c.prior !== null ? "; re-refining a prior refinement" : ""}) → ${entered.path}; ` +
          "read-only ON — author with objective_refinement_draft, review with plan_review.",
      );
      pi.sendUserMessage(
        refinementGuidance(c, entered.path) + bindingSuffix(ctx.cwd, `stage:${REFINE_STAGE}`),
      );
    },
  });

  registerPerkCommand(pi, "objective-refinement-save", {
    description:
      "Save the current validated refinement draft as the node's refinement comment — the " +
      "human's explicit save gesture (no arguments; artifact-first; refinement sessions only).",
    handler: async (args, ctx) => {
      const warn = (message: string) => report(ctx, SCOPE_SAVE, "warning", message);
      if ((args ?? "").trim() !== "") {
        warn("/objective-refinement-save takes no arguments (invalid_input)");
        return;
      }
      if (!inRefinementStage(ctx)) {
        warn(
          "not an objective-refine session (wrong_stage) — nothing saved. Enter one with " +
            "`perk objective refine <objective>` or /objective-refine.",
        );
        return;
      }
      if (!ctx.isIdle()) {
        warn("the model is running (session_busy) — wait for the turn to finish, then re-run");
        return;
      }
      // The command IS the human authorization: the state table lives in the manual-save
      // mutation boundary (absent/consumed/invalidated → proceed; opening/pending → invalidated
      // first; dispatch/uncertain → refused). Inside it, the shared seam strict-resumes both
      // artifacts and saves the EXACT draft bytes; the gate exits only on a verified save.
      const facts: DraftReviewConfirmedFacts = {};
      const mutation = await reviews.mutateAsync(ctx, "manual-save", async (session) => {
        const outcome = await refinementApprovalSave(
          mutationRefinementSaveDeps(
            { session, backend: coldDoorRefinementBackend(pi, ctx), gate: gateFor(gating, ctx) },
            facts,
            "approval",
          ),
        );
        switch (outcome.status) {
          case "no-draft":
            report(
              ctx,
              SCOPE_SAVE,
              "error",
              "no working refinement draft — nothing saved. Write it with objective_refinement_draft " +
                "(the model's tool), then re-run /objective-refinement-save.",
            );
            return;
          case "no-context":
            report(
              ctx,
              SCOPE_SAVE,
              "error",
              "no refinement context in this session — nothing saved. Re-enter a grounding pass " +
                "with /objective-refine, rewrite the draft, then re-run.",
            );
            return;
          case "refused-draft":
            report(
              ctx,
              SCOPE_SAVE,
              "error",
              `the working refinement draft is invalid: ${outcome.problem} — nothing saved. ` +
                "Rewrite it with objective_refinement_draft, then re-run /objective-refinement-save.",
            );
            return;
          case "saved": {
            const result = refinementSaveResultOf(ctx, outcome.save);
            // One headline line: the verified facts AND the advisory statement stay visible.
            report(
              ctx,
              SCOPE_SAVE,
              "info",
              `manual human save (not a reviewer approval): ${(result.content[0]?.text ?? "saved").replace(/\n/g, " ")}`,
            );
            return;
          }
          case "save-failed": {
            const s = outcome.save;
            const diagnostics =
              `write_attempted=${s.writeAttempted === null ? "unknown" : String(s.writeAttempted)}` +
              (s.commentIds.length > 0 ? `; comment_ids=${s.commentIds.join(",")}` : "");
            report(
              ctx,
              SCOPE_SAVE,
              "error",
              `manual save FAILED (${s.errorType}): ${s.message} [${diagnostics}] — the session ` +
                "stays read-only; read the node's comments back and reconcile before another attempt.",
            );
            return;
          }
        }
      });
      if (!mutation.ok)
        warn(
          draftReviewMutationRefusal(mutation, facts).content[0]?.text ?? "Draft review stopped",
        );
    },
  });
}

// ------------------------------------------------------------------------ the review arm

const REFINEMENT_SUBJECT: ReviewSubject = {
  noun: "refinement",
  present: "the complete refinement to the user",
  presentUnavailable: "the complete refinement to the user",
  implementHereWhere: "on the refinement path",
  draftTool: "objective_refinement_draft",
  failsafeCmd: "/objective-refinement-save",
  detailsExtra: { subject: "refinement" },
  noSourceError: "no refinement draft resolved",
  saveDestination: "Linear (the node's refinement comment)",
};

const REFINEMENT_REVIEW_EDITOR_TITLE =
  "Refinement review (view only — edits are not saved) — Enter: continue to verdict · Esc: " +
  "skip · Ctrl+G: $EDITOR";

function noRefinementDraftResult(): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "no refinement draft to review — write the working refinement with " +
          "objective_refinement_draft, then call plan_review again.",
      },
    ],
    details: {
      ok: false,
      error: "no refinement draft to review — write it with objective_refinement_draft first",
      error_type: "no_refinement_draft",
      status: "skipped",
      reason: "no_refinement_draft",
      subject: "refinement",
    },
  };
}

function noRefinementContextResult(): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "no refinement context in this session — the working draft cannot be reviewed. " +
          "Ask the human to re-enter a grounding pass with /objective-refine, then rewrite the " +
          "draft with objective_refinement_draft and call plan_review again.",
      },
    ],
    details: {
      ok: false,
      error: "no refinement context — a grounding pass is required",
      error_type: "refinement_context_missing",
      status: "skipped",
      reason: "no_refinement_context",
      subject: "refinement",
    },
  };
}

/** Translate a review-door outcome into the feature's `RefinementReviewOutcome`. */
function refinementOutcomeOf(outcome: ReviewOutcome): RefinementReviewOutcome {
  switch (outcome.status) {
    case "completed": {
      const carried = {
        ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
        reviewId: outcome.reviewId,
      };
      if (outcome.approved) {
        if (outcome.feedback !== undefined && hasDirectEditsHeading(outcome.feedback))
          return { status: "approvedDirectEdits", feedback: outcome.feedback, ...carried };
        return { status: "approved", ...carried };
      }
      return { status: "denied", ...carried };
    }
    case "unavailable":
      return { status: "unavailable", warning: outcome.warning };
    case "aborted":
      return { status: "aborted" };
    case "dismissed":
    case "implement-here":
      return { status: "dismissed" };
  }
}

function firstPartyRefinementReviewer(ctx: ExtensionContext): RefinementDraftReviewer {
  return {
    async review(rendered, signal) {
      const fp = await runFirstPartyReview({
        ui: ctx.ui,
        plan: rendered,
        writeDraft: () => true,
        signal,
        editorTitle: REFINEMENT_REVIEW_EDITOR_TITLE,
        verdicts: verdictsFor(REFINEMENT_SUBJECT),
        viewOnly: true,
      });
      return refinementOutcomeOf(fp.outcome);
    },
  };
}

function completedOutcome(
  approved: boolean,
  carried: { feedback?: string; reviewId?: string },
): Extract<ReviewOutcome, { status: "completed" }> {
  return {
    status: "completed",
    approved,
    ...(carried.feedback !== undefined ? { feedback: carried.feedback } : {}),
    reviewId: carried.reviewId ?? "",
  };
}

/**
 * The `plan_review` refinement arm: headless soft-skip; the validated (draft, context) PAIR as
 * the sole review source (a well-typed `plan` param is ignored upstream); reviewer dispatch
 * (plannotator bridge with capability-fenced dispatch, or the first-party view-only editor);
 * outcome mapping through the shared subject machinery. An approval carrying Direct Edits
 * returns the NON-terminating revise round with nothing saved; a plain approval re-resumes the
 * pair through `refinementApprovalSave` (gate released only after the verified save).
 *
 * The first-party path fences its own wait: the reviewed pair (draft bytes + context digest)
 * and the routing binding are captured BEFORE the editor opens; after the verdict, under the
 * reacquired mutation exclusion, an approval saves only when the binding still matches and the
 * seam finds the SAME pair — a replacement written during the wait stops with nothing saved.
 * The plannotator path's capability performs the equivalent comparison itself; a worker
 * failure inside it is a conservative unresolved-dispatch stop whose typed diagnostics are
 * retained beside the stop (never a bypass, never a replay).
 */
export async function runRefinementReviewV1(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: RegisteredDraftReviewBridge,
  signal?: AbortSignal,
  toolCallId?: string,
): Promise<ToolResult> {
  if (!ctx.hasUI) return skipResult();
  const sig = signal ?? ctx.signal;
  const session = openSession(pi, ctx);
  if (isPlannotatorPlanSelected(ctx.cwd)) {
    if (sig?.aborted) return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, { status: "aborted" });
    const resumed = resumeRefinementDraft(session);
    if (resumed.kind === "absent") return noRefinementDraftResult();
    if (resumed.kind === "no-context") return noRefinementContextResult();
    if (resumed.kind === "refused" || resumed.kind === "mismatch")
      return renderRefinementReviewResult(ctx, {
        status: "refusedDraft",
        problem: resumed.problem,
      });
    if (!toolCallId?.trim() || typeof bridge.prepare !== "function")
      return draftReviewRefusalResult({
        status: "refused",
        code: "invalid-state",
        phase: "open",
        detail: "required tool identity or review safety dependency unavailable",
      });
    const prepared = bridge.prepare(ctx, undefined, sig);
    if (!prepared.ok) return draftReviewRefusalResult(prepared.refusal);
    const review = prepared.value;
    const diagnostics: RefinementSaveDiagnostics = {};
    try {
      const outcome = await bridge.review(
        review.snapshot.markdown,
        review.registration,
        review.signal,
      );
      if (outcome.status === "refused") return draftReviewRefusalResult(outcome);
      if (review.signal.aborted)
        return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, { status: "aborted" });
      if (outcome.status !== "completed")
        return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, outcome);
      const completion = await review.complete(outcome, {
        effect:
          outcome.approved &&
          !(outcome.feedback !== undefined && hasDirectEditsHeading(outcome.feedback))
            ? "save"
            : "revision",
        carrier: { kind: "tool", tool_call_id: toolCallId },
        execute: (capability) =>
          completeRefinementReviewV1(pi, ctx, gating, outcome, capability, diagnostics),
      });
      return withRefinementWorkerDiagnostics(draftReviewCompletionResult(completion), diagnostics);
    } finally {
      review.dispose();
    }
  }
  const reviewer = firstPartyRefinementReviewer(ctx);
  const facts: DraftReviewConfirmedFacts = {};
  const result = await captureDraftReviewRefusal(
    (async (): Promise<ReviewRefinementResult | DraftReviewStop> => {
      if (sig?.aborted) return { status: "aborted" as const };
      const resumed = resumeRefinementDraft(session);
      if (resumed.kind === "absent") return { status: "noDraft" as const };
      if (resumed.kind === "no-context") return { status: "noContext" as const };
      if (resumed.kind === "refused" || resumed.kind === "mismatch")
        return { status: "refusedDraft" as const, problem: resumed.problem };
      // Capture what the human will judge BEFORE display: the exact pair and the routing
      // binding (run, stage, config, environment, context artifact). A binding that cannot be
      // captured has no reviewable target.
      const reviewed = reviewedPairOf(resumed.pair);
      const bound = captureDraftReviewBinding(ctx.cwd, session);
      if (!bound.ok)
        return { status: "refused", code: bound.reason, phase: "open", detail: bound.detail };
      // Invalidate competing browser eligibility at entry; release exclusion for the human wait.
      draftReviewMutationValue(bridge.mutate(ctx, "first-party-review", () => undefined));
      const rendered = renderRefinementDraft(resumed.pair);
      const outcome = await reviewer.review(rendered, sig);
      if (sig?.aborted) return { status: "aborted" as const };
      // Reacquire exclusion. An approval saves only against the reviewed binding (compared
      // here) and the reviewed pair (compared by the seam) — never a replacement.
      return draftReviewMutationValue(
        await bridge.mutateAsync(
          ctx,
          "first-party-review",
          async (mutationSession): Promise<ReviewRefinementResult | DraftReviewStop> => {
            if (outcome.status === "approved") {
              const current = captureDraftReviewBinding(ctx.cwd, mutationSession);
              if (!current.ok)
                return {
                  status: "refused",
                  code: current.reason,
                  phase: "mutation",
                  detail: current.detail,
                };
              if (current.binding.subject !== bound.binding.subject)
                return {
                  status: "refused",
                  code: "subject-changed",
                  phase: "mutation",
                  detail: "the session's review subject changed during the refinement review",
                };
              if (current.binding.digest !== bound.binding.digest)
                return {
                  status: "refused",
                  code: "target-changed",
                  phase: "mutation",
                  detail:
                    "the refinement's routing binding (run, stage, config or grounding context) " +
                    "changed during the review — nothing was saved; call plan_review again; " +
                    targetDriftDetail({
                      checkpoint: "save",
                      reviewed: bound.binding.digest,
                      current: current.binding.digest,
                      changed: changedTargetComponents(
                        bound.binding.components,
                        current.binding.components,
                      ),
                    }),
                };
            }
            return completeRefinementReview(outcome, () =>
              refinementApprovalSave(
                mutationRefinementSaveDeps(
                  {
                    session: mutationSession,
                    backend: coldDoorRefinementBackend(pi, ctx),
                    gate: gateFor(gating, ctx),
                    reviewed,
                  },
                  facts,
                  "approval",
                ),
              ),
            );
          },
        ),
      );
    })(),
  );
  if (result.status === "refused") return draftReviewRefusalResult(result, facts);
  return renderRefinementReviewResult(ctx, result);
}

/**
 * A worker failure inside the capability-fenced save is a conservative unresolved-dispatch stop
 * (the capability saw no receipt); the worker's typed diagnostics are retained beside that stop
 * so the human reconciles from facts — which comment ids were observed and whether a write was
 * attempted — rather than from a bare refusal. They are DATA for reconciliation, never a retry
 * license.
 */
function withRefinementWorkerDiagnostics(
  result: ToolResult,
  diagnostics: RefinementSaveDiagnostics,
): ToolResult {
  const failure = diagnostics.failure;
  if (failure === undefined || result.details.ok !== false) return result;
  const attempted =
    failure.writeAttempted === null ? "unknown" : failure.writeAttempted ? "yes" : "no";
  const ids = failure.commentIds.length === 0 ? "none" : failure.commentIds.join(", ");
  return {
    ...result,
    content: [
      ...result.content,
      {
        type: "text",
        text:
          `Refinement worker diagnostics (${failure.errorType}): ${failure.message}. ` +
          `Write attempted: ${attempted}; refinement comment ids observed: ${ids}. Read the ` +
          "node's refinement comment back before any reconciliation; nothing here authorizes a retry.",
      },
    ],
    details: {
      ...result.details,
      worker_failure: {
        error_type: failure.errorType,
        message: failure.message,
        write_attempted: failure.writeAttempted,
        comment_ids: failure.commentIds,
      },
    },
  };
}

export function renderRefinementReviewResult(
  ctx: ExtensionContext,
  result: ReviewRefinementResult,
): ToolResult {
  switch (result.status) {
    case "noDraft":
      return noRefinementDraftResult();
    case "noContext":
      return noRefinementContextResult();
    case "refusedDraft":
      return {
        content: [
          {
            type: "text",
            text:
              `the working refinement draft is invalid: ${result.problem} — rewrite it with ` +
              "objective_refinement_draft, then call plan_review again.",
          },
        ],
        details: {
          ok: false,
          error: result.problem,
          error_type: "bad_state",
          status: "skipped",
          reason: "refinement_draft_refused",
          subject: "refinement",
        },
      };
    case "directEditsRevise":
      return {
        content: [
          {
            type: "text",
            text:
              "refinement APPROVED with direct browser edits — nothing was saved. Fold the " +
              "Markdown hunks below into one objective_refinement_draft rewrite; hunks against " +
              "the header (objective, node, carrier, pass time, checkout observation) are bound " +
              "metadata — they need a new grounding pass (/objective-refine), never fabricated " +
              `values. Then call plan_review again to confirm.\n\nReviewer feedback:\n${result.feedback}`,
          },
        ],
        details: {
          ok: true,
          status: "revise",
          reason: "direct_edits",
          approved: true,
          feedback: result.feedback,
          reviewId: result.reviewId,
          subject: "refinement",
        },
      };
    case "approvedSaved":
      return approvedSubjectSaveResult(REFINEMENT_SUBJECT, completedOutcome(true, result), {
        status: "saved",
        result: refinementSaveResultOf(ctx, result.save.save),
        gateExited: result.save.gateExited,
      });
    case "approvedSaveFailed":
      return approvedSubjectSaveResult(REFINEMENT_SUBJECT, completedOutcome(true, result), {
        status: "save-failed",
        result: refinementSaveResultOf(ctx, result.save.save),
        gateExited: false,
      });
    case "approvedNoDraft":
      return approvedSubjectSaveResult(REFINEMENT_SUBJECT, completedOutcome(true, result), {
        status: "no-source",
      });
    case "approvedRefusedDraft":
      return approvedSubjectSaveResult(REFINEMENT_SUBJECT, completedOutcome(true, result), {
        status: "refused-draft",
        problem: result.problem,
      });
    case "approvedSourceChanged": {
      const what =
        result.changed === "context"
          ? "grounding context was re-prepared"
          : "working draft was rewritten";
      return {
        content: [
          {
            type: "text",
            text:
              `refinement APPROVED by reviewer, but the ${what} after the reviewed version was ` +
              "shown — nothing was saved and the session stays read-only. An approval never " +
              "transfers to a replacement: call plan_review again over the current draft.",
          },
        ],
        details: {
          ok: false,
          status: "stale",
          reason: "source_changed",
          changed: result.changed,
          approved: true,
          ...(result.feedback !== undefined ? { feedback: result.feedback } : {}),
          ...(result.reviewId !== undefined ? { reviewId: result.reviewId } : {}),
          subject: "refinement",
        },
      };
    }
    case "denied":
      return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, completedOutcome(false, result));
    case "dismissed":
      return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, { status: "dismissed" });
    case "aborted":
      return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, { status: "aborted" });
    case "unavailable":
      return subjectReviewOutcomeResult(REFINEMENT_SUBJECT, {
        status: "unavailable",
        warning: result.warning,
      });
  }
}

/** Subject policy called only within verified dispatch (the bound, capability-fenced save). */
export async function completeRefinementReviewV1(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  outcome: Extract<ReviewOutcome, { status: "completed" }>,
  capability: DraftReviewCapability,
  diagnostics: RefinementSaveDiagnostics = {},
): Promise<ToolResult> {
  return renderRefinementReviewResult(
    ctx,
    await completeRefinementReview(refinementOutcomeOf(outcome), () =>
      refinementApprovalSave(
        boundRefinementSaveDeps(
          {
            session: openSession(pi, ctx),
            backend: coldDoorRefinementBackend(pi, ctx),
            gate: gateFor(gating, ctx),
          },
          capability,
          diagnostics,
        ),
      ),
    ),
  );
}

/** The refusal text the plan-graph surfaces render inside a refinement session. */
export { refinementStageRefusal };
