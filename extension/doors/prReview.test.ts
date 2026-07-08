// Tests for the warm `/pr-review` door. The pure `prReviewGuidance` + `decodePostParams`
// are pinned directly; the `post_pr_review` delegation + the command/tool registration + headless
// safety are exercised against a REAL bound session via the T1 harness, OFFLINE (a fake `perk`
// stands in for the GitHub mutation, so no LLM / network / gh / Python is invoked).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { decodePostParams, prReviewGuidance } from "./prReview.ts";

// --- prReviewGuidance: the multi-angle classify-then-act seed -------------------------------

test("prReviewGuidance spawns 2–3 perk.pr-reviewer children with a fresh context", () => {
  const text = prReviewGuidance();
  assert.match(text, /perk\.pr-reviewer/);
  assert.match(text, /context: "fresh"/);
  assert.match(text, /2.3/); // "2–3" reviewers in parallel
  assert.match(text, /parallel/i);
});

test("prReviewGuidance names the four angles with plan-fidelity always included", () => {
  const text = prReviewGuidance();
  assert.match(text, /ALWAYS include.*Plan fidelity/s);
  assert.match(text, /Correctness & regressions/);
  assert.match(text, /Tests & validation/);
  assert.match(text, /Code quality, simplicity/);
});

test("prReviewGuidance instructs reconcile/union/dedupe and verdict derivation", () => {
  const text = prReviewGuidance();
  assert.match(text, /union/i);
  assert.match(text, /dedupe/i);
  assert.match(text, /if ANY reviewer is actionable/i);
});

test("prReviewGuidance tells the parent to post via the post_pr_review tool", () => {
  const text = prReviewGuidance();
  assert.match(text, /post_pr_review/);
  assert.match(text, /last_pr_review/);
});

test("prReviewGuidance injects the configured model when set (on every reviewer spawn)", () => {
  const text = prReviewGuidance("anthropic/claude-opus-4");
  assert.match(text, /model: "anthropic\/claude-opus-4"/);
  assert.match(text, /every reviewer spawn/);
  assert.match(text, /\[models\.subagents\] pr-reviewer model/);
});

test("prReviewGuidance omits the model override when unset", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /model: "/);
  assert.match(text, /default model/);
});

test("prReviewGuidance renders both verdict outcomes and the next-step surfacing", () => {
  const text = prReviewGuidance();
  // actionable → advisory COMMENT review, next step /address
  assert.match(text, /COMMENT review/);
  assert.match(text, /actionable .*`\/address`/u);
  // clean → a single 👍 reaction, next step /land
  assert.match(text, /\u{1F44D} reaction/u);
  assert.match(text, /clean .*`\/land`/u);
  // FYI notes are surfaced in-session only
  assert.match(text, /FYI notes/);
});

test("prReviewGuidance describes report-only children, not posting children", () => {
  const text = prReviewGuidance();
  // the children report; the parent reconciles + posts (no "the child posts" wording)
  assert.match(text, /\{angle, verdict, findings, fyi\}/);
  assert.doesNotMatch(text, /child .*posts/i);
});

test("prReviewGuidance does not hardcode the perk-pr-review skill pointer (binding suffix)", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /Follow the perk-pr-review skill/);
});

test("prReviewGuidance injects the operator directive when set (within the invariants)", () => {
  const text = prReviewGuidance("", "focus on the dignified-python skill");
  assert.match(text, /Operator focus for this run/);
  assert.match(text, /focus on the dignified-python skill/);
  assert.match(text, /Plan-fidelity angle stays mandatory/);
});

test("prReviewGuidance is byte-stable when the directive is empty/absent", () => {
  assert.equal(prReviewGuidance("m"), prReviewGuidance("m", ""));
  assert.doesNotMatch(prReviewGuidance("", ""), /Operator focus for this run/);
});

// --- decodePostParams: strict decode (a GitHub mutation — whole-batch refusal on any drift) --

test("decodePostParams accepts a valid clean verdict (no comments)", () => {
  const p = decodePostParams({ verdict: "clean", summary: "all good", angles: ["plan-fidelity"] });
  assert.ok(p);
  assert.equal(p?.verdict, "clean");
  assert.equal(p?.comments, undefined);
  assert.deepEqual(p?.angles, ["plan-fidelity"]);
});

test("decodePostParams accepts a valid actionable verdict with comments + fyi", () => {
  const p = decodePostParams({
    verdict: "actionable",
    summary: "two issues",
    comments: [{ path: "a.ts", line: 12, body: "fix this" }],
    fyi: ["a nit"],
    pr: 7,
    angles: ["plan-fidelity", "tests"],
  });
  assert.ok(p);
  assert.equal(p?.comments?.length, 1);
  assert.equal(p?.comments?.[0]?.line, 12);
  assert.equal(p?.pr, 7);
});

test("decodePostParams rejects a clean verdict carrying comments (contradiction)", () => {
  assert.equal(
    decodePostParams({
      verdict: "clean",
      summary: "ok",
      comments: [{ path: "a.ts", line: 1, body: "x" }],
    }),
    null,
  );
});

test("decodePostParams rejects a malformed comment row", () => {
  assert.equal(
    decodePostParams({
      verdict: "actionable",
      summary: "s",
      comments: [{ path: "a.ts", line: 1.5, body: "x" }], // non-integer line
    }),
    null,
  );
  assert.equal(
    decodePostParams({
      verdict: "actionable",
      summary: "s",
      comments: [{ path: "", line: 1, body: "x" }], // empty path
    }),
    null,
  );
});

test("decodePostParams rejects a missing/invalid verdict or summary", () => {
  assert.equal(decodePostParams({ summary: "s" }), null);
  assert.equal(decodePostParams({ verdict: "maybe", summary: "s" }), null);
  assert.equal(decodePostParams({ verdict: "clean" }), null);
  assert.equal(decodePostParams({ verdict: "clean", summary: "" }), null);
});

// --- post_pr_review: end-to-end delegation (offline fake perk) ------------------------------

const ACTIONABLE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  pr: 42,
  mode: "review",
  verdict: "actionable",
  fyi: [],
  next_command: "/address",
  comment_count: 2,
});

const CLEAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  pr: 42,
  mode: "reaction",
  verdict: "clean",
  fyi: [],
  next_command: "/land",
  comment_count: 0,
});

test("tool: post_pr_review delegates an actionable batch, records last_pr_review", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: ACTIONABLE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", {
      verdict: "actionable",
      summary: "two issues",
      comments: [{ path: "a.ts", line: 12, body: "fix" }],
      angles: ["plan-fidelity", "correctness"],
      pr: 42,
    });
    const details = result.details as { ok: boolean; comment_count?: number; verdict?: string };
    assert.equal(details.ok, true);
    assert.equal(details.comment_count, 2);
    const rec = h.workflowState().last_pr_review as {
      pr?: number;
      verdict?: string;
      angles?: string[];
      comment_count?: number;
      mode?: string;
    };
    assert.equal(rec?.pr, 42);
    assert.equal(rec?.verdict, "actionable");
    assert.deepEqual(rec?.angles, ["plan-fidelity", "correctness"]);
    assert.equal(rec?.comment_count, 2);
    assert.equal(rec?.mode, "review");
  } finally {
    h.dispose();
  }
});

test("tool: post_pr_review delegates a clean batch (👍), records last_pr_review", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CLEAN_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", {
      verdict: "clean",
      summary: "clean",
      angles: ["plan-fidelity"],
    });
    const details = result.details as { ok: boolean; verdict?: string };
    assert.equal(details.ok, true);
    assert.match(result.content[0]?.text ?? "", /Next step: \/land/);
    const rec = h.workflowState().last_pr_review as { verdict?: string; comment_count?: number };
    assert.equal(rec?.verdict, "clean");
    assert.equal(rec?.comment_count, 0);
  } finally {
    h.dispose();
  }
});

test("tool: a failing worker fails loud-but-soft (no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "x" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.equal(h.workflowState().last_pr_review, undefined);
  } finally {
    h.dispose();
  }
});

test("/pr-review and post_pr_review register and are headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("pr-review"), "the /pr-review command is registered");
    // The tool is registered and executes without a UI: a bad-input call decodes to bad_input
    // before any exec (no fake perk needed), proving registration + headless safety.
    const result = await h.invokeTool("post_pr_review", { summary: "missing verdict" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});
