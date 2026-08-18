---
title: The jsdom React component harness — bootstrap traps, controlled inputs, keyboard contracts
read_when: Testing React components or keyboard/focus contracts under node:test + jsdom — DOM bootstrap before react-dom import, controlled-input value tracker, latest-wins + key remount
cluster: toolchain-gotchas
---

# The jsdom React component harness

Rendered component tests are the last layer in a testing stack, not the first. The reusable harness
lives in `tools/prose-review/componentHarness.ts`, with its import-order bootstrap in
`tools/prose-review/domBootstrap.ts`. It exists to test behavior that genuinely belongs to React's
mount, event, and focus boundaries while leaving fetch and state-machine logic in cheaper
framework-free tests.

## Extract controllers before rendering components

The default posture in `tools/prose-review` is to move fetch orchestration and state transitions into
framework-free `src/*.ts` controllers. Drive those controllers with `node:test` and structural fetch
stubs; keep React components thin. The mechanism exercised by the test must be the production
mechanism. A parallel test-only implementation of deduplication, invalidation, or request ordering
can pass while the component still calls a different path.

Rendered tests are justified where mounting changes the contract: unmount/remount invalidation,
shared loader lifetime, controlled form plumbing, delegated keyboard events, and focus movement.
Budget these suites and their jsdom/React packaging pins in the plan rather than adding them only
after review exposes an untested boundary. `tests/test_packaging.py` owns the exact-pin guard for the
tooling workspace.

## Bootstrap the DOM before `react-dom` evaluation

`react-dom` performs environment probes at module evaluation time. If it loads before any DOM
exists, it can select an old change-event fallback whose browser assumptions do not hold in jsdom;
controlled `onChange` handlers then appear broken even though the rendered markup looks correct.

`tools/prose-review/domBootstrap.ts` installs a minimal global window and document before
`react-dom/client` is imported. Keep that side-effect import first in
`componentHarness.ts`. Each test still creates and tears down its own fresh JSDOM instance; the
bootstrap window exists only to make import-time capability detection match a browser-like
environment. Installing a DOM after importing React DOM is too late.

## Drive controlled inputs through React's value tracker

Assigning an input's `value` and dispatching an event is insufficient for a controlled React input.
React tracks the last seen value and may classify the synthetic change as no change. The harness
uses the element prototype's native value setter, resets React's value tracker to the previous
value, and then dispatches bubbling input and change events inside `React.act`.

The sequence is a harness responsibility, not something each component test should reproduce.
Select elements have a different contract: they need a value assignment and native change event,
not the input tracker dance. Centralizing both paths keeps future React upgrades confined to one
mechanics file.

## Keyboard events must preserve browser-observable behavior

Dispatch a bubbling, cancelable `KeyboardEvent` inside `React.act`, and return the event to the
test. React's delegated handlers and window listeners then see the same event, while the assertion
can verify `defaultPrevented`. A helper that returns only after settling but discards the event
cannot prove that a shortcut claimed the key.

Two keyboard requirements should be planning defaults:

- A review-gated, state-changing shortcut ignores `event.repeat` in the listener that performs the
  action. Filtering later can still duplicate intermediate work.
- Arrow-key handlers claim only unmodified, non-composing events. Modifier chords and IME
  composition remain available to the browser and assistive technology.

jsdom implements real focus and `document.activeElement`, so tests can assert complete focus
movement, wraparound, and restoration contracts. What it cannot prove is CSS geometry, visible
focus-ring pixels, or behavior inside a third-party shadow DOM; reserve a browser leg for those.

## Polyfill only missing platform mechanics

The harness supplies no-op shims for jsdom APIs that production calls but whose visual effect is
outside the test, such as `scrollIntoView`. Keep these shims minimal and centralized. Do not
replace focus with a fake — jsdom's real active-element behavior is valuable evidence — and do not
mock event bubbling when the delegated event graph is what the suite needs to prove.

Every interaction and render runs under `React.act`, followed by a bounded event-loop settle. This
is about React update accounting, not arbitrary sleeps; a timer-based wait can hide a missing
state transition and make the suite nondeterministic.

## Latest response wins, but identity must own state

A monotonic request counter prevents an older response from overwriting a newer response. That is
only half the stale-view problem. Existing component state can still render under a newly requested
identity before either response settles.

Bind state to the requested id or key/remount the state-owning component when identity changes. The
counter protects response ordering; the key or identity-bound state protects presentation ordering.
Tests need both adversarial sequences: old response after new response, and identity change while
old local state is still populated.

## Raw-CDP fallback for browser dogfood

When a browser wrapper refuses the interaction needed by a dogfood gate, the fallback is a headless
browser shell driven through DevTools JSON-RPC. Use the browser's DevTools discovery endpoint,
connect to the selected page, and drive real keyboard/focus/zoom/layout behavior. This is an
executable fallback, not a reason to defer the gate to an unnamed human.

Keep the browser leg narrow. Component suites already own state, event, and focus contracts; CDP
exists for visual geometry and browser-only behavior. Record the exact launcher-served build and
teardown evidence so the browser result is attributable.

## Test and packaging boundaries

- `tools/prose-review/componentHarness.ts` is a shared plain TypeScript module imported by the
  component suites; it is not itself matched as a test file.
- `tools/prose-review/domBootstrap.ts` must stay importable before React DOM and should contain no
  per-suite state.
- `toolchain/node-test-async-determinism.md` carries the wider event-loop and test-isolation rules.
- `toolchain/docs-site-astro-starlight.md` records the jsdom-pin versus `engine-strict=true`
  compatibility check.
- `tests/test_packaging.py` pins the tooling dependencies and publish-isolation surfaces that a
  new rendered suite expands.

## Cross-references

- `docs/learned/toolchain/node-test-async-determinism.md` — deterministic async settlement under
  `node:test`
- `docs/learned/toolchain/docs-site-astro-starlight.md` — jsdom engine-floor and static-a11y facts
- `docs/learned/workflow/prose-review-workbench.md` — the workbench architecture and wire/edit
  contracts this harness supports
- `docs/learned/workflow/vacuity-proof-tests.md` — collision, stale-state, and real-default-path
  proof patterns
