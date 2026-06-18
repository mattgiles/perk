---
title: The github.py gateway — parse-helper family, consolidation boundary rules, the not-found fold, mutation-posting policies
read_when: You are touching `perk/github/`, consolidating repeated subprocess/parse idioms, debugging a phantom-`None` GitHub lookup, adding a REST/GraphQL call, or designing a mutation-posting policy (failure ladders, verdict-driven artifacts).
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

## The resolved `dry_run` ruling (record)

Every gateway-mutation caller was audited: all dry-run-capable flows either plumb `dry_run` to the
op or guard/early-return before any mutation (offline previews for the PR verbs; the run-report
path is reached only from the remote worker, which has no dry-run mode). No forgotten
plumb-through — the `= False` defaults are audited and stay.

## Cross-references

- `perk/github/` — the gateway and the helper family
- `docs/learned/pi/extension-seams.md` — the TS sibling of idiom consolidation (minimal structural
  seams)
- `docs/learned/toolchain/ruff.md` — the preview-rule enablement collateral from the same sweep
- `docs/learned/workflow/cold-door-client.md` — the parent-posts warm-tool recipe (`post_pr_review`)
- `docs/learned/pi/subagents.md` — the report-only reviewer-agent change (read-only fan-out)
