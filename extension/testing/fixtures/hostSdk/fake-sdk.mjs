// A fake host SDK that exports ONLY its `VERSION` (from the test's env) — every symbol the SDK
// adapter names (`createAgentSessionServices`, `ModelRuntime`, …) is missing.
export const VERSION = process.env.PERK_TEST_FAKE_SDK_VERSION;
