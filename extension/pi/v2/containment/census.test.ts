// The containment probes' closed floor (fast tier): the directory holds exactly the three slow
// probe files and this census; all three run in the slow tier; every `mechanism` / `criterion`
// literal they emit is in the evidence vocabulary pinned here (the vocabulary of the evidence
// record's decision rule — docs/design/archive/pi-durable-v2-containment-characterization.md);
// every row the rule requires, and every residual it names, is emitted by the supervised file; and
// every probe is bounded by the per-case timeout. Changing the vocabulary means editing it here.

import assert from "node:assert/strict";
import { globSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { CRITERIA, MECHANISMS, RESULTS } from "../testing/containment/evidence.ts";
import { v2TierFiles } from "../testing/tiers.ts";

const ROOT = resolve(import.meta.dirname, "..", "..", "..", "..");

const PROBE_FILES = [
  "alternatives.slow.test.ts",
  "ownerDeath.slow.test.ts",
  "supervised.slow.test.ts",
];

const VOCABULARY = {
  mechanisms: [
    "repro",
    "supervised",
    "pidns",
    "bwrap",
    "pdeathsig",
    "journal",
    "cgroup",
    "systemd-scope",
    "marker",
  ],
  criteria: [
    "availability",
    "crash-A",
    "crash-B",
    "crash-C",
    "descendants",
    "pid-reuse",
    "setsid-escape",
    "leader-exited",
    "group-kill",
    "group-kill-mitigated",
    "report",
    "survival",
  ],
  results: ["PASS", "FAIL", "unavailable", "not_measured", "recorded"],
};

/** The supervised rows the decision rule requires to PASS on every host. */
const REQUIRED = [
  "availability",
  "crash-A",
  "crash-B",
  "crash-C",
  "descendants",
  "pid-reuse",
  "group-kill-mitigated",
];

/** The supervised rows the rule records as residuals (never verdict-moving). */
const RESIDUAL = ["setsid-escape", "leader-exited", "group-kill"];

/** The literal options argument every probe passes (compared whitespace-insensitively). */
const TIMEOUT_OPTIONS = "{ timeout: CASE_TIMEOUT_MS }";

/** One `test(` call: its title (a string literal), then its second argument up to the next comma. */
const TEST_CALL = /\btest\(\s*(["'`])(.*?)\1\s*,\s*(\{[^{}]*\})\s*,/gs;

/** An argument's source with whitespace and a trailing comma before its closing brace dropped. */
function normalized(text: string): string {
  return text.replace(/\s+/g, "").replace(/,\}$/, "}");
}

function source(file: string): string {
  return readFileSync(join(import.meta.dirname, file), "utf8");
}

function literals(text: string, key: "mechanism" | "criterion"): string[] {
  return [...text.matchAll(new RegExp(`\\b${key}: "([^"]*)"`, "g"))].map((match) => match[1] ?? "");
}

test("the containment directory is the three slow probe files and this census", () => {
  assert.deepEqual(
    globSync("*.ts", { cwd: import.meta.dirname }).sort(),
    [...PROBE_FILES, "census.test.ts"].sort(),
  );
});

test("every containment probe file runs in the slow tier", () => {
  const slow = v2TierFiles("slow", ROOT);
  for (const file of PROBE_FILES) {
    const path = `extension/pi/v2/containment/${file}`;
    assert.ok(slow.includes(path), `the slow tier holds ${path}`);
  }
});

test("the evidence instrument's vocabulary is the pinned one", () => {
  assert.deepEqual([...MECHANISMS], VOCABULARY.mechanisms);
  assert.deepEqual([...CRITERIA], VOCABULARY.criteria);
  assert.deepEqual([...RESULTS], VOCABULARY.results);
});

test("every mechanism and criterion literal the probes use is in the vocabulary", () => {
  const stray: string[] = [];
  for (const file of PROBE_FILES) {
    const text = source(file);
    for (const mechanism of literals(text, "mechanism")) {
      if (!VOCABULARY.mechanisms.includes(mechanism)) stray.push(`${file}: mechanism ${mechanism}`);
    }
    for (const criterion of literals(text, "criterion")) {
      if (!VOCABULARY.criteria.includes(criterion)) stray.push(`${file}: criterion ${criterion}`);
    }
  }
  assert.deepEqual(stray, []);
});

test("the supervised file emits every required and every residual row of the rule", () => {
  const pairs = new Set(
    [
      ...source("supervised.slow.test.ts").matchAll(
        /mechanism: "([^"]*)",\s*criterion: "([^"]*)"/g,
      ),
    ].map((match) => `${match[1]}/${match[2]}`),
  );
  for (const criterion of [...REQUIRED, ...RESIDUAL]) {
    assert.ok(pairs.has(`supervised/${criterion}`), `supervised/${criterion} is emitted`);
  }
});

test("every probe is bounded by the per-case timeout", () => {
  for (const file of PROBE_FILES) {
    const text = source(file);
    const calls = [...text.matchAll(TEST_CALL)];
    assert.equal(
      calls.length,
      text.match(/\btest\(/g)?.length ?? 0,
      `every test( call in ${file} has a literal title and an options object`,
    );
    for (const [, , title = "", options = ""] of calls) {
      assert.equal(
        normalized(options),
        normalized(TIMEOUT_OPTIONS),
        `${file}: "${title}" passes ${TIMEOUT_OPTIONS}`,
      );
    }
  }
});
