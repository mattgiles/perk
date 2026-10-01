// The one production registration seam for perk's model-facing tools (contracts.md §8.40).
// Every perk tool registers here with its policy descriptor: the policy is validated, recorded
// in the tool catalog, and the derived Pi metadata (`exposure`, `annotations.readOnlyHint`) is
// added to the definition. Nothing else changes — `execute` and every other definition field pass
// through untouched (no wrapping, no result rewriting), so a terminating result stays exactly what
// the tool returned; the `kind: terminal` set is kept honest by the census pins, not at runtime.

import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
  derivePiMetadata,
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
  pi.registerTool<TParams, TDetails>({ ...definition, ...derivePiMetadata(policy) });
}
