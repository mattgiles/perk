---
title: Pydantic boundary-model conversion (the strict/lenient parse boundaries)
read_when: Converting a frozen-dataclass parse boundary (registry/bindings/providers/config/plan-metadata/cache) to a Pydantic v2 model, deciding strict vs lenient, relocating a tolerant parser into a validator, preserving byte-stable stored YAML, or writing ty-clean negative tests against a typed pydantic model.
---

# Pydantic boundary-model conversion

perk's input boundaries were hand-rolled frozen dataclasses with separate tolerant parse functions
(`_parse_*` + `_str`/`_map`/`_str_list` helpers that collapsed absent/wrong-type values to
`""`/empty). The boundary-first objective replaced them with Pydantic v2 models anchored on one
leaf, `perk/boundary.py`, which exports the two base configs (`StrictBoundaryModel`,
`LenientApiModel`), the `StrTuple` coercion type, and the `format_validation_error` /
`translate_validation_errors` error-translation seam. This doc is the reusable recipe + the
decisions and gotchas that recur across every conversion.

## The two-base decision: strict vs lenient

The single most load-bearing call is **which base a boundary extends**, and it tracks **who authors
the input**:

- **`StrictBoundaryModel`** (`frozen` + `extra="forbid"` + `strict=True`) — for **perk-authored
  contract shapes** we control: the registry, bindings, providers, and plan/objective/cache
  metadata. Strict mode rejects implicit scalar coercion and bool-as-int by default, and
  `extra="forbid"` rejects unknown keys. These boundaries *want* to sharpen: a wrong field type or
  a stray key is a real defect, not tolerable drift.
- **A plain frozen `pydantic.BaseModel`** (NOT strict) — for the **deliberately forgiving** boundary.
  `Config` is the canonical example: it accepts already-coerced / pre-validated values (a `Path`,
  lenient overlay output) and must not fight the silent-omit semantics. The node text said
  "BaseModel" (generic) precisely to mark this contrast with its strict siblings.
- **`LenientApiModel`** (`populate_by_name=True`, additive-tolerant) — for **external API responses**
  (GitHub / Linear) whose schemas grow additively and must not raise on unknown fields.

"No Pydantic Settings" ≠ "no Pydantic": it means do not adopt the `pydantic-settings` library
(auto env/file reading). The hand-rolled `_read_toml` / `_overlay` / secret-reader pipeline stays.

## The model validates the assembled result; it does NOT replace the `_parse_*` layer

For a lenient boundary, the real semantic contract — silent-omit (`base=7`→None, unknown
`[subagents]` key dropped, mixed `setup` filtered), overlay-wins — lives in the `_parse_*` helpers
**before** the model is constructed. Those stay byte-identical; the model is a typed, frozen
structural backstop at the final construction point. The existing parse-layer test suite is the
regression guard that the semantics didn't move.

For a strict boundary, the choice between **`Model.model_validate(raw)`** and **explicit-kwarg
construction** (`Registry(id=..., stages=...)`) is the lever controlling whether `extra="forbid"`
bites: `model_validate(dict)` enforces it (unknown keys raise), explicit kwargs do not. Decide it
deliberately per object — per-element/per-stage validation typically uses `model_validate(raw)`
(so unknown sub-keys raise) while a top-level container built from explicit kwargs keeps top-level
extra keys tolerated.

## The structural/content split is preserved by DEFAULTING fields, not requiring them

The pre-existing two-tier contract is: **structural** failures raise the domain error
(`RegistryError`/`BindingsError`/`ProvidersError`); **content** failures are returned by
`validate() -> list[Issue]` and never raise. The old parsers defaulted *absent* fields to `""`/empty
so `validate()` (not the parser) reported them. To keep that intact, **every model field gets a
default** — a *missing* key stays a content Issue, not a structural raise. The strict model sharpens
the boundary only where intended: **wrong field types** and **unknown keys** now raise (were silently
defaulted/dropped). Choosing defaults over required-fields is deliberate: required fields would move
absent-field handling from content→structural and break `validate()`'s findings.

Corollary: **keep value-untyped fields untyped to keep `validate()`'s checks live.** Fields whose
*values* carry vocabulary semantics (`mode`, `worktree`, free-form `doors`/`run_id` dicts) stay
plain `str` / `dict[str, Any]` so strict mode only checks the structural shape and defers all
enum/value-vocabulary checks to `validate()`. Typing `mode` as an enum would relocate a content
Issue into a structural raise (e.g. a test feeding a *valid str, invalid enum value* must stay a
content Issue). The same reasoning keeps list fields plain `list[str]` (not `StrTuple`/tuple) where
tests assert list equality and consumers index them.

## The "model IS the tolerant parser" pattern

When a frozen dataclass had a separate tolerant parse function that coerced every field through a
sentinel-collapse helper (absent/wrong-type → `""`), **relocate the tolerance into a
`@model_validator(mode="before") @classmethod`** that returns a dict of exactly the declared keys,
each run through the retained `_str` helper. Delete the standalone parse function; its call sites
become `Model.model_validate(raw)`. This keeps a single tolerant parse surface and preserves the
two-tier contract — the model **never raises for content** because every field comes out the right
type.

Why `strict=False` does NOT substitute for the `_str` helper: per the pydantic v2 conversion table,
a `str` target accepts only `str←str` and `str←bytes/bytearray` — there is **no `str←int/float/
bool/None` row**, so pydantic raises on a non-string scalar for a `str` field in **both** strict and
lax modes. `_str()` is a *sentinel-collapse* (absent/wrong-type→`""`), not a coercion any strict
toggle provides. The tolerance must be relocated, never replaced by a config flag.

Two structural consequences:

- **Because the before-validator returns ONLY the declared keys, a stray key is stripped before
  `extra="forbid"` is reached** — so unknown keys are silently dropped exactly as the old parser did
  (no robustness regression on a user overlay like `[[bindings]]`). Worth an explicit
  `not hasattr(obj, "bogus")` test.
- **Derived fields become `@property`, not declared fields.** Values that were always pure functions
  of another field (e.g. `kind`/`target_id` split from `trigger`) drop out of the declared fields
  and become read-only properties computed from the retained split helper — single source of truth.
  This shrinks the model to its real input fields and forces positional test constructors to drop the
  derived args (keyword-only construction).

Vocabulary and uniqueness checks (known modes, known trigger kinds, duplicate-trigger detection)
deliberately stay in `validate()` returning `Issue`s — encoding them as model constraints would
relocate findings off the `validate()` path and break the two-tier contract.

## Context-gated set-level validator (lenient at load, surfaced in `validate()`)

A set-level invariant that must stay lenient at load but surface as `Issue`s in `validate()` (the
providers "exactly-one-`default:true`-per-seam" rule) uses a reusable pattern:

- The invariant lives **once** as `@model_validator(mode="after")` on the set model, but **only
  raises when the caller opts in** via pydantic validation context
  (`if info.context and info.context.get("enforce_single_default"): raise ValueError(...)`).
- **Load stays lenient**: plain `ProviderSet(...)` construction → `info.context is None` → the
  validator skips → only *structural* failures raise the domain error.
- **`validate()` opts in**: it re-runs the validator via
  `Model.model_validate(model.model_dump(), context={...})`, catches `ValidationError`, and converts
  `exc.errors()[i]["msg"]` → `Issue` records.
- **Constraint that travels with the pattern**: because `validate()` re-validates the *dumped* model
  and `model_dump()` emits a **list**, the re-validated collection field must be `list[Provider]`,
  not a strict `tuple`/`StrTuple` (a strict tuple field would reject the dumped list). If a future
  sibling wants `StrTuple`, the re-validation-of-the-dump path must be reconciled with it.

Lenient per-field coercion is expressed as module-private `Annotated` types with **named**
before-validator functions (no bare lambdas, per dignified-python). Semantics: an *absent* key falls
to the field default (the before-validator does **not** run); a *present-but-ill-typed* value runs
the coercer, which returns a real value of the strict target type so strict validation then accepts
it.

## Byte-stable stored YAML depends on field-declaration ORDER

For any model whose `model_dump(mode="json")` output is rendered into a stored issue body
(`render_metadata_block` does `yaml.safe_dump(sort_keys=False)`), **`model_dump` emits in
field-declaration order**, rendered verbatim. The old hand-written `to_data()` often **reordered**
fields versus the dataclass declaration. So when converting a dataclass-with-`to_data()`, declare
the model fields in the **old `to_data()` emission order, NOT the dataclass field order** — otherwise
every existing stored body churns on next save. Pin it with an order-guard test (assert the rendered
YAML key positions are strictly increasing). Pydantic v2 imposes **no** "required-after-default"
ordering rule (unlike dataclasses), so required-no-default fields may legally sit among/after
defaulted fields — every caller uses kwargs, so the only reason for the order is serialization
parity. Leave a load-bearing comment on the field block.

## Error translation stays at the boundary seam

Wrap model construction at a read/parse boundary in
`translate_validation_errors(<DomainError>, source=str(path))` so any per-element `ValidationError`
becomes the domain error with a dotted field-path message. Keep the explicit structural pre-checks
(file exists / top-level mapping / `schema_version`) — they carry specific helpful messages and
pydantic does no I/O; the model's typed `schema_version: int` only types the value, it does not own
the version gate.

For models built from **code-controlled** values (e.g. `PlanHeader`/`PlanRef`, or a `Config(...)`
constructed from already-parsed helper output), do **not** add an error-translation wrapper: a
`ValidationError` there can only mean a perk bug (a helper returned a wrong-typed value), so let it
surface loud. The two-tier `translate_validation_errors` seam is the boundary contract for inputs we
do *not* control.

`frozen` carries over, but the raised type changes: mutating a frozen pydantic model raises
`pydantic.ValidationError` (not the dataclass `FrozenInstanceError`). Frozen-contract tests import
`ValidationError` (re-exported from `perk/boundary.py`) and assert `pytest.raises(ValidationError)`
on attribute assignment.

## Testing gotchas (ty + pydantic + ruff)

- **Test runtime validation through `Model.model_validate({...})`, never typed kwargs.** ty
  type-checks `tests/` (`[tool.ty.src] include = ["perk", "tests"]`) and statically flags every
  deliberately-invalid kwarg against a typed pydantic model (`invalid-argument-type`,
  `unknown-argument`, `missing-argument`). `model_validate` takes `Any`, so ty stays clean — AND it
  is the *real* boundary-usage shape (the untyped dict/list that YAML/JSON actually produces). This
  is the idiomatic way to exercise strict rejection / coercion under a strict type-checker.
- **When a typed-kwarg negative test is unavoidable, suppress per-diagnostic with
  `# ty: ignore[<rule>]`** — mypy-style `# type: ignore` does NOT suppress ty (see
  `docs/learned/toolchain/ty.md`). A frozen-mutation reassignment (`model.field = x` with a
  type-valid value) is a *runtime-only* constraint and is NOT ty-flagged — no suppression needed.
- **Pydantic lax coercion picks the negative-test target.** On a non-strict model, a `str`→`Path`
  coercion IS accepted, so a non-coercible negative case must target a field that genuinely cannot
  coerce (e.g. a bare `str` where `list[str]` is required). Confirm each field's lax behavior before
  writing the negative.
- **Pydantic models reject positional args** — grep for positional model constructors when
  converting a dataclass and switch them to keyword construction.
- **ty narrowing across separate calls**: `set.default_for("x").id` fails ty (`X | None` has no
  `.id`) even right after an `is not None` on a *separate* call — bind to a local first. This often
  surfaces only in `run_ci`, not local pytest.
- **The `mode="before"` dict needs an explicit annotation**: `d = raw if isinstance(raw, dict) else
  {}` makes ty infer the `{}` arm as `dict[Never, Never]` (so `d.get(key)` fails "Expected Never") —
  annotate `d: dict[Any, Any] = ...`.
- **ruff isort is case-sensitive** — `BindingsError` sorts before `BindingSet`,
  `StrictBoundaryModel` before `StrTuple`; let `ruff check --fix` settle import order rather than
  guessing. Replacing `.to_data()` with `.model_dump(mode="json")` and widening keyword constructors
  lengthens lines (E501) — `ruff format` rewrites the module *after* CI is green, so always run the
  formatter before committing.

## Whole-tree ty gate caveat

`typecheck-py` runs `uv run ty check` over the **whole tree** (not change-scoped), so any `.py` touch
trips it. A latent test-construction bug an earlier PR left in `tests/` (a typed-model kwarg that ty
rejects) lands red on main and blocks an unrelated PR's gate. Expect to clear pre-existing ty debt in
`tests/` when doing a conversion; commit the repair separately as a clearly-scoped pre-existing fix,
and verify it predates your change with the git-stash diagnostic.

## Cross-plane / docs posture

These conversions are **Python-internal validation tightening with byte-identical observable
behavior** — the TS twins (`extension/substrate/registry.ts`, `config.ts`, etc.) read the same
`shared/` files independently and parse semantics are unchanged. So they touch **neither**
`shared/contracts.md` **nor** `docs/user-docs/`. This is the rule, not the exception, for a parse-
internals refactor: which surface reports what is preserved, so there is nothing cross-plane to
reconcile.

## Sources

- Pydantic v2 conversion table (the `str` target accepts only `str`/`bytes`, no scalar rows) —
  https://docs.pydantic.dev/latest/concepts/conversion_table/
