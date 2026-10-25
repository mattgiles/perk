# Plannotator release assessment — 2026-09-21

Status: proposed follow-up work, based on released source, installed artifacts, and
annotation-transform probes. No provider behavior or runtime package changes here.

Use **Plannotator 0.27.17 as the next minimum supported baseline**, coordinated with
Pi 0.87.0 and pi-subagents 0.70.1. No breaking change was found in the event contracts
or annotation operations that perk currently uses. There is also no demonstrated
reason to delete perk's browser readiness, review identity, or save-policy guards.

The strongest adoption candidate is the new `patchFile` event payload: open stack
review from an artifact generated from the captured stack snapshot. This can remove
the browser's dependence on a later moving branch/merge-base calculation. Ordinary
PR review should keep its existing PR mode and platform posting. Diagram comments
and reduced background remote probes mostly arrive through the package upgrade.

## Snapshot and evidence

Perk was assessed at 3.5.0, commit
`8e0843fa597996c0693fd9a1547a4a0f6c30c829`. Release publication dates were verified
through `gh`; the 0.27.17 release was published on September 21 even though its
commit was authored earlier.

| Release | Published, UTC | Release commit | Relevant scope |
| --- | --- | --- | --- |
| [0.27.14][release-02714] | September 11 | `421c6af4cde06e8c12e75b3c6a86e6765f469009` | Pre-week comparison baseline |
| [0.27.15][release-02715] | September 15 | `bcffccb403e24e49b82936248be6679eea614119` | Executable browser scripts on macOS |
| [0.27.16][release-02716] | September 18 | `01eb347daecc143b37f67f0f7ba8098111dac879` | Static patch review; themed Mermaid and diagram anchors |
| [0.27.17][release-02717] | September 21 | `8f2a8a81a384f1cd39c5f083d3c6fcd35a956422` | Diagram files, RPC URL notifications, reduced idle remote probing, UI fixes |

Both perk's and Savant's local `@plannotator/pi-extension` installations are
**0.27.17**. The checkout at `~/dev/github/backnotprop/plannotator` matches the
release commit. Installed `plannotator-events.ts`, `plannotator-browser.ts`,
`server/external-annotations.ts`, `server/network.ts`, and
`server/serverReview.ts` were compared byte-for-byte with the release and matched.

**Reproduced** means installed annotation-transform code was executed.
**Source-supported** conclusions compare released upstream code with perk's call
sites. **Needs validation** proposals require live HTTP/browser behavior; that was
not exercised during this assessment.

| Perk integration | Contract retained by perk |
| --- | --- |
| [Plan provider][provider] | Subscribe before emit; correlate review identity; carry approval notes/direct edits into perk's draft/save policy |
| [Code-review handoff][handoff] | Open PR or local `since-base` review and await the final result |
| [Annotation adapter][annotations] | Map findings, POST annotations, DELETE only the owned source's annotations |
| [Stack review][stack-review] | Review one captured stack; map results back to per-PR publication |
| [Context-file generation][context-files] | Materialize PR diff/plan/body artifacts and stack combined/per-PR patches |
| [Console capture][console-capture] | Keep borrowed browser-launch output safe for the TUI |

## 1. Integration changes that need fixing

### No mandatory migration found in the current event protocol

**Source-supported.** The released [event API][up-events] retains the plan-review
and code-review result shapes used by perk. Between 0.27.14 and 0.27.17, the relevant
code-review payload change is additive: `patchFile?: string`. Perk's `cwd`, `prUrl`,
`diffType: "since-base"`, and `defaultBranch` paths remain accepted.

Upstream now [validates structured fields][up-annotations] for external-annotation **PATCH** requests
and drops unknown fields. Perk uses POST and source-scoped DELETE, not PATCH, so
this does not establish a break in the current adapter. If perk adopts PATCH later,
its typed update shape must be reviewed explicitly rather than assuming POST data
can be sent unchanged.

### Existing annotation mappings pass the installed transforms

**Reproduced, parser scope only.** Five representative outputs from perk's
`mapFindings()` were passed into installed `transformReviewInput()` or
`transformPlanInput()` from `generated/external-annotation.ts`, loaded with the
locally installed Jiti. Each produced one annotation without an error:

| Finding | Representative input | Preserved result |
| --- | --- | --- |
| Review line | `a.ts`, line 1, RIGHT side | File/line targeting and new-side mapping |
| Review file | `a.ts`, no line | File-level concern |
| Review general | Empty path, no line | General concern |
| Plan phrase | `quoted plan` | Quoted-text comment |
| Plan global | No phrase | Global comment |

All five retained source `perk:correctness` and the text
`[major/high] Audit fixture`. This supports the current shape, source ownership,
and severity/confidence formatting. It does not certify HTTP endpoints, SSE
delivery, visual positioning, old-side rendering, or platform comment publication.

### Distinguish existing issues from this release's changes

The [September 5 assessment][old-assessment] identified approval-note loss and
subscription ordering problems. The current provider already carries the notes
and subscribes before emitting the request; do not schedule those fixes again.
Likewise, the direct-edit result format still fits perk's
[unified-diff application seam][unified-diff]. No new replacement format was found.

Stack review's dependence on a local `since-base` calculation is an existing
limitation that the new patch API can address, not a regression introduced by
0.27.17. Preserve that distinction in the follow-up implementation and its tests.

## 2. Adaptations to remove or tighten

### No unconditional deletion of browser coordination is justified

The [browser implementation][up-browser] now sends the URL through `ctx.ui.notify`
in RPC sessions even when opening a browser succeeds. That is an informational
notification, not a typed readiness response carrying an owned server handle.
The public event result still arrives only when review finishes; it does not
provide a ready URL, cancellation handle, or server ownership token.

Keep perk's port reservation, temporary `PLANNOTATOR_PORT` coordination, readiness
polls against `/api/plan` or `/api/diff`, environment restoration, and TUI-safe
console capture until an actual replacement contract is available. Keep the
single-current-review, session-lifecycle, reviewed-bytes, and save-destination
guards. An upstream browser convenience does not establish perk's save authority.

The macOS executable-browser-script repair is inherited from upstream. No matching
perk workaround was found to delete. The long-line scrollbar, whitespace selection,
and nested-frontmatter improvements similarly do not require adapter code.

### P1: remove stack browser dependence on `since-base`, conditionally

Adopting `patchFile` can remove the stack browser's dependence on a live
`origin/<stack base>` lookup and Plannotator's local merge-base/fallback behavior.
This is a targeted simplification of the **browser input**, conditional on proving
the patch is generated from the captured stack's exact commits.

It is not a reason to remove the detached checkout used by reviewers and source
exploration. It is also not a reason to alter ordinary `prUrl` review, whose browser
supports direct platform posting. Keep existing per-PR stack publication and its
identity/annotation mapping checks.

## 3. Improvements worth purposeful adoption

### P1: review the captured stack through a static patch

**Source-supported API fit; live behavior needs validation.** In 0.27.16+, a
code-review event can supply `patchFile` to open a static patch. The browser reads
the file once, resolves a relative path against the supplied cwd, rejects stdin
(`-`) and empty input, and uses the path as its label. Treat `patchFile` and `prUrl`
as mutually exclusive in perk's own request type/construction; do not rely on
upstream branch precedence to reject an ambiguous request.

Current stack review opens a detached top checkout using `since-base` with
`origin/<stack base>`. Its own source documents the risk of a failed merge-base
calculation falling back to an empty HEAD diff. A static patch moves the displayed
diff's identity to an explicit artifact rather than another branch calculation.

**Plan:** materialize a combined patch from the exact base/topology/head identities
already accepted for the review. Reuse `combined.patch` from context-file generation
only if its provenance matches that same captured snapshot. Do not regenerate it
by refetching moving PR heads. Extend the handoff options with a mutually exclusive
static-patch case and use it only for the stack browser path initially.

Static-patch mode has material limits: it has no workspace/git context, live refresh,
or PR platform posting. Repository-backed source navigation and exploration may
differ even if the patch itself looks identical. Retain the detached checkout for
reviewers and evaluate the browser's loss of repository context before adopting.
Stack review is a better fit than ordinary PR review because perk already owns
per-PR stack publication.

**Acceptance:** after capture, moving refs must not change the browser diff; the
artifact and review identity must agree on the exact stack; old/new-side annotation
mapping and per-PR publication must remain correct; rename/binary cases must be
understood; missing, empty, and invalid patches must fail visibly. Verify that stack
review does not acquire unintended browser platform posting and ordinary PR mode
retains its existing behavior. Exercise close/cancel and stale-session handling.

### P2: use upstream diagram review in existing plan review

**Source-supported; inherited rendering benefit.** Release 0.27.16 upgrades themed
Mermaid rendering and supports node, edge, and cluster comments with external
diagram anchors. Release 0.27.17 adds standalone `.mmd`, `.mermaid`, `.dot`, and `.gv`
review. Perk plans that already contain diagrams can benefit without a second
renderer or a new plan-review workflow.

First validate diagram feedback in an ordinary perk draft review, through the
existing decision/feedback and save-policy path. Only add machine-authored diagram
anchors to `push_annotations` if a real reviewer workflow needs them; that would
require an explicit schema/mapping change and separate tests. Standalone diagram
review is optional future scope, not needed for the current plan provider upgrade.

### Inherit quieter remote checks without weakening review identity

**Source-supported; 0.27.17.** The [review server's][up-review-server] idle
`/api/diff/fresh` polling no longer repeatedly
runs network `git ls-remote`. Initial load, explicit fetch, and diff changes can
still check the remote; failed probes back off, and shutdown reaps owned git
processes. This reduces background work in existing browser sessions automatically.

The CLI flag `--no-git-remote-check`, environment variable
`PLANNOTATOR_GIT_REMOTE_CHECK=0`, and internal `gitRemoteCheck: false` option are not
interchangeable with a public Pi event field. The released event payload exposes
neither `gitRemoteCheck` nor `openStateFromFlags`. Do not add speculative fields to
perk's event requests, or assume the CLI's strict explicit-base validation applies
to the current `defaultBranch` event path. Keep perk's own captured-review identity
checks regardless of the remote-probe policy.

## Ordered implementation and verification

1. **Smoke-test the existing provider on the new baseline.** Exercise plan approval
   with notes, requested changes, direct edits, close/cancel, and stale sessions.
   In PR review, verify owned annotation POST/DELETE, both diff sides, and platform
   posting. Confirm polling and console handling under interactive and RPC launch.
2. **Implement static patch input for stack review as a bounded change.** First
   prove artifact provenance from captured identities, then add the handoff case
   and browser path. Update the actual cross-plane contract and user documentation
   in the implementation if the artifact or visible workflow changes.
3. **Validate the tradeoff before removing the old stack path.** Verify the exact
   diff under moving refs and failed merge-base conditions; assess lost repository
   context; exercise per-PR publication. Retain needed reviewer checkout behavior.
4. **Exercise diagram feedback.** Adopt the rendering benefit directly; defer new
   machine annotation fields until there is a concrete consumer and validation.

Completed evidence is released-source review, five installed-file identity checks,
and five annotation-transform cases. Live HTTP/SSE behavior, complete browser
flows, and stack publication were not tested in this assessment. Coordinate browser
waves with the [pi-subagents reverification work][subagents-assessment] and the
[Pi 0.87 repairs][pi-assessment]; a compatible annotation parser is not a successful
end-to-end wave.

[release-02714]: https://github.com/backnotprop/plannotator/releases/tag/v0.27.14
[release-02715]: https://github.com/backnotprop/plannotator/releases/tag/v0.27.15
[release-02716]: https://github.com/backnotprop/plannotator/releases/tag/v0.27.16
[release-02717]: https://github.com/backnotprop/plannotator/releases/tag/v0.27.17
[up-events]: https://github.com/backnotprop/plannotator/blob/8f2a8a81a384f1cd39c5f083d3c6fcd35a956422/apps/pi-extension/plannotator-events.ts
[up-browser]: https://github.com/backnotprop/plannotator/blob/8f2a8a81a384f1cd39c5f083d3c6fcd35a956422/apps/pi-extension/plannotator-browser.ts
[up-annotations]: https://github.com/backnotprop/plannotator/blob/8f2a8a81a384f1cd39c5f083d3c6fcd35a956422/apps/pi-extension/server/external-annotations.ts
[up-review-server]: https://github.com/backnotprop/plannotator/blob/8f2a8a81a384f1cd39c5f083d3c6fcd35a956422/apps/pi-extension/server/serverReview.ts
[provider]: ../../extension/pi/v1/providers/plannotator.ts
[handoff]: ../../extension/pi/v1/providers/plannotatorHandoff.ts
[annotations]: ../../extension/pi/v1/providers/annotations.ts
[stack-review]: ../../extension/pi/v1/codeReview/stack.ts
[context-files]: ../../src/perk/cli/commands/pr/review/context_files.py
[console-capture]: ../../extension/substrate/consoleCapture.ts
[unified-diff]: ../../extension/substrate/unifiedDiff.ts
[old-assessment]: plannotator-assessment-2026-09-05.md
[subagents-assessment]: pi-subagents-assessment-2026-09-21.md
[pi-assessment]: pi-assessment-2026-09-21.md
