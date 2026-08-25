// Atomic-write regression guard (contracts.md §8.1).
// Production extension code writes files through `atomicWriteFileSync` (substrate/cache.ts —
// temp file in the same directory + atomic rename) so a concurrent writer can never tear a
// `.perk/workflow/` file. Bare fs write APIs are banned outside a small per-API allowlist:
// the seam's own body (cache.ts), clipboard.ts (a fresh private mkdtemp dir — unshared by
// construction), and the append-only NDJSON streams — the stage-execution seam's `events.ndjson`
// plus the §8.58 hunk-watch `outbox.ndjson`/`delivered.ndjson` (O_APPEND appends cannot truncate-tear,
// and whole-file replace would introduce a read-modify-write race between independent
// processes). A textual backstop, not a completeness proof (see
// docs/learned/workflow/source-scan-guards.md). The Python twin is tests/test_write_guard.py.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

// Per-API allowlist: pattern → files allowed to call it. Each pattern requires `(` immediately
// after the API name (a call site), so `writeFileSync(` never double-matches `writeFile(`'s
// rule. `writeFile(`/`appendFile(`/`createWriteStream(` are unused today — banned everywhere
// (future-proofing).
const RULES: { api: string; pattern: RegExp; allowed: string[] }[] = [
  {
    api: "writeFileSync(",
    pattern: /\bwriteFileSync\(/,
    allowed: ["substrate/cache.ts", "substrate/clipboard.ts"],
  },
  {
    api: "appendFileSync(",
    pattern: /\bappendFileSync\(/,
    // worker/stageExecution.ts: the append-only `events.ndjson` stream. hunkFeedback/store.ts
    // (the receiver's `delivered.ndjson`) and hunkFeedback/perkFeedback.ts (the standalone
    // bundled publisher's `outbox.ndjson`) are the §8.58 append-only NDJSON streams — same
    // O_APPEND rationale: appends cannot truncate-tear, and whole-file replace would introduce
    // a read-modify-write race between the two independent processes.
    allowed: ["worker/stageExecution.ts", "hunkFeedback/store.ts", "hunkFeedback/perkFeedback.ts"],
  },
  { api: "writeFile(", pattern: /\bwriteFile\(/, allowed: [] },
  { api: "appendFile(", pattern: /\bappendFile\(/, allowed: [] },
  { api: "createWriteStream(", pattern: /\bcreateWriteStream\(/, allowed: [] },
];

/**
 * Discover production sources under extension/: every `.ts` file (recursively, so future
 * subdirectories are scanned by default) except test files and the testing/ fakes.
 */
function productionFiles(): string[] {
  const entries = readdirSync(import.meta.dirname, { recursive: true }) as string[];
  return entries
    .map((entry) => entry.split(path.sep).join("/"))
    .filter(
      (entry) =>
        entry.endsWith(".ts") && !entry.endsWith(".test.ts") && !entry.startsWith("testing/"),
    )
    .sort();
}

/**
 * Strip block comments then line comments before matching. Deliberately naive — this would also
 * eat `//` inside string literals — acceptable because the stripped text is only consumed for
 * matching and a perk string/URL plausibly containing `//` would not also carry a bare fs write
 * call on the same line.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

/** Collect `«relative-path»:«1-based line»: «api»` violations across all rules. */
function violationsOf(files: string[]): string[] {
  const violations: string[] = [];
  for (const file of files) {
    const stripped = stripComments(readFileSync(path.join(import.meta.dirname, file), "utf8"));
    const lines = stripped.split("\n");
    for (const rule of RULES) {
      if (rule.allowed.includes(file)) continue;
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line === undefined) continue;
        if (rule.pattern.test(line)) violations.push(`${file}:${i + 1}: ${rule.api}`);
      }
    }
  }
  return violations.sort();
}

test("file writes go through the atomic seam (atomicWriteFileSync in substrate/cache.ts)", () => {
  const files = productionFiles();
  // Self-checks: a future path/layout change that silently empties the scan must fail loudly
  // instead of passing vacuously.
  assert.ok(files.length > 0, "production-file scan came up empty — guard is vacuous");
  assert.ok(
    files.includes("substrate/cache.ts"),
    "scan missed substrate/cache.ts — guard is misaimed",
  );
  assert.ok(files.includes("index.ts"), "scan missed index.ts — guard is misaimed");

  // Non-vacuous pattern checks: the seam's own body carries the banned call (the helper writes
  // the temp file via writeFileSync), and the documented append exemption really appends.
  const cacheSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "substrate", "cache.ts"), "utf8"),
  );
  assert.ok(
    /\bwriteFileSync\(/.test(cacheSource),
    "substrate/cache.ts no longer matches writeFileSync( — guard is vacuous",
  );
  const workerSource = stripComments(
    readFileSync(path.join(import.meta.dirname, "worker", "stageExecution.ts"), "utf8"),
  );
  assert.ok(
    /\bappendFileSync\(/.test(workerSource),
    "worker/stageExecution.ts no longer matches appendFileSync( — guard is vacuous",
  );

  const violations = violationsOf(files);
  assert.deepEqual(
    violations,
    [],
    "bare fs write call outside the per-API allowlist — use atomicWriteFileSync from " +
      "substrate/cache.ts (torn-write-proof); a genuinely exempt writer gets a justified " +
      "allowlist entry in writeGuard.test.ts:\n" +
      violations.join("\n"),
  );
});
