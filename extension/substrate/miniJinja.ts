// A deliberately minimal Jinja-subset renderer for perk's OWN bundled prompt templates only
// (`prompts/**`) — this is NOT a general-purpose template engine.
//
// Why this exists: pi loads the perk extension from a git-package clone whose imports resolve
// through a FIXED host-alias set (`@earendil-works/pi-*`, `typebox`) plus native `node_modules`
// walking. The extension must therefore be SELF-CONTAINED — zero runtime npm deps: a bare
// `import nunjucks from "nunjucks"` would only resolve if pi's `npm install --omit=dev` happened
// to install it, which is fragile (and perk pre-materializes the clone with a plain `git clone`
// and NO `npm install` at all, so the clone has no `node_modules` to resolve against). This
// renderer replaces the lone non-host runtime import (`nunjucks`) with Node builtins only — NO
// bare npm imports — so the extension loads from a bare git checkout regardless of whether any
// install ran. The bare-import invariant is durably guarded by `extension/bareImportGuard.test.ts`.
//
// Scope — exactly the frozen "mini-jinja" subset (SSOT: `shared/contracts.md §8.31`):
//   1. `{{ <ident> }}` variable substitution, identifier matching `^[A-Za-z_][A-Za-z0-9_]*$` only.
//   2. `{% include "<path>" %}`, double-quoted root-relative path only.
//   3. `{% if <cond> %}` / `{% elif <cond> %}` / `{% else %}` / `{% endif %}`, where `<cond>` is
//      built only from bare identifiers (truthiness), double-quoted string literals, `==`, and the
//      keywords `and` / `or` / `not` (precedence `or` < `and` < `not` < `==`).
//   4. Plain `{% %}` tags only — `{%- … -%}` / `{{- … -}}` whitespace-control markers are NOT in
//      the subset; tag-line stripping rides the `trim_blocks` flag (baked in here, see below).
//
// Everything outside that surface is made to THROW loudly (prefix `perk mini-jinja:`) rather than
// silently mis-render: comments (`{# … #}`), loops (`for`/`endfor`), `set`/`macro`/`block`/
// `extends`/`raw`, filters (`|`), attribute access (`.`), `!=`/`<`/`>`/`in`/`is`, parentheses,
// numeric literals, and escaped string literals. An unsupported future template edit fails CI
// loudly (and the frozen-grammar guards in `promptGrammar.test.ts` / `test_prompt_grammar.py`
// catch it at author time too).
//
// The render contract is STRING-ONLY and faithful to jinja2 (`StrictUndefined`): a referenced
// name that is absent OR non-string THROWS (this deliberately tightens the looser nunjucks
// `throwOnUndefined`, forbidding a `String(value)` divergence — a future `false` must never render
// `"false"`). The frozen render config — `trim_blocks` on, `lstrip_blocks` off, trailing newline
// preserved — is BAKED IN; the subset is frozen, so there is no config object. jinja2
// (`perk/prompts.py`) remains the reference engine: the committed golden bytes under
// `prompts/_fixtures/golden/` ARE jinja2's output, and this renderer reproduces them byte-for-byte
// (proven by `prompts.test.ts`).

import { readFileSync } from "node:fs";
import { isAbsolute, resolve, sep } from "node:path";

import { promptsDir } from "./resources.ts";

const PFX = "perk mini-jinja:";
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

// ---------------------------------------------------------------------------
// Path containment
// ---------------------------------------------------------------------------

/**
 * Resolve a root-relative template `name` against `rootDir`, rejecting traversal. Guards BOTH the
 * top-level `render(name, …)` and every `{% include "<path>" %}`: reject empty / absolute / any
 * `..`-segment path, then defense-in-depth reject anything that does not stay within `rootDir`.
 */
function resolveTemplatePath(rootDir: string, name: string): string {
  if (name === "") throw new Error(`${PFX} empty template path`);
  if (isAbsolute(name)) throw new Error(`${PFX} absolute template path not allowed: ${name}`);
  if (name.split(/[\\/]/).includes("..")) {
    throw new Error(`${PFX} '..' segment not allowed in template path: ${name}`);
  }
  const root = resolve(rootDir);
  const full = resolve(root, name);
  if (full !== root && !full.startsWith(root + sep)) {
    throw new Error(`${PFX} template path escapes the prompts root: ${name}`);
  }
  return full;
}

// ---------------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------------

type Token =
  | { kind: "text"; value: string }
  | { kind: "var"; name: string }
  | { kind: "block"; inner: string };

/**
 * Scan the template source for `{{ }}`, `{% %}`, and `{# #}` markers. `{# #}` throws (comments are
 * outside the subset). A `{{ }}` must hold a single bare identifier. A `{% %}` keeps its trimmed
 * inner text for the parser. trim_blocks: the single `\n` immediately following a block tag's `%}`
 * is consumed so it never enters the following literal.
 */
function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  let text = "";
  let i = 0;
  const flushText = () => {
    if (text !== "") {
      tokens.push({ kind: "text", value: text });
      text = "";
    }
  };
  while (i < src.length) {
    const two = src.slice(i, i + 2);
    if (two === "{#") {
      throw new Error(`${PFX} comments ({# … #}) are not supported`);
    }
    if (two === "{{" || two === "{%") {
      flushText();
      const close = two === "{{" ? "}}" : "%}";
      const end = src.indexOf(close, i + 2);
      if (end === -1) throw new Error(`${PFX} unterminated ${two} tag`);
      const inner = src.slice(i + 2, end);
      if (inner.includes("-")) {
        // Cheap pre-check for whitespace-control markers ({%- … -%} / {{- … -}}); a real `-`
        // never appears elsewhere in the subset (idents, the few string literals, `==`).
        const t = inner.trim();
        if (t.startsWith("-") || t.endsWith("-")) {
          throw new Error(
            `${PFX} whitespace-control markers ({%- … -%} / {{- … -}}) are not supported`,
          );
        }
      }
      if (two === "{{") {
        const name = inner.trim();
        if (!IDENT.test(name)) {
          throw new Error(
            `${PFX} only a bare identifier is allowed in {{ … }}: ${JSON.stringify(inner)}`,
          );
        }
        tokens.push({ kind: "var", name });
        i = end + 2;
      } else {
        tokens.push({ kind: "block", inner: inner.trim() });
        i = end + 2;
        if (src[i] === "\n") i++; // trim_blocks
      }
      continue;
    }
    text += two.charAt(0);
    i += 1;
  }
  flushText();
  return tokens;
}

// ---------------------------------------------------------------------------
// Condition lexer / parser / evaluator
// ---------------------------------------------------------------------------

type CTok =
  | { t: "id"; v: string }
  | { t: "str"; v: string }
  | { t: "eq" }
  | { t: "and" }
  | { t: "or" }
  | { t: "not" };

/**
 * Lex a condition string into atoms {identifier, double-quoted string (no escapes), `==`,
 * `and`/`or`/`not`}. Any other character (parens, `!`, `<`, `>`, `|`, `.`, digits, a `\` in a
 * string) throws — the runtime double-guard of the frozen subset. `in`/`is` lex as identifiers and
 * are rejected later by the parser (adjacent-atom error).
 */
function lexCond(s: string): CTok[] {
  const toks: CTok[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === undefined) break;
    if (/\s/.test(c)) {
      i += 1;
      continue;
    }
    if (c === '"') {
      let j = i + 1;
      let v = "";
      while (j < s.length && s[j] !== '"') {
        if (s[j] === "\\") {
          throw new Error(`${PFX} escapes are not supported in a string literal: ${s.slice(i)}`);
        }
        v += s[j];
        j += 1;
      }
      if (j >= s.length) throw new Error(`${PFX} unterminated string literal in condition: ${s}`);
      toks.push({ t: "str", v });
      i = j + 1;
      continue;
    }
    if (c === "=") {
      if (s[i + 1] === "=") {
        toks.push({ t: "eq" });
        i += 2;
        continue;
      }
      throw new Error(
        `${PFX} unsupported operator in condition (only '==' is allowed): ${s.slice(i)}`,
      );
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < s.length) {
        const cj = s[j];
        if (cj === undefined || !/[A-Za-z0-9_]/.test(cj)) break;
        j += 1;
      }
      const word = s.slice(i, j);
      if (word === "and" || word === "or" || word === "not") toks.push({ t: word });
      else toks.push({ t: "id", v: word });
      i = j;
      continue;
    }
    throw new Error(`${PFX} unsupported token in condition: ${JSON.stringify(s.slice(i))}`);
  }
  return toks;
}

type CondNode =
  | { op: "or"; l: CondNode; r: CondNode }
  | { op: "and"; l: CondNode; r: CondNode }
  | { op: "not"; e: CondNode }
  | { op: "eq"; l: CondNode; r: CondNode }
  | { op: "id"; name: string }
  | { op: "str"; value: string };

interface Cursor {
  i: number;
}

// Recursive descent: precedence `or` < `and` < `not` < `==` < atom. Each level rejects malformed
// valid-token sequences (missing operand / adjacent atoms with no operator) by throwing.
function parseOr(toks: CTok[], p: Cursor): CondNode {
  let left = parseAnd(toks, p);
  while (toks[p.i]?.t === "or") {
    p.i += 1;
    left = { op: "or", l: left, r: parseAnd(toks, p) };
  }
  return left;
}

function parseAnd(toks: CTok[], p: Cursor): CondNode {
  let left = parseNot(toks, p);
  while (toks[p.i]?.t === "and") {
    p.i += 1;
    left = { op: "and", l: left, r: parseNot(toks, p) };
  }
  return left;
}

function parseNot(toks: CTok[], p: Cursor): CondNode {
  if (toks[p.i]?.t === "not") {
    p.i += 1;
    return { op: "not", e: parseNot(toks, p) };
  }
  return parseEq(toks, p);
}

function parseEq(toks: CTok[], p: Cursor): CondNode {
  const left = parseAtom(toks, p);
  if (toks[p.i]?.t === "eq") {
    p.i += 1;
    return { op: "eq", l: left, r: parseAtom(toks, p) };
  }
  return left;
}

function parseAtom(toks: CTok[], p: Cursor): CondNode {
  const tok = toks[p.i];
  if (tok === undefined) throw new Error(`${PFX} malformed condition (expected an operand)`);
  if (tok.t === "id") {
    p.i += 1;
    return { op: "id", name: tok.v };
  }
  if (tok.t === "str") {
    p.i += 1;
    return { op: "str", value: tok.v };
  }
  throw new Error(`${PFX} malformed condition (expected an operand, got an operator)`);
}

function parseCondition(raw: string): CondNode {
  const toks = lexCond(raw);
  const p: Cursor = { i: 0 };
  const node = parseOr(toks, p);
  if (p.i !== toks.length) {
    throw new Error(`${PFX} malformed condition (unexpected trailing token): ${raw}`);
  }
  return node;
}

/** String-only variable lookup: absent OR non-string throws (jinja2 StrictUndefined parity). */
function lookupString(name: string, vars: Record<string, unknown>): string {
  const value = vars[name];
  if (typeof value !== "string") {
    const what = value === undefined ? "is undefined" : "is not a string";
    throw new Error(
      `${PFX} variable ${JSON.stringify(name)} ${what} (the render contract is string-only)`,
    );
  }
  return value;
}

function atomValue(node: CondNode, vars: Record<string, unknown>): string {
  if (node.op === "id") return lookupString(node.name, vars);
  if (node.op === "str") return node.value;
  // Unreachable: `==` operands are always atoms (id/str) by construction in parseEq.
  throw new Error(`${PFX} internal: '==' operand is not an atom`);
}

function evalCondition(node: CondNode, vars: Record<string, unknown>): boolean {
  switch (node.op) {
    case "or":
      return evalCondition(node.l, vars) || evalCondition(node.r, vars);
    case "and":
      return evalCondition(node.l, vars) && evalCondition(node.r, vars);
    case "not":
      return !evalCondition(node.e, vars);
    case "eq":
      return atomValue(node.l, vars) === atomValue(node.r, vars);
    case "id":
      // Truthiness: a string is truthy iff non-empty (StrictUndefined on absent/non-string).
      return lookupString(node.name, vars) !== "";
    case "str":
      return node.value !== "";
  }
}

// ---------------------------------------------------------------------------
// Parser (token stream → node tree)
// ---------------------------------------------------------------------------

type RNode =
  | { kind: "text"; value: string }
  | { kind: "var"; name: string }
  | { kind: "include"; path: string }
  | { kind: "if"; branches: { cond: CondNode | null; body: RNode[] }[] };

const STOP = new Set(["elif", "else", "endif"]);

/** First leading-alpha word of a block's inner text (the tag keyword), or "" if none. */
function keyword(inner: string): string {
  const m = /^[A-Za-z_]+/.exec(inner);
  return m ? m[0] : "";
}

/** The condition text after a leading `if`/`elif` keyword (must be whitespace-separated). */
function conditionAfter(inner: string, kw: string): string {
  const rest = inner.slice(kw.length);
  if (!/^\s/.test(rest)) throw new Error(`${PFX} malformed {% ${kw} %}: ${inner}`);
  const cond = rest.trim();
  if (cond === "") throw new Error(`${PFX} empty condition in {% ${kw} %}`);
  return cond;
}

function parseInclude(inner: string): RNode {
  const m = /^include\s+"([^"\\]*)"$/.exec(inner);
  if (m === null) {
    throw new Error(`${PFX} malformed {% include %} (expected {% include "<path>" %}): ${inner}`);
  }
  return { kind: "include", path: m[1] ?? "" };
}

/** Parse a body up to (but not consuming) the next STOP keyword (elif/else/endif) or EOF. */
function parseBody(tokens: Token[], p: Cursor): RNode[] {
  const out: RNode[] = [];
  while (p.i < tokens.length) {
    const tok = tokens[p.i];
    if (tok === undefined) break;
    if (tok.kind === "text") {
      out.push({ kind: "text", value: tok.value });
      p.i += 1;
      continue;
    }
    if (tok.kind === "var") {
      out.push({ kind: "var", name: tok.name });
      p.i += 1;
      continue;
    }
    const kw = keyword(tok.inner);
    if (STOP.has(kw)) return out; // leave the stop token for the caller (parseIf / top-level)
    if (kw === "include") {
      out.push(parseInclude(tok.inner));
      p.i += 1;
      continue;
    }
    if (kw === "if") {
      out.push(parseIf(tokens, p));
      continue;
    }
    throw new Error(`${PFX} unsupported construct: {% ${tok.inner} %}`);
  }
  return out;
}

function parseIf(tokens: Token[], p: Cursor): RNode {
  const open = tokens[p.i];
  if (open === undefined || open.kind !== "block") {
    throw new Error(`${PFX} internal: parseIf called off an {% if %}`);
  }
  const ifCond = parseCondition(conditionAfter(open.inner, "if"));
  p.i += 1;
  const branches: { cond: CondNode | null; body: RNode[] }[] = [
    { cond: ifCond, body: parseBody(tokens, p) },
  ];
  let sawElse = false;
  for (;;) {
    const stop = tokens[p.i];
    if (stop === undefined || stop.kind !== "block") {
      throw new Error(`${PFX} unclosed {% if %} (missing {% endif %})`);
    }
    const kw = keyword(stop.inner);
    if (kw === "elif") {
      if (sawElse) throw new Error(`${PFX} {% elif %} after {% else %}`);
      const cond = parseCondition(conditionAfter(stop.inner, "elif"));
      p.i += 1;
      branches.push({ cond, body: parseBody(tokens, p) });
    } else if (kw === "else") {
      if (sawElse) throw new Error(`${PFX} duplicate {% else %}`);
      if (stop.inner !== "else") throw new Error(`${PFX} malformed {% else %}: ${stop.inner}`);
      sawElse = true;
      p.i += 1;
      branches.push({ cond: null, body: parseBody(tokens, p) });
    } else if (kw === "endif") {
      if (stop.inner !== "endif") throw new Error(`${PFX} malformed {% endif %}: ${stop.inner}`);
      p.i += 1;
      break;
    } else {
      throw new Error(`${PFX} unexpected {% ${stop.inner} %} inside {% if %}`);
    }
  }
  return { kind: "if", branches };
}

function parse(tokens: Token[]): RNode[] {
  const p: Cursor = { i: 0 };
  const nodes = parseBody(tokens, p);
  const leftover = tokens[p.i];
  if (leftover !== undefined) {
    // parseBody only returns early on a STOP keyword; reaching here means a stray elif/else/endif.
    const inner = leftover.kind === "block" ? leftover.inner : "";
    throw new Error(`${PFX} stray {% ${inner} %} without a matching {% if %}`);
  }
  return nodes;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function renderNodes(nodes: RNode[], vars: Record<string, unknown>, rootDir: string): string {
  let out = "";
  for (const node of nodes) {
    if (node.kind === "text") {
      out += node.value;
    } else if (node.kind === "var") {
      out += lookupString(node.name, vars);
    } else if (node.kind === "include") {
      out += render(node.path, vars, rootDir);
    } else {
      for (const branch of node.branches) {
        if (branch.cond === null || evalCondition(branch.cond, vars)) {
          out += renderNodes(branch.body, vars, rootDir);
          break;
        }
      }
    }
  }
  return out;
}

/**
 * Render the template at `name` (root-relative under `rootDir`) with `vars`. Mirrors the nunjucks
 * `Environment` + `FileSystemLoader` it replaced: the renderer owns the filesystem and resolves
 * `{% include %}` against the SAME `rootDir`. `rootDir` defaults to `promptsDir()` (the bundled
 * `prompts/`); the optional override keeps the renderer unit-testable against throwaway temp dirs.
 */
export function render(
  name: string,
  vars: Record<string, unknown>,
  rootDir: string = promptsDir(),
): string {
  const file = resolveTemplatePath(rootDir, name);
  const src = readFileSync(file, "utf8");
  return renderNodes(parse(tokenize(src)), vars, rootDir);
}
