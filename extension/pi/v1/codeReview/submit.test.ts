// Adapter tests for the `submit_pr_review` installer: the pure `decodeSubmitParams` is pinned
// directly; the production `ReviewSubmitter` cold-door composition runs over an in-memory exec
// recorder (argv + staged-batch pins); the `FormalEventGate` production is pinned with a
// structural fake ctx; the registered tool's delegation + outcomes run against a REAL bound
// session via the T1 harness, OFFLINE (a fake `perk` stands in for the cold door — no LLM /
// network / gh / Python). The gate-ladder POLICY matrix lives in
// `codeReview/submission.test.ts` over deterministic fakes.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExecResult, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { reviewPostsOf } from "../../../session/workflowSession.ts";
import type { ExecHost } from "../../../substrate/coldDoor.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../../../testing/harness.ts";
import {
  createColdDoorReviewSubmitter,
  decodeSubmitParams,
  formalEventGateFor,
  type SubmitGateCtx,
} from "./submit.ts";

// --- compile-time satisfaction: the structural ctx slice can never drift from the SDK --------

const _c: SubmitGateCtx = {} as ExtensionContext;
void _c;

// --- decodeSubmitParams: strict decode (a GitHub mutation — whole-batch refusal) ---------------

test("decodeSubmitParams accepts a minimal approve (empty body, no comments)", () => {
  const p = decodeSubmitParams({ pr: 42, event: "approve", body: "" });
  assert.deepEqual(p, { pr: 42, event: "approve", body: "" });
});

test("decodeSubmitParams accepts a full comment batch with sides and dry_run", () => {
  const p = decodeSubmitParams({
    pr: 42,
    event: "comment",
    body: "overall",
    comments: [
      { path: "a.ts", line: 12, body: "fix" },
      { path: "b.ts", line: 3, side: "LEFT", body: "removed" },
    ],
    dry_run: true,
  });
  assert.ok(p);
  assert.equal(p?.comments?.length, 2);
  assert.equal(p?.comments?.[0]?.side, undefined);
  assert.equal(p?.comments?.[1]?.side, "LEFT");
  assert.equal(p?.dry_run, true);
});

test("decodeSubmitParams: allow_repost decodes strictly (boolean or absent)", () => {
  const p = decodeSubmitParams({ pr: 1, event: "comment", body: "x", allow_repost: true });
  assert.equal(p?.allow_repost, true);
  assert.equal(decodeSubmitParams({ pr: 1, event: "comment", body: "x" })?.allow_repost, undefined);
  assert.equal(
    decodeSubmitParams({ pr: 1, event: "comment", body: "x", allow_repost: "yes" }),
    null,
  );
});

test("decodeSubmitParams rejects a bad event / missing pr / non-string body", () => {
  assert.equal(decodeSubmitParams({ pr: 1, event: "APPROVE", body: "" }), null);
  assert.equal(decodeSubmitParams({ pr: 1, event: "merge", body: "" }), null);
  assert.equal(decodeSubmitParams({ event: "comment", body: "x" }), null);
  assert.equal(decodeSubmitParams({ pr: 1.5, event: "comment", body: "x" }), null);
  assert.equal(decodeSubmitParams({ pr: 1, event: "comment" }), null);
  assert.equal(decodeSubmitParams({ pr: 1, event: "comment", body: 3 }), null);
});

test("decodeSubmitParams rejects a malformed comment row (whole-batch refusal)", () => {
  const base = { pr: 1, event: "comment" as const, body: "x" };
  assert.equal(
    decodeSubmitParams({ ...base, comments: [{ path: "a.ts", line: 1.5, body: "x" }] }),
    null,
  );
  assert.equal(decodeSubmitParams({ ...base, comments: [{ path: "", line: 1, body: "x" }] }), null);
  assert.equal(
    decodeSubmitParams({ ...base, comments: [{ path: "a.ts", line: 1, body: "" }] }),
    null,
  );
  assert.equal(
    decodeSubmitParams({ ...base, comments: [{ path: "a.ts", line: 1, side: "TOP", body: "x" }] }),
    null,
  );
  assert.equal(decodeSubmitParams({ ...base, dry_run: "yes" }), null);
});

// --- the FormalEventGate production (structural fake ctx) ---------------------------------------

test("formalEventGateFor: hasUI selects the arm; interactive wraps ctx.ui.confirm", async () => {
  assert.deepEqual(
    formalEventGateFor({ hasUI: false, ui: { notify() {}, confirm: () => Promise.resolve(true) } }),
    {
      kind: "headless",
    },
  );
  const confirms: { title: string; message: string }[] = [];
  const gate = formalEventGateFor({
    hasUI: true,
    ui: {
      notify() {},
      confirm(title: string, message: string) {
        confirms.push({ title, message });
        return Promise.resolve(false);
      },
    },
  });
  assert.equal(gate.kind, "interactive");
  assert.ok(gate.kind === "interactive");
  assert.equal(await gate.confirm("Q?", "S"), false);
  assert.deepEqual(confirms, [{ title: "Q?", message: "S" }]);
});

// --- the ReviewSubmitter production (in-memory exec recorder) ------------------------------------

const SUBMIT_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  pr: 42,
  event: "comment",
  mode: "review",
  comment_count: 2,
});

/** A fake `pi` exec host recording calls and returning a scripted result. */
function fakeExec(result: Partial<ExecResult>): {
  pi: ExecHost;
  calls: { command: string; args: string[] }[];
} {
  const calls: { command: string; args: string[] }[] = [];
  return {
    calls,
    pi: {
      exec: (command: string, args: string[]) => {
        calls.push({ command, args });
        return Promise.resolve({ stdout: "", stderr: "", code: 0, killed: false, ...result });
      },
    },
  };
}

function coldCtx(): { cwd: string; sessionManager: { getBranch(): unknown[] } } {
  return {
    cwd: mkdtempSync(join(tmpdir(), "submit-pr-review-test-")),
    sessionManager: { getBranch: () => [] },
  };
}

test("submitter: the argv shape + the staged batch file (the stdin channel at argv END)", async () => {
  const { pi, calls } = fakeExec({ stdout: SUBMIT_OK_JSON });
  const submitter = createColdDoorReviewSubmitter(pi, coldCtx());
  const comments = [{ path: "a.ts", line: 12, side: "RIGHT" as const, body: "fix" }];
  const outcome = await submitter.submit({
    pr: 42,
    event: "comment",
    body: "overall",
    comments,
    dryRun: false,
  });
  assert.ok(outcome.ok);
  assert.deepEqual(outcome.ok ? outcome.data : null, {
    dry_run: false,
    pr: 42,
    event: "comment",
    mode: "review",
    comment_count: 2,
  });
  const args = calls[0]?.args ?? [];
  assert.deepEqual(args.slice(0, 7), [
    "pr",
    "review-submit",
    "--pr",
    "42",
    "--event",
    "comment",
    "--json",
  ]);
  assert.equal(args[args.length - 2], "--batch", "the --batch flag lands at argv end");
  const staged = readFileSync(args[args.length - 1] ?? "", "utf8");
  assert.equal(staged, `${JSON.stringify({ body: "overall", comments }, null, 2)}\n`);
});

test("submitter: dryRun rides the argv as --dry-run; the batch omits comments when absent", async () => {
  const { pi, calls } = fakeExec({ stdout: SUBMIT_OK_JSON });
  const submitter = createColdDoorReviewSubmitter(pi, coldCtx());
  await submitter.submit({ pr: 42, event: "approve", body: "", dryRun: true });
  const args = calls[0]?.args ?? [];
  assert.ok(args.includes("--dry-run"), "argv carries --dry-run");
  const staged = readFileSync(args[args.length - 1] ?? "", "utf8");
  assert.equal(staged, `${JSON.stringify({ body: "" }, null, 2)}\n`);
});

test("submitter: bad_anchors with decodable invalid[] yields the typed repair arm", async () => {
  const { pi } = fakeExec({
    stdout: JSON.stringify({
      success: false,
      error_type: "bad_anchors",
      message: "1 of 2 comment anchor(s) not in the PR diff — repair and retry",
      invalid: [{ index: 0, path: "a.ts", line: 999, side: "RIGHT", reason: "line not in diff" }],
    }),
    code: 1,
  });
  const submitter = createColdDoorReviewSubmitter(pi, coldCtx());
  const outcome = await submitter.submit({ pr: 42, event: "comment", body: "b", dryRun: true });
  assert.ok(!outcome.ok && outcome.kind === "bad_anchors");
  if (!outcome.ok && outcome.kind === "bad_anchors") {
    assert.deepEqual(outcome.invalid, [
      { index: 0, path: "a.ts", line: 999, side: "RIGHT", reason: "line not in diff" },
    ]);
    assert.equal(outcome.message, "1 of 2 comment anchor(s) not in the PR diff — repair and retry");
  }
});

test("submitter: a malformed invalid[] payload degrades to the failed arm (never a half table)", async () => {
  const { pi } = fakeExec({
    stdout: JSON.stringify({
      success: false,
      error_type: "bad_anchors",
      message: "anchors rejected",
      invalid: [{ index: "zero", path: "a.ts" }],
    }),
    code: 1,
  });
  const submitter = createColdDoorReviewSubmitter(pi, coldCtx());
  const outcome = await submitter.submit({ pr: 42, event: "comment", body: "b", dryRun: true });
  assert.deepEqual(outcome, {
    ok: false,
    kind: "failed",
    message: "anchors rejected",
    errorType: "bad_anchors",
  });
});

test("submitter: a structured fail envelope passes message + error_type through the failed arm", async () => {
  const { pi } = fakeExec({
    stdout: JSON.stringify({
      success: false,
      error_type: "github_unauthed",
      message: "gh is not authenticated",
    }),
    code: 1,
  });
  const submitter = createColdDoorReviewSubmitter(pi, coldCtx());
  const outcome = await submitter.submit({ pr: 7, event: "comment", body: "b", dryRun: false });
  assert.deepEqual(outcome, {
    ok: false,
    kind: "failed",
    message: "gh is not authenticated",
    errorType: "github_unauthed",
  });
});

// --- submit_pr_review: end-to-end through the harness (offline fake perk) ----------------------

test("tool: a comment submission succeeds, records last_review + the review_posts row", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: SUBMIT_OK_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit_pr_review", {
      pr: 42,
      event: "comment",
      body: "overall",
      comments: [
        { path: "a.ts", line: 12, body: "fix" },
        { path: "b.ts", line: 3, side: "LEFT", body: "removed" },
      ],
    });
    const details = result.details as { ok: boolean; mode?: string; comment_count?: number };
    assert.equal(details.ok, true);
    assert.equal(details.comment_count, 2);
    assert.match(result.content[0]?.text ?? "", /submitted comment review to PR #42/);
    const rec = h.workflowState().last_review as {
      pr?: number;
      event?: string;
      comment_count?: number;
      mode?: string;
    };
    assert.equal(rec?.pr, 42);
    assert.equal(rec?.event, "comment");
    assert.equal(rec?.comment_count, 2);
    assert.equal(rec?.mode, "review");
    const posts = reviewPostsOf(h.workflowState().review_posts);
    assert.deepEqual(
      posts.map((r) => ({ pr: r.pr, event: r.event })),
      [{ pr: 42, event: "comment" }],
      "the real success also appends its review_posts ledger row",
    );
  } finally {
    h.dispose();
  }
});

test("tool: the enforced resume guard — already_posted on a repeat; dry-run and allow_repost pass", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // The envelope carries no `pr`, so each record falls back to its own call's param.
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: true, event: "comment", mode: "review" }),
  });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const first = await h.invokeTool("submit_pr_review", { pr: 41, event: "comment", body: "x" });
    assert.equal((first.details as { ok: boolean }).ok, true);

    const repeat = await h.invokeTool("submit_pr_review", { pr: 41, event: "comment", body: "y" });
    const repeatDetails = repeat.details as { ok: boolean; error_type?: string };
    assert.equal(repeatDetails.ok, false);
    assert.equal(repeatDetails.error_type, "already_posted");

    // The repair loop is never blocked: a dry-run against the same PR still validates.
    const dry = await h.invokeTool("submit_pr_review", {
      pr: 41,
      event: "comment",
      body: "y",
      dry_run: true,
    });
    assert.equal((dry.details as { ok: boolean }).ok, true);

    // The deliberate escape hatch: allow_repost posts a second review to the same PR.
    const deliberate = await h.invokeTool("submit_pr_review", {
      pr: 41,
      event: "comment",
      body: "y",
      allow_repost: true,
    });
    assert.equal((deliberate.details as { ok: boolean }).ok, true);
    // Ordered ledger rows: read-rebuild-append carries the whole history.
    const posts = reviewPostsOf(h.workflowState().review_posts);
    assert.deepEqual(
      posts.map((r) => r.pr),
      [41, 41],
    );
  } finally {
    h.dispose();
  }
});

test("tool: a review_folded mode gets the fold note", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const folded = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    dry_run: false,
    pr: 42,
    event: "request-changes",
    mode: "review_folded",
    comment_count: 3,
  });
  const bin = fakePerk(cwd, { stdout: folded });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    // `comment` keeps the harness path confirm-free; the fold note renders from the payload mode.
    const result = await h.invokeTool("submit_pr_review", { pr: 42, event: "comment", body: "b" });
    assert.match(result.content[0]?.text ?? "", /comments folded into the review body/);
  } finally {
    h.dispose();
  }
});

test("tool: a dry-run success validates without recording last_review", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const validated = JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    dry_run: true,
    pr: 42,
    event: "approve",
    mode: "validated",
    comment_count: 1,
  });
  const bin = fakePerk(cwd, { stdout: validated });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit_pr_review", {
      pr: 42,
      event: "approve",
      body: "",
      comments: [{ path: "a.ts", line: 12, body: "fix" }],
      dry_run: true,
    });
    const details = result.details as { ok: boolean };
    assert.equal(details.ok, true);
    assert.match(result.content[0]?.text ?? "", /validated — 1 inline comment\(s\)/);
    assert.equal(h.workflowState().last_review, undefined, "no record on dry-run");
  } finally {
    h.dispose();
  }
});

test("tool: bad_anchors with decodable invalid[] renders the per-comment repair table", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const badAnchors = JSON.stringify({
    success: false,
    error_type: "bad_anchors",
    message: "1 of 2 comment anchor(s) not in the PR diff — repair and retry",
    dry_run: true,
    pr: 42,
    event: "comment",
    invalid: [{ index: 0, path: "a.ts", line: 999, side: "RIGHT", reason: "line not in diff" }],
  });
  const bin = fakePerk(cwd, { stdout: badAnchors, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit_pr_review", {
      pr: 42,
      event: "comment",
      body: "b",
      comments: [{ path: "a.ts", line: 999, body: "fix" }],
      dry_run: true,
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_anchors");
    const text = result.content[0]?.text ?? "";
    assert.match(text, /comment\[0\] a\.ts:999 \(RIGHT\) — line not in diff/);
    assert.match(text, /repair these anchors and re-run with dry_run: true/);
  } finally {
    h.dispose();
  }
});

test("tool: bad_anchors with a malformed payload renders a plain fail (never a half table)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = JSON.stringify({
    success: false,
    error_type: "bad_anchors",
    message: "anchors rejected",
    invalid: [{ index: "zero", path: "a.ts" }],
  });
  const bin = fakePerk(cwd, { stdout: malformed, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit_pr_review", {
      pr: 42,
      event: "comment",
      body: "b",
      dry_run: true,
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_anchors");
    assert.doesNotMatch(result.content[0]?.text ?? "", /repair these anchors/);
  } finally {
    h.dispose();
  }
});

test("tool: a structured fail envelope on a non-zero exit surfaces its error_type", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const unauthed = JSON.stringify({
    success: false,
    error_type: "github_unauthed",
    message: "gh is not authenticated",
  });
  const bin = fakePerk(cwd, { stdout: unauthed, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("submit_pr_review", { pr: 7, event: "comment", body: "b" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "github_unauthed");
    assert.equal(h.workflowState().last_review, undefined);
  } finally {
    h.dispose();
  }
});

test("tool: headless + a formal event refuses (headless_formal_event), nothing executed", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: SUBMIT_OK_JSON, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
  });
  try {
    const result = await h.invokeTool("submit_pr_review", { pr: 42, event: "approve", body: "" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "headless_formal_event");
    assert.equal(existsSync(argvFile), false, "the cold door was never executed");
  } finally {
    h.dispose();
  }
});

test("tool: malformed params decode to bad_input before any exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    const result = await h.invokeTool("submit_pr_review", { pr: 42, event: "comment" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});
