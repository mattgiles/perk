# Boundaries and Errors

Read this reference when handling network data, JSON, storage, plugin input, DOM messages, errors,
logs, retries, authentication, authorization, or other trust boundaries.

## Build one narrow boundary

Use this sequence:

1. bound the amount of work or data;
2. receive an `unknown` value;
3. validate the load-bearing shape;
4. normalize external naming and optionality;
5. construct a smaller internal value;
6. keep downstream code free of repeated defensive casts.

```ts
type ProviderItem = { id: string; createdAt: number };

function parseProviderItem(value: unknown): ProviderItem {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalidProviderResponse();
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.id !== "string" ||
    typeof record.created_at !== "number" ||
    !Number.isFinite(record.created_at)
  ) {
    throw invalidProviderResponse();
  }
  return { id: record.id, createdAt: record.created_at };
}
```

Validate every field that later participates in authorization, filtering, cursors, resource
selection, or arithmetic. Pass through non-load-bearing provider metadata only when the internal
type admits it explicitly and callers understand that it remains untrusted.

## Prefer schemas for shared or recursive contracts

Use a runtime schema when values cross a wire or persistence boundary, the shape is recursive,
several producers must agree, or error reporting benefits from structured paths. Derive the static
type from the schema.

Configure strict object schemas for protocols that must reject unknown fields. Test both inbound and
outbound validation. Never assume encoding implies validation.

Use handwritten parsers when the shape is small, the accepted subset is deliberate, or a security
check depends on a few explicitly validated fields. Keep these parsers beside the boundary.

## Bound first, parse second

Apply limits before allocating or parsing untrusted bodies. Use both declared length and streamed
byte counts when possible. Cancel the reader on refusal and release its lock in `finally`.

Reject a truncated structured payload rather than pretending the prefix is valid. Bound recursive
depth, item counts, string lengths, redirects, pages, retries, and concurrent operations wherever an
external party controls them.

For URLs and redirects, validate every hop. Drop credentials when authority changes. Fail closed
when a URL cannot be parsed or an allowlist decision cannot be made.

## Reconstruct allowlisted output

At a security or privacy boundary, construct a fresh object containing only allowed fields. Do not
spread an untrusted object and delete a few known-dangerous properties; new properties would bypass
the deletion list.

Normalize a URL by parsing it and rebuilding only the approved origin/path components. Do not trim a
raw string and assume credentials, queries, fragments, or opaque schemes are gone.

## Treat thrown values as unknown

JavaScript permits throwing any value. Normalize defensively:

```ts
function toError(caught: unknown): Error {
  return caught instanceof Error ? caught : new Error(String(caught));
}
```

When error objects may contain hostile getters or cannot cross the platform boundary, serialize only
bounded own/readable fields inside a final defensive `try/catch`. Return a safe fallback if inspection
itself throws.

## Choose exception, result, or nullable return by semantics

Use an exception when:

- the operation cannot fulfill its contract;
- a dependency failed unexpectedly;
- invalid input should abort the current call;
- the natural platform API already rejects.

Use a discriminated result when:

- failure is a normal domain outcome;
- the caller must branch on several expected reasons;
- the outcome crosses a serialization boundary;
- partial or pending states are part of the protocol.

Use `undefined` or `null` only for one well-defined absence case. Do not use a nullable return to hide
why an operation failed.

## Give programmatic errors stable metadata

Subclass `Error` when callers need a code, status, resource id, or retry classification:

```ts
class ServiceError extends Error {
  readonly code: "not-found" | "busy";

  constructor(
    code: "not-found" | "busy",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ServiceError";
    this.code = code;
  }
}
```

Keep provider-authored text separate from safe programmatic codes. A message may be safe to return to
the initiating caller but unsafe to log, aggregate, or report.

Preserve the original error through `cause` when supported, or rethrow it unchanged when consumers
depend on its identity or enumerable flags. Do not wrap merely to change the message punctuation.

## Catch at a meaningful boundary

Inside a `catch`, do one or more of these explicitly:

- translate to a domain error;
- add safe context and preserve the cause;
- compensate for a partial action;
- release a resource (prefer `finally` when unconditional);
- classify and retry a replay-safe operation;
- report/log once at the responsible boundary;
- return a documented fallback;
- rethrow unchanged.

Avoid broad catches that silently turn bugs into empty arrays, false values, or stale cache entries.
Permit a best-effort fallback only when the product contract explicitly says failure must not affect
the caller and the failure remains diagnosable where appropriate.

## Design logs as a public data boundary

Log stable structured fields such as event name, component, operation, safe ids, numeric provider
codes, counts, and timings. Pass the caught value through the repository's error field so one
serializer owns redaction and bounding.

Never log:

- access tokens, cookies, authorization headers, or secret configuration;
- prompts or user documents by default;
- complete request or response bodies;
- unbounded exception messages/stacks;
- a client-supplied identity as if it were verified authority;
- a remote string that can forge structure through control characters or newlines.

Redact secrets before truncating: truncation can split a secret and defeat exact replacement. Check
common encodings when the remote side may echo encoded credentials.

## Separate identity from claims

Only verified authentication material may establish identity. Keep client-reported user ids and
display metadata explicitly labeled as unverified diagnostics.

Prefer capability-shaped APIs: hand code the narrow object it is authorized to use instead of a
large environment plus repeated permission booleans. Enforce authorization at the single place that
mints the capability.

Fail closed when a grant is missing or ambiguous. Preserve meaningful distinctions such as omitted
scope (all by documented policy) versus an empty scope (none).

## Retry only with a proof

Before retrying, answer:

1. Is the failure transient based on stable data rather than brittle message text?
2. Is the operation replay-safe, idempotent, or protected by an idempotency key?
3. Can the first attempt have succeeded while its response was lost?
4. Does the second attempt acquire a fresh connection, stub, token, or transaction when required?
5. Is the retry budget bounded and cancellable?
6. Are delays jittered when many clients may retry together?
7. Does the final failure retain identity and useful metadata?

Keep classification separate from retry policy. A failure can be observable as a reset without being
safe to replay.

## Test the boundary adversarially

Include tests for:

- null, primitives, arrays, cyclic objects, and hostile getters;
- missing, extra, wrong-type, empty, and contradictory fields;
- exact size limits, one byte over, multibyte text, and encoded secrets;
- URL credentials, fragments, queries, private hosts, and redirects;
- verified versus client-claimed identity;
- safe log fields and excluded sensitive values;
- retryable, non-retryable, overloaded, aborted, and second-failure cases;
- preservation of error identity, cause, flags, and bounded messages.
