# The Linear live smoke gate (Objective #252, Node 4.1)

The manual runbook that validates perk's Linear issue backend against a **real** Linear
workspace. The offline regression surface is `tests/test_linear_lifecycle.py` (a stateful
`FakeLinearWorkspace` driving the real `LinearIssueBackend` through the real CLI commands); this
gate covers what no fake can prove: ProseMirror round-trip fidelity, Linear's actual error
shapes, rate-limit behavior, and the GitHub-integration automations.

Run **Mode 1 on a bare workspace first** (perk must stay correct with zero integration/automation
config), then Mode 2 if a GitHub-integration-installed workspace is available. Record what you
observe in the **Recorded observations** section at the bottom — each row feeds a documented
follow-up.

> **Caveat — GitHub Issues Sync.** If the scratch team has Linear's *GitHub Issues* two-way sync
> enabled, perk-created Linear issues will be mirrored into GitHub issues (and vice versa). Use a
> team without Issues Sync; this runbook does not cover sync interactions.

## Prerequisites

- A **scratch Linear team** you can freely pollute (e.g. key `ENG` in a test workspace).
- A personal API key: `export LINEAR_API_KEY=…` (linear.app → Settings → Security & access).
  Environment-only — never in config files (contracts §8.21).
- The committed selection in `.pi/perk.toml`:

  ```toml
  [issues]
  backend = "linear"
  team = "ENG"
  ```

- `perk init --verify` green — the init readiness probe ensures the four perk labels
  (`perk:plan`, `perk:learn`, `perk:consolidated`, `perk:objective`) on the workspace.
- `perk doctor` green, including the verify-gated `linear` group (`linear-auth` /
  `linear-team` / `linear-labels`).

## Mode 1 — bare workspace (no GitHub integration)

Drive a throwaway plan through the full lifecycle. At each step, verify both the envelope (string
`ENG-*` ids everywhere — contracts §8.21) and the workspace state in the Linear UI.

1. **Plan-save.** `perk plan-save --plan-file <plan.md> --run-id $(perk state run-id 2>/dev/null || echo 01SMOKE) --json`
   - The issue is created in the team with label `perk:plan`; `issue.id` is the identifier
     (`ENG-<n>`); `plan_ref.provider == "linear"`.
   - Open the issue in Linear: the description's `plan-header` block and the first comment's
     `plan-body` block use the inline-code sentinel encoding (`` `perk:metadata-block:…` ``) —
     **no** raw `<!-- … -->` or `<details>` artifacts.
2. **Re-save idempotency / ProseMirror round-trip.** Edit the plan file and re-run the same
   `plan-save` (same run id). Verify: same `ENG-<n>` (`existed: true`, `updated: true`), the
   plan-body comment patched in place (not duplicated), and the header block still parseable
   after Linear's ProseMirror re-encoding (the `find_metadata_block` round-trip — THE fidelity
   check this gate exists for).
3. **Implement.** `perk implement ENG-<n>` — worktree/branch `plan-ENG-<n>`; make a trivial
   committed change.
4. **Submit.** `/submit` (or `perk pr submit --json` in the worktree). Verify the PR opens as
   draft and the Linear description's `plan-header` gains `branch` / `pr` / `lifecycle_stage`.
5. **Land.** `/land` (or `perk pr land --json`). Verify:
   - the squash commit message footer is `Plan: ENG-<n> — <url>` (no `Closes #N`, no Linear
     magic words);
   - the plan issue is **explicitly closed** by perk (`plan_issue_closed: true` in the envelope;
     Done in Linear) — on a bare workspace nothing else would close it;
   - pending-learn set.
6. **Learn.** `/learn` with a summary. Verify the `perk:learn` issue (`ENG-<m>`) and the
   back-link comment on the plan issue.
7. **Objective loop.** `perk objective create` (with `--roadmap`), `objective show/next/node`,
   link a plan via the factory (or `plan-save --objective-id ENG-<o> --node-id 1.1`), land it,
   and verify the auto node-done + `perk objective reconcile`'s prose splice survive the
   ProseMirror round-trip (the roadmap table re-render in the body comment stays parseable).
8. **Error-shape capture.** `perk resume ENG-9999 --json` (a nonexistent issue): record the
   exact GraphQL error message and any `extensions.code` Linear returns for a missing entity —
   this feeds the `.codes` tightening of the `"not found"` substring tolerance in
   `LinearIssueBackend._issue_or_none` / `_comment_body_or_none`.
9. **Rate limits.** If any step trips RATELIMITED (HTTP 400, `extensions.code == "RATELIMITED"`),
   record the context + headers — this feeds the retry/backoff deferral.

## Mode 2 — GitHub integration installed

Repeat the lifecycle on a team with Linear's GitHub integration (pull-request linking +
workflow automations) and additionally verify:

- **Branch-name auto-link.** Pushing `plan-ENG-<n>` attaches the PR to the Linear issue
  (PR + review state visible on the issue) — the D3 payoff of identifier-shaped worktree names.
- **Automations coexist.** If the team automations move the issue In Progress on push and Done
  on merge, perk's explicit on-land close must be an idempotent no-op beside them (no error, no
  state flapping).
- **Linkback tolerance.** The integration posts linkback comments on linked issues; verify
  perk's marker-keyed upserts (run-report notes, the objective body comment) still patch their
  OWN comments and `get_plan_body` still resolves (the offline twin:
  `test_foreign_linkback_comment_does_not_perturb_marker_scans`).
- **Mutation identifier acceptance.** Optionally probe whether mutations (`issueUpdate`,
  `commentCreate.issueId`) accept the human identifier directly — if they reliably do, record
  it: that would let `_uuid_for` simplify to a pass-through.

## Agent session emission (Objective #252, Node 5.1 — stretch)

The opt-in Linear Agents-UI mirror of an implement run (`perk/linear_agent.py`, contracts §8.22).
Offline fakes pin request *composition* only — this live smoke is the only surface that can prove
Linear actually **accepts** the agent mutations (`agentSessionCreateOnIssue`,
`agentActivityCreate`, `agentSessionUpdate`).

### One-time setup

1. Create a **Linear OAuth application with agent capability** (linear.app → Settings → API →
   OAuth applications → enable "Agent" / `app:assignable`+`app:mentionable` as documented).
2. Install it into the scratch workspace and complete the OAuth flow with **`actor=app`** — the
   resulting access token acts *as the app*, which is what the AgentSession API requires (a
   personal `LINEAR_API_KEY` is rejected).
3. `export LINEAR_AGENT_TOKEN=<that access token>` (environment-only; without it the emission
   layer is fully dormant).

### Smoke script

On a Linear-backed plan (the `[issues] backend = "linear"` setup above):

1. `perk implement ENG-<n>` — verify in Linear's Agents UI: an **AgentSession** appears on the
   plan issue with a `thought` activity ("Starting implement run …") and that
   `.pi/workflow/agent-session.json` was written into the worktree. For a remote drive
   (`perk implement --remote …`), the session's external links include the GitHub Actions run.
2. `/submit` (or `perk pr submit --json`) — verify an `action` activity ("Opened pull request",
   parameter = branch, result = PR URL) and the **PR link attached** to the session
   (`addedExternalUrls`).
3. `/land` (or `perk pr land --json`) — verify a `response` activity ("PR #n squash-merged." +
   the objective-node summary when linked) and that the session's derived status settles.
4. **Failed remote drive** (optional): force a remote implement to fail and verify the `error`
   activity lands beside the terminal run-report note.
5. Re-run any step **without** `LINEAR_AGENT_TOKEN` and verify zero agent-API traffic
   (byte-identical behavior — the dormant guarantee).

### Deferral register (agent emission)

- **Exact mutation signatures unverified offline** — the GraphQL documents are substring-pinned
  in `tests/test_linear_agent.py`; record any live schema rejection here.
- **Staleness** — Linear marks sessions `stale` ~30 min after the last activity; long implement
  runs show stale until the submit/land activity refreshes them (accepted, not mitigated).
- **`perk address` emission** — deferred (no activity on the address stage).
- **Agent plan checklist** (`agentSessionUpdate.plan`; Agent Plan API is a technology preview) —
  deferred.
- **Remote-created session invisible to a local land** — `agent-session.json` stays in the
  runner's checkout; a later local land skips its emission (stderr note).

## Recorded observations

> Append dated entries after each live run. Each observation feeds the named follow-up.

| Date | Mode | Observation | Feeds |
|---|---|---|---|
| _none yet_ | — | — | `.codes` tightening (`_issue_or_none`) · RATELIMITED posture (retry/backoff deferral) · `_uuid_for` simplification |
