---
title: Pydantic boundary↔domain conversion (Pydantic at the edges, frozen `@dataclass` domain)
read_when: Converting a registry/bindings/providers/config/plan-metadata/objective/cache boundary onto the lenient-parse-model → frozen-`@dataclass` → `validate()` pattern, deciding read-into-the-type vs serialize-only direction, preserving byte-stable stored YAML/JSON, or writing ty-clean negative tests against a frozen dataclass + its Pydantic boundary model.
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

## The boundary-DIRECTION decision (the big recurring correction)

Whether a model is a `LenientParseModel` (**read-into-the-type**) or an `OutputModel`
(**serialize-only**) is decided by **whether a real read-into-the-type consumer exists** — not by the
roadmap's framing. Two arc nodes (Config; PlanHeader/PlanRef) had roadmap prose asserting a "lenient
parse model at the boundary" that the code disproved: the stored block was read back as a raw
`dict`, never re-parsed into the type. **When no read consumer exists, realize the boundary as an
`OutputModel` with an explicit `from_domain`, and do NOT author a read-parser with no consumer**
("don't author fiction for unbuilt components"). The planner's "Correction to the node framing
(verified against the code)" section is doing real work — **trust the code over the roadmap prose.**

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
dataclass** (`ConfigModel(LenientParseModel)` built then converted to a frozen `@dataclass Config`):

- Do **not** wrap the `ConfigModel(...)` construction in `translate_validation_errors` — it is built
  from code-controlled, already-`_parse_*`-typed values, so a `ValidationError` there can only be a
  perk bug and must surface loud. (Error translation belongs only at **uncontrolled** boundaries.)
- **Never `Config(**model.model_dump())`** — `model_dump()` recursively dicts nested `Binding` models
  and corrupts `user_bindings`. Use **explicit attribute access**; with pydantic's default
  `revalidate_instances="never"`, `model.user_bindings` holds the original `Binding` instances by
  identity (tests assert `config.user_bindings[0] is binding`).

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
