---
title: The src/perk/github/ gateway package — parse-helper family, consolidation boundary rules, the not-found fold, mutation-posting policies, strict per-PR paginated reads, merge-async outcome classification
read_when: You are touching `src/perk/github/`, adding a REST/GraphQL call, designing a mutation-posting policy or failure ladder, debugging a phantom-`None` lookup, or parsing diffs into review-comment anchors.
cluster: backends-and-integrations
---

# The src/perk/github/ gateway package

`src/perk/github/` is the gateway package for `gh` subprocess calls (the `_exec.py` transport
helper family + the PR/CI/repo-tier reads and mutations). The GitHub backend's issue/objective
substrate (`src/perk/backends/github/`) rides the same `_exec` helpers — see `issue-backend.md`. A
dignified-sweep consolidation carried 19 hand-rolled parse sites onto a small helper family; this
doc preserves the boundary rules that made the migration safe and the one residual risk it
accepted.

## Distillation

- The parse-helper family is FIVE functions (`_run`, `_run_json`, `_parse_json`, `_rest_args`,
  `_graphql` untouched) because none-on-nonzero readers share only the parse step — "The
  five-function helper family — and why it's five, not four".
- What may/may not fold into a shared helper — "Consolidation boundary rules (these
  generalize)".
- The tolerant `_dicts`/`_opt_*` helpers ENCODE fail-open; a fail-closed boundary ("can't
  verify ⇒ don't promise") must validate strictly and raise — pick by the boundary's failure
  posture — "The tolerant helpers encode a fail-open posture".
- Mutation-posting policy patterns (the verdict-driven split, the parent-posts reshape, the
  failure ladder) — "Mutation-posting policies (the /pr-review verdict split)".
- `Closes #N` autocloses ONLY on a default-branch merge — non-default bases need the explicit
  close — "GitHub `Closes #N` autoclose fires ONLY on a default-branch merge".
- A journaled mutation classifies total-outcome by exact (status, body-state) pairs — a 5xx with
  a parseable body stays AMBIGUOUS — "The merge-async mutation — total-outcome classification +
  retry semantics".
- Reads split by completeness contract — bounded browse vs full census; "every open X" readers
  use `gh api --paginate --slurp` and fail closed on shape — "List-read completeness contracts
  (label-scoped reads)".

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
- **When a migration drops a module's `subprocess` import, census ALL module-attribute patch
  strings first.** The `perk.substrate.proc` centralization (`run_captured` + structured
  `ProcFailure` with canonical default `str()` shapes, resolving `subprocess.run` at call time on
  the shared module object so global monkeypatches survive; `src/perk/github/_exec.py` now sits atop
  it) removed facade modules' own `subprocess` imports — breaking every test patch that resolves
  *through* a facade module. `grep -rn "\.subprocess" tests/` finds them all, in BOTH forms:
  string-path patches (`monkeypatch.setattr("pkg.mod.subprocess.run", …)`) AND attribute-chain
  patches (`monkeypatch.setattr(pkg.mod.subprocess, "run", …)`). Each needs the mechanical
  retarget to the global `subprocess` module — behavior-identical, since the patch effect was
  already global. Evidence: the plan predicted five string-path retargets and missed a sixth
  attribute-chain patch (`_ext_install.npm.subprocess.run`), costing one failed run + an amend.

## The tolerant helpers encode a fail-open posture — pick by the boundary's failure posture

The tolerant `_dicts`/`_opt_*` helpers (`src/perk/github/_exec.py`) normalize malformed payloads
to empty/absent — `_dicts` folds a non-list payload to `[]` and drops non-dict elements. That is
right for fail-open reads, and **wrong at a fail-closed boundary** ("can't verify ⇒ don't
promise"): the branch-rules capability probe read a malformed payload as "no merge queue" and
promised what it couldn't verify. A fail-closed read must validate shapes strictly and raise
`GitHubError`, never normalize. The decision rule: pick the helper family by the boundary's
failure posture, not by convenience.

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
  `DriveStage`. The new `post_pr_review` ok-result + a `last_pr_review` workflow-state append follows
  the same terminal-evidence pattern as `address`'s `finalize_address` + `last_review_batch` — what a
  worker's `applyEvent`/`evaluateTerminal` latches onto. **Reshaping a "child-posts" door to
  "parent-posts" incidentally unlocks headless-drivability** — worth noting even when deferring the
  build (promotion is a clean follow-up: a `DriveStage` arm + terminal branch + `cold_remote` door +
  seed-prompt mirror).
- **Event-aware ladder for the human-in-the-loop review-door posting (`perk pr review-submit`,
  consumed by the warm `submit_pr_review` tool)**: the
  same one-atomic-review POST (`comments + body + event`), but the caller carries an explicit
  `--event` (the wire spellings `approve|request-changes|comment`; the dangerous formal verdicts
  always require explicit spelling). The failure ladder is **event-conditioned**: a failed COMMENT
  degrades to a discussion comment (the existing fallback), but a failed **formal** event
  (APPROVE/REQUEST_CHANGES) is retried **once** with the comments folded into the review body and
  the **event preserved** (`mode: "review_folded"`) — a formal verdict is *never* converted into a
  non-review comment, never silently dropped. Own-PR is classified *on failure* from the stable
  `your own pull request` 422 substring and surfaces as `OwnPrReviewError` (no retry — it would fail
  identically). Source pointers: the section banner + `_formal_review_fallback` arm of `post_pr_review`
  in `src/perk/github/reviews.py`.
- **A dry-run must validate *eligibility*, not just anchors.** A dry-run that checks content
  anchors but *not* event eligibility validates a doomed post — a dogfood run lost a human-approved
  curated batch to GitHub's atomic own-PR 422 *after* the dry-run reported "submittable". The
  pattern: **predict the deterministic platform rejection in the dry-run, before anchor
  validation**, and fail-open when the inputs are unresolvable. Concretely `--dry-run` on a formal
  event fetches the PR author (`get_pr_author` in `prs.py`) and refuses `own_pr` when it equals the
  authenticated viewer; an unresolvable login just falls through (a missing PR still surfaces as
  `pr_not_found` in anchor validation, and the real path keeps GitHub as the authority). Source
  pointer: `_check_own_pr_formal_event` in `src/perk/cli/commands/pr/review_submit_cmd.py`.
  **Generalize: any "submittable" verdict must cover every deterministic platform-rejection class,
  not just payload shape.**

Residual: the reviewer agent-def is hand-committed in `.pi/agents/`, and agent-def delivery to
consumer repos is a known gap — a consumer running an old prompt against a new CLI gets a typed
bad-batch error. Acceptable at 0.0.1; remember it when the delivery gap closes.

## The pure unified-diff anchor parser (`diff_anchors.py`)

`src/perk/github/diff_anchors.py` is the first (and only) unified-diff parser in `src/` — it walks a
PR's merge-base 3-dot diff into a commentable `{path -> frozenset[(side, line)]}` map so
`review-submit` can validate a review batch's `{path, line, side}` anchors *before* burning an atomic
review POST on a 422 (a `+` line anchors RIGHT/new, a `-` line anchors LEFT/old, a context line
anchors **both**). Two durable points:

- **Hunk-header old/new count bookkeeping is load-bearing — prefix-only `+`/`-` classification is
  wrong by construction.** A post-hunk `--- a/<path>` file header *starts with `-`*, so a parser
  that classifies lines purely by leading character reads that header as a deleted line. The
  `@@ -old,oldN +new,newN @@` counts delimit each hunk body precisely (advance the `old_remaining`/
  `new_remaining` counters, and only re-enter file-header handling once both hit zero); the *why*
  lives as a code comment in `parse_diff_anchors`.
- **Two reusable verification crafts:**
  - *End-to-end replay proof* — replay a real `git diff` through the parser and content-verify
    every `+` line's recorded RIGHT line number against the actual worktree file (the run that built
    this checked 1584 anchors against the tree, 0 mismatches). A pure parser earns real confidence
    only by re-deriving its output against ground truth, not just crafted fixtures.
  - *Numerically disjoint old/new hunk starts in side-specific rejection fixtures* — a fixture that
    proves a `-` line is not RIGHT-anchorable (and vice versa) must use non-overlapping LEFT/RIGHT
    line numbers, or a coincidental collision hides the bug. See the "Non-colliding numbering"
    fixture in `tests/test_github_diff_anchors.py::test_side_mismatches_rejected` (LEFT 2 is a pure
    deletion; RIGHT 41 is a pure addition).

## `repo_identity` — a third repo-view read shape (strict-on-incomplete)

`src/perk/github/repo.py::repo_identity(repo_root) -> RepoIdentity(name, url, default_branch)` is a
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
`src/perk/github/__init__.py` keeps `__all__` isort-sorted (`RepoIdentity` before `Review`,
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

## The merge-async mutation — total-outcome classification + retry semantics

The atomic-landing mutation (contracts §8.56; source pointers `src/perk/delivery/landing.py`,
`src/perk/github/`) hardened a set of rules for any gateway mutation whose outcome must be
journaled as proven-terminal vs ambiguous:

- **Classify total-outcome HTTP replies by exact (status, body-state) protocol pairs, never body
  alone.** A 5xx carrying a parseable `failed` body must stay *ambiguous*, not journal a
  proven-terminal — the server may have acted despite the error reply. Admit only the enumerated
  pairs (202/409 + pending, 200 + merged, 404, 400 + failed, bare 422); everything else is
  ambiguous. Pin the discordant case (5xx + parseable body) in tests.
- **A retry cannot conclude the first attempt's ambiguity with its own failure.** After an
  ambiguous mutation, only evidence that the first attempt succeeded/recovered resolves it — a
  retry-side 404/422/`failed` proves nothing about attempt one → stay pending, never abandon.
- **Post-merge verification corroborates identity, not just the MERGED bit** — the approved head
  OID, the branch, and the merge target. Plus the GitHub gotcha: deleting a merged stacked branch
  retargets its child PRs' base, so base verification needs delete-time retarget tolerance (the
  parent branch OR the objective base both pass).
- **"Byte-for-byte unchanged" is the wrong claim for an envelope that grows trailing fields** —
  claim "field prefix/order preserved" instead. And a mutation-path envelope constructor must
  re-derive every shared field the dry-run path derives — a field derived on one path and
  defaulted on the other is a silent divergence.

## Strict per-PR paginated reads (the landing-readiness land-facts read)

The landing-readiness read (the gateway's per-PR land-facts read) established the strict-read
shape for anything feeding a fail-closed consumer:

- **Per-PR strict paginated reads beat batched aliasing.** Aliased batch queries can't express
  independent per-alias pagination cursors, and GitHub gives no cross-PR snapshot consistency
  anyway — so batching buys nothing coherence-wise. One strict read per PR, with in-read
  coherence: repeated scalars are re-parsed on every page, and any drift across pages ⇒ error.
- **Strict reads validate identity + cardinality, not just field presence** — reject a
  non-list/empty/multi-member connection where the query implies exactly one member, and reject a
  payload whose PR number differs from the requested one. Test corollary: fixtures must
  distinguish omitted keys from explicit-null/empty values.
- **Multi-connection pagination needs per-connection state that retains exhausted cursors** — an
  exhausted connection stops accumulating but its final `endCursor` is still sent while the other
  connection pages on; add a cursor-progress rule (every page must advance at least one cursor)
  and a hard request cap.
- **Coherence-only fields stay gateway-internal** — transport-internal state (e.g. a rollup used
  only for the per-page coherence guard) is deliberately omitted from the pure view models.

Residual (both sections): the merge-async wire shapes and the readiness reads are
hermetic/fake-proven; live-host behavior is unproven until a dogfood node.

## List-read completeness contracts (label-scoped reads)

The incident class first (#2003): **a truthful report over a silently truncated census is the
most dangerous partial-failure shape** — any read whose contract says "every open X" is in this
class the moment it uses a default-page list read. A first-page-only idempotency finder mints
duplicates past ~30 open issues. The rules (#2003, #2004):

- **Split reads by completeness contract, not endpoint.** *Bounded browse* (one default page,
  membership beyond it not promised) vs *full census* (idempotency finders, learn/gist
  inboxes). The fix kept two helpers so bounded callers had zero churn; the `find_plan_issue`
  parameterization backs the learn/gist/objective finders.
- **`gh api --paginate --slurp` is the exhaustive mechanism:** Link-header termination, one
  subprocess (existing error handling intact), an array-of-page-arrays payload to flatten. It
  needs gh ≥ 2.48.0 (documented-not-probed — an older gh fails loudly with `unknown flag`) and
  is incompatible with `--jq`. Hand-rolled page loops over `gh api` are a smell.
- **Census boundaries are fail-closed.** An unexpected slurp shape raises, and for an
  authoritative census read empty stdout raises — only a genuinely parsed `[]` reads as empty.
  The bounded browse keeps its tolerant `[]` fold.
- **Latent same-class residual:** comment-list finders (`find_comment_id_by_marker`) stay
  unpaginated past ~30 comments — a marker placed late in a long thread is exposed.

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

## Response converters validate through lenient parse models

The gateway's response converters (`_pull_request` / `_parse_review_threads` / `_parse_reviews` /
the issue + workflow-run reads) now validate the raw `gh` JSON through **lenient parse models**
(`PullRequestModel`, `WorkflowRunModel`, `ReviewThreadModel` / `ReviewModel` / `ReviewCommentModel` +
`_Actor`, `IssueReadModel`) before converting into the frozen domain objects. The converters keep
their names + signatures; only their bodies become `Model.model_validate(raw).to_domain()`, wrapped
at each **call site** with `translate_validation_errors(GitHubError, source=<operation label>)`. The
edge posture is identity-required / rest-tolerant (byte-identical happy path; only a
present-but-malformed payload changes — now a labelled `GitHubError` instead of a raw
`KeyError`/`ValueError`), and lookup-miss guards (`none_on_not_found` / `"databaseId" not in data`)
run **before** validation so a legitimate miss never becomes a raise. The full recipe (call-site
validation, `AliasChoices` for two wire shapes, the `object`-param widening, nested-children
composition) lives in `pydantic-boundary-models.md` — not duplicated here.

## Cross-references

- `src/perk/github/` — the gateway and the helper family
- `docs/learned/workflow/pydantic-boundary-models.md` — the boundary↔domain conversion recipe (the
  gateway response converters apply its lenient-parse-model → frozen-dataclass pattern)
- `docs/learned/workflow/init-external-cli.md` — the repo-authored-skills convergence, sole consumer
  of the `repo_identity` read (network-skip ordering, sibling-fragment self-exclusion)
- `docs/learned/pi/extension-seams.md` — the TS sibling of idiom consolidation (minimal structural
  seams)
- `docs/learned/toolchain/ruff.md` — the preview-rule enablement collateral from the same sweep
- `docs/learned/workflow/cold-door-client.md` — the parent-posts warm-tool recipe (`post_pr_review`)
- `docs/learned/pi/subagents.md` — the report-only reviewer-agent change (read-only fan-out)
- `docs/learned/toolchain/python-package-splits.md` — the cross-package relocation arc that produced
  the gateway-purification refinement (the `backend_id` literal, the import-direction guard)
