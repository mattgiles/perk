// The warm `objective_save` door, the objective mirror of planSave.ts. The in-session twin
// of the Python cold door (`perk objective create`): a deterministic, terminating tool + command
// that WRAP the existing storage — they do NOT reimplement the GitHub write. `saveObjective()`
// passes the STRUCTURED roadmap as `--roadmap <json>` (the agent never hand-writes roadmap YAML)
// and delegates to `perk objective create --json` via the shared cold-door client (`runColdDoor`,
// the prose rides the run-scratch stdin channel), then links the live session: `active_objective` + a fresh `perk:objective-budget` activation marker
// (mirrors the `/objective <id>` activation in objective.ts). Failures are loud-but-non-fatal.
//
// APPROVAL→SAVE ORCHESTRATION (mirroring planSave.ts's `approvalSave`). The
// exported `objectiveApprovalSave` seam is the shared APPROVED-review → save flow: re-read the
// STRUCTURED artifact (`readObjectiveDraft` — never the rendered markdown, never the transcript)
// → `saveObjective` → D1a gate exit on a successful save (snapshot `gating.isActive()` BEFORE the
// save; a failed save leaves the gate ON). `plan_review`'s objective arm (planReview.ts) wires
// its APPROVED outcome into it; the `/objective-save` command is the artifact-first MANUAL
// FAILSAFE invocation of the same seam, keeping the legacy drive-the-session behavior as the
// no-draft fallback (objectives have no transcript scrape by design).

import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { atomicWriteFileSync, ensureRunScratch } from "../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { appendWorkflowState, branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report, type Severity } from "../surfaces/report.ts";
import { OBJECTIVE_BUDGET_TYPE } from "./objective.ts";
import {
  DELIVERY_PARAM_SCHEMA,
  type DeliveryChoice,
  DREAM_REPORT_PARAM_SCHEMA,
  decodeObjectiveSaveParams,
  ROADMAP_PARAM_SCHEMA,
  readObjectiveDraft,
} from "./objectiveDraft.ts";
import { resolveDreamReportGate } from "../authoring/objective/dreamReportGate.ts";

/** The `objective-save` registry stage id (the objectiveAuthor.ts constant's sibling). */
export const OBJECTIVE_SAVE_STAGE = "objective-save";

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
 * The single save implementation both surfaces call. Delegates the GitHub write to the Python cold
 * door, then links the live session (`active_objective` + budget marker). Returns a soft result
 * (never throws); failures set `details.ok = false` and append no linkage.
 *
 * `dream_report` is ONE carrier with two sources (§8.63): the direct tool path supplies
 * `{input}` and the save stamps `generated_at`; the approval path passes the artifact block
 * through with its stored stamp AND stored parts — the stored parts are byte-compared against
 * the freshly re-rendered ones, so run-scratch drift or artifact tamper between draft-write
 * and save refuses `bad_state` (nothing saved, the gate stays on). On the dream arm the
 * reviewed CANONICAL parts cross to the Python plane through the run-scoped
 * `dream-report-transfer.json` handoff (§8.64) — staged atomically before the cold door (a
 * write failure is the soft `scratch_failed` refusal; the door is not invoked) — and
 * `perk objective create` re-validates the transfer and converges the companion idempotently.
 */
export async function saveObjective(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: {
    prose: string;
    title?: string;
    roadmap?: unknown[];
    base?: string;
    delivery?: DeliveryChoice;
    dream_report?: { input: unknown; generated_at?: string; parts?: string[] };
  },
): Promise<ObjectiveSaveResult> {
  const fail = failFor(ctx, "objective-save");

  const prose = opts.prose.trim();
  if (!prose)
    return fail("no objective prose to save (draft the objective first)", "invalid_input");
  if (opts.roadmap !== undefined && !Array.isArray(opts.roadmap)) {
    return fail("roadmap must be a JSON array of nodes", "invalid_input");
  }

  // The §8.63 fail-closed re-validation, before anything reaches the cold door. Presence is
  // the `opts.dream_report === undefined` boundary — an `{input: undefined}` carrier is never
  // constructed (the execute wraps only a present decoded value; the approval path passes the
  // validated artifact block).
  const generatedAt = opts.dream_report?.generated_at ?? new Date().toISOString();
  const gate =
    opts.dream_report === undefined
      ? resolveDreamReportGate(ctx, undefined, generatedAt)
      : resolveDreamReportGate(ctx, opts.dream_report.input, generatedAt);
  if (gate.kind === "refuse") {
    return fail(gate.detail, gate.errorType);
  }
  if (gate.kind === "block" && opts.dream_report?.parts !== undefined) {
    // The approval path: the reviewed (stored) parts must byte-match the re-render against
    // freshly recovered context — the same stored `generated_at` stamp keeps the comparison
    // deterministic.
    if (JSON.stringify(gate.block.parts) !== JSON.stringify(opts.dream_report.parts)) {
      return fail(
        "the reviewed report no longer matches the wave state — re-draft and re-review",
        "bad_state",
      );
    }
  }

  const branch = () => branchOf(ctx);
  const runId = rebuildWorkflowState(branch()).run_id ?? "";

  if (gate.kind === "block") {
    // The §8.64 transfer write (the dream arm only): the reviewed CANONICAL parts cross to the
    // Python save door through the run-scoped scratch handoff — written atomically BEFORE the
    // cold door is invoked. A write failure is the soft `scratch_failed` failure (the
    // runColdDoor stdin-staging precedent): the cold door is NOT invoked, nothing activates,
    // and the read-only gate stays on. Non-dream saves write nothing (byte-identical).
    try {
      const dir = ensureRunScratch(ctx.cwd, runId);
      const content = `${JSON.stringify(
        { schema_version: "1", run_id: runId, parts: gate.block.parts },
        null,
        2,
      )}\n`;
      atomicWriteFileSync(join(dir, DREAM_REPORT_TRANSFER_FILENAME), content);
    } catch (err) {
      return fail(`could not stage the dream-report transfer: ${String(err)}`, "scratch_failed");
    }
  }

  const args = ["objective", "create", "--json"];
  if (opts.title) args.push("--title", opts.title);
  if (opts.base) args.push("--base", opts.base);
  // The reviewed delivery choice rides verbatim; the cold door owns validation + preflight.
  if (opts.delivery) args.push("--delivery", opts.delivery);
  if (runId) args.push("--run-id", runId);
  if (opts.roadmap && opts.roadmap.length > 0) {
    args.push("--roadmap", JSON.stringify(opts.roadmap));
  }
  const r = await runColdDoor<ObjectiveCreatePayload>(pi, ctx, args, {
    label: "perk objective create",
    decode: decodeObjectiveCreate,
    stdin: { flag: "--body", content: prose, filename: "objective.md" },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Link the live session: set active_objective (LWW) + seed a fresh budget activation marker
  // (mirrors objective.ts's `/objective <id>` activation), so budget tracking starts immediately.
  // The envelope id is already the opaque string id (§8.21) — no coercion needed.
  const objective = r.data.objective;
  const objectiveId = objective.id;
  const linked = rebuildWorkflowState(branch()).active_objective ?? null;
  if (linked !== objectiveId) {
    appendWorkflowState(pi, ctx, {
      data: { active_objective: objectiveId },
      field: "active_objective",
      expected: objectiveId,
      scope: "objective-save",
      failure: `active_objective read-back failed for #${objectiveId}`,
    });
    pi.appendEntry(OBJECTIVE_BUDGET_TYPE, {
      objective_id: objectiveId,
      activated_at: new Date().toISOString(),
    });
  }

  const verb = objective.existed ? "Found existing" : "Saved";
  return ok(
    `${verb} objective #${objective.id} → ${objective.url}`,
    {
      objective: { id: objective.id, url: objective.url },
      existed: objective.existed ?? null,
    },
    { terminate: true },
  );
}

/** The approval→save orchestration outcome (the objective `ApprovalSaveOutcome`). */
export type ObjectiveApprovalSaveOutcome =
  | { status: "no-draft" }
  | { status: "saved" | "save-failed"; result: ObjectiveSaveResult; gateExited: boolean };

/**
 * The shared approval→save orchestration seam (the objective sibling of
 * planSave.ts's `approvalSave`): an APPROVED objective review (`plan_review`'s objective arm)
 * and the manual `/objective-save` failsafe both run THIS. Flow: re-read the STRUCTURED draft
 * artifact at save time (`readObjectiveDraft` — never the rendered markdown, never in-hand
 * bytes) → `saveObjective` → gate exit on a successful save while read-only (the D1a pattern:
 * snapshot `gating.isActive()` before the save; a failed save leaves the gate ON). No draft →
 * `no-draft` (nothing saved, the gate untouched); callers render their own fallback. Title
 * precedence: an explicit `opts.title` wins; else the draft's `title`; else the cold door
 * derives from the prose heading. The returned result keeps `saveObjective`'s `terminate: true`
 * for tool-path callers.
 */
export async function objectiveApprovalSave(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { title?: string } = {},
): Promise<ObjectiveApprovalSaveOutcome> {
  const draft = readObjectiveDraft(ctx);
  if (draft === null) return { status: "no-draft" };
  // D1a: snapshot the gate BEFORE the save; on success, exit it so save marks the read-only →
  // read-write boundary in one gesture. A failed save leaves the gate on.
  const wasReadOnly = gating.isActive();
  const result = await saveObjective(pi, ctx, {
    prose: draft.prose,
    title: opts.title ?? draft.title,
    roadmap: draft.roadmap,
    base: draft.base,
    delivery: draft.delivery,
    // The approval path passes the artifact block through whole — stored stamp + stored parts
    // (the save re-validates and byte-compares, §8.63).
    ...(draft.dream_report !== undefined ? { dream_report: draft.dream_report } : {}),
  });
  let gateExited = false;
  if (result.details.ok && wasReadOnly) {
    gating.exit(ctx);
    gateExited = true;
  }
  return { status: result.details.ok ? "saved" : "save-failed", result, gateExited };
}

const TOOL_GUIDELINES = [
  "Use objective_save only after the objective + roadmap are decision-complete; it creates the canonical perk:objective issue, activates it, and ends the turn.",
  "Pass objective_save the objective PROSE in `prose` and the STRUCTURED roadmap in `roadmap` (a JSON array of nodes) — never hand-write roadmap YAML.",
  'Each objective_save roadmap node needs a stable `id` (e.g. "1.1") and a `description`; `status` defaults to pending. Use `depends_on` for explicit ordering.',
];

/**
 * The seed guidance the warm `/objective-save` injects to drive the structured save (the
 * perk-objective-author skill pointer rides the skill-binding suffix — not hardcoded
 * here). Pure + exported for offline tests.
 */
export function objectiveSaveGuidance(title?: string): string {
  const named = title?.trim() || "";
  return render("stages/objective-save.md", { title: named });
}

/** Register the warm door: the `objective_save` tool (canonical) + the `/objective-save` twin. */
export function registerObjectiveSave(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "objective_save",
    label: "Save objective",
    description:
      "Persist a drafted objective + structured roadmap to GitHub as a perk:objective issue, " +
      "activate it, and start budget tracking. Terminating: ends the turn on save. Call only when " +
      "the objective and roadmap are decision-complete.",
    promptSnippet: "Save the decision-complete objective + roadmap to GitHub (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
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
      // The direct tool path wraps ONLY a present decoded value as the `{input}` carrier (the
      // save stamps generated_at); no stored parts, so no byte-compare on this path.
      const { dream_report, ...rest } = decoded;
      return saveObjective(pi, ctx, {
        ...rest,
        ...(dream_report !== undefined ? { dream_report: { input: dream_report } } : {}),
      });
    },
  });

  registerPerkCommand(pi, "objective-save", {
    description:
      "Save the working objective draft to GitHub — the manual failsafe for the approval→save " +
      "flow (artifact-first; drives the structured save only when no draft exists).",
    handler: async (args, ctx) => {
      const title = args.trim() || undefined;
      // The artifact-first manual-failsafe invocation of the shared approval→save
      // seam (the D1a gate exit lives in the seam). The legacy drive-the-session behavior is kept
      // as the NO-DRAFT fallback — objectives have no transcript scrape by design, so a draftless
      // session still needs a working save path.
      const outcome = await objectiveApprovalSave(pi, ctx, gating, { title });
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
