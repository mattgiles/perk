// perk Pi extension — the published entry: a thin bootstrap that admits the loaded host SDK
// (contracts.md §8.76(f)) BEFORE the SDK-bearing composition root is linked.
//
// Why thin: the composition root (`pi/activation.ts`) statically imports named symbols from the
// SDK, so on a host whose SDK lacks them the import would fail before any refusal could run. This
// file's only value imports are three SDK-free substrate modules (the one SDK observation —
// `VERSION` — is a namespace read in `substrate/hostSdkVersion.ts`, never link-fatal); the
// composition root is reached by a dynamic import only after the host is admitted.
//
// A refused host THROWS from the factory: Pi's loader discards a throwing extension (it commits
// registrations only after the factory returns) and reports its own "Failed to load extension"
// error diagnostic carrying perk's refusal — so nothing registers, the host-SDK bridge is never
// installed, and a plain `pi` never runs with a partial set of perk tools.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PerkActivationOptions } from "./pi/activation.ts";
import { admitHostSdk, formatHostSdkRefusal } from "./substrate/hostAdmission.ts";
import { loadHostFloor } from "./substrate/hostFloor.ts";
import { loadedHostSdkVersion } from "./substrate/hostSdkVersion.ts";

export interface PerkEntryOptions extends PerkActivationOptions {
  /**
   * Construction-only: the observed host SDK version (default: the loaded SDK's `VERSION`). Tests
   * inject it to drive the refusal arms; production never passes it.
   */
  hostSdkVersion?: () => unknown;
}

export default async function perk(
  pi: ExtensionAPI,
  options: PerkEntryOptions = {},
): Promise<void> {
  const { hostSdkVersion, ...activation } = options;
  const hostSdk = admitHostSdk(
    (hostSdkVersion ?? loadedHostSdkVersion)(),
    loadHostFloor().piMinVersion,
  );
  if (hostSdk.outcome !== "admitted") {
    throw new Error(formatHostSdkRefusal(hostSdk, "extension"));
  }
  const { activatePerk } = await import("./pi/activation.ts");
  activatePerk(pi, hostSdk, activation);
}
