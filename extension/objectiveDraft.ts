// Objective #352 Node 2.1 — the `objective_draft` file tool: the objective-flavored twin of the
// `plan_draft` carve-out (#339 Node 2.1, planDraft.ts).
//
// Carve-out doctrine: the tool takes NO path/name parameter — the artifact name is the fixed
// constant `OBJECTIVE_DRAFT_ARTIFACT` and the path is derived exclusively through the session-data
// accessor seam (`writeSessionArtifact`, sessionData.ts), so the only bytes it can ever write are
// the one working-objective artifact in the current run's data dir (gitignored scratch).
// Allowlisting its name in `READ_ONLY_TOOLS` (toolGating.ts) is therefore safe: the read-only
// invariant (the worktree stays untouched) holds, and the gate's `tool_call` edit/write/bash
// blocking logic is UNCHANGED. Full rewrite per call, non-terminating; NOT a save —
// `objective_save`/`/objective-save` still persist the objective to GitHub.
//
// Format doctrine: JSON is the storage/transport format, NEVER the human review surface. The
// artifact carries `{schema_version, title?, prose, roadmap}` — the structured roadmap rides
// verbatim (node-shape validation stays with the Python plane at save time, the
// `parse_structured_roadmap` path). The review surface (node 2.2, forthcoming) renders markdown
// (the prose + a roadmap table) from the artifact; the approval→`objective_save` orchestration
// (node 2.3, forthcoming) feeds the recovered roadmap back as structured JSON. Consumers read the
// draft only via `readSessionArtifact` (digest-validated, fail-open).
//
// Imports stay node builtins + sibling seams (sessionData.ts, objectiveSave.ts, result.ts) so the
// module loads under `node --test`; no manual `scratch`/`runs` path segments (cacheGuard.test.ts).

import { relative } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { decodeObjectiveSaveParams, ROADMAP_PARAM_SCHEMA } from "./objectiveSave.ts";
import type { ReportTarget } from "./report.ts";
import { failFor, ok, type Result } from "./result.ts";
import {
  activeSessionRunId,
  digestSessionData,
  type SessionDataCtx,
  writeSessionArtifact,
} from "./sessionData.ts";
import type { EntrySink } from "./workflowState.ts";

/** The fixed working-objective artifact name (one JSON file: prose + the structured roadmap). */
export const OBJECTIVE_DRAFT_ARTIFACT = "objective-draft.json";

/** The ok-arm details — provenance-consistent with the recorded `session_artifacts` pointer. */
export interface ObjectiveDraftOk {
  name: string;
  path: string;
  digest: string;
  bytes: number;
  run_id: string;
  roadmap_nodes: number;
}

export type ObjectiveDraftResult = Result<ObjectiveDraftOk>;

/**
 * The core both the tool handler and tests call: serialize the working objective (prose + the
 * structured roadmap, verbatim — the draft never validates node shapes) as one JSON artifact and
 * write it through the accessor seam (file + `session_artifacts` provenance pointer). Soft
 * result, never throws — failure taxonomy: empty prose → `invalid_input`; no session run_id →
 * `no_run_id`; file-or-pointer write failure → `write_failed` (the seam already warned).
 */
export function writeObjectiveDraft(
  sink: EntrySink,
  ctx: SessionDataCtx & ReportTarget,
  opts: { prose: string; title?: string; roadmap?: unknown[] },
): ObjectiveDraftResult {
  const fail = failFor(ctx, "objective-draft");

  if (!opts.prose.trim()) {
    return fail("no objective prose to write (pass the full working draft)", "invalid_input");
  }

  const runId = activeSessionRunId(ctx);
  if (runId === null) {
    return fail("session has no run_id — cannot write the objective-draft artifact", "no_run_id");
  }

  // Deterministic key order via the explicit literal; `title` is omitted when absent/blank.
  const title = opts.title?.trim();
  const roadmap = opts.roadmap ?? [];
  const payload = {
    schema_version: 1,
    ...(title ? { title } : {}),
    prose: opts.prose,
    roadmap,
  };
  const content = `${JSON.stringify(payload, null, 2)}\n`;

  const written = writeSessionArtifact(sink, ctx, OBJECTIVE_DRAFT_ARTIFACT, content);
  if (written === null) {
    return fail(
      `could not write the ${OBJECTIVE_DRAFT_ARTIFACT} artifact (see warnings)`,
      "write_failed",
    );
  }

  // Derive digest/relative path consistently with the pointer the seam recorded.
  const digest = digestSessionData(content);
  const relPath = relative(ctx.cwd, written);
  return ok(`Objective draft written → ${relPath} (${digest}; ${roadmap.length} roadmap nodes)`, {
    name: OBJECTIVE_DRAFT_ARTIFACT,
    path: relPath,
    digest,
    bytes: Buffer.byteLength(content, "utf8"),
    run_id: runId,
    roadmap_nodes: roadmap.length,
  });
}

const TOOL_GUIDELINES = [
  "Call objective_draft to persist the current working objective as you author or revise it; pass the FULL prose and the FULL structured roadmap each time (it rewrites the whole draft).",
  "objective_draft never saves to GitHub and never ends the turn — objective_save//objective-save remain the canonical save surface. Never hand-write roadmap YAML — hand the structured roadmap to the tool.",
];

/** Register the `objective_draft` tool (the #352 Node 2.1 carve-out producer; interior-only). */
export function registerObjectiveDraft(pi: ExtensionAPI): void {
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
        roadmap: {
          type: "array",
          description:
            "The structured roadmap: a JSON array of nodes. Never hand-write roadmap YAML.",
          items: ROADMAP_PARAM_SCHEMA,
        },
      },
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // The shared param contract: the same decode as `objective_save`, so the two cannot drift.
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
      return writeObjectiveDraft(pi, ctx, decoded);
    },
  });
}
