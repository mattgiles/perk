// Pure unit tests for the tool-boundary decode seam (toolParams.ts). Each helper's tri-state
// contract: absent → undefined, valid → value, present-but-mistyped → null (the invalid sentinel).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  arrayParam,
  numberArrayParam,
  numberParam,
  objectParam,
  paramsOf,
  stringArrayParam,
  stringParam,
} from "./toolParams.ts";

test("paramsOf: plain objects pass; everything else is null", () => {
  const obj = { a: 1 };
  assert.equal(paramsOf(obj), obj);
  assert.deepEqual(paramsOf({}), {});
  assert.equal(paramsOf(null), null);
  assert.equal(paramsOf(undefined), null);
  assert.equal(paramsOf([1, 2]), null);
  assert.equal(paramsOf("x"), null);
  assert.equal(paramsOf(5), null);
  assert.equal(paramsOf(true), null);
});

test("stringParam: tri-state", () => {
  assert.equal(stringParam({}, "k"), undefined);
  assert.equal(stringParam({ k: "v" }, "k"), "v");
  assert.equal(stringParam({ k: "" }, "k"), "");
  assert.equal(stringParam({ k: 5 }, "k"), null);
  assert.equal(stringParam({ k: null }, "k"), null);
  assert.equal(stringParam({ k: ["v"] }, "k"), null);
});

test("numberParam: tri-state", () => {
  assert.equal(numberParam({}, "k"), undefined);
  assert.equal(numberParam({ k: 7 }, "k"), 7);
  assert.equal(numberParam({ k: 0 }, "k"), 0);
  assert.equal(numberParam({ k: "7" }, "k"), null);
  assert.equal(numberParam({ k: null }, "k"), null);
});

test("stringArrayParam: tri-state; every element must be a string", () => {
  assert.equal(stringArrayParam({}, "k"), undefined);
  assert.deepEqual(stringArrayParam({ k: [] }, "k"), []);
  assert.deepEqual(stringArrayParam({ k: ["a", "b"] }, "k"), ["a", "b"]);
  assert.equal(stringArrayParam({ k: "a" }, "k"), null);
  assert.equal(stringArrayParam({ k: ["a", 1] }, "k"), null);
  assert.equal(stringArrayParam({ k: null }, "k"), null);
});

test("stringArrayParam: returns a fresh array (no aliasing)", () => {
  const input = ["a"];
  const out = stringArrayParam({ k: input }, "k");
  assert.deepEqual(out, ["a"]);
  assert.notEqual(out, input);
});

test("numberArrayParam: tri-state; every element must be a number", () => {
  assert.equal(numberArrayParam({}, "k"), undefined);
  assert.deepEqual(numberArrayParam({ k: [1, 2] }, "k"), [1, 2]);
  assert.equal(numberArrayParam({ k: [1, "2"] }, "k"), null);
  assert.equal(numberArrayParam({ k: "1" }, "k"), null);
});

test("arrayParam: any array passes; non-arrays are null; fresh copy", () => {
  assert.equal(arrayParam({}, "k"), undefined);
  const input = [1, "a", { x: 1 }];
  const out = arrayParam({ k: input }, "k");
  assert.deepEqual(out, input);
  assert.notEqual(out, input);
  assert.equal(arrayParam({ k: "x" }, "k"), null);
  assert.equal(arrayParam({ k: {} }, "k"), null);
  assert.equal(arrayParam({ k: null }, "k"), null);
});

test("objectParam: plain objects only; arrays/null are invalid", () => {
  assert.equal(objectParam({}, "k"), undefined);
  assert.deepEqual(objectParam({ k: { a: 1 } }, "k"), { a: 1 });
  assert.deepEqual(objectParam({ k: {} }, "k"), {});
  assert.equal(objectParam({ k: [] }, "k"), null);
  assert.equal(objectParam({ k: null }, "k"), null);
  assert.equal(objectParam({ k: "x" }, "k"), null);
  assert.equal(objectParam({ k: 5 }, "k"), null);
});
