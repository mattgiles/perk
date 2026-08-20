# perk providers & issue backends

Provider selection and issue-backend selection are independent:

- A **provider** supplies one Pi-facing `plan`, `footer`, or `web` surface. Each `[providers]`
  key selects one id from the supported catalog.
- The **issue backend** owns canonical plan, learning, gist, and objective state. One committed
  `[issues]` selection chooses both the issue-operation protocol and the distinct objective-store
  protocol, keeping them in the same tracker family.

Provider selection never changes the tracker. Backend selection never chooses plan, footer, or web
tools. Pull requests, review, CI, and merge remain GitHub operations under either backend.

## Supported provider catalog

`shared/providers.yaml` is the catalog read by the Python exterior and TypeScript interior in
declaration order. Exactly one entry per seam is the no-selection default.

| Provider id | Seam | Default | Posture | Package |
| --- | --- | --- | --- | --- |
| `perk-plan` | `plan` | yes | reference (native) | — |
| `tombell-plan` | `plan` | — | REPLACE | `npm:@tombell/pi-plan` |
| `plannotator-plan` | `plan` | — | AUGMENT | `npm:@plannotator/pi-extension` |
| `perk-footer` | `footer` | yes | reference (native) | — |
| `powerline-footer` | `footer` | — | REPLACE (vacate-only) | `npm:pi-powerline-footer` |
| `pi-bar-footer` | `footer` | — | REPLACE (vacate-only) | `npm:pi-bar` |
| `pi-status-footer` | `footer` | — | REPLACE (vacate-only) | `npm:@tombell/pi-status` |
| `pi-default` | `footer` | — | install nothing | — |
| `pi-web-access` | `web` | yes | reference (foreign package) | `npm:pi-web-access` |
| `ollama-web-search` | `web` | — | REPLACE (vacate-only) | `npm:@ollama/pi-web-search` |
| `juicesharp-web-tools` | `web` | — | REPLACE (vacate-only) | `npm:@juicesharp/rpiv-web-tools` |

The defaults are `perk-plan`, `perk-footer`, and `pi-web-access`.

## Provider postures

### Plan seam: durable-artifact adapters

The plan seam must always produce perk's reviewed, canonical plan artifact.

- **`perk-plan` — reference.** perk registers its complete authoring surface and writes the result
  through `plan_save` into the plan reference used by later stages.
- **`tombell-plan` — REPLACE.** perk does not register `/plan`, `--plan`, or `Ctrl+Alt+P`, avoiding
  collisions with `@tombell/pi-plan`. The `planAdapterTombell` prompt bridge directs foreign prose
  through perk's own review/save contract. It does not drive the foreign tool and does not bypass
  perk's read-only gate.
- **`plannotator-plan` — AUGMENT.** perk retains `/plan`, authoring context, and the read-only gate,
  but vacates `--plan`, `Ctrl+Alt+P`, and the colliding startup handler. `planAdapterPlannotator`
  sends the draft through `plan_review` to the browser. Approval without direct edits uses the
  ordinary approval/save seam. Approved plan direct edits are applied and the edited bytes saved;
  an unapplyable diff falls back to the original bytes with a warning. Approved objective or gist
  direct edits do not save: they return one revise round so the agent folds the edits into the
  structured draft and re-reviews. Denial returns feedback to the agent.

The warm `/pr-review-browser` door also uses plannotator when that package is installed. It can
review a foreign PR, the active worktree's PR, or a local since-base diff before submission. That
PR-review choice is command-owned, not a provider seam.

A plan reference's `provider` field means the **issue backend** (`github` or `linear`), never the
plan-provider id.

### Footer seam: vacate-only

The footer has no durable artifact and no adapter.

- `perk-footer` installs perk's footer in a headful session.
- `powerline-footer`, `pi-bar-footer`, and `pi-status-footer` make perk skip that installation so
  the selected package owns the single footer slot.
- `powerline-footer` and `pi-bar-footer` render extension statuses, so objective progress remains
  visible. `pi-status-footer` does not; hidden objective progress is its accepted limitation.
- `pi-default` skips perk's footer and installs no replacement, leaving Pi's stock footer.

### Web seam: package selection

perk registers no native web tools. Every web entry is therefore vacate-only with no adapter, and
the default `pi-web-access` is itself a foreign package.

Provider tool vocabularies are not normalized:

- `pi-web-access`: `web_search`, `fetch_content`, and `get_search_content` (`code_search` stays
  allowlisted for version tolerance);
- `ollama-web-search`: `ollama_web_search` and `ollama_web_fetch`;
- `juicesharp-web-tools`: `web_search` and `web_fetch`.

The read-only gate recognizes the union. `pi-web-access` is zero-config; `ollama-web-search`
requires a local Ollama daemon; `juicesharp-web-tools` requires an API key. The bundled `librarian`
skill is specific to `pi-web-access`, so either alternative removes it from the delivered surface.

### Built in, not selectable

`ask_user_question` and `todo` are borrowed built-ins installed in every managed repository through
`@juicesharp/rpiv-ask-user-question` and `@juicesharp/rpiv-todo`. They are not provider seams. The
retired `[providers] askuser`, `[providers] todo`, and `[providers] review` keys hard-fail config
validation with removal guidance. `/pr-review-terminal` selects hunk and `/pr-review-browser`
selects plannotator directly.

## Provider selection, convergence, and fallback

`perk init` reconciles provider-managed `.pi/settings.json` package entries in both directions:

- every selected catalog package is added in Pi's package-object form;
- a supported provider package is removed when no selected seam wants it;
- null-package providers add nothing;
- default `pi-web-access` is still added because its catalog entry names a package;
- borrowed packages and unrelated operator-managed packages remain untouched.

Desired packages are computed across all seams before mutation, so sharing cannot cause accidental
removal. If config is malformed, ill-typed, or contains a retired provider key, init cannot prove
intent and performs no provider add/removal. The config check reports the error and a later init
converges once config is valid.

The hunk CLI is independent of provider selection. Verified init tries best-effort
`npm install -g hunkdiff` when `hunk` is absent; failure is a warning with the manual install hint.
The verify-gated `review-cli` doctor check reports availability and `doctor --fix` retries.

Both planes resolve one provider per seam:

- absent key → catalog default, silently;
- unknown id or id from the wrong seam → one warning and that seam's default;
- one bad seam does not switch another seam or ordinarily crash the session.

A catalog with no default is corrupt installation/version-skew, not an ordinary selection error.
The short-lived Python CLI fails it as corrupt installation. A long-lived TypeScript session may
have loaded code against changed catalog bytes, so it synthesizes the known reference fallback for
only that seam and reports the problem. Config-read catches likewise report and fall back to
reference behavior.

`perk doctor` reports `plan=…`, `footer=…`, and `web=…`. Catalog load/validation failure is an
installation failure; selection fallback is a warning. Package drift is repaired by the existing
`settings-wiring` convergence.

## Issue backend comparison

| Concern | GitHub | Linear |
| --- | --- | --- |
| Selection | default when absent or `github` | `backend = "linear"` plus a team key |
| Auth | authenticated `gh` CLI | personal `LINEAR_API_KEY` as plain `Authorization` |
| Plan/learn/gist | GitHub Issues | Linear issues; objective-scoped gist may be a light Project |
| Objective | one Issue plus first comment | one Project, node-issues, milestones, relations, metadata sentinel |
| PR/review/CI/merge | GitHub | still GitHub |
| Identifiers | numeric issue ids / `#42` | issue ids such as `ENG-123`; opaque Project ids |
| Metadata | readable HTML-comment blocks | machine envelopes in native issue attachments |

The `[issues]` table is read only from the **main checkout's committed** `.perk/config.toml`, even
when a command runs in a linked worktree. `.perk/local.toml` cannot override backend or team. A
branch-local backend edit takes effect only after it reaches the main checkout.

## GitHub backend

GitHub is zero-config: an absent `[issues]` table and explicit `backend = "github"` resolve
`GitHubIssueBackend` and `GitHubObjectiveStore`.

Authentication uses `gh` and the current repository remote. Verify-gated doctor checks are:

- `github-auth`: authenticated account;
- `github-repo`: repository resolution and push access.

The shared offline `issues-backend` check validates selection before network readiness.

Plans, learnings, plan-scoped gists, and objective-scoped gists are GitHub Issues. Writes lazily
ensure their relevant `perk:*` labels. Numeric ids are commonly rendered `#42`; id-taking commands
accept `.../issues/42` URLs but reject `.../pull/42` URLs.

A GitHub objective is one Issue. The issue body owns the objective header and canonical roadmap;
its first comment owns the rendered roadmap table and Reconcilable prose. Metadata remains readable
as marker-bounded blocks inspectable with `gh issue view`. The roadmap block is the authoritative
manifest.

Plan selection is positively identified by the plan-header body block: the explicit-id plan doors
(`implement`, `address`, `ready`, `plan resume`) refuse an existing issue without one
(`issue_kind_mismatch`; an objective issue's refusal names `perk objective plan <N>`). Plan-header
writes are merge-only — `update_plan_header` refuses a blockless body (creation is confined to
plan-issue creation and in-place adoption). A malformed-but-present block degrades to an empty
header on read while still identifying a plan (the tolerant GitHub read posture).

GitHub replan creates a new issue, carries unfinished roadmap rows as fresh rows, stamps the
predecessor/successor lineage, and closes the old issue after the successor is established. There
are no node-issue moves or backend-native node-cancellation projections.

## Linear backend

### Selection, auth, and package

Committed configuration requires the Linear team **key**, not display name:

```toml
[issues]
backend = "linear"
team = "ENG"
```

A personal `LINEAR_API_KEY` resolves from a non-blank environment variable first, then
`[linear] api_key` in the main checkout's gitignored `.perk/local.toml`. This makes one local secret
available to linked worktrees without copying it. It is sent as `Authorization: <key>`, never
Bearer-prefixed. Interactive `perk init` can prompt for a missing key, validate it, and store the
file with restrictive permissions; non-interactive, non-TTY, and JSON modes never prompt.

`perk init` adds `npm:pi-mono-linear` when Linear is selected and removes it when deselected.
Hand-adding that package without selecting Linear is unsupported.

### Issue storage, labels, and identifiers

Plans, learnings, and plan-scoped gists are Linear issues. An objective-scoped gist first uses the
objective store to create a deliberately light Project containing only its name/overview; if that
path is unavailable, it falls back to the issue tier.

Readiness looks up or ensures six workspace labels: `perk:plan`, `perk:learn`, `perk:gist`,
`perk:consolidated`, `perk:objective`, and `perk:objective-node`. Every perk-created issue is
assigned to the API-key user.

Issue identifiers use team form such as `ENG-123`; worktrees use `plan-ENG-123`, and land writes
`Plan: ENG-123 — <url>` instead of `Closes #N`. Commands accept Linear issue URLs and Project URLs,
peel an opaque id, and leave resolution to the configured backend.

Plan selection is positively identified by the plan-header **attachment**: the explicit-id plan
doors refuse a Linear issue without one (`issue_kind_mismatch`, no right-door hint), and a Linear
**Project** id resolves `plan_not_found` (a Project is not an issue). `update_plan_header` is
merge-only (creation is confined to plan-issue creation, adoption, and the node-plan unification
writer). Unlike GitHub's tolerant body-block read, a perk-marked plan attachment with a corrupt
payload **fails loud** at every plan read — fail-early at the door, before any side effect;
presence-only tolerance lives only in the adoption/doctor reads.

### Readiness checks

Offline `issues-backend` rejects an unknown backend or Linear without a team. The verify-gated,
non-fatal Linear checks run in explanatory order:

1. `linear-auth` resolves the personal-key viewer;
2. `linear-team` resolves the committed team key;
3. `linear-labels` verifies all six labels (`init` and `doctor --fix` can ensure them);
4. `linear-project-scopes` verifies Project read access;
5. `linear-workflow-states` verifies unstarted, started, completed, and canceled state types.

The latter checks report workspace readiness; they do not mutate Project scopes or workflow states.

### Project-backed objectives

A Linear objective is a Project, not an issue. Its overview contains the copyable command callout
and human Reconcilable prose. Each roadmap node is an issue attached to the Project, each phase is
a Project Milestone, and explicit dependencies are Linear blocking relations. The Project's opaque
id is perk's objective id.

Native attributes and fail-open mirrors include:

- API-key user as Project lead and assignee of perk-created issues;
- start date on new Projects;
- best-effort Project move to Started when node work starts and Completed on objective closure;
- Project Updates on objective creation, plan landing, and reconciliation;
- a native Linear sidebar attachment added/updated when a GitHub PR is stamped.

The PR itself, review, CI, and merge remain GitHub-authoritative.

### Native attachment metadata

Plan, learning, gist, objective-node, objective-header, and objective-manifest bookkeeping uses
native Linear issue attachments with machine-readable envelopes. A stable attachment URL is the
upsert identity; updates replace the whole envelope. Issue descriptions and Project overviews stay
human prose.

Because Linear has no project-level arbitrary metadata attachment, every full objective carries a
small sentinel issue named `Perk: objective metadata`, linked to the Project and normally born in
the canceled state. Its two attachments hold the objective header and structural manifest. Each
node-issue carries node metadata and, after planning, plan metadata. Prose-level plan-body callouts
and Reconcilable markers use Linear-safe inline-code sentinels where they must remain in text.

This attachment model is a clean break. Inline metadata from earlier perk versions is not read;
those Linear artifacts must be re-created or re-saved.

### The dream-report companion

Dormant until the `perk learn dream` door ships. A dream-session objective persists the reviewed
dream report as immutable marker-keyed comments (`perk:learn-dream-report:<run_id>:<part>`) on
its report carrier: GitHub — the objective issue itself (the comments are the human-visible
report); Linear — the Project's metadata sentinel issue, plus an uploaded markdown asset linked
in the Project's **Resources** as `Dream report (<run_id>)`. The `objective-header` records the
carrier id under `dream_report`. Saves converge idempotently; a changed part fails loudly.

Documented residual: a crash after Project creation but before the sentinel exists leaves an
orphan Project invisible to every perk lookup (the dream-origin guard included); a retried dream
save creates a fresh Project. Identify the orphan by its missing `Perk: objective metadata` issue
and header attachment, and delete it manually — it holds no perk state and no report parts.

### Replan and cancellation

Linear replan creates a new Project, moves carried unfinished node-issues into it (preserving
identity, discussion, and open PRs), and moves dropped open node-issues to a canceled workflow state
when available. It links both objective headers and completes the old Project only after the
successor is established.

For stacked objectives on either backend, replan uses the interruption-safe transfer protocol:
published plans carry in exact order, the old objective closes only after successor verification,
and `perk objective stack recover <old-id>` concludes an interrupted transfer.

A human-canceled Linear node-issue reads as an effective `skipped` projection while its attachment
status remains unchanged for diagnosis. `perk objective doctor --fix` persists the skip only after
positive proof that it is unpublished future work with no conflicting identity, checkpoint,
publication, branch, PR, or journal claim. Anything unprovable remains a visible canceled layer
with blockers.

### Optional AgentSession emission

A separate `LINEAR_AGENT_TOKEN` can opt an implement run into a one-way, fail-soft mirror in
Linear's Agents UI. It must be an OAuth `actor=app` token and is sent as
`Authorization: Bearer <token>`; the personal API key cannot call this API. Without the agent token,
emission is dormant. The operations are covered against offline fakes but remain unverified against
a live workspace, so this is not part of ordinary Linear readiness.

## Current caveats and maturity

- Linear has broad offline regression coverage and dated live validation for the core issue
  lifecycle, project-backed objectives, and native attachment behavior. A green offline suite does
  not prove one workspace's auth, team, labels, Project scopes, or workflow states; run the
  verify-gated checks.
- Core lifecycle was live-validated 2026-06-15, project-backed objectives 2026-06-16, and native
  attachment semantics in a 2026-07-12 spike. Do not generalize those point-in-time proofs to every
  workspace.
- Linear `RATELIMITED` GraphQL failures are loud and have no retry/backoff. Low-volume validation
  has not exercised rate limiting.
- AgentSession emission is off by default and not live-verified.
- GitHub Issues Sync interactions are outside coverage; prefer a team without that two-way sync
  unless separately validated.
- `pi-status-footer` hides extension status; non-default web providers have local credential or
  daemon requirements and remove the `pi-web-access`-specific `librarian` skill.

Canonical operator sources:

- `docs/user-docs/reference/providers-and-backends.md`
- `docs/user-docs/reference/providers-and-backends/providers.md`
- `docs/user-docs/reference/providers-and-backends/issue-backends.md`
