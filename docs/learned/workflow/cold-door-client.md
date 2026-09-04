---
title: The runColdDoor envelope-aware client — decode policy, narrowing helpers, door migrations
read_when: You are adding a warm door that shells to a `--json` cold door, writing or strictening a cold-door envelope decode, consuming a fail-arm payload, or hardening a door against cold/warm version skew.
cluster: doors-and-launch
---

# The cold-door client (`runColdDoor`)

`extension/substrate/coldDoor.ts` is the one envelope-aware client for running a cold Python door from the
extension: it execs the door, parses the JSON envelope, and returns typed success/failure —
replacing the per-door exec/parse copies. This doc captures the decode policy split, the exported
narrowing helpers, and the migration playbook that keeps door tests green.

## Distillation

- The substrate is MANDATORY: every warm door shelling to a `--json` cold door consumes
  `runColdDoor` — hand-rolled exec/parse is a regression (guard-enforced:
  `coldDoorGuard.test.ts`) — "Rollout COMPLETE — the substrate is mandatory".
- Decode strictness is a policy SPLIT by tier (which fields strict-fail vs default) — "The
  decode policy split (the reusable pattern)".
- The parsed `success:false` envelope rides `payload` only on the two envelope-bearing fail
  arms; re-narrow it with the SAME decode as success, and on uncertainty drop partial detail —
  never render a half table — "The fail-arm payload narrowing pattern".
- Pre-flight guards (input shape, gates, argv null checks) run BEFORE `runColdDoor` — the
  substrate owns delegation, not door policy — "Pre-flight guards stay OUTSIDE the substrate".
- Envelope edge semantics (exit/parse/scratch arms) — "Envelope edge semantics"; the legacy
  `label` reproduces pre-migration fallback texts byte-exactly during migrations — "Label choice
  is the byte-compat lever".

## Rollout COMPLETE — the substrate is mandatory

Every warm door that shells to a Python `--json` cold door delegates through `runColdDoor`,
enforced by the source-scan guard `extension/coldDoorGuard.test.ts` (no `PERK_BIN` reference and
no perk exec outside `substrate/coldDoor.ts`). The live consumer census is **derived, never
listed** — grep `runColdDoor` imports under `extension/pi/v1/` (this
census froze once at "nine" and drifted). No per-door `activeRunId` copies remain (the stamp
fallback is uniformly `cold-door-<ts>`). **A new warm door that shells to a Python `--json` cold
door MUST consume the substrate — hand-rolled exec/parse is a regression, not a style choice.**

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
mutation already succeeded, so the success report must survive. Four arms, chosen per payload
field:

- **Strict on the core payload:** malformed → decode returns `null` → the client reports
  `bad_output` with "`<label>` reported success but returned an unexpected payload — the perk CLI
  and the perk extension may be version-skewed (update/rebase so both planes match)". Use this arm for anything the
  success message/marker logic **dereferences** or persists. Reference: `decodePlanRef`.
  (`decodePlanSave` is the reference example for the criterion: strict **iff** appended to
  workflow-state — it is strict only on `plan_ref`.)
- **Advisory sub-objects are validated-but-dropped:** malformed → the field becomes `undefined` and
  the success report survives. Use this arm for report-only extras whose underlying mutation already
  succeeded (e.g. land's `objective`/`learn` sub-reports). Reference: `decodeObjectiveNode`.
- **Fully lenient when *every* payload field is advisory display detail:** the decode defaults each
  field (`?? false`) and never returns null — the `bad_output` arm is deliberately unreachable for
  that door and needs **no decode-edge tests** (they can't fail). References: the objectivePlan
  decode and `extension/pi/v1/learning/learn.ts` (`decodeLearnCapture` — `learn_issue` is render-only and the
  capture mutation precedes the decode, so a success envelope must survive an undecodable
  sub-object — `learn_issue?` is optional, never null, and `bad_output` is unreachable for that
  door; the post-#387 cold/warm skew lesson).
- **Derive-don't-decode (the strongest tier):** when a payload field is render-only AND
  redundant with a strict field (constructed from the same source in the cold door), **derive it
  from the strict field** instead of decoding it independently — the field's shape becomes
  *unrepresentable as a failure mode*, stronger than lenient decoding (which still parses the field
  and merely tolerates absence). Realized twice: `decodePlanSave` (strict only on `plan_ref`;
  the rendered `issue.id`/`url` derived from the ref — byte-identical by construction in the cold
  door, which builds the ref from the issue; `existed` advisory via `booleanField`) and the learn
  door.

**The `bad_output` reachability acceptance test.** The doctrine's intended end-state for a door's
decode: `bad_output` is reachable **only** for a payload whose persistence would corrupt
workflow-state. When auditing other doors' decodes, use that as the acceptance criterion.

**A new parity-only field on a STRICT cross-plane decoder must be LENIENT.** TS `decodePlanRef`
rejects on `objective_id === undefined` (strict) but treats the newer `base` **leniently**
(`nullableStringField` → present null/string carried; absent/mistyped → `undefined`, never a decode
failure). Two reasons it MUST be lenient: (1) `planRefsEqual`/dedup compares only `provider`+`pr_id`,
so a malformed `base` can't poison anything; (2) a strict `base === undefined` guard would reject
**legacy pre-`base` plan-refs** that lack the field (and hand-written fixtures lack it too). **Rule:
adding a parity-only field to an existing strict cross-plane decoder requires lenient handling
whenever any pre-existing payload could lack the field.**

**Plan-internal inconsistency rule:** when a plan's test expectation contradicts its own
implementation spec (the `existed === false` vs `null` resolution — a legacy fixture that *is* a
decodable object with a valid boolean), implement the **specified mechanism** and split the
assertions to cover both arms.

A dropped advisory field must also **short-circuit any follow-up drive** — land's reconcile drive
skips when `objective` is `undefined` (pinned by test). Don't let a downstream drive dereference an
advisory field the decode dropped.

## Version skew between the planes

**Cross-plane skew is structural for the dev flow.** Warm doors exec bare `perk` from PATH (a
uv-tool editable install → an arbitrary dev worktree) while the session loaded the extension at
start; no operational guard exists (a doctor skew check / launch-time `PERK_BIN` pinning were
explicitly deferred). The landed mitigation tier is **per-door decode hardening** — strict decodes
still hard-fail under skew, they just say so honestly.

**The skew-naming reword:** `runColdDoor`'s decode-null message names version skew ("the perk CLI
and the perk extension may be version-skewed"), and the `unexpected payload` substring was
deliberately preserved so the door-test `/unexpected payload/` regexes needed zero edits. **The
substring-preserving reword is the general lever for hardening shared error text** without
assertion churn.

## The fail-arm payload narrowing pattern

`runColdDoor` attaches the parsed `success:false` envelope as `payload` **only** on the two
envelope-bearing fail arms (non-zero-exit-with-envelope, exit-0 `success:false`) — never on
exec-throw / scratch-failure / unparseable / `bad_output`. A door that renders partial-failure
detail (e.g. a partial batch table) re-narrows that payload with the **same decode it uses for
success**, and re-derives its own fail-arm defaults from the payload — the client's generic
defaults (`github_error`/`exec_failed`) differ from per-door legacy contracts. Uncertainty ⇒ drop
the partial detail and plain-fail — **never render a half table**.

## Compose the exported narrowing helpers

`extension/substrate/coldDoor.ts` exports `stringField` / `numberField` / `booleanField` / `objectField` (the
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
  it contains the `.perk/workflow/scratch/runs/<runId>` path, then read the staged file back.

## Migration test rituals

- **Exactly one envelope-flip per migrated door:** a `success:false` envelope at non-zero exit
  previously asserted `exec_failed` + stderr-tail and now asserts the structured
  `error_type`/`message`. Expect one such test rename/flip per migration.
- **One sibling-standard envelope-aware regression per tool**, modeled on
  `extension/pi/v1/delivery/submit.test.ts`.
- **Strictening a formerly-unchecked `JSON.parse … as X` requires grepping the whole tree** for
  every fake/route emitting that door's payload — door test files, `fakePerkRouter` routes, and
  e2e scenarios (e.g. `extension/worker/stageExecutionE2e.test.ts`) — and bringing fixtures up to full contract
  shape. **Fix the fixture, never loosen the decode** (the real cold door always emits the full
  shape).
- **The merge-race fixture sweep.** Semantically-green-per-PR ≠ green-after-merge when two
  in-flight PRs share a contract shape (one adds consumers of a shape, the other renames its
  fields): git merges cleanly (no textual conflict), each branch's CI is green, merged main is red
  (the #386/#387 `issue: { number }`→`id` race, which then recurred as a delete/edit rebase
  conflict in #396). **After ANY cross-plane shape change lands, grep ALL test fixtures repo-wide
  for the legacy field name** — never trust the changing PR's own sweep; in-flight branches
  re-introduce the old shape. No CI guard for this class exists (merge queue / post-merge main CI
  both absent).
- **`assert.deepEqual` pins on a discriminated-union arm are shape-exhaustive:** adding an optional
  field to the arm (e.g. `payload` on the fail arm) is an assertion change wherever the arm is
  pinned exactly.

## Testing notes

- Permission-based fs-failure tests (chmod a dir read-only to force a mkdir failure) need a
  `process.platform === "win32" || process.getuid?.() === 0` skip guard — root and Windows ignore
  the read-only bit.

## The parent-posts warm tool (post_pr_review)

The reusable recipe for a warm tool where the **parent** posts a durable GitHub mutation by
delegating to an existing cold door:

- A **strict `decode*Params`** that refuses the **whole batch** — ANY malformed field ⇒ `null` —
  *because posting is a durable GitHub mutation* (mirrors `decodeResolveParams`). Each new tool's
  decode tends to grow its **own** row/array validators (the `/pr-review` one needed local
  `decodeComments`/`decodeStringArray` rather than reusing address's `decodeCounts` — different
  shapes).
- A `postX(pi, ctx, params)` that builds the exact `--batch` shape, calls
  `runColdDoor([..., "--json"], {stdin:{flag:"--batch", content, filename}, decode})`, returns a
  **soft** `Result` (`failFor`/`ok`, never throws), and on success does a **best-effort**
  `appendWorkflowState` **with strict read-back**. `execute` decodes → `bad_input` on `null`, else
  delegates.
- **The existing cold door is reused unchanged** — `perk pr review-post --batch <file>` was already
  `runColdDoor`-stdin-compatible (same as `resolve-threads`); **no Python changes were needed at
  all**. When reshaping a posting boundary, check whether the cold door already speaks `--batch`
  before adding a Python surface.
- **A new workflow-state field needs no rebuild change.** Adding `last_pr_review?: unknown` to
  `WorkflowState` required only the interface field — `rebuildWorkflowState`'s per-field LWW handles
  any new key automatically (same as `conflict_resolution_attempts`). Recorded
  `{pr, verdict, angles, comment_count, mode, at}`, best-effort/non-fatal.

## Cross-references

- `extension/substrate/coldDoor.ts` — `runColdDoor`, the narrowing helpers (incl. `nullableStringField`),
  `activeRunId`
- `extension/substrate/coldDoor.test.ts` — the client mechanics pins + the compile-time `ExecHost` drift check
- `extension/coldDoorGuard.test.ts` — the mandatory-delegation source-scan guard
- `extension/pi/v1/delivery/land.ts` — the advisory-drop + three-way-narrow exemplar
- `extension/pi/v1/plan.ts` — `decodePlanSave`, the derive-don't-decode exemplar
- `extension/pi/v1/delivery/address.ts` — the fail-arm payload re-narrowing exemplar
- `docs/learned/workflow/warm-door-commands.md` — a warm door must render every cold-door outcome;
  this client is the mechanism
- `docs/learned/pi/tool-param-decode.md` — the tool boundary's tri-state strict-fail decode (a
  deliberately separate policy; never share helpers across the two boundaries)
- `docs/learned/workflow/plan-ref-lifecycle.md` — the non-default `base` field whose parity-only
  lenient decode this doc references
