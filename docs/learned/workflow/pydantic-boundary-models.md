---
title: Pydantic boundary↔domain conversion (Pydantic at the edges, frozen `@dataclass` domain)
read_when: You are modeling config/API/subprocess/CLI boundaries, strict discriminated unions, frozen domain conversion, named parse results, or pinned JSON envelopes.
cluster: quality-and-guards
---

# Pydantic boundary↔domain conversion

**Pydantic lives ONLY at the parse/serialize edge; the domain object is a frozen `@dataclass`**
that imports no pydantic. A lenient parse model reads the untrusted edge, an explicit converter
copies into the frozen dataclass, and the existing `validate() -> list[Issue]` content pass is
unchanged. Nothing internal depends on pydantic. 2026-06: this boundary↔domain inversion superseded
the earlier "strict Pydantic model AS the frozen domain" philosophy — the model is **not** the
domain, the tolerant-parser `@model_validator(mode="before")` relocation and the context-gated
set-level validator are removed, and frozen mutation raises `dataclasses.FrozenInstanceError` (not
`pydantic.ValidationError`).

## Distillation

- Three role-named bases — `LenientParseModel` (read edge: stored files + external APIs),
  `StrictInputModel` (machine-authored CLI batch inputs), `OutputModel` (`--json` envelopes) —
  "The three role-named bases in `src/perk/boundary.py`".
- Every conversion follows lenient parse model → explicit `_to_X()` converter → frozen dataclass
  → the unchanged `validate()` content pass — "The canonical per-model recipe" (the executable
  reference is `tests/test_boundary.py`).
- Pick the base by boundary DIRECTION (who authored the bytes), not by the data's importance —
  "The boundary-DIRECTION decision (the big recurring correction)".
- Converters copy fields EXPLICITLY — `**model_dump()` is the anti-pattern — "Explicit field
  copy over `**model_dump()`" (+ the TWO decoupled field orderings beside it).
- `--json` envelopes are golden-pinned via `OutputModel.from_domain(...).model_dump(mode="json")`,
  including conditional-key omission — "OUTPUT-envelope golden-pinning".
- ty flags frozen-model mutation as `invalid-assignment` in tests — every conversion hits it;
  the fix idiom is in "The ty `invalid-assignment` frozen-mutation gotcha".
- Strict discriminated request/response models belong only at a subprocess edge; variants copy
  explicitly into frozen domain dataclasses — "Strict subprocess protocols".
- At three payload components, return a frozen named result and use `dataclasses.replace` in tests
  rather than extending positional tuples — "Strict subprocess protocols".
- Historical: the 2026-06 boundary↔domain inversion superseded "strict model AS the frozen
  domain" (the intro's dated supersession line); the dated one-liners under each rule record
  migration incidents, not guidance to re-apply.

## The three role-named bases in `src/perk/boundary.py`

`src/perk/boundary.py` exports three **role-named** bases, plus the `StrTuple` coercion type and
the `format_validation_error` / `translate_validation_errors` / `ValidationError` helpers (the
module's full `__all__`). The canonical recipe is an executable **reference test** in
`tests/test_boundary.py` — mirror that test's shape:

- **`LenientParseModel`** — `frozen=True, extra="ignore", strict=False, populate_by_name=True`.
  The read boundary for **perk's own stored files AND external API responses** (renames the old
  `LenientApiModel`; no deprecated alias). `extra="ignore"` drops sibling keys; lax coercion
  tolerates `"true"`/`1` → `True` and a YAML list → tuple. It has **no `str ← int/bool/None`
  coercion row**, so a bad-typed field still raises — the malformed-edge message contract survives.
- **`StrictInputModel`** — `frozen=True, extra="forbid", strict=True` (the config the removed
  legacy `StrictBoundaryModel` carried — see the AST discipline guard below); for machine-authored
  CLI batch inputs where a typo must fail loudly.
- **`OutputModel`** — `frozen=True, extra="forbid"` (no `strict` — built from trusted domain
  values). For `--json` snapshots and stored-block serialization via `model_dump(mode="json")`.

## The canonical per-model recipe

Every per-model conversion follows the same seam (registry, bindings, providers, objective
metadata, cache all mirror it):

1. A lenient parse model (on `LenientParseModel`, via `Model.model_validate(raw)`) at the **read**
   boundary.
2. An **explicit field-by-field** `_to_X()` / `to_domain()` converter into the frozen `@dataclass`
   domain object — collections become `tuple` / `frozenset`; the domain object carries its own
   methods.
3. The existing `validate() -> list[Issue]` content pass, unchanged.

- Set-level invariants live in `validate()` as a direct extend, never in a `@model_validator`
  (2026-06: the context-gated `@model_validator(mode="after")` + dump-then-revalidate dance was
  removed with the inversion).
- **One lenient parse model can back two read consumers** (objective's `ObjectiveNodeEntry` backs
  both the roadmap-block and manifest-block paths): `extra="ignore"` drops the keys each path
  doesn't want; bad-type field-path errors still raise.

2026-06: the old `_tolerate` `@model_validator(mode="before")` collapses and the
`StrTuple`/`BeforeValidator` strict shims were deleted — the lenient base does this natively.

## Mirroring a template copies its latent bugs — and the template keeps them

When a plan says "mirror module X symbol-for-symbol", budget a review pass on X's *own* contract
adherence: the mirror inherits X's defects, and review may fix only the copy (2026-08: the
expectations loader inherited `bindings.py`'s bare-`yaml.safe_load` leak and its `schema_version`
equality gate). The loader family's canonical fixed shape is
`packages/perk-dev/src/perk_dev/audit/expectations.py::load_catalog`.

## Loader/validator test-shape refinements

- **Message-fragment assertions under-pin `Issue` findings** — they never verify `Issue.where` or
  that `validate()` *accumulates* independent findings. Add one multi-defect fixture asserted as
  exact `(severity, where, message)` tuples, covering the generic and entry-id locations.
- **Pin the loader's field-for-field conversion with full domain equality.** One success-path
  assertion against a fully populated expected frozen dataclass (plus the pinned schema version)
  catches swapped/miswired `to_domain()` assignments invisible to every negative test.

## On a read whose absence has semantic weight, a model default is a fail-open bug

Require the field in the lenient parse model. The shipped instance (the stacks preview read): a
pagination flag whose absence would silently claim non-truncation — defaulting it manufactures
evidence the payload never carried. If the field can legitimately be absent, absence must degrade
or raise, never default into a positive claim (see `objective-delivery.md`'s stable/preview query
split).

## The boundary-DIRECTION decision (the big recurring correction)

Whether a model is a `LenientParseModel` (**read-into-the-type**) or an `OutputModel`
(**serialize-only**) is decided by **whether a real read-into-the-type consumer exists** — not by
the roadmap's framing. **When no read consumer exists, realize the boundary as an `OutputModel`
with an explicit `from_domain`, and do NOT author a read-parser with no consumer** ("don't author
fiction for unbuilt components") — **trust the code over the roadmap prose.** 2026-06: two arc
nodes had roadmap prose asserting a "lenient parse model at the boundary" that the code disproved
(the stored block was read back as a raw `dict`, never re-parsed into the type).

## Applying the lenient-parse pattern to API gateway response shapes

The boundary-inversion recipe applies unchanged to **external API response shapes** (GitHub `gh`
JSON, Linear GraphQL nodes). Concrete models: `src/perk/github/` and
`src/perk/backends/linear/_helpers.py`. The gateway-specific mechanics:

- **Validate at the CALL SITE, not inside the converter.** Converter bodies become
  `Model.model_validate(raw).to_domain()` (names + signatures unchanged); each call site wraps
  `translate_validation_errors(<ErrorType>, source=<operation label>)` so the error carries that
  site's label. **Wrap ONLY `model_validate`** — the downstream domain step already raises the
  gateway error type and must not be relabelled.
- **Prefer `Field(validation_alias=AliasChoices(...))` over `Field(alias=...)`** — one model
  serves two wire shapes (`WorkflowRunModel.id` reads `AliasChoices("databaseId", "id")`: the
  camelCase `gh run view` producer AND the snake_case REST producer).
- **Widen a converter param to `object`** when deleting its `isinstance(data, dict)` guard —
  `model_validate` accepts `Any`/`object`.
- **Edge-sharpening posture:** the identity field is required, every non-identity field keeps a
  default → byte-identical happy path; only a *present-but-malformed* payload now raises a
  labelled error. **Lookup-miss guards run BEFORE validation** (a soft
  `"databaseId" not in data → None` stays ahead of `model_validate`) so a legitimate miss never
  becomes a raise.
- **Nested-children composition:** validate child nodes separately and inject via a keyword-only
  `to_domain(*, comments=...)` rather than the parent model owning the nested list.
- **1-shape→1-domain gets a single `to_domain()`; 1-shape→N-domains gets accessors +
  normalizers.** Linear's recurring selection feeds two domain objects (`PlanState` via `get_plan`
  AND `AdoptableIssue` via `read_issue`), so the model exposes **validated field accessors + a
  small normalizer** (`normalized_state()`), and each call site assembles its own domain object.
- **Fold a shared helper into a model only after grep-confirming single-package use** (`_pr_state`
  → `PullRequestModel._normalized_state()`); retain generic connection-walk plumbing (no nameable
  boundary).
- **Substrate-home rule:** the payload-shape model lives in the package leaf
  (`src/perk/backends/linear/_helpers.py`), not the generic client module.

Byte-identical Python-internal tightening → **neither `shared/contracts.md` nor
`docs/user-docs/`** is touched (the cross-plane posture below).

## Explicit field copy over `**model_dump()` (the settled "1:1 no-op" objection)

When the parse model and the domain dataclass have identical fields, the field-by-field copy looks
like a no-op. The owner-settled rationale to keep the explicit split:

- It keeps pydantic types **out of the domain** (dignified-pydantic rule 1).
- It is NOT purely a no-op — it is where `set → frozenset`, `list → tuple`, frozen-mutation becomes
  `FrozenInstanceError`, and the domain's own methods attach.
- Template consistency: several siblings (providers, objective) are NOT 1:1, so a uniform
  parse→frozen-dataclass seam pays off; the 1:1 cases eat the boilerplate for that consistency.
- Prefer it over `X(**entry.model_dump())`: `model_dump()` is `dict[str, Any]`, so a `**`-spread
  type-checks as `Any` and **loses per-field ty checking** (dignified-pydantic §38).

## `from_domain` + TWO decoupled field orderings

The serialize-only `OutputModel` (e.g. `PlanHeaderOut`/`PlanRefOut`) carries an explicit
`from_domain(cls, x) -> Out` mapping every field (no `**dataclasses.asdict`). Two **separate**
orderings:

- **Domain dataclass field order is FREE** (declared required-first to obey "no required field
  after a defaulted field"); it does not control serialization.
- **The `OutputModel` field-declaration order IS load-bearing** — `model_dump(mode="json")` emits
  in declaration order, rendered verbatim, so it must match the prior emission order
  byte-for-byte. Pydantic v2 permits a required field **after** defaulted fields, so the
  `OutputModel` keeps the exact legacy order even when the dataclass can't. **The load-bearing
  comment moves onto the `OutputModel`.**

A **serialize-only header** (`ObjectiveHeader`, plan-header) needs **no read model at all** — only
an explicit `render_*_block(header) -> dict` builder (flat scalars in declaration order are
byte-identical to `model_dump(mode="json")`). Node-mutation sites revert `model_copy(update=...)`
→ `dataclasses.replace`.

## The `.model_dump()` blast radius — the recurring undercount + the ty oracle

Converting a Pydantic model → dataclass **removes `.model_dump()`**, so EVERY `<Type>.model_dump()`
call site breaks — and a writer-signature flip (`write_plan_ref(dict)` → `write_plan_ref(PlanRef)`)
ALSO breaks dict-literal call sites with **no type name to grep**. A plan's enumerated test-file
list **undercounts** every time (2026-06). **Whole-tree `ty check tests perk` is the completeness
oracle** — it flags every `unresolved-attribute … has no attribute model_dump` at once; grep does
not. The mechanical fixes:

- a module-level `_REF = {...}` dict consumed only by the writer → a `PlanRef(...)` dataclass;
- `{**_REF, "base": "develop"}` spread → `dataclasses.replace(_REF, base="develop")`;
- a test still needing the dict (a dry-run `--json` assertion) keeps a separate
  `_PLAN_REF_JSON = PlanRefOut.from_domain(_PLAN_REF).model_dump(mode="json")`;
- a shared override helper → `PlanRefModel.model_validate({**_REF, **over}).to_domain()`.

## The ty `invalid-assignment` frozen-mutation gotcha (EVERY node hits it)

A frozen `@dataclass` field is **statically read-only**, so ty flags `obj.field = x` as
`invalid-assignment` — even though ty does NOT flag the equivalent assignment on a frozen Pydantic
model. A frozen-mutation negative test, flipped from `pytest.raises(ValidationError)` →
`pytest.raises(FrozenInstanceError)`, therefore needs **`# ty: ignore[invalid-assignment]` on each
mutating line** (mypy-style `# type: ignore` does NOT suppress ty — see `toolchain/ty.md`).
Whole-tree `typecheck-py` is the gate that catches it; the per-model pytest suite stays green
without it. **Don't trust a plan that says "no suppression needed"** (2026-06: a node disproved
its own plan's claim).

## `str = ""` vs `str | None = None` on a parse field

When a parse field has a test feeding YAML `null` (`id:`) AND the domain wants a non-optional
`str`: type the parse field **`str | None = None`** and normalize `None → ""` in the converter
(`id=entry.id or ""`). `LenientParseModel` given `None` for a `str` field still **raises** (no
`None → str` coercion row) — which would wrongly turn a missing-id *content Issue* into a
structural raise. `str = ""` is safe **only** when there is no `id: null` test (e.g. registry's
`StageEntry.id: str = ""`).

## Per-field mapping extraction beats an all-or-nothing lenient model when field independence matters

A lenient parse model nukes **every** field if ANY declared field is invalid — fine for the
learned/skill frontmatter edge (one bad field ⇒ treat the whole block as absent), wrong where a
malformed foreign key (`cluster: [a, b]`) must never contaminate independent fields like
`title`/`description`. Read fields directly off the parsed mapping through a tiny
`_str_or_none`-style helper (per-field fallback for free, never reads unknown keys); when falling
back to a body walk, strip the frontmatter block first. Anchor: the user-docs frontmatter read in
`src/perk/learn/docs_scan.py`.

## Whole-file lenient parse + a separate content pass (the cluster-registry read)

When reading an untrusted config-like file, **parse the WHOLE file through one lenient parse
model, then run a separate content pass** returning frozen dataclasses or a typed refusal with a
precise human reason — the two-phase split keeps shape errors and domain errors separately
reportable. Realized instance: the cluster-registry read in `src/perk/learn/`. Companion rules:

- **Absence-selects-fallback boundaries must mean *true absence*** — a "read failed ⇒ fallback"
  arm lets a present-but-broken input silently select the fallback. Gotchas widening "broken":
  `FileNotFoundError` also fires for a *dangling symlink* (check `is_symlink()` first), and
  `IsADirectoryError` is an `OSError` subclass. Every broken-present state is a typed refusal.
- **Content-pass micro-traps**: `re.fullmatch`, not `match(...$)`, for identifiers (`$` accepts a
  trailing newline); one-line checks via `splitlines()`, not `"\n" in s`; require non-whitespace
  (`.strip()`), not just non-empty, for human-facing values.

## Config degrades to lenient-parse → frozen-dataclass (no `validate()` step)

Config has no content `validate()` pass, so the pattern degrades to **lenient-parse → frozen
dataclass** (`ConfigFileModel(LenientParseModel)` → frozen `@dataclass Config`):

- `ConfigFileModel` validates the **raw merged TOML** — an uncontrolled boundary — so `load_config`
  **does** wrap `model_validate` in `translate_validation_errors(ConfigError, ...)`: translate
  only at **uncontrolled** boundaries. 2026-07: the polarity flipped — the old "do not wrap"
  directive was correct only while the model re-validated code-controlled values (the converter
  still uses explicit attribute copy, never `model_dump()`).
- `user_bindings` is **not a model field**: bindings keep their loud-but-non-fatal
  `parse_user_bindings` seam, passed as a method param to
  `ConfigFileModel.to_domain(repo_root, *, user_bindings=...)`.

## Strict-input CLI-batch parsers (`StrictInputModel` / `RootModel`)

**Machine-authored CLI batch inputs** (the `--batch` / `--roadmap` JSON a sibling tool writes) go
the opposite way from the lenient read edge — a typo must fail **loudly**:

- **`translate_validation_errors` CANNOT carry `error_type`** (it constructs `error_cls(message)`).
  Catch `ValidationError` directly and raise
  `UserFacingCliError(format_validation_error(exc, source="batch"), error_type="bad_batch") from exc`;
  the JSON-decode `try/except` stays a SEPARATE raise.
- **`RootModel` strictness must be restated** — `RootModel` subclasses `BaseModel` directly, so
  the `StrictInputModel` base config does NOT apply; restate
  `model_config = ConfigDict(strict=True)` on the RootModel subclass.
- **Opt-in coercion fields:** a `StrEnum` field needs `Field(default=..., strict=False)` for
  value-based lookup; a JSON-array→tuple field reuses the `StrTuple` `BeforeValidator`. These are
  the ONLY intentionally-coercing fields.
- **Per-parser error contracts diverge — verify each command's existing contract before assuming
  one shared class** (2026-06 inbox correction): the `pr` batch parsers raise `bad_batch`; the
  objective roadmap path keeps its `(nodes, errors)` contract → `invalid_roadmap`; `state new-run`
  keeps a bare `UserFacingCliError`.
- **Fork, don't parameterize, a shared lenient validator when ONE caller must go strict** — inline
  the envelope handling into the strict path, leaving the shared lenient validator byte-unchanged.
  A side-map key (`adopt_issue`) declared on the strict node model with a default survives
  `extra="forbid"` and is dropped in `to_domain`.
- **Intended behavior change (NOT byte-identical):** unknown/ill-typed keys on a strictened path
  now fail loudly with a field path — aligning Python with the TS `ROADMAP_PARAM_SCHEMA` the agent
  path already enforced (no contract change: it enforces an already-documented TS contract).
- **The error-STRING change gotcha:** replacing a hand-rolled `isinstance` check changes the
  user-facing error STRING even when behavior is identical — grep tests for the old message
  substring. `Field(min_length=1)` deliberately relaxes an old `.strip()` check. A cross-field
  rule is a `@model_validator(mode="after")` raising `ValueError`.
- **A domain dataclass + gateway signature flip** (e.g. `github.ResolveThreadRequest` replacing a
  `list[dict]` item) is completeness-proven by the whole-tree ty oracle (the `.model_dump()`
  blast-radius rule) — it catches every stale dict-literal call site grep would miss.

## Strict subprocess protocols with discriminated variants

Keep strict Pydantic at the subprocess trust boundary only: request/response models use
`extra="forbid"`, strict validation, discriminated variants, and model-level rules for cross-field
pairing; each validated variant copies field-by-field into frozen dataclasses (internal domain
types never inherit Pydantic behavior).

- A PEP 695 union alias annotated with a `Field` discriminator remains strict under that posture.
  For a degenerate variant, make its no-payload field a *required* `Literal[None]` (callers must
  send the explicit null; any mismatch fails at the wire). Pin each variant's wrong-discriminator,
  extra-field, missing-null, and pairing errors at the wire decoder.
- When a subprocess wrapper has no stdin channel, write the validated request to an adapter-owned
  temporary file and pass only its path in argv — a transport detail; validation and cleanup stay
  at the adapter boundary.
- At three payload components, replace the positional tuple with a frozen named-result dataclass;
  tests start from a real parsed result and use `dataclasses.replace` to compose variant cases
  (preserves field meaning, avoids fixtures drifting from parser defaults).

## OUTPUT-envelope golden-pinning (`OutputModel.from_domain(...).model_dump(mode="json")`)

Converting hand-rolled `--json` dict builders to
`OutputModel.from_domain(...).model_dump(mode="json")` byte-identically:

- **The golden-snapshot harness is the byte-identity oracle (the durable win).**
  `tests/_golden.py`'s `assert_golden(name, actual)`, under the `PERK_UPDATE_GOLDEN` env flag,
  **regens THEN still re-reads + asserts** (a non-roundtrippable regen still fails loudly);
  snapshots committed under `tests/golden/json/`.
- **"Pin FIRST" via an in-process oracle:** generate each envelope's golden from the **pre-swap
  committed builder** (`git show HEAD:<path>` → `exec`), fed a fixture built from the CURRENT
  domain classes (duck-typed), commit the golden, swap the builder, re-run WITHOUT the flag —
  green IS the proof; a final flagged regen with **zero git diff** confirms. Commit each swap
  right after its golden so the `HEAD:` oracle stays pre-swap.
- **Fixtures must populate optional fields + the nullable arms** exercising the `None`-guard
  branches — full + minimal variants, with/without the optional nested object.
- **Promote a `dict`-typed domain field to a frozen `@dataclass` + its own nested `*Out` BEFORE
  the swap** (plan-save's `objective_node` → `ObjectiveNodeLink`); emitted JSON stays
  byte-identical.
- **Nested-OutputModel discipline:** each nested object gets its own named `*Out` whose
  `from_domain` picks the **EXACT legacy subset** (the golden catches an extra/missing key);
  **reuse a sibling's existing `*Out`** (`model_dump(mode="json")` recurses); field declaration
  order = legacy key order on every `*Out` (the `(order load-bearing)` docstring convention);
  map-not-copy fields and computed-derived keys (doctor `summary`, feedback `counts`) live in
  `from_domain` (pure, no I/O).
- **Mechanics:** whole-tree `ty check tests perk` is the completeness oracle; removing a
  re-export-only helper is a 3-site edit (callers + import + `__all__`, RUF022 ordering); expect
  E501/`ruff format` churn (CI-green ≠ committed-format-green).
- **Conditional omission needs a serializer, not a nullable dump** — a wrap-mode model serializer
  removes the conditional key on the legacy-absent arm. Serialization-mode JSON Schema cannot
  express that omission, so the committed schema snapshot is a drift tripwire, not an instance
  validator; the pre-existing emitted-key-order tests stay unchanged (their pass is the no-drift
  acceptance for presence and order).

## Byte-identity discipline

The on-disk blob is the only durable contract, so the conversion must keep it byte-identical:

- `exclude_unset` is retained **ONLY** where the on-disk blob is intentionally minimal (the
  handoff cache); elsewhere serialize the **FULL** domain dataclass — byte-identical **because
  production always wrote full shapes** (confirm that premise first).
- A consume/mutate writer that did `model_copy(update=...)` + `exclude_unset` must **re-read the
  raw JSON through the Model directly** (the read path now returns a dataclass).
- Nested cache records recurse (`to_domain` / `from_domain` recurse through nested models);
  open-ended keys ride an `extra: Mapping` field with `extra="allow"` (folded on `to_domain`,
  spread back on `from_domain`).
- A lenient read boundary is an **intended edge shift** (a malformed `consumed: 1` now coerces to
  `True` instead of raising, matching pre-pydantic behavior) — document the coerced read in the
  test.
- **Verification that works:** generate every blob from a scratch dir on the branch AND on a
  `main` checkout, then `diff` — byte-identity in one shot.

## Converter-idiom unification + the discipline guard

**Free `_to_X(entry)` functions → `to_domain()` methods on parse models** (the method idiom used
everywhere else). Gotchas: a whole-file model gets `to_domain(self, schema_version)` with
`schema_version` as a **method param, not a model field** (a structural pre-check, never parsed);
the **string forward-ref return annotation is mandatory** (the model precedes its domain dataclass
in source order); the **collection type must match the domain field** (don't blindly tuple-ify);
keep the **explicit attribute-copy** (never `Config(**model.model_dump())` — it recursively dicts
nested instances and corrupts them); adding a *method* adds no field, so the unification is
schema-invisible.

**`StrTuple` is redundant on LENIENT models, load-bearing only on STRICT.** A `LenientParseModel`
(`strict=False`) coerces a JSON list → tuple natively (simplify the shim away); a
`StrictInputModel` **rejects** it, so the shim is load-bearing. The only behavioral delta is on a
malformed non-list input — verify it's absent from all blobs/fixtures before claiming
byte-identity.

**The `StrictBoundaryModel` removal → the AST discipline guard.** The durable artifact is
`tests/test_boundary_discipline.py` (mirrors `test_paths_guard.py`): `ast.walk` every module, flag
any `ClassDef` whose base is an `ast.Name` in `{BaseModel, StrictBoundaryModel}`, allowlist
`boundary.py` only; `RootModel[...]` is an `ast.Subscript` (not flagged). Pair vacuousness
self-checks + positive/negative arms; a backstop-not-proof (written base names only) — see
`source-scan-guards.md`. 2026-06: the guard landed with the removal of the legacy
strict-as-domain base (zero production consumers, import-proven dead).

**contracts.md value-type drift after a behavior-neutral retype:** `shared/contracts.md`
value-type blocks can still name old class identities (e.g. "`RunHandle` is a frozen Pydantic
model" after it became a frozen `@dataclass`) — **grep the type names when a domain type is
renamed/retyped** and reconcile.

## Publishing generated JSON Schemas as a committed contract

**A generated-artifact drift harness mirrors `tests/_golden.py`** (`tests/_schemas.py` is the 2nd
instance). The recipe:

- An **ordered module-level registry tuple** (relative path + model + mode) is the single source
  of truth — the per-item drift tests and the coverage test both derive from it.
- `render()` = `json.dumps(..., indent=2) + "\n"` with **no `sort_keys`** (pydantic emits
  declaration order); `assert_*` does **regen-then-ALWAYS-reread-and-assert** gated on a
  **dedicated** env flag (`PERK_UPDATE_SCHEMAS`, separate from `PERK_UPDATE_GOLDEN`).
- The helper module has **no `test_` prefix**; add a no-orphans/no-gaps coverage test (glob vs
  registry, both directions) + a mode-correctness smoke.
- **Per-category schema MODE is the load-bearing decision** (dignified-pydantic §32): parse/input
  models publish what perk **accepts** → validation mode; output envelopes publish what `--json`
  consumers **receive** → serialization mode. Nested sub-models ride along in `$defs`.
- **`shared/` force-include bundles a new subdir into both planes for free** (wheel `perk/_shared`
  + npm `shared/` files entry) — just add one representative path to both packaging tests.
- **The doc-amendment rule's deliberate exception:** a node that **defers** the schema-publish +
  contract/doc amendments makes those same-turn amendments **mandatory**, not drift (five surfaces
  in lockstep: `contracts.md`, `shared/README.md`, a user-docs reference + index link, the
  `perk-expert` mirror).

## Cross-plane / docs posture

These conversions are **Python-internal validation refactors with byte-identical observable
behavior** — stored YAML/JSON and the `validate()` findings are unchanged, and the TS twins read
the same `shared/` files independently. So they touch **neither `shared/contracts.md` nor
`docs/user-docs/`**. This is the rule, not the exception, for a parse-internals refactor.

## Testing gotchas (ty + pydantic + ruff)

- **Exercise lenient rejection / coercion through `Model.model_validate({...})`, never typed
  kwargs.** ty type-checks `tests/` and statically flags every deliberately-invalid kwarg against
  a typed pydantic model; `model_validate` takes `Any` and is the *real* boundary shape the
  untyped dict/JSON produces.
- **A tolerant-construction site dropping the model** (`.model_validate(item)`) must re-add the
  non-dict element guard (`if isinstance(item, dict)`) the model had handled implicitly.
- **Pydantic models reject positional args** — grep for positional constructors when converting
  and switch to keyword construction.
