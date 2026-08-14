---
title: "How to review a PR human-in-the-loop"
description: "Run a human-in-the-loop adversarial review of any PR, where nothing reaches GitHub without your explicit approval."
sidebar:
  order: 2040
sidebarGroup: "Core workflow"
---

# How to review a PR human-in-the-loop

Run a human-in-the-loop adversarial review of a PR — a foreign PR perk's own flow did not
author, or the active worktree's own PR. Adversarial reviewers fan out asynchronously, finding
batches stream live onto your review surface, you triage them together, and anything that
reaches GitHub does so only with your explicit approval. **The command is the surface pick** —
there is no provider selection:

- **`/pr-review-terminal`** — the [hunk](https://github.com/modem-dev/hunk) terminal TUI.
  Findings are pushed incrementally into your live hunk session (never the same anchor twice);
  launches carry `--agent-notes`, so pushed findings appear immediately. Posting is perk's gated
  `submit_pr_review` tool — the sole GitHub path on this door.
- **`/pr-review-browser`** — [plannotator](https://github.com/backnotprop/plannotator)'s browser
  UI, opened in the background (the session stays free while you review). Findings stream in as
  badged annotation waves — and **you post to GitHub from the UI** (perk composes nothing by
  default).

Both doors share the same arg semantics and three modes: a PR number/URL reviews that
**foreign** PR (detached, read-only checkout — untrusted foreign code, nothing from it is ever
executed); no arg reviews the **active worktree's own PR** in place; and pre-PR (no PR yet) each
door opens a surface-only **since-base** review — no reviewers, nothing posts to GitHub. See the
[Review and authoring](../reference/in-session/review-and-authoring.md#pr-review-terminal) for the mode details.

**Prerequisites (per door):**

- **`/pr-review-terminal`:** the `hunk` CLI installed — `perk init` installs it automatically
  (best-effort) whenever it is absent; `npm i -g hunkdiff` or `brew install hunk` is the manual
  fallback. [`perk doctor`](../reference/cli.md#perk-doctor)'s `review-cli` check verifies it;
  the door refuses at start with the install hint when it's absent.
- **`/pr-review-browser`:** the `npm:@plannotator/pi-extension` package loaded — select the
  plannotator plan provider (`[providers] plan = "plannotator-plan"`), run `perk init`, then
  restart pi. The door refuses at start when the extension is absent, and it requires an
  interactive session (the browser review is refused headless outright).
- An interactive session on either door, if you want to post a formal verdict
  (`approve`/`request-changes` are refused headless; `comment` is not).

## Steps (`/pr-review-terminal`)

1. **Invoke the door.** In a perk session in the repo, run `/pr-review-terminal <pr number|url>`,
   optionally followed by a free-form focus note — e.g. `/pr-review-terminal 123 have one
   reviewer dig into the CI changes` — or no PR at all to review the active worktree's own PR.
   For a foreign PR, perk checks out the PR head into a detached, read-only worktree. A
   cross-repo PR URL is not validated against this repo: only the number is extracted, so a
   wrong-repo URL resolves to this repo's PR of that number (or fails `pr_not_found`).
2. **hunk opens for you.** The door tries to open hunk in a new terminal pane/window (a tmux
   pane, or your macOS terminal — Ghostty / iTerm2 / Terminal.app) running
   `cd <worktree> && hunk diff <base_sha> --agent-notes`. **The first macOS run may show an
   Automation permission prompt (attributed to your terminal app); denying or missing it just
   means you run the printed command yourself.** Either way the launch command also arrives as a
   loud message *and* on your clipboard, so you can paste it into any terminal. Meanwhile 2–3
   adversarial reviewers are already reviewing in parallel (the `claimed-intent` angle is always
   included; the model comes from `[models.subagents] adversarial-reviewer`). Set
   `PERK_TERMINAL_LAUNCH` to a custom launcher (it receives the worktree as `$1` and the command
   as `$2`) or `PERK_CLIPBOARD_CMD` to a custom copier if the defaults don't fit; set either to
   the empty string to turn that side effect off.
3. **Review in the hunk TUI, write your own notes.** Finding batches stream into your live hunk
   session as comments while the reviewers still work; their final reports are reconciled as the
   source of truth. Read the diff, and leave your own notes in hunk — they are read back as
   first-class review comments. If hunk doesn't come up, the flow **checks in and waits for
   you** — it re-shows the launch command and asks whether to keep checking or continue without
   hunk; it never proceeds on its own. Continuing without hunk (sandboxes can block its loopback
   daemon) degrades loudly to an in-session findings table — everything below is unchanged.
4. **Answer the triage questions.** The agent walks the findings with you — keep, drop, or
   reword each — and settles the review event (`comment`, `approve`, or `request-changes`) last.
   You can also just talk; the loop is a conversation, not a form.
5. **Approve the final post.** Nothing reaches GitHub before this step. On your explicit
   go-ahead the agent validates the batch (`dry_run`), repairs any anchor errors, then posts one
   atomic review via `submit_pr_review`. A formal event (`approve`/`request-changes`)
   additionally raises a blocking confirm dialog in the TUI. On your **own** PR only `comment`
   can land — GitHub rejects formal verdicts from the PR author, and the dry-run tells you so
   up front (`own_pr`) instead of validating a doomed post.
6. **Cleanup happens for you** (foreign PRs only). The review checkout is removed
   (`perk pr review cleanup` — idempotent; abandoned checkouts are reaped by a 7-day gc backstop
   on the next checkout). An active-worktree review has nothing to clean up.

## Steps (`/pr-review-browser`)

The same review on plannotator's browser UI — with the posting direction **flipped**:

1. **The browser opens for you, in the background.** No launch command — the door starts the
   local review server and injects the flow immediately (the PR fetch can take a little while;
   an info note lands when the browser is up).
2. **Findings stream in live.** Finding batches are pushed into the browser as badged
   annotations (`perk:<angle>`) while the reviewers still work — you watch them arrive, and you
   can annotate freely alongside them.
3. **You post directly from the UI — that is the GitHub path.** The browser posts inline
   comments (yours and perk's pushed findings) to GitHub natively, with an APPROVE or COMMENT
   verdict — never REQUEST_CHANGES (that verdict always travels perk's gated path). A platform
   post ends the browser session.
4. **Any ending returns to the session.** Send Feedback / Approve / a platform post / closing
   the tab — each resolves the review once and routes back into the perk session as a message;
   the conversation continues there.
5. **perk composes nothing by default.** `submit_pr_review` (same gates: dry-run repair loop,
   explicit go-ahead, formal events confirm in the TUI) is used only for a **request-changes**
   verdict — the one verdict the UI cannot post — or when you explicitly ask perk to post
   something on your behalf. If you posted from the browser and ask nothing more, perk posts
   nothing.

If the browser server never becomes ready (or a findings push fails), the flow degrades loudly
to the same in-session findings table — triage and posting are unchanged.

## Related

- **Do:** [How to address review feedback on a PR](address-review-feedback.md) — the other side: responding to a review your plan received.
- **Do:** [How to review a stacked PR train](review-a-stacked-train.md) — reviewing layer-by-layer when the PR is part of a stacked train.
- **Look up:** [Review and authoring](../reference/in-session/review-and-authoring.md) — the full mode and refusal detail for both review doors.
