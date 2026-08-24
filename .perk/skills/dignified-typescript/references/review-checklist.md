# Review Checklist

Use this after the task-relevant guidance. Prioritize findings that affect runtime correctness, security, ownership, public contracts, or future change. Do not manufacture style findings that the formatter or repository conventions already settle.

## Project contract

- [ ] Read the nearest instructions, manifests, complete `tsconfig` chain, and relevant tool configuration.
- [ ] Identify the runtime, module resolver, emission or bundling path, package boundary, and public entry points.
- [ ] Preserve local formatting and naming conventions unless the task explicitly changes them.
- [ ] Verify assumptions against adjacent source and tests rather than a generic TypeScript preference.

## Runtime and type truth

- [ ] Treat external, persisted, decoded, DOM, plugin, and provider values as untrusted until narrowed.
- [ ] Derive static types from runtime schemas or authoritative values where possible.
- [ ] Avoid mirrored interfaces, double assertions, leaking `any`, and unjustified non-null assertions.
- [ ] Ensure type predicates and assertion functions perform every check they claim.
- [ ] Keep literals narrow with `satisfies` or `as const` only where that improves the contract.

## State and API design

- [ ] Use discriminated unions for states or commands with different valid fields.
- [ ] Make contradictory combinations unrepresentable, including with `never` fields when useful.
- [ ] Handle union variants exhaustively when a missing case would be dangerous.
- [ ] Use `type`, `interface`, and `class` according to their role, not a blanket rule.
- [ ] Annotate exported contracts while allowing local mechanics to infer naturally.
- [ ] Keep options, defaults, nullability, mutation, and ownership explicit.
- [ ] Document public behavior, limits, side effects, cancellation, and compatibility obligations.

## Boundaries, errors, and security

- [ ] Bound input size before expensive parsing and validate before property access.
- [ ] Reconstruct narrow internal values instead of spreading untrusted provider objects.
- [ ] Catch `unknown` only to classify, translate, compensate, add safe context, report, or rethrow.
- [ ] Preserve stable error identity, metadata, cause, and retry semantics where callers use them.
- [ ] Keep secrets, credentials, raw bodies, and unbounded values out of errors and logs.
- [ ] Distinguish verified identity and granted capability from client-claimed metadata.
- [ ] Retry only transient, replay-safe operations with bounded policy and cancellation.

## Async and resources

- [ ] Give every promise a visible owner and every background failure an observation path.
- [ ] Propagate `AbortSignal` through cancellable layers and remove related listeners and timers.
- [ ] Dispose resources on success, failure, and cancellation at the scope that acquired them.
- [ ] Choose `Promise.all`, `allSettled`, sequential work, or a queue according to failure and ordering semantics.
- [ ] Serialize by the real contention key and clean queues without races.
- [ ] Preserve backpressure and explicit close/cancel semantics for streams.

## Modules and packages

- [ ] Match import spelling to the actual resolver, emitted runtime, and repository convention.
- [ ] Use static and type-only imports intentionally; justify dynamic imports with runtime behavior.
- [ ] Keep public entry points explicit, side-effect free, and aligned with package export maps.
- [ ] Avoid accidental barrels, deep sibling-package imports, and hidden dependency cycles.
- [ ] Verify declaration output or consumer imports when changing a library surface.
- [ ] Use only TypeScript syntax supported by the chosen runtime transformation path.

## Tests and verification

- [ ] Test the public contract, not private implementation structure.
- [ ] Cover valid, invalid, empty, missing, contradictory, boundary-size, and adversarial cases.
- [ ] Test type-level promises when runtime tests cannot observe them.
- [ ] Test cancellation, cleanup, retry, concurrency, and error identity deterministically.
- [ ] Exercise the real package or protocol boundary at least once when it changes.
- [ ] Run focused type checking and tests, then broader documented checks when the risk warrants them.
- [ ] Report what was not verified and why.

## Final quality bar

- [ ] The change is smaller or clearer than the problem it solves.
- [ ] The type model helps a reader predict runtime behavior.
- [ ] Unsafe interop is isolated and justified at the exact seam.
- [ ] Authority, ownership, lifecycle, and compatibility are visible.
- [ ] Comments explain invariants and surprises rather than narrating code.
- [ ] No compatibility shim, abstraction, generic, or framework was added without a present need.

