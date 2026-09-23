// The host-SDK bridge (contracts.md §8.73), proven at exactly one layer per branch:
//   - pure units (facade text/URL, root matching, Node-equivalent exports resolution, the hook
//     state machine over fake nextResolve/nextLoad) — in-process, no hooks registered;
//   - the install decision table (every registry/opt-out/capability/failure branch) — in-process
//     over a fresh `global: {}` with a recording `registerHooks` fake;
//   - five end-to-end fixture-process scenarios (a fixture "Pi" host + two fixture consumers +
//     decoy SDK copies, materialized into a temp tree because `node_modules/`/`dist/` segments are
//     gitignored) — public Node APIs only, no registry branch re-proven here;
//   - the census drift guard over the installed consumers' import specifiers.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, sep } from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { extractSpecifiers } from "../testing/importGraph.ts";
import {
  type ActiveBridgeRegistry,
  BRIDGE_DISABLE_ENV,
  BRIDGE_MARKER,
  BRIDGE_REGISTRY_KEY,
  BRIDGE_SCHEMA,
  type BridgePorts,
  type BridgeStatus,
  createBridgeHooks,
  deriveHostEntry,
  describeBridge,
  facadeSource,
  facadeUrl,
  HOST_PACKAGE_NAME,
  installNativeSdkBridge,
  NATIVE_CONSUMER_INSTALL_ROOT,
  NATIVE_SDK_CENSUS,
  NATIVE_SDK_CONSUMERS,
  resolvePackageEntry,
  rootOf,
  verifyConsumerRoots,
} from "./nativeSdkBridge.ts";

const scratchDirs: string[] = [];
function scratch(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), `perk-bridge-${prefix}-`));
  scratchDirs.push(dir);
  return dir;
}
after(() => {
  for (const dir of scratchDirs) rmSync(dir, { recursive: true, force: true });
});

function writeJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

// ---------------------------------------------------------------------------
// Pure: facadeSource / facadeUrl / rootOf
// ---------------------------------------------------------------------------

test("facadeSource: string export names (default included), read once from the registry namespace", () => {
  const source = facadeSource("typebox", ["Type", "default", "not an identifier"]);
  assert.equal(
    source,
    [
      'const registry = globalThis[Symbol.for("perk.native-sdk-bridge")];',
      'const ns = registry.namespaces.get("typebox");',
      'const _0 = ns["Type"];',
      'export { _0 as "Type" };',
      'const _1 = ns["default"];',
      'export { _1 as "default" };',
      'const _2 = ns["not an identifier"];',
      'export { _2 as "not an identifier" };',
      "",
    ].join("\n"),
  );
  assert.doesNotMatch(source, /\bimport\b/);
});

test("facadeUrl: one physical address — fileURLToPath drops the marker query", () => {
  const entry = join(sep, "host", "dist", "index.js");
  const url = facadeUrl(pathToFileURL(entry).href, "@earendil-works/pi-ai/compat");
  assert.ok(url.includes(`?${BRIDGE_MARKER}=%40earendil-works%2Fpi-ai%2Fcompat`));
  assert.equal(fileURLToPath(url), entry);
});

test("rootOf: exact root and descendants match; look-alike siblings and nested node_modules do not", () => {
  const root = join(sep, "install", "pi-subagents");
  const roots = [root];
  assert.equal(rootOf(root, roots), root);
  assert.equal(rootOf(join(root, "x.js"), roots), root);
  assert.equal(rootOf(join(root, "src", "deep", "x.js"), roots), root);
  assert.equal(rootOf(`${root}-fork${sep}x.js`, roots), null);
  assert.equal(rootOf(join(root, "node_modules", "dep", "x.js"), roots), null);
  assert.equal(rootOf(join(sep, "elsewhere", "x.js"), roots), null);
});

// ---------------------------------------------------------------------------
// Pure: resolvePackageEntry (Node's conditional-exports walk)
// ---------------------------------------------------------------------------

test("resolvePackageEntry: the exports table", () => {
  const root = scratch("exports");
  for (const file of ["dist/a.js", "dist/b.js", "dist/main.js", "index.js"]) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), "export {};\n");
  }
  const real = (rel: string) => realpathSync(join(root, rel));
  const cases: [string, unknown, string | null][] = [
    ["string target", { exports: "./dist/a.js" }, real("dist/a.js")],
    ["dot-keyed string", { exports: { ".": "./dist/a.js" } }, real("dist/a.js")],
    ["{ import } conditions", { exports: { ".": { import: "./dist/a.js" } } }, real("dist/a.js")],
    [
      "node-first declaration order",
      { exports: { ".": { node: "./dist/a.js", import: "./dist/b.js" } } },
      real("dist/a.js"),
    ],
    [
      "nested conditions",
      { exports: { ".": { node: { import: "./dist/b.js" } } } },
      real("dist/b.js"),
    ],
    [
      "array: first resolvable member",
      { exports: { ".": ["./missing.js", "./dist/b.js"] } },
      real("dist/b.js"),
    ],
    ["null blocks", { exports: { ".": null } }, null],
    ["unmatched conditions", { exports: { ".": { require: "./dist/a.js" } } }, null],
    [
      "conditions object without dot keys IS the dot target",
      { exports: { import: "./dist/b.js" } },
      real("dist/b.js"),
    ],
    ["main fallback", { main: "dist/main.js" }, real("dist/main.js")],
    ["index.js fallback", {}, real("index.js")],
    ["unresolvable main falls to index.js", { main: "./nope.js" }, real("index.js")],
    ["non-object manifest", "nope", null],
  ];
  for (const [label, manifest, expected] of cases) {
    assert.equal(resolvePackageEntry(manifest, root), expected, label);
  }
  const bare = scratch("bare");
  assert.equal(resolvePackageEntry({}, bare), null, "nothing to fall back to");
});

// ---------------------------------------------------------------------------
// Pure: createBridgeHooks — the root state machine over fake nextResolve/nextLoad
// ---------------------------------------------------------------------------

function fakeRecord(
  rootStates: Record<string, "armed" | "bridged" | "preloaded">,
): ActiveBridgeRegistry {
  const hostEntryPath = join(sep, "host", "dist", "index.js");
  return {
    schema: BRIDGE_SCHEMA,
    kind: "active",
    hostEntryPath,
    hostEntryUrl: pathToFileURL(hostEntryPath).href,
    roots: new Map(Object.entries(rootStates)),
    namespaces: new Map(),
    facadeSources: new Map(NATIVE_SDK_CENSUS.map((s) => [s, `facade:${s}`])),
  };
}

function hookHarness(record: ActiveBridgeRegistry) {
  const hooks = createBridgeHooks(record);
  const nextResolves: string[] = [];
  const nextLoads: string[] = [];
  const context = { conditions: ["node", "import"], importAttributes: {} };
  return {
    resolve: (specifier: string, parentURL: string | undefined) =>
      hooks.resolve(specifier, { ...context, parentURL }, (s) => {
        nextResolves.push(s);
        return { url: `next:${s}` };
      }),
    load: (url: string) =>
      hooks.load(url, { ...context, format: undefined }, (u) => {
        nextLoads.push(u);
        return { format: "module", source: `next:${u}` };
      }),
    nextResolves,
    nextLoads,
  };
}

const ROOT = join(sep, "install", "pi-subagents");
const inside = (rel: string) => pathToFileURL(join(ROOT, rel)).href;

test("hooks: an outside-parent resolve leaves an armed root armed (a resolve proves no fresh load)", () => {
  const record = fakeRecord({ [ROOT]: "armed" });
  const h = hookHarness(record);
  const out = h.resolve(inside("index.js"), pathToFileURL(join(sep, "pi", "loader.js")).href);
  assert.deepEqual(out, { url: `next:${inside("index.js")}` });
  assert.equal(record.roots.get(ROOT), "armed");
});

test("hooks: a fresh load under an armed root → bridged; its census imports then hit the facades", () => {
  const record = fakeRecord({ [ROOT]: "armed" });
  const h = hookHarness(record);
  const loaded = h.load(inside("index.js"));
  assert.deepEqual(loaded, { format: "module", source: `next:${inside("index.js")}` });
  assert.equal(record.roots.get(ROOT), "bridged");
  for (const specifier of NATIVE_SDK_CENSUS) {
    assert.deepEqual(h.resolve(specifier, inside("index.js")), {
      url: facadeUrl(record.hostEntryUrl, specifier),
      format: "module",
      shortCircuit: true,
    });
  }
  // The exact host entry (path and file: URL forms) maps to the HOST_PACKAGE_NAME facade.
  const expected = {
    url: facadeUrl(record.hostEntryUrl, HOST_PACKAGE_NAME),
    format: "module",
    shortCircuit: true,
  };
  assert.deepEqual(h.resolve(record.hostEntryPath, inside("src/x.js")), expected);
  assert.deepEqual(h.resolve(record.hostEntryUrl, inside("src/x.js")), expected);
  // Non-census specifiers pass through untouched.
  assert.deepEqual(h.resolve("node:fs", inside("index.js")), { url: "next:node:fs" });
  assert.deepEqual(h.resolve("./local.js", inside("index.js")), { url: "next:./local.js" });
  assert.deepEqual(h.resolve("@earendil-works/pi-ai/oauth", inside("index.js")), {
    url: "next:@earendil-works/pi-ai/oauth",
  });
});

test("hooks: an inside-parent resolve of an armed root → preloaded; census imports pass through forever", () => {
  const record = fakeRecord({ [ROOT]: "armed" });
  const h = hookHarness(record);
  assert.deepEqual(h.resolve("./lazy.js", inside("index.js")), { url: "next:./lazy.js" });
  assert.equal(record.roots.get(ROOT), "preloaded");
  // A later fresh load under the root does not re-arm it.
  h.load(inside("lazy.js"));
  assert.equal(record.roots.get(ROOT), "preloaded");
  assert.deepEqual(h.resolve("typebox", inside("lazy.js")), { url: "next:typebox" });
});

test("hooks: a nested-dependency parent is outside every root", () => {
  const record = fakeRecord({ [ROOT]: "bridged" });
  const h = hookHarness(record);
  const nested = pathToFileURL(join(ROOT, "node_modules", "dep", "index.js")).href;
  assert.deepEqual(h.resolve("typebox", nested), { url: "next:typebox" });
  assert.deepEqual(h.resolve("typebox", undefined), { url: "next:typebox" });
  assert.deepEqual(h.resolve("typebox", "data:text/javascript,"), { url: "next:typebox" });
});

test("hooks: load serves a facade URL from the cached source; unknown suffixes and other URLs reach nextLoad", () => {
  const record = fakeRecord({ [ROOT]: "bridged" });
  const h = hookHarness(record);
  assert.deepEqual(h.load(facadeUrl(record.hostEntryUrl, "typebox")), {
    format: "module",
    source: "facade:typebox",
    shortCircuit: true,
  });
  const unknown = facadeUrl(record.hostEntryUrl, "not-in-census");
  assert.deepEqual(h.load(unknown), { format: "module", source: `next:${unknown}` });
  assert.deepEqual(h.load(record.hostEntryUrl), {
    format: "module",
    source: `next:${record.hostEntryUrl}`,
  });
  assert.deepEqual(h.nextLoads, [unknown, record.hostEntryUrl]);
});

// ---------------------------------------------------------------------------
// The install decision table (in-process; the ONLY layer proving the registry branches)
// ---------------------------------------------------------------------------

function fakeNamespaces(omit: string[] = []): Map<string, object> {
  const map = new Map<string, object>();
  for (const specifier of NATIVE_SDK_CENSUS) {
    if (!omit.includes(specifier)) map.set(specifier, { origin: "host", Marker: class {} });
  }
  return map;
}

/** A scratch host package: manifest + entry + a bundle "cli" to hand in as argv[1]. */
function scratchHost(exports: unknown = { ".": "./dist/index.js" }): {
  argv1: string;
  entryPath: string;
} {
  const root = scratch("host");
  writeJson(join(root, "package.json"), { name: HOST_PACKAGE_NAME, type: "module", exports });
  mkdirSync(join(root, "dist", "bundle"), { recursive: true });
  writeFileSync(join(root, "dist", "index.js"), "export const origin = 'unbundled';\n");
  writeFileSync(join(root, "dist", "bundle", "cli.js"), "export {};\n");
  return {
    argv1: join(root, "dist", "bundle", "cli.js"),
    entryPath: realpathSync(join(root, "dist", "index.js")),
  };
}

/** A scratch project with the named consumers installed under the project install root. */
function scratchInstall(names: readonly string[]): { cwd: string; roots: string[] } {
  const cwd = scratch("install");
  const roots: string[] = [];
  for (const name of names) {
    const dir = join(cwd, NATIVE_CONSUMER_INSTALL_ROOT, name);
    writeJson(join(dir, "package.json"), { name, type: "module" });
    roots.push(realpathSync(dir));
  }
  return { cwd, roots };
}

function recordingHooks(): { registerHooks: BridgePorts["registerHooks"]; calls: unknown[] } {
  const calls: unknown[] = [];
  return {
    calls,
    registerHooks: (options) => {
      calls.push(options);
      return { deregister() {} };
    },
  };
}

function portsFor(over: Partial<BridgePorts> = {}): BridgePorts {
  return {
    cwd: over.cwd ?? scratch("empty-cwd"),
    argv1: over.argv1,
    env: over.env ?? {},
    registerHooks: over.registerHooks,
    isBun: over.isBun ?? false,
    global: over.global ?? {},
  };
}

test("install: PERK_DISABLE_NATIVE_SDK_BRIDGE=1 disables and claims a disabled record read once per process", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const base = { cwd: install.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global };
  const first = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ ...base, env: { [BRIDGE_DISABLE_ENV]: " 1 " } }),
  );
  assert.deepEqual(first, {
    state: "disabled",
    hostEntry: null,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "",
  });
  assert.deepEqual(global[BRIDGE_REGISTRY_KEY], { schema: BRIDGE_SCHEMA, kind: "disabled" });
  // The env is NOT re-read: a later activation without it stays disabled.
  const second = installNativeSdkBridge(fakeNamespaces(), portsFor({ ...base, env: {} }));
  assert.equal(second.state, "disabled");
  assert.equal(hooks.calls.length, 0);
  // Any other value leaves the bridge on.
  for (const value of ["0", "true", "", "yes"]) {
    const status = installNativeSdkBridge(
      fakeNamespaces(),
      portsFor({ ...base, global: {}, env: { [BRIDGE_DISABLE_ENV]: value } }),
    );
    assert.equal(status.state, "installed", `value ${JSON.stringify(value)}`);
  }
});

test("install: unsupported capability claims nothing (no registerHooks; Bun)", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const global: Record<symbol, unknown> = {};
  const noHooks = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: host.argv1, registerHooks: undefined, global }),
  );
  assert.deepEqual(noHooks, {
    state: "unsupported:no-register-hooks",
    hostEntry: null,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "",
  });
  const hooks = recordingHooks();
  const bun = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: install.cwd,
      argv1: host.argv1,
      registerHooks: hooks.registerHooks,
      isBun: true,
      global,
    }),
  );
  assert.equal(bun.state, "unsupported:bun");
  assert.equal(bun.hostEntry, null);
  assert.equal(hooks.calls.length, 0);
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
});

test("install: an embedded host (argv[1] outside the Pi package) is unsupported and claims nothing", () => {
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  for (const argv1 of [import.meta.filename, undefined, join(scratch("nowhere"), "missing.js")]) {
    const status = installNativeSdkBridge(
      fakeNamespaces(),
      portsFor({ cwd: install.cwd, argv1, registerHooks: hooks.registerHooks, global }),
    );
    assert.equal(status.state, "unsupported:embedded-host", String(argv1));
    assert.equal(status.hostEntry, null);
  }
  assert.equal(hooks.calls.length, 0);
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
  assert.deepEqual(deriveHostEntry(import.meta.filename), { kind: "embedded-host" });
});

test("install: a host manifest with no resolvable entry is failed:host-entry (nothing claimed)", () => {
  const host = scratchHost({ ".": { require: "./dist/index.cjs" } });
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.equal(status.state, "failed:host-entry");
  assert.equal(status.hostEntry, null);
  assert.match(status.detail, /no resolvable "\." entry/);
  assert.equal(hooks.calls.length, 0);
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
});

test("install: the host entry follows the symlinked bin and the nested node-first exports", () => {
  const host = scratchHost({
    ".": { node: { import: "./dist/index.js" }, import: "./dist/other.js" },
  });
  const bin = join(scratch("bin"), "pi");
  symlinkSync(host.argv1, bin);
  const derived = deriveHostEntry(bin);
  assert.equal(derived.kind, "ok");
  if (derived.kind === "ok") assert.equal(derived.entryPath, host.entryPath);
});

test("install: fresh install claims then registers; the status carries the verified roots", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.deepEqual(status, {
    state: "installed",
    hostEntry: host.entryPath,
    roots: install.roots,
    specifiers: NATIVE_SDK_CENSUS.length,
    reused: false,
    detail: "",
  });
  assert.equal(hooks.calls.length, 1);
  const registered = hooks.calls[0] as { resolve?: unknown; load?: unknown };
  assert.equal(typeof registered.resolve, "function");
  assert.equal(typeof registered.load, "function");
  const record = global[BRIDGE_REGISTRY_KEY] as ActiveBridgeRegistry;
  assert.equal(record.kind, "active");
  assert.equal(record.hostEntryPath, host.entryPath);
  assert.deepEqual(
    [...record.roots.entries()],
    install.roots.map((root) => [root, "armed"]),
  );
  assert.deepEqual([...record.facadeSources.keys()], [...NATIVE_SDK_CENSUS]);
  assert.equal(
    describeBridge(status),
    `installed (roots=2, specifiers=${NATIVE_SDK_CENSUS.length})`,
  );
});

test("install: a partially installed project reports the unverified consumer in detail", () => {
  const host = scratchHost();
  const install = scratchInstall(["pi-subagents"]);
  // A directory whose manifest carries the wrong name is unverified too.
  writeJson(join(install.cwd, NATIVE_CONSUMER_INSTALL_ROOT, "pi-web-access", "package.json"), {
    name: "pi-web-access-fork",
  });
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: install.cwd,
      argv1: host.argv1,
      registerHooks: recordingHooks().registerHooks,
    }),
  );
  assert.equal(status.state, "installed");
  assert.deepEqual(status.roots, install.roots);
  assert.equal(status.detail, "unverified consumers: pi-web-access");
  assert.equal(
    describeBridge(status),
    "installed (roots=1, specifiers=7) — unverified consumers: pi-web-access",
  );
  assert.deepEqual(verifyConsumerRoots(install.cwd), {
    roots: install.roots,
    skipped: ["pi-web-access"],
  });
});

test("install: a registry of another schema (or an unrecognized value) is declined untouched", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const stale = { schema: 0, kind: "active", hostEntryPath: "/elsewhere", roots: new Map() };
  const staleCopy = { ...stale, roots: new Map() };
  const global: Record<symbol, unknown> = { [BRIDGE_REGISTRY_KEY]: stale };
  const declined = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.deepEqual(declined, {
    state: "declined:schema-mismatch",
    hostEntry: host.entryPath,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "existing registry schema 0",
  });
  assert.equal(global[BRIDGE_REGISTRY_KEY], stale);
  assert.deepEqual(stale, staleCopy);
  const foreign: Record<symbol, unknown> = { [BRIDGE_REGISTRY_KEY]: "garbage" };
  const unrecognized = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: install.cwd,
      argv1: host.argv1,
      registerHooks: hooks.registerHooks,
      global: foreign,
    }),
  );
  assert.equal(unrecognized.state, "declined:schema-mismatch");
  assert.equal(unrecognized.detail, "existing registry schema unrecognized");
  assert.equal(foreign[BRIDGE_REGISTRY_KEY], "garbage");
  assert.equal(hooks.calls.length, 0);
  assert.equal(describeBridge(declined), "declined:schema-mismatch — existing registry schema 0");
});

test("install: an active bridge for another host is declined; the earlier bridge stays as it was", () => {
  const hostA = scratchHost();
  const hostB = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const first = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: hostA.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.equal(first.state, "installed");
  const record = global[BRIDGE_REGISTRY_KEY] as ActiveBridgeRegistry;
  const rootsBefore = [...record.roots.entries()];
  const declined = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: install.cwd, argv1: hostB.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.deepEqual(declined, {
    state: "declined:host-mismatch",
    hostEntry: hostB.entryPath,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: `active bridge host: ${hostA.entryPath}`,
  });
  assert.equal(global[BRIDGE_REGISTRY_KEY], record);
  assert.deepEqual([...record.roots.entries()], rootsBefore);
  assert.equal(hooks.calls.length, 1);
});

test("install: reuse merges only NEW roots as armed — never removes, never downgrades", () => {
  const host = scratchHost();
  const partial = scratchInstall(["pi-subagents"]);
  const full = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const first = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: partial.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.equal(first.state, "installed");
  const record = global[BRIDGE_REGISTRY_KEY] as ActiveBridgeRegistry;
  const partialRoot = partial.roots[0] ?? "";
  record.roots.set(partialRoot, "bridged");
  const second = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({ cwd: full.cwd, argv1: host.argv1, registerHooks: hooks.registerHooks, global }),
  );
  assert.deepEqual(second, {
    state: "installed",
    hostEntry: host.entryPath,
    roots: [partialRoot, ...full.roots],
    specifiers: NATIVE_SDK_CENSUS.length,
    reused: true,
    detail: "",
  });
  assert.equal(record.roots.get(partialRoot), "bridged");
  for (const root of full.roots) assert.equal(record.roots.get(root), "armed");
  assert.equal(hooks.calls.length, 1, "a reuse registers no second hook pair");
  assert.equal(
    describeBridge(second),
    `installed (roots=3, specifiers=${NATIVE_SDK_CENSUS.length}, reused)`,
  );
  // A reuse from a project with no consumers still reports installed (the earlier roots), with detail.
  const empty = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: scratch("none"),
      argv1: host.argv1,
      registerHooks: hooks.registerHooks,
      global,
    }),
  );
  assert.equal(empty.state, "installed");
  assert.equal(empty.reused, true);
  assert.equal(empty.detail, "unverified consumers: pi-subagents, pi-web-access");
});

test("install: zero verified roots on a fresh install is skipped:no-consumers (no claim, no hook)", () => {
  const host = scratchHost();
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: scratch("none"),
      argv1: host.argv1,
      registerHooks: hooks.registerHooks,
      global,
    }),
  );
  assert.deepEqual(status, {
    state: "skipped:no-consumers",
    hostEntry: host.entryPath,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "",
  });
  assert.equal(hooks.calls.length, 0);
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
  assert.equal(describeBridge(status), "skipped:no-consumers");
});

test("install: a missing or empty captured namespace is failed:namespace-capture (no claim, no hook)", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const global: Record<symbol, unknown> = {};
  const ports = portsFor({
    cwd: install.cwd,
    argv1: host.argv1,
    registerHooks: hooks.registerHooks,
    global,
  });
  const missing = installNativeSdkBridge(fakeNamespaces(["typebox/compile"]), ports);
  assert.equal(missing.state, "failed:namespace-capture");
  assert.equal(missing.hostEntry, host.entryPath);
  assert.equal(missing.detail, "no captured host namespace for typebox/compile");
  const empty = fakeNamespaces();
  empty.set("@earendil-works/pi-tui", {});
  const hollow = installNativeSdkBridge(empty, ports);
  assert.equal(hollow.state, "failed:namespace-capture");
  assert.equal(hollow.detail, "no captured host namespace for @earendil-works/pi-tui");
  assert.equal(hooks.calls.length, 0);
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
});

test("install: a throwing registerHooks is failed:register-hooks and the claim is rolled back", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const global: Record<symbol, unknown> = {};
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: install.cwd,
      argv1: host.argv1,
      global,
      registerHooks: () => {
        throw new Error("hooks refused\nsecond line");
      },
    }),
  );
  assert.deepEqual(status, {
    state: "failed:register-hooks",
    hostEntry: host.entryPath,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "hooks refused",
  });
  assert.equal(BRIDGE_REGISTRY_KEY in global, false);
  assert.equal(describeBridge(status), "failed:register-hooks — hooks refused");
});

test("install: a frozen global is failed:registry-claim with zero registrations", () => {
  const host = scratchHost();
  const install = scratchInstall(NATIVE_SDK_CONSUMERS);
  const hooks = recordingHooks();
  const status = installNativeSdkBridge(
    fakeNamespaces(),
    portsFor({
      cwd: install.cwd,
      argv1: host.argv1,
      registerHooks: hooks.registerHooks,
      global: Object.freeze({}) as Record<symbol, unknown>,
    }),
  );
  assert.equal(status.state, "failed:registry-claim");
  assert.equal(status.hostEntry, host.entryPath);
  assert.ok(status.detail.length > 0);
  assert.equal(hooks.calls.length, 0);
});

test("describeBridge: the per-state renderings", () => {
  const base: BridgeStatus = {
    state: "disabled",
    hostEntry: null,
    roots: [],
    specifiers: 0,
    reused: false,
    detail: "",
  };
  assert.equal(describeBridge(base), "disabled");
  assert.equal(
    describeBridge({ ...base, state: "unsupported:embedded-host" }),
    "unsupported:embedded-host",
  );
  assert.equal(
    describeBridge({ ...base, state: "failed:facade-prep", detail: "boom" }),
    "failed:facade-prep — boom",
  );
  assert.equal(
    describeBridge({
      ...base,
      state: "installed",
      roots: ["/a"],
      specifiers: 7,
      reused: true,
      detail: "x",
    }),
    "installed (roots=1, specifiers=7, reused) — x",
  );
});

// ---------------------------------------------------------------------------
// Fixture processes — the end-to-end proofs (public Node APIs only)
// ---------------------------------------------------------------------------

const FIXTURES = join(import.meta.dirname, "..", "testing", "fixtures", "nativeSdkBridge");
const HOST_ROOT = join("host", "node_modules", "@earendil-works", "pi-coding-agent");
const INSTALL = "install";
const CONSUMERS = join(INSTALL, NATIVE_CONSUMER_INSTALL_ROOT);
const SUBAGENTS = join(CONSUMERS, "pi-subagents");
/** `[committed source → materialized destination]` — the committed tree carries no node_modules/dist. */
const LAYOUT: readonly [string, string][] = [
  ["host/package.json", join(HOST_ROOT, "package.json")],
  ["host/unbundled-entry.js", join(HOST_ROOT, "dist", "index.js")],
  ["host/cli.js", join(HOST_ROOT, "dist", "bundle", "cli.js")],
  ["consumer-subagents/package.json", join(SUBAGENTS, "package.json")],
  ["consumer-subagents/index.js", join(SUBAGENTS, "index.js")],
  ["consumer-subagents/src/extension", join(SUBAGENTS, "src", "extension")],
  ["consumer-subagents/src/nested/index.js", join(SUBAGENTS, "src", "nested", "index.js")],
  [
    "consumer-subagents/src/nested/nested-dep",
    join(SUBAGENTS, "src", "nested", "node_modules", "nested-dep"),
  ],
  ["consumer-web-access/package.json", join(CONSUMERS, "pi-web-access", "package.json")],
  ["consumer-web-access/entry.js", join(CONSUMERS, "pi-web-access", "dist", "index.js")],
  ["unrelated", join(CONSUMERS, "unrelated")],
  ["decoys/pi-coding-agent", join(CONSUMERS, "@earendil-works", "pi-coding-agent")],
  ["decoys/pi-tui", join(CONSUMERS, "@earendil-works", "pi-tui")],
  ["decoys/pi-ai", join(CONSUMERS, "@earendil-works", "pi-ai")],
  ["decoys/pi-agent-core", join(CONSUMERS, "@earendil-works", "pi-agent-core")],
  ["decoys/typebox", join(CONSUMERS, "typebox")],
];

interface BridgeFixture {
  cli: string;
  binSymlink: string;
  installCwd: string;
  partialCwd: string;
  hostEntry: string;
  consumerRoots: string[];
}

/** Copy the committed fixture sources into a temp tree shaped like a Pi install + project. */
function materializeBridgeFixture(): BridgeFixture {
  const tmp = scratch("fixture");
  for (const [source, destination] of LAYOUT) {
    const target = join(tmp, destination);
    mkdirSync(dirname(target), { recursive: true });
    cpSync(join(FIXTURES, source), target, { recursive: true });
  }
  const cli = join(tmp, HOST_ROOT, "dist", "bundle", "cli.js");
  mkdirSync(join(tmp, "host", "bin"), { recursive: true });
  const binSymlink = join(tmp, "host", "bin", "pi");
  symlinkSync(cli, binSymlink);
  // A second project whose install root holds ONLY pi-subagents (a symlink to the same package,
  // so its realpath root is the full project's).
  const partialCwd = join(tmp, "install-partial");
  mkdirSync(join(partialCwd, NATIVE_CONSUMER_INSTALL_ROOT), { recursive: true });
  symlinkSync(
    join(tmp, SUBAGENTS),
    join(partialCwd, NATIVE_CONSUMER_INSTALL_ROOT, "pi-subagents"),
    "dir",
  );
  return {
    cli,
    binSymlink,
    installCwd: join(tmp, INSTALL),
    partialCwd,
    hostEntry: realpathSync(join(tmp, HOST_ROOT, "dist", "index.js")),
    consumerRoots: NATIVE_SDK_CONSUMERS.map((name) => realpathSync(join(tmp, CONSUMERS, name))),
  };
}

let fixture: BridgeFixture | null = null;
function bridgeFixture(): BridgeFixture {
  fixture ??= materializeBridgeFixture();
  return fixture;
}

const BRIDGE_MODULE_URL = pathToFileURL(join(import.meta.dirname, "nativeSdkBridge.ts")).href;

/** Run one scenario in a fresh Node process (`node <cli-or-symlink> <scenario>`) and parse its JSON line. */
function runScenario(
  scenario: string,
  opts: { viaSymlink?: boolean; env?: Record<string, string> } = {},
): Record<string, unknown> {
  const f = bridgeFixture();
  const env: Record<string, string | undefined> = {
    ...process.env,
    PERK_BRIDGE_MODULE: BRIDGE_MODULE_URL,
  };
  delete env[BRIDGE_DISABLE_ENV];
  Object.assign(env, opts.env ?? {});
  const result = spawnSync(process.execPath, [opts.viaSymlink ? f.binSymlink : f.cli, scenario], {
    cwd: f.installCwd,
    env,
    encoding: "utf8",
  });
  assert.equal(
    result.status,
    0,
    `scenario ${scenario} failed:\n${result.stderr}\n${result.stdout}`,
  );
  const line = result.stdout.trim().split("\n").at(-1) ?? "";
  return JSON.parse(line) as Record<string, unknown>;
}

const HOST_VIEW = { origin: "host", markerIsHost: true, instanceOfHost: true };
const DECOY_VIEW = { origin: "decoy", markerIsHost: false, instanceOfHost: false };
const allHost = (keys: readonly string[]) => Object.fromEntries(keys.map((k) => [k, HOST_VIEW]));
const allDecoy = (keys: readonly string[]) => Object.fromEntries(keys.map((k) => [k, DECOY_VIEW]));
const WEB_STATICS = ["@earendil-works/pi-tui", "typebox"];

test("fixture identity: through the bin symlink, every census import from both consumers is the host's own", () => {
  const f = bridgeFixture();
  const out = runScenario("identity", { viaSymlink: true });
  assert.deepEqual(out.status, {
    state: "installed",
    hostEntry: f.hostEntry,
    roots: f.consumerRoots,
    specifiers: NATIVE_SDK_CENSUS.length,
    reused: false,
    detail: "",
  });
  assert.equal(out.hostEntry, f.hostEntry);
  const subagents = out.subagents as Record<string, unknown>;
  assert.deepEqual(subagents.statics, allHost(NATIVE_SDK_CENSUS));
  assert.deepEqual(subagents.lazy, {
    "typebox/compile": HOST_VIEW,
    "@earendil-works/pi-ai/compat": HOST_VIEW,
    relative: HOST_VIEW,
  });
  assert.equal(
    subagents.resolvedHost,
    f.hostEntry,
    "import.meta.resolve → the physical host entry",
  );
  assert.equal(
    subagents.exactEntry,
    "host",
    "the exact-entry import reaches the host, not the unbundled copy",
  );
  assert.equal(subagents.nestedOrigin, "decoy", "a nested dependency stays on ordinary resolution");
  assert.deepEqual(out.webAccess, {
    statics: allHost(WEB_STATICS),
    lazy: { compat: HOST_VIEW, host: HOST_VIEW },
  });
  assert.equal(out.unrelated, "decoy", "an unrelated package is never bridged");
  assert.deepEqual(out.rootStates, Object.fromEntries(f.consumerRoots.map((r) => [r, "bridged"])));
});

test("fixture additive-roots: a second activation adds roots to the live bridge; hooks outlive the statuses", () => {
  const f = bridgeFixture();
  const out = runScenario("additive-roots", { env: { PERK_BRIDGE_PARTIAL_CWD: f.partialCwd } });
  const first = out.first as BridgeStatus;
  const second = out.second as BridgeStatus;
  assert.equal(first.state, "installed");
  assert.equal(first.reused, false);
  assert.deepEqual(first.roots, [f.consumerRoots[0]]);
  assert.equal(first.detail, "unverified consumers: pi-web-access");
  assert.equal(second.state, "installed");
  assert.equal(second.reused, true);
  assert.deepEqual(second.roots, f.consumerRoots);
  assert.deepEqual(out.subagents, allHost(NATIVE_SDK_CENSUS));
  assert.deepEqual(out.webAccess, allHost(WEB_STATICS));
  assert.deepEqual(out.afterDrop, HOST_VIEW);
});

test("fixture preloaded-consumer: consumers evaluated before the bridge keep ordinary loading forever", () => {
  const f = bridgeFixture();
  const out = runScenario("preloaded-consumer");
  assert.equal((out.status as BridgeStatus).state, "installed");
  assert.deepEqual(out.before, {
    subagents: allDecoy(NATIVE_SDK_CENSUS),
    webAccess: allDecoy(WEB_STATICS),
  });
  assert.equal(out.sameEntry, true, "the re-import hit the cache (resolve fired, no load)");
  assert.deepEqual(out.subagentsAfter, { relative: DECOY_VIEW, compile: DECOY_VIEW });
  assert.deepEqual(out.webAccessAfter, { compat: DECOY_VIEW });
  assert.deepEqual(
    out.rootStates,
    Object.fromEntries(f.consumerRoots.map((r) => [r, "preloaded"])),
  );
});

test("fixture opt-out: PERK_DISABLE_NATIVE_SDK_BRIDGE=1 means no hook — ordinary loading everywhere", () => {
  const out = runScenario("opt-out", { env: { [BRIDGE_DISABLE_ENV]: "1" } });
  assert.equal((out.status as BridgeStatus).state, "disabled");
  assert.deepEqual(out.subagents, {
    statics: allDecoy(NATIVE_SDK_CENSUS),
    lazy: {
      "typebox/compile": DECOY_VIEW,
      "@earendil-works/pi-ai/compat": DECOY_VIEW,
      relative: DECOY_VIEW,
    },
  });
  assert.deepEqual(out.webAccess, { statics: allDecoy(WEB_STATICS), lazy: { compat: DECOY_VIEW } });
  assert.equal(out.registry, "disabled");
});

test("fixture failure-fallback: a capture failure installs nothing and leaves no registry", () => {
  const out = runScenario("failure-fallback");
  const status = out.status as BridgeStatus;
  assert.equal(status.state, "failed:namespace-capture");
  assert.equal(status.detail, "no captured host namespace for typebox/compile");
  assert.deepEqual((out.subagents as Record<string, unknown>).statics, allDecoy(NATIVE_SDK_CENSUS));
  assert.deepEqual((out.webAccess as Record<string, unknown>).statics, allDecoy(WEB_STATICS));
  assert.equal(out.hasRegistry, false);
});

// ---------------------------------------------------------------------------
// Census drift guard: the installed consumers' SDK import specifiers equal NATIVE_SDK_CENSUS
// ---------------------------------------------------------------------------

const CENSUS_ROOT_ENV = "PERK_NATIVE_CONSUMER_CENSUS_ROOT";
const SDK_SPECIFIER = /^(@earendil-works\/|@mariozechner\/|typebox|@sinclair\/typebox)/;

/** Every `.js/.mjs/.cjs` under `dir`, skipping nested `node_modules/`. */
function consumerSources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules") out.push(...consumerSources(path));
    } else if (/\.(js|mjs|cjs)$/.test(entry.name)) {
      out.push(path);
    }
  }
  return out.sort();
}

/** The scan location: the env-named node_modules (MUST hold both consumers), else the live install, else null. */
function censusScanRoot(): { root: string; source: string } | null {
  const fromEnv = process.env[CENSUS_ROOT_ENV];
  if (fromEnv !== undefined && fromEnv !== "") {
    for (const name of NATIVE_SDK_CONSUMERS) {
      assert.ok(
        existsSync(join(fromEnv, name, "package.json")),
        `${CENSUS_ROOT_ENV}=${fromEnv} does not hold ${name} — the audited consumer install is incomplete`,
      );
    }
    return { root: fromEnv, source: CENSUS_ROOT_ENV };
  }
  const live = join(import.meta.dirname, "..", "..", NATIVE_CONSUMER_INSTALL_ROOT);
  if (NATIVE_SDK_CONSUMERS.every((name) => existsSync(join(live, name, "package.json")))) {
    return { root: live, source: "live project install" };
  }
  return null;
}

test("census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS", (t) => {
  const scan = censusScanRoot();
  if (scan === null) {
    t.skip(
      `no consumer install to scan — set ${CENSUS_ROOT_ENV} to a node_modules holding both consumers`,
    );
    return;
  }
  const observed = new Set<string>();
  const versions: string[] = [];
  let scanned = 0;
  for (const name of NATIVE_SDK_CONSUMERS) {
    const root = join(scan.root, name);
    const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
      version?: string;
    };
    versions.push(`${name}@${manifest.version ?? "?"}`);
    for (const file of consumerSources(root)) {
      scanned += 1;
      for (const specifier of extractSpecifiers(readFileSync(file, "utf8"))) {
        if (SDK_SPECIFIER.test(specifier)) observed.add(specifier);
      }
    }
  }
  assert.ok(scanned > 0, "the census scan visited no consumer sources");
  const expected = [...NATIVE_SDK_CENSUS].sort();
  assert.deepEqual(
    [...observed].sort(),
    expected,
    `native consumer SDK census drift (${scan.source}: ${versions.join(", ")}) — an extra specifier is a ` +
      "silently reloaded SDK copy (extend NATIVE_SDK_CENSUS + bump BRIDGE_SCHEMA); a missing one is a stale entry",
  );
});
