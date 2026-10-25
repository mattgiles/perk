# Pi session management

Add a config-aware way to browse and resume Pi conversations, give perk sessions useful names,
and make the currently non-launching branches of `perk plan resume` useful for interactive work.
This ticket describes proposed behavior; implementing the commands is a separate change.

Today, perk launches can use a different `PI_CODING_AGENT_DIR` from a hand-run `pi`, making
sessions appear missing. Unnamed sessions display their first message in Pi's picker, so repeated
perk startup prompts make conversations difficult to distinguish. A submitted PR can also make
`perk plan resume` print guidance and exit even though its implementation conversation is useful
to reopen.

## Config-aware session picker

Add a local `perk resume [PLAN] [--worktree NAME] [--dry-run]` command:

| Invocation | Target |
| --- | --- |
| `perk resume` | The invoking checkout, including when invoked from a linked worktree. |
| `perk resume --worktree NAME` | An existing named worktree; `root` selects the main checkout. |
| `perk resume PLAN` | The selected plan's existing implementation worktree. |
| `perk resume PLAN --worktree NAME` | The named checkout, after validating its binding to the selected plan. |

Use the existing plan selectors, including backend-specific IDs and supported plan/PR URLs.
Resolve worktree names against the main checkout's effective configuration. Bare invocation
must not follow the main checkout's mutable active-plan selector into another worktree.

Launch native `pi --resume` in the target checkout. Pi owns session enumeration, its Current
Folder/All scopes, and selection: opening the picker is the default even when only one session
exists. Empty lists and cancellation retain Pi's native behavior.

Reuse the existing agent-directory precedence: a non-blank `PI_CODING_AGENT_DIR` environment
override, then the main checkout's effective `[pi] agent_dir` from committed config and the local
overlay, then Pi's normal default. Relative configured paths resolve against the main checkout;
blank inherited values receive the same normalization as existing launches.

Resume the selected conversation with its recorded identity and context. Do not mint a launch
run ID, write a new handoff, append a stage prompt, or apply fresh-stage model settings. Missing
or mismatched worktrees produce actionable diagnostics; this command does not create, restore,
or rebind checkouts. The dry-run preview reports the target checkout, resolved agent directory,
and Pi command without launching or writing state.

## Fill the non-launching plan-resume branches

Preserve **every existing path that launches a session**. For ordinary local interactive
`perk plan resume PLAN`, add the picker only where an unfinished plan currently receives a gate
message and no launch:

| Current outcome | Proposed behavior |
| --- | --- |
| No PR: `implement` | Existing implementation launch unchanged. |
| Actionable feedback: `address` | Existing address launch unchanged. |
| Merged, learning pending: `learn` | Existing learn launch unchanged. |
| Draft PR: `ready_for_review` | Print the existing guidance, then open the plan worktree's picker. |
| Awaiting review: `awaiting_review` | Print the existing guidance, then open the plan worktree's picker. |
| Closed unmerged PR: `pr_closed` | Print the existing guidance, then open the plan worktree's picker. |
| Merged and learned: `done` | Existing done report unchanged. |

Retain the distinction between incremental and stacked guidance. Opening a conversation does
not mark a PR ready, reopen it, address feedback, or cross any review/landing gate.

If the worktree is unavailable, retain the gate report and explain the missing checkout rather
than starting fresh work. Remote behavior, machine reports, and dry-run gate reports stay
noninteractive. Do not change the shared next-action classifier used by the objective supervisor;
this is an interactive response to its existing gate outcomes.

## Persistent, useful session names

Use Pi's existing `setSessionName` API for new perk sessions and unnamed sessions when reopened.
The picker displays and searches these names, which persist in native `session_info` entries.

The label describes the conversation's **original purpose**, enriched with a plan ID, objective
ID/node, and meaningful title when available. Examples:

```text
plan | Improve session discovery
plan | plan #2460 | Improve session discovery
implement | plan #2460 | objective #2400 / 2.1 | Improve session discovery
review | plan #2460 | Improve session discovery
```

- Derive identifiers from recorded workflow linkage and topics from available plan, objective,
  or draft titles. Add identifiers when they become available, including after saving a plan.
- Keep the original purpose stable: an implementation conversation stays labeled `implement`
  after submitting or reviewing. A conversation originating in review can be labeled `review`.
- Preserve manually supplied names, including `/name` and `--name`. Record ownership of
  generated names and update one only while it remains owned by perk.
- Omit unknown details rather than guessing them. An older session's original purpose must come
  from available origin records, not an assumption that its latest stage was its purpose.
- Treat naming as best-effort metadata: failures are reported but do not block startup.

Bulk historical renaming and archive scans before opening the picker are out of scope. Existing
unnamed sessions gain labels when reopened, so their next appearance in the picker is clearer.

## Implementation guidance and acceptance

Build on these existing seams:

- `launch_pi_agent_dir` and `effective_pi_agent_dir` in
  [the config module](../../src/perk/substrate/config.py) own agent-directory resolution.
- `select_plan` in [plan selection](../../src/perk/cli/plan_selection.py) and
  `resolve_plan_worktree_name` / existing-checkout validation in
  [worktree positioning](../../src/perk/run/launch/worktree.py) supply selection rules. Reuse
  validation without entering the positioner's creation or restoration paths.
- `resume_cmd` in [plan resume](../../src/perk/cli/commands/plan/resume_cmd.py) owns the gate
  response; `resolve_next_action` remains the shared classifier. Keep session resumption separate
  from fresh-stage launch orchestration while sharing applicable launch-environment preparation.
- `establishSessionIdentity` and `resolveSessionStartFacts` in
  [the session lifecycle](../../extension/session/lifecycle.ts), together with authoring/save
  linkage updates, provide the context and events for naming.

Pi source reference: `~/dev/github/earendil-works/pi/packages/coding-agent/src/`.
`core/extensions/types.ts` exposes `setSessionName` / `getSessionName`;
`core/session-manager.ts` persists names; `modes/interactive/components/session-selector.ts`
displays `session.name ?? session.firstMessage`; `session-selector-search.ts` searches names.
The feature can use these existing Pi capabilities entirely from perk.

Future implementation acceptance criteria:

- Verify main/linked checkout selection, named worktrees, plan selectors, combined selectors,
  and missing/mismatched targets. Bare selection must stay in the invoking checkout.
- Cover configured agent directories, main-checkout local overlays, relative paths, explicit
  environment overrides, and blank-value normalization; check preview/launch agreement.
- Verify picker launches preserve conversation identity and add no handoff or startup prompt.
- Preserve existing implementation/address/learn launches and remote/machine behavior. Cover
  picker launches at all three gate outcomes, unavailable worktrees, and the unchanged done case.
- Verify names survive reload/resume, gain identifiers after save, retain original purpose,
  preserve manual edits, and tolerate missing metadata or naming failures without blocking work.
- Exercise the picker with named planning, implementation, and review sessions in main and
  linked worktrees. Use the existing `pytest` and `node:test` suites for regression coverage.

When implementing the feature, update the CLI help/reference and resume how-to in
`docs/user-docs/`, the matching configuration reference in `skills/perk-expert/references/`, and
`shared/contracts.md` for the cross-plane behavior. Keep those updates with the implementation;
this planning ticket does not advertise unbuilt commands as available user functionality.
