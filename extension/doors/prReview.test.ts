// Tests for the warm `/pr-review` door. The pure `prReviewGuidance` + `decodePostParams`
// are pinned directly; the `post_pr_review` delegation + the command/tool registration + headless
// safety are exercised against a REAL bound session via the T1 harness, OFFLINE (a fake `perk`
// stands in for the GitHub mutation, so no LLM / network / gh / Python is invoked).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { decodePostParams, PR_REVIEW_REPORT_SCHEMA, prReviewGuidance } from "./prReview.ts";

// --- prReviewGuidance: ONE foreground workflowScript report wave ----------------------------

test("prReviewGuidance launches one foreground workflowScript wave of perk.pr-reviewer lanes", () => {
  const text = prReviewGuidance();
  assert.match(text, /workflowScript/);
  assert.match(text, /async: false/);
  assert.match(text, /runs\.all/);
  assert.match(text, /perk\.pr-reviewer/);
  assert.match(text, /context: "fresh"/);
  assert.match(text, /phase: "review"/);
});

test("prReviewGuidance names the four angle-slug keys with plan-fidelity mandatory", () => {
  const text = prReviewGuidance();
  assert.match(text, /ALWAYS include \*\*plan-fidelity\*\*/);
  assert.match(text, /\*\*correctness\*\*/);
  assert.match(text, /\*\*tests\*\*/);
  assert.match(text, /\*\*quality\*\*/);
  // the lane-count cap (the wave's cost/latency bound): plan-fidelity + 1–2 others
  assert.match(text, /add 1–2 of/);
  // key = label = the angle slug (stable identity for the trace and reconciliation)
  assert.match(text, /`key` and `label` are the angle slug/);
});

test("prReviewGuidance sets outputSchema and returns the typed structuredOutput aggregate", () => {
  const text = prReviewGuidance();
  assert.match(text, /outputSchema/);
  assert.match(text, /structuredOutput/);
  assert.match(text, /report: structuredOutput \?\? null/);
});

test("prReviewGuidance embeds PR_REVIEW_REPORT_SCHEMA verbatim (fenced-block round-trip)", () => {
  const text = prReviewGuidance();
  const fenced = text.match(/```json\n([\s\S]*?)\n\s*```/);
  assert.ok(fenced?.[1], "the guidance carries one fenced json schema block");
  assert.deepEqual(JSON.parse(fenced[1]), PR_REVIEW_REPORT_SCHEMA);
});

test("PR_REVIEW_REPORT_SCHEMA pins the report shape (closed, all four fields required)", () => {
  const s = PR_REVIEW_REPORT_SCHEMA as {
    additionalProperties: boolean;
    required: string[];
    properties: {
      angle: { enum: string[] };
      verdict: { enum: string[] };
      findings: {
        items: {
          additionalProperties: boolean;
          required: string[];
          properties: { line: { type: string } };
        };
      };
      fyi: { items: { type: string } };
    };
    if: unknown;
    then: unknown;
  };
  assert.equal(s.additionalProperties, false);
  assert.deepEqual(s.required, ["angle", "verdict", "findings", "fyi"]);
  assert.deepEqual(s.properties.angle.enum, ["plan-fidelity", "correctness", "tests", "quality"]);
  assert.deepEqual(s.properties.verdict.enum, ["clean", "actionable"]);
  assert.equal(s.properties.findings.items.additionalProperties, false);
  assert.deepEqual(s.properties.findings.items.required, ["path", "line", "body"]);
  assert.equal(s.properties.findings.items.properties.line.type, "integer");
  assert.equal(s.properties.fyi.items.type, "string");
  // The internal-consistency conditional: a clean verdict cannot carry findings — an
  // inconsistent lane report is schema-invalid (fails the lane), never reconciled.
  assert.deepEqual(s.if, { properties: { verdict: { const: "clean" } } });
  assert.deepEqual(s.then, { properties: { findings: { maxItems: 0 } } });
});

test("prReviewGuidance states the completeness policy (covered ⟺ ok + report; one retry; never clean)", () => {
  const text = prReviewGuidance();
  assert.match(text, /COVERED iff its lane resolved `ok: true` with a non-null `report`/);
  assert.match(text, /exactly ONE targeted retry wave/);
  assert.match(text, /NEVER derive or post a `clean` verdict from partial coverage/);
});

test("prReviewGuidance drops the fenced-JSON-scraping relay (negative pins)", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /collect each child's fenced/);
  // The upstream-removed grouped-execution vocabulary (`tasks` / tasks: / tasks[) — scoped so
  // an ordinary future plural ("the lanes' tasks") can't trip the pin.
  assert.doesNotMatch(text, /`tasks`|tasks\s*[:[]/);
});

test("prReviewGuidance instructs reconcile/union/dedupe and verdict derivation over typed reports", () => {
  const text = prReviewGuidance();
  assert.match(text, /union/i);
  assert.match(text, /dedupe/i);
  assert.match(text, /if ANY report is actionable/i);
});

test("prReviewGuidance tells the parent to post via the post_pr_review tool", () => {
  const text = prReviewGuidance();
  assert.match(text, /post_pr_review/);
  assert.match(text, /last_pr_review/);
});

test("prReviewGuidance injects the configured model as a workflow-level default when set", () => {
  const text = prReviewGuidance("anthropic/claude-opus-4");
  assert.match(text, /model: "anthropic\/claude-opus-4"/);
  assert.match(text, /applied to every lane/);
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
