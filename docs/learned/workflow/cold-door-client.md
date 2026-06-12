---
title: The runColdDoor envelope-aware client — decode policy, narrowing helpers, door migrations
read_when: You are adding a warm door that shells to a `--json` cold door (the substrate is mandatory), writing a decode for a cold-door JSON envelope, choosing strict vs advisory vs fully-lenient validation for a payload field, consuming a fail-arm payload, or chasing a door/fixture assertion change after strictening a decode.
---

# The cold-door client (`runColdDoor`)

`extension/coldDoor.ts` is the one envelope-aware client for running a cold Python door from the
extension: it execs the door, parses the JSON envelope, and returns typed success/failure —
replacing the per-door exec/parse copies. This doc captures the decode policy split, the exported
narrowing helpers, and the migration playbook that keeps door tests green.

## Rollout COMPLETE — the substrate is mandatory

All nine warm doors (submit/ready/land, planSave/objectiveSave, address/learn/learnDocs,
objectivePlan ×2) delegate through `runColdDoor`; no per-door `activeRunId` copies remain (the
stamp fallback is uniformly `cold-door-<ts>`). **A new warm door that shells to a Python `--json`
cold door MUST consume the substrate — hand-rolled exec/parse is a regression, not a style
choice.**

## What the client is

- `runColdDoor<T>` takes an `ExecHost`, argv, a label, and a caller-supplied `decode`; it never
  throws (the decode call is try/caught → `bad_output`, so the guarantee is unconditional) and
  returns either the decoded payload or a typed failure (`errorType` + message).
- `ExecHost` uses the SDK's `ExecOptions`/`ExecResult` types via **type-only import** — method-
  parameter bivariance keeps the structural slice satisfiable by `ExtensionAPI`. The compile-time
  drift checks (`const _h: ExecHost = {} as ExtensionAPI`) live in the **test file**, so divergence
  fails `tsc`.
- `activeRunId` is exported deliberately so tests assert the `cold-door-<ts>` stamp fallback and the
  workflow-state read directly.

## The decode policy split (the reusable pattern)

The crisp criterion: **anything the warm door appends into workflow-state must be fully strict** —
a half-formed `plan_ref` poisons `planRefsEqual` and every downstream consumer, so any miss is
`bad_output`. **Render-only sub-objects are advisory** — validated, dropped on malformation — the
mutation already succeeded, so the success report must survive. Three arms, chosen per payload
field:

- **Strict on the core payload:** malformed → decode returns `null` → the client reports
  `bad_output` with "`<label>` reported success but returned an unexpected payload — the perk CLI
  and the perk extension may be version-skewed (update/rebase so both planes match)". Use this arm for anything the
  success message/marker logic **dereferences** or persists. Reference: `decodePlanRef`.
- **Advisory sub-objects are validated-but-dropped:** malformed → the field becomes `undefined` and
  the success report survives. Use this arm for report-only extras whose underlying mutation already
  succeeded (e.g. land's `objective`/`learn` sub-reports). Reference: `decodeObjectiveNode`.
- **Fully lenient when *every* payload field is advisory display detail:** the decode defaults each
  field (`?? false`) and never returns null — the `bad_output` arm is deliberately unreachable for
  that door and needs **no decode-edge tests** (they can't fail). References: the objectivePlan
  decode and `extension/learn.ts` (`decodeLearnCapture` — `learn_issue` is render-only and the
  capture mutation precedes the decode, so a success envelope must survive an undecodable
  sub-object; the post-#387 cold/warm skew lesson).

A dropped advisory field must also **short-circuit any follow-up drive** — land's reconcile drive
skips when `objective` is `undefined` (pinned by test). Don't let a downstream drive dereference an
advisory field the decode dropped.

## The fail-arm payload narrowing pattern

`runColdDoor` attaches the parsed `success:false` envelope as `payload` **only** on the two
envelope-bearing fail arms (non-zero-exit-with-envelope, exit-0 `success:false`) — never on
exec-throw / scratch-failure / unparseable / `bad_output`. A door that renders partial-failure
detail (e.g. a partial batch table) re-narrows that payload with the **same decode it uses for
success**, and re-derives its own fail-arm defaults from the payload — the client's generic
defaults (`github_error`/`exec_failed`) differ from per-door legacy contracts. Uncertainty ⇒ drop
the partial detail and plain-fail — **never render a half table**.

## Compose the exported narrowing helpers

`extension/coldDoor.ts` exports `stringField` / `numberField` / `booleanField` / `objectField` (the
latter rejects arrays and null). Door decodes should compose these, not re-implement `typeof`
checks; they're unit-covered in `coldDoor.test.ts`, so new decodes only need door-level tests.

- TS **inferred type predicates** handle element-checked arrays:
  `Array.isArray(x) && x.every((n) => typeof n === "string")` narrows `unknown` to `string[]` under
  the repo's tsc — no explicit `is` predicate needed.
- `string | null` contract fields need a **three-way narrow** (string / null / wrong-typed): the
  helper's `undefined` is ambiguous with an absent key, so pair it with an explicit
  `obj.key !== undefined` presence check when wrong-typed must reject the sub-object. The
  nullable-string accessor started as a deliberate local duplicate in two doors (don't export
  door-internal helpers across doors) and was promoted into the substrate as `nullableStringField`
  when a third door needed it — the **rule of three for door-helper hoisting**: two copies are a
  decision, a third need hoists into `coldDoor.ts` next to the exported helpers.

## Pre-flight guards stay OUTSIDE the substrate

Input-shape checks, completion-audit gates, and argv-builder null checks run **before**
`runColdDoor` because they must never exec. The substrate owns only the delegation seam, not
door-specific policy. (The tool *boundary* above the door uses a different, tri-state strict-fail
decode policy — see `pi/tool-param-decode.md`; never reuse the cold-door lenient helpers there.)

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

## Stdin-channel gotchas

- **Doors trim input before staging** — the staged run-scratch file lacks the source's trailing
  newline. Staging tests must assert against the *trimmed* source content.
- **The stdin flag lands at the END of argv** (`runColdDoor` appends `[flag, path]` after the
  caller's argv). Write argv assertions by flag *adjacency* (`argv[argv.indexOf(flag) + 1]`) or
  order-independent regex — never positionally.
- The staging assertion shape: read the fake-perk argv file, take the value after the flag, assert
  it contains the `.pi/workflow/scratch/runs/<runId>` path, then read the staged file back.

## Migration test rituals

- **Exactly one envelope-flip per migrated door:** a `success:false` envelope at non-zero exit
  previously asserted `exec_failed` + stderr-tail and now asserts the structured
  `error_type`/`message`. Expect one such test rename/flip per migration.
- **One sibling-standard envelope-aware regression per tool**, modeled on
  `extension/submit.test.ts`.
- **Strictening a formerly-unchecked `JSON.parse … as X` requires grepping the whole tree** for
  every fake/route emitting that door's payload — door test files, `fakePerkRouter` routes, and
  e2e scenarios (e.g. `extension/workerE2e.test.ts`) — and bringing fixtures up to full contract
  shape. **Fix the fixture, never loosen the decode** (the real cold door always emits the full
  shape).
- **`assert.deepEqual` pins on a discriminated-union arm are shape-exhaustive:** adding an optional
  field to the arm (e.g. `payload` on the fail arm) is an assertion change wherever the arm is
  pinned exactly.

## Testing notes

- Permission-based fs-failure tests (chmod a dir read-only to force a mkdir failure) need a
  `process.platform === "win32" || process.getuid?.() === 0` skip guard — root and Windows ignore
  the read-only bit.

## Cross-references

- `extension/coldDoor.ts` — `runColdDoor`, the narrowing helpers (incl. `nullableStringField`),
  `activeRunId`
- `extension/coldDoor.test.ts` — the client mechanics pins + the compile-time `ExecHost` drift check
- `extension/land.ts` — the advisory-drop + three-way-narrow exemplar
- `extension/address.ts` — the fail-arm payload re-narrowing exemplar
- `docs/learned/workflow/warm-door-commands.md` — a warm door must render every cold-door outcome;
  this client is the mechanism
- `docs/learned/pi/tool-param-decode.md` — the tool boundary's tri-state strict-fail decode (a
  deliberately separate policy; never share helpers across the two boundaries)
