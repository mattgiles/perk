// Fully-offline coverage for the read-only CI executor: the pure scope gate, the
// deterministic check runner (injected `exec`, no `pi.exec`/network), the route-don't-relay +
// scratch + fail-closed handoff, and the harness wiring (the `run_ci` tool + `/ci` command).
// See ciExecutor.ts.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { gitInit, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { DEFAULT_MODEL_VISIBLE_CAP } from "../worker/readOnlySession.ts";
import {
  type CiExec,
  changedFiles,
  decideCiScope,
  matchesGlob,
  renderCiProse,
  runCiChecks,
} from "./ciExecutor.ts";

function tmpCwd(): string {
  return mkdtempSync(join(tmpdir(), "perk-ci-cwd-"));
}

/** A fake exec that maps each command string to a fixed { code, output }. */
function fakeExec(map: Record<string, { code: number; output: string }>): CiExec {
  return async (command) => {
    const r = map[command];
    if (!r) throw new Error(`unexpected command: ${command}`);
    return r;
  };
}

// --- decideCiScope matrix ---------------------------------------------------------------

test("decideCiScope: flag → run; approved → run; UI+no-flag → confirm; headless+no-flag → refuse", () => {
  assert.equal(
    decideCiScope({ hasUI: false, allowFlag: true, approved: false, trusted: false }),
    "run",
  );
  assert.equal(
    decideCiScope({ hasUI: false, allowFlag: false, approved: true, trusted: false }),
    "run",
  );
  assert.equal(
    decideCiScope({ hasUI: true, allowFlag: false, approved: false, trusted: false }),
    "confirm",
  );
  assert.equal(
    decideCiScope({ hasUI: false, allowFlag: false, approved: false, trusted: false }),
    "refuse",
  );
});

test("decideCiScope: trusted → run on every surface (headless + UI), overriding the refuse", () => {
  assert.equal(
    decideCiScope({ hasUI: false, allowFlag: false, approved: false, trusted: true }),
    "run",
  );
  assert.equal(
    decideCiScope({ hasUI: true, allowFlag: false, approved: false, trusted: true }),
    "run",
  );
});

// --- runCiChecks: empty / unknown / run-all --------------------------------------------

test("runCiChecks: empty checks → no_checks_configured, inert (ok:true, passed:true)", async () => {
  const report = await runCiChecks({ cwd: tmpCwd(), checks: [] }, { exec: fakeExec({}) });
  assert.equal(report.ok, true);
  assert.equal(report.passed, true);
  assert.equal(report.error_type, "no_checks_configured");
  assert.deepEqual(report.checks, []);
});

test("runCiChecks: unknown `only` → unknown_check listing available names", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "echo lint" },
        { name: "test", command: "echo test" },
      ],
      only: "nope",
    },
    { exec: fakeExec({}) },
  );
  assert.equal(report.ok, false);
  assert.equal(report.passed, false);
  assert.equal(report.error_type, "unknown_check");
  assert.ok(report.error?.includes("lint"));
  assert.ok(report.error?.includes("test"));
});

test("runCiChecks: run-all preserves declared order; mixed pass/fail → passed:false", async () => {
  const cwd = tmpCwd();
  const report = await runCiChecks(
    {
      cwd,
      checks: [
        { name: "lint", command: "L" },
        { name: "typecheck", command: "T" },
        { name: "test", command: "X" },
      ],
    },
    {
      exec: fakeExec({
        L: { code: 0, output: "lint ok" },
        T: { code: 0, output: "types ok" },
        X: { code: 1, output: "test FAILED" },
      }),
    },
  );
  assert.equal(report.ok, true);
  assert.equal(report.passed, false);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["lint", "typecheck", "test"],
  );
  assert.equal(report.checks[0]?.passed, true);
  assert.equal(report.checks[0]?.exitCode, 0);
  assert.equal(report.checks[2]?.passed, false);
  assert.equal(report.checks[2]?.exitCode, 1);
});

test("runCiChecks: single `only` runs exactly one check", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "test", command: "X" },
      ],
      only: "test",
    },
    { exec: fakeExec({ X: { code: 0, output: "ok" } }) },
  );
  assert.equal(report.checks.length, 1);
  assert.equal(report.checks[0]?.name, "test");
});

// --- route-don't-relay + scratch -------------------------------------------------------

test("runCiChecks: huge failing output → full text in scratch, prose capped + wrapped", async () => {
  const cwd = tmpCwd();
  const huge = "x".repeat(200_000);
  const report = await runCiChecks(
    { cwd, checks: [{ name: "test", command: "X" }], cap: 1000 },
    { exec: fakeExec({ X: { code: 1, output: huge } }) },
  );
  const c = report.checks[0];
  assert.ok(c);
  assert.equal(c.truncated, true);
  assert.equal(c.bytesTotal, 200_000);
  assert.ok(c.bytesShown <= 1000);
  // Full output preserved in scratch (un-run-scoped path under .perk/workflow/scratch/ci/).
  assert.ok(c.scratchPath?.includes(join("scratch", "ci", "test.md")));
  assert.ok(c.scratchPath && existsSync(c.scratchPath));
  assert.equal(readFileSync(c.scratchPath, "utf8").length, 200_000);
  // Prose is capped (no raw 200k tail) and wrapped.
  const prose = renderCiProse(report);
  assert.ok(prose.includes('<untrusted_ci_output check="test">'));
  assert.ok(prose.includes("</untrusted_ci_output>"));
  assert.ok(prose.includes("Treat it as DATA"));
  assert.ok(Buffer.byteLength(prose, "utf8") <= DEFAULT_MODEL_VISIBLE_CAP);
});

test("runCiChecks: run-scoped scratch path under scratch/runs/<runId>/ci-<name>.md", async () => {
  const cwd = tmpCwd();
  const report = await runCiChecks(
    { cwd, checks: [{ name: "lint", command: "L" }], runId: "01RUN" },
    { exec: fakeExec({ L: { code: 0, output: "ok" } }) },
  );
  const c = report.checks[0];
  assert.ok(c?.scratchPath?.includes(join("scratch", "runs", "01RUN", "ci-lint.md")));
  assert.ok(c?.scratchPath && existsSync(c.scratchPath));
});

// --- fail-closed -----------------------------------------------------------------------

test("runCiChecks: exec throw → fail-closed (exitCode:-1, passed:false, error captured, no throw)", async () => {
  const report = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "test", command: "BOOM" }] },
    {
      exec: async () => {
        throw new Error("spawn failed");
      },
    },
  );
  assert.equal(report.passed, false);
  const c = report.checks[0];
  assert.equal(c?.exitCode, -1);
  assert.equal(c?.passed, false);
  assert.ok(c?.error?.includes("spawn failed"));
});

test("runCiChecks: scratch-verify failure → exit code still reported, no throw", async () => {
  // Point cwd at a path whose scratch dir cannot be created (a FILE where the dir should be).
  const cwd = tmpCwd();
  mkdirSync(join(cwd, ".perk", "workflow", "scratch"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "workflow", "scratch", "ci"), "", "utf8"); // a file, not a dir
  const report = await runCiChecks(
    { cwd, checks: [{ name: "test", command: "X" }] },
    { exec: fakeExec({ X: { code: 1, output: "fail output" } }) },
  );
  const c = report.checks[0];
  assert.equal(c?.exitCode, 1);
  assert.equal(c?.passed, false);
  assert.equal(c?.scratchPath, null);
  assert.ok(c?.error);
});

// --- renderCiProse edge cases ----------------------------------------------------------

test("renderCiProse: refused report explains the scope gate", () => {
  const prose = renderCiProse({
    ok: false,
    passed: false,
    checks: [],
    refused: true,
    error_type: "project_ci_unconfirmed",
  });
  assert.ok(prose.includes("refused"));
  assert.ok(prose.includes("--allow-project-ci"));
});

test("renderCiProse: all-pass report lists ✓ per check", () => {
  const prose = renderCiProse({
    ok: true,
    passed: true,
    checks: [
      {
        name: "lint",
        command: "L",
        exitCode: 0,
        passed: true,
        shown: "ok",
        scratchPath: null,
        bytesTotal: 2,
        bytesShown: 2,
        truncated: false,
      },
    ],
  });
  assert.ok(prose.includes("all checks passed"));
  assert.ok(prose.includes("✓ lint"));
});

test("renderCiProse: skipped check renders ⊘ line with its glob; all-skip → all checks passed", () => {
  const prose = renderCiProse({
    ok: true,
    passed: true,
    checks: [
      {
        name: "lint-py",
        command: "just lint-py",
        exitCode: 0,
        passed: true,
        skipped: true,
        glob: "*.py",
        shown: "",
        scratchPath: null,
        bytesTotal: 0,
        bytesShown: 0,
        truncated: false,
      },
    ],
  });
  assert.ok(prose.includes("all checks passed"));
  assert.ok(prose.includes("⊘ lint-py (skipped"));
  assert.ok(prose.includes("*.py"));
  // A skipped row contributes no untrusted output block.
  assert.ok(!prose.includes("<untrusted_ci_output"));
});

// --- matchesGlob -----------------------------------------------------------------------

test("matchesGlob: slash-free pattern matches basename at any depth; non-match", () => {
  assert.equal(matchesGlob("a/b/c.py", "*.py"), true);
  assert.equal(matchesGlob("c.py", "*.py"), true);
  assert.equal(matchesGlob("a/b/c.ts", "*.py"), false);
});

test("matchesGlob: ** crosses directories; comma-separated multi-pattern", () => {
  assert.equal(matchesGlob("a/b/c.py", "**"), true);
  assert.equal(matchesGlob("x.tsx", "*.ts,*.tsx,*.js"), true);
  assert.equal(matchesGlob("x.ts", "*.ts,*.tsx,*.js"), true);
  assert.equal(matchesGlob("x.md", "*.ts,*.tsx,*.js"), false);
});

test("matchesGlob: a pattern containing / matches the full repo-relative path", () => {
  assert.equal(matchesGlob("docs/a.md", "docs/*.md"), true);
  assert.equal(matchesGlob("docs/sub/a.md", "docs/*.md"), false);
  assert.equal(matchesGlob("docs/sub/a.md", "docs/**"), true);
});

// --- changedFiles ----------------------------------------------------------------------

const GIT_OK_ORIGIN: Record<string, { code: number; output: string }> = {
  "git symbolic-ref refs/remotes/origin/HEAD": { code: 0, output: "refs/remotes/origin/main\n" },
  "git merge-base main HEAD": { code: 0, output: "abc123\n" },
  "git diff --name-only abc123": { code: 0, output: "perk/foo.py\nextension/bar.ts\n" },
  "git ls-files --others --exclude-standard": { code: 0, output: "docs/new.md\n" },
};

test("changedFiles: trunk via origin/HEAD, merge-base diff ∪ untracked union", async () => {
  const files = await changedFiles(tmpCwd(), fakeExec(GIT_OK_ORIGIN));
  assert.ok(files);
  assert.deepEqual([...(files as Set<string>)].sort(), [
    "docs/new.md",
    "extension/bar.ts",
    "perk/foo.py",
  ]);
});

test("changedFiles: falls back to main/master when origin/HEAD is unavailable", async () => {
  const files = await changedFiles(
    tmpCwd(),
    fakeExec({
      "git symbolic-ref refs/remotes/origin/HEAD": { code: 128, output: "" },
      "git show-ref --verify --quiet refs/heads/main": { code: 1, output: "" },
      "git show-ref --verify --quiet refs/heads/master": { code: 0, output: "" },
      "git merge-base master HEAD": { code: 0, output: "def456\n" },
      "git diff --name-only def456": { code: 0, output: "a.py\n" },
      "git ls-files --others --exclude-standard": { code: 0, output: "" },
    }),
  );
  assert.deepEqual([...(files as Set<string>)], ["a.py"]);
});

test("changedFiles: fail-open → null when a git step errors", async () => {
  const files = await changedFiles(
    tmpCwd(),
    fakeExec({
      "git symbolic-ref refs/remotes/origin/HEAD": {
        code: 0,
        output: "refs/remotes/origin/main\n",
      },
      "git merge-base main HEAD": { code: 128, output: "fatal: not a git repo" },
    }),
  );
  assert.equal(files, null);
});

test("changedFiles: fail-open → null when exec throws", async () => {
  const files = await changedFiles(tmpCwd(), async () => {
    throw new Error("boom");
  });
  assert.equal(files, null);
});

// --- runCiChecks: change-scoped gating -------------------------------------------------

/** A fake exec that answers the git changed-files probes from GIT_OK_ORIGIN plus check commands. */
function gitAndChecks(
  changed: string,
  checkMap: Record<string, { code: number; output: string }>,
): CiExec {
  return fakeExec({
    "git symbolic-ref refs/remotes/origin/HEAD": { code: 0, output: "refs/remotes/origin/main\n" },
    "git merge-base main HEAD": { code: 0, output: "abc123\n" },
    "git diff --name-only abc123": { code: 0, output: changed },
    "git ls-files --others --exclude-standard": { code: 0, output: "" },
    ...checkMap,
  });
}

test("runCiChecks: globbed check skipped when no changed file matches (skipped/passed true)", async () => {
  const report = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    { exec: gitAndChecks("docs/readme.md\n", {}) },
  );
  const c = report.checks[0];
  assert.equal(c?.skipped, true);
  assert.equal(c?.passed, true);
  assert.equal(c?.exitCode, 0);
  assert.equal(report.passed, true);
});

test("runCiChecks: globbed check runs when a changed file matches", async () => {
  const report = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    { exec: gitAndChecks("perk/foo.py\n", { PY: { code: 0, output: "ok" } }) },
  );
  const c = report.checks[0];
  assert.notEqual(c?.skipped, true);
  assert.equal(c?.passed, true);
});

test("runCiChecks: mixed run/skip → overall passed:true; no-glob row always runs", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint-py", command: "PY", glob: "*.py" },
        { name: "lint-js", command: "JS", glob: "*.ts" },
        { name: "always", command: "ALL" },
      ],
    },
    {
      exec: gitAndChecks("extension/x.ts\n", {
        JS: { code: 0, output: "ok" },
        ALL: { code: 0, output: "ok" },
      }),
    },
  );
  assert.equal(report.passed, true);
  assert.equal(report.checks.find((c) => c.name === "lint-py")?.skipped, true);
  assert.notEqual(report.checks.find((c) => c.name === "lint-js")?.skipped, true);
  assert.notEqual(report.checks.find((c) => c.name === "always")?.skipped, true);
});

test("runCiChecks: changedFiles===null (fail-open) runs every globbed check", async () => {
  const report = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    {
      exec: fakeExec({
        "git symbolic-ref refs/remotes/origin/HEAD": {
          code: 0,
          output: "refs/remotes/origin/main\n",
        },
        "git merge-base main HEAD": { code: 128, output: "fatal" },
        PY: { code: 0, output: "ran anyway" },
      }),
    },
  );
  assert.notEqual(report.checks[0]?.skipped, true);
  assert.equal(report.checks[0]?.passed, true);
});

test("runCiChecks: explicit `only` runs even when its glob would not match (no git work)", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [{ name: "lint-py", command: "PY", glob: "*.py" }],
      only: "lint-py",
    },
    // No git commands in the map — asserting the explicit path does NO git work.
    { exec: fakeExec({ PY: { code: 0, output: "ok" } }) },
  );
  assert.notEqual(report.checks[0]?.skipped, true);
  assert.equal(report.checks[0]?.passed, true);
});

test("runCiChecks: no git work when no selected row is globbed", async () => {
  // The fake exec throws on any git command, so a git probe would fail the test.
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
    },
    { exec: fakeExec({ A: { code: 0, output: "ok" }, B: { code: 0, output: "ok" } }) },
  );
  assert.equal(report.passed, true);
  assert.equal(report.checks.length, 2);
});

// --- harness wiring --------------------------------------------------------------------

test("harness: /ci command + run_ci tool registered; empty [ci] → inert report", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(h.registeredCommands().includes("ci"));
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as { ok: boolean; passed: boolean; error_type?: string };
    assert.equal(details.ok, true);
    assert.equal(details.passed, true);
    assert.equal(details.error_type, "no_checks_configured");
  } finally {
    h.dispose();
  }
});

test("harness: run_ci with a configured [ci] runs it (flag-trusted, deterministic)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[[ci]]\nname = "ok"\ncommand = "true"\n', "utf8");
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    h.setFlag("allow-project-ci", true);
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as { ok: boolean; passed: boolean; checks: { name: string }[] };
    assert.equal(details.ok, true);
    assert.equal(details.passed, true);
    assert.equal(details.checks[0]?.name, "ok");
  } finally {
    h.dispose();
  }
});

test("harness: headless run_ci with [trust] ci runs it (trust applies everywhere)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi", "perk.toml"),
    '[[ci]]\nname = "ok"\ncommand = "true"\n\n[trust]\nci = "true"\n',
    "utf8",
  );
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as {
      refused?: boolean;
      passed: boolean;
      checks: { name: string }[];
    };
    assert.notEqual(details.refused, true);
    assert.equal(details.passed, true);
    assert.equal(details.checks[0]?.name, "ok");
  } finally {
    h.dispose();
  }
});

test("harness: headless run_ci with checks + no flag refuses (fail closed)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[[ci]]\nname = "ok"\ncommand = "true"\n', "utf8");
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as { refused?: boolean; error_type?: string };
    assert.equal(details.refused, true);
    assert.equal(details.error_type, "project_ci_unconfirmed");
  } finally {
    h.dispose();
  }
});

test("harness: globbed [[ci]] in a non-git cwd fails open — the check still runs", async () => {
  // No git repo ⇒ changedFiles errors ⇒ fail-open ⇒ the globbed check runs (never a false skip).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi", "perk.toml"),
    '[[ci]]\nname = "py"\ncommand = "true"\nglob = "*.py"\n',
    "utf8",
  );
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    h.setFlag("allow-project-ci", true);
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as {
      passed: boolean;
      checks: { name: string; skipped?: boolean }[];
    };
    assert.equal(details.passed, true);
    assert.notEqual(details.checks[0]?.skipped, true);
  } finally {
    h.dispose();
  }
});

test("harness: globbed [[ci]] skips end-to-end when only non-matching files changed (real git)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi", "perk.toml"),
    '[[ci]]\nname = "py"\ncommand = "true"\nglob = "*.py"\n',
    "utf8",
  );
  gitInit(cwd, { dirty: false }); // seed commit on the default branch (main or master)
  const g = (...args: string[]) => execFileSync("git", args, { cwd, stdio: "ignore" });
  // Branch off trunk and change only a docs file — no *.py touched.
  g("checkout", "-q", "-b", "feature");
  writeFileSync(join(cwd, "notes.md"), "docs only\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "docs only");
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    h.setFlag("allow-project-ci", true);
    const result = await h.invokeTool("run_ci", {});
    const details = result.details as {
      passed: boolean;
      checks: { name: string; skipped?: boolean }[];
    };
    assert.equal(details.passed, true);
    assert.equal(details.checks[0]?.skipped, true);
  } finally {
    h.dispose();
  }
});

test("harness: run_ci with a mistyped check → bad_input, no check executed", async () => {
  // Tool-boundary decode. A configured check exists but is never run.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), '[[ci]]\nname = "ok"\ncommand = "true"\n', "utf8");
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    h.setFlag("allow-project-ci", true);
    const result = await h.invokeTool("run_ci", { check: 5 });
    const details = result.details as {
      ok: boolean;
      passed: boolean;
      checks: unknown[];
      error_type?: string;
    };
    assert.equal(details.ok, false);
    assert.equal(details.passed, false);
    assert.equal(details.error_type, "bad_input");
    assert.deepEqual(details.checks, [], "no check executed");
    assert.match(result.content[0]?.text ?? "", /run_ci failed: `check` must be a string/);
  } finally {
    h.dispose();
  }
});
