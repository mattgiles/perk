# Smoke: the `tombell-plan` foreign plan provider (Objective #115, Node 2.3)

**Status:** validation record for the first 3rd-party plan adapter (`planAdapterTombell`). Node 2.3's
explicit mandate is to *validate the provider contract against a real foreign surface*. The unit
harness loads **only** perk's extension (not the foreign package), so it can prove perk's
registration-time deferral and the shim's injection in isolation, but **not** the true coexistence
(the foreign `/plan` actually present, with no duplicate-registration collision). This doc is the
end-to-end smoke that closes that gap: a runnable procedure on a scratch repo + the recorded result.

## What the unit tests already cover (no smoke needed)

- `extension/planMode.test.ts` — under `[providers] plan = "tombell-plan"`, perk does **not** register
  `/plan`, and `--plan` is inert (no read-only flip, no `perk:plan-context` injection).
- `extension/planAdapterTombell.test.ts` — under `tombell-plan` the shim injects the
  `perk:plan-adapter-tombell` bridge context (directing prose → `/plan-save`); under the default
  selection it injects nothing and strips any stale marker.
- `extension/providers.test.ts` / `tests/test_providers.py` — the real entry has **no**
  `package_filter`.
- `tests/test_init_idempotent.py` — selecting `tombell-plan` wires `{"source":
  "npm:@tombell/pi-plan"}` (object form, no filter); deselecting removes it; idempotent.

## The runnable smoke (deterministic half — recorded result)

The `perk init` wiring half is fully deterministic and was run on a scratch repo from this worktree:

```sh
mkdir /tmp/perk-smoke-23 && cd /tmp/perk-smoke-23 && git init -q
mkdir .pi && printf '[providers]\nplan = "tombell-plan"\n' > .pi/perk.toml
<worktree>/.venv/bin/perk init --no-interactive
```

**Recorded result (select):** `.pi/settings.json` `packages` gains the foreign package in **object
form with no filter** —

```json
{ "source": "npm:@tombell/pi-plan" }
```

— i.e. the real entry drops the illustrative `extensions: ["extensions/*.ts"]` filter (which matched
nothing — `@tombell/pi-plan`'s sole extension is its root `index.ts`). Omitting the filter means Pi
loads exactly that one extension, so the foreign `/plan` surface actually registers.

**Recorded result (deselect):** setting `[providers] plan = "perk-plan"` and re-running `perk init`
prints `removed @tombell/pi-plan` and the entry is gone from `packages`; the borrowed/user packages
survive untouched.

## The coexistence half (manual, requires a live `pi` session)

The duplicate-registration avoidance is structural and cannot collide given the design, but to
confirm against the real foreign surface, in a repo with `tombell-plan` selected and `perk init` run:

1. Launch `pi`. perk's plan surface is **not** registered (Node 2.3 registration-time deferral), so
   the foreign `@tombell/pi-plan` owns bare `/plan`, `Ctrl+Alt+P`, and `--plan` with **no** `:N`
   suffix (Pi suffixes duplicate command names — the reason handler-time deferral alone is
   insufficient once the foreign package is loaded).
2. `/plan` (foreign) enters its read-only exploration mode; the assistant authors a **free-form prose
   plan**. perk's read-only gate is also engaged for cold-door planning launches
   (`session_start → syncFromState(handoff.mode=read-only)`); the foreign package self-enforces
   read-only for ad-hoc `pi --plan`. The shim injects the `perk:plan-adapter-tombell` bridge context
   directing the model to persist via perk's canonical save.
3. When decision-complete, run `/plan-save` (it scrapes the latest plan prose via
   `extractPlanMarkdown`) — the plan lands at `cache.plan-ref` with `provider="github"` (the issue
   **storage backend**, NOT restamped to `tombell-plan`; the authoring-provider id lives only in the
   `[providers] plan` selection). Any `objective_id`/`node_id`/`consumed_learn` from the launch
   handoff are recovered automatically.
4. Deselect (or set back to `perk-plan`) + `perk init` → the foreign package is removed and perk's own
   `/plan` surface returns on the next launch.

All downstream stages bind only to the provider-agnostic plan-ref and are unchanged — the
dimension-7 isolation guarantee holds.
