// The shared persisted-dream test fixture (offline, minimal): ONE 1-lane / 1-doc dream corpus
// whose doc final-keeps — so a valid §8.62 report input needs no curation units — planted as
// the real run-scratch files the §8.63 gate recovers (the manifest + the FINALIZED bundle with
// its bound manifest digest) over a REAL clean git repo whose HEAD is the stamped `commit_sha`,
// so the boundary suites exercise the production revalidation bracket (contracts.md §8.65)
// end-to-end. Both objective boundary suites (objectiveDraft.test.ts, objectiveSave.test.ts)
// and the dream-wave registered-tool e2e consume this one encoding of the persisted format
// instead of each maintaining a copy; the resolver suite (objectiveDreamReport.test.ts) keeps
// its own richer 2-lane fixture (with injected bracket stubs) because it exercises
// proposal/stance shapes and per-arm corruption this minimal fixture deliberately lacks.
// Test-only — never imported by production modules.

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { runScratchDir } from "../substrate/cache.ts";
import { digestSessionData } from "../substrate/sessionData.ts";
import {
  DREAM_ANALYSES_FILENAME,
  DREAM_REDUCER_ANGLES,
  type DreamReducerAnalysis,
  finalizeDreamBundle,
} from "../waves/dreamReducerWave.ts";
import {
  DREAM_MANIFEST_FILENAME,
  type DreamLaneAnalysis,
  type DreamManifest,
  decodeDreamManifest,
} from "../waves/dreamWave.ts";

/** The one corpus doc (final disposition keep). */
export const DREAM_FIXTURE_DOC = "docs/learned/pi/subagents.md";

/** The minimal 1-lane / 1-doc raw producer manifest, stamped with `commitSha`. */
export function dreamRawManifest(commitSha = "abc123"): Record<string, unknown> {
  return {
    schema_version: "1",
    commit_sha: commitSha,
    registry_mode: "clusters",
    doc_count: 1,
    total_bytes: 100,
    findings: {
      structural: {
        stale_pointers: [],
        broken_doc_paths: [],
        duplicate_cues: [],
        missing_frontmatter: [],
      },
      advisory: {
        distillation_issues: [],
        source_code_blocks: [],
        overlong_cues: [],
        cue_hazards: [],
        empty_clusters: [],
      },
    },
    lanes: [
      {
        id: "pi-1",
        rollup: null,
        docs: [
          { path: DREAM_FIXTURE_DOC, title: null, read_when: null, cluster: null, bytes: 100 },
        ],
      },
    ],
  };
}

/** The exact manifest bytes `plantDreamFiles` writes (what the bound manifest digest covers). */
export function dreamManifestBytes(commitSha = "abc123"): string {
  return `${JSON.stringify(dreamRawManifest(commitSha), null, 2)}\n`;
}

/** One complete analyst wave over the fixture corpus (the doc proposed keep). */
export function dreamAnalyses(): DreamLaneAnalysis[] {
  return [
    {
      lane: "pi-1",
      report: {
        docs: [
          {
            path: DREAM_FIXTURE_DOC,
            disposition: "keep",
            merge_target: null,
            rationale: "still true",
            preserve: [],
            evidence_checked: [],
            confidence: "high",
          },
        ],
        overlap_signals: [],
        harvest_followups: [],
        uncertainties: [],
        overlap_signals_omitted: 0,
        harvest_followups_omitted: 0,
        uncertainties_omitted: 0,
      },
    },
  ];
}

/** One complete reducer wave (empty stances — the keep-only corpus has no proposals). */
export function dreamReducers(): DreamReducerAnalysis[] {
  return DREAM_REDUCER_ANGLES.map((angle) => ({
    angle,
    report: {
      stances: [],
      angle_findings: [],
      uncertainties: [],
      stances_omitted: 0,
      angle_findings_omitted: 0,
      uncertainties_omitted: 0,
    },
  }));
}

/** A valid §8.62 model input over the fixture (the keep row; no units needed). */
export function dreamReportInput(): Record<string, unknown> {
  return {
    rows: [
      {
        path: DREAM_FIXTURE_DOC,
        disposition: "keep",
        merge_target: null,
        rationale: "the parent's reason",
        fallback_reason: null,
      },
    ],
    uncertainties: [],
    selected_units: [],
    overflow_units: [],
    harvest_followups: [],
    predicted_effects: { docs_after: 1, bytes_after: 100, note: null },
  };
}

/** Run one git command in the fixture cwd (test-only; throws loudly on failure). */
function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] })
    .toString()
    .trim();
}

/**
 * Commit everything currently in the fixture repo (`git add -A` + an allow-empty commit) and
 * return the new HEAD sha — the one-liner the drift cases use to move HEAD off the stamped
 * snapshot after planting.
 */
export function dreamRepoCommit(cwd: string, message: string): string {
  git(cwd, "add", "-A");
  git(cwd, "commit", "-q", "--allow-empty", "-m", message);
  return git(cwd, "rev-parse", "HEAD");
}

/**
 * Turn the fixture cwd into a REAL clean git repo: `git init` + a committed `.gitignore`
 * covering the run scratch (`/.perk/workflow/` — so planted scratch never dirties the tree)
 * and the harness's session/fake-bin conveniences, then ONE commit of everything present.
 * Returns the HEAD sha (what the planted manifest stamps as `commit_sha`).
 */
export function initDreamRepo(cwd: string): string {
  git(cwd, "init", "-q");
  git(cwd, "config", "user.email", "t@example.com");
  git(cwd, "config", "user.name", "perk tests");
  writeFileSync(join(cwd, ".gitignore"), "/.perk/workflow/\n*.jsonl\nfake-perk.sh\nargv.txt\n");
  return dreamRepoCommit(cwd, "dream fixture snapshot");
}

/**
 * Plant the run-scoped dream files over a real clean git repo whose HEAD is the stamped
 * `commit_sha` (so the production revalidation bracket passes as planted and drifts when the
 * repo moves): the manifest, and (unless `finalized: false`) the FINALIZED bundle binding the
 * manifest bytes' digest. Returns the `dream_bundle_digest` marker value for the planted state
 * (`""` when not finalized — the caller decides where the marker entry lives: a fake branch
 * array or a planted session). Throws on a broken fixture (test-only code).
 */
export function plantDreamFiles(
  cwd: string,
  runId: string,
  opts: { finalized?: boolean } = {},
): string {
  const sha = initDreamRepo(cwd);
  const scratch = runScratchDir(cwd, runId);
  mkdirSync(scratch, { recursive: true });
  const manifestPath = join(scratch, DREAM_MANIFEST_FILENAME);
  const manifestBytes = dreamManifestBytes(sha);
  writeFileSync(manifestPath, manifestBytes);
  if (opts.finalized === false) return "";
  const decoded = decodeDreamManifest(dreamRawManifest(sha), manifestPath);
  if (!decoded.ok) {
    throw new Error(`dream fixture manifest failed to decode: ${decoded.detail}`);
  }
  const bundle = finalizeDreamBundle(
    (decoded as { ok: true; manifest: DreamManifest }).manifest,
    dreamAnalyses(),
    dreamReducers(),
    digestSessionData(manifestBytes),
  );
  writeFileSync(join(scratch, DREAM_ANALYSES_FILENAME), bundle);
  return digestSessionData(bundle);
}
