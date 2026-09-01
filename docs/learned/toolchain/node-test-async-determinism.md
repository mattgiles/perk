---
title: Deterministic async & timer coverage in node:test
read_when: You are testing interval/timer lifecycles or streamed progress in node:test — mock.timers setup, a leaked/unasserted ticker, or an immediately-resolving fake that hides completion-only streaming.
cluster: toolchain-gotchas
---

# Deterministic async & timer coverage in node:test

Two failure families from testing timer-driven and streamed-progress code with `node:test`, both
resolved deterministically — no real-time sleeps, no timeouts. Source pointer: the run-CI
progress work in `extension/delivery/ci.ts` and its interval/`onUpdate` tests in
`extension/pi/v1/delivery/ci.test.ts`.

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

## Inject every effect seam, drive with a hand-rolled FakeTimers

For a subsystem whose behavior is *made of* time (debounce, poll, backoff, heartbeat), inject
every effect seam: the clock (`now()`), the timers (set/clear timeout **and** interval), the
`fs.watch` factory, and the report sink. A ~60-line hand-rolled FakeTimers — absolute-time due
ordering, intervals rescheduled on fire — then drives arbitrary debounce/poll/backoff/heartbeat
interleavings with zero sleeps. Anchor: `extension/hunkFeedback/inbox.test.ts` (the `FakeTimers`
class and the seam-injected inbox under test).

## Sequential "race" tests are fiction — use test-only race hooks

A test that performs step A, then step B, then asserts "the race is handled" never ran a race —
it ran a sequence. Lease-reclaim races only became testable via explicit test-only hooks
(`beforeQuarantine`/`afterQuarantine` in `acquireLease`, `extension/hunkFeedback/store.ts`) that
run a competitor synchronously *inside* the check-then-act window — and the first hook-driven
interleaving immediately exposed a real defect the sequential test had passed over. (The lease
protocol itself is documented in `workflow/lease-outbox-delivery.md`.)
