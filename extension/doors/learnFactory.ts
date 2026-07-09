// hop-2 — the two learn plan factories' warm transition surfaces: the `/learn-docs` and
// `/learn-code` commands (the warm twins of the `perk learn docs` / `perk learn code` cold
// doors). One shared register parameterized by a kind config — mirroring the Python plane's
// `factory_common.py` (`LearnFactoryKind` + `DOCS_FACTORY`/`CODE_FACTORY` + `run_factory`).
//
// Each door DELEGATES the gather to the Python plane (`perk learn <kind> --gather --json` via the
// shared cold-door client `runColdDoor` — gate-safe, not subject to the read-only bash allowlist),
// decodes `{ inbox_path, learn_numbers }`, then injects the factory guidance via
// `pi.sendUserMessage` so the model reads the inbox, authors the plan, and saves it. The save is
// surface-dependent (the seed spells this out): where `plan_save` is active (a read-write session,
// the warm doors' usual host) the model passes `consumed_learn` explicitly — load-bearing here,
// because the warm gather is side-effect-free and writes NO handoff carrier; in a gated read-only
// session `plan_save` is hidden (toolGating.ts), so the save lands review-first via `plan_review`
// and the COLD doors' handoff carrier supplies `consumed_learn`. No model tool is registered here.
//
// Headless-safe: rich UI is guarded by `ctx.hasUI`; without a UI it logs to stderr and returns
// (the gather still runs so the inbox is materialized, but no turn is driven).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { type ColdJson, runColdDoor, stringField } from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { render } from "../substrate/prompts.ts";
import { report } from "../surfaces/report.ts";

/**
 * The per-door parameter bundle shared by the two warm learn-factory doors (the TS twin of the
 * frozen `LearnFactoryKind` dataclass). `subcommand` derives the cold argv, the `runColdDoor`
 * label, and the headless log tail; `seedTemplate` and `bindingTrigger` stay explicit so the
 * strings remain greppable against `prompts/stages/` and `shared/bindings.yaml`.
 */
export interface LearnFactoryDoorKind {
  /** The command id and `report()` scope. */
  readonly name: string;
  /** The cold-door verb under `perk learn`. */
  readonly subcommand: string;
  readonly seedTemplate: string;
  readonly bindingTrigger: string;
  /** The `registerPerkCommand` description. */
  readonly description: string;
  /** The gentle `no_learn_issues` warning. */
  readonly emptyMessage: string;
}

export const DOCS_DOOR: LearnFactoryDoorKind = {
  name: "learn-docs",
  subcommand: "docs",
  seedTemplate: "stages/learn-docs.md",
  bindingTrigger: "command:learn-docs",
  description:
    "Start the learned-docs plan factory: gather open perk:learn issues into an inbox and author " +
    "a docs/learned consolidation plan.",
  emptyMessage: "nothing to consolidate (no open perk:learn issues).",
};

export const CODE_DOOR: LearnFactoryDoorKind = {
  name: "learn-code",
  subcommand: "code",
  seedTemplate: "stages/learn-code.md",
  bindingTrigger: "command:learn-code",
  description:
    "Start the learn-code plan factory: gather pre-stamped SHOULD_BE_CODE perk:learn issues into " +
    "an inbox and author a plan routing each into its real code home.",
  emptyMessage: "nothing to route into code (no SHOULD_BE_CODE perk:learn issues).",
};

/** The decoded `perk learn <kind> --gather --json` payload slice the warm door consumes. */
export interface LearnGatherPayload {
  inbox_path: string;
  /** Opaque string learn-issue ids (GitHub "45", Linear "ENG-45") — §8.21. */
  learn_numbers: string[];
}

/** Strict decode — the guidance dereferences both fields; `launched` is unconsumed. Exported for offline reject-branch tests. */
export function decodeGather(payload: ColdJson): LearnGatherPayload | null {
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
 * The seed guidance the warm door injects to start the factory loop (the per-kind skill pointer
 * rides the skill-binding suffix — not hardcoded here). Pure + exported for offline tests.
 */
export function learnFactoryGuidance(
  kind: LearnFactoryDoorKind,
  inboxPath: string,
  learnNumbers: string[],
): string {
  return render(kind.seedTemplate, {
    inbox_path: inboxPath,
    num_list: learnNumbers.join(", "),
  });
}

/** Register one warm learn-factory door: the `/<kind.name>` command (no model tool). */
export function registerLearnFactoryDoor(pi: ExtensionAPI, kind: LearnFactoryDoorKind): void {
  registerPerkCommand(pi, kind.name, {
    description: kind.description,
    handler: async (_args, ctx: ExtensionContext) => {
      // Report-only door (no Result type): branch on `errorType` directly (the coldDoor header
      // convention). A clean empty inbox exits non-zero with error_type=no_learn_issues — the
      // client's envelope-aware arm surfaces it gently.
      const r = await runColdDoor<LearnGatherPayload>(
        pi,
        ctx,
        ["learn", kind.subcommand, "--gather", "--json"],
        { label: `perk learn ${kind.subcommand}`, decode: decodeGather },
      );
      if (!r.ok) {
        if (r.errorType === "no_learn_issues") {
          report(ctx, kind.name, "warning", kind.emptyMessage);
        } else {
          report(ctx, kind.name, "error", `gather failed: ${r.message}`);
        }
        return;
      }

      if (!ctx.hasUI) {
        // Headless can't drive a turn — the inbox is materialized; log and return (fail-safe).
        console.error(
          `perk: /${kind.name} invoked (headless) — gathered ${r.data.learn_numbers.length} ` +
            `learn issue(s) into ${r.data.inbox_path}; run interactively to author the ` +
            `${kind.subcommand} plan.`,
        );
        return;
      }

      report(ctx, kind.name, "info", `gathered ${r.data.learn_numbers.length} learn issue(s)`);
      pi.sendUserMessage(
        learnFactoryGuidance(kind, r.data.inbox_path, r.data.learn_numbers) +
          bindingSuffix(ctx.cwd, kind.bindingTrigger),
      );
    },
  });
}
