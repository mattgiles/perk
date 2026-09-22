// Runtime smoke for the module census tracer, proven through public Node APIs only
// (`node --import`, `node:module` registerHooks) — never engine internals.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const TRACER_URL = new URL("./module_tracer.mjs", import.meta.url).href;

function tempDir() {
  return mkdtempSync(join(tmpdir(), "perk-census-"));
}

function censusFiles(dir) {
  return readdirSync(dir).filter((name) => /^census-\d+\.jsonl$/.test(name));
}

function readCensus(dir, name) {
  return readFileSync(join(dir, name), "utf8")
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line));
}

function envWith(dir) {
  const env = { ...process.env };
  delete env.NODE_OPTIONS;
  if (dir === undefined) {
    delete env.PERK_MODULE_CENSUS_DIR;
  } else {
    env.PERK_MODULE_CENSUS_DIR = dir;
  }
  return env;
}

test("records a process header and the resolutions of a traced process", () => {
  const dir = tempDir();
  try {
    const result = spawnSync(
      process.execPath,
      ["--import", TRACER_URL, "-e", "import('node:fs').then(() => {})"],
      { env: envWith(dir), encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    const files = censusFiles(dir);
    assert.equal(files.length, 1, `expected one census file, got ${files.join(", ")}`);
    assert.equal(files[0], `census-${result.pid}.jsonl`);
    const rows = readCensus(dir, files[0]);
    const [header, ...rest] = rows;
    assert.equal(header.kind, "process");
    assert.equal(header.pid, result.pid);
    assert.equal(header.hooks, true);
    assert.equal(header.execPath, process.execPath);
    assert.equal(header.node, process.version);
    assert.ok(Array.isArray(header.argv));
    const resolves = rest.filter((row) => row.kind === "resolve");
    assert.ok(resolves.length > 0, "expected at least one resolve row");
    assert.ok(
      resolves.some((row) => row.url === "node:fs" && row.specifier === "node:fs"),
      `no resolve row for node:fs in ${JSON.stringify(resolves)}`,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("writes nothing when PERK_MODULE_CENSUS_DIR is unset", () => {
  const dir = tempDir();
  try {
    const result = spawnSync(
      process.execPath,
      ["--import", TRACER_URL, "-e", "import('node:fs').then(() => {})"],
      { env: envWith(undefined), encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(censusFiles(dir), []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// Every wait on the traced child is bounded: a regression that leaves it alive after SIGTERM
// must FAIL the test, never hang `test-js`.
const STEP_TIMEOUT_MS = 10_000;

function withDeadline(promise, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${label} did not happen within ${STEP_TIMEOUT_MS} ms`)),
      STEP_TIMEOUT_MS,
    );
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

function onceExited(child) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return new Promise((resolve) => {
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}

test("a SIGTERM'd process still flushes its census through the exit handler", async () => {
  const dir = tempDir();
  const child = spawn(
    process.execPath,
    [
      "--import",
      TRACER_URL,
      "-e",
      "process.stdout.write('ready\\n'); setInterval(() => {}, 1000);",
    ],
    { env: envWith(dir), stdio: ["ignore", "pipe", "pipe"] },
  );
  const exited = onceExited(child);
  try {
    await withDeadline(
      new Promise((resolve, reject) => {
        let out = "";
        child.stdout.on("data", (chunk) => {
          out += chunk.toString();
          if (out.includes("ready")) {
            resolve();
          }
        });
        child.once("error", reject);
        exited.then(({ code, signal }) =>
          reject(new Error(`exited early (code ${code}, signal ${signal})`)),
        );
      }),
      "the traced child's ready line",
    );
    child.kill("SIGTERM");
    const { code, signal } = await withDeadline(exited, "the traced child's exit after SIGTERM");
    assert.equal(signal, null, "the tracer's handler turns SIGTERM into an orderly exit");
    assert.equal(code, 0);
    const files = censusFiles(dir);
    assert.deepEqual(files, [`census-${child.pid}.jsonl`]);
    const [header] = readCensus(dir, files[0]);
    assert.equal(header.kind, "process");
    assert.equal(header.hooks, true);
  } finally {
    // Kill-and-await cleanup: whatever failed above, the child never outlives the test.
    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGKILL");
      await withDeadline(exited, "the traced child's exit after SIGKILL").catch(() => {});
    }
    rmSync(dir, { recursive: true, force: true });
  }
});
