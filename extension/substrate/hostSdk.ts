// The host SDK namespaces perk itself was handed — the instances jiti resolves for perk's own
// imports (the bundle's `VIRTUAL_MODULES` under the `pi` bin, the alias files under the unbundled
// host), i.e. the host's own copies. The host-SDK bridge's facades re-export EXACTLY these, so a
// bridged consumer shares values and class identity with the running host. pi-tui arrives through
// the surfaces module's re-export (the one home pi-tui imports are confined to); the pi-ai root and
// its `/compat` subpath are captured separately and may be the same object — the host decides.

import * as hostPiAgentCore from "@earendil-works/pi-agent-core";
import * as hostPiAi from "@earendil-works/pi-ai";
import * as hostPiAiCompat from "@earendil-works/pi-ai/compat";
import * as hostPiCodingAgent from "@earendil-works/pi-coding-agent";
import * as hostTypebox from "typebox";
import * as hostTypeboxCompile from "typebox/compile";
import { hostPiTui } from "../surfaces/surfaces.ts";
import type { CensusSpecifier } from "./nativeSdkBridge.ts";

/** Each census specifier → the host namespace perk captured for it. */
export function hostSdkNamespaces(): ReadonlyMap<CensusSpecifier, object> {
  return new Map<CensusSpecifier, object>([
    ["@earendil-works/pi-coding-agent", hostPiCodingAgent],
    ["@earendil-works/pi-tui", hostPiTui],
    ["@earendil-works/pi-ai", hostPiAi],
    ["@earendil-works/pi-ai/compat", hostPiAiCompat],
    ["@earendil-works/pi-agent-core", hostPiAgentCore],
    ["typebox", hostTypebox],
    ["typebox/compile", hostTypeboxCompile],
  ]);
}
