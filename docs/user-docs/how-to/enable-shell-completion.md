---
title: "How to enable shell completion"
description: "Activate TAB completion for perk in zsh, bash, or fish — plan and objective ids complete from the live issue backend, with title previews."
sidebar:
  order: 2295
sidebarGroup: "Customization"
---

# How to enable shell completion

Activate TAB completion for `perk` so plan- and objective-taking commands complete their id
arguments from the live issue backend. `perk impl <TAB>` offers the **open** plan ids
(newest-created-first); `perk objective plan <TAB>` offers the open objective ids. zsh and fish
render a truncated title beside each candidate; bash shows bare ids (a shell limitation).

perk uses Click's native completion protocol — there is no wrapper command, and perk never edits
your shell rc files.

## Steps

1. **Activate for your shell.**

   - **zsh** — add to `~/.zshrc`:

     ```sh
     eval "$(_PERK_COMPLETE=zsh_source perk)"
     ```

   - **bash** (requires bash ≥ 4.4 — macOS stock bash 3.2 is unsupported) — add to `~/.bashrc`:

     ```sh
     eval "$(_PERK_COMPLETE=bash_source perk)"
     ```

   - **fish** — write the completion file once (fish auto-loads it; no rc edit):

     ```sh
     _PERK_COMPLETE=fish_source perk > ~/.config/fish/completions/perk.fish
     ```

2. **Prefer the write-to-file variant** if the `eval` noticeably slows shell startup — the inline
   form re-runs `perk` on every new shell. Generate the script once and source the file instead
   (regenerate after upgrading perk):

   ```sh
   _PERK_COMPLETE=zsh_source perk > ~/.perk-complete.zsh   # then in ~/.zshrc:
   source ~/.perk-complete.zsh
   ```

3. **Open a new shell and use it.** Every plan-taking command completes plan ids
   (`perk implement`, `perk address`, `perk ready`, `perk plan resume`, `perk plan replan`,
   `perk plan watch`), and every objective-taking command completes objective ids
   (`perk objective plan/show/next/...` and the `perk objective stack` verbs). Anything after the
   bare `--` separator belongs to `pi` — perk offers no completions there.

## What each TAB costs

Candidates are read live, per TAB — one Python startup plus one bounded backend read (no cache,
no cursor pagination): on GitHub a single REST request (the default list page, ~30 rows); on
Linear 2–3 GraphQL requests (the per-process team-id lookup plus one or two single-page lists).
The population is the **open** plans/objectives on the most recent page — an id beyond that page
still works typed out; it just isn't offered.

## Expected result

TAB after a plan/objective argument lists the open ids newest-first, with title previews in
zsh/fish. When something is off — offline, unauthenticated, outside a repo — completion fails
soft: TAB simply offers no candidates, and nothing garbles the prompt. The invoked command still
validates whatever id you accept.

## Related

- **Do:** [Resume a plan at its current stage](./resume-a-plan.md) — the plan-selecting recipe
  whose id argument you will complete most.
- **Look up:** [Issue backends](../reference/providers-and-backends/issue-backends.md) — the
  backend the candidates are read from.
