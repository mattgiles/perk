// The production `DreamGateRecovery` capability for the §8.63 `dream_report` gate — the
// Pi/session edge that mints the resolver's trusted-context recovery per operation. The
// mechanics live HERE (workflow-state snapshot, run-scratch reads, the decode/digest ladder,
// the §8.65 bracket) so `authoring/objective/dreamReportGate.ts` stays storage-free; the gate
// matrix, outcome union, and every rendered byte stay with the resolver.
//
// Fail-closed hardenings at this edge (both classify as `unreadable` → the resolver's
// `bad_state`, never a silent "non-dream"): the claimed run_id is narrowed through
// `isSafeRunId` BEFORE any path derivation (the canonical read-path trust boundary — the
// `activeSessionRunId` degrade-to-null posture is for the identity-optional data seam; the
// gate refuses loudly on a pathological id), and the `dream_bundle_digest` marker is
// runtime-narrowed to string-or-absent (the rebuilt state is a cast — a mistyped marker is
// corrupted state, not "no finalized wave").

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { DreamGateRecovery } from "../../authoring/objective/dreamReportGate.ts";
import { DREAM_MANIFEST_FILENAME, decodeDreamManifest } from "../../learning/dream.ts";
import {
  DREAM_ANALYSES_FILENAME,
  decodeFinalizedDreamBundle,
} from "../../learning/dreamReducer.ts";
import { isSafeRunId, runScratchDir } from "../../substrate/cache.ts";
import { revalidationBracket } from "../../substrate/git.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import {
  branchOf,
  rebuildWorkflowState,
  type WorkflowState,
} from "../../substrate/workflowState.ts";

/**
 * Mint the production recovery capability over the live session context. Every `detail` on the
 * `unreadable` arm is the RAW CAUSE (the resolver owns the rendering prefix); `recoverContext`
 * details are the final text, byte-preserved from the recovery ladder this capability carries.
 * `recoverContext` re-executes the full read+decode+digest ladder on EVERY call (the
 * anti-proof-object contract — nothing is cached across calls); `runId` only ever arrives from
 * `readSession()`'s narrowing (the one mint point).
 */
export function productionDreamGateRecovery(ctx: ExtensionContext): DreamGateRecovery {
  return {
    readSession() {
      let state: WorkflowState;
      try {
        state = rebuildWorkflowState(branchOf(ctx));
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        return { kind: "unreadable", detail };
      }
      // The rebuilt state is a CAST, not runtime-validated — narrow both fields here.
      const rawRunId: unknown = state.run_id;
      const claimed = typeof rawRunId === "string" && rawRunId.length > 0 ? rawRunId : null;
      if (claimed !== null && !isSafeRunId(claimed)) {
        // Fail-closed BEFORE any path derivation: a pathological claimed id refuses loudly
        // rather than degrading to "non-dream".
        return { kind: "unreadable", detail: "claimed run_id is not a safe path component" };
      }
      const rawMarker: unknown = state.dream_bundle_digest;
      if (rawMarker !== undefined && typeof rawMarker !== "string") {
        // Corrupted state is bad_state, not "no finalized wave" — mapping a mistyped marker
        // to absent would misreport corruption.
        return { kind: "unreadable", detail: "workflow-state dream_bundle_digest is not a string" };
      }
      // The empty string is kept as-is — it is the invalidation residue the recovery ladder
      // already refuses.
      const marker = rawMarker;
      const dream =
        claimed !== null &&
        existsSync(join(runScratchDir(ctx.cwd, claimed), DREAM_MANIFEST_FILENAME));
      return { kind: "read", runId: claimed, dream, marker };
    },

    /**
     * The trusted-context recovery ladder — every arm fail-closed with a named detail (the
     * resolver maps them to `bad_state`):
     *
     *  1. the run-scoped manifest: read + parse + `decodeDreamManifest` (the strict §8.60
     *     decoder, path bound at decode time). No `verifyDocContainment` — this path reads no
     *     doc files; the lexical decode suffices (resolved containment is the wave tool's
     *     pre-spawn concern);
     *  2. the freshness check: the `dream_bundle_digest` marker (from the resolver's ONE
     *     workflow-state snapshot) must be present, non-empty, and equal the digest of the
     *     bundle bytes just read — a bare file is never trusted (missing marker = no finalized
     *     wave; empty = invalidated by a newer attempt, including a cleanup-failure residue;
     *     mismatch = stale/tampered bytes);
     *  3. the strict finalized decode (`decodeFinalizedDreamBundle` over the digest of the
     *     manifest bytes just read — the marker authenticates the bundle bytes and the
     *     bundle's `manifest_digest` extends that authority to the manifest, so an at-rest
     *     manifest edit refuses; the analyses-only mid-wave shape refuses here too).
     */
    recoverContext(runId, marker) {
      const manifestPath = join(runScratchDir(ctx.cwd, runId), DREAM_MANIFEST_FILENAME);
      let manifestBytes: string;
      let rawManifest: unknown;
      try {
        manifestBytes = readFileSync(manifestPath, "utf8");
        rawManifest = JSON.parse(manifestBytes);
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
      const decoded = decodeFinalizedDreamBundle(
        rawBundle,
        manifest.manifest,
        digestSessionData(manifestBytes),
      );
      if (!decoded.ok) {
        return { ok: false, detail: `${decoded.detail} — re-run the dream wave` };
      }
      return {
        ok: true,
        manifest: manifest.manifest,
        analyses: decoded.analyses,
        reducers: decoded.reducers,
      };
    },

    bracket(expectedSha) {
      // The production §8.65 bracket: END-STATE HEAD + tree-clean against the manifest's
      // stamped commit — fail-closed (an unprovable probe reads as drift).
      return revalidationBracket(ctx.cwd, expectedSha);
    },
  };
}
