# Smoke: the `juicesharp-todo` foreign todo provider (Objective #115, Node 3.2)

**Status:** validation record for the first 3rd-party todo adapter (`todoAdapterJuicesharp`).
*2026-08 note (Objective #1416): the smoked selection mechanism — `[providers] todo`, the runtime
deferral, the adapter shim — no longer exists; the package is a required borrowed built-in
(`BORROWED_PACKAGES`). The recorded smoke evidence stands as history; the zero-config
borrowed-built-in reality is smoked in `borrowed-askuser-todo-dogfood.md`.* Node
3.2's explicit mandate is to *validate the todo provider contract against a real foreign surface*.
The unit harness loads **only** perk's extension (not the foreign package), so it can prove perk's
runtime deferral (Node 3.1) and the shim's injection in isolation, but **not** the true coexistence
(the foreign `@juicesharp/rpiv-todo` overlay actually present, with no command-name collision). This
doc is the end-to-end smoke that closes that gap: a runnable procedure on a scratch repo + the
recorded result.

## What the unit tests already cover (no smoke needed)

- `extension/checkpoints.test.ts` — under `[providers] todo = "juicesharp-todo"`, perk's checkpoints
  **defer**: `session_start` seeds no `perk:checkpoint` entry and renders no status (silent), while
  `/checkpoints` **announces** the deferral (Node 3.1).
- `extension/todoAdapterJuicesharp.test.ts` — under `juicesharp-todo` **and an active workflow** the
  shim injects the `perk:todo-adapter-juicesharp` bridge context (`[TODO ADAPTER: JUICESHARP]`,
  directing the model to seed the overlay from `## Steps`); under no active workflow it injects
  nothing (active-workflow gate); under the default selection it injects nothing and strips any stale
  marker.
- `extension/providers.test.ts` / `tests/test_providers.py` — the real entry has **no**
  `package_filter`.
- `tests/test_init_idempotent.py` — selecting `juicesharp-todo` wires `{"source":
  "npm:@juicesharp/rpiv-todo"}` (object form, no filter); deselecting removes it; idempotent.

## The runnable smoke (deterministic half — recorded result)

The `perk init` wiring half is fully deterministic and was run on a scratch repo from this worktree:

```sh
mkdir /tmp/perk-smoke-32 && cd /tmp/perk-smoke-32 && git init -q
mkdir .pi && printf '[providers]\ntodo = "juicesharp-todo"\n' > .pi/perk.toml
<worktree>/.venv/bin/perk init --no-interactive
```

**Recorded result (select):** `.pi/settings.json` `packages` gains the foreign package in **object
form with no filter** —

```json
{ "source": "npm:@juicesharp/rpiv-todo" }
```

— i.e. the real entry carries no `package_filter` (single-concern checklist overlay), so Pi loads its
bundled extension and the foreign overlay surface actually registers.

**Recorded result (deselect):** setting `[providers] todo = "perk-checkpoints"` and re-running `perk
init` prints `removed @juicesharp/rpiv-todo` and the entry is gone from `packages`; the
borrowed/user packages survive untouched.

## The coexistence half (manual, requires a live `pi` session)

Unlike the plan seam, the todo seam needs **no registration-time vacating** — perk registers
`/checkpoints`, the foreign overlay registers its own differently-named command(s), so there is no
duplicate-name collision and no Pi `:N` suffixing. Node 3.1's runtime deferral is sufficient. To
confirm against the real foreign surface, in a repo with `juicesharp-todo` selected and `perk init`
run:

1. Launch `pi`. The foreign `@juicesharp/rpiv-todo` overlay's command/surface registers with **no
   `/checkpoints` collision and no `:N` suffix** (validating Correction 1 — no command-name clash on
   the todo seam).
2. In an **active implement workflow** (a worktree with `active_plan_ref`), the shim injects the
   `perk:todo-adapter-juicesharp` bridge context. The assistant seeds the foreign overlay from the
   plan body's `## Steps` (one checklist item per step, in order) and marks each item complete as it
   finishes the step — perk's implement-progress discipline carried onto the foreign overlay.
3. perk emits **no competing checkpoint status** (Node 3.1 deferral): no `perk:checkpoint` entry, no
   progress status/widget; the overlay is the sole, uncontested progress surface. (perk's
   `[WIP:n]`/`[DONE:n]` markers remain harmless no-ops here — the checkpoint scanner is deferred.)
4. Deselect (or set back to `perk-checkpoints`) + `perk init` → the foreign package is removed and
   perk's own `/checkpoints` surface returns on the next launch.

The shim never owns the read-only gate, never `setActiveTools`, never writes `perk:checkpoint`, and
never restamps any provider field — the todo seam's dimension-7 isolation guarantee holds.
