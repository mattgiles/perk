# Pi and pi-subagents release assessment — 2026-10-24

Status: assessment complete; a bounded compatibility bump is proposed. This document changes
no runtime implementation, pins, host floor, generated wiring, or compatibility stamp.

Assess **Pi 1.4.0 + pi-subagents 0.81.0** as the next adopted pair, with **Pi ≥1.4.0** as the
new host floor. Both were npm's `latest` and the latest stable GitHub releases when checked on
October 24. The supplier requires Pi ≥1.2.0; this assessment targets the latest stable Pi 1.4.0.
[Pi release][pi-release],
[supplier release][sub-release], [published manifests][pi-npm], [supplier manifest][sub-npm].

The minimum work is small enough to keep separate from feature adoption:

- Repair two context hooks for custom-message starts, classify the new SDK tool field in the
  prose map, and adapt the runner/cursor test boundaries.
- Move the version facts together and remove Chord from the adopted installation family.
  Pi now pins its internal dependencies exactly: the extra sibling installation specs are
  obsolete, and a single exact Pi install was verified to produce the complete seven-package
  family.
- Resolve the existing held lifecycle claims before calling the new pair certified. This
  audit supplies source findings and offline probes, not the missing live matrix.

**Keep the native SDK bridge and the report-wave transport.** Supplier bundling does not
replace SDK identity sharing, and native data-only parallel workflows do not preserve Perk's
report contract. The best additional opportunities are native retry diagnostics, checks against
upstream configuration schemas, cache-preserving discovery restoration, and sandboxed child
launchers. Their adoption is independent of the minimum bump.

## 1. Snapshot, comparisons, and evidence

| Fact | Current checkout / host | Assessed target |
| --- | --- | --- |
| Perk | 4.1.0; `333981290e71de3008bf162ddee2f20d8c1c1389`; initially clean | Same source revision, independently copied for experiments |
| Development SDK | Four direct Pi development pins and installed packages at 1.1.0; wildcard host peers | All four exact 1.4.0; regenerated lockfile |
| PATH CLI / adopted Pi / remote installation | 1.1.0 / 1.1.0 / 1.1.0 | Adopted and remote installation 1.4.0 |
| Host floor | Pi ≥1.1.0 | Pi ≥1.4.0, independently enforced at CLI and SDK admission |
| Managed / installed supplier | `npm:pi-subagents@0.76.1` / 0.76.1 | Exact 0.81.0 |
| Guidance stamp | 0.75.0 | Stays unchanged until the required supplier certification rows pass |
| Other native bridge consumer | Installed pi-web-access 0.37.0 | Held at 0.37.0 in experiments |
| Toolchain | Node 26.12.1; npm 11.20.0; uv 0.13.5; Python 3.13.9 | Same; existing Node supported-line floors and TypeBox 1.3.27 suffice |
| Pi release | Baseline v1.1.0 | v1.4.0, `4a080252f06caf63a525d7873c5d94d3c23887e0`; GitHub publication 2026-10-21 22:49:48 UTC |
| Supplier release | Baseline v0.76.1 | v0.81.0, `1bc941363cb62fc23c94c5519364b03dc150be3e`; GitHub publication 2026-10-22 20:21:52 UTC |

The supplier tag is annotated: `05ac2a4b9f91bbf50672ea29e978437cfaaa117b` points to the
commit above, which also matches npm's `gitHead`. Pi's tag points directly to its listed commit.
The npm publications precede GitHub's: Pi at 22:48:58.431 UTC on October 21, and the supplier at
20:21:26.540 UTC on October 22. These are publication-channel differences.

The [reverification guide][reverify] defines the separate version facts and adoption versus
certification. The most recent [1.1.0 certification][certification] is **HELD**, with W4, W6,
and W7a failing and other required cells not run. The new audit does not convert that record to a
pass or treat an adopted pin as a certification stamp.

Evidence labels used here:

- **Reproduced:** an actual released package or current Perk boundary was exercised offline.
  Controlled callbacks and faux-model sessions are identified as such.
- **Source-supported:** the tagged implementation and matching published JavaScript establish
  the behavior; the complete user path was not driven.
- **Unverified:** the proposed adoption or live acceptance condition still needs measurement.

Research used npm artifacts and GitHub release-tag archives fetched through `gh`. The library's
older Pi source checkout and pinned pi-subagents 0.71.0 mirror are historical context, not
target-release evidence. No moving `main` implementation is counted as shipped functionality.

### Released delta coverage

The coding-agent, agent-core, pi-ai, and TUI changelogs were read through 1.4.0, together with
every supplier release after 0.76.1. The relevant dispositions are:

| Release | Consequence for this assessment |
| --- | --- |
| Pi 1.2.0 | Custom-message starts now run `before_agent_start`; its event is a discriminated union. Startup is busy before hooks finish. Chord and the source-only experimental application stack are removed. Configuration schemas and TUI fake-cursor markers require checking producer/test assumptions. |
| Pi 1.3.0 | Internal Pi dependency declarations become exact. Resume preserves active tools; cancelled codemode workers count until actual exit. Removed frame helpers have no current Perk caller. |
| Pi 1.4.0 | Tool restoration handles later-registered extensions; codemode queues for workers; summaries use the model output limit. Provider/client identity and transcript-tool APIs change, but the removed low-level APIs have no current Perk caller. |
| Supplier 0.77.0 | Smaller tool definitions and result previews, declaration pinning, native parallel workflow, launcher wrappers, child-session provenance, stricter project-trust handling, and broader RPC stop support. |
| Supplier 0.78.0 | Chord aliases become conditional on the chosen host declaring Chord, repairing background launch on Pi 1.2+. Escape holds parent wakes; capacity, output retention, and structured-output validation improve. |
| Supplier 0.79.0 | Same-process session handoff adopts background work; reload/restore tool activation is repaired. Native child session paths and prompt handling improve. This does not restore Perk's activation-owned report handles. |
| Supplier 0.79.1 | Background helpers become lazy, embedded hosts take precedence for child launch, and finished child results survive workflow-host failure. |
| Supplier 0.79.2 | Undelivered notices survive process restart, explicitly leaving reload behavior unchanged; child `APPEND_SYSTEM.md` inheritance is removed and reused workflow capacity is released. |
| Supplier 0.80.0 | Pi ≥1.2.0 is required; custom notices directly trigger parent turns; native parallel items accept cwd/model. Source maps stop shipping. |
| Supplier 0.81.0 | Bundled parent entry/subpath exports, one bounded missing-structured-output repair turn, safe provider diagnostics, notice-origin tagging, and frontmatter comment parsing fixes. |

Sources: [coding-agent changelog][pi-changelog], [agent-core][agent-changelog],
[pi-ai][ai-changelog], [TUI][tui-changelog], and [supplier changelog][sub-changelog]. Model
catalog, terminal/platform, and provider fixes are inherited unless a concrete Perk caller is
identified below. No provider-specific live run or Windows benchmark was performed here.

### Earlier recommendations reconciled

The September [Pi assessment][old-pi], [supplier assessment][old-sub],
[Pi 1.0 recommendations][old-recommendations], and [pre-durable true-up][true-up] are inputs,
not an unchanged backlog. Current code already has canonical context projection, the `script`
RPC dialect, own-name-only tool activation, nested-call enforcement, eight SDK bridge
specifiers, descendant ceilings, writer bridge-off, partial settlement handling, project-only
worker MCP, and prepared feedback classification. The old FFF/completion-guard removals are
already complete. Do not schedule them again or attribute them to these releases.

Chord/application-host proposals in older integration memos are not a prerequisite for this
bump. The experimental application stack was removed, while durable execution is a separately
scoped product. Preserve the current local SDK and supplier roles.

## 2. What strictly needs changing

### R1 — narrow prompt access while retaining custom-start guidance

**Reproduced runtime boundary defect and typecheck failure.**
[`installInjectedContext`][context-injection] and [`registerBindingDelivery`][binding-delivery]
both unconditionally call `event.prompt.includes(...)`. Pi 1.4.0's
[`BeforeAgentStartEvent`][pi-types] gives `prompt` only to `messageType: "user"`; a custom
notice instead carries `message`. Eligible Perk contexts therefore throw on custom starts.
This is directly relevant to 0.80+'s native completion wakes.

The smallest repair is to guard **only the submitting-user-prompt dedup check** with
`event.messageType === "user"`. Continue the existing branch/projection checks and guidance
injection for custom starts. Returning early for every custom event would silently omit the
bindings and authoring guidance that the new host now permits those runs to receive. Preserve
runner-child suppression, render-before-dedup, and the two hooks' existing read-error policies.

Controlled hook probes reproduced both failures with the released custom-event shape while
equivalent user events injected normally. The two one-line guards made both custom probes pass
in the temporary copy. Acceptance also needs user-seed dedup, existing live-copy dedup, custom
starts after compaction, and runner suppression. Existing pure hook fixtures must carry the
new user discriminator so they exercise the intended branch.

### R2 — classify the new SDK field in the prose map

**Reproduced build failure.** [`TOOL_FIELD_POLICIES`][prose-selector] exhaustively satisfies
`Record<keyof ToolDefinition, ToolFieldPolicy>`. The target adds `reachesTools`, and root
`npm run typecheck` fails until the field has a policy.

Classify it as non-prose with a runtime reachability reason. Its callback tells late-registering
extensions which tools a call may reach; it is not model-facing text or an authorization grant.
The [MCP implementation][pi-mcp] consults it before execution. Preserve Perk's nested-call and
MCP restrictions rather than deriving access from this hint. The classification, together with
R1, cleared all three target typecheck diagnostics in the temporary repair preview.

This is a development-tool repair, not a shipped extension migration. Run the existing opt-in
prose-review checks when implementing it; keep those suites outside default CI as documented.

### R3 — update the installation graph and version facts together

**Reproduced graph mismatch; source-supported supplier dependency break.** Keeping 0.76.1
while moving the host is unsafe: that supplier requires Chord aliases from hosts that no longer
provide Chord. The target supplier repairs that requirement. Coordinate the pair rather than
bumping only the SDK or only the supplier.

Pi 1.4.0's complete internal family is the coding agent plus **six companions**: agent-core,
ai, codemode, mcp, telemetry, and tui. Chord is absent. A one-spec install of
`@earendil-works/pi-coding-agent@1.4.0` into a fresh prefix installed all seven at 1.4.0, and every
internal dependency declaration in that graph is exact. The old eight-name closure assertion
fails on the target lockfile specifically because it still expects Chord.

Update the adopted family and its tests to remove Chord. The recommended simplification is to
make `PI_INSTALL_SPECS` name only the exact coding-agent spec: upstream now supplies the exact
companion selection. Keep the adopted-family coherence probe, with its corrected six-companion
set; exact dependency declarations do not prove a partially damaged installation is intact.
There is no evidence here to remove that diagnostic. See [the current owner][pi-host],
[target manifest][pi-package], and [conditional supplier aliases][runner-aliases].

The implementation must reach these existing owners and their regression fixtures:

| Version/wiring surface | Required update |
| --- | --- |
| Four development pins and lockfile | Exact 1.4.0 through the existing bump path; inspect the resulting graph |
| Shared host floor | `pi.min_version: "1.4.0"`; preserve independent CLI/SDK admission and current Node floors |
| Adopted Pi and install command | 1.4.0; corrected family; simplified exact install specs |
| Remote installation | Continue deriving from the adopted pin; reconverge the owned action and managed digest |
| Supplier convergence | Exact 0.81.0 in `SUBAGENTS_PACKAGE`; reconverge project settings and their managed digest |
| Tests and compatibility prose | Update pin-bound assertions, generated-artifact expectations, requirements/setup guidance, the developer reverification procedure, and matching perk-expert configuration reference |
| Guidance stamp | Leave at 0.75.0 until the required new supplier certification passes |

Amend the affected shared contracts in the implementation turn. Document the exact dependency
semantics and changed custom-start behavior; do not leave the guide's caret-range/always-Chord
description as current guidance. User docs should distinguish the adopted target from its actual
certification status throughout.

### R4 — adapt tests to Pi's runner and rendering boundaries

**Reproduced test integration failures, distinct from R1.** The
[`emitBeforeAgentStart` harness helper][harness] casts the runner to an obsolete four-argument
method. The target accepts `(trigger, systemPromptOptions)`. Its missing second argument caused
25 tests to fail before their hooks ran, with an undefined `customPrompt` read in Pi. Updating
only this helper to send `{messageType: "user", prompt}` and an options object made all **334**
selected integration tests pass. That run still had the unmodified R1 hooks: passing those tests
does not cover custom-message starts.

The [BTW rendering tests][btw-tests] have six additional failures because Pi's `Input.render()`
now emits fake-cursor APC markers for the [TUI renderer][pi-tui] to resolve. All six failures
identify those exact markers on the input row. This is not evidence of hostile text escaping
Perk's sanitizer. Adapt the assertion boundary to recognize only Pi's sanctioned cursor markers
or exercise their actual TUI resolution, while retaining rejection of arbitrary APC/ESC/BEL,
C1, and line controls. Do not strip the markers from the live input or broadly waive control
checks. A test-only normalization of the two exact native markers restored **94/94** in the
surface/BTW selection; live keyboard and terminal rendering remain unverified.

### R5 — close or explicitly reconcile the held lifecycle cases

These are carryover acceptance gaps, not three newly demonstrated upgrade regressions. The
latest fixes do not justify silently changing their status or moving the stamp.

| Existing cell | Target evidence | Minimum follow-up |
| --- | --- | --- |
| W4: queued wake around Escape and reload | **Source-supported.** The notifier now persists undelivered notices on process shutdown and replays them on the active branch. Its shutdown persistence explicitly excludes reload. Escape intentionally holds automatic wakes. | Drive completion while busy, Escape, reload, then a user prompt; require the stopped parent to remain stopped and the result to remain available. Reconcile the old auto-wake expectation with the new explicit stop policy. No automatic resume shim. |
| W6: unfinished lane absent from partial `results` | **Source-supported carryover.** The target still builds partial `results` from `partial.children`, separately from `workflowChildren`; running lanes can remain roster-only. | Repair Perk's explicit-native-partial normalization to use the correlated roster for unfinished-lane failure diagnostics, while taking report data only from the existing validated carrier. Preserve finished reports and incomplete coverage; prove the slow lane becomes `lane-failed` under the current contract. |
| W7a: cancellation proof/reload-stop expectations | **Reproduced helper boundary plus source support.** A closed workflow with a running child still returns pending child-process proof. In-process workflow controllers still disappear on replacement; stopped runs can yield `invalid_state`. | Re-run cancel, later status, and reload-then-stop. Assert semantic stop acknowledgement/refusal and observed/pending/unknown proof, rather than one fixed reason string. `writer-close-unverified` remains uncertainty requiring diagnosis, never inferred termination. |

Sources: [notifier][notify], [workflow result construction][executor],
[RPC stop][sub-rpc], [terminal proof][terminal-proof], and the original
[live observations][certification]. This audit did not reproduce the complete live W4/W6/W7a
scenarios. The roster repair above is a bounded Perk proposal, not a claim that 0.81.0 already
contains it. Preserve the historical observations and record target-pair evidence separately
when certification runs.

### Boundaries with no required migration found

The target keeps the v1 request/reply event envelope, advertised completion channel, RPC `script`
carrier, and foreground structured delegation. Perk's current spawn dialect remains valid.
Queued/paused stop support is additive; a stop reply still acknowledges a request rather than
proving process exit. [RPC][sub-rpc], [delegation contract][delegation].

Source inspection retains project-trust forwarding, package-agent discovery, definition-relative
skills, the prompt-runtime provenance path, extension bindings, and empty descendant ceilings.
Stricter untrusted-project discovery may refuse project/package agents; preserve that refusal
rather than bypassing trust. All shipped Perk agents use replacement prompts; the new empty
append-prompt list prevents accidental operator `APPEND_SYSTEM.md` inheritance. These checks
need real-child acceptance later. [Agent discovery][agents-source], [child session][child-session].

The target's installed-consumer census exactly matches the existing eight specifiers: **no
census widening or bridge schema bump was indicated**. Worker MCP, native compaction/retry,
nested restrictions, and codemode policy survived the selected offline tests. No current caller
was found for the removed low-level pi-ai telemetry/transcript/frame/user-agent APIs; model and
provider wire fixes are inherited. Public peers, Node floors, and TypeBox need no change for
this pair.

## 3. What can be removed, simplified, or must stay

| Perk adaptation | Disposition and evidence |
| --- | --- |
| Explicit sibling installation to defeat Pi's caret ranges | **Simplify now.** Pi 1.3+ pins internal dependencies exactly; the clean one-spec 1.4.0 install produced the full seven-package family. Drop the extra install specs and old floating-companion rationale. Correct, retain, and test the family-health diagnostic separately. |
| Chord family entry | **Remove now.** No target dependency requires it; the target lockfile closure rejects the stale entry. |
| Native SDK bridge and host namespace capture | **Retain.** Real bundled 1.4.0 startup with the released supplier/web consumer had zero censused native resolutions escaping the bridge; bridge-off had 17 resolutions into separate installed SDK modules. The [host loader][pi-loader] still uses virtual modules in bundled mode. Full foreground-child and late-import retirement proof is still owed. |
| Foreign-tool activation ownership | **Already simplified.** Perk reconciles its own names and preserves foreign selections. New supplier lazy tools and declaration pinning inherit that behavior. Retain stage presentation and read-only enforcement. |
| Restoration window and discovery-cohort startup deferral | **Retain for the bump; investigate narrower startup handling.** Native resume/tree fixes are useful, but Perk's own removals can still destroy pending selections. The restoration-window and own-name tests pass on the target. Preserve enforcement while measuring whether fresh-session initialization can stop resetting valid restored Perk selections. |
| Canonical context projection and delivery predicates | **Retain.** Host projection does not decide whether Perk's current guidance was delivered. R1 changes event access, not deduplication ownership. |
| Root completion correlation, subscribe-before-spawn, aggregate validation, and drain-once collection | **Retain.** Native child notices/status are not a complete typed wave aggregate. Restart replay and same-process run adoption do not reconstruct Perk's activation-owned collection handle. |
| Settlement grace, stop/proof separation, launch freshness token, stale/context-less RPC guards | **Retain.** Controllers remain in-process, reuse remains supported, and acknowledgement remains distinct from terminal evidence. No released replacement was demonstrated. Pi's stdio RPC fixes concern a different transport. |
| Explicit acceptance `none`, intercom bridge-off, restriction packet, descendant ceiling, worker MCP floor | **Retain.** The native structured-output repair turn does not replace these policies. [Acceptance inference][acceptance] changes for built-in read-only roles do not remove the completion-policy guarantee for Perk's custom agents. |
| BTW live-runtime adaptation | **Retain.** Target [ModelRegistry][pi-model-registry] still holds its runtime privately and exposes no replacement accessor. The cursor-marker test repair is independent of runtime/auth sharing. |
| Worker `finishTurn`, constrained model calls, and budget enforcement | **Retain.** The 48 offline worker end-to-end tests pass. Worker-pool queuing, pricing, and summary-output fixes do not prove a replacement for Perk's execution budget or terminal outcome. |

This revisits all six retention rows in the last certification. Its browser-owner marker and
post-collection annotation adaptations also stay: this audit held the browser supplier outside
scope and found no Pi/pi-subagents replacement for that separate handoff contract.

### Why native parallel does not replace ReportWave

The [native parallel resolver][workflow-resources] accepts tasks with agent/task and optional
cwd/model. The [generated workflow][structured-workflows] assigns keys such as `task-1` and
projects ordinary output. A focused source-module probe rejects caller-supplied lane keys,
`outputSchema`, and `extensionBindings`; its successful generated projection omits
`structuredOutput`.

Top-level controls can apply shared settings, but do not restore Perk's per-assignment schemas,
explicit identities, skill/label metadata, restriction packet, and compact report projection.
Switching transports would require another adapter to reconstruct these guarantees. Keep
Perk's small rendered `runs.all` script for reports. Native parallel is a useful lower-cost
interface for ordinary ad hoc delegation, with no need to route that delegation through
ReportWave.

## 4. New capabilities worth pursuing

Priorities below concern Perk changes beyond the bump. Benefits are inferred from the released
interfaces unless a measurement is listed; no local cost or latency improvement is claimed.

| Priority | Opportunity | Bounded adoption and value | Cost / acceptance |
| --- | --- | --- | --- |
| 1 | Native provider retry diagnostics | The structured delegation update/response now exposes safe retry/backoff and error-category facts. Surface them during existing foreground conflict resolution so a user can distinguish backoff from a long model turn. Use the existing event seam and surfaces module. | Small–medium. Validate the optional field once; keep absence as unavailable. Test old payloads, backoff/in-flight transitions, listener cleanup and terminal races. No raw provider-body logging, new recorder, retry controller, or effect on lock release. |
| 2 | Generated upstream configuration schemas | Validate representative Perk-generated Pi settings and model configuration against the released schemas in producer tests. This catches the kind of schema drift that now fails earlier during host startup. | Small. Pin the schema fixture/source to the adopted release and respect extension-owned keys. Keep validation offline; do not fetch `latest` at runtime or invent a second settings parser. |
| 3 | Preserve useful restored discovery selections | Pi's restored-tool defaults and the supplier's pinned/lazy declarations reduce prompt churn. Examine Perk's remaining activation-local initial deferral of its own four-tool family, which currently resets selections on resume/reload. | Medium, separate experiment. Compare fresh/resume/reload/tree requests and cache-prefix stability. Preserve stage eligibility, read-only backstops, no-tools exclusions, and restoration of late MCP tools before deleting any state. |
| 4 | Sandbox wrappers for report children | Supplier `launcher` plus user-owned `runnerLaunchers` can wrap the existing background Pi runner while retaining native steering/results. This is a real path to stronger filesystem/network isolation around report roles without replacing the engine. | Strategic. First characterize one report role with an explicitly configured launcher: necessary repo reads, credentials, artifact writes, cancellation/process proof, and unavailable-launcher refusal. A launcher is not itself a sandbox policy; remote placement/external runners do not combine with it. Keep current restrictions and make no default enforcement claim. |

Sources: [public diagnostics type][delegation], [current foreground adapter][foreground],
[settings schema documentation][pi-settings], [model schema documentation][pi-models],
[Perk discovery initialization][activation], [launcher resolution][launcher], and
[supplier configuration][sub-config]. A future diagnostics implementation needs to subscribe
to updates through the existing delegation owner, which currently does not expose that stream.
Terminal usage remains authoritative; progress snapshots are not spend accounting.

### Benefits inherited by upgrading

Take these without adding a Perk subsystem:

- **Structured completion recovery:** a native child missing `structured_output` gets one
  follow-up in its existing session and deadline; usage includes it. Rejected calls do not get
  this extra turn. Keep schema validation and failed-status coverage rules; do not add a second
  Perk repair loop. [Foreground recovery][foreground-execution], [background recovery][run-child].
- **Cheaper parent context and startup:** smaller and pinned supplier declarations, lazy
  background helpers, preview-sized native notices, and bundled parent imports. Perk's typed
  report payload is separate; do not truncate its structured carrier to match a prose preview.
- **More dependable host execution:** codemode waits for workers; cancelled workers remain
  accounted for; summary generation uses the model's output allowance; malformed/truncated
  tool-call handling, deferred-tool caching, and provider retries improve. Keep Perk's own budget
  and timeout semantics, including the possibility of queue delay.
- **Clearer provenance and isolation:** supplier notices identify their automated origin,
  child headers link to the parent session, model displays use provider-qualified identity,
  and replacement-prompt children do not inherit the operator's append file.

Image classifiers, a new classification/routing layer, an execution-platform migration,
automatic reload report recovery, blanket slash-command suppression, and a custom progress
dashboard are deferred. The current classifier, completion-only report collection, and native
inspectors already have deliberate contracts. Upstream feature availability alone supplies no
measured reason to replace them.

## 5. Verification performed and follow-up order

The assessment used `/tmp/perk-pi-assessment.2f7ryH`, with a `git archive` copy of the pinned
Perk revision, fresh npm installations, and separate upstream archives. No npm installation used
the main checkout's shared or hard-linked `.pi/npm` metadata. Commands in the copied checkout
explicitly selected Node 26.12.1: entering a directory outside this repo otherwise selected an
unsupported global Node 25, which the first install correctly refused before target testing.

Supplier and web-access installation used `--legacy-peer-deps` to leave host peers owned by
the independently installed SDK. Lifecycle scripts were disabled. The single-Pi-prefix control
installed only the exact coding agent. The main checkout's manifests, lockfiles, settings, and
global Pi remained at the baseline values.

### Measured ledger

| Check | Baseline / unmodified target | Controlled temporary adaptation / limit |
| --- | --- | --- |
| Root `npm run typecheck` | Baseline PASS; target FAIL with exactly three diagnostics: two prompt reads and missing `reachesTools` policy | PASS after the two discriminant guards and one non-prose classification; no production repair committed |
| Selected 12-file integration set | Baseline **334 PASS**; target **309 PASS / 25 FAIL / 0 skipped** | **334 PASS / 0 skipped** after adapting only the harness runner call; production custom-start defects still present during this run |
| Worker `stageExecutionE2e` | Target **48 PASS / 0 skipped** | Real SDK, faux model, local test MCP servers; no external model or production remote worker |
| Surface/BTW selection | Baseline **94 PASS**; target **88 PASS / 6 FAIL / 0 skipped** | **94 PASS / 0 skipped** after test-only normalization of the two fake-cursor markers |
| Five Python compatibility/policy suites | Baseline **120 PASS**; target graph **119 PASS / 1 FAIL** | Failure is the stale Chord family expectation; host floor and supplier source constants were intentionally left at their baseline values |
| Native consumer import census | PASS on supplier 0.81.0 plus web-access 0.37.0; the census test ran, not skipped | Existing eight-specifier set remains exact |
| Hook probes | Both eligible user starts inject; both custom starts reproduce `prompt.includes` exceptions | Both custom starts inject after the two proposed guards |
| Native parallel shape probe | Rejects lane key, schema, and extension-binding item fields; ordinary generated result omits structured output | Confirms the replacement gap; no agent launched |
| Released terminal-proof helper | Closed dispatch plus running child returns pending with a child-specific reason | Proves the helper boundary, not a live cancellation/runner-exit result |
| Exact single-spec host install | Seven internal packages, all 1.4.0; no Chord | Fresh prefix, no manual sibling install |
| Bundled CLI import smoke, bridge on/off | Both exit 0, register consumer tools, and report installed/disabled bridge as expected; native escaping resolutions **0 / 17** | Explicit extension paths in a sterile project; selfcheck reports **WIRING GAP / agents MISSING**, as expected without normal package-agent wiring. This is an import/identity control, not a green full selfcheck or child certification |

The CLI smoke used the temporary repair-preview source. It performed no model turn; the
placeholder credential was never sent. The trace records censused resolutions from the two
consumer roots that reach native module resolution; the bridge short-circuits those imports
when enabled. The off control resolves into the copied checkout's SDK modules rather than the
separate bundled host's namespaces. This supports retention without pretending to replace the
full in-process child/late-import retirement proof.

### Reproduction entrypoints

In an independent copy, install the four target SDK development packages and the two exact
consumer artifacts, then run:

```bash
npm run typecheck
node --test --test-concurrency=4 \
  extension/substrate/nativeSdkBridge.test.ts extension/substrate/toolGating.test.ts \
  extension/substrate/ownNamesActivation.test.ts extension/substrate/restorationWindow.test.ts \
  extension/substrate/mcpReadOnlyFloor.test.ts extension/substrate/codemodeLift.test.ts \
  extension/substrate/bindingDelivery.test.ts extension/pi/v1/contextInjection.test.ts \
  extension/waves/rpcAdapter.test.ts extension/waves/reportWaveRpc.test.ts \
  extension/waves/reportWave.test.ts extension/pi/v1/waveIsolation.test.ts
node --test extension/worker/stageExecutionE2e.test.ts
node --test extension/vendor/btw/btw.test.ts extension/surfaces/surfaces.test.ts \
  extension/surfacesGuard.test.ts
uv run pytest -n0 -q tests/test_pi_host.py tests/test_host_floor.py \
  tests/test_subagent_agents.py tests/test_repo_local_agents.py \
  tests/test_native_sdk_bridge_parity.py
```

Temporary probes recorded expected defects with assertions: registered hook callbacks received
the actual user/custom event shapes; the parallel generator received each unsupported field
individually; the installed terminal-proof helper read a running child's status file. These
were bounded experiments, not a new committed test framework. No full target CI or opt-in
prose-review suite was run. The document's final local-link and whitespace checks are separate
from pair certification.

Artifact identities from npm metadata (npm verified integrity during installation):

```text
@earendil-works/pi-coding-agent@1.4.0
sha512-Z41LpZ3yYHSC/UUps6Mr39UMFPwH8elhJBG9DY1P7kuzsE5qSK/6eMj2EHzO5evJRQWLbKSqUMw+4nCNtIyiQg==
pi-subagents@0.81.0
sha512-nS4otciP317cYBqIs+6IE8nsudWpPTbI0Lzx7BLgZHbawGs6KThjLc9429Z6eHBc5ip7rXCMRc9XhgZKyF+9Dg==
```

### Recommended execution order

1. **Implement the compatibility repairs together.** R1/R2, the harness and pure event fixtures,
   the narrowly adapted rendering assertion, and coordinated pins/install graph/convergence.
   Update their existing tests, shared contracts, user docs, developer guide, and expert mirror.
   Preserve the current authority boundaries and report execution mechanism.
2. **Resolve lifecycle acceptance and run the real gates.** Implement the bounded W6 diagnostic
   repair; reconcile W4/W7a with observed semantics; run the existing offline suites and opt-in
   prose checks, then the [documented live matrix][reverify]. Required child, browser, worker,
   remote, trust, and cancellation cells remain owed. Use actual target-package loading and
   package-agent discovery rather than the sterile import smoke.
3. **Adopt and certify with distinct claims.** Characterization/offline evidence may precede
   adoption under the existing contract. Keep the stamp and support wording truthful until
   required supplier/live evidence passes; publish a dated archive certification record.
4. **Take optional improvements separately.** Start with diagnostics or schema producer checks;
   measure discovery/cache changes and one sandboxed report role before expanding them.

Live model runs, interactive browser/terminal drives, and production remote certification were
not run. The new pair remains uncertified; source fixes and passing offline tests do not close
those evidence gaps.

[pi-release]: https://github.com/earendil-works/pi/releases/tag/v1.4.0
[sub-release]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.81.0
[pi-npm]: https://registry.npmjs.org/@earendil-works/pi-coding-agent/1.4.0
[sub-npm]: https://registry.npmjs.org/pi-subagents/0.81.0
[pi-package]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/package.json
[pi-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/CHANGELOG.md
[agent-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/agent/CHANGELOG.md
[ai-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/ai/CHANGELOG.md
[tui-changelog]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/tui/CHANGELOG.md
[sub-changelog]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/CHANGELOG.md
[pi-types]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/src/core/extensions/types.ts
[pi-loader]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/src/core/extensions/loader.ts
[pi-model-registry]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/src/core/model-registry.ts
[pi-mcp]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/src/extensions/mcp/index.ts
[pi-tui]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/tui/src/tui.ts
[pi-settings]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/docs/settings.md
[pi-models]: https://github.com/earendil-works/pi/blob/4a080252f06caf63a525d7873c5d94d3c23887e0/packages/coding-agent/docs/models.md
[runner-aliases]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/background/runner-aliases.ts
[sub-rpc]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/extension/rpc.ts
[notify]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/background/notify.ts
[executor]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/foreground/subagent-executor.ts
[terminal-proof]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/background/workflow-terminal-proof.ts
[delegation]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/api/delegation.ts
[child-session]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/shared/child-session.ts
[acceptance]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/shared/acceptance.ts
[agents-source]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/agents/agents.ts
[workflow-resources]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/workflows/workflow-resources.ts
[structured-workflows]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/workflows/structured-workflow-scripts.ts
[launcher]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/shared/runner-launcher.ts
[sub-config]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/docs/configuration.md
[foreground-execution]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/foreground/execution.ts
[run-child]: https://github.com/nicobailon/pi-subagents/blob/1bc941363cb62fc23c94c5519364b03dc150be3e/src/runs/background/run-child-session.ts
[reverify]: ../developers/pi-subagents-reverify.md
[certification]: ../design/archive/pi-1.1.0-certification.md
[old-pi]: pi-assessment-2026-09-29.md
[old-sub]: pi-subagents-assessment-2026-09-21.md
[old-recommendations]: perk-recommendations-for-pinning-pi-1.md
[true-up]: pre-pi-durable-true-up.md
[context-injection]: ../../extension/pi/v1/contextInjection.ts
[binding-delivery]: ../../extension/substrate/bindingDelivery.ts
[prose-selector]: ../../tools/prose-map/selector.ts
[pi-host]: ../../src/perk/substrate/pi_host.py
[harness]: ../../extension/testing/harness.ts
[btw-tests]: ../../extension/vendor/btw/btw.test.ts
[foreground]: ../../extension/pi/v1/foregroundDelegation.ts
[activation]: ../../extension/pi/activation.ts
