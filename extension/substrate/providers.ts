// The TS plane's reader for the shared provider-selection supported set (`shared/providers.yaml`).
//
// Twin of perk/substrate/providers.py: both planes parse the SAME bundled file (no codegen). This is the
// THIRD parsed cross-plane contract (after registry.yaml and bindings.yaml). It is the SUPPORTED
// SET — the catalog of plan/todo/askuser/footer/web providers perk knows how to wire — distinct from
// the per-repo SELECTION (the flat `[providers]` table in .perk/config.toml).
//
// The Python CLI is the authoritative validator (perk/substrate/providers.py); this side does a thin
// structural parse only — no deep content validation here. `resolveProviders` is CONSUMED by
// `planMode` (plan-seam registration-time vacating when a foreign plan provider is selected); the
// todo-seam runtime deferral is likewise live.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "./miniYaml.ts";
import { sharedDir } from "./resources.ts";

export interface Provider {
  id: string;
  seam: string;
  package: string | null;
  adapter: string | null;
  default: boolean;
  packageFilter?: Record<string, unknown>;
}

export const PROVIDER_SEAMS = ["plan", "todo", "askuser", "footer", "web"] as const;

/** The bundled reference provider ids (the behavior-preserving no-config defaults per seam). */
export const PERK_PLAN_PROVIDER_ID = "perk-plan";
export const PERK_CHECKPOINTS_PROVIDER_ID = "perk-checkpoints";
export const PERK_ASK_USER_PROVIDER_ID = "perk-ask-user";
export const PERK_FOOTER_PROVIDER_ID = "perk-footer";

/** The foreign `@tombell/pi-plan` plan-provider id. */
export const TOMBELL_PLAN_PROVIDER_ID = "tombell-plan";

/** The foreign `@plannotator/pi-extension` plan-provider id (augment-posture adapter selection check). */
export const PLANNOTATOR_PLAN_PROVIDER_ID = "plannotator-plan";

/** The foreign `@juicesharp/rpiv-todo` todo-provider id. */
export const JUICESHARP_TODO_PROVIDER_ID = "juicesharp-todo";

/** The foreign `@juicesharp/rpiv-ask-user-question` askuser-provider id (vacate-only interface seam). */
export const JUICESHARP_ASK_USER_PROVIDER_ID = "juicesharp-ask-user";

/** The foreign `pi-powerline-footer` footer-provider id (vacate-only interface seam). */
export const POWERLINE_FOOTER_PROVIDER_ID = "powerline-footer";

/** The foreign `pi-bar` footer-provider id (vacate-only interface seam). */
export const PI_BAR_FOOTER_PROVIDER_ID = "pi-bar-footer";

/** The foreign `@tombell/pi-status` footer-provider id (vacate-only; no extension-status rendering). */
export const PI_STATUS_FOOTER_PROVIDER_ID = "pi-status-footer";

/** The "install nothing / pi stock footer" footer-provider id (`package: null`, vacate-only). */
export const PI_DEFAULT_FOOTER_PROVIDER_ID = "pi-default";

/** The web seam DEFAULT id — the FOREIGN reference provider (`pi-web-access`; perk owns no native web impl). */
export const PI_WEB_ACCESS_PROVIDER_ID = "pi-web-access";

/** The foreign `@ollama/pi-web-search` web-provider id (vacate-only interface seam). */
export const OLLAMA_WEB_PROVIDER_ID = "ollama-web-search";

/** The foreign `@juicesharp/rpiv-web-tools` web-provider id (vacate-only interface seam). */
export const JUICESHARP_WEB_PROVIDER_ID = "juicesharp-web-tools";

/** Parse the bundled `providers.yaml`. Throws on a missing file or unexpected shape. */
export function loadProviders(): Provider[] {
  const path = join(sharedDir(), "providers.yaml");
  const data = parse(readFileSync(path, "utf8")) as unknown;

  if (typeof data !== "object" || data === null) {
    throw new Error(`perk: ${path} is not a mapping`);
  }
  const record = data as Record<string, unknown>;
  const providers = record.providers;
  if (!Array.isArray(providers)) {
    throw new Error(`perk: ${path} has no providers`);
  }

  return providers.map((raw) => {
    const entry = raw as Record<string, unknown>;
    const packageFilter = entry.package_filter;
    const provider: Provider = {
      id: typeof entry.id === "string" ? entry.id : "",
      seam: typeof entry.seam === "string" ? entry.seam : "",
      package: typeof entry.package === "string" ? entry.package : null,
      adapter: typeof entry.adapter === "string" ? entry.adapter : null,
      default: entry.default === true,
    };
    if (typeof packageFilter === "object" && packageFilter !== null) {
      provider.packageFilter = packageFilter as Record<string, unknown>;
    }
    return provider;
  });
}

// ------------------------------------------------------------------------ resolve

/**
 * The effective provider per seam after resolving a repo selection against the supported set.
 * `issues` collects every loud-but-non-fatal finding (an unknown id or a wrong-seam provider) as a
 * plain string — the TS plane has no `Issue`/`Severity` (those live in `perk/substrate/registry.py`); the
 * Python plane is the authoritative validator. Twin of `perk.substrate.providers.ResolvedProviders`.
 */
export interface ResolvedProviders {
  plan: Provider;
  todo: Provider;
  askuser: Provider;
  footer: Provider;
  web: Provider;
  issues: string[];
}

/** The first `default: true` provider for `seam` (the validator enforces exactly one). */
function defaultFor(set: Provider[], seam: string): Provider | undefined {
  return set.find((p) => p.seam === seam && p.default);
}

/** Map `id -> Provider` (last wins on a duplicate id; the Python validator flags duplicates). */
function byId(set: Provider[]): Map<string, Provider> {
  const map = new Map<string, Provider>();
  for (const p of set) if (p.id) map.set(p.id, p);
  return map;
}

/**
 * Resolve a per-seam selection against the supported set (pure mirror of `resolve_providers`).
 *
 * For each seam, the selection resolves to the named provider **iff** the id exists AND its `seam`
 * matches the key; otherwise it falls back to `defaultFor(seam)` and appends a loud-but-non-fatal
 * issue (unknown id / seam mismatch). An **absent** key falls back to the default **silently** (the
 * zero-config default — no issue). Defaults are trusted (not re-validated). Throws if the bundled
 * set has no default for a seam (a corrupt install — the caller's try/catch fails safe). Omitting
 * `set` loads the bundled `providers.yaml`.
 */
export function resolveProviders(
  selection: { plan?: string; todo?: string; askuser?: string; footer?: string; web?: string },
  set?: Provider[],
): ResolvedProviders {
  const providers = set ?? loadProviders();
  const ids = byId(providers);
  const issues: string[] = [];

  const requireDefault = (seam: string): Provider => {
    const def = defaultFor(providers, seam);
    if (def === undefined) {
      throw new Error(`perk: no default provider for seam \`${seam}\` — reinstall perk`);
    }
    return def;
  };

  const resolveSeam = (seam: "plan" | "todo" | "askuser" | "footer" | "web"): Provider => {
    const selected = selection[seam];
    if (selected == null) return requireDefault(seam);
    const provider = ids.get(selected);
    if (provider === undefined) {
      issues.push(`\`${seam}\` selects unknown provider \`${selected}\``);
      return requireDefault(seam);
    }
    if (provider.seam !== seam) {
      issues.push(`provider \`${selected}\` is a \`${provider.seam}\` provider, not \`${seam}\``);
      return requireDefault(seam);
    }
    return provider;
  };

  return {
    plan: resolveSeam("plan"),
    todo: resolveSeam("todo"),
    askuser: resolveSeam("askuser"),
    footer: resolveSeam("footer"),
    web: resolveSeam("web"),
    issues,
  };
}
