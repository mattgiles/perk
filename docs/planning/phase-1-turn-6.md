# Phase 1 · Turn 6 — prek pre-commit ruff hook

> Small devex turn (perk plan [#1](https://github.com/mattgiles/perk/issues/1)): wire a
> [prek](https://prek.j178.dev) git pre-commit hook that runs `ruff check` on staged Python,
> so lint regressions are caught at commit time without depending on a system/`.venv` ruff
> being on PATH.

---

## 1. Decisions (locked in the issue thread)

1. **Remote repo, not a `local` hook.** `prek.toml` uses
   `repo = "https://github.com/astral-sh/ruff-pre-commit"`. prek clones that repo and builds
   the ruff env via `uv` itself, so the hook is **PATH-free** — it never relies on a system or
   `.venv` ruff. The cost is a second ruff pin (the repo `rev`).
2. **Plain check, no mutation.** A single `ruff-check` hook (the current non-deprecated id),
   lint-only — **no `--fix`, no `ruff-format`**. The hook reports; it does not rewrite files on
   commit. (`--config pyproject.toml` is passed explicitly though redundant with ruff's
   auto-discovery.)
3. **Pin in lockstep.** `rev = "v0.15.15"` is aligned to the `dev`-group `ruff>=0.15.15` floor
   in `pyproject.toml`. `prek auto-update` can bump `rev` but won't read `pyproject.toml`, so the
   two are kept aligned by hand; the T6 verify gate fails if they drift.

## 2. Scope

- `prek.toml` — the config (one ruff-check hook, pinned remote repo).
- `justfile` — a `hooks:` recipe (`prek install`) folded into `setup:` as a dependency.
- `README.md` — a Develop-section note on the hook + `just hooks` after a fresh clone.
- `scripts/verify-p1-t6.sh` — an **offline** hard gate (config validity, rev↔floor lockstep,
  setup wiring), wired into `just verify`.

It does **not** add `--fix`/format-on-commit, extra hooks (trailing-whitespace etc.), or a
network-dependent "hook actually runs" check in CI (the gate stays offline).

## 3. Outcomes

Built as planned. `prek validate-config prek.toml` passes; `prek install` writes the
pre-commit shim; `prek run ruff-check --all-files` passes against the current tree. The T6 gate
is green and folded into the cumulative `just verify`. No cross-plane contract change (this is a
dev-tooling-only turn).
