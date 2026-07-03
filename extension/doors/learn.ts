// The warm `/learn` door — a multi-angle knowledge-capture orchestrator (mirrors `/pr-review`).
//
// Bare interactive `/learn` gathers a reproducible evidence bundle ONCE via the cold door
// (`perk learn evidence --render --json`; the parent owns the gather per §8.35), then branches:
// a learn-docs plan short-circuits to a deterministic marker-clear no-op; a gather failure (or a
// bundle-less success) degrades to the simple `learnGuidance` injection (/learn is never a dead
// end); otherwise it injects the orchestration seed (`learnOrchestrateGuidance`) so the model spawns
// 2–4 fresh-context `perk.learn-analyst` children, reconciles their reports into ONE classified
// decision, and captures (via the `learn` tool, with the routable `decision`/`target` persisted on
// the issue header — both backends) or skips.
//
// The `learn` tool is the capture half: with a `summary`, DELEGATE to `perk learn capture --json`
// via the shared cold-door client (`runColdDoor` — the body rides the run-scratch stdin channel,
// the `decision`/`target` classification rides flags; canonical write in Python), creating a
// `perk:learn` issue + clearing `pending-learn`, then mirror the marker-clear in-session
// (idempotent). With no `summary`, DELEGATE to `perk learn skip --json` (contracts.md §8.36) —
// the deliberate skip is recorded canonically on the plan-header (`learn_state: skipped`, unless
// already `captured`), never a TS-only marker-clear.
// Never throws (soft `details.ok`); both decodes are fully LENIENT — a `success: true`
// envelope always yields the terminating ok result even when the payload is undecodable
// (render-only fields; see `decodeLearnCapture` / `decodeLearnSkip`).
//
// Headless bare `/learn` stays the safe no-summary path (cannot drive a turn / spawn children).
// `/learn <text>` / `/learn skip` stay the existing verbatim-capture / skip-recording paths
// (decision-less escape hatches). Cold `perk learn` launch stays the simple investigate+capture.
//
// The analyst model is configurable via `[subagents] learn-analyst` in `.perk/config.toml`; because
// `subagents.agentOverrides` does NOT reach project agents, the orchestration seed injects that
// model as a per-call inline `model` override on every analyst spawn.

import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import {
  clearMarker,
  hasMarker,
  PENDING_LEARN,
  type PlanRef,
  readPlanRef,
} from "../substrate/cache.ts";
import {
  booleanField,
  type ColdJson,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { loadPerkConfig } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";
import { planReadInstruction } from "./lifecycleGates.ts";

/** The ok-arm fields. */
export interface LearnOk {
  was_pending: boolean;
  captured: boolean;
  /** `id` is the opaque string issue id (GitHub "42", Linear "ENG-123") — §8.21. */
  learn_issue?: { id: string; url: string; existed: boolean };
}

export type LearnResult = Result<LearnOk>;

/** The decoded `perk learn capture --json` payload slice the warm door consumes. */
interface LearnCapturePayload {
  learn_issue?: { id: string; url: string; existed: boolean };
}

/** The decoded `perk learn skip --json` payload slice (render-only fields). */
interface LearnSkipPayload {
  learn_state: string | null;
  pending_cleared: boolean | null;
}

/**
 * Decode the `perk learn skip --json` success payload — fully LENIENT (mirrors `decodeEvidence`):
 * it **never returns null**, so any success envelope yields a usable object and the `bad_output`
 * arm is deliberately unreachable for this door. Both fields are render-only (they flavor the
 * report text); the `success: true` envelope is the cold door's authoritative statement that the
 * skip was recorded and the on-disk marker cleared.
 */
function decodeLearnSkip(payload: ColdJson): LearnSkipPayload {
  return {
    learn_state: stringField(payload, "learn_state") ?? null,
    pending_cleared: booleanField(payload, "pending_cleared") ?? null,
  };
}

/**
 * The closed CAPTURED-classification set persisted on a `perk:learn` header (contracts.md §8.35) —
 * the reconciliation DECISION set minus `SKIP` (a skip creates no issue). Mirrors
 * `plan.CapturedDecision` (the Python SSOT) and the `learn` tool's JSON-schema enum.
 */
const CAPTURED_DECISIONS = [
  "CAPTURE_LEARN",
  "SHOULD_BE_CODE",
  "UPDATE_EXISTING_DOC",
  "NEW_DOC",
  "STALE_DOC",
] as const;

/** The decoded `perk learn evidence --json` slice the orchestrator branches on. */
interface EvidenceDecode {
  skipped: boolean;
  skip_reason: string | null;
  bundle_dir: string | null;
}

/**
 * Decode the `perk learn evidence --render --json` success payload — fully LENIENT (mirrors
 * `decodeLearnCapture`): it **never returns null**, so any success envelope yields a usable object
 * and the `runColdDoor` `bad_output` arm is deliberately unreachable for this door. A missing/
 * mistyped `skipped` defaults false; `bundle_dir`/`skip_reason` default null. `!r.ok` (exec /
 * transport / `success:false`) routes to the gather-failure fallback, not here.
 */
function decodeEvidence(payload: ColdJson): EvidenceDecode {
  return {
    skipped: booleanField(payload, "skipped") ?? false,
    skip_reason: stringField(payload, "skip_reason") ?? null,
    bundle_dir: stringField(payload, "bundle_dir") ?? null,
  };
}

/**
 * Narrow the `perk learn capture --json` success payload — fully LENIENT, per the decode-policy
 * criterion (strict iff the field is appended to workflow-state; see
 * `docs/learned/workflow/cold-door-client.md`). `learn_issue` is render-only — it feeds only the
 * success message text and `details` — and the `success: true` envelope is the cold door's
 * authoritative statement that the capture mutation completed and the on-disk `pending-learn`
 * marker was already cleared. So any miss on the sub-object (absent key, a legacy `number` shape,
 * mistyped fields — e.g. under CLI↔extension version skew) yields
 * `{ learn_issue: undefined }`, never null: the warm report must survive an undecodable payload,
 * and the `bad_output` arm is deliberately unreachable for this door. `pending_cleared` is
 * unconsumed.
 */
function decodeLearnCapture(payload: ColdJson): LearnCapturePayload {
  const issue = objectField(payload, "learn_issue");
  if (issue === undefined) return { learn_issue: undefined };
  const id = stringField(issue, "id");
  const url = stringField(issue, "url");
  const existed = booleanField(issue, "existed");
  if (id === undefined || url === undefined || existed === undefined) {
    return { learn_issue: undefined };
  }
  return { learn_issue: { id, url, existed } };
}

/** Clear `pending-learn` (idempotent — a no-op if it was not set). Reports whether it was set. */
function clearPending(ctx: ExtensionContext): { wasPending: boolean } {
  const wasPending = hasMarker(ctx.cwd, PENDING_LEARN);
  clearMarker(ctx.cwd, PENDING_LEARN);
  return { wasPending };
}

/**
 * The single learn implementation both surfaces call. With a `summary`, delegate the capture to
 * the Python cold door; without one, delegate the skip-recording to `perk learn skip` (§8.36 —
 * the canonical `learn_state: skipped` stamp, no empty issue). Both arms mirror the marker-clear
 * in-session on success. Returns a soft result (never throws).
 */
export async function learnDone(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  summary?: string,
  decision?: string,
  target?: string,
): Promise<LearnResult> {
  const trimmed = (summary ?? "").trim();
  const fail = failFor(ctx, "learn");

  // No summary: record the deliberate skip canonically (the cold door stamps the plan-header and
  // clears the marker; the skip carries no classification, so `decision`/`target` are
  // intentionally ignored on this arm). On failure the marker is NOT cleared — never silently
  // close the learn cycle on uncertainty (the marker is the retry signal).
  if (trimmed.length === 0) {
    const r = await runColdDoor<LearnSkipPayload>(pi, ctx, ["learn", "skip", "--json"], {
      label: "perk learn skip",
      decode: decodeLearnSkip,
    });
    if (!r.ok) return fail(r.message, r.errorType);
    // Mirror the marker-clear in-session (idempotent; the worker already cleared it on disk).
    const { wasPending } = clearPending(ctx);
    const text =
      r.data.learn_state === "captured"
        ? "Learnings were already captured — kept; pending-learn cleared."
        : "Skip recorded on the plan; pending-learn cleared — the worktree is releasable. " +
          "(No summary given; no learn issue created.)";
    return ok(text, { was_pending: wasPending, captured: false }, { terminate: true });
  }

  // The captured classification (contracts.md §8.35) rides flags on the capture argv; Click parses
  // them regardless of order, and the `--body` stdin channel is unchanged.
  const argv = ["learn", "capture", "--json"];
  if (decision !== undefined) argv.push("--decision", decision);
  if (target !== undefined) argv.push("--target", target);

  const r = await runColdDoor<LearnCapturePayload>(pi, ctx, argv, {
    label: "perk learn capture",
    decode: decodeLearnCapture,
    stdin: { flag: "--body", content: `${trimmed}\n`, filename: `learn-${Date.now()}.md` },
  });
  if (!r.ok) return fail(r.message, r.errorType);

  // Mirror the marker-clear in-session (idempotent; the worker also cleared it on disk). Runs
  // even when `learn_issue` is undecodable — a success envelope clears the marker.
  const { wasPending } = clearPending(ctx);
  const issue = r.data.learn_issue;
  if (issue === undefined) {
    return ok(
      "Captured learnings; pending-learn cleared. (learn issue details undecodable — the perk " +
        "CLI and the perk extension may be version-skewed.)",
      { was_pending: wasPending, captured: true },
      { terminate: true },
    );
  }
  const verb = issue.existed ? "Found existing" : "Created";
  return ok(
    `${verb} learn issue #${issue.id}; pending-learn cleared.`,
    { was_pending: wasPending, captured: true, learn_issue: issue },
    { terminate: true },
  );
}

const TOOL_GUIDELINES = [
  "Call learn after a plan has landed; pass a `summary` of the durable learnings to capture them in a perk:learn issue (and clear pending-learn). Omit `summary` to record the skip on the plan and clear the marker.",
  "The summary is captured verbatim — write the learnings as markdown (what changed vs. the plan, deviations, residual risks).",
];

/** Resolve the active plan-ref (worktree first, then the rebuilt workflow-state). */
function activePlanRef(ctx: ExtensionContext): PlanRef | null {
  const fromWorktree = readPlanRef(ctx.cwd);
  if (fromWorktree) return fromWorktree;
  try {
    const branch = branchOf(ctx);
    return (rebuildWorkflowState(branch).active_plan_ref as PlanRef | null) ?? null;
  } catch {
    return null;
  }
}

/**
 * Inject the learn-workflow guidance the model follows (the perk-learn skill pointer rides the
 * skill-binding suffix — not hardcoded here). The wording lives in the canonical template
 * `prompts/stages/learn.md`, rendered identically by both planes via the shared render seam
 * (contracts.md §8.31); the github/linear/other/no-ref branching is the template conditional on
 * `provider` (+ `pr_id` presence), and `read_cmd` is the node-2.1 plan-read instruction. Unified
 * onto the cold `_learn_prompt` body — byte-identical to it for every provider arm (the four
 * `learn-*` golden cases are the cross-plane parity proof). When no plan-ref is known, render the
 * no-ref arm (learn can proceed without a ref — no dead-end null-guard).
 */
export function learnGuidance(planRef: PlanRef | null): string {
  if (planRef === null) {
    return render("stages/learn.md", { provider: "", pr_id: "", url: "", read_cmd: "" });
  }
  const read_cmd = planReadInstruction(planRef.provider, planRef.pr_id, planRef.url);
  return render("stages/learn.md", {
    provider: planRef.provider,
    pr_id: planRef.pr_id,
    url: planRef.url,
    read_cmd,
  });
}

/**
 * The orchestration seed the warm bare `/learn` injects to spawn the angle-specialized analysts and
 * reconcile their reports into one classified capture/skip (the perk-learn skill pointer rides the
 * skill-binding suffix — stage:learn — not hardcoded here). Pure + exported for offline tests
 * (mirrors `prReviewGuidance`). When `model` is set, EVERY analyst spawn carries an inline `model`
 * override; otherwise the agent's default is used. `manifestPath` is absolute; `bundleDir` is the
 * absolute bundle directory.
 */
export function learnOrchestrateGuidance(opts: {
  model?: string;
  manifestPath: string;
  bundleDir: string;
}): string {
  return render("stages/learn-orchestrate.md", {
    model: opts.model ?? "",
    manifest_path: opts.manifestPath,
    bundle_dir: opts.bundleDir,
  });
}

/** Register the warm door: the `learn` terminating tool + the `/learn` command twin. */
export function registerLearn(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "learn",
    label: "Finish learn",
    description:
      "Capture learnings from a landed plan into a perk:learn issue (pass `summary`), then clear " +
      "the pending-learn semaphore and release the worktree. Omit `summary` to record the skip " +
      "on the plan and clear pending-learn. Terminating: ends the turn.",
    promptSnippet:
      "Capture learnings (optional summary) and clear pending-learn (terminates the turn)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        summary: {
          type: "string",
          description:
            "Markdown learnings to capture in a perk:learn issue. Omit to record the skip.",
        },
        decision: {
          type: "string",
          enum: [...CAPTURED_DECISIONS],
          description:
            "The reconciled captured-classification token, persisted on the perk:learn header. " +
            "Omit on a verbatim /learn <text> capture (the decision-less escape hatch).",
        },
        target: {
          type: "string",
          description:
            "An optional routable pointer (e.g. an existing doc path) for the classification.",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // Tool-boundary decode (mirrors the `summary` strictness): absent → undefined (the
      // marker-clear / decision-less path); a present-but-mistyped/out-of-enum value →
      // strict-fail — never silently clear the pending-learn marker on uncertainty.
      const p = paramsOf(params);
      const fail = failFor(ctx, "learn");
      const summary = p === null ? undefined : stringParam(p, "summary");
      if (summary === null) {
        return fail("learn `summary` must be a string", "bad_input");
      }
      const decision = p === null ? undefined : stringParam(p, "decision");
      if (decision === null) {
        return fail("learn `decision` must be a string", "bad_input");
      }
      if (decision !== undefined && !(CAPTURED_DECISIONS as readonly string[]).includes(decision)) {
        return fail(
          `learn \`decision\` must be one of ${CAPTURED_DECISIONS.join(", ")}`,
          "bad_input",
        );
      }
      const target = p === null ? undefined : stringParam(p, "target");
      if (target === null) {
        return fail("learn `target` must be a string", "bad_input");
      }
      return learnDone(pi, ctx, summary, decision, target);
    },
  });

  registerPerkCommand(pi, "learn", {
    description:
      "Investigate the landed change and capture learnings (bare /learn drives the workflow); " +
      "/learn skip records the skip on the plan and clears pending-learn; " +
      "/learn <text> captures the text verbatim.",
    handler: async (args, ctx) => {
      const trimmed = (args ?? "").trim();

      // Explicit text (or `skip`): the existing learnDone path — capture verbatim / record skip.
      if (trimmed.length > 0) {
        const summary = trimmed === "skip" ? "" : args;
        const result = await learnDone(pi, ctx, summary);
        // Failure already reported loudly via failFor (the single error surface) — success only.
        if (result.details.ok) {
          report(ctx, "learn", "info", result.content[0]?.text ?? "learn done");
        }
        return;
      }

      // Bare `/learn`: headless can't drive a turn or spawn children — take the safe no-summary
      // path (the canonical skip recording; fail-safe).
      if (!ctx.hasUI) {
        const result = await learnDone(pi, ctx, "");
        console.error(`perk: /learn invoked (headless) — ${result.content[0]?.text ?? "cleared"}`);
        return;
      }

      // Interactive bare `/learn`: the multi-angle orchestrator (mirrors /pr-review). Gather the
      // evidence bundle ONCE (the parent owns the gather — §8.35), then branch.
      const fallback = () => {
        // Graceful degrade — /learn is never a dead end. Fall back to the simple learn pass (the
        // prior behavior); the agent clears the marker itself via the `learn` tool.
        pi.sendUserMessage(
          learnGuidance(activePlanRef(ctx)) + bindingSuffix(ctx.cwd, "stage:learn"),
        );
      };

      const r = await runColdDoor<EvidenceDecode>(
        pi,
        ctx,
        ["learn", "evidence", "--render", "--json"],
        { label: "perk learn evidence", decode: decodeEvidence },
      );

      // Gather failure (exec / transport / success:false): degrade to the simple learn pass.
      if (!r.ok) {
        report(
          ctx,
          "learn",
          "info",
          "evidence gather unavailable — falling back to the simple learn pass",
        );
        fallback();
        return;
      }

      // Short-circuit: a learn-docs consolidation plan — clear the local marker only, inject
      // nothing (land already stamped `learn_state: skipped` for a `consumed_learn` plan, §8.36 —
      // no cold skip delegation needed here).
      if (r.data.skipped) {
        clearPending(ctx);
        report(ctx, "learn", "info", "learn-docs plan; learn capture skipped");
        return;
      }

      // Defensive: a success envelope with no bundle dir — same graceful fallback.
      if (r.data.bundle_dir === null) {
        report(
          ctx,
          "learn",
          "info",
          "evidence bundle unavailable — falling back to the simple learn pass",
        );
        fallback();
        return;
      }

      // Orchestrate: spawn analysts over the shared bundle, reconcile, capture-or-skip. `bundle_dir`
      // is repo_root-relative; the door's cwd is the worktree root the command resolved against.
      const bundleDir = join(ctx.cwd, r.data.bundle_dir);
      const manifestPath = join(bundleDir, "manifest.json");
      const model = loadPerkConfig(ctx.cwd).subagents["learn-analyst"];
      report(ctx, "learn", "info", "multi-angle learn: spawn analysts → reconcile → capture");
      // The agent captures via the `learn` tool (clearing the marker itself) — do NOT clear here.
      pi.sendUserMessage(
        learnOrchestrateGuidance({ model, manifestPath, bundleDir }) +
          bindingSuffix(ctx.cwd, "stage:learn"),
      );
    },
  });
}
