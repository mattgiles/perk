// The `dream_report` gate for the objective draft/review/save path (contracts.md §8.63).
//
// ONE resolver implements the whole gate matrix — `reviseObjectiveDraft` (draft.ts) and
// `saveObjective` (save.ts) both consume its typed outcome, so no parallel branch/message
// implementation can drift. "Dream session" is detected structurally, exactly
// like `run_dream_wave` (pi/v1/learning/dream.ts): the session's claimed `run_id` plus the
// existence of the run-scoped dream manifest (no claimed run counts as non-dream). The gate is
// fail-closed in BOTH directions: a dream session refuses a report-less objective (the
// objective and its report review as ONE bundle — an approval is always savable), and a
// `dream_report` outside a dream session refuses rather than being silently dropped. Absence
// on a non-dream path is byte-identical no-op behavior.
//
// Trusted-context recovery follows the session-artifacts digest-pointer doctrine: the bare
// run-scratch bundle is never trusted — the `dream_bundle_digest` workflow-state marker
// (cleared at wave entry, set to the finalized bytes' digest after a successful finalize) is
// the freshness/integrity authority, and the bundle is strictly re-decoded through the
// finalized-bundle decoder on every recovery read (untrusted-at-rest posture). The recovery
// MECHANICS are edge-owned: the resolver consumes the runtime-minted `DreamGateRecovery`
// capability (production: `pi/v1/objectiveDreamGate.ts`), so this module stays storage-free.
// After a successful recovery the revalidation bracket (contracts.md §8.65) re-proves
// HEAD-unchanged + tree-clean against the manifest's stamped `commit_sha` — at draft-write AND
// save, since both consumers flow through the one resolver; drift refuses `bad_state` (the
// analysis is stale).
//
// Imports only the dream wave siblings — cycle-free (nothing in `waves/` imports `authoring/`)
// and loadable under `node --test`.

import {
  codePointLength,
  type DreamLaneAnalysis,
  type DreamManifest,
} from "../../learning/dream.ts";
import type { DreamReducerAnalysis } from "../../learning/dreamReducer.ts";
import { buildDreamReport, type DreamReportContext } from "../../learning/dreamReport.ts";

/**
 * The shared part-invariance + size rule's comment-body cap (contracts §8.64) — the full
 * rendered companion comment (marker + blank line + part) must fit with margin under GitHub's
 * 65,536-char issue-comment limit. The Python twin is
 * `perk.learn.dream_companion.COMPANION_COMMENT_MAX_CHARS` (parity-pinned fixtures).
 */
export const COMPANION_COMMENT_MAX_CHARS = 65_000;

// The invariance shapes (the exact shapes the Linear transcoder `to_linear_markdown`
// rewrites/drops — derived locally by the same rule, mirroring the Python twin).
const MARKER_TEXT = "perk:learn-dream-report";
const PERK_HTML_MARKER_RE = /<!--\s*\/?perk:[^>]+?\s*-->/;
const DETAILS_OPEN_RE = /^<details><summary><code>[^<]*<\/code><\/summary>$/;
const DETAILS_CLOSE = "</details>";
// Every line boundary Python's `str.splitlines()` recognizes EXCEPT `\n` — the Linear
// transcoder splits on all of them and rejoins with `\n`, so any other boundary form would be
// normalized in the stored body and defeat the persistence-side byte comparison forever.
const NON_CANONICAL_LINE_BOUNDARIES = [
  "\r",
  "\v",
  "\f",
  "\u001c",
  "\u001d",
  "\u001e",
  "\u0085",
  "\u2028",
  "\u2029",
];

/**
 * The TS mirror of Python's `validate_report_parts` (contracts §8.64) — run over the freshly
 * rendered parts at draft-write AND save (both flow through `resolveDreamReportGate`), so an
 * approved report is always Python-savable: no empty/blank part, no perk HTML-comment marker,
 * no literal companion marker text, no perk-rendered `<details>` wrapper line (the shapes the
 * Linear transcoder rewrites/drops — transcode-invariance keeps the persistence-side
 * dual-candidate byte comparison exact), and every rendered comment body (marker + blank line +
 * part) within `COMPANION_COMMENT_MAX_CHARS` code points. Returns named violations (`[]` =
 * valid). Parity-pinned against the Python twin by the shared fixture set.
 */
export function reportPartInvarianceViolations(parts: string[], runId: string): string[] {
  const violations: string[] = [];
  parts.forEach((part, i) => {
    const index = i + 1;
    const where = `part ${index}`;
    if (part.trim() === "") {
      violations.push(`${where}: empty part`);
      return;
    }
    if (part.includes(MARKER_TEXT)) {
      violations.push(`${where}: carries the literal '${MARKER_TEXT}' marker text`);
    }
    if (PERK_HTML_MARKER_RE.test(part)) {
      violations.push(
        `${where}: carries a perk HTML-comment marker (<!-- perk:… --> is rewritten by the ` +
          "Linear transcoder)",
      );
    }
    if (
      part.split(/\r\n|\r|\n/).some((line) => DETAILS_OPEN_RE.test(line) || line === DETAILS_CLOSE)
    ) {
      violations.push(
        `${where}: carries a perk-rendered <details> wrapper line (dropped by the Linear ` +
          "transcoder)",
      );
    }
    if (NON_CANONICAL_LINE_BOUNDARIES.some((boundary) => part.includes(boundary))) {
      violations.push(
        `${where}: carries a line boundary other than \\n (normalized by the Linear transcoder)`,
      );
    }
    const bodyLength = codePointLength(`<!-- ${MARKER_TEXT}:${runId}:${index} -->\n\n${part}`);
    if (bodyLength > COMPANION_COMMENT_MAX_CHARS) {
      violations.push(
        `${where}: rendered comment body is ${bodyLength} chars (cap ${COMPANION_COMMENT_MAX_CHARS})`,
      );
    }
  });
  if (parts.length === 0) violations.push("parts: empty list");
  return violations;
}

/**
 * The `dream_report` block the objective-draft artifact carries (tool-written only — the model
 * never writes the artifact): the validated model input, the ONE `generated_at` stamp that
 * keeps re-rendering deterministic across review and save, and the stored CANONICAL parts the
 * review surface renders and the save byte-compares.
 */
export interface ObjectiveDreamReportBlock {
  input: unknown;
  generated_at: string;
  parts: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The artifact-side shape check `readObjectiveDraft` uses: a plain object carrying a
 * plain-object `input`, a non-blank string `generated_at`, and a non-empty all-string `parts`.
 * Deep validation stays with the resolver (the save re-runs the full gate); `null` = malformed.
 */
export function decodeDreamReportBlock(value: unknown): ObjectiveDreamReportBlock | null {
  if (!isRecord(value)) return null;
  if (!isRecord(value.input)) return null;
  if (typeof value.generated_at !== "string" || !value.generated_at.trim()) return null;
  if (!Array.isArray(value.parts) || value.parts.length === 0) return null;
  const parts: string[] = [];
  for (const part of value.parts) {
    if (typeof part !== "string") return null;
    parts.push(part);
  }
  return { input: value.input, generated_at: value.generated_at, parts };
}

/**
 * The narrow per-operation trusted-context recovery capability the Pi/session edge mints
 * (production: `productionDreamGateRecovery` in `pi/v1/objectiveDreamGate.ts`; tests inject
 * fakes). ANTI-PROOF-OBJECT CONTRACT: the decode/digest/revalidation checks behind
 * `recoverContext` and `bracket` are runtime verification executed on EVERY consuming
 * operation (draft-write and save), never replaced by a structural type, assertion, or
 * previously computed proof object.
 */
export interface DreamGateRecovery {
  /** ONE fresh workflow-state snapshot per gate resolution (run identity + freshness marker + dream detection).
   *  `detail` is always the RAW CAUSE (a caught message or a fixed cause literal) — the resolver
   *  owns the one rendering prefix; the capability never pre-renders. */
  readSession():
    | { kind: "unreadable"; detail: string }
    | { kind: "read"; runId: string | null; dream: boolean; marker: string | undefined };
  /** Fresh manifest+bundle read + the full decode/digest ladder — re-executed on EVERY call, never cached.
   *  `detail` here IS the final text (today's recovery details are complete sentences; byte-preserved). */
  recoverContext(
    runId: string,
    marker: string | undefined,
  ):
    | {
        ok: true;
        manifest: DreamManifest;
        analyses: DreamLaneAnalysis[];
        reducers: DreamReducerAnalysis[];
      }
    | { ok: false; detail: string };
  /** The §8.65 revalidation bracket against the recovered manifest's stamped commit_sha. */
  bracket(expectedSha: string): { ok: boolean; detail: string | null };
}

/** The typed gate outcome both consumers branch on — the whole matrix, one vocabulary. */
export type DreamReportGateOutcome =
  | { kind: "absent" }
  | { kind: "block"; block: ObjectiveDreamReportBlock }
  | { kind: "refuse"; errorType: "invalid_input" | "bad_state"; detail: string };

/**
 * The ONE gate resolver (contracts §8.63) — identical at draft-write and save. `input` is the
 * model-supplied `dream_report` value, or `undefined` for "no dream_report" (callers pass the
 * value only when present; an `{input: undefined}` carrier is never constructed). The matrix:
 *
 * | session   | `dream_report` | outcome |
 * | --------- | -------------- | ------- |
 * | non-dream | absent         | `absent` — unchanged, byte-identical behavior |
 * | non-dream | present        | refuse `invalid_input` (never silently dropped) |
 * | dream     | absent         | refuse `invalid_input` (one approval bundle) |
 * | dream     | present        | recover context → `buildDreamReport` → refuse or `block` |
 *
 * An UNREADABLE workflow state (`readSession()`'s `unreadable` arm — a throwing branch read,
 * or the capability's fail-closed run-id/marker narrowing) refuses `bad_state` BEFORE the
 * matrix — it is never conflated with a confirmed non-dream session (the `activeSessionRunId`
 * null-on-throw sentinel would otherwise let a transient read failure surface as `absent`).
 * The capability's `detail` is the RAW CAUSE; this resolver owns the one rendering prefix.
 *
 * Failure taxonomy: gate violations + `buildDreamReport` refusals → `invalid_input` (the
 * bounded ≤25 named details newline-joined); an unreadable workflow state and
 * context-recovery failures → `bad_state` (recovery details pass through UNPREFIXED).
 */
export function resolveDreamReportGate(
  recovery: DreamGateRecovery,
  input: unknown,
  generatedAt: string,
): DreamReportGateOutcome {
  // ONE workflow-state snapshot for the whole gate (run identity + the freshness marker +
  // dream detection), read with error distinction: unreadable state fails closed, never
  // "non-dream".
  const session = recovery.readSession();
  if (session.kind === "unreadable") {
    return {
      kind: "refuse",
      errorType: "bad_state",
      detail: `session workflow state is unreadable — cannot resolve the dream_report gate: ${session.detail}`,
    };
  }
  const runId = session.runId;
  if (runId === null || !session.dream) {
    if (input === undefined) return { kind: "absent" };
    return {
      kind: "refuse",
      errorType: "invalid_input",
      detail:
        "dream_report is only valid inside a perk learn dream session — refusing rather than " +
        "silently dropping it",
    };
  }
  if (input === undefined) {
    return {
      kind: "refuse",
      errorType: "invalid_input",
      detail:
        "this dream session's objective must carry dream_report — the objective and its " +
        "report review as one bundle",
    };
  }
  // The marker rides the SAME snapshot as the run identity (the one-snapshot rule); the
  // capability re-executes the full read+decode+digest ladder on every call, never caching.
  const recovered = recovery.recoverContext(runId, session.marker);
  if (!recovered.ok) {
    return { kind: "refuse", errorType: "bad_state", detail: recovered.detail };
  }
  const context: DreamReportContext = {
    manifest: recovered.manifest,
    analyses: recovered.analyses,
    reducers: recovered.reducers,
    run_id: runId,
    generated_at: generatedAt,
  };
  // The revalidation-bracket re-check (contracts.md §8.65): the manifest — with its stamped
  // commit_sha — is now decoded and authenticated, so re-prove HEAD-unchanged + tree-clean
  // against it. Both `writeObjectiveDraft` and `saveObjective` flow through this resolver, so
  // the bracket re-fires at draft-write AND save; non-dream paths never reach it (the matrix
  // above returned already).
  const drift = recovery.bracket(context.manifest.commit_sha);
  if (!drift.ok) {
    return {
      kind: "refuse",
      errorType: "bad_state",
      detail:
        `the repository moved since the dream snapshot (${drift.detail}) — the analysis is ` +
        "stale; re-run perk learn dream",
    };
  }
  const built = buildDreamReport(input, context);
  if (!built.ok) {
    return { kind: "refuse", errorType: "invalid_input", detail: built.details.join("\n") };
  }
  // The §8.64 invariance mirror, at draft-write AND save (this resolver is both), so an
  // approved report is always savable by the Python door's identical rule.
  const violations = reportPartInvarianceViolations(built.parts, runId);
  if (violations.length > 0) {
    return {
      kind: "refuse",
      errorType: "invalid_input",
      detail: `dream report parts violate the invariance rule: ${violations.join("; ")}`,
    };
  }
  return { kind: "block", block: { input, generated_at: generatedAt, parts: built.parts } };
}
