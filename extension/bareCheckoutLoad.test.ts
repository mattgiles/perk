// The bare-checkout load proof: a published-shape checkout of perk — `extension/` (v2 workspace
// included), `shared/`, `prompts/`, `agents/`, `package.json`, and NO `node_modules` — links the
// whole v1 import graph once only the peer packages pi's host-alias set provides are present,
// while the v2 host entry fails to link there because v2's own dependencies are genuinely absent.
//
// Scope, honestly: this is a MODULE-LINK proof over the full v1 graph — the entry plus the two
// seams production defers behind `await import(…)` (`workerMain.ts` runs `main()` at module scope,
// so it is never imported) — not an activation proof. Real activation needs a live `ExtensionAPI`
// and host admission; `index.test.ts` covers it with installed dependencies, and it does not vary
// with v2's presence. The static nets beside it are `bareImportGuard.test.ts` (v1) and
// `pi/v2/layeringGuard.test.ts` (v1 ↔ v2).

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { v1ExtensionFiles } from "./testing/v1Corpus.ts";

const ROOT = resolve(import.meta.dirname, "..");

/** The seams production defers behind a dynamic import — the probe must link each one. */
const DEFERRED_SEAMS = ["./pi/activation.ts", "./worker/stageExecution.ts"];

const PROBE_V1 = [
  'await import("./extension/index.ts");',
  'await import("./extension/pi/activation.ts");',
  'await import("./extension/worker/stageExecution.ts");',
  'console.log("perk-v1-linked");',
  "",
].join("\n");

const PROBE_V2 = 'await import("./extension/pi/v2/host.ts");\n';

/** Every production `await import("…")` literal under the v1 corpus (comments stripped). */
function deferredImports(): Set<string> {
  const found = new Set<string>();
  const production = v1ExtensionFiles().filter(
    (file) => file.endsWith(".ts") && !file.endsWith(".test.ts") && !file.startsWith("testing/"),
  );
  for (const file of production) {
    const stripped = readFileSync(join(import.meta.dirname, file), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    for (const match of stripped.matchAll(/await import\("([^"]+)"\)/g)) {
      if (match[1] !== undefined) found.add(match[1]);
    }
  }
  return found;
}

/** Every directory named `node_modules` under `dir`. */
function nodeModulesDirs(dir: string): string[] {
  return readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name === "node_modules")
    .map((entry) => join(entry.parentPath, entry.name));
}

function run(
  cwd: string,
  probe: string,
): { status: number | null; stdout: string; stderr: string } {
  const result = spawnSync(process.execPath, [probe], { cwd, encoding: "utf8", timeout: 60_000 });
  return { status: result.status, stdout: result.stdout, stderr: result.stderr };
}

test("a bare checkout links the whole v1 graph with only the peers present; v2 cannot link there", () => {
  // The probe's seam list is the production one: a third deferred seam fails here until linked.
  assert.deepEqual([...deferredImports()].sort(), DEFERRED_SEAMS);

  const tmp = mkdtempSync(join(tmpdir(), "perk-bare-checkout-"));
  try {
    // 1. The checkout: the published surface, any node_modules pruned, v2 present.
    cpSync(join(ROOT, "extension"), join(tmp, "extension"), {
      recursive: true,
      filter: (src) => basename(src) !== "node_modules",
    });
    for (const dir of ["shared", "prompts", "agents"]) {
      cpSync(join(ROOT, dir), join(tmp, dir), { recursive: true });
    }
    cpSync(join(ROOT, "package.json"), join(tmp, "package.json"));
    assert.ok(existsSync(join(tmp, "extension/pi/v2/host.ts")), "the v2 workspace is present");
    assert.deepEqual(
      nodeModulesDirs(join(tmp, "extension")),
      [],
      "no node_modules under extension/",
    );

    // 2. The probes.
    writeFileSync(join(tmp, "probe-v1.mjs"), PROBE_V1);
    writeFileSync(join(tmp, "probe-v2.mjs"), PROBE_V2);

    // 3. Isolation control: with no peer provided, v1 cannot link — the fixture does not resolve
    // the repo's node_modules by accident.
    const isolated = run(tmp, "probe-v1.mjs");
    assert.notEqual(isolated.status, 0, "v1 does not link before the peers are provided");
    assert.match(isolated.stderr, /ERR_MODULE_NOT_FOUND/);

    // 4. The host-alias stand-in: exactly the peer packages, linked from the repo's install.
    const manifest: unknown = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
    assert.ok(typeof manifest === "object" && manifest !== null);
    const peers: unknown = Reflect.get(manifest, "peerDependencies");
    assert.ok(typeof peers === "object" && peers !== null, "package.json declares peers");
    const peerNames = Object.keys(peers);
    assert.ok(peerNames.length > 0, "at least one peer");
    for (const name of peerNames) {
      const target = resolve(ROOT, "node_modules", name);
      assert.ok(existsSync(target), `${target} exists — run \`npm ci\` first`);
      const link = join(tmp, "node_modules", name);
      mkdirSync(dirname(link), { recursive: true });
      symlinkSync(target, link);
    }

    // 5. The whole v1 graph links.
    const v1 = run(tmp, "probe-v1.mjs");
    assert.equal(v1.status, 0, `v1 links with only the peers present:\n${v1.stderr}`);
    assert.match(v1.stdout, /perk-v1-linked/);

    // 6. v2's own dependencies are absent here, so its host entry cannot link.
    const v2 = run(tmp, "probe-v2.mjs");
    assert.notEqual(v2.status, 0, "the v2 host entry does not link without its dependencies");
    assert.match(v2.stderr, /ERR_MODULE_NOT_FOUND/);
    assert.match(v2.stderr, /@earendil-works\/(chord|pi-durable)/);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
