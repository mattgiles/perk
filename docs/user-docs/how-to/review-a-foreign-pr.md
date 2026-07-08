# How to review a foreign PR with `/review`

Run a human-in-the-loop adversarial review of a PR that perk's own flow did not author — guest
reviewers fan out, findings land in your live [hunk](https://github.com/modem-dev/hunk) session,
you triage them together, and exactly one curated review is posted to GitHub with your explicit
approval. Use this when you're asked to review someone else's PR.

**Prerequisites:**

- The `hunk` CLI installed (`npm i -g hunkdiff` or `brew install hunk`). A verified `perk init`
  installs it best-effort when the review selection needs it, and
  [`perk doctor`](../reference/cli.md#perk-doctor)'s `review-cli` check verifies it; the door
  refuses at start with the install hint when it's absent.
- The `[providers] review` selection left at its default (`hunk`). Selecting
  `plannotator-review` refuses at start — that arm is not wired yet (see the
  [providers reference](../reference/providers-and-backends.md)).
- An interactive session, if you want to post a formal verdict (`approve`/`request-changes` are
  refused headless; `comment` is not).

## Steps

1. **Invoke the door.** In a perk session in the repo, run `/review <pr number|url>`, optionally
   followed by a free-form focus note — e.g. `/review 123 have one reviewer dig into the CI
   changes`. perk checks out the PR head into a detached, read-only worktree (untrusted foreign
   code — nothing from it is ever executed). A cross-repo PR URL is not validated against this
   repo: only the number is extracted, so a wrong-repo URL resolves to this repo's PR of that
   number (or fails `pr_not_found`).
2. **Launch hunk when the command is printed.** The session prints a verbatim launch command —
   `cd <worktree> && hunk diff <base_sha>` — run it in another terminal. Meanwhile 2–3 guest
   reviewers are already reviewing in parallel (the `claimed-intent` angle is always included;
   the model comes from `[models.subagents] guest-reviewer`).
3. **Review in the hunk TUI, write your own notes.** Once the reviewers return, the agent
   reconciles their findings and pushes them into your live hunk session as comments. Read the
   diff, and leave your own notes in hunk — they are read back as first-class review comments.
   If the hunk session never connects (sandboxes can block its loopback daemon), the flow
   degrades loudly to an in-session findings table — everything below is unchanged.
4. **Answer the triage questions.** The agent walks the findings with you — keep, drop, or
   reword each — and settles the review event (`comment`, `approve`, or `request-changes`) last.
   You can also just talk; the loop is a conversation, not a form.
5. **Approve the final post.** Nothing reaches GitHub before this step. On your explicit
   go-ahead the agent validates the batch (`dry_run`), repairs any anchor errors, then posts one
   atomic review via `submit_pr_review`. A formal event (`approve`/`request-changes`)
   additionally raises a blocking confirm dialog in the TUI.
6. **Cleanup happens for you.** The review checkout is removed (`perk pr review cleanup` —
   idempotent; abandoned checkouts are reaped by a 7-day gc backstop on the next checkout).

---

← Back to the [how-to router](index.md).
