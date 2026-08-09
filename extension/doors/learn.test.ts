// Live warm-door tests for `/learn`. No gh — the cold doors are faked via `fakePerk`. The
// no-summary arm delegates to `perk learn skip` (the canonical §8.36 skip recording) and mirrors
// the marker-clear. Driven through a REAL bound AgentSession via the T1 harness.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { markerPath, PENDING_LEARN, setMarker, writePlanRef } from "../substrate/cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { createMemoryWaveAdapter } from "../waves/memoryAdapter.ts";
import { WAVE_RPC_REPLY_EVENT_PREFIX, WAVE_RPC_REQUEST_EVENT } from "../waves/rpcAdapter.ts";
import { executeLearnWave, learnGuidance, learnOrchestrateGuidance } from "./learn.ts";

const PLAN_REF = {
  provider: "github",
  pr_id: "42",
  url: "https://gh/o/r/issues/42",
  labels: ["perk:plan"],
  objective_id: null,
};

const SKIP_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  plan_issue: "42",
  learn_state: "skipped",
  pending_cleared: true,
  dry_run: false,
});

const CAPTURE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  learn_issue: { id: "99", url: "https://gh/o/r/issues/99", existed: false },
  plan_issue: 7,
  commented: true,
  pending_cleared: true,
  dry_run: false,
});

test("tool: learn (no summary) delegates the skip and clears pending-learn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN); // land left it set
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: SKIP_OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", {});
    assert.equal(result.terminate, true);
    const details = result.details as { ok: boolean; was_pending: boolean };
    assert.equal(details.ok, true);
    assert.equal(details.was_pending, true);
    assert.match(result.content[0]?.text ?? "", /Skip recorded on the plan/);
    assert.match(readFileSync(argvFile, "utf8"), /learn\nskip\n--json/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn cleared");
  } finally {
    h.dispose();
  }
});

test("tool: learn (no summary) reports the kept state on an already-captured plan", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const captured = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    plan_issue: "42",
    learn_state: "captured",
    pending_cleared: true,
    dry_run: false,
  });
  const bin = fakePerk(cwd, { stdout: captured });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", {});
    assert.equal(result.terminate, true);
    assert.match(result.content[0]?.text ?? "", /already captured/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)));
  } finally {
    h.dispose();
  }
});

test("tool: learn (no summary) with a failing skip door fails soft and KEEPS the marker", async () => {
  // Never silently clear on uncertainty — the marker is the retry signal.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true);
    assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "marker kept on a failed skip");
  } finally {
    h.dispose();
  }
});

test("/learn skip: delegates the canonical skip and clears the marker", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: SKIP_OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.runCommandHandler("learn", "skip");
    assert.match(readFileSync(argvFile, "utf8"), /learn\nskip\n--json/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "/learn skip cleared pending-learn");
  } finally {
    h.dispose();
  }
});

test("/learn (bare, headless): the safe no-summary path (same cold skip delegation)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: SKIP_OK_JSON });
  const h = await loadPerkSession({
    cwd,
    headful: false,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
  });
  try {
    await h.runCommandHandler("learn", "");
    assert.ok(
      !existsSync(markerPath(cwd, PENDING_LEARN)),
      "headless bare /learn recorded the skip + cleared pending-learn (can't drive a turn)",
    );
  } finally {
    h.dispose();
  }
});

test("/learn (bare, interactive, no worker): degrades to the simple pass and keeps the marker", async () => {
  // With no PERK_BIN/handoff the evidence cold door is unavailable, so bare /learn degrades to the
  // simple learn pass (never a dead end). The agent clears the marker via the `learn` tool, so the
  // command must NOT clear it here.
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  writePlanRef(cwd, PLAN_REF);
  const h = await loadPerkSession({ cwd });
  try {
    await h.runCommandHandler("learn", "");
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "bare /learn left pending-learn for the capture pass",
    );
    assert.ok(
      h.notifies.some((n) => n.includes("falling back to the simple learn pass")),
      "notified the graceful fallback",
    );
  } finally {
    h.dispose();
  }
});

test("learnGuidance derives the head branch from the plan-ref (skill pointer is suffix-delivered)", () => {
  const withRef = learnGuidance(PLAN_REF);
  // The perk-learn skill pointer is no longer hardcoded — it rides the binding suffix.
  assert.doesNotMatch(withRef, /Follow the perk-learn skill/);
  assert.match(withRef, /plan-42/);
  assert.match(withRef, /gh pr list --head plan-42/);
  assert.match(withRef, /`learn` tool/);
  assert.match(withRef, /\/learn skip/);
  // Without a plan-ref it still names the tool (no branch derivation).
  const noRef = learnGuidance(null);
  assert.doesNotMatch(noRef, /Follow the perk-learn skill/);
  assert.match(noRef, /`learn` tool/);
});

test("learnGuidance: a linear plan-ref reads via the linear tools but keeps the gh PR derivation", () => {
  // PRs are GitHub-universal under every issue backend.
  const linear = learnGuidance({ ...PLAN_REF, provider: "linear" });
  assert.match(linear, /linear_get_issue/);
  assert.match(linear, /linear_list_comments/);
  assert.match(linear, /gh pr list --head plan-42/);
  assert.doesNotMatch(linear, /gh issue view/);
  // The github arm is unchanged.
  assert.match(learnGuidance(PLAN_REF), /gh issue view 42 --comments/);
  // An unknown provider collapses to a single "Open the plan and its merged change" line
  // (no merged-PR derivation) — the unified `other` arm matches cold `_learn_prompt`.
  const other = learnGuidance({ ...PLAN_REF, provider: "gitlab" });
  assert.match(other, /Open the plan and its merged change: https:\/\/gh\/o\/r\/issues\/42/);
  assert.doesNotMatch(other, /gh pr list --head plan-42/);
});

test("tool: learn with a summary delegates capture, surfaces the issue, and clears", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: CAPTURE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "## Learnings\n\nWe deviated on X." });
    assert.equal(result.terminate, true);
    const details = result.details as {
      ok: boolean;
      captured?: boolean;
      learn_issue?: { id?: string };
    };
    assert.equal(details.ok, true);
    assert.equal(details.captured, true);
    assert.equal(details.learn_issue?.id, "99");
    assert.match(result.content[0]?.text ?? "", /#99/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "pending-learn cleared after capture");
  } finally {
    h.dispose();
  }
});

test("tool: malformed learn_issue + success envelope → captured-ok, marker cleared (lenient decode)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const malformed = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    learn_issue: { id: 99, url: "https://gh/o/r/issues/99" }, // id a number → undecodable (string ids, §8.21)
  });
  const bin = fakePerk(cwd, { stdout: malformed });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "something durable" });
    assert.equal(result.terminate, true);
    const details = result.details as { ok: boolean; captured?: boolean; learn_issue?: unknown };
    assert.equal(details.ok, true);
    assert.equal(details.captured, true);
    assert.equal(details.learn_issue, undefined);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Captured learnings/);
    assert.match(text, /version-skewed/);
    assert.ok(
      !existsSync(markerPath(cwd, PENDING_LEARN)),
      "a success envelope clears the marker even when learn_issue is undecodable",
    );
  } finally {
    h.dispose();
  }
});

test("tool: legacy learn_issue shape (number, no id) → captured-ok (the skew regression)", async () => {
  // The exact cold/warm version-skew payload pair that produced the false 'learn failed':
  // a success envelope whose learn_issue carries the legacy `number` field instead of `id`.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const legacy = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    learn_issue: { number: 99, url: "https://gh/o/r/issues/99", existed: false },
  });
  const bin = fakePerk(cwd, { stdout: legacy });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "something durable" });
    assert.equal(result.terminate, true);
    const details = result.details as { ok: boolean; captured?: boolean; learn_issue?: unknown };
    assert.equal(details.ok, true);
    assert.equal(details.captured, true);
    assert.equal(details.learn_issue, undefined);
    assert.match(result.content[0]?.text ?? "", /version-skewed/);
    assert.ok(!existsSync(markerPath(cwd, PENDING_LEARN)), "marker cleared on the skew payload");
  } finally {
    h.dispose();
  }
});

test("tool: learn with a summary but a failing worker fails soft (no terminate, marker kept)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", { summary: "something" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.notEqual(result.terminate, true);
    // A failed capture leaves the marker so the cycle is not silently closed.
    assert.ok(existsSync(markerPath(cwd, PENDING_LEARN)), "marker kept on capture failure");
  } finally {
    h.dispose();
  }
});

// --- tool-boundary decode (strict-fail on mistyped params) -----------------------

test("tool: learn with a mistyped summary → bad_input AND the marker is NOT cleared", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", { summary: 5 });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "pending-learn NOT cleared on uncertainty",
    );
  } finally {
    h.dispose();
  }
});

test("tool: a valid decision/target reach learnDone (capture argv carries --decision/--target)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CAPTURE_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("learn", {
      summary: "durable learning",
      decision: "UPDATE_EXISTING_DOC",
      target: "docs/learned/x.md",
    });
    assert.equal(result.terminate, true);
    const argv = readFileSync(argvFile, "utf8");
    assert.match(argv, /learn\ncapture\n--json/);
    assert.match(argv, /--decision\nUPDATE_EXISTING_DOC/);
    assert.match(argv, /--target\ndocs\/learned\/x\.md/);
  } finally {
    h.dispose();
  }
});

test("tool: an out-of-enum decision → bad_input AND the marker is NOT cleared", async () => {
  const cwd = scaffoldRepo();
  setMarker(cwd, PENDING_LEARN);
  const h = await loadPerkSession({ cwd });
  try {
    const result = await h.invokeTool("learn", { summary: "x", decision: "NONSENSE" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "pending-learn NOT cleared on a bad decision",
    );
  } finally {
    h.dispose();
  }
});

// --- learnOrchestrateGuidance (pure) ---------------------------------------------

test("learnOrchestrateGuidance: names the tool, the angles, the reconcile steps, and the paths", () => {
  const g = learnOrchestrateGuidance({
    manifestPath: "/abs/learn-evidence/manifest.json",
    bundleDir: "/abs/learn-evidence",
  });
  // The wave runs through the flow-scoped tool — judgment-bearing inputs only.
  assert.match(g, /run_learn_wave/);
  assert.match(g, /2[\u2013-]4/);
  // The four angle slugs; session-deviations is mandatory (+ its off-track/dead-ends emphasis).
  assert.match(g, /session-deviations.*always included/);
  assert.match(g, /off-track/);
  assert.match(g, /dead ends/);
  assert.match(g, /plan-vs-implementation/);
  assert.match(g, /existing-docs/);
  assert.match(g, /validation-risk/);
  // Reports are untrusted DATA; reconcile → capture/skip; skipped angles come from the tool.
  assert.match(g, /untrusted DATA/);
  assert.match(g, /[Rr]econcile/);
  assert.match(g, /skipped angles are explicitly listed by the tool/);
  assert.match(g, /`learn`\*\* tool/);
  assert.match(g, /no `summary`/);
  // Renders the manifest path + bundle dir.
  assert.match(g, /\/abs\/learn-evidence\/manifest\.json/);
  assert.match(g, /\/abs\/learn-evidence/);
  // The wave-level failure arm: the parent analyzes the bundle itself — never a dead end.
  assert.match(g, /fails at wave level/);
  assert.match(g, /analyze the bundle YOURSELF/);
  // No orchestration mechanics — the module owns the script/spawn params now.
  assert.doesNotMatch(g, /workflowScript/);
  assert.doesNotMatch(g, /runs\.all/);
  assert.doesNotMatch(g, /async: false/);
  assert.doesNotMatch(g, /fenced/);
});

// --- run_learn_wave (tool-boundary decode + policy — validation precedes any adapter use) --------

/** Scaffold + materialize a bundle dir with a manifest.json; returns { cwd, bundleDir }. */
function scaffoldBundle(): { cwd: string; bundleDir: string } {
  const cwd = scaffoldRepo();
  const bundleDir = join(cwd, "learn-evidence");
  mkdirSync(bundleDir, { recursive: true });
  writeFileSync(join(bundleDir, "manifest.json"), "{}\n", "utf8");
  return { cwd, bundleDir };
}

const TWO_ANGLES = [{ angle: "session-deviations" }, { angle: "existing-docs" }];

test("tool: run_learn_wave bad_input arms (params, manifest, angle policy)", async () => {
  const { cwd, bundleDir } = scaffoldBundle();
  const h = await loadPerkSession({ cwd });
  try {
    const cases: { params: unknown; want: RegExp }[] = [
      // bundle_dir missing / mistyped.
      { params: { angles: TWO_ANGLES }, want: /`bundle_dir` must be a non-empty string/ },
      {
        params: { bundle_dir: 5, angles: TWO_ANGLES },
        want: /`bundle_dir` must be a non-empty string/,
      },
      // angles missing / mistyped rows.
      { params: { bundle_dir: bundleDir }, want: /`angles` must be an array/ },
      {
        params: { bundle_dir: bundleDir, angles: ["session-deviations"] },
        want: /`angles` items must be/,
      },
      {
        params: {
          bundle_dir: bundleDir,
          angles: [{ angle: "session-deviations", emphasis: 5 }, { angle: "existing-docs" }],
        },
        want: /`angles` items must be/,
      },
      // The angle policy, enforced in code.
      {
        params: { bundle_dir: bundleDir, angles: [{ angle: "session-deviations" }] },
        want: /2–4 angles \(got 1\)/,
      },
      {
        params: {
          bundle_dir: bundleDir,
          angles: [
            { angle: "session-deviations" },
            { angle: "plan-vs-implementation" },
            { angle: "existing-docs" },
            { angle: "validation-risk" },
            { angle: "session-deviations" },
          ],
        },
        want: /2–4 angles \(got 5\)/,
      },
      {
        params: {
          bundle_dir: bundleDir,
          angles: [{ angle: "session-deviations" }, { angle: "session-deviations" }],
        },
        want: /duplicate angle/,
      },
      {
        params: {
          bundle_dir: bundleDir,
          angles: [{ angle: "session-deviations" }, { angle: "vibes" }],
        },
        want: /unknown angle 'vibes'/,
      },
      {
        params: {
          bundle_dir: bundleDir,
          angles: [{ angle: "plan-vs-implementation" }, { angle: "existing-docs" }],
        },
        want: /'session-deviations' angle is mandatory/,
      },
      // A bundle dir without a manifest (the gather-first rule).
      {
        params: { bundle_dir: join(cwd, "nowhere"), angles: TWO_ANGLES },
        want: /gather the bundle via bare \/learn first/,
      },
    ];
    for (const { params, want } of cases) {
      const result = await h.invokeTool("run_learn_wave", params);
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false, `expected failure for ${JSON.stringify(params)}`);
      assert.equal(details.error_type, "bad_input");
      assert.match(result.content[0]?.text ?? "", want);
    }
  } finally {
    h.dispose();
  }
});

/**
 * A fake pi-subagents RPC responder (the fakePlannotator pattern): answers ping with the
 * advertised capabilities, answers spawn by materializing a durable status.json aggregate in a
 * temp asyncDir, then emits the async-complete event. Captured spawn params land in `spawns`.
 */
function fakeSubagentsRpc(
  aggregate: unknown[],
  spawns: Record<string, unknown>[] = [],
): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.events.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const req = raw as { requestId?: unknown; method?: unknown };
      const reply = (payload: Record<string, unknown>): void => {
        pi.events.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${String(req.requestId)}`, {
          version: 1,
          requestId: req.requestId,
          method: req.method,
          ...payload,
        });
      };
      if (req.method === "ping") {
        reply({
          success: true,
          data: {
            capabilities: { asyncSpawn: true },
            methods: ["ping", "spawn", "stop"],
            events: { asyncComplete: "subagent:async-complete" },
          },
        });
        return;
      }
      if (req.method === "spawn") {
        const params = (raw as { params?: unknown }).params;
        spawns.push(params as Record<string, unknown>);
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-learn-wave-"));
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({ state: "complete", workflow: { value: aggregate } }),
        );
        reply({ success: true, data: { text: "ok", details: { asyncId: "wave-1", asyncDir } } });
        pi.events.emit("subagent:async-complete", { id: "wave-1", asyncDir });
      }
    });
  };
}

test("tool: run_learn_wave end-to-end over the RPC seam — typed reports + explicit skipped angles", async () => {
  const { cwd, bundleDir } = scaffoldBundle();
  const report = {
    angle: "session-deviations",
    verdict: "actionable",
    candidates: [
      {
        decision: "CAPTURE_LEARN",
        summary: "a durable trap",
        target: null,
        evidence: "implementation-main chunk",
      },
    ],
    fyi: [],
  };
  const aggregate = [
    { key: "session-deviations", ok: true, error: null, report },
    { key: "existing-docs", ok: false, error: "analyst crashed", report: null },
  ];
  const h = await loadPerkSession({ cwd, extraExtensions: [fakeSubagentsRpc(aggregate)] });
  try {
    const result = await h.invokeTool("run_learn_wave", {
      bundle_dir: bundleDir,
      angles: TWO_ANGLES,
    });
    const details = result.details as {
      ok: boolean;
      reports?: { angle: string; report: unknown }[];
      skipped?: { angle: string; reason: string; detail: string }[];
      attempts?: {
        flow: string;
        attempt: number;
        requestedKeys: string[];
        runId?: string;
        state: string;
        children: unknown[];
      }[];
    };
    assert.equal(details.ok, true);
    assert.notEqual(result.terminate, true, "non-terminating: the parent continues to reconcile");
    assert.deepEqual(details.reports, [{ angle: "session-deviations", report }]);
    assert.deepEqual(details.skipped, [
      { angle: "existing-docs", reason: "lane-failed", detail: "analyst crashed" },
    ]);
    // The single attempt receipt rides the structured details (identity-only completion ⇒
    // empty children); receipts never enter the prose.
    assert.equal(details.attempts?.length, 1);
    const attempt = details.attempts?.[0];
    assert.equal(attempt?.flow, "learn");
    assert.equal(attempt?.attempt, 1);
    assert.deepEqual(attempt?.requestedKeys, ["session-deviations", "existing-docs"]);
    assert.equal(attempt?.runId, "wave-1");
    assert.equal(attempt?.state, "complete");
    assert.deepEqual(attempt?.children, []);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /untrusted DATA/);
    assert.match(text, /```json/);
    assert.match(text, /a durable trap/);
    assert.match(text, /Skipped angles:/);
    assert.match(text, /existing-docs \(lane-failed\): analyst crashed/);
    assert.equal(text.includes("attempts"), false, "receipts never enter the prose");
  } finally {
    h.dispose();
  }
});

test("tool: run_learn_wave resolves [models.subagents] learn-analyst onto the wave spawn", async () => {
  const { cwd, bundleDir } = scaffoldBundle();
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nlearn-analyst = "faux/analyst-model"\n',
    "utf8",
  );
  const aggregate = [
    { key: "session-deviations", ok: false, error: "x", report: null },
    { key: "existing-docs", ok: false, error: "x", report: null },
  ];
  const spawns: Record<string, unknown>[] = [];
  const h = await loadPerkSession({ cwd, extraExtensions: [fakeSubagentsRpc(aggregate, spawns)] });
  try {
    const result = await h.invokeTool("run_learn_wave", {
      bundle_dir: bundleDir,
      angles: TWO_ANGLES,
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.equal(spawns.length, 1);
    assert.equal(
      spawns[0]?.model,
      "faux/analyst-model",
      "the configured analyst model must ride the spawn as the workflow-level default",
    );
  } finally {
    h.dispose();
  }
});

test("tool: run_learn_wave with no RPC responder soft-fails loudly as unavailable", async () => {
  // No fakeSubagentsRpc bound → the capability ping goes unanswered → the wave-level
  // `unavailable` arm: a loud soft-fail (error_type = the WaveFailureReason), never a throw and
  // never a silent fallback — the guidance routes the parent to analyze the bundle itself.
  const { cwd, bundleDir } = scaffoldBundle();
  const h = await loadPerkSession({ cwd, env: { PERK_WAVE_RPC_PING_MS: "20" } });
  try {
    const result = await h.invokeTool("run_learn_wave", {
      bundle_dir: bundleDir,
      angles: TWO_ANGLES,
    });
    const details = result.details as { ok: boolean; error_type?: string; error?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "unavailable");
    assert.notEqual(result.terminate, true);
    assert.match(result.content[0]?.text ?? "", /run_learn_wave failed:/);
    assert.match(result.content[0]?.text ?? "", /report-wave capabilities/);
  } finally {
    h.dispose();
  }
});

test("executeLearnWave: each wave-level failure maps to a soft-fail with its reason + detail", async () => {
  // The extracted execute core, driven directly through the memory adapter (no session needed).
  const notified: string[] = [];
  const target = { hasUI: true, ui: { notify: (m: string) => notified.push(m) } };
  const opts = {
    bundleDir: "/abs/learn-evidence",
    selections: [{ angle: "session-deviations" }, { angle: "existing-docs" }],
  };

  const unavailable = await executeLearnWave(createMemoryWaveAdapter({ ping: null }), target, opts);
  assert.equal(unavailable.details.ok, false);
  const u = unavailable.details as { error_type?: string; attempts?: unknown };
  assert.equal(u.error_type, "unavailable");
  // The fail details retain the attempt receipt known before the failure.
  assert.deepEqual(u.attempts, [
    {
      flow: "learn",
      attempt: 1,
      requestedKeys: ["session-deviations", "existing-docs"],
      state: "unavailable",
      children: [],
    },
  ]);

  const spawnFailed = await executeLearnWave(
    createMemoryWaveAdapter({ spawnError: "no session" }),
    target,
    opts,
  );
  assert.equal(spawnFailed.details.ok, false);
  const s = spawnFailed.details as { error_type?: string; error?: string; attempts?: unknown[] };
  assert.equal(s.error_type, "spawn-failed");
  assert.match(s.error ?? "", /no session/);
  assert.equal((s.attempts?.[0] as { state?: string } | undefined)?.state, "spawn-failed");
  assert.match(spawnFailed.content[0]?.text ?? "", /run_learn_wave failed: .*no session/);
  assert.ok(
    notified.some((m) => m.includes("run_learn_wave")),
    "the failure is reported loudly through the report seam",
  );
});

// --- bare interactive /learn orchestration branches ------------------------------

const SKIP_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  skipped: true,
  skip_reason: "learn-docs plan",
  plan_id: "7",
  bundle_dir: null,
  sources: [],
  existing_docs: [],
  render: null,
});

const GATHERED_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  skipped: false,
  skip_reason: null,
  plan_id: "7",
  bundle_dir: ".perk/workflow/scratch/learn-evidence",
  sources: [],
  existing_docs: [],
  render: null,
});

test("/learn (bare, learn-docs plan): clears the marker, no orchestration", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: SKIP_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.runCommandHandler("learn", "");
    assert.ok(
      !existsSync(markerPath(cwd, PENDING_LEARN)),
      "learn-docs short-circuit clears pending-learn",
    );
    assert.ok(
      h.notifies.some((n) => n.includes("learn-docs plan; learn capture skipped")),
      "reported the learn-docs skip",
    );
    assert.ok(
      !h.notifies.some((n) => n.includes("multi-angle learn")),
      "no orchestration kickoff on a learn-docs plan",
    );
  } finally {
    h.dispose();
  }
});

test("/learn (bare, gathered bundle): keeps the marker and kicks off orchestration", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  const bin = fakePerk(cwd, { stdout: GATHERED_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.runCommandHandler("learn", "");
    // The model captures via the `learn` tool, so the command must NOT clear the marker.
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "bare /learn left pending-learn for the capture pass",
    );
    assert.ok(
      h.notifies.some((n) => n.includes("multi-angle learn")),
      "reported the orchestration kickoff",
    );
  } finally {
    h.dispose();
  }
});

test("/learn (bare, gather failure): keeps the marker and falls back to the simple pass", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  setMarker(cwd, PENDING_LEARN);
  writePlanRef(cwd, PLAN_REF);
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.runCommandHandler("learn", "");
    assert.ok(
      existsSync(markerPath(cwd, PENDING_LEARN)),
      "gather failure leaves the marker for the fallback capture pass",
    );
    assert.ok(
      h.notifies.some((n) => n.includes("falling back to the simple learn pass")),
      "reported the graceful fallback",
    );
  } finally {
    h.dispose();
  }
});
