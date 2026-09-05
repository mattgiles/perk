# Native-wake review streaming: development baseline and live protocol

**Date:** 2026-09-05. **Status: IN PROGRESS — not submission evidence yet.** The repo-local
background-launch prerequisite passed. Required live legs T/B/D/N/U remain **unobserved / not
passed**. This record does not certify native streaming, global hosts, or consumer compatibility.

## Part A — repeatable protocol and preconditions

### Actors, identity, and host selection

The implementation session stages disposable targets and captures evidence. The human launches
fresh **interactive** Pi sessions and operates real hunk/browser surfaces. Never reuse the
implementing session, replace an interactive door with a headless probe, alter reviewer tool
allowlists, or switch runners to make a leg pass.

1. Commit the exercised code. Record absolute cwd, branch, full SHA, clean status, Pi executable,
   all five installed dev Pi versions, installed (unpinned) pi-subagents version, effective
   model configuration and observed model metadata, reviewer-definition hashes, exact Ponytail
   skill files/hashes, child mode/tool availability, and bridge configuration for each leg.
2. Use the repo-local `node_modules/.bin/pi`, with coding-agent/ai/tui/server/client at 0.85.1.
   Follow `docs/developers/pi-subagents-reverify.md` for the host-alias probe and existing smoke.
   The smoke is a prerequisite, not a substitute for streaming evidence.
3. Bare probes remove inherited `PERK_RUN_ID` and `PI_SESSION_FILE`; normal draft legs instead
   acquire fresh `perk plan` handoffs with the repo-local Pi selected first on PATH. Use
   branch-under-test perk code and normally converged reviewer definitions. Ending a model
   turn must leave the Pi host open.
4. Use a small disposable docs-only PR with a fresh verifiably wrong fact for T/B/U, a scratch
   draft with verifiable named-symbol/decision defects for D, and a bounded decision-complete
   draft for N. Do ordinary review work: no fake reports, scripted empty progress, artificial
   delays, hidden capability overrides, or instructions to manufacture a clean outcome.

### Five factored live legs

| Leg | Door / condition | Unique required observation |
| --- | --- | --- |
| T | `/pr-review-terminal <scratch-pr>`, bridge on, findings | Native adversarial batches reach real hunk; ledger/final remainder and human authority survive reconciliation. |
| B | `/pr-review-browser <scratch-pr>`, bridge on, findings | Native adversarial batches reach real browser; source-scoped final replacement retains correct findings. |
| D | `/plan-review-browser <custom lens>`, bridge on, findings | Separate draft tool pair, phrase anchors and custom priming reach browser and reconcile. |
| N | `/plan-review-browser`, bridge on, no findings | No empty progress; native completion alone triggers one collection; covered false reports receive neutral disclosure. |
| U | `/pr-review-browser <scratch-pr>`, bridge off, findings | No progress; native completion triggers one collection; covered false reports still reach final browser sink with completion-only warning. |

These are **not a full cross-product**. Both report families' disclosure/lifecycle matrices are
offline-pinned at their tool-pair cores. Objective rendered-context/priming, stack selection,
active/foreign variants and pre-PR wave-free behavior are **offline-pinned**, not extra live legs.

For U, in the isolated driver checkout change only `subagents.intercomBridge.mode` to `off`.
Retain a byte-exact restoration copy of settings, capture the effective setting and doctor
warning, and start a fresh session. Restore afterward. If capability/delivery unexpectedly
remains present, record the contradiction and stop; never manufacture `streamed: false`.

### Event-order acceptance

For T/B/D capture parent and child JSONL event order/timestamps, workflow/child identities, actual
turn boundaries, decisive tool-result excerpts and real sink observations:

- Exactly one start and real background children; a nonempty `contact_supervisor` batch from
  the unchanged reviewer definition accepted/queued **before workflow completion**.
- Parent ends the launch turn; a native supervisor message arrives without human prompting and
  its provisional batch reaches the real sink **before final reconciliation**. Identify that
  provisional hunk/push call separately from final remainder/`replace: true` calls.
- Progress may queue during an active turn, and progress/completion may arrive together. Relay
  already-delivered batches before collect; no extra turn boundary is required. A sink push
  after the producing child or workflow settled is not itself a failure.
- Only matching native **workflow** completion triggers one successful typed collect, without
  a human nudge, polling chain, or notification-preview reconciliation. Final reports/coverage
  are authoritative; duplicate/late notices must not replay provisional data over final findings.
- Record final sink contents and real dedupe/replace results, not just `streamed: true`.

For N/U prove completion and exactly-once collection **without progress messages**, schema-valid
false status, unchanged coverage and the correct neutral/warning disclosure. No-findings is an
ordinary false status, not evidence of a broken bridge. Any real concern on N leaves that leg
unmet pending owner disposition; do not force clean.

One wave per planned leg, no in-flow retries. Missing delivery/observations, duplicate/churny
sink effects, collection still unsettled after observed completion/grace, bridge contradictions,
or launch failures halt relevant validation for the owner. Additional attempts need explicit
owner direction and separate records. Changed exercised code requires rerunning affected legs
at the new SHA; evidence-only trailing commits may follow.

### Teardown and submission gate

End draft reviews with DENY/close and abandon scratch drafts — no approve/save. Do not post any
review. Before submission: close scratch PRs unmerged, remove scratch branches/review checkouts
and temporary driver checkout, stop owned hunk/browser sessions, restore settings byte-exactly,
and independently verify git status plus remote/checkout absence. Preserve sufficient sanitized
inline evidence before deleting runtime artifacts; never broad-delete shared session stores.
All five passed legs and verified teardown are submission prerequisites. The final single run-all
`run_ci` follows those prerequisites, not a promise to collect them later.

## Part B — observations, defect log, and teardown

### Background prerequisite: PASS (not streaming acceptance)

Exercised code: `52c4fde5763e6d2b7b2bb18af831460a35d6321f`, branch `plan-2226`, clean tree.
Cwd: `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2226`.
Pi executable: that cwd's `node_modules/.bin/pi`. Coding-agent/ai/tui/server/client all resolved
locally to **0.85.1**; installed pi-subagents **0.65.1** remained unpinned. No global installation,
production child mode, reviewer capability, or bridge configuration was changed.

Install succeeded. `npm run typecheck`, `extension/piAiCompatGuard.test.ts`, and the packaging
pin-lockstep/zero-runtime-dependencies tests passed before committing the dependency slice.
The installed engine's jiti loaded `src/runs/background/runner-aliases.ts` and called
`resolveHostPeerAliases` against the absolute repo-local coding-agent root. Result:

```json
{"missing": [], "supplemental": []}
```

Every target existed. Paths relative to the cwd's `node_modules/` (the probe used absolute paths):

| Alias | Resolved path |
| --- | --- |
| `@earendil-works/pi-coding-agent` | `@earendil-works/pi-coding-agent/dist/index.js` |
| `@earendil-works/pi-agent-core` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core/dist/index.js` |
| `@earendil-works/pi-agent-core/node` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core/dist/node.js` |
| `@earendil-works/chord` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/chord/dist/index.js` |
| `@earendil-works/chord/context` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/chord/dist/context/index.js` |
| `@earendil-works/pi-server` | `@earendil-works/pi-server/dist/index.js` |
| `@earendil-works/pi-server/unix` | `@earendil-works/pi-server/dist/transports/unix/index.js` |
| `@earendil-works/pi-client/unix` | `@earendil-works/pi-client/dist/unix.js` |
| `@earendil-works/pi-tui` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui/dist/index.js` |
| `@earendil-works/pi-ai`, `@earendil-works/pi-ai/compat` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/compat.js` |
| `@earendil-works/pi-ai/oauth` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/oauth.js` |
| `@earendil-works/pi-ai/providers/all` | `@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/providers/all.js` |
| `typebox` | `@earendil-works/pi-coding-agent/node_modules/typebox/build/index.mjs` |
| `typebox/compile` | `@earendil-works/pi-coding-agent/node_modules/typebox/build/compile/index.mjs` |
| `typebox/value` | `@earendil-works/pi-coding-agent/node_modules/typebox/build/value/index.mjs` |

The **one** existing `just subagents-smoke` run produced:

```text
subagents-smoke: PASS
perk 3.2.0 @ 52c4fde5763e6d2b7b2bb18af831460a35d6321f
pi 0.85.1 (pinned dev toolchain) · pi-subagents 0.65.1 (installed, unpinned)
observed 1 explore_objective_node execution(s) · pi exit 0
```

Receipt: workflow `bd64a3dd-d3fc-4b86-af10-aa1c95af8913`, state `complete`, mode `workflow`,
PID **67298**. Child `8cabbabb-d1fb-4c5c-9ac3-16c3dc58e5f2`, workflow key `explore`, state
`complete`, mode `single`, PID **67412**. Child process-terminal evidence:

```json
{"state":"observed","runnerProcessInstanceId":"aa4fd2e9-d80d-4141-be96-2d92e0a426c1",
 "instances":[{"kind":"runner","processInstanceId":"aa4fd2e9-d80d-4141-be96-2d92e0a426c1",
 "closeObservedAt":1788642313918,"exitCode":0,"signal":null}]}
```

The separate runner process, child async artifact directory, and observed runner close establish
background execution, not a foreground-configured PASS. The child performed one
`structured_output` call (tool end **2026-09-05T21:05:12.773Z**); parent
`explore_objective_node` returned `details.ok: true`, a report, one attempt and a successful
child with `outputState: "present"` at **21:05:13.774Z**. Parent model metadata:
`anthropic/claude-opus-4-8`; child `openai/gpt-5.6-terra`, fresh context, 9 turns, exit 0.
The smoke harness removed inherited `PERK_RUN_ID`/`PI_SESSION_FILE` and launched the repo-local
executable. This smoke did **not** test reviewer streaming, hunk/browser delivery, or bridge-off.

Non-authoritative retained raw evidence is under
`.perk/workflow/scratch/runs/01M1SNZFQ3MCYNS32DQ0MJWQ36/agent/`: `host-aliases.json`,
`background-smoke.log`, `smoke-parent.jsonl`, `smoke-child-status.json`,
`smoke-workflow-status.json`. Original runtime child artifacts lived under
`…/pi-subagents-uid-502/async-subagent-runs/8cabbabb-d1fb-4c5c-9ac3-16c3dc58e5f2/`.
No disposable PR, scratch draft, temporary checkout, or review surface was created for this
prerequisite; git status remained clean immediately after the smoke.

### Offline verification and preparation blockers

- Both selected CI subsets passed: `lint-js,typecheck-js,test-js,docs-check` and
  `lint-py,typecheck-py,test-py`. The final run-all gate is deliberately **not yet run**.
- Both opt-in prose gates passed (`just prose-review-test`: 553 tests; `just prose-review-check`).
  Prose-map sync initially failed on 15 pre-existing unmapped vendored dignified-python files;
  the same failure reproduced with the implementation stashed. Adding that source directory
  to the existing utility-skill route allowed normal regeneration (no new prose abstraction).
- Reviewer definitions were reconverged through init's `_converge_subagent_agents`; schema/def
  tests verify the committed `.pi/agents/perk/` copies are byte-identical.
- **Inherited-worktree skill conflict resolved for dogfood via an isolated driver.** The
  original `skills sync --dry-run` found inherited links into the parent checkout's cache.
  The owner then explicitly approved a disposable checkout whose user-owned skill manifest
  selects the committed local source. Normal `skills sync` and a following dry-run passed in
  that checkout; all four review skill files and both reviewer definitions compare byte-identical
  to the implementation. Generated mirrors were not hand-edited; original driver manifests and
  Pi settings are retained for restoration. Main/global configuration was untouched.
  There are no committed skill-copy mirrors in the implementation worktree.
- Retired-literal census: remaining exact wait-name hits are negative regression guards,
  explicitly historical learned/archive/changelog/dated-assessment passages, or the installed
  upstream source filename pinned by doctor. No positive tool census or executable relay
  prescription remains in the changed live carriers; no replacement wait tool was adopted.

### Prepared interactive environment

The isolated driver is at the implementation worktree's
`.perk/workflow/scratch/runs/01M1SNZFQ3MCYNS32DQ0MJWQ36/agent/live/driver`, branch
`dogfood-2226-driver`, code SHA `bdf6dd29a380fbc0b7fe999d1746573318a25555`.
It loads its own branch-under-test perk package and committed reviewer definitions, using the
same repaired implementation-worktree Pi executable as the background prerequisite. Installed
pi-subagents is 0.65.1 and exact Ponytail package is 4.9.0; hashes, source paths and configuration
are captured in `live/driver-preflight.json`. The launch wrapper selects the existing agent home
`/Users/mattgiles/dev/github/mattgiles/perk/.pi/agent` without editing it and removes inherited
`PERK_RUN_ID`/`PI_SESSION_FILE`. Project bridge mode and agent-home subagent overrides are unset.

Read-only doctor confirms the selected Pi executable, skill delivery, converged reviewer defs,
compatible subagent/Ponytail surfaces, hunk presence, and active bridge. Its **overall result is
not healthy**: it also reports the deliberately replaced manifest declaration/alias, an empty
fresh workflow directory, and absent optional local config. No doctor repair was run; it would
undo the explicit branch-bound skill selection. These setup observations are not a live pass.

Disposable draft PR **#2228**, branch `dogfood/native-wake-2226-01M1SNZF`, head
`1b48e703` over `dcf051c785f08574cb589d92933bea40c55b4414`, contains only
`docs/developers/review-wave-schema-note.md`. Its false claim that both review schemas require
`verdict` is independently checkable against the real source. It must be closed unmerged after
T/B/U. The target checkout is `live/target`, owned by the isolated driver's worktree list.

The one-shot `live/start-T.sh` is prepared but has **not been run**. It starts an interactive
session with logs under `live/T/parent`, does not launch a wave itself, and asks the human to
invoke `/pr-review-terminal 2228` once. Its only added parent instructions are the disposable
no-post/no-save/no-repository-edit/no-retry boundaries and a pause after reconciliation; it does
not coach the relay mechanism or reviewer output. The normal door/tool/skill carriers own that.

### Streaming legs and teardown

| Leg | Exercised SHA | Verdict | Evidence |
| --- | --- | --- | --- |
| T | — | Unobserved / not passed | Awaiting fresh human-operated interactive session |
| B | — | Unobserved / not passed | Awaiting fresh human-operated interactive session |
| D | — | Unobserved / not passed | Awaiting fresh normal plan handoff and browser session |
| N | — | Unobserved / not passed | Awaiting fresh normal plan handoff and browser session |
| U | — | Unobserved / not passed | Awaiting isolated driver, bridge-off capture and restoration |

No streaming defect verdict or full teardown verdict is claimed yet. Submission remains blocked
on these observations and independently verified teardown. The original failing baseline and
historical held-turn measurements remain unchanged in their respective archive records.
