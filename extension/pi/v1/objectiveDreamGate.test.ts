// The §8.63 gate's BOUNDARY suite: `productionDreamGateRecovery` through the real resolver,
// over REAL run-scratch fixtures (the `testing/dreamFixtures.ts` recipes — `plantDreamFiles`
// plants the manifest + finalized bundle over a REAL clean git repo whose HEAD is the stamped
// `commit_sha`, so the PRODUCTION revalidation bracket runs end-to-end). Every arm of the
// digest-pointer recovery ladder, the two fail-closed readSession hardenings (the unsafe
// claimed run_id; the mistyped `dream_bundle_digest`), the throwing-branch arm, repository
// drift through the real bracket (moved HEAD + dirty tree), the every-call re-verification pin
// (no cached proof object), and the composed unreadable-prefix rendering. Fully offline
// (local git only).

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  type DreamReportGateOutcome,
  resolveDreamReportGate,
} from "../../authoring/objective/dreamReportGate.ts";
import { DREAM_MANIFEST_FILENAME, decodeDreamManifest } from "../../learning/dream.ts";
import { composeDreamBundle, DREAM_ANALYSES_FILENAME } from "../../learning/dreamReducer.ts";
import { runScratchDir } from "../../substrate/cache.ts";
import { digestSessionData } from "../../substrate/sessionData.ts";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import {
  dreamAnalyses,
  dreamRawManifest,
  dreamRepoCommit,
  dreamReportInput,
  plantDreamFiles,
} from "../../testing/dreamFixtures.ts";
import { productionDreamGateRecovery } from "./objectiveDreamGate.ts";

const RUN_ID = "01DREAMGATEBOUNDARY";
const STAMP = "2026-02-03T04:05:06Z";

/** A minimal structural ctx over a live branch array (ExtensionContext satisfies the slice). */
function ctxOf(cwd: string, branch: unknown[]): ExtensionContext {
  return { cwd, sessionManager: { getBranch: () => branch } } as unknown as ExtensionContext;
}

function stateEntry(data: Record<string, unknown>): unknown {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

/** Plant the full git-backed dream fixture and return the ctx over a marker-carrying branch. */
function plantGate(opts: { marker?: string | number | false } = {}): {
  cwd: string;
  ctx: ExtensionContext;
  digest: string;
} {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
  const digest = plantDreamFiles(cwd, RUN_ID);
  const branch: unknown[] = [stateEntry({ run_id: RUN_ID })];
  if (opts.marker !== false) {
    branch.push(stateEntry({ dream_bundle_digest: opts.marker ?? digest }));
  }
  return { cwd, ctx: ctxOf(cwd, branch), digest };
}

function resolve(ctx: ExtensionContext, input?: unknown): DreamReportGateOutcome {
  return resolveDreamReportGate(
    productionDreamGateRecovery(ctx),
    input === undefined ? dreamReportInput() : input,
    STAMP,
  );
}

function refusal(outcome: DreamReportGateOutcome): { errorType: string; detail: string } {
  assert.equal(outcome.kind, "refuse", JSON.stringify(outcome));
  const refused = outcome as { kind: "refuse"; errorType: string; detail: string };
  return { errorType: refused.errorType, detail: refused.detail };
}

function bundlePath(cwd: string): string {
  return join(runScratchDir(cwd, RUN_ID), DREAM_ANALYSES_FILENAME);
}

function manifestPath(cwd: string): string {
  return join(runScratchDir(cwd, RUN_ID), DREAM_MANIFEST_FILENAME);
}

/** The planted repo's HEAD sha (what the planted manifest stamps as `commit_sha`). */
function dreamRepoCommitSha(cwd: string): string {
  const raw = JSON.parse(readFileSync(manifestPath(cwd), "utf8")) as { commit_sha: string };
  return raw.commit_sha;
}

/** Plant the fixture and return the stamped sha (the finalized bundle is planted too). */
function plantSha(cwd: string): string {
  plantDreamFiles(cwd, RUN_ID);
  return dreamRepoCommitSha(cwd);
}

// --- the happy path over the real capability + real bracket -----------------------------------

test("boundary: dream + valid input recovers, passes the REAL bracket, and blocks", () => {
  const { cwd, ctx } = plantGate();
  try {
    const outcome = resolve(ctx);
    assert.equal(outcome.kind, "block", JSON.stringify(outcome));
    const block = (outcome as { kind: "block"; block: { parts: string[] } }).block;
    assert.ok(block.parts[0]?.startsWith(`# Dream report — ${RUN_ID}`));
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("boundary: non-dream arms — no claimed run, and a claimed run without a manifest", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
  try {
    assert.deepEqual(
      resolveDreamReportGate(productionDreamGateRecovery(ctxOf(cwd, [])), undefined, STAMP),
      {
        kind: "absent",
      },
    );
    const outcome = resolveDreamReportGate(
      productionDreamGateRecovery(ctxOf(cwd, [stateEntry({ run_id: RUN_ID })])),
      dreamReportInput(),
      STAMP,
    );
    const { errorType, detail } = refusal(outcome);
    assert.equal(errorType, "invalid_input");
    assert.match(detail, /only valid inside a perk learn dream session/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- readSession: the throwing-branch arm + the two fail-closed hardenings --------------------

test("boundary: a throwing getBranch → unreadable with the RAW caught message, fully rendered", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
  try {
    const throwing = {
      cwd,
      sessionManager: {
        getBranch: () => {
          throw new Error("branch storage exploded");
        },
      },
    } as unknown as ExtensionContext;
    for (const input of [undefined, dreamReportInput()]) {
      const outcome = resolveDreamReportGate(productionDreamGateRecovery(throwing), input, STAMP);
      const { errorType, detail } = refusal(outcome);
      assert.equal(errorType, "bad_state");
      // The composed rendering pin: the capability's RAW cause through the resolver's ONE
      // rendering prefix — the exact bytes the old in-feature throw arm produced.
      assert.equal(
        detail,
        "session workflow state is unreadable — cannot resolve the dream_report gate: " +
          "branch storage exploded",
      );
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("boundary: an unsafe claimed run_id refuses bad_state BEFORE any path derivation", () => {
  const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
  try {
    const ctx = ctxOf(cwd, [stateEntry({ run_id: "../evil" })]);
    for (const input of [undefined, dreamReportInput()]) {
      const { errorType, detail } = refusal(
        resolveDreamReportGate(productionDreamGateRecovery(ctx), input, STAMP),
      );
      assert.equal(errorType, "bad_state");
      assert.equal(
        detail,
        "session workflow state is unreadable — cannot resolve the dream_report gate: " +
          "claimed run_id is not a safe path component",
      );
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("boundary: a mistyped dream_bundle_digest refuses bad_state (corrupted state, never non-dream)", () => {
  const { cwd, ctx } = plantGate({ marker: 42 });
  try {
    const { errorType, detail } = refusal(resolve(ctx));
    assert.equal(errorType, "bad_state");
    assert.equal(
      detail,
      "session workflow state is unreadable — cannot resolve the dream_report gate: " +
        "workflow-state dream_bundle_digest is not a string",
    );
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the recovery failure ladder (every arm bad_state, named) ---------------------------------

test("boundary: recovery failure arms are bad_state with named details", () => {
  const arms: {
    label: string;
    plant: () => { cwd: string; ctx: ExtensionContext };
    detail: RegExp;
  }[] = [
    {
      label: "unreadable manifest",
      plant: () => {
        const planted = plantGate();
        writeFileSync(manifestPath(planted.cwd), "{not json");
        return planted;
      },
      detail: /dream manifest unreadable/,
    },
    {
      label: "bundle absent",
      plant: () => {
        const planted = plantGate();
        rmSync(bundlePath(planted.cwd));
        return planted;
      },
      detail: /no dream bundle at .* — re-run the dream wave/,
    },
    {
      label: "marker missing",
      plant: () => plantGate({ marker: false }),
      detail: /no finalized dream wave for this session — re-run the dream wave/,
    },
    {
      // The cleanup-failure→draft path: files intact, marker cleared → refuse.
      label: "marker empty (invalidated)",
      plant: () => plantGate({ marker: "" }),
      detail: /no finalized dream wave for this session — re-run the dream wave/,
    },
    {
      label: "digest mismatch (stale/tampered bundle bytes)",
      plant: () => {
        const planted = plantGate();
        // Rewrite the on-disk bundle; the marker still names the original finalized digest.
        writeFileSync(bundlePath(planted.cwd), `${JSON.stringify({ tampered: true }, null, 2)}\n`);
        return planted;
      },
      detail: /does not match the session's finalized digest — re-run the dream wave/,
    },
    {
      // The at-rest manifest tamper the bound manifest_digest catches: the echoed identity
      // fields survive the edit, so only the digest binding refuses — the marker still matches
      // the untouched bundle bytes.
      label: "manifest tampered at rest (identity fields preserved)",
      plant: () => {
        const planted = plantGate();
        const sha = dreamRepoCommitSha(planted.cwd);
        const tampered = dreamRawManifest(sha);
        (tampered.findings as { advisory: { empty_clusters: unknown[] } }).advisory.empty_clusters =
          ["prose-governance"];
        writeFileSync(manifestPath(planted.cwd), `${JSON.stringify(tampered, null, 2)}\n`);
        return planted;
      },
      detail:
        /manifest_digest .* does not match the digest of the manifest just read — the manifest changed after the wave finalized/,
    },
    {
      label: "malformed bundle JSON (digest-matching)",
      plant: () => {
        const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
        plantDreamFiles(cwd, RUN_ID);
        writeFileSync(bundlePath(cwd), "{not json");
        const branch: unknown[] = [
          stateEntry({ run_id: RUN_ID }),
          stateEntry({ dream_bundle_digest: digestSessionData("{not json") }),
        ];
        return { cwd, ctx: ctxOf(cwd, branch) };
      },
      detail: /dream bundle is not valid JSON/,
    },
    {
      // A cleanly-digested analyses-only bundle (mid-wave shape): freshness passes, the
      // finalized decode refuses.
      label: "analyses-only bundle",
      plant: () => {
        const cwd = mkdtempSync(join(tmpdir(), "objective-dream-gate-test-"));
        const sha = plantSha(cwd);
        const decoded = decodeDreamManifest(dreamRawManifest(sha), manifestPath(cwd));
        assert.equal(decoded.ok, true, JSON.stringify(decoded));
        const analysesOnly = composeDreamBundle(
          (decoded as { ok: true; manifest: Parameters<typeof composeDreamBundle>[0] }).manifest,
          dreamAnalyses(),
        ).content;
        writeFileSync(bundlePath(cwd), analysesOnly);
        const branch: unknown[] = [
          stateEntry({ run_id: RUN_ID }),
          stateEntry({ dream_bundle_digest: digestSessionData(analysesOnly) }),
        ];
        return { cwd, ctx: ctxOf(cwd, branch) };
      },
      detail: /no reducers section — the dream wave did not finalize .*— re-run the dream wave/,
    },
  ];
  for (const arm of arms) {
    const planted = arm.plant();
    try {
      const { errorType, detail } = refusal(resolve(planted.ctx));
      assert.equal(errorType, "bad_state", arm.label);
      assert.match(detail, arm.detail, arm.label);
    } finally {
      rmSync(planted.cwd, { recursive: true, force: true });
    }
  }
});

// --- repository drift through the REAL revalidation bracket (contracts §8.65) ------------------

test("boundary: HEAD moved off the stamped snapshot refuses bad_state through the real bracket", () => {
  const { cwd, ctx } = plantGate();
  try {
    dreamRepoCommit(cwd, "drift: the repo moved after the wave");
    const { errorType, detail } = refusal(resolve(ctx));
    assert.equal(errorType, "bad_state");
    assert.match(detail, /repository moved since the dream snapshot/);
    assert.match(detail, /HEAD moved from/);
    assert.match(detail, /the analysis is stale; re-run perk learn dream/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("boundary: a dirty working tree refuses bad_state through the real bracket", () => {
  const { cwd, ctx } = plantGate();
  try {
    writeFileSync(join(cwd, "dirty.txt"), "uncommitted\n");
    const { errorType, detail } = refusal(resolve(ctx));
    assert.equal(errorType, "bad_state");
    assert.match(detail, /repository moved since the dream snapshot/);
    assert.match(detail, /the working tree is no longer clean/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- the every-call re-verification pin (the anti-proof-object contract) -----------------------

test("boundary: every consuming call re-verifies — tampering between two calls refuses the second", () => {
  const { cwd, ctx } = plantGate();
  try {
    // ONE capability instance, TWO resolutions: nothing may be cached across calls.
    const recovery = productionDreamGateRecovery(ctx);
    const first = resolveDreamReportGate(recovery, dreamReportInput(), STAMP);
    assert.equal(first.kind, "block", JSON.stringify(first));
    // Tamper the on-disk bundle between the calls; the marker still names the original digest.
    writeFileSync(bundlePath(cwd), `${JSON.stringify({ tampered: true }, null, 2)}\n`);
    const second = resolveDreamReportGate(recovery, dreamReportInput(), STAMP);
    const { errorType, detail } = refusal(second);
    assert.equal(errorType, "bad_state");
    assert.match(detail, /does not match the session's finalized digest — re-run the dream wave/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});
