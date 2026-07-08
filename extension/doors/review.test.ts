// Tests for the warm `/review` door. The pure `parseReviewArgs` + `reviewGuidance` +
// `decodeSubmitParams` are pinned directly; the command's provider dispatch / refuse-at-start /
// checkout / injection and the `submit_pr_review` delegation + outcomes run against a REAL bound
// session via the T1 harness, OFFLINE (a fake `perk` stands in for the cold doors and a fake
// `hunk` on PATH stands in for the review CLI — no LLM / network / gh / Python). The formal-event
// confirm gate is exercised through the exported `submitPrReview` core with structural fakes
// (the coldDoor.test.ts idiom) because the harness UI context carries no `confirm`.

import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExecResult, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ExecHost } from "../substrate/coldDoor.ts";
import type { BranchEntry, EntrySink } from "../substrate/workflowState.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import {
  decodeSubmitParams,
  HUNK_INSTALL_HINT,
  parseReviewArgs,
  reviewGuidance,
  type SubmitCtx,
  submitPrReview,
} from "./review.ts";

// --- compile-time satisfaction: the structural ctx slice can never drift from the SDK --------

const _c: SubmitCtx = {} as ExtensionContext;
void _c;

// --- parseReviewArgs --------------------------------------------------------------------------

test("parseReviewArgs: a bare PR number", () => {
  assert.deepEqual(parseReviewArgs("123"), { pr: 123, directive: "" });
  assert.deepEqual(parseReviewArgs("  123  "), { pr: 123, directive: "" });
});

test("parseReviewArgs: a GitHub PR URL (plain, trailing slash, query, fragment, subpath)", () => {
  const expected = { pr: 45, directive: "" };
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/45"), expected);
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/45/"), expected);
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/45?diff=split"), expected);
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/45#discussion_r1"), expected);
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/45/files"), expected);
});

test("parseReviewArgs: number + free-form directive", () => {
  assert.deepEqual(parseReviewArgs("123 have one reviewer dig into the CI changes"), {
    pr: 123,
    directive: "have one reviewer dig into the CI changes",
  });
  assert.deepEqual(parseReviewArgs("https://github.com/o/r/pull/9 check the deps"), {
    pr: 9,
    directive: "check the deps",
  });
});

test("parseReviewArgs: garbage/missing → null", () => {
  assert.equal(parseReviewArgs(""), null);
  assert.equal(parseReviewArgs("   "), null);
  assert.equal(parseReviewArgs("nope"), null);
  assert.equal(parseReviewArgs("https://github.com/o/r/issues/45"), null);
  assert.equal(parseReviewArgs("-3"), null);
  assert.equal(parseReviewArgs("focus on CI 123"), null);
});

// --- reviewGuidance ---------------------------------------------------------------------------

const GUIDANCE_OPTS = {
  arm: "hunk" as const,
  pr: 148,
  worktree: "/wt/review-148",
  baseSha: "0f8a1b2c3d4e5f60718293a4b5c6d7e8f9012345",
};

test("reviewGuidance carries the worktree path, the launch command, and the PR number", () => {
  const text = reviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /FOREIGN PR #148/);
  assert.ok(text.includes("`/wt/review-148`"));
  assert.ok(
    text.includes("cd /wt/review-148 && hunk diff 0f8a1b2c3d4e5f60718293a4b5c6d7e8f9012345"),
  );
  assert.match(text, /perk pr review cleanup --pr 148/);
});

test("reviewGuidance spawns 2–3 perk.guest-reviewer children with claimed-intent mandatory", () => {
  const text = reviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /perk\.guest-reviewer/);
  assert.match(text, /context: "fresh"/);
  assert.match(text, /2.3/); // "2–3" children in parallel
  assert.match(text, /ALWAYS include the \*\*claimed-intent\*\*/);
  assert.match(text, /Never fetch `perk pr review-context` yourself/);
});

test("reviewGuidance pins the posting flow through submit_pr_review with dry_run first", () => {
  const text = reviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /submit_pr_review/);
  assert.match(text, /dry_run: true/);
  assert.match(text, /only on the human's explicit go-ahead/);
  assert.match(text, /never use `gh`/);
});

test("reviewGuidance injects the configured model when set and not otherwise", () => {
  const withModel = reviewGuidance({ ...GUIDANCE_OPTS, model: "anthropic/claude-opus-4" });
  assert.match(withModel, /model: "anthropic\/claude-opus-4"/);
  assert.match(withModel, /\[models\.subagents\] guest-reviewer model/);
  const without = reviewGuidance(GUIDANCE_OPTS);
  assert.doesNotMatch(without, /model: "/);
  assert.match(without, /default model/);
});

test("reviewGuidance injects the operator directive when set (within the invariants)", () => {
  const text = reviewGuidance({ ...GUIDANCE_OPTS, directive: "dig into the CI changes" });
  assert.match(text, /Operator focus for this run/);
  assert.match(text, /dig into the CI changes/);
  assert.match(text, /claimed-intent stays mandatory/);
  assert.doesNotMatch(reviewGuidance(GUIDANCE_OPTS), /Operator focus for this run/);
});

test("reviewGuidance does not hardcode the perk-review skill pointer (binding suffix)", () => {
  assert.doesNotMatch(reviewGuidance(GUIDANCE_OPTS), /Follow the `perk-review` skill/);
});

// --- reviewGuidance: the plannotator arm --------------------------------------------------------

const PLANNOTATOR_OPTS = {
  arm: "plannotator" as const,
  pr: 148,
  worktree: "/wt/review-148",
  baseSha: "0f8a1b2c3d4e5f60718293a4b5c6d7e8f9012345",
  prUrl: "https://github.com/o/r/pull/148",
};

test("reviewGuidance(plannotator) carries the tool call, the pr_url, and no hunk launch command", () => {
  const text = reviewGuidance(PLANNOTATOR_OPTS);
  assert.match(text, /FOREIGN PR #148/);
  assert.match(text, /plannotator surface/);
  assert.ok(text.includes("`/wt/review-148`"));
  assert.ok(
    text.includes(
      '`open_plannotator_review` with `{pr: 148, pr_url: "https://github.com/o/r/pull/148"}`',
    ),
  );
  assert.doesNotMatch(text, /hunk diff/);
  assert.doesNotMatch(text, /hunk session/);
  assert.match(text, /perk pr review cleanup --pr 148/);
});

test("reviewGuidance(plannotator) pins the wave push, cleanup, and read-back disciplines", () => {
  const text = reviewGuidance(PLANNOTATOR_OPTS);
  assert.match(text, /ONE atomic wave/);
  assert.match(text, /source: "perk:<angle>"/);
  assert.match(text, /scope: "file"/);
  assert.match(text, /Never `GET <url>\/api\/diff`/);
  assert.match(text, /DELETE <url>\/api\/external-annotations\?id=<uuid>/);
  assert.match(text, /Never delete the human's annotations/);
  assert.match(text, /Read back \+ dedupe, ALWAYS/);
  assert.match(text, /APPROVE\/COMMENT only/);
  assert.match(text, /submit_pr_review/);
  assert.match(text, /dry_run: true/);
});

test("reviewGuidance(plannotator) threads model and directive like the hunk arm", () => {
  const withModel = reviewGuidance({ ...PLANNOTATOR_OPTS, model: "anthropic/claude-opus-4" });
  assert.match(withModel, /model: "anthropic\/claude-opus-4"/);
  const withDirective = reviewGuidance({ ...PLANNOTATOR_OPTS, directive: "dig into CI" });
  assert.match(withDirective, /Operator focus for this run/);
  assert.match(withDirective, /dig into CI/);
  const bare = reviewGuidance(PLANNOTATOR_OPTS);
  assert.doesNotMatch(bare, /model: "/);
  assert.doesNotMatch(bare, /Operator focus for this run/);
});

test("reviewGuidance(hunk) output is unchanged by the arm split (no plannotator strings)", () => {
  const text = reviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /hunk surface/);
  assert.doesNotMatch(text, /open_plannotator_review/);
  assert.doesNotMatch(text, /external-annotations/);
});

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
    cwd: mkdtempSync(join(tmpdir(), "review-door-test-")),
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

// --- /review: the command flow through the harness ---------------------------------------------

const CHECKOUT_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  path: "/wt/review-77",
  pr: 77,
  url: "https://github.com/o/r/pull/77",
  head_sha: "aaaabbbbccccddddeeeeffff0000111122223333",
  base_sha: "0123456789abcdef0123456789abcdef01234567",
  base_ref: "main",
});

/** Write an executable fake `hunk` into `<cwd>/fakebin` and return that dir (for PATH). */
function fakeHunk(cwd: string, opts?: { code?: number; markerFile?: string }): string {
  const dir = join(cwd, "fakebin");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "hunk");
  const marker = opts?.markerFile ? `touch ${opts.markerFile}\n` : "";
  writeFileSync(
    path,
    `#!/usr/bin/env bash\n${marker}echo hunk 0.0.0\nexit ${opts?.code ?? 0}\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return dir;
}

/** A fake plannotator extension: registers ONLY the `plannotator-review` presence-probe target. */
function fakePlannotatorExtension(pi: ExtensionAPI): void {
  pi.registerCommand("plannotator-review", {
    description: "fake plannotator (test)",
    handler: async () => {},
  });
}

/** The path-carrying nudge pointer line the binding suffix delivers for `skill`. */
function pointer(skill: string): string {
  return `Follow the \`${skill}\` skill (read \`.agents/skills/${skill}/SKILL.md\`).`;
}

function writePerkConfig(cwd: string, body: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), body, "utf8");
}

test("/review: registers and a missing/unparseable arg reports usage, no work", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    assert.ok(h.registeredCommands().includes("review"), "the /review command is registered");
    await h.runCommandHandler("review", "not-a-pr");
    assert.ok(
      h.notifies.some((n) => n.includes("usage: /review <pr number|url> [focus note]")),
      "usage reported",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no checkout attempted");
  } finally {
    h.dispose();
  }
});

test("/review: plannotator selected but the extension absent → refuse, no checkout", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writePerkConfig(cwd, '[providers]\nreview = "plannotator-review"\n');
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("the plannotator extension is not loaded") &&
          n.includes("run `perk init`, then restart pi"),
      ),
      "the absence refusal names the fix",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no checkout attempted");
  } finally {
    h.dispose();
  }
});

test("/review: plannotator selected + present but headless → refuse, no checkout", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writePerkConfig(cwd, '[providers]\nreview = "plannotator-review"\n');
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
    extraExtensions: [fakePlannotatorExtension],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77");
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no checkout attempted");
  } finally {
    h.dispose();
  }
});

test("/review: the plannotator arm runs the checkout, skips the hunk probe, injects the arm guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writePerkConfig(cwd, '[providers]\nreview = "plannotator-review"\n');
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  // A marker-writing fake hunk FIRST on PATH: the plannotator arm must never probe it.
  const hunkMarker = join(cwd, "hunk-probed.txt");
  const hunkDir = fakeHunk(cwd, { markerFile: hunkMarker });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
    extraExtensions: [fakePlannotatorExtension],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77");
    assert.ok(
      h.notifies.some((n) => n.includes("plannotator browser triage")),
      "the info line names the plannotator triage",
    );
    assert.equal(existsSync(hunkMarker), false, "NO hunk --version exec on this arm");
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /FOREIGN PR #77/);
    assert.ok(text.includes("`/wt/review-77`"), "the worktree path threads through");
    assert.ok(
      text.includes(
        '`open_plannotator_review` with `{pr: 77, pr_url: "https://github.com/o/r/pull/77"}`',
      ),
      "the tool call carries the checkout url",
    );
    assert.match(text, /ONE atomic wave/);
    assert.match(text, /Read back \+ dedupe, ALWAYS/);
    assert.doesNotMatch(text, /hunk diff/);
    const marker = pointer("perk-review");
    assert.equal(text.split(marker).length - 1, 1, "exactly one command:review pointer");
  } finally {
    h.dispose();
  }
});

test("/review: the open_plannotator_review tool registers and strict-decodes (bad_input)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    const result = await h.invokeTool("open_plannotator_review", { pr: 77 });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});

test("/review: an absent/failing hunk binary refuses with the install hint (no checkout)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  // The failing fake hunk is FIRST on PATH, shadowing any real install (deterministic; pi.exec
  // never throws on spawn failure — a resolution error resolves code≠0 — so this one arm covers
  // the whole refuse-at-start probe).
  const hunkDir = fakeHunk(cwd, { code: 1 });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77");
    assert.ok(
      h.notifies.some((n) => n.includes(HUNK_INSTALL_HINT)),
      "the install hint is reported",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no checkout attempted");
  } finally {
    h.dispose();
  }
});

test("/review: a checkout failure (pr_not_found) is surfaced and nothing is injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const notFound = JSON.stringify({
    success: false,
    error_type: "pr_not_found",
    message: "PR #999 not found",
  });
  const bin = fakePerk(cwd, { stdout: notFound, code: 1 });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "999");
    assert.ok(
      h.notifies.some((n) => n.includes("pr_not_found") && n.includes("PR #999 not found")),
      "the envelope failure is surfaced",
    );
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/review: success injects the guidance with the worktree, launch command, and ONE binding pointer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77");
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /FOREIGN PR #77/);
    // The launch command carries the SHORT (12-char) base sha — the full form wraps in the
    // TUI and a wrapped paste launches a bare `hunk diff` (the first dogfood's R2).
    assert.ok(text.includes("cd /wt/review-77 && hunk diff 0123456789ab"));
    assert.ok(
      !text.includes("0123456789abcdef"),
      "the full base sha never reaches the guidance",
    );
    assert.doesNotMatch(text, /model: "/); // no [models.subagents] guest-reviewer configured
    assert.doesNotMatch(text, /Operator focus for this run/); // no directive passed
    const marker = pointer("perk-review");
    assert.equal(text.split(marker).length - 1, 1, "exactly one command:review pointer");
  } finally {
    h.dispose();
  }
});

test("/review: the configured guest-reviewer model and the directive thread into the guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writePerkConfig(cwd, '[models.subagents]\nguest-reviewer = "test/model"\n');
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("review", "77 dig into the CI changes");
    const text = injected[0] ?? "";
    assert.match(text, /model: "test\/model"/);
    assert.match(text, /Operator focus for this run/);
    assert.match(text, /dig into the CI changes/);
  } finally {
    h.dispose();
  }
});
