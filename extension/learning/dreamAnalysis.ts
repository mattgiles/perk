// The learn-dream analysis workflow as ONE typed feature operation — the two-level
// ordering/recovery POLICY sitting above the analyst tier (`dream.ts`) and the reducer tier
// (`dreamReducer.ts`). The sequence: the first-level analyst wave (strict) → the compact
// analyst bundle written under the enforced aggregate byte budget → the three fixed reducer
// lanes — reducers launch ONLY after a complete first wave and an in-budget write — then, only
// when BOTH waves completed, the revalidation bracket against the manifest's stamped
// `commit_sha` (drift skips the finalize AND the marker set — a drifted wave is structurally
// undraftable) and, bracket ok, the finalize-in-place rewrite of the same fixed name
// (`finalizeDreamBundle`, the added `reducers` section). Two writes of ONE name: the analyst
// write feeds the reducers; the finalize rewrite is what the dream-report recovery consumes.
// The `dream_bundle_digest` workflow-state marker is the recovery-side freshness authority:
// cleared unconditionally at entry BEFORE the stale-bundle removal attempt (the invalidation
// record — a failed cleanup leaves prior files behind, but recovery refuses them), set to the
// sha256 of the finalized bytes only after the finalize write succeeds.
//
// Pi-free by construction: the `ReportWave` seam and the function-shaped
// capabilities (`markBundleDigest`, `bracket`, `writeBundle`, `removeBundle`) are the only
// mechanism edges — the adapter constructs and threads them; artifact storage is never owned
// here. Analyst and reducer reports are untrusted DATA, re-decoded in code before they reach
// the caller. (contracts.md §8.61/§8.65)

import { dirname, join } from "node:path";
import type { ReportWave, ReportWaveAttemptReceipt } from "../waves/reportWave.ts";
import {
  type DreamLaneAnalysis,
  type DreamLaneFailure,
  type DreamManifest,
  runDreamAnalystWave,
} from "./dream.ts";
import {
  composeDreamBundle,
  DREAM_ANALYSES_FILENAME,
  DREAM_BUNDLE_BUDGET_BYTES,
  type DreamReducerAnalysis,
  type DreamReducerFailure,
  finalizeDreamBundle,
  nonKeepProposals,
  runDreamReducerWave,
} from "./dreamReducer.ts";

/** The first-level analysis section every aggregate arm carries. */
interface AnalysisSection<C extends boolean> {
  complete: C;
  analyses: DreamLaneAnalysis[];
  failures: DreamLaneFailure[];
}

/** The reducer section on the two pre-launch skip arms. */
interface SkippedReducers<R extends "incomplete-analysis" | "budget-exceeded"> {
  launched: false;
  skip_reason: R;
  complete: false;
  reports: [];
  failures: [];
}

/** The reducer section after a launch (failures only when the wave stayed incomplete — plus
 * the synthetic `digest-marker` entry on the failed-marker-set arm). */
interface LaunchedReducers<C extends boolean, F extends DreamReducerFailure[] | []> {
  launched: true;
  skip_reason: null;
  complete: C;
  reports: DreamReducerAnalysis[];
  failures: F;
}

/** The written-bundle accounting (the happy write: in budget, `overflow_bytes` pinned 0). */
interface WrittenBundle {
  path: string;
  written: true;
  bytes: number;
  budget_bytes: number;
  overflow_bytes: 0;
}

/**
 * The typed normalized aggregate — a discriminated union of the real post-launch arms over the
 * exact wire fields (`complete`, `bundle` null/`written`, `bracket` null/`ok`, the
 * `reducers.skip_reason` literals), each arm constructed at exactly one policy site, so
 * contradictory combinations (e.g. `complete: true` with `bracket: null`) are unrepresentable
 * while the serialized JSON stays byte-identical to the flat aggregate shape. Arms in policy
 * order: incomplete first wave (no bundle, no bracket, no reducers) · over-budget (explicit
 * accounting, nothing written — the loud corpus-growth tripwire, never truncation) ·
 * incomplete reducer wave (the analyses-only bundle stays behind with a cleared marker) ·
 * bracket drift (both waves done; finalize + marker set skipped — structurally undraftable) ·
 * failed marker set (finalize landed; the unverified append is the synthetic `digest-marker`
 * failure — honestly incomplete) · complete.
 */
export type DreamAnalysisAggregate = { attempts: ReportWaveAttemptReceipt[] } & (
  | {
      complete: false;
      analysis: AnalysisSection<false>;
      bracket: null;
      bundle: null;
      reducers: SkippedReducers<"incomplete-analysis">;
    }
  | {
      complete: false;
      analysis: AnalysisSection<true>;
      bracket: null;
      bundle: {
        path: string;
        written: false;
        bytes: number;
        budget_bytes: number;
        overflow_bytes: number;
      };
      reducers: SkippedReducers<"budget-exceeded">;
    }
  | {
      complete: false;
      analysis: AnalysisSection<true>;
      bracket: null;
      bundle: WrittenBundle;
      reducers: LaunchedReducers<false, DreamReducerFailure[]>;
    }
  | {
      complete: false;
      analysis: AnalysisSection<true>;
      bracket: { ok: false; detail: string | null };
      bundle: WrittenBundle;
      reducers: LaunchedReducers<true, []>;
    }
  | {
      complete: false;
      analysis: AnalysisSection<true>;
      bracket: { ok: true; detail: string | null };
      bundle: WrittenBundle;
      reducers: LaunchedReducers<true, DreamReducerFailure[]>;
    }
  | {
      complete: true;
      analysis: AnalysisSection<true>;
      bracket: { ok: true; detail: string | null };
      bundle: WrittenBundle;
      reducers: LaunchedReducers<true, []>;
    }
);

/**
 * The typed dream-analysis outcome: ONE `io_failed` arm for every io site — the unverified
 * marker clear, a failed stale-bundle removal, a bundle-write throw, a finalize-write throw —
 * retaining the analyst analyses AND every already-recorded attempt receipt (empty arrays
 * pre-launch); or the post-launch `aggregate`.
 */
export type DreamAnalysisOutcome =
  | {
      kind: "io_failed";
      detail: string;
      analyses: DreamLaneAnalysis[];
      attempts: ReportWaveAttemptReceipt[];
    }
  | { kind: "aggregate"; details: DreamAnalysisAggregate };

/**
 * The one dream-analysis entry op — the two-level ordering/recovery policy with every
 * capability REQUIRED (the compiler walks every call site to an explicit choice; the adapter
 * wires production seams, tests inject fakes). Caller preconditions: the manifest came from
 * `decodeDreamManifest` and `verifyDocContainment` was run (the registered tool's pre-spawn
 * ladder). The ordered sequence and each step's invariant are commented at their policy sites
 * below: verified marker clear → entry-time bundle removal → the strict analyst wave → the
 * budget check before reducer composition → the analyst-bundle write → the reducer wave → the
 * §8.65 bracket (only after BOTH waves) → the finalize-in-place rewrite → the marker set.
 */
export async function analyzeDream(
  wave: ReportWave,
  opts: {
    manifest: DreamManifest;
    /** The `sha256:<hex>` digest of the manifest BYTES the caller read + decoded — bound into
     * the finalized bundle so recovery authenticates the manifest too. */
    manifestDigest: string;
    /** The one function-shaped `dream_bundle_digest` marker capability: `null` is the
     * invalidation clear; a string is the FINALIZED BUNDLE BYTES, digested by the capability
     * owner (the digest convention lives with the adapter, not the feature); the boolean is
     * the verified append+read-back result. The adapter wires the production
     * `appendWorkflowState` closure; tests inject fakes. */
    markBundleDigest: (finalized: string | null) => boolean;
    /** The post-wave revalidation bracket (contracts.md §8.65) — REQUIRED on purpose: every
     * call site (production and tests) makes an explicit choice; production wires
     * `revalidationBracket(ctx.cwd, manifest.commit_sha)`. */
    bracket: () => { ok: boolean; detail: string | null };
    writeBundle: (path: string, content: string) => void;
    removeBundle: (path: string) => void;
    analystModel?: string;
    reducerModel?: string;
    signal?: AbortSignal;
  },
): Promise<DreamAnalysisOutcome> {
  // The invalidation record FIRST: any new attempt clears the digest marker before the removal
  // attempt below, so a failed cleanup leaves prior files behind that recovery refuses. An
  // UNVERIFIED clear refuses outright — with the old digest possibly still live, a failed
  // removal below would leave the prior bundle+digest pair recoverable as fresh.
  if (!opts.markBundleDigest(null)) {
    return {
      kind: "io_failed",
      detail:
        "dream_bundle_digest invalidation could not be verified — refusing to run the wave " +
        "over possibly-recoverable prior finalized state",
      analyses: [],
      attempts: [],
    };
  }

  // One path authority: the bundle lives beside the decode-time-bound manifest path — no
  // second runScratchDir derivation inside this op. A failed removal refuses BEFORE any
  // spawn (a typed io_failed, never an uncaught throw): launching over an irremovable stale
  // bundle would break the current-attempt-only invariant.
  const bundlePath = join(dirname(opts.manifest.manifestPath), DREAM_ANALYSES_FILENAME);
  try {
    opts.removeBundle(bundlePath);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      kind: "io_failed",
      detail: `stale dream bundle removal failed at '${bundlePath}': ${detail}`,
      analyses: [],
      attempts: [],
    };
  }

  const analysis = await runDreamAnalystWave(
    wave,
    {
      manifest: opts.manifest,
      ...(opts.analystModel !== undefined ? { model: opts.analystModel } : {}),
    },
    opts.signal,
  );
  const attempts = [analysis.attempt];

  if (!analysis.complete) {
    // STRICT: no bundle write, no reducer launch after an incomplete first wave.
    return {
      kind: "aggregate",
      details: {
        complete: false,
        analysis: { complete: false, analyses: analysis.analyses, failures: analysis.failures },
        bracket: null,
        bundle: null,
        reducers: {
          launched: false,
          skip_reason: "incomplete-analysis",
          complete: false,
          reports: [],
          failures: [],
        },
        attempts,
      },
    };
  }
  const analysisDetails = {
    complete: true as const,
    analyses: analysis.analyses,
    failures: analysis.failures,
  };

  const { content, bytes } = composeDreamBundle(opts.manifest, analysis.analyses);
  if (bytes > DREAM_BUNDLE_BUDGET_BYTES) {
    // The loud corpus-growth tripwire: explicit accounting, nothing written, no reducers —
    // never truncation (enforced BEFORE reducer task composition).
    return {
      kind: "aggregate",
      details: {
        complete: false,
        analysis: analysisDetails,
        bracket: null,
        bundle: {
          path: bundlePath,
          written: false,
          bytes,
          budget_bytes: DREAM_BUNDLE_BUDGET_BYTES,
          overflow_bytes: bytes - DREAM_BUNDLE_BUDGET_BYTES,
        },
        reducers: {
          launched: false,
          skip_reason: "budget-exceeded",
          complete: false,
          reports: [],
          failures: [],
        },
        attempts,
      },
    };
  }

  try {
    opts.writeBundle(bundlePath, content);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      kind: "io_failed",
      detail: `dream bundle write failed: ${detail}`,
      analyses: analysis.analyses,
      attempts,
    };
  }
  const bundleDetails: WrittenBundle = {
    path: bundlePath,
    written: true,
    bytes,
    budget_bytes: DREAM_BUNDLE_BUDGET_BYTES,
    overflow_bytes: 0,
  };

  const reducers = await runDreamReducerWave(
    wave,
    {
      manifestPath: opts.manifest.manifestPath,
      bundlePath,
      proposals: nonKeepProposals(analysis.analyses),
      ...(opts.reducerModel !== undefined ? { model: opts.reducerModel } : {}),
    },
    opts.signal,
  );
  attempts.push(reducers.attempt);

  if (!reducers.complete) {
    // An incomplete reducer wave leaves the analyses-only bundle and a cleared marker (the
    // finalized decode refuses it); the bracket is never evaluated on an earlier arm.
    return {
      kind: "aggregate",
      details: {
        complete: false,
        analysis: analysisDetails,
        bracket: null,
        bundle: bundleDetails,
        reducers: {
          launched: true,
          skip_reason: null,
          complete: false,
          reports: reducers.reports,
          failures: reducers.failures,
        },
        attempts,
      },
    };
  }

  // The post-wave revalidation bracket (§8.65): evaluated only after BOTH waves completed,
  // BEFORE the finalize write. Drift skips the finalize AND the marker set — the entry
  // clear stands, so recovery refuses the analyses-only bundle left behind (a drifted wave
  // is structurally undraftable); the analyses + reducer reports stay in the aggregate for
  // honest coverage reporting.
  const bracket = opts.bracket();
  if (!bracket.ok) {
    return {
      kind: "aggregate",
      details: {
        complete: false,
        analysis: analysisDetails,
        bracket: { ok: false, detail: bracket.detail },
        bundle: bundleDetails,
        reducers: {
          launched: true,
          skip_reason: null,
          complete: true,
          reports: reducers.reports,
          failures: [],
        },
        attempts,
      },
    };
  }

  // Finalize in place — the SAME fixed name gains the reducers section (never a second
  // file), then the digest marker publishes the finalized bytes for the recovery consumer.
  // An incomplete reducer wave never reaches here: the analyses-only shape stays behind with
  // a cleared marker, and the finalized decode refuses it.
  const finalized = finalizeDreamBundle(
    opts.manifest,
    analysis.analyses,
    reducers.reports,
    opts.manifestDigest,
  );
  try {
    opts.writeBundle(bundlePath, finalized);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      kind: "io_failed",
      detail: `dream bundle finalize write failed: ${detail}`,
      analyses: analysis.analyses,
      attempts,
    };
  }

  // A failed marker append (an unverified read-back) leaves the marker cleared by the
  // entry clear — recovery refuses (fail-closed) — and the aggregate reports the outcome
  // as honestly incomplete; re-running the wave repairs it.
  if (!opts.markBundleDigest(finalized)) {
    return {
      kind: "aggregate",
      details: {
        complete: false,
        analysis: analysisDetails,
        bracket: { ok: true, detail: bracket.detail },
        bundle: bundleDetails,
        reducers: {
          launched: true,
          skip_reason: null,
          complete: true,
          reports: reducers.reports,
          failures: [
            {
              angle: "digest-marker",
              reason: "run-failed",
              detail:
                "dream_bundle_digest marker append failed its read-back — the marker stays " +
                "cleared, so recovery refuses this bundle; re-run perk learn dream",
            },
          ],
        },
        attempts,
      },
    };
  }

  return {
    kind: "aggregate",
    details: {
      complete: true,
      analysis: analysisDetails,
      bracket: { ok: true, detail: bracket.detail },
      bundle: bundleDetails,
      reducers: {
        launched: true,
        skip_reason: null,
        complete: true,
        reports: reducers.reports,
        failures: [],
      },
      attempts,
    },
  };
}
