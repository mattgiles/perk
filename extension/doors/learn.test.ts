// Live warm-door tests for `/learn`. No gh — the cold doors are faked via `fakePerk`. The
// no-summary arm delegates to `perk learn skip` (the canonical §8.36 skip recording) and mirrors
// the marker-clear. Driven through a REAL bound AgentSession via the T1 harness.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { markerPath, PENDING_LEARN, setMarker, writePlanRef } from "../substrate/cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { learnGuidance, learnOrchestrateGuidance } from "./learn.ts";

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

test("learnOrchestrateGuidance: names the angles, the spawn/reconcile steps, and renders the paths", () => {
  const g = learnOrchestrateGuidance({
    manifestPath: "/abs/learn-evidence/manifest.json",
    bundleDir: "/abs/learn-evidence",
  });
  // Spawn step: 2–4 fresh-context analysts via ONE foreground workflowScript wave.
  assert.match(g, /2[\u2013-]4/);
  assert.match(g, /perk\.learn-analyst/);
  assert.match(g, /subagent/);
  assert.match(g, /workflowScript/);
  assert.match(g, /async: false/);
  assert.match(g, /runs\.all/);
  assert.match(g, /context: "fresh"/);
  // session-deviations is mandatory + carries the off-track/dead-ends/wasted-effort emphasis.
  assert.match(g, /session-deviations/);
  assert.match(g, /off-track/);
  assert.match(g, /dead ends/);
  assert.match(g, /plan-vs-implementation/);
  assert.match(g, /existing-docs/);
  // Reconcile → capture/skip, and the missing/malformed-child instruction.
  assert.match(g, /[Rr]econcile/);
  assert.match(g, /missing or malformed child report/);
  assert.match(g, /`learn`\*\* tool/);
  assert.match(g, /no `summary`/);
  // Renders the manifest path + bundle dir.
  assert.match(g, /\/abs\/learn-evidence\/manifest\.json/);
  assert.match(g, /\/abs\/learn-evidence/);
});

test("learnOrchestrateGuidance: model override appears when set, absent when empty", () => {
  const withModel = learnOrchestrateGuidance({
    model: "google/gemini-3.5-flash",
    manifestPath: "/m.json",
    bundleDir: "/d",
  });
  assert.match(withModel, /model: "google\/gemini-3\.5-flash"/);
  const noModel = learnOrchestrateGuidance({ manifestPath: "/m.json", bundleDir: "/d" });
  assert.doesNotMatch(noModel, /model:/);
  assert.match(noModel, /no model override/);
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
