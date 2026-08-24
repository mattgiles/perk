# Type Design

Read this reference when changing unions, interfaces, generics, schemas, guards, assertions, or
public type surfaces.

## Start from the value and its owner

Ask before naming a type:

1. Does the value exist at runtime?
2. Who constructs it?
3. Which boundary validates it?
4. Is the set of variants open or closed?
5. Does a caller need the entire value or only a capability-shaped subset?

Prefer a type that describes the smallest stable contract the consumer needs. Avoid importing a
large application object when a `Pick` or focused interface expresses the dependency.

## Derive from the source of truth

### Derive from constants

```ts
const levels = ["low", "medium", "high"] as const;
type Level = (typeof levels)[number];

function isLevel(value: string): value is Level {
  return (levels as readonly string[]).includes(value);
}
```

Keep the unavoidable assertion inside the guard rather than at every caller.

### Derive from schemas

Define the runtime validator once, then infer the static type through the schema library. Configure
object schemas to reject unknown properties when the wire contract is strict. Do not handwrite the
same shape in an interface.

### Derive from existing APIs

```ts
type Loader = typeof loadWorkspace;
type LoadOptions = Parameters<Loader>[1];
type Workspace = Awaited<ReturnType<Loader>>;
type Failed = Extract<Operation, { status: "failed" }>;
```

Use derivation when it preserves a real relationship. Do not hide a simple domain concept behind a
stack of utility types merely to avoid writing three fields.

## Use discriminated unions for closed state

Give every variant a literal discriminant. Share fields through a base only when they have identical
semantics in every variant.

```ts
type Command =
  | { kind: "list" }
  | { kind: "open"; id: string; create?: never }
  | { kind: "create"; name: string; id?: never };
```

Use `never` properties when object literals could otherwise express incompatible options. Avoid
making every forbidden property optional-`never` if the variants are already unambiguous.

Preserve correlated fields in the union:

```ts
type Reply<T> =
  | { ok: true; value: T; error?: never }
  | { ok: false; error: DomainError; value?: never };
```

Do not replace the correlation with `{ ok: boolean; value?: T; error?: DomainError }`.

## Make exhaustiveness useful

Use an exhaustive helper when a newly added variant must break the consumer:

```ts
function unreachable(value: never): never {
  throw new Error(`Unhandled variant: ${String(value)}`);
}

function label(status: Status): string {
  switch (status.kind) {
    case "ready":
      return "Ready";
    case "failed":
      return status.message;
    default:
      return unreachable(status);
  }
}
```

Omit a synthetic `default` when the function's control flow and return type already prove coverage
and the runtime should not invent behavior for future values. Do not use `default` to hide a missing
case.

## Choose interface or type deliberately

Prefer an `interface` for:

- a structural capability supplied by callers;
- a contract implemented by classes;
- a public object API intended for extension;
- a stable named boundary that benefits from readable diagnostics.

Prefer a `type` for:

- unions or intersections;
- mapped, indexed, or conditional transformations;
- tuples and function aliases;
- closed data objects that participate in unions;
- aliases derived from schemas or values.

Do not convert between the two for aesthetics. Do not rely on declaration merging unless the API is
explicitly designed for augmentation.

## Use classes only for runtime behavior

Use a class when at least one of these matters:

- stable object identity;
- private mutable state;
- a required framework base class;
- lifecycle methods or disposal;
- runtime recognition with `instanceof`;
- construction invariants that cannot be represented as plain data.

Use native `#private` fields when runtime privacy is required and the target supports them. Follow
the repository's class-field and decorator compilation settings. Under erasable-only execution,
avoid parameter properties, enums, namespaces, and other syntax that needs transformation.

## Keep generics relational

Use a type parameter when the same type relationship appears in at least two meaningful positions:

```ts
interface Store<T> {
  get(id: string): T | undefined;
  put(value: T): void;
}
```

Question a generic used only once. Prefer `unknown`, a concrete type, or a non-generic overload when
the parameter does not preserve information for the caller.

Constrain the capability actually used:

```ts
function byId<T extends { id: string }>(items: readonly T[]): Map<string, T> {
  return new Map(items.map((item) => [item.id, item]));
}
```

Avoid public conditional types whose behavior a caller cannot predict. Give complex derived types a
domain name and add type-level tests when the relationship is important.

## Prefer `satisfies` for checked construction

Use a type annotation when the variable's public type should be widened. Use `satisfies` when the
initializer should retain literal or tuple precision while being checked against a contract.

```ts
const routes = {
  health: { method: "GET", path: "/health" },
  create: { method: "POST", path: "/items" },
} as const satisfies Record<string, { method: "GET" | "POST"; path: string }>;
```

Do not append `as const` automatically. Use it when literal identity or readonly tuples are part of
the relationship.

## Design type guards as parsers of one fact

Keep a guard small and honest:

```ts
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
```

Do not claim a rich domain type after checking one field. Either return a narrower structural type,
validate the complete load-bearing shape, or use a schema.

Use `asserts value is T` only when invalid input should throw immediately. Name it `assert...` or
`require...` so the control flow is visible to the reader.

## Express ownership with readonly types

Use `readonly` parameters when a function does not own mutation. Use `Readonly<T>` for configuration
or capability objects passed across layers. Keep internal mutable storage private and expose
read-only views when callers must not mutate it.

Remember that TypeScript readonly is shallow and compile-time only. Copy, freeze, or validate at
runtime when mutation by untrusted code would violate an invariant.

## Localize escape hatches

Permit a cast only when adjacent runtime evidence or an external invariant proves it. Cast to the
narrowest type and return a safe public type.

Prefer:

```ts
if (!isRecord(value)) throw new TypeError("Expected an object");
const record = value;
if (typeof record.id !== "string") throw new TypeError("Missing id");
return { id: record.id };
```

Avoid returning `record as DomainObject`. If a framework type is wrong, create one adapter module,
document the upstream mismatch, test it, and keep `any` or double assertions inside that file.

## Document public contracts

Document exported symbols whose behavior is not obvious from the signature. Explain:

- ownership and disposal;
- defaults and bounds;
- failure and cancellation behavior;
- whether a callback may be async;
- whether data is trusted, normalized, or provider-authored;
- compatibility or wire-format obligations.

Do not write comments that simply restate field names.
