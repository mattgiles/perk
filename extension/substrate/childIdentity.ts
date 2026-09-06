// A spoofable startup prompt claim for scratch policy, never an authorization principal.

import { type ReportTarget, report } from "../surfaces/report.ts";
import {
  type NativeSessionKey,
  type NativeSessionSource,
  nativeSessionKeysEqual,
  readNativeSessionKey,
} from "./nativeSessionKey.ts";

const PROVENANCE = "native-system-prompt-prefix";
const MAX_PREFIX_BYTES = 4096;
const MAX_NAME_BYTES = 256;

type UnavailableReason = "absent" | "malformed" | "unreadable" | "stale";
export type ChildIdentity = { provenance: typeof PROVENANCE } & (
  | { status: "available"; name: string }
  | { status: "unavailable"; reason: UnavailableReason }
);

export interface ChildIdentitySnapshot {
  identity: ChildIdentity;
  /** Captured independently from the name; used only for unavailable-identity fallback. */
  runner: boolean;
}

type IdentityContext = NativeSessionSource & ReportTarget;
type CaptureContext = IdentityContext & { getSystemPrompt(): string };

function unavailable(reason: UnavailableReason): ChildIdentity {
  return { status: "unavailable", reason, provenance: PROVENANCE };
}

function encodeName(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const ENTITIES: Readonly<Record<string, string>> = {
  "&amp;": "&",
  "&quot;": '"',
  "&lt;": "<",
  "&gt;": ">",
};

/** Scan at most one bounded LF-delimited prefix, without copying/splitting the whole prompt. */
export function parseChildIdentity(prompt: string): ChildIdentity {
  let end = 0;
  let bytes = 0;
  while (end < prompt.length && prompt.charCodeAt(end) !== 10) {
    const point = prompt.codePointAt(end);
    if (point === undefined) break;
    bytes += point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
    if (bytes > MAX_PREFIX_BYTES) return unavailable("malformed");
    end += point > 0xffff ? 2 : 1;
  }
  const line = prompt.slice(0, end);
  const match = /^<active_agent name="([^"<>]*)"\/>$/.exec(line);
  if (match?.[0] === line && match[1] !== undefined) {
    const encoded = match[1];
    const name = encoded.replace(/&(?:amp|quot|lt|gt);/g, (entity) => ENTITIES[entity] ?? entity);
    if (
      name.length > 0 &&
      Buffer.byteLength(name, "utf8") <= MAX_NAME_BYTES &&
      !/\p{Cc}/u.test(name) &&
      encodeName(name) === encoded
    ) {
      return { status: "available", name, provenance: PROVENANCE };
    }
  }
  return unavailable(line.includes("<active_agent") ? "malformed" : "absent");
}

const WARNINGS: Record<UnavailableReason, string> = {
  absent: "native child identity prefix is absent; agent scratch is suppressed",
  malformed: "native child identity prefix is malformed; agent scratch is suppressed",
  unreadable: "native child identity is unreadable; agent scratch is suppressed",
  stale: "native child identity snapshot is stale; agent scratch is suppressed",
};

export interface ChildIdentityController {
  capture(ctx: CaptureContext, runner: boolean): void;
  lookup(ctx: IdentityContext): ChildIdentitySnapshot;
  clear(): void;
}

export function createChildIdentity(): ChildIdentityController {
  let lastKnownKey: NativeSessionKey | undefined;
  let knownWarnings = new Set<UnavailableReason>();
  const anonymousWarnings = new Set<UnavailableReason>();
  let snapshot:
    | {
        key: NativeSessionKey | undefined;
        value: ChildIdentitySnapshot;
        warnings: Set<UnavailableReason>;
      }
    | undefined;

  function warn(
    ctx: ReportTarget,
    value: ChildIdentitySnapshot,
    reasons: Set<UnavailableReason>,
  ): void {
    if (!value.runner || value.identity.status === "available") return;
    const reason = value.identity.reason;
    if (reasons.has(reason)) return;
    reasons.add(reason);
    report(ctx, "child identity", "warning", WARNINGS[reason], { alsoLog: true });
  }

  return {
    capture(ctx, runner) {
      const read = readNativeSessionKey(ctx);
      const key = read.status === "known" ? read.key : undefined;
      if (key !== undefined) {
        if (lastKnownKey !== undefined && !nativeSessionKeysEqual(lastKnownKey, key)) {
          knownWarnings = new Set();
        }
        lastKnownKey = key;
      }
      let identity: ChildIdentity = unavailable("unreadable");
      if (key !== undefined) {
        try {
          identity = parseChildIdentity(ctx.getSystemPrompt());
        } catch {
          identity = unavailable("unreadable");
        }
      }
      const warnings = key === undefined ? anonymousWarnings : knownWarnings;
      snapshot = { key, value: { identity, runner }, warnings };
      warn(ctx, snapshot.value, warnings);
    },
    lookup(ctx) {
      const read = readNativeSessionKey(ctx);
      const runner = snapshot?.value.runner ?? false;
      if (read.status === "unreadable" || snapshot?.key === undefined) {
        const value = { identity: unavailable("unreadable"), runner };
        warn(ctx, value, anonymousWarnings);
        return value;
      }
      if (!nativeSessionKeysEqual(snapshot.key, read.key)) {
        const value = { identity: unavailable("stale"), runner };
        warn(ctx, value, snapshot.warnings);
        return value;
      }
      return snapshot.value;
    },
    clear() {
      snapshot = undefined;
      lastKnownKey = undefined;
      knownWarnings.clear();
      anonymousWarnings.clear();
    },
  };
}
