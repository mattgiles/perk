// A8 — the report tool's argument check agrees with `parseFixtureReport`; the read tools behave as
// specified (docs/design/pi-durable-v2-foundations.md §12 the native assignment). Over a fixed
// corpus, the report arguments pass Durable's pipeline — `prepareArguments`, then pi-ai's
// `validateToolArguments` — exactly when `parseFixtureReport` accepts, and an accepted value comes
// through unchanged. The schema alone agrees everywhere except where pi-ai converts types first (a
// numeric summary becomes text, an object `findings` becomes a list): those cases are pinned here,
// and `prepareArguments` is what refuses them. `ls`/`find`/`grep` over a `SnapshotEnv`: bytewise
// order, glob matching, literal search (a catastrophic-backtracking pattern is plain text), the
// empty-text error, the size and binary skips, and the caps.

import assert from "node:assert/strict";
import { mkdirSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { validateToolArguments } from "@earendil-works/pi-ai";
import { SnapshotEnv } from "../durable/snapshotEnv.ts";
import {
  createReportTool,
  findPaths,
  GREP_MAX_BYTES,
  grepText,
  LIST_CAP,
  listDirectory,
  MATCH_CAP,
  TRUNCATED,
} from "../durable/workerTools.ts";
import { parseFixtureReport } from "../kernel/report.ts";
import { T1 } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";

const context = BACKGROUND_CONTEXT;

const reportTool = createReportTool({
  deps: () => {
    throw new Error("unused");
  },
  verify: () => Promise.reject(new Error("unused")),
});

const BASE = { subjectDigest: T1, summary: "ok", findings: [] };
const finding = (path: string, note = "n") => ({ ...BASE, findings: [{ path, note }] });

/** The corpus: name → arguments. */
const CORPUS: Readonly<Record<string, unknown>> = {
  "valid, minimal": BASE,
  "valid, with findings": {
    ...BASE,
    findings: [
      { path: "a/b", note: "n" },
      { path: "c", note: "m" },
    ],
  },
  "an extra top-level key": { ...BASE, extra: 1 },
  "an extra finding key": { ...BASE, findings: [{ path: "a", note: "n", line: 3 }] },
  "a missing key": { subjectDigest: T1, summary: "ok" },
  "an empty summary": { ...BASE, summary: "" },
  "a lone surrogate": { ...BASE, summary: "\uD800" },
  "a valid surrogate pair": { ...BASE, summary: "\uD83D\uDE00" },
  "an uppercase digest": { ...BASE, subjectDigest: T1.toUpperCase() },
  "a non-oid digest": { ...BASE, subjectDigest: "abc" },
  "a 64-hex digest": { ...BASE, subjectDigest: "b".repeat(64) },
  "path a/b": finding("a/b"),
  "path ../x": finding("../x"),
  "path /abs": finding("/abs"),
  "path a//b": finding("a//b"),
  "path ./a": finding("./a"),
  "path a/.": finding("a/."),
  "path a\\nb": finding("a\nb"),
  "path with dots .x/..y": finding(".x/..y"),
  "an empty note": finding("a", ""),
  "a non-array findings": { ...BASE, findings: { path: "a", note: "n" } },
  "a numeric summary": { ...BASE, summary: 5 },
};

/** The corpus cases pi-ai's own validation converts into a passing value. */
const CONVERTED = ["a non-array findings", "a numeric summary"];

function toolCall(args: unknown) {
  return {
    type: "toolCall" as const,
    id: "c1",
    name: "report",
    arguments: structuredClone(args) as Record<string, never>,
  };
}

function schemaAccepts(args: unknown): boolean {
  try {
    validateToolArguments(reportTool, toolCall(args));
    return true;
  } catch {
    return false;
  }
}

/** Durable's pipeline: the tool's `prepareArguments`, then validation of its result. */
function pipeline(
  args: unknown,
): { readonly ok: true; readonly value: unknown } | { readonly ok: false } {
  try {
    const prepared = reportTool.prepareArguments?.(structuredClone(args));
    return { ok: true, value: validateToolArguments(reportTool, toolCall(prepared)) };
  } catch {
    return { ok: false };
  }
}

test("A8: the report argument check accepts exactly what parseFixtureReport accepts", () => {
  const accepted: string[] = [];
  for (const [name, args] of Object.entries(CORPUS)) {
    const authority = parseFixtureReport(args) !== null;
    const checked = pipeline(args);
    assert.equal(checked.ok, authority, `${name}: the pipeline agrees`);
    if (checked.ok) {
      assert.deepEqual(checked.value, args, `${name}: the validated arguments are the input`);
      accepted.push(name);
    }
    if (CONVERTED.includes(name)) {
      assert.equal(authority, false, name);
      assert.equal(schemaAccepts(args), true, `${name}: pi-ai alone converts it into a pass`);
    } else {
      assert.equal(schemaAccepts(args), authority, `${name}: the schema agrees`);
    }
  }
  assert.deepEqual(accepted, [
    "valid, minimal",
    "valid, with findings",
    "a valid surrogate pair",
    "a 64-hex digest",
    "path a/b",
    "path with dots .x/..y",
  ]);
});

async function snapshot(
  t: Parameters<typeof tempDir>[0],
  files: Readonly<Record<string, string | Buffer>>,
): Promise<SnapshotEnv> {
  const root = join(await tempDir(t, "perk-v2-tools-"), "subjects", "root");
  mkdirSync(root, { recursive: true });
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(join(root, path, ".."), { recursive: true });
    writeFileSync(join(root, path), content);
  }
  const env = await SnapshotEnv.open(root);
  assert.ok(env !== null);
  return env;
}

test("A8: ls lists one directory bytewise, marking directories and symlink entries", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const env = await snapshot(t, { b: "", a: "", B: "", é: "", "dir/x": "" });
  symlinkSync("a", join(env.cwd, "link"));
  assert.deepEqual(await listDirectory(env, undefined, context), [
    "B",
    "a",
    "b",
    "dir/",
    "link@",
    "é",
  ]);
  assert.deepEqual(await listDirectory(env, "dir", context), ["x"]);
});

test("A8: find matches globs against the path relative to the search root", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const env = await snapshot(t, {
    "a.ts": "",
    "README.md": "",
    "src/b.ts": "",
    "src/deep/c.ts": "",
    "dir/1.txt": "",
    "dir/22.txt": "",
    "dir/z.txt": "",
  });
  assert.deepEqual(await findPaths(env, "**/*.ts", undefined, context), [
    "a.ts",
    "src/b.ts",
    "src/deep/c.ts",
  ]);
  assert.deepEqual(await findPaths(env, "*.md", undefined, context), ["README.md"]);
  assert.deepEqual(await findPaths(env, "dir/?.txt", undefined, context), [
    "dir/1.txt",
    "dir/z.txt",
  ]);
  assert.deepEqual(await findPaths(env, "*.ts", "src", context), ["src/b.ts"], "relative to src");
});

test("A8: grep is a literal, case-sensitive substring search", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const env = await snapshot(t, {
    "long.txt": `${"a".repeat(64 * 1024)}\n`,
    "pattern.txt": "x (a+)+$ y\nAlpha\nalpha\r\n",
  });
  const started = Date.now();
  assert.deepEqual(await grepText(env, "(a+)+$", "long.txt", context), [], "no regex semantics");
  assert.ok(Date.now() - started < 1000, "returns at once");
  assert.deepEqual(await grepText(env, "(a+)+$", undefined, context), ["pattern.txt:1:x (a+)+$ y"]);
  assert.deepEqual(await grepText(env, "alpha", undefined, context), ["pattern.txt:3:alpha"]);
  await assert.rejects(grepText(env, "", undefined, context), /text is empty/);
});

test("A8: grep skips large and binary files and cuts long lines", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const env = await snapshot(t, {
    "big.txt": `needle\n${"x".repeat(GREP_MAX_BYTES)}`,
    "binary.bin": Buffer.from("needle\0\n"),
    "long.txt": `needle${"y".repeat(400)}\n`,
  });
  assert.deepEqual(await grepText(env, "needle", undefined, context), [
    `long.txt:1:needle${"y".repeat(294)}`,
  ]);
});

test("A8: every list is capped with a final [truncated] line", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const files: Record<string, string> = {};
  for (let i = 0; i < LIST_CAP + 1; i++) files[`f${String(i).padStart(4, "0")}.txt`] = "hit\n";
  const env = await snapshot(t, files);
  const listed = await listDirectory(env, undefined, context);
  assert.equal(listed.length, LIST_CAP + 1);
  assert.equal(listed.at(-1), TRUNCATED);
  const found = await findPaths(env, "*.txt", undefined, context);
  assert.equal(found.length, LIST_CAP + 1);
  assert.equal(found.at(-1), TRUNCATED);
  assert.equal(found[0], "f0000.txt");
  const matched = await grepText(env, "hit", undefined, context);
  assert.equal(matched.length, MATCH_CAP + 1);
  assert.equal(matched.at(-1), TRUNCATED);
  assert.equal(matched[0], "f0000.txt:1:hit");
});
