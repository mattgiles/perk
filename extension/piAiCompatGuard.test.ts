// Compat-entrypoint guard for the pinned pi toolchain (defect env-1's regression pin).
//
// Settings-delivered Pi packages are deliberately unpinned, and the current pi-web-access imports
// `@earendil-works/pi-ai/compat`. The extension loader of the repo-pinned SDK resolves that import
// against the pi-ai copy nested inside the SDK — so if the devDeps pin regresses below pi-ai 0.80
// (the first compat-bearing line), every remote-runner drive logs a non-fatal
// "Failed to load extension: Cannot find module '…/pi-ai/dist/index.js/compat'" and silently loses
// the web tools. This guard resolves the pi-ai copy *as the SDK's loader would* (the nested copy
// when present, else the deduped top-level — mirroring the harness's `fauxModelRuntime`
// probe) and asserts its `exports` map carries `"./compat"`.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

test("the SDK-resolved pi-ai exports ./compat (unpinned pi-web-access imports it)", () => {
  const pcaIndex = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
  // pcaIndex is <…>/pi-coding-agent/dist/index.js → the package root is one level up from dist/.
  const pcaRoot = resolve(dirname(pcaIndex), "..");
  const nested = join(pcaRoot, "node_modules", "@earendil-works", "pi-ai", "package.json");
  // Fallback mirrors the pcaIndex shape: the top-level resolve lands on <root>/dist/index.js.
  const topLevelRoot = resolve(
    dirname(fileURLToPath(import.meta.resolve("@earendil-works/pi-ai"))),
    "..",
  );
  const piAiPackageJson = existsSync(nested) ? nested : join(topLevelRoot, "package.json");
  const pkg = JSON.parse(readFileSync(piAiPackageJson, "utf8")) as {
    version?: string;
    exports?: Record<string, unknown>;
  };
  assert.ok(
    pkg.exports && "./compat" in pkg.exports,
    `pi-ai ${pkg.version ?? "?"} at ${piAiPackageJson} has no "./compat" export — a pi toolchain ` +
      "pin below 0.80 reproduces the remote runner's silent web-tool loss (env-1): " +
      "settings-delivered packages (pi-web-access) import @earendil-works/pi-ai/compat.",
  );
});
