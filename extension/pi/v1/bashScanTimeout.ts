// The bash scan-timeout guard's Pi hooks (contracts.md §8.69): the `tool_call` injection of the
// default `timeout` onto a gitignore-blind scan that carries none, and the `tool_result` steer
// appended when such a call expired. The policy — the constant, the classifier, the status parse,
// the note — is pure and lives in `substrate/bashScanTimeout.ts`; this module only adapts it to
// Pi's event shapes.
//
// Always on, never blocks, fail-OPEN: this is a performance guard, not a safety gate — a hook
// error is reported and the call proceeds unmodified (the read-only gate is the fail-closed one).
// A throwing `tool_call` handler would otherwise escape Pi's dispatch and abort the call.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  classifyScanCommand,
  expiredAfterSeconds,
  SCAN_TIMEOUT_SECONDS,
  scanTimeoutNote,
} from "../../substrate/bashScanTimeout.ts";

/** The narrowed bash input both hooks read (the union's `input` is narrowed by hand, gate-style). */
type BashInput = { command?: unknown; timeout?: unknown };

/**
 * Register the two hooks. Unconditional — every perk session, gated or not, runner children
 * included (the slow scans were observed in read-write sessions too). Registration order puts the
 * gate's `tool_call` hook first; a gate block short-circuits before injection matters.
 */
export function registerBashScanTimeout(pi: ExtensionAPI): void {
  pi.on("tool_call", async (event) => {
    try {
      if (event.toolName !== "bash") return;
      const input = event.input as BashInput;
      if (typeof input.command !== "string") return;
      // Any explicit value — the model's override — is left untouched.
      if (input.timeout !== undefined) return;
      if (classifyScanCommand(input.command) === null) return;
      input.timeout = SCAN_TIMEOUT_SECONDS;
    } catch (error) {
      console.error(`perk: bash scan-timeout hook failed — ${String(error)}`);
    }
    return;
  });

  // Stateless by design: keyed off the (possibly mutated) input + Pi's own terminal status line,
  // so it also fires when the model's explicit timeout expired — the wording is right either way.
  pi.on("tool_result", async (event) => {
    try {
      if (event.toolName !== "bash" || event.isError !== true) return;
      const command = (event.input as BashInput).command;
      if (typeof command !== "string") return;
      const kind = classifyScanCommand(command);
      if (kind === null) return;
      const last = event.content.at(-1);
      if (last === undefined || last.type !== "text") return;
      const seconds = expiredAfterSeconds(last.text);
      if (seconds === null) return;
      return {
        content: [...event.content, { type: "text", text: scanTimeoutNote(kind, seconds) }],
      };
    } catch (error) {
      console.error(`perk: bash scan-timeout note failed — ${String(error)}`);
      return;
    }
  });
}
