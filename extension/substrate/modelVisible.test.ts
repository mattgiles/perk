// Fully-offline coverage for the model-visible cap helper (route-don't-relay): under/over cap,
// UTF-8 boundary safety, and the head/tail keep modes. See modelVisible.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { capForModel, DEFAULT_MODEL_VISIBLE_CAP } from "./modelVisible.ts";

test("capForModel: under cap is unchanged, truncated:false", () => {
  const text = "hello world";
  const r = capForModel(text, DEFAULT_MODEL_VISIBLE_CAP);
  assert.equal(r.shown, text);
  assert.equal(r.truncated, false);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.equal(r.bytesShown, r.bytesTotal);
});

test("capForModel: over cap truncates with bytesShown <= cap and a scratch-pointing notice", () => {
  const text = "x".repeat(5000);
  const r = capForModel(text, 1000, "/tmp/scratch/child.md");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 1000, `bytesShown ${r.bytesShown} should be <= cap`);
  assert.equal(r.bytesTotal, 5000);
  assert.ok(r.shown.includes("[Output truncated"));
  assert.ok(r.shown.includes("/tmp/scratch/child.md"));
});

test("capForModel: UTF-8 multibyte boundary safe (never splits a code point)", () => {
  // "💎" is 4 UTF-8 bytes; a cap landing mid-character must trim to a whole char.
  const text = "💎".repeat(100);
  const r = capForModel(text, 10);
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 10);
  // The shown prefix (before the notice) must be valid (no replacement char from a split).
  const prefix = r.shown.split("\n\n[Output truncated")[0] ?? "";
  assert.ok(!prefix.includes("\uFFFD"));
  assert.equal(Buffer.byteLength(prefix, "utf8") % 4, 0);
});

test("capForModel: tail mode under cap is unchanged, truncated:false", () => {
  const text = "hello world";
  const r = capForModel(text, DEFAULT_MODEL_VISIBLE_CAP, null, "tail");
  assert.equal(r.shown, text);
  assert.equal(r.truncated, false);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.equal(r.bytesShown, r.bytesTotal);
});

test("capForModel: tail mode keeps the LAST cap bytes with a prepended notice", () => {
  const text = `${"x".repeat(5000)}FINAL-TAIL-MARKER`;
  const r = capForModel(text, 1000, "/tmp/scratch/child.md", "tail");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 1000, `bytesShown ${r.bytesShown} should be <= cap`);
  assert.equal(r.bytesTotal, Buffer.byteLength(text, "utf8"));
  assert.ok(r.shown.endsWith("FINAL-TAIL-MARKER"), "shown must end with the original tail");
  assert.ok(r.shown.startsWith("[Output truncated"), "notice must be a prefix in tail mode");
  assert.ok(r.shown.includes("/tmp/scratch/child.md"));
});

test("capForModel: tail mode UTF-8 multibyte boundary safe (never splits a code point)", () => {
  // "💎" is 4 UTF-8 bytes; a cap landing mid-character must trim to a whole char.
  const text = "💎".repeat(100);
  const r = capForModel(text, 10, null, "tail");
  assert.equal(r.truncated, true);
  assert.ok(r.bytesShown <= 10);
  // The shown suffix (after the prepended notice) must be valid (no lone surrogate from a split).
  const suffix = r.shown.slice(r.shown.indexOf("\n\n") + 2);
  assert.ok(!suffix.includes("\uFFFD"));
  assert.equal(Buffer.byteLength(suffix, "utf8") % 4, 0);
});
