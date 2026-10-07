// `--import` preload for the SDK-boundary admission's cold-process tests: maps the bare host SDK
// specifier to a fake module that exports (at most) `VERSION` — so every NAMED export the SDK
// adapter needs is missing, exactly like an SDK older than perk expects. Everything else resolves
// normally. `PERK_TEST_FAKE_SDK_FIXTURE=no-version` selects the fake with no `VERSION` at all.

import { registerHooks } from "node:module";

const fixture =
  process.env.PERK_TEST_FAKE_SDK_FIXTURE === "no-version"
    ? "fake-sdk-no-version.mjs"
    : "fake-sdk.mjs";
const fakeUrl = new URL(fixture, import.meta.url).href;

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@earendil-works/pi-coding-agent") {
      return { url: fakeUrl, format: "module", shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});
