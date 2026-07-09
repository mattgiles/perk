---
name: dignified-pydantic
description: House style for using Pydantic v2 well — validation/serialization at trust boundaries, strict vs lenient and extra-field policy, request/response/domain model separation, field/model validators, aliases, PATCH (exclude_unset) semantics, settings, and writing constructor calls that type-check under `ty`. Use when adding or reviewing a Pydantic model, designing an API/Celery/config/third-party-API boundary, deciding model_validate vs the constructor, choosing strict/coercion or extra ignore/forbid/allow, untangling "one model for everything", moving business logic out of validators, or making Pydantic code type-checker-friendly.
stages: [plan, objective-plan, implement, address]
references:
  - references/principles
  - references/integrations
  - references/house-style-and-examples
---

# Dignified Pydantic

Opinionated house style for Pydantic v2. The full guide — 48 numbered sections with runnable
examples — lives in the sibling `references/` files; read them when you need depth on a specific
mechanism. This page is the durable judgment you apply on every model.

## When to use this skill

Reach for this when you are:

- **adding or reviewing a Pydantic model** — and choosing its base, fields, and config;
- **designing a boundary** — an HTTP request/response, a Celery task payload, a config/settings
  loader, a third-party API response, or an LLM structured output;
- **deciding `Model.model_validate(raw)` vs the constructor `Model(...)`**;
- **choosing strictness and extra-field policy** — `strict=True` vs coercion, `extra` `forbid` /
  `ignore` / `allow`;
- **untangling "one model for everything"** into separate request / domain / response shapes;
- **moving business logic out of a validator** into a service;
- **making Pydantic code type-check cleanly under `ty`** (which has no Pydantic plugin).

## The core idea

Pydantic is a **runtime data-validation and serialization library built on type annotations**. Its
value is highest at the **edges** of a system, where data crosses a trust boundary:

```text
messy external data  -> Pydantic model -> clean internal Python values
clean internal values -> Pydantic model -> serialized external data
```

It is **not** "a better dataclass" and **not** your whole object model.

## The durable rules

1. **Use Pydantic at boundaries, not everywhere.** Validate at the edge; convert to a frozen
   dataclass / plain class / ORM object for internal domain state. (`references/principles.md` §3,
   §36)
2. **`model_validate` for untrusted/external data; the constructor for trusted, Python-shaped
   values.** This is the single most load-bearing habit. (§4)
3. **The strongest `ty` rule: constructor calls must type-check without relying on coercion;
   coercion enters through `model_validate`.** `User(id="123")` may pass at runtime but is not
   type-checker-friendly — write `User.model_validate({"id": "123"})` instead.
   (`references/house-style-and-examples.md` §38)
4. **Validation is not business logic.** A validator checks shape and local invariants; it never
   touches the database, network, or workflow policy — that belongs in a service. (§6, §9, §10)
5. **Separate input / domain / output models.** `CreateUserRequest`, `User`, `UserResponse` are
   three different contracts — never one mutable do-everything model. (§13, §40)
6. **Pick `extra` and strictness deliberately.** Your own API inputs: usually `extra="forbid"`.
   Third-party responses: usually `extra="ignore"`. Internal DTOs / task payloads: consider
   `strict=True` so coercion can't hide a bug. (§15, §16)
7. **`T | None` ≠ optional.** Nullable means the value may be `None`; *omittable* needs a default
   (`field: T | None = None`). (§12)
8. **Serialize with `model_dump` / `model_dump_json`; use `exclude_unset=True` for PATCH** to tell
   "omitted" apart from "explicitly null". (§17, §30)
9. **Prefer declarative `Field(...)` constraints over hand-rolled validators**, and name models for
   the boundary they serve (`CreateUserRequest`, not `UserModel`). (§7, §8, §39)

## The loop

When you create or review a model, run the decision checklist
(`references/house-style-and-examples.md` §46): What boundary is this? Input, output, config,
payload, or third-party? Forbid/ignore/allow extras? Strict or coercing? Aliases? Defaults correct?
Optional vs nullable? Separate from the domain object? Any validator doing business logic? How does
it serialize? If you can't name the boundary, the model may not need to exist.
