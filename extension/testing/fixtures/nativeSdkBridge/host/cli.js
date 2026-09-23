// The fixture "Pi": the host package's bin (materialized at dist/bundle/cli.js, reached through a
// bin/pi symlink). It imports the REAL bridge module (`PERK_BRIDGE_MODULE`, a file: URL of
// nativeSdkBridge.ts — Node type stripping), captures fake host namespaces per census key, runs the
// scenario named by argv[2] against the consumers installed under the cwd's project install root,
// and prints ONE JSON line. Public Node APIs only: import(), import.meta.resolve, registerHooks, fs.
import { realpathSync } from "node:fs";
import * as nodeModule from "node:module";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const bridge = await import(process.env.PERK_BRIDGE_MODULE);
const {
  BRIDGE_REGISTRY_KEY,
  NATIVE_CONSUMER_INSTALL_ROOT,
  NATIVE_SDK_CENSUS,
  installNativeSdkBridge,
} = bridge;

class HostMarker {}

/** The host's namespaces: one object per census key (`default` exercises string export names). */
function hostNamespaces(omit = []) {
  const map = new Map();
  for (const specifier of NATIVE_SDK_CENSUS) {
    if (omit.includes(specifier)) continue;
    map.set(specifier, { origin: "host", Marker: HostMarker, default: { specifier } });
  }
  return map;
}

function ports(cwd = process.cwd()) {
  return {
    cwd,
    argv1: process.argv[1],
    env: process.env,
    registerHooks: nodeModule.registerHooks,
    isBun: false,
    global: globalThis,
  };
}

/** The physical host entry (dist/index.js beside this bundle) — what the bridge must derive. */
const hostEntry = realpathSync(fileURLToPath(new URL("../index.js", import.meta.url)));

const consumerUrl = (name, rel, cwd = process.cwd()) =>
  pathToFileURL(join(cwd, NATIVE_CONSUMER_INSTALL_ROOT, name, rel)).href;

/** What a consumer sees of one namespace: its origin + whether identity is the host's. */
function describe(ns) {
  return {
    origin: ns.origin,
    markerIsHost: ns.Marker === HostMarker,
    instanceOfHost: new ns.Marker() instanceof HostMarker,
  };
}

function describeAll(namespaces) {
  return Object.fromEntries(Object.entries(namespaces).map(([key, ns]) => [key, describe(ns)]));
}

async function importSubagents() {
  return (await import(consumerUrl("pi-subagents", "index.js"))).extension;
}

async function importWebAccess() {
  return import(consumerUrl("pi-web-access", "dist/index.js"));
}

async function probeSubagentsLazies(ext) {
  return {
    "typebox/compile": describe(await ext.lazyCompile()),
    "@earendil-works/pi-ai/compat": describe(await ext.lazyCompat()),
    relative: describe(await ext.lazyRelative()),
  };
}

function rootStates() {
  const registry = globalThis[BRIDGE_REGISTRY_KEY];
  if (registry === undefined) return null;
  if (registry.kind !== "active") return registry.kind;
  return Object.fromEntries(registry.roots);
}

const scenarios = {
  async identity() {
    const status = installNativeSdkBridge(hostNamespaces(), ports());
    const ext = await importSubagents();
    const web = await importWebAccess();
    const unrelated = await import(consumerUrl("unrelated", "index.js"));
    return {
      status,
      subagents: {
        statics: describeAll(ext.statics),
        lazy: await probeSubagentsLazies(ext),
        resolvedHost: fileURLToPath(ext.resolvedHost),
        exactEntry: (await ext.exactEntry(hostEntry)).origin,
        nestedOrigin: ext.nestedOrigin,
      },
      webAccess: {
        statics: describeAll(web.statics),
        lazy: { compat: describe(await web.lazyCompat()), host: describe(await web.lazyHost()) },
      },
      unrelated: unrelated.origin,
      rootStates: rootStates(),
    };
  },

  async "additive-roots"() {
    let first = installNativeSdkBridge(hostNamespaces(), ports(process.env.PERK_BRIDGE_PARTIAL_CWD));
    let second = installNativeSdkBridge(hostNamespaces(), ports());
    const summary = { first: { ...first }, second: { ...second } };
    const ext = await importSubagents();
    const web = await importWebAccess();
    const before = {
      subagents: describeAll(ext.statics),
      webAccess: describeAll(web.statics),
    };
    // Drop every reference to both statuses: the hooks are process-owned, never status-owned.
    first = null;
    second = null;
    const afterDrop = describe(await ext.lazyLate());
    return { ...summary, ...before, afterDrop, rootStates: rootStates() };
  },

  async "preloaded-consumer"() {
    // Both consumers are fully evaluated BEFORE the bridge exists.
    const ext = await importSubagents();
    const web = await importWebAccess();
    const before = { subagents: describeAll(ext.statics), webAccess: describeAll(web.statics) };
    const status = installNativeSdkBridge(hostNamespaces(), ports());
    // (a) the cached entry is re-resolved from outside (resolve fires, no load), then the
    // consumer's own lazy paths run from inside the root.
    const again = await importSubagents();
    const relative = describe(await again.lazyRelative());
    const compile = describe(await again.lazyCompile());
    // (b) the other consumer's lazy census import runs directly.
    const webCompat = describe(await web.lazyCompat());
    return {
      status,
      before,
      sameEntry: again === ext,
      subagentsAfter: { relative, compile },
      webAccessAfter: { compat: webCompat },
      rootStates: rootStates(),
    };
  },

  async "opt-out"() {
    const status = installNativeSdkBridge(hostNamespaces(), ports());
    const ext = await importSubagents();
    const web = await importWebAccess();
    return {
      status,
      subagents: { statics: describeAll(ext.statics), lazy: await probeSubagentsLazies(ext) },
      webAccess: { statics: describeAll(web.statics), lazy: { compat: describe(await web.lazyCompat()) } },
      registry: rootStates(),
    };
  },

  async "failure-fallback"() {
    const status = installNativeSdkBridge(hostNamespaces(["typebox/compile"]), ports());
    const ext = await importSubagents();
    const web = await importWebAccess();
    return {
      status,
      subagents: { statics: describeAll(ext.statics), lazy: await probeSubagentsLazies(ext) },
      webAccess: { statics: describeAll(web.statics), lazy: { compat: describe(await web.lazyCompat()) } },
      hasRegistry: BRIDGE_REGISTRY_KEY in globalThis,
    };
  },
};

const scenario = scenarios[process.argv[2]];
if (scenario === undefined) {
  process.stderr.write(`unknown scenario: ${process.argv[2]}\n`);
  process.exit(2);
}
const result = await scenario();
process.stdout.write(`${JSON.stringify({ hostEntry, ...result })}\n`);
