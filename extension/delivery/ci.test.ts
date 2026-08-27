// Fully-offline coverage for the CI-execution feature: the pure scope gate and the deterministic
// check runner over its two semantic ports (`RunConfiguredCheck`, `ObserveChangedFiles`) — the
// typed outcome union, selection/ordering/glob policy, route-don't-relay scratch handling,
// fail-closed recovery, and the typed progress stream. No Pi, no timers. See ci.ts.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { DEFAULT_MODEL_VISIBLE_CAP } from "../substrate/modelVisible.ts";
import {
  type CiProgressEvent,
  decideCiScope,
  type ObserveChangedFiles,
  type RunConfiguredCheck,
  runCiChecks,
} from "./ci.ts";

function tmpCwd(): string {
  return mkdtempSync(join(tmpdir(), "perk-ci-cwd-"));
}

/** A fake check port that maps each row's command string to a fixed { code, output }. */
function fakeRun(map: Record<string, { code: number; output: string }>): RunConfiguredCheck {
  return async (check) => {
    const r = map[check.command];
    if (!r) throw new Error(`unexpected command: ${check.command}`);
    return r;
  };
}

/** An observer that must never be consulted (no-glob and explicit-`only` paths). */
const noObserve: ObserveChangedFiles = async () => {
  throw new Error("observeChangedFiles must not be called");
};

/** An observer reporting a fixed changed set (or the fail-open null). */
function observing(files: string[] | null): ObserveChangedFiles {
  return async () => (files === null ? null : new Set(files));
}

/** Drain the event loop until `predicate` holds (deterministic — no wall-clock timers). */
async function until(predicate: () => boolean): Promise<void> {
  while (!predicate()) {
    await new Promise((resolve) => setImmediate(resolve));
  }
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

test("runCiChecks: empty checks → not_configured (inert)", async () => {
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [] },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.deepEqual(outcome, { kind: "not_configured" });
});

test("runCiChecks: unknown `only` → invalid_selection listing available names", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "echo lint" },
        { name: "test", command: "echo test" },
      ],
      only: "nope",
    },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.deepEqual(outcome, {
    kind: "invalid_selection",
    message: "unknown check 'nope'; available: lint, test",
  });
});

test("runCiChecks: run-all preserves declared order; mixed pass/fail → passed:false", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "typecheck", command: "T" },
        { name: "test", command: "X" },
      ],
    },
    {
      runCheck: fakeRun({
        L: { code: 0, output: "lint ok" },
        T: { code: 0, output: "types ok" },
        X: { code: 1, output: "test FAILED" },
      }),
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, false);
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["lint", "typecheck", "test"],
  );
  const [lint, , testCheck] = outcome.checks;
  assert.equal(lint?.kind, "executed");
  if (lint?.kind === "executed") assert.equal(lint.exitCode, 0);
  assert.equal(testCheck?.kind, "executed");
  if (testCheck?.kind === "executed") assert.equal(testCheck.exitCode, 1);
});

test("runCiChecks: single `only` runs exactly one check", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "test", command: "X" },
      ],
      only: "test",
    },
    { runCheck: fakeRun({ X: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.checks.length, 1);
  assert.equal(outcome.checks[0]?.name, "test");
});

test('runCiChecks: scope — run-all → "all"; explicit `only` → "subset"; error arms carry none', async () => {
  const all = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint", command: "L" }] },
    { runCheck: fakeRun({ L: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(all.kind === "completed" ? all.scope : undefined, "all");
  const subset = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "test", command: "X" },
      ],
      only: "test",
    },
    { runCheck: fakeRun({ X: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(subset.kind === "completed" ? subset.scope : undefined, "subset");
  // The early-return arms are scope-less by construction (no scope field on their union arms).
  const empty = await runCiChecks(
    { cwd: tmpCwd(), checks: [] },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.equal(empty.kind, "not_configured");
  const unknown = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "a", command: "A" }], only: "nope" },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.equal(unknown.kind, "invalid_selection");
});

// --- concurrent execution ---------------------------------------------------------------

test("runCiChecks: checks launch concurrently; report keeps declared order", async () => {
  // Deterministic proof, no timers: each run logs `start:`, yields one macrotask, logs `end:`.
  // Concurrent launch ⇒ both starts precede any end; a sequential loop would interleave
  // start:a,end:a,start:b,end:b.
  const log: string[] = [];
  const runCheck: RunConfiguredCheck = async (check) => {
    log.push(`start:${check.command}`);
    await new Promise((r) => setImmediate(r));
    log.push(`end:${check.command}`);
    return { code: 0, output: "ok" };
  };
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
    },
    { runCheck, observeChangedFiles: noObserve },
  );
  assert.deepEqual(log.slice(0, 2), ["start:A", "start:B"], "both checks start before any ends");
  assert.deepEqual(log.slice(2).sort(), ["end:A", "end:B"]);
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["a", "b"],
    "report keeps declared order",
  );
});

test("runCiChecks: out-of-order completion still reports declared order", async () => {
  // The FIRST declared check finishes last: it blocks on a deferred promise resolved by the
  // LAST declared check's run (no timeouts — pure causal ordering).
  let release: (() => void) | undefined;
  const gate = new Promise<void>((r) => {
    release = r;
  });
  const done: string[] = [];
  const runCheck: RunConfiguredCheck = async (check) => {
    if (check.command === "SLOW") {
      await gate;
      done.push("slow");
      return { code: 0, output: "slow done" };
    }
    done.push("fast");
    release?.();
    return { code: 1, output: "fast failed" };
  };
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "slow", command: "SLOW" },
        { name: "fast", command: "FAST" },
      ],
    },
    { runCheck, observeChangedFiles: noObserve },
  );
  assert.deepEqual(done, ["fast", "slow"], "fast completed first");
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["slow", "fast"],
    "report keeps declared order despite completion order",
  );
  const [slow, fast] = outcome.checks;
  assert.equal(slow?.kind === "executed" ? slow.exitCode : -99, 0);
  assert.equal(fast?.kind === "executed" ? fast.exitCode : -99, 1);
  assert.equal(outcome.passed, false);
});

test("runCiChecks: one port throw under concurrency — siblings' results intact, no rejection", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "good", command: "G" },
        { name: "boom", command: "BOOM" },
        { name: "also-good", command: "H" },
      ],
    },
    {
      runCheck: async (check) => {
        if (check.command === "BOOM") throw new Error("spawn failed");
        return { code: 0, output: "ok" };
      },
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, false);
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["good", "boom", "also-good"],
  );
  const thrower = outcome.checks[1];
  assert.equal(thrower?.kind, "executed");
  if (thrower?.kind === "executed") {
    assert.equal(thrower.exitCode, -1);
    assert.ok(thrower.error?.includes("spawn failed"));
  }
  assert.equal(outcome.checks[0]?.kind === "executed" && outcome.checks[0].exitCode === 0, true);
  assert.equal(outcome.checks[2]?.kind === "executed" && outcome.checks[2].exitCode === 0, true);
});

// --- runCiChecks: multi-name `only` -----------------------------------------------------

test("runCiChecks: comma-separated `only` runs exactly those rows CONCURRENTLY, declared order, no observation", async () => {
  // Start/end log (as in the run-all concurrency proof): both selected rows must launch before
  // either completes. `observeChangedFiles` is the throwing fake — proving the explicit path
  // never observes the changed set even with a globbed row selected.
  const log: string[] = [];
  const runCheck: RunConfiguredCheck = async (check) => {
    log.push(`start:${check.command}`);
    await new Promise((r) => setImmediate(r));
    log.push(`end:${check.command}`);
    return { code: 0, output: "ok" };
  };
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A", glob: "*.py" },
        { name: "b", command: "B" },
        { name: "c", command: "C" },
      ],
      only: "c,a",
    },
    { runCheck, observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.deepEqual(
    log.slice(0, 2),
    ["start:A", "start:C"],
    "both selected rows launch (declared order) before either ends; no observation ran",
  );
  assert.deepEqual(log.slice(2).sort(), ["end:A", "end:C"]);
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["a", "c"],
    "declared order, not argument order",
  );
  assert.equal(outcome.checks[0]?.kind, "executed", "explicit selection bypasses the glob gate");
});

test("runCiChecks: an exact `only` match beats comma-splitting (delimiter-unsafe names stay selectable)", async () => {
  // `parseCiChecks` accepts any nonblank name — including one containing a comma. The exact-match
  // path keeps such a name selectable, exactly as the pre-list single-name selector did.
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "fast", command: "F" },
        { name: "lint,fast", command: "LF" },
      ],
      only: "lint,fast",
    },
    { runCheck: fakeRun({ LF: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["lint,fast"],
    "the exact name wins over splitting into lint + fast",
  );
});

test("runCiChecks: duplicate names — explicit `only` selects the FIRST declared row only", async () => {
  // Pre-concurrency `find` semantics: `only: "a"` never broadens to every row named `a` (which
  // would race on the same ci-a.md scratch target).
  const ran: string[] = [];
  const runCheck: RunConfiguredCheck = async (check) => {
    ran.push(check.command);
    return { code: 0, output: "ok" };
  };
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A1" },
        { name: "a", command: "A2" },
        { name: "b", command: "B" },
      ],
      only: "a",
    },
    { runCheck, observeChangedFiles: noObserve },
  );
  assert.deepEqual(ran, ["A1"], "only the first declared row named `a` runs");
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.checks.length, 1);
  assert.equal(outcome.checks[0]?.command, "A1");
});

test("runCiChecks: one shared AbortSignal reaches every in-flight check; abort settles fail-closed", async () => {
  // Deterministic, no timers: both runs block on the signal; once BOTH are in flight the second
  // launch aborts the shared controller — every run must observe the abort and reject, and the
  // outcome must settle fail-closed (exitCode -1) instead of hanging.
  const ac = new AbortController();
  const started: string[] = [];
  const aborted: string[] = [];
  const runCheck: RunConfiguredCheck = (check, o) =>
    new Promise((_resolve, reject) => {
      started.push(check.command);
      o.signal?.addEventListener("abort", () => {
        aborted.push(check.command);
        reject(new Error(`aborted: ${check.command}`));
      });
      if (started.length === 2) ac.abort();
    });
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      signal: ac.signal,
    },
    { runCheck, observeChangedFiles: noObserve },
  );
  assert.deepEqual(started, ["A", "B"], "both checks were in flight before the abort");
  assert.deepEqual(aborted.sort(), ["A", "B"], "every in-flight run observed the shared signal");
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, false, "an aborted run never reports success");
  for (const c of outcome.checks) {
    assert.equal(c.kind, "executed");
    if (c.kind === "executed") {
      assert.equal(c.exitCode, -1);
      assert.ok(c.error?.includes("aborted"));
    }
  }
});

test("runCiChecks: `only` with an unknown name among knowns → invalid_selection naming it", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      only: "a, nope",
    },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.deepEqual(outcome, {
    kind: "invalid_selection",
    message: "unknown check 'nope'; available: a, b",
  });
});

test('runCiChecks: `only` of blanks (",") → the no-names invalid_selection diagnostic', async () => {
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "a", command: "A" }], only: "," },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve },
  );
  assert.deepEqual(outcome, {
    kind: "invalid_selection",
    message: "no check names given; available: a",
  });
});

test("runCiChecks: whitespace around names tolerated", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      only: " a , b ",
    },
    {
      runCheck: fakeRun({ A: { code: 0, output: "ok" }, B: { code: 0, output: "ok" } }),
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.deepEqual(
    outcome.checks.map((c) => c.name),
    ["a", "b"],
  );
});

// --- route-don't-relay + scratch -------------------------------------------------------

test("runCiChecks: huge failing output → full text in scratch, shown capped to the tail", async () => {
  const cwd = tmpCwd();
  const huge = `HEAD-MARKER${"x".repeat(200_000 - 22)}TAIL-MARKER`;
  const outcome = await runCiChecks(
    { cwd, checks: [{ name: "test", command: "X" }] },
    { runCheck: fakeRun({ X: { code: 1, output: huge } }), observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  const c = outcome.checks[0];
  assert.equal(c?.kind, "executed");
  if (c?.kind !== "executed") return;
  assert.equal(c.truncated, true);
  assert.equal(c.bytesTotal, 200_000);
  assert.ok(c.bytesShown <= DEFAULT_MODEL_VISIBLE_CAP);
  // The model-visible slice keeps the TAIL (failure summaries end pytest/tsc output).
  assert.ok(c.shown.endsWith("TAIL-MARKER"), "shown must keep the output tail");
  assert.ok(!c.shown.includes("HEAD-MARKER"), "shown must drop the output head");
  // Full output preserved in scratch (un-run-scoped path under .perk/workflow/scratch/ci/).
  assert.ok(c.scratchPath?.includes(join("scratch", "ci", "test.md")));
  assert.ok(c.scratchPath && existsSync(c.scratchPath));
  assert.equal(readFileSync(c.scratchPath, "utf8").length, 200_000);
});

test("runCiChecks: run-scoped scratch path under scratch/runs/<runId>/ci-<name>.md", async () => {
  const cwd = tmpCwd();
  const outcome = await runCiChecks(
    { cwd, checks: [{ name: "lint", command: "L" }], runId: "01RUN" },
    { runCheck: fakeRun({ L: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  const c = outcome.checks[0];
  assert.equal(c?.kind, "executed");
  if (c?.kind !== "executed") return;
  assert.ok(c.scratchPath?.includes(join("scratch", "runs", "01RUN", "ci-lint.md")));
  assert.ok(c.scratchPath && existsSync(c.scratchPath));
});

// --- fail-closed -----------------------------------------------------------------------

test("runCiChecks: port throw → fail-closed (exitCode:-1, error captured, no throw)", async () => {
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "test", command: "BOOM" }] },
    {
      runCheck: async () => {
        throw new Error("spawn failed");
      },
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, false);
  const c = outcome.checks[0];
  assert.equal(c?.kind, "executed");
  if (c?.kind !== "executed") return;
  assert.equal(c.exitCode, -1);
  assert.ok(c.error?.includes("spawn failed"));
});

test("runCiChecks: scratch-verify failure → exit code still reported, no throw", async () => {
  // Point cwd at a path whose scratch dir cannot be created (a FILE where the dir should be).
  const cwd = tmpCwd();
  mkdirSync(join(cwd, ".perk", "workflow", "scratch"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "workflow", "scratch", "ci"), "", "utf8"); // a file, not a dir
  const outcome = await runCiChecks(
    { cwd, checks: [{ name: "test", command: "X" }] },
    {
      runCheck: fakeRun({ X: { code: 1, output: "fail output" } }),
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  const c = outcome.checks[0];
  assert.equal(c?.kind, "executed");
  if (c?.kind !== "executed") return;
  assert.equal(c.exitCode, 1);
  assert.equal(c.scratchPath, null);
  assert.ok(c.error);
});

// --- change-scoped gating through the ObserveChangedFiles port ---------------------------

test("runCiChecks: globbed check skipped when no changed file matches; basename matches at any depth", async () => {
  const skip = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    { runCheck: fakeRun({}), observeChangedFiles: observing(["docs/readme.md"]) },
  );
  assert.equal(skip.kind, "completed");
  if (skip.kind !== "completed") return;
  assert.deepEqual(skip.checks, [
    { kind: "skipped", name: "lint-py", command: "PY", glob: "*.py" },
  ]);
  assert.equal(skip.passed, true);
  // A slash-free pattern gates on the BASENAME at any depth (the gitignore/fnmatch rule).
  const run = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    {
      runCheck: fakeRun({ PY: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["a/b/c.py"]),
    },
  );
  assert.equal(run.kind === "completed" ? run.checks[0]?.kind : "?", "executed");
});

test("runCiChecks: ** crosses directories; a slash pattern matches the full repo-relative path", async () => {
  const checks = [{ name: "docs", command: "D", glob: "docs/*.md" }];
  const deep = await runCiChecks(
    { cwd: tmpCwd(), checks },
    { runCheck: fakeRun({}), observeChangedFiles: observing(["docs/sub/a.md"]) },
  );
  assert.equal(
    deep.kind === "completed" ? deep.checks[0]?.kind : "?",
    "skipped",
    "docs/*.md never crosses a directory",
  );
  const shallow = await runCiChecks(
    { cwd: tmpCwd(), checks },
    {
      runCheck: fakeRun({ D: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["docs/a.md"]),
    },
  );
  assert.equal(shallow.kind === "completed" ? shallow.checks[0]?.kind : "?", "executed");
  const doubleStar = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "docs", command: "D", glob: "docs/**" }] },
    {
      runCheck: fakeRun({ D: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["docs/sub/a.md"]),
    },
  );
  assert.equal(
    doubleStar.kind === "completed" ? doubleStar.checks[0]?.kind : "?",
    "executed",
    "** crosses directories",
  );
});

test("runCiChecks: comma multi-pattern globs match any pattern", async () => {
  const checks = [{ name: "js", command: "J", glob: "*.ts,*.tsx,*.js" }];
  const hit = await runCiChecks(
    { cwd: tmpCwd(), checks },
    {
      runCheck: fakeRun({ J: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["x.tsx"]),
    },
  );
  assert.equal(hit.kind === "completed" ? hit.checks[0]?.kind : "?", "executed");
  const miss = await runCiChecks(
    { cwd: tmpCwd(), checks },
    { runCheck: fakeRun({}), observeChangedFiles: observing(["x.md"]) },
  );
  assert.equal(miss.kind === "completed" ? miss.checks[0]?.kind : "?", "skipped");
});

test("runCiChecks: mixed run/skip → overall passed:true; no-glob row always runs", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint-py", command: "PY", glob: "*.py" },
        { name: "lint-js", command: "JS", glob: "*.ts" },
        { name: "always", command: "ALL" },
      ],
    },
    {
      runCheck: fakeRun({ JS: { code: 0, output: "ok" }, ALL: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["extension/x.ts"]),
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.equal(outcome.checks.find((c) => c.name === "lint-py")?.kind, "skipped");
  assert.equal(outcome.checks.find((c) => c.name === "lint-js")?.kind, "executed");
  assert.equal(outcome.checks.find((c) => c.name === "always")?.kind, "executed");
});

test("runCiChecks: a null observation (fail-open) runs every globbed check", async () => {
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    {
      runCheck: fakeRun({ PY: { code: 0, output: "ran anyway" } }),
      observeChangedFiles: observing(null),
    },
  );
  assert.equal(outcome.kind === "completed" ? outcome.checks[0]?.kind : "?", "executed");
});

test("runCiChecks: a THROWING observer folds to the fail-open arm (never skip on uncertainty)", async () => {
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "lint-py", command: "PY", glob: "*.py" }] },
    {
      runCheck: fakeRun({ PY: { code: 0, output: "ran anyway" } }),
      observeChangedFiles: async () => {
        throw new Error("git blew up");
      },
    },
  );
  assert.equal(outcome.kind === "completed" ? outcome.checks[0]?.kind : "?", "executed");
});

test("runCiChecks: explicit `only` runs even when its glob would not match (no observation)", async () => {
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [{ name: "lint-py", command: "PY", glob: "*.py" }],
      only: "lint-py",
    },
    // The throwing observer proves the explicit path does NO observation work.
    { runCheck: fakeRun({ PY: { code: 0, output: "ok" } }), observeChangedFiles: noObserve },
  );
  assert.equal(outcome.kind === "completed" ? outcome.checks[0]?.kind : "?", "executed");
});

test("runCiChecks: no observation when no selected row is globbed", async () => {
  // The throwing observer fake would fail the run if consulted.
  const outcome = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
    },
    {
      runCheck: fakeRun({ A: { code: 0, output: "ok" }, B: { code: 0, output: "ok" } }),
      observeChangedFiles: noObserve,
    },
  );
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.equal(outcome.checks.length, 2);
});

// --- the typed progress stream -----------------------------------------------------------

test("runCiChecks: run_started is synchronous with ordered entries; skips render skipped", async () => {
  const events: CiProgressEvent[] = [];
  const promise = runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint-py", command: "PY", glob: "*.py" },
        { name: "docs", command: "D" },
      ],
    },
    {
      runCheck: fakeRun({ D: { code: 0, output: "ok" } }),
      observeChangedFiles: observing(["docs/readme.md"]),
      onProgress: (event) => events.push(event),
    },
  );
  const outcome = await promise;
  assert.equal(outcome.kind, "completed");
  assert.deepEqual(events[0], {
    kind: "run_started",
    entries: [
      { name: "lint-py", state: "skipped" },
      { name: "docs", state: "running" },
    ],
  });
  // A skip resolves synchronously and emits no check_settled of its own.
  assert.deepEqual(events.at(-1), {
    kind: "check_settled",
    entries: [
      { name: "lint-py", state: "skipped" },
      { name: "docs", state: "passed" },
    ],
  });
  assert.equal(events.length, 2);
});

test("runCiChecks: a check_settled arrives while a sibling is still pending; final entries settled", async () => {
  const events: CiProgressEvent[] = [];
  // Each check blocks on its own deferred, so the test controls completion order exactly —
  // proving the completion-driven emission fires WHILE the sibling is still running (a broken
  // implementation emitting only after everything settles cannot pass the mid-flight assert).
  let releasePass: (() => void) | undefined;
  let releaseFail: (() => void) | undefined;
  const passGate = new Promise<void>((r) => {
    releasePass = r;
  });
  const failGate = new Promise<void>((r) => {
    releaseFail = r;
  });
  const runCheck: RunConfiguredCheck = async (check) => {
    if (check.command === "P") {
      await passGate;
      return { code: 0, output: "ok" };
    }
    await failGate;
    return { code: 1, output: "bad" };
  };
  const promise = runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "pass", command: "P" },
        { name: "fail", command: "F" },
      ],
    },
    { runCheck, observeChangedFiles: noObserve, onProgress: (event) => events.push(event) },
  );
  // The run_started emission happens synchronously during the call, before any check settles.
  assert.deepEqual(events, [
    {
      kind: "run_started",
      entries: [
        { name: "pass", state: "running" },
        { name: "fail", state: "running" },
      ],
    },
  ]);
  // Settle ONLY the first check and wait for ITS event while the sibling stays gated.
  releasePass?.();
  await until(() => events.length >= 2);
  assert.deepEqual(
    events[1],
    {
      kind: "check_settled",
      entries: [
        { name: "pass", state: "passed" },
        { name: "fail", state: "running" },
      ],
    },
    "the first completion emits while the sibling is still running",
  );
  releaseFail?.();
  const outcome = await promise;
  assert.equal(outcome.kind === "completed" ? outcome.passed : undefined, false);
  assert.deepEqual(events.at(-1), {
    kind: "check_settled",
    entries: [
      { name: "pass", state: "passed" },
      { name: "fail", state: "failed" },
    ],
  });
});

test("runCiChecks: the refusal arms emit nothing", async () => {
  const events: CiProgressEvent[] = [];
  const onProgress = (event: CiProgressEvent) => events.push(event);
  await runCiChecks(
    { cwd: tmpCwd(), checks: [] },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve, onProgress },
  );
  await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "a", command: "A" }], only: "nope" },
    { runCheck: fakeRun({}), observeChangedFiles: noObserve, onProgress },
  );
  assert.deepEqual(events, [], "not_configured and invalid_selection emit no progress");
});

test("runCiChecks: snapshot isolation — retained events never mutate; a mutating sink is contained", async () => {
  // (a) A retained run_started event stays deep-equal to its original bytes after settlement:
  // shared references to the internal state array would mutate it in place.
  const retained: CiProgressEvent[] = [];
  await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "a", command: "A" }] },
    {
      runCheck: fakeRun({ A: { code: 0, output: "ok" } }),
      observeChangedFiles: noObserve,
      onProgress: (event) => retained.push(event),
    },
  );
  assert.deepEqual(retained[0], {
    kind: "run_started",
    entries: [{ name: "a", state: "running" }],
  });
  // (b) A sink that MUTATES its received entries changes neither later events nor the outcome.
  const seen: CiProgressEvent[] = [];
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "a", command: "A" }] },
    {
      runCheck: fakeRun({ A: { code: 0, output: "ok" } }),
      observeChangedFiles: noObserve,
      onProgress: (event) => {
        seen.push(JSON.parse(JSON.stringify(event)) as CiProgressEvent);
        for (const entry of event.entries) {
          (entry as { name: string; state: string }).name = "mutated";
          (entry as { name: string; state: string }).state = "failed";
        }
      },
    },
  );
  assert.deepEqual(seen.at(-1), {
    kind: "check_settled",
    entries: [{ name: "a", state: "passed" }],
  });
  assert.equal(outcome.kind, "completed");
  if (outcome.kind !== "completed") return;
  assert.equal(outcome.passed, true);
  assert.equal(outcome.checks[0]?.name, "a");
});

test("runCiChecks: a throwing sink AND an async-rejecting sink leave the run intact, no unhandled rejection", async () => {
  const rejections: unknown[] = [];
  const listener = (reason: unknown) => {
    rejections.push(reason);
  };
  process.on("unhandledRejection", listener);
  try {
    const throwing = await runCiChecks(
      { cwd: tmpCwd(), checks: [{ name: "ok", command: "K" }] },
      {
        runCheck: fakeRun({ K: { code: 0, output: "fine" } }),
        observeChangedFiles: noObserve,
        onProgress: () => {
          throw new Error("sink exploded");
        },
      },
    );
    assert.equal(throwing.kind === "completed" ? throwing.passed : undefined, true);
    const rejecting = await runCiChecks(
      { cwd: tmpCwd(), checks: [{ name: "ok", command: "K" }] },
      {
        runCheck: fakeRun({ K: { code: 0, output: "fine" } }),
        observeChangedFiles: noObserve,
        onProgress: (() => Promise.reject(new Error("async sink"))) as unknown as (
          e: CiProgressEvent,
        ) => void,
      },
    );
    assert.equal(rejecting.kind === "completed" ? rejecting.passed : undefined, true);
    // Give any leaked rejection two macrotask turns to surface.
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    assert.deepEqual(rejections, [], "no unhandled rejection escaped the sink containment");
  } finally {
    process.off("unhandledRejection", listener);
  }
});

// --- port cancellation threading ----------------------------------------------------------

test("runCiChecks: the opts.signal instance reaches both ports", async () => {
  const ac = new AbortController();
  const seen: (AbortSignal | undefined)[] = [];
  const outcome = await runCiChecks(
    { cwd: tmpCwd(), checks: [{ name: "py", command: "PY", glob: "*.py" }], signal: ac.signal },
    {
      runCheck: async (_check, o) => {
        seen.push(o.signal);
        return { code: 0, output: "ok" };
      },
      observeChangedFiles: async (o) => {
        seen.push(o.signal);
        return new Set(["x.py"]);
      },
    },
  );
  assert.equal(outcome.kind, "completed");
  assert.equal(seen.length, 2, "the observation and the check both received opts");
  assert.ok(
    seen.every((s) => s === ac.signal),
    "the exact signal instance reaches both ports",
  );
});
