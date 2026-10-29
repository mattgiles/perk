// V6 — the host CLI as a real process (docs/design/pi-durable-v2-foundations.md §11, contracts.md
// §8.77): `node door/main.ts start …` over a fixture repo prints exactly one JSON envelope line and
// exits 0; a usage error exits 2 and a fault exits 1, both with empty stdout.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { E, REF } from "../testing/binding.ts";
import { cliArgv } from "../testing/door.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import { fixtureSubject } from "../testing/worker.ts";

const MAIN = resolve(import.meta.dirname, "main.ts");

function host(argv: readonly string[]) {
  return spawnSync(process.execPath, [MAIN, ...argv], {
    encoding: "utf8",
    timeout: CASE_TIMEOUT_MS,
  });
}

test("V6: start prints exactly one pending_decision envelope line and exits 0", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { repo, tree, store } = await fixtureSubject(t);
  const result = host(
    cliArgv("start", {
      store,
      execution: E,
      "repo-identity": join(repo, ".git"),
      repo,
      ref: REF,
    }),
  );
  assert.equal(result.status, 0, result.stderr);
  assert.ok(result.stdout.endsWith("\n"), "a trailing newline");
  const lines = result.stdout.split("\n");
  assert.equal(lines.length, 2, "exactly one line");
  const envelope = JSON.parse(lines[0] ?? "");
  assert.equal(envelope.envelope, 1);
  assert.equal(envelope.outcome, "pending_decision");
  assert.equal(envelope.verb, "start");
  assert.equal(envelope.executionId, E);
  assert.equal(envelope.status.observation.tree, tree);
});

test("V6: a usage error exits 2 and a fault exits 1, both with empty stdout", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const usage = host(["bogus"]);
  assert.equal(usage.status, 2);
  assert.equal(usage.stdout, "");
  assert.match(usage.stderr, /^perk v2 host: /);

  // A store under a regular file cannot be created: the host throws, and the entry reports it.
  const dir = await tempDir(t, "perk-v2-door-main-");
  const file = join(dir, "file");
  writeFileSync(file, "");
  const fault = host(
    cliArgv("start", {
      store: join(file, "store"),
      execution: E,
      "repo-identity": join(dir, ".git"),
      repo: dir,
      ref: REF,
    }),
  );
  assert.equal(fault.status, 1, fault.stderr);
  assert.equal(fault.stdout, "");
  assert.match(fault.stderr, /^perk v2 host fault: /);
});
