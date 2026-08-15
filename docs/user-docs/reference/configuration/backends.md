---
title: "Backends"
description: "The [providers], [issues], and [linear] keys that select provider seams, the issue store, and local Linear credentials."
sidebar:
  order: 3033
---

# Backends

These tables select perk's provider seams and canonical issue store, and define the local-only
credential fallback for Linear. Supported-provider behavior and backend mechanics live in the
separate [Providers & issue backends](../providers-and-backends.md) reference.

## `[providers]`

Per-seam provider selection — provider-id strings pointing into perk's supported provider set.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan` | string | `perk-plan` | The plan-authoring provider. |
| `footer` | string | `perk-footer` | The footer provider (selectable: `powerline-footer`, `pi-bar-footer`, `pi-status-footer`, `pi-default`). |
| `web` | string | `pi-web-access` | The web search/fetch provider (selectable: `ollama-web-search`, `juicesharp-web-tools`). |

An absent key falls back to the behavior-preserving default. The retired `review`, `askuser`, and
`todo` keys **hard-fail config load** with removal guidance. The PR-review surface is picked by
the command itself (`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator). The
`ask_user_question` questionnaire tool is **built-in** (perk installs
`npm:@juicesharp/rpiv-ask-user-question` for every repo), and the todo checklist overlay is also
**built-in** (perk installs `npm:@juicesharp/rpiv-todo` for every repo). Remove `review`,
`askuser`, or `todo` from `[providers]` if present.

This is **config-key reference depth only**. The supported provider set, postures, and selection
mechanics are in the [Providers reference](../providers-and-backends/providers.md).

```toml
[providers]
plan = "perk-plan"
footer = "perk-footer"
web = "pi-web-access"
```

## `[issues]`

Where canonical plan, learn, and objective issues live. **Committed-only** — read from
`.perk/config.toml`, never the overlay, because a per-user override would fragment the canonical
store. The read is anchored to the **main checkout's** config even when a command runs inside a
linked worktree. A worktree's checkout state, including a detached HEAD or a commit without
`.perk/`, can never flip the canonical store; an in-worktree `[issues]` edit takes effect when it
reaches the main checkout.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | string | `github` | `"github"` or `"linear"`. |
| `team` | string | _(none)_ | The Linear team key, such as `"ENG"`; required when `backend = "linear"`. |

Selecting Linear also requires a personal `LINEAR_API_KEY`. Set it in the environment or in the
gitignored `.perk/local.toml` `[linear] api_key`; never put it in the committed file. This is
**config-key reference depth only**. The Linear backend reference for authentication, labels,
identifiers, and maturity is in
[Issue backends — Linear](../providers-and-backends/issue-backends.md#linear).

```toml
[issues]
backend = "linear"
team = "ENG"
```

## `[linear]`

A personal Linear API key used by both perk's Linear issue backend and the in-session `linear_*`
tools. **Gitignored-local-only** — read from `.perk/local.toml`, never the committed
`.perk/config.toml`, which structurally prevents a committed secret.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `api_key` | string | _(none)_ | A personal Linear API key (linear.app → Settings → Security & access). |

An exported `LINEAR_API_KEY` environment variable **wins** over this config; the config value is a
fallback. When set locally, perk seeds the launched `pi` session's environment with the key so
the borrowed in-session `linear_*` tools authenticate too. The key is read from the **main
checkout** at launch. Because the file is gitignored and never copied into a worktree, this
environment seed carries the key into the worktree session and tools or workers it spawns.

perk also reads the key directly from the main checkout's `.perk/local.toml` when a command runs
inside a linked worktree (`/submit`, `/land`, and other cold doors). One main-checkout entry
therefore authenticates every worktree session and cold door even when the launch environment
seed did not fire. Malformed local TOML is ignored (fail-soft).

You rarely need to write the key by hand. When the committed `[issues] backend` is `"linear"`
with a `team`, and no key resolves, **interactive `perk init`** prompts for it with hidden input,
validates it against Linear's API, and persists it here atomically. It tightens the file to mode
`0600` and refuses outright unless the file is provably untracked and gitignored, so a secret
never lands in a committable file. The prompt never runs under `--no-interactive`, non-TTY stdin,
or `--json`.

```toml
# .perk/local.toml (gitignored)
[linear]
api_key = "lin_api_…"
```

## Related

- **Do:** [How to select a provider](../../how-to/select-a-provider.md) — choose a provider for a supported seam.
- **Do:** [How to switch the issue backend to Linear](../../how-to/switch-to-linear.md) — configure the team and local credential.
- **Look up:** [Providers & issue backends](../providers-and-backends.md) — supported providers and backend mechanics.
