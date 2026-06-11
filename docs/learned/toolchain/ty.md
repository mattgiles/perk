---
title: ty gotchas — narrowing untyped JSON values, suppression syntax, enum strictness in tests
read_when: You hit a ty invalid-argument-type or no-matching-overload error while handling untyped or object-form values parsed from JSON/settings, need to suppress a ty diagnostic in a test, or ty rejects a string literal where an enum is annotated.
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

Follow-on: ruff's SIM108 then prefers the ternary form over an if/else block — so the `cast` fix and
a ruff style change usually land **together** in the same edit.

## 2. `dict.update(x)` where `x: dict[str, object] | None` fails `no-matching-overload`

Guard with a **truthiness** check (`if x:`) rather than `isinstance(x, dict)` — it satisfies the
overload and is cleaner.

## Generalization

ty narrows bare / `object` values pessimistically. When a value originated as untyped JSON, prefer
an explicit `cast` (for member access) or a truthiness guard (for overloaded calls) over
`isinstance`.

## ty suppression + enum strictness in tests

- **ty only honors its own `# ty: ignore[rule]` form** — the reflexive mypy-style
  `# type: ignore[...]` does NOT suppress ty diagnostics. In-repo precedent: the frozen-dataclass
  immutability tests in `tests/test_issue_backend.py` (deliberate invalid assignments expecting
  `FrozenInstanceError`) use `# ty: ignore[invalid-assignment]`.
- **ty rejects string literals where an enum-typed param is annotated** — pass the enum member
  (e.g. a `NodeStatus` member, not `"done"`). This is caught only in CI by ty, not by pytest, so
  it surfaces late if you only run tests locally.

## Cross-references

- `perk/providers.py`, `perk/init.py` — settings.json `packages` handling
- `tests/test_issue_backend.py` — the `# ty: ignore[invalid-assignment]` precedent
- `docs/learned/toolchain/ruff.md` — the SIM108 / formatter interaction
- the `ty` skill
