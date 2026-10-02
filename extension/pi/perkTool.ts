// The one production registration seam for perk's model-facing tools (contracts.md §8.40).
// Every perk tool registers here with its policy descriptor: the policy is validated, recorded
// in the tool catalog, and the derived Pi metadata (`exposure`, `annotations.readOnlyHint`) is
// added to the definition. Nothing else changes — `execute` and every other definition field pass
// through untouched (no wrapping, no result rewriting), so a terminating result stays exactly what
// the tool returned; the `kind: terminal` set is kept honest by the census pins, not at runtime.
//
// The loadout host (`perk_stage`) is the one other registrant here: the only tool allowed a
// `prepareLoadout` hook, which presents the session's stage/mode loadout by hiding declarations.

import type {
  ExtensionAPI,
  ToolDefinition,
  ToolLoadout,
  ToolLoadoutChanges,
} from "@earendil-works/pi-coding-agent";
import {
  derivePiMetadata,
  LOADOUT_HOST_NAME,
  type POLICY_OWNED_FIELDS,
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

/** Register a perk tool: validate + catalog its policy, then register with the derived metadata. */
export function registerPerkTool<TParams extends ToolDefinition["parameters"], TDetails = unknown>(
  pi: ExtensionAPI,
  definition: PerkToolDefinition<TParams, TDetails>,
  policy: ToolPolicy,
): void {
  validateToolPolicy(definition.name, definition, policy, REGISTRY_STAGE_IDS);
  recordPerkTool(definition.name, policy);
  pi.registerTool({ ...definition, ...derivePiMetadata(policy) });
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
 * no guidelines, so it never reaches the system prompt either.
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
