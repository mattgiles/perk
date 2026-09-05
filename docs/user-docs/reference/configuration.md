---
title: "Configuration files"
description: "Precedence, overlay semantics, value types, and the table map for perk's repository configuration."
sidebar:
  order: 3030
---

# Configuration files

This is the stable orientation page for perk's repository configuration. It explains the two
configuration files, their precedence and value types, then routes each table to its exact-detail
reference. The table entries are human-reviewed against perk's Python and TypeScript config
readers and the `perk init` templates; unlike CLI `--help`, they do not come from one
introspectable schema.

## Orientation

perk reads two files under `.perk/`:

- **`.perk/config.toml`** — the committed project config, shared by everyone working in the repo.
  It is also perk's repo **initialization marker**.
- **`.perk/local.toml`** — a gitignored, per-user overlay for personal settings and secrets.

[`perk init`](./cli/setup-and-health.md#perk-init) scaffolds both with a commented template, and
[`perk doctor`](./cli/setup-and-health.md#perk-doctor) validates them. See the
[Repository layout](./configuration/repository-layout.md) reference for the complete ownership and
lifecycle contract.

> **Migrating from `.pi/perk.toml`.** perk's config used to live at `.pi/perk.toml` /
> `.pi/perk.local.toml`. A repo still carrying only the legacy committed file makes `perk init`
> **refuse** (with a `perk doctor --fix` remediation) rather than re-scaffold over it. Run
> [`perk doctor --fix`](./cli/setup-and-health.md#perk-doctor): it migrates the config to `.perk/` secret-safely
> (the gitignored `.pi/perk.local.toml` secret moves to `.perk/local.toml` and is never promoted
> into the committed file), then re-run `perk init`.

> **Breaking: config schema v2.** There is **no migration tooling and no dual-read**. Pre-v2
> spellings hard-fail every `perk` command with a pointer to the new home. Rename map:
> `[stages.<id>]` → `[models.stages.<id>]` · `[subagents]` → `[models.subagents]` ·
> `[models] model` → `[models] default` · `[[ci]]` → `[[ci.checks]]` ·
> `[trust] ci = "true"` → `[ci] trusted = true` ·
> `[objective] compact_threshold = "0.8"` → `[compaction] objective_threshold = 0.8`.
> Types are now honest: `trusted` is a native boolean and `objective_threshold` a native float.

## Local overrides & overlay semantics

How the two files combine:

1. `.perk/local.toml` recursively overlays `.perk/config.toml`: local scalar leaves win.
2. Local `[[bindings]]` and `[[ci.checks]]` arrays **replace** their committed arrays wholesale;
   arrays do not merge row by row.
3. Keys perk **converges into committed artifacts** ignore the overlay: `[models]`
   `default`/`thinking`, `[compaction]` `enabled`/`reserve_tokens`/`keep_recent_tokens`, and
   `[issues]` are read from `.perk/config.toml` only. This keeps the canonical issue store and
   committed `.pi/settings.json` deterministic.
4. Keys **read at runtime** honor the overlay: `[models.stages.<id>]`, `[models.subagents]`,
   `[ci]`, `[compaction] objective_threshold`, `[workflow]`, `[worktree]`, `[providers]`,
   `[skills]`, `[pi]`, and `[[bindings]]`. For `[pi] agent_dir`, **both files are read from
   the main checkout**, even when launching from a linked worktree; worktree-local edits to
   either file are not consulted.
5. `[linear] api_key` is the local-only exception: it is read only from `.perk/local.toml`, and
   the `LINEAR_API_KEY` environment variable takes precedence over it.

## Tables

| Family | Owned tables or surface | Use it to answer |
| --- | --- | --- |
| [Repository layout](./configuration/repository-layout.md) | The dot-directory ownership and lifecycle contract | Where a perk-relevant path lives, who owns it, whether it is versioned, and how it is materialized. |
| [Workflow and CI](./configuration/workflow-and-ci.md) | `[worktree]`, `[workflow]`, `[ci]`, `[[ci.checks]]` | Where work is placed, how plans choose a base, and how configured checks run. |
| [Backends](./configuration/backends.md) | `[providers]`, `[issues]`, `[linear]` | Which provider seams and issue backend are selected and where local Linear credentials resolve. |
| [Models and compaction](./configuration/models-and-compaction.md) | `[models]`, `[models.stages.<id>]`, `[models.subagents]`, `[compaction]`, `[pi]` | Which AI defaults apply, where Pi's agent config is stored, and how session context is managed. |
| [Skills and bindings](./configuration/skills-and-bindings.md) | `[skills]`, `[[bindings]]`, repo-authored `.perk/skills/` | Which skills are exposed, how bindings deliver them, and how repository skills are maintained. |

## A note on value types

Types are **honest** in config schema v2: booleans are native booleans (`trusted = true`) and
numbers are native numbers (`objective_threshold = 0.8`, `reserve_tokens = 16384`). The old rule
that TypeScript-read keys had to be quoted strings is gone. The TypeScript reader accepts the
native boolean and number forms for the keys it consumes; a quoted `"true"` does not grant CI
trust, and a quoted `"0.8"` objective threshold is ignored.

Python-read keys are **validated at load**. An ill-typed value such as `base = 7` under
`[workflow]` fails `perk` commands with a field-path error
(`workflow.base: Input should be a valid string`), and
[`perk doctor`](./cli/setup-and-health.md#perk-doctor) pinpoints the bad field in its `config` check. The
`[compaction]` integers must be positive native integers: a quoted numeric string such as
`"16384"` is accepted by coercion, but a bare boolean such as `reserve_tokens = true` is rejected.
Legacy tables and keys (`[trust]`, `[objective]`, `[subagents]`, `[stages.<id>]`, `[[ci]]`, and
`[models] model`) hard-fail with the new location instead of being silently dropped.

## Related

- **Look up:** [Setup and health](./cli/setup-and-health.md) — the exact `perk init` and
  `perk doctor` reference.
- **Look up:** [In-session commands & tools](./in-session.md) — the warm `/…` commands and
  model-facing tools.
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md) — the workflow model
  behind the settings.
