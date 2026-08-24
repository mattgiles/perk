# Core Standards

Apply these standards to every TypeScript and TSX task after inspecting the project contract.

## Keep runtime truth and type truth together

Treat values crossing a trust, serialization, persistence, process, network, DOM, or plugin boundary as
`unknown`. Convert them into an internal type through a schema, parser, or explicit narrowing function.

```ts
type Job = { id: string; attempts: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseJob(value: unknown): Job {
  if (!isRecord(value)) {
    throw new TypeError("Invalid job payload");
  }

  const { id, attempts } = value;
  if (typeof id !== "string" || typeof attempts !== "number" || !Number.isInteger(attempts)) {
    throw new TypeError("Invalid job payload");
  }

  return { id, attempts };
}
```

For a substantial shape, prefer a runtime schema and derive `Job` from it. Use a handwritten guard for a
small, load-bearing subset when validating the entire provider payload would add noise without protection.

Never write this at a boundary:

```ts
const job = (await response.json()) as Job;
```

## Let control flow narrow values

Prefer ordinary JavaScript checks that also communicate runtime intent:

```ts
function messageOf(caught: unknown): string {
  if (caught instanceof Error) return caught.message;
  if (typeof caught === "string") return caught;
  return "Unknown failure";
}
```

Use a type predicate when the same check is reused. Use an assertion function only when failure should stop
the current operation.

Do not destructure an untrusted object before narrowing it. Do not use property access in a security check
until the containing value and the property have been validated.

## Model state instead of decorating it with booleans

Use one discriminant and give each state only the fields it can validly possess:

```ts
type Operation<T> =
  | { status: "pending"; startedAt: number; value?: never; error?: never }
  | { status: "complete"; value: T; error?: never }
  | { status: "failed"; error: Error; value?: never };
```

Avoid shapes such as `{ loading: boolean; result?: T; error?: Error }`; they permit impossible combinations.

Switch directly on the discriminant. Add an exhaustive `never` check when a missing case could otherwise
fall through or return a plausible value.

## Derive instead of mirror

Prefer these sources of truth:

- runtime schema -> inferred static type;
- `as const` data -> indexed union;
- existing function -> `Parameters`, `ReturnType`, or `Awaited`;
- existing interface -> `Pick`, `Omit`, indexed access, or a mapped type;
- command union -> `Extract` for a specific variant.

Use `satisfies` to check a value without widening away useful literals:

```ts
type HandlerMap = Record<"open" | "close", () => void>;

const handlers = {
  open: () => start(),
  close: () => stop(),
} satisfies HandlerMap;
```

Do not introduce a handwritten interface that mirrors another owned contract and then bridge the mismatch
with a cast.

## Choose `type`, `interface`, and `class` by role

- Use `type` for unions, intersections, tuples, mapped/conditional types, aliases, and closed data shapes.
- Use `interface` for a named object contract implemented by classes or supplied structurally by callers.
- Use `class` when identity, encapsulated mutable state, inheritance required by a framework, or runtime
  behavior such as `instanceof` matters.
- Do not create classes merely to make plain data look important.
- Do not turn every object into an interface; declaration merging should be intentional, not accidental.

## Annotate contracts, infer mechanics

Annotate exported functions when the return type is part of the contract or when inference could expose an
implementation detail. Annotate callbacks, recursive functions, public class members, and boundary adapters
when doing so prevents widening or accidental API drift.

Let local constants, small private helpers, and obvious callbacks infer their types. Avoid repeating a type
the initializer already states exactly.

## Use the assertion ladder

Before writing a cast or non-null assertion, try in order:

1. improve the source type;
2. narrow with control flow;
3. validate with a schema or guard;
4. use `satisfies` for a constructed value;
5. isolate a single assertion immediately after the runtime evidence;
6. place unavoidable unsafe interop behind a typed adapter.

Treat `as unknown as T`, `!`, `any`, and `@ts-ignore` as claims that need visible evidence. Permit them in
tests that deliberately construct impossible inputs, in generated code, or at a framework seam only when
the escape hatch cannot contaminate callers.

Prefer `@ts-expect-error` over `@ts-ignore` for a deliberate type-level negative test because it fails when
the expected error disappears.

## Preserve absence semantics

Use explicit checks when the domain distinguishes values:

```ts
const timeout = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
if (record.note !== undefined) publish(record.note);
if (token === null) return unauthenticated();
```

Use `||` only when every falsy value means the same thing. Do not substitute `?.` for required invariants;
optional chaining is appropriate only when absence is valid.

Model wire-level omission deliberately. Test whether optional `undefined` properties are omitted, retained,
or normalized according to the serializer contract.

## Keep APIs narrow and named

Use an options object when several parameters share a primitive type, optional policy is growing, or callers
would otherwise pass positional booleans. Keep the essential subject positional when that improves reading.

```ts
async function fetchDocument(
  id: string,
  options: { signal?: AbortSignal; deadline?: number },
): Promise<Document> {
  // ...
}
```

Make defaults express stable policy, not caller forgetfulness. Centralize security limits, retry budgets,
timeouts, and normalization rules. Document defaults on exported contracts when callers need to reason about
them.

Use `Readonly`, `readonly`, or a narrow `Pick` to express ownership and least capability. Do not add deep
immutability mechanically to values that are intentionally stateful.

## Keep modules unsurprising

Use the import spelling and module-resolution rules already selected by the repository. Mark type-only
imports and exports explicitly. Keep imports at module scope by default.

Allow dynamic imports only for a real runtime need such as optional capability loading, measured startup
cost, or bundler code splitting. Do not use them to conceal a dependency cycle.

Keep package entry modules declarative and side-effect free. Re-export intentionally to define a supported
public surface; do not create convenience barrels that make internal symbols public or introduce cycles.

## Make ownership visible in async code

Pass `AbortSignal` through cancellable layers. Remove listeners and clear timers. Use `using`/`await using`
with `Symbol.dispose`/`Symbol.asyncDispose` when the configured runtime and libraries support them; otherwise
use `try/finally`.

Use `Promise.all` when all results are required and one failure should fail the operation. Use
`Promise.allSettled` for best-effort cleanup or fan-out only when every rejection is inspected.

Never leave background work unowned. Attach it to a platform lifecycle such as `waitUntil`, await it, or
store and drain it through an explicit manager. Always define its rejection behavior.

## Keep errors meaningful

Catch `unknown`. Catch close to the operation only to classify, translate, compensate, add safe context, or
perform required cleanup. Otherwise let the error reach the boundary that can present or report it.

Use a custom `Error` subclass when callers branch on stable programmatic metadata. Use a discriminated
`Result` when failure is an expected domain outcome that the caller must handle. Avoid converting every
exception into a result or every expected outcome into an exception.

Never log secrets, credentials, complete remote bodies, or unbounded thrown values. Preserve the original
error or its stable metadata when rethrowing; do not turn a useful error into an unstructured string.

## Test the contract

Test observable behavior, not the current line structure. Include successful cases, malformed inputs,
missing and empty values, boundary sizes, cancellation, cleanup, failure identity, and every state variant
that carries different semantics.

Use table-driven tests for a behavior matrix. Keep fake capabilities narrow. Add a regression test for a real
failure mode; do not build speculative test infrastructure for imaginary features.
