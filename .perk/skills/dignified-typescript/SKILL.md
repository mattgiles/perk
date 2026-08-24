---
name: dignified-typescript
description: Opinionated production TypeScript and TSX guidance for writing, reviewing, refactoring, and designing maintainable code. Use for TypeScript code quality, type modeling, runtime validation, assertions and `any`, discriminated unions, async cancellation and cleanup, ESM/package boundaries, Node CLIs, React, Cloudflare Workers/RPC, tests, or requests to make code idiomatic, elegant, strict, or safer. Inspect the repository toolchain and runtime first; preserve explicit project conventions when they differ.
stages: [gist-author, objective-author, objective-plan, plan, implement, stack-review]
---

# Dignified TypeScript

Write TypeScript that makes runtime truth visible in the types, keeps authority and ownership explicit,
and remains ordinary JavaScript where no type machinery is needed.

Treat this as an opinionated production baseline, not a substitute for repository instructions. Prefer a
small coherent change over a style crusade.

## Follow the workflow

1. Inspect the repository before proposing a pattern.
2. Read `references/core.md` completely.
3. Load only the task-relevant references from the table below.
4. Preserve the existing runtime, module, packaging, formatting, and test strategy unless the task changes it.
5. Implement or review the smallest design that makes invalid behavior difficult to express.
6. Run the repository's own focused checks first, then its documented broader verification when warranted.
7. Report behavioral changes, compatibility impact, validation performed, and any remaining uncertainty.

## Detect the project contract

Inspect these sources in order:

1. `AGENTS.md`, `CONTRIBUTING.md`, `REVIEW.md`, and local instructions.
2. The nearest `package.json` and workspace manifest; note the package manager, engines, `type`, `exports`,
   scripts, pinned versions, and package boundaries.
3. The complete `tsconfig` inheritance chain; note `strict`, `target`, `lib`, `module`, `moduleResolution`,
   `noEmit`, `isolatedModules`, `erasableSyntaxOnly`, JSX, path mappings, and file inclusion.
4. The formatter, linter, bundler, test runner, runtime configuration, and adjacent source imports.
5. Existing public entry points, schemas, error types, lifecycle conventions, and test patterns.

Do not infer import suffixes, emitted file locations, decorator support, DOM globals, Node globals, or direct
TypeScript execution from the file extension alone. Distinguish at least these common modes:

- emitted Node ESM (`NodeNext`/`Node16`);
- source executed through Node type stripping;
- source consumed by a bundler (`moduleResolution: "bundler"`);
- browser/React code;
- Workers/workerd code;
- library packages with explicit export maps.

## Apply the default stance

| Concern | Default |
| --- | --- |
| Untrusted values | Accept `unknown`; validate or narrow once at the boundary. |
| Runtime and static models | Derive one from the other; never maintain mirrored shapes by hand. |
| State | Use discriminated unions; make contradictory fields unrepresentable. |
| `type` vs `interface` | Use `type` for unions/transformations/data aliases; use `interface` for named behavioral or extensible contracts. |
| Inference | Infer local implementation details; annotate exported contracts and ambiguous boundaries. |
| Assertions | Prefer narrowing, schemas, `satisfies`, or a small adapter; isolate unavoidable assertions. |
| `any` | Confine it to proven interop seams; never let it escape into ordinary code. |
| Absence | Preserve the difference among missing, `undefined`, `null`, `false`, `0`, and `""`. |
| Async work | Propagate cancellation, name the owner of background work, and make cleanup deterministic. |
| Modules | Use static top-level imports by default and explicit type-only imports. |
| Public API | Publish intentional entry points; keep façades declarative and side-effect free. |
| Mutation | Use `const` by default; use localized mutation when it expresses a real state transition more clearly. |
| Compatibility | Preserve documented public contracts; otherwise migrate call sites instead of accumulating shims. |
| Comments | Explain invariants, trust boundaries, ownership, and surprising provider/runtime behavior—not syntax. |

## Enforce the hard rules

- Do not treat a TypeScript type, interface, assertion, or generic constraint as runtime validation.
- Do not add `as unknown as`, a non-null assertion, or `any` merely to silence the checker.
- Do not catch a value without deciding whether to translate, retry, report, compensate, or rethrow it.
- Do not silently discard a promise unless the surrounding API explicitly owns it and its failure path.
- Do not retry a side effect without proving that replay is safe or supplying an idempotency mechanism.
- Do not collapse absence with truthiness when `false`, `0`, or an empty string is meaningful.
- Do not retain listeners, timers, streams, handles, RPC stubs, subscriptions, or locks beyond their owner.
- Do not broaden a public export surface accidentally through convenience barrels.
- Do not create a second type vocabulary for an existing schema, RPC interface, or source-of-truth constant.
- Do not normalize formatting by hand; use the repository's formatter.

## Load references conditionally

| Situation | Read |
| --- | --- |
| Every invocation | `references/core.md` |
| Designing unions, interfaces, generics, guards, or assertions | `references/type-design.md` |
| Parsing external values, handling errors, logging, retries, or security boundaries | `references/boundaries-and-errors.md` |
| Working with promises, aborts, streams, queues, listeners, or disposable resources | `references/async-and-resources.md` |
| Changing imports, entry points, package exports, build modes, or generated code | `references/modules-and-packages.md` |
| Adding or reviewing tests | `references/testing.md` |
| Building a Node CLI, React surface, Worker, Durable Object, or RPC API | `references/platform-patterns.md` |
| Performing the final review | `references/review-checklist.md` |
| Auditing why this skill recommends a rule or updating its evidence base | `references/evidence-base.md` |

## Resolve conflicts deliberately

Prefer, in order:

1. user requirements;
2. repository instructions and established public contracts;
3. runtime and compiler facts;
4. adjacent code that is demonstrably intentional;
5. this skill's defaults.

Call out an intentional deviation when it affects correctness, security, compatibility, or maintenance. Do
not spend review attention on semicolons, quotes, tabs, line width, or import grouping when automation owns
those choices.
