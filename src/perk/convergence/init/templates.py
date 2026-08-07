"""Init's committed TOML templates, the post-init handoff, and the config scaffold."""

from pathlib import Path

from perk.substrate import paths
from perk.substrate.output import user_confirm
from perk.substrate.paths import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME

PERK_TOML_TEMPLATE = """\
# perk project config (committed). Edit freely; per-user overrides go in
# .perk/local.toml (gitignored). Schema principle: every top-level header
# answers one operator question; structure encodes relationships (model
# precedence is visible as nesting). Overlay rule: keys perk converges into
# committed artifacts ([models] default/thinking, [compaction]'s settings keys,
# [issues]) ignore .perk/local.toml; keys read at runtime honor it
# ([models.stages.*], [models.subagents], [ci], [compaction]
# objective_threshold, [workflow], [worktree], [providers], [[bindings]]).

# ═══ Which AI runs where (precedence = nesting: flag > stage > default) ═══

# Repo-default model + thinking (optional) — converged by `perk init` into
# .pi/settings.json defaultProvider/defaultModel/defaultThinkingLevel, which pi
# reads natively at session boot. Applies to every pi session in the repo: perk
# cold doors, plain `pi`, and the headless worker (local + remote). Per-door
# overrides win: [models.stages.<id>] below, and an explicit `perk <stage>
# --model X`. `default` must be exact `provider/id` (pi's settings default is
# an exact lookup); a `:thinking` suffix on `default` also works (an explicit
# `thinking` key wins). Committed-only (a local.toml [models] default/thinking
# is ignored); removing the keys leaves the settings.json keys in place to
# clean up by hand.
#
# [models]
# default = "anthropic/claude-opus-4-1"
# thinking = "high"

# Per-stage model + thinking defaults (optional) — injected as pi `--model` /
# `--thinking` flags when `perk <stage>` cold-launches that stage's pi session.
# Either key may be set alone; an unset key leaves pi's own default untouched (no
# enforced perk default). A user-passed `perk <stage> --model X` wins (the config
# flag is injected first; pi parses last-wins). Overlay-aware (a local.toml
# [models.stages.<id>] leaf-merges over these). Valid stage ids: the registry
# stages (plan, implement, address, learn, objective-author, objective-plan, …
# — see `perk registry`). Thinking ∈ off/minimal/low/medium/high/xhigh. A
# `model:thinking` suffix also works (pi `--model` accepts it). `perk doctor`
# validates the configured stage ids + thinking levels (loud-but-non-fatal).
#
# [models.stages.implement]
# model = "anthropic/claude-opus-4-1"
# thinking = "high"
#
# [models.stages.plan]
# thinking = "xhigh"

# Per-agent subagent models (optional) — override the model each perk-owned
# subagent uses (the frontmatter default in .pi/agents/<name>.md is used when
# unset). Set a per-user override in .perk/local.toml to avoid dirtying this
# file. A `model:thinking` suffix sets that agent's thinking level (e.g.
# pr-reviewer = "anthropic/claude-sonnet-4-5:high"); the special value
# "inherit" makes the agent inherit the parent session's model.
#
# [models.subagents]
# pr-reviewer = "anthropic/claude-sonnet-4-5"
# review-classifier = "anthropic/claude-haiku-4-5"
# objective-explorer = "anthropic/claude-haiku-4-5"
# conflict-resolver = "anthropic/claude-sonnet-4-5"
# learn-analyst = "anthropic/claude-sonnet-4-5"
# adversarial-reviewer = "anthropic/claude-fable-5"
# review-angle-selector = "anthropic/claude-opus-5"

# ═══ How work is verified — and whether it's trusted ═══

# `trusted = true` (a native boolean) declares the [[ci.checks]] commands below
# trusted: they run WITHOUT a per-session confirm (and headless runs need no
# --allow-project-ci). Leave it unset for cloned/untrusted repos.
#
# [ci]
# trusted = true

# CI checks (optional) — named checks the `run_ci` tool / `/ci` command run and
# REPORT pass/fail (they never edit or fix). Each [[ci.checks]] row is
# name/command plus an optional `glob` (a comma-separated pattern string); a
# check with a `glob` is SKIPPED on the run-all path when no changed file (vs
# the repo's trunk) matches it — so a docs-only change reports success fast. A
# row without `glob` always runs. Project-supplied CI is untrusted by default
# (see `trusted` above).
#
# [[ci.checks]]
# name = "lint"
# command = "just lint"
# glob = "*.py,*.ts"
#
# [[ci.checks]]
# name = "test"
# command = "just test"

# ═══ How the loop fits this repo ═══

# base — the default target branch plans/objectives base off (unset ⇒ the
# repo's default branch). plan_authoring — a project-supplied addendum appended
# into plan-authoring sessions' guidance.
#
# [workflow]
# base = "develop"
# plan_authoring = \"\"\"Always cite a file path.\"\"\"

# ═══ Where work happens ═══

[worktree]
# Where `perk worktree create` and cold-door stages place worktrees.
# Relative paths resolve against the repo root.
root = ".worktrees"

# Worktree setup hook (optional) — shell commands run, in order, inside each
# freshly created worktree before pi starts (via `bash -lc`, cwd = the worktree).
# Use it to prepare the environment (dependency installs, codegen). A non-zero
# exit ABORTS the launch (re-run after fixing — the worktree is reused). Skipped
# on resume/reuse and on the remote runner. Overlay-aware (a local.toml
# [worktree] setup array replaces this one wholesale).
#
# setup = ["uv sync", "npm ci"]

# ═══ What repo skills attach where ═══

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
#   mode    — `nudge` delivers a short pointer to follow the skill, carrying
#             its read path (works even for a skill hidden from the ambient
#             prompt via `disable-model-invocation: true`); `transclude`
#             inlines the skill's SKILL.md into the prompt — heavier context,
#             but the full body is guaranteed present.
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

# ═══ Where canonical state lives ═══

# Issue backend (optional) — where canonical plan/learn/objective issues live.
# "github" (the default when unset) and "linear" are supported. Selecting
# "linear" requires `team` (the Linear team key, e.g. "ENG") and a personal
# LINEAR_API_KEY — set it in the environment, or in the gitignored
# .perk/local.toml [linear] api_key (an exported env var wins); never in
# THIS committed file. The `backend`/`team` keys below are committed-only: read
# from THIS file, never from the local.toml overlay (a per-user override
# would fragment the canonical issue store). `perk init` converges the
# npm:pi-mono-linear Pi package when linear is selected (and removes it when
# deselected).
#
# [issues]
# backend = "linear"
# team = "ENG"

# ═══ Which pluggable piece fills each seam ═══

# Provider selection (optional) — pick which pluggable piece fills each seam
# (plan, todo, askuser, footer, web); bare provider ids from perk's
# supported set (see `perk providers`). Absent keys use the seam default.
#
# [providers]
# plan = "plannotator-plan"

# ═══ How the session manages its context ═══

# Interactive auto-compaction — tunes pi's global compaction for `perk <stage>`
# sessions by converging the settings keys (enabled/reserve_tokens/
# keep_recent_tokens) into .pi/settings.json's `compaction` object (pi reads
# that natively at session boot). Those keys are committed-only (read from THIS
# file, never the local.toml overlay) so the committed settings.json stays
# deterministic; per-user overrides belong in pi's global
# ~/.pi/agent/settings.json. Editing them requires re-running `perk init` (or
# `perk doctor --fix`) to converge; removing them leaves a stale settings.json
# `compaction` to clean up by hand. `objective_threshold` is the odd one out:
# read at runtime (overlay-aware) — the context-usage fraction (0,1] that
# triggers compaction while an objective is active.
#
# [compaction]
# enabled = true            # turn pi's auto-compaction on/off
# reserve_tokens = 16384    # tokens reserved for the response (pi default)
# keep_recent_tokens = 20000 # recent tokens kept verbatim (pi default)
# objective_threshold = 0.8 # compact when an objective session crosses this
"""

PERK_LOCAL_TOML_TEMPLATE = """\
# perk per-user local overrides (gitignored). Mirrors .perk/config.toml's shape; values
# here win over the committed config for runtime-read keys (committed-converged keys —
# [models] default/thinking, [compaction]'s settings keys, [issues] — ignore this file).
# Example:
#   [models.stages.implement]
#   thinking = "xhigh"
#
# A local [[bindings]] array REPLACES the committed [[bindings]] array wholesale
# (whole-array override, not element-wise merge — unlike scalar leaf-merge).
#
# Linear API key (optional) — a personal Linear API key, used by perk's Linear
# issue backend AND the in-session linear_* tools. ONLY read from this gitignored
# file (never the committed config.toml). An exported LINEAR_API_KEY env var wins.
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
    # Construct every config-family target through the `paths` seam (the single redirection point
    # for the family) so a later move of the family is a localized edit there — no hand-built
    # `.perk/...` here.
    paths.config_dir(root).mkdir(parents=True, exist_ok=True)
    for name, path, template, legacy in (
        (
            CONFIG_FILENAME,
            paths.config_file(root),
            PERK_TOML_TEMPLATE,
            paths.legacy_config_file(root),
        ),
        (
            LOCAL_CONFIG_FILENAME,
            paths.local_config_file(root),
            PERK_LOCAL_TOML_TEMPLATE,
            paths.legacy_local_config_file(root),
        ),
    ):
        # Legacy-safe seeding guard: never warn-and-seed a fresh template over an unmigrated
        # legacy config (belt-and-suspenders for the doctor `_fix_config` path; init itself
        # refuses legacy-only earlier). The doctor migration moves the legacy file first.
        if not path.is_file() and legacy.is_file():
            continue
        if not path.is_file():
            path.write_text(template, encoding="utf-8")
            changes.append(f".perk/{name}: created")
        elif force and path.read_text(encoding="utf-8") != template:
            if interactive and not user_confirm(
                f"Re-seed .perk/{name} to defaults?", default=False
            ):
                continue
            path.write_text(template, encoding="utf-8")
            changes.append(f".perk/{name}: re-seeded")
