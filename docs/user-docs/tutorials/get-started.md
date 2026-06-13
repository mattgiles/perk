# Get started with perk

By the end of this lesson you will have driven a tiny change through perk's complete
workflow — planned it, implemented it on a branch, opened and merged a pull request, and
captured a learning — all on a throwaway repo you can delete afterward. This is the perk
**spine**: `plan → save → implement → submit → land → learn`. Every command here works if
you follow them in order; there is one path, and you walk it to the end.

## Before you start

perk drives the [`pi`](https://github.com/earendil-works/pi) agent harness and talks to
GitHub through the `gh` CLI. Before you begin, confirm you have each of these — the same
environment `perk init` checks for:

- **A git repo** — you will create one in Step 2.
- **`git`** — `git --version`
- **`gh`** — the GitHub CLI, **authenticated**: `gh auth status`. The spine opens and merges
  real pull requests, so an authenticated `gh` (and a GitHub account) is required, not
  optional.
- **`node` ≥ 22** — `node --version`
- **`pi`** — the agent harness perk drives; confirm it is on your PATH: `pi --version`
- **`uv`** — `uv --version`; used to install perk in Step 1.

perk reaches GitHub only through `gh`, so a GitHub account with an authenticated `gh` is
mandatory for this tutorial.

## Step 1 — Install perk

perk is not yet published to a package index, so install it **from source** with `uv`:

```bash
git clone https://github.com/mattgiles/perk.git
cd perk
uv tool install --editable .
```

This puts the `perk` CLI on your PATH (uv's tool bin, `~/.local/bin`). If your shell can't
find `perk` afterward, that directory isn't on your `PATH` — run `uv tool update-shell` and
restart your shell. Confirm the install:

```bash
perk --version
```

You should see a version line like `perk 0.0.1`.

## Step 2 — Create a scratch repo

Create a brand-new private repo to play in, seed it with a single file, and push it. This
repo is disposable — you'll delete it at the end.

```bash
gh repo create perk-tutorial --private --clone
cd perk-tutorial
```

Create `greetings.py` with one function:

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

Then commit it and push `main`:

```bash
git add greetings.py && git commit -m "Add greet()"
git push -u origin main
```

Run the rest of the tutorial from inside this `perk-tutorial` checkout.

## Step 3 — Wire the repo for perk

Tell perk to set up the repo:

```bash
perk init
```

`perk init` scaffolds perk's Pi wiring (`.pi/settings.json` and the `.pi/workflow/` cache),
writes managed blocks into `.gitignore` and `AGENTS.md`, and drops a `.pi/perk.toml` config
(with the `[[ci]]` checks block **commented out** by default). It is idempotent — re-running it
on an already-wired repo is a no-op.

Confirm the setup is healthy:

```bash
perk doctor
```

`perk doctor` runs grouped checks and reports their health. On a freshly-initialized repo the
core groups (environment, package, repository, state) report green; a few advisory items —
mostly the optional remote-runner credentials — may show as warnings, which is fine for this
tutorial. Commit the wiring perk added so the branch perk creates later starts from a clean
tree:

```bash
git add -A && git commit -m "perk init"
```

## Step 4 — Plan the change

Now plan the change you want perk to build:

```bash
perk plan
```

This opens an interactive `pi` session in **read-only plan mode** — the agent can explore the
repo but not edit it. Type one short request, for example:

> Add a `farewell(name)` function to greetings.py, mirroring greet().

The agent reads the repo and drafts a plan, then perk presents it for your review. **Approve**
it. On approval, perk **saves the plan as a GitHub issue** and the session leaves read-only
mode. perk prints the issue URL; you can also see it with:

```bash
gh issue list
```

The plan is now a real GitHub issue — the canonical record of what's going to be built.

## Step 5 — Implement it

Build the plan:

```bash
perk implement
```

With no argument, `perk implement` picks up the plan you just saved (the active plan in
perk's local cache). You can also pass the plan's issue number explicitly, e.g.
`perk implement 1`. perk materializes a **worktree branch** and launches a fresh `pi` session
primed to build that plan. The agent adds the `farewell()` function to `greetings.py`,
committing as it goes. Eyeball what it built:

```bash
git diff main
```

(Or read the agent's own summary in the session.)

## Step 6 — Open the PR

Still inside the same implement session, open a pull request with the warm command:

```
/submit
```

perk opens a **draft PR** for the worktree branch and prints its URL. Inspect it with:

```bash
gh pr view
```

## Step 7 — Make it ready and land it

Still in the implement session, run two more warm commands:

```
/ready
```

`/ready` runs the repo's CI checks and flips the PR from draft to ready-for-review. Your
scratch repo configured no checks (the `[[ci]]` block is commented out), so perk reports there
are no checks to run — that's non-fatal and won't block you.

```
/land
```

`/land` squash-merges the PR into `main`. On a fresh personal repo there's no branch
protection, so the merge goes through cleanly. Confirm the merged state:

```bash
gh pr view          # shows MERGED
git checkout main && git pull   # main now has farewell()
```

## Step 8 — Capture what you learned

Finally, still in the session, run:

```
/learn
```

`/learn` captures a durable learning from the change you just landed — perk's way of
recording lessons after work merges, so future planning can draw on them.

## What you did

You just drove the full perk spine on a real change: you **planned** a one-function addition,
**saved** it as a GitHub issue, **implemented** it on a worktree branch, **opened** and
**landed** a pull request, and **captured** a learning. You now have a merged change on
`main` and a recorded learning to show for it.

The `perk-tutorial` repo was disposable — delete it whenever you like:

```bash
gh repo delete perk-tutorial
```

To find your way around the rest of the docs, head back to the
[user-docs router](../index.md).
