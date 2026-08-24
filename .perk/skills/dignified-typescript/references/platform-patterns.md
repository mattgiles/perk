# Platform Patterns

Use only the sections relevant to the current codebase. Platform conventions refine the core rules; they do not replace them.

## React

### Keep context contracts honest

Represent an unavailable context explicitly and centralize the failure:

```tsx
const AuthContext = createContext<AuthState | undefined>(undefined);

export function useAuth(): AuthState {
	const value = useContext(AuthContext);
	if (value === undefined) {
		throw new Error("useAuth must be used within AuthProvider");
	}
	return value;
}
```

Do not assert a fabricated default object merely to avoid the check.

### Make effect ownership complete

An effect that subscribes, opens, schedules, or acquires must return cleanup. Capture the exact resource created by that effect invocation; avoid cleanup through mutable state that may now refer to a newer resource.

Pass `AbortSignal` to owned asynchronous work where possible. Guard against stale results if the underlying API cannot cancel.

### Derive state when possible

Do not store data that can be computed cheaply from props and existing state. Redundant state creates synchronization obligations and impossible combinations.

Use discriminated unions for multi-stage UI state:

```ts
type LoadState<T> =
	| { kind: "idle" }
	| { kind: "loading" }
	| { kind: "loaded"; value: T }
	| { kind: "failed"; error: Error };
```

### Preserve server/client boundaries

Do not pass non-serializable values through a serialization boundary. Keep provider clients, capabilities, and secrets on the server side. Treat user-visible error text as a separate, sanitized projection of internal failures.

## Workers and edge runtimes

### Treat environment bindings as capabilities

Pass the narrow binding required by a component, not the entire environment object. Keep authority visible in constructors and function parameters.

Do not expose secrets or privileged binding objects through logs, serialized errors, client state, or broad shared types.

### Own background work with the runtime

Use the platform lifetime mechanism, such as `waitUntil`, for work that should outlive the response. Observe failures through the established reporting path.

Do not rely on process-global background loops, shutdown hooks, or filesystem assumptions that do not hold in isolate runtimes.

### Parse every remote response

Typed `fetch` wrappers do not make provider JSON trustworthy. Bound the body, parse it, validate its structure, and project only fields needed by the domain.

### Keep durable state transitions explicit

For stateful worker objects, centralize transaction, retry, alarm, and concurrency semantics. Do not spread implicit read-modify-write sequences across handlers.

## Node services and libraries

### Follow the real ESM contract

Align source specifiers, emitted files, `package.json` type, and export maps. If Node runs TypeScript through type stripping, restrict code to erasable TypeScript syntax and do not expect type-aware transformation.

### Keep process lifecycle at the edge

Libraries should not call `process.exit`, install global handlers, or eagerly read environment variables on import. Application entry points may translate failures into exit codes and own signal handling.

### Bound operating-system interactions

Validate paths, arguments, environment input, subprocess output, and file sizes. Prefer structured subprocess APIs with argument arrays over shell command construction.

Dispose file handles, watchers, child processes, and temporary resources deterministically.

## Command-line interfaces

### Separate parsing, domain work, and presentation

A clean CLI shape is:

1. parse arguments into a typed command;
2. validate configuration and dependencies;
3. run domain logic;
4. render output;
5. translate the result into an exit status at the entry point.

Do not scatter `process.exit` calls through helpers.

### Model commands as a discriminated union

```ts
type Command =
	| { kind: "list"; json: boolean }
	| { kind: "show"; id: string; json: boolean }
	| { kind: "delete"; id: string; force: boolean };
```

This removes invalid option combinations from downstream code and makes dispatch exhaustive.

### Treat output as an API

Keep machine-readable output stable and free of progress messages. Send diagnostics to the correct stream. Sanitize errors and avoid printing credentials embedded in URLs or environment-derived configuration.

Map expected usage, domain, and transport failures to deliberate exit codes. Preserve cancellation semantics for signals where the platform contract requires it.

## Framework and RPC handles

Framework-provided stubs and clients may carry lifecycle obligations even when they look like ordinary objects. Check for `Symbol.dispose`, `Symbol.asyncDispose`, framework cleanup functions, or React effect cleanup.

Some RPC systems pipeline promises intentionally. A non-awaited call can be correct when ownership transfers to the framework. Require a clear framework contract and keep error observation explicit; do not apply a generic no-floating-promises rewrite mechanically.

## Platform review checklist

- Does React cleanup correspond to the resource created by that effect?
- Are edge bindings treated as narrow capabilities?
- Is background work registered with the platform lifetime primitive?
- Does Node code match its actual emission and ESM mode?
- Does the CLI separate parsing, domain behavior, presentation, and exit status?
- Are framework-specific promise and disposal semantics understood before refactoring?

