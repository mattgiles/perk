// The single chokepoint that gives every perk command a uniform, immediate "running…"
// acknowledgement at entry. pi does not echo the invoked command and handlers only report() at the
// end, so without this a command's async work (cold-door subprocess calls, GitHub round-trips) is
// dead air between Enter and completion. registerPerkCommand attaches the command's durable report-
// detail sink to the exact context object, then emits one transient entry toast through report()
// before awaiting the original handler. The toast fires synchronously before the first await, so it
// lands before any cold-door work, sendUserMessage drive, or gate transition; the wrapper does not
// try/catch, so errors propagate exactly as before. The WeakMap attachment deliberately survives the
// handler for background work launched with the same context.

import type { ExtensionAPI, RegisteredCommand } from "@earendil-works/pi-coding-agent";
import { attachReportDetailSink, report } from "../surfaces/report.ts";
import { createReportDetailSink } from "../surfaces/surfaces.ts";

export function registerPerkCommand(
  pi: ExtensionAPI,
  name: string,
  options: Omit<RegisteredCommand, "name" | "sourceInfo">,
): void {
  pi.registerCommand(name, {
    ...options,
    handler: async (args, ctx) => {
      attachReportDetailSink(ctx, createReportDetailSink(pi));
      report(ctx, name, "info", "running…");
      await options.handler(args, ctx);
    },
  });
}
