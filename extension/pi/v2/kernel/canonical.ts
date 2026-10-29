// Canonical JSON and hashing for the v2 domain kernel (docs/design/pi-durable-v2-foundations.md
// §4: the capability-set digest and every duplicate-compared payload are canonical JSON).
//
// Invariants:
// - `canonicalJson` follows RFC 8785 (JCS): keys sorted by UTF-16 code units, recursively, no
//   whitespace, ECMAScript number and string serialization. It throws `TypeError` for anything
//   outside the JSON domain — non-finite numbers, ill-formed strings (a lone surrogate, in a value
//   or a key), cycles, and every non-plain object.
// - `asJsonValue` is the boundary check for caller-supplied values: every value it returns is
//   accepted by `canonicalJson`, so comparing a caller payload never throws.
// - `isWellFormedText` is the kernel's one text predicate.

import { createHash } from "node:crypto";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

/** True iff `value` holds no lone surrogate (under the `u` flag a valid pair is one non-Cs code point). */
export function isWellFormedText(value: string): boolean {
  return !/\p{Cs}/u.test(value);
}

function isPlainObject(value: object): boolean {
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function canonicalString(value: string): string {
  if (!isWellFormedText(value)) throw new TypeError("canonical JSON: ill-formed string");
  return JSON.stringify(value);
}

function canonicalNode(value: unknown, ancestors: WeakSet<object>): string {
  if (value === null) return "null";
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      if (!Number.isFinite(value)) throw new TypeError("canonical JSON: non-finite number");
      // JSON.stringify renders -0 as 0 and otherwise matches ECMAScript Number serialization.
      return JSON.stringify(value);
    case "string":
      return canonicalString(value);
    case "object":
      break;
    default:
      throw new TypeError(`canonical JSON: unsupported ${typeof value}`);
  }
  if (ancestors.has(value)) throw new TypeError("canonical JSON: cycle");
  ancestors.add(value);
  let text: string;
  if (Array.isArray(value)) {
    const items: string[] = [];
    for (let i = 0; i < value.length; i++) items.push(canonicalNode(value[i], ancestors));
    text = `[${items.join(",")}]`;
  } else {
    if (!isPlainObject(value)) throw new TypeError("canonical JSON: not a plain object");
    const members: string[] = [];
    for (const key of Object.keys(value).sort()) {
      members.push(`${canonicalString(key)}:${canonicalNode(Reflect.get(value, key), ancestors)}`);
    }
    text = `{${members.join(",")}}`;
  }
  ancestors.delete(value);
  return text;
}

/** RFC 8785 canonical JSON of `value`; throws `TypeError` outside the JSON domain. */
export function canonicalJson(value: JsonValue): string {
  return canonicalNode(value, new WeakSet());
}

function isJsonNode(value: unknown, ancestors: WeakSet<object>): boolean {
  if (value === null) return true;
  switch (typeof value) {
    case "boolean":
      return true;
    case "number":
      return Number.isFinite(value);
    case "string":
      return isWellFormedText(value);
    case "object":
      break;
    default:
      return false;
  }
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  let ok: boolean;
  if (Array.isArray(value)) {
    ok = true;
    for (let i = 0; ok && i < value.length; i++) ok = isJsonNode(value[i], ancestors);
  } else {
    ok =
      isPlainObject(value) &&
      Object.getOwnPropertySymbols(value).length === 0 &&
      Object.keys(value).every(
        (key) => isWellFormedText(key) && isJsonNode(Reflect.get(value, key), ancestors),
      );
  }
  ancestors.delete(value);
  return ok;
}

function isJsonValue(value: unknown): value is JsonValue {
  return isJsonNode(value, new WeakSet());
}

/** `value` as a JSON value if it is one `canonicalJson` accepts, else `null`. */
export function asJsonValue(value: unknown): JsonValue | null {
  return isJsonValue(value) ? value : null;
}

/** Equal canonical JSON. */
export function jsonEquals(a: JsonValue, b: JsonValue): boolean {
  return canonicalJson(a) === canonicalJson(b);
}

/** Lowercase hex sha256 of the UTF-8 bytes of `text`. */
export function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** True iff `value` is exactly `length` lowercase hex digits. */
export function isLowerHex(value: string, length: number): boolean {
  return typeof value === "string" && value.length === length && /^[0-9a-f]*$/.test(value);
}
