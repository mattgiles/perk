// The warm `gist_save` door, the gist mirror of objectiveSave.ts. The in-session twin of the
// Python cold door (`perk gist create`): a deterministic, terminating tool + command that WRAP
// the existing storage — they do NOT reimplement the backend write. `saveGist()` delegates to
// `perk gist create --json` via the shared cold-door client (`runColdDoor`, the prose rides the
// run-scratch stdin channel). Unlike the plan/objective twins there is NO session linkage after
// the save — nothing consumes a gist in-session (adoption happens later via the cold doors), so
// a successful save just relays the envelope's id/url/consumption story.
//
// APPROVAL→SAVE ORCHESTRATION (mirroring objectiveSave.ts's `objectiveApprovalSave`). The
// exported `gistApprovalSave` seam is the shared APPROVED-review → save flow: re-read the
// artifact (`readGistDraft` — never the rendered markdown, never the transcript) → `saveGist` →
// D1a gate exit on a successful save (snapshot `gating.isActive()` BEFORE the save; a failed
// save leaves the gate ON). `plan_review`'s gist arm (planReview.ts) wires its APPROVED outcome
// into it; the `/gist-save` command is the artifact-first MANUAL FAILSAFE invocation of the same
// seam, keeping the legacy drive-the-session behavior as the no-draft fallback (gists have no
// transcript scrape by design).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
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
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report, type Severity } from "../surfaces/report.ts";
import { decodeGistSaveParams, GIST_SCOPES, type GistScope, readGistDraft } from "./gistDraft.ts";

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface GistSaveOk {
  /** `id` is the opaque string gist id (GitHub "7", Linear "ENG-7"/project id) — §8.21. */
  gist: { id: string; url: string };
  scope: string | null;
  existed: boolean | null;
}

export type GistSaveResult = Result<GistSaveOk>;

/** The decoded `perk gist create --json` payload slice the warm door consumes. */
interface GistCreatePayload {
  gist: { id: string; url: string; existed: boolean | undefined };
  scope: string | undefined;
}

/** Narrow the `perk gist create --json` success payload; strict on `gist`. */
function decodeGistCreate(payload: ColdJson): GistCreatePayload | null {
  const gist = objectField(payload, "gist");
  if (gist === undefined) return null;
  const id = stringField(gist, "id");
  const url = stringField(gist, "url");
  if (id === undefined || url === undefined) return null;
  return {
    gist: { id, url, existed: booleanField(gist, "existed") },
    scope: stringField(payload, "scope"),
  };
}

/** The consumption pointer relayed after a save — the adoption door matching the saved scope. */
function consumptionHint(id: string, scope: string | undefined): string {
  return scope === "objective"
    ? `Consume with: perk objective author --from ${id}`
    : `Consume with: perk plan from ${id}`;
}

/**
 * The single save implementation both surfaces call. Delegates the backend write to the Python
 * cold door (which owns scope resolution: an explicit `scope` wins, else the launch handoff's
 * pre-seeded `gist_scope`, else `plan`). Returns a soft result (never throws); failures set
 * `details.ok = false`. No session linkage on success — nothing consumes a gist in-session.
 */
export async function saveGist(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: { prose: string; title?: string; scope?: GistScope },
): Promise<GistSaveResult> {
  const fail = failFor(ctx, "gist-save");

  const prose = opts.prose.trim();
  if (!prose) return fail("no gist prose to save (draft the gist first)", "invalid_input");
  if (opts.scope !== undefined && !(GIST_SCOPES as readonly string[]).includes(opts.scope)) {
    return fail("scope must be plan or objective", "invalid_input");
  }

  const runId = rebuildWorkflowState(branchOf(ctx)).run_id ?? "";

  const args = ["gist", "create", "--json"];
  if (opts.title) args.push("--title", opts.title);
  if (opts.scope) args.push("--scope", opts.scope);
  if (runId) args.push("--run-id", runId);
  const r = await runColdDoor<GistCreatePayload>(pi, ctx, args, {
    label: "perk gist create",
    decode: decodeGistCreate,
    stdin: { flag: "--body", content: prose, filename: "gist.md" },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  const gist = r.data.gist;
  const verb = gist.existed ? "Found existing" : "Saved";
  return ok(
    `${verb} gist ${gist.id} → ${gist.url}\n${consumptionHint(gist.id, r.data.scope)}`,
    {
      gist: { id: gist.id, url: gist.url },
      scope: r.data.scope ?? null,
      existed: gist.existed ?? null,
    },
    { terminate: true },
  );
}

/** The approval→save orchestration outcome (the gist `ApprovalSaveOutcome`). */
export type GistApprovalSaveOutcome =
  | { status: "no-draft" }
  | { status: "saved" | "save-failed"; result: GistSaveResult; gateExited: boolean };

/**
 * The shared approval→save orchestration seam (the gist sibling of objectiveSave.ts's
 * `objectiveApprovalSave`): an APPROVED gist review (`plan_review`'s gist arm) and the manual
 * `/gist-save` failsafe both run THIS. Flow: re-read the draft artifact at save time
 * (`readGistDraft` — never the rendered markdown, never in-hand bytes) → `saveGist` → gate exit
 * on a successful save while read-only (the D1a pattern: snapshot `gating.isActive()` before the
 * save; a failed save leaves the gate ON). No draft → `no-draft` (nothing saved, the gate
 * untouched); callers render their own fallback. Title/scope precedence: explicit opts win; else
 * the draft's; else the cold door derives/defaults. The returned result keeps `saveGist`'s
 * `terminate: true` for tool-path callers.
 */
export async function gistApprovalSave(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  opts: { title?: string } = {},
): Promise<GistApprovalSaveOutcome> {
  const draft = readGistDraft(ctx);
  if (draft === null) return { status: "no-draft" };
  // D1a: snapshot the gate BEFORE the save; on success, exit it so save marks the read-only →
  // read-write boundary in one gesture. A failed save leaves the gate on.
  const wasReadOnly = gating.isActive();
  const result = await saveGist(pi, ctx, {
    prose: draft.prose,
    title: opts.title ?? draft.title,
    scope: draft.scope,
  });
  let gateExited = false;
  if (result.details.ok && wasReadOnly) {
    gating.exit(ctx);
    gateExited = true;
  }
  return { status: result.details.ok ? "saved" : "save-failed", result, gateExited };
}

const TOOL_GUIDELINES = [
  "Use gist_save only after the gist says what it means; it creates the tracked gist in the issue backend and ends the turn.",
  "Pass gist_save the statement-of-intent PROSE in `prose` — problem-focused, with at most high-level solution leanings; no implementation steps or roadmap.",
  "Pass gist_save's `scope` only once the consumption tier is settled (plan or objective); omit it to keep the pre-seeded/default scope.",
];

/**
 * The seed guidance the warm `/gist-save` injects to drive the save (the perk-gist-author skill
 * pointer rides the skill-binding suffix — not hardcoded here). Pure + exported for offline
 * tests.
 */
export function gistSaveGuidance(title?: string): string {
  const named = title?.trim() || "";
  return render("stages/gist-save.md", { title: named });
}

/** Register the warm door: the `gist_save` tool (canonical) + the `/gist-save` twin. */
export function registerGistSave(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "gist_save",
    label: "Save gist",
    description:
      "Persist a drafted gist (a statement of intent) to the issue backend as a tracked " +
      "perk:gist. Terminating: ends the turn on save. Call only when the gist says what it " +
      "means.",
    promptSnippet: "Save the converged gist to the issue backend (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["prose"],
      properties: {
        prose: {
          type: "string",
          description:
            "The gist prose (the problem-space intent: what we want, why it matters, what " +
            "bounds it, and any high-level solution leanings — no implementation steps).",
        },
        title: {
          type: "string",
          description: "Optional gist title (defaults to the prose's first heading).",
        },
        scope: {
          type: "string",
          enum: [...GIST_SCOPES],
          description:
            "Optional consumption tier: plan (plan-sized intent) or objective (objective-sized).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodeGistSaveParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "gist-save",
          "gist_save",
        )(
          "gist_save needs { prose: string, scope?: plan|objective } per the tool schema",
          "bad_input",
        );
      }
      return saveGist(pi, ctx, decoded);
    },
  });

  registerPerkCommand(pi, "gist-save", {
    description:
      "Save the working gist draft to the issue backend — the manual failsafe for the " +
      "approval→save flow (artifact-first; drives the save only when no draft exists).",
    handler: async (args, ctx) => {
      const title = args.trim() || undefined;
      // The artifact-first manual-failsafe invocation of the shared approval→save seam (the D1a
      // gate exit lives in the seam). The legacy drive-the-session behavior is kept as the
      // NO-DRAFT fallback — gists have no transcript scrape by design, so a draftless session
      // still needs a working save path.
      const outcome = await gistApprovalSave(pi, ctx, gating, { title });
      if (outcome.status === "no-draft") {
        // Exit the read-only gate so the gist_save tool (excluded from READ_ONLY_TOOLS) becomes
        // reachable on the driven turn, then drive the turn (mirrors /objective-save).
        if (gating.isActive()) gating.exit(ctx);
        report(ctx, "gist-save", "info", "handing the save to the session");
        // The perk-gist-author pointer rides the skill-binding suffix (D5) since a warm
        // /gist-save outside a stage:gist-author session gets none from Mechanism A.
        pi.sendUserMessage(gistSaveGuidance(title) + bindingSuffix(ctx.cwd, "stage:gist-author"));
        return;
      }
      // Saved or save-failed: relay the save message (which carries the consumption hint).
      const result = outcome.result;
      const message = result.content[0]?.text ?? "gist-save done";
      const severity: Severity = result.details.ok ? "info" : "error";
      report(ctx, "gist-save", severity, message);
    },
  });
}
