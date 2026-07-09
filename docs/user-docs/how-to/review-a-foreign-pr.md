# How to review a foreign PR with `/review`

Run a human-in-the-loop adversarial review of a PR that perk's own flow did not author — guest
reviewers fan out, findings land on your configured review surface (the
[hunk](https://github.com/modem-dev/hunk) terminal TUI by default, or
[plannotator](https://github.com/backnotprop/plannotator)'s browser UI), you triage them
together, and the curated review is posted to GitHub with your explicit approval. Use this when
you're asked to review someone else's PR.

> **`/pr-review-terminal`** is the **terminal-surface** entry into the same review: the identical
> hunk flow below with no provider selection needed (the command names the surface), plus a
> **no-arg mode** that reviews the *active worktree's own PR* in place (and, pre-PR, opens a
> surface-only since-base hunk review). Its launches carry `--agent-notes`, so pushed findings
> appear in hunk immediately. See the
> [in-session reference](../reference/in-session.md#pr-review-terminal) for the mode details.

**Prerequisites (per arm** — the `[providers] review` selection picks the surface; see the
[providers reference](../reference/providers-and-backends.md)**):**

- **hunk (the default):** the `hunk` CLI installed — `perk init` installs it automatically
  (best-effort) whenever it is absent; `npm i -g hunkdiff` or `brew install hunk` is the manual
  fallback. [`perk doctor`](../reference/cli.md#perk-doctor)'s `review-cli` check verifies it;
  the door refuses at start with the install hint when it's absent.
- **plannotator (`review = "plannotator-review"`):** the `npm:@plannotator/pi-extension` package
  loaded (`perk init` converges it for this selection — then restart pi) **and** an interactive
  session (the browser review is refused headless outright).
- An interactive session on any arm, if you want to post a formal verdict
  (`approve`/`request-changes` are refused headless; `comment` is not).

## Steps (the hunk arm — the default)

1. **Invoke the door.** In a perk session in the repo, run `/review <pr number|url>`, optionally
   followed by a free-form focus note — e.g. `/review 123 have one reviewer dig into the CI
   changes`. perk checks out the PR head into a detached, read-only worktree (untrusted foreign
   code — nothing from it is ever executed). A cross-repo PR URL is not validated against this
   repo: only the number is extracted, so a wrong-repo URL resolves to this repo's PR of that
   number (or fails `pr_not_found`).
2. **hunk opens for you.** The door tries to open hunk in a new terminal pane/window (a tmux
   pane, or your macOS terminal — Ghostty / iTerm2 / Terminal.app) running
   `cd <worktree> && hunk diff <base_sha>`. **The first macOS run may show an Automation
   permission prompt (attributed to your terminal app); denying or missing it just means you run
   the printed command yourself.** Either way the launch command also arrives as a loud message
   *and* on your clipboard, so you can paste it into any terminal. Meanwhile 2–3 guest reviewers
   are already reviewing in parallel (the `claimed-intent` angle is always included; the model
   comes from `[models.subagents] guest-reviewer`). Set `PERK_TERMINAL_LAUNCH` to a custom
   launcher (it receives the worktree as `$1` and the command as `$2`) or `PERK_CLIPBOARD_CMD` to
   a custom copier if the defaults don't fit; set either to the empty string to turn that side
   effect off.
3. **Review in the hunk TUI, write your own notes.** Once the reviewers return, the agent
   reconciles their findings and pushes them into your live hunk session as comments. Read the
   diff, and leave your own notes in hunk — they are read back as first-class review comments.
   If hunk doesn't come up, the flow **checks in and waits for you** — it re-shows the launch
   command and asks whether to keep checking or continue without hunk; it never proceeds on its
   own. Continuing without hunk (sandboxes can block its loopback daemon) degrades loudly to an
   in-session findings table — everything below is unchanged.
4. **Answer the triage questions.** The agent walks the findings with you — keep, drop, or
   reword each — and settles the review event (`comment`, `approve`, or `request-changes`) last.
   You can also just talk; the loop is a conversation, not a form.
5. **Approve the final post.** Nothing reaches GitHub before this step. On your explicit
   go-ahead the agent validates the batch (`dry_run`), repairs any anchor errors, then posts one
   atomic review via `submit_pr_review`. A formal event (`approve`/`request-changes`)
   additionally raises a blocking confirm dialog in the TUI. On your **own** PR only `comment`
   can land — GitHub rejects formal verdicts from the PR author, and the dry-run tells you so
   up front (`own_pr`) instead of validating a doomed post.
6. **Cleanup happens for you.** The review checkout is removed (`perk pr review cleanup` —
   idempotent; abandoned checkouts are reaped by a 7-day gc backstop on the next checkout).

## The plannotator arm (browser triage)

With `[providers] review = "plannotator-review"` the same door drives plannotator's browser
code-review UI instead of the hunk TUI. The flow deltas:

1. **The browser opens for you.** No launch command — right after spawning the reviewers the
   agent calls the `open_plannotator_review` tool, which opens plannotator's review UI on the PR
   (a local server; the PR fetch can take a little while).
2. **Findings stream in live.** As each guest reviewer returns, the agent pushes that angle's
   findings into the browser as badged annotations (`perk:<angle>`) — you watch them arrive
   while later reviewers still run, and you can annotate freely alongside them.
3. **You may platform-post directly from the UI.** The browser can post inline comments (yours
   and perk's pushed findings) to GitHub natively, with an APPROVE or COMMENT verdict — never
   REQUEST_CHANGES (that verdict always travels perk's gated path). A platform post ends the
   browser session.
4. **Any ending returns to the session.** Send Feedback / Approve / a platform post / closing
   the tab — each resolves the review once and routes back into the perk session as a message;
   the triage conversation continues there.
5. **perk posts only the remainder.** Before any perk-side post the agent reads back what
   already landed on the PR and dedupes — what you platform-posted is never re-posted.
   Typically the remainder is just the formal verdict, posted via `submit_pr_review` with the
   same gates (explicit go-ahead; formal events confirm in the TUI). If you platform-approved
   and nothing remains, perk posts nothing.

If the browser server never becomes ready (or a findings push fails), the flow degrades loudly
to the same in-session findings table — triage and posting are unchanged.

---

← Back to the [how-to router](index.md).
