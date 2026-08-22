// The warm `/ready` door: the deliberate ready gesture. The in-session twin of the Python
// cold door (`perk pr ready`): a terminating tool + command that DELEGATE the mechanics
// (mutations canonical in Python). For an incremental plan this is the review gate — perk
// deliberately does NOT auto-publish on submit; `/ready` is the explicit gesture that opens the
// draft PR for review. For a STACKED layer it is the deliberate HUMAN handoff made after review +
// address: it stamps the exact verified published head into the delivery journal (draft AND
// non-draft PRs — mark-ready mechanics first, then the journal append), and every successful
// stacked stamp continues into the ready-time reconcile pass (`driveReadyReconcile` — the warm
// continuation, contracts.md §8.66). Mirrors `submit.ts`: write nothing, delegate via `pi.exec`,
// surface the structured result, never throw.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { fetchObjectiveUrl, objectiveReadInstruction } from "../factories/objectivePlan.ts";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { resolveIssueBackendId } from "../substrate/config.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
import { report } from "../surfaces/report.ts";

// The drive's strict evidence vocabulary (contracts.md §8.66), local on purpose: this is
// exact-evidence validation at the continuation boundary, NOT the lenient render vocabulary
// other stack surfaces use. Both diff-range endpoints must be the full 40-hex lowercase
// object id; ids must be marker-safe segments.
const READY_EVIDENCE_ID_RE = /^[A-Za-z0-9._-]{1,64}$/;
const READY_FULL_SHA_RE = /^[0-9a-f]{40}$/;

/** The stacked handoff cohort — decoded all-or-nothing (advisory detail, never half-rendered).
 * Deliberately facts-only: the worker envelope's `reconcile_notice`/`reconcile_retry` are cold
 * presentation strings — the warm door derives its own retry gesture from `plan`, so missing
 * presentation data can never suppress an otherwise valid continuation. */
export interface ReadyHandoff {
  objective: string;
  node: string;
  stamped_head: string;
  stamp_advanced: boolean;
  plan: string;
  parent_checkpoint: string;
}

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state.
 * `stacked` is the worker's own routing fact, passed through so a malformed cohort
 * (`stacked === true`, `handoff` absent) is distinguishable from an incremental result. */
export interface ReadyOk {
  pr: { number: number; url: string };
  was_draft?: boolean;
  stacked?: boolean;
  handoff?: ReadyHandoff;
}

export type ReadyResult = Result<ReadyOk>;
export type ReadyDetails = ReadyResult["details"];

/**
 * Narrow the `perk pr ready --json` success payload; strict on `pr`, lenient on the rest.
 *
 * The stacked continuation decodes as ONE cohort: the handoff augmentation is attached only when
 * `stacked === true` AND every cohort field decodes (the two continuation fields `plan` /
 * `parent_checkpoint` included); a partial/wrong-typed cohort is validated-and-dropped whole
 * (the worker's own success already proved the mechanics — advisory detail is never
 * half-rendered), leaving the `stacked` passthrough as the visible mismatch signal. An absent
 * `stacked` (an old worker) is the same no-augmentation arm.
 */
function decodeReady(payload: ColdJson): ReadyOk | null {
  const pr = objectField(payload, "pr");
  if (pr === undefined) return null;
  const number = numberField(pr, "number");
  const url = stringField(pr, "url");
  if (number === undefined || url === undefined) return null;
  const result: ReadyOk = {
    pr: { number, url },
    was_draft: booleanField(payload, "was_draft"),
    stacked: booleanField(payload, "stacked"),
  };
  if (result.stacked === true) {
    const objective = stringField(payload, "objective");
    const node = stringField(payload, "node");
    const stampedHead = stringField(payload, "stamped_head");
    const stampAdvanced = booleanField(payload, "stamp_advanced");
    const plan = stringField(payload, "plan");
    const parentCheckpoint = stringField(payload, "parent_checkpoint");
    if (
      objective !== undefined &&
      node !== undefined &&
      stampedHead !== undefined &&
      stampAdvanced !== undefined &&
      plan !== undefined &&
      parentCheckpoint !== undefined
    ) {
      result.handoff = {
        objective,
        node,
        stamped_head: stampedHead,
        stamp_advanced: stampAdvanced,
        plan,
        parent_checkpoint: parentCheckpoint,
      };
    }
  }
  return result;
}

/**
 * The single ready implementation both surfaces call. Delegates to the Python cold door; returns a
 * soft result (never throws) — failures set `details.ok = false`.
 */
export async function markReady(pi: ExtensionAPI, ctx: ExtensionContext): Promise<ReadyResult> {
  const fail = failFor(ctx, "ready");

  const r = await runColdDoor<ReadyOk>(pi, ctx, ["pr", "ready", "--json"], {
    label: "perk pr ready",
    decode: decodeReady,
  });
  if (!r.ok) return fail(r.message, r.errorType);

  const verb = r.data.was_draft ? "Marked ready" : "Already ready";
  let message = `${verb}: PR #${r.data.pr.number} is open for review.`;
  const handoff = r.data.handoff;
  if (handoff !== undefined) {
    // Stamp facts only — the continuation is announced by driveReadyReconcile, and only once
    // its refusal arms (gate, cohort, evidence) have actually accepted the drive.
    const stamped = handoff.stamp_advanced ? "Handoff stamped" : "Handoff already stamped";
    message +=
      ` ${stamped}: objective #${handoff.objective} node ${handoff.node} at ` +
      `${handoff.stamped_head}.`;
  }
  return ok(message, r.data, { terminate: true });
}

/** One loud skipped-pass warning (the stamp itself stands; re-running `/ready` re-enters). */
function warnSkippedPass(ctx: ExtensionContext, reason: string, retry: string): void {
  report(
    ctx,
    "ready",
    "warning",
    `ready-time reconcile pass not driven — ${reason}. The handoff stamp stands; re-run ${retry} to enter the pass.`,
  );
}

/**
 * After a successful stacked stamp, drive the session into the ready-time reconcile pass
 * (contracts.md §8.66): inject the rendered `stages/objective-reconcile-ready.md` guidance —
 * the warm twin of the cold wrapper's seeded launch. Fires on EVERY successful stacked stamp,
 * `existed=true` re-stamps included (re-running `/ready` re-enters reconciliation). The
 * refusal arms are LOUD, never silent: a gate-active session (the pass's write tools are
 * gated off — a drive would dead-end), a malformed/mixed-version stacked cohort, and evidence
 * failing the strict vocabulary all warn and skip; the stamp itself always stands.
 * Incremental results and failures drive nothing, quietly.
 */
export async function driveReadyReconcile(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  gating: ToolGating,
  details: ReadyDetails,
): Promise<void> {
  if (details.ok !== true) return;
  const handoff = details.handoff;
  if (handoff === undefined) {
    if (details.stacked === true) {
      // A successful stacked stamp whose continuation cohort failed to decode — a
      // malformed/mixed-version envelope must never fail silent.
      warnSkippedPass(
        ctx,
        "the worker reported a stacked stamp but its continuation facts were malformed " +
          "(a mixed-version envelope?)",
        "/ready",
      );
    }
    return; // incremental / old worker: nothing to drive
  }
  const retry = `\`perk ready ${READY_EVIDENCE_ID_RE.test(handoff.plan) ? handoff.plan : "<plan>"}\``;
  if (gating.isActive()) {
    warnSkippedPass(
      ctx,
      "this session is read-only (the pass's write tools are gated off); exit the read-only " +
        "session or run the pass from a terminal",
      retry,
    );
    return;
  }
  const idsValid =
    READY_EVIDENCE_ID_RE.test(handoff.objective) &&
    READY_EVIDENCE_ID_RE.test(handoff.node) &&
    READY_EVIDENCE_ID_RE.test(handoff.plan);
  const shasValid =
    READY_FULL_SHA_RE.test(handoff.stamped_head) &&
    READY_FULL_SHA_RE.test(handoff.parent_checkpoint);
  if (!idsValid || !shasValid || !Number.isInteger(details.pr.number)) {
    warnSkippedPass(
      ctx,
      "the stamp evidence failed strict validation (ids marker-safe; both diff-range " +
        "endpoints full 40-hex lowercase)",
      retry,
    );
    return;
  }
  const backend = resolveIssueBackendId(ctx.cwd);
  const url = backend === "linear" ? await fetchObjectiveUrl(pi, ctx, handoff.objective) : "";
  const readClause = objectiveReadInstruction(backend, handoff.objective, url);
  const message =
    render("stages/objective-reconcile-ready.md", {
      objective: handoff.objective,
      node: handoff.node,
      plan: handoff.plan,
      pr: String(details.pr.number),
      parent_checkpoint: handoff.parent_checkpoint,
      stamped_head: handoff.stamped_head,
      read_clause: readClause,
    }) + bindingSuffix(ctx.cwd, "command:objective-reconcile");
  // Announce the continuation only HERE — after every refusal arm has accepted the drive.
  report(
    ctx,
    "ready",
    "info",
    `continuing into the ready-time reconcile pass — objective #${handoff.objective}, ` +
      `pinned range ${handoff.parent_checkpoint}..${handoff.stamped_head}`,
  );
  if (ctx.isIdle()) {
    // The `/ready` command path (idle): inject an immediate turn.
    pi.sendUserMessage(message);
  } else {
    // The `ready` tool path (streaming): deliver after the terminating ready batch.
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

const TOOL_GUIDELINES = [
  "For an incremental plan, call ready only when the PR is ready for human review; it marks the draft PR ready (the deliberate review gate). submit keeps the PR draft on purpose.",
  "For a STACKED plan, /ready is the deliberate HUMAN handoff made AFTER review + address: it stamps the exact verified published head into the delivery journal (draft and non-draft PRs alike), and the recorded stamp unblocks planning of the layer's direct dependents. Never call it as routine post-submit choreography — review happens on the draft layer PR; only invoke it when the human explicitly asks.",
  "ready operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch. Idempotent: an already-ready PR is success, and a re-run converges on the same stamp.",
  "A failed stamp (error_type ready_stamp_failed) names its own remediation: the ambiguous/transient arms converge on re-run; deterministic failures need their named repair first.",
];

/** Register the warm door: the `ready` terminating tool + the `/ready` command twin. */
export function registerReady(pi: ExtensionAPI, gating: ToolGating): void {
  pi.registerTool({
    name: "ready",
    label: "Mark PR ready",
    description:
      "Ready the active plan's PR. Incremental: mark the draft PR ready for review (the " +
      "deliberate review gate; submit keeps the PR draft). Stacked: the deliberate post-review " +
      "HUMAN handoff — stamps the exact verified published head (draft and non-draft PRs); " +
      "never routine post-submit choreography, never auto-run. Terminating: ends the turn.",
    promptSnippet:
      "Ready the PR: open the draft for review (incremental) or record the post-review " +
      "handoff stamp (stacked; human-asked only). Terminates the turn.",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const result = await markReady(pi, ctx);
      await driveReadyReconcile(pi, ctx, gating, result.details);
      return result;
    },
  });

  registerPerkCommand(pi, "ready", {
    description:
      "Ready the plan's PR: open the draft for review (incremental) or record the " +
      "post-review handoff stamp (stacked).",
    handler: async (_args, ctx) => {
      const result = await markReady(pi, ctx);
      // Failure already reported loudly via failFor (the single error surface) — success only.
      if (result.details.ok) {
        report(ctx, "ready", "info", result.content[0]?.text ?? "ready done");
      }
      await driveReadyReconcile(pi, ctx, gating, result.details);
    },
  });
}
