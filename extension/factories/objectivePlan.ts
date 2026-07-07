// The objective plan-factory's warm transition surface. Two pieces:
//
//   1. `/objective-plan [<number>] [--node ID]` — the warm entry: resolve the objective (arg, else
//      `active_objective` from the rebuilt `perk:workflow-state`), enter the read-only gate when it
//      is off (parity with the cold door's `mode: read-only` handoff claim; skip-if-active; exit
//      stays owned by `plan_save` / `/plan` off), and `pi.sendUserMessage(...)` to start the
//      factory loop in-session (mirrors `/address`). Headless-safe.
//
//   2. `objective_node` tool — the BOUNDED model-facing transition surface. It DELEGATES the
//      mutation to the Python cold door (`perk objective node`, canonical mutations in Python) and
//      NEVER throws (soft `details.ok`, mirrors `resolveReviewThreads`). Its description strictly
//      bounds when it may fire; a `status:"done"` call requires a non-trivial completion `audit`.
//
// The completion-audit gate is a property of THIS model-facing boundary only — NOT an invariant on
// the node-`done` state: the canonical `perk objective node --status done` (human/CI cold CLI) has
// no audit gate, and the auto-on-merge node-done deliberately sets `done` without one. Both are
// intentional non-audited paths; the structural refusal protects the model's path only. The
// "are we done?" judgment text lives in the perk-objective-plan skill.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { readPlanRef } from "../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { loadPerkConfig, resolveIssueBackendId } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import {
  idParam,
  numberParam,
  paramsOf,
  stringArrayParam,
  stringParam,
} from "../substrate/toolParams.ts";
import {
  appendWorkflowState,
  type BranchSource,
  branchOf,
  rebuildWorkflowState,
  type WorkflowState,
} from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";

/** The valid node statuses (mirrors the Python `objective.NodeStatus` StrEnum). */
const NODE_STATUSES = ["pending", "planning", "in_progress", "done", "blocked", "skipped"] as const;
type NodeStatus = (typeof NODE_STATUSES)[number];

/** The minimum trimmed length of a non-trivial completion `audit` (the pinnable predicate). */
export const MIN_AUDIT_LENGTH = 40;

interface ObjectiveNodeParams {
  /** Opaque string objective id (GitHub "7", Linear "ENG-7") — §8.21. */
  objective: string;
  node: string;
  status?: NodeStatus;
  pr?: string;
  description?: string;
  audit?: string;
}

/** The ok-arm fields. */
export interface ObjectiveNodeOk {
  objective: string;
  node: string;
  comment_updated: boolean;
}

export type ObjectiveNodeResult = Result<ObjectiveNodeOk>;

type ObjectiveNodeClaim = NonNullable<WorkflowState["objective_node_claim"]>;

/** Structural claim equality (objective + node match); absent compares equal only to absent. */
export function nodeClaimsEqual(
  a: WorkflowState["objective_node_claim"] | undefined,
  b: WorkflowState["objective_node_claim"] | undefined,
): boolean {
  const an = a ?? null;
  const bn = b ?? null;
  if (an === null || bn === null) return an === bn;
  return an.objective === bn.objective && an.node === bn.node;
}

/** The rebuilt `objective_node_claim`, read fail-open (malformed/throwing branch → null). */
export function readNodeClaim(ctx: BranchSource): ObjectiveNodeClaim | null {
  try {
    const claim = rebuildWorkflowState(branchOf(ctx)).objective_node_claim ?? null;
    if (
      claim !== null &&
      typeof claim.objective === "string" &&
      claim.objective !== "" &&
      typeof claim.node === "string" &&
      claim.node !== ""
    ) {
      return claim;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Record/clear the warm node-link carrier after a SUCCESSFUL `objective_node`
 * status transition. `planning` writes the claim (the exact moment the warm factory learns the
 * node id); any other explicit status clears it iff the rebuilt claim matches this objective +
 * node (an unrelated claim is never clobbered). Best-effort: a failed append is loud via
 * appendWorkflowState's report() but never fails the tool result.
 */
function recordNodeClaim(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  params: ObjectiveNodeParams,
): void {
  if (params.status === undefined) return; // pr-only / description-only: untouched.
  const claim: ObjectiveNodeClaim = { objective: params.objective, node: params.node };
  if (params.status === "planning") {
    appendWorkflowState(pi, ctx, {
      data: { objective_node_claim: claim },
      field: "objective_node_claim",
      expected: claim,
      scope: "objective-plan",
      failure: `objective_node_claim read-back failed for #${params.objective} node ${params.node}`,
      equals: nodeClaimsEqual,
    });
    return;
  }
  if (!nodeClaimsEqual(readNodeClaim(ctx), claim)) return;
  appendWorkflowState(pi, ctx, {
    data: { objective_node_claim: null },
    field: "objective_node_claim",
    expected: null,
    scope: "objective-plan",
    failure: `objective_node_claim clear read-back failed for #${params.objective} node ${params.node}`,
    equals: nodeClaimsEqual,
  });
}

/** The fields `objectiveNode` consumes off the success envelope. */
interface ObjectiveNodePayload {
  comment_updated: boolean;
}

/** Lenient decode — `comment_updated` is advisory display detail; never returns null. */
function decodeObjectiveNode(payload: ColdJson): ObjectiveNodePayload {
  return { comment_updated: booleanField(payload, "comment_updated") ?? false };
}

/**
 * Decode unknown tool-call params into `ObjectiveNodeParams` (the tool-boundary seam):
 * `objective` required number, `node` required non-empty string; `status` narrowed against
 * `NODE_STATUSES` (present-but-unknown → null — fail before any exec instead of riding to the
 * Click enum); `pr`/`description`/`audit` optional strings. Null on any miss (strict-fail).
 */
export function decodeObjectiveNodeParams(params: unknown): ObjectiveNodeParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  // Objective ids are opaque strings (§8.21); bare numbers (the GitHub habit) coerce.
  const objective = idParam(p, "objective");
  const node = stringParam(p, "node");
  if (typeof objective !== "string" || !objective || typeof node !== "string" || !node) {
    return null;
  }
  const rawStatus = stringParam(p, "status");
  if (rawStatus === null) return null;
  let status: NodeStatus | undefined;
  if (rawStatus !== undefined) {
    const known = NODE_STATUSES.find((s) => s === rawStatus);
    if (known === undefined) return null;
    status = known;
  }
  const pr = stringParam(p, "pr");
  const description = stringParam(p, "description");
  const audit = stringParam(p, "audit");
  if (pr === null || description === null || audit === null) return null;
  return { objective, node, status, pr, description, audit };
}

/**
 * Decode unknown tool-call params into `ReconcileObjectiveParams` (the tool-boundary seam):
 * `objective` required number, `prose` required string. Null on any miss (strict-fail).
 */
export function decodeReconcileParams(params: unknown): ReconcileObjectiveParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  const prose = stringParam(p, "prose");
  if (typeof objective !== "string" || !objective || typeof prose !== "string") return null;
  return { objective, prose };
}

/** A non-trivial audit iff it is a string whose value after `.trim()` is ≥ MIN_AUDIT_LENGTH. */
export function isNonTrivialAudit(audit: unknown): boolean {
  return typeof audit === "string" && audit.trim().length >= MIN_AUDIT_LENGTH;
}

/**
 * Build the `perk objective node` argv from the tool params (conditional, matching the substrate's optional
 * `--status`/`--pr`: `--status ""` is a Click error, so it is OMITTED when no status change).
 * Returns `null` when the call is structurally invalid (neither status nor pr).
 */
export function buildObjectiveNodeArgs(params: ObjectiveNodeParams): string[] | null {
  const { objective, node, status, pr, description } = params;
  const hasDescription = description !== undefined && description !== null;
  if (status === undefined && (pr === undefined || pr === null) && !hasDescription) return null;
  const args = ["objective", "node", objective, "--node", node];
  if (status !== undefined) args.push("--status", status);
  if (pr !== undefined && pr !== null) args.push("--pr", pr);
  if (hasDescription) args.push("--description", description);
  args.push("--json");
  return args;
}

/**
 * The bounded `objective_node` transition (delegates to the Python cold door). Returns a soft
 * result (never throws); failures set `details.ok = false`. Records nothing in workflow-state — the
 * objective's canonical state is the GitHub issue (re-read on demand).
 */
export async function objectiveNode(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  params: ObjectiveNodeParams,
): Promise<ObjectiveNodeResult> {
  const fail = failFor(ctx, "objective-plan", "objective_node");

  if (
    typeof params?.objective !== "string" ||
    !params.objective ||
    typeof params?.node !== "string" ||
    !params.node
  ) {
    return fail("objective_node needs { objective: <id>, node: <id> }", "bad_input");
  }

  // The completion-audit gate (model-path-only): `status:"done"` requires a non-trivial `audit`.
  if (params.status === "done" && !isNonTrivialAudit(params.audit)) {
    return fail(
      `setting a node to "done" requires a completion audit (a requirement→evidence mapping of ` +
        `at least ${MIN_AUDIT_LENGTH} characters) — confirm the work actually landed first.`,
      "audit_required",
    );
  }

  const args = buildObjectiveNodeArgs(params);
  if (args === null) {
    return fail(
      "objective_node needs a `status`, a `pr`, or a `description` to change",
      "bad_input",
    );
  }

  const r = await runColdDoor<ObjectiveNodePayload>(pi, ctx, args, {
    label: "perk objective node",
    decode: decodeObjectiveNode,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Maintain the warm node-link carrier off the successful transition.
  recordNodeClaim(pi, ctx, params);

  const detail = params.status
    ? `node ${params.node} → ${params.status}`
    : params.pr !== undefined && params.pr !== null
      ? `linked node ${params.node} to ${params.pr}`
      : `updated node ${params.node} description`;
  return ok(`Updated objective #${params.objective}: ${detail}.`, {
    objective: params.objective,
    node: params.node,
    comment_updated: r.data.comment_updated,
  });
}

interface ReconcileObjectiveParams {
  /** Opaque string objective id (§8.21). */
  objective: string;
  prose: string;
}

/** The ok-arm fields. */
export interface ReconcileObjectiveOk {
  objective: string;
  updated: boolean;
}

export type ReconcileObjectiveResult = Result<ReconcileObjectiveOk>;

/** The fields `reconcileObjective` consumes off the success envelope. */
interface ReconcilePayload {
  updated: boolean;
}

/** Lenient decode — `updated` is advisory display detail; never returns null. */
function decodeReconcile(payload: ColdJson): ReconcilePayload {
  return { updated: booleanField(payload, "updated") ?? false };
}

/**
 * The `reconcile_objective` transition: rewrite the objective's Reconcilable prose region (the
 * roadmap table + Immutable notes are never touched). Writes the prose to a run-scoped scratch file
 * (pi.exec has no stdin channel), delegates to the Python cold door, and never throws (soft
 * `details.ok`, mirrors `resolveReviewThreads`).
 */
export async function reconcileObjective(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  params: ReconcileObjectiveParams,
): Promise<ReconcileObjectiveResult> {
  const fail = failFor(ctx, "objective-reconcile", "reconcile_objective");

  if (
    typeof params?.objective !== "string" ||
    !params.objective ||
    typeof params?.prose !== "string"
  ) {
    return fail("reconcile_objective needs { objective: <id>, prose: <string> }", "bad_input");
  }

  // The substrate's stdin channel stages the prose in run scratch (pi.exec has no stdin) and
  // appends `--body <path>` to the argv.
  const r = await runColdDoor<ReconcilePayload>(
    pi,
    ctx,
    ["objective", "reconcile", params.objective, "--json"],
    {
      label: "perk objective reconcile",
      decode: decodeReconcile,
      stdin: {
        flag: "--body",
        content: params.prose,
        filename: `objective-reconcile-${Date.now()}.md`,
      },
    },
  );
  if (!r.ok) return fail(r.message, r.errorType);

  return ok(`Reconciled objective #${params.objective} prose region.`, {
    objective: params.objective,
    updated: r.data.updated,
  });
}

interface AddObjectiveNodeParams {
  /** Opaque string objective id (§8.21). */
  objective: string;
  phase: number;
  description: string;
  status?: NodeStatus;
  slug?: string;
  depends_on?: string[];
  comment?: string;
}

/** The ok-arm fields. */
export interface AddObjectiveNodeOk {
  objective: string;
  node: string;
  comment_updated: boolean;
}

export type AddObjectiveNodeResult = Result<AddObjectiveNodeOk>;

/** The fields `addObjectiveNode` consumes off the success envelope. */
interface AddObjectiveNodePayload {
  node_id: string;
  comment_updated: boolean;
}

/** Lenient decode — both fields are advisory display detail; never returns null. */
function decodeAddObjectiveNode(payload: ColdJson): AddObjectiveNodePayload {
  return {
    node_id: stringField(payload, "node") ?? "",
    comment_updated: booleanField(payload, "comment_updated") ?? false,
  };
}

/**
 * Decode unknown tool-call params into `AddObjectiveNodeParams` (the tool-boundary seam):
 * `objective` required opaque id (bare numbers coerce), `phase` a required positive integer,
 * `description` a required non-empty string; `status` narrowed against `NODE_STATUSES`
 * (present-but-unknown → null); `slug`/`comment` optional strings; `depends_on` an optional
 * `string[]`. Null on any miss (strict-fail).
 */
export function decodeAddObjectiveNodeParams(params: unknown): AddObjectiveNodeParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const objective = idParam(p, "objective");
  if (typeof objective !== "string" || !objective) return null;
  const phase = numberParam(p, "phase");
  if (typeof phase !== "number" || !Number.isInteger(phase) || phase <= 0) return null;
  const description = stringParam(p, "description");
  if (typeof description !== "string" || !description) return null;
  const rawStatus = stringParam(p, "status");
  if (rawStatus === null) return null;
  let status: NodeStatus | undefined;
  if (rawStatus !== undefined) {
    const known = NODE_STATUSES.find((s) => s === rawStatus);
    if (known === undefined) return null;
    status = known;
  }
  const slug = stringParam(p, "slug");
  const comment = stringParam(p, "comment");
  const dependsOn = stringArrayParam(p, "depends_on");
  if (slug === null || comment === null || dependsOn === null) return null;
  if (dependsOn?.some((d) => !d)) return null;
  return { objective, phase, description, status, slug, depends_on: dependsOn, comment };
}

/**
 * Build the `perk objective node-add` argv from the tool params: the required `--phase`/
 * `--description`, then a conditional `--status`/`--slug`/`--comment`, one `--depends-on <id>`
 * per dependency, ending `--json`.
 */
export function buildAddObjectiveNodeArgs(params: AddObjectiveNodeParams): string[] {
  const { objective, phase, description, status, slug, depends_on, comment } = params;
  const args = [
    "objective",
    "node-add",
    objective,
    "--phase",
    String(phase),
    "--description",
    description,
  ];
  if (status !== undefined) args.push("--status", status);
  if (slug !== undefined && slug !== null) args.push("--slug", slug);
  for (const dep of depends_on ?? []) args.push("--depends-on", dep);
  if (comment !== undefined && comment !== null) args.push("--comment", comment);
  args.push("--json");
  return args;
}

/**
 * The `add_objective_node` transition: insert a NEW roadmap node (auto-assigned `<phase>.<n>`).
 * Delegates the write to the Python cold door and never throws (soft `details.ok`, mirrors
 * `objectiveNode`).
 */
export async function addObjectiveNode(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  params: AddObjectiveNodeParams,
): Promise<AddObjectiveNodeResult> {
  const fail = failFor(ctx, "objective-reconcile", "add_objective_node");

  if (
    typeof params?.objective !== "string" ||
    !params.objective ||
    typeof params?.phase !== "number" ||
    typeof params?.description !== "string" ||
    !params.description
  ) {
    return fail(
      "add_objective_node needs { objective: <id>, phase: <int>, description: <string> }",
      "bad_input",
    );
  }

  const r = await runColdDoor<AddObjectiveNodePayload>(pi, ctx, buildAddObjectiveNodeArgs(params), {
    label: "perk objective node-add",
    decode: decodeAddObjectiveNode,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  return ok(`Added node ${r.data.node_id} to objective #${params.objective}.`, {
    objective: params.objective,
    node: r.data.node_id,
    comment_updated: r.data.comment_updated,
  });
}

/** Resolve the active objective number from the rebuilt workflow-state (for the warm command). */
function activeObjective(ctx: ExtensionContext): string | null {
  try {
    const branch = branchOf(ctx);
    return rebuildWorkflowState(branch).active_objective ?? null;
  } catch {
    return null;
  }
}

/**
 * Resolve the objective number for `/objective-reconcile` via three tiers: the command arg, the
 * active objective from workflow-state, then the just-landed plan's `objective_id` from the
 * plan-ref (so the post-land path works even when `active_objective` is unset). Returns `null` when
 * none resolves.
 */
export function resolveReconcileObjective(args: string, ctx: ExtensionContext): string | null {
  const { number } = parseCommandArgs(args);
  if (number !== null) return number;
  const active = activeObjective(ctx);
  if (active !== null) return active;
  try {
    return readPlanRef(ctx.cwd)?.objective_id ?? null;
  } catch {
    return null;
  }
}

/** Parse `--node ID` out of the command args (everything else is the objective id — an opaque
 * string per §8.21: `7`, `#7`, or Linear's `ENG-7`). */
function parseCommandArgs(args: string): { number: string | null; node: string | null } {
  const nodeMatch = args.match(/--node[=\s]+(\S+)/);
  const node = nodeMatch?.[1] ?? null;
  const rest = args.replace(/--node[=\s]+\S+/, "").trim();
  const token = rest.split(/\s+/)[0]?.replace(/^#/, "") ?? "";
  return { number: token.length > 0 ? token : null, node };
}

/**
 * Backend-aware supplemental clause for the objective-read step of the factory prompts.
 * The wording lives in `prompts/common/objective-read/linear.md`, rendered identically by both
 * planes via the shared render seam (contracts.md §8.31); branching stays in code. github (and any
 * non-linear) → "" (the `perk objective show` step already covers it); linear → the Project URL +
 * the linear_get_issue/linear_list_comments tools (an `open <url>` fallback when the url is known).
 */
export function objectiveReadInstruction(
  backend: string,
  objectiveId: string,
  url: string,
): string {
  if (backend !== "linear") return "";
  const where = url ? `(${url})` : `(run \`perk objective show ${objectiveId}\` for its URL)`;
  const fallback = url ? `; if the linear tools are unavailable, open ${url}` : "";
  return render("common/objective-read/linear.md", { where, fallback });
}

/**
 * Fetch the objective's URL via `perk objective show <id> --json` (reading `objective.url`).
 * Lenient: returns "" on any failure / missing url — never throws (the seed prompt's step-1
 * `perk objective show <id>` step surfaces the URL anyway). Only called for the linear backend
 * (github needs no clause → no fetch).
 */
async function fetchObjectiveUrl(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  objectiveId: string,
): Promise<string> {
  try {
    const r = await runColdDoor<string>(pi, ctx, ["objective", "show", objectiveId, "--json"], {
      label: "perk objective show",
      decode: (payload: ColdJson) =>
        stringField(objectField(payload, "objective") ?? {}, "url") ?? "",
    });
    return r.ok ? r.data : "";
  } catch {
    return "";
  }
}

/** The seed guidance the warm `/objective-plan` injects to start the factory loop (the
 * perk-objective-plan skill pointer rides the skill-binding suffix — not hardcoded).
 * The loop is file-first (`plan_draft` → `plan_review` → approval-driven save); the node link
 * rides the `objective_node_claim` carrier recorded by the unconditional `planning` mark.
 * When `model` is set, the OPTIONAL `perk.objective-explorer` spawn carries an inline `model`
 * override ([subagents] objective-explorer); otherwise the agent's frontmatter default is used. */
export function factoryGuidance(
  objective: string,
  node: string | null,
  model?: string,
  backend = "github",
  url = "",
): string {
  const readClause = objectiveReadInstruction(backend, objective, url);
  return render("stages/objective-plan/guidance.md", {
    objective,
    node: node ?? "",
    read_clause: readClause,
    model: model ?? "",
  });
}

/** The seed guidance the warm `/objective-reconcile` injects to start the reconcile pass (the
 * perk-objective-reconcile skill pointer rides the skill-binding suffix — not
 * hardcoded). */
export function reconcileGuidance(objective: string, backend = "github", url = ""): string {
  const readClause = objectiveReadInstruction(backend, objective, url);
  return render("stages/objective-reconcile.md", { objective, read_clause: readClause });
}

const RECONCILE_TOOL_GUIDELINES = [
  "Call reconcile_objective only to rewrite the objective's Reconcilable prose region after a PR merged — the roadmap table and Immutable notes are never touched.",
  "Pass reconcile_objective the FULL replacement prose; it overwrites the marker-bounded Reconcilable region wholesale.",
  "Judgment + durable writes stay with you; skip reconcile_objective when nothing is stale (do not churn).",
];

const ADD_NODE_TOOL_GUIDELINES = [
  "Use add_objective_node SPARINGLY — only during reconciliation, when a genuine new unit of work emerged that wasn't planned.",
  "add_objective_node is only for genuinely-new, unplanned work — never to restate, rename, or re-scope an existing node (use objective_node's `description` for that).",
  "Judgment + durable writes stay with you; add_objective_node delegates the write to the canonical Python plane.",
];

const TOOL_GUIDELINES = [
  'Call objective_node only as part of the objective workflow: (a) to link a saved plan to its node — pass pr:"#N" with no status; or (b) to advance a node\'s status.',
  'Set objective_node status:"done" ONLY when the node\'s work has actually landed, and supply a completion `audit` (a requirement→evidence mapping). Treat uncertainty as not-done.',
  "Mutations are canonical in the Python plane — objective_node delegates; judgment and durable plan writes stay with you.",
];

/**
 * Register the warm objective plan-factory door: the `objective_node` bounded transition tool + the
 * `/objective-plan` command. Headless-safe; the tool never throws.
 */
export function registerObjectivePlan(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_node",
    label: "Update objective node",
    description:
      "Update an objective node as part of the objective workflow. Call ONLY to (a) link a saved " +
      'plan to its node — pass pr:"#N" with no status; or (b) advance a node\'s status when ' +
      'explicitly part of the workflow — and set status:"done" ONLY when the node\'s work has ' +
      "actually landed, supplying the completion `audit`.",
    promptSnippet: "Link a saved plan to its objective node, or advance a node's status",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["objective", "node"],
      properties: {
        objective: { type: ["string", "number"], description: "The objective issue id." },
        node: { type: "string", description: "The roadmap node id (e.g. 2.3)." },
        status: {
          type: "string",
          enum: [...NODE_STATUSES],
          description: "Optional new status (explicit-only; never inferred from pr).",
        },
        pr: {
          type: "string",
          description: 'Set/clear the linked PR/plan ("#N" sets, "" clears).',
        },
        description: {
          type: "string",
          description:
            "Optional new node description (e.g. reconciling node scope/naming drift against the " +
            "merged diff). May be passed alone (no status/pr).",
        },
        audit: {
          type: "string",
          description:
            'Required when status is "done": a requirement→evidence mapping proving the node\'s ' +
            "work actually landed (treat uncertainty as not-done).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeObjectiveNodeParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-plan",
          "objective_node",
        )("objective_node needs { objective: <id>, node: <id> }", "bad_input");
      }
      return objectiveNode(pi, ctx, decoded);
    },
  });

  pi.registerTool({
    name: "reconcile_objective",
    label: "Reconcile objective prose",
    description:
      "Rewrite the objective's Reconcilable prose region (the marker-bounded prose in the " +
      "objective body) to reconcile it against a merged PR. The Mechanical roadmap table and any " +
      "Immutable notes are NEVER touched. Delegates the write to the perk cold door.",
    promptSnippet: "Reconcile the objective's Reconcilable prose region against the merged diff",
    promptGuidelines: RECONCILE_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["objective", "prose"],
      properties: {
        objective: { type: ["string", "number"], description: "The objective issue id." },
        prose: {
          type: "string",
          description:
            "The full replacement prose for the Reconcilable region (overwrites it wholesale).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeReconcileParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-reconcile",
          "reconcile_objective",
        )("reconcile_objective needs { objective: <id>, prose: <string> }", "bad_input");
      }
      return reconcileObjective(pi, ctx, decoded);
    },
  });

  pi.registerTool({
    name: "add_objective_node",
    label: "Add objective node",
    description:
      "Add a NEW node to an objective roadmap. Use SPARINGLY — only during reconciliation, when a " +
      "genuine new unit of work emerged that wasn't planned. Auto-assigns the next `<phase>.<n>` " +
      "id. Delegates the write to the perk cold door.",
    promptSnippet: "Add a genuinely-new node to an objective roadmap (sparingly, during reconcile)",
    promptGuidelines: ADD_NODE_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["objective", "phase", "description"],
      properties: {
        objective: { type: ["string", "number"], description: "The objective issue id." },
        phase: { type: "number", description: "The phase number to insert the node into." },
        description: { type: "string", description: "What the new node delivers." },
        status: {
          type: "string",
          enum: [...NODE_STATUSES],
          description: "Optional initial status (defaults to pending).",
        },
        slug: {
          type: "string",
          description: "Optional short slug (auto-derived from the description if omitted).",
        },
        depends_on: {
          type: "array",
          items: { type: "string" },
          description: "Optional node ids this node depends on.",
        },
        comment: { type: "string", description: "Optional note attached to the node." },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeAddObjectiveNodeParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-reconcile",
          "add_objective_node",
        )(
          "add_objective_node needs { objective: <id>, phase: <int>, description: <string> }",
          "bad_input",
        );
      }
      return addObjectiveNode(pi, ctx, decoded);
    },
  });

  registerPerkCommand(pi, "objective-reconcile", {
    description:
      "Reconcile an objective's roadmap prose against a merged PR (post-land). Pass an objective " +
      "number (else the active objective, else the just-landed plan's objective).",
    handler: async (args, ctx) => {
      const objective = resolveReconcileObjective(args ?? "", ctx);
      if (objective === null) {
        report(
          ctx,
          "objective-reconcile",
          "warning",
          "no objective given and none active or linked. Use `/objective-reconcile <number>`.",
        );
        return;
      }
      report(ctx, "objective-reconcile", "info", `#${objective}`);
      const backend = resolveIssueBackendId(ctx.cwd);
      const url = backend === "linear" ? await fetchObjectiveUrl(pi, ctx, objective) : "";
      pi.sendUserMessage(
        reconcileGuidance(objective, backend, url) +
          bindingSuffix(ctx.cwd, "command:objective-reconcile"),
      );
    },
  });

  registerPerkCommand(pi, "objective-plan", {
    description:
      "Start the objective plan factory: select the next node and author a bounded plan. " +
      "Pass an objective number (else the active objective) and optional --node ID.",
    handler: async (args, ctx) => {
      const { number, node } = parseCommandArgs(args ?? "");
      const objective = number ?? activeObjective(ctx);
      if (objective === null) {
        report(
          ctx,
          "objective-plan",
          "warning",
          "no objective given and none active. Use `/objective-plan <number>` or `/objective <id>` first.",
        );
        return;
      }
      report(ctx, "objective-plan", "info", `#${objective}${node ? ` node ${node}` : ""}`);
      // Enter the read-only gate (parity with the cold door's `mode: read-only` handoff claim) —
      // skip-if-active so an already-gated session (cold objective-plan, `/plan` on) gets no
      // duplicate `mode` append or announce. Entering BEFORE sendUserMessage means the seeded
      // factory turn runs gated and picks up the [READ-ONLY MODE] + [PLAN AUTHORING] injections
      // on its before_agent_start. Exit stays owned by plan_save (approval auto-save included)
      // and `/plan` off.
      if (!gating.isActive()) {
        gating.enter(ctx);
        report(
          ctx,
          "objective-plan",
          "info",
          "read-only ON — structurally enforced exploration; plan_save exits (approval auto-saves), or /plan toggles off.",
        );
      }
      // Inject the factory guidance as a user message so the model starts the loop (always a turn).
      // The perk-objective-plan pointer rides the skill-binding suffix (D5) since a warm
      // /objective-plan outside a stage:objective-plan session gets none from Mechanism A.
      const model = loadPerkConfig(ctx.cwd).subagents["objective-explorer"];
      const backend = resolveIssueBackendId(ctx.cwd);
      const url = backend === "linear" ? await fetchObjectiveUrl(pi, ctx, objective) : "";
      pi.sendUserMessage(
        factoryGuidance(objective, node, model, backend, url) +
          bindingSuffix(ctx.cwd, "stage:objective-plan"),
      );
    },
  });
}
