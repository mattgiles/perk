// Tests for the warm `/commit-and-compact` door: the pure guidance/instruction helpers, the
// extracted start/settle core over recorder `CommitCompactIo` fakes + real scratch repos, and one
// spy-injected end-to-end pass through the registered command (the dirty/drive arm). The settle
// path is covered via the extracted core — the harness cannot fire `agent_settled`.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { headSha } from "../substrate/git.ts";
import { gitInit, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import {
  type CommitCompactIo,
  commitAndCompactGuidance,
  compactInstructions,
  DIRECT_COMPACT_INSTRUCTIONS,
  type PendingCompact,
  settleCommitAndCompact,
  startCommitAndCompact,
} from "./commitCompact.ts";

/** A recorder `CommitCompactIo`: every side effect captured, nothing performed. */
function recorderIo(): CommitCompactIo & {
  reports: { severity: string; message: string }[];
  sends: string[];
  compacts: string[];
} {
  const reports: { severity: string; message: string }[] = [];
  const sends: string[] = [];
  const compacts: string[] = [];
  return {
    reports,
    sends,
    compacts,
    report: (severity, message) => {
      reports.push({ severity, message });
    },
    send: (guidance) => {
      sends.push(guidance);
    },
    compact: (customInstructions) => {
      compacts.push(customInstructions);
    },
  };
}

/** Commit everything in a scratch repo (the settle-arm "the model committed" simulation). */
function commitAll(cwd: string, subject: string): void {
  const g = (...args: string[]) => execFileSync("git", args, { cwd, stdio: "ignore" });
  g("add", "-A");
  g("commit", "-qm", subject);
}

// --- pure guidance / instruction pins -----------------------------------------------------------

test("commitAndCompactGuidance: drives a commit, forbids pushing, hardcodes no skill pointer", () => {
  const text = commitAndCompactGuidance();
  assert.ok(text.includes("Commit the work completed so far"), "the guidance opens on the commit");
  assert.ok(text.includes("Do NOT push"), "pushing is out of scope for the driven turn");
  assert.ok(!text.includes(".agents/skills"), "skill pointers ride bindingSuffix, never inline");
});

test("compactInstructions: embeds the --oneline listing; the null arm stays explicit", () => {
  const withCommits = compactInstructions("abc1234 add the feature\ndef5678 fix the test");
  assert.ok(withCommits.includes("abc1234 add the feature"));
  assert.ok(withCommits.includes("def5678 fix the test"));
  assert.ok(withCommits.includes("was just committed"));
  const withoutCommits = compactInstructions(null);
  assert.ok(withoutCommits.includes("(commit list unavailable)"));
});

// --- startCommitAndCompact core arms ------------------------------------------------------------

test("start: read-only gate → immediate compact with the direct instructions, no drive", () => {
  const io = recorderIo();
  const pending = startCommitAndCompact(scaffoldRepo(), true, io);
  assert.equal(pending, null);
  assert.deepEqual(io.compacts, [DIRECT_COMPACT_INSTRUCTIONS]);
  assert.deepEqual(io.sends, []);
  assert.ok(io.reports.some((r) => r.severity === "info" && r.message.includes("read-only")));
});

test("start: clean worktree → immediate compact with the direct instructions, no drive", () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  const io = recorderIo();
  const pending = startCommitAndCompact(cwd, false, io);
  assert.equal(pending, null);
  assert.deepEqual(io.compacts, [DIRECT_COMPACT_INSTRUCTIONS]);
  assert.deepEqual(io.sends, []);
  assert.ok(io.reports.some((r) => r.severity === "info" && r.message.includes("worktree clean")));
});

test("start: dirty worktree → drive the commit turn, capture headBefore, no compact yet", () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: true });
  const io = recorderIo();
  const pending = startCommitAndCompact(cwd, false, io);
  assert.deepEqual(pending, { cwd, headBefore: headSha(cwd) });
  assert.equal(io.sends.length, 1);
  assert.ok(io.sends[0]?.includes("Commit the work completed so far"));
  assert.deepEqual(io.compacts, []);
  assert.ok(io.reports.some((r) => r.severity === "info" && r.message.includes("driving")));
});

test("start: undeterminable git state → warn and skip (fail-safe: no compact, no drive)", () => {
  const io = recorderIo();
  const pending = startCommitAndCompact(scaffoldRepo(), false, io);
  assert.equal(pending, null);
  assert.deepEqual(io.sends, []);
  assert.deepEqual(io.compacts, []);
  const warning = io.reports.find((r) => r.severity === "warning");
  assert.ok(warning !== undefined, "the undeterminable arm must warn");
  assert.ok(warning.message.includes("compaction skipped"));
  assert.ok(warning.message.includes("/compact"), "the skip names pi's /compact escape hatch");
});

// --- settleCommitAndCompact core arms -----------------------------------------------------------

test("settle: HEAD unchanged → warn and skip compaction (never compact away uncommitted work)", () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: true });
  const pending: PendingCompact = { cwd, headBefore: headSha(cwd) };
  const io = recorderIo();
  settleCommitAndCompact(pending, io);
  assert.deepEqual(io.compacts, []);
  const warning = io.reports.find((r) => r.severity === "warning");
  assert.ok(warning !== undefined, "the no-commit arm must warn");
  assert.ok(warning.message.includes("no commit was made"));
  assert.ok(warning.message.includes("/compact"), "the skip names pi's /compact escape hatch");
});

test("settle: HEAD advanced → compact with instructions naming the new commit", () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: true });
  const pending: PendingCompact = { cwd, headBefore: headSha(cwd) };
  commitAll(cwd, "the driven commit");
  const io = recorderIo();
  settleCommitAndCompact(pending, io);
  assert.equal(io.compacts.length, 1);
  assert.ok(io.compacts[0]?.includes("the driven commit"), "instructions embed the new subject");
  assert.ok(io.reports.some((r) => r.severity === "info" && r.message.includes("committed")));
});

// --- registration + end-to-end (the dirty/drive arm through the registered command) -------------

test("registration smoke: /commit-and-compact registers in a headless-safe load", async () => {
  const h = await loadPerkSession({ cwd: scaffoldRepo() });
  try {
    assert.ok(h.registeredCommands().includes("commit-and-compact"));
  } finally {
    h.dispose();
  }
});

test("/commit-and-compact (dirty) injects the driving guidance", async () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: true });
  writeFileSync(join(cwd, "work-in-progress.txt"), "wip\n", "utf8");
  const h = await loadPerkSession({ cwd });
  const seen = spyInjections(h); // mandatory: the handler seeds a turn the keyless harness can't run
  try {
    await h.invokeCommand("commit-and-compact");
    const msg = seen.join("\n");
    assert.ok(msg.includes("Commit the work completed so far"), "the template opening line lands");
    assert.ok(
      h.notifies.some((n) => n.includes("driving a commit of the work completed so far")),
      "the dirty-arm report reaches the UI",
    );
  } finally {
    h.dispose();
  }
});
