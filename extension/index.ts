// perk Pi extension — the session *interior*.
//
// T1 is a deliberate **no-op**: it proves the extension loads, that `shared/`
// resolves, and establishes the headless-fail-safe convention (every rich-UI
// call guarded by `ctx.hasUI`). Workflow tools/commands/modes arrive in later
// turns (see docs/phase-0-plan.md).

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { perkVersion, sharedDir } from "./resources";

export default function (pi: ExtensionAPI) {
  const version = perkVersion();
  let sharedOk = false;
  try {
    sharedDir();
    sharedOk = true;
  } catch {
    sharedOk = false;
  }

  pi.on("session_start", async (_event, ctx) => {
    // Headless-fail-safe: rich UI only when there is a UI.
    if (ctx.hasUI) {
      ctx.ui.notify(`perk ${version} loaded`, "info");
    }

    // Scriptable load proof. Env-gated so normal launches have no side effects;
    // `scripts/verify-t1.sh` sets PERK_SELFCHECK=1 and asserts this sentinel.
    if (process.env.PERK_SELFCHECK) {
      try {
        const dir = join(ctx.cwd, ".pi", "workflow");
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
        writeFileSync(
          join(dir, ".perk-loaded"),
          `perk ${version} loaded; shared=${sharedOk ? "ok" : "miss"}; hasUI=${ctx.hasUI}\n`,
        );
      } catch {
        // never throw from a load probe
      }
    }
  });

  pi.registerCommand("perk-selfcheck", {
    description: "Report that the perk extension is loaded.",
    handler: async (_args, ctx) => {
      ctx.ui.notify(
        `perk ${version} loaded; shared=${sharedOk ? "ok" : "miss"}`,
        sharedOk ? "info" : "warning",
      );
    },
  });
}
