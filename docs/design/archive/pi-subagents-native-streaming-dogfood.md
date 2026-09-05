# Native-wake review streaming: development baseline and live protocol

**Date:** 2026-09-05. **Status: IN PROGRESS — not submission evidence yet.** The repo-local
background-launch prerequisite and live legs T/B passed. Required live legs D/N/U remain
**unobserved / not passed**. This record does not certify the remaining streaming routes,
global hosts, or consumer compatibility.

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

The human ran the one-shot `live/start-T.sh`, starting an interactive session with logs under
`live/T/parent`, then invoked `/pr-review-terminal 2228` once. The wrapper did not launch a wave
itself. Its only added parent instructions are the disposable
no-post/no-save/no-repository-edit/no-retry boundaries and a pause after reconciliation; it does
not coach the relay mechanism or reviewer output. The normal door/tool/skill carriers own that.

### Streaming legs and teardown

| Leg | Exercised SHA | Verdict | Evidence |
| --- | --- | --- | --- |
| T | `bdf6dd29a380fbc0b7fe999d1746573318a25555` | PASS | Native supervisor relay → one real hunk comment → one final collect; evidence below |
| B | `bdf6dd29a380fbc0b7fe999d1746573318a25555` | PASS | Native browser pushes, global dedupe, and all-covered-angle final replacement; evidence below |
| D | — | Unobserved / not passed | Awaiting fresh normal plan handoff and browser session |
| N | — | Unobserved / not passed | Awaiting fresh normal plan handoff and browser session |
| U | — | Unobserved / not passed | Awaiting isolated driver, bridge-off capture and restoration |

No full teardown verdict is claimed yet. Submission remains blocked on the remaining legs and
independently verified teardown. The original failing baseline and historical held-turn
measurements remain unchanged in their respective archive records.

### Leg T — PASS: native batches reach the real hunk sink

The human reported successful Pi startup, hunk opening after only entering
`/pr-review-terminal 2228`, visible reviewer comments, **no messages/nudges after launch**, one
final visible comment, and no errors. The screenshot `Screenshot 2026-09-05 at 5.51.45 PM.png`
was inspected directly: it shows the new documentation file and one **correctness** note at
new line 7, titled “Schema reference reverses the actual contract (verdict is forbidden, not
required)”, with the expected explanatory body. A retained copy is `live/T/hunk-final.png`,
SHA-256 `f0b0c7870b5983d73530776a73ab99e190d46e21d08fc13aa6a500c97b28267b`.
The user was unsure of visual timing; the JSONL order below supplies that proof instead.

Parent session: `01a0738c-62e9-7292-8ab0-1282472a1d93`, model
`anthropic/claude-opus-4-8`, driver cwd/branch/SHA and host exactly as recorded above.
One workflow: `97f67310-010a-4297-8ea9-d5091d568dc9`, parent process PID 27911.
Four real fresh-context background children, all model `openai/gpt-6-astra`, with distinct
runner PIDs and observed runner exits 0:

| Lane | Child run | Runner PID | Final streamed / findings |
| --- | --- | --- | --- |
| claimed-intent | `42d40796-fabf-4a41-b154-ed1c2773d3d5` | 28245 | true / 1 |
| correctness | `92b4f33a-941f-4359-aa33-89b9a2c7bfb2` | 28246 | true / 1 |
| tests | `03f43690-9873-4f2f-949f-8037097bbb05` | 28247 | false / 0 |
| ponytail | `c47e274e-bcc5-4406-bba4-97660c588705` | 28248 | false / 0 |

Ponytail metadata names the source-bound `ponytail-review` skill. The unchanged reviewer
allowlists received working `contact_supervisor` and `structured_output` capabilities; both
finding-producing lanes used the former and all four used the latter successfully. No
production launch-mode, capability, or profile override was introduced.

Decisive order (UTC, 2026-09-05; persisted JSONL timestamps):

| Time | Event |
| --- | --- |
| 21:50:32.123 | Single start accepted, requested/runnable = claimed-intent, correctness, tests, ponytail; no preflight failures. |
| 21:50:35.072 | Parent assistant ends its launch turn (`stopReason: stop`). |
| 21:51:07.176 | Correctness child receives “Supervisor progress update queued.” with `delivered: true`, request `34a2929e-cae8-4e1e-b25a-42dced18ab24`; batch contains one nonempty finding. |
| 21:51:07.318 | Native `subagent_supervisor_request` is injected into idle parent; next parent action is the hunk handshake, without human input. |
| 21:51:08.938 | Claimed-intent child receives the same successful queue result for request `36e9a73b-ad3a-4e95-b862-721669947505`, also one finding. |
| 21:51:12.177 | Hunk handshake succeeds: session `191b55a2-647e-4b15-9817-388192913377`, agent notes visible, 0 live comments. |
| 21:51:12.178 | Second native batch is delivered while the parent relay turn is active. |
| 21:51:16.052 | Workflow terminal status records completion; both nonempty submissions precede this. |
| 21:51:29.919 | Provisional `hunk session comment apply` returns “Applied 1 live comments”, new line 7, id `mcp:7ac89b37-5604-407a-9453-a6a42ee90142:0`. Parent explicitly retains its path+line ledger and dedupes the second same-anchor batch. |
| 21:51:29.920 | Native `subagent-notify` enters the parent with `Workflow run: 97f67310-010a-4297-8ea9-d5091d568dc9`. |
| 21:51:32.188 | The single `collect_review_wave` returns ok, complete=true, all four covered, failures=[], one attempt. |
| 21:51:45.223 | Parent finishes reconciliation and ends the relay turn. One unioned finding, already pushed; no final unpushed remainder or duplicate sink effect. |

The provisional sink push happened **after** workflow settlement but **before** the parent
received matching completion and before collection/final reconciliation. That satisfies the
planned ordering contract; it is not a parent-versus-child speed test. Progress queued into the
active relay turn and matching completion followed a tool return; no artificial extra turn
boundary was introduced.

The collected tool text includes the neutral disclosure:

```text
Review wave complete: covered 4/4 angle(s).
perk: collect_review_wave — no provisional batches (no findings): tests, ponytail
```

The parent retained tests' factual `fyi` without pushing it. There were exactly one start, one
hunk comment-apply, and one successful collect, no wait/poll tool, no manual status-file
reconciliation, no re-collect, and no late provisional replay in the captured parent session.
A subsequent read-only hunk comment listing still contains exactly the same single comment
id/anchor; read-only GitHub verification showed `{state: OPEN, isDraft: true, review_count: 0}`.
No review was posted. The human then confirmed **“T closed”**. Independent verification found
parent PID 27911 absent and `hunk session get` returning “No active session matches repoRoot”.
The normal `perk pr review cleanup --pr 2228 --json` returned `success: true, removed: true`;
the review checkout is absent both on disk and from the driver's Git worktree list. The scratch
PR/branch and fixture checkout are deliberately retained for B/U; full teardown is still pending.

Raw parent/child session snapshots and workflow/child status receipts are retained under
`live/T/captured-runtime/`; compact extracted evidence is in `live/T/evidence.json`, with
`hunk-session.txt`, `hunk-comments.txt`, and `github-posting-check.json`. These paths are
non-authoritative conveniences; the sanitized decisive observations above survive their removal.
Per-leg closure receipts are `live/T/hunk-after-close.txt`, `checkout-cleanup.json`,
`worktrees-after-cleanup.txt`, and `github-after-cleanup.json`.

### Leg B — PASS: native browser relay and source-scoped final replacement

The human launched `live/start-B.sh` and invoked `/pr-review-browser 2228` once. The wrapper
selected the same code SHA, repaired host, bridge-on configuration and branch-bound
skill/definition files as T, with fresh logs under `live/B/parent`. The installed browser
integration is `@plannotator/pi-extension` 0.27.12. The human reported successful Pi/browser
startup, visible annotations, **no messages/nudges after launch**, one final annotation, no
remaining duplicate/missing annotations, and no errors.

The screenshot `Screenshot 2026-09-05 at 6.06.08 PM.png` was inspected directly: it shows one
**PERK:QUALITY** annotation at new line 7 of the documentation file, major/high, with the final
schema-contract-reversal body. The UI's unsubmitted “Post Comments” badge is 1. A retained copy
is `live/B/browser-final.png`, SHA-256
`d5c104efaf1c52196ef68f7ad308a7ddf82f4f08e86941a3607e9d46c2cb2d62`.
The user was unsure whether it appeared before the final summary; JSONL supplies that ordering.

Parent session: `01a07398-f7de-7352-9a76-f2d7985de1c1`, model
`anthropic/claude-opus-4-8`. One workflow `37613aaa-a2b7-433f-b962-ef6c053e1815`, parent PID
30150. All three fresh-context children used `openai/gpt-6-astra`, separate background runner
processes and observed runner exits 0:

| Lane | Child run | Runner PID | Final streamed / findings |
| --- | --- | --- | --- |
| claimed-intent | `78cb58b1-b331-48e2-85d1-f149feb00fd7` | 30844 | true / 1 |
| quality | `35210511-9b8b-4d65-aa07-dbbc16555e1a` | 30845 | true / 1 |
| ponytail | `50ed5bb4-0e93-45cf-ab89-3d13542fde46` | 30846 | false / 0 |

Ponytail metadata names the exact `ponytail-review` skill; the existing reviewer definitions
were unchanged. Both nonempty batches successfully used the injected supervisor capability,
and every lane completed via a successful `structured_output` call.

Decisive order (UTC, 2026-09-05):

| Time | Event |
| --- | --- |
| 22:04:15.568 | Single start accepted, requested/runnable = claimed-intent, quality, ponytail, no preflight failures. |
| 22:04:19.665 | Parent ends the launch turn. |
| 22:04:50.337 | Quality child receives “Supervisor progress update queued.”, `delivered: true`, request `a449249f-15a0-42e9-83a0-593a64c9f86a`, one nonempty finding. |
| 22:04:50.462 | Native quality progress message wakes the idle parent without human input. |
| 22:04:50.922 | Claimed-intent receives the same successful queue result, request `ef9ff898-1604-428f-b17c-fcfe9ba09308`, one nonempty finding. |
| 22:04:54.341 | Provisional quality `push_annotations`: pushed=1, held=0, deleted=0, id `85d23213-262f-4893-a0e6-7fe69555d46b`. |
| 22:04:54.345 | Claimed-intent native batch is delivered during the active relay turn. |
| 22:04:58.791 | Provisional claimed-intent push: pushed=0, one skipped duplicate anchor `line:docs/developers/review-wave-schema-note.md:7`, held=0. |
| 22:04:58.907 | Workflow terminal status records completion, after both successful batch submissions and the first provisional browser push. |
| 22:05:02.171 | Parent ends its relay turn with no completion notice yet delivered. |
| 22:05:02.182 | Matching native `subagent-notify` wakes the parent; its correlation names workflow `37613aaa-a2b7-433f-b962-ef6c053e1815`. |
| 22:05:04.310 | Single collect succeeds: complete=true, all three covered, failures=[], one attempt. |
| 22:05:18.471 | Final claimed-intent `replace: true`: pushed=0, same duplicate anchor skipped, deleted=0. |
| 22:05:18.490 | Final quality `replace: true`: pushed=1, deleted=1, new id `77122f98-0a44-4f98-890e-980492983bea`. |
| 22:05:18.503 | Final Ponytail `replace: true`, empty findings: pushed=0, deleted=0, no held batches. |
| 22:05:28.334 | Final summary and parent turn end. |

There is one final replacement call **per covered angle**, including the empty final array.
The tool's actual results prove global dedupe and source-scoped replacement: only quality's
existing annotation was cleared/replaced, the same-anchor sibling stayed deduped, and the real
browser retained one final annotation. No annotation HTTP was composed by the model.
No artificial waits, manual status-file reconciliation, retries, duplicate collects or late
provisional replay occurred in the captured session. The native turn boundaries are observed,
not a requirement that inference outrun child execution.

Collection and the parent both disclosed Ponytail neutrally:

```text
Review wave complete: covered 3/3 angle(s).
perk: collect_review_wave — no provisional batches (no findings): ponytail
```

Read-only GitHub verification showed `{state: OPEN, isDraft: true, review_count: 0}`; no review
was posted. Browser/Pi are still open pending human-confirmed closure; per-leg cleanup has not
yet been claimed. Raw parent/child snapshots and status receipts are under
`live/B/captured-runtime/`; sanitized timeline and extraction are `live/B/parent-timeline.json`
and `live/B/evidence.json`, with `github-posting-check.json` and the screenshot alongside.
