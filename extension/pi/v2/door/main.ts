// The host CLI's process entry (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77):
// `node extension/pi/v2/door/main.ts <verb> --name=value…`, invoked by the Python door.
//
// The exit contract: one JSON envelope line on stdout and exit 0; a usage error on stderr and exit
// 2; a fault (any throw) on stderr and exit 1. Stdout stays empty on every non-zero exit. The
// process exits from the write callback, so lingering handles cannot keep it alive and the line is
// flushed first. When `PERK_V2_TEST_GATE` is set, the test gate (`testGate.ts`) is composed first,
// before any store work, and a malformed value is a fault.

import { runCli } from "./cli.ts";
import { testGateFromEnv } from "./testGate.ts";

function writeThenExit(stream: NodeJS.WriteStream, text: string, code: number): void {
  stream.write(text, () => process.exit(code));
}

try {
  const onVerify = testGateFromEnv(process.env);
  const result = await runCli(process.argv.slice(2), onVerify === undefined ? {} : { onVerify });
  if (result.kind === "usage") {
    writeThenExit(process.stderr, `perk v2 host: ${result.message}\n`, 2);
  } else {
    writeThenExit(process.stdout, `${JSON.stringify(result.envelope)}\n`, 0);
  }
} catch (error) {
  const shown = error instanceof Error ? (error.stack ?? error.message) : String(error);
  writeThenExit(process.stderr, `perk v2 host fault: ${shown}\n`, 1);
}
