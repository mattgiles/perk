// The containment probes' owner process (dev-only): `node owner.ts <config.json>` (see
// `OwnerConfig` in `fixture.ts`). It runs ONE command through the chosen execution environment and
// prints a line per milestone on stdout, so a test can SIGKILL it at exactly that point:
//
//   daemon <pid>  supervised only: the pi-env daemon answered `hello` (its pid, for teardown)
//   connected     the environment is up (supervised: after a warm-up `exec(["true"])`)
//   exec          immediately before `env.exec(program, …)` is called
//   started       the command's first stdout chunk arrived
//   ready         every `expect`ed identity record exists in the probe directory
//   settled …     `exec` settled (its exit code or error code)
//
// It never exits on its own before its 60 s lifetime bound, except on stdin EOF: with
// `cleanOnStdinEnd` it first runs `env.cleanup()` and closes the connection (the clean-close
// control); without it, it just exits (teardown only). Stdout writes to a pipe are synchronous on
// Linux, so a milestone line is out before the step that follows it runs.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { argv, exit, stderr, stdin, stdout } from "node:process";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { ExecutionEnv } from "@earendil-works/pi-durable/env";
import { NodeExecutionEnv } from "@earendil-works/pi-durable/env/node";
import { Connection, localDaemon, RemoteExecutionEnv } from "@earendil-works/pi-env";
import type { OwnerConfig } from "./fixture.ts";
import { MARKER_EPOCH, MARKER_STORE, readIdentity } from "./procfs.ts";

const LIFETIME_MS = 60_000;
const context = BACKGROUND_CONTEXT;

function say(line: string): void {
  stdout.write(`${line}\n`);
}

const configPath = argv[2];
if (configPath === undefined) {
  stderr.write("usage: node owner.ts <config.json>\n");
  exit(2);
}
// The config is written by `startOwner` from a typed `OwnerConfig`.
const config = JSON.parse(readFileSync(configPath, "utf8")) as OwnerConfig;

setTimeout(() => exit(0), LIFETIME_MS);

let connection: Connection | undefined;
let env: ExecutionEnv;
if (config.env === "supervised") {
  const daemon = localDaemon();
  const supervised = new Connection({
    command: config.daemonWrap === "setsid" ? ["setsid", daemon] : [daemon],
    onLog: (text) => stderr.write(text),
  });
  connection = supervised;
  env = new RemoteExecutionEnv({ connection: supervised, id: "pi-env:local", cwd: config.cwd });
  const warm = await env.exec(["true"], undefined, context);
  if (!warm.ok || warm.value.exitCode !== 0) {
    const why = warm.ok
      ? `exit=${warm.value.exitCode}`
      : `${warm.error.code}: ${warm.error.message}`;
    stderr.write(`warm-up exec failed: ${why}\n`);
    exit(3);
  }
  say(`daemon ${(await supervised.info()).pid}`);
} else {
  env = new NodeExecutionEnv({ cwd: config.cwd });
}
say("connected");

stdin.on("end", () => {
  void (async () => {
    if (config.cleanOnStdinEnd === true) {
      await env.cleanup(context);
      connection?.close();
    }
    exit(0);
  })();
});
stdin.resume();

const poll = setInterval(() => {
  if (config.expect.every((name) => readIdentity(join(config.dir, `${name}.pid`)) !== undefined)) {
    clearInterval(poll);
    say("ready");
  }
}, 10);

let started = false;
say("exec");
env
  .exec(
    config.program,
    {
      env: { [MARKER_STORE]: config.store, [MARKER_EPOCH]: String(config.epoch) },
      onOutput: (_text, _context, info) => {
        if (started || info.stream !== "stdout") return;
        started = true;
        say("started");
      },
    },
    context,
  )
  .then(
    (result) =>
      say(`settled ${result.ok ? `exit=${result.value.exitCode}` : `error=${result.error.code}`}`),
    (error: unknown) => say(`settled threw=${JSON.stringify(String(error))}`),
  );
