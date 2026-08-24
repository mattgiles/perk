# Evidence Base

This reference records how the skill was derived. Read it when auditing a recommendation or refreshing the skill against newer repository versions; it is not required for normal TypeScript work.

## Research method

The guidance was produced in August 2026 from three sources:

1. the structure and editorial method of Dagster's `dignified-python` skill;
2. a stratified review of TypeScript packages in `earendil-works/pi`;
3. a stratified review of TypeScript packages in `cloudflare/cloudflare-os`.

The repository review combined:

- project instructions, manifests, export maps, workspace configuration, compiler configuration, formatter and linter rules;
- a census of non-generated `.ts` and `.tsx` files by package root;
- a sample spanning every package root plus intentionally selected boundary, protocol, lifecycle, error, CLI, React, Worker, and test code;
- construct counts used as discovery signals, followed by direct reading to distinguish preferred patterns from legacy, generated, test-only, and interop code;
- cross-checks against official TypeScript and Node documentation for compiler and runtime facts.

The snapshots reviewed were:

- Dagster skills: `a0774616a075182cd84b4fafc63d788f35431bc1`
- pi: `dcd461925db2edf69a43c8135db1180d418afd54f`
- cloudflare-os: `23ff840bc8af035da4079da6b662a48f160e3778`

The sample covered 57 pi files and 61 cloudflare-os files across their TypeScript package roots. Counts informed where to look; they were not treated as votes. Explicit repository policy and high-scrutiny kernel or boundary code received more weight than incidental frequency.

## What came from the upstream skill

The upstream skill demonstrates a compact dispatcher backed by one always-loaded core reference and focused conditional references. It favors explicit defaults, anti-patterns, checklists, version awareness, and project inspection before advice.

This TypeScript skill adopts that information architecture without translating Python rules literally. In particular, intentional public re-export façades are often appropriate in TypeScript packages, while runtime validation, module resolution, emitted syntax, and resource disposal require TypeScript-specific treatment.

- [Dagster dignified-python skill](https://github.com/dagster-io/skills/tree/a0774616a075182cd84b4fafc63d788f35431bc1/skills/dignified-python/skills/dignified-python)

## Evidence from pi

The pi repository strongly supports:

- strict compiler settings and erasable TypeScript syntax;
- static imports, explicit package entry points, and type-only imports;
- schema-derived protocol types;
- discriminated unions, including `never` fields that forbid invalid combinations;
- abort propagation and deterministic disposal;
- per-resource serialization with `finally` cleanup;
- small helpers, exact dependencies, and testing at protocol and retry boundaries;
- using `any` or assertions only where an actual compatibility or test seam requires them.

Primary examples:

- [Repository instructions](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/AGENTS.md)
- [Compiler baseline](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/tsconfig.base.json)
- [Schema-derived protocol model](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/packages/protocol/src/schemas.ts)
- [Discriminated session types](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/packages/agent/src/harness/session/types.ts)
- [Abort-signal composition](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/packages/ai/src/utils/abort-signals.ts)
- [Per-file mutation queue](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/packages/agent/src/harness/tools/file-mutation-queue.ts)
- [Protocol contract tests](https://github.com/earendil-works/pi/blob/dcd461925db2edf69a43c8135db1180d418afd54f/packages/protocol/test/protocol.test.ts)

## Evidence from cloudflare-os

The cloudflare-os repository adds a higher-scrutiny view of boundaries and platform ownership:

- public kernel APIs require an unusually high design and documentation bar;
- types should be derived from real schemas or RPC contracts rather than mirrored and double-cast;
- provider responses are bounded, parsed, validated, and projected;
- errors are classified while retaining stable identity and safe context;
- retries preserve replay and failure semantics;
- capabilities and verified identity are distinct from client claims;
- Worker lifetime primitives and RPC disposal define ownership;
- promise pipelining may be intentional when the framework owns completion;
- different packages legitimately use different formatting and compilation modes.

Primary examples:

- [Repository instructions](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/AGENTS.md)
- [Review policy](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/REVIEW.md)
- [Workspace tool versions](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/pnpm-workspace.yaml)
- [Bounded observability parser](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/gatekeeper-cloudflare/src/observability-parse.ts)
- [Typed fetch boundary](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/mcp-shared/src/fetch.ts)
- [Retry implementation](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/workshop-backend/src/do-retry.ts)
- [Retry contract tests](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/workshop-backend/__tests__/do-retry.test.ts)
- [Safe exception serialization](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/error-reporting/src/serialize-exception.ts)
- [Shared API surface](https://github.com/cloudflare/cloudflare-os/blob/23ff840bc8af035da4079da6b662a48f160e3778/packages/workshop-shared/src/api.ts)

## Compiler and runtime facts

These official references anchor claims that are version-sensitive or runtime-specific:

- [`erasableSyntaxOnly`](https://www.typescriptlang.org/tsconfig/erasableSyntaxOnly.html)
- [`satisfies` operator](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html)
- [Control-flow narrowing and `never`](https://www.typescriptlang.org/docs/handbook/2/narrowing.html)
- [Explicit resource management](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-2.html)
- [TypeScript module reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html)
- [Node.js TypeScript type stripping](https://nodejs.org/api/typescript.html)
- [Node.js package entry points and exports](https://nodejs.org/api/packages.html)

Recheck the active repository's installed compiler and runtime documentation before relying on a recently introduced language feature.

## Deliberate synthesis choices

The central stance is: **strict and explicit at boundaries; compact and inference-friendly inside**.

The skill deliberately does not prescribe:

- semicolons, quote style, tabs versus spaces, or import grouping;
- one universal import-extension policy;
- `type` or `interface` exclusively;
- schema validation for every private in-memory object;
- `readonly` or deep immutability everywhere;
- `Result` for all failures;
- zero assertions under every framework or generated-code constraint;
- compatibility shims without an actual compatibility obligation.

These are context-sensitive decisions. The stable requirements are honest runtime boundaries, deliberate ownership, explicit public contracts, and evidence for each unsafe escape hatch.

## Updating this evidence

When refreshing the skill:

1. pin new repository snapshots;
2. re-read the project instructions and toolchain before sampling source;
3. cover every TypeScript package root and select high-scrutiny boundary code;
4. distinguish preferred current patterns from generated, legacy, test-only, and interop code;
5. update rules only when several high-quality examples or explicit policy support them;
6. verify version-sensitive statements against current official documentation;
7. record meaningful disagreements instead of forcing the repositories into one style.

