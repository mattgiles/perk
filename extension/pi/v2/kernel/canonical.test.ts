// Canonical JSON, the text predicate, the JSON boundary check and sha256
// (docs/design/pi-durable-v2-foundations.md §4: canonical JSON is RFC 8785, no whitespace). The
// expected texts are literals; the hash vectors are the published sha256 test vectors.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  asJsonValue,
  canonicalJson,
  isLowerHex,
  isWellFormedText,
  type JsonValue,
  jsonEquals,
  sha256Hex,
} from "./canonical.ts";

test("canonicalJson sorts keys by UTF-16 code units, recursively, with no whitespace", () => {
  assert.equal(
    canonicalJson({ z: 1, é: [true, null, "x"], a: { c: 1.5, b: -0 } }),
    '{"a":{"b":0,"c":1.5},"z":1,"é":[true,null,"x"]}',
  );
  assert.equal(canonicalJson([]), "[]");
  assert.equal(canonicalJson({}), "{}");
  assert.equal(canonicalJson('quote " and \\ and \n'), '"quote \\" and \\\\ and \\n"');
});

test("canonicalJson renders numbers the ECMAScript way", () => {
  assert.equal(canonicalJson(1e21), "1e+21");
  assert.equal(canonicalJson(-0), "0");
  assert.equal(canonicalJson(0.1), "0.1");
  assert.equal(canonicalJson(1e-7), "1e-7");
});

/** Feed a value outside the JSON type to `canonicalJson` (the runtime check under test). */
function canonicalOf(value: unknown): string {
  return canonicalJson(value as JsonValue);
}

test("canonicalJson throws TypeError outside the JSON domain", () => {
  for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
    assert.throws(() => canonicalJson(value), TypeError);
  }
  assert.throws(() => canonicalJson("a\uD800b"), TypeError, "lone surrogate in a value");
  assert.throws(() => canonicalJson({ "\uDC00": 1 }), TypeError, "lone surrogate in a key");
  const cyclic: { self?: unknown } = {};
  cyclic.self = cyclic;
  assert.throws(() => canonicalOf(cyclic), TypeError, "a cycle");
  assert.throws(() => canonicalOf(new Map()), TypeError, "a Map");
  assert.throws(() => canonicalOf({ a: undefined }), TypeError, "an undefined member");
});

test("isWellFormedText accepts paired surrogates and rejects lone or reversed ones", () => {
  for (const value of ["", "ascii", "\u{1F600}", "é\u{1F600}x"]) {
    assert.equal(isWellFormedText(value), true, JSON.stringify(value));
  }
  for (const value of ["\uD800", "\uDC00", "a\uD800b", "\uDE00\uD83D"]) {
    assert.equal(isWellFormedText(value), false, JSON.stringify(value));
  }
});

class Point {
  x = 1;
}

test("asJsonValue accepts JSON values and returns null for everything else", () => {
  const accepted: unknown[] = [
    true,
    0,
    -1.5,
    "",
    "\u{1F600}",
    [],
    [1, "a", null, [{}]],
    {},
    { a: { b: [1, 2] }, "\u{1F600}": "x" },
    Object.assign(Object.create(null), { k: 1 }),
  ];
  for (const value of accepted) {
    const json = asJsonValue(value);
    assert.notEqual(json, null, `accepted: ${String(JSON.stringify(value))}`);
    if (json !== null) assert.doesNotThrow(() => canonicalJson(json));
  }
  // `null` is itself a JSON value; the boundary returns it unchanged.
  assert.equal(asJsonValue(null), null);
  const shared = { v: 1 };
  assert.notEqual(asJsonValue([shared, shared]), null, "a shared (non-cyclic) reference");

  const cyclic: unknown[] = [];
  cyclic.push(cyclic);
  const holey: unknown[] = [1];
  holey[2] = 3;
  const rejected: [string, unknown][] = [
    ["undefined", undefined],
    ["an undefined member", { a: undefined }],
    ["an array hole", holey],
    ["a function", () => 1],
    ["a symbol", Symbol("s")],
    ["a symbol key", { [Symbol("s")]: 1 }],
    ["a bigint", 1n],
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["a Date", new Date(0)],
    ["a Map", new Map()],
    ["a class instance", new Point()],
    ["a cycle", cyclic],
    ["a lone surrogate value", { a: "\uD800" }],
    ["a lone surrogate key", { "\uD800": 1 }],
  ];
  for (const [label, value] of rejected) {
    assert.equal(asJsonValue(value), null, label);
  }
});

test("jsonEquals compares canonical forms", () => {
  assert.equal(jsonEquals({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 }), true);
  assert.equal(jsonEquals({ a: [1, 2] }, { a: [2, 1] }), false);
  assert.equal(jsonEquals({ a: 0 }, { a: -0 }), true);
});

test("sha256Hex matches the published vectors", () => {
  assert.equal(sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(
    sha256Hex("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
});

test("isLowerHex checks length and case", () => {
  assert.equal(isLowerHex("0a1b", 4), true);
  assert.equal(isLowerHex("0A1B", 4), false);
  assert.equal(isLowerHex("0a1", 4), false);
  assert.equal(isLowerHex("0a1g", 4), false);
});
