// The perk-dev module census tracer, loaded into every Node process of a profiled launch via
// `NODE_OPTIONS=--import=<this file>`. Inert unless PERK_MODULE_CENSUS_DIR names a directory.
//
// It records what Node's loader RESOLVES (ESM and CJS both pass through the sync `registerHooks`
// resolve hook, Node >= 22.15) into an in-memory buffer — no per-resolve I/O perturbing the CPU
// profile — and flushes one JSONL file per process (`census-<pid>.jsonl`) on `exit`: a header
// line describing the process, then one `resolve` line per resolution. A process the harness
// terminates after its startup marker still runs its exit handlers because SIGTERM is turned
// into an orderly `process.exit(0)` (Node's default disposition would skip both this flush and
// `--cpu-prof`'s profile write); the harness's SIGTERM→SIGKILL grace is the write window.
import { appendFileSync, mkdirSync } from "node:fs";
import * as nodeModule from "node:module";
import { join } from "node:path";

const censusDir = process.env.PERK_MODULE_CENSUS_DIR;

if (censusDir) {
  const registerHooks =
    typeof nodeModule.registerHooks === "function" ? nodeModule.registerHooks : undefined;
  const lines = [
    JSON.stringify({
      kind: "process",
      pid: process.pid,
      ppid: process.ppid,
      argv: process.argv,
      execPath: process.execPath,
      node: process.version,
      cwd: process.cwd(),
      hooks: registerHooks !== undefined,
    }),
  ];

  if (registerHooks !== undefined) {
    registerHooks({
      resolve(specifier, context, nextResolve) {
        const result = nextResolve(specifier, context);
        lines.push(
          JSON.stringify({
            kind: "resolve",
            url: result.url,
            parent: context.parentURL ?? null,
            specifier,
          }),
        );
        return result;
      },
    });
  }

  const flush = () => {
    if (lines.length === 0) {
      return;
    }
    try {
      mkdirSync(censusDir, { recursive: true });
      appendFileSync(join(censusDir, `census-${process.pid}.jsonl`), `${lines.join("\n")}\n`);
    } catch {
      // Best-effort: a census that cannot be written must never break the traced process.
    }
    lines.length = 0;
  };

  process.on("exit", flush);
  process.once("SIGTERM", () => {
    process.exit(0);
  });
}
