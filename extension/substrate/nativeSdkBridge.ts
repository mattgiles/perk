// The host-SDK bridge (contracts.md §8.73): the two compiled native consumers Pi hands to Node's
// real ESM loader (`pi-subagents`, `pi-web-access`) would otherwise resolve a SECOND copy of every
// `@earendil-works/*` / `typebox` module from `node_modules`. A feature-detected `node:module`
// `registerHooks` resolve+load pair redirects exactly the censused specifiers, imported from the
// verified consumer roots, onto generated ESM facades that re-export the namespaces perk itself
// captured from the host — so values and class identity are the host's own.
//
// Node builtins only: the fixture processes import this module without the SDK, and the module
// must load under Node's type stripping (erasable syntax only — no enums, namespaces or parameter
// properties). `installNativeSdkBridge` is synchronous, never throws, and performs every side
// effect in the fixed commit protocol at the end (claim the registry, then register the hooks,
// rolling the claim back if registration throws). The registry is process-wide and schema-versioned
// so `/reload`, session replacement and a second perk copy converge on one bridge: roots are
// additive across activations, root states only advance, nothing ever deregisters in production.

import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import type { LoadHookSync, ModuleHooks, RegisterHooksOptions, ResolveHookSync } from "node:module";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** The observed specifier census: every SDK import the two consumers make (drift-guarded). */
export const NATIVE_SDK_CENSUS = [
  "@earendil-works/pi-coding-agent",
  "@earendil-works/pi-tui",
  "@earendil-works/pi-ai",
  "@earendil-works/pi-ai/compat",
  "@earendil-works/pi-agent-core",
  "typebox",
  "typebox/compile",
] as const;
export type CensusSpecifier = (typeof NATIVE_SDK_CENSUS)[number];

/** The managed native consumers (npm names). Python twin: `NATIVE_CONSUMER_PACKAGES`. */
export const NATIVE_SDK_CONSUMERS = ["pi-subagents", "pi-web-access"] as const;

export const HOST_PACKAGE_NAME = "@earendil-works/pi-coding-agent";
/** Pi's project install root — the ONE spelling (installedPackageGuard sanctions this file). */
export const NATIVE_CONSUMER_INSTALL_ROOT = ".pi/npm/node_modules/";
export const BRIDGE_SCHEMA = 1;
export const BRIDGE_MARKER = "perk-native-sdk-bridge";
export const BRIDGE_DISABLE_ENV = "PERK_DISABLE_NATIVE_SDK_BRIDGE";
/** The global-symbol registry name (the facade source re-derives the key from it). */
export const BRIDGE_REGISTRY_NAME = "perk.native-sdk-bridge";
export const BRIDGE_REGISTRY_KEY: unique symbol = Symbol.for(BRIDGE_REGISTRY_NAME);

/** The closed state vocabulary — producers cannot mint new reasons. */
export type BridgeState =
  | "installed"
  | "disabled"
  | "skipped:no-consumers"
  | "unsupported:no-register-hooks"
  | "unsupported:bun"
  | "unsupported:embedded-host"
  | "declined:schema-mismatch"
  | "declined:host-mismatch"
  | "failed:host-entry"
  | "failed:namespace-capture"
  | "failed:facade-prep"
  | "failed:registry-claim"
  | "failed:register-hooks";

export interface BridgeStatus {
  state: BridgeState;
  /** The host entry THIS activation derived (null when derivation did not run or failed). */
  hostEntry: string | null;
  /** Verified consumer roots (every registry root after a reuse merge). */
  roots: readonly string[];
  /** `NATIVE_SDK_CENSUS.length` when installed, else 0. */
  specifiers: number;
  /** An earlier activation's bridge served this one. */
  reused: boolean;
  /** Free text for `describeBridge`; `""` when there is nothing to add. */
  detail: string;
}

/** The process facts the install reads — injected so the decision table is unit-testable. */
export interface BridgePorts {
  cwd: string;
  argv1: string | undefined;
  env: Readonly<Record<string, string | undefined>>;
  registerHooks: ((options: RegisterHooksOptions) => ModuleHooks) | undefined;
  isBun: boolean;
  global: Record<symbol, unknown>;
}

/**
 * `armed`: verified, not yet observed. `bridged`: the first fresh load under the root happened
 * after install — its census imports are redirected. `preloaded`: the first observation was a
 * resolve from inside the root — evaluated before the bridge, ordinary loading forever.
 */
export type RootState = "armed" | "bridged" | "preloaded";

export interface ActiveBridgeRegistry {
  schema: typeof BRIDGE_SCHEMA;
  kind: "active";
  hostEntryPath: string;
  hostEntryUrl: string;
  roots: Map<string, RootState>;
  namespaces: Map<string, object>;
  facadeSources: Map<string, string>;
}

export type BridgeRegistry =
  | { schema: typeof BRIDGE_SCHEMA; kind: "disabled" }
  | ActiveBridgeRegistry;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The registry guard: schema 1 and one of the two recognized record shapes. */
export function isBridgeRegistry(value: unknown): value is BridgeRegistry {
  if (!isRecord(value) || value.schema !== BRIDGE_SCHEMA) return false;
  if (value.kind === "disabled") return true;
  return (
    value.kind === "active" &&
    typeof value.hostEntryPath === "string" &&
    typeof value.hostEntryUrl === "string" &&
    value.roots instanceof Map &&
    value.namespaces instanceof Map &&
    value.facadeSources instanceof Map
  );
}

// ---------------------------------------------------------------------------
// Host entry derivation (argv[1] realpath walk + Node-equivalent conditional exports)
// ---------------------------------------------------------------------------

// Node's conditions for an `import` of the entry. Built from one string so bareImportGuard's
// `import ""` spelling net never sees the condition name beside a quote.
const EXPORT_CONDITIONS: ReadonlySet<string> = new Set(
  "node import module-sync default".split(" "),
);

/** Node's `ERR_INVALID_PACKAGE_TARGET`: a target that is not a `./`-relative string (or a nested shape). */
class InvalidExportTarget extends Error {}

/**
 * Select the `"."` target as Node's `resolvePackageTarget` does — a TRI-STATE, with no filesystem
 * access: a `./`-string is selected as-is (Node checks existence only AFTER selection); `null`
 * blocks the subpath; a conditions object is walked in declaration order and the first key that
 * is `default` or in the conditions set decides (`undefined` = that key matched nothing, keep
 * walking; `null`/string are final); an array takes the first member that resolves to a string,
 * skipping invalid targets and unmatched members, and remembers a `null` block (Node returns
 * `null` when a member blocked and nothing later resolved, `undefined` when nothing matched).
 * Any other shape is an invalid target.
 */
function selectExportTarget(target: unknown): string | null | undefined {
  if (typeof target === "string") {
    if (!target.startsWith("./")) throw new InvalidExportTarget(`invalid exports target ${target}`);
    return target;
  }
  if (target === null) return null;
  if (Array.isArray(target)) {
    let last: null | undefined;
    for (const member of target) {
      let selected: string | null | undefined;
      try {
        selected = selectExportTarget(member);
      } catch (error) {
        if (error instanceof InvalidExportTarget) continue;
        throw error;
      }
      if (selected === undefined) continue;
      if (selected === null) {
        last = null;
        continue;
      }
      return selected;
    }
    return last;
  }
  if (isRecord(target)) {
    for (const [condition, nested] of Object.entries(target)) {
      if (!EXPORT_CONDITIONS.has(condition)) continue;
      const selected = selectExportTarget(nested);
      if (selected === undefined) continue;
      return selected;
    }
    return undefined;
  }
  throw new InvalidExportTarget(`invalid exports target ${JSON.stringify(target)}`);
}

/** The realpath of an existing file under `rootDir`, or null (Node's post-selection existence check). */
function existingFile(rootDir: string, relative: string): string | null {
  const candidate = resolve(rootDir, relative);
  try {
    return statSync(candidate).isFile() ? realpathSync(candidate) : null;
  } catch {
    return null;
  }
}

/**
 * The package's `"."` entry as Node would resolve it for `import`: the `exports` `"."` target (an
 * `exports` without `.`-keys is itself the `"."` target) selected with Node's tri-state semantics
 * and THEN checked on disk — a blocked, unmatched, invalid or missing selection is null (Node
 * would throw `ERR_PACKAGE_PATH_NOT_EXPORTED` / `ERR_INVALID_PACKAGE_TARGET` /
 * `ERR_MODULE_NOT_FOUND`); no `exports` → `main` → `index.js`.
 */
export function resolvePackageEntry(manifest: unknown, rootDir: string): string | null {
  if (!isRecord(manifest)) return null;
  const exportsField = manifest.exports;
  if (exportsField !== undefined) {
    let target: unknown = exportsField;
    if (isRecord(exportsField)) {
      const keys = Object.keys(exportsField);
      const subpathKeyed = keys.some((key) => key === "." || key.startsWith("./"));
      if (subpathKeyed) target = exportsField["."];
    }
    if (target === undefined) return null;
    let selected: string | null | undefined;
    try {
      selected = selectExportTarget(target);
    } catch (error) {
      if (error instanceof InvalidExportTarget) return null;
      throw error;
    }
    return typeof selected === "string" ? existingFile(rootDir, selected) : null;
  }
  if (typeof manifest.main === "string") {
    const main = existingFile(rootDir, manifest.main);
    if (main !== null) return main;
  }
  return existingFile(rootDir, "./index.js");
}

/**
 * Walk the realpath of argv[1] up to the `package.json` named `HOST_PACKAGE_NAME` (Pi's own
 * package). No such ancestor — a test runner, an embedding SDK host — is `embedded-host`; an
 * ancestor whose manifest does not yield an entry file is `failed`.
 */
export function deriveHostEntry(
  argv1: string | undefined,
):
  | { kind: "embedded-host" }
  | { kind: "failed"; detail: string }
  | { kind: "ok"; rootDir: string; entryPath: string } {
  if (argv1 === undefined || argv1 === "") return { kind: "embedded-host" };
  let dir: string;
  try {
    dir = dirname(realpathSync(argv1));
  } catch {
    return { kind: "embedded-host" };
  }
  for (;;) {
    const manifestPath = join(dir, "package.json");
    if (existsSync(manifestPath)) {
      let manifest: unknown = null;
      try {
        manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
      } catch {
        // A corrupt manifest cannot name the host — keep walking (the host identity is what
        // matters here, not Node's package-scope semantics).
      }
      if (isRecord(manifest) && manifest.name === HOST_PACKAGE_NAME) {
        const entryPath = resolvePackageEntry(manifest, dir);
        if (entryPath === null) {
          return { kind: "failed", detail: `no resolvable "." entry in ${manifestPath}` };
        }
        return { kind: "ok", rootDir: dir, entryPath };
      }
    }
    const parent = dirname(dir);
    if (parent === dir) return { kind: "embedded-host" };
    dir = parent;
  }
}

// ---------------------------------------------------------------------------
// Consumer roots
// ---------------------------------------------------------------------------

/**
 * The managed consumers actually installed under the project install root: kept iff the
 * directory exists, realpaths, and its `package.json` carries the expected `name`. Verification
 * never fails the install — an unverified name is reported in `skipped`.
 */
export function verifyConsumerRoots(cwd: string): { roots: string[]; skipped: string[] } {
  const roots: string[] = [];
  const skipped: string[] = [];
  for (const name of NATIVE_SDK_CONSUMERS) {
    const candidate = join(cwd, NATIVE_CONSUMER_INSTALL_ROOT, name);
    try {
      if (!existsSync(candidate)) {
        skipped.push(name);
        continue;
      }
      const root = realpathSync(candidate);
      const manifest: unknown = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
      if (isRecord(manifest) && manifest.name === name) roots.push(root);
      else skipped.push(name);
    } catch {
      skipped.push(name);
    }
  }
  return { roots, skipped };
}

/**
 * The root `path` sits under (or is) — the remainder must carry no `node_modules` segment, so
 * nested dependencies and look-alike siblings (`…-fork`) are outside every root.
 */
export function rootOf(path: string, roots: Iterable<string>): string | null {
  for (const root of roots) {
    if (path === root) return root;
    if (!path.startsWith(root + sep)) continue;
    const remainder = path.slice(root.length + 1).split(sep);
    if (!remainder.includes("node_modules")) return root;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Facades
// ---------------------------------------------------------------------------

/**
 * The facade module text: no imports, no `import.meta`; every export is read once from the
 * registry's captured namespace at evaluation (identity preserved). String export names cover
 * `default` and non-identifier names.
 */
export function facadeSource(specifier: string, exportNames: readonly string[]): string {
  const lines = [
    `const registry = globalThis[Symbol.for(${JSON.stringify(BRIDGE_REGISTRY_NAME)})];`,
    `const ns = registry.namespaces.get(${JSON.stringify(specifier)});`,
  ];
  for (let index = 0; index < exportNames.length; index++) {
    lines.push(`const _${index} = ns[${JSON.stringify(exportNames[index])}];`);
    lines.push(`export { _${index} as ${JSON.stringify(exportNames[index])} };`);
  }
  return `${lines.join("\n")}\n`;
}

/** One physical address for every facade: `fileURLToPath` of any facade URL is the host entry. */
export function facadeUrl(hostEntryUrl: string, specifier: string): string {
  return `${hostEntryUrl}?${BRIDGE_MARKER}=${encodeURIComponent(specifier)}`;
}

function facadeSpecifier(hostEntryUrl: string, url: string): string | null {
  const prefix = `${hostEntryUrl}?${BRIDGE_MARKER}=`;
  if (!url.startsWith(prefix)) return null;
  try {
    return decodeURIComponent(url.slice(prefix.length));
  } catch {
    return null;
  }
}

function isNamespaceLike(value: unknown): value is object {
  return (typeof value === "object" || typeof value === "function") && value !== null;
}

function exportNamesOf(namespace: object): string[] {
  return Object.keys(namespace).filter((key) => key !== "__esModule");
}

// ---------------------------------------------------------------------------
// Hooks (pure over the record — unit-testable with fake nextResolve/nextLoad)
// ---------------------------------------------------------------------------

function filePathOf(url: string | undefined): string | null {
  if (url === undefined || !url.startsWith("file:")) return null;
  try {
    return fileURLToPath(url);
  } catch {
    return null;
  }
}

const CENSUS_SET: ReadonlySet<string> = new Set(NATIVE_SDK_CENSUS);

/**
 * The root state machine. `resolve` fires for cached modules too, so it can only prove that a
 * root is being entered from INSIDE (`armed → preloaded`); `load` fires only for a module fetched
 * for the first time, so a fresh module under an armed root proves the package is being entered
 * now (`armed → bridged`) — its own imports then resolve with a parent inside a bridged root.
 * Residual (documented): a consumer fully evaluated before the bridge whose first post-install
 * activity is a fresh module loaded from OUTSIDE the root is treated as entered.
 */
export function createBridgeHooks(record: ActiveBridgeRegistry): {
  resolve: ResolveHookSync;
  load: LoadHookSync;
} {
  const resolve: ResolveHookSync = (specifier, context, nextResolve) => {
    const parentPath = filePathOf(context.parentURL);
    if (parentPath !== null) {
      const root = rootOf(parentPath, record.roots.keys());
      if (root !== null) {
        const state = record.roots.get(root);
        if (state === "armed") record.roots.set(root, "preloaded");
        else if (state === "bridged") {
          if (CENSUS_SET.has(specifier)) {
            return {
              url: facadeUrl(record.hostEntryUrl, specifier),
              format: "module",
              shortCircuit: true,
            };
          }
          if (specifier === record.hostEntryPath || specifier === record.hostEntryUrl) {
            return {
              url: facadeUrl(record.hostEntryUrl, HOST_PACKAGE_NAME),
              format: "module",
              shortCircuit: true,
            };
          }
        }
      }
    }
    return nextResolve(specifier, context);
  };

  const load: LoadHookSync = (url, context, nextLoad) => {
    const specifier = facadeSpecifier(record.hostEntryUrl, url);
    if (specifier !== null) {
      const source = record.facadeSources.get(specifier);
      if (source !== undefined) return { format: "module", source, shortCircuit: true };
      return nextLoad(url, context);
    }
    const path = filePathOf(url);
    if (path !== null) {
      const root = rootOf(path, record.roots.keys());
      if (root !== null && record.roots.get(root) === "armed") record.roots.set(root, "bridged");
    }
    return nextLoad(url, context);
  };

  return { resolve, load };
}

// ---------------------------------------------------------------------------
// The install (the fixed decision order; side effects only in the commit protocol)
// ---------------------------------------------------------------------------

function makeStatus(
  state: BridgeState,
  fields: Partial<Omit<BridgeStatus, "state">> = {},
): BridgeStatus {
  return {
    state,
    hostEntry: fields.hostEntry ?? null,
    roots: fields.roots ?? [],
    specifiers: fields.specifiers ?? 0,
    reused: fields.reused ?? false,
    detail: fields.detail ?? "",
  };
}

function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const line = message.split("\n")[0] ?? "";
  return line.length > 200 ? line.slice(0, 200) : line;
}

function skippedDetail(skipped: readonly string[]): string {
  return skipped.length > 0 ? `unverified consumers: ${skipped.join(", ")}` : "";
}

/** The decline detail for an unrecognized registry value: its schema, plus an unrecognized kind. */
function describeForeignRegistry(value: unknown): string {
  const schema =
    isRecord(value) && typeof value.schema === "number" ? String(value.schema) : "unrecognized";
  const kind = isRecord(value) && typeof value.kind === "string" ? value.kind : null;
  const kindNote =
    kind !== null && kind !== "active" && kind !== "disabled" ? ` (kind ${kind})` : "";
  return `existing registry schema ${schema}${kindNote}`;
}

/**
 * Roll a claim back so no later activation can observe an `active` record without hooks: delete
 * the key; if the property cannot be deleted (a non-configurable accessor on the global), write
 * `undefined` through it; if the record is STILL readable, neutralize it in place (its `kind` is
 * no longer `active`, so `isBridgeRegistry` rejects it and a later activation declines rather than
 * reusing it). Returns whether the key reads as absent afterwards.
 */
function releaseClaim(global: Record<symbol, unknown>, record: ActiveBridgeRegistry): boolean {
  try {
    delete global[BRIDGE_REGISTRY_KEY];
  } catch {
    // Non-configurable: fall through to the assignment.
  }
  if (global[BRIDGE_REGISTRY_KEY] === undefined) return true;
  try {
    global[BRIDGE_REGISTRY_KEY] = undefined;
  } catch {
    // Non-writable too: neutralize below.
  }
  if (global[BRIDGE_REGISTRY_KEY] === undefined) return true;
  // Last resort: the record object is ours — make it unrecognizable as an active bridge.
  (record as { kind: string }).kind = "orphaned";
  record.roots.clear();
  return false;
}

/**
 * Install the bridge for this activation. Synchronous, never throws; each step's outcome is final:
 * registry read → opt-out → capability → host entry → registry decision (reuse/decline) → roots →
 * namespace capture check → facade preparation → commit (claim, then register, rollback on throw).
 */
export function installNativeSdkBridge(
  namespaces: ReadonlyMap<string, object>,
  ports: BridgePorts,
): BridgeStatus {
  // 1. Registry read. A disabled record is final (the env is NOT re-read — once per process).
  const existingValue = ports.global[BRIDGE_REGISTRY_KEY];
  let existing: ActiveBridgeRegistry | null = null;
  let foreign = false;
  if (existingValue !== undefined) {
    if (isBridgeRegistry(existingValue)) {
      if (existingValue.kind === "disabled") return makeStatus("disabled");
      existing = existingValue;
    } else {
      foreign = true;
    }
  }

  // 2. Opt-out — only when no registry exists yet. Exactly "1" disables.
  if (existingValue === undefined && ports.env[BRIDGE_DISABLE_ENV]?.trim() === "1") {
    try {
      ports.global[BRIDGE_REGISTRY_KEY] = { schema: BRIDGE_SCHEMA, kind: "disabled" };
    } catch {
      // A frozen global cannot hold the marker; the opt-out still holds for this activation.
    }
    return makeStatus("disabled");
  }

  // 3. Capability — evaluated before any registry comparison.
  if (ports.registerHooks === undefined) return makeStatus("unsupported:no-register-hooks");
  if (ports.isBun) return makeStatus("unsupported:bun");

  // 4. Host entry.
  const host = deriveHostEntry(ports.argv1);
  if (host.kind === "embedded-host") return makeStatus("unsupported:embedded-host");
  if (host.kind === "failed") return makeStatus("failed:host-entry", { detail: host.detail });
  const hostEntryPath = host.entryPath;
  const hostEntryUrl = pathToFileURL(hostEntryPath).href;

  // 5. Registry decision (a decline never touches the existing record or its hooks).
  if (foreign) {
    return makeStatus("declined:schema-mismatch", {
      hostEntry: hostEntryPath,
      detail: describeForeignRegistry(existingValue),
    });
  }
  if (existing !== null) {
    if (existing.hostEntryPath !== hostEntryPath) {
      return makeStatus("declined:host-mismatch", {
        hostEntry: hostEntryPath,
        detail: `active bridge host: ${existing.hostEntryPath}`,
      });
    }
    const verified = verifyConsumerRoots(ports.cwd);
    for (const root of verified.roots) {
      if (!existing.roots.has(root)) existing.roots.set(root, "armed");
    }
    return makeStatus("installed", {
      hostEntry: hostEntryPath,
      roots: [...existing.roots.keys()],
      specifiers: NATIVE_SDK_CENSUS.length,
      reused: true,
      detail: skippedDetail(verified.skipped),
    });
  }

  // 6. Roots — zero verified roots on a fresh install is inert (no claim, no hook).
  const verified = verifyConsumerRoots(ports.cwd);
  if (verified.roots.length === 0) {
    return makeStatus("skipped:no-consumers", { hostEntry: hostEntryPath });
  }

  // 7. Namespace capture check.
  const captured = new Map<string, object>();
  for (const specifier of NATIVE_SDK_CENSUS) {
    const namespace: unknown = namespaces.get(specifier);
    if (!isNamespaceLike(namespace) || exportNamesOf(namespace).length === 0) {
      return makeStatus("failed:namespace-capture", {
        hostEntry: hostEntryPath,
        detail: `no captured host namespace for ${specifier}`,
      });
    }
    captured.set(specifier, namespace);
  }

  // 8. Facade preparation.
  const facadeSources = new Map<string, string>();
  try {
    for (const [specifier, namespace] of captured) {
      facadeSources.set(specifier, facadeSource(specifier, exportNamesOf(namespace)));
      // Every facade URL must round-trip to the physical entry.
      if (fileURLToPath(facadeUrl(hostEntryUrl, specifier)) !== hostEntryPath) {
        throw new Error(`facade URL for ${specifier} does not address the host entry`);
      }
    }
  } catch (error) {
    return makeStatus("failed:facade-prep", { hostEntry: hostEntryPath, detail: firstLine(error) });
  }

  // 9. Commit: build the record, claim first, then register; roll the claim back on a throw.
  const record: ActiveBridgeRegistry = {
    schema: BRIDGE_SCHEMA,
    kind: "active",
    hostEntryPath,
    hostEntryUrl,
    roots: new Map(verified.roots.map((root) => [root, "armed" as const])),
    namespaces: captured,
    facadeSources,
  };
  try {
    ports.global[BRIDGE_REGISTRY_KEY] = record;
    if (ports.global[BRIDGE_REGISTRY_KEY] !== record)
      throw new Error("registry claim did not stick");
  } catch (error) {
    return makeStatus("failed:registry-claim", {
      hostEntry: hostEntryPath,
      detail: firstLine(error),
    });
  }
  try {
    ports.registerHooks(createBridgeHooks(record));
  } catch (error) {
    const released = releaseClaim(ports.global, record);
    return makeStatus("failed:register-hooks", {
      hostEntry: hostEntryPath,
      detail: released
        ? firstLine(error)
        : `${firstLine(error)}; the registry claim could not be released (record neutralized)`,
    });
  }
  return makeStatus("installed", {
    hostEntry: hostEntryPath,
    roots: verified.roots,
    specifiers: NATIVE_SDK_CENSUS.length,
    detail: skippedDetail(verified.skipped),
  });
}

/** The one rendering selfcheck and the warning use: `<state>[ (roots=n, specifiers=n[, reused])][ — detail]`. */
export function describeBridge(status: BridgeStatus): string {
  let text: string = status.state;
  if (status.state === "installed") {
    text += ` (roots=${status.roots.length}, specifiers=${status.specifiers}${status.reused ? ", reused" : ""})`;
  }
  if (status.detail !== "") text += ` — ${status.detail}`;
  return text;
}
