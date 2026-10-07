// The TS semver parser/comparator behind the SDK-boundary admission (contracts.md §8.76). The
// pinned literal tables mirror tests/test_semver.py's — the cross-plane drift alarm (one grammar,
// one precedence, two planes).

import assert from "node:assert/strict";
import { test } from "node:test";
import { compareSemver, formatSemver, parseSemver, type Semver, satisfiesFloor } from "./semver.ts";

function sv(major: number, minor: number, patch: number, prerelease: string[] = []): Semver {
  return { major, minor, patch, prerelease };
}

const ACCEPTS: [string, Semver][] = [
  ["0.99.2", sv(0, 99, 2)],
  ["1.0.0", sv(1, 0, 0)],
  ["1.0.0-rc.1", sv(1, 0, 0, ["rc", "1"])],
  ["1.0.0-beta+exp.sha.5114f85", sv(1, 0, 0, ["beta"])],
  ["v22.19.0", sv(22, 19, 0)],
  [" 1.0.0\n", sv(1, 0, 0)],
  ["1.0.0+build.7", sv(1, 0, 0)],
  ["1.0.0-0.3.7", sv(1, 0, 0, ["0", "3", "7"])],
  ["1.0.0-x-y-z.--", sv(1, 0, 0, ["x-y-z", "--"])],
];

for (const [text, expected] of ACCEPTS) {
  test(`parseSemver accepts ${JSON.stringify(text)}`, () => {
    assert.deepEqual(parseSemver(text), expected);
  });
}

const REJECTS = [
  "",
  "1.0",
  "1.0.0.0",
  "01.0.0",
  "1.00.0",
  "1.0.0-",
  "1.0.0-01",
  "1.0.0+",
  "latest",
  "pi 1.0.0",
  "vv1.0.0",
  "1.0.0 extra",
  "\u0661.\u0660.\u0660", // non-ASCII digits
];

for (const text of REJECTS) {
  test(`parseSemver rejects ${JSON.stringify(text)}`, () => {
    assert.equal(parseSemver(text), null);
  });
}

test("parseSemver rejects oversized input without throwing", () => {
  assert.equal(parseSemver(`${"9".repeat(4301)}.0.0`), null);
  assert.equal(parseSemver(`1.0.0-${"9".repeat(4301)}`), null);
  // 257 chars: grammatical, but longer than any version.
  assert.equal(parseSemver(`1.0.0-${"a".repeat(251)}`), null);
});

test("parseSemver accepts a version at the length cap", () => {
  const text = `1.0.0-${"a".repeat(250)}`; // exactly 256 chars
  assert.equal(text.length, 256);
  assert.deepEqual(parseSemver(text), sv(1, 0, 0, ["a".repeat(250)]));
});

function v(text: string): Semver {
  const parsed = parseSemver(text);
  assert.ok(parsed !== null, text);
  return parsed;
}

test("formatSemver renders the canonical text without build metadata", () => {
  assert.equal(formatSemver(v("v1.0.0-rc.1+abc")), "1.0.0-rc.1");
  assert.equal(formatSemver(v("22.19.0")), "22.19.0");
});

const SEMVER_ORG_CHAIN = [
  "1.0.0-alpha",
  "1.0.0-alpha.1",
  "1.0.0-alpha.beta",
  "1.0.0-beta",
  "1.0.0-beta.2",
  "1.0.0-beta.11",
  "1.0.0-rc.1",
  "1.0.0",
];

test("compareSemver follows the semver.org precedence chain", () => {
  for (let i = 0; i + 1 < SEMVER_ORG_CHAIN.length; i += 1) {
    const lower = SEMVER_ORG_CHAIN[i] as string;
    const higher = SEMVER_ORG_CHAIN[i + 1] as string;
    assert.equal(compareSemver(v(lower), v(higher)), -1, `${lower} < ${higher}`);
    assert.equal(compareSemver(v(higher), v(lower)), 1, `${higher} > ${lower}`);
  }
});

test("compareSemver is numeric, not lexical", () => {
  assert.equal(compareSemver(v("1.10.0"), v("1.9.0")), 1);
  assert.equal(compareSemver(v("0.99.2"), v("1.0.0")), -1);
  assert.equal(compareSemver(v("22.9.0"), v("22.19.0")), -1);
});

test("compareSemver: build metadata carries no precedence", () => {
  assert.equal(compareSemver(v("1.0.0+a"), v("1.0.0+b")), 0);
  assert.equal(compareSemver(v("1.0.0"), v("1.0.0")), 0);
});

test("compareSemver: numeric prerelease identifiers compare exactly past 2^53", () => {
  // Number() would round both of these to the same double; the digit-string compare does not.
  assert.equal(compareSemver(v("1.0.0-90071992547409921"), v("1.0.0-9007199254740993")), 1);
  assert.equal(compareSemver(v("1.0.0-9007199254740993"), v("1.0.0-9007199254740992")), 1);
  assert.equal(compareSemver(v("1.0.0-9007199254740993"), v("1.0.0-9007199254740993")), 0);
});

test("satisfiesFloor is a minimum", () => {
  const floor = v("1.0.0");
  assert.ok(satisfiesFloor(v("1.0.0"), floor));
  assert.ok(satisfiesFloor(v("1.0.3"), floor));
  assert.ok(satisfiesFloor(v("1.10.0"), floor));
  assert.ok(satisfiesFloor(v("2.0.0-alpha"), floor));
  assert.ok(!satisfiesFloor(v("1.0.0-rc.1"), floor));
  assert.ok(!satisfiesFloor(v("0.99.2"), floor));
});
