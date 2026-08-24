# Dogfood record: ts-decomposition Phase 2 gate (gist authoring through the typed slice)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-2
close: *author, review, and save a real gist through the migrated flow — exactly one v1 binding
active, state and artifacts reading back through `WorkflowSession`* — after the gist-owned code
moved from `extension/factories/` into `extension/authoring/gist/` + `extension/session/` +
`extension/pi/v1/gist.ts` (the injected review arm) and the deferred import-direction guard
rules activated.

Executed starting **2026-08-24** in the implementation worktree, against the branch under test:

- **Worktree:** `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2094`
- **Tested commit:** `3bb46b9cb2290953cd0fde304ca107583e4d9575` (Tasks 1–7 all committed: the
  classified session cores, the typed feature, the v1 installer + injected arm, the rewiring +
  deletions, the guard activation, the docs/contracts reconciliation, and the adapter escalation
  pin; the evidence-record commit follows it)
- **Session shapes:** one **headless SDK probe** (the `defaultCreateRuntime` mirror from
  `docs/learned/pi/headless-session-drive.md`: disk-layered
  `SettingsManager.create(worktree, throwawayAgentDir)`, `ModelRuntime.create()`,
  `bindExtensions({ mode: "json" })` ⇒ `ctx.hasUI === false`; model SDK-resolved to
  `anthropic/claude-opus-4-8`) claiming a run minted by the **real `perk gist author` cold
  door** — plus one **interactive `perk gist author` run by the human** (PENDING below) for the
  review/save/close observables.
- **cwd confirmation:** the probe logged
  `probe cwd: /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2094` (the self-repo
  loads the perk extension from the invoking checkout via the worktree's `.pi/settings.json`
  `".."` package entry, so the session ran this branch's extension).

**Honesty framing (the headless/interactive split — operator-approved at execution time):** the
plan's gate prescribes an interactive authoring session; the implement session cannot launch an
interactive TUI. Before executing, the executor put the split to the operator as a structured
question (options: hybrid / defer-everything / fully-interactive-by-human), and the operator
explicitly chose the **hybrid** execution: the automatable observables (injection bytes, tool
gating, the artifact + pointer, the `openBranchWorkflowSession` read-back, the runtime tool
census) were captured by the headless probe — which binds the identical extension from the
identical checkout through the identical cold-door claim path — while the human-judgment
observables (a real review decision, the auto-save creating a real `perk:gist` issue, the gate
transition observed live, the issue close) are the human's interactive run, recorded below when
executed.

## Arm 1 — headless probe (executed 2026-08-24)

**Run identity via the real cold door.** `perk gist author --no-sync --json -- --version`
resolved in this worktree and wrote handoff `01M0V04AFK81QH4A4GHBMBSQAE.json`
(`mode: read-only`, `stage: gist-author`, `consumed: false`); the probe session (launched with
`PERK_RUN_ID=01M0V04AFK81QH4A4GHBMBSQAE`, `PI_SESSION_FILE` unset) claimed it through the
production path — the handoff flipped to `consumed: true` with the probe's `pi_session_id`
recorded, and the branch's `perk:workflow-state` read
`run_id=01M0V04AFK81QH4A4GHBMBSQAE mode=read-only stage=gist-author`.

**Injection bytes (one live copy of each, no plan context).** After one real agent turn the
persisted session carried exactly one `custom_message` per context:

- `perk:gist-author-context` — **521 bytes**, first line `[GIST AUTHORING]`, naming
  `gist_draft` + `plan_review`, ending with the skill pointer line (`… the perk-gist-author
  skill (delivered as a nudge at launch).`);
- `perk:mode-context` — 519 bytes, `[READ-ONLY MODE]`;
- `perk:plan-adapter-plannotator` — 947 bytes, first line `[GIST ADAPTER: PLANNOTATOR]` (the
  GIST flavor; the committed config selects `plannotator-plan`);
- `perk:binding-context` — 130 bytes (the `perk-gist-author` skill nudge);
- `perk:plan-context` — **0 entries** (planMode defers in a gist-author session).

**Tool gating.** The model's own enumeration (the model-visible set, not the registered census)
was `read, grep, find, ls, bash, plan_review, plan_draft, objective_draft, gist_draft,
objective_node, web_search, fetch_content, get_search_content, subagent, subagent_wait,
explore_objective_node, push_annotations, start_draft_review_wave, collect_draft_review_wave,
run_audit_wave, run_harvest_wave, run_dream_wave, subagent_supervisor` — **no `edit`, no
`write`** (and no `gist_save`: the save tool joins the surface only after the gate exits — the
pre-existing census, unchanged by this slice). The structural bash gate was exercised live: the
model called `bash` with `touch .perk-dogfood-gist-probe` and the gate blocked it before
execution — tool result verbatim:

```text
perk read-only mode: command blocked (not allowlisted).
Command: touch .perk-dogfood-gist-probe
```

`blocked file created: false` (the file never appeared).

**The draft artifact + pointer, read back through `openBranchWorkflowSession`.** The model
called `gist_draft` (title "Phase-2 dogfood probe", scope `plan`) **while read-only**; the tool
result details carried `ok: true`, `name: gist-draft.json`, `bytes: 186`,
`run_id: 01M0V04AFK81QH4A4GHBMBSQAE`. Four independent surfaces agreed on the digest
`sha256:0cfd76de1881f5913ae0a6e8e03673cb7a119942669895516d13e39d6bcca5d3`:

1. the `gist_draft` tool-result details,
2. the `session_artifacts` pointer rebuilt from the branch
   (`{run_id, name, path, digest, at}` — strict-append via `WorkflowSession.writeArtifact`),
3. the `openBranchWorkflowSession(...).readArtifact("gist-draft.json")` read-back
   (`status: found`; parsed keys `prose,schema_version,scope,title`, `schema_version: 1`,
   `scope: "plan"`, prose first line `# Phase-2 dogfood probe`),
4. the on-disk file at
   `.perk/workflow/scratch/runs/01M0V04AFK81QH4A4GHBMBSQAE/data/gist-draft.json`.

`openBranchWorkflowSession` reported `opened` with `session.runId` equal to the claimed run —
the state and artifact read back **through `WorkflowSession`**, as the gate demands.

**Exactly one v1 binding active, proven two ways.**

1. *Location ratchet:* `extension/importDirectionGuard.test.ts` Rule E (activated in this
   slice) scans the production corpus for registration tokens — `pi/v1/gist.ts` is the only
   `pi/` registrar, the frozen `LEGACY_REGISTRANTS` census admits no gist file (the three
   deleted gist factories never joined it), and the census is shrink-only.
2. *Runtime observation:* the live session's model-visible census (above) carries `gist_draft`
   exactly once, the bind reported no duplicate-registration errors, and the injected contexts
   appeared exactly once each — the v1 installer is the only gist binding the session loaded.

## Arm 2 — interactive authoring/review/save (human) — **PENDING**

To be executed by the operator from this worktree (`cd .worktrees/plan-2094 && perk gist
author`): draft via `gist_draft`, review via `plan_review` (first-party view-only editor or the
plannotator browser), APPROVE → the auto-save creates a real `perk:gist` issue. Observables to
record here when executed:

- the saved issue id/url (+ `existed: false`);
- the gate transition observed **only after** the verified save (the session flips read-only →
  read-write on the saved arm; a failed save leaves the gate on);
- the review outcome shape (approve verdict, the relayed save text with the consumption hint);
- the post-compaction re-injection observable **if a compaction occurs** (not fabricated
  otherwise; the behavior is test-pinned in `pi/v1/gist.test.ts` +
  `adapters/planAdapterPlannotator.test.ts`).

## Skipped arms

- **Post-compaction re-injection (live):** not exercised in the headless probe (no compaction
  occurred in the short probe session); covered by the harness pins (a planted compaction entry
  → re-injection) and eligible for live observation in Arm 2 if a compaction happens.
- **Gate transition after verified save (live):** deliberately reserved for Arm 2 — a headless
  save would create a throwaway real backend issue; the seam is test-pinned
  (`authoring/gist/save.test.ts` D1a cases, `pi/v1/gist.test.ts` command/arm cases).

## Defect log

Empty so far — every headless observation matched the expected behavior; no product defects
surfaced. (The probe script's first branch-inspection pass mis-filtered `type: "custom"` for the
injected `type: "custom_message"` entries — a probe bug, corrected by offline inspection of the
persisted session file; not a product defect.)

## Cleanup — **PENDING**

- The probe's run residue (handoff `01M0V04AFK81QH4A4GHBMBSQAE.json`, the scratch run dir, the
  probe session file) is git-invisible local state; swept after Arm 2 completes.
- **Planned close (the two-step sequence):** after Arm 2 saves the dogfood gist, the gist issue
  is closed with a comment pointing at this record; the close is verified, and this record is
  amended with the observed close/comment outcome in a follow-up commit — the final CI/ready
  stamp runs on that head.

## Claim → evidence checklist

| Claim (the node's gate enumeration) | Evidence |
|---|---|
| The session runs the migrated flow from this checkout | cold-door handoff claim (`consumed` flip + `pi_session_id`); probe cwd log |
| Gist-authoring context injected (bytes, once, no plan context) | Arm 1: one 521-byte `perk:gist-author-context` (`[GIST AUTHORING]`), `perk:plan-context` count 0 |
| Read-only gating live | Arm 1: model-visible set without `edit`/`write`; verbatim bash block; file never created |
| `gist_draft` works under the gate; artifact + pointer land | Arm 1: `ok: true` details while `mode=read-only`; pointer digest recorded |
| State/artifacts read back through `WorkflowSession` | Arm 1: `openBranchWorkflowSession` → `opened` / `found`; four-way digest agreement |
| Exactly one v1 binding active (two ways) | Arm 1: Rule E location ratchet + the runtime census |
| Real gist authored/reviewed/saved; issue id/url | **PENDING — Arm 2 (human)** |
| Gate transition only after verified save (live) | **PENDING — Arm 2 (human)**; test-pinned meanwhile |
| Dogfood issue closed, record amended | **PENDING — the planned close above** |
