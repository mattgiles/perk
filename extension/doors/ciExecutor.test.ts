// Fully-offline coverage for the read-only CI executor: the pure scope gate, the
// deterministic check runner (injected `exec`, no `pi.exec`/network), the route-don't-relay +
// scratch + fail-closed handoff, and the harness wiring (the `run_ci` tool + `/ci` command).
// See ciExecutor.ts.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mock, test } from "node:test";
import { gitInit, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { DEFAULT_MODEL_VISIBLE_CAP } from "../worker/readOnlySession.ts";
import {
  type CiExec,
  changedFiles,
  decideCiScope,
  matchesGlob,
  renderCiProgress,
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

// --- concurrent execution ---------------------------------------------------------------

test("runCiChecks: checks launch concurrently; report keeps declared order", async () => {
  // Deterministic proof, no timers: each exec logs `start:`, yields one macrotask, logs `end:`.
  // Concurrent launch ⇒ both starts precede any end; the old sequential loop would interleave
  // start:a,end:a,start:b,end:b.
  const log: string[] = [];
  const exec: CiExec = async (command) => {
    log.push(`start:${command}`);
    await new Promise((r) => setImmediate(r));
    log.push(`end:${command}`);
    return { code: 0, output: "ok" };
  };
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
    },
    { exec },
  );
  assert.deepEqual(log.slice(0, 2), ["start:A", "start:B"], "both checks start before any ends");
  assert.deepEqual(log.slice(2).sort(), ["end:A", "end:B"]);
  assert.equal(report.passed, true);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["a", "b"],
    "report keeps declared order",
  );
});

test("runCiChecks: out-of-order completion still reports declared order", async () => {
  // The FIRST declared check finishes last: it blocks on a deferred promise resolved by the
  // LAST declared check's exec running (no timeouts — pure causal ordering).
  let release: (() => void) | undefined;
  const gate = new Promise<void>((r) => {
    release = r;
  });
  const done: string[] = [];
  const exec: CiExec = async (command) => {
    if (command === "SLOW") {
      await gate;
      done.push("slow");
      return { code: 0, output: "slow done" };
    }
    done.push("fast");
    release?.();
    return { code: 1, output: "fast failed" };
  };
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "slow", command: "SLOW" },
        { name: "fast", command: "FAST" },
      ],
    },
    { exec },
  );
  assert.deepEqual(done, ["fast", "slow"], "fast completed first");
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["slow", "fast"],
    "report keeps declared order despite completion order",
  );
  assert.equal(report.checks[0]?.passed, true);
  assert.equal(report.checks[1]?.passed, false);
  assert.equal(report.passed, false);
});

test("runCiChecks: one exec throw under concurrency — siblings' results intact, no rejection", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "good", command: "G" },
        { name: "boom", command: "BOOM" },
        { name: "also-good", command: "H" },
      ],
    },
    {
      exec: async (command) => {
        if (command === "BOOM") throw new Error("spawn failed");
        return { code: 0, output: "ok" };
      },
    },
  );
  assert.equal(report.ok, true);
  assert.equal(report.passed, false);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["good", "boom", "also-good"],
  );
  const thrower = report.checks[1];
  assert.equal(thrower?.exitCode, -1);
  assert.equal(thrower?.passed, false);
  assert.ok(thrower?.error?.includes("spawn failed"));
  assert.equal(report.checks[0]?.passed, true);
  assert.equal(report.checks[2]?.passed, true);
});

// --- runCiChecks: multi-name `only` -----------------------------------------------------

test("runCiChecks: comma-separated `only` runs exactly those rows CONCURRENTLY, declared order, no git work", async () => {
  // Start/end log (as in the run-all concurrency proof): both selected rows must launch before
  // either completes — a sequential explicit-selection path would interleave start/end. The log
  // also proves NO git work happens (a git probe would appear as a `start:git …` entry — and
  // throw — even with a globbed row selected).
  const log: string[] = [];
  const exec: CiExec = async (command) => {
    log.push(`start:${command}`);
    await new Promise((r) => setImmediate(r));
    log.push(`end:${command}`);
    return { code: 0, output: "ok" };
  };
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A", glob: "*.py" },
        { name: "b", command: "B" },
        { name: "c", command: "C" },
      ],
      only: "c,a",
    },
    { exec },
  );
  assert.equal(report.ok, true);
  assert.equal(report.passed, true);
  assert.deepEqual(
    log.slice(0, 2),
    ["start:A", "start:C"],
    "both selected rows launch (declared order) before either ends; no git command ran",
  );
  assert.deepEqual(log.slice(2).sort(), ["end:A", "end:C"]);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["a", "c"],
    "declared order, not argument order",
  );
  assert.notEqual(report.checks[0]?.skipped, true, "explicit selection bypasses the glob gate");
});

test("runCiChecks: an exact `only` match beats comma-splitting (delimiter-unsafe names stay selectable)", async () => {
  // `parseCiChecks` accepts any nonblank name — including one containing a comma. The exact-match
  // path keeps such a name selectable, exactly as the pre-list single-name selector did.
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint", command: "L" },
        { name: "fast", command: "F" },
        { name: "lint,fast", command: "LF" },
      ],
      only: "lint,fast",
    },
    { exec: fakeExec({ LF: { code: 0, output: "ok" } }) },
  );
  assert.equal(report.ok, true);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["lint,fast"],
    "the exact name wins over splitting into lint + fast",
  );
});

test("runCiChecks: duplicate names — explicit `only` selects the FIRST declared row only", async () => {
  // Pre-concurrency `find` semantics: `only: "a"` never broadens to every row named `a` (which
  // would race on the same ci-a.md scratch target).
  const ran: string[] = [];
  const exec: CiExec = async (command) => {
    ran.push(command);
    return { code: 0, output: "ok" };
  };
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A1" },
        { name: "a", command: "A2" },
        { name: "b", command: "B" },
      ],
      only: "a",
    },
    { exec },
  );
  assert.deepEqual(ran, ["A1"], "only the first declared row named `a` runs");
  assert.equal(report.checks.length, 1);
  assert.equal(report.checks[0]?.command, "A1");
});

test("runCiChecks: one shared AbortSignal reaches every in-flight check; abort settles fail-closed", async () => {
  // Deterministic, no timers: both execs block on the signal; once BOTH are in flight the second
  // launch aborts the shared controller — every exec must observe the abort and reject, and the
  // report must settle fail-closed (exitCode -1, passed:false) instead of hanging.
  const ac = new AbortController();
  const started: string[] = [];
  const aborted: string[] = [];
  const exec: CiExec = (command, o) =>
    new Promise((_resolve, reject) => {
      started.push(command);
      o.signal?.addEventListener("abort", () => {
        aborted.push(command);
        reject(new Error(`aborted: ${command}`));
      });
      if (started.length === 2) ac.abort();
    });
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      signal: ac.signal,
    },
    { exec },
  );
  assert.deepEqual(started, ["A", "B"], "both checks were in flight before the abort");
  assert.deepEqual(aborted.sort(), ["A", "B"], "every in-flight exec observed the shared signal");
  assert.equal(report.ok, true);
  assert.equal(report.passed, false, "an aborted run never reports success");
  for (const c of report.checks) {
    assert.equal(c.exitCode, -1);
    assert.equal(c.passed, false);
    assert.ok(c.error?.includes("aborted"));
  }
});

test("runCiChecks: `only` with an unknown name among knowns → unknown_check naming it", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      only: "a, nope",
    },
    { exec: fakeExec({}) },
  );
  assert.equal(report.ok, false);
  assert.equal(report.error_type, "unknown_check");
  assert.ok(report.error?.includes("nope"));
  assert.ok(report.error?.includes("a"));
  assert.ok(report.error?.includes("b"));
  assert.deepEqual(report.checks, []);
});

test('runCiChecks: `only` of blanks (",") → no-names error in the unknown_check shape', async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [{ name: "a", command: "A" }],
      only: ",",
    },
    { exec: fakeExec({}) },
  );
  assert.equal(report.ok, false);
  assert.equal(report.error_type, "unknown_check");
  assert.ok(report.error?.includes("no check names given"));
  assert.ok(report.error?.includes("a"));
});

test("runCiChecks: whitespace around names tolerated", async () => {
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "a", command: "A" },
        { name: "b", command: "B" },
      ],
      only: " a , b ",
    },
    { exec: fakeExec({ A: { code: 0, output: "ok" }, B: { code: 0, output: "ok" } }) },
  );
  assert.equal(report.passed, true);
  assert.deepEqual(
    report.checks.map((c) => c.name),
    ["a", "b"],
  );
});

// --- route-don't-relay + scratch -------------------------------------------------------

test("runCiChecks: huge failing output → full text in scratch, prose capped + wrapped", async () => {
  const cwd = tmpCwd();
  const huge = `HEAD-MARKER${"x".repeat(200_000 - 22)}TAIL-MARKER`;
  const report = await runCiChecks(
    { cwd, checks: [{ name: "test", command: "X" }], cap: 1000 },
    { exec: fakeExec({ X: { code: 1, output: huge } }) },
  );
  const c = report.checks[0];
  assert.ok(c);
  assert.equal(c.truncated, true);
  assert.equal(c.bytesTotal, 200_000);
  assert.ok(c.bytesShown <= 1000);
  // The model-visible slice keeps the TAIL (failure summaries end pytest/tsc output).
  assert.ok(c.shown.endsWith("TAIL-MARKER"), "shown must keep the output tail");
  assert.ok(!c.shown.includes("HEAD-MARKER"), "shown must drop the output head");
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

// --- renderCiProgress + the live progress stream -----------------------------------------

test("renderCiProgress: mixed states render glyphs in entry order with the elapsed suffix", () => {
  const line = renderCiProgress(
    [
      { name: "a", state: "passed" },
      { name: "b", state: "failed" },
      { name: "c", state: "skipped" },
      { name: "d", state: "running" },
    ],
    12,
  );
  assert.equal(line, "✓ a · ✗ b · ⊘ c · … d (12s)");
});

test("renderCiProgress: all-running set renders … per entry at 0s", () => {
  const line = renderCiProgress(
    [
      { name: "a", state: "running" },
      { name: "b", state: "running" },
    ],
    0,
  );
  assert.equal(line, "… a · … b (0s)");
});

test("renderCiProgress: control characters in a configured name collapse to spaces (single line)", () => {
  // `parseCiChecks` accepts any nonblank name — including one carrying escaped/multi-line string
  // newlines — so the renderer owns the replace-in-place single-line contract.
  const line = renderCiProgress([{ name: "bad\nname\twith\rctl", state: "running" }], 3);
  assert.equal(line, "… bad name with ctl (3s)");
  assert.ok(!line.includes("\n"));
});

test("runCiChecks: onProgress streams initial all-running → intermediate at first completion → settled", async () => {
  const lines: string[] = [];
  let emitWaiter: (() => void) | undefined;
  const onProgress = (text: string) => {
    lines.push(text);
    emitWaiter?.();
  };
  // Each check blocks on its own deferred, so the test controls completion order exactly —
  // proving the completion-driven emission fires WHILE the sibling is still running (a broken
  // implementation emitting only after everything settles cannot pass the intermediate assert).
  let releasePass: (() => void) | undefined;
  let releaseFail: (() => void) | undefined;
  const passGate = new Promise<void>((r) => {
    releasePass = r;
  });
  const failGate = new Promise<void>((r) => {
    releaseFail = r;
  });
  const exec: CiExec = async (command) => {
    if (command === "P") {
      await passGate;
      return { code: 0, output: "ok" };
    }
    await failGate;
    return { code: 1, output: "bad" };
  };
  const reportPromise = runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "pass", command: "P" },
        { name: "fail", command: "F" },
      ],
    },
    { exec, onProgress },
  );
  // The initial emission happens synchronously during the call, before any check settles.
  assert.deepEqual(lines, ["… pass · … fail (0s)"], "initial all-running emission");
  // Settle ONLY the first check; wait for ITS settled line (robust to a stray ticker line on a
  // pathologically slow run) while the sibling stays gated.
  const intermediate = new Promise<void>((resolve) => {
    emitWaiter = () => {
      if (lines.at(-1)?.startsWith("✓ pass")) resolve();
    };
  });
  releasePass?.();
  await intermediate;
  assert.match(
    lines.at(-1) ?? "",
    /^✓ pass · … fail \(\d+s\)$/u,
    "first completion emits an intermediate line while the sibling is still running",
  );
  emitWaiter = undefined;
  releaseFail?.();
  const report = await reportPromise;
  assert.equal(report.passed, false);
  assert.match(lines.at(-1) ?? "", /^✓ pass · ✗ fail \(\d+s\)$/u, "last line shows both settled");
  for (const line of lines) {
    assert.ok(!line.includes("\n"), "every progress emission is a single line");
    assert.match(line, /^[✓✗⊘…] .+ \(\d+s\)$/u, "glyph-led line with the elapsed suffix");
  }
});

test("runCiChecks: the 1s ticker advances the elapsed suffix and is cleared after completion", async () => {
  // Mock timers (setInterval + Date) make the ticker deterministic: a tick must emit an updated
  // elapsed line, and after the report settles the interval must be cleared (no later emissions).
  mock.timers.enable({ apis: ["setInterval", "Date"] });
  try {
    const lines: string[] = [];
    let release: (() => void) | undefined;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const exec: CiExec = async () => {
      await gate;
      return { code: 0, output: "ok" };
    };
    const reportPromise = runCiChecks(
      { cwd: tmpCwd(), checks: [{ name: "slow", command: "S" }] },
      { exec, onProgress: (text) => lines.push(text) },
    );
    assert.deepEqual(lines, ["… slow (0s)"], "initial emission before any tick");
    mock.timers.tick(1000);
    assert.equal(lines.at(-1), "… slow (1s)", "a tick advances the elapsed suffix");
    mock.timers.tick(1000);
    assert.equal(lines.at(-1), "… slow (2s)");
    release?.();
    const report = await reportPromise;
    assert.equal(report.passed, true);
    assert.equal(lines.at(-1), "✓ slow (2s)", "completion emits the settled line");
    const settled = lines.length;
    mock.timers.tick(10_000);
    assert.equal(lines.length, settled, "the interval is cleared — no emissions after completion");
  } finally {
    mock.timers.reset();
  }
});

test("runCiChecks: a skipped-by-glob check renders ⊘ in the initial progress emission", async () => {
  const lines: string[] = [];
  const report = await runCiChecks(
    {
      cwd: tmpCwd(),
      checks: [
        { name: "lint-py", command: "PY", glob: "*.py" },
        { name: "docs", command: "D" },
      ],
    },
    {
      exec: gitAndChecks("docs/readme.md\n", { D: { code: 0, output: "ok" } }),
      onProgress: (text) => lines.push(text),
    },
  );
  assert.equal(report.passed, true);
  assert.equal(lines[0], "⊘ lint-py · … docs (0s)");
  assert.match(lines.at(-1) ?? "", /^⊘ lint-py · ✓ docs \(\d+s\)$/u);
});

test("runCiChecks: a throwing onProgress sink never breaks the run (incl. timer-driven emissions)", async () => {
  // The exec blocks until after a mocked tick, so the throwing sink is exercised on ALL THREE
  // emission paths — initial, timer-driven (an unswallowed interval throw would escape
  // `mock.timers.tick` and fail this test synchronously), and per-completion.
  mock.timers.enable({ apis: ["setInterval", "Date"] });
  try {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const exec: CiExec = async () => {
      await gate;
      return { code: 0, output: "fine" };
    };
    const reportPromise = runCiChecks(
      { cwd: tmpCwd(), checks: [{ name: "ok", command: "K" }] },
      {
        exec,
        onProgress: () => {
          throw new Error("sink exploded");
        },
      },
    );
    mock.timers.tick(1000);
    release?.();
    const report = await reportPromise;
    assert.equal(report.ok, true);
    assert.equal(report.passed, true);
    assert.equal(report.checks[0]?.passed, true);
  } finally {
    mock.timers.reset();
  }
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
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "ok"\ncommand = "true"\n',
    "utf8",
  );
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

test("harness: headless run_ci with [ci] trusted runs it (trust applies everywhere)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "ok"\ncommand = "true"\n\n[ci]\ntrusted = true\n',
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
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "ok"\ncommand = "true"\n',
    "utf8",
  );
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

test("harness: globbed [[ci.checks]] in a non-git cwd fails open — the check still runs", async () => {
  // No git repo ⇒ changedFiles errors ⇒ fail-open ⇒ the globbed check runs (never a false skip).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "py"\ncommand = "true"\nglob = "*.py"\n',
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

test("harness: globbed [[ci.checks]] skips end-to-end when only non-matching files changed (real git)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "py"\ncommand = "true"\nglob = "*.py"\n',
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

test("harness: run_ci streams in_progress partials via onUpdate; final report carries no marker", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "ok"\ncommand = "true"\n',
    "utf8",
  );
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    h.setFlag("allow-project-ci", true);
    const partials: { content: { text?: string }[]; details: unknown }[] = [];
    const result = await h.invokeTool("run_ci", {}, { onUpdate: (p) => partials.push(p) });
    assert.ok(partials.length >= 1, "at least one streamed partial");
    const first = partials[0];
    assert.match(
      first?.content[0]?.text ?? "",
      /^[✓✗⊘…] ok \(\d+s\)$/u,
      "partial text is the one-line progress indicator",
    );
    assert.equal((first?.details as { in_progress?: boolean }).in_progress, true);
    // The final result is the normal report — never marked in_progress.
    const details = result.details as {
      passed: boolean;
      in_progress?: boolean;
      checks: { name: string }[];
    };
    assert.equal(details.passed, true);
    assert.equal(details.in_progress, undefined);
    assert.equal(details.checks[0]?.name, "ok");
    assert.match(result.content[0]?.text ?? "", /all checks passed/);
  } finally {
    h.dispose();
  }
});

test("harness: run_ci with a mistyped check → bad_input, no check executed", async () => {
  // Tool-boundary decode. A configured check exists but is never run.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[[ci.checks]]\nname = "ok"\ncommand = "true"\n',
    "utf8",
  );
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
