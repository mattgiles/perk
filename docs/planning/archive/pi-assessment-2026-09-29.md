# Pi release assessment — 2026-09-29

Status: audit complete; follow-up implementation proposed. This assessment changes
no runtime code, dependency pins, or compatibility claims.

Use **Pi 0.99.1 as the next minimum supported baseline** for the follow-up work.
The review found three conditional integration defects to address: codemode can
continue after a terminating workflow tool, tool reconciliation can discard native
tool-search selections, and learning normalization drops nested tool-call evidence.
They matter when the new tool orchestration features are used; this audit did not
establish an unconditional failure of ordinary perk sessions after a host upgrade.

**No large adapter is demonstrably redundant in this release.** Keep the native
SDK bridge, stage/read-only enforcement, `/btw` runtime adaptation, and report RPC
guards. Adopt the new tool exposure API to protect workflow boundaries first;
consider structured results and bounded codemode/MCP support afterward. Inherit
session persistence and rendering improvements through the host upgrade.

## Snapshot and evidence boundary

| Subject | Audited snapshot |
| --- | --- |
| Perk | 3.8.0, `fa84a885593cb6127e527a778312d238aa2aa2ea`; initially clean checkout |
| Development SDK | All six Pi development pins and installed packages are **0.87.0**: agent-core, ai, client, coding-agent, server, tui. Peer ranges remain `*`. See [package.json][package]. |
| Executable on PATH | Global `pi --version` reports **0.87.1**, under mise Node **26.3.0**. This is distinct from the development SDK. |
| Target release | [v0.99.1][release], commit `d86654abb8862e201933517d6f1fce9f88dd117f`, published September 29 at **18:27:00 UTC**, verified through `gh release view` |
| Comparison baseline | v0.87.0, commit `16787ad5b2dc748047f314ca1bfe7708f30f54f3`; include 0.87.1, 0.99.0, and 0.99.1 changes |
| Refreshed source mirror | `docs/library/source-code/github.com/earendil-works/pi`, HEAD `1b347794e2a630e4359f2584f4eea388145d0ddf`, **13 commits after v0.99.1** |
| Refreshed documentation | `docs/library/documentation/pi`, mirrored from `pi.dev/docs/latest`; library freshness check was **unverifiable**, not evidence of stale content. Release-tag source determines release claims. |
| Relevant installed suppliers | `.pi/npm/node_modules`: pi-subagents **0.73.1**, pi-web-access **0.33.0**, Plannotator **0.27.21**. The pi-subagents library mirror is 0.71.0 and is not the installed baseline. |

The [coding-agent][up-changelog], [ai][up-ai-changelog], and
[tui][up-tui-changelog] changelogs were checked against the consumed interfaces.
The earlier [September 21 assessment][previous] and [September 24 integration
memo][deep-opportunities] supply history, not an unchanged backlog. Canonical
context projection, `/btw` session-manager seeding, public streaming for its
summary, and the coordinated 0.87.0 development pins have already landed.

Evidence labels in this document have specific limits:

- **Reproduced at the boundary:** current perk code exercised with the relevant
  released Pi source module and a controlled host. This is not a full 0.99.1 host
  run. The tested source files were verified byte-for-byte against v0.99.1.
- **Source-supported:** the released implementation and its perk caller establish
  the behavior; the complete runtime path was not executed.
- **Needs validation:** an adoption or retirement proposal with acceptance work
  still outstanding.

The mirror is a partial Git clone. Some historical blobs are absent, so the 0.87.0
comparison also used original TypeScript embedded in the installed package's
source maps. Twenty relevant coding-agent files were matched to their 0.99.1 blob
IDs; sixteen had installed baseline source maps. Additional session-probe
dependencies and codemode's executor were also matched to the release.

Published 0.99.1 packages were unavailable locally, and the attempted npm metadata
lookup failed with `ENOTFOUND registry.npmjs.org`. Consequently there is **no full
0.99.1 package typecheck, extension-loading certification, or worker certification**
in this assessment. No live provider, MCP server, browser review, or TUI session
was exercised. The source-module probes use available 0.87.0 dependencies where
needed; TypeBox is 1.3.27 in both the installed environment and target manifest.

## 1. What needs fixing for the upgrade

Treat the following as prerequisites for supporting the new orchestration paths.
They are scoped compatibility fixes, not evidence for a worker or extension rewrite.

### F1 — keep terminal workflow tools out of nested execution

**Source-supported, with the nested-runner behavior reproduced.** Existing tools
such as [`submit`][submit], [`ready`][ready], [`land`][land], and
[`finalize_address`][address] rely on a result containing `terminate: true` to stop
the agent after the workflow operation. They specify sequential execution but no
exposure. Under the new [tool contract][up-types], omitted exposure means `direct`:
the tool is callable by another tool through `ctx.executeTool()` while active.

Pi's released [nested runner][up-nested] returns the terminating result to its
caller but does not stop subsequent nested calls. The released
[codemode executor][up-codemode-execute] converts the outcome into text or structured
content and returns its own result without propagating `terminate`. Sequential
execution prevents overlap; it does not end the script or the outer agent loop.

The offline probe used the real `NestedToolCallRunner` with a stub `submit` returning
`terminate: true`, followed by a stub `write`. It observed:

```json
{
  "terminateReturned": true,
  "executions": ["submit", "write"],
  "allEventsCarryParentId": true
}
```

This demonstrates the nested execution boundary, not an actual submission or a
QuickJS end-to-end run. Combined with codemode's result conversion, it establishes
why perk's top-level termination contract does not survive composition. Perk's
[worker event adapter][sdk-adapter] does observe `tool_execution_end` events;
the defect is continued execution, not a claim that nested completion events vanish.

**Fix:** mark tools requiring a top-level workflow decision, terminal transition,
or human interaction as `exposure: "model-only"`. Start with the terminal delivery
tools and inventory the save/review/learning families that also return or propagate
termination. Pi documents `model-only` for interactive and orchestration tools.
Keep safely composable tools eligible for a separate, deliberate adoption decision.
Do not rely on `executionMode: "sequential"` as a substitute.

**Acceptance:** the affected tools remain declared in their eligible stages and
their ordinary calls still terminate correctly; they are absent from the nested
callable set and `ctx.executeTool()` refuses them. Cover codemode's `on` and `only`
modes, the direct worker completion path, cancellation, and failed non-terminating
results. Retain existing reviewed-artifact and publication checks. Record any
changed cross-plane completion behavior in [shared/contracts.md][contracts].

### F2 — preserve native tool-search activation during reconciliation

**Reproduced at the boundary.** Pi's [native `tool_search`][up-tool-search] activates
registered `codemode`/`deferred` tools by updating the active set. That choice is
intended to survive branch navigation, resume, and fork. Perk's
[`registerToolGating()`][gating] snapshots active tools and a census of registered
names when stage scoping or the read-only gate first engages. Its restoration
baseline recognizes live selection only for the enumerated `subagents_enable` and
`web_enable` owners, plus genuinely late registrations.

A native deferred tool is already in that first census but inactive. Native search
can activate it, yet perk's next reconciliation omits it from the baseline. A
recording host using the real perk gate and real released search tool produced:

| Step | Active tools |
| --- | --- |
| Enter read-write `implement` | `read`, `bash`, `tool_search` |
| Search reference documentation | Above, plus `mcp__reference__search` |
| Repeat `syncFromState("read-write", "implement")` | `read`, `bash`, `tool_search`; the discovered tool is lost |
| Control: never engage either perk scope | The discovered selection survives |

The trigger is reconciliation after activation, including applicable workflow
rebuilds and `resources_discover`; this is not a claim that every turn immediately
removes the tool. Nor is it a permission guarantee: Pi's `codemode` and `deferred`
tools remain callable from codemode while registered, even when their model-facing
declaration is removed.

**Fix:** extend selection ownership to native discovery using the public exposure
metadata. Preserve Pi's live selection of native deferred/codemode tools while
applying perk's existing stage eligibility and read-only policy. Keep initially
inactive ordinary tools inactive, retain the known supplier loaders' ownership,
and preserve late-registration and bare-session behavior. Replacing the baseline
with every registered tool would violate those requirements.

**Acceptance:** search then reconcile; search then tree/resume/fork restoration;
owner deactivation; gate entry and exit; stage changes; late registration; and
initially inactive ordinary tools. Existing lazy-loader refusal and adopted-child
restriction tests must still pass. Update the selection-ownership description in
contracts §8.40 when implementing the change.

### F3 — retain bounded nested-call evidence in learning transcripts

**Reproduced at the boundary.** Nested execution events have `parentToolCallId`, but
Pi does not persist a separate ordinary message for every nested tool result. Its
[session handler][up-session] attaches a bounded `nestedCalls` record to the parent
tool-result message. The [recorder][up-nested] retains call names, IDs, arguments
when within budget, status, duration, and bounded error text. It marks incomplete
records with `complete: false`; it does not provide all nested result bodies.

Perk's [JSONL read model][jsonl] ignores this new field, and its
[normalizer/renderer][normalize] therefore exposes only the outer codemode result.
The probe used Pi's actual recorder for a successful read, a failed write, and a
read whose oversized arguments were omitted. Passing that record through perk's
actual parser and renderer produced:

```text
Upstream: 3 nested calls; one error; complete=false.
Perk:     0 projected calls; outer is_error=false.
Rendered: <tool_result tool="codemode" error="false" id="result-entry">Script completed; error handled</tool_result>
```

The outer success can be correct when a script handles an error. The lost child
failure and missing-arguments indicator are still important learning evidence.
`raw_chars` correctly includes the unprojected bytes, so this is a projection loss,
not a broken transcript-size census. The session format remains version 3.

**Fix:** add a lenient, bounded nested-call projection and render it with its parent
association, status, and completeness. Preserve the outer result's own semantics;
an unsuccessful child must remain visible without automatically changing the
parent's success flag. Do not invent omitted arguments or reconstruct unavailable
child result bodies. Review downstream classification/selection so retained nested
failures actually reach the normalized learning input.

**Acceptance:** old transcripts remain equivalent; nested success, handled failure,
cancellation, missing/oversized arguments, incomplete/truncated records, and
malformed optional metadata degrade explicitly. Call IDs remain associated with
the parent, and raw-size accounting and branch selection remain correct. Pin the
test fixtures to the released `nestedCalls` grammar and update the evidence
contract if its externally observable rendering changes.

### Other compatibility checks and limits

| Surface checked | Result and required follow-up |
| --- | --- |
| Public SDK and model APIs | Source review found the consumed coding-agent exports retained. The new tool context extends the old context. Chat reads remain chat-only; old chat model objects may omit `type`. Perk has no references to the removed plural image-model/provider APIs listed in the ai changelog. A published-package typecheck remains required. |
| TUI API removals | Perk does not call `queryTerminalColorScheme`, `queryTerminalBackgroundColor`, or `parseOsc11BackgroundColor`, the APIs removed in 0.99.0. Visual compatibility with the new default theme remains untested. |
| Launch, settings, packages | The audited launch path does not depend on the removed built-in diagnostic spellings. `defaultTools` modifiers and built-in extension configuration are additive. Review Pi's changed `--no-extensions` semantics for any future pass-through use; the matching current perk flag handling is for **hunk**, a different executable. Pi's Node floor of 22.19.0 already existed in 0.87.0. |
| Read-only and child restrictions | Released nested calls pass through the session's normal tool-call hooks. Calling perk's actual hook with nested event IDs still rejected write, unknown MCP, codemode, and unsafe bash; read remained allowed. Native codemode and `tool_search` are absent from perk's read-only allowlist. No read-only bypass was reproduced. This is source tracing plus a hook probe, not a live nested-session certification. |
| Context, compaction, `/btw` seed | Existing canonical projection/seeding repairs remain appropriate. A released SessionManager source probe retained omission and replacement semantics. There is no reason to restore independent context replay. |
| Worker lifecycle | Existing service/runtime construction is still present upstream. Preserve deadlines, cancellation, budgets, terminal evidence, and disabled auto-compaction/retry. Baseline fake-provider tests passed; target worker behavior has not been certified. |
| Extension-registered native providers | The mirror includes a **[post-release fix][up-provider-fix]** for new sessions ignoring a saved default or reporting no available models with stored credentials. This is an upstream watch item for worker and side-session model selection, not a perk defect reproduced here. Test that case against the published target and do not assume the HEAD fix shipped in 0.99.1. |

Literal checks of the three installed suppliers' JavaScript/TypeScript sources
also found no references to those removed image and terminal-query APIs. This
narrows the known removal risks; it does not certify those packages on 0.99.1.

## 2. What can be simplified or removed

| Adaptation | Release evidence | Decision and retirement condition |
| --- | --- | --- |
| [Native SDK bridge][bridge] and [host namespace capture][host-sdk] | The [package manager][up-package-manager] now avoids automatic peer installation for managed Git packages; extension loading warns about host modules in `dependencies`. The released [extension loader][up-loader] retains the native JavaScript/jiti resolution behavior that motivated the bridge. Avoiding new duplicates does not give existing native consumers the host's class/namespace identity. | **Keep.** Its two consumers and eight-specifier census remain relevant. Retire only after an upstream supported identity seam passes real pi-subagents/pi-web-access imports, late imports, reload, multiple activation, and mismatch cases without the bridge. Do not infer retirement from the install warning. |
| Tool selection, stage census, lazy loaders | `exposure`, `defaultActive`, `prepareLoadout`, and discovery provide richer presentation/activation mechanisms. `prepareLoadout` can hide declarations while tools remain active and callable. | **Tighten via F1/F2; retain policy.** Native discovery may eventually replace supplier-specific lazy loaders when those suppliers adopt it. It does not replace perk's eligibility rules or allowlist. |
| [`/btw` live runtime probe][btw] | The released [ModelRegistry][up-registry] still holds its runtime privately; new classifier/image operations do not expose a supported side-session factory sharing that runtime. | **Keep the narrow probe.** Summary-only session construction is already gone: summarization uses public `streamSimple()`. A future public runtime/session-sharing API is the retirement condition. |
| [Report RPC stale/contextless-responder guards][rpc-adapter] | Subscription tracking and runtime invalidation already existed in 0.87.0. The new `RpcClient` listener-mutation fix concerns a different client/event path. No removal of trust-phase orphan responders was established. | **Keep.** Require an actual duplicate-discovery/trust/reload reproduction to pass without the guard before deleting it. |
| [Worker adapter][sdk-adapter] completion, cancellation, and budgets | Input dispositions and provider stream events add observation, not perk's workflow completion proof. | **Keep.** A receipt or idle event cannot replace successful `submit`/`finalize_address` evidence or the worker's terminal-result contract. |
| [Context evidence][context-evidence] and bindings | Canonical projection continues to supply edited active messages. | **Already simplified.** Keep perk's ownership/evidence predicates; avoid reimplementing the upstream projector. |
| Browser-review coordination | This Pi release supplies no replacement for Plannotator readiness, decision correlation, or server ownership. | **No release-driven deletion.** The separate browser-review consolidation proposal remains independent work. |

The realistic reduction opportunity is **future custom activation plumbing**, if
native discovery can carry a supplier's selection without weakening perk policy.
There is no evidence-backed deletion of a major adapter to include in this upgrade.

## 3. New features worth adopting

The priority order below is a recommendation, not a claim that these features have
already been integrated or measured.

| Priority | Candidate and proposed use | Scope and acceptance |
| --- | --- | --- |
| First | **`exposure: "model-only"`** for terminal and interactive workflow tools | Implement F1 before advertising codemode support. Preserve ordinary top-level workflow behavior. |
| Next | **`outputSchema`, `structuredContent`, and `isError`** for a small set of composable query tools | Codemode otherwise receives text; perk's existing `details.ok` is not a structured output contract. Review the [result seam][results], deliberately map success/error semantics, and prove direct callers and renderers still work. Do not blanket-convert terminal operations into script APIs. |
| Next | **Native discovery and deferred tools** to reduce declarations for large optional tool families | Repair F2, measure prompt-size savings and discoverability, then consider retiring specific lazy-loader glue only when the supplying package uses the native contract. |
| Bounded pilot | **Codemode and MCP** for independent research/read operations and batched tool work | F1–F3 precede the pilot. Choose an explicit tool/server allowlist and define interactive/worker/child availability. Verify cancellation, nested evidence, denied writes, and output limits. MCP `readOnlyHint` is author-supplied metadata, not a verified permission grant. |
| Bounded pilot | **Virtual models and classifiers** for per-request routing | Potentially useful for reviewer/planner cost and latency, but virtual models are experimental. Preserve explicit stage model overrides and account for actual physical models, thinking levels, and usage. Compare against deterministic role selection before adopting a router. |
| Optional diagnostics | **`provider_stream_event` and input dispositions** | Use bounded, opt-in diagnostics to explain provider errors and prompt/steer/follow-up acceptance. Test cleanup and redaction. Neither is successful workflow execution or a replacement for pi-subagents' separate event RPC. |
| Inherit, then inspect | **System theme, `theme.style`, colors, appearance, and TUI fixes** | Check footer, widgets, reports, and `/btw` in light/dark/system themes during the later live validation. Keep rich UI inside [surfaces][surfaces] and respect the existing [TUI charter][tui-charter]. |

There is an important SDK/CLI distinction in the [released SDK guide][up-sdk-doc]:
the CLI loads built-in codemode, tool search, and MCP extensions; **SDK sessions
must supply their factories explicitly**. Perk's worker constructs services without
those factories, and `/btw` deliberately uses an empty resource loader. Setting
`defaultTools: ["+codemode"]` alone will not install a missing worker tool. Decide
which session kinds should acquire these capabilities and test their lifecycle;
do not copy the parent's MCP resources into side sessions as an incidental upgrade.

Some benefits require no new perk feature. The SessionManager now flushes on the
first user message, preventing loss before the first assistant response. A source
probe observed no file after that input with installed 0.87.0 and a persisted file
with released 0.99.1 SessionManager code. Provider/catalog, clipboard, rendering,
and compaction maintenance fixes arrive through Pi. New OpenAI authentication and
model defaults do not automatically migrate perk's explicit provider/model choices;
test those choices in the later provider smoke work.

### Keep source experiments separate from release adoption

The refreshed checkout is useful research, but its `Unreleased` sections are not
0.99.1 capabilities. The native-provider credential fix described above, the
lightweight [`@earendil-works/pi-ai/models` entry point][up-models-entry], and durable runtime work
after the tag belong on a watchlist. In particular, the newer durable tool turns,
inbox/live view, and ownership/subagent behavior are post-release work.

The released coding-agent [manifest][up-package] exposes `./client` and
`./experimental/plugin` only under the `source` condition and excludes their dist
directories from the shipped file list. This is not a supported drop-in replacement
for perk's installed SDK adapter. AgentHarness/Chord/durable and remote attachment
remain separate architecture investigations with the retirement criteria from the
[integration memo][deep-opportunities], not prerequisites for adopting 0.99.1.

## Follow-up implementation order

1. **Obtain and validate the complete 0.99.1 package set in an isolated checkout.**
   Resolve all six coordinated pins and the lockfile together. Run the published
   type surface against perk, check extension loading, host identity, and the
   real installed suppliers. Add the native-provider saved-credential case to
   model-selection checks. Source probes cannot close this package-validation gap.
2. **Implement the three scoped fixes.** Add the model-only workflow boundary,
   preserve native discovered selections, and retain nested learning evidence with
   the acceptance cases above. Keep them reviewable as independent changes even
   if delivered with one baseline bump. Update shared contracts where behavior
   changes and user docs for the supported orchestration/configuration choices.
3. **Complete upgrade verification before claiming support.** Exercise cold/warm
   launch, reload/tree/resume, context edits/compaction, `/btw` seed and summary,
   worker success/cancel/budget, report waves, and browser-review lifecycle. Run the
   required repository gate on the implementation; a perk session uses the single
   final `run_ci` run. Provider/TUI/browser checks are future acceptance work, not
   part of this offline audit.
4. **Choose one adoption pilot.** Prefer structured query results plus bounded
   native discovery/codemode work. Measure usefulness and keep the adapter-retirement
   conditions explicit. Virtual routing and durable/remote architecture can proceed
   independently when their own evidence justifies them.

## Verification performed

| Check | Outcome | What it establishes |
| --- | --- | --- |
| `npm run typecheck` | Passed | Current source against installed **0.87.0** dependencies |
| Focused `node:test` selection | 570 cases; initially 564 passed and six worker E2E cases failed on home-directory writes | Baseline bridge, gating, context, bindings, scratch, `/btw`, SDK/worker, lifecycle, RPC, compaction, and surfaces coverage |
| Worker E2E retry with writable `PI_CODING_AGENT_DIR` and `PI_OFFLINE=1` | All seven cases passed, including the six initial failures | Those failures were sandbox `EPERM` creating `~/.pi/agent/sessions`, not target-release regressions; all 570 selected cases passed across the runs |
| Focused pytest selection | **230 passed** | Coordinated pin/bridge parity, learning JSONL, launch, and materialization baseline |
| Released search + current perk gate | Reproduced F2; bare-session control retained selection | Native activation is lost on an engaged reconciliation |
| Released nested runner/recorder + current perk hooks/parser | Reproduced continued calls after a terminating outcome and loss of nested evidence; read-only hook remained closed | The specific boundaries in F1/F3 and the negative permission control |
| Released SessionManager module | Canonical omission/replacement passed; first-user persistence improved; format version 3 | Narrow persistence/projection behavior with installed shared dependencies; `cross-spawn` resolved from the installed coding-agent package |

The exact baseline test selections were:

```sh
node --test --test-reporter=spec \
  extension/piAiCompatGuard.test.ts \
  extension/substrate/hostSdk.test.ts \
  extension/substrate/nativeSdkBridge.test.ts \
  extension/substrate/toolGating.test.ts \
  extension/substrate/stageTools.test.ts \
  extension/substrate/childRestrictions.test.ts \
  extension/pi/v1/contextEvidence.test.ts \
  extension/pi/v1/contextInjection.test.ts \
  extension/substrate/bindingDelivery.test.ts \
  extension/substrate/agentScratch.test.ts \
  extension/vendor/btw/btw.test.ts \
  extension/worker/sdkAdapter.test.ts \
  extension/worker/stageExecution.test.ts \
  extension/worker/stageExecutionE2e.test.ts \
  extension/session/workflowSession.test.ts \
  extension/session/lifecycle.test.ts \
  extension/waves/rpcAdapter.test.ts \
  extension/waves/adapterContract.test.ts \
  extension/pi/v1/draftCompact.test.ts \
  extension/pi/v1/delivery/commitCompact.test.ts \
  extension/surfaces/surfaces.test.ts \
  extension/surfacesGuard.test.ts

uv run --no-sync pytest -n0 \
  tests/test_packaging.py::test_pi_toolchain_pin_lockstep \
  tests/test_native_sdk_bridge_parity.py \
  tests/test_learn_session_jsonl.py \
  tests/test_launch.py \
  tests/test_launch_materialize.py -q
```

For the sandboxed runs, `UV_CACHE_DIR` and the worker retry's
`PI_CODING_AGENT_DIR` pointed to separate writable scratch directories. The
deterministic probes and logs were kept in temporary scratch, not installed into
perk or the library. To recreate the source probes, verify the imported files
against the target tag first; use a recording ExtensionAPI for F2, a controlled
`runToolCall` port for F1, and actual `NestedCallRecorder` output passed to
`SessionEntryModel.to_domain()`/`render_entry()` for F3. None of these substitutes
for the published-package validation above.

[package]: ../../package.json
[previous]: ./pi-assessment-2026-09-21.md
[deep-opportunities]: ./deep-opportunities-pi-integration.md
[contracts]: ../../shared/contracts.md
[gating]: ../../extension/substrate/toolGating.ts
[submit]: ../../extension/pi/v1/delivery/submit.ts
[ready]: ../../extension/pi/v1/delivery/ready.ts
[land]: ../../extension/pi/v1/delivery/land.ts
[address]: ../../extension/pi/v1/delivery/address.ts
[jsonl]: ../../src/perk/learn/session_jsonl.py
[normalize]: ../../src/perk/learn/normalize.py
[bridge]: ../../extension/substrate/nativeSdkBridge.ts
[host-sdk]: ../../extension/substrate/hostSdk.ts
[btw]: ../../extension/vendor/btw/btw.ts
[rpc-adapter]: ../../extension/waves/rpcAdapter.ts
[sdk-adapter]: ../../extension/worker/sdkAdapter.ts
[context-evidence]: ../../extension/pi/v1/contextEvidence.ts
[results]: ../../extension/substrate/result.ts
[surfaces]: ../../extension/surfaces/surfaces.ts
[tui-charter]: ../design/tui-charter.md
[release]: https://github.com/earendil-works/pi/releases/tag/v0.99.1
[up-changelog]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/CHANGELOG.md
[up-ai-changelog]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/ai/CHANGELOG.md
[up-tui-changelog]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/tui/CHANGELOG.md
[up-types]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/extensions/types.ts
[up-nested]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/nested-tool-calls.ts
[up-codemode-execute]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/extensions/codemode/execute.ts
[up-tool-search]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/extensions/tool-search/tool.ts
[up-session]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/agent-session.ts
[up-loader]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/extensions/loader.ts
[up-registry]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/model-registry.ts
[up-sdk-doc]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/docs/sdk.md
[up-package]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/package.json
[up-package-manager]: https://github.com/earendil-works/pi/blob/d86654abb8862e201933517d6f1fce9f88dd117f/packages/coding-agent/src/core/package-manager.ts
[up-provider-fix]: https://github.com/earendil-works/pi/commit/fddc968b96052176e0f570949df2bdfdd700c740
[up-models-entry]: https://github.com/earendil-works/pi/commit/ba7d5fbedb1864c1d6e1b26910b95b1634a665c9
