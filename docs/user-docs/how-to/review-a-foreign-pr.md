# How to review a foreign PR with `/review`

Run a human-in-the-loop adversarial review of a PR that perk's own flow did not author — guest
reviewers fan out, findings land on your configured review surface (the
[hunk](https://github.com/modem-dev/hunk) terminal TUI by default, or
[plannotator](https://github.com/backnotprop/plannotator)'s browser UI), you triage them
together, and the curated review is posted to GitHub with your explicit approval. Use this when
you're asked to review someone else's PR.

**Prerequisites (per arm** — the `[providers] review` selection picks the surface; see the
[providers reference](../reference/providers-and-backends.md)**):**

- **hunk (the default):** the `hunk` CLI installed (`npm i -g hunk` or `brew install hunk`).
  A verified `perk init` installs it best-effort when the review selection needs it, and
  [`perk doctor`](../reference/cli.md#perk-doctor)'s `review-cli` check verifies it; the door
  refuses at start with the install hint when it's absent.
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
2. **Launch hunk when the command is printed.** The session prints a verbatim launch command —
   `cd <worktree> && hunk diff <base_sha>` — run it in a separate terminal. Meanwhile 2–3 guest
   reviewers are already reviewing in parallel (the `claimed-intent` angle is always included;
   the model comes from `[models.subagents] guest-reviewer`).
3. **Review in the hunk TUI, write your own notes.** Once the reviewers return, the agent
   reconciles their findings and pushes them into your live hunk session as comments. Read the
   diff, and leave your own notes in hunk — they are read back as first-class review comments.
   If the hunk session never connects (sandboxes can block its loopback daemon), the flow
   degrades loudly to an in-session findings table — everything below is unchanged.
4. **Answer the triage questions.** The agent walks the findings with you — keep, drop, or
   reword each — and settles the review event (`comment`, `approve`, or `request-changes`) last.
   You can also simply talk; the loop is a conversation, not a form.
5. **Approve the final post.** Nothing reaches GitHub before this step. On your explicit
   go-ahead the agent validates the batch (`dry_run`), repairs any anchor errors, then posts one
   atomic review via `submit_pr_review`. A formal event (`approve`/`request-changes`)
   additionally raises a blocking confirm dialog in the TUI.
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
