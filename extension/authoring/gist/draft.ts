// The gist working-draft feature: the typed `GistDraft` model, its schema_version-1 JSON
// encode/decode (JSON is storage/transport only — the review surface is `renderGistDraft`'s
// markdown, never raw bytes), and the two draft operations over the WorkflowSession seam.
//
// Carve-out doctrine: the artifact name is the fixed constant `GIST_DRAFT_ARTIFACT` and every
// byte flows through the session seam (file + verified `session_artifacts` pointer), so the only
// thing the draft ops can ever touch is the one working-gist artifact in the current run's data
// dir (gitignored scratch). A revision is a WHOLE-VALUE replacement — no revision ids, no
// compare-and-swap claims the backing cannot prove.
//
// Format doctrine: the artifact carries `{schema_version, title?, scope?, prose}` — deliberately
// light: a gist is a problem-space statement of intent with no structured roadmap
// (contracts.md §8.41).

import type { SessionArtifactPointer } from "../../substrate/workflowState.ts";
import type { WorkflowSession } from "../../session/workflowSession.ts";

/** The registry stage id of the gist-authoring session (shared with planMode's defer check). */
export const GIST_AUTHOR_STAGE = "gist-author";

/** The gist consumption tiers (`scope` — contracts.md §8.41). */
export const GIST_SCOPES = ["plan", "objective"] as const;

export type GistScope = (typeof GIST_SCOPES)[number];

/** The fixed working-gist artifact name (one JSON file: the prose + the optional scope hint). */
export const GIST_DRAFT_ARTIFACT = "gist-draft.json";

/** The validated working-gist draft shape. */
export interface GistDraft {
  title?: string;
  scope?: GistScope;
  prose: string;
}

/**
 * Serialize a working gist as the schema_version-1 JSON artifact: deterministic key order via
 * the explicit literal; `title`/`scope` omitted when blank — byte-identical to what the artifact
 * always carried. Pure; never throws.
 */
export function encodeGistDraft(draft: { prose: string; title?: string; scope?: GistScope }): string {
  const title = draft.title?.trim();
  const payload = {
    schema_version: 1,
    ...(title ? { title } : {}),
    ...(draft.scope ? { scope: draft.scope } : {}),
    prose: draft.prose,
  };
  return `${JSON.stringify(payload, null, 2)}\n`;
}

/**
 * Decode + validate working-gist artifact bytes. Fail-open `null` with a stderr warning on
 * malformed JSON, a non-object payload, an unsupported `schema_version`, or blank prose (the
 * same refusal taxonomy + warning strings the reader always had). `title` is kept only when a
 * non-blank string; `scope` only when a member of the enum (an unknown scope degrades to
 * absent, never poisons the draft). Never throws.
 */
export function decodeGistDraft(content: string): GistDraft | null {
  const refuse = (why: string): null => {
    console.error(`perk: warning: ${GIST_DRAFT_ARTIFACT} ${why} — refusing the draft`);
    return null;
  };
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
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

/**
 * The revise outcome. `rejected` splits by `reason` so the adapter renders the exact failure
 * taxonomy it always had: `blank_prose` (input refused), `no_identity` (no session), and
 * `write_refused` (the seam refused before any effect); `unverified` means an effect may have
 * landed but the read-back proof failed. `problem` carries the caller-facing message bytes.
 */
export type ReviseGistDraftResult =
  | { status: "revised"; pointer: SessionArtifactPointer; bytes: number }
  | { status: "unchanged"; pointer: SessionArtifactPointer; bytes: number }
  | { status: "rejected"; reason: "blank_prose" | "no_identity" | "write_refused"; problem: string }
  | { status: "unverified"; problem: string };

/**
 * Rewrite the working gist draft (a whole-value replacement) through the session seam.
 * Diagnostic precedence preserved: blank prose is refused FIRST, missing identity second
 * (`session: null` — an identity-less caller is representable without a session), then the
 * verified artifact write. Never throws.
 */
export function reviseGistDraft(
  input: { prose: string; title?: string; scope?: GistScope },
  session: WorkflowSession | null,
): ReviseGistDraftResult {
  if (!input.prose.trim()) {
    return {
      status: "rejected",
      reason: "blank_prose",
      problem: "no gist prose to write (pass the full working draft)",
    };
  }
  if (session === null) {
    return {
      status: "rejected",
      reason: "no_identity",
      problem: "session has no run_id — cannot write the gist-draft artifact",
    };
  }
  const content = encodeGistDraft(input);
  const bytes = Buffer.byteLength(content, "utf8");
  const written = session.writeArtifact(GIST_DRAFT_ARTIFACT, content);
  switch (written.status) {
    case "applied":
      return { status: "revised", pointer: written.pointer, bytes };
    case "unchanged":
      return { status: "unchanged", pointer: written.pointer, bytes };
    case "rejected":
      return {
        status: "rejected",
        reason: "write_refused",
        problem: `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
      };
    case "unverified":
      return {
        status: "unverified",
        problem: `could not write the ${GIST_DRAFT_ARTIFACT} artifact (see warnings)`,
      };
  }
}

/**
 * Resume the working gist draft from the session. Fail-open `null` everywhere: `absent` is the
 * silent no-draft arm; `invalid` was already warned by the seam; a decodable-but-refused payload
 * warns through `decodeGistDraft`'s refusal taxonomy. Never throws.
 */
export function resumeGistDraft(session: WorkflowSession): GistDraft | null {
  const read = session.readArtifact(GIST_DRAFT_ARTIFACT);
  if (read.status !== "found") return null;
  return decodeGistDraft(read.content);
}
