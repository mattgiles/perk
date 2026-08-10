# How to capture a gist (a statement of intent)

Capture "something we would likely want to do" as a tracked, durable **gist** — a rough,
problem-space-focused statement of intent, upstream of both plans and objectives. A gist is
code-informed but carries **no implementation detail** (no steps, no roadmap, no estimates); it
sits in the backlog until someone consumes it through the normal adoption doors. Use it when an
idea is worth keeping but not worth planning yet.

This runs in a **read-only** session and is **local-only**.

## Steps

1. **Open the authoring session.** Run [`perk gist author`](../reference/cli.md#perk-gist-author)
   from the repo root. Pass `--scope objective` if you already know the intent is
   objective-sized (a long-running, multi-plan goal); the default scope is `plan` (a bounded,
   single-plan-sized intent). The scope pre-seeds the save; you can still settle it while
   authoring.
2. **Converge on the intent.** Work with the agent to say what you want and why it matters — the
   problem or desire and the constraints that bound it. The agent explores the codebase lightly
   (honest problem-space framing, plus a strategic-level read on the solution's biggest
   questions) and keeps the working draft current with the `gist_draft` tool. If it starts enumerating implementation steps, pull it back — that is the downstream
   plan's job.
3. **Review + save.** When the gist says what it means, the agent calls `plan_review`: the review
   surface shows the rendered gist (title + scope + prose), view-only — deny with feedback to
   change it. Approving **auto-saves** the gist to the issue backend and prints the consumption
   command. (`/gist-save` is the manual failsafe if the review was skipped.)
4. **See the backlog.** [`perk gist list`](../reference/cli.md#perk-gist-list) shows the
   unconsumed gists (adopted ones are hidden by default; `--include-adopted` marks them).
5. **Consume it later.** When someone is ready to act on the gist, adopt it in place through
   the normal doors — nothing gist-specific:
   - plan scope → [`perk plan from <gist>`](./adopt-an-existing-issue.md)
   - objective scope → [`perk objective author --from <gist>`](./adopt-an-existing-project.md)

   Adoption stamps the plan/objective metadata beside the gist's own header — the gist *becomes*
   the plan/objective and inherits its lifecycle; that is exactly what flips it to adopted in
   `perk gist list`.

## Notes

- **Gist vs plan vs objective.** A plan says *how* a bounded change will be made; an objective
  says *what long goal* generates plans; a gist says *that we want something and why*, with at
  most a strategic-level lean on the solution. Reach
  for a gist when the intent is real but the design conversation hasn't earned a session yet.
- **Storage.** A gist is a `perk:gist` issue in the issue backend (GitHub or Linear). On Linear,
  an objective-scoped gist is stored as a deliberately light **project**, so objective authoring
  adopts it in place.
