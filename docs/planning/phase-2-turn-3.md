# Phase 2 · Turn 3 — enforce formatting via a prek `ruff-format` hook

> Implementation-level plan for **P2.T3**. The Phase-2 decomposition (`docs/phase-2-plan.md`)
> proposed a `tool_result` post-edit formatter middleware (the Pi analogue of erk's PostToolUse
> Ruff-on-edit). This turn **declines the middleware** and instead meets its load-bearing goal —
> *formatting never becomes a CI iteration* — with a one-line addition to `prek.toml`: a
> `ruff-format` pre-commit hook alongside the existing `ruff-check` hook.
>
> The canonical plan (decisions, full key-changes list, test plan, assumptions) is GitHub plan
> issue **#7**. This doc records the decision, the prior-art / spike pass, and the **outcomes**.
> Per repo convention, plan bodies are historical records — the deviation from `docs/phase-2-plan.md`
> is reconciled here, not by rewriting the P2.T3 decomposition.

---

## 1. The decision

P2.T3 as decomposed proposed a `tool_result` middleware to reformat files after each `edit`.
This turn declines it in favor of a **commit-time `ruff-format` prek hook** (Option A).

**Rationale.** prek currently wires only `ruff-check` (lint, non-mutating), so there is no local
*format* enforcement today — a `ruff-format` hook is **not** redundant with anything that exists.
The middleware's only unique benefit over a commit-time hook is mid-session canonical formatting,
which is marginal because pi's `edit` tool re-reads files before editing. The
CI-iteration-avoidance goal is met equally by the commit hook, with far less moving machinery
(no session interior code, no per-edit subprocess, no headless-safety surface).

The two hooks differ in stance deliberately:
- **`ruff-check`** stays **report-only** (no `--fix`, no mutation) — unchanged.
- **`ruff-format`** **mutates** (reformats staged Python and fails the commit if it changed
  anything; the dev re-stages and commits). The `prek.toml` header note that "the hook reports, it
  does not mutate files" is now scoped to the lint hook, not generalized to all hooks.

## 2. Prior-art / spike pass

**Worktree hook semantics (verified evidence).** The implement cold door commits inside worktrees,
so the hook must fire there:
- `.git/hooks/pre-commit` is prek-generated and lives in the **common** git dir.
- Per-worktree gitdirs (`.git/worktrees/<name>/`) contain `commondir` + `gitdir` + `HEAD` +
  `index` + `refs/` but **no `hooks/` dir**, so git resolves hooks to the shared common dir;
  commits in any worktree run the same hook.
- No `core.hooksPath` override exists in `.git/config`.
- perk never runs `git commit` itself (no commit invocation in `perk/`; `perk/launch.py`'s
  implement prompt instructs the *agent* to commit; `merge_pr` uses the GitHub squash-merge API),
  so the agent's worktree commits are normal commits that trigger the hook.
- **Conclusion:** install once via `prek install` (`just setup` / `just hooks`) and the hook covers
  every worktree the implement cold door creates.

**Caveats (documented, not blocking).** The hook fires only if `prek install` ran in the clone
(already true of today's `ruff-check` hook); it is not a CI-side guarantee (fork PRs / skipped
setup / `--no-verify` bypass it). perk has no `.github/workflows` of its own, so the local hook +
the `just verify` gate are the enforcement surface.

## 3. Files

- **`prek.toml`** — add `{ id = "ruff-format", types_or = ["python", "pyi"], args = ["--config",
  "pyproject.toml"] }` to the `astral-sh/ruff-pre-commit` `[[repos]]` block (pin unchanged); scope
  the "reports, does not mutate" note to the lint hook.
- **`justfile`** — `hooks:` recipe comment now reads "ruff lint + format hooks"; `verify:` recipe
  gains `bash scripts/verify-p2-t3.sh` after `verify-p2-t2c.sh`.
- **`scripts/verify-p2-t3.sh` (new)** — four offline checks (format hook present, lint hook
  preserved, rev pin intact, tree format-clean).
- **Tree reformat** — `uv run ruff format perk tests` run once so the new hook does not block the
  first subsequent commit.

This is **dev-tooling only** for perk's own repo — not part of `perk init`'s managed convergence
(`prek.toml` is perk's own pre-commit config, not wiring emitted into consumer repos). No
cross-plane behavior change, so `shared/contracts.md` needs no amendment this turn.

## 4. Outcomes

Built as planned. Notes:

- **Config change is one hook entry.** `prek.toml` now wires both `ruff-check` (report-only) and
  `ruff-format` (mutating), with the pin held at `rev = "v0.15.15"`.
- **Tree reformat touched one file.** `uv run ruff format perk tests` reformatted a single file
  (`tests/test_plan.py`); committed in this turn so the new hook is a no-op on the next commit.
- **Verify gate is offline + degrades gracefully.** `scripts/verify-p2-t3.sh` skips the
  format-clean check with a clear message when `uv`/`ruff` is unavailable, mirroring the other
  gates; the three static `prek.toml` checks always run.
