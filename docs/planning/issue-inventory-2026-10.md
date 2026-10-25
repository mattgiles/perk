# Open issue inventory — October 2026

## Snapshot and assessment method

This is a planning inventory for perk maintainers. It recommends dispositions; it does not
close issues, create replacement issues, or implement their proposals.

- **Repository:** [mattgiles/perk](https://github.com/mattgiles/perk).
- **Reviewed:** October 24, 2026, America/New_York; issue snapshot captured October 25 at
  01:50 UTC (October 24 at 21:50 EDT).
- **Source baseline:** `911b41484fef0539a8195915962f5047bbcebcfa`, a clean local `main`, also
  confirmed through `gh api repos/mattgiles/perk/commits/main` during the review.
- **Included:** 33 open issues — 19 tagged `perk:gist`, 14 with no labels.
- **Excluded:** issues carrying `perk:objective`, `perk:plan`, or `perk:learn`, including any
  issue that also carries `perk:gist`; issues with other labels and no gist label are outside
  this inventory. Linked historical work is supporting evidence, not another inventory entry.

The selection was obtained through `gh`, with complete bodies and comments:

```sh
gh issue list --repo mattgiles/perk --state open --limit 1000 \
  --json number,title,body,labels,url,updatedAt,comments \
  --jq '[.[] | select(
    (any(.labels[]; .name == "perk:objective" or .name == "perk:plan" or .name == "perk:learn") | not)
    and ((.labels | length) == 0 or any(.labels[]; .name == "perk:gist"))
  )]'
```

The open population was below the limit. Every eligible body and its returned comments were
read. Claims were checked against current source, tests, contracts, documentation, and relevant
history. Renamed modules were followed to their current owners. Issue age and an unsuccessful
search were not grounds for declaring an issue stale. The single discussion on #2096 confirms
that its dogfood origin was deliberately not a reason to discard the intent.

**Applicability and recommendation are independent.** An issue is **stale** when its need has
been implemented or its premise superseded. An issue **still applies** when a meaningful part
remains, even if other parts landed. A still-applicable idea can nevertheless warrant declining.

| Recommendation | Meaning |
| --- | --- |
| `implement` | Pursue the remaining bounded change. |
| `close-without-implementing` | Close because the need is addressed or obsolete; no further implementation is needed. |
| `close-low-value` | The remaining proposal offers too little benefit to justify pursuing it. |
| `close-too-expensive` | The benefit exists, but the scope and maintenance burden do not justify investment now. |
| `fold-into-larger-planning-effort` | Carry the remaining intent into the concrete workstream named below. |

Value and cost recommendations are qualitative judgments based on the stated scope and existing
capabilities. They are not measured effort estimates or evidence that nobody wants a feature.
Folding is a proposed destination, not evidence that an existing plan already accepts the work.

## Summary

**3 stale; 30 still apply**, including partially addressed bundles.

| Recommendation | Count |
| --- | ---: |
| `implement` | 17 |
| `close-without-implementing` | 3 |
| `close-low-value` | 1 |
| `close-too-expensive` | 1 |
| `fold-into-larger-planning-effort` | 11 |
| **Total** | **33** |

Titles in this table are abbreviated; each numbered entry below reviews the corresponding issue.

| Issue | Intent | Labels | Applicability | Recommendation |
| --- | --- | --- | --- | --- |
| [#1658](https://github.com/mattgiles/perk/issues/1658) | Preserve hand-added PR-description sections | `perk:gist` | Still applies | `fold-into-larger-planning-effort` |
| [#1738](https://github.com/mattgiles/perk/issues/1738) | First-class repo-specific Pi extensions | `perk:gist` | Still applies | `close-too-expensive` |
| [#1742](https://github.com/mattgiles/perk/issues/1742) | Establish core vocabulary baseline | `perk:gist` | Still applies | `implement` |
| [#2096](https://github.com/mattgiles/perk/issues/2096) | Complete the shell-completion experience | `perk:gist` | Still applies | `implement` |
| [#2303](https://github.com/mattgiles/perk/issues/2303) | Share native worktree-default classifier fixtures | Untagged | Stale | `close-without-implementing` |
| [#2304](https://github.com/mattgiles/perk/issues/2304) | Accept pre-authored PR-body sections | Untagged | Still applies | `fold-into-larger-planning-effort` |
| [#2305](https://github.com/mattgiles/perk/issues/2305) | Bound the plan embed in PR bodies | Untagged | Stale | `close-without-implementing` |
| [#2420](https://github.com/mattgiles/perk/issues/2420) | Neutralize engagement wrapper tags | Untagged | Still applies | `implement` |
| [#2421](https://github.com/mattgiles/perk/issues/2421) | Recover from unreopenable closed PRs | Untagged | Still applies | `implement` |
| [#2422](https://github.com/mattgiles/perk/issues/2422) | Require stronger scout evidence of absence | Untagged | Still applies | `implement` |
| [#2498](https://github.com/mattgiles/perk/issues/2498) | Load CLI command groups lazily | `perk:gist` | Still applies | `fold-into-larger-planning-effort` |
| [#2499](https://github.com/mattgiles/perk/issues/2499) | Reduce bare-launch configuration import cost | `perk:gist` | Still applies | `fold-into-larger-planning-effort` |
| [#2527](https://github.com/mattgiles/perk/issues/2527) | Close five regression-coverage gaps | `perk:gist` | Still applies, partially addressed | `implement` |
| [#2528](https://github.com/mattgiles/perk/issues/2528) | Add documentation-verification advisories | `perk:gist` | Still applies | `fold-into-larger-planning-effort` |
| [#2529](https://github.com/mattgiles/perk/issues/2529) | Report dream source-file coverage ratios | `perk:gist` | Still applies | `close-low-value` |
| [#2530](https://github.com/mattgiles/perk/issues/2530) | Detect new Plannotator tool names | `perk:gist` | Stale | `close-without-implementing` |
| [#2531](https://github.com/mattgiles/perk/issues/2531) | Correct injection roster and model-order rationale | `perk:gist` | Still applies, partially addressed | `implement` |
| [#2577](https://github.com/mattgiles/perk/issues/2577) | Sanitize report headlines and extend UI guards | Untagged | Still applies | `implement` |
| [#2578](https://github.com/mattgiles/perk/issues/2578) | Reject PR descriptions as required evidence storage | Untagged | Still applies | `fold-into-larger-planning-effort` |
| [#2579](https://github.com/mattgiles/perk/issues/2579) | Reconcile the audit's copied bash gate | Untagged | Still applies | `implement` |
| [#2580](https://github.com/mattgiles/perk/issues/2580) | Check package skills, settings paths, and guidance drift | Untagged | Still applies | `fold-into-larger-planning-effort` |
| [#2581](https://github.com/mattgiles/perk/issues/2581) | Fix comment pagination, lease handling, and mode parity | Untagged | Still applies | `implement` |
| [#2582](https://github.com/mattgiles/perk/issues/2582) | Correct skill-authoring JSON documentation | Untagged | Still applies | `implement` |
| [#2583](https://github.com/mattgiles/perk/issues/2583) | Complete supplier verification residuals | Untagged | Still applies, partly superseded | `fold-into-larger-planning-effort` |
| [#2584](https://github.com/mattgiles/perk/issues/2584) | Harden the delivery lock and correct stale comments | Untagged | Still applies | `implement` |
| [#2618](https://github.com/mattgiles/perk/issues/2618) | Retain warm-door bindings through compaction | `perk:gist` | Still applies, partially addressed | `fold-into-larger-planning-effort` |
| [#2624](https://github.com/mattgiles/perk/issues/2624) | Include ignored submodule dirt in cleanliness proofs | `perk:gist` | Still applies | `implement` |
| [#2625](https://github.com/mattgiles/perk/issues/2625) | Return canonical Linear project IDs | `perk:gist` | Still applies | `implement` |
| [#2626](https://github.com/mattgiles/perk/issues/2626) | Fix relative crawl links and request deadlines | `perk:gist` | Still applies | `implement` |
| [#2627](https://github.com/mattgiles/perk/issues/2627) | Accept an artifact for objective reconciliation | `perk:gist` | Still applies | `fold-into-larger-planning-effort` |
| [#2628](https://github.com/mattgiles/perk/issues/2628) | Fix loaded-host fixture timeout and replay coverage | `perk:gist` | Still applies, partly superseded | `implement` |
| [#2629](https://github.com/mattgiles/perk/issues/2629) | Harden change-stat execution and coverage | `perk:gist` | Still applies | `implement` |
| [#2733](https://github.com/mattgiles/perk/issues/2733) | Dispose the objective-save linkage gap | `perk:gist` | Still applies, historical framing changed | `fold-into-larger-planning-effort` |

## Individual assessments

### #1658 — PR-body splice protection

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

The requested preservation of human additions is absent. Both the incremental submit path in
[`submit_cmd.py`](../../src/perk/cli/commands/pr/submit_cmd.py) and publication in
[`publish.py`](../../src/perk/delivery/publish.py) compose and replace a complete body. The shared
[`pr_body.compose`](../../src/perk/delivery/pr_body.py) accepts generated sections but does not
read an existing description or preserve an unmanaged region. Its size protection addresses
#2305, not this ownership problem.

Fold into **PR descriptions and durable evidence**, with #2304 and #2578. Define generated and
human-owned content together, including republish behavior and the existing body-size budget.
Preserving PR text must not become a claim that it survives in the repository after squash.

### #1738 — First-class repo-specific Pi extensions

**Applicability:** still applies. **Recommendation:** `close-too-expensive`.

Perk has guided skill creation and refinement through its
[`skills` command group](../../src/perk/cli/commands/skills/__init__.py), but no equivalent
extension-authoring product. Existing documentation already accommodates native project
extensions and their providers in [models and compaction](../user-docs/reference/configuration/models-and-compaction.md).
That native capability does not satisfy the gist's guided authoring and diagnostic promises.

The expensive part is the requested dependable availability and diagnosis across direct Pi,
local/headless/remote perk workflows, worktrees, trust states, and the entire extension API.
That is a new supported customization surface, beyond reusing a scaffolding command. Recommend
declining that broad product commitment now and using native Pi extension authoring for concrete
repo needs. Reconsider when a real extension exposes a specific unsupported launch or diagnosis
case that can bound the investment. This is a scope/value judgment, not a measured cost or a
finding that native extensions are unavailable.

### #1742 — Establish perk's core vocabulary baseline

**Applicability:** still applies. **Recommendation:** `implement`.

[`CONTEXT.md`](../../CONTEXT.md) contains substantial vocabulary, but its organization still
tracks particular subsystems: model-facing prose, gating, report waves, plan save, review,
delivery, and the library. It defines Gist while lacking comparable top-level definitions of
Plan, Objective, Stage, and Run. Existing glossary work therefore does not establish that the
requested product-wide editorial baseline has been completed.

Perform the bounded current-state audit the gist asks for: ground core terms in both planes
and shared contracts, add supported distinctions to the concise glossary, and retain unresolved
conflicts in an audit record. Keep identifier migrations and ongoing enforcement outside this
work. The source supports the missing baseline; this inventory is not itself that vocabulary
audit.

### #2096 — Make shell completion deliver its intended experience

**Applicability:** still applies. **Recommendation:** `implement`.

[`completions.py`](../../src/perk/cli/completions.py) still provides plan/objective ID callbacks.
The named coverage gaps remain visible in the command wiring: `plan from`'s issue argument,
worktree checkout/remove names, and skill refine/delete names lack completion callbacks.
[`test_cli_completions.py`](../../tests/test_cli_completions.py) covers callback behavior and
wiring, rather than the reported stock-zsh interaction.

Implement the missing populations using the existing bounded, fail-soft pattern, and reproduce
the zsh menu claim before selecting a shell-specific repair. The original first-TAB failure was
not reproduced in this review; missing argument-family coverage alone keeps the issue relevant.
Its comment explicitly retains the gist as genuine intent after dogfooding.

### #2303 — Cross-plane native worktree-default fixture

**Applicability:** stale, premise removed. **Recommendation:** `close-without-implementing`.

The proposed fixture would synchronize a Python convergence classifier with a TypeScript
classifier. History shows `src/perk/convergence/init/subagent_config.py` removed by
[`eb4bd441`](https://github.com/mattgiles/perk/commit/eb4bd441aa2565aed39f772073e3947d7439dd8b),
after this issue was filed. Current convergence no longer contains that counterpart.
The surviving read is [`readNativeWorktreeDefault`](../../extension/pi/v1/foregroundDelegation.ts),
used by the writer engines; it explicitly refuses incompatible settings without rewriting them.

Close with the deletion and current owner as evidence. Do not add a shared fixture for a
cross-plane behavior that no longer exists.

### #2304 — Fold a pre-authored section into the PR body

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

[`pr_body.compose`](../../src/perk/delivery/pr_body.py) has an internal `sections` input, now
used for generated change stats, but this is not a user-supplied pre-submit artifact interface.
[`submit_cmd.py`](../../src/perk/cli/commands/pr/submit_cmd.py) supplies the generated section;
it does not load the proposed scratch contribution. The existence of an internal composition
hook therefore does not fulfill the issue.

Fold into **PR descriptions and durable evidence**. Resolve how initial human contributions
and later edits coexist before adding another body input. Required acceptance evidence needs a
durable carrier independently of whether this convenience is adopted.

### #2305 — Bound the embedded plan in PR descriptions

**Applicability:** stale, implemented. **Recommendation:** `close-without-implementing`.

[`pr_body.py`](../../src/perk/delivery/pr_body.py) defines `PR_BODY_MAX_CHARS = 65_536`, reserves
footer space, and replaces an oversized plan embed with an explicit pointer. Both incremental
and stacked composers use this shared kernel. The regression
`test_real_submit_drops_the_embed_when_the_plan_exceeds_githubs_body_cap` in
[`test_pr_submit.py`](../../tests/test_pr_submit.py) passed during this review.

Close with this implementation and regression as evidence. This resolves the reported oversized
plan case; it is not a blanket proof that arbitrary future unbounded sections can fit.

### #2420 — Neutralize fixed engagement wrapper tags

**Applicability:** still applies. **Recommendation:** `implement`.

[`engagement.py`](../../src/perk/backends/engagement.py) still interpolates truncated comment
bodies into fixed `untrusted_*_engagement` wrappers. `_render_engagement` joins the content and
tags directly, and `render_objective_engagement` constructs its fixed wrapper separately.
Truncation does not neutralize a closing wrapper embedded in untrusted content.

Apply the existing wrapper-neutralization approach across this renderer family, retaining raw
JSON data. Add an adversarial closing-tag regression in
[`test_engagement.py`](../../tests/test_engagement.py). This is a source-confirmed framing gap;
an end-to-end model-injection experiment was not performed.

### #2421 — Recover from an unreopenable closed PR

**Applicability:** still applies. **Recommendation:** `implement`.

[`submit_cmd.py`](../../src/perk/cli/commands/pr/submit_cmd.py) still pushes, reuses a closed PR,
and calls `reopen_pr` without the proposed recovery. The existing
[`submission tests`](../../tests/test_pr_submit.py) explicitly pin a reopen failure as a loud
`github_error` with no header advancement. Reporting that failure is useful, but does not
recover the recreated-branch case or provide its specific repair guidance.

Implement a bounded recovery/refusal for the known non-reopenable case across applicable
submit/publication paths; preserve unrelated GitHub failures. Add a fake 422 regression and
cover the already-published branch state. The historical GitHub 422 was not reproduced live.

### #2422 — Require stronger scout evidence of absence

**Applicability:** still applies. **Recommendation:** `implement`.

[`agents/scout.md`](../../agents/scout.md) says to verify before asserting and distinguish
verified claims from inference, but does not include the specific no-match/read-back rule.
The stronger lesson exists in [`subagents.md`](../learned/pi/subagents.md), which is not a
substitute for the delivered scout definition's own instructions.

Add the short lane-side rule: confirm absence by reading the candidate or correcting the query;
otherwise report the claim as unverified. Reconverge the delivered definition and run the
opt-in prose checks required for that prompt change. This inventory establishes the guidance
gap, not a new observed false scout report.

### #2498 — Load command groups lazily

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

[`cli.py::_register_root_commands`](../../src/perk/cli/cli.py) still imports and registers the
whole command catalog on the first subcommand lookup. A refreshed local probe measured median
`uv run --no-sync perk --version` at **110.48 ms** and `release-notes --help` at **728.02 ms**:
a **617.54 ms** difference over five alternating measured pairs after a discarded warm-up pair.
These are local process timings including uv, not a cross-platform performance guarantee.

Fold with #2499 into **CLI startup boundaries**. Preserve the full help/alias tree and existing
[`import-tier tests`](../../tests/test_cli_import_tiers.py), and measure which imports each
boundary actually removes. The current evidence supports investigating group loading without
inventing a wall-clock CI gate.

### #2499 — Reduce configuration cost on the bare launch path

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

[`cli/context.py`](../../src/perk/cli/context.py) still imports the typed configuration module
at module scope. An isolated current `-X importtime` trace of that import measured
`perk.substrate.config` at **82.26 ms cumulative**, including bindings and Pydantic imports.
This is one profiled import observation, not a refreshed full bare-Pi handoff measurement.

Fold with #2498 into **CLI startup boundaries**. Establish the minimum launch read while
preserving config validation and diagnostic behavior. The issue's proposed cache is not a
requirement: determine whether import separation is sufficient before adding cache state or
duplicating configuration semantics.

### #2527 — Five regression-coverage gaps

**Applicability:** still applies, partially addressed. **Recommendation:** `implement`.

The bundle needs trimming, not replaying unchanged:

- [`draftCompact.test.ts`](../../extension/pi/v1/draftCompact.test.ts) checks that gist and
  refinement sessions are driven toward their own writer, but that test does not perform the
  real writes and settle them with literal expected identities.
- [`readOnlyBash.test.ts`](../../extension/substrate/readOnlyBash.test.ts) pins a handwritten
  review-context command; it does not consume `pinnedReviewContextCommand` directly, so the
  requested producer/gate coupling is still missing.
- The [TypeScript](../../extension/substrate/sessionPointers.test.ts) and
  [Python](../../tests/test_session_pointers.py) pointer byte fixtures remain ASCII-only.
- [`test_plain_session.py`](../../tests/test_plain_session.py) does not establish the requested
  forced-interactive version-surface ordering before terminal/repository refusals.
- [`lifecycle.test.ts`](../../extension/session/lifecycle.test.ts) now explicitly pins the
  claim/fork/adopt/mint append payloads. The original claim that only their consequences are
  tested is outdated. Warm refinement has stage-entry tests in
  [`workflowSession.test.ts`](../../extension/session/workflowSession.test.ts); check the exact
  emitted payload when completing the residual identity-shape census rather than duplicating
  the now-pinned lifecycle arms.

Implement the surviving integration pins, with independently justified expected values.

### #2528 — Documentation-verification advisories

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

[`docs_scan.py`](../../src/perk/learn/docs_scan.py) reports stale source pointers, broken document
references, and duplicates. Its findings model does not include either requested advisory;
[`docs-check`](../../src/perk/cli/commands/learn/docs_check_cmd.py) does not expose them either.
However, the proposed literal verification-stamp parser must be refreshed against today's
distinction between historical version evidence, adopted pins, and certification status.

Fold into **Dependency resources and guidance drift**, merging the Pi reminder with #2580's
third item. Keep the history-style advisory distinct from dependency currency. Agree on the
actual supported document shapes before building a regex around an old example, and preserve
the report-only exit behavior.

### #2529 — Dream source-file coverage ratio

**Applicability:** still applies. **Recommendation:** `close-low-value`.

[`dream-analyst.md`](../../agents/dream-analyst.md) requires selective source verification and
an `evidence_checked` list, capped at six items. The
[`dream report schemas and reduction`](../../extension/learning/dreamReducer.ts) do not compute
the proposed ratio. The missing capability is real; its usefulness is the weak part.

A count of self-reported checked files divided by extracted pointer files does not establish
which substantive claims were verified. Incidental pointers inflate the denominator, a file
read can be superficial, and the bounded evidence list is not a complete read log. Adding
pointer normalization and a reporting contract could make the resulting number look more
authoritative without fixing the missed-claim failure. Decline this metric; retain explicit
evidence and uncertainties. Reconsider a narrower check tied to a concrete claim or invariant
if it can demonstrate that it catches an actual missed correction.

### #2530 — Plannotator load-time tool-name drift guard

**Applicability:** stale, superseded by architecture. **Recommendation:** `close-without-implementing`.

[`toolPolicy.ts`](../../extension/substrate/toolPolicy.ts) now classifies foreign tools by
registrar provenance. The selected Plannotator package receives posture `never`, regardless
of its tool names. The old `BORROWED_TOOLS`/`PLANNOTATOR_PHASE_TOOLS` enumeration is gone.
[`ownNamesActivation.test.ts`](../../extension/substrate/ownNamesActivation.test.ts) registers
`plannotator_future_tool` alongside known names and verifies its exclusion from stage-visible
requests. All 12 tests in that file passed during this review.

Close with the package-wide policy and future-name regression. An installed-package census of
names would guard a mechanism perk no longer relies on.

### #2531 — Injection roster and model-order rationale

**Applicability:** still applies, partially addressed. **Recommendation:** `implement`.

The flow-owned injection roster in [`contracts.md` §8.31](../../shared/contracts.md) still lists
objective/gist/plan contexts without explicitly including the refinement context alongside
them, despite describing refinement selection elsewhere. The model-order rationale survives
in [`stageExecution.ts`](../../extension/worker/stageExecution.ts) and
[`sdkAdapter.test.ts`](../../extension/worker/sdkAdapter.test.ts). The named old rationale is
no longer present in `sdkAdapter.ts` itself.

Make the narrow contract/prose correction at the surviving sites: catalog order is not a
curated default. Preserve the behavior of letting the SDK choose its default rather than
preselecting index zero. This does not call for a model-selection refactor.

### #2577 — Sanitize report headlines and extend UI guards

**Applicability:** still applies. **Recommendation:** `implement`.

[`report.ts::headlineFor`](../../extension/surfaces/report.ts) folds logical lines and horizontal
whitespace but does not strip terminal controls before notifying. That improvement therefore
does not satisfy terminal sanitization. [`surfacesGuard.test.ts`](../../extension/surfacesGuard.test.ts)
still omits the four named methods; all four remain in the installed Pi 1.4.0 UI declarations.

The small documentation residuals also remain: the `invokeTool` comment in
[`harness.ts`](../../extension/testing/harness.ts) omits `confirm`, and the
[TUI charter](../design/tui-charter.md) retains its old checkpoint-block reference. Implement
the shared sanitizer leaf and control-bearing regression, extend the UI guard, and correct
those descriptions. The current local sink is source-confirmed; the issue's old upstream
rendering description was not independently re-certified as a live terminal exploit.

### #2578 — Flag PR descriptions as required evidence carriers

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

The [planner skill](../../skills/perk-plan/SKILL.md),
[draft-reviewer definition](../../agents/draft-reviewer.md), and current stage prompts do not
carry the requested explicit steer/detector. The submission path still does not accept a
pre-authored evidence artifact, and ordinary PR-description preservation would not itself
make evidence part of repository history.

Fold into **PR descriptions and durable evidence**. Start with short planner/reviewer guidance
pointing required evidence to a committed record or plan-issue comment. A detector can follow
if it catches the realized examples without rejecting ordinary PR-description instructions;
there is no need to commit to a new lint mechanism merely to deliver the requested warning.

### #2579 — Audit bash gate has drifted from enforcement

**Applicability:** still applies. **Recommendation:** `implement`.

[`perk_dev/audit/gate_policy.py`](../../packages/perk-dev/src/perk_dev/audit/gate_policy.py)
still uses the copied leading-word/segment policy and explicitly accepts drift. Controlled
pure-function probes against it and
[`readOnlyBash.ts`](../../extension/substrate/readOnlyBash.ts) confirmed both drift directions:

| Command | Python audit accepts | Current TS gate accepts |
| --- | --- | --- |
| `env X=1 grep foo f` | Yes | No |
| `rg=payload` | Yes | No |
| `rg --pre cat x` | Yes | No |
| `for f in a b; do cat "$f"; done` | No | Yes |
| `git branch --list` | Yes | Yes |

Replace the stale policy copy with the current authoritative policy boundary where practical,
and pin discriminating cases. The final row is deliberately not evidence of divergence.
The audit remains a lead generator; its drift is not evidence that runtime enforcement admits
the three refused commands.

### #2580 — Package-skill, settings-path, and guidance checks

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

All three gaps remain in the named areas:

- [`test_skill_declarations.py`](../../tests/test_skill_declarations.py) still takes the literal
  `PACKAGE_SKILLS` set as part of its known-name universe without the proposed installed-package
  reverse check.
- [`checks.py::_settings_packages`](../../src/perk/convergence/doctor/checks.py) still returns
  `[]` whenever `is_file()` is false, conflating a directory with absence.
- The supplier guidance stamp has its own diagnostic, but the requested Pi-documentation
  verification reminder is not represented by the scanner findings inspected for #2528.

Fold into **Dependency resources and guidance drift**. Merge the duplicate reminder intent
with #2528, while retaining the reverse-skill and non-regular-path checks as explicit bounded
tasks. A skip when the package is not installed is appropriate for the reverse check; it must
not silently claim the installed census passed.

### #2581 — Comment pagination, hunk lease, and submit mode parity

**Applicability:** still applies. **Recommendation:** `implement`.

The bundle contains three separate surviving concerns:

- [`plans.py::_find_plan_body_comment_id`](../../src/perk/backends/github/plans.py) still reads
  one comments page, while `find_comment_id_by_marker` uses `--paginate --slurp`.
- [`hunkFeedback/store.ts`](../../extension/hunkFeedback/store.ts) still turns every `readLease`
  failure into `null`. Its post-rename restoration recognizes only a well-formed fresh lease,
  leaving the missing/corrupt successor-write window described in the issue.
- [`submitConflict.ts::valid`](../../extension/pi/v1/delivery/submitConflict.ts) still requires
  an explicit `mode === "read-write"`; absence is not equivalent to gate-off. The underlying
  [`resolver engine`](../../extension/pi/v1/delivery/conflictResolverEngine.ts) accepts a
  separate read-only predicate, so the positive controller condition needs an intentional
  authorization decision rather than an incidental parity edit.

Implement the pagination and lease fixes with >30-comment and controlled reclaim/I/O cases.
Resolve and document the submit mode floor explicitly before changing it; cover the warm-minted
no-mode case. Do not collapse this bundle into a claim that all three have the same root cause
or weaken authorization merely to make the implementations look alike.

### #2582 — Skill-authoring JSON report documentation

**Applicability:** still applies. **Recommendation:** `implement`.

The create/refine entries in [remote and utility commands](../user-docs/reference/cli/remote-and-utility.md)
still say `--json` emits a stable report without restricting the claim to `--dry-run`.
[`create_cmd.py`](../../src/perk/cli/commands/skills/create_cmd.py) emits the preview JSON only
in the dry-run branch before the real scaffold/launch path;
[`refine_cmd.py`](../../src/perk/cli/commands/skills/refine_cmd.py) likewise launches on the real path.

Correct the docs to describe the implemented dry-run report. Check the matching
[perk-expert reference](../../skills/perk-expert/references/configuration.md) when making the
edit; its current high-level create/refine description does not repeat the blanket JSON promise.
Changing launch semantics or introducing a pre-exec report is unnecessary for this correction.

### #2583 — Supplier 0.71.0 re-verification residuals

**Applicability:** still applies, historical version work partly superseded.
**Recommendation:** `fold-into-larger-planning-effort`.

The old request to certify/stamp 0.71.0 is obsolete: current adoption is Pi 1.4.0 with supplier
0.81.0, while the guidance stamp remains 0.75.0. Those independent facts are documented in the
[reverification guide](../developers/pi-subagents-reverify.md); the old baseline is not a target
to restore or a reason to advance the current stamp without evidence.

Some residual claims need a narrower disposition:

- The learning-wave description in [`contracts.md` §8.35](../../shared/contracts.md) still uses
  the outdated `covered angle ⟺ ok lane ⟺ schema-valid report` chain. Elsewhere the contract
  distinguishes failed lanes retaining valid report evidence; this wording still needs repair.
- The [child policy](../design/pi-subagents-child-execution-policy.md) and developer guide now
  acknowledge the fork repair in 0.71.0. That part is addressed.
- Loader-name enumeration has been superseded by package provenance, including the loader and
  future-name fixtures discussed under #2530. Do not resurrect `BORROWED_TOOLS`.
- The requested systematic changelog-to-claims sweep and structured-output retention review
  should be reconciled against the current runbook. An old scoped verification date in
  [native-sdk-bridge.md](../learned/pi/native-sdk-bridge.md) is historical evidence, not a stamp
  that should be advanced mechanically.

Fold surviving contract/runbook work into **Dependency resources and guidance drift**, using
the current adopted pair. This inventory does not certify that pair or settle its live matrix.

### #2584 — Delivery lock no-follow posture and stale comments

**Applicability:** still applies. **Recommendation:** `implement`.

[`delivery/oplock.py`](../../src/perk/delivery/oplock.py) still uses `path.open("a")`.
[`library/lock.py`](../../src/perk/library/lock.py) already has the no-follow, nonblocking open,
regular-file verification, and typed error posture the issue contrasts with it. The workspace
comment in [`pyproject.toml`](../../pyproject.toml) still claims `packages/*` matches nothing,
and [headless-worker.md](../design/headless-worker.md) still names `SDK_READ_ONLY_TOOLS` as
current machinery.

Apply the safe-open posture to the delivery lock and add redirected/non-regular-path coverage
in [`test_delivery_oplock.py`](../../tests/test_delivery_oplock.py). Correct the two descriptions.
Do not make a general flock abstraction a prerequisite for this concrete hardening.

### #2618 — Preserve warm-door bindings through compaction

**Applicability:** still applies, partially addressed. **Recommendation:** `fold-into-larger-planning-effort`.

[`bindingDelivery.ts::activeBindingTrigger`](../../extension/substrate/bindingDelivery.ts)
still resolves only a recorded stage or stage-less plan mode. It has no durable warm command
override. However, [`objectivePlanning.ts`](../../extension/pi/v1/objectivePlanning.ts) now
records `objective-plan` at the warm factory door, and the binding-delivery comments explicitly
describe its later-turn retention. That example in the gist is outdated.

The command-specific seeds for other warm doors can still differ from the session's durable
stage/mode, so the general gap survives. Fold into **Session continuity and complete outcomes**.
Define entry, clear, completion, navigation, and compaction semantics across the remaining doors
before adding a field. Preserve the separate distinction between a binding trigger and a stage;
do not solve every door by impersonating a different workflow stage.

### #2624 — Cleanliness proofs must override submodule ignore

**Applicability:** still applies. **Recommendation:** `implement`.

[`git.ts::worktreeDirty`](../../extension/substrate/git.ts) still executes plain
`git status --porcelain`. Its neighboring `trackedChanges` explicitly adds
`--ignore-submodules=none`, with a real submodule regression in
[`git.test.ts`](../../extension/substrate/git.test.ts). The cleanliness proof therefore still
depends on user/repository ignore settings in a way the sibling probe does not.

Apply the explicit override to the shared dirty probe and exercise dirty content, untracked
submodule content, and a moved submodule head under ignore settings. The current missing flag
is source-confirmed; this review did not run a new submodule reproduction.

### #2625 — Return canonical Linear project IDs

**Applicability:** still applies. **Recommendation:** `implement`.

[`project_store.py`](../../src/perk/backends/linear/project_store.py) still returns `id=source_id`
from `read_objective_source` and `id=objective_id` from `get_objective`, despite fetching the
project's ID. [`replan_cmd.py`](../../src/perk/cli/commands/objective/replan_cmd.py) compares the
guidance reference and prepared objective ID to refuse aliases of the subject.

Return the fetched canonical identity and add fake slug/UUID equivalence cases in
[`test_linear_project_store.py`](../../tests/test_linear_project_store.py), including the replan
consumer. The returned-input identity is established by source; whether the live Linear
`project(id:)` endpoint accepts the specific slug spelling remains unverified. Do not describe
the production alias bypass as reproduced.

### #2626 — Relative crawl links and hard request deadlines

**Applicability:** still applies. **Recommendation:** `implement`.

[`copy_docs_to_markdown.py::rewrite_markdown_links`](../../skills/librarian/scripts/copy_docs_to_markdown.py)
still performs exact lookup of converted targets without resolving them against the effective
page URL. Discovery's URL joining does not fix the later Markdown-rewrite phase.
[`probe.py`](../../src/perk/library/probe.py) explicitly uses per-operation HTTP timeouts;
[`check.py`](../../src/perk/library/check.py) checks the entry budget between requests.

Implement these as two bounded fixes: retain the effective URL needed to resolve rendered
links, and enforce a request deadline that survives trickling bodies/redirects. Pin the rendered
relative link and a controlled slow-response case. A live trickling-server overrun was not
reproduced here; the distinction between the implemented timeout and requested deadline is
visible in the source.

### #2627 — Artifact input for objective reconciliation

**Applicability:** still applies. **Recommendation:** `fold-into-larger-planning-effort`.

[`objectivePlanning.ts`](../../extension/pi/v1/objectivePlanning.ts) still registers
`reconcile_objective` with required `{objective, prose}` and no additional properties. Its
guidance requires the whole replacement region in the tool call. The CLI file-input workaround
therefore does not make the warm tool artifact-aware.

Fold into **Artifact inputs for authoring and reconciliation**, grounded in the existing
[explicit-artifact opportunity](./command-interface-and-structured-output-opportunities.md#4-make-explicit-artifacts-the-normal-authoring-completion-path).
Prefer a bounded file/artifact input using the existing cold-door path over a new anchored-patch
language. Preserve objective identity, scratch containment, and whole-region replacement
semantics while avoiding a second full transcription through the model.

### #2628 — Loaded-host fixture timeout and owner replay coverage

**Applicability:** still applies, owner-replay framing partly superseded.
**Recommendation:** `implement`.

[`worktreeResolverLock.test.ts`](../../extension/substrate/worktreeResolverLock.test.ts) still
sets a 5,000 ms timeout on git fixture initialization and worktree operations. The reported
host-load flake was not recreated, but the narrow threshold remains.

The old foreign-tool deactivation model is gone. Current
[`ownNamesActivation.test.ts`](../../extension/substrate/ownNamesActivation.test.ts) covers
recorded owner selection across tree navigation and subsequent model-visible tool censuses;
foreign tools deliberately remain active while policy hides their declarations. Its 12 tests
passed. The restoration window is also explicit in
[`toolGating.ts`](../../extension/substrate/toolGating.ts). Do not add an assertion that demands
immediate foreign deactivation, contrary to the current ownership contract.

Implement the fixture-timeout correction using an appropriate bounded git-fixture policy.
Retain or refine replay tests only for a concrete current presentation/enforcement gap rather
than the obsolete active-name expectation.

### #2629 — Change-stat CI, memory, and gitlink residuals

**Applicability:** still applies. **Recommendation:** `implement`.

The [CI workflow](../../.github/workflows/ci.yml) has no explicit cloc installation, while the
real-cloc test in [`test_change_stats.py`](../../tests/test_change_stats.py) skips if it is absent.
This leaves execution dependent on the runner image; it does not prove every past CI run
skipped. [`git.py::read_blobs`](../../src/perk/substrate/git.py) still captures the complete
`cat-file --batch` response, and
[`change_stats.py`](../../src/perk/delivery/change_stats.py) requests all changed blob contents
before materialization, including binary blobs. The named repository-level suite covers
symlink transitions but lacks the proposed gitlink transition cases.

Install cloc explicitly for CI and add repository-level gitlink add/update/file-transition
coverage. Bound the raw-blob memory exposure through the smallest suitable cap or streaming
change after characterizing a large input. This review did not measure a memory failure, so
streaming is a candidate solution rather than an already-justified architecture rewrite.

### #2733 — Dispose the objective-save linkage gap

**Applicability:** still applies, historical framing changed.
**Recommendation:** `fold-into-larger-planning-effort`.

[`saveObjective`](../../extension/authoring/objective/save.ts) still returns the session linkage
result, while [`objectiveSaveResultOf`](../../extension/pi/v1/objectiveAuthoring.ts) omits it
from the terminating result. The save operation explicitly documents that a held link can leave
an older `active_objective`; no-argument consumers in
[`objectivePlanning.ts`](../../extension/pi/v1/objectivePlanning.ts) prefer that field.
This supports the gist's stale-target concern even though the seam reports a failure separately.

The linked historical [objective #2707](https://github.com/mattgiles/perk/issues/2707) is closed;
its current body no longer contains the specific objective-save candidate wording cited by
the gist. Do not replay that prose rewrite as if its old location were unchanged.

Fold the substantive gap into **Session continuity and complete outcomes**, using this existing
issue as the tracked input rather than creating another meta-disposition issue by default.
The follow-up should carry linkage and repair guidance through human/model results, prove the
older-target case, and verify retry idempotency for each backend before advertising a retry.
Failure injection and backend retry certification were not performed in this inventory.

## Consolidation recommendations

These are proposed bounded planning destinations. The references supply context; they do not
mean that old planning prose is current or that a roadmap already accepts these issues.

| Workstream | Issues | Intended outcome and planning input |
| --- | --- | --- |
| **PR descriptions and durable evidence** | #1658, #2304, #2578 | Set generated/human content ownership, contribution and republish behavior, and the separate durable-evidence rule. Reuse the existing bounded body composer; recommend closing #2305 as implemented. |
| **CLI startup boundaries** | #2498, #2499 | Plan group import boundaries and launch configuration dependencies together, retaining help/alias/validation semantics. Start from the [startup closing evidence](../design/archive/perk-startup-closing-evidence.md) and this review's fresh local probes. |
| **Dependency resources and guidance drift** | #2528, #2580, #2583 | Produce one Pi-guidance reminder, installed-resource checks, and a current-version contract/runbook residual list. Use the [reverification guide](../developers/pi-subagents-reverify.md) and [October release assessment](./pi-and-subagents-assessment-2026-10-24.md); preserve the distinction between adoption and certification. |
| **Session continuity and complete outcomes** | #2618, #2733 | Preserve the correct warm-door binding across compaction and expose objective-save linkage/repair facts without silently retaining the wrong target. Extend the [complete-outcomes direction](./command-interface-and-structured-output-opportunities.md#2-carry-complete-outcomes-through-the-ux-seam) from the current code, where plan-save projection has already advanced. |
| **Artifact inputs for authoring and reconciliation** | #2627 | Incorporate the warm reconciliation gap into the existing [explicit-artifact direction](./command-interface-and-structured-output-opportunities.md#4-make-explicit-artifacts-the-normal-authoring-completion-path), with a bounded artifact/file input and existing write ownership. |

The two product declines are independent of staleness: #1738 is a broad support commitment
whose current cost is not justified; #2529 proposes a weak confidence metric. Neither should
be closed with a misleading “already implemented” explanation.

## Verification and limits

Verification performed during the review:

- The eligible set was fetched again before writing and after the draft: the same 33 issue IDs,
  labels, and update timestamps remained. A one-off check confirmed 33 unique detailed entries,
  matching summary recommendations and totals, and 92 resolving local links with their anchors.
- `uv run --no-sync pytest tests/test_pr_submit.py::test_real_submit_drops_the_embed_when_the_plan_exceeds_githubs_body_cap -q`:
  **1 passed**.
- `node --test extension/substrate/ownNamesActivation.test.ts`: **12 passed, none skipped**.
- Pure Python-audit and TypeScript-gate calls produced the comparison under #2579; no command
  in that comparison was executed as a shell operation.
- The startup probe used one discarded warm-up pair and five alternating measured pairs of
  `uv run --no-sync perk --version` and `uv run --no-sync perk release-notes --help`, with
  `PERK_SKIP_VERSION_CHECK=1`. A separate
  `uv run --no-sync python -X importtime -c 'from perk.cli.context import PerkContext'` trace
  supplied the configuration import observation. No Pi session was launched by these probes.
- The installed Pi UI declarations were read for #2577; outdated library mirrors were not
  used as proof of the current API.

Source inspection establishes the stated current shapes and remaining gaps. Reading an existing
test is not represented as running it. The passing targeted tests do not certify unrelated
workflows, prove a historical host-load failure, or establish live GitHub/Linear behavior.

This change contains only this planning document. No GitHub issue mutation, implementation fix,
full CI run, live provider test, compatibility certification, memory stress test, or shell-menu
interaction was performed. Refresh the snapshot and the relevant evidence before acting on a
recommendation.
