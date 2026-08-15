---
title: "Repository layout"
description: "The canonical owner, lifecycle, and version-control status of every perk-relevant path in a wired repository."
sidebar:
  order: 3031
---

# Repository layout

## Repository layout — the dot-directory contract

This is the canonical file-location reference for a perk-wired repo: every perk-relevant path,
who owns it, and how it lives in git. It is the single source of truth for "where does X live?"
questions; the rest of perk's docs link here rather than re-deriving the topology.

**Ownership vs. discovery.** `.perk/` is the authoritative, **perk-owned** dot-directory — perk's
committed source (`config.toml`, repo-authored `skills/`) plus its local cache (`workflow/`,
`local.toml`). `.pi/` and `.agents/` are **discovery** namespaces owned by their host tools — Pi
and the skills CLI, respectively. perk writes a few **generated materializations** into those
namespaces because that is where the host tool looks for them, but `.pi/` is **not** generally
perk-owned: it is Pi's directory with a perk-managed slice.

| Path | Owner | Lifecycle | Versioned |
| --- | --- | --- | --- |
| `.perk/config.toml` | maintainer / perk (the init marker) | committed | yes |
| `.perk/local.toml` | user | gitignored | no |
| `.perk/workflow/` | perk | gitignored (runtime cache) | no |
| `.perk/skills/<name>/SKILL.md` | maintainer / perk | committed | yes |
| `.perk/required-perk-version` | perk-generated (`perk init` / `doctor --fix`) | committed | yes |
| `.perk/managed-state.toml` | perk-generated (`perk init` / `doctor --fix`) | committed | yes |
| `.pi/settings.json` | Pi (perk-managed slice) | committed | yes |
| `.pi/npm/`, `.pi/git/` | Pi | gitignored | no |
| `.pi/agents/perk/*.md` | perk-generated (Pi materialization) | committed | yes |
| `.pi/APPEND_SYSTEM.md` | perk-generated (committed ambient index) | committed | yes |
| `.agents/manifest.yaml` | user / skills CLI | committed | yes |
| `.agents/manifest.d/perk*.yaml` | perk-generated (skills materialization) | committed | yes |
| `.agents/skills/`, `.agents/cache/` | skills CLI (runtime) | gitignored | no |
| `.worktrees/` | perk (worktrees) | gitignored | no |
| `.pi-subagents/` | pi-subagents (borrowed engine, runtime) | gitignored | no |

**One perk-owned path lives *outside* the repo.** `~/.perk/last-seen-version` is the user-level,
machine-local store behind the one-line post-upgrade notice (see
[`perk release-notes`](../cli/remote-and-utility.md#perk-release-notes)): the max perk version this user has run
interactively. It is self-healing (missing or garbled content is silently re-recorded) and safe
to delete; no doctor check or init convergence touches it.

**Pi-native materializations.** Two committed perk outputs live in Pi's namespace rather than
under `.perk/`, because Pi discovers them there: `.pi/APPEND_SYSTEM.md` (the generated ambient
routing index appended to every session's system prompt) and `.pi/agents/perk/` (perk's owned
slice of Pi's project-agent namespace). They are perk-generated and committed, but they are
framed as materializations into a host tool's directory — not evidence that `.pi/` is perk-owned.

## Related

- [Configuration files](../configuration.md) — file precedence, overlay semantics, and the table map.
- [How to diagnose a perk repo](../../how-to/diagnose-a-perk-repo.md) — investigate wiring and repair drift.
- [How perk thinks](../../explanation/how-perk-thinks.md) — the workflow model that uses these paths.
