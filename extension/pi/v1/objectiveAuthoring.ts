// The v1 Pi installer for the objective authoring flow (module-contracts.md's named-installer
// shape): `installObjectiveAuthoringBindings` owns the objective-authoring context hook pair,
// the `objective_draft`/`objective_save` tools, and the `/objective-save` command —
// registration metadata pinned by the suite's registration-parity tests. The feature logic lives in `authoring/objective/`; this
// module decodes at the tool boundary, builds the cold-door backend + gate + dream-gate
// adapters, constructs the warm-door Result envelopes, and places the feature-owned prose in Pi
// fields. `objectiveApprovalSaveV1` is the composed approval→save twin the review arm
// (`pi/v1/objectiveReview.ts`) and the browser door consume.
//
// The objective-authoring injection rides the shared `installInjectedContext` helper
// (pi/v1/contextInjection.ts — contracts §8.31 semantics): a live copy in the
// compaction-active window suppresses re-injection, and compaction dropping it from model
// context re-injects on the next turn.
//
// Format doctrine (rides the tools): JSON is the storage/transport format, NEVER the human
// review surface — the review arm renders markdown via the feature's resume+render helpers; the
// approval→save orchestration re-reads the STRUCTURED artifact. Carve-out doctrine: the draft
// tool takes NO path/name parameter (the artifact name is fixed and the bytes flow through the
// session seam), so allowlisting `objective_draft` in `READ_ONLY_TOOLS` keeps the read-only
// invariant intact.

import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  DELIVERY_CHOICES,
  isDeliveryChoice,
  OBJECTIVE_DRAFT_ARTIFACT,
  type ObjectiveDraftInput,
  reviseObjectiveDraft,
} from "../../authoring/objective/draft.ts";
import {
  type DreamReportGateOutcome,
  resolveDreamReportGate,
} from "../../authoring/objective/dreamReportGate.ts";
import {
  OBJECTIVE_AUTHOR_CONTEXT_TYPE,
  OBJECTIVE_AUTHOR_MARKER,
  OBJECTIVE_AUTHOR_STAGE,
  objectiveAuthoringContextContent,
  objectiveSaveGuidance,
} from "../../authoring/objective/prose.ts";
import {
  type ObjectiveApprovalSaveDeps,
  type ObjectiveBackend,
  objectiveApprovalSave,
  type SaveObjectiveOutcome,
  saveObjective,
} from "../../authoring/objective/save.ts";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import { DREAM_REPORT_INPUT_SCHEMA } from "../../learning/dreamReport.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import { atomicWriteFileSync, ensureRunScratch } from "../../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { loadPerkConfig } from "../../substrate/config.ts";
import { failFor, ok, type Result } from "../../substrate/result.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { arrayParam, objectParam, paramsOf, stringParam } from "../../substrate/toolParams.ts";
import { type BranchEntry, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { report, type Severity } from "../../surfaces/report.ts";
import { installInjectedContext } from "./contextInjection.ts";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import { productionDreamGateRecovery } from "./objectiveDreamGate.ts";

// ------------------------------------------------------------------- the tool-boundary decode

/**
 * The decoded `objective_save` tool params (shared with `objective_draft`) — an ALIAS of the
 * feature's draft input, not a second handwritten contract: the tool boundary decodes exactly
 * the shape the feature operations consume (`dream_report` stays opaque here — deep validation
 * is the gate resolver's; the save path wraps it as its `{input}` carrier arm).
 */
export type ObjectiveSaveParams = ObjectiveDraftInput;

/**
 * The `delivery` enum property, shared between `objective_save` and `objective_draft` so the
 * two tools' delivery contracts cannot drift. The description bakes in the explicit-human-choice
 * discipline: the agent must ASK, with incremental recommended.
 */
export const DELIVERY_PARAM_SCHEMA = {
  type: "string",
  enum: DELIVERY_CHOICES,
  description:
    "The reviewed delivery choice — ask the human explicitly (incremental is the recommended " +
    "default: each plan lands independently; stacked lands ALL non-skipped roadmap nodes as " +
    "one atomic PR train — capability-checked at save).",
} as const;

/**
 * The `dream_report` property, shared between `objective_save` and `objective_draft` so the
 * two tools' dream contracts cannot drift: the §8.62 `DREAM_REPORT_INPUT_SCHEMA` embedded by
 * identifier (the `DELIVERY_PARAM_SCHEMA`/`ROADMAP_PARAM_SCHEMA` shared-schema pattern) plus
 * the gate description. Structurally reachable only inside a `perk learn dream` session (the
 * resolver refuses it outside one).
 */
export const DREAM_REPORT_PARAM_SCHEMA = {
  ...DREAM_REPORT_INPUT_SCHEMA,
  description:
    "The perk learn dream session's final report input (the parent's decisions only) — " +
    "required inside a dream session, refused outside one.",
} as const;

/**
 * The roadmap-node items JSON schema, shared between `objective_save` and `objective_draft`
 * so the two tools' roadmap contracts cannot drift.
 */
export const ROADMAP_PARAM_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["id", "description"],
  properties: {
    id: { type: "string", description: 'A stable node id, e.g. "1.1".' },
    description: { type: "string", description: "What this node delivers." },
    status: {
      type: "string",
      enum: ["pending", "planning", "in_progress", "done", "blocked", "skipped"],
      description: "Optional initial status (defaults to pending).",
    },
    slug: { type: "string", description: "Optional short slug." },
    pr: { type: "string", description: 'Optional plan/PR backlink, e.g. "#42".' },
    depends_on: {
      type: "array",
      items: { type: "string" },
      description: "Optional explicit dependency node ids.",
    },
    comment: { type: "string", description: "Optional note." },
    adopt_issue: {
      type: "string",
      description:
        "Optional: the id/identifier of a pre-existing source issue this node adopts in place " +
        "(objective author --from, Linear only).",
    },
  },
} as const;

/**
 * Decode unknown `objective_save` tool-call params (the tool-boundary seam). `prose`
 * absent decodes to `""` (so `saveObjective`'s "no objective prose to save" `invalid_input` arm
 * keeps owning that message) but present-but-mistyped → null (strict-fail). `roadmap` stays
 * `unknown[]` — the Python cold door owns node-shape validation.
 */
export function decodeObjectiveSaveParams(params: unknown): ObjectiveSaveParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const prose = stringParam(p, "prose");
  const title = stringParam(p, "title");
  const roadmap = arrayParam(p, "roadmap");
  const base = stringParam(p, "base");
  const delivery = stringParam(p, "delivery");
  // `dream_report` must be a plain object when present (absent → undefined); deep validation
  // stays with the gate resolver (resolveDreamReportGate).
  const dreamReport = objectParam(p, "dream_report");
  if (
    prose === null ||
    title === null ||
    roadmap === null ||
    base === null ||
    delivery === null ||
    dreamReport === null
  ) {
    return null;
  }
  // The delivery enum is strict beyond `string`: an off-enum value is present-but-mistyped.
  if (delivery !== undefined && !isDeliveryChoice(delivery)) return null;
  return { prose: prose ?? "", title, roadmap, base, delivery, dream_report: dreamReport };
}

// -------------------------------------------------------------- the cold-door backend adapter

/**
 * The run-scoped dream-report transfer filename (contracts §8.64) — the extension→door handoff
 * carrying the reviewed CANONICAL parts. The Python mirror is
 * `perk.learn.dream_companion.DREAM_REPORT_TRANSFER_FILENAME` (parity-pinned by test), beside
 * the existing `DREAM_MANIFEST_FILENAME` mirror pair.
 */
export const DREAM_REPORT_TRANSFER_FILENAME = "dream-report-transfer.json";

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface ObjectiveSaveOk {
  /** `id` is the opaque string objective id (GitHub "7", Linear "ENG-7") — §8.21. */
  objective: { id: string; url: string };
  existed: boolean | null;
}

export type ObjectiveSaveResult = Result<ObjectiveSaveOk>;

/** The decoded `perk objective create --json` payload slice the warm door consumes. */
interface ObjectiveCreatePayload {
  objective: { id: string; url: string; existed: boolean | undefined };
}

/** Narrow the `perk objective create --json` success payload; strict on `objective`. */
function decodeObjectiveCreate(payload: ColdJson): ObjectiveCreatePayload | null {
  const objective = objectField(payload, "objective");
  if (objective === undefined) return null;
  const id = stringField(objective, "id");
  const url = stringField(objective, "url");
  if (id === undefined || url === undefined) return null;
  return { objective: { id, url, existed: booleanField(objective, "existed") } };
}

/**
 * The production `ObjectiveBackend` over the Python cold door (`perk objective create --json`
 * via the shared cold-door client; the prose rides the run-scratch stdin channel; `runId: null`
 * or blank omits `--run-id` — an identity-less save keeps working). On the dream arm
 * (`dreamParts` present) the reviewed CANONICAL parts cross to the Python plane through the
 * run-scoped `dream-report-transfer.json` handoff (§8.64) — staged atomically BEFORE the cold
 * door (a write failure is the soft `scratch_failed` refusal, the runColdDoor stdin-staging
 * precedent: the door is NOT invoked, nothing activates, the read-only gate stays on) — and
 * `perk objective create` re-validates the transfer and converges the companion idempotently.
 * Non-dream saves write nothing (byte-identical).
 */
function coldDoorObjectiveBackend(pi: ExtensionAPI, ctx: ExtensionContext): ObjectiveBackend {
  return {
    async create(req) {
      const runId = req.runId ?? "";
      if (req.dreamParts !== undefined) {
        try {
          const dir = ensureRunScratch(ctx.cwd, runId);
          const content = `${JSON.stringify(
            { schema_version: "1", run_id: runId, parts: req.dreamParts },
            null,
            2,
          )}\n`;
          atomicWriteFileSync(join(dir, DREAM_REPORT_TRANSFER_FILENAME), content);
        } catch (err) {
          return {
            status: "failed",
            message: `could not stage the dream-report transfer: ${String(err)}`,
            errorType: "scratch_failed",
          };
        }
      }
      const args = ["objective", "create", "--json"];
      if (req.title) args.push("--title", req.title);
      if (req.base) args.push("--base", req.base);
      // The reviewed delivery choice rides verbatim; the cold door owns validation + preflight.
      if (req.delivery) args.push("--delivery", req.delivery);
      if (runId) args.push("--run-id", runId);
      if (req.roadmap && req.roadmap.length > 0) {
        args.push("--roadmap", JSON.stringify(req.roadmap));
      }
      const r = await runColdDoor<ObjectiveCreatePayload>(pi, ctx, args, {
        label: "perk objective create",
        decode: decodeObjectiveCreate,
        stdin: { flag: "--body", content: req.prose, filename: "objective.md" },
      });
      if (!r.ok) return { status: "failed", message: r.message, errorType: r.errorType };
      return {
        status: "saved",
        id: r.data.objective.id,
        url: r.data.objective.url,
        existed: r.data.objective.existed ?? null,
      };
    },
  };
}

// ------------------------------------------------------------------------- adapter plumbing

/** Open the branch-backed session (always opens; `runId: null` is the identity-less arm). */
function openSession(pi: ExtensionAPI, ctx: ExtensionContext): WorkflowSession {
  return openBranchWorkflowSession(pi, ctx);
}

/** The narrow gate slice the feature releases (D1a: exit only after a verified save). */
function gateFor(gating: ToolGating, ctx: ExtensionContext): ApprovalGate {
  return { isActive: () => gating.isActive(), exit: () => gating.exit(ctx) };
}

/** The ctx-bound §8.63 gate resolver the feature ops consume — the resolver over the
 * runtime-minted production recovery capability (`pi/v1/objectiveDreamGate.ts`). */
function dreamGateFor(
  ctx: ExtensionContext,
): (input: unknown, generatedAt: string) => DreamReportGateOutcome {
  return (input, generatedAt) =>
    resolveDreamReportGate(productionDreamGateRecovery(ctx), input, generatedAt);
}

/**
 * The production approval→save dependency bag (the `planSaveDepsFor` mirror): session via the
 * branch backing, the cold-door backend, the gate slice, and the ctx-bound dream-gate resolver.
 * The review arm + the browser door consume the composed `objectiveApprovalSaveV1` instead.
 */
function objectiveSaveDepsFor(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
): ObjectiveApprovalSaveDeps {
  return {
    session: openSession(pi, ctx),
    backend: coldDoorObjectiveBackend(pi, ctx),
    gate: gateFor(gating, ctx),
    resolveDreamGate: dreamGateFor(ctx),
  };
}

/**
 * Seed a fresh `perk:objective-budget` activation marker off a successful save whose linkage
 * differed (mirrors `/objective <id>`'s activation, so budget tracking starts immediately).
 * Byte-equivalent to the historical `linked !== objectiveId` guard: the seam's `unchanged` is
 * the equal case, and applied/unverified/rejected all imply "differed" (the marker never keyed
 * off the append's read-back result).
 */
function activateBudgetIfLinked(pi: ExtensionAPI, save: SaveObjectiveOutcome): void {
  if (save.status !== "saved") return;
  if (save.linkage === null || save.linkage.status === "unchanged") return;
  pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
    objective_id: save.id,
    activated_at: new Date().toISOString(),
  });
}

/**
 * Render a save outcome as the warm-door Result envelope (the ONE result-construction site for
 * every objective save surface — tool, command relay, review arm, browser door). A `saved`
 * outcome renders the terminating "Saved/Found existing objective #id → url" twin; a `failed`
 * outcome reports through the `failFor` seam (byte-identical to the failure the save always
 * rendered).
 */
function objectiveSaveResultOf(
  ctx: ExtensionContext,
  save: SaveObjectiveOutcome,
): ObjectiveSaveResult {
  if (save.status === "failed") {
    return failFor(ctx, "objective-save")(save.message, save.errorType);
  }
  const verb = save.existed ? "Found existing" : "Saved";
  return ok(
    `${verb} objective #${save.id} → ${save.url}`,
    {
      objective: { id: save.id, url: save.url },
      existed: save.existed,
    },
    { terminate: true },
  );
}

/** The approval→save orchestration outcome, rendered (the door/arm-facing twin).
 * `refused-draft` passes through unrendered — no `result`, no `gateExited`: nothing was saved,
 * the gate was never touched, and no budget activation runs. */
export type ObjectiveApprovalSaveV1Outcome =
  | { status: "no-draft" }
  | { status: "refused-draft"; problem: string }
  | { status: "saved" | "save-failed"; result: ObjectiveSaveResult; gateExited: boolean };

/**
 * The composed approval→save twin (the shape `plan_review`'s objective arm, the browser door,
 * and the `/objective-save` failsafe consume): run the feature's `objectiveApprovalSave` over
 * the production deps, seed the budget activation marker off a linked save, and render the
 * Result envelope. Flow semantics live in the feature op (artifact re-read, D1a gate exit,
 * §8.63 re-validation); this twin owns only composition + rendering.
 */
export async function objectiveApprovalSaveV1(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { title?: string } = {},
): Promise<ObjectiveApprovalSaveV1Outcome> {
  const outcome = await objectiveApprovalSave(objectiveSaveDepsFor(pi, ctx, gating), opts);
  if (outcome.status === "no-draft") return { status: "no-draft" };
  if (outcome.status === "refused-draft") {
    return { status: "refused-draft", problem: outcome.problem };
  }
  activateBudgetIfLinked(pi, outcome.result);
  return {
    status: outcome.status,
    result: objectiveSaveResultOf(ctx, outcome.result),
    gateExited: outcome.gateExited,
  };
}

/**
 * Whether the current branch is an objective-author session (read-only gate AND stage match).
 * Fail-open: a throwing state rebuild reports false.
 */
function isObjectiveAuthoring(gating: ToolGating, branch: readonly BranchEntry[]): boolean {
  if (!gating.isActive()) return false;
  try {
    return rebuildWorkflowState(branch).stage === OBJECTIVE_AUTHOR_STAGE;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------------------ the installer

const DRAFT_TOOL_GUIDELINES = [
  "Call objective_draft to persist the current working objective as you author or revise it; pass the FULL prose and the FULL structured roadmap each time (it rewrites the whole draft).",
  "objective_draft never saves to GitHub and never ends the turn — objective_save//objective-save remain the canonical save surface. Never hand-write roadmap YAML — hand the structured roadmap to the tool.",
  "Pass objective_draft's `base` only to target a non-default branch; omit it to use the repo default.",
];

const SAVE_TOOL_GUIDELINES = [
  "Use objective_save only after the objective + roadmap are decision-complete; it creates the canonical perk:objective issue, activates it, and ends the turn.",
  "Pass objective_save the objective PROSE in `prose` and the STRUCTURED roadmap in `roadmap` (a JSON array of nodes) — never hand-write roadmap YAML.",
  'Each objective_save roadmap node needs a stable `id` (e.g. "1.1") and a `description`; `status` defaults to pending. Use `depends_on` for explicit ordering.',
];

/**
 * Install every objective-authoring Pi binding: the objective-authoring context hook pair (the
 * frozen hooks-ordering slot index.ts calls this at — planMode.ts defers when the stage is
 * objective-author, so exactly one authoring context is injected), the `objective_draft` and
 * `objective_save` tools, and the `/objective-save` command — registration metadata pinned by
 * the registration-parity tests. Inert outside objective sessions; never throws.
 */
export function installObjectiveAuthoringBindings(pi: ExtensionAPI, gating: ToolGating): void {
  // The objective-authoring context injection (display:false), keyed off (read-only gate AND
  // stage === objective-author); the inject/strip mechanics (active-window dedup, stale-marker
  // strip) live in the shared helper.
  installInjectedContext(pi, {
    customType: OBJECTIVE_AUTHOR_CONTEXT_TYPE,
    markers: [OBJECTIVE_AUTHOR_MARKER],
    select: (ctx, branch) =>
      isObjectiveAuthoring(gating, branch)
        ? {
            marker: OBJECTIVE_AUTHOR_MARKER,
            content: () => objectiveAuthoringContextContent(loadPerkConfig(ctx.cwd).planAuthoring),
          }
        : null,
    live: (_ctx, branch) => isObjectiveAuthoring(gating, branch),
  });

  pi.registerTool({
    name: "objective_draft",
    label: "Objective draft",
    description:
      "Write (or overwrite) the working objective draft — prose + the structured roadmap — to " +
      "the session data dir and record its provenance pointer. The only sanctioned write surface " +
      "while read-only. NOT a save — objective_save//objective-save still persist the objective " +
      "to GitHub.",
    promptSnippet:
      "Persist the working objective draft (prose + structured roadmap) to the session data dir (full rewrite)",
    promptGuidelines: DRAFT_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["prose"],
      properties: {
        prose: {
          type: "string",
          description: "The objective prose (the why, the design, the boundaries/non-goals).",
        },
        title: {
          type: "string",
          description: "Optional objective title (defaults to the prose's first heading).",
        },
        base: {
          type: "string",
          description:
            "Optional target branch for this objective's plans (omit to use the repo default).",
        },
        delivery: DELIVERY_PARAM_SCHEMA,
        dream_report: DREAM_REPORT_PARAM_SCHEMA,
        roadmap: {
          type: "array",
          description:
            "The structured roadmap: a JSON array of nodes. Never hand-write roadmap YAML.",
          items: ROADMAP_PARAM_SCHEMA,
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // The shared param contract: the same decode as `objective_save`, so the two cannot
      // drift. (The parameter literals are duplicated at both registration sites on purpose —
      // the prose-review workbench needs in-place literals — and pinned identical by the
      // registration baselines.)
      const decoded = decodeObjectiveSaveParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-draft",
          "objective_draft",
        )(
          "objective_draft needs { prose: string, roadmap?: array } per the tool schema",
          "bad_input",
        );
      }
      const fail = failFor(ctx, "objective-draft");
      const revised = reviseObjectiveDraft(decoded, {
        session: openSession(pi, ctx),
        resolveDreamGate: dreamGateFor(ctx),
      });
      switch (revised.status) {
        case "revised":
        case "unchanged":
          // A byte-identical rewrite short-circuits interior-side; the rendered result is
          // computed from identical content either way, so the surface stays byte-stable.
          return ok(
            `Objective draft written → ${revised.receipt.path} (${revised.receipt.digest}; ` +
              `${revised.roadmapNodes} roadmap nodes)`,
            {
              name: OBJECTIVE_DRAFT_ARTIFACT,
              path: revised.receipt.path,
              digest: revised.receipt.digest,
              bytes: revised.bytes,
              run_id: revised.receipt.runId,
              roadmap_nodes: revised.roadmapNodes,
            },
          );
        case "rejected":
          return fail(revised.problem, revised.errorType);
        case "unverified":
          return fail(revised.problem, "write_failed");
      }
    },
  });

  pi.registerTool({
    name: "objective_save",
    label: "Save objective",
    description:
      "Persist a drafted objective + structured roadmap to GitHub as a perk:objective issue, " +
      "activate it, and start budget tracking. Terminating: ends the turn on save. Call only when " +
      "the objective and roadmap are decision-complete.",
    promptSnippet: "Save the decision-complete objective + roadmap to GitHub (terminates the turn)",
    promptGuidelines: SAVE_TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["prose"],
      properties: {
        prose: {
          type: "string",
          description: "The objective prose (the why, the design, the boundaries/non-goals).",
        },
        title: {
          type: "string",
          description: "Optional objective title (defaults to the prose's first heading).",
        },
        base: {
          type: "string",
          description:
            "Optional target branch for this objective's plans (omit to use the repo default).",
        },
        delivery: DELIVERY_PARAM_SCHEMA,
        dream_report: DREAM_REPORT_PARAM_SCHEMA,
        roadmap: {
          type: "array",
          description:
            "The structured roadmap: a JSON array of nodes. Never hand-write roadmap YAML.",
          items: ROADMAP_PARAM_SCHEMA,
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeObjectiveSaveParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "objective-save",
          "objective_save",
        )(
          "objective_save needs { prose: string, roadmap?: array } per the tool schema",
          "bad_input",
        );
      }
      // The direct tool path wraps ONLY a present decoded value as the union's `direct` arm
      // (the save stamps generated_at); no stored parts, so no byte-compare on this path.
      const { dream_report, ...rest } = decoded;
      const save = await saveObjective(
        {
          ...rest,
          ...(dream_report !== undefined
            ? { dream_report: { source: "direct" as const, input: dream_report } }
            : {}),
        },
        objectiveSaveDepsFor(pi, ctx, gating),
      );
      activateBudgetIfLinked(pi, save);
      return objectiveSaveResultOf(ctx, save);
    },
  });

  registerPerkCommand(pi, "objective-save", {
    description:
      "Save the working objective draft to GitHub — the manual failsafe for the approval→save " +
      "flow (artifact-first; drives the structured save only when no draft exists).",
    handler: async (args, ctx) => {
      const title = args.trim() || undefined;
      // The artifact-first manual-failsafe invocation of the shared approval→save
      // seam (the D1a gate exit lives in the seam). The drive-the-session fallback covers
      // draft-LESS sessions — objectives have no transcript scrape by design, so a draftless
      // session still needs a working save path.
      const outcome = await objectiveApprovalSaveV1(pi, ctx, gating, { title });
      if (outcome.status === "refused-draft") {
        // Fail-closed stop: the command's own precondition is a VALID draft — no gate exit,
        // no driven turn (those fallbacks are for draft-LESS sessions; driving a fresh
        // model-authored save over a corrupted artifact would silently abandon its bytes).
        report(
          ctx,
          "objective-save",
          "error",
          `the working objective draft is invalid: ${outcome.problem} — rewrite it with ` +
            "objective_draft, then re-run /objective-save",
        );
        return;
      }
      if (outcome.status === "no-draft") {
        // Exit the read-only gate so the objective_save tool (excluded from READ_ONLY_TOOLS)
        // becomes reachable on the driven turn, then drive the turn (mirrors /address and
        // /objective-plan).
        if (gating.isActive()) gating.exit(ctx);
        report(ctx, "objective-save", "info", "handing the structured save to the session");
        // The perk-objective-author pointer rides the skill-binding suffix (D5) since a
        // warm /objective-save outside a stage:objective-author session gets none from Mechanism A.
        pi.sendUserMessage(
          objectiveSaveGuidance(title) + bindingSuffix(ctx.cwd, "stage:objective-author"),
        );
        return;
      }
      // Saved or save-failed: relay the save message. No node-link sub-step on the objective path,
      // so the severity ladder is simpler than /plan-save's (no warning tier).
      const result = outcome.result;
      const message = result.content[0]?.text ?? "objective-save done";
      const severity: Severity = result.details.ok ? "info" : "error";
      report(ctx, "objective-save", severity, message);
    },
  });
}
