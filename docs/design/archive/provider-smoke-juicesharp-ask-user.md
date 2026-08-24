# Smoke: the `juicesharp-ask-user` foreign ask-user provider (the `askuser` interface seam)

**Status:** validation record for the third provider seam, **`askuser`**. *2026-08 note
(Objective #1416): the smoked selection mechanism — `[providers] askuser`, the seam's
registration-time vacating — no longer exists; the package is a required borrowed built-in
(`BORROWED_PACKAGES`). The recorded smoke evidence stands as history; the zero-config
borrowed-built-in reality is smoked in `borrowed-askuser-todo-dogfood.md`.* An **interface seam**
(no durable artifact to bridge), vacate-only (`adapter: null`, no shim, no injected context). It
lets a repo swap perk's first-party `ask_user_question` tool (`extension/doors/askUser.ts`) for the
foreign `@juicesharp/rpiv-ask-user-question` extension, which registers a tool with the **identical
name** `ask_user_question` (a richer multi-question dialog). The unit harness loads **only** perk's
extension (not the foreign package), so it can prove perk's **registration-time vacating** in
isolation, but **not** the true coexistence (the foreign tool actually present, exactly one
`ask_user_question` standing). This doc is the end-to-end smoke that closes that gap: a runnable
procedure on a scratch repo + the recorded result.

## What the unit tests already cover (no smoke needed)

- `extension/doors/askUser.test.ts` — under `[providers] askuser = "juicesharp-ask-user"`,
  `registerAskUser` registers **no** tool (registration-time vacating); under the default it
  registers `ask_user_question` exactly as before. `resolvedAskUserProviderId` /
  `isPerkAskUserReferenceSelected` resolve the default and a foreign selection, fail-safe to
  `perk-ask-user` on a corrupt set. The pure-core (`runAskUserQuestion` / `decodeAskUserParams`)
  tests are unchanged.
- `extension/substrate/providers.test.ts` / `tests/test_providers.py` — `PROVIDER_SEAMS` / `SEAMS`
  include `"askuser"`; `ResolvedProviders.askuser` is populated; the real `juicesharp-ask-user`
  entry has `adapter: null` and **no** `package_filter`; the resolver handles default / selection /
  wrong-seam / unknown-id for the new seam.
- `extension/substrate/config.test.ts` / `tests/test_config.py` — the `askuser` `[providers]` key
  is read on both planes.
- `tests/test_init_idempotent.py` — selecting `juicesharp-ask-user` wires
  `{"source": "npm:@juicesharp/rpiv-ask-user-question"}` (object form, no filter); deselecting
  removes it; idempotent; borrowed/user packages untouched.
- `tests/test_doctor.py` — the `providers` ok-summary now includes `askuser=<resolved id>`.

## The runnable smoke (deterministic half — recorded result)

The `perk init` wiring half is fully deterministic and was run on a scratch repo from this worktree:

```sh
mkdir /tmp/perk-smoke-askuser && cd /tmp/perk-smoke-askuser && git init -q
mkdir .pi && printf '[providers]\naskuser = "juicesharp-ask-user"\n' > .pi/perk.toml
<worktree>/.venv/bin/perk init --no-interactive
```

**Recorded result (select):** `.pi/settings.json` `packages` gains the foreign package in **object
form with no filter** —

```json
{ "source": "npm:@juicesharp/rpiv-ask-user-question" }
```

— i.e. the real entry carries no `package_filter` (the verified manifest is
`{"extensions": ["./index.ts"]}`, so omitting the filter loads exactly that one extension), so Pi
loads the foreign extension and its `ask_user_question` tool actually registers.

**Recorded result (deselect):** setting `[providers] askuser = "perk-ask-user"` and re-running `perk
init` prints `removed @juicesharp/rpiv-ask-user-question` and the entry is gone from `packages`; the
borrowed/user packages survive untouched.

## The coexistence half (manual, requires a live `pi` session)

The `askuser` seam is an **interface seam** keyed on the tool *name* `ask_user_question`. Because
the foreign tool shares that **exact** name and tools — unlike commands — are **not** `:N`-suffixed
(a same-named tool replaces/warns by extension load order, non-deterministically), perk vacates at
**registration time**: under a foreign selection `registerAskUser` registers nothing, leaving
exactly one `ask_user_question` standing. To confirm against the real foreign surface, in a repo
with `juicesharp-ask-user` selected and `perk init` run:

1. Launch `pi`. There is **exactly one** `ask_user_question` tool present — perk's is vacated, the
   foreign `@juicesharp/rpiv-ask-user-question` tool is the sole registrant (no replace/warn
   ambiguity, no `:N` suffix).
2. When the model calls `ask_user_question`, the **foreign multi-question dialog** is what fires
   (not perk's single-question prompt) — the foreign tool self-documents via its own
   `promptGuidelines`. The model continues its turn with the answer (non-terminating-answer
   semantics, the seam's stable contract).
3. The tool is callable **during planning / read-only mode**: `ask_user_question` is already in
   `READ_ONLY_TOOLS`, and the foreign tool shares that exact name, so it is allowlisted
   automatically (no `READ_ONLY_TOOLS` change was needed).
4. Deselect (or set back to `perk-ask-user`) + `perk init` → the foreign package is removed and
   perk's own `ask_user_question` tool returns on the next launch.

There is **no adapter shim** (`adapter: null`), no injected context, and no durable artifact — the
seam's whole contract is the tool name plus its non-terminating-answer semantics. Headless SDK child
sessions are unaffected: `SDK_READ_ONLY_TOOLS` does not include `ask_user_question` (headless
children never prompt a human), and that is unchanged.
