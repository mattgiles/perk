// hop-2 — the two learn plan factories' warm transition surfaces: the `/learn-docs` and
// `/learn-code` commands (the warm twins of the `perk learn docs` / `perk learn code` cold
// doors). One shared register parameterized by the `learning/routing.ts` kind vocabulary —
// mirroring the Python plane's `factory_common.py` (`LearnFactoryKind` +
// `DOCS_FACTORY`/`CODE_FACTORY` + `run_factory`).
//
// Each door DELEGATES the gather to the Python plane (`perk learn <kind> --gather --json` via the
// shared cold-door client `runColdDoor` — gate-safe, not subject to the read-only bash allowlist),
// decodes `{ inbox_path, learn_numbers }`, then injects the factory guidance via
// `pi.sendUserMessage` so the model reads the inbox, authors the plan, and saves it. The warm
// gather is side-effect-free and writes NO handoff carrier, so `plan_save` passing
// `consumed_learn` explicitly is the ONLY surface that can carry the consumed numbers here — the
// interactive host guard (contracts.md §8.2) enforces it: an interactive session where the
// `plan_save` tool is not currently active (`pi.getActiveTools()` — the authority, reflecting the
// read-only gate, worktree stage scoping, AND foreign providers' `setActiveTools` restrictions
// that write no perk workflow-state) is refused BEFORE the gather, pointing at the cold door
// (`perk learn docs` / `perk learn code`), whose handoff carrier supplies `consumed_learn` on the
// review-first save path. Workflow-state only flavors the refusal message, never decides it. No
// model tool is registered here.
//
// Headless-safe: rich UI is guarded by `ctx.hasUI`; without a UI it logs to stderr and returns
// (the gather still runs so the inbox is materialized, but no turn is driven — the save hazard
// cannot occur, so the guard is interactive-only).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { learnFactoryGuidance } from "../../../learning/prose.ts";
import { CODE_FACTORY, DOCS_FACTORY, type LearnFactoryKind } from "../../../learning/routing.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import { type ColdJson, runColdDoor, stringField } from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { branchOf, rebuildWorkflowState } from "../../../substrate/workflowState.ts";
import { report } from "../../../surfaces/report.ts";

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

/** Register one warm learn-factory door: the `/<kind.name>` command (no model tool). */
function registerLearnFactoryDoor(pi: ExtensionAPI, kind: LearnFactoryKind): void {
  registerPerkCommand(pi, kind.name, {
    description: kind.description,
    handler: async (_args, ctx: ExtensionContext) => {
      // The interactive host guard (see the header): refuse BEFORE the gather when `plan_save`
      // is not currently active — `pi.getActiveTools()` is the authoritative predicate;
      // workflow-state only flavors the message (it cannot see foreign restrictions).
      if (ctx.hasUI && !pi.getActiveTools().includes("plan_save")) {
        const state = rebuildWorkflowState(branchOf(ctx));
        const why =
          state.mode === "read-only"
            ? "this session is read-only"
            : state.stage !== undefined
              ? `this session is scoped to the ${state.stage} stage`
              : "a provider restriction hides it";
        report(
          ctx,
          kind.name,
          "error",
          `the plan_save tool is not active here (${why}), so this session cannot save a plan ` +
            `carrying consumed_learn — use the cold door instead: perk learn ${kind.subcommand}.`,
        );
        return;
      }
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

/** Install both warm learn-factory doors (`/learn-docs`, `/learn-code`) from the kind vocabulary. */
export function installLearnFactoryBindings(pi: ExtensionAPI): void {
  for (const kind of [DOCS_FACTORY, CODE_FACTORY]) {
    registerLearnFactoryDoor(pi, kind);
  }
}
