# Driving Pi without a human UI

The central choice is not “terminal or no terminal.” It is which Pi interface perk treats as the
semantic boundary for a bounded unattended session.

## Recommendation

Use Pi's in-process SDK as the primary interior implementation and inject an unattended
`ExtensionUIContext` while binding extensions in RPC mode. Add a subprocess RPC adapter only when
process isolation or a language-neutral worker boundary becomes valuable. Keep terminal emulation
as a last-resort compatibility adapter, not the core.

This preserves extension semantics, typed tool calls, session events, and cancellation without
making ANSI output, focus, dimensions, or terminal timing part of perk's execution contract.

## What Pi exposes

Pi has three relevant surfaces:

| Surface | Shape | UI state | Best use here |
| --- | --- | --- | --- |
| SDK | `createAgentSession` and `AgentSession` in the same process | Caller supplies extension bindings | Primary TypeScript worker |
| RPC mode | Line-delimited JSON subprocess protocol | `ctx.mode = "rpc"`, `ctx.hasUI = true`; UI calls become requests | Optional isolated worker or non-TypeScript controller |
| TUI in a PTY | Human terminal application | Full interactive rendering | Manual operation and compatibility fallback |

The local Pi documentation describes the [SDK](../../library/pi/sdk.md) as the interface for
programmatic use and automated pipelines. The [RPC protocol](../../library/pi/rpc.md) exposes
extension UI calls such as `select`, `confirm`, `input`, and `editor` as structured request/response
messages. The [extension mode matrix](../../library/pi/extensions.md) says RPC has UI while JSON and
print modes do not.

## Primary design: SDK plus policy UI

The existing worker already constructs an `AgentSessionRuntime`. Its binding can evolve from:

```ts
{ mode: "json", uiContext: undefined }
```

to a purpose-built unattended binding conceptually like:

```ts
{
  mode: "rpc",
  uiContext: unattendedPolicyUi,
}
```

This does not require launching `pi --mode rpc`. The mode tells extensions which semantics are
available; the SDK caller still owns the session in-process. The injected UI implementation can
resolve approved dialogs and reject everything else.

The policy UI should be a deep module. Its small interface hides question matching, retry counting,
provenance, and receipt creation:

```ts
interface UnattendedDecisionPolicy {
  resolve(request: SemanticDecisionRequest): Promise<DecisionResolution>;
}
```

The session driver should not expose raw `select()` and `input()` calls to the exterior. It should
translate the allowlisted semantic interaction into a typed decision receipt in its final outcome.

### Why bind as RPC mode

`ask_user_question` is removed when `ctx.hasUI` is false. RPC mode retains it and routes its dialog
through ordinary UI calls. That makes the actual installed extension usable without patching or
forking it.

There is a risk: setting `hasUI=true` can awaken other UI-dependent extension branches. The policy
must therefore fail closed. An unexpected `confirm`, `editor`, `select`, `input`, or custom UI call
must end the recipe as `policy_violation`; it must never receive a generic affirmative response.

## The ask-user recommendation policy

The policy is intentionally narrower than “answer questions automatically.”

For each `ask_user_question` request:

1. identify options whose labels end in `(Recommended)`;
2. for a single-select question, choose its recommended option;
3. for a multi-select question, choose every recommended option;
4. record the question, presented options, chosen labels, policy version, and source as an
   unattended decision receipt;
5. if there is no recommendation, submit the custom answer:

   > No recommendation was provided. Please make a recommendation and ask again.

6. allow the agent one corrected re-prompt for that question;
7. if the corrected question still has no recommendation, halt with `policy_violation`.

“First option” can be a compatibility check, because the extension's authoring guidance puts the
recommendation first, but it should not be the selection rule. The visible `(Recommended)` marker
is more auditable and fails safely if the convention drifts.

The receipt must attribute the decision to `unattended-policy`, not to a human. Downstream prompts
can then distinguish an owner decision from a configured automation choice.

### Event versus dialog interception

The extension emits `rpiv:ask-user:prompt` before opening its dialog. Observe that event to attach
semantic identity and the complete option metadata to the pending decision. Resolve the ensuing
RPC-style UI call through the policy UI. Correlating the semantic event and UI request is safer than
matching dialog titles or agent prose alone.

If the expected UI request does not follow, or an unrelated UI request appears, fail closed. Do not
build a general-purpose “AI clicks dialogs” layer.

## Plan review is a separate semantic decision

Plan approval should not impersonate a click in Plannotator and should not pass through generic
`confirm()`. It is a first-party machine gate:

1. run the existing plan draft review wave directly;
2. require the four standard lanes plus Ponytail;
3. collect all available typed reports;
4. dispose every finding as fixed, already covered, or rejected with rationale;
5. rerender the plan if fixes changed it;
6. approve and save with a decision receipt.

Exactly one wave is allowed. Partial non-zero coverage may approve with a warning and named missing
lanes. Zero completed reports halt. This asymmetry preserves progress when one critic fails without
calling an unreviewed plan reviewed.

## Generalize the worker around recipes

`implement` and `address` are stages; `pr-review` is a command; `objective-plan` has special
positioning and save semantics. Forcing all four into the stage registry would blur real domain
differences. Introduce a bounded run recipe instead:

```ts
type RunKind = "objective-plan" | "implement" | "pr-review" | "address";

interface RunRecipe {
  kind: RunKind;
  primer: string;
  seed?: string;
  allowedTools: readonly string[];
  terminalSignals: readonly TerminalSignal[];
  budget: RunBudget;
  decisionPolicy: DecisionPolicyRef;
}
```

The recipe implementation should hide:

- session creation and replacement;
- extension resource tiers;
- initial prompt and handoff construction;
- tool allowlists and terminal predicates;
- token, turn, elapsed, and retry budgets;
- cancellation;
- normalized action and decision receipts.

Only create adapter interfaces where two implementations are real. The first refactor can deepen
the existing SDK worker without prematurely defining a universal agent-runtime port.

## Optional subprocess RPC adapter

A `pi --mode rpc` subprocess becomes useful when any of these are requirements:

- hard process isolation between conductor and model runtime;
- the conductor is no longer TypeScript-capable;
- independent worker upgrades or crash containment matter;
- raw Pi RPC transcripts are useful operational diagnostics.

The adapter would still consume typed JSON events and UI requests. Its output must normalize to the
same `RunOutcome` as the SDK implementation, so the exterior conductor cannot tell which process
topology ran the recipe.

Process lifetime and conductor lifetime are independent axes:

| Conductor style | Worker style | Valid? |
| --- | --- | --- |
| Attached loop | In-process SDK | Yes; simplest local implementation |
| Attached loop | Subprocess RPC | Yes; local isolation |
| Restartable one-step CLI | Remote SDK worker | Yes; current GitHub Actions direction |
| Durable workflow | Ephemeral SDK or RPC worker | Yes; strongest cloud resumption |

“Stepwise resumable” therefore does not mean the user must choose attached or fire-and-forget now.
It means the conductor can re-enter from durable state after each bounded action. A local command
may loop over `step()` while attached; a workflow service may invoke the same logical step in a new
container.

## Why not a cloud terminal emulator as the foundation

A PTY can run the existing human application with minimal initial integration, but it creates the
wrong durable boundary:

- prompts are inferred from presentation rather than semantic events;
- resizing, ANSI rendering, focus, and timing become correctness concerns;
- cancellation and terminal success are harder to distinguish from a hung UI;
- transcripts are weaker receipts than typed outcomes;
- browser/TUI doors can accidentally become reachable;
- replay after a container loss requires reconstructing terminal state rather than domain state.

A PTY adapter can still be valuable for an extension that exposes no SDK/RPC-compatible semantic
surface. That is not the current perk/Pi situation.

## Session-level failure contract

Every recipe should terminate with one of a small number of normalized outcomes:

```text
succeeded(action receipts, decision receipts, usage)
policy_violation(request, reason, receipts)
budget_exhausted(usage, last stable signal)
cancelled(reason)
failed(error class, retryability, diagnostics)
inconclusive(last stable signal, diagnostics)
```

The worker must not claim success merely because the Pi process exited cleanly. Success is a
recipe-specific terminal signal plus any required canonical postcondition, such as the draft PR
existing or the review being posted.

## Testing implications

The policy UI and recipe interpreter should be testable without a model:

- recommended single- and multi-select choices;
- no-recommendation complaint, corrected re-prompt, and second-failure halt;
- unrelated dialogs fail closed;
- duplicate semantic/UI events do not create duplicate decisions;
- recipe terminal signals cannot be borrowed across kinds;
- session replacement rebinds runtime observers and policy UI;
- SDK and any future RPC adapter satisfy the same conformance cases.

The interface is the test surface. Tests should assert typed outcomes and receipts, not terminal
text.

