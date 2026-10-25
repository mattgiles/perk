# Plannotator integration assessment — September 5, 2026

Assessment baseline: Perk [`34f5c168`](https://github.com/mattgiles/perk/tree/34f5c168), locally installed `@plannotator/pi-extension` **0.27.12**, and the **August 22–September 5, 2026** release window. This is a maintainer assessment and ranked proposal; it implements no integration changes. Release dates below use GitHub publication timestamps in UTC.

**Executive recommendation.** Keep Perk's structured authoring, approval, and publishing authority, with Plannotator providing the browser review surface. Repair approval-note loss first, then establish compatibility checks against the installed package and recoverable, explicitly owned review sessions. Standardize feedback handling while retaining each subject's save policy. Experiment with document review before expanding into HTML, browser agents, or embedded UI. Replacing Perk's planning lifecycle with native Plannotator planning is a larger architectural choice with substantial migration costs. The evidence supports improving the existing boundary before moving it: current annotation payloads remain compatible, but new upstream decision semantics expose a concrete downstream defect. [Perk bridge][p-bridge], [response handlers][p-handoff], [upstream decisions][u-decision].

## 1. How Perk uses Plannotator today

Package selection belongs to Perk's exterior. The provider registry maps `[providers] plan = "plannotator-plan"` to `npm:@plannotator/pi-extension`; `perk init` converges the desired package union into Pi settings. This checkout selects that provider and loads the whole extension without a version pin. Browser code review depends on the package being present, independently of which plan provider is selected. Perk detects presence through the registered `plannotator-review` command. [Provider registry][p-providers], [settings][p-settings], [handoff][p-handoff].

Inside Pi, Perk emits the documented `plannotator:request` event. `plan-review` returns a pending `reviewId`, then publishes the decision on `plannotator:review-result`; `code-review` invokes its response callback when review finishes. These are distinct asynchronous contracts. Perk does not invoke another extension's slash command. Its plan adapter augments Perk's authoring lifecycle, yielding the colliding `--plan` flag and `Ctrl+Alt+P` shortcut while keeping Perk's `/plan`, draft tools, gate, and save machinery. [Adapter][p-bridge], [installer][p-plan], [event API][u-events].

Perk's draft tools own the working artifacts: plan markdown and structured objective/gist JSON, rendered as markdown for review. `plan_review` prefers the validated artifact; its `plan` argument is a plan-only fallback. Plannotator returns the human's decision, while Perk's save composition persists the appropriate subject and exits the gate only after success. Upstream history or a returned `savedPath` does not replace that authority. [Plan dispatcher][p-plan-review], [objective review][p-objective], [gist review][p-gist].

| Entry point | Subject | Transport | Lifecycle | Save/publish authority | Assessed coverage |
|---|---|---|---|---|---|
| `plan_review` | Plan draft | Plan event + decision event | Blocking review, or optional streamed wave | Perk approval-save; manual `/plan-save` fallback | Bridge tested; save implementation read |
| `plan_review` | Objective draft | Same plan transport | Render structured artifact; review; save or revise | Perk objective save; structured edits require another review | Bridge tested; objective implementation read |
| `plan_review` | Gist draft | Same plan transport | Render title/scope/prose; review; save or revise | Perk gist save; structured edits require another review | Bridge tested; gist implementation read |
| `/plan-review-browser`, `/objective-review-browser` | Current draft | Plan events + annotation HTTP | Open, prime, stream wave, observe decision, clear | Perk subject-specific save, with stale-draft checks | Both door files tested |
| `/pr-review-browser` active/foreign | One PR | Code event + annotation HTTP | Active worktree or detached checkout; streamed review | Human posts through Plannotator; Perk posting only by policy | Bridge/push tested; door implementation read |
| `/pr-review-browser` before PR | Local since-base diff | Code event only | Background review; no wave or annotation priming | Local feedback; no attached PR | Response helper tested; door implementation read |
| `/stack-review-browser`, `open_stack_review` | Combined stack diff | Code event + annotation HTTP | Detached top head; since-base against `origin/<base>`; wave | Perk routes approved batches to individual PRs | Response/push tested; stack implementation read |

The annotation channel is separate from decisions. Perk's `push_annotations` posts mapped batches to `/api/external-annotations`; source-scoped DELETE implements replacement. Upstream distributes changes to the browser through SSE. Perk owns finding validation, deduplication, retries, and its active surface handle; Plannotator owns the HTTP server and browser state. Foreign/stack checkout cleanup remains a Perk guidance-driven action; active worktrees are retained. Upstream additionally manages its own PR checkout pool. [Annotation provider][p-annotations], [upstream HTTP][u-annotations], [PR lifecycle][p-browser], [stack lifecycle][p-stack], [browser sessions][u-browser].

## 2. What works well

Perk has a valuable authority boundary. A browser approval enters a subject-specific save path; it does not itself replace an objective's structured roadmap or publish arbitrary reviews. Plans can apply a clean Direct Edits patch to the reviewed bytes. Objectives and gists require model-mediated reconciliation into their structured fields and another review when Direct Edits are present. Streamed draft reviews reject stale approvals after the underlying artifact changes. These distinctions protect artifact meaning rather than merely enforcing UI consistency. [Plan review][p-plan-review], [objective review][p-objective], [gist review][p-gist], [draft browser][p-plan-browser].

Rendered drafts let reviewers judge the assembled document rather than its storage format. Source badges distinguish Perk findings from human comments. The annotation provider structurally limits deletion to `perk:<angle>`, preserves alternate findings during cross-source reconciliation, and accumulates batches while startup is pending. Shared code serves PR/stack review and both draft modes. Failures produce an in-session review route; draft degradation also blocks a late browser approval from unexpectedly saving. [Annotation provider][p-annotations], [draft readiness][p-plan-browser].

The installed browser already supplies rich rendering, direct editing, human annotation undo, automatic viewed-state tracking, code references/hover cards, and optional Ask AI/Guided Review facilities. Perk need not rebuild these features to expose them through its existing opens. Availability still depends on the surface and prerequisites: symbol navigation needs useful repository context and ripgrep; AI facilities need configured providers. These are inherited upstream capabilities, not features exercised live in this assessment. [Release ledger](#appendix-a-release-ledger), [upstream browser implementation][u-browser].

## 3. Limitations and inelegance

**Confirmed defect: approval notes are lost in PR and stack response handling.** Both `respondMessage` and `stackRespondMessage` return their approval-only message when `approved` is true and decoded annotations are empty, ignoring nonempty `feedback`. The offline probe reproduced this through the actual Perk bridge and both handlers. Upstream's `buildReviewApprovalBody` explicitly produces this shape for “Approve with a note…”. This concerns feedback returned to Perk; it does not demonstrate loss of a review posted directly to GitHub. [Handlers][p-handoff], [upstream payload builder and platform routing][u-review-decision].

**Accepted tradeoffs, with costs.** Perk presets process-global `PLANNOTATOR_PORT` to discover the annotation endpoint, then polls a surface-specific route. It temporarily intercepts global `console.error` to protect Pi's terminal rendering. The interceptor has restoration and reentrancy guards, but neither mechanism is a session-addressed integration API. Selecting and releasing a free port before upstream binds also leaves a reservation gap. [Open core][p-handoff], [console capture][p-console].

Direct Edits arrive as formatted prose containing a heading and fenced unified diff. Perk deliberately parses the structure, ignores variable preamble wording, and applies patches strictly. This remains coupling to an export format. Failed plan application still attempts to save the original plan with a warning; objectives/gists instead stop saving and request structured reconciliation. These existing policies should be evaluated explicitly, not accidentally unified during refactoring. [Parser][p-bridge], [plan save policy][p-plan-policy], [objective policy][p-objective].

**Untested lifecycle risks.** One activation shares a mutable annotation surface. Priming replaces it; an older review's unconditional cleanup can clear a newer surface. Concurrent port overrides can also restore stale environment values. Source inspection establishes the opportunity for interference; no overlapping live-session failure was reproduced. Perk cancellation settles its waits and removes listeners, but the public request envelope has no cancellation operation. Exported upstream session helpers have `stop`/signal capabilities that Perk's event path does not receive. [Annotation state][p-annotations], [cleanup][p-browser], [session helpers][u-browser].

The plan bridge subscribes after the handshake and never queries upstream's available `review-status` recovery action. A missed decision or interrupted wait therefore lacks Perk-level recovery. Code review has neither a comparable status contract nor a bounded handshake. The readiness poll's nominal 120-second budget bounds attempts; an individual fetch has no separate deadline. These are recovery gaps, not evidence that ordinary reviews fail. [Bridge][p-bridge], [readiness][p-handoff], [status API][u-events].

Feedback also loses structure. Returned code annotations retain coordinates and six optional strings, dropping IDs, timestamps, richer context, and other metadata. Plan decisions retain only ID, approval, and text. Deduplication intentionally excludes diff side and can merge different findings at one anchor. Pre-PR review omits waves and readiness discovery, while draft flows add stronger feedback delimiters and save guards. Some differences serve workflow needs; the inconsistent lifecycle and provenance handling do not. [Decoder][p-handoff], [mapping][p-annotations], [draft routing][p-plan-browser].

## 4. Four major recent changes

### Unified decisions, approval notes, and general comments

[v0.27.12](https://github.com/backnotprop/plannotator/releases/tag/v0.27.12) introduces a shared adaptive decision control: the primary action follows current feedback state; alternatives and note composers sit behind its menu. Bare approvals no longer send placeholder feedback. The server advertises approval-note support, and review-level general comments preserve scope in archives. Perk's installed browser inherits this UI, but its PR/stack consumers still violate the note-delivery contract. An upstream capability advertisement cannot verify a downstream callback consumer. [Decision specification][u-decision], [decision tests][u-decision-tests], [server delivery tests][u-approval-tests].

Agent-directed decisions and platform posting remain different transports. Despite the menu label “Request changes…”, tagged platform routing still opens a **comment** submission; it does not add formal GitHub `REQUEST_CHANGES`. Perk's exceptional posting path therefore remains relevant. Preserve both the approval verdict and its nonblocking guidance when adapting responses. [Transport routing][u-review-decision].

### WebMCP document tools and threaded comments

[v0.27.9](https://github.com/backnotprop/plannotator/releases/tag/v0.27.9) adds a feature-detected catalog on `document.modelContext` for plans and annotate surfaces. `read_document` supplies windowed text, outline, comments, and state nudges; companion tools add, update, remove, reveal, and reply to comments, with folder listing where applicable. Replies use `inReplyTo` and survive feedback export as threads. [Document tools][u-document-tools], [catalog tests][u-webmcp-tests].

The human still approves, submits, closes, stages, and marks viewed: none of those actions belongs to this tool catalog. Browser agents may modify only their own comments, and tools are not registered inside reviewed iframes. Code review remains excluded at v0.27.12. Consequently, this can augment draft-review collaboration today in a compatible browser; it cannot replace Perk's PR annotation delivery. Browser capability and actual session behavior remain unverified locally. [Browser adapter][u-model-context], [catalog tests][u-webmcp-tests], [iframe isolation tests][u-iframe-tests].

### Reusable document/HTML UI and host integration

Also in v0.27.9, `HtmlSurfaceControls`, `useHtmlRefresh`, anchor projection/persistence helpers, and unanchored-comment indicators let hosts reuse more of Plannotator's HTML experience. Lazy diagram/math loading and an optional separately served iframe bridge reduce host integration costs. Local raw-HTML annotation gains manual Refresh with annotation restoration; this is not automatic live-app refresh, and HTML source saving remains disabled. [Host API][u-ui-readme], [refresh implementation][u-refresh], [refresh tests][u-refresh-tests].

These are opportunities for Perk's prose workbench, not an already embedded editor. Its fragment identities, assembly previews, source adapters, and validated save pipeline remain distinct responsibilities. The release tag contains `@plannotator/ui` **0.38.0**, whereas the npm registry currently publishes **0.37.0**. An experiment must use and test the published artifact rather than infer availability from the monorepo manifest. [Tagged manifest][u-ui-package], [npm artifact][npm-ui], [workbench contract][p-workbench].

### Durable local feedback archives and provenance

[v0.27.11](https://github.com/backnotprop/plannotator/releases/tag/v0.27.11) adds project-organized feedback under `~/.plannotator/feedback/` (or the configured data directory): an append-only `index.jsonl` and readable sidecars for content-bearing submissions. Decision-only records need no sidecar. Records carry surface, decision, client, annotations, and available target provenance; code records describe the reviewed target without copying the whole diff. Archiving defaults on, can be disabled with `PLANNOTATOR_FEEDBACK_HISTORY=0` or `feedbackHistory: false`, and must not block submission when writing fails. [Archive schema/writer][u-archive], [Pi handler tests][u-archive-tests], [privacy policy](https://plannotator.ai/privacy).

This supplies recovery evidence and potential learning inputs, not a Perk audit trail. The event plan handler does not forward Perk's `origin` or `planFilePath`; its browser helper supplies `origin: "pi"`. `clientVersion` is reserved but not populated by the shared writer, and checkout paths can disappear. Perk run, artifact revision, objective node, and stack-member mapping still need explicit correlation. Future learning must enter Perk's `/learn` workflow. [Event handler][u-events], [browser helper][u-browser], [archive schema][u-archive].

The remaining changes are recorded in Appendix A. In particular, native Pi's append-only phase framing fixes upstream's own conversation-cache lifecycle. Perk's separate gate, injected context, and approval-save flow do not automatically acquire that behavior. The installed README still describes filtering old framing; tagged implementation and its prefix-stability test take precedence. [Phase tests][u-phase-tests], [Perk adapter][p-bridge].

## 5. More idiomatic existing usage

Treat the documented event channel as the supported extension boundary. Exported functions such as `startCodeReviewBrowserSession` are useful implementation evidence, but importing them directly would couple Perk to upstream context, packaging, and lifecycle internals. Prefer an upstream event capability that returns session identity, URL, cancellation, and progress. Existing `review-status` already provides a narrower, immediately useful recovery path for plan decisions. It does not recover code reviews or establish whether a crashed server behind a pending record is alive. [Public contract and status storage][u-events], [exported helpers][u-browser].

**Repair now** — effort is relative implementation scope; availability codes are defined in Appendix B.

| Rank | Recommendation and benefit | Workflows; effort; dependencies/availability | Concrete validation |
|---|---|---|---|
| R1 | Preserve approval notes and explicitly frame them as nonblocking guidance. Evidence: confirmed loss and upstream payload builder. [Handlers][p-handoff], [builder][u-review-decision] | PR, stack; small; installed behavior **I**, local adapter change **L** | Return approval with text and zero annotations; verify exact note delivery, approval retained, and no automatic GitHub post. |
| R2 | Exercise installed contracts, replacing historical compatibility assumptions with evidence. [Current payload mapping][p-annotations], [upstream transforms][u-annotations] | All reviews; medium; installed package **I**, test harness **L** | Run actual transforms and decision builders for line/file/general and phrase/global findings, notes, bare approval, exit, and Direct Edits; check package version in failures. |
| R3 | Persist pending review identity plus subject/revision; query `review-status` after subscription and on recovery, with idempotent delivery. [Status contract][u-events] | Plan/objective/gist reviews; medium; existing API **I**, Perk correlation **L** | Deliver decision before listener registration, then restart; recover once, reject a changed draft, and never save twice. |

## 6. More consistent usage

A common lifecycle should represent opening, ready, completed, degraded, and cancelled states, with cleanup conditional on the owning session. A common feedback envelope should retain decision, text, annotation identity, source, scope, and target revision. Neither abstraction should decide how a subject is saved or where a review is posted.

Keep explicit policies: plan patch application; objective/gist structured reconciliation; PR platform posting; stack per-PR routing; pre-PR local feedback. Preserve human and machine provenance through round trips, with untrusted-feedback framing across entry points. Align commands, prompts, skills, and compatibility guidance together. Any future cross-plane change must amend `shared/contracts.md`; user-facing/provider changes must update the corresponding user docs and `perk-expert` mirror. [Current review contract][p-contract], [repository rules][p-agents].

**Standardize next.**

| Rank | Recommendation and benefit | Workflows; effort; dependencies/availability | Concrete validation |
|---|---|---|---|
| S1 | Introduce session-owned cleanup and seek explicit URL/cancel/progress event capabilities, removing global discovery workarounds. [Open core][p-handoff], [session helpers][u-browser] | Streamed drafts, PR, stack; medium–large; ownership guard **L**, public capabilities **U** | Open A then B; complete/abort A; B's endpoint, queue, and console behavior survive. Cancellation closes only its upstream server. |
| S2 | Share lifecycle/feedback handling with named subject policies; retain IDs, reply relations, scope, revision, and source. Reassess anchor-only deduplication. [Mapping][p-annotations], [subject policies][p-plan-review], [threads][u-document-tools] | All reviews; medium; adapters/guidance **L**, structured edits/enriched plan events **U** | Round-trip two findings on opposite diff sides and a threaded reply; exercise each subject's approve/edit/deny/exit policy and verify only intended artifacts/posts change. |

## 7. Broader usage

Rank experiments by how much existing capability they can reuse without taking over Perk's workflow. Document/folder and last-response review have the shortest path. Generated HTML and live applications need distinct handling: the native Pi annotate command performs loading and live-app detection, whereas the event `annotate` handler does not reproduce that complete launcher. A URL-shaped event request must not be assumed to create a live proxy. [Native command][u-native], [event implementation][u-events].

**Experiment later**, in this order:

| Rank | Opportunity and benefit | Workflows; effort; dependencies/availability | Concrete validation |
|---|---|---|---|
| E1 | Document/folder and last-response review: reuse annotations for maintainer docs and explanations. [Events][u-events] | Docs/messages; small–medium; **I/L**, native loading **N** | Review two files and a selected response; preserve target identity and distinguish feedback from approval. Use gate mode when approval is intended. |
| E2 | Generated HTML/live-app review: annotate reports and running interfaces. [Native launcher][u-native], [refresh][u-refresh] | Reports/UI QA; medium; **N/L**, event parity **U** | Refresh rewritten HTML with one broken anchor; keep its comment. Separately verify localhost HMR/navigation and graceful remote-mode refusal. |
| E3 | Browser-agent collaboration: contextual draft discussion beside the human. [Document tools][u-document-tools] | Drafts/docs; medium; compatible browser **W**, integration **L** | Agent replies to a human comment but cannot alter it or approve; human decision returns through Perk. Confirm code-review exclusion. |
| E4 | Feedback-informed learning: recover review rationale and recurring issues. [Archive schema][u-archive] | Post-land `/learn`; medium; archive **I**, provenance joins **L** | Correlate a record with a landed Perk change, separate human/machine comments, and feed a candidate through `/learn`; write no ad hoc learned document. |
| E5 | Guided Reviews: explain a complex diff and preserve a portable walkthrough. [Guide export tests][u-guide] | PR/stack comprehension; medium; browser **I**, provider/CLI prerequisites **N** | Generate/export/reopen a guide; verify its revision and links against the stack snapshot before treating it as review evidence. |
| E6 | Reusable UI in the prose workbench: improve rendered preview/commenting. [Host APIs][u-ui-readme], [workbench][p-workbench] | Workbench; large; published packages **P**, adapter **L** | Embed one read-only assembled preview; test CSP, anchors, refresh, and actual npm imports; preserve existing validated source-save authority. |
| E7 | Native Plannotator planning: evaluate a different authoring owner. [External execution][u-native] | Plan lifecycle; large; native mode **N**, translation/gates **L** | Approve a native plan in external execution mode; validate/translate it once into Perk, with no duplicate execution or save. |

Native planning would give Plannotator responsibility for the markdown plan file, phase models/tools, review submission, and possibly execution/checklist progress. Its external execution mode emits `plannotator:plan-approved` and returns to idle, providing a plausible handoff for Perk to retain implementation, worktrees, issue storage, objectives, and delivery trains. Perk would relinquish or reimplement its current authoring injections, structured draft invariants, and approval-save composition. Native planning also permits unrestricted Bash under guidance, unlike Perk's enforced read-only boundary. Perk currently excludes `plannotator_submit_plan` from its stage allowlists, so this is an explicit redesign, not a configuration shortcut. [Native lifecycle][u-native], [Perk gate contract][p-contract].

## Appendix A. Release ledger

The earlier **August 12 v0.27.0** Pi rebuild, **August 17 v0.27.4** portable Guided Reviews, and **August 21 v0.27.5–0.27.6** live-app rollout are context outside this window. [Rebuild](https://github.com/backnotprop/plannotator/releases/tag/v0.27.0), [guides](https://github.com/backnotprop/plannotator/releases/tag/v0.27.4), [live app on Pi](https://github.com/backnotprop/plannotator/releases/tag/v0.27.6).

| Release; UTC date | Changes and applicability | Tagged implementation/test evidence |
|---|---|---|
| [0.27.7](https://github.com/backnotprop/plannotator/releases/tag/v0.27.7); Aug 23 | Provider pipe failure containment; Call Flow cap/degradation; JJ fork-point base; knowledge skill/llms.txt; oh-my-pi origin. Browser/provider improvements are inherited where used; JJ/OMP are not Perk's Git workflow. | [Child I/O](https://github.com/backnotprop/plannotator/blob/v0.27.7/packages/ai/providers/child-io.ts), [real-process regression](https://github.com/backnotprop/plannotator/blob/v0.27.7/packages/ai/providers/pi-stdio-failure.test.ts) |
| [0.27.8](https://github.com/backnotprop/plannotator/releases/tag/v0.27.8); Aug 24 | Append-only Pi phase framing preserves cache; restricted HTML thumbs-up returns; published embed picker seam. Native phase fix does not modify Perk authoring. | [Pi lifecycle](https://github.com/backnotprop/plannotator/blob/v0.27.8/apps/pi-extension/index.ts), [prefix regression][u-phase-tests] |
| [0.27.9](https://github.com/backnotprop/plannotator/releases/tag/v0.27.9); Aug 27 | WebMCP/threads; HTML refresh/host APIs; lazy rendering/bridge asset; faster atomic-editor entry; Windows uninstall repair. QA fixes include share race, unreadable HTML fallback, refresh diff retention, touch controls, reply cycles. UI publishes progress through 0.34.0. | [Document tools][u-document-tools], [catalog tests][u-webmcp-tests], [refresh][u-refresh], [refresh tests][u-refresh-tests] |
| [0.27.10](https://github.com/backnotprop/plannotator/releases/tag/v0.27.10); Aug 31 | Annotation undo/redo; automatic viewed tracking; stale share-link fix; npm 12 terminal build repair; OpenCode 2 command/URL fixes; Herdr introduction and marketing forced-colors fix. Viewed marks respect dwell, manual unview, and changed content. | [Viewed logic](https://github.com/backnotprop/plannotator/blob/v0.27.10/packages/review-editor/utils/autoViewed.ts), [viewed tests](https://github.com/backnotprop/plannotator/blob/v0.27.10/packages/review-editor/utils/autoViewed.test.ts), [undo tests](https://github.com/backnotprop/plannotator/blob/v0.27.10/packages/ui/utils/undoHistory.test.ts) |
| [0.27.11](https://github.com/backnotprop/plannotator/releases/tag/v0.27.11); Sep 1 | Local feedback archive; lazy, private, cleaned-up OpenCode AI servers; unknown CLI command refusal; UI 0.35.2/core 0.25.1 repair broken publishes and add Quick Label hiding; privacy documentation. The resource fix concerns upstream AI providers. | [Archive writer][u-archive], [Pi archive tests][u-archive-tests], [provider tests](https://github.com/backnotprop/plannotator/blob/v0.27.11/packages/ai/providers/opencode-sdk.test.ts) |
| [0.27.12](https://github.com/backnotprop/plannotator/releases/tag/v0.27.12); Sep 3 | Unified decisions, notes, general comments; symbol hover and side references; local-vs-remote diff from fetched refs; OpenCode notice queue fix; gate guidance; insecure-context IDs; Escape handling. New diff choice does not change Perk's forced since-base opens. | [Decisions][u-decision], [decision tests][u-decision-tests], [approval delivery tests][u-approval-tests], [hover tests](https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/review-editor/hooks/useTokenHover.test.tsx) |

## Appendix B. Availability matrix

| Code | Available surface | Boundary |
|---|---|---|
| **I** | Installed Pi 0.27.12: events, annotation HTTP, bundled review UI, archives | Already installed; no inference of live verification. [Package][u-pi-package] |
| **N** | Native-command lifecycle: planning, file/URL loading, live-app detection; standalone guide CLI where installed | Perk's present events do not expose complete native launcher behavior. [Launcher][u-native], [events][u-events] |
| **W** | Browser WebMCP document tools | Requires `document.modelContext`; human decisions excluded; no code-review catalog. [Adapter][u-model-context] |
| **P** | Published `@plannotator/ui` and core host APIs | npm UI **0.37.0** observed September 5; tag UI **0.38.0** is not the published artifact. [npm][npm-ui], [tag][u-ui-package] |
| **U** | Proposed upstream session/cancellation, richer provenance/edit contracts, launcher parity | Not shipped public capabilities; requires upstream agreement and implementation. [Current event types][u-events] |
| **L** | Proposed Perk adapters, state, tests, or guidance | Local engineering work recommended here, not implemented. |

## Appendix C. Completed verification and limits

On September 5, the five focused `node:test` files passed: **146 tests, zero failures/skips**. This verifies existing offline contracts, not every workflow end to end. Reproduce from the repository root:

```sh
node --test extension/pi/v1/providers/{plannotator,plannotatorHandoff,annotations}.test.ts extension/pi/v1/{planReviewBrowser,objectiveReviewBrowser}.test.ts
```

The installed version came from `.pi/npm/node_modules/@plannotator/pi-extension/package.json`; `npm view @plannotator/ui version --json` returned `"0.37.0"`. Release timestamps and source paths were checked through `gh api` against the release tags.

An offline compatibility probe fed Perk's mapped line, file, and general code findings plus phrase and global plan findings through the **installed 0.27.12** `transformReviewInput`/`transformPlanInput`: all five shapes passed. The generated parser and its thread helper were copied byte-for-byte outside `node_modules` for Node's TypeScript loader. This checked parsers, not HTTP/SSE delivery.

A second probe returned `{approved: true, feedback: "Approved, but document the retry limit.", annotations: []}` through `requestPlannotatorCodeReview`. The bridge retained the note; both response mappers dropped it. Upstream's tagged approval builder independently establishes that this is a real supported payload shape. [Builder/tests](https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/review-editor/reviewDecision.test.ts).

Live browser opening, overlapping sessions, cancellation, restart recovery, WebMCP, GitHub posting, archive creation from a Perk session, and embedded-package behavior remain **unverified**. Upstream tests were inspected as evidence, not reported as locally executed. This documentation-only change does not claim a full CI run. The assessment contains seven substantive sections, exactly four recent-change themes, all six releases, and ranked recommendations with evidence, availability, dependencies, effort, and validation scenarios.

[p-bridge]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/providers/plannotator.ts
[p-handoff]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/providers/plannotatorHandoff.ts#L345
[p-providers]: https://github.com/mattgiles/perk/blob/34f5c168/shared/providers.yaml#L120
[p-settings]: https://github.com/mattgiles/perk/blob/34f5c168/.pi/settings.json
[p-plan]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/plan.ts
[p-annotations]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/providers/annotations.ts
[p-browser]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/codeReview/browser.ts
[p-stack]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/codeReview/stack.ts
[p-plan-review]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/planReview.ts
[p-plan-policy]: https://github.com/mattgiles/perk/blob/34f5c168/extension/authoring/plan/review.ts
[p-objective]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/objectiveReview.ts
[p-gist]: https://github.com/mattgiles/perk/blob/34f5c168/extension/authoring/gist/review.ts
[p-plan-browser]: https://github.com/mattgiles/perk/blob/34f5c168/extension/pi/v1/planReviewBrowser.ts
[p-console]: https://github.com/mattgiles/perk/blob/34f5c168/extension/substrate/consoleCapture.ts
[p-contract]: https://github.com/mattgiles/perk/blob/34f5c168/shared/contracts.md
[p-agents]: https://github.com/mattgiles/perk/blob/34f5c168/AGENTS.md
[p-workbench]: https://github.com/mattgiles/perk/blob/34f5c168/docs/design/prose-review-stack.md
[u-pi-package]: https://github.com/backnotprop/plannotator/blob/v0.27.12/apps/pi-extension/package.json
[u-events]: https://github.com/backnotprop/plannotator/blob/v0.27.12/apps/pi-extension/plannotator-events.ts
[u-browser]: https://github.com/backnotprop/plannotator/blob/v0.27.12/apps/pi-extension/plannotator-browser.ts
[u-annotations]: https://github.com/backnotprop/plannotator/blob/v0.27.12/apps/pi-extension/server/external-annotations.ts
[u-decision]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/ui/utils/decisionSpec.ts
[u-decision-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/ui/utils/decisionSpec.test.ts
[u-review-decision]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/review-editor/reviewDecision.ts
[u-approval-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/server/review-approval-notes.test.ts
[u-document-tools]: https://github.com/backnotprop/plannotator/blob/v0.27.9/packages/editor/webmcp/documentTools.ts
[u-webmcp-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.9/packages/editor/webmcp/documentTools.test.ts
[u-iframe-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.9/packages/ui/webmcp/iframeIsolation.test.ts
[u-model-context]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/ui/webmcp/modelContext.ts
[u-ui-readme]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/ui/README.md
[u-refresh]: https://github.com/backnotprop/plannotator/blob/v0.27.9/packages/ui/hooks/useHtmlRefresh.ts
[u-refresh-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.9/packages/ui/hooks/useHtmlRefresh.test.tsx
[u-ui-package]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/ui/package.json
[npm-ui]: https://www.npmjs.com/package/@plannotator/ui/v/0.37.0
[u-archive]: https://github.com/backnotprop/plannotator/blob/v0.27.11/packages/shared/feedback-archive.ts
[u-archive-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.11/apps/pi-extension/server/feedback-archive.test.ts
[u-phase-tests]: https://github.com/backnotprop/plannotator/blob/v0.27.8/apps/pi-extension/phase-prompts.test.ts
[u-native]: https://github.com/backnotprop/plannotator/blob/v0.27.12/apps/pi-extension/index.ts
[u-guide]: https://github.com/backnotprop/plannotator/blob/v0.27.12/packages/server/guide-export-e2e.test.ts
