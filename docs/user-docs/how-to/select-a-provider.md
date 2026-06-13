# How to select a plan or todo provider

Swap perk's bundled plan-authoring or todo/checkpoint surface for a supported foreign provider (or
back to perk's default). perk ships zero-config defaults — `perk-plan` and `perk-checkpoints` — and
selecting a provider is just pointing the `[providers]` table at a different id from the supported
set.

**Prerequisite:** know which seam you want to change (`plan` or `todo`) and which provider id from
the [supported set](../reference/providers-and-backends.md#provider-seam--the-supported-set) you
want. The `[providers]` row shape is documented in the
[configuration reference](../reference/configuration.md#providers).

## Steps

1. **Pick a seam.** There are two: `plan` (plan-authoring) and `todo` (checkpoints/todo overlay).
   Each is selected independently.

2. **Pick a provider id** from the supported set:
   - `plan`: `perk-plan` (default), `tombell-plan` (REPLACE posture,
     `npm:@tombell/pi-plan`), `plannotator-plan` (AUGMENT posture, `npm:@plannotator/pi-extension`).
   - `todo`: `perk-checkpoints` (default), `juicesharp-todo` (runtime-defer,
     `npm:@juicesharp/rpiv-todo`).

   See the [providers reference](../reference/providers-and-backends.md#postures) for what each
   posture does — REPLACE vacates perk's plan surface at registration time; AUGMENT keeps it and
   skips only the colliding flag/shortcut; runtime-defer (todo) just stands perk's checkpoints down
   at runtime.

3. **Write the `[providers]` row** in `.pi/perk.toml`. Set the seam key to the chosen id. Example —
   switch the plan seam to tombell and keep perk's checkpoints:

   ```toml
   [providers]
   plan = "tombell-plan"
   todo = "perk-checkpoints"
   ```

4. **Run `perk init` to converge the package.** Selecting a foreign provider adds its npm package to
   `.pi/settings.json` `packages`; deselecting it removes the entry. perk's own reference providers
   have no package, so selecting a default adds nothing.

5. **Run `perk doctor` to validate.** The `providers` check resolves the selection and reports
   `plan=…, todo=…`. It **warns** on problems but is never fatal — the default path is the hard
   guarantee.

## Fallback behavior

Selection is forgiving — the default seam provider is always the floor:

- An **absent** `[providers]` key falls back to the seam default **silently**.
- An **unknown id** or a **wrong-seam id** falls back to the seam default
  **loud-but-non-fatal** (a warning, never a crash).

So a typo in a provider id degrades to the bundled default rather than breaking the session.

## See also

- [Providers & issue backends reference](../reference/providers-and-backends.md) — the supported
  set, postures, and fallback semantics.
- [Configuration reference — `[providers]`](../reference/configuration.md#providers) — the row shape.
- [`perk init`](../reference/cli.md#perk-init) / [`perk doctor`](../reference/cli.md#perk-doctor) —
  converge the package and validate the selection.

---

← Back to the [how-to router](index.md).
