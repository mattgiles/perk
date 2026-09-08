# Validation: centralized session plan-ref reads and lifecycle facts (Objective #2257, Node 1.2)

**Status:** node-local validation record for the session-only plan-ref read
(`WorkflowSession.activeSessionPlanRef()`), the two-phase startup facts in
`extension/session/lifecycle.ts` (`sessionStartToolScope` before the gate;
`resolveSessionStartFacts` after it; `sessionTreeFacts` for navigation), and the reduction of
`extension/index.ts` to ordered composition. Records the SDK/executable versions actually resolved,
the deterministic gate, the two bounded fresh-session smokes exactly as exercised, and the
observations that stayed blocked. The authority/lazy-read matrix, the failure postures, and the
navigation asymmetry are proven by the tests named below — nothing here claims a boundary that was
not observed live.

## Versions (resolved in the implementation worktree)

| Surface | Version | How observed |
| --- | --- | --- |
| `@earendil-works/pi-coding-agent` (checkout install) | 0.85.1 | `node_modules/@earendil-works/pi-coding-agent/package.json` after ordinary worktree setup (`package.json` pins 0.85.1; the planning-time 0.84.1 root install is gone) |
| `pi` executable (global; the smoke launcher) | 0.85.1 | `pi --version` |
| perk | 3.2.0 | `perk --version`; stamped as `perk_version` in the smoke session's claim entry |
| Node | 26.3.0 | `node --version` (the `node --test` runner and the observation script) |
| Smoke model | `anthropic/claude-haiku-4-5`, thinking off | `--model`/`--thinking` on both smoke processes |

No Pi interface beyond those already consumed by the pre-change interior was needed (the
`session_start`/`session_tree` hooks, `ctx.sessionManager.getBranch()`/`getSessionFile()`,
`ctx.compact`, `pi.sendUserMessage`); no dependency or host-floor change.

## Deterministic gate

The focused set ran green while iterating — `node --test` over
`extension/session/workflowSession.test.ts`, `extension/session/lifecycle.test.ts`,
`extension/sessionLifecycle.test.ts`, `extension/pi/v1/delivery/commitCompact.test.ts`,
`extension/hunkFeedback/receiver.test.ts`, `extension/pi/v1/objectiveRefinement.test.ts`, the
import-direction / bare-import / surfaces guards; `npm run typecheck`; Biome on every changed
TypeScript file; the `docs-check` row for the changed operator page — then one run-all `run_ci`
immediately before submission.

Ownership is single per matrix:

- **Session seam** (`workflowSession.test.ts`, both bindings): the validator table (each required
  field absent/wrong-type/blank; labels empty/all-string vs mixed; `objective_id` null/string vs
  absent/wrong-type; `base` omitted/null/string vs wrong-type; accepted bytes untrimmed; `base`
  omission preserved; extra fields never escape), present/absent/identity-less reads, a later
  `link-plan-ref` observed through the same opened session, the branch-LWW sequence (latest ref,
  explicit-null clearing, unrelated patches, an invalid latest never falling back, reopen and
  navigated-prefix reads), and the recording/throwing-store proof (one rebuild per named read,
  no artifact I/O, no append, null on failure — the engine's open-time identity read accounted
  separately). The existing applied/unchanged/rejected/unverified, strict-ledger, provenance and
  fork/reload suites are retained; the reopen/fork cases now also read the new named read.
- **Lifecycle** (`lifecycle.test.ts`, both stores): the pure scope table across claimed / kept /
  forked / adopted / minted / both unclaimed shapes; the recorded post-gate sequence
  (rebuild → allowed handoff read → registry admission → checkout read on the consuming arm only
  → the one verified link, with every forbidden port throwing); consuming/non-consuming/unknown
  stages; registry-null with and without a launched stage; equal identity with changed metadata;
  different ref; missing cache; preserved linkage; the exact append field/comparator/scope/failure
  text; unchanged resolved facts on rejected/unverified (a kept ref survives, a claim keeps none);
  establish-before-consume observed at consumption and subsequent linkage; navigation facts read
  exactly five state keys (a recording Proxy) with the branch's own session id.
- **Registered paths** (`sessionLifecycle.test.ts`, a recording receiver through the new
  construction-only `feedbackReceiverFactory` option): a consuming cold start's real effect
  sequence — the one claim append → the stage-scoped tool install → the one `active_plan_ref`
  append → the receiver sync carrying the reconciled ref with the real implementation pointer
  already on disk; a post-gate branch-read failure (armed by the gate's own tool install) that
  leaves the gate applied, reaches no linkage/capture/receiver/sentinel, and surfaces the original
  exception through the harness error channel; a reload with conflicting branch (`plan`) and
  handoff (`implement`) stages plus a changed checkout binding (branch stage scopes the tools;
  the handoff stage drives capture and the receiver; the binding is re-read); navigation's
  gate-then-receiver order from one rebuilt state with no capture/linkage and the checkout never
  read. The existing floor/claim/reload/fork/adopt/pointer/navigation cases are retained.
- **`/commit-and-compact`** (`commitCompact.test.ts`): registration/message pins, settlement
  and callback tests retained; valid session linkage, LWW, cache-only generic continuation, the
  new conflicting valid-session/cache case, the throwing-branch fallback, one representative
  malformed case, and the deferred-compaction proof that later state changes cannot retarget the
  rendered continuation.

Deletions confirmed by grep: no `activeSessionPlanRef`/`rebuildWorkflowState` validator remains in
`commitCompact.ts` (it imports `PlanRef` through the session vocabulary and calls
`openBranchWorkflowSession(pi, ctx).activeSessionPlanRef()` at render time only); `index.ts` no
longer imports `resolveRunStage`, `stageConsumesPlanRef`, `appendWorkflowState`, `planRefsEqual`
or reads the checkout inline; no checkout fallback entered the session read; the import-direction
guard (Rules B/D/H) is unchanged and green.

## Smoke 1 — fresh sacrificial cold implement claim

**Launch.** From the implementation worktree (its `.pi/settings.json` `packages` carries `".."`,
so the launched extension IS this worktree's code), with `PI_SESSION_*`/`PI_SUBAGENT_*`/`PI_MODEL`
unset and a fresh handoff `{run_id, consumed: false, mode: "read-write", stage: "implement"}`
written for a newly minted run id (`mintRunId()` → `01M20TY23BB7K9XB0Q6R667HCS`) under the
worktree's `.perk/workflow/handoff/`:

```sh
PERK_RUN_ID=01M20TY23BB7K9XB0Q6R667HCS pi -p --mode json \
  --model anthropic/claude-haiku-4-5 --thinking off --session-dir <scratch>/smoke/sessions "…"
```

The prompt asked the model to `read` `shared/contracts.md` three times (to give the later
compaction something to summarize — Pi refuses to compact a session under its default
`keepRecentTokens`) and reply `OK`, with no edits or git commands. The worktree stayed clean
(`git status` empty) throughout both smokes; the checkout selector `plan-ref.json` (this plan,
#2293) was never written.

**Observed through the owning accessors** (`SessionManager.open(file)` +
`openBranchWorkflowSession(...)`, `readHandoff`, `readSessionPointers(mainCheckoutRoot(cwd), …)` —
never the model's recollection):

- Exactly **two** `perk:workflow-state` entries: the ONE combined claim entry
  `{run_id: 01M20TY23BB7K9XB0Q6R667HCS, pi_session_id: <session basename>, mode: "read-write",
  perk_version: "3.2.0", stage: "implement"}` at `15:42:25.116Z`, then the ONE verified link
  `{active_plan_ref: <the checkout's #2293 ref>}` at `15:42:25.128Z`.
- `session.runId` / `currentRunIdentity()` → the claimed run id.
- `session.activeSessionPlanRef()` → the six-field reconstruction
  `{provider: "github", pr_id: "2293", url, labels: ["perk:plan"], objective_id: "2257", base: null}`
  — the persisted linkage also carries `consumed_learn` and `delivery_lineage` (the checkout
  object was appended verbatim); neither escapes the named read, and the explicit `base: null` is
  preserved.
- Handoff: `consumed: true`, `pi_session_id` = the session basename (establish-before-consume).
- Implementation pointer under the **main checkout** root (`.perk/workflow/scratch/runs/<run>/
  session-pointers.json`): `implementation.main = {pi_session_id: <session basename>,
  parent_pi_session_id: null, at: 15:42:25.128Z}`; `planning.*` null. Reading under the worktree
  cwd returns null by design (§8.35 keys the shared main checkout).

## Smoke 2 — reload of the same session + `/commit-and-compact` on the clean tree

A second process over the SAME session file, `PERK_RUN_ID` unset, driven over RPC
(`pi --mode rpc --session <file> …`; the driver lives in the run's agent scratch): `get_state` to
confirm binding, then `prompt` `/commit-and-compact`, then `abort` the instant the continuation
user message appeared (so no model work ran past the dispatch).

- **Reload identity/linkage are stable.** Still exactly two workflow-state entries — no second
  claim, no `perk_version` rewrite, no re-appended link (the checkout ref equals the linked
  `(provider, pr_id)`, so the keep arm's re-read of the binding appended nothing). The handoff
  still records the original claimer and stays consumed once.
- **Pointer re-capture on keep (pre-existing behavior, recorded honestly):** the kept implement
  session re-captured `implementation.main` (`at` → `15:44:51.718Z`; same `pi_session_id`; the
  informational `session_file` now absolute because the RPC launch passed an absolute path where
  the print launch passed a relative `--session-dir`). This is the carrier's documented
  same-session refresh — `preserveForeign` only blocks a DIFFERENT session — and the pre-change
  interior captured on keep exactly the same way.
- **`/commit-and-compact`:** `perk: commit-and-compact — worktree clean — nothing to commit;
  compacting…` → `compaction_start` → a real model-generated `compaction_end` (compaction entry
  `711f13c4`, `firstKeptEntryId=5a097e30`, `tokensBefore=74902`) → ONE continuation user message
  (entry `c02417f8`, parent = the compaction entry) beginning
  `Compaction completed successfully. Resume work on the active plan #2293 (github:
  https://github.com/mattgiles/perk/issues/2293).` with the `worktree was already clean` arm and
  the `gh issue view 2293 --comments` re-read instruction — the SAME session-linked plan the
  claim reconciled, rendered from the session read at compaction time. The aborted assistant turn
  persisted empty; no commit, push, save, or backend mutation occurred.

Smoke sessions, both event transcripts, the observation script and the RPC driver live under the
implementation run's agent scratch (`.perk/workflow/scratch/runs/01M20RSXXPQC357GDRNDZX10KV/agent/
smoke/`) — non-authoritative, pruned with the run. The sacrificial handoff and the smoke run's own
scratch directories (worktree + main root) were removed after observation so no consumed
`implement` handoff lingers in the worktree.

## Blocked / not-observed live (covered deterministically instead)

- **Fork / adopt / mint / unclaimed arms, conflicting branch-vs-handoff stages, a changed
  checkout binding on reload, rejected/unverified link appends, a throwing post-gate read.**
  Not exercised live (the smoke ran one cold claim and one clean keep). Proven by
  `lifecycle.test.ts` over both stores and by the registered-path composition cases in
  `sessionLifecycle.test.ts` on a real bound `AgentSession`.
- **Interactive session-tree navigation.** Pi's RPC mode exposes no navigate command and the TUI
  `/tree` gesture was not driven headlessly; the navigation facts and the gate-then-receiver order
  are proven by `sessionTreeFacts`' pure test and the harness `navigateTo` composition case.
- **The feedback receiver's live eligibility.** Both smoke processes ran headless (`print`/`rpc`),
  so the receiver was structurally ineligible (`ctx.mode !== "tui"`); its inputs at sync are
  pinned by the recording receiver in `sessionLifecycle.test.ts`, and its own eligibility, fresh
  checkout read and lease behavior stay covered by the unchanged `receiver.test.ts`.
- **The committed and read-only `/commit-and-compact` arms.** Only the clean arm ran live (a
  committed arm would have required real model-authored commits on this branch); the driven,
  settled, read-only and skip arms remain covered by `commitCompact.test.ts` over the production
  deps composition.
