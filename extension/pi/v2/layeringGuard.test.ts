// The v2 guard set (docs/design/pi-durable-v2-foundations.md P10 — layers are enforced): v1 and
// v2 never import each other, every bare package v2 names is declared in its own manifest and
// confined to the Durable homes, and inside v2 the kernel imports only the kernel — so the kernel
// stays Durable-free transitively. The rules live in `testing/layering.ts`; each live assertion
// below is paired with synthetic controls fed to the SAME functions, so a rule that stops biting
// fails here instead of passing vacuously.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { extractSpecifiers } from "../../testing/importGraph.ts";
import { readExtensionFile, v1Files, v2Files } from "./testing/corpus.ts";
import {
  checkCrossImports,
  checkDependencyConfinement,
  checkLayering,
  packageName,
  V2_PACKAGE_NAME,
} from "./testing/layering.ts";

const GUARD_FILE = "pi/v2/layeringGuard.test.ts";

/** The workspace manifest, parsed and narrowed to an object. */
function v2Manifest(): object {
  const manifest: unknown = JSON.parse(
    readFileSync(resolve(import.meta.dirname, "package.json"), "utf8"),
  );
  assert.ok(typeof manifest === "object" && manifest !== null, "the manifest is an object");
  return manifest;
}

/** The workspace manifest's declared dependency names. */
function declaredPackages(): Set<string> {
  const dependencies: unknown = Reflect.get(v2Manifest(), "dependencies");
  assert.ok(
    typeof dependencies === "object" && dependencies !== null,
    "the manifest declares dependencies",
  );
  return new Set(Object.keys(dependencies));
}

/** A synthetic corpus: the file list and a reader over it. */
function corpus(sources: Record<string, string>): {
  files: string[];
  read: (file: string) => string;
} {
  const map = new Map(Object.entries(sources));
  return {
    files: [...map.keys()].sort(),
    read: (file) => {
      const text = map.get(file);
      assert.ok(text !== undefined, `the synthetic corpus holds ${file}`);
      return text;
    },
  };
}

// ── live ────────────────────────────────────────────────────────────────────────────────────────

test("both corpora are live: v2 holds the host and this guard; v1 holds index.ts and no v2 file", () => {
  const v2 = v2Files();
  assert.ok(v2.includes("pi/v2/host.ts"), "the v2 corpus contains the host entry");
  assert.ok(v2.includes(GUARD_FILE), "the v2 corpus contains this guard");
  const v1 = v1Files();
  assert.ok(v1.includes("index.ts"), "the v1 corpus contains index.ts");
  assert.deepEqual(
    v1.filter((file) => file.startsWith("pi/v2/")),
    [],
    "no v2 file in the v1 corpus",
  );
  assert.deepEqual(
    [...v1, ...v2].filter((file) => file.split("/").includes("node_modules")),
    [],
    "no node_modules segment in either corpus",
  );
});

test("v1 and v2 never import each other", () => {
  // The package-name arm guards the name the install actually links (`node_modules/perk-v2`).
  assert.equal(Reflect.get(v2Manifest(), "name"), V2_PACKAGE_NAME, "the guarded package name");
  assert.deepEqual(checkCrossImports(v2Files(), v1Files(), readExtensionFile), {
    v2ToV1: [],
    v1ToV2: [],
    staleAllowlist: [],
  });
});

test("every bare package v2 names is declared and confined to the Durable homes", () => {
  const declared = declaredPackages();
  assert.ok(declared.size > 0, "the workspace declares dependencies");
  assert.ok(declared.has("@earendil-works/pi-durable"), "pi-durable is declared");
  assert.deepEqual(checkDependencyConfinement(v2Files(), readExtensionFile, declared), {
    undeclared: [],
    leaked: [],
  });
  // Positive floor: the extractor sees the guarded vocabulary in the host entry.
  const hostPackages = extractSpecifiers(readExtensionFile("pi/v2/host.ts")).map(packageName);
  assert.ok(
    hostPackages.some((name) => declared.has(name)),
    "the host entry imports ≥1 declared package",
  );
});

test("inside v2, every relative edge obeys the layers — no cycles, nothing unresolved", () => {
  const { edges, violations, cycles, unresolved } = checkLayering(v2Files(), readExtensionFile);
  assert.deepEqual(
    { violations, cycles, unresolved },
    { violations: [], cycles: [], unresolved: [] },
  );
  assert.ok(
    edges.get("pi/v2/host.test.ts")?.includes("pi/v2/host.ts"),
    "the edge map carries the live host.test.ts → host.ts edge",
  );
});

// ── controls ────────────────────────────────────────────────────────────────────────────────────

test("control: cross-generation imports bite in both directions, tests included", () => {
  const v2 = corpus({
    "pi/v2/kernel/x.ts": 'import { a } from "../../../substrate/config.ts";\n',
    "pi/v2/x.test.ts":
      'import { h } from "../../testing/harness.ts";\nimport { g } from "../../testing/importGraph.ts";\n',
  });
  const v1 = corpus({
    "index.ts": 'import { openHost } from "./pi/v2/host.ts";\n',
    "substrate/x.test.ts": 'import { openHost } from "../pi/v2/host.ts";\n',
    "substrate/config.ts": "export const a = 1;\n",
    "testing/harness.ts": "export const h = 1;\n",
    "testing/importGraph.ts": "export const g = 1;\n",
  });
  const read = (file: string) => (file.startsWith("pi/v2/") ? v2.read(file) : v1.read(file));
  const result = checkCrossImports(v2.files, v1.files, read);
  assert.deepEqual(result.v2ToV1, [
    'pi/v2/kernel/x.ts: "../../../substrate/config.ts" → substrate/config.ts',
    'pi/v2/x.test.ts: "../../testing/harness.ts" → testing/harness.ts',
  ]);
  assert.deepEqual(result.v1ToV2, [
    'index.ts: "./pi/v2/host.ts" → pi/v2/host.ts',
    'substrate/x.test.ts: "../pi/v2/host.ts" → pi/v2/host.ts',
  ]);
  assert.deepEqual(result.staleAllowlist, []);
});

test("control: a v1 import of the workspace's package name or a subpath bites; lookalikes do not", () => {
  const v1 = corpus({
    "substrate/y.test.ts": `import { openHost } from "${V2_PACKAGE_NAME}/host.ts";\n`,
    "testing/z.ts": `import "${V2_PACKAGE_NAME}";\n`,
    "substrate/w.ts": `import { x } from "${V2_PACKAGE_NAME}-extra/x.ts";\nimport { y } from "@scope/${V2_PACKAGE_NAME}";\n`,
  });
  const result = checkCrossImports([], v1.files, v1.read);
  assert.deepEqual(result.v1ToV2, [
    `substrate/y.test.ts: "${V2_PACKAGE_NAME}/host.ts" → the ${V2_PACKAGE_NAME} workspace package`,
    `testing/z.ts: "${V2_PACKAGE_NAME}" → the ${V2_PACKAGE_NAME} workspace package`,
  ]);
});

test("control: the production allowlist admits only used, existing v1 files", () => {
  const v2 = corpus({
    "pi/v2/durable/records.ts": 'import { a } from "../../../substrate/a.ts";\n',
  });
  const v1 = corpus({ "substrate/a.ts": "export const a = 1;\n", "substrate/b.ts": "" });
  const read = (file: string) => (file.startsWith("pi/v2/") ? v2.read(file) : v1.read(file));
  const used = checkCrossImports(v2.files, v1.files, read, {
    production: ["substrate/a.ts"],
    dev: [],
  });
  assert.deepEqual(used, { v2ToV1: [], v1ToV2: [], staleAllowlist: [] });
  const unused = checkCrossImports(v2.files, v1.files, read, {
    production: ["substrate/a.ts", "substrate/b.ts"],
    dev: [],
  });
  assert.deepEqual(unused.staleAllowlist, ["substrate/b.ts"]);
  const absent = checkCrossImports(v2.files, v1.files, read, {
    production: ["substrate/a.ts", "substrate/gone.ts"],
    dev: [],
  });
  assert.deepEqual(absent.staleAllowlist, ["substrate/gone.ts"]);
  // A dev-allowlisted file is not a production licence.
  const devOnly = checkCrossImports(v2.files, v1.files, read, {
    production: [],
    dev: ["substrate/a.ts"],
  });
  assert.deepEqual(devOnly.v2ToV1, [
    'pi/v2/durable/records.ts: "../../../substrate/a.ts" → substrate/a.ts',
  ]);
});

test("control: bare packages leak from the kernel, and an undeclared one is caught anywhere", () => {
  const declared = new Set(["@earendil-works/pi-durable", "@earendil-works/chord"]);
  const { files, read } = corpus({
    "pi/v2/kernel/reconcile.ts": 'import { Harness } from "@earendil-works/pi-durable";\n',
    "pi/v2/kernel/reconcile.test.ts": 'import { Harness } from "@earendil-works/pi-durable";\n',
    "pi/v2/host.ts":
      'import pad from "left-pad";\nimport { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";\nimport { join } from "node:path";\n',
    "pi/v2/durable/records.ts": 'import { Harness } from "@earendil-works/pi-durable";\n',
    "pi/v2/observe.ts": 'import { Harness } from "@earendil-works/pi-durable";\n',
  });
  assert.deepEqual(checkDependencyConfinement(files, read, declared), {
    undeclared: ['pi/v2/host.ts: "left-pad"'],
    leaked: [
      'pi/v2/kernel/reconcile.test.ts: "@earendil-works/pi-durable"',
      'pi/v2/kernel/reconcile.ts: "@earendil-works/pi-durable"',
      'pi/v2/observe.ts: "@earendil-works/pi-durable"',
    ],
  });
});

test("control: the layers bite — kernel → kernel only, durable → kernel | durable", () => {
  const { files, read } = corpus({
    "pi/v2/host.ts": 'import { r } from "./durable/records.ts";\n',
    "pi/v2/host.test.ts": 'import { t } from "./kernel/types.ts";\n',
    "pi/v2/kernel/types.ts": "export const t = 1;\n",
    "pi/v2/kernel/x.ts":
      'import { h } from "../host.ts";\nimport { r } from "../durable/records.ts";\n',
    "pi/v2/kernel/x.test.ts": 'import { r } from "../durable/records.ts";\n',
    "pi/v2/durable/records.ts":
      'import { h } from "../host.ts";\nimport { t } from "../kernel/types.ts";\nexport const r = 1;\n',
  });
  const { violations, cycles, unresolved } = checkLayering(files, read);
  assert.deepEqual(violations.sort(), [
    "pi/v2/durable/records.ts → pi/v2/host.ts",
    "pi/v2/kernel/x.test.ts → pi/v2/durable/records.ts",
    "pi/v2/kernel/x.ts → pi/v2/durable/records.ts",
    "pi/v2/kernel/x.ts → pi/v2/host.ts",
  ]);
  // host.ts → durable/records.ts → host.ts is also a cycle (the layer rule and the cycle rule
  // are independent checks).
  assert.deepEqual(cycles, [["pi/v2/durable/records.ts", "pi/v2/host.ts"]]);
  assert.deepEqual(unresolved, []);
});

test("control: a kernel cycle and an unresolved v2 target are reported; outside targets are not", () => {
  const { files, read } = corpus({
    "pi/v2/kernel/a.ts": 'import { b } from "./b.ts";\nimport { m } from "./missing.ts";\n',
    "pi/v2/kernel/b.ts": 'import { a } from "./a.ts";\n',
    "pi/v2/testing/x.ts": 'import { g } from "../../../testing/importGraph.ts";\n',
  });
  const { violations, cycles, unresolved } = checkLayering(files, read);
  assert.deepEqual(violations, []);
  assert.deepEqual(cycles, [["pi/v2/kernel/a.ts", "pi/v2/kernel/b.ts"]]);
  assert.deepEqual(unresolved, ['pi/v2/kernel/a.ts: "./missing.ts" → pi/v2/kernel/missing.ts']);
});
