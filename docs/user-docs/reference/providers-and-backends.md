# Providers & issue backends

This page describes perk's **pluggable provider seams** (plan-authoring and todo/checkpoints) and
the **Linear issue backend**: the supported provider set, each provider's wiring posture, and the
Linear backend's auth, labels, identifiers, doctor groups, and current maturity. It describes the
surface; it does not teach a task (those belong in [how-to/](../how-to/index.md)) or argue a design
(those belong in [explanation/](../explanation/index.md)). See the [user-docs router](../index.md)
for how this quadrant fits the whole.

This page is **human-reviewed for accuracy** against the provider catalog
(`shared/providers.yaml`), the config readers (`perk/substrate/providers.py`,
`perk/backends/resolve.py`), and the Linear backend (`perk/backends/linear/`,
`perk/convergence/init.py`, `perk/convergence/doctor.py`) — provider and Linear surfaces are not
`--help`-introspectable, so accuracy is the governing virtue, like the
[configuration reference](./configuration.md).

## Orientation

Two related but distinct knobs live here:

- **Provider seams** — the *plan-authoring* surface, the *todo/checkpoint* surface, and the
  *ask-user* tool are each a **seam** that a foreign Pi package can fill in place of perk's bundled
  default. There are five seams: `plan`, `todo`, `askuser`, `footer`, and `web`.
- **Issue backend** — where canonical durable state is stored: GitHub (the default) or Linear.
  The `[issues]` selection governs **two storage tiers** — the *issue-tracking tier* (plan / learn
  issues, stored as issues under **either** backend) and the *objective-storage tier* (objectives,
  stored as an **issue** under GitHub but as a **Linear Project** under Linear).

Both are selected by config keys documented at key depth in the
[configuration reference](./configuration.md) — the `[providers]` table (`plan` / `todo` /
`askuser` / `footer` / `web`) and the `[issues]` table (`backend` / `team`). This page documents the **supported set** behind those keys
and what selecting each option actually does. The **selection** is the per-repo pointer; the
**supported set** is the catalog perk knows how to wire.

For the task recipes, see
[How to select a plan or todo provider](../how-to/select-a-provider.md) and
[How to switch the issue backend to Linear](../how-to/switch-to-linear.md).

## Provider seam — the supported set

The supported provider catalog is `shared/providers.yaml`, read directly by both planes
(`perk/substrate/providers.py`, `extension/substrate/providers.ts`). Every provider below is a
**fully-supported, selectable** option; perk's own bundled providers (`perk-plan`,
`perk-checkpoints`, `perk-ask-user`, `perk-footer`) are the zero-config **defaults** — the no-config hard guarantee — but the
foreign providers are first-class selections, not experiments.

| Provider id | Seam | Default? | Posture | Foreign package |
| --- | --- | --- | --- | --- |
| `perk-plan` | `plan` | ✅ | reference (native) | _(none)_ |
| `tombell-plan` | `plan` | | REPLACE | `npm:@tombell/pi-plan` |
| `plannotator-plan` | `plan` | | AUGMENT | `npm:@plannotator/pi-extension` |
| `perk-checkpoints` | `todo` | ✅ | reference (native) | _(none)_ |
| `juicesharp-todo` | `todo` | | runtime-defer | `npm:@juicesharp/rpiv-todo` |
| `perk-ask-user` | `askuser` | ✅ | reference (native) | _(none)_ |
| `juicesharp-ask-user` | `askuser` | | REPLACE (vacate-only) | `npm:@juicesharp/rpiv-ask-user-question` |
| `perk-footer` | `footer` | ✅ | reference (native) | _(none)_ |
| `powerline-footer` | `footer` | | REPLACE (vacate-only) | `npm:pi-powerline-footer` |
| `pi-bar-footer` | `footer` | | REPLACE (vacate-only) | `npm:pi-bar` |
| `pi-status-footer` | `footer` | | REPLACE (vacate-only) | `npm:@tombell/pi-status` |
| `pi-default` | `footer` | | install nothing (pi stock footer) | _(none)_ |
| `pi-web-access` | `web` | ✅ | reference (foreign package) | `npm:pi-web-access` |
| `ollama-web-search` | `web` | | REPLACE (vacate-only) | `npm:@ollama/pi-web-search` |
| `juicesharp-web-tools` | `web` | | REPLACE (vacate-only) | `npm:@juicesharp/rpiv-web-tools` |

### Postures

How perk yields its own surface to a selected foreign provider differs by provider:

- **REPLACE (`tombell-plan`).** perk **vacates** its plan surface at *registration* time: under a
  `tombell-plan` selection, perk does not register its own `/plan` command, `Ctrl+Alt+P` shortcut,
  or `--plan` flag, so the foreign package is the sole registrant (Pi suffixes duplicate command
  names). perk's `planAdapterTombell` shim bridges the foreign free-form prose surface to perk's
  canonical `plan_save` → `cache.plan-ref` contract.
- **AUGMENT (`plannotator-plan`).** perk **keeps** its plan surface — the `/plan` command, the
  plan-authoring injection, and the read-only gate all stay registered. perk skips only the two
  real registration collisions: the `--plan` flag and the `Ctrl+Alt+P` shortcut (both of which
  plannotator also registers; duplicate flag/shortcut registration is the known potentially-fatal
  Pi behavior). The `planAdapterPlannotator` shim bridges the model-callable `plan_review` tool to
  plannotator's browser plan-review event flow; saving stays the human-run `/plan-save`.
- **Runtime-defer (`juicesharp-todo`).** perk's own checkpoints simply **defer at runtime** — there
  is no registration-time vacating, because the todo seam has no command-name collision. The
  `todoAdapterJuicesharp` shim carries perk's implement-progress discipline onto the foreign
  checklist overlay (injection-only, gated to an active workflow).
- **REPLACE / vacate-only (`juicesharp-ask-user`).** The `askuser` seam is an **interface seam** —
  its contract is the tool *name* `ask_user_question` plus its non-terminating-answer semantics,
  with no durable artifact to bridge. The foreign `@juicesharp/rpiv-ask-user-question` extension
  registers a tool with the **identical name** `ask_user_question` (a richer multi-question
  dialog), and tools (unlike commands) are not numerically suffixed — a same-named tool
  replaces/warns by load order. So under a `juicesharp-ask-user` selection perk **vacates at
  registration time**: `registerAskUser` registers **nothing**, leaving the foreign tool as the
  sole `ask_user_question`. There is **no adapter shim** (`adapter: null`); the foreign tool
  self-documents via its own guidelines.
- **REPLACE / vacate-only (`powerline-footer`, `pi-bar-footer`, `pi-status-footer`).** The `footer`
  seam is the second **interface seam** — the footer produces no durable artifact, so there is
  nothing to bridge. perk installs its own footer (`installPerkFooter`) inside its `session_start`
  handler, so under a foreign footer selection perk **vacates at install time**: it simply does not
  call `installPerkFooter`, leaving the foreign footer (`pi-powerline-footer`, `pi-bar`, or
  `@tombell/pi-status`) as the sole footer surface. There is **no adapter shim** (`adapter: null`).
  For `powerline-footer` / `pi-bar-footer`, perk's objective/checkpoints progress still reaches the
  foreign footer automatically because both render extension statuses, and perk's composed `perk`
  status slot keeps publishing those segments regardless of footer ownership. **`pi-status-footer`
  is the exception:** `@tombell/pi-status` does **not** render extension statuses, so perk's
  objective/checkpoints progress is **not shown** in the footer when it is selected — an accepted
  limitation (it matches what pi-status already does today; perk does not build a status-bridge
  adapter for it).
- **Install nothing (`pi-default`).** Selecting `pi-default` (`package: null`) tells perk to add
  **no** footer package at all and to vacate its own install gate, leaving **pi's stock built-in
  footer** in place. Use this when you want neither perk's footer nor any foreign footer extension.
- **REPLACE / vacate-only (`ollama-web-search`, `juicesharp-web-tools`), with a foreign default.**
  The `web` seam is the third **interface seam** — its providers share no durable artifact *and* no
  common tool name, so there is nothing to bridge and **no adapter shim** (`adapter: null`).
  Selection simply **swaps the installed web package**; perk registers **no** web tools of its own,
  so there is **no perk surface to vacate** at all. The seam is **novel** in one way: its default
  (`pi-web-access`) is itself a **foreign package** — perk owns no native web implementation, so
  this is the one seam whose reference provider has a non-null package. The three providers expose
  **divergent tool names** (`pi-web-access`: `web_search`/`code_search`/`fetch_content`/
  `get_search_content`; `@ollama/pi-web-search`: `ollama_web_search`/`ollama_web_fetch`;
  `@juicesharp/rpiv-web-tools`: `web_search`/`web_fetch`); perk does **not** normalize them — the
  read-only allowlist carries the **union**. Only `pi-web-access` is zero-config; `@ollama/pi-web-search`
  needs a **local Ollama daemon** and `@juicesharp/rpiv-web-tools` needs an **API key**. Selecting a
  foreign web provider also **drops the bundled `librarian` skill** (it is pi-web-access-specific).

### What selection does

- **`perk init` converges the package.** Selecting a foreign provider adds its npm package to
  `.pi/settings.json` `packages`; deselecting it removes the entry. The convergence is
  two-directional (`_converge_provider_packages` in `perk/convergence/init.py`). perk's own
  reference providers have no package — nothing is added. (The `web` default `pi-web-access` is the
  exception: it *is* a foreign package, so a default repo still has `npm:pi-web-access` wired — now
  via the provider path, not the borrowed set.)
- **`perk doctor` reports the resolution.** The `providers` check resolves the selection and reports
  `plan=…, todo=…, askuser=…, footer=…, web=…`. It **warns** on problems but is never fatal — the default path is the hard
  guarantee.

### Fallback semantics

Selection lives in the flat `[providers]` table and is resolved by `resolve_providers`
(`perk/substrate/providers.py`):

- **Absent** key → falls back to the seam default **silently**.
- **Unknown id or wrong-seam id** → falls back to the seam default **loud-but-non-fatal** (a
  warning, never a crash).

## Issue backend — Linear reference

The `[issues] backend` vocabulary is `"github"` (default) or `"linear"`
(`perk/backends/resolve.py`), read **committed-only** from `.pi/perk.toml` — a
`.pi/perk.local.toml` value is silently ignored (this keeps the canonical issue store
deterministic). Switching to Linear changes where canonical plan / learn / objective issues live.

The one `[issues]` selection governs **two storage tiers**: the issue-tracking tier (plan / learn
issues) and the objective-storage tier (objectives). Objectives go through a distinct
`ObjectiveStore` seam rather than the issue backend directly, but it shares this selection — an
objective and its plan/learn issues always live on the same tracker. Both tiers are **issue-backed**
under GitHub and Linear today.

### Auth

- **`LINEAR_API_KEY`** — a personal Linear API key (linear.app → Settings → Security & access),
  supplied as an **environment variable** or via the gitignored `.pi/perk.local.toml`
  `[linear] api_key` (an exported env var wins); **never** in a committed file (contracts §8.21).
  perk reads this from the **main checkout's** `.pi/perk.local.toml` even when a command runs
  inside a linked worktree (the gitignored file is never copied into worktrees), so a single entry
  in the main checkout authenticates every worktree session and cold-door (`/submit`, `/land`, …).
  Setting it in `perk.local.toml` feeds both perk's Linear backend and the in-session `linear_*`
  tools.
- The key is sent as a **plain `Authorization: <key>`** header — **not** `Bearer`-prefixed.

### Required config

- **`[issues] team`** — the Linear team key (e.g. `"ENG"`), required when `backend = "linear"`.

### Converged package

`perk init` converges **`npm:pi-mono-linear`** — the borrowed Linear-tools Pi extension — into
`.pi/settings.json` `packages` when Linear is selected, and removes it when deselected
(`_converge_linear_package` / `LINEAR_PACKAGE` in `perk/convergence/init.py`).

### Ensured labels

The init readiness probe (`check_readiness` / `_PERK_LABELS` in
`perk/backends/linear/readiness.py`) ensures the five perk labels exist on the workspace. They are
created **workspace-scoped** (no `teamId` on create), matching Linear's cross-team-label guidance:

- `perk:plan`
- `perk:learn`
- `perk:consolidated`
- `perk:objective`
- `perk:objective-node` — on Linear project-backed roadmap node-issues (additive
  filterability; discovery is still by project membership + the node block)

### Identifier shapes

Linear issue ids are **strings** like `ENG-123` (vs GitHub's `#42`). The shape flows through:

- `cache.plan-ref.provider == "linear"`,
- the worktree / branch name `plan-ENG-123`,
- the land squash-commit footer `Plan: ENG-<n> — <url>` (no `Closes #N`, no Linear magic words).

### Doctor groups

- **`issues-backend`** (group `issues`, offline) — validates the selection and, for Linear, that
  `team` is set.
- **`linear-auth` / `linear-team` / `linear-labels`** (group `linear`, verify-gated) — the network
  probes; always non-fatal `warn`, run only under `perk init --verify` / `perk doctor` with
  verification.
- **`linear-project-scopes` / `linear-workflow-states`** (group `linear`, verify-gated, non-fatal)
  — the project-backed objective readiness probe: that the API token can read the team's Projects
  (the substrate every project-backed objective op depends on) and that the team exposes the
  workflow states the node-status board mirror needs. Run only after `linear-auth` + `linear-team`
  succeed; report-only (no `--fix` — scopes and states are user/workspace-owned).

### Linear project-backed objectives — milestones & Project Updates

Under Linear, an **objective** is a Linear **Project** (not an issue): each roadmap node is a
node-issue attached to the project, and **phases are grouped under Project Milestones** — one
milestone per phase, keyed by the phase name (the objective prose's `### Phase N: …` headers).
The project also posts a fail-open **Project Update** (the status-report feed) on three
transitions: when the objective is **created**, when **a plan lands** (marking node(s) done), and
when **reconciliation** rewrites the objective prose. Both behaviors are **additive and
non-fatal** — a Linear bookkeeping failure is logged but never breaks a merge or a node
transition, and neither exists on the GitHub backend. (The `projectUpdateCreate` write was
**live-verified 2026-06-16** at the Mode-4 smoke run — see the runbook's *Fourth live run* block.)

### Native footprint — attribution, status, attachments, prose-first metadata (#669)

perk authenticates with a personal `LINEAR_API_KEY` (the actor is **you**), and makes its Linear
footprint read natively. All of the following are **Linear-only** (the GitHub backend is
unchanged):

- **Attribution.** Every perk-created issue is **assigned to you** (the API-key user, via the
  cached `LinearClient.viewer_id()`); every objective **Project** has you as **lead** and a
  **start date** (required for Linear's project graph).
- **Project lifecycle.** A project-backed objective advances to **Started** when its first node
  enters a started-type status, and to **Completed** on land — both best-effort/fail-open.
- **PR attachments.** When a plan's PR is stamped, perk posts a native sidebar **attachment** card
  (`GitHub PR #N`, subtitle the PR state) — idempotent by URL, so re-stamps update it in place;
  best-effort/fail-open (it never fails the header write).
- **Prose-first, unobtrusive metadata.** Linear bodies render the human prose first and perk's
  inline-code bookkeeping blocks after — no HTML-comment markers or `<details>` artifacts. A
  native collapsed-toggle wrapper is a pending enhancement (gated on a live round-trip check).

Becoming a true Linear **Agent** (`actor=app`) is a separate, out-of-scope future effort.

## Known caveats & maturity

The Linear backend is **validated offline (against fakes) and live-validated on 2026-06-15**
against a real workspace. Its live-validation runbook is
[`docs/planning/linear-smoke-gate.md`](../../planning/linear-smoke-gate.md); the **Mode 1** lifecycle
(`plan → implement → submit → land → learn`) plus the issue-backed objective loop ran green
end-to-end — string `PER-*` ids throughout, the `perk:plan`/`perk:learn` labels applied, the
plan issue closed (Done) on land, and the node auto-marked done on the objective. See the
runbook's "Recorded observations" table for the dated findings. The offline regression twin is
`tests/test_linear_lifecycle.py` (a stateful `FakeLinearWorkspace` driving the real backend
through the real CLI commands).

What the live smoke **proved** (no longer deferred):

- **ProseMirror round-trip fidelity** — **proven (2026-06-15).** Linear re-encodes issue/comment
  bodies through ProseMirror; the inline-code sentinel encoding round-tripped cleanly for the plan
  header, the plan-body comment, and the objective-body re-render (roadmap table + reconcilable
  splice) — every `find_metadata_block` parse succeeded after Linear's re-encode, with zero raw
  `<!-- … -->` / `<details>` artifacts.
- **The real "not found" error shape** — **observed (2026-06-15), tightening implemented (node 1.2).**
  A missing entity returns GraphQL `message: "Entity not found: Issue"` with
  `extensions.code: "INPUT_ERROR"` (`type: "invalid input"`, `statusCode: 400`). The three
  not-found sites now **pair** `code == "INPUT_ERROR"` with the `"Entity not found"` message prefix
  (`INPUT_ERROR` alone is a generic input-error code, so the pairing is the discriminator); the old
  loose `"not found"` substring tolerance is gone.

The specific behaviors the offline fakes **cannot** prove, **still deferred**:

- **RATELIMITED behavior** — rate limits surface as HTTP 400 with `extensions.code == "RATELIMITED"`;
  perk **fails loud by design** — a typed `LinearGraphQLError`, **no retry/backoff**. **Decided
  fail-loud (node 1.2):** none tripped during the 2026-06-15 smoke (low request volume), so there is
  no observed behavior to justify backoff; the retry/backoff posture stays deferred until a live
  RATELIMITED is observed at the gate.
- **Mutation identifier acceptance** — whether mutations accept the human `ENG-<n>` identifier
  directly. **Resolved (2026-06-16):** the Mode 2 probe confirmed `issueUpdate`/`commentCreate`
  take the bare identifier, so the internal identifier→UUID lookup was **removed** outright — the
  verified mutations pass the identifier directly, and the objective blocking relations
  (`issueRelationCreate`, not verified for identifiers) use the issue UUID captured at
  issue-create time.
- **Agent-session GraphQL signatures** — see below.
- **GitHub Issues Sync interaction** — if a team has Linear's *GitHub Issues* two-way sync enabled,
  perk-created issues mirror into GitHub (and vice versa). perk does not cover sync interactions;
  use a team without Issues Sync.

### Agent-session emission (advanced, unverified-live)

perk can optionally mirror an implement run into Linear's **Agents UI** (an AgentSession on the plan
issue). This is **off by default**: it requires a separate **`LINEAR_AGENT_TOKEN`** — an OAuth
`actor=app` access token (a personal `LINEAR_API_KEY` is rejected by the AgentSession API) — and is
fully dormant without it. The mirror is one-way (perk → Linear), and its GraphQL mutation signatures
(`agentSessionCreateOnIssue`, `agentActivityCreate`, `agentSessionUpdate`) are **substring-pinned
offline but unverified against a live workspace**. It is **not** part of the switch-to-linear happy
path; see the agent-session section of [`docs/planning/linear-smoke-gate.md`](../../planning/linear-smoke-gate.md) for
the validation script and deferral register.

## See also

- [How to select a plan or todo provider](../how-to/select-a-provider.md) — the provider-selection
  recipe.
- [How to switch the issue backend to Linear](../how-to/switch-to-linear.md) — the Linear-switch
  recipe.
- [Configuration reference — `[providers]` / `[issues]`](./configuration.md#providers) — the raw
  config keys.
- [The Linear live smoke gate](../../planning/linear-smoke-gate.md) — the live-validation runbook (Mode 1 +
  the objective loop validated 2026-06-15).

---

← Back to the [reference router](index.md).
