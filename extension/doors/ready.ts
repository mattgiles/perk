// The warm `/ready` door: the deliberate ready gesture. The in-session twin of the Python
// cold door (`perk pr ready`): a terminating tool + command that DELEGATE the mechanics
// (mutations canonical in Python). For an incremental plan this is the review gate — perk
// deliberately does NOT auto-publish on submit; `/ready` is the explicit gesture that opens the
// draft PR for review. For a STACKED layer it is the deliberate HUMAN handoff made after review +
// address: it stamps the exact verified published head into the delivery journal (draft AND
// non-draft PRs — mark-ready mechanics first, then the journal append). Mirrors `submit.ts`:
// write nothing, delegate via `pi.exec`, surface the structured result, never throw.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { failFor, ok, type Result } from "../substrate/result.ts";
import { report } from "../surfaces/report.ts";

/** The stacked handoff cohort — decoded all-or-nothing (advisory detail, never half-rendered). */
export interface ReadyHandoff {
  objective: string;
  node: string;
  stamped_head: string;
  stamp_advanced: boolean;
  reconcile_notice: string;
  reconcile_retry: string;
}

/** The ok-arm fields — the structured `details` surface doubles as branch-safe persisted state. */
export interface ReadyOk {
  pr: { number: number; url: string };
  was_draft?: boolean;
  handoff?: ReadyHandoff;
}

export type ReadyResult = Result<ReadyOk>;

/**
 * Narrow the `perk pr ready --json` success payload; strict on `pr`, lenient on the rest.
 *
 * The stacked continuation decodes as ONE cohort: the handoff augmentation is attached only when
 * `stacked === true` AND every cohort field decodes; a partial/wrong-typed cohort is
 * validated-and-dropped whole (the worker's own success already proved the mechanics — advisory
 * detail is never half-rendered). An absent `stacked` (an old worker) is the same
 * no-augmentation arm.
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
  };
  if (booleanField(payload, "stacked") === true) {
    const objective = stringField(payload, "objective");
    const node = stringField(payload, "node");
    const stampedHead = stringField(payload, "stamped_head");
    const stampAdvanced = booleanField(payload, "stamp_advanced");
    const reconcileNotice = stringField(payload, "reconcile_notice");
    const reconcileRetry = stringField(payload, "reconcile_retry");
    if (
      objective !== undefined &&
      node !== undefined &&
      stampedHead !== undefined &&
      stampAdvanced !== undefined &&
      reconcileNotice !== undefined &&
      reconcileRetry !== undefined
    ) {
      result.handoff = {
        objective,
        node,
        stamped_head: stampedHead,
        stamp_advanced: stampAdvanced,
        reconcile_notice: reconcileNotice,
        reconcile_retry: reconcileRetry,
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
    const stamped = handoff.stamp_advanced ? "Handoff stamped" : "Handoff already stamped";
    message +=
      ` ${stamped}: objective #${handoff.objective} node ${handoff.node} at ` +
      `${handoff.stamped_head}. ${handoff.reconcile_notice}; re-run: ${handoff.reconcile_retry}.`;
  }
  return ok(message, r.data, { terminate: true });
}

const TOOL_GUIDELINES = [
  "For an incremental plan, call ready only when the PR is ready for human review; it marks the draft PR ready (the deliberate review gate). submit keeps the PR draft on purpose.",
  "For a STACKED plan, /ready is the deliberate HUMAN handoff made AFTER review + address: it stamps the exact verified published head into the delivery journal (draft and non-draft PRs alike), and the recorded stamp unblocks planning of the layer's direct dependents. Never call it as routine post-submit choreography — review happens on the draft layer PR; only invoke it when the human explicitly asks.",
  "ready operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch. Idempotent: an already-ready PR is success, and a re-run converges on the same stamp.",
  "A failed stamp (error_type ready_stamp_failed) names its own remediation: the ambiguous/transient arms converge on re-run; deterministic failures need their named repair first.",
];

/** Register the warm door: the `ready` terminating tool + the `/ready` command twin. */
export function registerReady(pi: ExtensionAPI): void {
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
      return markReady(pi, ctx);
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
    },
  });
}
