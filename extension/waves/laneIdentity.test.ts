// The routing-token fence's matrix: one exhaustive test per refused character class (every code
// point in each range, never a sample), each refused token asserted on BOTH exports — the
// predicate returns false AND the render helper throws with its EXACT message — plus the accepted
// set pinning the identity property (`renderRoutingToken(t) === t`) over routing-safe tokens that
// are hostile to everything else (run-key charset, length, shell/template syntax), including the
// range-boundary neighbors on both sides of every refused range.
//
// Throw messages are matched by exact string equality, never a `.*` regex: `JSON.stringify` leaves
// U+2028/U+2029 (and DEL/C1) as literal characters, and ECMAScript's `.` without the `s` flag does
// not match the line terminators U+2028/U+2029 — a dot-based matcher would fail those two classes
// even against a correct implementation.

import assert from "node:assert/strict";
import { test } from "node:test";
import { isRoutingToken, renderRoutingToken } from "./laneIdentity.ts";

function expectedMessage(token: string): string {
  return `renderRoutingToken: routing token ${JSON.stringify(token)} failed the fence — refuse or degrade it upstream`;
}

/** Assert one token is refused by the predicate AND thrown by the render helper (exact message). */
function assertRefused(token: string, why: string): void {
  assert.equal(isRoutingToken(token), false, `must refuse (${why}): ${JSON.stringify(token)}`);
  assert.throws(() => renderRoutingToken(token), { message: expectedMessage(token) });
}

/** Assert one token is admitted by the predicate AND rendered byte-identical (the identity). */
function assertAccepted(token: string, why: string): void {
  assert.equal(isRoutingToken(token), true, `must accept (${why}): ${JSON.stringify(token)}`);
  assert.equal(renderRoutingToken(token), token, `identity (${why})`);
}

// ------------------------------------------------------------------------ refused classes

test("isRoutingToken/renderRoutingToken: the empty token is refused", () => {
  assertRefused("", "empty");
});

test("isRoutingToken/renderRoutingToken: every C0 control U+0000–U+001F is refused, at any position", () => {
  for (let code = 0x00; code <= 0x1f; code += 1) {
    const ch = String.fromCharCode(code);
    assertRefused(`pi-${ch}1`, `C0 U+${code.toString(16).padStart(4, "0")} mid-token`);
  }
  // Position independence: a newline at the START and at the END of an otherwise-safe token.
  assertRefused("\npi-1", "U+000A at the start");
  assertRefused("pi-1\n", "U+000A at the end");
});

test("isRoutingToken/renderRoutingToken: DEL U+007F is refused", () => {
  assertRefused("pi-\u007f1", "DEL");
});

test("isRoutingToken/renderRoutingToken: every C1 control U+0080–U+009F is refused (NEL U+0085 included)", () => {
  for (let code = 0x80; code <= 0x9f; code += 1) {
    const ch = String.fromCharCode(code);
    assertRefused(`pi-${ch}1`, `C1 U+${code.toString(16).padStart(4, "0")}`);
  }
  assertRefused("pi-\u00851", "NEL U+0085 explicitly");
});

test("isRoutingToken/renderRoutingToken: the line separator U+2028 is refused", () => {
  assertRefused("pi-\u20281", "U+2028");
});

test("isRoutingToken/renderRoutingToken: the paragraph separator U+2029 is refused", () => {
  assertRefused("pi-\u20291", "U+2029");
});

test('isRoutingToken/renderRoutingToken: the double quote `"` is refused, mid-token and alone', () => {
  assertRefused('pi-"1', "double quote mid-token");
  assertRefused('"', "double quote as the whole token");
});

// ----------------------------------------------------------------- accepted (the identity)

test("isRoutingToken/renderRoutingToken: accepted tokens render byte-identical (the identity), with no length bound", () => {
  const accepted: [string, string][] = [
    ["pi-1", "a harvest id"],
    ["workflow-1", "a harvest id"],
    ["plan.grill-before-review", "an audit expectation id"],
    ["a b", "a space (run-key-hostile, routing-safe)"],
    ["@@weird lane", "leading `@` + a space (run-key-hostile, routing-safe)"],
    ["weird id/\u2603:so@hostile", "`/`, `☃`, `:`, `@` (run-key-hostile, routing-safe)"],
    ["x/y:z", "path/colon punctuation"],
    ["it's", "a single quote"],
    ["`pi-1`", "a backtick-wrapped token"],
    // biome-ignore lint/suspicious/noTemplateCurlyInString: the literal `${expr}` text is the point
    ["${expr}", "template-literal syntax as plain text"],
    ["x".repeat(300), "a 300-char token — no length bound"],
    ["\u{1F600}-1", "an astral character (two surrogate code units, neither in a refused range)"],
    // Range-boundary neighbors: the refused ranges are exact on both sides.
    ["pi-\u00201", "U+0020 space — the neighbor above C0"],
    ["pi-\u007e1", "U+007E `~` — the neighbor below DEL"],
    ["pi-\u00a01", "U+00A0 NBSP — the neighbor above C1"],
    ["pi-\u20271", "U+2027 — the neighbor below U+2028"],
    ["pi-\u202a1", "U+202A — the neighbor above U+2029"],
  ];
  for (const [token, why] of accepted) {
    assertAccepted(token, why);
  }
});
