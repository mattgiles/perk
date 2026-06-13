# erk's use of subagents — findings and governing principles

A systematic reading of the subagent-related learned docs in
the erk repo's `docs/learned/`. The goal is to extract the *governing principles* —
when erk delegates to subagents, why, and how — so perk can port the **judgment**, not
the Claude-Code-specific mechanism. A perk/Pi mapping closes the document (§11).

Primary sources (most load-bearing first):
`planning/agent-delegation.md`, `planning/agent-orchestration.md`,
`planning/agent-orchestration-safety.md`, `planning/agent-output-routing-strategies.md`,
`planning/sub-agent-context-limitations.md`, `planning/subagent-output-handling.md`,
`planning/token-optimization-patterns.md`, `planning/parallel-audit-pattern.md`,
`planning/exploration-strategies.md`, `architecture/parallel-agent-pattern.md`,
`architecture/task-context-isolation.md`, `architecture/context-efficiency.md`,
`architecture/agent-backpressure-gates.md`, `architecture/agent-schema-enforcement.md`,
`architecture/inference-hoisting.md`, `claude-code/context-fork-feature.md`,
`testing/devrun-agent.md`, `reviews/development.md`, `reviews/test-coverage-agent.md`,
`commands/tool-restriction-safety.md`, `planning/scratch-storage.md`.

---

## 0. The mental model (what a subagent *is* in erk)

erk runs on Claude Code. A "subagent" is an **isolated, disposable agent context** spawned
by a parent (the "root agent"), via one of two surfaces:

- **Manual `Task()`** — the parent writes a prompt at runtime and launches a child, optionally
  `run_in_background: true`, collecting the result with `TaskOutput(task_id, block: true)`.
- **`context: fork`** (Claude Code 2.1.0+) — declarative: a skill/command file's body *becomes*
  the entire prompt for a fresh child agent. The `agent:` frontmatter field picks the child
  type (`general-purpose`, `Explore` read-only, `Plan`); `allowed-tools` bounds its tools.

The defining property erk leans on everywhere: **a subagent's context is disposable.** When the
Task completes, all the verbose intermediate work (raw API JSON, classification reasoning,
file reads) *disappears* — only the child's final message enters the parent. Subagents are,
first and foremost, **a context-management device**, and only secondarily a parallelism or
cost device.

A second defining property: **a subagent is a capability boundary.** Its `allowed-tools` is the
hard limit on what it can do, and restrictions are **transitive** — a tool-restricted command's
children are intersected down to (at most) the parent's set.

---

## 1. The five governing principles

Everything below reduces to these.

1. **The parent context is the scarce resource; subagents are disposable buffers.**
   *Route* data between agents (pass file paths / compact summaries); never *relay* it (read
   it into the parent only to hand it onward). The "token sink" is always content fetching —
   push fetching down into children so the parent stays O(1) regardless of input volume.

2. **Authority follows capability — and it cascades.** Give a child exactly the tools its job
   needs (minimal-set), starting from zero. Read-only is enforced *structurally* (tool list),
   not by prompt instruction, and the guarantee inherits through the delegation chain.

3. **Judgment stays high, mechanics go low.** Quality-critical reasoning (prose reconciliation,
   design/architecture analysis, creative authoring, decisions the user will live with) stays
   in the parent / a top-tier model. Mechanical work (fetch, parse, classify, format, bucket)
   goes to cheap children. The same split governs *inference hoisting* (§8): deterministic
   subprocesses get pre-computed values, not nested reasoning.

4. **Trust nothing across the isolation boundary.** Outputs truncate silently, file writes fail
   silently, agent JSON drifts from its schema. Therefore: verify at the orchestration layer,
   hand off through files, and **gate** structured output with actionable feedback.

5. **The orchestrator owns control flow; agents are self-contained.** Launch order, model
   selection, file paths, and synchronization are the parent's job. Agent definitions never
   reference each other and carry no cross-agent state.

---

## 2. WHEN to delegate (and when emphatically not)

erk treats delegation as **earned, not default**. The decision tree (`agent-delegation.md`):

```
Does the command orchestrate 3+ steps?
├─ YES → consider delegation
└─ NO → Is error handling extensive (>50 lines)?
    ├─ YES → consider delegation
    └─ NO → Does it manage complex state?
        ├─ YES → consider delegation
        └─ NO → keep it inline
```

**Good candidates:** multi-step workflows (3+), heavy error formatting/recovery, cross-operation
state, tool orchestration, repeated patterns shared by several commands, and — the big one —
**context reduction**: processing large input (1000+ lines) under deterministic rules to return a
compact proposal (e.g. changelog: 2000+ commit lines → a 50–100 line proposal, ~95% reduction).

**Do NOT delegate (these are the sharp constraints, the parts most easily gotten wrong):**

- **Judgment-quality reasoning.** Prose reconciliation, design analysis, architectural comparison
  need top-tier reasoning *in the parent*. Delegating them to a cheap child loses quality.
  Case study: `/erk:system:objective-update-with-landed-pr` (PR #7336) was **refactored *back*
  from subagent delegation to inline execution** because two steps (prose reconciliation; a
  closing user prompt) needed caller-level model quality and user interaction. *erk actively
  pulls work back out of subagents when judgment or interaction is involved.*
- **Direct user interaction.** Subagents cannot relay interactive prompts ("Should I close
  this?"). User-facing questions must happen in the caller's context.
- **Session-bound bookkeeping.** See §3 — a hard platform constraint, not a style choice.
- **Data already in context.** If step 1 already fetched it, later steps use it directly.
- **Trivial wrappers / pure routing / config / status display.** No orchestration to hide.

---

## 3. The session-id constraint and the "root-agent-first sandwich"

The single most important *hard* constraint (`sub-agent-context-limitations.md`):

> `${CLAUDE_SESSION_ID}` is injected as a string substitution **only at the root-agent level**.
> Task subagents run in isolated contexts that do **not** inherit it. Any command needing
> `--session-id` (e.g. `plan-save`, `impl-signal started/ended`) **silently degrades** when
> delegated — the variable expands to empty.

Consequences erk codifies:

- **Classify every command** as session-dependent or session-independent *before* designing a
  workflow.
- **Session-dependent commands run in the root agent**, never inside a child. The pattern is a
  **sandwich**: the root does the session-bound bookkeeping (signal start … signal end), and the
  *implementation work in between* may be delegated. (`/erk:plan-implement` Steps 6 & 10 are the
  canonical brackets.)
- **Pass resolved values, not variable references.** If a child genuinely needs the id, the root
  must resolve it to a literal first — `${CLAUDE_SESSION_ID}` inside a child's prompt is dead text.
- erk's commands **fail loud** here (a structured `session-id-required` error) rather than
  proceeding with empty state — graceful degradation that doesn't get masked by `|| true`.

The generalized lesson for perk: **whoever owns durable identity/state owns those writes** — they
do not delegate across an isolation boundary.

---

## 4. WHY delegate — the four payoffs (ranked as erk ranks them)

### 4.1 Context isolation / token economy (the primary reason)
`task-context-isolation.md`, `context-efficiency.md`, `token-optimization-patterns.md`.

- A PR-comment fetch is ~2,500–3,000 tokens of raw JSON the parent doesn't need; processed in a
  child it returns ~750–900 tokens of summary — **65–70% reduction**, and the raw JSON *never
  enters* the parent.
- For **N-document analysis**, fetching in the parent is O(n) (7 plans × ~5k = ~35k tokens
  resident forever); delegating fetch-and-analyze to N children makes the parent grow only by
  N × summary (~8k total) — **~82% reduction** observed.
- Core insight: **content fetching is the token sink.** Move it into children; the parent sees
  only summaries.

### 4.2 Structural safety (read-only oracles)
`devrun-agent.md`, `tool-restriction-safety.md`, `reviews/development.md`.

erk's `devrun` agent is the exemplar: a **read-only, stateless oracle** that runs CI commands
(pytest/ty/ruff/prettier) and reports parsed results — it cannot edit. This deliberately separates
**observation from mutation**, which solves three problems:

1. **Unambiguous failure attribution** — every devrun report is a clean signal the parent must act on.
2. **No runaway fix loops** — a child that can both run and edit can silently break-then-"fix";
   removing Write/Edit makes that *structurally impossible*.
3. **Cost control** — the oracle is haiku; the expensive reasoning (what to fix) stays in the parent.

Enforced at **three levels** (defense in depth): the agent's `tools` list (no Write/Edit), explicit
forbidden-Bash-pattern instructions (no `sed -i`, `tee`, output redirection — closing the
"mutate via Bash" loophole), and a per-prompt reminder hook so even the parent doesn't bypass it by
running the tool directly. Tool restrictions are also **transitive** — a command restricted to
`Read, Glob, Grep, Task` can spawn children, but those children are intersected down to `Read,
Glob, Grep`. This is what makes read-only commands safe *inside plan mode*.

### 4.3 Parallelism
`parallel-agent-pattern.md`, `parallel-audit-pattern.md`. Independent work runs concurrently
(`run_in_background: true`) → wall-clock = slowest child, not the sum. Cap ~10 parallel children
(rate limits); for more items, batch (round-robin partitioning distributes evenly). Tolerate
partial failure: skip a failed item, note it, don't let one failure block the rest.

### 4.4 Model tiering / cost
`token-optimization-patterns.md`, `agent-orchestration.md`. The **orchestrator** (not the agent
definition) picks the model per launch, so one agent def runs at different tiers in different
contexts. Escalation rule:

| Work type | Model | Why |
|---|---|---|
| Mechanical: fetch / parse / format / bucket | **haiku** | deterministic, no creativity |
| Rule-based synthesis: dedup, classify, enum-mapping, scoring | **sonnet** | applying explicit criteria; status/label reasoning |
| Creative authoring: plan narrative, quality-critical prose | **opus** | the output *is* the deliverable |

Anti-pattern: "use opus everywhere to be safe" — wastes tokens/latency on mechanical work. Reserve
opus for agents whose output quality is the final product.

---

## 5. HOW erk orchestrates — topology

### 5.1 Command–agent delegation (separation of concerns)
`agent-delegation.md`. **Commands are the user-facing "what" contract** (<50 lines, prerequisites,
a *single* Task call, no inline logic); **agents implement the "how"** (orchestration, error
handling, reporting). One agent serves many commands; agents are tested independently; errors are
handled once in the agent (consistent templates) instead of duplicated across commands. Anti-patterns:
running a tool directly when an agent exists, embedding orchestration in the command, and **mixing
delegation with inline logic** (partial delegation muddies the boundary — delegate fully or not at all).

### 5.2 Multi-tier orchestration (parallel extraction → sequential synthesis)
`agent-orchestration.md`, `parallel-agent-pattern.md`. The canonical shape (the `/erk:learn` and
`/erk:replan` workflows):

```
Parallel tier   (independent, run_in_background)   ── analysis reads independent sources
  ├─ SessionAnalyzer        (sonnet)
  ├─ CodeDiffAnalyzer       (sonnet)
  ├─ ExistingDocsChecker    (sonnet)
  └─ PRCommentAnalyzer      (sonnet)
        │   ← tier boundary = synchronization point (block until ALL done)
Sequential tier 1  DocumentationGapIdentifier   (reads all parallel outputs)
Sequential tier 2  PlanSynthesizer              (opus — creative authoring)
Sequential tier 3  TripwireExtractor            (sonnet — structured extraction)
```

The governing insight: **analysis and synthesis have different dependency structures.** Analysis
reads independent sources (parallelizable); synthesis is inherently sequential (each step needs all
prior output). The 2-tier split is the *minimum* structure capturing both — merging into one
sequential pipeline wastes time; merging into one parallel pipeline produces incorrect synthesis
(agents reading incomplete inputs). Placement rules for a new agent: reads a primary source →
parallel tier; needs another agent's output → sequential tier after its dependency. Use 2-tier only
when there's real fan-out *and* a combine-all step; a single linear pipeline needs no tiers.

### 5.3 Output routing — who owns the prompt
`agent-output-routing-strategies.md`, `context-fork-feature.md`. Two strategies, chosen by **prompt
ownership**:

- **Embedded-prompt routing** (paths/inputs in the orchestrator's `Task` prompt) → reusable generic
  agents, orchestrator controls data flow, dynamic per-invocation. Use for multi-workflow agents and
  any **runtime-dependent** prompt (session ids, PR numbers extracted at runtime).
- **Agent-file routing** (`context: fork`; the contract baked into the skill/command file) →
  self-contained single-purpose agents, concise orchestrator, fixed output. Use for **reusable
  fetch-and-classify** logic with static rules (e.g. `pr-feedback-classifier`).

The **empty-output trap** for `context: fork`: the forked body must be a *task with concrete steps*,
not ambient guidelines ("here's how to approach X"). A subagent executes tasks; it has nothing to
*do* with reference material and returns empty.

---

## 6. HOW erk orchestrates — safe data handoff

This is where the deepest, hardest-won lessons live (`agent-orchestration-safety.md`,
`parallel-audit-pattern.md`, `context-efficiency.md`, `subagent-output-handling.md`).

**Two silent data-loss failure modes** — both produce no error, just truncated/missing data:

1. **Inline output truncates at ~10KB** (Bash/tool output channel). Analysis agents routinely emit
   10–30KB of markdown. Captured inline, the tail is silently dropped; a downstream synthesizer then
   produces a plausible-but-incomplete result the orchestrator can't detect.
2. **`Write` fails silently when the parent directory is missing.** A dependent child then burns its
   *entire* context window only to discover its input file isn't there.

**The fix — the three-step handoff** (applied at *every tier boundary*, never within a tier):

1. **Write** — the producing agent saves output to session scratch
   (`.erk/scratch/sessions/<session-id>/<step>.md`) via the Write tool.
2. **Verify** — the *orchestrator* confirms the file exists (`ls`). Fail-fast at the orchestration
   layer; **never** verify inside the dependent child (that wastes the child's whole budget).
3. **Pass the path** — launch the consumer with the file *path*, not the content.

**Supporting rules:**

- **Self-write, don't relay.** The *content-relay anti-pattern* — `TaskOutput` the content into the
  parent, then `Write` it to a file — duplicates 60–180K tokens in parent context (read once, write
  once) and can exhaust the window. Instead, instruct the child: *"Write your analysis to
  {path}. Do not return the content."* The parent routes paths and never loads the content.
- **Block before you depend.** `TaskOutput(block: true)` on every background child before any
  dependent op. Real failure mode: a synthesis agent found 1 of 3 input files because the parallel
  writers hadn't finished. (`/erk:replan` Step 4e is the canonical "wait for ALL.")
- **Use Write, not heredocs.** `cat <<EOF > file` corrupts markdown (backticks, `$`); the Write tool
  doesn't.
- **Persisted-output markers.** When a child's structured output is large, Claude Code may persist it
  to a file that contains the *raw transcript* (tool calls, system messages), not clean JSON. Parse
  JSON from the output *content*; do **not** `Read`/`cat`/`grep` the persisted path.

**Scratch storage discipline** (`scratch-storage.md`): AI-workflow intermediates live in
`.erk/scratch/sessions/<session-id>/` — worktree- and session-scoped, isolated per session so
parallel sessions never collide — **not** `/tmp` (reserved for shell-sourced files). Session-scoped
plans live at `.../<session-id>/plan.md`, enabling parallel sessions to find their own plan without
mtime races.

---

## 7. HOW erk orchestrates — the output *contract*

`task-context-isolation.md`, `context-fork-feature.md`.

- **Double-delivery: prose + JSON in one message.** Children return a **compact prose summary**
  (for the user to read) *and* a **structured JSON block** (for the parent to act on — thread ids,
  classification labels). The parent shows the prose and silently regex-extracts the JSON. One
  invocation serves both human display and machine action.
- **Errors appear in both formats**, with a `success` boolean the parent checks first (so it never
  tries to parse empty arrays).
- **Prose-leakage anti-pattern.** If the child copies verbose data into its prose summary (quoting
  2000 tokens of comment text), the isolation is defeated — the parent sees all of it. Keep prose a
  compact table; keep full detail in the JSON (e.g. a truncated `original_comment` for debugging).
- **Specify the output contract or pay for it.** Delegating without an explicit return format yields
  verbose unstructured output that costs as many parent tokens as the raw content would have. Don't
  "summarize summaries" — if a child's output is too big, fix *that child's* contract, don't add a
  layer.

---

## 8. The inverse boundary — inference hoisting

`inference-hoisting.md`, `agent-backpressure-gates.md`, `agent-schema-enforcement.md`. The same
"judgment-high / mechanics-low" principle (§1.3) also says where reasoning must *not* go:

- **No nested reasoning in deterministic subprocesses.** erk's exec scripts are Python subprocesses
  that run to completion with no agent context. Calling the Claude CLI from inside one (a nested
  LLM-in-LLM call) **deadlocks**. The fix: **hoist** the inference up to the skill/agent layer — the
  agent reasons to produce the value (e.g. a branch slug, a plan summary) and passes it to the script
  as a `--flag`. Reasoning lives in the agent layer; the script is purely deterministic.
- **But lightweight inference can live low.** A *direct* Anthropic SDK call (`LlmCaller`, haiku,
  `max_tokens=50`, ~200ms vs ~5s for a CLI subprocess) is fine inside the dispatch/CLI layer for
  slug generation or classification. The boundary is **mechanism, not "is there an LLM"**: full
  agentic reasoning hoists up; a bounded one-shot SDK call can stay.
- **Back-pressure gates instead of silent transforms.** When an agent *produces* a value, enforce it
  with a programmatic **gate** (regex / type-check / test / schema validator) that loops on failure
  with **actionable feedback** (expected pattern + actual value + examples) so the agent
  self-corrects. *Never silently sanitize* agent output — that masks the mistake and the agent never
  learns. (Silent transformation is for *human* producers where UX beats compliance signals.)
- **Normalize-then-validate at the boundary.** Agent JSON drifts (root-key/field-name drift, extra
  or missing fields) — that's a property of LLM systems, not a bug. Defense in depth: inline the
  schema in the prompt (reduce drift) + normalize known aliases at the boundary (recover) + validate
  and reject what's still malformed (correctness). Strip unknown fields so downstream code can't
  depend on drift.

---

## 9. Subagents as reviewers (the read-only-executor family)

`reviews/development.md`, `reviews/test-coverage-agent.md`, `devrun-agent.md`. erk's CI/review
agents are a specialized, hardened instance of read-only delegation:

- **Reviews are read-only by definition.** Each review is a markdown spec discovered by convention
  (drop a file in `.erk/reviews/`, no per-review workflow). Frontmatter sets the **security boundary**
  (`allowed_tools`, typically just `Read(*)` + `Bash(gh:*)` — never Write), `model` (haiku default,
  escalate only for deep reasoning), `paths` (trigger scope), and a unique `marker`. "If your review
  needs to modify files, it isn't a review — it's a linter/formatter belonging to a different job."
- **Classification taxonomy over prose.** Specs give explicit categories with actions ("Category A
  thin CLI wrapper → skip; Category B new source w/ logic → flag") rather than "analyze and flag
  issues." This produces meaningful activity logs and fewer false positives — the same
  prose-vs-structured discipline as §7.
- **The Run→Report→Fix→Verify cycle** (devrun): the read-only child is a *stateless oracle* invoked
  repeatedly; the **parent owns the entire fix loop and all iteration state**. Prompts must always be
  "Run [command] and report results" — never "run and fix," "keep running until green," or "continue
  the remaining failures" (assumes cross-invocation memory the child doesn't have).

---

## 10. Explore-then-Plan

`exploration-strategies.md`. Subagents also front-load *discovery*: launch parallel **Explore**
(read-only) children to gather facts — file locations, existing patterns, API surfaces, test
structures — *then* enter plan mode with full context and write the plan without further discovery.
Rationale: plan mode is optimized for *writing*, not *discovery*; mixing mechanical reads into
planning fragments the session. Search `docs/learned/` first (documented patterns beat re-discovery),
then verify against source. Skip exploration only when the task is small/known or a direct follow-up.

---

## 11. What this means for perk (Pi mapping)

perk should port the **principles** (§1) and the **safety machinery** (§3, §6, §7, §8), and re-host
the Claude-Code mechanism (`Task`/`context: fork`) on Pi primitives.

| erk concept | perk / Pi realization |
|---|---|
| `Task()` subagent | Spawn `pi --mode json -p --no-session --tools <set>` (Pi `examples/subagent/`), or a read-only SDK session (`createAgentSession` with `tools:["read",…]`). Parse JSON events; propagate abort. |
| `context: fork` (reusable, isolated) | A spawned read-only child session, or `ctx.newSession` handoff for a fresh context. The "empty-output trap" still applies: a forked surface needs a concrete task. |
| Disposable child context (the whole point) | **Cap model-visible output but keep the full result in the tool-result `details`** (fork-safe persistence) — the Pi analogue of "return a summary, not the raw data." This *is* §4.1 + §7 in one primitive. |
| Read-only oracle (`devrun`) + tool-restriction inheritance | perk's **gating primitive**: `setActiveTools` allowlist + `tool_call` blocking. Build it once; reuse for plan mode *and* the read-only CI executor. Structural, not prompt-based — same as erk's three-level enforcement. |
| Three-step file handoff + verify at orchestrator | Children write to `.pi/workflow/` session scratch; the orchestrator verifies before launching dependents. Prefer passing **paths / `details` refs**, never relaying content through the parent. |
| `TaskOutput(block:true)` synchronization | Await child sessions / JSON-event completion before any dependent step; tier boundaries block. |
| Double-delivery (prose + JSON) | Children return compact human text + a structured block the orchestrator parses; errors carry a `success` flag. Keep verbose detail out of the prose. |
| Model tiering (haiku/sonnet/opus, orchestrator-chosen) | Per-spawn model selection in Pi; cheap models for mechanical children, top-tier reserved for parent-level authoring. |
| `${CLAUDE_SESSION_ID}` isolation → root-agent-first | Session-bound / durable-state writes stay with the owner (the in-session extension or the CLI supervisor); never delegate them across a spawn boundary. The supervisor owns the queue; children own bounded mechanical work. |
| Inference hoisting (no nested reasoning in deterministic code) | Keep perk's deterministic extension tools / Python CLI free of agentic reasoning; the agent reasons and passes computed values. Bounded one-shot inference may sit low; full agent loops hoist up. |
| Back-pressure gates + normalize-then-validate | Validate agent-produced JSON at the tool boundary with actionable rejection (loop, don't sanitize); normalize known drift before validating. |

**The one-line takeaway for perk:** subagents are a *context and capability* device before they are a
parallelism device. Delegate to move verbose work out of the parent and to make read-only work
structurally safe — but keep judgment, user interaction, and durable-state writes in the owner, hand
data off through verified files/`details` rather than relaying it, and gate everything that crosses
the isolation boundary.
