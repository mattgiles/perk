# Providers & issue backends

This page describes perk's **pluggable provider seams** (plan-authoring and todo/checkpoints) and
the **Linear issue backend**: the supported provider set, each provider's wiring posture, and the
Linear backend's auth, labels, identifiers, doctor groups, and current maturity. It describes the
surface; it does not teach a task (those belong in [how-to/](../how-to/index.md)) or argue a design
(those belong in [explanation/](../explanation/index.md)). See the [user-docs router](../index.md)
for how this quadrant fits the whole.

This page is **human-reviewed for accuracy** against the provider catalog
(`shared/providers.yaml`), the config readers (`perk/substrate/providers.py`,
`perk/backends/issues.py`), and the Linear backend (`perk/backends/linear_backend.py`,
`perk/convergence/init.py`, `perk/convergence/doctor.py`) — provider and Linear surfaces are not
`--help`-introspectable, so accuracy is the governing virtue, like the
[configuration reference](./configuration.md).

## Orientation

Two related but distinct knobs live here:

- **Provider seams** — the *plan-authoring* surface, the *todo/checkpoint* surface, and the
  *ask-user* tool are each a **seam** that a foreign Pi package can fill in place of perk's bundled
  default. There are four seams: `plan`, `todo`, `askuser`, and `footer`.
- **Issue backend** — where canonical plan / learn / objective issues are stored: GitHub
  (the default) or Linear.

Both are selected by config keys documented at key depth in the
[configuration reference](./configuration.md) — the `[providers]` table (`plan` / `todo` /
`askuser` / `footer`) and the `[issues]` table (`backend` / `team`). This page documents the **supported set** behind those keys
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
- **REPLACE / vacate-only (`powerline-footer`, `pi-bar-footer`).** The `footer` seam is the second
  **interface seam** — the footer produces no durable artifact, so there is nothing to bridge. perk
  installs its own footer (`installPerkFooter`) inside its `session_start` handler, so under a
  foreign footer selection perk **vacates at install time**: it simply does not call
  `installPerkFooter`, leaving the foreign footer (`pi-powerline-footer` or `pi-bar`) as the sole
  footer surface. There is **no adapter shim** (`adapter: null`) — perk's objective/checkpoints
  progress still reaches the foreign footer automatically because both foreign footers render
  extension statuses, and perk's composed `perk` status slot keeps publishing those segments
  regardless of footer ownership.

### What selection does

- **`perk init` converges the package.** Selecting a foreign provider adds its npm package to
  `.pi/settings.json` `packages`; deselecting it removes the entry. The convergence is
  two-directional (`_converge_provider_packages` in `perk/convergence/init.py`). perk's own
  reference providers have no package — nothing is added.
- **`perk doctor` reports the resolution.** The `providers` check resolves the selection and reports
  `plan=…, todo=…, askuser=…, footer=…`. It **warns** on problems but is never fatal — the default path is the hard
  guarantee.

### Fallback semantics

Selection lives in the flat `[providers]` table and is resolved by `resolve_providers`
(`perk/substrate/providers.py`):

- **Absent** key → falls back to the seam default **silently**.
- **Unknown id or wrong-seam id** → falls back to the seam default **loud-but-non-fatal** (a
  warning, never a crash).

## Issue backend — Linear reference

The `[issues] backend` vocabulary is `"github"` (default) or `"linear"`
(`perk/backends/issues.py`), read **committed-only** from `.pi/perk.toml` — a
`.pi/perk.local.toml` value is silently ignored (this keeps the canonical issue store
deterministic). Switching to Linear changes where canonical plan / learn / objective issues live.

### Auth

- **`LINEAR_API_KEY`** — a personal Linear API key (linear.app → Settings → Security & access),
  supplied as an **environment variable only**, never stored in config (contracts §8.21).
- The key is sent as a **plain `Authorization: <key>`** header — **not** `Bearer`-prefixed.

### Required config

- **`[issues] team`** — the Linear team key (e.g. `"ENG"`), required when `backend = "linear"`.

### Converged package

`perk init` converges **`npm:pi-mono-linear`** — the borrowed Linear-tools Pi extension — into
`.pi/settings.json` `packages` when Linear is selected, and removes it when deselected
(`_converge_linear_package` / `LINEAR_PACKAGE` in `perk/convergence/init.py`).

### Ensured labels

The init readiness probe (`check_readiness` / `_PERK_LABELS` in
`perk/backends/linear_backend.py`) ensures the four perk labels exist on the workspace:

- `perk:plan`
- `perk:learn`
- `perk:consolidated`
- `perk:objective`

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

## Known caveats & maturity

The Linear backend is **validated offline (against fakes), not yet proven against a live Linear
workspace.** Its live-validation runbook is [`docs/linear-smoke-gate.md`](../../linear-smoke-gate.md),
and that smoke is **currently unrun** — its "Recorded observations" table reads *none yet*. The
offline regression twin is `tests/test_linear_lifecycle.py` (a stateful `FakeLinearWorkspace`
driving the real backend through the real CLI commands). Every claim above is sourced from that
offline suite and the audited API facts — **no live observations are recorded yet**, and this page
does not fabricate any.

The specific behaviors the offline fakes **cannot** prove, deferred to the live smoke:

- **ProseMirror round-trip fidelity** — Linear re-encodes issue/comment bodies through ProseMirror;
  the metadata-block round-trip is *mitigated* (the inline-code sentinel encoding) but not
  *proven* live.
- **The real "not found" error shape** — the exact GraphQL message and any `extensions.code` Linear
  returns for a missing entity (feeds the `.codes` tightening of the substring tolerance).
- **RATELIMITED behavior** — rate limits surface as HTTP 400 with `extensions.code == "RATELIMITED"`;
  perk does **no retry/backoff by design**, and live behavior is unrecorded.
- **Mutation identifier acceptance** — whether mutations accept the human `ENG-<n>` identifier
  directly (which would let the internal id lookup simplify to a pass-through).
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
path; see the agent-session section of [`docs/linear-smoke-gate.md`](../../linear-smoke-gate.md) for
the validation script and deferral register.

## See also

- [How to select a plan or todo provider](../how-to/select-a-provider.md) — the provider-selection
  recipe.
- [How to switch the issue backend to Linear](../how-to/switch-to-linear.md) — the Linear-switch
  recipe.
- [Configuration reference — `[providers]` / `[issues]`](./configuration.md#providers) — the raw
  config keys.
- [The Linear live smoke gate](../../linear-smoke-gate.md) — the (currently unrun) live-validation
  runbook.

---

← Back to the [reference router](index.md).
