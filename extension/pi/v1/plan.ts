// The v1 Pi installer for the plan feature (module-contracts.md's named-installer shape):
// `installPlanBindings` owns EVERY plan registration — perk-owned plan mode (the `/plan`
// command, `Ctrl+Alt+P` shortcut, `--plan` flag, and the plan-authoring context hook pair, with
// the three-tier provider deferral), the `plan_draft`/`plan_save` tools, the `/plan-save` and
// `/implement-here` commands, and the `plan_review` registration — with baseline-exact
// registration metadata. The feature logic lives in `authoring/plan/`; this module decodes at
// the tool boundary, builds the provider/backend/gate adapters (`planSaveDepsFor` — the ONE
// production composition point every plan-save surface AND the review door consume), constructs
// the warm-door Result envelopes (the byte-stable message assembly), and places the
// feature-owned prose units in Pi fields.
//
// PLAN MODE (the toggle surface over the read-only gate): grounded in pi's official
// `examples/extensions/plan-mode/` recipe, but perk adopts ONLY the read-only authoring half —
// there is no in-session "execution mode" flip (perk separates plan from implement). The
// plan-authoring injection dedups on the COMPACTION-ACTIVE window (contracts §8.31 — the gist
// precedent): a live copy suppresses re-injection; compaction dropping it re-injects next turn.
//
// REGISTRATION-TIME DEFERRAL, THREE-TIER. The plan-mode surface resolves the plan provider id
// once at install time and branches:
//   - `perk-plan` (and the fail-safe error path) → register EVERYTHING (the default path is the
//     hard guarantee, zero behavior change).
//   - `plannotator-plan` (AUGMENT posture) → register everything EXCEPT the `--plan` flag, the
//     `Ctrl+Alt+P` shortcut, and the `--plan` session_start handler: `@plannotator/pi-extension`
//     also registers that flag + shortcut, and duplicate flag/shortcut registration is the known
//     potentially-fatal Pi behavior — plannotator owns `--plan`/`Ctrl+Alt+P` exclusively while
//     perk keeps `/plan`, the authoring injection, and the read-only gate (plannotator augments
//     perk's plan flow via the providers/plannotator.ts `plan_review` bridge; it does not
//     replace it).
//   - any other foreign id (tombell, REPLACE posture) → register NOTHING of the mode surface;
//     the foreign package owns `/plan`/`Ctrl+Alt+P`/`--plan` unambiguously (Pi suffixes
//     duplicate command names, so handler-time deferral alone is insufficient once the foreign
//     package is loaded).
//
// SEAM-SHARED SUBSTRATE. `savePlan`/the `plan_save` tool/`/plan-save`/the read-only gate
// are the produced-contract landing for the PLAN seam (`adapter-architecture.md` Invariant 1) —
// the adapter bridges a foreign plan surface *to* `plan_save`/`cache.plan-ref`/the gate, so
// they must stay always-registered. They do NOT defer when a foreign `[providers] plan` is
// selected — only perk's own authoring surface (the mode tier above) steps aside.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { GIST_AUTHOR_STAGE } from "../../authoring/gist/draft.ts";
import { PLAN_DRAFT_ARTIFACT, revisePlanDraft } from "../../authoring/plan/draft.ts";
import {
  PLAN_CONTEXT_TYPE,
  PLAN_DRAFT_TOOL_GUIDELINES,
  PLAN_MARKER,
  PLAN_REVIEW_TOOL_GUIDELINES,
  PLAN_SAVE_TOOL_GUIDELINES,
  planAuthoringContextContent,
} from "../../authoring/plan/prose.ts";
import {
  type ObjectiveNodeLink,
  type PlanBackend,
  planApprovalSave,
  type SavePlanOutcome,
  savePlan,
} from "../../authoring/plan/save.ts";
import {
  extractPlanMarkdown,
  type PlanSource,
  resolvePlanSource,
} from "../../authoring/plan/source.ts";
import { OBJECTIVE_AUTHOR_STAGE } from "../../factories/objectiveAuthor.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { PlanRef } from "../../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  nullableStringField,
  objectField,
  runColdDoor,
  stringField,
} from "../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { loadPerkConfig } from "../../substrate/config.ts";
// Re-resolved here (not imported from providers/selection.ts) would drift — import the probe
// and compare against the provider registry ids at install time.
import { PERK_PLAN_PROVIDER_ID, PLANNOTATOR_PLAN_PROVIDER_ID } from "../../substrate/providers.ts";
import { failFor, ok, type Result } from "../../substrate/result.ts";
import { captureSessionPointer } from "../../substrate/sessionPointers.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { idArrayParam, paramsOf, stringParam } from "../../substrate/toolParams.ts";
import {
  activeContextWindow,
  branchCarries,
  branchOf,
  readNodeClaim,
  rebuildWorkflowState,
} from "../../substrate/workflowState.ts";
import { report, type Severity } from "../../surfaces/report.ts";
// `Key` via the surfaces re-export (keybinding vocabulary, not rich UI) — keeps pi-tui imports
// structurally confined to the surfaces module (the surfacesGuard pi-tui import rule).
import { Key } from "../../surfaces/surfaces.ts";
import { generatePlanTitle } from "./planTitle.ts";
import {
  type ApprovalSaveOutcome,
  executePlanReview,
  implementHereExit,
  implementHereGuidance,
  type PlanReviewV1Deps,
} from "./planReview.ts";
import { createPlannotatorBridge } from "./providers/plannotator.ts";
import { resolvedPlanProviderId } from "./providers/selection.ts";
import type { WaveLaunch } from "./review.ts";

// ------------------------------------------------------------------- the tool-boundary decode

/**
 * Decode unknown `plan_draft` tool-call params (the tool-boundary seam). `plan` absent decodes to
 * `""` (so the core's `invalid_input` arm owns the empty-plan message); present-but-mistyped →
 * null (strict-fail `bad_input`). Decode-before-side-effect.
 */
export function decodePlanDraftParams(params: unknown): { plan: string } | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const plan = stringParam(p, "plan");
  if (plan === null) return null;
  return { plan: plan ?? "" };
}

/** The decoded `plan_save` tool params (snake_case, as the schema declares them). */
interface PlanSaveParams {
  plan?: string;
  title?: string;
  objective_id?: string;
  node_id?: string;
  consumed_learn?: string[];
}

/**
 * Decode unknown `plan_save` tool-call params (the tool-boundary seam). `plan` is
 * optional (the validated plan-draft artifact is preferred) — absent decodes to
 * `undefined`, but present-but-mistyped → null (strict-fail); the optional fields likewise.
 */
export function decodePlanSaveParams(params: unknown): PlanSaveParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const plan = stringParam(p, "plan");
  if (plan === null) return null;
  const title = stringParam(p, "title");
  const objectiveId = stringParam(p, "objective_id");
  const nodeId = stringParam(p, "node_id");
  // Opaque string ids (§8.21); numbers are coerced — the learn-docs guidance renders bare
  // numeric ids on GitHub, so the model may echo them un-quoted.
  const consumedLearn = idArrayParam(p, "consumed_learn");
  if (title === null || objectiveId === null || nodeId === null || consumedLearn === null) {
    return null;
  }
  return {
    plan: plan ?? undefined,
    title,
    objective_id: objectiveId,
    node_id: nodeId,
    consumed_learn: consumedLearn,
  };
}

// -------------------------------------------------------------- the cold-door backend adapter

/** The ok-arm fields — the `details` surface doubles as branch-safe persisted state. */
export interface PlanSaveOk {
  /** `issue.id` is the opaque string issue id (GitHub "42", Linear "ENG-123") — §8.21. */
  issue: { id: string; url: string };
  plan_ref: PlanRef;
  cached: boolean;
  existed: boolean | null;
  updated: boolean;
  objective_node: ObjectiveNodeLink | null;
  plan_source: PlanSource | null;
}

/** A tool result patch (AgentToolResult has no `isError`; failure is signaled via details.ok). */
export type SaveResult = Result<PlanSaveOk>;

/**
 * The decoded `perk plan save --json` payload slice the warm door consumes. Decode policy
 * (`docs/learned/workflow/cold-door-client.md`: strict iff appended to workflow-state): only
 * `plan_ref` is strict. The rendered `issue.id`/`url` are DERIVED from the strict ref — the cold
 * door constructs the ref from the issue (`pr_id == issue.id`, `url == issue.url`), so they are
 * byte-identical by construction; `existed` and `objective_node` are advisory.
 */
interface PlanSavePayload {
  issue: { id: string; url: string; existed: boolean | undefined };
  plan_ref: PlanRef;
  cached?: boolean;
  updated?: boolean;
  objective_node: ObjectiveNodeLink | null;
}

/**
 * Fully strict `plan_ref` decode — a half-formed ref appended to workflow-state would poison
 * `planRefsEqual` and every downstream consumer, so any miss → null → bad_output.
 */
function decodePlanRef(payload: ColdJson): PlanRef | null {
  const ref = objectField(payload, "plan_ref");
  if (ref === undefined) return null;
  const provider = stringField(ref, "provider");
  const prId = stringField(ref, "pr_id");
  const url = stringField(ref, "url");
  const labels = ref.labels;
  const objectiveId = nullableStringField(ref, "objective_id");
  if (
    provider === undefined ||
    prId === undefined ||
    url === undefined ||
    !Array.isArray(labels) ||
    !labels.every((l) => typeof l === "string") ||
    objectiveId === undefined
  ) {
    return null;
  }
  // `base` stays Python-owned for all behavior; carrying it keeps the workflow-state
  // `active_plan_ref` copy byte-consistent with the cold door's `--json` plan_ref. Parity-only +
  // lenient: a present null/string is carried, an absent/mistyped value is simply omitted (never a
  // decode failure — legacy plan-refs lack the field).
  const base = nullableStringField(ref, "base");
  return { provider, pr_id: prId, url, labels, objective_id: objectiveId, base };
}

/** Validate the optional `objective_node` sub-object; malformed → null (advisory, never fatal). */
function decodeObjectiveNode(payload: ColdJson): ObjectiveNodeLink | null {
  const node = objectField(payload, "objective_node");
  if (node === undefined) return null;
  const linked = booleanField(node, "linked");
  const name = nullableStringField(node, "node");
  const status = nullableStringField(node, "status");
  const error = nullableStringField(node, "error");
  if (linked === undefined || name === undefined || status === undefined || error === undefined) {
    return null;
  }
  return { linked, node: name, status, error };
}

/**
 * Narrow the `perk plan save --json` success payload. Strict ONLY on `plan_ref` (malformed →
 * bad_output — it is appended to workflow-state, where a half-formed ref would poison
 * `planRefsEqual`). The rendered issue id/url are derived from the strict ref instead of decoded
 * independently — the cold door builds the ref FROM the issue, so they are byte-identical by
 * construction; this makes any `issue` sub-object shape change (e.g. a `number`→`id`
 * rename under CLI↔extension version skew) skew-harmless. `existed` and
 * `objective_node` are advisory — the plan genuinely saved, so the success report must survive
 * them. With `plan_ref` the only strict field, `bad_output` is reachable only for a payload whose
 * persistence would corrupt workflow-state.
 */
function decodePlanSave(payload: ColdJson): PlanSavePayload | null {
  const ref = decodePlanRef(payload);
  if (ref === null) return null;
  const issue = objectField(payload, "issue");
  const existed = issue === undefined ? undefined : booleanField(issue, "existed");
  return {
    issue: { id: ref.pr_id, url: ref.url, existed },
    plan_ref: ref,
    cached: booleanField(payload, "cached"),
    updated: booleanField(payload, "updated"),
    objective_node: decodeObjectiveNode(payload),
  };
}

/**
 * The production `PlanBackend` over the Python cold door (`perk plan save --json` via the
 * shared cold-door client; the plan markdown rides the run-scratch stdin channel). Argv
 * assembly byte-identical to what the save always emitted; `runId: null` omits `--run-id`
 * (an identity-less save keeps working).
 */
function coldDoorPlanBackend(pi: ExtensionAPI, ctx: ExtensionContext): PlanBackend {
  return {
    async save(req) {
      const args = ["plan", "save", "--json"];
      if (req.runId !== null && req.runId !== "") args.push("--run-id", req.runId);
      // The resolved title (explicit or LLM-generated). When absent, the cold door derives it.
      if (req.title) args.push("--title", req.title);
      // The plan→objective link. The objective plan-factory passes the active objective
      // number; non-objective plans omit it (unchanged behavior).
      if (req.objectiveId) args.push("--objective-id", req.objectiveId);
      // The objective plan factory passes the node id alongside the objective id; the cold
      // door commits the node→plan backlink + `in_progress` advance atomically. Non-factory
      // plans omit it (unchanged behavior).
      if (req.nodeId) args.push("--node-id", req.nodeId);
      // The learn-docs factory passes the consumed perk:learn issue numbers; docs plans land
      // them (close + label perk:consolidated). Non-factory plans omit it (unchanged behavior).
      if (req.consumedLearn && req.consumedLearn.length > 0) {
        args.push("--consumed-learn", req.consumedLearn.join(","));
      }
      const r = await runColdDoor<PlanSavePayload>(pi, ctx, args, {
        label: "perk plan save",
        decode: decodePlanSave,
        stdin: { flag: "--plan-file", content: req.plan, filename: "plan.md" },
      });
      if (!r.ok) return { status: "failed", message: r.message, errorType: r.errorType };
      return {
        status: "saved",
        ref: r.data.plan_ref,
        existed: r.data.issue.existed ?? null,
        updated: r.data.updated ?? false,
        cached: r.data.cached ?? false,
        nodeLink: r.data.objective_node,
      };
    },
  };
}

// ---------------------------------------------------------------- the byte-stable rendering

/**
 * Render a feature `SavePlanOutcome` as the warm-door SaveResult — the ONE message-assembly
 * site every plan-save surface shares (tool, command, approval seam, review arm). Byte-stable:
 * verb/existed, the node-link suffix (all THREE outcomes — a failed advance is a non-fatal
 * sub-step but must be VISIBLE, the §8.3 "surfaced, never swallowed" intent), the source suffix
 * + param-mismatch flag. The outcome's `linkage`/`claimClear` seam results are deliberately NOT
 * rendered (append/read-back failures stay loud through the seam's report() path exactly as
 * always); a `failed` outcome reports through the `failFor` seam (same scope, same bytes).
 */
function renderSavePlanOutcome(ctx: ExtensionContext, save: SavePlanOutcome): SaveResult {
  if (save.status === "failed") {
    return failFor(ctx, "plan-save")(save.message, save.errorType);
  }
  const ref = save.ref;
  const verb = save.existed ? "Updated" : "Saved";
  const nodeLink = save.nodeLink;
  // Render all THREE node-link outcomes (the silent-partial-failure fix). Both surfaces render
  // content[0].text, so this one site fixes the tool path (the model relays it) and the command
  // path (the user sees the notify) at once.
  let linkSuffix = "";
  if (nodeLink?.linked === true) {
    linkSuffix = ` · linked objective node ${nodeLink.node} → in_progress`;
  } else if (nodeLink && nodeLink.linked === false) {
    linkSuffix = ` · ⚠ objective node ${nodeLink.node} NOT advanced — re-run /plan-save to retry${
      nodeLink.error ? ` (${nodeLink.error})` : ""
    }`;
  }
  // Surface NON-param sources in the message (param-path success messages stay
  // byte-stable); a differing ignored param is visibly flagged, never silent.
  let sourceSuffix = "";
  if (save.source === "plan-draft" || save.source === "transcript") {
    sourceSuffix =
      save.source === "plan-draft"
        ? " · plan source: plan-draft artifact"
        : " · plan source: transcript";
    if (save.paramMismatch) {
      sourceSuffix += " (⚠ differing plan param ignored — the validated artifact was saved)";
    }
  }
  return ok(
    `${verb} plan #${ref.pr_id} → ${ref.url}${sourceSuffix}${linkSuffix}`,
    {
      issue: { id: ref.pr_id, url: ref.url },
      plan_ref: ref,
      cached: save.cached,
      existed: save.existed,
      updated: save.updated,
      objective_node: nodeLink,
      plan_source: save.source,
    },
    { terminate: true },
  );
}

// ------------------------------------------------------------------------ the composition seam

/**
 * Build the full production dependency bag every plan-save surface consumes (the `plan_save`
 * tool, `/plan-save`, `approvalSave`, AND the `plan_review` registration — ONE composition
 * point, so no reverse edges and no duplicated composition): the branch-backed session, the
 * cold-door `PlanBackend`, the D1a gate slice over `gating`, the LLM title closure (binding
 * `ctx` + `ctx.signal` over `pi/v1/planTitle.ts` — via `substrate/structuredOutput`'s consumer),
 * the best-effort planning-pointer capture (§8.35 — no-ops on absent identity), the transcript
 * scrape thunk, and the byte-stable save rendering.
 */
export function planSaveDepsFor(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
): PlanReviewV1Deps {
  const session = openBranchWorkflowSession(pi, ctx);
  return {
    session,
    backend: coldDoorPlanBackend(pi, ctx),
    gate: { isActive: () => gating.isActive(), exit: () => gating.exit(ctx) },
    generateTitle: (plan) => generatePlanTitle(ctx, plan, ctx.signal),
    capturePlanningPointer: () => {
      // Capture the planning session pointer (contracts.md §8.35): this planning run self-keys
      // by its own run_id into the shared main checkout, so a later/other session can resolve
      // it cross-run. Best-effort + non-fatal (the carrier warns + returns false; a successful
      // save must stand — and it no-ops on a blank/absent run id, the identity-less arm).
      captureSessionPointer({
        cwd: ctx.cwd,
        runId: session.runId ?? "",
        klass: "planning",
        site: "main",
        // Optional-chained: best-effort, and some side-session fakes have no getSessionFile.
        sessionFile: ctx.sessionManager.getSessionFile?.(),
      });
    },
    transcript: () => extractPlanMarkdown(branchOf(ctx)),
    renderSave: (save) => renderSavePlanOutcome(ctx, save),
  };
}

/**
 * The shared approval→save orchestration seam, adapter-composed: an APPROVED review outcome
 * (the `plan_review` door — the plannotator bridge AND the first-party in-TUI editor review;
 * the `/plan-review-browser` door's decision routing) and the manual `/plan-save` failsafe all
 * run THIS. Flow: artifact-first plan resolution (the reviewed plan text is the explicit
 * fallback, the transcript scrape last) → `savePlan` (warm node-link recovery inside) → gate
 * exit on a successful save while read-only (the D1a pattern). The returned rendered
 * `SaveResult` keeps `terminate: true` for tool-path callers.
 */
export async function approvalSave(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { reviewedPlan?: string; title?: string } = {},
): Promise<ApprovalSaveOutcome> {
  const deps = planSaveDepsFor(pi, ctx, gating);
  const outcome = await planApprovalSave(deps, opts);
  if (outcome.status === "no-plan") return { status: "no-plan" };
  return {
    status: outcome.status,
    result: deps.renderSave(outcome.result),
    gateExited: outcome.gateExited,
  };
}

// ------------------------------------------------------------------------------ the installer

/**
 * Install every plan Pi binding. Hook order is the frozen composition sequence — the plan-mode
 * hook pair registers FIRST inside this installer (index.ts calls this at the slot the mode
 * surface always held; the tombell/plannotator adapters follow); every tool/command
 * registration is name-keyed and order-insensitive. `wave` is the injected wave-launch deps
 * (index.ts composes them from the door open cores); absent ⇒ the chooser never appears and
 * every review path is byte-stable.
 */
export function installPlanBindings(pi: ExtensionAPI, gating: ToolGating, wave?: WaveLaunch): void {
  installPlanMode(pi, gating);

  // ------------------------------------------------------------------- the plan_draft tool
  // The working-draft file tool: the first session-data PRODUCER and the narrow structural
  // read-only-gate carve-out (session data dir only). The tool takes NO path/name parameter —
  // the artifact name is the fixed constant and the bytes flow through the session seam, so
  // allowlisting its name in READ_ONLY_TOOLS (toolGating.ts) is safe.
  pi.registerTool({
    name: "plan_draft",
    label: "Plan draft",
    description:
      "Write (or overwrite) the working plan draft to the session data dir and record its " +
      "provenance pointer. The only sanctioned write surface while read-only. NOT a save — " +
      "plan_save//plan-save still persist the plan to GitHub.",
    promptSnippet: "Persist the working plan draft to the session data dir (full rewrite)",
    promptGuidelines: PLAN_DRAFT_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["plan"],
      properties: {
        plan: {
          type: "string",
          description: "The full working-plan markdown (rewrites the whole draft).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodePlanDraftParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "plan-draft",
          "plan_draft",
        )("plan_draft needs { plan: string } per the tool schema", "bad_input");
      }
      const fail = failFor(ctx, "plan-draft");
      const revised = revisePlanDraft(decoded, openBranchWorkflowSession(pi, ctx));
      switch (revised.status) {
        case "revised":
        case "unchanged":
          // A byte-identical rewrite short-circuits interior-side; the rendered result is
          // computed from identical content either way, so the surface stays byte-stable.
          return ok(`Plan draft written → ${revised.pointer.path} (${revised.pointer.digest})`, {
            name: PLAN_DRAFT_ARTIFACT,
            path: revised.pointer.path,
            digest: revised.pointer.digest,
            bytes: revised.bytes,
            run_id: revised.pointer.run_id,
          });
        case "rejected":
          return fail(
            revised.problem,
            revised.reason === "blank_plan"
              ? "invalid_input"
              : revised.reason === "no_identity"
                ? "no_run_id"
                : "write_failed",
          );
        case "unverified":
          return fail(revised.problem, "write_failed");
      }
    },
  });

  // ------------------------------------------------- the plan_save tool + /plan-save command
  pi.registerTool({
    name: "plan_save",
    label: "Save plan",
    description:
      "Persist the current plan to GitHub as the canonical perk plan and link this session to it. " +
      "Terminating: ends the turn on save. Call only when the plan is decision-complete.",
    promptSnippet: "Save the decision-complete plan to GitHub (terminates the turn)",
    promptGuidelines: PLAN_SAVE_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        plan: {
          type: "string",
          description:
            "Optional — the validated plan-draft.md artifact is preferred when present; this " +
            "param is the fallback for sessions that never wrote a draft (no line-number " +
            "references).",
        },
        title: {
          type: "string",
          description: "Optional issue title (defaults to the plan's first heading).",
        },
        objective_id: {
          type: "string",
          description:
            "Optional objective issue number to link this plan to (the objective plan factory " +
            "passes the active objective; omit for a standalone plan).",
        },
        node_id: {
          type: "string",
          description:
            "Objective node id to commit on save — the objective plan factory passes it with " +
            "`objective_id` (links the node and advances it to `in_progress`); omit for a " +
            "standalone plan.",
        },
        consumed_learn: {
          type: "array",
          items: { type: ["string", "number"] },
          description:
            "Optional perk:learn issue ids this docs plan consumes (the learned-docs factory " +
            "passes the gathered ids; omit for a standalone plan). /land closes + labels them.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodePlanSaveParams(params);
      if (decoded === null) {
        // The `label` arg matters: this handler-level closure renders "plan_save failed: …" while
        // the save's internal failFor(ctx, "plan-save") stays as-is.
        return failFor(
          ctx,
          "plan-save",
          "plan_save",
        )("plan_save needs { plan: string, … } per the tool schema", "bad_input");
      }
      const deps = planSaveDepsFor(pi, ctx, gating);
      // No read-only fail-fast here (D1a): the `plan_save` TOOL is structurally unreachable
      // while read-only (the read-only allowlist excludes it), so reaching this handler means
      // the gate is already off; the `/plan-save` COMMAND is allowed to run while read-only and
      // exits the gate on a successful save (the read-only → read-write boundary in one gesture).
      const src = resolvePlanSource(
        {
          draft: (() => {
            const read = deps.session.readArtifact(PLAN_DRAFT_ARTIFACT);
            return read.status === "found" ? read.content : null;
          })(),
          ...(decoded.plan !== undefined ? { explicit: decoded.plan } : {}),
          transcript: deps.transcript,
        },
        "save",
      );
      if (src === null) {
        return failFor(
          ctx,
          "plan-save",
          "plan_save",
        )(
          "no plan to save — write the working draft with plan_draft, or pass the plan parameter",
          "invalid_input",
        );
      }
      const outcome = await savePlan(
        {
          plan: src.plan,
          source: src.source,
          paramMismatch: src.paramMismatch,
          ...(decoded.title !== undefined ? { title: decoded.title } : {}),
          ...(decoded.objective_id !== undefined ? { objectiveId: decoded.objective_id } : {}),
          ...(decoded.node_id !== undefined ? { nodeId: decoded.node_id } : {}),
          ...(decoded.consumed_learn !== undefined
            ? { consumedLearn: decoded.consumed_learn }
            : {}),
        },
        deps,
      );
      return deps.renderSave(outcome);
    },
  });

  registerPerkCommand(pi, "plan-save", {
    description:
      "Save the latest proposed plan to GitHub — the manual failsafe for the approval→save flow " +
      "(the read-only → read-write boundary).",
    handler: async (args, ctx) => {
      const title = args.trim() || undefined;
      // The manual-failsafe invocation of the shared approval→save seam. Artifact-first
      // (no explicit param on the command path ⇒ paramMismatch is always false); the D1a gate exit
      // lives in the seam. (The tool path never exits the gate — it is structurally unreachable
      // while read-only.)
      const outcome = await approvalSave(pi, ctx, gating, { title });
      if (outcome.status === "no-plan") {
        report(
          ctx,
          "plan-save",
          "warning",
          "no plan to save; write a draft with plan_draft, propose a plan, or call the plan_save tool.",
          { alsoLog: true },
        );
        return;
      }
      // Severity reflects a failed objective-node advance: not-ok → error; saved-but-link-failed →
      // warning; otherwise info. A failed node-link never blocks the gate exit above (the plan was
      // saved) — but it MUST surface (the silent-partial-failure fix), in headless runs too.
      const result = outcome.result;
      const message = result.content[0]?.text ?? "plan-save done";
      const details = result.details as SaveResult["details"];
      const severity: Severity = !details.ok
        ? "error"
        : details.objective_node?.linked === false
          ? "warning"
          : "info";
      report(ctx, "plan-save", severity, message);
    },
  });

  // -------------------------------------------------------------- the /implement-here command
  // The sanctioned "implement here" exit from plan authoring (contracts.md §8.23): the
  // read-only gate comes off WITHOUT saving to the issue backend. Human-only by construction:
  // the two surfaces are the first-party review's 4th verdict (planReview.ts) and this command
  // — no model tool exists, so the model can never choose to skip the backend on its own (the
  // /btw posture). Deliberately OUTSIDE the PR lifecycle: no issue, no plan-ref, no branch —
  // /submit, /address, and /land all key off `cache.plan-ref` and stay inapplicable. The
  // plan-draft artifact is left untouched, so /plan-save can still create the canonical issue.
  registerPerkCommand(pi, "implement-here", {
    description:
      "Exit plan mode WITHOUT saving an issue and implement the current plan draft in this " +
      "session (the human-owned lightweight path).",
    handler: async (_args, ctx) => {
      // 1. Objective-node planning sessions must save: an implement-here would strand the node in
      //    `planning` (the claim is only cleared by a node-linked save or a non-planning
      //    transition). Gate untouched, nothing injected.
      if (readNodeClaim(ctx) !== null) {
        report(
          ctx,
          "implement-here",
          "warning",
          "this is an objective-node planning session — a node-linked plan must be saved " +
            "(the node advance and backlink depend on it). Use plan_review / /plan-save instead.",
        );
        return;
      }
      // 2. Nothing to exit: the command's meaning is *exiting plan mode without saving*.
      if (!gating.isActive()) {
        report(
          ctx,
          "implement-here",
          "warning",
          "not in plan mode — nothing to exit; just ask the model to implement.",
        );
        return;
      }
      // 3. Gate off → instruct the model. No inlined plan: the model authored the draft in its
      //    own context (the review-path edited-bytes inlining lives in planReview.ts).
      implementHereExit(ctx, gating);
      const message = implementHereGuidance(ctx.cwd, {});
      if (ctx.isIdle()) {
        pi.sendUserMessage(message);
      } else {
        pi.sendUserMessage(message, { deliverAs: "followUp" });
      }
    },
  });

  // ---------------------------------------------------------------- the plan_review tool
  // perk's universal review door. In READ_ONLY_TOOLS so it is callable INSIDE plan mode (the
  // whole point — review happens before the gate ever comes off). Fail-open everywhere:
  // headless / dismissed / backend-unavailable all soft-skip so authoring never wedges.
  const bridge = createPlannotatorBridge(pi.events);
  pi.registerTool({
    name: "plan_review",
    label: "Plan review",
    description:
      "Present the plan to the configured review surface — the Plannotator browser UI when " +
      "selected, otherwise perk's in-TUI editor review — and wait for the human decision. " +
      "Reviews the validated plan-draft artifact (keep it current with plan_draft); on approval " +
      "the plan is auto-saved and the turn terminates. On deny, revise per the returned " +
      "feedback, rewrite the draft with plan_draft, and call again. On the Plannotator surface " +
      "the human may first opt into a streamed reviewer wave — the call then returns immediately " +
      'with wave guidance (status "wave_launched") to follow in the same turn, and the browser ' +
      "decision routes back automatically. No-op skip when the session is headless or the " +
      "review is dismissed.",
    promptSnippet: "Request a human review of the working plan draft",
    promptGuidelines: PLAN_REVIEW_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        plan: {
          type: "string",
          description:
            "Optional — the validated plan-draft.md artifact is preferred when present; this " +
            "param is the fallback for sessions that never wrote a draft.",
        },
      },
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executePlanReview(
        pi,
        ctx,
        gating,
        bridge,
        planSaveDepsFor(pi, ctx, gating),
        params,
        signal,
        wave,
      );
    },
  });
}

// -------------------------------------------------------------------------------- plan mode

/**
 * The perk-owned plan-mode toggle surface over the read-only gate: idempotent enter/exit (the
 * gate tracks its own on/off transition), fail-safe-headless (notify when UI, else stderr), and
 * the plan-authoring context injection. Three-tier registration branch (see the module header):
 * full registration for the reference (fail-safe default), a PARTIAL vacate (skip only `--plan`
 * + `Ctrl+Alt+P`) under the augment-posture plannotator selection, and a full vacate under any
 * other foreign selection (tombell).
 */
function installPlanMode(pi: ExtensionAPI, gating: ToolGating): void {
  const providerId = resolvedPlanProviderId(process.cwd());
  const plannotatorSelected = providerId === PLANNOTATOR_PLAN_PROVIDER_ID;
  if (providerId !== PERK_PLAN_PROVIDER_ID && !plannotatorSelected) return;

  if (!plannotatorSelected) {
    pi.registerFlag("plan", {
      description: "Start in perk plan mode (read-only exploration + plan authoring).",
      type: "boolean",
      default: false,
    });
  }

  function announce(ctx: ExtensionContext, on: boolean): void {
    const message = on
      ? "plan mode ON — read-only exploration; author the plan, then review with plan_review (approval auto-saves; /plan-save is the manual failsafe)."
      : "plan mode OFF — full tool access restored.";
    report(ctx, "plan-mode", "info", message);
  }

  function toggle(ctx: ExtensionContext): void {
    if (gating.isActive()) {
      gating.exit(ctx);
      announce(ctx, false);
    } else {
      gating.enter(ctx);
      announce(ctx, true);
    }
  }

  registerPerkCommand(pi, "plan", {
    description: "Toggle perk plan mode (read-only exploration + plan authoring).",
    handler: async (_args, ctx) => toggle(ctx),
  });

  if (!plannotatorSelected) {
    pi.registerShortcut(Key.ctrlAlt("p"), {
      description: "Toggle perk plan mode",
      handler: async (ctx) => toggle(ctx),
    });

    // `--plan` cold start: enter read-only on session_start when the flag is set and the gate is
    // off. (index.ts's session_start already syncs the gate from the rebuilt `mode`; this layers
    // the flag on top for ad-hoc `pi --plan` interactive starts — the cold plan door drives
    // read-only via the handoff `mode`, not this flag.) Skipped under the plannotator selection
    // along with the flag itself (the flag no longer exists on perk's side).
    pi.on("session_start", async (_event, ctx) => {
      if (pi.getFlag("plan") === true && !gating.isActive()) {
        gating.enter(ctx);
      }
    });
  }

  // Inject the plan-authoring context while the read-only gate is active (display:false). The
  // exceptions: objective-author and gist-author sessions are ALSO read-only, but
  // objectiveAuthor.ts / the gist installer inject their own authoring contexts there — so plan
  // mode defers when the launched stage is either (the coupling break: plan-authoring context is
  // no longer keyed off the bare read-only gate).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!gating.isActive()) return;
    const branch = branchOf(ctx);
    const launchedStage = rebuildWorkflowState(branch).stage;
    if (launchedStage === OBJECTIVE_AUTHOR_STAGE || launchedStage === GIST_AUTHOR_STAGE) return;
    // Once-only over the COMPACTION-ACTIVE window (contracts §8.31): a live copy suppresses
    // re-injection; compaction dropping it from model context re-injects on the next turn even
    // though the historical entry still sits on the branch.
    if (branchCarries(activeContextWindow(branch), PLAN_MARKER)) return;
    return {
      message: {
        customType: PLAN_CONTEXT_TYPE,
        content: planAuthoringContextContent(loadPerkConfig(ctx.cwd).planAuthoring),
        display: false,
      },
    };
  });

  // Strip the stale plan-authoring marker from context when the gate is off (so it never lingers).
  pi.on("context", async (event) => {
    if (gating.isActive()) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === PLAN_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(PLAN_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(PLAN_MARKER),
          );
        }
        return true;
      }),
    };
  });
}
