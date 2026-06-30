// hop-2 — the learn-code plan factory's warm transition surface: the `/learn-code` command.
//
// The warm twin of the `perk learn code` cold door (sibling of `/learn-docs`). It DELEGATES the
// gather to the Python plane (`perk learn code --gather --json` via the shared cold-door client
// `runColdDoor` — gate-safe, not subject to the read-only bash allowlist), decodes
// `{ inbox_path, learn_numbers }`, then injects the factory guidance via `pi.sendUserMessage` so
// the model reads the inbox, authors a code plan, and calls `plan_save` with `consumed_learn`. No
// model tool — the model uses the existing `plan_save` tool.
//
// Headless-safe: rich UI is guarded by `ctx.hasUI`; without a UI it logs to stderr and returns
// (the gather still runs so the inbox is materialized, but no turn is driven).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { type ColdJson, runColdDoor, stringField } from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { render } from "../substrate/prompts.ts";
import { report } from "../surfaces/report.ts";

/** The decoded `perk learn code --gather --json` payload slice the warm door consumes. */
interface LearnCodeGatherPayload {
  inbox_path: string;
  /** Opaque string learn-issue ids (GitHub "45", Linear "ENG-45") — §8.21. */
  learn_numbers: string[];
}

/** Strict decode — the guidance dereferences both fields; `launched` is unconsumed. */
function decodeGather(payload: ColdJson): LearnCodeGatherPayload | null {
  const inboxPath = stringField(payload, "inbox_path");
  const numbers = payload.learn_numbers;
  if (inboxPath === undefined) return null;
  // String ids are canonical (§8.21); numbers are tolerated + coerced (older envelopes).
  if (
    !Array.isArray(numbers) ||
    !numbers.every((n) => typeof n === "string" || typeof n === "number")
  ) {
    return null;
  }
  return { inbox_path: inboxPath, learn_numbers: numbers.map((n) => String(n)) };
}

/**
 * The seed guidance the warm `/learn-code` injects to start the factory loop (the perk-learn-code
 * skill pointer rides the skill-binding suffix — not hardcoded here). Pure + exported
 * for offline tests.
 */
export function learnCodeGuidance(inboxPath: string, learnNumbers: string[]): string {
  return render("stages/learn-code.md", {
    inbox_path: inboxPath,
    num_list: learnNumbers.join(", "),
  });
}

/** Register the warm learn-code door: the `/learn-code` command (no model tool). */
export function registerLearnCode(pi: ExtensionAPI): void {
  registerPerkCommand(pi, "learn-code", {
    description:
      "Start the learn-code plan factory: gather pre-stamped SHOULD_BE_CODE perk:learn issues into " +
      "an inbox and author a plan routing each into its real code home.",
    handler: async (_args, ctx: ExtensionContext) => {
      // Report-only door (no Result type): branch on `errorType` directly (the coldDoor header
      // convention). A clean "nothing to route" exits non-zero with error_type=no_learn_issues —
      // the client's envelope-aware arm surfaces it gently.
      const r = await runColdDoor<LearnCodeGatherPayload>(
        pi,
        ctx,
        ["learn", "code", "--gather", "--json"],
        { label: "perk learn code", decode: decodeGather },
      );
      if (!r.ok) {
        if (r.errorType === "no_learn_issues") {
          report(
            ctx,
            "learn-code",
            "warning",
            "nothing to route into code (no SHOULD_BE_CODE perk:learn issues).",
          );
        } else {
          report(ctx, "learn-code", "error", `gather failed: ${r.message}`);
        }
        return;
      }

      if (!ctx.hasUI) {
        // Headless can't drive a turn — the inbox is materialized; log and return (fail-safe).
        console.error(
          `perk: /learn-code invoked (headless) — gathered ${r.data.learn_numbers.length} ` +
            `learn issue(s) into ${r.data.inbox_path}; run interactively to author the code plan.`,
        );
        return;
      }

      report(ctx, "learn-code", "info", `gathered ${r.data.learn_numbers.length} learn issue(s)`);
      pi.sendUserMessage(
        learnCodeGuidance(r.data.inbox_path, r.data.learn_numbers) +
          bindingSuffix(ctx.cwd, "command:learn-code"),
      );
    },
  });
}
