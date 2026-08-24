# Testing Dignified TypeScript

Use this reference for unit, integration, type-level, boundary, lifecycle, and regression tests.

## Test the contract, not the implementation shape

Tests should explain what callers may rely on:

- accepted inputs and returned values;
- rejected inputs and error identity;
- state transitions and invariants;
- cancellation and cleanup;
- compatibility at package or protocol boundaries.

Avoid assertions about private helper call order unless that order is itself the contract.

## Pair positive and negative cases

Boundary code is incomplete when tested only with a happy-path object. Cover:

- missing required fields;
- wrong primitive types;
- `null`, empty strings, empty collections, and extra keys when relevant;
- malformed JSON and non-JSON responses;
- values at, below, and above limits;
- contradictory discriminants and fields;
- provider changes such as a new union member.

For validators and parsers, assert both the accepted normalized value and the rejected input's error category.

## Use table-driven tests for rule families

```ts
describe.each([
	["missing id", {}, "id"],
	["empty id", { id: "" }, "id"],
	["wrong state", { id: "x", state: "unknown" }, "state"],
])("parseJob: %s", (_name, input, expectedField) => {
	it("rejects the invalid value", () => {
		expect(() => parseJob(input)).toThrow(expectedField);
	});
});
```

Keep the case matrix readable. When cases need different setup or expected behavior, separate tests may communicate better.

## Assert error semantics precisely

If callers distinguish a custom error, retry flag, status, or cause, test it directly.

```ts
await expect(operation()).rejects.toMatchObject({
	name: "ClientError",
	retryable: false,
	status: 400,
});
```

Test that sensitive provider bodies, tokens, credentials, and oversized payloads do not appear in messages or logs.

When a wrapper must preserve the original error instance, assert identity with `toBe`, not merely an equal message.

## Test resource lifetimes

Exercise success, failure, and cancellation paths. Assert that:

- disposers run exactly once;
- listeners and timers are removed;
- a failed cleanup does not silently hide a more important primary failure unless the contract says so;
- queued work releases the next waiter;
- all shutdown operations are attempted when using all-settled semantics;
- RPC or framework handles do not outlive their scope.

Fake timers are useful for retries and cancellation only when they preserve the relevant event-loop behavior. Prefer a controlled clock abstraction over sleeps.

## Test concurrency invariants deterministically

Coordinate tests with deferred promises, latches, or explicit hooks rather than timing guesses.

```ts
function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((settle) => {
		resolve = settle;
	});
	return { promise, resolve };
}
```

Use this to prove ordering, parallelism, per-key serialization, and cleanup without relying on slow timeouts.

## Include compile-time tests where types are the product

When a library promises narrowing, generic inference, forbidden union combinations, or public declarations, runtime tests are insufficient. Use the project's established type-test mechanism, such as fixture compilation or `@ts-expect-error` assertions.

Each `@ts-expect-error` should state why the line must fail:

```ts
// @ts-expect-error A completed job cannot carry a retry delay.
const impossible: JobState = { kind: "completed", retryAfterMs: 100 };
```

Do not use type-error directives to mute unrelated compiler failures.

## Test public and protocol boundaries at the right level

For package APIs, import from the public entry point in at least one test. For protocols, round-trip or parse realistic wire values. For adapters, test the provider-specific translation while keeping domain tests provider-neutral.

Avoid making every unit test boot the full application. Use the narrowest level that still exercises the contract.

## Preserve regression intent

A regression test should make the former failure obvious in its name and setup. Minimize unrelated fixtures so a future reader can tell which invariant it protects.

## Review checklist

- Are happy, invalid, edge, and adversarial inputs covered?
- Are type-level promises tested when they cannot be observed at runtime?
- Are error identity, metadata, cause, and redaction asserted where contractual?
- Are cancellation, cleanup, and concurrent ordering deterministic?
- Does at least one test exercise the real public or protocol boundary?
- Would a failure message identify the broken rule without reading the implementation?

