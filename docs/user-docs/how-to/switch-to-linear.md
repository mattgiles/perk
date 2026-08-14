---
title: "How to switch the issue backend to Linear"
description: "Move perk's canonical plan, learn, and objective issue store from GitHub to Linear — a committed, repo-wide switch."
sidebar:
  order: 2310
sidebarGroup: "Providers & backends"
---

# How to switch the issue backend to Linear

Configure one repository to create and read perk plans, learnings, gists, and objectives in a Linear
team instead of GitHub Issues.

## Prerequisites

You need the Linear team key, a personal Linear API key, and access to that team's projects and
workflow states.

## Steps

1. **Provide the credential without committing it.** Prefer a `LINEAR_API_KEY` environment variable
   supplied by your shell or secret manager. Alternatively, put the key in the gitignored
   `.perk/local.toml`:

   ```toml
   [linear]
   api_key = "<your personal Linear API key>"
   ```

   The environment variable wins when both exist. Never put the key in `.perk/config.toml` or in a
   command, screenshot, log, or committed file. A main-checkout `.perk/local.toml` also serves
   linked worktrees.
2. **Commit the backend selection.** Add the team key to `.perk/config.toml`:

   ```toml
   [issues]
   backend = "linear"
   team = "ENG"
   ```

   Replace `ENG` with the Linear team key, not its display name. The `[issues]` selection is
   committed and repository-wide; a `.perk/local.toml` override does not change the canonical
   backend.
3. **Converge the integration.** Run `perk init`. It adds `npm:pi-mono-linear` and ensures six
   workspace labels: `perk:plan`, `perk:learn`, `perk:consolidated`, `perk:objective`,
   `perk:objective-node`, and `perk:gist`.
4. **Verify readiness.** Run `perk doctor --verify` and inspect both the offline `issues-backend`
   result and the network-backed `linear-auth`, `linear-team`, `linear-labels`,
   `linear-project-scopes`, and `linear-workflow-states` results. Resolve every warning before using
   the backend; the last two checks confirm project-scope access and the workflow-state types needed
   by project-backed objectives.
5. **Confirm one create/read round trip.** Create a small gist that is safe to keep or close after
   the check, then list it through the configured backend:

   ```bash
   body="$(mktemp)"
   printf '%s\n' 'Confirm the Linear issue backend can create and read a perk gist.' > "$body"
   perk gist create --body "$body" --title "Linear backend check" --scope plan --json
   perk gist list --all --json
   rm -f "$body"
   ```

   Confirm that the created Linear identifier and URL appear in the list response. If this was only
   a connectivity check, close the gist issue in Linear afterward.

## Expected result

New canonical perk issue artifacts use Linear identifiers such as `ENG-123`, while GitHub continues
to host pull requests. Switching the backend does **not** migrate existing GitHub plan, learn, gist,
or objective issues; finish them on GitHub or recreate the intended work in Linear deliberately.

## Related

- **Do:** [Select a provider](./select-a-provider.md) — configure the independent plan, footer, and
  web seams.
- **Look up:** [`[issues]` configuration](../reference/configuration/backends.md#issues) — Linear keys and
  credential precedence.
- **Look up:** [Linear backend reference](../reference/providers-and-backends/issue-backends.md#linear)
  — backend effects, identifiers, labels, and maturity.
