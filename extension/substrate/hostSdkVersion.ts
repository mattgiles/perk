// The loaded Pi SDK's public `VERSION` — the one observation the SDK-boundary admission reads
// (contracts.md §8.76(f)).
//
// This is the ONLY `@earendil-works/*` specifier either thin entry (`extension/index.ts`,
// `extension/workerMain.ts`) may reach before admission, and it is a NAMESPACE import on purpose:
// under Node's native ESM a missing NAMED export is a link-time SyntaxError, so a named import
// from an SDK older (or newer) than perk expects would fail before the useful refusal could run; a
// namespace binding never fails for a missing name — an SDK with no `VERSION` reads `undefined`
// here and is refused as unverifiable.
//
// Deliberately not `hostSdk.ts`: that module also captures pi-tui through the surfaces module and
// every other host namespace — not a thin leaf. Keep this file a single read with no other imports.

import * as hostPiCodingAgent from "@earendil-works/pi-coding-agent";

/** The loaded SDK's public VERSION as this process resolved the package (unknown: an old SDK may export none). */
export function loadedHostSdkVersion(): unknown {
  return (hostPiCodingAgent as { VERSION?: unknown }).VERSION;
}
