// Runner-only restrictions: independent of advisory identity and role classification.

import { type ReportTarget, report } from "../surfaces/report.ts";
import {
  type NativeSessionKey,
  type NativeSessionSource,
  nativeSessionKeysEqual,
  readNativeSessionKey,
} from "./nativeSessionKey.ts";

const NAMESPACE = "perk.parent-restrictions/1";
const FAMILY = "perk.parent-restrictions/";
const MAX_ENVELOPE_BYTES = 16384;

type InvalidReason = "oversized" | "json" | "envelope" | "version" | "value" | "unreadable";
export type ChildRestrictions =
  | { status: "ignored" }
  | { status: "legacy-absent" }
  | { status: "valid"; readOnly: boolean }
  | { status: "invalid"; reason: InvalidReason; readOnly: true };

function invalid(reason: InvalidReason): ChildRestrictions {
  return { status: "invalid", reason, readOnly: true };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** False and legacy absence are never write grants. Unrelated namespaces are opaque. */
export function decodeChildRestrictions(
  runner: boolean,
  raw: string | undefined,
): ChildRestrictions {
  if (!runner) return { status: "ignored" };
  if (raw === undefined) return { status: "legacy-absent" };
  if (Buffer.byteLength(raw, "utf8") > MAX_ENVELOPE_BYTES) return invalid("oversized");
  let envelope: unknown;
  try {
    envelope = JSON.parse(raw);
  } catch {
    return invalid("json");
  }
  if (!isObject(envelope)) return invalid("envelope");
  const keys = Object.keys(envelope);
  if (keys.some((key) => key.startsWith(FAMILY) && key !== NAMESPACE)) return invalid("version");
  if (!Object.hasOwn(envelope, NAMESPACE)) return { status: "legacy-absent" };
  const value = envelope[NAMESPACE];
  if (
    !isObject(value) ||
    Object.keys(value).length !== 1 ||
    !Object.hasOwn(value, "readOnly") ||
    typeof value.readOnly !== "boolean"
  ) {
    return invalid("value");
  }
  return { status: "valid", readOnly: value.readOnly };
}

const WARNINGS: Record<InvalidReason, string> = {
  oversized: "child restriction envelope is oversized; read-only restriction remains active",
  json: "child restriction envelope is invalid JSON; read-only restriction remains active",
  envelope: "child restriction envelope is not an object; read-only restriction remains active",
  version: "child restriction version is unsupported; read-only restriction remains active",
  value: "child restriction value is invalid; read-only restriction remains active",
  unreadable: "child restriction capture is unreadable; read-only restriction remains active",
};

export interface ChildRestrictionsController {
  capture(
    ctx: NativeSessionSource & ReportTarget,
    runner: boolean,
    readEnvelope: () => string | undefined,
  ): void;
  hasFloor(): boolean;
  clear(): void;
}

export function createChildRestrictions(): ChildRestrictionsController {
  let lastKnownKey: NativeSessionKey | undefined;
  let floor = false;
  const knownWarnings = new Set<InvalidReason>();
  const anonymousWarnings = new Set<InvalidReason>();

  return {
    capture(ctx, runner, readEnvelope) {
      const read = readNativeSessionKey(ctx);
      if (read.status === "known") {
        // Recovery alone cannot distinguish an anonymous session from this readable one.
        if (lastKnownKey !== undefined && !nativeSessionKeysEqual(lastKnownKey, read.key)) {
          floor = false;
          knownWarnings.clear();
        }
        lastKnownKey = read.key;
      }
      let decoded: ChildRestrictions;
      if (!runner) {
        decoded = { status: "ignored" };
      } else if (read.status === "unreadable") {
        decoded = invalid("unreadable");
      } else {
        try {
          decoded = decodeChildRestrictions(runner, readEnvelope());
        } catch {
          decoded = invalid("unreadable");
        }
      }
      if (decoded.status === "valid" || decoded.status === "invalid") floor ||= decoded.readOnly;
      if (decoded.status !== "invalid") return;
      const warnings = read.status === "known" ? knownWarnings : anonymousWarnings;
      if (warnings.has(decoded.reason)) return;
      warnings.add(decoded.reason);
      report(ctx, "child restriction", "warning", WARNINGS[decoded.reason], { alsoLog: true });
    },
    hasFloor: () => floor,
    clear() {
      floor = false;
      lastKnownKey = undefined;
      knownWarnings.clear();
      anonymousWarnings.clear();
    },
  };
}
