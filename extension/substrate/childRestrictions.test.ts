import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeReadOnlyFloor, isRunnerChild } from "./childRestrictions.ts";

const packet = (readOnly: boolean) =>
  JSON.stringify({ "perk.parent-restrictions/1": { readOnly } });

// [label, raw envelope, floor for a runner child]. No packet ⇒ false; malformed ⇒ true (fail
// closed, including an unsupported `perk.parent-restrictions/<n>` version); valid ⇒ the boolean.
const CASES: [string, string | undefined, boolean][] = [
  ["undefined", undefined, false],
  ["empty object", "{}", false],
  ["unrelated namespace only", '{"custom/1":{"nested":[null,1,{"readOnly":"yes"}]}}', false],
  ["not family (no slash)", '{"perk.parent-restrictions":null}', false],
  ["true", packet(true), true],
  ["false", packet(false), false],
  [
    "valid beside unrelated",
    '{"perk.parent-restrictions/1":{"readOnly":false},"opaque/9":[null,{"deep":"data"}]}',
    false,
  ],
  ["empty", "", true],
  ["bad JSON", "{", true],
  ["null", "null", true],
  ["array", "[]", true],
  ["number", "1", true],
  ["unsupported family version", '{"perk.parent-restrictions/2":{}}', true],
  ["empty version", '{"perk.parent-restrictions/":true}', true],
  [
    "unsupported version beside valid never un-floors",
    '{"perk.parent-restrictions/1":{"readOnly":false},"perk.parent-restrictions/0":null}',
    true,
  ],
  ["v1 null", '{"perk.parent-restrictions/1":null}', true],
  ["v1 array", '{"perk.parent-restrictions/1":[]}', true],
  ["v1 primitive", '{"perk.parent-restrictions/1":true}', true],
  ["v1 empty", '{"perk.parent-restrictions/1":{}}', true],
  ["v1 string readOnly", '{"perk.parent-restrictions/1":{"readOnly":"true"}}', true],
  ["v1 extra field", '{"perk.parent-restrictions/1":{"readOnly":true,"extra":1}}', true],
];

test("decoder: a non-runner never gets a floor, whatever the envelope", () => {
  for (const [label, raw] of CASES) {
    assert.equal(decodeReadOnlyFloor(false, raw), false, label);
  }
});

test("decoder: runner child — no packet ⇒ no floor, malformed ⇒ floor, valid ⇒ the boolean", () => {
  for (const [label, raw, floor] of CASES) {
    assert.equal(decodeReadOnlyFloor(true, raw), floor, label);
  }
});

test("decoder: an inherited readOnly never counts — a polluted prototype cannot un-floor", (t) => {
  const proto = Object.prototype as Record<string, unknown>;
  Object.defineProperty(proto, "readOnly", { value: false, configurable: true, writable: true });
  t.after(() => {
    delete proto.readOnly;
  });
  assert.equal(decodeReadOnlyFloor(true, '{"perk.parent-restrictions/1":{"extra":1}}'), true);
  assert.equal(decodeReadOnlyFloor(true, '{"perk.parent-restrictions/1":{}}'), true);
  assert.equal(decodeReadOnlyFloor(true, packet(false)), false, "an own boolean is still honored");
});

test("isRunnerChild reads exactly PI_SUBAGENT_CHILD=1", () => {
  assert.equal(isRunnerChild({ PI_SUBAGENT_CHILD: "1" }), true);
  assert.equal(isRunnerChild({ PI_SUBAGENT_CHILD: "0" }), false);
  assert.equal(isRunnerChild({ PI_SUBAGENT_CHILD: "" }), false);
  assert.equal(isRunnerChild({}), false);
});
