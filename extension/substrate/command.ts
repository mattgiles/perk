// The single chokepoint that gives every perk command a uniform, immediate "running…"
// acknowledgement at entry. pi does not echo the invoked command and handlers only report() at the
// end, so without this a command's async work (cold-door subprocess calls, GitHub round-trips) is
// dead air between Enter and completion. registerPerkCommand wraps the handler to emit one transient
// entry toast through the headless-safe report() seam (no cleanup state, headless-fail-safe for
// free) before awaiting the original handler. The toast fires synchronously before the first await,
// so it lands before any cold-door work, sendUserMessage drive, or gate transition; the wrapper does
// not try/catch, so errors propagate exactly as before.

import type { ExtensionAPI, RegisteredCommand } from "@earendil-works/pi-coding-agent";
import { report } from "../surfaces/report.ts";

export function registerPerkCommand(
  pi: ExtensionAPI,
  name: string,
  options: Omit<RegisteredCommand, "name" | "sourceInfo">,
): void {
  pi.registerCommand(name, {
    ...options,
    handler: async (args, ctx) => {
      report(ctx, name, "info", "running…");
      await options.handler(args, ctx);
    },
  });
}
