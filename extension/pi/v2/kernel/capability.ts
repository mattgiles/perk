// The capability set an assignment binds to (docs/design/pi-durable-v2-foundations.md §4, P7).
//
// Invariants:
// - The digest is the sha256 of the canonical JSON of the NORMALIZED set (extensions and tools
//   sorted), so a permuted input names the same assignment.
// - The workspace root is symbolic (`subject-snapshot`), never a path, so the digest is the same
//   in every store.
// - The posture is read-only; any other posture or root is malformed, never normalized away.

import { canonicalJson, isLowerHex, isWellFormedText, sha256Hex } from "./canonical.ts";

export type CapabilitySet = {
  readonly model: { readonly provider: string; readonly modelId: string };
  readonly extensions: readonly string[];
  readonly tools: readonly string[];
  readonly instructionsDigest: string;
  readonly posture: "read-only";
  readonly workspaceRoot: "subject-snapshot";
};

function isName(value: unknown): value is string {
  return typeof value === "string" && value !== "" && isWellFormedText(value);
}

function normalizedNames(field: string, names: readonly string[]): string[] {
  if (!Array.isArray(names)) throw new RangeError(`capability set: ${field} is not a list`);
  for (const name of names) {
    if (!isName(name)) throw new RangeError(`capability set: malformed ${field} entry`);
  }
  const sorted = names.toSorted();
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === sorted[i - 1]) {
      throw new RangeError(`capability set: duplicate ${field} entry ${JSON.stringify(sorted[i])}`);
    }
  }
  return sorted;
}

/** A fresh copy of `set` with extensions and tools sorted; throws `RangeError` when malformed. */
export function normalizeCapabilitySet(set: CapabilitySet): CapabilitySet {
  if (typeof set.model !== "object" || set.model === null) {
    throw new RangeError("capability set: malformed model");
  }
  if (!isName(set.model.provider)) throw new RangeError("capability set: malformed provider");
  if (!isName(set.model.modelId)) throw new RangeError("capability set: malformed modelId");
  const extensions = normalizedNames("extensions", set.extensions);
  const tools = normalizedNames("tools", set.tools);
  if (!isLowerHex(set.instructionsDigest, 64)) {
    throw new RangeError("capability set: instructionsDigest is not 64 lowercase hex");
  }
  if (set.posture !== "read-only")
    throw new RangeError("capability set: posture must be read-only");
  if (set.workspaceRoot !== "subject-snapshot") {
    throw new RangeError("capability set: workspaceRoot must be subject-snapshot");
  }
  return {
    model: { provider: set.model.provider, modelId: set.model.modelId },
    extensions,
    tools,
    instructionsDigest: set.instructionsDigest,
    posture: "read-only",
    workspaceRoot: "subject-snapshot",
  };
}

/** The sha256 of the canonical JSON of the normalized set. */
export function capabilitySetDigest(set: CapabilitySet): string {
  return sha256Hex(canonicalJson(normalizeCapabilitySet(set)));
}
