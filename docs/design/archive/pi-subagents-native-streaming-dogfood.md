# Native-wake review streaming: development baseline and live protocol

**Dates:** 2026-09-05–06 (UTC; screenshot names use local time).
**Status: BLOCKED — not submission evidence yet.** The repo-local background prerequisite,
original T/B legs, and repaired-code B2 passed. Original D remains **not passed**. The approved
browser repair worked in D2, but D2 is also **not passed**: two children successfully captured
reports yet were reported failed with “Request timed out.” N/U remain **unobserved / not passed**;
the authorized rerun is exhausted and further action requires owner disposition. This record does not certify the remaining streaming routes,
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
| D | `bdf6dd29a380fbc0b7fe999d1746573318a25555` | NOT PASSED / owner escalation | Custom lane streamed but produced no required final report; 4/5 covered; provisional-source retention described below |
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
was posted. The human then confirmed **“B closed”**. The parent transcript records the native
browser response “closed … without submitting”, followed only by an in-session question (no
posting/tool call). Independent verification found parent PID 30150 absent; the browser server
runs in that same process. Normal `perk pr review cleanup --pr 2228 --json` returned
`success: true, removed: true`; the checkout is absent on disk and from the driver's worktree
list. The scratch PR remains open/unmerged with zero reviews, retained for U.
Raw parent/child snapshots and status receipts are under `live/B/captured-runtime/`; sanitized
timeline and extraction are `live/B/parent-timeline.json` and `live/B/evidence.json`, with
`github-posting-check.json` and the screenshot alongside. Closure receipts are
`parent-session-after-close.jsonl`, `checkout-cleanup.json`, `worktrees-after-cleanup.txt`, and
`github-after-cleanup.json` in the respective capture/leg directories.

### Leg D preparation — fresh handoff and exact draft verified

`live/start-D.sh` is prepared to start a **normal fresh `perk plan` handoff**, using the same
repaired Pi selected first on PATH and the same inherited agent-home selection. `--no-sync`
preserves the committed driver SHA rather than advancing the test code. A read-only launch
preview succeeded; its preview run id is not an executed handoff. No model session or draft
review was launched by the implementation session.

The human subsequently launched the normal plan session and reported **“D draft ready”**.
Its consumed handoff is run `01M1STA1JRNNNB8XGAB6FN92HX`, `mode: read-only`, `stage: plan`,
bound to parent session `01a073a5-0763-74b6-a472-f2127c729347` (model
`anthropic/claude-opus-4-8`). The only preparation tools were `read` and `plan_draft`; no review
or subagent was launched. At 22:16:42.384Z the draft tool returned ok, 1790 bytes, with the exact
fixture digest below. Independent comparison of the persisted session artifact and fixture
confirmed byte identity; the driver remains at `bdf6dd29`. Captures are
`live/D/preparation-handoff.json`, `draft-verification.json`, and `verified-plan-draft.md`.

The supplied `live/D-draft.md` proposes a documentation reference and contains three concrete
review targets: a nonexistent `collectDraftReportsOnce` helper, an incorrect interpretation of
no-findings `streamed`, and a retry-policy choice deferred to implementation. SHA-256:
`618fb3125dc66d716282365c02ab6f816384e1324fb19717b17de4fc9f580bb4`.
The preparation message asks the parent only to read/register those exact bytes via `plan_draft`
and pause. It does not prescribe reviewer findings or delivery behavior, and forbids review
launch/save/post/retry during preparation. With working-draft identity and bytes verified, the human is being handed the custom-lens
invocation: `/plan-review-browser Check all stated helper names and the meaning of streamed
against the source; also check whether retry choices are settled.` Reviewers remain ordinary unchanged definitions; the draft is the intentionally flawed input,
not a scripted report.

### Leg D — NOT PASSED: custom completion failure and browser authority gap

The human invoked the supplied custom-lens command and reported: browser opened, annotations
appeared **before** the final summary, no subsequent input/nudges, five final annotations,
but **no visible custom-lane label**. The inspected screenshot
`Screenshot 2026-09-05 at 6.27.12 PM.png` shows five generic “Comment” rows, not per-lane badges.
The first two displayed bodies exactly match the custom lane's provisional findings. Copy:
`live/D/browser-final.png`, SHA-256
`8b37674f05debf949115f3909124936f2afa43be260dcda8eb3ce8e85934387b`.

One workflow `8e6c01eb-3b44-421a-b887-29969ed5e86b`, parent PID 32915, at the same driver
cwd/branch/SHA, repaired Pi host and bridge-on configuration. All five children actually launched
as separate fresh-context background runner processes using `openai/gpt-5.6-sol`:

| Lane | Child run | PID | Final result |
| --- | --- | --- | --- |
| grounding | `0ba91b90-9917-46ad-bb96-0f1f5624c35f` | 33939 | covered, streamed=true, 3 findings |
| decision-completeness | `6f5503af-e03c-41fd-bbe7-7bb4732bd655` | 33940 | covered, streamed=true, 2 findings |
| scope | `0ff4bb5c-9a2f-4535-b417-4327cacbba54` | 33941 | covered, streamed=true, 1 finding |
| custom | `ff2f9459-ec21-4ff6-82ed-a10381d6ebdf` | 33942 | failed: no structured_output call/report |
| ponytail | `c587db86-60c8-436a-9a20-d62448ed9987` | 33943 | covered, streamed=true, 1 finding |

Ponytail used the exact `ponytail` skill. Each recovery descriptor has the unchanged declared
read/grep/find/ls/bash allowlist and the required report schema including `streamed`; these
pre-injection descriptors do **not** by themselves prove each runtime tool was exposed. All
five lanes successfully used `contact_supervisor`; four successfully used `structured_output`.
The custom child's final assistant message at 22:23:16.432Z has `stopReason: stop`,
`rawStopReason: completed`, empty text and no tool calls. No failed structured-output attempt
is recorded. Its runner exited 0, but the engine correctly marked the step failed for missing
required output. The reason the model ended without the call is **not established**; this is
not evidence justifying a capability-list, host-version, or runner-mode change.

Decisive order (UTC, 2026-09-05):

| Time | Event |
| --- | --- |
| 22:22:28.779 | Single start accepted all five requested/runnable lanes, custom included; no preflight failures. |
| 22:22:32.167 | Parent ends the launch turn. |
| 22:22:47.249 | Decision-completeness nonempty supervisor batch accepted/queued. |
| 22:22:47.387 | Native progress wakes parent; browser push at 22:22:51.797 creates 2 annotations. |
| 22:22:53.510 | Parent ends relay turn. |
| 22:23:03.006 | Custom nonempty 3-finding batch accepted/queued, `delivered: true`, request `d91b7af3-1b46-468c-b54b-61e813ea0ac8`. |
| 22:23:03.190 | Native custom progress wakes parent. |
| 22:23:09.975 | Custom provisional browser push creates 2 annotations; skips 1 same-phrase duplicate. |
| 22:23:13.199 | Scope provisional push creates 1 annotation; later Ponytail/grounding pushes dedupe existing phrases. |
| 22:23:16.432 | Custom ends with empty assistant completion and no structured_output call. |
| 22:23:20.558 | Workflow terminal status records completion; all five successful nonempty supervisor submissions preceded it. |
| 22:23:24.054 | Matching native workflow-completion notice reaches parent after the delivered provisional batches were relayed. |
| 22:23:26.227 | One collect returns ok but complete=false, 4/5 covered, custom lane-failed, one attempt. |
| 22:23:47.602 | Grounding final `replace: true` pushes 0: all 3 phrases skipped because existing sources still own those anchors. |
| 22:23:47.632 | Decision-completeness final replacement clears 2 and pushes 2. |
| 22:23:47.663 | Scope final replacement clears 1 and pushes 1. |
| 22:23:47.681 | Ponytail final replacement pushes 0, same-phrase duplicate skipped. |
| 22:23:57.549 | Parent reports incomplete coverage and ends the turn; no retry. |

The exact collect failure begins:

```text
Draft-review wave INCOMPLETE: covered 4/5 lane(s).
custom: lane-failed
Missing structured_output call; this step has outputSchema and must finish by calling structured_output.
Required structured output was not produced: …/ff2f9459-ec21-4ff6-82ed-a10381d6ebdf/structured-output/pi-subagent-structured-nUGxUe/output.json
```

**Defect/disposition log:**

- **D1 — required custom final report absent.** Native launch, custom priming, supervisor
  submission, idle wakes and completion-triggered single collection worked, but the required
  custom lane is uncovered. Successful provisional submission is not a report or coverage;
  D is not passed. No retry, resume, mode change, tool-list change or subsequent leg was run.
- **D2 — final-report authority gap at the browser sink.** The two custom-created annotations
  (`26ce4857-8e58-47c8-b77b-7716809fa50d`, `d0341e9c-1d3d-4585-bbd7-71dbbb747a9d`) remain visible
  despite custom having no authoritative report. Parent replacement ran only for covered lanes;
  grounding's final findings were skipped against those retained custom anchors. The screenshot
  therefore contains custom **provisional wording**, not grounding's final wording. Overlapping
  concerns do not erase that authority distinction. The current covered-only replacement
  prescription needs owner disposition; no partial-report recovery is silently introduced.
- **D3 — attribution not visible in the observed plan UI.** The screenshot shows generic
  “Comment” labels for all five annotations; absence of a `custom` badge is not proof that
  custom failed to run (it did run and supplied the first two visible bodies). Perk's plan
  mapping carries `source: perk:<angle>` but no `author`. Subsequent read-only source inspection
  found the installed plan transformer preserves optional `author`, and the plan UI renders that
  author value next to “Comment” rather than a source badge. An offline call to the installed
  transformer accepted `author: perk:custom`. This identifies a metadata-carrier mismatch;
  live verification of a repair remains required. It is distinct from D1.

Evidence is preserved in `live/D/captured-runtime/` (parent/child JSONL, workflow/child status,
recovery descriptors and runner logs), `live/D/evidence.json`, and `parent-timeline.json`, with
the screenshot alongside. Implementation tree was clean before this evidence-only edit; driver
HEAD is still `bdf6dd29` with only the explicitly approved manifest relocation/source-selection
changes. At that capture, the original read-only plan handoff and draft bytes remained intact and
Pi/browser were retained pending owner direction; **no approval/save or full teardown was
claimed**. Further validation or repairs required explicit owner disposition under the plan's
escalation rule (subsequent approval and closure are recorded below).

### Read-only investigation and amendment proposal

The owner chose **“Investigate and propose a fix”**, explicitly before code edits or another
wave. No production code, reviewer definition, model policy, dependency or live session was
changed during that investigation.

The missing-output guard in installed pi-subagents (`src/runs/shared/structured-output.ts`)
returns this error when its capture file is absent; the observed failure is not a rejected
schema payload. The custom session records no structured-output attempt and no tool rejection,
timeout or extension error. Its exact runtime tool availability was not persisted, so the
underlying empty-completion cause remains unproven. The proposal keeps strict failure/coverage
and does not invent a capability or model fix.

A disposable **offline** replay of D's recorded pushes through the existing annotation core
and an in-memory endpoint reproduced the final screenshot's source ownership: two custom
provisional annotations remained, and the shared scope/Ponytail anchor retained the minor
scope body rather than merging the major Ponytail concern. Clearing the uncovered custom
source before replacement removed custom contamination. Additionally partitioning the
reconciled final findings into disjoint source arrays (first contributing covered lane owns
an anchor; merged text retains contributing angle/severity/confidence labels) preserved the
final valid concerns and maximum severity using the existing replace/alternate mechanism.
No real annotation HTTP, model call, or review retry occurred. The diagnostic script and
results are `live/D/replay-annotation-reconciliation.mjs` and
`offline-reconciliation-diagnosis.json`; its first loader attempt hit Node's node_modules
TypeScript-strip restriction, then the installed engine's jiti loaded the same upstream
transformer successfully. That local diagnostic loader correction was not another live leg.

The then-unapproved amendment (`live/D/proposed-plan-amendment.md`) proposed plan-mode
author metadata, browser reconciliation that clears uncovered sources and uses disjoint merged
final arrays, and focused tests/contract/docs. It proposed one explicitly owner-authorized
fresh B/D rerun after a committed repair, retaining the original failed D record and unchanged
T evidence; N/U and final teardown/gate still stand. No automatic retries, provisional-report
recovery, new wave API/manager, upstream patch, model or capability change was proposed.

### Approved repair — committed; amended live validation pending

The owner explicitly replied **“I approve”** to the bounded amendment. It was appended to the
canonical plan #2226 body through the existing Python issue-backend update seam, then read back
and compared; the plan header, selector and objective-node status were unchanged. Copies and
receipt are `live/D/approved-amendment.md`, `amended-plan.md`, and
`plan-amendment-receipt.json`. This approval amends the implementation plan; it does **not**
approve/save the disposable D draft.

Repair commit: **`2ed55c1b6574ff69bdf64d9e6027162fcf0c75e3`**.

- Plan COMMENT/GLOBAL_COMMENT mapping now supplies the owning `author` alongside `source`.
- Browser guidance clears uncovered sources, builds disjoint merged final arrays from valid
  reports with preserved contributor labels and maximum severity, and replaces every covered
  source including empty arrays. Held pure clears/replacements cannot be called finalized.
- Focused regressions cover both plan/review mapping, both final replacement orders, failed
  source cleanup, held clears, higher-severity merged concerns, and untouched human/unrelated
  annotations. Browser guidance pins, contracts, three relevant skill sources and user docs
  were updated. No reviewer definitions, report schemas, model settings, launch parameters,
  upstream package files or terminal/hunk flow were changed.
- The affected node:test suites passed (124 tests). Selected CI checks `lint-js`, `typecheck-js`,
  `test-js` and `docs-check` passed. `test-py` first found a stack-prompt size regression; the
  template was shortened to 8954 bytes under its unchanged 9088-byte budget, its targeted
  budget/render tests passed, and `run_ci(check: test-py)` then passed. Both opt-in prose gates
  passed; prose-map sync reports the projection current without changes. The final run-all
  gate is still reserved until live validation and teardown succeed.

The owner authorized **one new B attempt and one new D attempt** at this repaired SHA. Original
T/B/D evidence above is retained verbatim as historical attempts; D remains failed. T's passing
result is retained because this repair is browser-only (new annotation guidance explicitly
scopes reconciliation to a browser surface). N/U retain their original first-attempt requirements.
No automatic retry or completion-policy/capability workaround was introduced: another missing
required report stops validation for owner disposition.

| Amended attempt | Code SHA | Status |
| --- | --- | --- |
| B2 | `2ed55c1b6574ff69bdf64d9e6027162fcf0c75e3` | PASS; per-leg cleanup verified |
| D2 | `2ed55c1b6574ff69bdf64d9e6027162fcf0c75e3` | NOT PASSED: 3/5 covered; two runtime timeouts despite captured reports |
| N | — | Not launched |
| U | — | Not launched |

The human subsequently confirmed **“D closed”**. Parent PID 32915 is absent (its plan server
runs in-process); the captured session has no approval/save event or call, and the driver's
plan-ref is absent. No browser-close callback was persisted, so this is recorded as human-
confirmed close plus process absence, not an observed DENY callback. The exact old working
`plan-draft.md` matched the preserved fixture and was then removed to abandon that scratch
draft; snapshots/handoff evidence remain. Receipt: `live/D/abandonment.json`.

The isolated driver was then advanced to **`2ed55c1b`** on `dogfood-2226-driver`, preserving only
the approved temporary skill-manifest changes. Normal `skills sync` refreshed the branch-bound
sources; all four review skills and both reviewer definitions compare byte-identical to the
checked-out sources. Pi settings remain byte-identical to the original bridge-on backup. Host
versions remain five-package Pi 0.85.1, pi-subagents 0.65.1, Ponytail 4.9.0 and plannotator 0.27.12.
`live/driver-repair-preflight.json` records source paths and hashes. A diff check confirms the
reviewer definitions, wave modules, terminal tool/door/prompt and package pins are unchanged
from T's exercised SHA. The implementation checkout and all global configuration were untouched
by the isolated driver advance.

The human subsequently ran `live/start-B2.sh` and invoked `/pr-review-browser 2228` once,
using fresh logs under `live/B2/parent` after the wrapper checked the repaired SHA and unchanged
scratch PR head. The original B launcher/evidence is preserved. Full teardown and submission
remain blocked on the remaining amended live results plus N/U.

### Leg B2 — PASS: repaired reconciliation and visible owner/contributors

Exercised code: `2ed55c1b6574ff69bdf64d9e6027162fcf0c75e3`, driver branch
`dogfood-2226-driver`, same host/package/bridge configuration as `driver-repair-preflight.json`.
Parent session `01a07443-9f4b-70e9-866c-fc31275d5e94`, model
`anthropic/claude-opus-4-8`, PID 91241. One workflow
`ccf915e2-bc98-4b62-a982-53777050f6a2`, with three separate fresh-context background children,
all `openai/gpt-6-astra` and observed runner exits 0:

| Lane | Child run | PID | Final streamed / findings |
| --- | --- | --- | --- |
| claimed-intent | `b437ef9e-fab6-4417-838e-87aadb307c88` | 92212 | true / 1 |
| quality | `3c0a12e3-95d9-45e1-9f96-43936dcc438e` | 92215 | true / 1 |
| ponytail | `4122247d-0b21-49b6-9f47-055f63bb4716` | 92216 | false / 0 |

The human reported an opened browser, no input/nudges after launch, one final annotation,
visible attribution, and no duplicates/missing annotations/errors. The inspected screenshot
`Screenshot 2026-09-05 at 9.12.43 PM.png` shows one **PERK:CLAIMED-INTENT** annotation at line 7
with the new merged-body prefix (“flagged independently by two lanes”) and an unsubmitted
Post Comments badge of 1. Copy: `live/B2/browser-final.png`, SHA-256
`997b1839bc22918100e025e4b57d6b418751576495d6f0b716dd236093840ae4`.
Its collapsed preview does not display the entire body; the parent push payload below records
the contributor labels. The human was unsure about visual timing; JSONL establishes order.

Decisive order (UTC, **2026-09-06**):

| Time | Event |
| --- | --- |
| 01:10:23.091 | Single start accepted all three requested/runnable lanes, no preflight failures. |
| 01:10:26.927 | Parent ends launch turn. |
| 01:10:53.939 | Native quality progress wakes idle parent; its child queue-ack result is persisted at 01:10:53.950 with `delivered: true`, request `45d8e21b-125b-41aa-b71a-96f36fa649ca`. |
| 01:10:54.474 | Claimed-intent nonempty batch receives queue-ack `delivered: true`, request `255dd085-dd9f-4f4b-95db-1329c9197cd9`. |
| 01:10:58.114 | Provisional quality push creates 1 annotation, id `38f30192-0f7a-452b-be0d-47649172d50f`; held=0. |
| 01:10:58.116 | Claimed-intent progress is delivered during the active relay turn. |
| 01:11:02.038 | Its provisional push skips the shared line-7 anchor; no duplicate created. |
| 01:11:02.865 | Workflow terminal status records completion, after both nonempty submissions and the provisional browser push. |
| 01:11:05.947 | Parent ends relay turn. |
| 01:11:05.949 | Matching native workflow-completion notice wakes it. |
| 01:11:07.852 | One collect succeeds: complete=true, 3/3 covered, failures=[], one attempt. |
| 01:11:23.690 | Final merged claimed-intent replacement is initially skipped against quality's existing anchor; its final candidate is retained by the tool. |
| 01:11:23.709 | Empty final quality replacement clears its 1 provisional annotation and promotes the retained claimed-intent final: pushed=1, id `9d224dcf-7294-4d85-91b7-f5d17c426fde`. |
| 01:11:23.726 | Empty final Ponytail replacement: pushed=0, deleted=0, held/held_batches=0. |
| 01:11:36.527 | Parent reports finalized reconciliation and ends turn. |

All lanes were covered, so uncovered-source clearing was vacuous on this live leg (the failure
branch remains offline-pinned). The parent explicitly assigned the shared anchor to the first
covered contributor, claimed-intent, and sent **disjoint** final arrays: one merged finding,
then empty quality/Ponytail arrays. Its merged body retained `[claimed-intent · major/high]`
and `[quality · major/high]` segments. The real promotion result reads:

```text
Annotations — perk:quality: cleared 1; perk:claimed-intent: pushed 1.
```

The screenshot's changed owner and merged-body prefix corroborate that replacement, not merely
a child-reported streaming flag. No held work remained. Ponytail received the normal neutral
no-provisional-batches/no-findings disclosure; its `fyi` stayed in-session. There was no polling,
manual status-file reconciliation, retry, duplicate collect, annotation HTTP composition or
late provisional replay. Read-only GitHub verification showed open draft PR #2228 with zero
reviews; no posting occurred. The human then confirmed **“B2 closed”**. At
2026-09-06T01:18:13.182Z the parent transcript records the browser closing without submitting;
no subsequent tool call is recorded. Parent PID 91241 is absent, including its in-process
browser server. Normal review cleanup returned `success: true, removed: true`, and the checkout
is absent on disk and from the driver's worktree list. PR #2228 remains draft/open with zero
reviews, retained for U.

Raw captures are under `live/B2/captured-runtime/`; `parent-timeline.json`, `evidence.json`,
`github-posting-check.json` and the screenshot retain the supporting artifacts. This is the
single owner-authorized B rerun, not an automatic retry; the original B evidence is unchanged.
Closure receipts are `live/B2/captured-runtime/parent-session-after-close.jsonl`,
`checkout-cleanup.json`, `worktrees-after-cleanup.txt`, and `github-after-cleanup.json`.

### D2 preparation — fresh draft verified; review not yet launched

The one-shot `live/start-D2.sh` is prepared for a fresh normal `perk plan --no-sync` handoff
at repair SHA `2ed55c1b`, using the same repaired Pi, agent home, reviewer definitions/model
policy and bridge-on configuration. It reuses the **exact original** D fixture and preparation
message (fixture hash checked by the launcher); no content is changed to force a passing report.
The launch preview passed without starting Pi or a review. The human is asked only to let
`plan_draft` register the supplied bytes and report **“D2 draft ready”**; handoff/artifact
verification precedes the same custom-lens review invocation. The original failed D run is
preserved, and another required-output failure would stop the flow rather than trigger a retry.

The human then launched D2 and reported **“D2 draft ready”**. Verified normal-plan handoff:
`01M1T4X0CT95HP6SCA3SF8S602`, consumed, read-only, stage plan, bound to parent session
`01a0744e-8351-733c-8bc0-d6127b60eca2` (model `anthropic/claude-opus-4-8`). At
2026-09-06T01:22:00.306Z `plan_draft` succeeded with 1790 bytes and the original fixture digest
`618fb3125dc66d716282365c02ab6f816384e1324fb19717b17de4fc9f580bb4`. Independent byte comparison
and receipt-digest verification passed; only `read` and `plan_draft` ran, with no review/save/
delegation attempt. Driver HEAD remains `2ed55c1b`. Captures: `live/D2/draft-verification.json`,
`preparation-handoff.json`, `verified-plan-draft.md`, and `parent-preparation.jsonl`.
The same custom-lens invocation is now handed to the human; any final custom attribution may
appear in an owning author label or in merged contributor text, not necessarily a separate card.

### D2 — NOT PASSED: runtime failure despite captured structured reports

Exercised SHA `2ed55c1b6574ff69bdf64d9e6027162fcf0c75e3`; normal plan handoff and original
fixture identity are verified above. Parent session `01a0744e-8351-733c-8bc0-d6127b60eca2`,
model `anthropic/claude-opus-4-8`, PID 637. One workflow
`038ec106-32ee-45b2-a855-30a07dbb7eea`; all five selected/automatic lanes were runnable and
launched as separate fresh-context background runners with unchanged `openai/gpt-5.6-sol`:

| Lane | Child run | PID | Final engine/collect result |
| --- | --- | --- | --- |
| grounding | `14c1575f-f024-4171-bb88-ccf932645506` | 5570 | covered; streamed=true, 3 findings |
| decision-completeness | `b067d3bc-22c9-4490-9622-50cdc8366e06` | 5571 | failed: Request timed out.; structured report captured |
| scope | `3786172e-8de4-4b41-a1cd-6dac981eb7e5` | 5572 | covered; streamed=false, 0 findings |
| custom | `cd326746-492e-46e6-aea1-4a0f1a8d2958` | 5575 | failed: Request timed out.; structured report captured |
| ponytail | `4c0fc2e5-b387-4b05-8803-6c13dc17f000` | 5576 | covered; streamed=true, 1 finding |

All runner processes have observed exits 0; that does not override the failed step statuses.
Ponytail used the exact `ponytail` skill. **Unlike original D**, both failing children called
`structured_output` successfully: decision-completeness at 01:30:20.215Z and custom at
01:30:20.265Z, each returning “Structured output captured.” Their output files exist and were
preserved, but are **not** accepted as coverage or manually recovered into the aggregate:

| Failed lane | Capture content | SHA-256 of capture |
| --- | --- | --- |
| decision-completeness | angle=decision-completeness, streamed=true, 1 finding | `90886adba96550490a74c64ac88001828e0e1d1c07db99dfeb502f3b8f748267` |
| custom | angle=custom, streamed=true, 3 findings | `1e8b477d23e2ec992c212e9d2075077f2793514c14172feca18fae9299d0c914` |

This is evidence of successful report capture alongside a failed runtime outcome, not a missing
completion-tool assumption. The later trace below identifies stale-error accounting after
successful native retry; the original network timeout's cause remains unknown. The collect
itself settled promptly; no collect-grace expiry or replacement wave occurred.

Decisive order (UTC, 2026-09-06):

| Time | Event |
| --- | --- |
| 01:29:26.491 | Single start accepted all five lanes, no preflight failures. |
| 01:29:29.654 | Parent ends launch turn. |
| 01:30:08.349 | Decision-completeness nonempty supervisor batch successfully queued; native wake at 01:30:08.363. |
| 01:30:12.181 | First provisional browser push creates one decision-completeness annotation. |
| 01:30:15.235 | Custom's nonempty batch is successfully queued; delivered into the active parent turn at 01:30:19.170. |
| 01:30:19.158 | Grounding push creates two annotations, skipping the shared retry-policy phrase. |
| 01:30:20.215 / .265 | Both subsequently failed lanes receive successful structured-output capture results. |
| 01:30:20.786 / .802 | Their terminal step records are failed with `Request timed out.` |
| 01:30:27.013 | Custom provisional push skips all three already-owned phrases. |
| 01:30:30.309 | Ponytail provisional push adds one annotation. |
| 01:30:32.744 | Parent ends relay turn. |
| 01:30:33.836 | Workflow terminal status records completion. |
| 01:30:34.075 | Matching native completion notice wakes the parent. |
| 01:30:36.756 | Single collect: complete=false, covered grounding/scope/ponytail, two lane-failed rows, one attempt. |
| 01:30:59.758 | Empty `replace:true` for uncovered decision-completeness clears its one provisional annotation. |
| 01:30:59.795 | Empty replacement for uncovered custom clears zero (its provisional findings had all deduped). |
| 01:30:59.815 | Grounding final replacement clears 2 and pushes its 3 authoritative findings. |
| 01:30:59.832 | Empty scope final replacement, no effects. |
| 01:30:59.856 | Ponytail final replacement clears 1 and pushes 1. All held counts remain zero. |
| 01:31:13.869 | Parent explicitly reports INCOMPLETE 3/5 and stops; no retry. |

The **browser repair is observed working**, but the **live leg is not passed**. The failed
source owning the retry-policy phrase was removed before covered final replacement; the final
screen contains only three grounding findings and one Ponytail finding, not failed-lane
provisional content. Scope received neutral no-provisional-batches/no-findings disclosure.
No partial-report recovery, polling, annotation HTTP composition or extra wave was used.

Human observations: browser opened, annotations appeared before final summary, no subsequent
Pi input/nudges, four final annotations, visible attribution, no duplicate/missing-annotation
complaint, and INCOMPLETE 3/5 coverage. The inspected screenshot
`Screenshot 2026-09-05 at 9.31.34 PM.png` visibly labels the final owners **perk:grounding** and
**perk:ponytail**. It does not show a final custom contribution; custom is correctly uncovered.
Copy `live/D2/browser-final.png`, SHA-256
`c3ee40410038b206beb589892708cf1e1e81f59e28207464674d929871ab3601`.

The browser offered **“Draft Recovered — Found 5 annotations from 3 hours ago”** at open. The
operator asked which option to choose and was told **No**, to avoid restoring original D's
annotations. The owner subsequently explicitly confirmed **declining restoration**; old annotations were
not restored. This recovery prompt is a separate freshness observation, not the explanation
for the engine's timeout statuses.

Captured parent/child JSONL, workflow/child status, recovery descriptors, runner logs and failed
capture files are under `live/D2/captured-runtime/`. `evidence.json`, `parent-timeline.json` and
`post-capture-failures.json` index the decisive facts. Implementation tree was clean before this
evidence-only update; driver remains at `2ed55c1b` with only approved manifest changes. Pi/browser
remain open for capture; no approval/save or full teardown is claimed. N/U were not launched.
Further diagnosis, capability/model changes or live attempts require a new explicit owner
decision; this record does not convert repeated failures into a passing result.

### D2 timeout diagnosis — recovered error remains latched upstream

The owner authorized a **read-only** timeout trace, not another live run or a settings/code
change. The complete event streams explain the misleading final timeout statuses:

| Event | decision-completeness | custom |
| --- | --- | --- |
| Earlier assistant error: Request timed out. | 01:30:00.714Z | 01:30:01.686Z |
| Native `auto_retry_end`, success=true | 01:30:08.292Z | 01:30:06.712Z |
| Successful structured-output capture | 01:30:20.215Z | 01:30:20.265Z |
| `agent_settled` | 01:30:20.239Z | 01:30:20.276Z |
| Final failed step status repeats old timeout | 01:30:20.786Z | 01:30:20.802Z |

These are upstream Pi **model-request retries within the same child**, not another perk wave
attempt or a retry policy introduced by this implementation. The session JSONL contains the
earlier error; `events.jsonl` additionally records successful recovery. Inspecting only final
messages was insufficient to distinguish a new timeout from a retained historical error.

The installed pi-subagents 0.65.1 source matches the driver's source byte-for-byte.
`src/runs/background/run-child-session.ts` assigns `assistantError` from an assistant
`message_end.errorMessage`. It does not clear the latch on successful `auto_retry_end`; its
clear branch requires a clean **nonempty plain-text terminal stop**. A report-only child ends
through a structured-output tool-use message/result, so that branch never runs. `settle`
folds `error ?? assistantError` into exitCode 1. `subagent-runner.ts` in turn requires
`run.exitCode === 0 && !run.error` before validating/reading the captured report, so the stale
error blocks the ordinary successful-report path.

An offline replay into the **unmodified installed `runChildSession`** reproduced this for both
recorded event sequences. The factory was a stub that emits captured events and resolves—no
model request, child process, real session, upstream patch or live wave:

| Replay | Result for both children |
| --- | --- |
| Recorded sequence unchanged | exitCode=1, error=Request timed out., structuredOutputToolInvoked=true, timedOut=false |
| Control omitting the historical assistant-error message_end | exitCode=0, error=null, structuredOutputToolInvoked=true |
| Control adding a clean nonempty plain-text final stop | exitCode=0, error=null, structuredOutputToolInvoked=true |

The controls are diagnostic counterfactuals, **not recommended live workarounds**. In particular,
reviewers must not append prose after their required final tool solely to clear stale engine
state, and perk must not salvage capture files from failed runs. The initial transient network
error's cause is not established; the reproduced bug is its persistence after successful native
recovery. This does not explain original D's separate missing-tool-call failure.

Inspected source SHA-256:
`86f302832a21afdb0e79446d20d58be242d23c09f3d425bf4db254a09c10c940`.
Artifacts: `live/D2/retry-event-trace.json`, `replay-stale-assistant-error.mjs`, and
`stale-assistant-error-replay.json`. A sanitized, **not-posted** upstream bug-report draft is
`live/D2/upstream-timeout-report.md`, targeting the installed package's declared repository
`nicobailon/pi-subagents`. Suggested upstream repair: reconcile recoverable assistant-error
state on confirmed retry success without clearing hard run/stop/timeout errors, with tests for
structured-output completion, failed retry and real termination errors. No production source,
capability/model setting, dependency version, or live-attempt count changed during this trace.
D2 remains not passed; N/U and submission remain blocked pending owner disposition.
