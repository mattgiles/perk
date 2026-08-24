# Modules and Package Boundaries

Use this reference for imports, exports, ESM behavior, package entry points, declaration emission, and workspace boundaries.

## Read the module contract before editing

Determine:

- `module` and `moduleResolution`;
- whether code runs directly in Node, through a bundler, or in a Worker-like runtime;
- whether the package emits JavaScript, declarations only, or nothing;
- whether the package is ESM, CommonJS, or dual-format;
- the package `exports` map and public entry points;
- whether TypeScript syntax must be erasable at runtime.

These choices change what counts as a correct import. Do not transplant a convention from a NodeNext-emitted package into a source-bundled package without checking the build.

## Prefer static imports

Use top-level static imports for normal dependencies. They support analyzers, bundlers, cycle detection, and predictable initialization.

Use `import type` when an import is purely a type dependency:

```ts
import { createClient } from "./client.js";
import type { ClientOptions } from "./types.js";
```

Use dynamic `import()` only for a real runtime purpose: code splitting, optional dependencies, feature loading, or deferred expensive initialization. Do not hide an ordinary dependency in a function.

## Respect runtime specifiers

In NodeNext-style emitted code, source imports may need the extension that the runtime will load, such as `.js`, or a project-supported TypeScript extension rewrite. In bundler-oriented projects, extensionless source imports may be the established contract.

Follow the repository's compiler, package manager, and test runner together. An import that type-checks but fails after emission is not correct.

## Keep public entry points intentional

TypeScript packages often benefit from a small, explicit façade:

```ts
export { createClient } from "./client.js";
export type { Client, ClientOptions } from "./types.js";
```

This is not the same as an accidental barrel. A good public entry point:

- mirrors the package `exports` map;
- exposes a deliberate supported surface;
- has no import-time side effects;
- does not leak internal framework or provider types unintentionally;
- does not create cycles among implementation modules.

Avoid recursive `export *` trees whose public API changes whenever an internal file adds an export.

## Keep dependency direction legible

Prefer layers such as:

1. dependency-free types and pure utilities;
2. domain logic;
3. adapters for storage, transport, or frameworks;
4. composition and entry points.

Do not make shared domain code import an application entry point. If two modules form a cycle, move the stable contract downward or inject the behavior; do not disguise the cycle with dynamic imports.

## Account for emitted runtime syntax

When `erasableSyntaxOnly` or Node type stripping applies, avoid TypeScript constructs that require runtime transformation, including enums, parameter properties, namespaces with runtime code, and import aliases using `import =`.

Prefer:

```ts
const Status = {
	Ready: "ready",
	Failed: "failed",
} as const;

type Status = (typeof Status)[keyof typeof Status];
```

This also produces a value that serialization code can inspect.

## Protect declaration quality

For packages that emit declarations:

- annotate exported contracts when inference would expose implementation details;
- avoid inferred types that name private or deep dependency paths;
- export supporting public types intentionally;
- verify the generated declaration surface after structural changes;
- use type-only exports where appropriate.

Do not handwrite a mirror interface merely to make declaration output convenient. Derive or wrap the authoritative type.

## Avoid import-time work

Module evaluation should usually define values, not perform network calls, mutate global state, start timers, or read environment-dependent resources. Put lifecycle work behind an explicit factory or entry point.

Small, immutable configuration constants are fine. If initialization can fail, make the failure occur at an owned application boundary.

## Workspace packages are real boundaries

Even inside a monorepo:

- import through supported package entry points unless working inside the package;
- keep dependencies declared exactly where they are used;
- avoid reaching into sibling `src/` internals;
- keep shared packages free of application-only assumptions;
- test the published or built shape when consumers do not run raw source.

## Review checklist

- Does the import style match the actual resolver and runtime?
- Are type-only dependencies marked as such?
- Is each dynamic import justified by runtime behavior?
- Does the public façade match the export map without accidental leakage?
- Are entry modules side-effect free until explicitly invoked?
- Can the package emit or bundle without deep private type references?
- Is dependency direction acyclic and understandable?

