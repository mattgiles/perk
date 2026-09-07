# Validation: Pi-owned live context projection (Objective #2257, Node 1.1)

**Status:** node-local validation record for the delegation of live-context dedup evidence to Pi's
own projection (`extension/pi/v1/contextEvidence.ts`) and the deletion of perk's manual
compaction-window traversal (`activeContextWindow`). Records the SDK/executable versions actually
resolved, the deterministic gate, the two bounded fresh-session smokes exactly as exercised, and
the observations that stayed blocked. The exhaustive retained/drop, repeated-compaction, and
branch-navigation proof belongs to the tests named below — nothing here claims a boundary that was
not observed live.

## Versions (resolved in the implementation worktree)

| Surface | Version | How observed |
| --- | --- | --- |
| `@earendil-works/pi-coding-agent` (checkout install) | 0.85.1 | `node_modules/@earendil-works/pi-coding-agent/package.json` after ordinary worktree setup (`package.json` pins 0.85.1; the planning-time 0.84.1 root install is gone) |
| `pi` executable (global, used by the cold door's `execvpe`) | 0.85.1 | `pi --version` |
| perk | 3.2.0 | `perk --version`; stamped as `perk_version` in both smoke sessions' workflow-state |
| Node | 26.3.0 | the `node --test` runner |
| Smoke model | `anthropic/claude-haiku-4-5`, thinking off | `--model` on every live turn |

Public Pi interfaces consumed: `ExtensionContext.sessionManager.buildContextEntries()` (the
current leaf's compaction-aware `SessionEntry[]`) and the package-root
`sessionEntryToContextMessages` converter. Both exist on 0.85.1 as the plan grounded; no
compatibility behavior or dependency change was needed.

## Deterministic gate

The focused set ran green during implementation (all `node --test` files below, the import/bare/
surfaces guards, `npm run typecheck`, Biome on the changed files, and
`uv run pytest tests/test_binding_render_parity.py tests/test_user_docs_metadata.py -q`), then one
run-all `run_ci` immediately before submission.

Ownership of the projection matrix is single: `extension/pi/v1/contextEvidence.test.ts` drives
real `SessionManager` append/compaction/branch/branchWithSummary APIs and asserts literal native
messages — carriers, negatives that the retired serialized scan would have matched, malformed
parts, a retained→summarized→fresh compaction sequence, a sibling/abandoned-branch/pre-compaction
navigation sequence, and the one-read/no-`getBranch`/propagating-throw source discipline. Consumer
suites (`contextInjection.test.ts` incl. one `loadPerkSession` composition smoke with real
`navigateTo` + reload, `bindingDelivery.test.ts`, `agentScratch.test.ts`, `providers/
plannotator.test.ts`, `workflowState.test.ts`, `toolGating.test.ts`) own only their distinct
policies and wiring. `grep activeContextWindow|firstKeptEntryId extension --include=*.ts` (excluding
tests) returns nothing.

## Smoke 1 — fresh sacrificial seeded authoring session

**Launch.** From the implementation worktree (its `.pi/settings.json` `packages` carries `".."`,
so the launched extension IS this worktree's code), with `PERK_RUN_ID`/`PI_SESSION_*`/
`PI_SUBAGENT_*` unset for an independent identity:

```sh
perk plan from <scratch>/smoke-notes.md --no-sync -- -p --mode json \
  --model anthropic/claude-haiku-4-5 --thinking off --session-dir <scratch>/smoke-sessions
```

`perk plan from` a local file mints no issue and adopts nothing; the seed told the model to reply
`OK` and never save. The session header's `cwd` is the worktree; workflow-state recorded
`run_id=01M1YZQHZM6V462BG86NFW8XS7`, `mode=read-only`, `stage=plan`, `perk_version=3.2.0`.

**Turn 1 (the cold launch turn, print mode).** Persisted entries: the cold USER prompt carrying
`The following skill binding(s) apply here:` exactly once (the `stage:plan` `perk-plan` pointer);
exactly one `perk:mode-context`, one `perk:plan-context` (`[PLAN AUTHORING]`), and one
`perk:plan-adapter-plannotator` (the PLAN flavor — `[providers] plan = "plannotator-plan"` is
selected in this repo); **no** `perk:binding-context` (first-turn cold dedup via the submitting
prompt); no `perk:agent-scratch` (read-only). No duplicate selected authoring/provider flavor.

**Turns 2–4 (RPC `prompt`, same session file).** Two small turns appended no new custom
message (dedup on the live copies). A first RPC `compact` was refused by Pi — `Nothing to compact
(session too small)`: Pi's default `keepRecentTokens` is 20 000 and the session was smaller — so
a bulk turn made the model `read` `shared/contracts.md` three times (real tool results, ~71k
tokens before compaction); that turn also appended no new custom message.

**Real compaction (RPC `compact`, model-generated).** Compaction entry `e5472b09`,
`firstKeptEntryId=b436f249` (the assistant `OK` that closed the bulk turn), `tokensBefore=71094`.
The summary quotes none of the markers or the header.

**Turn after compaction (RPC `prompt`).** Persisted: a NEW `perk:plan-context`, a NEW
`perk:plan-adapter-plannotator`, and a NEW `perk:binding-context` (the cold user prompt was
compacted out, so Mechanism A re-delivered the render) — one each — and **no** new
`perk:mode-context` (full-branch once-per-branch policy: the historical copy still sits on the
branch). Pi's own projection of the final leaf (`SessionManager.open(file).buildContextEntries()`
→ `sessionEntryToContextMessages`, read through the production leaf): 7 projected entries over a
29-entry branch — `compaction, message, message, custom_message(perk:plan-context),
custom_message(perk:plan-adapter-plannotator), custom_message(perk:binding-context), message`;
`contextCarriesMarker` = live for plan/plannotator/binding (2/2/1 copies on the full branch, 1/1/1
in projection) and NOT live for the mode context (1 on the branch, 0 in projection); the
compaction summary IS in the projection and is not evidence.

**Turn 5 (print mode, same file).** After the re-delivery, one more turn appended no custom
message (7 before, 7 after): the re-delivered copies dedup in turn.

## Smoke 2 — fresh write-capable, scratch-eligible session

A bare warm `pi -p --mode json` session in the worktree (no handoff → warm-minted identity,
read-write, no advisory child identity):

- workflow-state `run_id=01M1YZXN4SS2JBHMBV3MY8KK5Z`, no `mode` (write-capable),
  `perk_version=3.2.0`;
- `.perk/workflow/scratch/runs/01M1YZXN4SS2JBHMBV3MY8KK5Z/agent/` provisioned, POSIX mode `0700`;
- exactly one hidden `perk:agent-scratch` custom message whose bytes equal the rendered block for
  that run id byte-for-byte (marker line + the two guidance lines);
- a second turn on the same session appended no second block.

## Blocked / not-observed live (covered deterministically instead)

- **Interactive session-tree navigation.** Pi's RPC mode exposes no navigate command (only
  extension command contexts reach `navigateTree`), and the TUI `/tree` gesture was not driven
  headlessly. Live/missing/abandoned-branch evidence and the pre-compaction checkpoint are proven
  by `contextEvidence.test.ts` over real `branch`/`branchWithSummary`, and the registered
  extension's behavior across `navigateTo` + reload by the `contextInjection.test.ts` composition
  smoke on a real bound `AgentSession`.
- **The `context`-filtered LLM input.** Headless print/RPC output does not expose the post-filter
  message list; what was observed is the persisted branch plus Pi's projection through the
  production leaf. Strip/keep behavior (owned custom + owned user markers; binding's user-prompt
  survival even after the stage stops binding; scratch's direct-only cleanup) is pinned by the
  consumer suites.
- **Repeated compaction.** One real compaction was exercised live; the second-compaction and
  retained-tail arms live in `contextEvidence.test.ts`.

Smoke sessions, transcripts, and the RPC driver live under the implementation run's agent scratch
(`.perk/workflow/scratch/runs/01M1YY6VJ0DDN081GWFK9TRPGX/agent/`) — non-authoritative, pruned with
the run. No review, save, or backend mutation occurred in either smoke session.
