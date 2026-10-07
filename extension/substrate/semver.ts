// A bounded semver 2.0.0 parser and comparator — the TS twin of perk/substrate/semver.py
// (contracts.md §8.76). Pure leaf: no imports, no I/O.
//
// The SDK-boundary admission compares the loaded Pi SDK's `VERSION` against the shared host floor
// with semver precedence (semver.org §11): the triple compares numerically; a release outranks
// any prerelease of the same triple (so `1.0.0-rc.1` is BELOW a `1.0.0` floor); prerelease
// identifiers compare one by one — numeric < alphanumeric, numerics by value, alphanumerics
// lexically — and when every shared identifier is equal the longer list wins. Build metadata
// carries no precedence and is never kept.
//
// The accept/reject grammar mirrors the Python twin exactly: the semver.org grammar, the
// 256-character cap (npm's), and one leniency — a single leading `v`/`V`. JS `\d` is ASCII-only,
// matching Python's `re.ASCII`.
//
// Precision note: triple components are JS numbers, so a component above 2^53 loses precision in
// the comparison (never a real host version; it does not change what parses). Numeric prerelease
// identifiers compare EXACTLY — shorter digit string is smaller, equal length compares lexically —
// so they never round.

export interface Semver {
  major: number;
  minor: number;
  patch: number;
  prerelease: readonly string[];
}

/** npm's semver cap; also keeps every numeric identifier bounded. */
export const MAX_VERSION_LENGTH = 256;

const SEMVER_RE =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/;

const NUMERIC_ID = /^\d+$/;

/**
 * Parse `text` as semver 2.0.0 (one optional leading `v`/`V`); `null` when it is not one.
 *
 * Surrounding whitespace is trimmed. Longer than `MAX_VERSION_LENGTH` characters is not a
 * version. Never throws.
 */
export function parseSemver(text: string): Semver | null {
  let candidate = text.trim();
  if (candidate.startsWith("v") || candidate.startsWith("V")) {
    candidate = candidate.slice(1);
  }
  if (candidate.length > MAX_VERSION_LENGTH) {
    return null;
  }
  const match = SEMVER_RE.exec(candidate);
  if (match === null) {
    return null;
  }
  const pre = match[4];
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: pre === undefined ? [] : pre.split("."),
  };
}

function sign(a: number | string, b: number | string): -1 | 0 | 1 {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/** Semver §11.4 for one prerelease identifier pair (numerics compared exactly, never rounded). */
function compareIdentifier(a: string, b: string): -1 | 0 | 1 {
  const aNumeric = NUMERIC_ID.test(a);
  const bNumeric = NUMERIC_ID.test(b);
  if (aNumeric && bNumeric) {
    // The grammar forbids leading zeros, so the shorter digit string is the smaller number.
    if (a.length !== b.length) return a.length < b.length ? -1 : 1;
    return sign(a, b);
  }
  if (aNumeric !== bNumeric) {
    return aNumeric ? -1 : 1;
  }
  return sign(a, b);
}

/** `-1`/`0`/`1` by semver §11 precedence (build metadata already discarded). */
export function compareSemver(a: Semver, b: Semver): -1 | 0 | 1 {
  const triple = sign(a.major, b.major) || sign(a.minor, b.minor) || sign(a.patch, b.patch);
  if (triple !== 0) {
    return triple;
  }
  // A release outranks any prerelease of the same triple.
  const aRelease = a.prerelease.length === 0;
  const bRelease = b.prerelease.length === 0;
  if (aRelease || bRelease) {
    return sign(Number(aRelease), Number(bRelease));
  }
  const shared = Math.min(a.prerelease.length, b.prerelease.length);
  for (let i = 0; i < shared; i += 1) {
    const order = compareIdentifier(a.prerelease[i] as string, b.prerelease[i] as string);
    if (order !== 0) {
      return order;
    }
  }
  // All shared identifiers equal: the longer identifier list has higher precedence.
  return sign(a.prerelease.length, b.prerelease.length);
}

/** Whether `observed` is at or above `floor` (a floor is a minimum, never an equality). */
export function satisfiesFloor(observed: Semver, floor: Semver): boolean {
  return compareSemver(observed, floor) >= 0;
}

/** The canonical text: `M.m.p` or `M.m.p-pre.ids` — build metadata is never kept. */
export function formatSemver(v: Semver): string {
  const triple = `${v.major}.${v.minor}.${v.patch}`;
  return v.prerelease.length === 0 ? triple : `${triple}-${v.prerelease.join(".")}`;
}
