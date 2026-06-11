---
title: The runColdDoor envelope-aware client — decode policy, narrowing helpers, door migrations
read_when: You are migrating a warm door onto `runColdDoor`, writing a decode for a cold-door JSON envelope, choosing strict vs advisory validation for a payload field, or chasing a door-test assertion change after a migration.
---

# The cold-door client (`runColdDoor`)

`extension/coldDoor.ts` is the one envelope-aware client for running a cold Python door from the
extension: it execs the door, parses the JSON envelope, and returns typed success/failure —
replacing the per-door exec/parse copies. This doc captures the decode policy split, the exported
narrowing helpers, and the migration playbook that keeps door tests green.

## What the client is

- `runColdDoor<T>` takes an `ExecHost`, argv, a label, and a caller-supplied `decode`; it never
  throws (with one residual caveat below) and returns either the decoded payload or a typed failure
  (`errorType` + message).
- `ExecHost` uses the SDK's `ExecOptions`/`ExecResult` types via **type-only import** — method-
  parameter bivariance keeps the structural slice satisfiable by `ExtensionAPI`. The compile-time
  drift checks (`const _h: ExecHost = {} as ExtensionAPI`) live in the **test file**, so divergence
  fails `tsc`.
- `activeRunId` is exported deliberately so tests assert the `cold-door-<ts>` stamp fallback and the
  workflow-state read directly.

## The decode policy split (the reusable pattern)

Two arms, chosen per payload field:

- **Strict on the core payload:** malformed → decode returns `null` → the client reports
  `bad_output` with "`<label>` returned an unexpected payload". Use this arm for anything the
  success message/marker logic **dereferences**.
- **Advisory sub-objects are validated-but-dropped:** malformed → the field becomes `undefined` and
  the success report survives. Use this arm for report-only extras whose underlying mutation already
  succeeded (e.g. land's `objective`/`learn` sub-reports).

A dropped advisory field must also **short-circuit any follow-up drive** — land's reconcile drive
skips when `objective` is `undefined` (pinned by test). Don't let a downstream drive dereference an
advisory field the decode dropped.

## Compose the exported narrowing helpers

`extension/coldDoor.ts` exports `stringField` / `numberField` / `booleanField` / `objectField` (the
latter rejects arrays and null). Door decodes should compose these, not re-implement `typeof`
checks; they're unit-covered in `coldDoor.test.ts`, so new decodes only need door-level tests.

- TS **inferred type predicates** handle element-checked arrays:
  `Array.isArray(x) && x.every((n) => typeof n === "string")` narrows `unknown` to `string[]` under
  the repo's tsc — no explicit `is` predicate needed.
- `string | null` contract fields need a **three-way narrow** (string / null / wrong-typed): the
  helper's `undefined` is ambiguous with an absent key, so pair it with an explicit
  `obj.key !== undefined` presence check when wrong-typed must reject the sub-object (see
  `nullableString` in `extension/land.ts`).

## Label choice is the byte-compat lever

Passing the legacy label (e.g. `label: "perk pr <sub>"`) reproduces the pre-migration fallback
texts **exactly**, keeping a door migration test-green without touching existing assertions. The two
pre-announced behavior changes are pinned once and never need re-pinning per door:

- envelope-aware non-zero exit (the envelope's `error_type`/`message` is surfaced instead of a
  generic stderr-tail message);
- malformed payload → `bad_output` instead of `github_error`.

Future doors only test their own decode edges.

## Envelope edge semantics

- On non-zero exit, a `success: false` envelope with **non-string** `error_type`/`message` still
  takes the structured arm — message falls back to the generic exit text, errorType to
  `exec_failed`. Only string-typed fields are honored.
- Door failure messages **will change as doors migrate** (envelope surfaced instead of stderr tail);
  expect assertion churn per migration and reconcile the door's own tests in the same turn.
- **Residual:** the caller-supplied `decode` is not try/caught — the "never throws" guarantee holds
  only if `decode` doesn't throw. Cheap fix when touching the client: wrap the decode call in
  try/catch → `bad_output`.

## Testing notes

- Permission-based fs-failure tests (chmod a dir read-only to force a mkdir failure) need a
  `process.platform === "win32" || process.getuid?.() === 0` skip guard — root and Windows ignore
  the read-only bit.

## Cross-references

- `extension/coldDoor.ts` — `runColdDoor`, the narrowing helpers, `activeRunId`
- `extension/coldDoor.test.ts` — the client mechanics pins + the compile-time `ExecHost` drift check
- `extension/land.ts` — the advisory-drop + three-way-narrow exemplar
- `docs/learned/workflow/warm-door-commands.md` — a warm door must render every cold-door outcome;
  this client is the mechanism
