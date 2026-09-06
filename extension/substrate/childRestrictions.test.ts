import assert from "node:assert/strict";
import { test } from "node:test";
import { createChildRestrictions, decodeChildRestrictions } from "./childRestrictions.ts";

const packet = (readOnly: boolean) =>
  JSON.stringify({ "perk.parent-restrictions/1": { readOnly } });

test("runner-only decoder matrix: strict bounded reserved namespace, opaque unrelated data", () => {
  const cases: [string, string | undefined, string, (string | boolean)?][] = [
    ["undefined", undefined, "legacy-absent"],
    ["empty object", "{}", "legacy-absent"],
    ["true", packet(true), "valid", true],
    ["false", packet(false), "valid", false],
    ["empty", "", "invalid", "json"],
    ["whitespace", " \t\n", "invalid", "json"],
    ["bad JSON", "{", "invalid", "json"],
    ["null", "null", "invalid", "envelope"],
    ["array", "[]", "invalid", "envelope"],
    ["primitive", "true", "invalid", "envelope"],
    ["string", '"x"', "invalid", "envelope"],
    ["number", "1", "invalid", "envelope"],
    ["unrelated", '{"custom/1":{"nested":[null,1,{"readOnly":"yes"}]}}', "legacy-absent"],
    ["not family", '{"perk.parent-restrictions":null}', "legacy-absent"],
    ["unsupported", '{"perk.parent-restrictions/2":{}}', "invalid", "version"],
    [
      "unsupported alongside valid",
      '{"perk.parent-restrictions/1":{"readOnly":false},"perk.parent-restrictions/0":null}',
      "invalid",
      "version",
    ],
    ["empty version", '{"perk.parent-restrictions/":true}', "invalid", "version"],
    ["exact raw limit", `{}${" ".repeat(16382)}`, "legacy-absent"],
    ["one raw byte over", `{}${" ".repeat(16383)}`, "invalid", "oversized"],
    ["multibyte limit", `{"x":"${"é".repeat(8188)}"}`, "legacy-absent"],
    ["multibyte one over", `{"x":"${"é".repeat(8188)}x"}`, "invalid", "oversized"],
    [
      "JSON last-key semantics",
      '{"perk.parent-restrictions/1":{"readOnly":true,"readOnly":false}}',
      "valid",
      false,
    ],
  ];
  for (const value of [
    null,
    [],
    true,
    1,
    "false",
    {},
    { readOnly: "true" },
    { readOnly: 0 },
    { readOnly: null },
    { readOnly: [] },
    { readOnly: true, extra: false },
    { inherited: true },
  ]) {
    cases.push([
      `invalid value ${JSON.stringify(value)}`,
      JSON.stringify({ "perk.parent-restrictions/1": value }),
      "invalid",
      "value",
    ]);
  }
  for (const [label, raw, status, detail] of cases) {
    assert.deepEqual(
      decodeChildRestrictions(true, raw),
      status === "invalid"
        ? { status, reason: detail, readOnly: true }
        : status === "valid"
          ? { status, readOnly: detail }
          : { status },
      label,
    );
    assert.deepEqual(
      decodeChildRestrictions(false, raw),
      { status: "ignored" },
      `foreground negative boundary: ${label}`,
    );
  }
});

function context() {
  let id = "uuid-a";
  let file: string | null = "/one/session.jsonl";
  let broken = false;
  const warnings: string[] = [];
  const ctx = {
    hasUI: true,
    ui: {
      notify: (message: string) => {
        warnings.push(message);
      },
    },
    sessionManager: {
      getSessionId: () => {
        if (broken) throw "SENSITIVE_KEY";
        return id;
      },
      getSessionFile: () => file,
    },
  };
  return {
    ctx,
    warnings,
    breakKey: (value: boolean) => {
      broken = value;
    },
    key: (value: string, path: string | null = file) => {
      id = value;
      file = path;
    },
  };
}

test("floor ORs same-key captures, ignores non-runners and resets only on positive key difference/shutdown", () => {
  const h = context();
  const restrictions = createChildRestrictions();
  restrictions.capture(h.ctx, false, () => {
    throw "must not read foreground packet";
  });
  assert.equal(restrictions.hasFloor(), false);
  restrictions.capture(h.ctx, true, () => packet(false));
  assert.equal(restrictions.hasFloor(), false);
  restrictions.capture(h.ctx, true, () => packet(true));
  for (const raw of [undefined, packet(false), "{}"]) {
    restrictions.capture(h.ctx, true, () => raw);
    restrictions.capture(h.ctx, false, () => raw);
    assert.equal(restrictions.hasFloor(), true);
  }
  h.key("uuid-a", "/two/session.jsonl");
  restrictions.capture(h.ctx, true, () => packet(false));
  assert.equal(restrictions.hasFloor(), false);
  restrictions.capture(h.ctx, true, () => packet(true));
  h.key("uuid-b", "/two/session.jsonl");
  restrictions.capture(h.ctx, false, () => packet(true));
  assert.equal(restrictions.hasFloor(), false);
  restrictions.capture(h.ctx, true, () => packet(true));
  restrictions.clear();
  assert.equal(restrictions.hasFloor(), false);
  assert.deepEqual(h.warnings, []);
});

test("unreadable runner capture is restrictive; anonymous recovery carries floor and retains last known comparison", () => {
  const h = context();
  const restrictions = createChildRestrictions();
  h.breakKey(true);
  restrictions.capture(h.ctx, false, () => undefined);
  assert.equal(restrictions.hasFloor(), false);
  restrictions.capture(h.ctx, true, () => undefined);
  assert.equal(restrictions.hasFloor(), true);
  h.breakKey(false);
  restrictions.capture(h.ctx, true, () => packet(false));
  assert.equal(restrictions.hasFloor(), true, "first known key inherits anonymous floor");
  h.breakKey(true);
  restrictions.capture(h.ctx, true, () => undefined);
  h.breakKey(false);
  h.key("uuid-b");
  restrictions.capture(h.ctx, true, () => packet(false));
  assert.equal(
    restrictions.hasFloor(),
    false,
    "known difference resets despite intervening failed read",
  );
  restrictions.capture(h.ctx, true, () => {
    throw "SENSITIVE_PACKET";
  });
  assert.equal(restrictions.hasFloor(), true);
  const other = createChildRestrictions();
  other.capture(h.ctx, true, () => undefined);
  assert.equal(other.hasFloor(), false);
});

test("private finite warning scopes survive retries/recovery; silence legacy input and ignored carriers", () => {
  const h = context();
  const restrictions = createChildRestrictions();
  for (const raw of [undefined, "{}", packet(false)]) restrictions.capture(h.ctx, true, () => raw);
  assert.equal(h.warnings.length, 0);
  for (let n = 0; n < 2; n++) restrictions.capture(h.ctx, true, () => "SENSITIVE_PACKET");
  assert.equal(h.warnings.length, 1);
  h.breakKey(true);
  for (let n = 0; n < 2; n++) restrictions.capture(h.ctx, true, () => undefined);
  assert.equal(h.warnings.length, 2);
  h.breakKey(false);
  restrictions.capture(h.ctx, true, () => "SENSITIVE_PACKET");
  assert.equal(h.warnings.length, 2, "same known scope survives key outage");
  h.key("uuid-b", null);
  restrictions.capture(h.ctx, true, () => "SENSITIVE_PACKET");
  assert.equal(h.warnings.length, 3);
  h.breakKey(true);
  restrictions.capture(h.ctx, true, () => undefined);
  assert.equal(h.warnings.length, 3, "anonymous suppression survives known-key reset");
  restrictions.clear();
  restrictions.capture(h.ctx, true, () => undefined);
  assert.equal(h.warnings.length, 4);
  assert.doesNotMatch(h.warnings.join("\n"), /SENSITIVE/);
});
