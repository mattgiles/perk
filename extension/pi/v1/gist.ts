// The v1 Pi installer for the gist feature (module-contracts.md's named-installer shape):
// `installGistBindings` owns every gist registration — the `gist_draft`/`gist_save` tools, the
// `/gist-save` command, and the gist-authoring context hook pair — with baseline-exact
// registration metadata; `runGistReviewV1` is the injected `plan_review` gist arm. The feature
// logic lives in `authoring/gist/`; this module decodes at the tool boundary, builds the
// provider/backend/gate adapters, constructs the warm-door Result envelopes, and places the
// feature-owned prose units in Pi fields.
//
// Provider vocabulary is translated AT the adapter: plannotator's `# Direct Edits` feedback
// convention becomes the feature's `approvedDirectEdits` variant here, and the first-party editor review
// runs through the shared review-surface machinery (`pi/v1/review.ts` — the leaf every review
// arm composes; the review door's stage dispatcher imports this module's arm directly).
//
// The gist-authoring injection dedups on the COMPACTION-ACTIVE window
// (`branchCarries(activeContextWindow(branch), marker)` — the bindingDelivery composition): a
// live copy suppresses re-injection, and compaction dropping it from model context re-injects
// on the next turn even though the historical entry still sits on the branch.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  GIST_AUTHOR_STAGE,
  GIST_DRAFT_ARTIFACT,
  GIST_SCOPES,
  type GistScope,
  reviseGistDraft,
} from "../../authoring/gist/draft.ts";
import {
  GIST_AUTHOR_CONTEXT_TYPE,
  GIST_AUTHOR_MARKER,
  GIST_DRAFT_TOOL_GUIDELINES,
  GIST_SAVE_TOOL_GUIDELINES,
  gistAuthoringContextContent,
} from "../../authoring/gist/prose.ts";
import {
  type GistDraftReviewer,
  type GistReviewOutcome,
  reviewGist,
} from "../../authoring/gist/review.ts";
import {
  type GistBackend,
  type GistGate,
  gistApprovalSave,
  type SaveGistOutcome,
  saveGist,
} from "../../authoring/gist/save.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { loadPerkConfig } from "../../substrate/config.ts";
import { render } from "../../substrate/prompts.ts";
import { failFor, ok, type Result } from "../../substrate/result.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { paramsOf, stringParam } from "../../substrate/toolParams.ts";
import {
  activeContextWindow,
  type BranchEntry,
  branchCarries,
  branchOf,
  rebuildWorkflowState,
} from "../../substrate/workflowState.ts";
import { report, type Severity } from "../../surfaces/report.ts";
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

// ------------------------------------------------------------------- the tool-boundary decode

/** The decoded `gist_save` tool params (shared with `gist_draft`). */
export interface GistSaveParams {
  prose: string;
  title?: string;
  scope?: GistScope;
}

/**
 * Decode unknown `gist_save` tool-call params (the tool-boundary seam). `prose` absent decodes
 * to `""` (so `saveGist`'s "no gist prose to save" `invalid_input` arm keeps owning that
 * message) but present-but-mistyped → null (strict-fail); a present `scope` outside the enum is
 * likewise a strict-fail (the schema already declares the enum — a bad value means a malformed
 * call, never a silent default).
 */
export function decodeGistSaveParams(params: unknown): GistSaveParams | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const prose = stringParam(p, "prose");
  const title = stringParam(p, "title");
  const scope = stringParam(p, "scope");
  if (prose === null || title === null || scope === null) return null;
  if (scope !== undefined && !(GIST_SCOPES as readonly string[]).includes(scope)) return null;
  return { prose: prose ?? "", title, scope: scope as GistScope | undefined };
}

// -------------------------------------------------------------- the cold-door backend adapter

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

/**
 * The production `GistBackend` over the Python cold door (`perk gist create --json` via the
 * shared cold-door client; the prose rides the run-scratch stdin channel). The cold door owns
 * scope resolution beyond an explicit value (the launch handoff's pre-seeded `gist_scope`, else
 * `plan`); `runId: null` omits `--run-id` (an identity-less save keeps working).
 */
function coldDoorGistBackend(pi: ExtensionAPI, ctx: ExtensionContext): GistBackend {
  return {
    async save(req) {
      const args = ["gist", "create", "--json"];
      if (req.title) args.push("--title", req.title);
      if (req.scope) args.push("--scope", req.scope);
      if (req.runId !== null && req.runId !== "") args.push("--run-id", req.runId);
      const r = await runColdDoor<GistCreatePayload>(pi, ctx, args, {
        label: "perk gist create",
        decode: decodeGistCreate,
        stdin: { flag: "--body", content: req.prose, filename: "gist.md" },
      });
      if (!r.ok) return { status: "failed", message: r.message, errorType: r.errorType };
      return {
        status: "saved",
        id: r.data.gist.id,
        url: r.data.gist.url,
        existed: r.data.gist.existed ?? null,
        scope: r.data.scope ?? null,
      };
    },
  };
}

/** The consumption pointer relayed after a save — the adoption door matching the saved scope. */
function consumptionHint(id: string, scope: string | undefined): string {
  return scope === "objective"
    ? `Consume with: perk objective author --from ${id}`
    : `Consume with: perk plan from ${id}`;
}

/**
 * Render a save outcome as the warm-door Result envelope (the ONE result-construction site for
 * every gist save surface — tool, command relay, review arm). A `saved` outcome renders the
 * created/found line + consumption hint and terminates; a `failed` outcome reports through the
 * `failFor` seam (byte-identical to the failure the save always rendered).
 */
function gistSaveResultOf(ctx: ExtensionContext, save: SaveGistOutcome): GistSaveResult {
  if (save.status === "failed") {
    return failFor(ctx, "gist-save")(save.message, save.errorType);
  }
  const verb = save.existed ? "Found existing" : "Saved";
  return ok(
    `${verb} gist ${save.id} → ${save.url}\n${consumptionHint(save.id, save.scope ?? undefined)}`,
    {
      gist: { id: save.id, url: save.url },
      scope: save.scope,
      existed: save.existed,
    },
    { terminate: true },
  );
}

// ------------------------------------------------------------------------- adapter plumbing

/** Open the branch-backed session (always opens; `runId: null` is the identity-less arm). */
function openSession(pi: ExtensionAPI, ctx: ExtensionContext): WorkflowSession {
  return openBranchWorkflowSession(pi, ctx);
}

/** The narrow gate slice the feature releases (D1a: exit only after a verified save). */
function gateFor(gating: ToolGating, ctx: ExtensionContext): GistGate {
  return { isActive: () => gating.isActive(), exit: () => gating.exit(ctx) };
}

/**
 * The seed guidance the warm `/gist-save` injects to drive the save (the perk-gist-author skill
 * pointer rides the skill-binding suffix — not hardcoded here). Pure + exported for offline
 * tests.
 */
export function gistSaveGuidance(title?: string): string {
  const named = title?.trim() || "";
  return render("stages/gist-save.md", { title: named });
}

/** Whether the current branch is a gist-author session (read-only gate AND stage match). */
function isGistAuthoring(gating: ToolGating, branch: readonly BranchEntry[]): boolean {
  return gating.isActive() && rebuildWorkflowState(branch).stage === GIST_AUTHOR_STAGE;
}

// ------------------------------------------------------------------------------ the installer

/**
 * Install every gist Pi binding: the gist-authoring context hook pair (the frozen hooks-ordering
 * slot index.ts calls this at), the `gist_draft` and `gist_save` tools, and the `/gist-save`
 * command — registration metadata baseline-exact. Inert outside gist sessions; never throws.
 */
export function installGistBindings(pi: ExtensionAPI, gating: ToolGating): void {
  // The gist-authoring context injection (display:false), keyed off (read-only gate AND stage
  // === gist-author). Dedup on the COMPACTION-ACTIVE window: a live copy suppresses
  // re-injection; compaction dropping it from model context re-injects on the next turn.
  pi.on("before_agent_start", async (_event, ctx) => {
    const branch = branchOf(ctx);
    if (!isGistAuthoring(gating, branch)) return;
    if (branchCarries(activeContextWindow(branch), GIST_AUTHOR_MARKER)) return;
    return {
      message: {
        customType: GIST_AUTHOR_CONTEXT_TYPE,
        content: gistAuthoringContextContent(loadPerkConfig(ctx.cwd).planAuthoring),
        display: false,
      },
    };
  });

  // Strip the stale gist-authoring marker from context once the session is no longer authoring
  // (gate off, or the stage moved on) so it never lingers — the same hygiene planMode applies.
  pi.on("context", async (event, ctx) => {
    const branch = branchOf(ctx);
    if (isGistAuthoring(gating, branch)) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === GIST_AUTHOR_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(GIST_AUTHOR_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(GIST_AUTHOR_MARKER),
          );
        }
        return true;
      }),
    };
  });

  pi.registerTool({
    name: "gist_draft",
    label: "Gist draft",
    description:
      "Write (or overwrite) the working gist draft — the statement-of-intent prose + an " +
      "optional scope hint — to the session data dir and record its provenance pointer. The " +
      "only sanctioned write surface while read-only. NOT a save — gist_save//gist-save still " +
      "persist the gist to the issue backend.",
    promptSnippet:
      "Persist the working gist draft (statement-of-intent prose) to the session data dir (full rewrite)",
    promptGuidelines: GIST_DRAFT_TOOL_GUIDELINES,
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
      // The shared param contract: the same decode as `gist_save`, so the two cannot drift.
      const decoded = decodeGistSaveParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "gist-draft",
          "gist_draft",
        )(
          "gist_draft needs { prose: string, scope?: plan|objective } per the tool schema",
          "bad_input",
        );
      }
      const fail = failFor(ctx, "gist-draft");
      const revised = reviseGistDraft(decoded, openSession(pi, ctx));
      switch (revised.status) {
        case "revised":
        case "unchanged":
          // A byte-identical rewrite short-circuits interior-side; the rendered result is
          // computed from identical content either way, so the surface stays byte-stable.
          return ok(`Gist draft written → ${revised.pointer.path} (${revised.pointer.digest})`, {
            name: GIST_DRAFT_ARTIFACT,
            path: revised.pointer.path,
            digest: revised.pointer.digest,
            bytes: revised.bytes,
            run_id: revised.pointer.run_id,
          });
        case "rejected":
          return fail(
            revised.problem,
            revised.reason === "blank_prose"
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

  pi.registerTool({
    name: "gist_save",
    label: "Save gist",
    description:
      "Persist a drafted gist (a statement of intent) to the issue backend as a tracked " +
      "perk:gist. Terminating: ends the turn on save. Call only when the gist says what it " +
      "means.",
    promptSnippet: "Save the converged gist to the issue backend (terminates the turn)",
    promptGuidelines: GIST_SAVE_TOOL_GUIDELINES,
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
      const save = await saveGist(decoded, {
        backend: coldDoorGistBackend(pi, ctx),
        runId: openSession(pi, ctx).runId,
      });
      return gistSaveResultOf(ctx, save);
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
      // The session always opens (identity-optional): an identity-less session reads the
      // draft `absent` → the no-draft fallback below, exactly the old open-absent branch.
      const session = openSession(pi, ctx);
      const outcome = await gistApprovalSave(
        { session, backend: coldDoorGistBackend(pi, ctx), gate: gateFor(gating, ctx) },
        { title },
      );
      if (outcome.status !== "no-draft") {
        // Saved or save-failed: relay the save message (which carries the consumption hint).
        const result = gistSaveResultOf(ctx, outcome.save);
        const message = result.content[0]?.text ?? "gist-save done";
        const severity: Severity = result.details.ok ? "info" : "error";
        report(ctx, "gist-save", severity, message);
        return;
      }
      // Exit the read-only gate so the gist_save tool (excluded from READ_ONLY_TOOLS) becomes
      // reachable on the driven turn, then drive the turn (mirrors /objective-save).
      if (gating.isActive()) gating.exit(ctx);
      report(ctx, "gist-save", "info", "handing the save to the session");
      // The perk-gist-author pointer rides the skill-binding suffix (D5) since a warm
      // /gist-save outside a stage:gist-author session gets none from Mechanism A.
      pi.sendUserMessage(gistSaveGuidance(title) + bindingSuffix(ctx.cwd, "stage:gist-author"));
    },
  });
}

// ------------------------------------------------------------------------ the review arm

const GIST_SUBJECT: ReviewSubject = {
  noun: "gist",
  present: "the complete gist to the user",
  presentUnavailable: "the complete gist to the user",
  implementHereWhere: "on the gist path",
  draftTool: "gist_draft",
  failsafeCmd: "/gist-save",
  detailsExtra: { subject: "gist" },
  noSourceError: "no gist draft resolved",
};

const GIST_REVIEW_EDITOR_TITLE =
  "Gist review (view only — edits are not saved) — Enter: continue to verdict · Esc: skip · " +
  "Ctrl+G: $EDITOR";

/** The gist arm's soft skip when no reviewable draft exists (byte-stable redirect). */
function noGistDraftResult(): ToolResult {
  return {
    content: [
      {
        type: "text",
        text:
          "no gist draft to review — write the working gist with gist_draft (the " +
          "statement-of-intent prose), then call plan_review again.",
      },
    ],
    details: {
      ok: false,
      error: "no gist draft to review — write it with gist_draft first",
      error_type: "no_gist_draft",
      status: "skipped",
      reason: "no_gist_draft",
    },
  };
}

/**
 * Translate a review-door outcome (`ReviewOutcome`) into the feature's `GistReviewOutcome`.
 * Plannotator's vocabulary is translated here: an approval whose feedback OPENS with the
 * `# Direct Edits` heading becomes the `approvedDirectEdits` variant (the heading check
 * suffices — the diff goes to the model verbatim either way; the variant requires the feedback,
 * so the edits can never be dropped on the save path). The `implement-here` arm is unreachable
 * on the gist path (neither reviewer offers it) and maps defensively to `dismissed`.
 */
function gistOutcomeOf(outcome: ReviewOutcome): GistReviewOutcome {
  switch (outcome.status) {
    case "completed": {
      const carried = {
        ...(outcome.feedback !== undefined ? { feedback: outcome.feedback } : {}),
        reviewId: outcome.reviewId,
      };
      if (outcome.approved) {
        if (outcome.feedback !== undefined && hasDirectEditsHeading(outcome.feedback)) {
          return { status: "approvedDirectEdits", feedback: outcome.feedback, ...carried };
        }
        return { status: "approved", ...carried };
      }
      return { status: "denied", ...carried };
    }
    case "unavailable":
      return { status: "unavailable", warning: outcome.warning };
    case "aborted":
      return { status: "aborted" };
    case "dismissed":
      return { status: "dismissed" };
    case "implement-here":
      return { status: "dismissed" };
  }
}

/** The plannotator reviewer adapter: the event-bus bridge judges the rendered draft. */
function plannotatorGistReviewer(bridge: {
  review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome>;
}): GistDraftReviewer {
  return {
    async review(rendered, signal) {
      return gistOutcomeOf(await bridge.review(rendered, signal));
    },
  };
}

/** The first-party reviewer adapter: the in-TUI editor review, VIEW-ONLY (3 verdicts). */
function firstPartyGistReviewer(ctx: ExtensionContext): GistDraftReviewer {
  return {
    async review(rendered, signal) {
      const fp = await runFirstPartyReview({
        ui: ctx.ui,
        plan: rendered,
        writeDraft: () => true, // unreachable under viewOnly — the branch is skipped
        signal,
        editorTitle: GIST_REVIEW_EDITOR_TITLE,
        verdicts: verdictsFor(GIST_SUBJECT),
        viewOnly: true,
      });
      return gistOutcomeOf(fp.outcome);
    },
  };
}

/** Rebuild the door's completed outcome from the arm result (the mappers consume it). */
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
 * The injected `plan_review` gist arm (the `GistReviewArm` shape): headless soft-skip, the
 * validated draft artifact as the SOLE review source (absent identity or absent draft → the
 * `no_gist_draft` skip), reviewer dispatch (plannotator bridge or first-party view-only
 * editor), and outcome mapping through the shared subject machinery — byte-stable with the
 * review door's results. An approval carrying Direct Edits returns the NON-terminating revise
 * round with NOTHING saved; a plain approval re-reads the artifact through `gistApprovalSave`
 * (gate released only after the verified save).
 */
export async function runGistReviewV1(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  bridge: { review(plan: string, signal?: AbortSignal): Promise<ReviewOutcome> },
  signal?: AbortSignal,
): Promise<ToolResult> {
  // Headless → soft skip (fail-open; never wedges CI/supervisor runs on an interactive UI).
  if (!ctx.hasUI) return skipResult();
  const sig = signal ?? ctx.signal;
  // The session always opens (identity-optional): an identity-less session reads the draft
  // `absent`, so `reviewGist` classifies `noDraft` — the same rendered redirect as before.
  const session = openSession(pi, ctx);
  const reviewer = isPlannotatorPlanSelected(ctx.cwd)
    ? plannotatorGistReviewer(bridge)
    : firstPartyGistReviewer(ctx);
  const result = await reviewGist(
    { session, reviewer, backend: coldDoorGistBackend(pi, ctx), gate: gateFor(gating, ctx) },
    sig,
  );
  switch (result.status) {
    case "noDraft":
      return noGistDraftResult();
    case "directEditsRevise":
      // The Direct-Edits carve-out (contracts §8.23's gist arm): rendered edits cannot be
      // folded back into the structured draft mechanically — one model-mediated revise round,
      // nothing saved, the gate untouched.
      return {
        content: [
          {
            type: "text",
            text:
              "gist APPROVED with direct browser edits — these cannot be auto-applied to the " +
              "structured draft, so nothing was saved. Fold each Direct Edits hunk below into " +
              "the matching gist_draft field (a `# <title>` heading hunk → title, a `Scope:` " +
              "line hunk → scope, prose hunks → prose), then call plan_review again to " +
              `confirm.\n\nReviewer feedback:\n${result.feedback}`,
          },
        ],
        details: {
          ok: true,
          status: "revise",
          reason: "direct_edits",
          approved: true,
          feedback: result.feedback,
          reviewId: result.reviewId,
          subject: "gist",
        },
      };
    case "approvedSaved":
      return approvedSubjectSaveResult(GIST_SUBJECT, completedOutcome(true, result), {
        status: "saved",
        result: gistSaveResultOf(ctx, result.save.save),
        gateExited: result.save.gateExited,
      });
    case "approvedSaveFailed":
      return approvedSubjectSaveResult(GIST_SUBJECT, completedOutcome(true, result), {
        status: "save-failed",
        result: gistSaveResultOf(ctx, result.save.save),
        gateExited: false,
      });
    case "approvedNoDraft":
      return approvedSubjectSaveResult(GIST_SUBJECT, completedOutcome(true, result), {
        status: "no-source",
      });
    case "denied":
      return subjectReviewOutcomeResult(GIST_SUBJECT, completedOutcome(false, result));
    case "dismissed":
      return subjectReviewOutcomeResult(GIST_SUBJECT, { status: "dismissed" });
    case "aborted":
      return subjectReviewOutcomeResult(GIST_SUBJECT, { status: "aborted" });
    case "unavailable":
      return subjectReviewOutcomeResult(GIST_SUBJECT, {
        status: "unavailable",
        warning: result.warning,
      });
  }
}
