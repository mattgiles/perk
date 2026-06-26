"""Init's committed TOML templates, the post-init handoff, and the config scaffold."""

from pathlib import Path

from perk.substrate.output import user_confirm
from perk.substrate.paths import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME

PERK_TOML_TEMPLATE = """\
# perk project config (committed). Edit freely; per-user overrides go in
# .pi/perk.local.toml (gitignored). The schema grows as perk does.

[worktree]
# Where `perk worktree create` and cold-door stages place worktrees.
# Relative paths resolve against the repo root.
root = ".worktrees"

# Worktree setup hook (optional) — shell commands run, in order, inside each
# freshly created worktree before pi starts (via `bash -lc`, cwd = the worktree).
# Use it to prepare the environment (dependency installs, codegen). A non-zero
# exit ABORTS the launch (re-run after fixing — the worktree is reused). Skipped
# on resume/reuse and on the remote runner. Overlay-aware (a perk.local.toml
# [worktree] setup array replaces this one wholesale).
#
# setup = ["uv sync", "npm ci"]

# Skill bindings (optional) — attach a skill to a stage or command, delivered
# into that session. Each [[bindings]] row binds one trigger to one skill:
#   trigger — "<kind>:<id>"; kind is `stage` or `command`.
#               stage:<id>   fires at that stage's launch / session entry.
#                            (ids: plan, implement, address, learn,
#                             objective-author, objective-plan, … — see
#                             `perk registry`.)
#               command:<id> fires when that perk command runs.
#                            (deliverable: objective-reconcile, learn-docs.)
#   skill   — a skill name installed under .agents/skills/<name>/.
#   mode    — `nudge` delivers a short pointer to follow the skill (its body
#             stays ambient / Pi-discovered); `transclude` inlines the skill's
#             SKILL.md into the prompt. Pick `nudge` for an already-installed
#             skill Pi can find on its own; `transclude` to force the full body
#             in (heavier context, but guaranteed present).
# A row at a trigger perk already binds OVERRIDES perk's default there; a new
# trigger is added. `perk doctor` validates every binding's skill + target.
#
# [[bindings]]
# trigger = "stage:implement"
# skill = "house-style"
# mode = "nudge"
#
# [[bindings]]
# trigger = "command:learn-docs"
# skill = "house-style"
# mode = "transclude"

# Per-agent subagent models — override the model each perk-owned subagent uses
# (the frontmatter default in .pi/agents/<name>.md is used when unset). Set a
# per-user override in .pi/perk.local.toml to avoid dirtying this file.
#
# [subagents]
# pr-reviewer = "anthropic/claude-sonnet-4-5"
# review-classifier = "anthropic/claude-haiku-4-5"
# objective-explorer = "anthropic/claude-haiku-4-5"
# conflict-resolver = "anthropic/claude-sonnet-4-5"

# CI checks (optional) — named checks the `run_ci` tool / `/ci` command run and
# REPORT pass/fail (they never edit or fix). Each [[ci]] row is name/command plus
# an optional `glob` (a comma-separated pattern string); a check with a `glob` is
# SKIPPED on the run-all path when no changed file (vs the repo's trunk) matches
# it — so a docs-only change reports success fast. A row without `glob` always
# runs. Project-supplied CI is untrusted by default (see [trust] below).
#
# [[ci]]
# name = "lint"
# command = "just lint"
# glob = "*.py,*.ts"
#
# [[ci]]
# name = "test"
# command = "just test"

# Trust (optional) — declare parts of this repo trusted so perk skips a safety
# prompt. With `ci = "true"`, the [[ci]] checks above run WITHOUT a per-session
# confirm (and headless runs need no --allow-project-ci). Leave it unset for
# cloned/untrusted repos. Value is a quoted string. The table may grow later.
#
# [trust]
# ci = "true"

# Interactive auto-compaction — tunes pi's global compaction for `perk <stage>`
# sessions by converging the specified keys into .pi/settings.json's `compaction`
# object (pi reads that natively at session boot). Keys are committed-only (read
# from THIS file, never the perk.local.toml overlay) so the committed settings.json
# stays deterministic; per-user overrides belong in pi's global ~/.pi/agent/settings.json.
# Editing this requires re-running `perk init` (or `perk doctor --fix`) to converge.
# Removing this block leaves a stale settings.json `compaction` to clean up by hand.
#
# [compaction]
# enabled = true            # turn pi's auto-compaction on/off
# reserve_tokens = 16384    # tokens reserved for the response (pi default)
# keep_recent_tokens = 20000 # recent tokens kept verbatim (pi default)

# Issue backend (optional) — where canonical plan/learn/objective issues live.
# "github" (the default when unset) and "linear" are supported. Selecting
# "linear" requires `team` (the Linear team key, e.g. "ENG") and a personal
# LINEAR_API_KEY — set it in the environment, or in the gitignored
# .pi/perk.local.toml [linear] api_key (an exported env var wins); never in
# THIS committed file. The `backend`/`team` keys below are committed-only: read
# from THIS file, never from the perk.local.toml overlay (a per-user override
# would fragment the canonical issue store). `perk init` converges the
# npm:pi-mono-linear Pi package when linear is selected (and removes it when
# deselected).
#
# [issues]
# backend = "linear"
# team = "ENG"
"""

PERK_LOCAL_TOML_TEMPLATE = """\
# perk per-user local overrides (gitignored). Mirrors .pi/perk.toml's shape; values
# here win over the committed config. Example:
#   [worktree]
#   root = "/abs/path/to/worktrees"
#
# A local [[bindings]] array REPLACES the committed [[bindings]] array wholesale
# (whole-array override, not element-wise merge — unlike scalar leaf-merge).
#
# Linear API key (optional) — a personal Linear API key, used by perk's Linear
# issue backend AND the in-session linear_* tools. ONLY read from this gitignored
# file (never the committed perk.toml). An exported LINEAR_API_KEY env var wins.
#
# [linear]
# api_key = "lin_api_…"
"""

# The post-init handoff — an agent-readable markdown on-ramp (distinct from the
# machine run-handoff JSON). Regenerated each init; kept true to what's built.
POST_INIT_TEMPLATE = """\
# perk is initialized ({mode})

This repo follows the **perk** plan-oriented workflow on Pi. Conventions live in `AGENTS.md`
(the perk-managed block). `perk init` owns all Pi wiring and is safe to re-run.

The spine `plan -> save -> implement -> submit -> land -> learn` is **closed and deepened**
(Phase 2 complete): perk-owned plan mode + tool-gating, a read-only CI executor, the
`/address` review loop, and objectives as plan factories. `objective-plan` is the new initial
node (select the next actionable objective node, emit a bounded plan); `/address` sits between
`submit` and `land` (classify review feedback, resolve threads).

**Start here:** `perk plan` (or `perk objective plan` to drive from an objective roadmap)
mints a `run_id`, positions a worktree, and launches a primed `pi` session. `perk resume`
resolves any plan to its current actionable stage. `perk doctor` reports on this setup.
"""


def converge_config(
    root: Path, changes: list[str], *, force: bool = False, interactive: bool = True
) -> None:
    """Scaffold the committed + local TOML config.

    Seeded once; never overwritten — *unless* ``force`` re-seeds it back to the template
    (confirmed when ``interactive``). This is the one mildly-destructive init op.
    """
    pi_dir = root / ".pi"
    pi_dir.mkdir(parents=True, exist_ok=True)
    for name, template in (
        (CONFIG_FILENAME, PERK_TOML_TEMPLATE),
        (LOCAL_CONFIG_FILENAME, PERK_LOCAL_TOML_TEMPLATE),
    ):
        path = pi_dir / name
        if not path.is_file():
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: created")
        elif force and path.read_text(encoding="utf-8") != template:
            if interactive and not user_confirm(f"Re-seed .pi/{name} to defaults?", default=False):
                continue
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: re-seeded")
