# Async Work, Cancellation, and Resources

Use this reference for concurrent work, cancellation, retries, streams, handles, sessions, RPC stubs, timers, files, and background tasks.

## Make async ownership visible

Every asynchronous operation needs an owner responsible for its result, failure, and lifetime.

- `await` work whose result belongs to the current operation.
- Return a promise when the caller owns completion.
- Register background work with the platform's lifetime primitive when one exists.
- Intentionally detach work only when its errors are observed and its lifetime is safe.

Avoid bare floating promises. A deliberate transport optimization, such as pipelined RPC, is acceptable only when the surrounding contract makes that ownership clear.

## Propagate cancellation

Accept `AbortSignal` at the boundary of cancellable work and pass it through every layer that can honor it.

```ts
export async function loadProfile(
	userId: string,
	options: { signal?: AbortSignal } = {},
): Promise<Profile> {
	const response = await fetch(`/api/users/${encodeURIComponent(userId)}`, {
		signal: options.signal,
	});

	return parseProfileResponse(response);
}
```

If several signals should cancel the same work, compose them rather than inventing mutable flags. Remove event listeners once settled when the runtime does not do so automatically.

Treat abort as a distinct outcome when callers need to distinguish it from transport or domain failure.

## Clean up deterministically

Prefer lexical resource management when the project runtime supports it:

```ts
using session = await openSession();
return await session.run(request);
```

Use `await using` for async disposal. Otherwise use `try`/`finally`:

```ts
const session = await openSession();
try {
	return await session.run(request);
} finally {
	await session.close();
}
```

Disposal belongs at the scope that acquired the resource. This applies to RPC stubs, locks, timers, subscriptions, readers, temporary files, and framework sessions—not only database connections.

Do not assume garbage collection performs protocol-level cleanup.

## Choose the concurrency primitive by failure semantics

Use `Promise.all` when:

- all tasks must succeed;
- one failure invalidates the aggregate result;
- remaining work is harmless or cancellable.

Use `Promise.allSettled` when:

- cleanup or shutdown must attempt every operation;
- partial completion is meaningful;
- every failure will be inspected or reported.

Use sequential awaits when order, rate limits, resource bounds, or shared mutation matter. Do not serialize independent work accidentally, and do not parallelize merely for compact syntax.

## Serialize work by the real contention key

When operations conflict only for a particular resource, queue by that resource rather than globally.

```ts
const tails = new Map<string, Promise<void>>();

export async function mutateFile<T>(path: string, task: () => Promise<T>): Promise<T> {
	const previous = tails.get(path) ?? Promise.resolve();
	let release!: () => void;
	const current = new Promise<void>((resolve) => {
		release = resolve;
	});
	const tail = previous.then(() => current);
	tails.set(path, tail);

	await previous;
	try {
		return await task();
	} finally {
		release();
		if (tails.get(path) === tail) tails.delete(path);
	}
}
```

The map cleanup condition must not delete a newer queued tail. Prefer an existing queue or mutex abstraction when the project has one.

## Retry only replay-safe operations

A retry policy needs proof, not optimism. Establish:

- the operation is idempotent or protected by an idempotency key;
- which errors are transient;
- the maximum attempts or time budget;
- backoff and jitter;
- cancellation behavior;
- what happens if retry bookkeeping itself fails.

Preserve the original error identity and metadata where callers rely on it. Avoid a final generic wrapper that erases the useful cause.

```ts
export async function withRetry<T>(
	operation: () => Promise<T>,
	options: { attempts: number; signal?: AbortSignal },
): Promise<T> {
	let lastError: unknown;

	for (let attempt = 1; attempt <= options.attempts; attempt += 1) {
		options.signal?.throwIfAborted();
		try {
			return await operation();
		} catch (error: unknown) {
			lastError = error;
			if (attempt === options.attempts || !isRetryable(error)) throw error;
			await delay(backoffFor(attempt), options.signal);
		}
	}

	throw lastError;
}
```

The unreachable final throw exists to satisfy control-flow analysis; prefer a loop shape that makes the invariant evident over a cast.

## Model streams as lifetimes

For streams and async iterables, specify:

- who closes or cancels the producer;
- how consumer cancellation propagates;
- whether partial output is valid;
- how errors surface after some values were emitted;
- whether backpressure is preserved.

Avoid buffering an unbounded stream just to simplify its type.

## Review checklist

- Does every promise have an owner?
- Does cancellation reach network, storage, subprocess, and timer operations?
- Is each acquired resource disposed on success, failure, and cancellation?
- Does the chosen concurrency primitive match partial-failure semantics?
- Are retries bounded, cancellable, and demonstrably replay-safe?
- Are queues scoped to the actual contention key and cleaned without races?
- Do background failures remain observable?
