---
title: ty gotchas — narrowing untyped JSON values, suppression syntax, enum strictness in tests
read_when: You hit a ty invalid-argument-type or no-matching-overload error while handling untyped or object-form values parsed from JSON/settings (incl. deep GraphQL payloads — the narrowing-helper family), want to read a known key off an `object`-narrowed dict without a `cast` (the `.items()`-iteration idiom), hit per-element `isinstance` not refining the surrounding container, are choosing between the raising `_require_*` and the lenient `_opt_*` helper family (the disposition-matching rule), need to suppress a ty diagnostic in a test, or ty rejects a string literal where an enum is annotated.
---

# ty narrowing of untyped / JSON-shaped dict values

These two recurring gotchas both surface when handling Pi `settings.json` `packages` entries, which
are each a `str` **or** an object-form dict. ty narrows bare / `object` values pessimistically, so
`isinstance`-based narrowing fights it.

## 1. `isinstance(entry, dict)` collapses an untyped value to `dict[Never, Never]`

After `isinstance(entry, dict)` on an untyped / `object` value, ty narrows it to
`dict[Never, Never]`. A subsequent `entry.get("source")` then fails `invalid-argument-type`
("Expected `Never`, found `Literal["source"]`").

**Fix:** `cast("dict[str, object]", entry).get(...)`.

This trap recurred **three more times** across the Linear GraphQL work (source and tests); the
documented `cast` fix held every time — reach for it immediately, don't re-diagnose.

### The cast-free alternative: read a known key via `.items()` iteration

When you **don't want to** (or can't) `cast` an `object`-narrowed dict but need ONE known key off
it, `.items()` iteration carries no key-type constraint, so it type-checks where every direct access
fails. `entry.get("source")` / `entry["source"]` / `Mapping.get(...)` all fail `Expected Never` after
the `isinstance(entry, dict)` collapse — but
`next((v for k, v in entry.items() if k == "source"), None)` type-checks cleanly. Reach for this when
the `cast` would be the *only* reason to introduce one (a single key read in a tolerant scan); reach
for the documented `cast` when you read several keys or want the value typed downstream.

### Per-element `isinstance` in a loop does NOT refine the container's element type

An `isinstance` check *inside* a `for` loop refines the loop variable, but does **not** refine the
surrounding container's element type — `tuple(raw)` stays `tuple[object, ...]` no matter what the
body asserts. The behavior-preserving fix is **typed-list accumulation**: declare
`acc: list[str] = []`, `acc.append(item)` inside the same `isinstance` guard, then `tuple(acc)`.
Note these two idioms (`.items()` known-key read and typed-list accumulation) are **restructures**,
not signature-only edits — they change the shape of the body, so re-run the test oracle, not just
the type checker.

Follow-on: ruff's SIM108 then prefers the ternary form over an if/else block — so the `cast` fix and
a ruff style change usually land **together** in the same edit.

## 2. `dict.update(x)` where `x: dict[str, object] | None` fails `no-matching-overload`

Guard with a **truthiness** check (`if x:`) rather than `isinstance(x, dict)` — it satisfies the
overload and is cleaner.

## Generalization

ty narrows bare / `object` values pessimistically. When a value originated as untyped JSON, prefer
an explicit `cast` (for member access) or a truthiness guard (for overloaded calls) over
`isinstance`.

## Heterogeneous list/dict literal → annotate the local explicitly

ty infers a heterogeneous list/dict literal with its **narrowest union element type** and then
fails to pass it to a `list[dict[str, object]]` / `dict[str, object]` param
(`invalid-argument-type`). For example a `nodes = [{"type": "blocks", "relatedIssue": {...}}, ...]`
literal infers as `list[dict[str, str | dict[str, str]]]` and won't pass to a
`list[dict[str, object]]` param.

**Fix: annotate the local explicitly** (`nodes: list[dict[str, object]] = [...]`,
`existing: dict[str, object] = {...}`). Do **not** reach for `# type: ignore` — that's mypy syntax
and does NOT suppress ty anyway (reaffirms the suppression note below). This is caught by
`run_ci` / `just ci`'s typecheck-py even when a bare local `pytest` was green — `just ci` ≠ a bare
`pytest` run.

## The narrowing-helper family for deep untyped payloads

When navigating deep untyped payloads (GraphQL responses as `dict[str, object]`), per-site casts
and asserts don't scale: ty does **not** narrow `assert isinstance` through a subsequent
`__getitem__`. The pattern that works is a small **narrowing-helper family** —
`_require_dict`/`_require_list`/`_require_str`, each a `cast` wrapper raising a typed error
(`IssueBackendError`) on a malformed shape — which doubles as the never-silently-truncate guard
for the payload. In tests, one shared cast helper (e.g. `_input_payload()` for a recorded
GraphQL `variables["input"]`) beats per-site asserts the same way. See
`workflow/linear-backend.md` for the originating queries.

### The `_opt_*` lenient twin of `_require_*` + the disposition-matching rule

The raising `_require_*` family has a lenient twin: the **`_opt_*` family**
(`_opt_dict`/`_opt_list`/`_opt_str`), each `cast(...) if isinstance(...) else None` — it **never
raises**, returning `None` on a malformed/absent shape. The two families exist so a parse site keeps
its original *disposition*:

- **The disposition-matching rule:** never route a tolerant / skip / default parse site through a
  *raising* helper. Doing so silently flips tolerant parsing to fail-loud — a behavior change, not a
  type-only edit. When replacing a former bare `cast`, match it to the helper of its **own**
  disposition: a site that raised stays `_require_*`; a site that tolerated stays `_opt_*`.
- `_opt_str(x) or ""` is **byte-equivalent** to the `x if isinstance(x, str) else ""` it replaces —
  the safe mechanical swap for a tolerant string default.
- The four `cast(` calls that remain in the Linear package live **inside the `_opt_*`/`_require_*`
  definitions** (`perk/backends/linear.py`), internalizing the ty quirk so call sites stay cast-free.
  See `workflow/linear-backend.md`.

## ty suppression + enum strictness in tests

- **ty only honors its own `# ty: ignore[rule]` form** — the reflexive mypy-style
  `# type: ignore[...]` does NOT suppress ty diagnostics. In-repo precedent: the frozen-dataclass
  immutability tests in `tests/test_issue_backend.py` (deliberate invalid assignments expecting
  `FrozenInstanceError`) use `# ty: ignore[invalid-assignment]`.
- **ty rejects string literals where an enum-typed param is annotated** — pass the enum member
  (e.g. a `NodeStatus` member, not `"done"`). This is caught only in CI by ty, not by pytest, so
  it surfaces late if you only run tests locally.

## Cross-references

- `perk/substrate/providers.py`, `perk/convergence/init.py` — settings.json `packages` handling
- `tests/test_issue_backend.py` — the `# ty: ignore[invalid-assignment]` precedent
- `docs/learned/toolchain/ruff.md` — the SIM108 / formatter interaction
- `docs/learned/workflow/linear-backend.md` — the GraphQL payloads the helper family narrows
- the `ty` skill
