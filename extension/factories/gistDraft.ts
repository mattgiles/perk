// The `gist_draft` file tool: the third member of the draft carve-out family
// (planDraft.ts, objectiveDraft.ts) — the gist twin, minus the roadmap.
//
// Carve-out doctrine: the tool takes NO path/name parameter — the artifact name is the fixed
// constant `GIST_DRAFT_ARTIFACT` and the path is derived exclusively through the session-data
// accessor seam (`writeSessionArtifact`, sessionData.ts), so the only bytes it can ever write are
// the one working-gist artifact in the current run's data dir (gitignored scratch). Allowlisting
// its name in `READ_ONLY_TOOLS` (toolGating.ts) is therefore safe: the read-only invariant (the
// worktree stays untouched) holds, and the gate's `tool_call` edit/write/bash blocking logic is
// UNCHANGED. Full rewrite per call, non-terminating; NOT a save — `gist_save`/`/gist-save` still
// persist the gist to the issue backend.
//
// Format doctrine: JSON is the storage/transport format, NEVER the human review surface. The
// artifact carries `{schema_version, title?, scope?, prose}` — deliberately light: a gist is a
// problem-space statement of intent with no structured roadmap (contracts.md §8.41). The review
// surface reads the draft via `readGistDraft` (over `readSessionArtifact` — digest-validated,
// fail-open) and renders markdown via `renderGistDraft` (title + a `Scope:` line + the prose) —
// never raw JSON.
//
// Vocabulary ownership: this module owns the shared draft/save param vocabulary
// (`GistSaveParams`, `decodeGistSaveParams`, `GIST_SCOPES`) — gistDraft is the LEAF (mirroring
// planDraft←planSave's direction); gistSave.ts consumes it, so it may value-import
// `readGistDraft` cycle-free for the approval→save orchestration.
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
import { paramsOf, stringParam } from "../substrate/toolParams.ts";
import type { EntrySink } from "../substrate/workflowState.ts";
import type { ReportTarget } from "../surfaces/report.ts";

/** The gist consumption tiers (`scope` — contracts.md §8.41). */
export const GIST_SCOPES = ["plan", "objective"] as const;

export type GistScope = (typeof GIST_SCOPES)[number];

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

/** The fixed working-gist artifact name (one JSON file: the prose + the optional scope hint). */
export const GIST_DRAFT_ARTIFACT = "gist-draft.json";

/** The ok-arm details — provenance-consistent with the recorded `session_artifacts` pointer. */
export interface GistDraftOk {
  name: string;
  path: string;
  digest: string;
  bytes: number;
  run_id: string;
}

export type GistDraftResult = Result<GistDraftOk>;

/**
 * The core both the tool handler and tests call: serialize the working gist (prose + the
 * optional title/scope) as one JSON artifact and write it through the accessor seam (file +
 * `session_artifacts` provenance pointer). Soft result, never throws — failure taxonomy: empty
 * prose → `invalid_input`; no session run_id → `no_run_id`; file-or-pointer write failure →
 * `write_failed` (the seam already warned).
 */
export function writeGistDraft(
  sink: EntrySink,
  ctx: SessionDataCtx & ReportTarget,
  opts: { prose: string; title?: string; scope?: GistScope },
): GistDraftResult {
  const fail = failFor(ctx, "gist-draft");

  if (!opts.prose.trim()) {
    return fail("no gist prose to write (pass the full working draft)", "invalid_input");
  }

  const runId = activeSessionRunId(ctx);
  if (runId === null) {
    return fail("session has no run_id — cannot write the gist-draft artifact", "no_run_id");
  }

  // Deterministic key order via the explicit literal; `title`/`scope` are omitted when blank.
  const title = opts.title?.trim();
  const payload = {
    schema_version: 1,
    ...(title ? { title } : {}),
    ...(opts.scope ? { scope: opts.scope } : {}),
    prose: opts.prose,
  };
  const content = `${JSON.stringify(payload, null, 2)}\n`;

  const written = writeSessionArtifact(sink, ctx, GIST_DRAFT_ARTIFACT, content);
  if (written === null) {
    return fail(
      `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
      "write_failed",
    );
  }

  // Derive digest/relative path consistently with the pointer the seam recorded.
  const digest = digestSessionData(content);
  const relPath = relative(ctx.cwd, written);
  return ok(`Gist draft written → ${relPath} (${digest})`, {
    name: GIST_DRAFT_ARTIFACT,
    path: relPath,
    digest,
    bytes: Buffer.byteLength(content, "utf8"),
    run_id: runId,
  });
}

// ------------------------------------------------------------------- the reader + the renderer

/** The validated working-gist draft shape consumers receive from `readGistDraft`. */
export interface GistDraft {
  title?: string;
  scope?: GistScope;
  prose: string;
}

/**
 * Read + validate the working-gist draft artifact. Fail-open `null` everywhere (mirroring
 * `readSessionArtifact`'s loud tier): no pointer/file/digest → `null` (the seam already spoke);
 * malformed JSON, a non-object payload, an unsupported `schema_version`, or blank prose → a
 * stderr warning + `null`. `title` is kept only when a non-blank string; `scope` only when a
 * member of the enum (an unknown scope degrades to absent, never poisons the draft). Never
 * throws.
 */
export function readGistDraft(ctx: SessionDataCtx): GistDraft | null {
  const artifact = readSessionArtifact(ctx, GIST_DRAFT_ARTIFACT);
  if (artifact === null) return null;

  const refuse = (why: string): null => {
    console.error(`perk: warning: ${GIST_DRAFT_ARTIFACT} ${why} — refusing the draft`);
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
  const title =
    typeof payload.title === "string" && payload.title.trim() ? payload.title : undefined;
  const scope =
    typeof payload.scope === "string" && (GIST_SCOPES as readonly string[]).includes(payload.scope)
      ? (payload.scope as GistScope)
      : undefined;
  return {
    ...(title !== undefined ? { title } : {}),
    ...(scope !== undefined ? { scope } : {}),
    prose,
  };
}

/**
 * Render the draft as the markdown review surface (JSON is storage/transport only — contracts
 * §8.1): the optional `# title` heading, a `Scope:` line when the hint is set, and the prose
 * verbatim. Pure; never throws.
 */
export function renderGistDraft(draft: GistDraft): string {
  let out = "";
  if (draft.title) out += `# ${draft.title}\n\n`;
  if (draft.scope) out += `Scope: ${draft.scope}\n\n`;
  return out + draft.prose;
}

const TOOL_GUIDELINES = [
  "Call gist_draft to persist the current working gist as you author or revise it; pass the FULL prose each time (it rewrites the whole draft).",
  "gist_draft never saves to the issue backend and never ends the turn — gist_save//gist-save remain the canonical save surface.",
  "Pass gist_draft's `scope` only once the consumption tier is settled: `plan` for plan-sized intent, `objective` for objective-sized intent.",
];

/** Register the `gist_draft` tool (the carve-out producer; interior-only). */
export function registerGistDraft(pi: ExtensionAPI): void {
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
      return writeGistDraft(pi, ctx, decoded);
    },
  });
}
