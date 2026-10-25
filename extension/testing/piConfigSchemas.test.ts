// The Pi config-schema loader and validators: the resolved dev package is the dev pin and ships
// both schemas; each compiled validator accepts perk's shapes and rejects a single fault on a
// perk-written key (so a mis-resolved `$ref` or a vacuous schema cannot pass silently); the
// reported thinking enum is the one the validator enforces; and the harness's planted
// `models.json` (loaded by a real Pi in the worker e2e) conforms. The perk-producer matrix — real
// `perk init` convergence validated through `piConfigSchemasLive.ts` — lives in
// `tests/test_pi_config_schemas.py`.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { plantGlobalModelAuth } from "./harness.ts";
import {
  type ConfigValidator,
  loadPiConfigSchemas,
  PI_DEV_PACKAGE,
  piDevPin,
  schemaErrors,
} from "./piConfigSchemas.ts";

const schemas = loadPiConfigSchemas();

/** True when some `"<pointer>: …"` error sits at `pointer` or beneath it. */
function faultedAt(errors: readonly string[], pointer: string): boolean {
  return errors.some((error) => {
    const at = error.slice(0, error.indexOf(": "));
    return at === pointer || at.startsWith(`${pointer}/`);
  });
}

function assertSingleFaults(
  validator: ConfigValidator,
  base: Record<string, unknown>,
  rows: readonly { readonly pointer: string; readonly document: unknown }[],
): void {
  assert.deepEqual(schemaErrors(validator, base), [], "the unfaulted base must conform");
  for (const { pointer, document } of rows) {
    const errors = schemaErrors(validator, document);
    assert.ok(errors.length > 0, `a fault at ${pointer} was accepted`);
    assert.ok(faultedAt(errors, pointer), `no error at ${pointer}: ${errors.join("; ")}`);
  }
}

test("the resolved dev pi-coding-agent is the dev pin and ships both config schemas", () => {
  const rootManifest = JSON.parse(
    readFileSync(join(import.meta.dirname, "..", "..", "package.json"), "utf8"),
  );
  assert.equal(piDevPin(), rootManifest.devDependencies[PI_DEV_PACKAGE]);
  assert.equal(schemas.version, piDevPin());
  assert.ok(schemas.thinkingLevels.length > 0);
  for (const level of schemas.thinkingLevels) assert.equal(typeof level, "string");
});

test("the settings validator accepts perk's shapes and rejects each single fault on the perk-written keys", () => {
  const base: Record<string, unknown> = {
    packages: ["npm:a", { source: "npm:b", extensions: [], skills: [], prompts: [], themes: [] }],
    defaultProvider: "anthropic",
    defaultModel: "claude-opus-4-1",
    defaultThinkingLevel: "high",
    compaction: { enabled: false, reserveTokens: 8192, keepRecentTokens: 20000 },
    defaultTools: ["+tool_search"],
  };
  const compaction = { enabled: false, reserveTokens: -1, keepRecentTokens: 20000 };
  assertSingleFaults(schemas.settings, base, [
    // An unresolved `$ref` into `$defs` would reject the base too — this row proves it resolves.
    { pointer: "/defaultThinkingLevel", document: { ...base, defaultThinkingLevel: "bogus" } },
    { pointer: "/packages/0", document: { ...base, packages: [42] } },
    { pointer: "/packages/0", document: { ...base, packages: [{ extensions: [] }] } },
    { pointer: "/compaction/reserveTokens", document: { ...base, compaction } },
    { pointer: "/defaultTools", document: { ...base, defaultTools: "+tool_search" } },
  ]);
});

test("every reported thinking level is one the settings validator enforces", () => {
  for (const level of schemas.thinkingLevels) {
    assert.deepEqual(schemaErrors(schemas.settings, { defaultThinkingLevel: level }), [], level);
  }
  assert.notDeepEqual(schemaErrors(schemas.settings, { defaultThinkingLevel: "bogus" }), []);
});

test("the models validator accepts a minimal provider and rejects each single fault", () => {
  const provider = {
    baseUrl: "http://127.0.0.1:9/v1",
    api: "openai-completions",
    models: [{ id: "m" }],
  };
  assertSingleFaults(schemas.models, { providers: { p: provider } }, [
    { pointer: "/", document: {} },
    {
      pointer: "/providers/p/models/0",
      document: { providers: { p: { ...provider, models: [{}] } } },
    },
    { pointer: "/providers/p/api", document: { providers: { p: { ...provider, api: "" } } } },
  ]);
});

test("the harness's planted models.json conforms to the pinned Pi models schema", (t) => {
  const dir = mkdtempSync(join(tmpdir(), "perk-pi-models-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  plantGlobalModelAuth(dir, { provider: "perk-fixture", key: "k" });
  const planted: unknown = JSON.parse(readFileSync(join(dir, "models.json"), "utf8"));
  assert.deepEqual(schemaErrors(schemas.models, planted), []);
});
