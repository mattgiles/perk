# Smoke: the `powerline-footer` / `pi-bar-footer` foreign footer providers (the `footer` interface seam)

**Status:** validation record for the fourth provider seam, **`footer`** — the **second interface
seam** (no durable artifact to bridge), vacate-only (`adapter: null`, no shim, no injected context)
for **both** foreign entries. It lets a repo swap perk's own footer (`installPerkFooter`,
`extension/surfaces/surfaces.ts`) for a foreign footer package — `powerline-footer`
(→ `npm:pi-powerline-footer`) or `pi-bar-footer` (→ `npm:pi-bar`). Unlike the `askuser` /`plan`
seams (registration-time vacating), perk installs its footer inside the `session_start` event
handler, so the vacating is **install-site (runtime)**: a guard at that single install site keyed
off `ctx.cwd`. The unit harness loads **only** perk's extension (not the foreign package), so it can
prove perk's vacating in isolation (no factory captured), but not the true coexistence (the foreign
footer rendering perk's `perk` status slot). This doc closes that gap.

## The 3→4 widening census (every site touched + the explicit "no change needed")

Adding the `footer` seam to the three-seam (`plan`/`todo`/`askuser`) substrate touched exactly:

- **`shared/providers.yaml`** — header seam vocabulary + footer status note; the `perk-footer`
  reference entry (`default: true`) and the two foreign entries (`adapter: null`, no
  `package_filter`).
- **Python plane** — `SEAMS` tuple; `ResolvedProviders.footer`; `resolve_providers` constructs
  `footer=resolve_seam("footer")`; `_parse_providers_selection`'s seam tuple; `init.py`
  `_converge_provider_packages`'s desired-package loop; `doctor.py` `_providers_check` ok-summary.
- **TypeScript plane** — `PROVIDER_SEAMS`; the three id constants (`PERK_FOOTER_PROVIDER_ID`,
  `POWERLINE_FOOTER_PROVIDER_ID`, `PI_BAR_FOOTER_PROVIDER_ID`); `ResolvedProviders.footer`;
  `resolveSeam`'s union + selection param + return; `PerkConfig.providers` type +
  `parseProvidersSelection`; the **new** `extension/surfaces/footerProvider.ts` helper pair;
  `index.ts`'s install guard (`&& isPerkFooterReferenceSelected(ctx.cwd)`).
- **Contracts** — §8.10 seam-vocabulary enumerations + footer status note; the footer-ownership
  passage ("by default" + vacate) and the `BORROWED_PACKAGES` borrow-vs-provider-seam reconciliation.
- **User docs** — `reference/providers-and-backends.md`, `reference/configuration.md`,
  `how-to/select-a-provider.md`.

**Explicit "no change needed" sites** (seam-generic, verified):

- **`validate`** (`perk/substrate/providers.py`) — iterates `SEAMS` and `default_counts`, so the
  fourth seam's exactly-one-default check is enforced automatically.
- **`by_id` / `default_for`** — seam-generic map/lookup; no per-seam branching.
- **`_managed_identities`** (`init.py`) — already iterates the **whole** supported set for the
  provider-managed identity discriminator, so the foreign footer packages are removable-on-deselect
  for free.
- **`surfaces.ts` `perkFooter` / `installPerkFooter`** — unchanged; stays the reference footer. The
  only change is *whether* `index.ts` calls it.
- **`cache.plan-ref`** — untouched (the footer has no artifact; no restamp).
- **todo seam / checkpoints** — untouched; checkpoints publishing into the `perk` status slot is
  already footer-ownership-independent, which is exactly why the foreign-footer bridge is automatic.

## What the unit tests already cover (no smoke needed)

- `extension/surfaces/footerProvider.test.ts` — `resolvedFooterProviderId` /
  `isPerkFooterReferenceSelected` resolve the default (and explicit `perk-footer`) as the reference,
  a foreign `pi-bar-footer` / `powerline-footer` selection as NOT the reference, and fail-safe to
  `perk-footer` on a corrupt config (perk keeps installing its footer).
- `extension/sessionLifecycle.test.ts` — driving a real bound session: under `[providers] footer =
  "pi-bar-footer"` `session_start` captures **no** footer factory (perk vacated); the default repo
  captures one (the `claim` test).
- `extension/substrate/providers.test.ts` / `tests/test_providers.py` — `PROVIDER_SEAMS` / `SEAMS`
  include `"footer"`; `ResolvedProviders.footer` is populated; the real foreign entries have
  `adapter: null` and **no** `package_filter`; the resolver handles default / selection / wrong-seam
  / unknown-id for the new seam.
- `extension/substrate/config.test.ts` / `tests/test_config.py` — the `footer` `[providers]` key is
  read on both planes.
- `tests/test_init_idempotent.py` — selecting `pi-bar-footer` wires `{"source": "npm:pi-bar"}`
  (object form, no filter); deselecting removes it; borrowed/user packages untouched.
- `tests/test_doctor.py` — the `providers` ok-summary now includes `footer=<resolved id>`.

## The runnable smoke (deterministic half — recorded result)

The `perk init` wiring half is fully deterministic and was run on a scratch repo from this worktree:

```sh
mkdir /tmp/perk-smoke-footer && cd /tmp/perk-smoke-footer && git init -q
mkdir .pi && printf '[providers]\nfooter = "pi-bar-footer"\n' > .pi/perk.toml
<worktree>/.venv/bin/perk init --no-interactive
```

**Recorded result (select):** `.pi/settings.json` `packages` gains the foreign package in **object
form with no filter** — `{ "source": "npm:pi-bar" }` — so Pi loads the foreign footer extension.

**Recorded result (deselect):** setting `[providers] footer = "perk-footer"` and re-running `perk
init` removes the entry; borrowed/user packages survive untouched.

## The coexistence half (manual, requires a live `pi` session)

The `footer` seam is an **interface seam** with no durable artifact: the "bridge" is automatic
because both foreign footers render extension statuses, and perk's composed `perk` `setStatus` slot
keeps publishing its objective/checkpoints segments regardless of footer ownership. To confirm
against the real foreign surface, in a repo with `pi-bar-footer` (or `powerline-footer`) selected
and `perk init` run:

1. Launch `pi`. perk does **not** install its own footer; the foreign footer (`pi-bar` /
   `pi-powerline-footer`) is the sole footer surface.
2. perk's `perk` status slot (its objective + checkpoints segments) appears as one of the foreign
   footer's rendered extension statuses — no bridge code, no adapter shim (`adapter: null`).
3. Deselect (or set back to `perk-footer`) + `perk init` → the foreign package is removed and perk's
   own footer returns on the next launch (the default path is the hard zero-change guarantee).
