---
title: Structured output over pi-ai — tool-calling, not JSON mode
read_when: You need a model to return structured/typed data in an extension, are gating a model call offline in tests (PERK_NO_LLM is the only gate), or are writing offline tests for provider-calling code.
cluster: pi-extension
---

# Structured output over pi-ai

pi-ai exposes **no JSON mode**. The portable way to get typed/structured data back from a model is
**tool-calling**: declare a single tool whose parameters are the schema you want, ask the model to
call it, and validate the call.

## The tool-calling idiom

Build one `Tool` with a TypeBox `parameters` schema, put it in `Context.tools`, complete it
(registry dispatch, or the compat `complete` fallback), then run `validateToolCall([tool], call)`
on the first `content` block of `type === "toolCall"`.

- `extension/substrate/structuredOutput.ts` is the reusable layer: `completeStructured(opts)`
  builds the single-tool `Context` and completes it via the injected registry **`dispatch`** when
  the host provides one — pi ≥ 0.84's `ModelRegistry.complete`, where **pi owns final request
  assembly end to end** (resolved auth, nullable headers, credential-resolved `baseUrl`, provider
  `env`) — else falls back to the compat `complete` with caller-resolved auth
  (`resolveModelAuth(ctx)` reusing the session's configured + authenticated model). The fallback
  has a pre-existing limitation: it forwards apiKey/headers/env but has **no `baseUrl` option**,
  so a credential-resolved endpoint is silently dropped on old hosts — the dispatch path is the
  fix. Either path validates the returned tool call.
- `extension/pi/v1/planTitle.ts` is the first consumer: it **feature-detects**
  `registry.complete` (`typeof … === "function"` — absent on older hosts, never assumed) and
  wraps it as `dispatch`.

Both layers return **never-throwing soft outcomes** (`{ok, value?, error?}`) — no throw reaches the
caller.

## There is no portable forced tool-use — always keep a deterministic fallback

`complete`'s generic options expose no portable `toolChoice` (providers disagree on `"required"` vs
`"any"`). So **instruct tool use in the prompt** and keep a deterministic fallback at the call site
(e.g. a non-LLM default title). Use `StringEnum([...])` — **not** `Type.Enum` — for enum fields, per
pi-ai's Google-compat guidance.

## A deterministic offline gate is a dedicated env var, not an overload

`PERK_NO_LLM` is set by the **test harness** (defaulted in the harness env, with the caller env
spread last so it stays overridable) and **never by the production `perk` CLI**. So production
sessions generate output while tests stay offline — even on a dev machine that has provider keys
configured. This mirrors the existing `PERK_SELFCHECK` pattern.

**`ModelRegistry.getApiKeyAndHeaders` is NOT an offline gate.** It returns `ok: true` with an
undefined key when none exists (absent `authHeader` config), so auth resolution *succeeds* for
keyless real models — no credential seeding is needed for faux models, and `PERK_NO_LLM` is the
ONLY thing keeping keyless tests offline. Never rely on auth-resolution failure as a test guard.

## Faux-provider routing depends on WHO makes the model call

The harness's nested registration (`fauxModelRegistration()`, a nested pi-coding-agent copy of
pi-ai) serves **session-runtime** streaming only. **Extension-initiated** structured-output calls
resolve pi-ai at the **top level** under `node --test`, so register via the top-level
`registerFauxProvider()` — imported from `@earendil-works/pi-ai/compat` (the global API moved off
the root in pi-ai 0.80) — and pass the model in via `loadPerkSession({ model })`; a nested
registration would miss, and the runtime never streams the model in these tests.

## Offline model-call tests use the faux provider

The pattern: register the faux provider, set canned responses (a faux assistant message carrying a
faux tool call with `stopReason: "toolUse"`), drive the code, assert, then unregister in `finally`.

- A `callCount === 0` assertion proves **no** model call fired — that is the gate test for
  `PERK_NO_LLM`.
- The faux model is typed `Model<string>`; cast it for the `Model<Api>` parameter.

`extension/pi/v1/planTitle.test.ts` is the worked example (the harness code is not reproduced here).

## Residual

No live end-to-end test exercises a real LLM call — by design, all tests run offline — so production
behavior against a real provider is unexercised by CI. Any schema fields captured but currently
ignored are deliberate seams for future consumers.

## Sources

Third-party API names, to re-verify against the installed `@earendil-works/pi-ai` before relying on
them:

- `@earendil-works/pi-ai` (root) — the types plus `validateToolCall`, `StringEnum`, `Type`.
- `@earendil-works/pi-coding-agent` — `ModelRegistry.complete` (`dist/core/model-registry.d.ts`),
  the pi ≥ 0.84 registry dispatch `completeStructured` prefers; feature-detect it, never assume it.
- `@earendil-works/pi-ai/compat` — the old global API since pi-ai 0.80: `complete`, `getModel`, and
  the faux-provider test helpers (`registerFauxProvider`, `setResponses`, the faux tool-call /
  message builders). Pi's extension loader aliases the root to the compat entry (plus an explicit
  `/compat` alias), but tsc / plain `node --test` resolve the real root — value imports of the
  global API must name `/compat`. The bare-import guard (`extension/bareImportGuard.test.ts`)
  allowlists the loader-aliased `/compat` specifier.

## Cross-references

- `extension/substrate/structuredOutput.ts` — `resolveModelAuth`, `completeStructured`
- `extension/pi/v1/planTitle.ts` — first consumer + the `PERK_NO_LLM` gate
- `extension/pi/v1/planTitle.test.ts` — the faux-provider offline test
- `docs/learned/pi/extension-api.md` — the broader extension API surface
- `docs/learned/toolchain/worktree-node-modules.md` — resolving the installed SDK in a worktree
