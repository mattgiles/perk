// The SIGKILL proof's host process (dev-only): `node hostChild.ts <config.json>` (see
// `HostChildConfig` in `host.ts`). It runs one `start` over the fake program with the default lock
// options — real procfs liveness and its real identity — and prints a line per milestone on stdout,
// so a test can SIGKILL it at exactly that point:
//
//   <role>-blocked   the role's phase started and will never settle (`blockRole`)
//   <role>-accepted  the role's phase committed its acceptance
//   outcome <kind>   `runHost` returned (then it exits 0)
//
// Every phase start is appended to the shared phase log as `"<role> <pid>\n"`. It never exits on
// its own before its 60 s lifetime bound unless `runHost` returns. Stdout writes to a pipe are
// synchronous on Linux, so a milestone line is out before the step that follows it runs.

import { readFileSync } from "node:fs";
import { argv, exit, stderr, stdout } from "node:process";
import { runHost } from "../host.ts";
import { C1, T1 } from "./binding.ts";
import {
  fakeProgram,
  filePhaseHooks,
  type HostChildConfig,
  hostOptions,
  observed,
} from "./host.ts";

const LIFETIME_MS = 60_000;

function say(line: string): void {
  stdout.write(`${line}\n`);
}

const configPath = argv[2];
if (configPath === undefined) {
  stderr.write("usage: node hostChild.ts <config.json>\n");
  exit(2);
}
// The config is written by `startHostChild` from a typed `HostChildConfig`.
const config = JSON.parse(readFileSync(configPath, "utf8")) as HostChildConfig;

setTimeout(() => exit(0), LIFETIME_MS);

const hooks = filePhaseHooks(config.phaseLog, { block: config.blockRole, say });
const outcome = await runHost(hostOptions(config.storeDir, fakeProgram({ hooks })), {
  type: "start",
  observe: observed(T1, C1),
});
say(`outcome ${outcome.kind}`);
exit(0);
