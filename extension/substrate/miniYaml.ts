// A deliberately minimal YAML-subset reader for perk's OWN bundled contract files only
// (`shared/{registry,bindings,providers}.yaml`) — this is NOT a general-purpose YAML parser.
//
// Why this exists: pi loads the perk extension from a git-package clone whose imports resolve
// through a FIXED host-alias set (`@earendil-works/pi-*`, `typebox`) plus native `node_modules`
// walking. The extension must therefore be SELF-CONTAINED — zero runtime npm deps: a bare
// `import { parse } from "yaml"` would only resolve if pi's `npm install --omit=dev` happened to
// install it, which is fragile (and perk pre-materializes the clone with a plain `git
// clone` and NO `npm install` at all, so the clone has no `node_modules` to resolve against). This
// reader replaces the lone non-host runtime import (`yaml`) with Node builtins only — NO bare npm
// imports — so the extension loads from a bare git checkout regardless of whether any install ran.
//
// Scope (the bounded feature surface across the three shipped files):
//   - block mappings (indentation-nested) and block sequences (`- item`, incl. `- id: x`
//     map-as-sequence-item),
//   - flow mappings `{ k: v, ... }` and flow sequences `[a, b]` / `[]`,
//   - scalars: integers, `true`/`false`, `null`, bare strings, double-quoted strings (whose
//     contents may contain `:` / `@` / `/`, and where a `#` is NOT a comment), and the folded
//     block scalar `>` used by source-bound package skill frontmatter,
//   - trailing `#` comments (outside double quotes), whole-line `#` comments, and blank lines.
//
// Explicitly UNSUPPORTED (and made to throw loudly rather than silently mis-parse): YAML
// anchors/aliases (`&`/`*`), literal block scalars (`|`), single-quoted strings, `~` null,
// floats, and multi-document `---`/`...` streams. An unsupported future edit fails CI loudly.
//
// Fidelity to the reference `yaml` library is pinned by `miniYaml.test.ts`, which deep-equals this
// reader's output against `yaml.parse` for all three bundled files (the `yaml` lib is a dev-only
// dependency that powers that test and never ships in the consumer git clone). This reader is the
// twin of the Python plane's `pyyaml`-based readers in `perk/substrate/{registry,bindings,providers}.py`.

interface Line {
  indent: number;
  text: string;
}

interface Cursor {
  i: number;
}

/** Strip a trailing `#` comment, honoring double-quoted strings (a `#` inside a quote is literal). */
function stripComment(line: string): string {
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"' && (i === 0 || line[i - 1] !== "\\")) {
      inQuote = !inQuote;
    } else if (c === "#" && !inQuote && (i === 0 || /\s/.test(line[i - 1] ?? ""))) {
      return line.slice(0, i);
    }
  }
  return line;
}

/** Split raw text into comment-stripped, blank-free logical lines with their indentation depth. */
function preprocess(text: string): Line[] {
  const out: Line[] = [];
  for (const raw of text.split("\n")) {
    const stripped = stripComment(raw);
    if (stripped.trim() === "") continue;
    const indent = stripped.length - stripped.trimStart().length;
    const body = stripped.slice(indent).trimEnd();
    if (body === "---" || body === "...") {
      throw new Error("perk miniYaml: multi-document streams (`---`/`...`) are not supported");
    }
    out.push({ indent, text: body });
  }
  return out;
}

/**
 * Index of the first `:` that delimits a key from a value: not inside double quotes, not inside a
 * flow collection, and followed by whitespace or end-of-string. Returns -1 if there is none.
 */
function findColon(s: string): number {
  let inQuote = false;
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '"' && (i === 0 || s[i - 1] !== "\\")) {
      inQuote = !inQuote;
    } else if (!inQuote && (c === "{" || c === "[")) {
      depth++;
    } else if (!inQuote && (c === "}" || c === "]")) {
      depth--;
    } else if (c === ":" && !inQuote && depth === 0) {
      const next = s[i + 1];
      if (next === undefined || /\s/.test(next)) return i;
    }
  }
  return -1;
}

/** Split `key: value` at the delimiting colon into trimmed `[key, value]`. */
function splitKeyValue(text: string): [string, string] {
  const idx = findColon(text);
  if (idx === -1) return [text.trim(), ""];
  return [text.slice(0, idx).trim(), text.slice(idx + 1).trim()];
}

/** Split a flow body on top-level commas (honoring quotes and nested flow collections). */
function splitTopLevel(s: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let inQuote = false;
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '"' && (i === 0 || s[i - 1] !== "\\")) {
      inQuote = !inQuote;
      cur += c;
    } else if (!inQuote && (c === "{" || c === "[")) {
      depth++;
      cur += c;
    } else if (!inQuote && (c === "}" || c === "]")) {
      depth--;
      cur += c;
    } else if (c === "," && !inQuote && depth === 0) {
      parts.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  if (cur.trim() !== "") parts.push(cur);
  return parts;
}

/** Unescape the minimal set of double-quoted escapes that the reference parser would process. */
function unescapeDoubleQuoted(inner: string): string {
  return inner.replace(/\\(["\\nt])/g, (_m, ch) => {
    if (ch === "n") return "\n";
    if (ch === "t") return "\t";
    return ch; // `\"` -> `"`, `\\` -> `\`
  });
}

/** Type a leaf scalar token to match `yaml.parse`. Throws on an unsupported construct. */
function parseScalar(token: string): unknown {
  const t = token.trim();
  if (t === "") return null;
  if (t.startsWith('"')) {
    if (!t.endsWith('"') || t.length < 2) {
      throw new Error(`perk miniYaml: malformed double-quoted scalar: ${token}`);
    }
    return unescapeDoubleQuoted(t.slice(1, -1));
  }
  if (t.startsWith("'")) {
    throw new Error("perk miniYaml: single-quoted strings are not supported");
  }
  if (t.startsWith("&") || t.startsWith("*")) {
    throw new Error("perk miniYaml: anchors/aliases (`&`/`*`) are not supported");
  }
  if (t === "~" || /^[|>][+-]?\d*$/.test(t)) {
    throw new Error(`perk miniYaml: unsupported scalar/block construct: ${token}`);
  }
  if (t === "true") return true;
  if (t === "false") return false;
  if (t === "null") return null;
  if (/^-?\d+$/.test(t)) return Number(t);
  return t;
}

/** Parse a value that may be a flow collection or a leaf scalar. */
function parseFlowOrScalar(token: string): unknown {
  const t = token.trim();
  if (t.startsWith("{")) return parseFlowMapping(t);
  if (t.startsWith("[")) return parseFlowSequence(t);
  return parseScalar(t);
}

function parseFlowMapping(s: string): Record<string, unknown> {
  if (!s.endsWith("}")) throw new Error(`perk miniYaml: unterminated flow mapping: ${s}`);
  const map: Record<string, unknown> = {};
  for (const part of splitTopLevel(s.slice(1, -1))) {
    const [key, value] = splitKeyValue(part.trim());
    if (key === "") continue;
    map[key] = parseFlowOrScalar(value);
  }
  return map;
}

function parseFlowSequence(s: string): unknown[] {
  if (!s.endsWith("]")) throw new Error(`perk miniYaml: unterminated flow sequence: ${s}`);
  return splitTopLevel(s.slice(1, -1)).map((part) => parseFlowOrScalar(part.trim()));
}

function isDash(text: string): boolean {
  return text === "-" || text.startsWith("- ");
}

/** Parse a block node (mapping or sequence) whose content lives at column `indent`. */
function parseNode(lines: Line[], cursor: Cursor, indent: number): unknown {
  const first = lines[cursor.i];
  if (first === undefined) return null;
  if (isDash(first.text)) return parseSequence(lines, cursor, indent);
  return parseMapping(lines, cursor, indent);
}

function parseMapping(lines: Line[], cursor: Cursor, indent: number): Record<string, unknown> {
  const map: Record<string, unknown> = {};
  while (cursor.i < lines.length) {
    const line = lines[cursor.i];
    if (line === undefined || line.indent !== indent) break;
    const [key, rest] = splitKeyValue(line.text);
    cursor.i++;
    if (rest === "") {
      const next = lines[cursor.i];
      if (next !== undefined && next.indent > indent) {
        map[key] = parseNode(lines, cursor, next.indent);
      } else {
        map[key] = null;
      }
    } else if (rest === ">") {
      const folded: string[] = [];
      while (cursor.i < lines.length) {
        const continuation = lines[cursor.i];
        if (continuation === undefined || continuation.indent <= indent) break;
        folded.push(continuation.text.trim());
        cursor.i++;
      }
      map[key] = folded.join(" ");
    } else {
      map[key] = parseFlowOrScalar(rest);
    }
  }
  return map;
}

function parseSequence(lines: Line[], cursor: Cursor, indent: number): unknown[] {
  const arr: unknown[] = [];
  while (cursor.i < lines.length) {
    const line = lines[cursor.i];
    if (line === undefined || line.indent !== indent || !isDash(line.text)) break;
    const after = line.text === "-" ? "" : line.text.slice(2);
    if (after === "") {
      cursor.i++;
      const next = lines[cursor.i];
      if (next !== undefined && next.indent > indent) {
        arr.push(parseNode(lines, cursor, next.indent));
      } else {
        arr.push(null);
      }
    } else if (findColon(after) !== -1) {
      // A mapping as a sequence item (`- id: x` + deeper-indented continuation keys). Rewrite the
      // dash line into a plain mapping line at the content column, then parse the whole mapping.
      const contentIndent = indent + 2;
      lines[cursor.i] = { indent: contentIndent, text: after };
      arr.push(parseMapping(lines, cursor, contentIndent));
    } else {
      cursor.i++;
      arr.push(parseFlowOrScalar(after));
    }
  }
  return arr;
}

/**
 * Parse a YAML-subset document into a `yaml.parse`-equivalent JS value graph. Same call shape as
 * `yaml`'s `parse`. Throws a clear `Error` on any construct outside the supported surface.
 */
export function parse(text: string): unknown {
  const lines = preprocess(text);
  if (lines.length === 0) return null;
  const cursor: Cursor = { i: 0 };
  const result = parseNode(lines, cursor, lines[0]?.indent ?? 0);
  if (cursor.i !== lines.length) {
    throw new Error(
      `perk miniYaml: unexpected content at line ${cursor.i + 1} (indentation not understood)`,
    );
  }
  return result;
}
