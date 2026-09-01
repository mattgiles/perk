// The ready + handoff bindings: the `ready` terminating tool + the `/ready` command twin,
// adapting the Pi-free ready operation in `delivery/ready.ts`. The in-session twin of the Python
// cold door (`perk pr ready`): a terminating surface that DELEGATES the mechanics (mutations
// canonical in Python). For an incremental plan this is the review gate — perk deliberately does
// NOT auto-publish on submit; `/ready` is the explicit gesture that opens the draft PR for
// review. For a STACKED layer it is the deliberate HUMAN handoff made after review + address: it
// stamps the exact verified published head into the delivery journal (draft AND non-draft PRs —
// mark-ready mechanics first, then the journal append), and every successful stacked stamp
// continues into the ready-time reconcile pass (`driveReadyContinuation` — the warm
// continuation, contracts.md §8.66). Write nothing, delegate via the cold-door seam, surface the
// structured result, never throw. This tier is pure decoding, rendering, process invocation, and
// Pi delivery — the arm order, the strict evidence vocabulary, and the continuation decision
// live in the feature op.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { objectiveReadInstruction } from "../../../authoring/objective/prose.ts";
import {
  type ReadyDeps,
  type ReadyDriveEvidence,
  type ReadyFacts,
  type ReadyHandoff,
  type ReadyOutcome,
  type ReadyPr,
  readyChange,
} from "../../../delivery/ready.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  runColdDoor,
  stringField,
} from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { resolveIssueBackendId } from "../../../substrate/config.ts";
import { render } from "../../../substrate/prompts.ts";
import { failFor, ok } from "../../../substrate/result.ts";
import type { ToolGating } from "../../../substrate/toolGating.ts";
import { report } from "../../../surfaces/report.ts";
import { fetchObjectiveUrl } from "../objective.ts";

/**
 * Narrow the `perk pr ready --json` success payload into the correlated facts variants; strict
 * on `pr`, lenient on the rest. The stacked continuation decodes as ONE cohort: a
 * partial/wrong-typed cohort is validated-and-dropped whole into `stacked_unverified` (the
 * worker's own success already proved the mechanics — advisory detail is never half-rendered),
 * keeping the routing fact as the visible mismatch signal. An absent-or-false `stacked` (an old
 * worker included) is the `incremental` variant, false-vs-absent preserved for the wire.
 */
function decodeReady(payload: ColdJson): ReadyFacts | null {
  const prField = objectField(payload, "pr");
  if (prField === undefined) return null;
  const number = numberField(prField, "number");
  const url = stringField(prField, "url");
  if (number === undefined || url === undefined) return null;
  const pr: ReadyPr = { number, url };
  const wasDraft = booleanField(payload, "was_draft");
  const stacked = booleanField(payload, "stacked");
  if (stacked !== true) {
    return { route: "incremental", pr, was_draft: wasDraft, stacked };
  }
  const objective = stringField(payload, "objective");
  const node = stringField(payload, "node");
  const stampedHead = stringField(payload, "stamped_head");
  const stampAdvanced = booleanField(payload, "stamp_advanced");
  const plan = stringField(payload, "plan");
  const parentCheckpoint = stringField(payload, "parent_checkpoint");
  if (
    objective === undefined ||
    node === undefined ||
    stampedHead === undefined ||
    stampAdvanced === undefined ||
    plan === undefined ||
    parentCheckpoint === undefined
  ) {
    return { route: "stacked_unverified", pr, was_draft: wasDraft };
  }
  return {
    route: "stacked",
    pr,
    was_draft: wasDraft,
    handoff: {
      objective,
      node,
      stamped_head: stampedHead,
      stamp_advanced: stampAdvanced,
      plan,
      parent_checkpoint: parentCheckpoint,
    },
  };
}

/** The ONE production `MarkReady` adapter: `perk pr ready --json` through the cold-door seam
 * (cancellation, envelope validation, and version-skew diagnostics ride the seam).
 * Module-private: production composes only through `readyDepsFor`. */
function createReadyMarker(pi: ExtensionAPI, ctx: ExtensionContext): ReadyDeps["markReady"] {
  return async () => {
    const r = await runColdDoor<ReadyFacts>(pi, ctx, ["pr", "ready", "--json"], {
      label: "perk pr ready",
      decode: decodeReady,
    });
    if (!r.ok) return { ok: false, message: r.message, errorType: r.errorType };
    return { ok: true, facts: r.data };
  };
}

/** The one production `ReadyDeps` composition (module-private: the one-composition invariant
 * is structural). The gate read is the injected capability — the feature op reads it only on
 * the stamped-with-cohort path. */
function readyDepsFor(pi: ExtensionAPI, ctx: ExtensionContext, gating: ToolGating): ReadyDeps {
  return {
    markReady: createReadyMarker(pi, ctx),
    sessionReadOnly: () => gating.isActive(),
  };
}

/** The wire-identical ok-arm details rebuilt from the facts variants: incremental ⇒ `stacked`
 * passthrough (false or absent), no `handoff`; `stacked_unverified` ⇒ `stacked: true`, no
 * `handoff`; `stacked` ⇒ `stacked: true` + the six-field cohort. Optional keys carry
 * `undefined` exactly where the old decode left them absent (the JSON round-trip drops them). */
interface ReadyDetails {
  pr: ReadyPr;
  was_draft?: boolean;
  stacked?: boolean;
  handoff?: ReadyHandoff;
}

function readyDetails(facts: ReadyFacts): ReadyDetails {
  switch (facts.route) {
    case "incremental":
      return { pr: facts.pr, was_draft: facts.was_draft, stacked: facts.stacked };
    case "stacked_unverified":
      return { pr: facts.pr, was_draft: facts.was_draft, stacked: true };
    case "stacked":
      return { pr: facts.pr, was_draft: facts.was_draft, stacked: true, handoff: facts.handoff };
  }
}

/** Render the success message: the ready line, plus — exactly when the facts route is
 * `stacked` — the handoff-stamped line. Stamp facts only: the continuation is announced by
 * `driveReadyContinuation`, and only once the feature op's refusal arms have accepted. */
function renderReadyMessage(facts: ReadyFacts): string {
  const verb = facts.was_draft ? "Marked ready" : "Already ready";
  let message = `${verb}: PR #${facts.pr.number} is open for review.`;
  if (facts.route === "stacked") {
    const handoff = facts.handoff;
    const stamped = handoff.stamp_advanced ? "Handoff stamped" : "Handoff already stamped";
    message +=
      ` ${stamped}: objective #${handoff.objective} node ${handoff.node} at ` +
      `${handoff.stamped_head}.`;
  }
  return message;
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

/** The retry gesture from the feature op's safe-interpolation policy: a marker-safe plan id
 * interpolates; `null` renders the `<plan>` placeholder. */
function retryGesture(retryPlan: string | null): string {
  return `\`perk ready ${retryPlan ?? "<plan>"}\``;
}

/** Inject the rendered ready-time reconcile pass (contracts.md §8.66) — the warm twin of the
 * cold wrapper's seeded launch. Interpolates exclusively from the mint-only evidence. */
async function driveReconcilePass(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  evidence: ReadyDriveEvidence,
): Promise<void> {
  const backend = resolveIssueBackendId(ctx.cwd);
  const url = backend === "linear" ? await fetchObjectiveUrl(pi, ctx, evidence.objective) : "";
  const readClause = objectiveReadInstruction(backend, evidence.objective, url);
  const message =
    render("stages/objective-reconcile-ready.md", {
      objective: evidence.objective,
      node: evidence.node,
      plan: evidence.plan,
      pr: String(evidence.pr),
      parent_checkpoint: evidence.parent_checkpoint,
      stamped_head: evidence.stamped_head,
      read_clause: readClause,
    }) + bindingSuffix(ctx.cwd, "command:objective-reconcile");
  // Announce the continuation only HERE — after every refusal arm has accepted the drive.
  report(
    ctx,
    "ready",
    "info",
    `continuing into the ready-time reconcile pass — objective #${evidence.objective}, ` +
      `pinned range ${evidence.parent_checkpoint}..${evidence.stamped_head}`,
  );
  if (ctx.isIdle()) {
    // The `/ready` command path (idle): inject an immediate turn.
    pi.sendUserMessage(message);
  } else {
    // The `ready` tool path (streaming): deliver after the terminating ready batch.
    pi.sendUserMessage(message, { deliverAs: "followUp" });
  }
}

/**
 * Translate the feature op's outcome into the warm continuation (contracts.md §8.66): the drive
 * fires on EVERY accepted stacked stamp (`stamp_advanced: false` re-stamps included — re-running
 * `/ready` re-enters reconciliation). The refusal arms are LOUD, never silent; the stamp itself
 * always stands. `failed` and `completed` are explicit quiet arms. Exported as the one direct
 * test seam — the streaming `followUp` branch is unreachable through the idle harness.
 */
export async function driveReadyContinuation(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  outcome: ReadyOutcome,
): Promise<void> {
  switch (outcome.kind) {
    case "failed":
    case "completed":
      return; // exterior failure / incremental: nothing to drive, quietly
    case "stamp_facts_unverified":
      // A successful stacked stamp whose continuation cohort failed to decode — a
      // malformed/mixed-version envelope must never fail silent.
      warnSkippedPass(
        ctx,
        "the worker reported a stacked stamp but its continuation facts were malformed " +
          "(a mixed-version envelope?)",
        "/ready",
      );
      return;
    case "stamped": {
      const continuation = outcome.continuation;
      switch (continuation.kind) {
        case "refused_read_only":
          warnSkippedPass(
            ctx,
            "this session is read-only (the pass's write tools are gated off); exit the " +
              "read-only session or run the pass from a terminal",
            retryGesture(continuation.retryPlan),
          );
          return;
        case "evidence_invalid":
          warnSkippedPass(
            ctx,
            "the stamp evidence failed strict validation (ids marker-safe; both diff-range " +
              "endpoints full 40-hex lowercase)",
            retryGesture(continuation.retryPlan),
          );
          return;
        case "drive":
          await driveReconcilePass(pi, ctx, continuation.evidence);
          return;
      }
      // Exhaustive over the continuation (no catch-all): union growth breaks the adapter here.
      const exhaustiveContinuation: never = continuation;
      throw new Error(`unreachable ready continuation: ${JSON.stringify(exhaustiveContinuation)}`);
    }
  }
  // Exhaustive over the outcome (no catch-all): union growth breaks the adapter here.
  const exhaustive: never = outcome;
  throw new Error(`unreachable ready outcome: ${JSON.stringify(exhaustive)}`);
}

const TOOL_GUIDELINES = [
  "For an incremental plan, call ready only when the PR is ready for human review; it marks the draft PR ready (the deliberate review gate). submit keeps the PR draft on purpose.",
  "For a STACKED plan, /ready is the deliberate HUMAN handoff made AFTER review + address: it stamps the exact verified published head into the delivery journal (draft and non-draft PRs alike), and the recorded stamp unblocks planning of the layer's direct dependents. Never call it as routine post-submit choreography — review happens on the draft layer PR; only invoke it when the human explicitly asks.",
  "ready operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch. Idempotent: an already-ready PR is success, and a re-run converges on the same stamp.",
  "A failed stamp (error_type ready_stamp_failed) names its own remediation: the ambiguous/transient arms converge on re-run; deterministic failures need their named repair first.",
];

/** Install the ready + handoff bindings: the `ready` terminating tool + the `/ready` command
 * twin. */
export function installReadyBindings(pi: ExtensionAPI, gating: ToolGating): void {
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
      const fail = failFor(ctx, "ready");
      const outcome = await readyChange(readyDepsFor(pi, ctx, gating));
      if (outcome.kind === "failed") return fail(outcome.message, outcome.errorType);
      const result = ok(renderReadyMessage(outcome.facts), readyDetails(outcome.facts), {
        terminate: true,
      });
      await driveReadyContinuation(pi, ctx, outcome);
      return result;
    },
  });

  registerPerkCommand(pi, "ready", {
    description:
      "Ready the plan's PR: open the draft for review (incremental) or record the " +
      "post-review handoff stamp (stacked).",
    handler: async (_args, ctx) => {
      const fail = failFor(ctx, "ready");
      const outcome = await readyChange(readyDepsFor(pi, ctx, gating));
      // Failure is reported loudly via failFor (the single error surface) — success only.
      if (outcome.kind === "failed") {
        fail(outcome.message, outcome.errorType);
        return;
      }
      // Report-before-drive (load-bearing order): the success line lands before the injected
      // reconcile turn.
      report(ctx, "ready", "info", renderReadyMessage(outcome.facts));
      await driveReadyContinuation(pi, ctx, outcome);
    },
  });
}
