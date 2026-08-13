# perk providers & issue backends

Two distinct knobs:

- **Provider seams** — three surfaces a foreign Pi package can fill in place of perk's bundled
  default: `plan`, `footer`, `web`. Selected by the `[providers]` table. (There
  is **no** review seam — the PR-review surface is picked by the command itself:
  `/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator. There is **no** askuser seam
  either — the `ask_user_question` questionnaire tool is **built-in**: the borrowed
  `@juicesharp/rpiv-ask-user-question` package, installed for every repo, not selectable. There
  is **no** todo seam either — the todo checklist overlay is **built-in**: the borrowed
  `@juicesharp/rpiv-todo` package, installed for every repo, not selectable. The
  retired `[providers] review`, `[providers] askuser`, and `[providers] todo` keys **hard-fail
  config load** with removal guidance.)
- **Issue backend** — where canonical durable state is stored: GitHub (default) or Linear. Selected
  by `[issues] backend`. It governs **two storage tiers**: the issue-tracking tier (plan / learn
  issues — issues under either backend) and the objective-storage tier (objectives — a GitHub issue
  under GitHub, a **Linear Project** under Linear).

## The supported provider set

The catalog is `shared/providers.yaml`, read by both planes. perk's own bundled providers are the
zero-config **defaults** (the no-config hard guarantee); the foreign providers are first-class
selections.

| Provider id | Seam | Default? | Posture | Foreign package |
| --- | --- | --- | --- | --- |
| `perk-plan` | `plan` | ✅ | reference (native) | _(none)_ |
| `tombell-plan` | `plan` | | REPLACE | `npm:@tombell/pi-plan` |
| `plannotator-plan` | `plan` | | AUGMENT | `npm:@plannotator/pi-extension` |
| `perk-footer` | `footer` | ✅ | reference (native) | _(none)_ |
| `powerline-footer` | `footer` | | REPLACE (vacate-only) | `npm:pi-powerline-footer` |
| `pi-bar-footer` | `footer` | | REPLACE (vacate-only) | `npm:pi-bar` |
| `pi-status-footer` | `footer` | | REPLACE (vacate-only) | `npm:@tombell/pi-status` |
| `pi-default` | `footer` | | install nothing (pi stock footer) | _(none)_ |
| `pi-web-access` | `web` | ✅ | reference (foreign package) | `npm:pi-web-access` |
| `ollama-web-search` | `web` | | REPLACE (vacate-only) | `npm:@ollama/pi-web-search` |
| `juicesharp-web-tools` | `web` | | REPLACE (vacate-only) | `npm:@juicesharp/rpiv-web-tools` |

## Postures (how perk yields its surface)

- **REPLACE** (`tombell-plan`) — perk **vacates at registration time** (does not register its own
  `/plan` command, shortcut, or `--plan` flag) so the foreign package is the sole registrant. An
  adapter shim bridges the foreign surface to perk's canonical `plan_save` → `cache.plan-ref`
  contract.
- **AUGMENT** (`plannotator-plan`) — perk **keeps** its plan surface and skips only the two real
  registration collisions (the `--plan` flag + the `Ctrl+Alt+P` shortcut). A shim bridges the
  `plan_review` tool to plannotator's browser review flow; approval auto-saves (with `/plan-save`
  as the manual failsafe), and the browser's **direct edits** are honored — an approved plan
  review auto-applies the reviewer's `# Direct Edits` diff to the draft and saves the edited
  bytes (verbatim save + a loud warning if unapplyable); an approved objective review carrying
  direct edits skips the save and routes one `objective_draft` fold-in + re-review; denials hand
  the diff to the agent as feedback. The bridge covers all three authoring tiers with a
  per-stage adapter flavor (plan / objective / **gist** — the browser shows the rendered gist);
  an approved gist review carrying direct edits likewise skips the save and routes one
  field-aware `gist_draft` fold-in (title/scope/prose) + re-review.
  The warm **`/pr-review-browser`** door also reuses plannotator's `code-review` `pi.events` action
  to open the browser review on a PR (foreign or the active worktree's own — URL filled in
  automatically, findings streamed in live, GitHub posting from the UI), or — before `/submit`,
  when the plan worktree has no PR yet — a **local since-base review** of the working tree
  against the plan's pinned base, whenever `@plannotator/pi-extension` is installed — the
  `plannotator-plan` selection is how that package gets converged.
- **REPLACE / vacate-only** (the **interface seams** — `footer`, `web`) — no durable
  artifact to bridge, so **no adapter shim** (`adapter: null`). perk vacates its own surface and the
  foreign provider stands alone:
  - `footer`: perk just doesn't call `installPerkFooter`. For `powerline-footer` / `pi-bar-footer`,
    perk's objective progress still reaches the footer (both render extension statuses);
    **`pi-status-footer` is the exception** — it does **not** render extension statuses, so perk's
    progress is not shown (accepted limitation).
  - `web`: selection swaps the installed web package; perk registers no web tools of its own, so
    there is **nothing to vacate**. The seam is novel — its default (`pi-web-access`) is itself a
    **foreign package** (perk owns no native web impl). Tool names diverge across providers and are
    **not** normalized (the read-only allowlist carries the union). Only `pi-web-access` is
    zero-config (`@ollama/pi-web-search` needs a local Ollama daemon; `@juicesharp/rpiv-web-tools`
    needs an API key). Selecting a foreign web provider also **drops the bundled `librarian` skill**
    (pi-web-access-specific).
- **Install nothing** (`pi-default`) — adds no footer package and vacates perk's install gate,
  leaving pi's stock built-in footer.
- **Built-in, not selectable** (`ask_user_question`, `todo`) — the askuser and todo seams are
  **retired**: the questionnaire tool is the borrowed `@juicesharp/rpiv-ask-user-question` package
  and the todo checklist overlay is the borrowed `@juicesharp/rpiv-todo` package, each installed
  for every repo via perk's borrowed set. No provider to select, no `[providers]` key (a leftover
  `askuser` / `todo` key hard-fails config load). The todo overlay is the sole checklist surface
  (perk's checkpoint substrate is removed).

## What selection does

- **`perk init` converges the package** — selecting a foreign provider adds its npm package to
  `.pi/settings.json` `packages`; deselecting removes it (two-directional). perk's native reference
  providers have no package. (`pi-web-access` is wired even by default — it's a foreign package.)
- **`perk init` installs the hunk CLI (best-effort)** — whenever the binary is absent —
  unconditionally, it is not a provider selection — a verified init attempts
  `npm install -g hunkdiff`; failure degrades to
  a warning with the manual hint (`npm i -g hunkdiff` or `brew install hunk`), never fatal. The
  hunk CLI is the `/pr-review-terminal` surface.
- **`perk doctor` reports the resolution** — the `providers` check reports
  `plan=…, footer=…, web=…`. It **warns** on problems but is never
  fatal. The **`review-cli`** check (group `providers`, verify-gated) always probes for the
  `hunk` binary — ok when present, warn with the install hint when absent;
  `perk doctor --fix` retries the install.

## Fallback semantics

Resolved by `resolve_providers`:

- **Absent** key → seam default, **silently**.
- **Unknown id / wrong-seam id** → seam default, **loud-but-non-fatal** (a warning, never a crash).

## Issue backend — Linear

`[issues] backend` is `"github"` (default) or `"linear"`, read **committed-only** from the
**main checkout's** `.perk/config.toml` even inside a linked worktree — a worktree's checkout
state can never flip the canonical store (an in-worktree `[issues]` edit takes effect when it
reaches the main checkout). Switching to Linear moves where canonical plan / learn / objective
state lives.

- **Auth — `LINEAR_API_KEY`.** A personal Linear key (linear.app → Settings → Security & access),
  set as an **environment variable** or via the gitignored `.perk/local.toml` `[linear] api_key`
  (an exported env var wins); **never** committed. perk reads it from the **main checkout's**
  `.perk/local.toml` even when a command runs inside a linked worktree (the gitignored file is
  never copied into worktrees), so a single entry authenticates every worktree session and
  cold-door (`/submit`, `/land`, …). Sent as a **plain `Authorization: <key>`** header — **not**
  `Bearer`-prefixed. **Interactive `perk init`** prompts for the key when the committed backend
  is `linear` (with a `team`) and none resolves — hidden input, validated against Linear, stored
  in `.perk/local.toml` (tightened to `0600`); disabled by `--no-interactive`, a non-TTY stdin,
  or `--json`.
- **Required config — `[issues] team`** — the Linear team **key** (e.g. `"ENG"`).
- **Converged package** — `perk init` adds `npm:pi-mono-linear` (the borrowed Linear-tools
  extension) when Linear is selected, removes it when deselected.
- **Ensured labels** — the init readiness probe ensures six labels exist: `perk:plan`,
  `perk:learn`, `perk:gist`, `perk:consolidated`, `perk:objective`, `perk:objective-node`.
- **Identifier shape** — Linear ids are **strings** like `ENG-123` (vs GitHub's `#42`); flows
  through `cache.plan-ref.provider == "linear"`, the branch name `plan-ENG-123`, and the land
  squash footer `Plan: ENG-<n> — <url>` (no `Closes #N`). Anywhere a command takes an id you may
  paste the issue/objective **URL** instead (GitHub `.../issues/N`; Linear `.../issue/IDENT` or
  `.../project/SLUG`) — perk peels the id from it; the peeled id stays opaque, the backend remains
  the authority on whether it resolves (`/pull/N` is deliberately not accepted).
- **Doctor groups** — `issues-backend` (group `issues`, offline) validates the selection (+ `team`
  for Linear); `linear-auth` / `linear-team` / `linear-labels` (group `linear`, verify-gated,
  non-fatal `warn`) are the network probes; `linear-project-scopes` / `linear-workflow-states`
  (verify-gated, report-only) probe project-backed objective readiness.
- **Project-backed objectives** — under Linear an objective is a Linear **Project**: each roadmap
  node is a node-issue attached to the project, **phases group under Project Milestones** (one per
  phase, keyed by the `### Phase N: …` header), and a fail-open **Project Update** posts on create /
  plan-land / reconcile. Both behaviors are additive and non-fatal, and neither exists on GitHub.
  A node-issue a human **cancels natively** in Linear reads back as an effective skip (a
  *cancellation projection*: the persisted attachment status is untouched) — but only when perk can
  positively prove it is unpublished future work (a clean plan backlink is acceptable; any
  identity conflict, checkpoint/PR claim, completed or unresolved publication, remote branch, or
  branch-owned PR is not); anything unprovable
  stays a visible `canceled` layer with blockers, and `perk objective doctor --fix` persists the
  proven-safe skips into the node attachment.
- **Attachment-native metadata (clean bodies)** — perk's Linear bookkeeping (plan/learn headers,
  the objective header + manifest, per-node roadmap state) is stored as native issue
  **attachments** with machine-readable metadata envelopes; descriptions and project overviews
  stay clean human prose. Each objective project carries one canceled **metadata sentinel issue**
  (`Perk: objective metadata`, linked from the project's Resources) holding the project-scoped
  envelopes. **Clean break:** inline metadata blocks written by earlier perk versions are not
  read back — re-save/re-create those artifacts.
- **Objective replan is backend-specific** — `perk objective replan <N>` re-authors an objective as
  a net-new objective that supersedes and closes the old one (carrying forward only the unfinished
  work; `supersedes`/`superseded_by` link the two headers bidirectionally). On **Linear** the
  unfinished node-issues are **moved** into the new Project (identity / open PRs preserved) and
  dropped open node-issues are **Canceled**; on **GitHub** carried nodes are re-authored as fresh
  roadmap rows and the old issue is closed. The dormant issue-backed Linear store reports
  "unsupported". Replanning a **stacked** objective runs the interruption-safe transfer protocol
  on either backend (published plans carry in exact order; the old objective closes only after
  the successor verifies; an interrupted transfer concludes via
  `perk objective stack recover <old-id>`).

## Maturity caveat

The Linear backend is **validated offline (against fakes) and live-validated 2026-06-15** (Mode 1
lifecycle + the issue-backed objective loop ran green end-to-end; Mode-4 project-backed lifecycle
live-verified 2026-06-16). **Proven live:** ProseMirror round-trip fidelity; the real "not found"
error shape (paired `INPUT_ERROR` code + `"Entity not found"` message); bare-identifier mutation
acceptance; attachment metadata semantics (2026-07-12 spike — `perk.invalid` URLs accepted,
`metadata` round-trips verbatim, `attachmentsForURL` exact-match, re-create on the same
`(url, issue)` REPLACES metadata in place). **Still deferred / unproven:** RATELIMITED retry/backoff (fail-loud by design, no
backoff); the **agent-session emission** mirror into Linear's Agents UI (off by default, requires a
separate `LINEAR_AGENT_TOKEN` OAuth `actor=app` token, GraphQL signatures substring-pinned offline
but **unverified live** — not part of the switch-to-linear happy path); GitHub Issues Sync
interactions (use a team without Issues Sync). Never overstate Linear's proven surface beyond this.

---

*Canonical source: `docs/user-docs/reference/providers-and-backends.md`.*
