// Node 1.1 (objective #339) — the TS-plane ULID mint. The grammar assertions here are the
// cross-plane validity proof: spec-conformant ULIDs are exactly what `perk/state/run_id.py`'s
// `ULID.from_str` parses (decision: no node-subprocess pytest).

import assert from "node:assert/strict";
import { test } from "node:test";
import { CROCKFORD, decodeTime, mintRunId } from "./runId.ts";

// Exactly the Crockford base32 set — no I/L/O/U — and exactly 26 chars.
const ULID_RE = /^[0-9A-HJKMNP-TV-Z]{26}$/;

test("mintRunId emits a 26-char Crockford base32 ULID", () => {
  const id = mintRunId();
  assert.match(id, ULID_RE);
  for (const ch of id) {
    assert.ok(CROCKFORD.includes(ch), `character ${ch} not in the Crockford alphabet`);
  }
});

test("decodeTime(mintRunId()) is within a small window of Date.now()", () => {
  const before = Date.now();
  const decoded = decodeTime(mintRunId());
  const after = Date.now();
  assert.ok(decoded >= before && decoded <= after, `${decoded} not in [${before}, ${after}]`);
});

test("mintRunId is unique over a few hundred mints", () => {
  const ids = new Set<string>();
  for (let i = 0; i < 500; i++) ids.add(mintRunId());
  assert.equal(ids.size, 500);
});

test("two mints in the same millisecond differ (randomness component)", () => {
  // Mint a burst quickly; at least one same-ms pair is virtually guaranteed, and every
  // pair must differ regardless (the 80-bit randomness tail).
  const a = mintRunId();
  const b = mintRunId();
  assert.notEqual(a, b);
  if (decodeTime(a) === decodeTime(b)) {
    assert.equal(a.slice(0, 10), b.slice(0, 10));
    assert.notEqual(a.slice(10), b.slice(10));
  }
});

test("decodeTime rejects non-Crockford characters", () => {
  assert.throws(() => decodeTime("ILOU567890ABCDEFGHJKMNPQRS"));
});
