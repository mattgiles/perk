// The `objective_draft` file tool: the objective-flavored twin of the
// `plan_draft` carve-out (planDraft.ts).
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
// `parse_structured_roadmap` path). The review surface reads the draft via
// `readObjectiveDraft` (over `readSessionArtifact` — digest-validated, fail-open) and renders
// markdown via `renderObjectiveDraft` (the prose + a roadmap table) — never raw JSON; the
// approval→`objective_save` orchestration feeds the recovered roadmap
// back as structured JSON.
//
// Vocabulary ownership: this module owns the shared draft/save param vocabulary
// (`ObjectiveSaveParams`, `decodeObjectiveSaveParams`, `ROADMAP_PARAM_SCHEMA`) — objectiveDraft is
// the LEAF (mirroring planDraft←planSave's direction); objectiveSave.ts consumes it, so it may
// value-import `readObjectiveDraft` cycle-free for the approval→save orchestration.
//
// Imports stay node builtins + sibling seams (sessionData.ts, result.ts) so the module loads
// under `node --test`; no manual `scratch`/`runs` path segments (cacheGuard.test.ts).

import { relative } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { failFor, ok, type Result } from "../substrate/result.ts";
import {
  activeSessionRunId,
  digestSessionData,
  readSessionArtifact,
  type SessionDataCtx,
  writeSessionArtifact,
} from "../substrate/sessionData.ts";
import { arrayParam, paramsOf, stringParam } from "../substrate/toolParams.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";

/** The decoded `objective_save` tool params (shared with `objective_draft`). */
export interface ObjectiveSaveParams {
  prose: string;
  title?: string;
  roadmap?: unknown[];
  // The objective's target branch; omitted to use the repo default.
  base?: string;
}

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
  if (prose === null || title === null || roadmap === null || base === null) return null;
  return { prose: prose ?? "", title, roadmap, base };
}

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
  opts: { prose: string; title?: string; roadmap?: unknown[]; base?: string },
): ObjectiveDraftResult {
  const fail = failFor(ctx, "objective-draft");

  if (!opts.prose.trim()) {
    return fail("no objective prose to write (pass the full working draft)", "invalid_input");
  }

  const runId = activeSessionRunId(ctx);
  if (runId === null) {
    return fail("session has no run_id — cannot write the objective-draft artifact", "no_run_id");
  }

  // Deterministic key order via the explicit literal; `title`/`base` are omitted when blank.
  const title = opts.title?.trim();
  const base = opts.base?.trim();
  const roadmap = opts.roadmap ?? [];
  const payload = {
    schema_version: 1,
    ...(title ? { title } : {}),
    ...(base ? { base } : {}),
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

// ------------------------------------------------------------------- the reader + the renderer

/** The validated working-objective draft shape consumers receive from `readObjectiveDraft`. */
export interface ObjectiveDraft {
  title?: string;
  prose: string;
  roadmap: unknown[];
  // The objective's target branch; kept only when a non-blank string in the artifact.
  base?: string;
}

/**
 * Read + validate the working-objective draft artifact. Fail-open `null` everywhere (mirroring
 * `readSessionArtifact`'s loud tier): no pointer/file/digest → `null` (the seam already spoke);
 * malformed JSON, a non-object payload, an unsupported `schema_version`, or blank prose → a
 * stderr warning + `null`. `roadmap` defaults to `[]` when absent/non-array; `title` is kept
 * only when a non-blank string. Never throws.
 */
export function readObjectiveDraft(ctx: SessionDataCtx): ObjectiveDraft | null {
  const artifact = readSessionArtifact(ctx, OBJECTIVE_DRAFT_ARTIFACT);
  if (artifact === null) return null;

  const refuse = (why: string): null => {
    console.error(`perk: warning: ${OBJECTIVE_DRAFT_ARTIFACT} ${why} — refusing the draft`);
    return null;
  };
  let parsed: unknown;
  try {
    parsed = JSON.parse(artifact.content);
  } catch {
    return refuse("is not valid JSON");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return refuse("is not a JSON object");
  }
  const payload = parsed as Record<string, unknown>;
  if (payload.schema_version !== 1) {
    return refuse(`has an unsupported schema_version (${JSON.stringify(payload.schema_version)})`);
  }
  const prose = payload.prose;
  if (typeof prose !== "string" || !prose.trim()) {
    return refuse("has no prose");
  }
  const roadmap = Array.isArray(payload.roadmap) ? payload.roadmap : [];
  const title =
    typeof payload.title === "string" && payload.title.trim() ? payload.title : undefined;
  const base = typeof payload.base === "string" && payload.base.trim() ? payload.base : undefined;
  return {
    ...(title !== undefined ? { title } : {}),
    ...(base !== undefined ? { base } : {}),
    prose,
    roadmap,
  };
}

/** Sanitize a table cell: `|` escaped, newlines collapsed to a single space. */
function tableCell(value: string): string {
  return value.replace(/\r?\n/g, " ").replace(/\|/g, "\\|");
}

/** Read a string field off an unknown-shaped roadmap node (`""` when absent/mistyped). */
function nodeString(node: unknown, key: string): string {
  if (typeof node !== "object" || node === null) return "";
  const value = (node as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

/** Render a node's `depends_on` as a `", "`-join of its string members; `-` when empty/absent. */
function nodeDependsOn(node: unknown): string {
  if (typeof node !== "object" || node === null) return "-";
  const value = (node as Record<string, unknown>).depends_on;
  if (!Array.isArray(value)) return "-";
  const deps = value.filter((d): d is string => typeof d === "string");
  return deps.length > 0 ? deps.join(", ") : "-";
}

/**
 * Render the draft as the markdown review surface (JSON is storage/transport only — contracts
 * §8.1): the optional `# title` heading, the prose verbatim, and (when the roadmap is non-empty)
 * a `## Roadmap` section with ONE markdown table. The `Phase` column appears only when some node
 * carries a non-blank string `phase`. Pure; never throws.
 */
export function renderObjectiveDraft(draft: ObjectiveDraft): string {
  let out = "";
  if (draft.title) out += `# ${draft.title}\n\n`;
  out += draft.prose;

  if (draft.roadmap.length === 0) return out;

  const withPhase = draft.roadmap.some((node) => nodeString(node, "phase").trim().length > 0);
  const header = withPhase
    ? "| Node | Phase | Description | Depends On | Status |\n| --- | --- | --- | --- | --- |"
    : "| Node | Description | Depends On | Status |\n| --- | --- | --- | --- |";
  const rows = draft.roadmap.map((node) => {
    const cells = [
      tableCell(nodeString(node, "id")),
      ...(withPhase ? [tableCell(nodeString(node, "phase"))] : []),
      tableCell(nodeString(node, "description")),
      tableCell(nodeDependsOn(node)),
      tableCell(nodeString(node, "status") || "pending"),
    ];
    return `| ${cells.join(" | ")} |`;
  });
  return `${out.trimEnd()}\n\n## Roadmap\n\n${header}\n${rows.join("\n")}\n`;
}

const TOOL_GUIDELINES = [
  "Call objective_draft to persist the current working objective as you author or revise it; pass the FULL prose and the FULL structured roadmap each time (it rewrites the whole draft).",
  "objective_draft never saves to GitHub and never ends the turn — objective_save//objective-save remain the canonical save surface. Never hand-write roadmap YAML — hand the structured roadmap to the tool.",
  "Pass objective_draft's `base` only to target a non-default branch; omit it to use the repo default.",
];

/** Register the `objective_draft` tool (the carve-out producer; interior-only). */
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
        base: {
          type: "string",
          description:
            "Optional target branch for this objective's plans (omit to use the repo default).",
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
