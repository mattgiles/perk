// The SDK-boundary admission at BOTH thin entries, observed in cold processes (contracts.md
// §8.76(f), §8.11 *The entry admission*).
//
// Every child runs under a `--import` resolve hook that maps `@earendil-works/pi-coding-agent` to
// a fake SDK exporting at most `VERSION` — so every NAMED export the SDK adapter (and the
// extension's composition root) needs is missing, exactly as on an SDK older than perk expects.
// That is what an in-process test cannot show: the harness has already linked the real SDK and
// the extension entry, so only a fresh process proves the entry links nothing SDK-bearing before
// it admits. The link-fatality controls below prove the fake really breaks a named import.
//
// Isolation: every child gets its own fresh `TMPDIR` (the child's `os.tmpdir()`), and every
// "no throwaway agent dir" census reads THAT root — never the parent's shared temp dir, where
// concurrently running test files create their own `perk-worker-agent-*` dirs.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { runEventsPath } from "./substrate/cache.ts";
import { admitHostSdk, formatHostSdkRefusal } from "./substrate/hostAdmission.ts";
import { fakePerkRouter, scaffoldWorkerWorktree } from "./testing/harness.ts";
import type { RunEvent, RunOutcome } from "./worker/runEnvelope.ts";

const HOOK_URL = pathToFileURL(
  join(import.meta.dirname, "testing", "fixtures", "hostSdk", "resolve-fake-sdk.mjs"),
).href;
const WORKER_ENTRY = join(import.meta.dirname, "workerMain.ts");
const EXTENSION_ENTRY_URL = pathToFileURL(join(import.meta.dirname, "index.ts")).href;
const ACTIVATION_URL = pathToFileURL(join(import.meta.dirname, "pi", "activation.ts")).href;

interface SpawnOptions {
  /** The fake SDK's `VERSION` (`PERK_TEST_FAKE_SDK_VERSION`). */
  version?: string;
  /** `no-version` selects the fake SDK with no `VERSION` export. */
  fixture?: "no-version";
  /** When set, a PATH-first `pi` stub prints this version (proves a passing CLI certifies nothing). */
  pathPi?: string;
  env?: Record<string, string>;
}

interface SpawnResult {
  status: number | null;
  stdout: string;
  stderr: string;
  /** The child's own `TMPDIR` — the root every throwaway-dir census reads. */
  tmpdir: string;
}

/** Run `node --import <fake-SDK hook> …args` with a minimal env and a fresh per-child TMPDIR. */
function spawnNode(args: string[], opts: SpawnOptions = {}): SpawnResult {
  const childTmp = mkdtempSync(join(tmpdir(), "perk-entry-admission-tmp-"));
  let pathValue = process.env.PATH ?? "";
  if (opts.pathPi !== undefined) {
    const bin = mkdtempSync(join(tmpdir(), "perk-entry-admission-bin-"));
    const pi = join(bin, "pi");
    writeFileSync(pi, `#!/bin/sh\necho ${opts.pathPi}\n`, "utf8");
    chmodSync(pi, 0o755);
    pathValue = `${bin}:${pathValue}`;
  }
  const env: Record<string, string> = {
    PATH: pathValue,
    HOME: mkdtempSync(join(tmpdir(), "perk-entry-admission-home-")),
    TMPDIR: childTmp,
    ...(opts.version !== undefined ? { PERK_TEST_FAKE_SDK_VERSION: opts.version } : {}),
    ...(opts.fixture !== undefined ? { PERK_TEST_FAKE_SDK_FIXTURE: opts.fixture } : {}),
    ...opts.env,
  };
  const result = spawnSync(process.execPath, ["--import", HOOK_URL, ...args], {
    env,
    encoding: "utf8",
    timeout: 60_000,
  });
  return { status: result.status, stdout: result.stdout, stderr: result.stderr, tmpdir: childTmp };
}

function throwawayAgentDirs(root: string): string[] {
  return readdirSync(root).filter((name) => name.startsWith("perk-worker-agent-"));
}

let runCounter = 0;

/** Drive the REAL worker entry in a cold process over a scaffolded worktree. */
function spawnWorker(opts: SpawnOptions & { stage?: string } = {}) {
  const runId = `01JADMIT${String(runCounter++).padStart(18, "0")}`;
  const cwd = scaffoldWorkerWorktree({ runId, stage: "implement" });
  const argvFile = join(cwd, "perk-argv.txt");
  const perkBin = fakePerkRouter(cwd, {}, { argvFile });
  const agentDir = mkdtempSync(join(tmpdir(), "perk-entry-admission-agent-"));
  const result = spawnNode([WORKER_ENTRY, opts.stage ?? "implement", "--worktree", cwd], {
    ...opts,
    env: {
      PERK_RUN_ID: runId,
      PERK_BIN: perkBin,
      PI_CODING_AGENT_DIR: agentDir,
      PI_OFFLINE: "1",
      ...opts.env,
    },
  });
  const lastLine = result.stdout.trim().split("\n").at(-1) ?? "";
  return { ...result, cwd, runId, argvFile, agentDir, lastLine };
}

function readEvents(cwd: string, runId: string): RunEvent[] {
  return readFileSync(runEventsPath(cwd, runId), "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as RunEvent);
}

/** The refused run's shared shape: typed outcome on stdout, the §8.12 pair, nothing driven. */
function assertRefusedBeforeDrive(
  run: ReturnType<typeof spawnWorker>,
  expected: { errorType: string; message: string | RegExp },
): RunOutcome {
  assert.equal(run.status, 1, run.stderr);
  const outcome = JSON.parse(run.lastLine) as RunOutcome;
  assert.equal(outcome.run_id, run.runId);
  assert.equal(outcome.stage, "implement");
  assert.equal(outcome.status, "failed");
  assert.equal(outcome.terminal_signal, "model_error");
  assert.equal(outcome.pr, null);
  assert.equal(outcome.budget.turns, 0);
  assert.equal(outcome.budget.tokens, 0);
  assert.equal(outcome.error?.type, expected.errorType);
  if (typeof expected.message === "string") assert.equal(outcome.error?.message, expected.message);
  else assert.match(outcome.error?.message ?? "", expected.message);

  const events = readEvents(run.cwd, run.runId);
  assert.deepEqual(
    events.map((e) => [e.kind, e.seq]),
    [
      ["run_started", 0],
      ["run_finished", 1],
    ],
  );
  const [started, finished] = events;
  assert.ok(started?.kind === "run_started");
  assert.equal(started.run_id, run.runId);
  assert.equal(started.stage, "implement");
  assert.ok(finished?.kind === "run_finished");
  assert.deepEqual(finished.outcome, outcome);

  // Nothing ran past the refusal: no throwaway agent dir, no perk CLI call, no session file.
  assert.deepEqual(throwawayAgentDirs(run.tmpdir), []);
  assert.equal(existsSync(run.argvFile), false, "the fake perk router must never be invoked");
  assert.equal(existsSync(join(run.agentDir, "sessions")), false);
  assert.doesNotMatch(run.stderr, /perk worker: model /);
  assert.doesNotMatch(run.stderr, /perk worker: compaction/);
  return outcome;
}

// --- the worker entry ----------------------------------------------------------------------------

test("worker: a below-floor SDK missing the adapter's exports is refused typed (exit 1), despite a passing PATH pi", () => {
  const run = spawnWorker({ version: "0.95.0", pathPi: "1.0.0" });
  assertRefusedBeforeDrive(run, {
    errorType: "pi_version_unsupported",
    message: formatHostSdkRefusal(admitHostSdk("0.95.0", "1.0.0"), "worker"),
  });
  // The refusal ran before the SDK-bearing graph could link.
  assert.doesNotMatch(run.stderr, /SyntaxError|does not provide an export/);
});

test("worker: a prerelease of the floor is unsupported", () => {
  const run = spawnWorker({ version: "1.0.0-rc.1" });
  assertRefusedBeforeDrive(run, {
    errorType: "pi_version_unsupported",
    message: formatHostSdkRefusal(admitHostSdk("1.0.0-rc.1", "1.0.0"), "worker"),
  });
});

test("worker: an SDK with no VERSION export is unverifiable", () => {
  const run = spawnWorker({ fixture: "no-version" });
  assertRefusedBeforeDrive(run, {
    errorType: "pi_version_unverifiable",
    message: /exports no VERSION string/,
  });
});

test("worker: an unparseable VERSION is unverifiable and names the value", () => {
  const run = spawnWorker({ version: "latest" });
  assertRefusedBeforeDrive(run, {
    errorType: "pi_version_unverifiable",
    message: /VERSION is "latest"/,
  });
});

test("worker: an at-floor SDK lacking the exports is a typed runtime_init (the lying SDK)", () => {
  const run = spawnWorker({ version: "1.0.0" });
  assertRefusedBeforeDrive(run, {
    errorType: "runtime_init",
    message: /^worker runtime initialization failed: .*does not provide an export named/,
  });
});

test("control: the fake SDK breaks a named import at link time, and its VERSION is live", () => {
  const named = spawnNode(
    [
      "--input-type=module",
      "-e",
      "import { createToolSearchExtension } from '@earendil-works/pi-coding-agent';",
    ],
    { version: "0.95.0" },
  );
  assert.notEqual(named.status, 0);
  assert.match(named.stderr, /does not provide an export named 'createToolSearchExtension'/);

  const version = spawnNode(
    [
      "--input-type=module",
      "-e",
      "import { VERSION } from '@earendil-works/pi-coding-agent'; console.log(VERSION);",
    ],
    { version: "0.95.0" },
  );
  assert.equal(version.status, 0, version.stderr);
  assert.equal(version.stdout.trim(), "0.95.0");
});

test("worker: usage errors still precede the admission (exit 2, no outcome)", () => {
  const run = spawnWorker({ version: "0.95.0", stage: "bogus" });
  assert.equal(run.status, 2);
  assert.equal(run.stdout, "");
  assert.match(run.stderr, /perk worker: stage must be 'implement' or 'address'/);
  assert.equal(existsSync(runEventsPath(run.cwd, run.runId)), false);
});

// --- the extension entry -------------------------------------------------------------------------

/** Import the published entry in a cold process and call its factory with a recording proxy. */
function extensionEntryScript(): string {
  return [
    `const { default: perk } = await import(${JSON.stringify(EXTENSION_ENTRY_URL)});`,
    "const touched = [];",
    "const proxy = new Proxy({}, { get(_, k) { touched.push(String(k)); return () => {}; } });",
    "try { await perk(proxy); console.log(JSON.stringify({ ok: true, touched })); }",
    "catch (e) { console.log(JSON.stringify({ rejected: e.message, touched })); }",
  ].join("\n");
}

test("extension: the entry links nothing SDK-bearing before admission and refuses an old SDK", () => {
  // The `import()` of index.ts itself succeeding under the export-less fake SDK is the proof: a
  // static import of the composition root (or any SDK-bearing module) in the entry would have
  // failed that import with a link SyntaxError before `perk` existed.
  const run = spawnNode(["--input-type=module", "-e", extensionEntryScript()], {
    version: "0.95.0",
  });
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout.trim()), {
    rejected: formatHostSdkRefusal(admitHostSdk("0.95.0", "1.0.0"), "extension"),
    touched: [],
  });
});

test("control: the composition root IS link-fatal under that SDK", () => {
  const run = spawnNode(
    ["--input-type=module", "-e", `await import(${JSON.stringify(ACTIVATION_URL)});`],
    { version: "0.95.0" },
  );
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /does not provide an export named/);
});

test("extension: an SDK with no VERSION export is refused as unverifiable at the entry", () => {
  const run = spawnNode(["--input-type=module", "-e", extensionEntryScript()], {
    fixture: "no-version",
  });
  assert.equal(run.status, 0, run.stderr);
  const result = JSON.parse(run.stdout.trim()) as { rejected?: string; touched: string[] };
  assert.equal(
    result.rejected,
    formatHostSdkRefusal(admitHostSdk(undefined, "1.0.0"), "extension"),
  );
  assert.match(result.rejected ?? "", /exports no VERSION string/);
  assert.deepEqual(result.touched, []);
});
