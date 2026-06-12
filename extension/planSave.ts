// P1.T3 — the warm `/plan-save` door (turn-3 §5/§6). The in-session twin of the Python cold
// door (`perk plan-save`): a deterministic, terminating tool + command that WRAP T2's storage —
// they do NOT reimplement the GitHub write. `savePlan()` delegates to `perk plan-save --json` via
// the shared cold-door client (`runColdDoor`, Node 1.4 — the plan markdown rides the run-scratch
// stdin channel), then appends `active_plan_ref` so the live session is linked immediately
// (strict read-back, idempotent, headless-safe). Failures are loud-but-non-fatal — never throw.
//
// FILE-FIRST PLAN SOURCE (Node 2.2). Both surfaces resolve their plan through
// `resolvePlanSource`: the validated `plan-draft.md` artifact (`readSessionArtifact`,
// digest-validated, fail-open) wins; the explicit `plan` param (tool only, now optional) is the
// fallback for sessions that never wrote a draft; `extractPlanMarkdown` (the transcript scrape)
// is the universal last resort. A differing ignored param is surfaced, never silent.
//
// SEAM-SHARED SUBSTRATE (Node 2.2). `savePlan`/the `plan_save` tool/`/plan-save`/the read-only gate
// are the produced-contract landing for the PLAN seam (`adapter-architecture.md` Invariant 1) — the
// Node 2.3 adapter bridges a foreign plan surface *to* `plan_save`/`cache.plan-ref`/the gate, so
// they must stay always-registered. They do NOT defer when a foreign `[providers] plan` is selected
// — only perk's own authoring surface (`extension/planMode.ts`: `/plan`, `Ctrl+Alt+P`, `--plan`,
// the `perk:plan-context` injection) steps aside. Deferring this substrate would break Node 2.3.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PlanRef } from "./cache.ts";
import {
  booleanField,
  type ColdJson,
  nullableStringField,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "./coldDoor.ts";
import { PLAN_DRAFT_ARTIFACT } from "./planDraft.ts";
import { generatePlanTitle } from "./planTitle.ts";
import { report, type Severity } from "./report.ts";
import { failFor, ok, type Result } from "./result.ts";
import { readSessionArtifact, type SessionDataCtx } from "./sessionData.ts";
import type { ToolGating } from "./toolGating.ts";
import { numberArrayParam, paramsOf, stringParam } from "./toolParams.ts";
import {
  appendWorkflowState,
  type BranchEntry,
  branchOf,
  planRefsEqual,
  rebuildWorkflowState,
} from "./workflowState.ts";

/** The ok-arm fields (turn-3 D6) — the `details` surface doubles as branch-safe persisted state. */
export interface PlanSaveOk {
  issue: { number: number; url: string };
  plan_ref: PlanRef;
  cached: boolean;
  existed: boolean | null;
  updated: boolean;
  objective_node: ObjectiveNodeLink | null;
  plan_source: PlanSource | null;
}

/** The atomic objective node→plan commit surfaced by `perk plan-save` (P2.T10). */
export interface ObjectiveNodeLink {
  linked: boolean;
  node: string | null;
  status: string | null;
  error: string | null;
}

/** A tool result patch (AgentToolResult has no `isError`; failure is signaled via details.ok). */
export type SaveResult = Result<PlanSaveOk>;
export type PlanSaveDetails = SaveResult["details"];

/** The decoded `perk plan-save --json` payload slice the warm door consumes. */
interface PlanSavePayload {
  issue: { number: number; url: string; existed: boolean | undefined };
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
  return { provider, pr_id: prId, url, labels, objective_id: objectiveId };
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
 * Narrow the `perk plan-save --json` success payload. Strict on `issue` and (fully) on `plan_ref`
 * (malformed → bad_output); the advisory `objective_node` sub-object is validated but dropped when
 * malformed — the plan genuinely saved, so the success report must survive it.
 */
function decodePlanSave(payload: ColdJson): PlanSavePayload | null {
  const issue = objectField(payload, "issue");
  if (issue === undefined) return null;
  const number = numberField(issue, "number");
  const url = stringField(issue, "url");
  if (number === undefined || url === undefined) return null;
  const ref = decodePlanRef(payload);
  if (ref === null) return null;
  return {
    issue: { number, url, existed: booleanField(issue, "existed") },
    plan_ref: ref,
    cached: booleanField(payload, "cached"),
    updated: booleanField(payload, "updated"),
    objective_node: decodeObjectiveNode(payload),
  };
}

/**
 * Whether perk-owned plan mode is active — read from perk's OWN signal, the `read-only` `mode` of
 * `perk:workflow-state` (the structural tool gate, P2.T1). This retires the P1.T3b soft coupling to
 * `@tombell/pi-plan`'s `plan-mode-state` entry: perk now owns plan mode (`/plan` toggles
 * `gating.enter`/`exit`, which append `mode`), so the gate's own field is the source of truth.
 */
export function isPlanModeActive(branch: readonly BranchEntry[]): boolean {
  return rebuildWorkflowState(branch).mode === "read-only";
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) => {
      const b = block as { type?: string; text?: string };
      return b.type === "text" && typeof b.text === "string" ? b.text : "";
    })
    .filter(Boolean)
    .join("\n");
}

/**
 * Best-effort, deterministic: the whole text of the latest assistant message, or null. As of
 * Node 2.2 this is the universal fail-open transcript FALLBACK behind the validated plan-draft
 * artifact (see `resolvePlanSource`) — no longer the `/plan-save` command's primary plan source.
 * Inherently fragile (it cannot tell a clean plan from conversation): keep the working draft
 * current with `plan_draft` so the validated artifact wins. (There is no tag/marker convention to
 * extract — the borrowed plan-mode package emits no structured plan, only free-form prose.)
 */
export function extractPlanMarkdown(entries: readonly unknown[]): string | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i] as { type?: string; message?: { role?: string; content?: unknown } };
    if (entry.type !== "message" || entry.message?.role !== "assistant") continue;
    const text = textOf(entry.message.content).trim();
    if (!text) continue;
    return text;
  }
  return null;
}

/** Where the saved plan bytes came from (the Node 2.2 file-first resolution order). */
export type PlanSource = "plan-draft" | "param" | "transcript";

/**
 * The shared plan-source resolver (Node 2.2) both save surfaces use — and Node 2.3's
 * approval→save orchestration later. Resolution order: (1) the validated `plan-draft.md`
 * artifact (`readSessionArtifact`: digest-validated, fail-open — null on no run_id / no pointer
 * / fork run_id mismatch / missing file / digest mismatch); (2) a non-blank explicit param;
 * (3) the transcript scrape (`extractPlanMarkdown`); else null.
 *
 * `paramMismatch` is true iff the artifact won AND a non-blank explicit param was passed whose
 * trimmed bytes differ from the artifact's — surfaced by `savePlan`, never silently dropped and
 * never a hard-fail.
 */
export function resolvePlanSource(
  ctx: SessionDataCtx,
  explicit?: string,
): { plan: string; source: PlanSource; paramMismatch: boolean } | null {
  const artifact = readSessionArtifact(ctx, PLAN_DRAFT_ARTIFACT);
  if (artifact !== null && artifact.content.trim().length > 0) {
    const param = explicit?.trim() ?? "";
    return {
      plan: artifact.content,
      source: "plan-draft",
      paramMismatch: param.length > 0 && param !== artifact.content.trim(),
    };
  }
  if (explicit !== undefined && explicit.trim().length > 0) {
    return { plan: explicit, source: "param", paramMismatch: false };
  }
  const scraped = extractPlanMarkdown(branchOf(ctx));
  if (scraped !== null) return { plan: scraped, source: "transcript", paramMismatch: false };
  return null;
}

/**
 * The single save implementation both surfaces call. Delegates the GitHub write to the Python
 * cold door, then links the live session. Returns a soft result (never throws); failures set
 * `details.ok = false` and append no linkage.
 */
export async function savePlan(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: {
    plan: string;
    title?: string;
    objectiveId?: string;
    nodeId?: string;
    consumedLearn?: number[];
    /** The resolved plan source (Node 2.2) — surfaced in the message + details when non-param. */
    source?: PlanSource;
    /** A differing explicit param was ignored in favor of the artifact (visibly flagged). */
    paramMismatch?: boolean;
  },
): Promise<SaveResult> {
  const fail = failFor(ctx, "plan-save");

  const plan = opts.plan.trim();
  if (!plan) return fail("no plan markdown to save (propose a plan first)", "invalid_input");

  // #129: forward an explicit title (previously accepted but DROPPED), else best-effort generate
  // one via the session model. On any failure the cold door's `derive_title` fallback takes over.
  const explicit = opts.title?.trim();
  const title =
    explicit && explicit.length > 0
      ? explicit
      : ((await generatePlanTitle(ctx, plan, ctx.signal)) ?? undefined);

  const branch = (): BranchEntry[] => branchOf(ctx);
  // No read-only fail-fast here (D1a): the `plan_save` TOOL is structurally unreachable while
  // read-only (T1's allowlist excludes it), so reaching savePlan via the tool means the gate is
  // already off; the `/plan-save` COMMAND is allowed to run while read-only and the command handler
  // exits the gate on a successful save (the read-only → read-write boundary in one gesture).
  const runId = rebuildWorkflowState(branch()).run_id ?? "";

  const args = ["plan-save", "--json"];
  if (runId) args.push("--run-id", runId);
  // #129: the resolved title (explicit or LLM-generated). When absent, the cold door derives it.
  if (title) args.push("--title", title);
  // P2.T10: the plan→objective link. The objective plan-factory passes the active objective
  // number; non-objective plans omit it (unchanged behavior).
  if (opts.objectiveId) args.push("--objective-id", opts.objectiveId);
  // P2.T10: the objective plan factory passes the node id alongside the objective id; the cold
  // door commits the node→plan backlink + `in_progress` advance atomically. Non-factory plans
  // omit it (unchanged behavior).
  if (opts.nodeId) args.push("--node-id", opts.nodeId);
  // hop-2: the learn-docs factory passes the consumed perk:learn issue numbers; docs plans land
  // them (close + label perk:consolidated). Non-factory plans omit it (unchanged behavior).
  if (opts.consumedLearn && opts.consumedLearn.length > 0) {
    args.push("--consumed-learn", opts.consumedLearn.join(","));
  }
  const r = await runColdDoor<PlanSavePayload>(pi, ctx, args, {
    label: "perk plan-save",
    decode: decodePlanSave,
    stdin: { flag: "--plan-file", content: plan, filename: "plan.md" },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Link the live session (turn-3 D4): append iff the rebuilt ref differs, with a strict read-back.
  const ref = r.data.plan_ref;
  if (!planRefsEqual(rebuildWorkflowState(branch()).active_plan_ref ?? null, ref)) {
    appendWorkflowState(pi, ctx, {
      data: { active_plan_ref: ref },
      field: "active_plan_ref",
      expected: ref,
      scope: "plan-save",
      failure: `plan-ref read-back failed for ${ref.provider}:${ref.pr_id}`,
      equals: planRefsEqual,
    });
  }

  const verb = r.data.issue.existed ? "Updated" : "Saved";
  const nodeLink = r.data.objective_node;
  // Render all THREE node-link outcomes (the silent-partial-failure fix, #124). A failed advance
  // (`linked: false`) is a non-fatal sub-step — the plan genuinely saved — but it must be VISIBLE
  // (the §8.4 "warn + retriable" intent), not swallowed. Both surfaces render content[0].text, so
  // this one site fixes the tool path (the model relays it) and the command path (the user sees the
  // notify) at once.
  let linkSuffix = "";
  if (nodeLink?.linked === true) {
    linkSuffix = ` · linked objective node ${nodeLink.node} → in_progress`;
  } else if (nodeLink && nodeLink.linked === false) {
    linkSuffix = ` · ⚠ objective node ${nodeLink.node} NOT advanced — re-run /plan-save to retry${
      nodeLink.error ? ` (${nodeLink.error})` : ""
    }`;
  }
  // Node 2.2: surface NON-param sources in the message (param-path success messages stay
  // byte-stable); a differing ignored param is visibly flagged, never silent.
  let sourceSuffix = "";
  if (opts.source === "plan-draft" || opts.source === "transcript") {
    sourceSuffix =
      opts.source === "plan-draft"
        ? " · plan source: plan-draft artifact"
        : " · plan source: transcript";
    if (opts.paramMismatch) {
      sourceSuffix += " (⚠ differing plan param ignored — the validated artifact was saved)";
    }
  }
  return ok(
    `${verb} plan #${ref.pr_id} → ${ref.url}${sourceSuffix}${linkSuffix}`,
    {
      issue: { number: r.data.issue.number, url: r.data.issue.url },
      plan_ref: ref,
      cached: r.data.cached ?? false,
      existed: r.data.issue.existed ?? null,
      updated: r.data.updated ?? false,
      objective_node: nodeLink,
      plan_source: opts.source ?? null,
    },
    { terminate: true },
  );
}

/** The decoded `plan_save` tool params (snake_case, as the schema declares them). */
interface PlanSaveParams {
  plan?: string;
  title?: string;
  objective_id?: string;
  node_id?: string;
  consumed_learn?: number[];
}

/**
 * Decode unknown `plan_save` tool-call params (the tool-boundary seam — Node 3.2). `plan` is
 * optional (Node 2.2: the validated plan-draft artifact is preferred) — absent decodes to
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
  const consumedLearn = numberArrayParam(p, "consumed_learn");
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

const TOOL_GUIDELINES = [
  "Use plan_save only after the plan is decision-complete and the user has agreed; it creates the canonical GitHub plan and ends the turn.",
  "Keep the working draft current with plan_draft — the validated plan-draft artifact is what plan_save saves; the `plan` parameter is only a fallback when no draft exists. Never reference line numbers — use durable anchors (function names, behavioral descriptions, structural locations).",
  "Pass consumed_learn (the gathered perk:learn issue numbers) only from the learned-docs factory — it links the issues the docs plan consolidates so /land closes + labels them.",
  "When saving an objective-factory plan, pass BOTH objective_id and node_id — this links the node to the plan and advances it planning → in_progress (no separate backlink call).",
];

/** Register the warm door: the `plan_save` tool (canonical) + the `/plan-save` command twin. */
export function registerPlanSave(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "plan_save",
    label: "Save plan",
    description:
      "Persist the current plan to GitHub as the canonical perk plan and link this session to it. " +
      "Terminating: ends the turn on save. Call only when the plan is decision-complete.",
    promptSnippet: "Save the decision-complete plan to GitHub (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
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
          items: { type: "number" },
          description:
            "Optional perk:learn issue numbers this docs plan consumes (the learned-docs factory " +
            "passes the gathered numbers; omit for a standalone plan). /land closes + labels them.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodePlanSaveParams(params);
      if (decoded === null) {
        // The `label` arg matters: this handler-level closure renders "plan_save failed: …" while
        // savePlan's internal failFor(ctx, "plan-save") stays as-is.
        return failFor(
          ctx,
          "plan-save",
          "plan_save",
        )("plan_save needs { plan: string, … } per the tool schema", "bad_input");
      }
      const src = resolvePlanSource(ctx, decoded.plan);
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
      return savePlan(pi, ctx, {
        plan: src.plan,
        source: src.source,
        paramMismatch: src.paramMismatch,
        title: decoded.title,
        objectiveId: decoded.objective_id,
        nodeId: decoded.node_id,
        consumedLearn: decoded.consumed_learn,
      });
    },
  });

  pi.registerCommand("plan-save", {
    description: "Save the latest proposed plan to GitHub (the read-only → read-write boundary).",
    handler: async (args, ctx) => {
      // Node 2.2: artifact-first; the transcript scrape is the demoted universal fallback. No
      // explicit param on the command path ⇒ paramMismatch is always false.
      const src = resolvePlanSource(ctx);
      if (src === null) {
        report(
          ctx,
          "plan-save",
          "warning",
          "no plan to save; write a draft with plan_draft, propose a plan, or call the plan_save tool.",
          { alsoLog: true },
        );
        return;
      }
      const title = args.trim() || undefined;
      // D1a: the command may run while read-only; on a successful save, exit the gate so save marks
      // the read-only → read-write boundary in one gesture. (The tool path never does this — it is
      // structurally unreachable while read-only.)
      const wasReadOnly = gating.isActive();
      const result = await savePlan(pi, ctx, { plan: src.plan, title, source: src.source });
      if (result.details.ok && wasReadOnly) {
        gating.exit(ctx);
      }
      // Severity reflects a failed objective-node advance: not-ok → error; saved-but-link-failed →
      // warning; otherwise info. A failed node-link never blocks the gate exit above (the plan was
      // saved) — but it MUST surface (the #124 silent-partial-failure fix), in headless runs too.
      const message = result.content[0]?.text ?? "plan-save done";
      const severity: Severity = !result.details.ok
        ? "error"
        : result.details.objective_node?.linked === false
          ? "warning"
          : "info";
      report(ctx, "plan-save", severity, message);
    },
  });
}
