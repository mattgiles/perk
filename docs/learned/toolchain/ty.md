---
title: ty narrowing of untyped / JSON-shaped dict values
read_when: You hit a ty invalid-argument-type or no-matching-overload error while handling untyped or object-form values parsed from JSON/settings (e.g. Pi settings.json packages entries).
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

## Cross-references

- `perk/providers.py`, `perk/init.py` — settings.json `packages` handling
- `docs/learned/toolchain/ruff.md` — the SIM108 / formatter interaction
- the `ty` skill
