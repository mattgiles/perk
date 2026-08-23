// Tests for the warm `submit_pr_review` tool. The pure `decodeSubmitParams` is pinned directly;
// the tool's delegation + outcomes run against a REAL bound session via the T1 harness, OFFLINE
// (a fake `perk` stands in for the cold door — no LLM / network / gh / Python). The formal-event
// confirm gate is exercised through the exported `submitPrReview` core with structural fakes
// (the coldDoor.test.ts idiom) because the harness UI context carries no `confirm`.

import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExecResult, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ExecHost } from "../substrate/coldDoor.ts";
import type { BranchEntry, EntrySink } from "../substrate/workflowState.ts";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  decodeSubmitParams,
  reviewPostsOf,
  type SubmitCtx,
  submitPrReview,
} from "./submitPrReview.ts";

// --- compile-time satisfaction: the structural ctx slice can never drift from the SDK --------

const _c: SubmitCtx = {} as ExtensionContext;
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

// --- submitPrReview gates + delegation (structural fakes — the coldDoor.test.ts idiom) ---------

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

interface FakePi {
  pi: ExecHost & EntrySink;
  calls: { command: string; args: string[] }[];
  branch: BranchEntry[];
}

/** A fake `pi` recording exec calls (scripted result) and appending entries onto the branch. */
function fakePi(result: Partial<ExecResult> | Error): FakePi {
  const calls: { command: string; args: string[] }[] = [];
  const branch: BranchEntry[] = [];
  return {
    calls,
    branch,
    pi: {
      exec: (command: string, args: string[]) => {
        calls.push({ command, args });
        if (result instanceof Error) return Promise.reject(result);
        return Promise.resolve({ stdout: "", stderr: "", code: 0, killed: false, ...result });
      },
      appendEntry: (customType: string, data?: unknown) => {
        branch.push({ type: "custom", customType, data: data as Record<string, unknown> });
      },
    },
  };
}

/** A fake SubmitCtx with a recorded, scripted confirm dialog. */
function fakeCtx(opts: { branch: BranchEntry[]; hasUI?: boolean; confirmAnswer?: boolean }): {
  ctx: SubmitCtx;
  confirms: { title: string; message: string }[];
} {
  const confirms: { title: string; message: string }[] = [];
  const ctx: SubmitCtx = {
    cwd: mkdtempSync(join(tmpdir(), "submit-pr-review-test-")),
    sessionManager: { getBranch: () => opts.branch },
    hasUI: opts.hasUI ?? true,
    ui: {
      notify: () => {},
      confirm: (title: string, message: string) => {
        confirms.push({ title, message });
        return Promise.resolve(opts.confirmAnswer ?? true);
      },
    },
  };
  return { ctx, confirms };
}

test("submitPrReview: a formal event raises the confirm (wire event + count); declined → no exec", async () => {
  const { pi, calls, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx, confirms } = fakeCtx({ branch, confirmAnswer: false });
  const result = await submitPrReview(pi, ctx, {
    pr: 42,
    event: "request-changes",
    body: "needs work\nsecond line",
    comments: [{ path: "a.ts", line: 12, body: "fix" }],
  });
  assert.equal(result.details.ok, false);
  if (!result.details.ok) assert.equal(result.details.error_type, "user_declined");
  assert.equal(confirms.length, 1);
  assert.match(confirms[0]?.title ?? "", /Post REQUEST_CHANGES review to PR #42\?/);
  assert.match(confirms[0]?.message ?? "", /1 inline comment\(s\)/);
  assert.match(confirms[0]?.message ?? "", /needs work/);
  assert.doesNotMatch(confirms[0]?.message ?? "", /second line/);
  assert.equal(calls.length, 0, "nothing executed on decline");
});

test("submitPrReview: an accepted confirm proceeds to the cold door", async () => {
  const { pi, calls, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx, confirms } = fakeCtx({ branch, confirmAnswer: true });
  const result = await submitPrReview(pi, ctx, { pr: 42, event: "approve", body: "" });
  assert.equal(confirms.length, 1);
  assert.equal(calls.length, 1);
  assert.equal(result.details.ok, true);
});

test("submitPrReview: a comment event never confirms", async () => {
  const { pi, calls, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx, confirms } = fakeCtx({ branch });
  await submitPrReview(pi, ctx, { pr: 42, event: "comment", body: "advisory" });
  assert.equal(confirms.length, 0);
  assert.equal(calls.length, 1);
});

test("submitPrReview: dry_run bypasses the confirm AND the headless gate; argv carries --dry-run", async () => {
  const { pi, calls, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx, confirms } = fakeCtx({ branch, hasUI: false });
  const result = await submitPrReview(pi, ctx, {
    pr: 42,
    event: "approve",
    body: "",
    dry_run: true,
  });
  assert.equal(confirms.length, 0);
  assert.equal(result.details.ok, true);
  assert.ok(calls[0]?.args.includes("--dry-run"), "argv carries --dry-run");
});

test("submitPrReview: the argv shape + the staged batch file (the stdin channel at argv END)", async () => {
  const { pi, calls, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx } = fakeCtx({ branch });
  const comments = [{ path: "a.ts", line: 12, side: "RIGHT" as const, body: "fix" }];
  await submitPrReview(pi, ctx, { pr: 42, event: "comment", body: "overall", comments });
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

test("submitPrReview: a real success appends last_review to the branch (strict read-back)", async () => {
  const { pi, branch } = fakePi({ stdout: SUBMIT_OK_JSON });
  const { ctx } = fakeCtx({ branch });
  const result = await submitPrReview(pi, ctx, { pr: 42, event: "comment", body: "overall" });
  assert.equal(result.details.ok, true);
  const entry = branch.find((e) => e.customType === "perk:workflow-state");
  const record = (entry?.data as { last_review?: Record<string, unknown> })?.last_review;
  assert.equal(record?.pr, 42);
  assert.equal(record?.event, "comment");
  assert.equal(record?.comment_count, 2);
  assert.equal(record?.mode, "review");
});

test("submitPrReview: real successes append ORDERED review_posts rows (the stack resume ledger)", async () => {
  // The envelope carries no `pr`, so the record falls back to each call's own param.
  const { pi, branch } = fakePi({
    stdout: JSON.stringify({ success: true, event: "comment", mode: "review" }),
  });
  const { ctx } = fakeCtx({ branch });
  await submitPrReview(pi, ctx, { pr: 41, event: "comment", body: "lower" });
  await submitPrReview(pi, ctx, { pr: 42, event: "comment", body: "upper" });
  const entries = branch.filter(
    (e) =>
      e.customType === "perk:workflow-state" &&
      (e.data as { review_posts?: unknown })?.review_posts !== undefined,
  );
  assert.equal(entries.length, 2, "one ledger append per real success");
  const rows = reviewPostsOf((entries[1]?.data as { review_posts?: unknown })?.review_posts);
  // Read-rebuild-append: the second write carries the full ordered history — the resume
  // reader sees every confirmed post and skips them, never replaying one.
  assert.deepEqual(
    rows.map((r) => r.pr),
    [41, 42],
  );
  assert.ok(rows.every((r) => r.event === "comment" && typeof r.at === "string"));
});

test("submitPrReview: the enforced resume guard — already_posted before exec AND confirm; dry-run and allow_repost pass", async () => {
  const { pi, calls, branch } = fakePi({
    stdout: JSON.stringify({ success: true, event: "comment", mode: "review" }),
  });
  const { ctx, confirms } = fakeCtx({ branch, confirmAnswer: true });
  const first = await submitPrReview(pi, ctx, { pr: 41, event: "comment", body: "first" });
  assert.equal(first.details.ok, true);
  assert.equal(calls.length, 1);

  // A repeat REAL post to the same PR refuses on the ledger row — before the cold-door
  // mutation and before any formal-event confirm dialog.
  const repeat = await submitPrReview(pi, ctx, { pr: 41, event: "approve", body: "again" });
  assert.equal(repeat.details.ok, false);
  if (!repeat.details.ok) assert.equal(repeat.details.error_type, "already_posted");
  assert.equal(calls.length, 1, "the guard refuses BEFORE the cold-door mutation");
  assert.equal(confirms.length, 0, "the guard refuses BEFORE the confirm dialog");

  // The repair loop is never blocked: a dry-run against the same PR still validates.
  const dry = await submitPrReview(pi, ctx, {
    pr: 41,
    event: "comment",
    body: "again",
    dry_run: true,
  });
  assert.equal(dry.details.ok, true);
  assert.equal(calls.length, 2);

  // The deliberate escape hatch: allow_repost posts a second review to the same PR.
  const deliberate = await submitPrReview(pi, ctx, {
    pr: 41,
    event: "comment",
    body: "again",
    allow_repost: true,
  });
  assert.equal(deliberate.details.ok, true);
  assert.equal(calls.length, 3);
  // Another PR was never blocked.
  const other = await submitPrReview(pi, ctx, { pr: 42, event: "comment", body: "upper" });
  assert.equal(other.details.ok, true);
});

test("submitPrReview: a dry-run and a failed submission never touch review_posts", async () => {
  const dry = fakePi({ stdout: JSON.stringify({ success: true, dry_run: true, pr: 41 }) });
  const dryCtx = fakeCtx({ branch: dry.branch });
  await submitPrReview(dry.pi, dryCtx.ctx, { pr: 41, event: "comment", body: "x", dry_run: true });
  assert.equal(dry.branch.length, 0, "no workflow-state writes on a dry run");

  const failed = fakePi({
    stdout: JSON.stringify({ success: false, error_type: "bad_batch", message: "nope" }),
    code: 1,
  });
  const failedCtx = fakeCtx({ branch: failed.branch });
  await submitPrReview(failed.pi, failedCtx.ctx, { pr: 41, event: "comment", body: "x" });
  assert.equal(failed.branch.length, 0, "no ledger row for a failed post");
});

test("reviewPostsOf: tolerant re-narrow — malformed rows drop, order preserved", () => {
  assert.deepEqual(reviewPostsOf(undefined), []);
  assert.deepEqual(reviewPostsOf("junk"), []);
  const rows = reviewPostsOf([
    { pr: 41, event: "comment", at: "t1" },
    { pr: "42", event: "comment", at: "t2" }, // malformed: dropped
    { pr: 43, event: "request-changes", at: "t3" },
  ]);
  assert.deepEqual(rows, [
    { pr: 41, event: "comment", at: "t1" },
    { pr: 43, event: "request-changes", at: "t3" },
  ]);
});

// --- submit_pr_review: end-to-end through the harness (offline fake perk) ----------------------

test("tool: a comment submission succeeds, records last_review, and reports the count", async () => {
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
