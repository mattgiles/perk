// Tests for the warm `/pr-review-terminal` door. The pure `parseReviewDoorArgs` +
// `prReviewTerminalGuidance` are pinned directly; the command's entry gates / checkout /
// active-PR resolution / injection run against a REAL bound session via the T1 harness, OFFLINE
// (a fake `perk` stands in for the cold doors, a fake `hunk` on PATH stands in for the review
// CLI, and the active/local arms run inside a scratch git repo whose `origin/*` refs are planted
// locally — the best-effort fetch fails offline, exercising the stale-ref arm naturally).
//
// What only a live run validates:
// - terminal launch + clipboard are disabled here (`PERK_TERMINAL_LAUNCH=""`,
//   `PERK_CLIPBOARD_CMD=""`) — the real macOS launch rungs (Ghostty/iTerm2/Terminal.app, TCC
//   dialogs), clipboard utilities, the soft-deadline race, and the background follow-up note
//   never execute;
// - `sinceBaseSha`'s fetch-TIMEOUT arm is structurally unreachable offline — the scaffold has no
//   remote so `git fetch origin` fails immediately, a different path from a real network hang
//   bounded by the 15s timeout falling back to the stale ref;
// - both cold-door integrations are faked (canned JSON) — real GitHub error shapes are
//   unexercised;
// - the template guidance is render-parity-tested only — whether the model follows the arms'
//   flows is behaviorally unvalidated.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { writePlanRef } from "../substrate/cache.ts";
import { REPORT_DETAIL_TYPE } from "../surfaces/surfaces.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import { parseReviewDoorArgs, prReviewTerminalGuidance } from "./prReviewTerminal.ts";

// --- parseReviewDoorArgs -----------------------------------------------------------------

test("parseReviewDoorArgs: empty/whitespace → active mode, no focus", () => {
  assert.deepEqual(parseReviewDoorArgs(""), { mode: "active", directive: "" });
  assert.deepEqual(parseReviewDoorArgs("   "), { mode: "active", directive: "" });
});

test("parseReviewDoorArgs: a PR number/URL (+ directive) → foreign mode", () => {
  assert.deepEqual(parseReviewDoorArgs("123"), { mode: "foreign", pr: 123, directive: "" });
  assert.deepEqual(parseReviewDoorArgs("https://github.com/o/r/pull/45"), {
    mode: "foreign",
    pr: 45,
    directive: "",
  });
  assert.deepEqual(parseReviewDoorArgs("123 dig into the CI changes"), {
    mode: "foreign",
    pr: 123,
    directive: "dig into the CI changes",
  });
});

test("parseReviewDoorArgs: plain text → active mode with the text as the focus note", () => {
  assert.deepEqual(parseReviewDoorArgs("focus on the CI changes"), {
    mode: "active",
    directive: "focus on the CI changes",
  });
});

test("parseReviewDoorArgs: a non-PR http(s) URL → null (never a silent focus note)", () => {
  assert.equal(parseReviewDoorArgs("https://github.com/o/r/issues/45"), null);
  assert.equal(parseReviewDoorArgs("http://github.com/o/r/issues/45 focus"), null);
});

// --- prReviewTerminalGuidance ------------------------------------------------------------------

const FOREIGN_OPTS = {
  mode: "foreign" as const,
  pr: 148,
  worktree: "/wt/review-148",
  baseSha: "0f8a1b2c3d4e",
};

const ACTIVE_OPTS = {
  mode: "active" as const,
  pr: 148,
  worktree: "/repo/.worktrees/plan-148",
  baseSha: "0f8a1b2c3d4e",
};

const LOCAL_OPTS = {
  mode: "local" as const,
  worktree: "/repo/.worktrees/plan-148",
  baseSha: "0f8a1b2c3d4e",
};

test("guidance(foreign): FOREIGN framing + cleanup step + the --agent-notes launch line", () => {
  const text = prReviewTerminalGuidance(FOREIGN_OPTS);
  assert.match(text, /FOREIGN PR #148/);
  assert.match(text, /untrusted foreign code/);
  assert.ok(text.includes("cd /wt/review-148 && hunk diff 0f8a1b2c3d4e --agent-notes"));
  assert.match(text, /perk pr review cleanup --pr 148/);
  assert.match(text, /perk\.adversarial-reviewer/);
  assert.match(text, /submit_pr_review/);
  assert.match(text, /dry_run: true/);
});

test("guidance(active): no cleanup, no detached-checkout framing, the authorship check", () => {
  const text = prReviewTerminalGuidance(ACTIVE_OPTS);
  assert.doesNotMatch(text, /review cleanup/);
  assert.doesNotMatch(text, /detached/);
  assert.doesNotMatch(text, /untrusted foreign code/);
  assert.match(text, /ACTIVE worktree/);
  assert.ok(text.includes("`/repo/.worktrees/plan-148`"));
  assert.ok(text.includes("cd /repo/.worktrees/plan-148 && hunk diff 0f8a1b2c3d4e --agent-notes"));
  assert.match(text, /own_pr/); // the own-PR authorship check carries over (the common case here)
  assert.match(text, /perk pr review-context --pr 148/);
  assert.match(text, /perk\.adversarial-reviewer/);
  assert.match(text, /submit_pr_review/);
});

test("guidance(local): surface-only — no reviewers, no posting, the notes read-back", () => {
  const text = prReviewTerminalGuidance(LOCAL_OPTS);
  assert.doesNotMatch(text, /perk\.adversarial-reviewer/);
  assert.doesNotMatch(text, /submit_pr_review/);
  assert.doesNotMatch(text, /async: true/);
  assert.doesNotMatch(text, /wait\(\{ timeoutMs/);
  assert.match(text, /NO reviewers were spawned/);
  assert.match(text, /including no automatic Ponytail lane/);
  assert.match(text, /NOTHING posts to GitHub/);
  assert.ok(text.includes("cd /repo/.worktrees/plan-148 && hunk diff 0f8a1b2c3d4e --agent-notes"));
  assert.match(text, /hunk session comment list --repo \/repo\/\.worktrees\/plan-148 --type user/);
  assert.match(text, /never poll on a timer/);
});

test("guidance: the directive arm renders/omits on foreign and active — no model arm exists", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const withDirective = prReviewTerminalGuidance({ ...opts, directive: "dig into CI" });
    assert.match(withDirective, /Operator focus for this run/);
    assert.match(withDirective, /dig into CI/);
    assert.match(withDirective, /claimed-intent stays mandatory/);
    assert.match(withDirective, /verbatim as the `directive` param/);
    const bare = prReviewTerminalGuidance(opts);
    assert.doesNotMatch(bare, /Operator focus for this run/);
    // Model resolution moved into start_review_wave — no model plumbing in any arm.
    for (const text of [withDirective, bare]) {
      assert.doesNotMatch(text, /model: "/);
      assert.doesNotMatch(text, /\[models\.subagents\]/);
    }
  }
});

test("guidance(foreign+active): the tool-owned streaming-loop pins (hunk mechanics retained)", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const text = prReviewTerminalGuidance(opts);
    assert.match(text, /start_review_wave/, "the fan-out is the launch tool");
    assert.match(text, /collect_review_wave/, "completion rides the collect tool");
    assert.match(
      text,
      /subagent_wait\(\{ timeoutMs: 30000 \}\)/,
      "the wait loop is the streaming cadence",
    );
    assert.match(text, /Subagent progress update/, "progress-update batches are processed");
    // Hunk sink mechanics are unchanged.
    assert.match(text, /hunk session get --repo/, "the handshake check stays");
    assert.match(text, /hunk session comment apply --repo/, "the comment-apply push stays");
    assert.match(text, /never re-push an anchor already pushed/, "incremental path+line dedupe");
    assert.match(text, /\{complete, covered, reports, failures\}/, "the typed aggregate");
    assert.match(text, /wave_running/, "the collect grace arm is named");
    assert.match(
      text,
      /completion reports are the \*\*source of truth\*\*/,
      "completion reports drive triage/posting",
    );
    assert.match(text, /never receive the surface handle/, "children get no hunk session details");
    assert.match(text, /reported honestly/, "incompleteness is surfaced, never papered over");
    assert.match(
      text,
      /Exactly one source-bound `ponytail` lane is required automatic coverage and appended last/,
    );
    assert.match(text, /outside the 2–3 selection cap/);
    assert.match(text, /MUST NOT be selected or duplicated/);
    assert.match(text, /does not spawn or fall back/);
    assert.match(text, /`skill-unavailable`/);
    // The retired model-authored mechanics are gone.
    for (const gone of [/workflowScript/, /runs\.all/, /status\.json/, /subagent\(\{\s*action/]) {
      assert.doesNotMatch(text, gone, `retired mechanics must not appear: ${gone}`);
    }
  }
});

test("guidance: no hardcoded perk-pr-review-terminal skill pointer in any arm (binding suffix)", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS, LOCAL_OPTS] as const) {
    assert.doesNotMatch(
      prReviewTerminalGuidance(opts),
      /Follow the `perk-pr-review-terminal` skill/,
    );
  }
});

// --- the command flow through the harness ------------------------------------------------------

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
function fakeHunk(cwd: string, opts?: { code?: number }): string {
  const dir = join(cwd, "fakebin");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "hunk");
  writeFileSync(path, `#!/usr/bin/env bash\necho hunk 0.0.0\nexit ${opts?.code ?? 0}\n`, "utf8");
  chmodSync(path, 0o755);
  return dir;
}

/** The path-carrying nudge pointer line the binding suffix delivers for `skill`. */
function pointer(skill: string): string {
  return `Follow the \`${skill}\` skill (read \`.agents/skills/${skill}/SKILL.md\`).`;
}

/**
 * `git init` the scaffold with two commits and locally-planted `origin/main` + `origin/HEAD`
 * refs at the FIRST commit (the merge-base the active/local arms resolve). No real remote —
 * `sinceBaseSha`'s best-effort fetch fails offline and the planted (stale) ref is used.
 */
function gitScaffold(cwd: string): { baseSha: string } {
  const g = (...args: string[]): string =>
    execFileSync("git", args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  writeFileSync(
    join(cwd, ".gitignore"),
    "/.perk/workflow/\n*.jsonl\nfake-perk.sh\nfakebin/\nargv.txt\n",
    "utf8",
  );
  writeFileSync(join(cwd, "seed.txt"), "seed\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "base");
  const baseSha = g("rev-parse", "HEAD");
  g("update-ref", "refs/remotes/origin/main", baseSha);
  g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main");
  writeFileSync(join(cwd, "work.txt"), "work\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "work");
  return { baseSha };
}

/** Plant the plan-ref the active arm reads its pinned base from (`base: null` ⇒ repo default). */
function plantPlanRef(cwd: string): void {
  writePlanRef(cwd, {
    provider: "github",
    pr_id: "42",
    url: "https://github.com/o/r/issues/42",
    labels: [],
    objective_id: null,
    base: null,
  });
}

const PR_URL_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://github.com/o/r/pull/42" },
});

test("/pr-review-terminal: registers; an unparseable PR URL reports usage, no work", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    assert.ok(h.registeredCommands().includes("pr-review-terminal"), "the command is registered");
    await h.runCommandHandler("pr-review-terminal", "https://github.com/o/r/issues/45");
    assert.ok(
      h.notifies.some((n) => n.includes("usage: /pr-review-terminal [pr number|url] [focus note]")),
      "usage reported",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal: headless → refusal, nothing executed", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "77");
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal: an absent/failing hunk refuses with the install hint, no cold call", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const hunkDir = fakeHunk(cwd, { code: 1 });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "77");
    assert.ok(
      h.notifies.some((n) => n.includes("npm i -g hunkdiff (or brew install hunk)")),
      "the install hint is reported",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal <pr>: foreign success injects ONE guidance with the worktree, the --agent-notes launch, and ONE pointer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "77");
    assert.ok(
      h.notifies.some((n) =>
        n.includes("PR #77 → adversarial reviewers → hunk triage → curated post"),
      ),
      "the info line names the flow",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /FOREIGN PR #77/);
    assert.ok(text.includes("`/wt/review-77`"), "the worktree path threads through");
    assert.ok(
      text.includes("cd /wt/review-77 && hunk diff 0123456789ab --agent-notes"),
      "the launch line carries the 12-char sha + --agent-notes",
    );
    assert.ok(!text.includes("0123456789abcdef"), "the full base sha never reaches the guidance");
    const marker = pointer("perk-pr-review-terminal");
    assert.equal(
      text.split(marker).length - 1,
      1,
      "exactly one command:pr-review-terminal pointer",
    );
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal <pr>: a checkout failure (pr_not_found) is surfaced, nothing injected", async () => {
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
    await h.runCommandHandler("pr-review-terminal", "999");
    assert.ok(
      h.notifies.some((n) => n.includes("pr_not_found") && n.includes("PR #999 not found")),
      "the envelope failure is surfaced",
    );
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal (no arg): a resolved PR injects the ACTIVE guidance homed at ctx.cwd", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const { baseSha } = gitScaffold(cwd);
  plantPlanRef(cwd);
  const bin = fakePerk(cwd, { stdout: PR_URL_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "");
    assert.ok(
      h.notifies.some((n) =>
        n.includes("PR #42 (active worktree) → adversarial reviewers → hunk triage → curated post"),
      ),
      "the info line names the active-worktree flow",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /ACTIVE worktree/);
    assert.ok(text.includes(`\`${cwd}\``), "ctx.cwd is the worktree");
    assert.ok(
      text.includes(`cd ${cwd} && hunk diff ${baseSha.slice(0, 12)} --agent-notes`),
      "the launch line carries the since-base merge-base + --agent-notes",
    );
    assert.doesNotMatch(text, /review cleanup/);
    const marker = pointer("perk-pr-review-terminal");
    assert.equal(text.split(marker).length - 1, 1, "exactly one pointer");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal (no arg): a focus note threads into the active guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  gitScaffold(cwd);
  plantPlanRef(cwd);
  const bin = fakePerk(cwd, { stdout: PR_URL_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "dig into the CI changes");
    const text = injected[0] ?? "";
    assert.match(text, /Operator focus for this run/);
    assert.match(text, /dig into the CI changes/);
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal (no arg, no PR yet): the reviewers-skipped note + the LOCAL guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const { baseSha } = gitScaffold(cwd);
  plantPlanRef(cwd);
  const noPr = JSON.stringify({ success: false, error_type: "no_pr", message: "No PR found" });
  const bin = fakePerk(cwd, { stdout: noPr, code: 1 });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "");
    assert.ok(
      h.notifies.some((n) =>
        n.includes("no PR yet — since-base review in hunk; reviewers skipped (no PR to review)"),
      ),
      "the reviewers-skipped note is reported",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /NO reviewers were spawned/);
    assert.doesNotMatch(text, /perk\.adversarial-reviewer/);
    assert.ok(text.includes(`cd ${cwd} && hunk diff ${baseSha.slice(0, 12)} --agent-notes`));
    const marker = pointer("perk-pr-review-terminal");
    assert.equal(text.split(marker).length - 1, 1, "exactly one pointer");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal (no arg): a no_plan_ref fail arm reports the pass-a-PR hint, nothing injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  gitScaffold(cwd);
  const noPlanRef = JSON.stringify({
    success: false,
    error_type: "no_plan_ref",
    message: "no plan-ref in this worktree",
  });
  const bin = fakePerk(cwd, { stdout: noPlanRef, code: 1 });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("no plan-ref in this worktree") &&
          n.includes("pass a PR number/URL, or run from a plan worktree"),
      ),
      "the fail arm appends the hint",
    );
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal (no arg): an unresolvable merge-base errors loudly, nothing launched/injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // A repo WITHOUT origin/main or origin/HEAD: sinceBaseSha resolves null.
  const g = (...args: string[]) => execFileSync("git", args, { cwd, stdio: "ignore" });
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  writeFileSync(join(cwd, "seed.txt"), "seed\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "base");
  plantPlanRef(cwd);
  const bin = fakePerk(cwd, { stdout: PR_URL_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "");
    assert.ok(
      h.notifies.some((n) =>
        n.includes("could not resolve the since-base merge-base — pass a PR number/URL instead"),
      ),
      "the merge-base failure is loud",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.ok(!h.notifyEvents.some((e) => e.message.includes("ACTION NEEDED")), "nothing launched");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal: the R7 headline keeps the verbatim launch line in report detail", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "77");
    const launchLine = "cd /wt/review-77 && hunk diff 0123456789ab --agent-notes";
    const warn = h.notifyEvents.find((e) => e.message.includes("ACTION NEEDED"));
    assert.ok(warn, "the manual-action notify fired (harness seams disabled)");
    assert.equal(warn?.severity, "warning");
    assert.equal(
      warn?.message,
      "perk: pr-review-terminal — ACTION NEEDED — run hunk in another terminal:",
    );
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: { text?: string; severity?: string };
    }[];
    const detail = entries.find(
      (entry) =>
        entry.customType === REPORT_DETAIL_TYPE && entry.data?.text?.includes("ACTION NEEDED"),
    );
    assert.equal(detail?.data?.severity, "warning");
    assert.ok(detail?.data?.text?.includes(`\n  ${launchLine}`), "detail keeps the launch line");
    assert.equal(injected.length, 1, "the guidance injection still follows (non-blocking)");
  } finally {
    h.dispose();
  }
});

test("/pr-review-terminal <pr>: a configured reviewer model never reaches the guidance (tool-resolved)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nadversarial-reviewer = "test/model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const hunkDir = fakeHunk(cwd);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PATH: `${hunkDir}:${process.env.PATH ?? ""}` },
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-terminal", "77 dig into the CI changes");
    const text = injected[0] ?? "";
    // Model resolution lives in start_review_wave now — the door reads no config and the
    // guidance carries no model plumbing.
    assert.doesNotMatch(text, /test\/model/);
    assert.doesNotMatch(text, /model: "/);
    assert.match(text, /Operator focus for this run/);
    assert.match(text, /dig into the CI changes/);
    assert.ok(
      h.notifies.some((n) => n.includes("(focus: dig into the CI changes)")),
      "the info line carries the focus",
    );
  } finally {
    h.dispose();
  }
});
