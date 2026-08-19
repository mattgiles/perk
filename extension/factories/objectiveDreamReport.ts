// The `dream_report` gate for the objective draft/review/save path (contracts.md §8.63).
//
// ONE resolver implements the whole gate matrix — `writeObjectiveDraft` (objectiveDraft.ts)
// and `saveObjective` (objectiveSave.ts) both consume its typed outcome, so no parallel
// branch/message implementation can drift. "Dream session" is detected structurally, exactly
// like `run_dream_wave` (doors/dreamWaveTools.ts): the session's claimed `run_id` plus the
// existence of the run-scoped dream manifest (no claimed run counts as non-dream). The gate is
// fail-closed in BOTH directions: a dream session refuses a report-less objective (the
// objective and its report review as ONE bundle — an approval is always savable), and a
// `dream_report` outside a dream session refuses rather than being silently dropped. Absence
// on a non-dream path is byte-identical no-op behavior.
//
// Trusted-context recovery follows the session-artifacts digest-pointer doctrine: the bare
// run-scratch bundle is never trusted — the `dream_bundle_digest` workflow-state marker
// (cleared at wave entry, set to the finalized bytes' digest after a successful finalize) is
// the freshness/integrity authority, and the bundle is strictly re-decoded through
// `decodeFinalizedDreamBundle` on every recovery read (untrusted-at-rest posture).
//
// Imports only the dream wave siblings, the substrate seams, and node builtins — cycle-free
// (nothing in `waves/` imports factories) and loadable under `node --test`.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { runScratchDir } from "../substrate/cache.ts";
import {
  activeSessionRunId,
  digestSessionData,
  type SessionDataCtx,
} from "../substrate/sessionData.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { DREAM_ANALYSES_FILENAME, decodeFinalizedDreamBundle } from "../waves/dreamReducerWave.ts";
import { buildDreamReport, type DreamReportContext } from "../waves/dreamReport.ts";
import { DREAM_MANIFEST_FILENAME, decodeDreamManifest } from "../waves/dreamWave.ts";

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
 * Recover the trusted `DreamReportContext` from the claimed run's scratch state — every arm
 * fail-closed with a named detail (the caller maps them to `bad_state`):
 *
 *  1. the run-scoped manifest: read + parse + `decodeDreamManifest` (the strict §8.60 decoder,
 *     path bound at decode time). No `verifyDocContainment` — this path reads no doc files;
 *     the lexical decode suffices (resolved containment is the wave tool's pre-spawn concern);
 *  2. the freshness check: the rebuilt `dream_bundle_digest` marker must be present, non-empty,
 *     and equal the digest of the bundle bytes just read — a bare file is never trusted
 *     (missing marker = no finalized wave; empty = invalidated by a newer attempt, including a
 *     cleanup-failure residue; mismatch = stale/tampered bytes);
 *  3. the strict finalized decode (`decodeFinalizedDreamBundle` — the analyses-only mid-wave
 *     shape refuses here).
 */
function recoverDreamReportContext(
  ctx: SessionDataCtx,
  runId: string,
  generatedAt: string,
): { ok: true; context: DreamReportContext } | { ok: false; detail: string } {
  const manifestPath = join(runScratchDir(ctx.cwd, runId), DREAM_MANIFEST_FILENAME);
  let rawManifest: unknown;
  try {
    rawManifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { ok: false, detail: `dream manifest unreadable at '${manifestPath}': ${detail}` };
  }
  const manifest = decodeDreamManifest(rawManifest, manifestPath);
  if (!manifest.ok) {
    return { ok: false, detail: `dream manifest invalid: ${manifest.detail}` };
  }

  const bundlePath = join(dirname(manifestPath), DREAM_ANALYSES_FILENAME);
  let bundleBytes: string;
  try {
    bundleBytes = readFileSync(bundlePath, "utf8");
  } catch {
    return {
      ok: false,
      detail: `no dream bundle at '${bundlePath}' — re-run the dream wave`,
    };
  }
  const marker = rebuildWorkflowState(branchOf(ctx)).dream_bundle_digest;
  if (marker === undefined || marker === "") {
    return {
      ok: false,
      detail: "no finalized dream wave for this session — re-run the dream wave",
    };
  }
  if (digestSessionData(bundleBytes) !== marker) {
    return {
      ok: false,
      detail:
        "the dream bundle does not match the session's finalized digest — re-run the dream wave",
    };
  }
  let rawBundle: unknown;
  try {
    rawBundle = JSON.parse(bundleBytes);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { ok: false, detail: `dream bundle is not valid JSON: ${detail}` };
  }
  const decoded = decodeFinalizedDreamBundle(rawBundle, manifest.manifest);
  if (!decoded.ok) {
    return { ok: false, detail: `${decoded.detail} — re-run the dream wave` };
  }
  return {
    ok: true,
    context: {
      manifest: manifest.manifest,
      analyses: decoded.analyses,
      reducers: decoded.reducers,
      run_id: runId,
      generated_at: generatedAt,
    },
  };
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
 * Failure taxonomy: gate violations + `buildDreamReport` refusals → `invalid_input` (the
 * bounded ≤25 named details newline-joined); context-recovery failures → `bad_state`.
 */
export function resolveDreamReportGate(
  ctx: SessionDataCtx,
  input: unknown,
  generatedAt: string,
): DreamReportGateOutcome {
  const runId = activeSessionRunId(ctx);
  const dream =
    runId !== null && existsSync(join(runScratchDir(ctx.cwd, runId), DREAM_MANIFEST_FILENAME));
  if (runId === null || !dream) {
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
  const recovered = recoverDreamReportContext(ctx, runId, generatedAt);
  if (!recovered.ok) {
    return { kind: "refuse", errorType: "bad_state", detail: recovered.detail };
  }
  const built = buildDreamReport(input, recovered.context);
  if (!built.ok) {
    return { kind: "refuse", errorType: "invalid_input", detail: built.details.join("\n") };
  }
  return { kind: "block", block: { input, generated_at: generatedAt, parts: built.parts } };
}
