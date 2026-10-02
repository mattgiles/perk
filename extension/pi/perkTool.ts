// The one production registration seam for perk's model-facing tools (contracts.md §8.40).
// Every perk tool registers here with its policy descriptor: the policy is validated, recorded
// in the tool catalog, and the seam adds exactly two things — the derived DEFINITION fields
// (`exposure`, `annotations.readOnlyHint`, a query's `outputSchema`) and the derived RESULT fields
// (`structuredContent`, `isError`, via the Result seam's `structureResult` around `execute`).
// Every other definition field passes through by reference and every other result field is spread
// through untouched — `terminate` included, byte-for-byte, so a terminating result stays exactly
// what the tool returned; the `kind: terminal` set is kept honest by the census pins, not at
// runtime. Streamed `onUpdate` partials are never rewritten.
//
// The loadout host (`perk_stage`) is the one other registrant here: the only tool allowed a
// `prepareLoadout` hook, which presents the session's stage/mode loadout by hiding declarations.
//
// The discovery cohort's re-registration lives here too (`deferDiscoveryFamily`): a definition can
// only be replaced by the extension that registered it, so the seam retains what each activation
// registered (keyed by that activation's own `pi`) and re-registers exactly that, deferred.

import type {
  ExtensionAPI,
  ToolDefinition,
  ToolLoadout,
  ToolLoadoutChanges,
} from "@earendil-works/pi-coding-agent";
import { structureResult } from "../substrate/result.ts";
import {
  derivePiMetadata,
  discoveryFamily,
  LOADOUT_HOST_NAME,
  type POLICY_OWNED_FIELDS,
  perkToolPolicy,
  REGISTRY_STAGE_IDS,
  recordPerkTool,
  type ToolPolicy,
  validateToolPolicy,
} from "../substrate/toolPolicy.ts";

/** A perk tool definition: Pi's, minus the fields the policy derives (or forbids). */
export type PerkToolDefinition<
  TParams extends ToolDefinition["parameters"] = ToolDefinition["parameters"],
  TDetails = unknown,
> = Omit<ToolDefinition<TParams, TDetails>, (typeof POLICY_OWNED_FIELDS)[number]>;

/**
 * What each activation registered through the seam, keyed by that activation's own `pi` —
 * ownership is the activation, never the name: a second bound session in the same process has its
 * own `pi` and its own map, and a tool another extension registered is never re-registered here.
 */
const RETAINED = new WeakMap<ExtensionAPI, Map<string, ToolDefinition>>();

/**
 * Register a perk tool: validate + catalog its policy, then register with the derived metadata
 * and an `execute` whose returned result carries the derived structured fields.
 */
export function registerPerkTool<TParams extends ToolDefinition["parameters"], TDetails = unknown>(
  pi: ExtensionAPI,
  definition: PerkToolDefinition<TParams, TDetails>,
  policy: ToolPolicy,
): void {
  validateToolPolicy(definition.name, definition, policy, REGISTRY_STAGE_IDS);
  recordPerkTool(definition.name, policy);
  const { execute } = definition;
  const registered = {
    ...definition,
    ...derivePiMetadata(policy),
    execute: async (...args: Parameters<typeof execute>) => structureResult(await execute(...args)),
  } as ToolDefinition;
  pi.registerTool(registered);
  let owned = RETAINED.get(pi);
  if (owned === undefined) {
    owned = new Map();
    RETAINED.set(pi, owned);
  }
  owned.set(definition.name, registered);
}

/**
 * Re-register the discovery-pilot family `exposure: "deferred"` in THIS activation's registry:
 * each catalogued `declared: "deferred"` name this `pi` registered and the host still has. Pi's
 * `registerTool` replaces by name within the owning extension and keeps the tool in the active set
 * (the gating controller's one-time deactivation removes it). A member the registry already
 * reports deferred is skipped, so a re-emitted `session_start` re-registers nothing; a per-name
 * failure is reported and skipped. Returns the family names now deferred, in catalog order.
 */
export function deferDiscoveryFamily(pi: ExtensionAPI): string[] {
  const owned = RETAINED.get(pi);
  if (owned === undefined) return [];
  const exposures = new Map(pi.getAllTools().map((t) => [t.name, t.exposure] as const));
  const deferred: string[] = [];
  for (const name of discoveryFamily()) {
    const retained = owned.get(name);
    const policy = perkToolPolicy(name);
    if (retained === undefined || policy === undefined || !exposures.has(name)) continue;
    if (exposures.get(name) === "deferred") {
      deferred.push(name);
      continue;
    }
    try {
      pi.registerTool({ ...retained, ...derivePiMetadata(policy, { cohort: true }) });
      deferred.push(name);
    } catch (error) {
      console.error(`perk: could not defer ${name} — ${error}`);
    }
  }
  return deferred;
}

/**
 * The loadout host's policy: eligible in every landing (every stage, gate-allowed, mode over
 * stage), so own-names-only activation keeps it active wherever it is registered — Pi runs
 * `prepareLoadout` only for ACTIVE tools.
 */
export const LOADOUT_HOST_POLICY: ToolPolicy = {
  stages: REGISTRY_STAGE_IDS,
  gated: "allowed",
  modeOverStage: true,
  kind: "host",
};

/**
 * Register the loadout host: an always-active, model-only tool with no action whose
 * `prepareLoadout` hides declarations from each request (itself always). No prompt snippet and
 * no guidelines, so it never reaches the system prompt either. Its `execute` is never called, so
 * it stays unwrapped.
 */
export function registerLoadoutHost(
  pi: ExtensionAPI,
  prepareLoadout: (loadout: ToolLoadout) => ToolLoadoutChanges,
): void {
  recordPerkTool(LOADOUT_HOST_NAME, LOADOUT_HOST_POLICY);
  pi.registerTool({
    name: LOADOUT_HOST_NAME,
    label: "perk stage",
    description:
      "perk's loadout host: it presents the session's stage/mode tool loadout and has no action.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
    ...derivePiMetadata(LOADOUT_HOST_POLICY),
    prepareLoadout,
    async execute() {
      return {
        content: [{ type: "text", text: "perk_stage has no action." }],
        details: {},
      };
    },
  });
}
