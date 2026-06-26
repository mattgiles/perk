---
title: The github.py gateway — parse-helper family, consolidation boundary rules, the not-found fold, mutation-posting policies
read_when: You are touching `perk/github/`, consolidating repeated subprocess/parse idioms, debugging a phantom-`None` GitHub lookup, adding a REST/GraphQL call (the gh-GraphQL transport facts — no `{owner}/{repo}` templating, cursor pagination, the GraphQL not-found shape), designing a mutation-posting policy (failure ladders, verdict-driven artifacts), fixing the non-default-base autoclose strand (`Closes #N` fires only on a default-branch merge), or purifying a neutral gateway that carries a backend-specific read (hoist it to the consumer as a value resolved via the resolver).
---

# The github.py gateway

`perk/github/` is the single gateway for `gh` subprocess calls. A dignified-sweep consolidation
carried 19 hand-rolled parse sites onto a small helper family; this doc preserves the boundary
rules that made the migration safe and the one residual risk it accepted.

## The five-function helper family — and why it's five, not four

The family: `_run` (subprocess wrapper), `_run_json` (run + parse), `_parse_json` (parse-only),
`_rest_args` (REST argv builder), with `_graphql` as a deliberately-untouched sibling.
`_parse_json` had to be split from `_run_json` because three none-on-nonzero readers keep their
**own** returncode handling and share only the parse step — folding their returncode policy into
the runner would have changed behavior.

## Consolidation boundary rules (these generalize)

- **Consolidate repeated *hand-rolled idioms*; leave an existing single-site wrapper alone when its
  error-message shape differs.** `_graphql` keeps its inline parse: its message template embeds the
  per-call context in a shape the shared helper's template cannot reproduce byte-identically — and
  it's already one site.
- **Byte-identical error preservation via per-site `what`/`source` params** is what carried 19
  sites onto 5 helpers with zero test churn — tests monkeypatch `subprocess.run`, so
  gateway-internal extraction is invisible to the suite as long as messages and argv don't change.
- **Post-parse `isinstance` narrowing deliberately stays at call sites** (`_run_json` returns
  loosely-typed): fallback behavior differs per caller (raise vs `None` vs `()`), and caller-side
  narrowing kept the migration transparent to ty.

## `_rest_args` structural limits

A flat string-field dict cannot express repeated keys (per-label `-f labels[]=…`) or non-body `-F`
fields. The clean pattern: **the helper builds the regular prefix, the caller appends the irregular
tail** — preserving exact argv order, which matters because tests assert on args contents and
order. Bare `gh api <path>` GETs with no `-X` stay off the helper entirely: adding `-X GET` would
change the argv.

## Residual risk: the lowercase "not found" fold

The `_is_not_found` haystack fold is **substring-based** on a lowercase `"not found"`: a gh stderr
that merely *mentions* "not found" for a non-404 failure reads as a lookup miss on the four sites
that previously matched a plain 404. Sanctioned and regression-pinned — but **if a phantom-`None`
GitHub lookup bug ever surfaces, `_is_not_found` is the place to look.** This doc exists largely to
give that bug a findable home.

## Mutation-posting policies (the /pr-review verdict split)

The verdict-driven `/pr-review` work established three policy patterns for gateway mutations, and
was later **reshaped** from a single posting child to a parent-driven classify-then-act boundary
(see the parent-posts sub-point below):

- **The verdict-driven mutation split**: when an agent-posted artifact has a "nothing to say"
  outcome, give it a *distinct minimal* artifact — one 👍 reaction via the issues-reactions
  endpoint (which covers PRs and is idempotent for same-user duplicates) — rather than a
  degenerate version of the rich artifact. A shared result type absorbing a third `mode` value
  keeps the CLI branch trivial.
- **Asymmetric failure policies coexist in one gateway section**: the review poster keeps a
  fallback ladder (a review must never be lost), while the reaction poster is hard-fail with no
  fallback (nothing review-shaped is lost if it fails). Record the rationale in the section
  banner and pin both policies in tests.
- **In-session-only fields are enforced structurally**: the gateway functions simply have no
  parameter for the in-session `fyi` channel, so it *cannot* reach a GitHub payload. Prefer that
  shape over prompt-level "don't post it" policy.
- **Single→parallel parent-posts reshape**: `/pr-review` was converted from a **single posting
  child** to the **same classify-then-act shape as `/address`** — 2–3 read-only
  **angle-specialized** children report structured findings, and the **parent reconciles + posts**
  via a new warm tool (`post_pr_review`). The verdict split (rich COMMENT review when actionable; a
  single 👍 reaction when clean) is unchanged — it just moved to a parent-driven boundary. See
  `docs/learned/workflow/cold-door-client.md` for the reusable parent-posts warm-tool recipe and
  `docs/learned/pi/subagents.md` for the report-only reviewer-agent change.
- **Structural-symmetry insight (recorded in contracts §8.3, build deferred):** the old "child
  posts" door gave the parent **no terminal tool signal**, so it could never be a worker-driven
  `DriveStage`. The new `post_pr_review` ok-result + a `last_pr_review` workflow-state append is
  **structurally identical** to `address`'s `resolve_review_threads` + `last_review_batch` — what a
  worker's `applyEvent`/`evaluateTerminal` latches onto. **Reshaping a "child-posts" door to
  "parent-posts" incidentally unlocks headless-drivability** — worth noting even when deferring the
  build (promotion is a clean follow-up: a `DriveStage` arm + terminal branch + `cold_remote` door +
  seed-prompt mirror).

Residual: the reviewer agent-def is hand-committed in `.pi/agents/`, and agent-def delivery to
consumer repos is a known gap — a consumer running an old prompt against a new CLI gets a typed
bad-batch error. Acceptable at 0.0.1; remember it when the delivery gap closes.

## `repo_identity` — a third repo-view read shape (strict-on-incomplete)

`perk/github/repo.py::repo_identity(repo_root) -> RepoIdentity(name, url, default_branch)` is a
**third** repo-view read shape, distinct from the two that came before it:

- `prs.default_branch` reads `defaultBranchRef` only;
- `auth.check_repo_access` / `_exec._owner_repo` read `nameWithOwner` only;
- `repo_identity` fetches all three at once via a single
  `gh repo view --json name,url,defaultBranchRef`.

It **reuses the lenient `_exec` parse helpers** (`_opt_str`/`_opt_dict`/`_parse_json`/`_failed`) but
is **strict-on-incomplete**: a 0-exit payload missing any of the three required fields raises
`GitHubError` rather than returning a partial identity. It is **GitHub-only by construction** —
`gh repo view` resolves only a GitHub remote, so a remote-less / non-GitHub repo just exits non-zero
and the lenient `_failed` path raises (no special-casing needed). The re-export from
`perk/github/__init__.py` keeps `__all__` isort-sorted (`RepoIdentity` before `Review`,
`repo_identity` before `rerun_workflow_run`).

The read's **sole consumer** is the repo-authored-skills source derivation (`derive_repo_source`),
so this read and `init-external-cli.md`'s "Repo-authored skills" section move together — see that
doc for the network-skip-ordering and self-exclusion patterns that wrap this single read.

## gh GraphQL transport facts (#690)

Extending the gateway to `gh api graphql` (for the honest engagement reads) surfaced transport facts
that differ from REST `gh api`:

- **`gh api graphql` does NOT auto-template `{owner}/{repo}`** (unlike REST `gh api`) — pass explicit
  `owner` / `name` / `number` variables. `_owner_repo` was promoted from `reviews.py` into `_exec.py`
  as generic repo-context infra.
- **Cursor pagination:** only pass `-f cursor=<endCursor>` once you HAVE one — omit it on the first
  page so the nullable `$cursor` var defaults to `null`. `-f cursor=` (empty string) is **not** the
  same as `null`.
- **The not-found shape differs from REST (HIGH gotcha, live-verified).** A missing node makes
  `gh api graphql` **exit 1** with stderr `could not resolve to an Issue with the number of N` plus a
  body carrying `"errors":[{"type":"NOT_FOUND"}]` — lowercased, that is `not_found` /
  `could not resolve to`, which the shared `_is_not_found` REST check (`"not found"` / `"404"`) does
  **not** match. So a mandated not-found→`()` fold **silently broke**. The fix broadens `_is_not_found`
  to also match `not_found` and `could not resolve to`, re-fixtured against REAL output.
- **Lesson:** extending a shared gateway helper to a NEW transport (REST→GraphQL) requires confirming
  the error shape against **live** output (`gh api graphql -F number=<bogus>` reproduces it), not a
  guessed fixture.

## GitHub `Closes #N` autoclose fires ONLY on a default-branch merge (#694)

A merge into any **non-default** base (`[workflow] base`, `objective create --base`, a pinned
plan-header base) **silently never autocloses** — the plan issue strands open. The fix surfaces the
PR's real `base.ref` on the `PullRequest` dataclass (trailing defaulted `base_ref: str = ""`), then at
land **closes the github plan issue explicitly only when the base is a confirmed non-default branch**
(default-base lands stay byte-identical, relying on autoclose — a targeted fallback, not "always
close"). Three durable craft points:

- **Match the parser's expected shape, not just the field name.** The plan said project
  `base: .base.ref` (a string), but `_pull_request` calls `.get("ref")` on `base` — so the `--jq`
  projection must be `base: {ref: .base.ref}` (an **object**) to stay uniform with the REST payload.
- **Capture-before-reassign.** `merge_pr()` returns a synthetic `PullRequest` with no `base_ref`, so
  capture `pr_base` from the **pre-merge** `find_pr_for_branch` result before the merge reassigns `pr`.
- **Fail-open layering.** An unknown base short-circuits *without* calling `default_branch`, and a
  `default_branch` lookup failure also returns `False` — both arms defer to autoclose, never block the
  land.

Semantics change to note: `plan_issue_closed` is now `True` on a non-default-base github land. No TS
twin — the warm `/land` delegates to `perk pr land`, and the envelope change is purely additive.

## Gateway purification by hoisting a backend-specific read to the consumer

A gateway meant to be **backend-neutral** can silently accrete a **backend-specific** read. The
concrete case: a "pure" github gateway carried a **github-only direct-fetch fallback** with a
silently-missing Linear path — present *only* because the gateway couldn't reach the other backend
without a layering violation. The clean fix is a single move:

- **Delete the read from the gateway, make the value a parameter, and resolve it in the consumer**
  backend-neutrally **via the resolver** (which owns the id shape — dropping the old `isdigit()` gate).
  This **simultaneously** makes the gateway pure AND adds the missing backend fallback **for free**.

**Generalizable signal: a layering violation forcing backend-specific branching into a neutral layer
means the read belongs in the CONSUMER, passed down as a value.** Two corroborating details: the
load-bearing **import-direction guard** now actually bites (the gateway imports neither the backends
nor the state tier), and the `backend_id = "github"` module-level **literal** that breaks the
resolver↔adapter import cycle (cross-ref `objective-store.md`, where it's already noted).

## The resolved `dry_run` ruling (record)

Every gateway-mutation caller was audited: all dry-run-capable flows either plumb `dry_run` to the
op or guard/early-return before any mutation (offline previews for the PR verbs; the run-report
path is reached only from the remote worker, which has no dry-run mode). No forgotten
plumb-through — the `= False` defaults are audited and stay.

## Cross-references

- `perk/github/` — the gateway and the helper family
- `docs/learned/workflow/init-external-cli.md` — the repo-authored-skills convergence, sole consumer
  of the `repo_identity` read (network-skip ordering, sibling-fragment self-exclusion)
- `docs/learned/pi/extension-seams.md` — the TS sibling of idiom consolidation (minimal structural
  seams)
- `docs/learned/toolchain/ruff.md` — the preview-rule enablement collateral from the same sweep
- `docs/learned/workflow/cold-door-client.md` — the parent-posts warm-tool recipe (`post_pr_review`)
- `docs/learned/pi/subagents.md` — the report-only reviewer-agent change (read-only fan-out)
- `docs/learned/toolchain/python-package-splits.md` — the cross-package relocation arc that produced
  the gateway-purification refinement (the `backend_id` literal, the import-direction guard)
