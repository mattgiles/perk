---
title: Pydantic boundary↔domain conversion (Pydantic at the edges, frozen `@dataclass` domain)
read_when: Converting a config/registry/objective/cache or external-API boundary onto the lenient-parse-model → frozen-`@dataclass` → `validate()` pattern, or pinning a `--json` envelope onto `OutputModel`.
---

# Pydantic boundary↔domain conversion

This **supersedes** the earlier "strict Pydantic model AS the frozen domain" philosophy this doc once
documented. The boundary↔domain reshape inverts it: **Pydantic lives ONLY at the parse/serialize
edge; the domain object is a frozen `@dataclass`** that imports no pydantic. A lenient parse model
reads the untrusted edge, an explicit converter copies into the frozen dataclass, and the existing
`validate() -> list[Issue]` content pass is unchanged. Nothing internal depends on pydantic.

If you are reading the old framing anywhere (a node's roadmap prose, a stale comment): the model is
**not** the domain, "the model IS the tolerant parser" `@model_validator(mode="before")` relocation
is **removed**, the context-gated set-level validator is **removed**, and frozen mutation now raises
`dataclasses.FrozenInstanceError` (not `pydantic.ValidationError`) — and ty statically flags the
mutation line.

## The three role-named bases in `perk/boundary.py`

`perk/boundary.py` exports three **role-named** bases plus the kept legacy `StrictBoundaryModel`. The
canonical recipe lives as an executable **reference test** in `tests/test_boundary.py` (a throwaway
`LenientParseModel` → `_to_X` converter → frozen `@dataclass` → `_validate -> list[str]` content
pass) — mirror that test's shape, not reproduced code here:

- **`LenientParseModel`** — `frozen=True, extra="ignore", strict=False, populate_by_name=True`. The
  read boundary for **perk's own stored files AND external API responses** (the role broadened from
  the old `LenientApiModel`, which it renames — no deprecated alias kept). `extra="ignore"` drops
  sibling keys natively; lax coercion tolerates `"true"`/`1` → `True` and a YAML list → tuple. It has
  **no `str ← int/bool/None` coercion row**, so a bad-typed field still raises — the malformed-edge
  message contract survives.
- **`StrictInputModel`** — `frozen=True, extra="forbid", strict=True`. **Config-identical to**
  `StrictBoundaryModel`; the differentiation is role-naming for machine-authored CLI batch inputs
  where a typo must fail loudly.
- **`OutputModel`** — `frozen=True, extra="forbid"` (no `strict` — coercion is irrelevant because it
  is built from trusted domain values). For `--json` snapshots and stored-block serialization dumped
  via `model_dump(mode="json")`.
- **`StrictBoundaryModel`** — KEPT (docstring re-marked legacy/transitional), plus the `StrTuple`
  coercion type and the `format_validation_error` / `translate_validation_errors` / `ValidationError`
  re-exports.

## The canonical per-model recipe

Every per-model conversion follows the same seam (registry, bindings, providers, objective metadata,
cache all mirror it):

1. A lenient `*File` / `*Entry` / `*Model` parse model (on `LenientParseModel`, via
   `Model.model_validate(raw)`) at the **read** boundary.
2. An **explicit field-by-field** `_to_X()` / `to_domain()` converter into the frozen `@dataclass`
   domain object — collections become `tuple` / `frozenset`, and the domain object carries its own
   methods.
3. The existing `validate() -> list[Issue]` content pass, unchanged.

This deletes the old `_tolerate` `@model_validator(mode="before")` collapses and the
`StrTuple`/`BeforeValidator` strict shims; the lenient base does natively what those shims did under
strict.

## Mirroring a template copies its latent bugs — and the template keeps them

When a plan says "mirror module X symbol-for-symbol", budget a review pass on X's *own* contract
adherence: the mirror inherits X's defects, and review may fix only the copy. The shipped
instance: the expectations loader mirrored `src/perk/substrate/bindings.py` and inherited its
bare-`yaml.safe_load` leak (a malformed file escaped the documented domain-error contract as
`yaml.YAMLError`) and its loose `schema_version` equality gate (YAML `true`/`1.0` pass `!=`
against an int — Python bool/float equality). Review fixed the copy only; the loader family was
later aligned to the fixed shape in
`packages/perk-dev/src/perk_dev/audit/expectations.py::load_catalog` (wrapped parse re-raising
the domain error with the path + `from exc`; a genuine-`int` gate explicitly rejecting `bool`).

## Loader/validator test-shape refinements

- **Message-fragment assertions under-pin `Issue` findings.** One-defect fixtures asserted via
  concatenated `message` fragments never verify `Issue.where` or that `validate()` *accumulates*
  independent findings — a regression returning only the first issue, or mis-addressing every
  issue, stays green. Add one multi-defect fixture asserted as exact
  `(severity, where, message)` tuples, covering both the generic location and the entry-id
  location.
- **Pin the loader's field-for-field conversion with full domain equality.** When `validate()` is
  mostly non-empty checks, swapped/miswired `to_domain()` assignments are invisible to every
  negative test. One success-path assertion comparing a loaded entry against a fully populated
  expected frozen dataclass (plus pinning the schema version) closes that hole.

## On a read whose absence has semantic weight, a model default is a fail-open bug

Require the field in the lenient parse model. The shipped instance (the stacks preview read): a
pagination flag whose absence would silently claim non-truncation — defaulting it manufactures
evidence the payload never carried. If the field can legitimately be absent, absence must degrade
or raise, never default into a positive claim (see `objective-delivery.md`'s stable/preview query
split).

## The boundary-DIRECTION decision (the big recurring correction)

Whether a model is a `LenientParseModel` (**read-into-the-type**) or an `OutputModel`
(**serialize-only**) is decided by **whether a real read-into-the-type consumer exists** — not by the
roadmap's framing. Two arc nodes (Config; PlanHeader/PlanRef) had roadmap prose asserting a "lenient
parse model at the boundary" that the code disproved: the stored block was read back as a raw
`dict`, never re-parsed into the type. **When no read consumer exists, realize the boundary as an
`OutputModel` with an explicit `from_domain`, and do NOT author a read-parser with no consumer**
("don't author fiction for unbuilt components"). The planner's "Correction to the node framing
(verified against the code)" section is doing real work — **trust the code over the roadmap prose.**

## Applying the lenient-parse pattern to API gateway response shapes

The boundary-inversion recipe applies unchanged to **external API response shapes** (GitHub `gh`
JSON, Linear GraphQL nodes) — not just perk's own stored files. Point at `perk/github/` and
`perk/backends/linear/_helpers.py` for the concrete models. The gateway-specific mechanics:

- **Validate at the CALL SITE, not inside the converter.** The hand-rolled converters
  (`_pull_request` / `_parse_review_threads` / `_parse_reviews` / the issue + workflow-run reads)
  keep their names + signatures so call sites are untouched; only their **bodies** become
  `Model.model_validate(raw).to_domain()`. Wrap `translate_validation_errors(<ErrorType>,
  source=<operation label>)` at each **call site** so the resulting error carries *that site's*
  operation label (`"create PR"`, `"read PR #42"`, `"read plan issue …"`). This is the clean way to
  give one shared converter a per-call-site error label without threading the label into the
  converter. **Wrap ONLY `model_validate`, never the downstream domain work** — the subsequent
  PR-resolve / domain step already raises the gateway error type and must stay *outside* the block so
  it isn't relabelled with the parse source.
- **Prefer `Field(validation_alias=AliasChoices(...))` over `Field(alias=...)` for response models.**
  `AliasChoices` lets **one model serve two wire shapes** — e.g. `WorkflowRunModel.id` reads
  `AliasChoices("databaseId", "id")` and `url` reads `AliasChoices("url", "html_url")`, unifying the
  camelCase `gh run view` producer AND the snake_case REST trigger-discovery producer into one
  model. The lenient base already sets `populate_by_name=True`.
- **Widen a converter param to `object` when you delete its `isinstance(data, dict)` narrowing
  guard.** Replacing the guard with `model_validate` removes the narrowing, and the subprocess JSON
  helpers (`_run_json` / `_graphql`) return `Any | None`; `model_validate` accepts `Any`/`object`, so
  retype the converter param `object`. (This incidentally lets `from typing import Any` be dropped
  where it was only there for the old `dict[str, Any]` param.)
- **Edge-sharpening posture (byte-identical happy path, cleaner error TYPE only).** The identity
  field is required (`number` / `id` / `identifier` / thread id); every non-identity field keeps a
  default, so happy-path output is unchanged. The only observable change is a *present-but-malformed*
  payload now raising a labelled error instead of a raw `KeyError`/`ValueError`. **Lookup-miss guards
  run BEFORE validation** (a soft `"databaseId" not in data → None` / `none_on_not_found → None` stays
  ahead of `model_validate`) so sharpening converts only a malformed payload into a raise, never a
  legitimate lookup miss. Deliberately-tolerant non-identity fields stay defaulted (e.g.
  `ReviewCommentModel.comment_id: int | None` — `databaseId` is documented absent on some nodes and
  is not the thread's identity).
- **Nested-children composition.** Validate child nodes separately and inject them via a
  keyword-only `to_domain(*, comments=...)` rather than the parent model owning the nested list
  (review threads build `comments = tuple(ReviewCommentModel.model_validate(c).to_domain() …)` then
  `ReviewThreadModel.model_validate(node).to_domain(comments=comments)`).
- **One boundary shape fanning out to differently-shaped domain objects ⇒ NO single `to_domain()`.**
  GitHub's `IssueReadModel` is 1-shape→1-domain → a single `to_domain()`. But Linear's recurring
  selection `id identifier url title description state{type}` feeds **two** domain objects
  (`PlanState` via `get_plan` AND `AdoptableIssue` via `read_issue`), so the model exposes
  **validated field accessors + a small normalizer** (`normalized_state()`) and each call site
  assembles its own domain object — the same posture as GitHub's `to_domain(*, comments=...)` /
  `_normalized_state()` split. **Decision rule:** 1-shape→1-domain gets a single `to_domain()`;
  1-shape→N-domains gets accessors + normalizers.
- **Fold a shared helper into a model only after grep-confirming single-package use** (`_pr_state` →
  `PullRequestModel._normalized_state()`, `_login` → a nested `_Actor(LenientParseModel)`); retain
  generic connection-walk plumbing (`_pr_node` / `_nodes` GraphQL `{nodes:[…]}` unwrapping — it has
  no nameable boundary). **Substrate-home rule:** the domain payload-shape model lives in the package
  leaf (`perk/backends/linear/_helpers.py`), not the generic client module that keeps the low-level
  `_opt_*`/`_require_*` helpers.

This is a Python-internal tightening with a byte-identical happy path, so per this doc's cross-plane
posture it touches **neither `shared/contracts.md` nor `docs/user-docs/`**.

## Explicit field copy over `**model_dump()` (the settled "1:1 no-op" objection)

When the parse model and the domain dataclass have the identical fields, the hand-rolled field-by-field
copy looks like a crazy no-op. The owner-settled rationale to keep the explicit split:

- It keeps pydantic types **out of the domain** (dignified-pydantic rule 1).
- It is NOT purely a no-op — it is where `set → frozenset`, `list → tuple`, frozen-mutation becomes
  `FrozenInstanceError`, and the domain's own methods attach.
- Template consistency: several siblings (providers, objective) are NOT 1:1, so a uniform
  parse→frozen-dataclass seam pays off; the 1:1 cases eat the boilerplate for that consistency.
- Prefer it over `X(**entry.model_dump())`: `model_dump()` is `dict[str, Any]`, so a `**`-spread
  type-checks as `Any` and **loses per-field ty checking** (dignified-pydantic §38). Explicit is the
  ty-safe form.

## `from_domain` + TWO decoupled field orderings

The serialize-only `OutputModel` (e.g. `PlanHeaderOut`/`PlanRefOut`) carries an explicit
`from_domain(cls, x) -> Out` that maps every field (no `**dataclasses.asdict`). Two **separate**
orderings, each with its own constraint:

- **Domain dataclass field order is FREE** — declared required-first to obey "no required field after
  a defaulted field"; it does not control serialization.
- **The `OutputModel` field-declaration order IS load-bearing** — `model_dump(mode="json")` emits in
  declaration order → `render_metadata_block` renders verbatim → must match the prior emission order
  byte-for-byte. Pydantic v2 permits a required field **after** defaulted fields, so the `OutputModel`
  keeps the exact legacy emission order even when the dataclass can't. **The load-bearing comment
  moves onto the `OutputModel`,** not the dataclass.

A **serialize-only header** (`ObjectiveHeader`, plan-header) needs **no read model at all** — only an
explicit `render_*_block(header) -> dict` builder. Byte-identity holds because all fields are flat
scalars: `model_dump(mode="json")` emits them in declaration order with no JSON transform, so a
hand-written dict in the same declaration order is byte-for-byte identical. Node-mutation sites revert
`model_copy(update=...)` → `dataclasses.replace`.

## The `.model_dump()` blast radius — the recurring undercount + the ty oracle

Converting a Pydantic model → dataclass **removes `.model_dump()`**, so EVERY `<Type>.model_dump()`
call site breaks — including test files / fixtures with inline `Type(...).model_dump()`. A
writer-signature flip (`write_plan_ref(dict)` → `write_plan_ref(PlanRef)`) ALSO breaks dict-literal
call sites with **no type name to grep**. The plan's enumerated test-file list **undercounts** every
time (one node listed 11, actual ~20). **Whole-tree `ty check tests perk` is the completeness
oracle** — it flags every `unresolved-attribute … has no attribute model_dump` at once; grep does
not. The mechanical fixes for the ripple:

- module-level `_REF = {...}` dict consumed only by the writer → a `PlanRef(...)` dataclass;
- `{**_REF, "base": "develop"}` spread → `dataclasses.replace(_REF, base="develop")`;
- where a test still needs the dict (a dry-run `--json` assertion), keep a separate
  `_PLAN_REF_JSON = PlanRefOut.from_domain(_PLAN_REF).model_dump(mode="json")`;
- a shared override helper → `PlanRefModel.model_validate({**_REF, **over}).to_domain()`.

The `--json` / dry-run output paths **can't `model_dump` a dataclass** → wrap as
`XOut.from_domain(ref).model_dump(mode="json")`. The **runner Protocol boundary stays dict-typed**, so
the caller keeps `plan_ref_data = PlanRefOut.from_domain(...).model_dump(...)` as the dict it passes.

## The ty `invalid-assignment` frozen-mutation gotcha (EVERY node hits it)

A frozen `@dataclass` field is **statically read-only**, so ty flags `obj.field = x` as
`invalid-assignment` (`Property '…' is read-only`) — even though ty does NOT flag the equivalent
assignment on a frozen Pydantic model (it treats the model's fields as settable). So a frozen-mutation
negative test, flipped from `pytest.raises(ValidationError)` → `pytest.raises(FrozenInstanceError)`,
also needs **`# ty: ignore[invalid-assignment]` on each mutating line** (mypy-style `# type: ignore`
does NOT suppress ty — see `toolchain/ty.md`). Whole-tree `typecheck-py` is the gate that catches it;
the per-model pytest suite stays green without it. **Don't trust a plan that says "no suppression
needed"** — node 1.4 explicitly disproved its own plan's "runtime-only, no ty suppression" claim.

## `str = ""` vs `str | None = None` on a parse field

When a parse field has a test feeding YAML `null` (`id:`) AND the domain wants a non-optional `str`:
type the parse field **`str | None = None`** and normalize `None → ""` in the converter
(`id=entry.id or ""`). `LenientParseModel` (strict=False) given `None` for a `str` field still
**raises** — there is no `None → str` coercion row — which would wrongly turn a missing-id *content
Issue* into a structural raise. `str = ""` is safe **only** when there is no `id: null` test (e.g.
registry's `StageEntry.id: str = ""`).

## One lenient parse model, two read consumers

A single `*Entry(LenientParseModel)` + `to_domain()` can back two read paths at once (objective's
`ObjectiveNodeEntry` backs both the roadmap-block and the manifest-block paths). `extra="ignore"`
drops the keys each path doesn't want (the manifest path injects `status=PENDING.value` then lets
`extra="ignore"` drop `pr`) — exactly what the deleted `_tolerate` used to do. Bad-type field-path
errors still raise (no `str ← int` row preserves the malformed-edge message contract).

## Invariant relocation + the removed context-gated dance

The providers "exactly-one-`default:true`-per-seam" invariant moved **OUT of** the context-gated
`@model_validator(mode="after")` + `model_dump()`-then-revalidate dance and **INTO** `validate()` as
a direct extend. The finding's core text is byte-identical, but it now surfaces as **one Issue per
violating seam WITHOUT pydantic's `"Value error, "` prefix** (both were artifacts of the removed
dance); existing substring assertions still pass. The **whole context-gated machinery is GONE** under
the inversion — set-level invariants live in `validate()`, not in a model validator.

## Config degrades to lenient-parse → frozen-dataclass (no `validate()` step)

Config has no content `validate()` pass, so the pattern degrades to **lenient-parse → frozen
dataclass** (`ConfigFileModel(LenientParseModel)` — the reshaped successor of the old `ConfigModel`
— built then converted to a frozen `@dataclass Config`):

- `ConfigFileModel` validates the **raw merged TOML** — an uncontrolled boundary — so `load_config`
  **does** wrap `model_validate` in `translate_validation_errors(ConfigError, ...)`. The rationale
  survives unchanged (translate only at **uncontrolled** boundaries), but the polarity flipped: the
  old "do not wrap" directive was correct only while the model re-validated code-controlled,
  already-`_parse_*`-typed values.
- `user_bindings` is **no longer a model field**: bindings keep their loud-but-non-fatal
  `parse_user_bindings` seam and are passed as a method param to
  `ConfigFileModel.to_domain(repo_root, *, user_bindings=...)`. The never-`model_dump()` caveat
  (nested `Binding` instances corrupted by a recursive dict) therefore no longer applies to config
  — the converter still uses explicit attribute copy.

## Strict-input CLI-batch parsers (`StrictInputModel` / `RootModel`)

The lenient base reads untrusted edges; **machine-authored CLI batch inputs** (the `--batch` /
`--roadmap` JSON a sibling tool writes) go the other way — a typo must fail **loudly**. Converting
hand-rolled `isinstance` ladders onto `StrictInputModel` / `RootModel`:

- **`translate_validation_errors` CANNOT carry `error_type`** — it constructs `error_cls(message)`
  with a single arg. For a CLI error that needs `error_type="bad_batch"`, do NOT use the context
  manager: catch `ValidationError` directly and raise the
  `UserFacingCliError(format_validation_error(exc, source="batch"), error_type="bad_batch") from exc`
  yourself, reusing the exported `format_validation_error` field-path renderer. The pre-existing
  JSON-decode `try/except` stays a SEPARATE raise (a `JSONDecodeError` is not a `ValidationError`).
- **`RootModel` strictness must be restated.** Bare-list / bare-dict batch roots
  (`class X(RootModel[list[Item]])` / `RootModel[dict[str, object]]`) read `model.root`, but the
  `StrictInputModel` base config does NOT apply — `RootModel` subclasses `BaseModel` directly — so
  restate `model_config = ConfigDict(strict=True)` on the RootModel subclass so a non-array/non-object
  fails loudly.
- **Opt-in coercion fields under an otherwise-strict model.** A `StrEnum` field needs
  `Field(default=..., strict=False)` to keep value-based lookup (`"done" → NodeStatus.DONE`); a
  JSON-array→tuple field reuses the `StrTuple` `BeforeValidator`. These are the ONLY
  intentionally-coercing fields — everything else stays strict.
- **Per-parser error contracts diverge** (the inbox correction to the node's "same `bad_batch` for
  every parser" framing): **verify each command's existing error contract before assuming one shared
  class.** Only the two `pr` parsers raise `bad_batch`; the objective structured-roadmap path keeps
  its `(nodes, errors)` contract → `invalid_roadmap`; `state new-run` has no `--json`/machine surface
  → keeps a bare `UserFacingCliError` with no `error_type`.
- **Forking a shared lenient validator when ONE caller must go strict.** The structured `--roadmap`
  path must go strict while the shared `validate_roadmap` (also used by the stored-YAML read + manifest
  read) MUST stay lenient. **Inline the envelope handling** (schema-version / nodes-is-list /
  per-item-is-mapping + the absent/blank-`status`→pending pre-default) into the strict path and
  validate each node via a strict node model, leaving the shared lenient validator byte-unchanged.
  Don't parameterize the shared validator with a strict flag — copy the envelope logic. A side-map key
  (`adopt_issue`, consumed by `parse_adopt_mapping`) declared on the strict node model with a default
  keeps `extra="forbid"` from rejecting it, and is dropped in `to_domain` to keep the domain object
  pristine.
- **Intended behavior change (NOT byte-identical).** An unknown/ill-typed key on a strictened path
  now fails loudly with a field path (previously silently dropped) — aligning Python with the TS
  `ROADMAP_PARAM_SCHEMA` (`additionalProperties: false`) the agent path already enforced. This is the
  exception to the "byte-identical, no contract/doc touch" rule, *and* it still needs no contract
  change because it enforces an already-documented TS contract.
- **Gotchas.** Switching a hand-rolled `isinstance` check to a pydantic model **changes the
  user-facing error STRING** even when exit code/behavior is identical (`new-run`'s
  `"--handoff must be a JSON object."` → pydantic's `"--handoff: <root>: Input should be a valid
  dictionary"`) — after any such conversion, grep existing tests for the old message substring (a
  `new-run` test pinned the old text). A `Field(min_length=1)` is a deliberate relaxation vs an old
  `.strip()` check (whitespace-only now passes; empty/missing/wrong-type still fails). A cross-field
  rule (clean-verdict-has-no-comments) is a `@model_validator(mode="after")` raising `ValueError`
  (surfaces as `ValidationError`). Negative tests drive through `Model.model_validate({...})`, never
  typed kwargs.
- **A domain dataclass + gateway signature flip** (introduce a frozen request dataclass, e.g.
  `github.ResolveThreadRequest`, to replace a `list[dict]` batch item, then flip the gateway signature
  and drop the now-redundant `str(item["thread_id"])` coercions) is completeness-proven by **whole-tree
  `ty check tests perk`** — it catches every stale dict-literal call site grep would miss.

## OUTPUT-envelope golden-pinning (`OutputModel.from_domain(...).model_dump(mode="json")`)

Converting hand-rolled `--json` dict builders (init/doctor reports, plan save, the pr verbs, learn
capture) to `OutputModel.from_domain(...).model_dump(mode="json")` byte-identically:

- **The golden-snapshot harness as the byte-identity oracle (the durable win).** Establish a minimal
  snapshot harness (`tests/_golden.py` with a `GOLDEN_DIR` + an `assert_golden(name, actual)` that,
  under a `PERK_UPDATE_GOLDEN` env flag, **regens THEN still re-reads + asserts** so a
  non-roundtrippable regen still fails loudly); snapshots committed under `tests/golden/json/`.
- **"Pin FIRST" realized via an in-process oracle, not branch-vs-main file diffing.** Generate each
  envelope's golden from the **pre-swap committed builder** loaded with `git show HEAD:<path>` →
  `exec(compile(...), module.__dict__)`, call the OLD builder with a fixture **built from the CURRENT
  domain classes** (duck-typed — the old builder only does attribute access, so class identity is
  irrelevant), commit that golden, swap the builder, then re-run WITHOUT the flag — green IS the proof.
  A final `PERK_UPDATE_GOLDEN=1` regen producing **zero git diff** is the strongest confirmation.
  **Commit cadence matters:** commit each envelope's swap right after generating its golden so each
  golden's `HEAD:` oracle is genuinely the pre-swap version of THAT file.
- **Fixtures must populate optional fields + the nullable arms** that exercise the `None`-guard
  branches (the riskiest) — full + minimal variants, with/without the optional nested object
  (init full + `github`/`linear` None; plan_save with/without `objective_node`; learn real/dry-run).
- **Dict-field promotion as a dignified precondition for a precise published schema.** The
  no-`dict[str, object]`-holes rule forces promoting an in-scope `dict`-typed domain field to a frozen
  `@dataclass` (with its own nested `*Out`) BEFORE the swap (plan-save's
  `objective_node: dict[str, object] | None` → a frozen `ObjectiveNodeLink`); emitted JSON stays
  byte-identical (existing assertions + the golden confirm). Generalize: an OUTPUT envelope nesting a
  `dict` field → promote the dict to a domain dataclass + its own nested `*Out` first.
- **Nested-OutputModel discipline.** Each nested object gets its own named `*Out` whose `from_domain`
  picks the **EXACT legacy subset** (never a wholesale domain dump — the golden catches an
  extra/missing key); **reuse a sibling node's existing `*Out`** rather than re-wrapping
  (`model_dump(mode="json")` recurses through nested `OutputModel`s); field declaration order = legacy
  key order on every `*Out` (carry the existing `(order load-bearing)` docstring convention).
  **Map-not-copy** fields are handled in `from_domain` (not a domain rename, e.g.
  `ObjectiveLandOut.id` from domain `update.objective`); **computed-derived keys** (doctor `summary`,
  feedback `counts`) compute pure counts in `from_domain` (no domain field, no I/O).
- **Mechanics.** Whole-tree `ty check tests perk` is the completeness oracle (no `.model_dump()`
  blast-radius miss AND no `from_domain` relying on coercion); **removing a re-export-only helper is a
  3-site edit** (grep callers first, then drop from BOTH the import and `__all__`; adding the new
  `*Out` needs the reciprocal import + RUF022 isort-alphabetical `__all__` insert); E501 churn from
  the longer `Model.from_domain(...).model_dump(...)` one-liners (shorten docstrings, `ruff format`
  reflows — CI-green ≠ committed-format-green); consolidating all goldens + fixtures in one test
  module is a defensible structural simplification (placement doesn't affect the byte-identity proof).
  Pure Python-internal byte-identical output → touches neither contracts nor user-docs (a later
  schema-publish node owns the `model_json_schema()` + contract/doc amendments).

## Byte-identity discipline

The on-disk blob is the only durable contract, so the conversion must keep it byte-identical:

- `exclude_unset` is retained **ONLY** where the on-disk blob is intentionally minimal (the handoff
  cache). Elsewhere serialize the **FULL** domain dataclass — byte-identical **because production
  always wrote full shapes** (the partial-key shapes were test-only; confirm that premise first).
- A consume/mutate writer that previously did `model_copy(update=...)` + `exclude_unset` must **re-read
  the raw JSON through the Model directly** (the read path now returns a dataclass with no
  `model_copy`).
- Nested cache records recurse: `DispatchModel` nests `PlanRefModel` + `RunHandleModel`; `to_domain` /
  `from_domain` recurse. Open-ended keys ride an `extra: Mapping` field with `extra="allow"` (folded
  on `to_domain`, spread back on `from_domain`).
- A lenient read boundary is an **intended edge shift**: a malformed `consumed: 1` now coerces to
  `True` instead of raising (matches pre-pydantic behavior). Document the coerced read in the test.
- **Verification that works:** generate every blob from a scratch dir on the branch AND on a `main`
  checkout, then `diff` the captured outputs — proves byte-identity in one shot.

## Converter-idiom unification + the discipline guard

**Free `_to_X(entry)` functions → `to_domain()` methods on parse models.** The substrate
(`registry.py` / `providers.py` / `bindings.py` / `config.py`) was the last holdout using module-level
free converters + inline assembly inside `load_*`; unify onto the `to_domain()` / `from_domain()`
method idiom used everywhere else. Recipe + gotchas:

- A per-entry model gets `to_domain(self) -> "DomainClass"`; a whole-file model gets
  `to_domain(self, schema_version)` with `schema_version` as a **method param, not a model field**
  (it's a structural pre-check, never parsed).
- The **string forward-ref return annotation is mandatory** because the parse model precedes its
  domain dataclass in source order.
- The **collection type must match the domain field** (build a list where the domain field is a list,
  a tuple where it's a tuple — don't blindly tuple-ify).
- `ConfigFileModel.to_domain()` keeps the **explicit attribute-copy** (never
  `Config(**model.model_dump())`, which recursively dicts nested instances and corrupts them).
- Adding a *method* adds no field, so the schema-drift suite is unaffected — the unification is
  schema-invisible.

**`StrTuple` is redundant on LENIENT models, load-bearing only on STRICT.** On a `LenientParseModel`
(`strict=False`) a plain `tuple[str, ...]` field coerces a JSON list → tuple natively, so the
`BeforeValidator(list→tuple)` shim is pure redundancy (simplify it away). On a `StrictInputModel`
(`strict=True`) a plain tuple field **rejects** a JSON list, so the shim is load-bearing — keep it.
Byte-identity caveat: every stored blob/fixture carries JSON arrays which both forms turn into the
identical tuple; the only behavioral delta is on a malformed non-list input (absent from all
blobs/fixtures — verify before claiming byte-identity).

**The `StrictBoundaryModel` removal → the AST discipline guard.** The legacy strict-as-domain base had
zero production consumers (import-proven dead). The durable artifact is the new
`tests/test_boundary_discipline.py` — an AST source-scan guard (mirrors `test_paths_guard.py`):
`ast.walk` every module under the package, flag any `ClassDef` whose base is an `ast.Name` in
`{BaseModel, StrictBoundaryModel}`, allowlist `boundary.py` only (it legitimately defines the
role-named bases). `RootModel[...]` is an `ast.Subscript` (not flagged); role-named bases are
different names (not flagged). Pair vacuousness self-checks + a positive arm (`class X(BaseModel)` IS
flagged) + negative arms. A backstop-not-proof (matches written base names, not re-exported aliases) —
see `source-scan-guards.md`.

**contracts.md value-type drift after a behavior-neutral retype.** A cross-plane behavior-neutral
refactor still leaves prose drift in `shared/contracts.md` value-type blocks that name old class
identities (e.g. "`RunHandle` is a frozen Pydantic model" after it became a frozen `@dataclass` whose
JSON boundary is a `LenientParseModel`). **Grep the type names when a domain type is
renamed/retyped** and reconcile the value-type blocks.

## Publishing generated JSON Schemas as a committed contract

**A generated-artifact drift harness mirrors `tests/_golden.py`** (`tests/_schemas.py` is the 2nd
instance). The recipe for any "commit a generated artifact as a reviewable contract":

- An **ordered module-level registry tuple** = single source of truth for *what is published* (each
  entry: relative path + model + mode), from which both the per-item drift tests and the coverage
  test derive (never duplicate the list).
- `render()` = `json.dumps(..., indent=2) + "\n"` with **no `sort_keys`** (pydantic emits declaration
  order, matching `_golden.py`).
- `assert_*` does **regen-then-ALWAYS-reread-and-assert** gated on a **dedicated** env flag
  (`PERK_UPDATE_SCHEMAS`, kept separate from `PERK_UPDATE_GOLDEN`) so a regen producing garbage still
  fails loudly.
- The helper module has **no `test_` prefix** (so pytest doesn't collect it).
- Add a no-orphans/no-gaps coverage test (glob committed files vs registry, both directions) + a
  mode-correctness smoke.

**Per-category schema MODE is the load-bearing decision** (dignified-pydantic §32). A JSON Schema *is*
the external contract, so direction matters: parse/input models publish what perk **accepts** →
validation mode (the default); output envelopes publish what `--json` consumers **receive** →
serialization mode. Nested `*Out` / `*Entry` sub-models ride along in `$defs` automatically.

**`shared/` force-include bundles a new subdir into both planes for free.** `shared/` is force-included
wholesale into the wheel as `perk/_shared` and shipped in npm via the `shared/` files entry, so a new
`shared/schemas/` subdir bundles into **both** planes with zero packaging-config change — only a guard
assertion is needed (add one representative path to both the wheel and npm-pack packaging tests,
reusing the existing build-once `xdist_group`).

**The doc-amendment rule's deliberate exception for schema-publish nodes.** The "Python-internal
byte-identical refactor touches neither `contracts.md` nor `docs/user-docs/`" discipline governs the
byte-identical refactor nodes; a node that **defers** the schema-publish + contract/doc amendments
makes those same-turn amendments **mandatory**, not drift (five surfaces in lockstep: `contracts.md`,
`shared/README.md`, a new user-docs reference + its index link, and the `perk-expert` mirror).

## Cross-plane / docs posture

These conversions are **Python-internal validation refactors with byte-identical observable
behavior** — stored YAML/JSON and the `validate()` findings are unchanged, and the TS twins read the
same `shared/` files independently. So they touch **neither `shared/contracts.md` nor
`docs/user-docs/`**. This is the rule, not the exception, for a parse-internals refactor.

## Process + toolchain reaffirmations

- **Objective-node linkage at save.** A plan saved as a *standalone* GitHub plan (not linked to the
  objective node) means `/land`'s deterministic auto-mark doesn't fire (status stays `planning`,
  `pr` stays `null`) and `/objective-reconcile` must do the mechanical mark. Save objective-node work
  **through the objective-plan factory** so land's auto-mark works.
- **Comment hygiene applies to freshly-authored docstrings too** — describe a migration's *nature*
  (`in-progress migration`), never its plan-phase label (`Phase N`).
- **E501 ripple:** a longer symbol (`render_header_block(header)` vs `header.model_dump(...)`,
  `Model.model_validate(...).to_domain()` chains) pushes lines over 100 cols — run `ruff format`
  before commit.
- **CI green ≠ committable:** pre-commit `ruff-format` can reflow a call AFTER `run_ci` passed —
  re-stage and re-commit.
- **Test exit 143 (SIGTERM) with no FAILED line is a transient kill** — rerun before debugging.
- **Whole-tree `typecheck-py` (ty) is change-unscoped:** a sibling node's latent `tests/` ty debt
  lands red on `main` and blocks an unrelated PR — clear it separately, proving it pre-existing via
  the git-stash diagnostic.

## Testing gotchas (ty + pydantic + ruff)

- **Exercise lenient rejection / coercion through `Model.model_validate({...})`, never typed kwargs.**
  ty type-checks `tests/` and statically flags every deliberately-invalid kwarg against a typed
  pydantic model (`invalid-argument-type`/`unknown-argument`/`missing-argument`); `model_validate`
  takes `Any` and is the *real* boundary shape the untyped dict/JSON produces.
- **The unavoidable frozen-mutation negative** flips `ValidationError` → `FrozenInstanceError` and
  needs `# ty: ignore[invalid-assignment]` per line (above).
- **A tolerant-construction site dropping the model** (`.model_validate(item)`) must re-add the
  non-dict element guard (`if isinstance(item, dict)`) the model had handled implicitly.
- **Pydantic models reject positional args** — grep for positional constructors when converting and
  switch to keyword construction.

## Sources

- Pydantic v2 conversion table (the `str` target accepts only `str`/`bytes`, no scalar rows — why a
  `None`/`int` for a `str` parse field still raises under `strict=False`) —
  https://docs.pydantic.dev/latest/concepts/conversion_table/
