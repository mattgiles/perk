---
title: Structured output over pi-ai — tool-calling, not JSON mode
read_when: You need a model to return structured/typed data in an extension, are choosing how to gate a model call offline in tests, or are writing offline tests for code that calls a provider.
---

# Structured output over pi-ai

pi-ai exposes **no JSON mode**. The portable way to get typed/structured data back from a model is
**tool-calling**: declare a single tool whose parameters are the schema you want, ask the model to
call it, and validate the call.

## The tool-calling idiom

Build one `Tool` with a TypeBox `parameters` schema, put it in `Context.tools`, call `complete()`,
then run `validateToolCall([tool], call)` on the first `content` block of `type === "toolCall"`.

- `extension/structuredOutput.ts` is the reusable layer: `resolveModelAuth(ctx)` reuses the session's
  configured + authenticated model; `completeStructured(opts)` builds the single-tool `Context`,
  calls `complete`, and validates the returned tool call.
- `extension/planTitle.ts` is the first consumer.

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

## Offline model-call tests use the faux provider

The pattern: register the faux provider, set canned responses (a faux assistant message carrying a
faux tool call with `stopReason: "toolUse"`), drive the code, assert, then unregister in `finally`.

- A `callCount === 0` assertion proves **no** model call fired — that is the gate test for
  `PERK_NO_LLM`.
- The faux model is typed `Model<string>`; cast it for the `Model<Api>` parameter.

`extension/planTitle.test.ts` is the worked example (the harness code is not reproduced here).

## Residual

No live end-to-end test exercises a real LLM call — by design, all tests run offline — so production
behavior against a real provider is unexercised by CI. Any schema fields captured but currently
ignored are deliberate seams for future consumers.

## Sources

Third-party API names, to re-verify against the installed `@earendil-works/pi-ai` before relying on
them:

- `@earendil-works/pi-ai` — `Tool`, `Context`, `complete`, `validateToolCall`, `StringEnum`, `Type`.
- The faux-provider test helpers — `registerFauxProvider`, `setResponses`, and the faux
  tool-call / message builders.

## Cross-references

- `extension/structuredOutput.ts` — `resolveModelAuth`, `completeStructured`
- `extension/planTitle.ts` — first consumer + the `PERK_NO_LLM` gate
- `extension/planTitle.test.ts` — the faux-provider offline test
- `docs/learned/pi/extension-api.md` — the broader extension API surface
- `docs/learned/toolchain/worktree-node-modules.md` — resolving the installed SDK in a worktree
