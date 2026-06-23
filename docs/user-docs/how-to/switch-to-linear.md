# How to switch the issue backend to Linear

Move perk's canonical plan / learn / objective issue store from GitHub (the default) to Linear. This
is a committed, repo-wide switch: it changes where issues live, the identifier shape, and the
branch/footer naming for everyone working in the repo.

**Prerequisite:** a Linear team you can use (its key, e.g. `ENG`) and a personal Linear API key. The
`[issues]` keys are documented at key depth in the
[configuration reference](../reference/configuration.md#issues); the full backend reference (auth,
labels, identifiers, doctor groups, maturity) is the
[providers & issue backends reference](../reference/providers-and-backends.md#issue-backend--linear-reference).

> **Maturity:** the Linear backend is validated offline against fakes **and** was **live-validated
> on 2026-06-15** — the Mode 1 lifecycle (`plan → implement → submit → land → learn`) plus the
> issue-backed objective loop ran green against a real workspace, with a clean ProseMirror
> round-trip. Read the
> [Known caveats & maturity](../reference/providers-and-backends.md#known-caveats--maturity) section
> for what remains deferred (Mode 2 / agent-session emission / the node-1.2 hardenings).

## Steps

1. **Set the `[issues]` table** in `.pi/perk.toml`. This is **committed-only** — a
   `.pi/perk.local.toml` value is ignored, so the canonical store stays deterministic for the whole
   repo.

   ```toml
   [issues]
   backend = "linear"
   team = "ENG"
   ```

   `team` is the Linear team key and is required when `backend = "linear"`.

2. **Supply `LINEAR_API_KEY`.** A personal API key from linear.app → Settings → Security & access.
   Either export it as an environment variable:

   ```sh
   export LINEAR_API_KEY=lin_api_…
   ```

   or set it in the **gitignored** `.pi/perk.local.toml` (never the committed `.pi/perk.toml`):

   ```toml
   [linear]
   api_key = "lin_api_…"
   ```

   An exported env var wins over the config. Setting it in `perk.local.toml` also feeds the
   in-session `linear_*` tools (perk seeds the launched session's environment with the key). perk
   reads this from the **main checkout's** `.pi/perk.local.toml` even when a command runs inside a
   linked worktree (the gitignored file is never copied into worktrees), so a single entry in the
   main checkout authenticates every worktree session and cold-door (`/submit`, `/land`, …).

3. **Run `perk init --verify`.** This converges the borrowed Linear-tools package
   `npm:pi-mono-linear` into `.pi/settings.json` `packages`, and the readiness probe ensures the
   five perk labels on the workspace: `perk:plan`, `perk:learn`, `perk:consolidated`,
   `perk:objective`, and `perk:objective-node`. perk creates them **workspace-scoped** (not
   team-scoped), matching Linear's guidance for cross-team labels.

4. **Run `perk doctor` and verify green.** Check the offline `issues-backend` check (selection +
   `team`) and the verify-gated `linear` group: `linear-auth`, `linear-team`, `linear-labels`,
   `linear-project-scopes`, `linear-workflow-states` (`linear-labels` now covers all **five** perk
   labels). These network probes are always non-fatal
   `warn`, so read them to confirm auth and labels resolved. The last two confirm Project
   read-access and the workflow states the node-status board mirror needs for project-backed
   objectives.

## What changes

Once Linear is the backend, issue identifiers become **strings** (`ENG-123`) instead of GitHub's
`#42`. That shape propagates to:

- the worktree / branch name — `plan-ENG-123`,
- the land squash-commit footer — `Plan: ENG-<n> — <url>` (no `Closes #N`).

perk also makes its Linear footprint read natively, rather than as a foreign body:

- **Attribution.** Every perk-created issue (plan, learn, objective, roadmap node) is **assigned
  to you** (the API-key user), so it shows up in your *My Issues*; every objective **Project** has
  you as its **lead** and a **start date** (which Linear's project graph requires).
- **Project status.** A project-backed objective advances to **In Progress** automatically when
  its first node starts, and to **Completed** when the objective lands.
- **Roadmap labels.** Roadmap node-issues carry the `perk:objective-node` label so you can filter
  them in Linear (they're still discovered by project membership, so the label is purely for you).
- **PR links as attachments.** When a plan's PR is stamped, perk posts a native **sidebar
  attachment** card (`GitHub PR #N`) on the Linear issue, updated in place on every push.
- **Unobtrusive metadata.** perk's bookkeeping blocks render **below** the human prose (prose
  first) in inline-code form — no raw HTML-comment markers, no `<details>` artifacts. (A native
  collapsed-toggle wrapper is a pending enhancement, gated on a live round-trip check; until then
  the blocks render prose-first but expanded.)

These are all **Linear-only**; the GitHub backend is unchanged. perk authenticates as **you** (a
personal API key), not as a Linear Agent — full Agent integration is a separate, future effort.

## Switching back

Set `backend = "github"` (and drop `team`) in `.pi/perk.toml`, then run `perk init` — convergence is
two-directional, so the `npm:pi-mono-linear` package is removed when Linear is deselected.

## See also

- [Providers & issue backends reference — Linear](../reference/providers-and-backends.md#issue-backend--linear-reference)
  — auth, labels, identifiers, doctor groups, and the maturity register.
- [Configuration reference — `[issues]`](../reference/configuration.md#issues) — the config keys and
  committed-only semantics.

---

← Back to the [how-to router](index.md).
