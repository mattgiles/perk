// Objective #339 Node 2.1 — the `plan_draft` file tool: the first session-data PRODUCER and the
// narrow structural read-only-gate carve-out (session data dir only).
//
// Carve-out doctrine: the tool takes NO path/name parameter — the artifact name is the fixed
// constant `PLAN_DRAFT_ARTIFACT` and the path is derived exclusively through the session-data
// accessor seam (`writeSessionArtifact`, sessionData.ts), so the only bytes it can ever write are
// the one working-plan artifact in the current run's data dir (gitignored scratch). Allowlisting
// its name in `READ_ONLY_TOOLS` (toolGating.ts) is therefore safe: the read-only invariant (the
// worktree stays untouched) holds, and the gate's `tool_call` edit/write/bash blocking logic is
// UNCHANGED. Full rewrite per call, non-terminating; NOT a save — `plan_save`/`/plan-save` still
// persist to GitHub. Consumers read the draft only via `readSessionArtifact` (digest-validated,
// fail-open); the artifact is consumed by `resolvePlanSource` (planSave.ts, Node 2.2) — both save
// surfaces prefer it over an explicit param and over the transcript scrape.
//
// Imports stay node builtins + sibling seams (sessionData.ts, toolParams.ts, result.ts) so the
// module loads under `node --test`; no manual `scratch`/`runs` path segments (cacheGuard.test.ts).

import { relative } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { failFor, ok, type Result } from "../substrate/result.ts";
import {
  activeSessionRunId,
  digestSessionData,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../substrate/sessionData.ts";
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";

/** The fixed working-plan artifact name (NOT `plan.md` — `cache.plan` is a different file). */
export const PLAN_DRAFT_ARTIFACT = "plan-draft.md";

/**
 * Decode unknown `plan_draft` tool-call params (the tool-boundary seam). `plan` absent decodes to
 * `""` (so the core's `invalid_input` arm owns the empty-plan message); present-but-mistyped →
 * null (strict-fail `bad_input`). Decode-before-side-effect.
 */
export function decodePlanDraftParams(params: unknown): { plan: string } | null {
  const p = paramsOf(params);
  if (p === null) return null;
  const plan = stringParam(p, "plan");
  if (plan === null) return null;
  return { plan: plan ?? "" };
}

/** The ok-arm details — provenance-consistent with the recorded `session_artifacts` pointer. */
export interface PlanDraftOk {
  name: string;
  path: string;
  digest: string;
  bytes: number;
  run_id: string;
}

export type PlanDraftResult = Result<PlanDraftOk>;

/**
 * The core both the tool handler and tests call: write the working-plan artifact through the
 * accessor seam (file + `session_artifacts` provenance pointer). Soft result, never throws —
 * failure taxonomy: empty plan → `invalid_input`; no session run_id → `no_run_id`; file-or-pointer
 * write failure → `write_failed` (the seam already warned on stderr).
 */
export function writePlanDraft(
  sink: EntrySink,
  ctx: SessionDataCtx & ReportTarget,
  plan: string,
): PlanDraftResult {
  const fail = failFor(ctx, "plan-draft");

  if (!plan.trim()) {
    return fail("no plan markdown to write (pass the full working draft)", "invalid_input");
  }

  const runId = activeSessionRunId(ctx);
  if (runId === null) {
    return fail("session has no run_id — cannot write the plan-draft artifact", "no_run_id");
  }

  const written = writeSessionArtifact(sink, ctx, PLAN_DRAFT_ARTIFACT, plan);
  if (written === null) {
    return fail(
      `could not write the ${PLAN_DRAFT_ARTIFACT} artifact (see warnings)`,
      "write_failed",
    );
  }

  // Derive digest/relative path consistently with the pointer the seam recorded.
  const digest = digestSessionData(plan);
  const relPath = relative(ctx.cwd, written);
  return ok(`Plan draft written → ${relPath} (${digest})`, {
    name: PLAN_DRAFT_ARTIFACT,
    path: relPath,
    digest,
    bytes: Buffer.byteLength(plan, "utf8"),
    run_id: runId,
  });
}

const TOOL_GUIDELINES = [
  "Call plan_draft to persist the current working draft as you author or revise the plan; pass the FULL plan markdown each time (it rewrites the whole draft).",
  "plan_draft never saves to GitHub and never ends the turn — plan_save//plan-save remain the canonical save surface.",
];

/** Register the `plan_draft` tool (the Node 2.1 carve-out producer; interior-only). */
export function registerPlanDraft(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "plan_draft",
    label: "Plan draft",
    description:
      "Write (or overwrite) the working plan draft to the session data dir and record its " +
      "provenance pointer. The only sanctioned write surface while read-only. NOT a save — " +
      "plan_save//plan-save still persist the plan to GitHub.",
    promptSnippet: "Persist the working plan draft to the session data dir (full rewrite)",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["plan"],
      properties: {
        plan: {
          type: "string",
          description: "The full working-plan markdown (rewrites the whole draft).",
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const decoded = decodePlanDraftParams(params);
      if (decoded === null) {
        return failFor(
          ctx,
          "plan-draft",
          "plan_draft",
        )("plan_draft needs { plan: string } per the tool schema", "bad_input");
      }
      return writePlanDraft(pi, ctx, decoded.plan);
    },
  });
}
