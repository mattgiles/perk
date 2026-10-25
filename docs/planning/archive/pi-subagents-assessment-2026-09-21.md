# pi-subagents release assessment — 2026-09-21

Status: proposed follow-up work, grounded in released source and installed-package
probes. This document does not update packages, runtime policy, or the doctor stamp.

Use **pi-subagents 0.70.1 as the next minimum supported baseline**, coordinated with
Pi 0.87.0 and Plannotator 0.27.17. On that baseline, the most concrete work is to
remove inert `completionGuard` declarations and retire the host-tool-intersection
workaround. The strongest small adoption candidate is an explicit descendant-agent
ceiling for agents whose existing contract already prohibits delegation.

No mandatory request-envelope migration was found for perk's current fresh-context
report waves or structured conflict delegation. That conclusion is narrower than
full compatibility certification: live browser waves remain required, and the
checkout's Pi 0.87 fork-context repair is newer than the installed release.

## Snapshot and evidence

Perk was assessed at 3.5.0, commit
`8e0843fa597996c0693fd9a1547a4a0f6c30c829`. GitHub publication dates were checked
with `gh`; annotated release tags were peeled to their commit objects.

| Release | Published, UTC | Release commit | Relevant scope |
| --- | --- | --- | --- |
| [0.68.0][release-0680] | September 15 | `f3ccf47dc236b6c0fcc0d897cec4a9e6da3e916d` | Required child extensions, workflow args, wrapped tool-slot repair |
| [0.69.0][release-0690] | September 18 | `f4918e80b531f1bf9f1d9e847b8f86c9016108f1` | Typed gate output |
| [0.70.0][release-0700] | September 20 | `b72714de95e612406b3461e63dfc182856333a7e` | Agent allowlists; removal of host builtin intersection |
| [0.70.1][release-0701] | September 21 | `1ac7b5e2652e9571164847ac2905ab4aded92791` | Removal of completion guard; acceptance inference changes |

The preceding comparison baseline is 0.67.0 at
`aa75b3353836f7868898e3bd58234d21eaff1463`. Both perk's and Savant's local
`.pi/npm/node_modules/pi-subagents` installations are **0.70.1**, shipping compiled
JavaScript and declaring `pi-ai >=0.80.0`.

The source checkout `~/dev/github/nicobailon/pi-subagents` was at
`0a2a3bf38b0d49d0c8f62f4ed40719d102aea519`, two commits beyond the release:

- [`a10ba079`][fork-fix] teaches fork/pruned-fork context about Pi 0.87 session edits.
- [`0a2a3bf3`][peer-floor] raises the pi-ai peer floor to 0.86.1.

Its package version still says 0.70.1. Neither change is in the installed 0.70.1
artifact. A version string alone is insufficient to equate this checkout with the
release under assessment.

**Reproduced** below means a pure helper from the installed package was executed.
**Source-supported** means released code and the perk call site were compared.
**Needs validation** marks proposed adoption or live integration behavior.

| Perk integration | Current contract |
| --- | --- |
| [RPC adapter][rpc-adapter] | Versioned event API, correlation, timeout and stale-responder handling; no borrowed-package bare import |
| [Wave transport][transport] | Async, fresh-context, non-mission report runs; explicit acceptance `none`; intercom bridge off |
| [Report script renderer][report-wave] | Static `runs.all(...)` assignments, structured output, complete key/schema validation, `worktree: false` |
| [Child restrictions][restrictions] | Runner bit plus versioned extension binding establish a latched read-only floor |
| [Conflict resolver engine][resolver] | Foreground structured delegation with fresh context, canonical cwd, timeout, and result schema |
| [Doctor checks][doctor] | Recorded guidance baseline is 0.68.0; contains the older host-intersection diagnostic |

## 1. Integration changes that need fixing

### No reproduced protocol break in perk's current paths

**Source-supported.** Comparing 0.68.0 with released 0.70.1 found no changes to
`src/extension/rpc.ts`, `src/api/delegation.ts`,
`src/slash/delegation-request.ts`, or `src/api/required-child-extensions.ts`.
Perk's current report payload still fits the released interface.

The stricter [acceptance inference][up-acceptance] in 0.70.1 is relevant but already neutralized
where perk deliberately owns completion. An installed-helper probe showed:

| Acceptance request | Effective result |
| --- | --- |
| Generic report agent, inferred from read-only task words | `attested`, requiring manual notes/residual risks |
| Same report, perk's explicit `level: "none"` | `none`, no acceptance evidence requirement |
| Generic conflict resolver without a declared role | `attested` |
| Generic agent with a declared writer role | `checked` |

The last two rows describe the helper, **not a new conflict-resolver failure**.
The released [structured delegation adapter][up-delegation] explicitly sets
`acceptance: false`. Perk already uses that path. Keep report-wave acceptance `none`
and structured-result validation; do not add a writer role merely to repair a
failure that the current delegation path does not have.

### Pi 0.87 context compatibility has a known scope limit

**Source-supported; not a current fresh-context reproduction.** The later fork fix
updates context reconstruction for Pi's new session edits. Since both report waves
and conflict delegation explicitly request fresh context, this particular fork
defect does not establish a break in either flow. Do not claim general Pi 0.87
fork/pruned-fork compatibility for installed 0.70.1, or cite the checkout repair as
already shipped. If a future perk path uses fork context, require a release containing
the repair or verify an explicitly installed patched artifact first.

### Reverify before changing the compatibility stamp

The doctor guidance stamp is a recorded 0.68.0 baseline, not evidence that this
assessment ran live 0.70.1 waves. The [archived 0.68.0 record][old-reverify] explicitly
marks its browser leg **NOT EXERCISED**. Follow the current
[reverification procedure][reverify]: review the installed artifact, run required
CI, and complete both plan and PR browser waves with N/N keyed reports before
advancing the stamp. The procedure already accommodates compiled package output;
do not mistake absent installed TypeScript for a missing extension.

## 2. Adaptations to remove or tighten

### P1: remove ignored `completionGuard` declarations

**Source-supported; 0.70.1.** The release removes the completion-guard heuristic and
its configuration. Agent frontmatter no longer reads `completionGuard`; existing
declarations are ignored, not rejected.

Remove `completionGuard: false` from perk's ten report agents and the repo-local
session auditor. Update [packaged-agent tests][agent-tests] and
[repo-local-agent tests][local-agent-tests], plus current prose that presents the
field as active policy. The affected report agents are `objective-explorer`,
`pr-reviewer`, `learn-analyst`, `review-classifier`, `dream-reducer`, `scout`,
`adversarial-reviewer`, `harvest-analyst`, `draft-reviewer`, and `dream-analyst`.

This cleanup must not weaken perk's actual report completion contract: valid
structured output, expected key coverage, and parent-owned wake/completion logic.
The earlier `fallbackModels` removal was different: that field was rejected, and
perk already adapted. Do not repeat that migration.

### P1: retire the forced FFF mode and obsolete host-intersection diagnostic

**Reproduced at the tool-plan boundary; 0.70.0.** Upstream
[child tool planning][up-tool-plan] no longer intersects required builtins with the
host's registered builtin names. Release 0.68.0 only fixed how wrapped slots were
counted; 0.70.0 removes the intersection itself.

Calling installed `resolvePiLaunchToolPlan()` for `perk.pr-reviewer` with
`read, grep, find, ls, bash`, structured output enabled, and the old
`hostAvailableBuiltins: []` input retained all five tools plus `structured_output`,
with no warnings. The obsolete input was ignored. This proves planning behavior,
not successful execution of a live wrapped child tool.

On the chosen minimum baseline, remove the workaround that supplies
`PI_FFF_MODE=tools-and-ui` by default in [cold launch][launch] and
[worker launch][run-worker]. Retire the doctor check whose historical affected
range is `>=0.67.0, <0.68.0` and whose newer-version explanation still says
the package counts wrapped core slots. Do not extend that historical range to
describe a different upstream implementation.

Preserve an explicit user `PI_FFF_MODE` override. Check the resulting parent tool
experience as well as child `grep`/`find`, because removing a default can change
the parent's normal FFF mode. Update launch/doctor tests and the stale intersection
description in the [child execution policy][child-policy] in the implementation
change; this assessment leaves existing documents untouched.

### Keep the distinct controls that still have a job

- Explicit wave acceptance `none` remains necessary for perk-owned structured
  completion under the new default inference. Intercom bridge `off` remains part
  of the report lane's parent-owned orchestration.
- The runner bit and `perk.parent-restrictions/1` binding enforce read-only behavior
  and suppress inappropriate child context/scratch behavior. An upstream tool
  allowlist does not constrain arbitrary bash commands or replace those policies.
- Keep RPC correlation and stale/contextless reply guards. Neither the package
  changes nor Pi's event unsubscribe API prove the duplicate responder problem fixed.
- The 0.68 fallback-model and progress-field adaptations, and the bridge-off
  change, already landed. The [earlier assessments][earlier-audit] describe historical
  work; they are not a new task list for this baseline.

## 3. Improvements worth purposeful adoption

### P2: enforce existing no-delegation policy with `allowedAgents`

**Source-supported; 0.70.0; needs live validation.** The
[agent ceiling][up-agents] intersects inherited and runtime restrictions using
canonical, case-sensitive agent names. Omission introduces no new restriction;
an empty list denies all descendants. It does not grant a nested delegation tool.
This directly fits report agents and the conflict resolver whose instructions
already prohibit spawning descendants.

Prefer an explicit empty ceiling where that policy is already unconditional.
Respect the actual parser: frontmatter is CSV/newline based, and an empty key
`allowedAgents:` represents an empty list. Do **not** assume the YAML-looking
`allowedAgents: []` has equivalent semantics. The typed settings form
`agentOverrides.<name>.allowedAgents: []` is a valid alternative. Upstream
[frontmatter tests][up-frontmatter-test] cover the empty-key behavior.

Acceptance requires a denied descendant attempt in both relevant foreground and
background paths, unchanged parent access, and unchanged structured completion.
Retain perk's tool/bash restriction layer; these controls address different powers.

### P2: investigate required child extensions through a supported seam

**Source-supported; available since 0.68.0.** The public
[`registerRequiredChildExtensions()` API][up-required] registers session-scoped
`{ sessionId, extensions: [{ id, path }] }` requirements and returns a disposer.
The launch snapshot carries the requirement through overrides/nesting and fails
when a required extension is denied or cannot load.

This could strengthen delivery of a narrow report-child enforcement extension.
It is a bounded design spike, not permission to load all parent perk behavior into
every child. First resolve a supported import/package-resolution seam consistent
with perk's [bare-import guard][import-guard]; the current event protocol has no
equivalent registration call. Verify lifecycle disposal, path identity, override
attempts, denied loads, and the deliberate distinction between report children and
foreground writers before proposing adoption.

### Defer improvements that do not yet simplify the current contract

| Upstream improvement | Assessment for perk |
| --- | --- |
| Immutable workflow `args` in 0.68 | Could move task data out of generated script text, but [the resource loader][up-workflow] caps args at **16 KiB**. `runs.all(args.assignments)` may also lose static child-count validation. Keep the current static renderer until realistic wave sizes, batching, and failure semantics justify a change. |
| Typed gate JSON output in 0.69 | [Acceptance validation][up-acceptance] forbids combining it with `outputSchema`, which report waves already use. It is not a replacement for their completion path. |
| Runtime-agent model overrides in 0.70.1 | No immediate gap established for perk's current packaged-agent flows; adopt only for a concrete model-selection requirement. |
| Child-only cache-retention support in 0.68 | Potential operational benefit; measure first. No new perk configuration surface is needed merely because upstream has a knob. |

## Ordered implementation and verification

1. **Coordinate with the [Pi repairs][pi-assessment].** Preserve fresh context for
   current waves/delegation. Record the unshipped fork fix as a support boundary.
2. **Remove inert guard declarations and the intersection workaround.** Update
   only the policy/tests/docs owned by those changes. Honor explicit FFF settings
   and exercise wrapped tools in both parent and report child.
3. **Perform 0.70.1 reverification.** Check the installed compiled artifact, run the
   required CI, and collect successful plan and PR browser waves with full keyed
   report coverage. Exercise timeout/cancel and structured conflict delegation.
   Update the doctor guidance stamp only after the documented gates pass.
4. **Adopt descendant ceilings as a separate small change.** Verify empty-list
   parsing and actual enforcement before applying it to all intended agents.
5. **Keep required-extension delivery as a bounded spike.** Do not couple it to
   baseline cleanup or rewrite workflow payloads without evidence of a net benefit.

Borrowed packages are intentionally unpinned today. Choosing a minimum supported
baseline does not itself decide to pin their installation entries. That packaging
policy and compatibility certification must remain explicit implementation choices.

Completed evidence consists of release/source comparisons, installed artifact
inspection, and pure acceptance/tool-plan probes. No new live child execution,
browser-wave certification, or full CI result is claimed here. See the companion
[Plannotator assessment][plannotator-assessment] for browser protocol coverage.

[release-0680]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.68.0
[release-0690]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.69.0
[release-0700]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.70.0
[release-0701]: https://github.com/nicobailon/pi-subagents/releases/tag/v0.70.1
[fork-fix]: https://github.com/nicobailon/pi-subagents/commit/a10ba079ab89eb3b91f31fb74b28cb8696207015
[peer-floor]: https://github.com/nicobailon/pi-subagents/commit/0a2a3bf38b0d49d0c8f62f4ed40719d102aea519
[up-delegation]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/src/slash/delegation-adapters.ts
[up-tool-plan]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/src/runs/shared/child-tool-plan.ts
[up-acceptance]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/src/runs/shared/acceptance.ts
[up-agents]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/docs/agents.md
[up-frontmatter-test]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/test/unit/agent-frontmatter.test.ts
[up-required]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/src/api/required-child-extensions.ts
[up-workflow]: https://github.com/nicobailon/pi-subagents/blob/1ac7b5e2652e9571164847ac2905ab4aded92791/src/workflows/workflow-resources.ts
[rpc-adapter]: ../../extension/waves/rpcAdapter.ts
[transport]: ../../extension/waves/transport.ts
[report-wave]: ../../extension/waves/reportWave.ts
[restrictions]: ../../extension/substrate/childRestrictions.ts
[resolver]: ../../extension/pi/v1/delivery/conflictResolverEngine.ts
[doctor]: ../../src/perk/convergence/doctor/checks.py
[launch]: ../../src/perk/run/launch/__init__.py
[run-worker]: ../../src/perk/run/run_worker.py
[agent-tests]: ../../tests/test_subagent_agents.py
[local-agent-tests]: ../../tests/test_repo_local_agents.py
[import-guard]: ../../extension/bareImportGuard.test.ts
[child-policy]: ../design/pi-subagents-child-execution-policy.md
[reverify]: ../developers/pi-subagents-reverify.md
[old-reverify]: ../design/archive/pi-subagents-0.68.0-reverify.md
[earlier-audit]: new-package-release-audit.md
[pi-assessment]: pi-assessment-2026-09-21.md
[plannotator-assessment]: plannotator-assessment-2026-09-21.md
