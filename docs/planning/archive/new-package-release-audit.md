# New package release audit

Audit date: **September 10, 2026**. Perk snapshot:
[`f8d6cb38f332fd8e4838a0e71fbd9fee2341f493`][p-snapshot].
This is a maintainer assessment of the latest release of each package, with proposed
follow-ups. It changes no integration code or compatibility certification.

**No mandatory integration API migration or safe defensive-code removal was identified.**
pi-subagents introduces conditional launch failures and additional parent wakes that deserve
compatibility testing. Its new per-delegation messaging policy offers one concrete improvement
for perk's conflict resolver. Plannotator's headline explicit-base behavior needs an upstream
event-API addition before perk can adopt it fully.

| Question | pi-subagents 0.67.0 | @plannotator/pi-extension 0.27.13 |
|---|---|---|
| Breaking changes affecting perk? | No required RPC/delegation migration found. Restricted host tools, undersized spawn budgets, and incremental notifications change behavior. | Core event contracts remain unchanged. Linked-document reads become stricter; command flag parsing changes outside perk's launch path. |
| Useful functionality requiring perk code? | Per-launch `intercomBridge` override for the foreground conflict resolver. | No immediately usable new public-event capability identified. |
| Workarounds now removable? | None confirmed. | None confirmed. |
| Worth investigating? | Progress/diagnostics, evidence auditing, watchdogs, inspection, standalone execution. | Strict explicit-base opening through the event API. |

## Scope and evidence

| Package | Installed comparison baseline | Audited release | Release tag commit | GitHub publication, UTC |
|---|---|---|---|---|
| `pi-subagents` | 0.66.0 | [0.67.0][s-release] | [`aa75b335`][s-tree] | 2026-09-10 04:40:35 |
| `@plannotator/pi-extension` | 0.27.12 | [0.27.13][a-release] | [`6d463954`][a-tree] | 2026-09-10 04:47:59 |

Both versions were confirmed as npm's `latest` during this audit. Research covered release
notes, commit/file comparisons, published npm contents, current perk integration code, and
focused verification. GitHub reads used `gh`; npm artifacts were inspected in memory without
installing them. The working installation remained at the comparison baselines above.

The [pi-subagents comparison][s-compare] contains 65 commits and 210 changed files. The
[Plannotator comparison][a-compare] contains 14 commits and 100 changed files, but GitHub
reports its tags as diverged. Published-package differences therefore take precedence over
assuming every commit in that comparison is newly shipped: the installed 0.27.12 review bundle
already contains token-hover trigger/delay settings and introduction markers. Do not reclassify
those as new 0.27.13 opportunities solely from the tag comparison.

[Pi settings][p-settings] select both packages **without version pins** and set
`subagents.disableBuiltins: true`. Perk's [Pi development dependencies][p-package] are pinned
to 0.85.1. The [doctor compatibility stamp][p-doctor] is still **0.65.1**, distinct from both
the installed version and this audit's comparison baseline. Doctor warns on a version mismatch;
this audit does not satisfy the full [re-verification procedure][p-reverify] or authorize a
stamp bump.

The September 5 assessments of [pi-subagents][p-old-sub] and [Plannotator][p-old-plan] are
historical context. Their proposed work must be checked against current code: several changes
have since landed, including Plannotator approval-note preservation and subscription ordering.

### Current integration boundaries

| Perk surface | Contract used today | Why it matters to this release |
|---|---|---|
| Report waves | [RPC adapter][p-rpc] uses v1 request/reply events and the advertised async-completion channel. [ReportWave][p-wave] renders config-object `runs.all(...)`, with stable keys, `worktree: false`, and a constant read-only restriction packet. | No direct package imports, launch-digest comparisons, or new incremental-message parsing. Root completion and validated aggregates remain authoritative. |
| Report completion | [Transport][p-transport] fixes async/fresh/mission-disabled execution, a deadline, structured output, and acceptance level `none`. [Report roles][p-reviewer] disable the separate completion guard. | Engine heuristic fixes do not replace this explicit completion policy. |
| Foreground conflict resolution | [Conflict resolver engine][p-resolver] uses structured delegation events, a typed canonical `cwd`, structured results, and cancellation/termination observation under a worktree lock. | It currently sends no per-launch bridge override and owns no supervisor question-answer loop. |
| Plan and code review | [Plan adapter][p-plan] uses a pending review handshake plus a decision event. [Code-review handoff][p-handoff] uses the callback-based event API; local review already passes `diffType` and `defaultBranch`. | New command arguments do not automatically become event options. |
| Browser readiness and annotations | [Handoff][p-handoff] reserves a port, captures launch console output, and probes the appropriate readiness route. [Annotations][p-annotations] uses source-scoped `/api/external-annotations` delivery with retries and deduplication. | Neither contract is replaced by document-endpoint or CLI changes. |

## pi-subagents 0.67.0

### 1. Breaking changes and compatibility risks

**No mandatory public API migration found.** The [v1 RPC implementation][s-rpc] retains the
request/reply and completion mechanics perk consumes; its direct delta adds `quiet` handling
for schedule management. The [delegation request type][s-delegation] gains an optional field.
This is source-level compatibility evidence, not a live execution certification.

| Change and evidence | Impact on current perk | Confidence and action |
|---|---|---|
| [Host-tool census and launch validation][s-tools] intersect declared tools with available host built-ins. Reviewer/scout names fail before launch if a requested, still-permitted repository tool is missing. Other names receive warnings and a pruned tool list. | Affects `perk.pr-reviewer`, `perk.draft-reviewer`, `perk.adversarial-reviewer`, and `perk.scout`. Analysts/classifiers do not receive the same name-based refusal. Explicitly excluded or capability-restricted tools are not a minimum-tool requirement. A complete host census preserves perk's five declared report tools. | **Verified with pure helpers.** Exercise restricted hosts and check that unavailable lanes become infrastructure failures, without treating incomplete inspection as a completed review. |
| [Static workflow validation][s-workflow] rejects known child counts above `maxSubagentSpawnsPerRun` before launching any children. | Perk's literal `runs.all` items are countable. A deliberately small limit can now produce an immediate spawn failure instead of allowing partial work first. The default limit remains 64; dynamically determined launches remain runtime-limited. | **Verified with perk-rendered script.** A three-lane wave passes at three and fails at two; the previous validator accepted the same script/options. Validate error presentation and completeness policy under the new failure timing. |
| [Per-child completion notifications][s-executor] send `subagent-incremental-child-notify` messages and record `subagent.workflow.child_settled`. Ordinary workflow notifications trigger a parent turn, including successful children whose messages have `display: false`. | Report waves can wake the parent before siblings finish. Perk's [review-wave guidance][p-review-tools] and [draft-review guidance][p-draft-tools] already require matching **workflow** completion before collection. Extra wakes can still add cost and scheduling noise. | **Source-supported; live ordering untested.** Keep collection authority unchanged. Do not parse notification prose or follow output references to bypass ReportWave. |
| [Launch contracts][s-launch] move to version 3 and launch-binding projections to version 2. [Preflight][s-preflight] now includes bridge and project refinements consistently. | Digests change, but perk currently compares none of them. Existing saved runs remain resumable according to the release. | **No current migration.** Any future digest integration must name the schema/version and compare equivalent launch inputs. |
| [Parallel worktree admission][s-worktree] validates repository identity and cleanliness before spawning isolated children. | Report lanes explicitly use `worktree: false`. The conflict resolver needs its existing canonical worktree, and delegation still supplies no per-request worktree override. | **No identified direct break in current policy.** Retain perk's rejection of incompatible global worktree defaults. The new check does not replace that guard. |

The signed-thinking recovery fix requires Pi 0.85.0 or newer. Perk's declared Pi baseline is
0.85.1 and its report/delegation paths use fresh context, so this is not a new requirement for
those paths. It should not be generalized into certification of arbitrary host installations.
[Release compatibility notes][s-release], [fork-context change][s-fork].

### 2. Useful functionality requiring perk code

**Recommend a bounded conflict-resolver follow-up: explicitly disable the bridge for that
delegation.** Version 0.67.0 accepts `intercomBridge: { mode: "off" }` on a structured
delegation request, replacing the global bridge configuration for that launch.
[Public request type][s-delegation], [request validation][s-delegation-parser],
[documented semantics][s-api].

This fits perk's existing resolver protocol. The [agent instructions][p-resolver-agent] require
structured blocker outcomes for ambiguity or unresolvable conflicts; the [parent engine][p-resolver]
awaits a terminal result while protecting the worktree. The upstream [default bridge prompt][s-bridge]
instead directs a child needing a decision to contact its supervisor and remain alive for a
reply. Perk has no code-owned question responder for this operation. Selecting `off` removes
that competing injected instruction/tool policy without changing messaging for report waves.

The API availability is **verified**: the published 0.67.0 parser accepts and forwards the
override as a foreground delegation, while installed 0.66.0 rejects it with
`Unsupported delegation field: intercomBridge.` The benefit to resolver reliability is an
**inference from the two protocols**; no live deadlock was reproduced. A follow-up must address
the 0.67.0 minimum before emitting this field to older installations, then verify structured
blockers, cancellation, and lock disposition. It must not change the global bridge setting.

### 3. Bug fixes that permit defensive-code removal

**None confirmed in this release.** Related fixes are useful, but they do not establish that
perk's current guards have become redundant.

| Existing policy or defense | Why it stays |
|---|---|
| `completionGuard: false` on report roles; acceptance level `none` in [transport][p-transport] | [Task-intent fixes][s-intent] narrow false positives involving read-only language, quoted implementation requests, and filenames. [Completion checks][s-completion] and [acceptance inference][s-acceptance] still exist, and `bash` remains mutation-capable. A report lane should complete on valid `structured_output`, independent of those heuristics. |
| Config-object `runs.all` in [ReportWave][p-wave] | The [new promise-composition support][s-workflow] explicitly preserves reasons to use config objects: batch validation, grouping, and `collectFailure`. Rewriting the renderer would surrender useful semantics without improving perk's contract. |
| Cancellation deadlines, termination observation, and [resolver locks][p-resolver] | Upstream now [proves detached descendants have stopped before reporting cleanup complete][s-process]. A persisted result still does not prove process termination, so uncertainty must not authorize unlocking a worktree. |
| [Native child execution policy][p-child-policy] and [restriction decoding][p-child-restrictions] | Moving the [child prompt filter before ambient extension inspection][s-child-session] preserves upstream context exclusions. It does not replace perk's read-only floor, child scratch suppression, or exclusion of parent authoring context. |
| Existing workflow completion authority | Incremental notices and steering/drain fixes do not authorize early collection. The earlier held-turn wait workaround has already been retired; there is no new deletion to attribute to 0.67.0. |

The built-in tool-wrapper fix also does not replace perk's [bash scan timeout hook][p-bash-timeout]:
perk injects a timeout through a tool-call hook rather than re-registering the built-in tool.

### 4. Features requiring more investigation

| Opportunity | Why it is interesting for perk | Investigation needed before adoption |
|---|---|---|
| Structured incremental progress | Earlier lane status could improve long [report-wave][p-wave] visibility. [Upstream notification implementation][s-executor]. | Establish a supported structured event surface and owned UI behavior; measure additional wakes. The internal callback/durable event is not a new typed RPC aggregate. Preserve final collection authority and [surface ownership][p-surfaces]. |
| Preflight and host-tool diagnostics | [Corrected preflight][s-preflight] can explain effective tools, bridge policy, and launch identity; [tool diagnostics][s-tools] reveal pruning in roles not covered by reviewer/scout refusal. | Determine how the already-loaded engine can expose these through a supported seam. Perk's [bare-import guard][p-import-guard] prevents solving this by importing another package instance. Validate equivalence across preflight, foreground, and async execution. |
| [Built-in evidence-auditor][s-evidence] | Source-backed claim checking could strengthen scout/research results. | Built-ins are disabled in [perk's settings][p-settings]. Adapt a deliberate role, available web tools, and report schema; do not enable the entire built-in agent set to obtain this role. |
| [Watchdog fallback and clarification][s-watchdog] | Bounded fallback can improve watchdog availability; optional questions can flag task drift. | Decide who owns watchdog configuration and interaction with perk gates. Fallback is for provider failure **before any tool work**, shares the existing deadline, and is not a general child retry mechanism. Questions are not approval. |
| [Portable Inspect actions][s-api] | A human could inspect an existing wave without inventing a perk dashboard. | Establish public action routing and surface ownership. Ghostty support is open-only on macOS with Ghostty 1.3+; unsupported lifecycle actions must remain explicit. Inspecting or closing an inspector does not transfer execution authority. |
| [Standalone background execution][s-standalone] | Potentially useful for future Linux worker packaging. | Upstream's supported target is the official Pi 0.85.1 **Linux x64** binary with adjacent assets. Other platforms/packagers remain unverified; this does not justify deleting Node/Pi dependencies or claiming macOS support. |

### Inherited fixes and changes with no current integration action

These are benefits or bounded no-action findings, not recommendations to recreate upstream
mechanisms in perk:

| Release area | Disposition |
|---|---|
| Steering consumption, queued follow-ups, resumed shutdown timers, paused completion checks, and detached descendant lifecycle | Inherited reliability improvements. Retain perk's deadline, receipt, and cancellation checks. [Steering][s-steering], [child session runner][s-run-child], [background runner][s-runner], [process cleanup][s-process]. |
| Wrapped built-ins, context-filter order, system-prompt shape preservation, and shorter child-facing instructions | Inherited engine fixes. No equivalent perk compatibility shim was found to remove. [Tool planning][s-tools], [child session][s-child-session], [prompt shape handling][s-prompt-shape], [tool instructions][s-tool-description]. |
| Pi package-root/TUI alias handling, `fast` recovery, OpenRouter fallback detection, and OpenCode session headers | Inherited compatibility improvements; these are not new perk APIs. [Runtime aliases][s-aliases], [model fallback][s-fallback], [provider headers][s-headers], [release ledger][s-release]. |
| Fleet identity colors, grouping/timers/usage, themes, transcript previews, model selectors, Orca handle parsing, and review prompt scoping | Native UI/prompt improvements; no perk change identified. [Release ledger][s-release]. |
| Quiet recurring schedules, manual scheduling timing, and old-session schedule deletion | No current perk scheduler integration. Quiet automatic successes suppress parent turns; do not repurpose scheduling metadata merely to silence ordinary report-wave notifications. [Schedule implementation][s-schedules], [notification policy][s-notify]. |
| Windows Worktrunk invocation and nested coordinators answering their own children | No corresponding current perk path: report roles do not fan out, and the resolver forbids child delegation. [Worktree support][s-worktree], [supervisor ownership][s-supervisor], [resolver role][p-resolver-agent]. |
| Remote SSH project/text-tool and Orca auto-close experiments visible in intermediate commits | Reverted before the final release; exclude them from shipped opportunities. [Release comparison][s-compare]. |

## @plannotator/pi-extension 0.27.13

### 1. Breaking changes and compatibility risks

**No direct break found in the event contracts perk consumes.** The published
`plannotator-events.ts` and `server/external-annotations.ts` are byte-identical to their
installed 0.27.12 counterparts. Plan handshake/decision delivery, code-review callback fields,
and source-scoped external annotation transport retain their existing shapes.
[Event implementation][a-events], [annotation endpoint][a-annotations], [perk adapters][p-handoff].

| Change | Impact and recommended treatment |
|---|---|
| [Strict review argument parsing][a-args] rejects unknown dash-prefixed flags. Pi/OpenCode slash commands also reject CLI-only flags such as `--tailscale` that were previously ignored. | Perk emits events instead of invoking the CLI/slash parser, so no core bridge migration is needed. Humans using native commands may see newly explicit usage errors. Parsing behavior was checked with published helpers. |
| [Document resolution][a-doc] requires both lexical and realpath containment for `/api/doc`. Symlinks escaping the project return 403, including escapes through ancestors of missing leaves. | Linked documents outside the reviewed project can stop opening. This is intentional containment, not a defect to work around. Internal symlinks and symlinked project roots remain supported. |
| HTML above the 2 MB cap consistently returns 413; an existing unreadable document returns 500 rather than 404. | Record these as conditional document-viewing changes. Perk's inline plan/event payloads and `/api/external-annotations` do not depend on the old behavior. [Shared resolution][a-doc], [Pi Node endpoint][a-reference], [Bun review server][a-bun-review]. |

Document-endpoint behavior was established from source and upstream tests, not a live local
browser run. Perk's unrelated prose-workbench file-containment controls remain necessary; an
upstream endpoint fix does not protect a different server.

### 2. Useful functionality requiring perk code

**No immediately usable new public-event capability identified.** Native review commands can
now request a base and one of nine opening diff modes, reject missing refs clearly, and retain
the requested opening state without writing saved defaults. This is useful for stacks, but
perk already passes `defaultBranch` and `diffType: "since-base"` for local/combined-stack
review. [New open-state resolver][a-open-state], [current handoff][p-handoff].

The difference is strict validation and protection against startup view changes. Those semantics
are gated by the new internal `openStateFromFlags` option in the [Pi browser launcher][a-browser].
The [unchanged event handler][a-events] forwards an explicit field set that excludes that option.
Adding an extra field to perk's event payload alone would therefore not activate the feature.
The API gap belongs in further investigation below, not a claim that this upgrade fixes perk's
stack-review opening behavior automatically.

### 3. Bug fixes that permit defensive-code removal

**None confirmed in this release.**

| Existing behavior or proposed cleanup | Audit result |
|---|---|
| Port reservation, `PLANNOTATOR_PORT` restoration, flavor-specific readiness probes, and [console capture][p-console] | Retain. The new event contract supplies no replacement session URL/ready lifecycle that removes these requirements. [Current handoff][p-handoff], [event implementation][a-events]. |
| Direct Edits feedback parsing and request cancellation handling | Retain. The release does not add a structured replacement for plan edit extraction or an event-based server-stop contract. [Plan adapter][p-plan], [event implementation][a-events]. |
| Annotation readiness queue, retry bounds, and deduplication | Retain. The endpoint is unchanged; `/api/doc` fixes concern a separate route. [Perk annotations][p-annotations], [upstream annotations][a-annotations]. |
| Canonical stack base and materialized remote ref | Retain. Perk's [review checkout][p-checkout] fetches the base and pins member heads; [handoff][p-handoff] passes `origin/<stack base>`. Command-only explicit-base handling does not replace those snapshot responsibilities or change event-launch behavior. |
| Workarounds for cached `PLANNOTATOR_DATA_DIR` | No matching workaround found in perk. Upstream [storage now resolves its directory per call][a-storage], so this fix is inherited without a deletion. |
| Approval-note preservation and plan subscription ordering | Already fixed in current perk: `approvalGuidanceSuffix` preserves notes for ordinary and stack decisions, and the plan adapter subscribes before emitting its request. Do not attribute these local fixes to 0.27.13. [Handoff][p-handoff], [plan adapter][p-plan], [historical assessment][p-old-plan]. |

### 4. Features requiring more investigation

**Prioritize event parity for explicit review opening state.** Request or investigate an
upstream public event option that carries the same strict opening intent as the new command
flags. A future perk integration could then preserve an explicitly requested base/diff view
through initial rendering and fail clearly on unresolved refs. [Browser option and forwarding][a-browser],
[event payload boundary][a-events], [server explicit-base/pinning behavior][a-server].

The integration must preserve the distinction between setting the opening view and preventing
the reviewer from changing it: the new flags do only the former. It should also preserve
PR-derived bases, distinguish Git from unsupported provider/workspace combinations, and avoid
changing saved defaults. Do not import browser internals or replace perk's event adapter with
a CLI subprocess simply to obtain flag behavior. Current source establishes the gap; UI timing
and the best public API shape remain investigation work.

### Inherited fixes and changes with no current integration action

| Release area | Disposition |
|---|---|
| Data-directory lookup and upstream test isolation | Per-call storage resolution is inherited. Upstream's test sandbox prevents its own suite from touching normal user data; it is not a new perk integration mechanism. [Storage][a-storage], [upstream fix][a-storage-pr]. |
| Live base label in the diff dropdown | Useful automatically in existing stack review: the label follows the selected base. No perk code required. [Review UI][a-review-ui]. |
| Mobile selection toolbar containment | Inherited browser UX fix. No perk code required. [Upstream fix][a-mobile-pr]. |
| Amp decision routing through CLI `review --json` | No current perk action. Perk already consumes structured callback decisions; it does not use Amp's prose classifier. [Upstream fix][a-amp-pr], [perk handoff][p-handoff]. |
| Token-hover configuration/introduction seen in the tag comparison | Already detectable in the installed 0.27.12 bundle. Excluded from new-release recommendations rather than inferred from commit titles. |

## Prioritized follow-ups

These are proposed work items, not implemented changes. No upstream issue or message was sent
as part of this audit.

| Priority | Follow-up | Acceptance evidence needed |
|---|---|---|
| Before advancing compatibility evidence | Validate 0.67.0 with perk's real report and foreground-delegation paths. | Full and restricted host tool menus; reviewer/scout refusal versus analyst pruning; a wave below/at/above the spawn budget; valid and missing/invalid structured output; child notices before the final workflow notice; timeout/cancellation with correct receipt and lock handling. Complete the existing re-verification procedure before changing its stamp. |
| Next bounded code proposal | Set the conflict resolver's per-launch bridge policy to `off`, with an explicit 0.67.0 availability strategy. | Prove the old-version rejection is handled without an unsafe retry, verify ordinary completion and structured blockers in both resolver modes, and preserve timeout/termination lock behavior. Other launches retain their current messaging policy. |
| Next upstream/API investigation | Expose strict explicit-base review opening through the event API. | Open a stacked layer and combined stack against the intended base; exercise missing refs, startup preferences/automatic view changes, and base-only/diff-only combinations; preserve PR review semantics, reviewer changes, and saved defaults. |
| Next diagnostics investigation | Make host-tool pruning and incremental progress useful through supported seams. | Show incomplete inspection as an infrastructure limitation; measure wake count; route display through perk surfaces; prove that progress cannot authorize early collection or replace validated reports. |
| Conditional browser smoke | Validate linked-document behavior where the review uses filesystem links. | Internal link and symlinked-root success; external-target and symlink-ancestor 403; HTML-over-cap 413; unreadable existing file 500; ordinary plan/code decisions and external annotations still work. |
| Later, separate experiments | Evidence-auditor role, watchdog policy, Inspect integration, Linux standalone packaging. | Each experiment names its owner, bounded benefit, supported runtime/tools, and interaction with existing perk authority. None is a prerequisite for documenting these releases. |

## Verification record and limits

The following existing tests ran during information gathering, at the perk snapshot above:

```sh
node --test --test-reporter=spec \
  extension/waves/rpcAdapter.test.ts \
  extension/waves/reportWaveRpc.test.ts \
  extension/pi/v1/delivery/conflictResolverEngine.test.ts \
  extension/pi/v1/providers/plannotator.test.ts \
  extension/pi/v1/providers/plannotatorHandoff.test.ts
```

**Result: 140 passed, 0 failed, 0 cancelled, 0 skipped; approximately 22.8 seconds.** These
exercise perk with simulated upstream responses. They do not load and certify the new engine
or prove browser behavior.

Five additional isolated checks evaluated published TypeScript helpers in memory, using
TypeScript transpilation and module-URL adaptation to resolve dependencies. They wrote no
package files and launched no model children or browser sessions:

| Probe | Result |
|---|---|
| Complete host census | All five canonical report tools remained available, with no warnings. |
| Missing `grep` | All three reviewer roles and `perk.scout` refused launch; `perk.learn-analyst` and `perk.review-classifier` continued with pruning warnings. |
| Delegation override | 0.67.0 accepted/forwarded `{ mode: "off" }` with foreground execution; 0.66.0 rejected the field. |
| Actual perk-rendered three-lane workflow | 0.67.0 validation passed at budget three and rejected budget two; the prior validator accepted the same input. Captured spawn parameters retained async/fresh/mission-disabled execution and acceptance `none`. |
| Plannotator arguments/open-state helpers | Valid base/merge-base input resolved; a mistyped flag, Pi-inapplicable transport flag, missing base, and PR-inapplicable base option produced errors. |

**All five passed.** These are exploratory helper checks, not a new committed regression
suite. Upstream tests were inspected as source but not run locally. Full CI, real SDK child
execution, live browser interaction, and the follow-up smoke scenarios above were not performed.

For artifact identity, the downloaded tarballs matched npm's published SHA-512 integrity:

| Artifact | Integrity |
|---|---|
| [pi-subagents 0.67.0 tarball][s-tarball] | `sha512-43FGBi82sbxEGhEfsaj0P7I/rRJfsw1UPuFSVSkjZw0Fy92lrBIB9d3gDTpwmK5hLj3ZzZUnvtlqiKQatySCTw==` |
| [@plannotator/pi-extension 0.27.13 tarball][a-tarball] | `sha512-qgSEoUuLYl7d+5MJLfnYfWjvbZUHjCfOJlUJVRwABp9NI4PtsH+ps08D17aB1R7qN4PS9nYoVFptw91LQ3ufVQ==` |

The pi-subagents npm `gitHead` matches its release tag. Plannotator's npm metadata has no
`gitHead`; its shipped files were compared directly with the installed baseline. The unchanged
Plannotator event and annotation files have Git blob hashes
`3e3012b9a6882a00672b95b23b34b36736524242` and
`ef0eccdb8e1e8eefd68bc2766638f1b22e395ab7`, respectively.

[p-snapshot]: https://github.com/mattgiles/perk/tree/f8d6cb38f332fd8e4838a0e71fbd9fee2341f493
[p-settings]: ../../.pi/settings.json
[p-package]: ../../package.json
[p-doctor]: ../../src/perk/convergence/doctor/checks.py#L727
[p-reverify]: ../developers/pi-subagents-reverify.md
[p-old-sub]: ./pi-subagents-assessment-2026-09-05.md
[p-old-plan]: ./plannotator-assessment-2026-09-05.md
[p-rpc]: ../../extension/waves/rpcAdapter.ts
[p-wave]: ../../extension/waves/reportWave.ts
[p-transport]: ../../extension/waves/transport.ts#L117
[p-reviewer]: ../../agents/pr-reviewer.md
[p-resolver]: ../../extension/pi/v1/delivery/conflictResolverEngine.ts
[p-resolver-agent]: ../../agents/conflict-resolver.md
[p-plan]: ../../extension/pi/v1/providers/plannotator.ts
[p-handoff]: ../../extension/pi/v1/providers/plannotatorHandoff.ts
[p-annotations]: ../../extension/pi/v1/providers/annotations.ts
[p-child-policy]: ../design/pi-subagents-child-execution-policy.md
[p-child-restrictions]: ../../extension/substrate/childRestrictions.ts
[p-review-tools]: ../../extension/pi/v1/codeReview/reviewWave.ts#L328
[p-draft-tools]: ../../extension/pi/v1/draftReviewWaveTools.ts#L300
[p-bash-timeout]: ../../extension/pi/v1/bashScanTimeout.ts
[p-surfaces]: ../design/tui-charter.md
[p-import-guard]: ../../extension/bareImportGuard.test.ts
[p-console]: ../../extension/substrate/consoleCapture.ts
[p-checkout]: ../../src/perk/cli/commands/pr/review/checkout_cmd.py
[s-release]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.67.0
[s-tree]: https://github.com/nicobailon/pi-subagents/tree/aa75b3353836f7868898e3bd58234d21eaff1463
[s-compare]: https://github.com/nicobailon/pi-subagents/compare/v0.66.0...v0.67.0
[s-rpc]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/extension/rpc.ts
[s-delegation]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/api/delegation.ts
[s-delegation-parser]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/slash/delegation-request.ts
[s-api]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/docs/extension-api.md
[s-tools]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/child-tool-plan.ts
[s-workflow]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/workflows/scripted-workflow.ts
[s-executor]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/foreground/subagent-executor.ts
[s-launch]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/shared/launch-contract.ts
[s-preflight]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/api/preflight.ts
[s-worktree]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/worktree.ts
[s-fork]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/shared/fork-context.ts
[s-bridge]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/intercom/intercom-bridge.ts
[s-intent]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/task-intent.ts
[s-completion]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/completion-guard.ts
[s-acceptance]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/acceptance.ts
[s-process]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/owned-process-tree.ts
[s-child-session]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/child-session.ts
[s-evidence]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/agents/evidence-auditor.md
[s-watchdog]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/docs/watchdog.md
[s-standalone]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/docs/standalone-background.md
[s-steering]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/steering.ts
[s-run-child]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/run-child-session.ts
[s-runner]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/subagent-runner.ts
[s-prompt-shape]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/agents/advertised-agent-prompt.ts
[s-tool-description]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/extension/tool-description.ts
[s-aliases]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/runner-aliases.ts
[s-fallback]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/shared/model-fallback.ts
[s-headers]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/shared/opencode-session-headers.ts
[s-schedules]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/scheduled-runs.ts
[s-notify]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/runs/background/notify.ts
[s-supervisor]: https://github.com/nicobailon/pi-subagents/blob/v0.67.0/src/intercom/native-supervisor-channel.ts
[s-tarball]: https://registry.npmjs.org/pi-subagents/-/pi-subagents-0.67.0.tgz
[a-release]: https://github.com/backnotprop/plannotator/releases/tag/v0.27.13
[a-tree]: https://github.com/backnotprop/plannotator/tree/6d4639545483f650c23c92cce2205699d62529c9
[a-compare]: https://github.com/backnotprop/plannotator/compare/v0.27.12...v0.27.13
[a-events]: https://github.com/backnotprop/plannotator/blob/v0.27.13/apps/pi-extension/plannotator-events.ts
[a-annotations]: https://github.com/backnotprop/plannotator/blob/v0.27.13/apps/pi-extension/server/external-annotations.ts
[a-args]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/shared/review-args.ts
[a-doc]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/shared/doc-resolve.ts
[a-reference]: https://github.com/backnotprop/plannotator/blob/v0.27.13/apps/pi-extension/server/reference.ts
[a-bun-review]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/server/review.ts
[a-open-state]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/shared/review-open-state.ts
[a-browser]: https://github.com/backnotprop/plannotator/blob/v0.27.13/apps/pi-extension/plannotator-browser.ts
[a-server]: https://github.com/backnotprop/plannotator/blob/v0.27.13/apps/pi-extension/server/serverReview.ts
[a-storage]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/shared/storage.ts
[a-storage-pr]: https://github.com/backnotprop/plannotator/pull/1473
[a-review-ui]: https://github.com/backnotprop/plannotator/blob/v0.27.13/packages/review-editor/App.tsx
[a-mobile-pr]: https://github.com/backnotprop/plannotator/pull/1471
[a-amp-pr]: https://github.com/backnotprop/plannotator/pull/1476
[a-tarball]: https://registry.npmjs.org/@plannotator/pi-extension/-/pi-extension-0.27.13.tgz
