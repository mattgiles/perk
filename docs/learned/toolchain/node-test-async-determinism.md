---
title: Deterministic async & timer coverage in node:test
read_when: You are testing interval/timer lifecycles or streamed progress in node:test — mock.timers setup, a leaked/unasserted ticker, or an immediately-resolving fake that hides completion-only streaming.
cluster: toolchain-gotchas
---

# Deterministic async & timer coverage in node:test

Two failure families from testing timer-driven and streamed-progress code with `node:test`, both
resolved deterministically — no real-time sleeps, no timeouts. Source pointer: the run-CI
progress work in `extension/doors/ciExecutor.ts` and its interval/`onUpdate` tests in
`extension/doors/ciExecutor.test.ts`.

## Interval lifecycle needs deterministic coverage, not real-time luck

Leaving a 1s ticker unasserted ("never fires within the test") means removing the ticker, a wrong
cadence, or a leaked interval all stay green. `node:test`'s `mock.timers`
(`apis: ["setInterval", "Date"]`) drives ticks and `Date.now` deterministically, works with the
`.unref()` path on the pinned Node runtime, and must be `reset()` in `finally`.

A bonus property: a tick-throw escaping a mocked interval surfaces **synchronously** through
`mock.timers.tick` — which also makes swallowed-throwing-sink guards testable on the timer path
(the "sink threw and the ticker swallowed it" arm is otherwise unobservable).

## Immediately-resolving fakes falsely validate completion-only streaming

A concurrency progress test whose fake exec resolves instantly lets everything settle before the
assertions run — so an implementation that emits only after `Promise.all` still passes
initial/final asserts. The streaming claim was never tested.

The deterministic shape: gate each fake check on its **own deferred** and await a **specific
intermediate emission while a sibling is still pending** — pure causal ordering, no timeouts. The
test proves an emission happened *mid-flight*, which is the actual streaming contract.
