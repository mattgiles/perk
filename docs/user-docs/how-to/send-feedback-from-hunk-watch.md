---
title: "How to send feedback from a hunk watch"
description: "Save notes on the live perk plan watch diff and steer the implementing agent in place — save is the send boundary."
sidebar:
  order: 2135
sidebarGroup: "Core workflow"
---

# How to send feedback from a hunk watch

Watch a plan's implementation diff live in [hunk](https://github.com/modem-dev/hunk) and steer
the implementing agent by **saving notes on the diff** — each saved note is sent to the live
implement session as a real user message. Save is the send boundary: no extra command, keybinding,
or confirmation.

**Prerequisites:** the `hunk` CLI on PATH (`perk init` installs it; `npm i -g hunkdiff`), and a
plan with an implementation worktree (run
[`perk implement <id>`](../reference/cli.md#perk-implement-plan-alias-impl) first).

## Steps

1. **Run the implement session.** `perk implement 42` (or `perk plan resume 42`) in one terminal
   — the interactive TUI implement session is the feedback consumer.
2. **Start the watch.** In another terminal, run
   [`perk plan watch 42`](../reference/cli/plan.md#perk-plan-watch-plan). Hunk opens on the plan's
   live diff and shows the one-time notice *“perk feedback active — saving a human note sends it
   to the implementation session.”*
3. **Save a note on a changed line.** Comment where the diff needs steering, as you would in a
   code review, and save it. Hunk confirms *“Feedback queued for the implementation session.”*
4. **Watch the agent react.** The note arrives in the implement session as a user message (with
   its file/line anchor); if the agent is mid-turn it is steered immediately, otherwise the note
   starts a new turn. The watch reloads live as the agent edits.

## What “queued” does and doesn't promise

- **Queued** = the note is durably written to the worktree's local outbox
  (`.perk/workflow/hunk-watch/` — disposable local state, removed with the worktree; it never
  reaches GitHub/Linear).
- **Delivered** = the note reached the implement session's transcript. Delivery is
  **at-least-once**: a crash can duplicate a note, never silently lose it. Delivery is not
  agreement — the agent is told to check each note's anchor against the current code before
  acting.
- **No consumer? Notes wait.** If no eligible implement session is live (or you stopped it),
  saved notes stay queued and are drained by the **next** eligible implement session for that
  plan. Only one session consumes at a time (a single-consumer lease); a second implement
  session for the same worktree says it is staying passive.
- Deleting a saved note in hunk does **not** retract already-queued feedback.

## Degradations (loud, never silent)

- An **incompatible hunk** (an extension-API generation perk hasn't verified) disables feedback
  with a visible warning — the watched diff stays fully usable. Update perk and/or hunk.
- An **unwritable outbox** (or an empty/oversized note — bodies are capped at 16 KiB) is refused
  visibly with the concrete reason; hunk never claims “queued” when nothing was written.
- Passing `--no-extensions` through to hunk is **refused** (it would silently disable the
  bridge); for an extension-free watch, run `hunk diff <base> --watch --no-extensions` in the
  worktree yourself.

## Related

- **Do:** [How to track implement progress](track-implement-progress.md) — the checklist view of
  the same live session.
- **Do:** [How to review a PR human-in-the-loop](review-a-foreign-pr.md) — the review-time use of
  the same hunk surface.
- **Look up:** [Plan commands](../reference/cli/plan.md) — exact `perk plan watch` syntax and flags.
