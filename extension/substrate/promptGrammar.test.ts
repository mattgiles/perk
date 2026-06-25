// Conformance guard: every `prompts/` template stays inside the frozen mini-jinja subset.
//
// The frozen template-grammar subset (the SSOT is `shared/contracts.md §8.31`) is exactly:
//   1. Variable substitution `{{ <ident> }}` (bare identifier only).
//   2. Include `{% include "<path>" %}` (double-quoted path).
//   3. Conditionals `{% if/elif <cond> %}` / `{% else %}` / `{% endif %}`, where `<cond>` is built
//      only from bare identifiers, double-quoted strings, `==`, and `and`/`or`/`not`.
//   4. Plain `{% %}` tags only (no `{%- … -%}` / `{{- … -}}` whitespace-control markers).
//
// Allowlist posture: extract every `{{ … }}` / `{% … %}` / `{# … #}` block and fail on any block
// matching no recognized construct — mirroring the node-4.2 vendored renderer's
// throw-loudly-on-anything-unsupported discipline. Construct membership only, not if/endif nesting
// balance (proven by the golden harness). Test-only tooling (like surfacesGuard.test.ts), not
// runtime code.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { promptsDir } from "./resources.ts";

// `{{ … }}`, `{% … %}`, or `{# … #}` block, captured non-greedily (blocks never span lines).
// Comments are matched only so the guard can REJECT them (not in the frozen subset).
const BLOCK = /\{\{(.*?)\}\}|\{%(.*?)%\}|\{#(.*?)#\}/g;

// A bare identifier — the only thing admitted inside `{{ }}` and the atom of a condition.
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const IDENT_G = /[A-Za-z_][A-Za-z0-9_]*/g;

// `include "<path>"` — double-quoted path only.
const INCLUDE = /^include\s+"[^"]*"$/;

// A whole `if`/`elif` condition: one-or-more of {identifier, double-quoted string, `==`} separated
// by whitespace. Anything else (parens, `!=`, `<`/`>`, filters, dots, numbers) → no full match.
const COND = /^(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*|"[^"]*"|==)\s*)+$/;

// Bare-word tokens that LOOK like identifiers but are jinja operators outside the frozen subset.
// (The admitted keywords are exactly `and`/`or`/`not`; every other bare word is a variable name.)
const BANNED_COND_WORDS = new Set(["in", "is"]);

/** True iff one extracted block (without its delimiters) is in the frozen subset. */
function blockIsValid(raw: string, isVariable: boolean): boolean {
  const inner = raw.trim();
  if (isVariable) {
    // `{{ X }}`: X must be a single bare identifier (catches `{{- x -}}`, dots, filters, …).
    return IDENT.test(inner);
  }
  // `{% X %}` (catches `{%- … -%}` since the leading `-` breaks every branch below).
  if (inner === "else" || inner === "endif") return true;
  if (INCLUDE.test(inner)) return true;
  for (const keyword of ["if ", "elif "]) {
    if (inner.startsWith(keyword)) {
      const cond = inner.slice(keyword.length).trim();
      if (cond === "" || !COND.test(cond)) return false;
      // Reject `in`/`is` operators (lexically identifiers) outside string literals.
      const words = cond.replace(/"[^"]*"/g, " ").match(IDENT_G) ?? [];
      return !words.some((word) => BANNED_COND_WORDS.has(word));
    }
  }
  return false;
}

/** Collect `path:line: <block>` violations in one template's source. */
function violations(text: string, rel: string): string[] {
  const out: string[] = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line === undefined) continue;
    for (const match of line.matchAll(BLOCK)) {
      const comment = match[3];
      if (comment !== undefined) {
        // `{# … #}` comment — never in the subset.
        out.push(`${rel}:${i + 1}: ${match[0]}`);
        continue;
      }
      const isVariable = match[1] !== undefined;
      const inner = isVariable ? match[1] : match[2];
      if (inner === undefined) continue;
      if (!blockIsValid(inner, isVariable)) out.push(`${rel}:${i + 1}: ${match[0]}`);
    }
  }
  return out;
}

/** Every rendered `prompts/` template: (relative-path, text), README.md excluded. */
function templateFiles(): { rel: string; text: string }[] {
  const root = promptsDir();
  const entries = readdirSync(root, { recursive: true }) as string[];
  return entries
    .map((entry) => entry.split(path.sep).join("/"))
    .filter((entry) => entry.endsWith(".md") && entry !== "README.md")
    .sort()
    .map((rel) => ({ rel, text: readFileSync(path.join(root, rel), "utf8") }));
}

test("prompt-template scan is not vacuous", () => {
  const rels = new Set(templateFiles().map((f) => f.rel));
  assert.ok(rels.size > 0, "prompt-template scan came up empty — guard is vacuous");
  for (const anchor of [
    "stages/learn.md",
    "stages/objective-plan/seed.md",
    "common/plan-read/github.md",
    "_fixtures/templates/with_include.md",
  ]) {
    assert.ok(rels.has(anchor), `scan missed ${anchor} — guard is misaimed`);
  }
  assert.ok(!rels.has("README.md"), "README.md must be excluded from the grammar scan");
});

test("all templates stay inside the frozen mini-jinja subset", () => {
  const found = templateFiles().flatMap((f) => violations(f.text, f.rel));
  assert.deepEqual(
    found,
    [],
    "prompt template(s) use constructs outside the frozen mini-jinja subset:\n" +
      `${found.join("\n")}\n` +
      "See the frozen template-grammar subset in shared/contracts.md §8.31.",
  );
});

test("validator flags out-of-subset blocks", () => {
  const bad = [
    "{% for x in y %}",
    "{% endfor %}",
    "{% set a = 1 %}",
    "{{ user.name }}",
    "{{ x | upper }}",
    "{%- if a -%}",
    "{{- x -}}",
    "{% if a in b %}",
    "{% if a != b %}",
    "{% if (a or b) %}",
    "{# comment #}",
  ];
  for (const block of bad) {
    assert.ok(violations(block, "synthetic.md").length > 0, `expected violation for ${block}`);
  }
});

test("validator accepts in-subset blocks", () => {
  const good = [
    "{{ provider }}",
    "{{ pr_id }}",
    '{% if provider == "github" or provider == "linear" %}',
    "{% if not pr_id %}",
    "{% if a and b %}",
    "{% elif model %}",
    "{% else %}",
    "{% endif %}",
    '{% include "_fixtures/templates/_greeting.md" %}',
  ];
  for (const block of good) {
    assert.deepEqual(violations(block, "synthetic.md"), [], `unexpected violation for ${block}`);
  }
});
