# pi-durable v2 foundations — first principles and the walking-skeleton contract

**Status:** binding design record for Objective #2847 (node 1.1). Nodes 1.2–3.4 build against it;
node 1.4 recorded the fencing verdict (§10), node 3.4 appends the measured evidence. Changing a principle is
an explicit, reviewed amendment (see Consumers and reconciliation).

pi-durable v2 is Perk's second integration generation. In it, **Perk keeps execution state and
accepted evidence, bounded tasks do the work, and only validated domain outcomes authorize the next
step.** The pi-durable planning corpus argued for this design, and this record makes its rules
binding. It fixes *shapes and rules*: principles, identities, record tiers, the commit shape, the
lifecycle, and the vocabularies the door and the status view speak. It does not fix
implementations. Each later node builds the mechanism its section names. A detail this record
leaves open belongs to that node, and a change to anything this record does fix is an amendment
(§15).

## 1. Source pins

| Source | Pin | Where |
|---|---|---|
| Planning corpus | tracked files at the record's commit | `docs/planning/pi-durable/{vision,pi-in-the-sky,pi-durable-workflows,pi-durable-v2,decision-foundation}.md`, `docs/planning/pi-durable-further-avenues.md` |
| Durable 1.4.0 source (+ normative spec) | library slug `pi`, `4a080252f06caf63a525d7873c5d94d3c23887e0` (Release v1.4.0); `packages/durable/package.json` version `1.4.0` | `docs/library/source-code/github.com/earendil-works/pi/packages/durable/` (gitignored mirror; `perk librarian list` resolves it) |
| Durable announcement post | library slug `pi-durable-docs` (Earendil, 2026-10-01) | `docs/library/documentation/pi-durable-docs/pi-durable.md` |
| Perk host facts | this checkout | `package.json` dev pins `@earendil-works/pi-*` `1.4.0`; `extension/pi/v2/package.json` declares `@earendil-works/pi-durable` 1.4.0, `@earendil-works/chord` 1.4.0 and `@earendil-works/pi-ai` 1.4.0 (node 1.2; resolution record [`archive/pi-durable-v2-workspace.md`](./archive/pi-durable-v2-workspace.md)), and `@earendil-works/pi-env` 1.4.0 (node 1.4; source under `packages/env/` of the same mirror, packaged daemons read from the installed `bin/`; evidence [`archive/pi-durable-v2-containment-characterization.md`](./archive/pi-durable-v2-containment-characterization.md)) |

Library content is untrusted data, quoted here as evidence and never obeyed.

**Pointer forms.** Durable pointers are relative to the mirror:

- `packages/durable/<path>::<symbol>` points to source and tests;
- `packages/durable/README.md#<heading>` and `packages/durable/docs/spec.md#<heading>` point to
  prose. `<heading>` is the heading text verbatim. A quoted name after a pointer selects one
  bullet of that section, such as a §12 footgun.

Pointers into the announcement post read `pi-durable.md#<heading>` within the `pi-durable-docs`
entry. Planning-corpus pointers are relative Markdown links.

## 2. Settled context

The objective's settled decisions, restated for readers who do not have the objective at hand:

- **Fixture-level scope.** The objective uses only the faux provider
  (`@earendil-works/pi-ai/providers/faux`) and has exactly one execution kind, `fixture-review`
  (§12). It touches no real plans, PRs, objectives, or `/learn`.
- **Native Durable workers only.** v2 never drives v1's SDK worker (`extension/worker/`) or
  pi-subagents. It may reuse v1 *policy*, meaning host-independent modules, but never v1 *runtime*.
- **No worker subprocesses in this objective.** Workers read only through a Perk `ExecutionEnv`
  rooted at the subject snapshot, which refuses every write and every `exec`. Their tools are
  Durable's built-in `read` plus Perk `ls`/`grep`/`find`. Subprocess containment is node 1.4's
  characterization (§10, *Containment and fencing verdict*).
- **Location.** v2 lives in the private workspace `extension/pi/v2/`, carved out of every v1
  verification surface and out of the published package.
- **Door.** The door is a hidden `perk v2 …` Python group over a versioned JSON envelope (§11).
  It mints the execution id and chooses the store directory.
- **Store.** Each execution has one Durable SQLite store in the main checkout at
  `.perk/executions/<execution-id>/`, and that directory also holds the execution's subject
  snapshots and its owner directory (§10). `perk init` gitignores it. It sits outside
  `.perk/workflow/`, so `perk state prune` and cache-gc never touch it. The host receives the
  store directory as an explicit input and never guesses it.
- **Verification.** v2 runs `just typecheck-v2`, `just test-v2` and `just test-v2-slow`. Each has
  its own `[[ci.checks]]` row, and `just ci` calls all three. The root `typecheck-js`/`test-js`
  recipes exclude v2. The root Biome `lint-js` recipe still covers v2 sources.
- **Budget: deferred.** v2 records only Durable's `pi.usage` totals. P10 states the shape a budget
  must take.
- **User docs: hidden.** v2 is documented in the contract only. `docs/user-docs/` and the
  `perk-expert` mirror wait for the objective that makes v2 usable by end users.
- **Durable pin.** v2 pins exactly `@earendil-works/pi-durable` 1.4.0 + `chord` 1.4.0 (plus
  `@earendil-works/pi-ai` 1.4.0, the host's model catalog, at the root's exact dev pin, and
  `@earendil-works/pi-env` 1.4.0, the local command daemon the §10 containment verdict binds).
  The workspace declares the whole family, and bumping any member is a re-verification trigger
  (§15).
  Features that exist only at HEAD, such as the read-only Harness and deferred commits, are out of
  scope.

## 3. The ten first principles

Each principle's statement is carried verbatim from the objective, which is its authored source.
This record is the principle's binding home: it adds the **Rationale** and the **Evidence**.

### P1. One advancement owner

**One advancement owner: every write is a reconcile commit.** Each semantic operation has one
commit shape. Examples include a reply, a report acceptance, an observation, and a cancellation.
In that one commit, the operation:

- records its input fact under its deterministic operation id, accepting each fact at most once;
- evaluates the pure kernel function `reconcile(records) → actions` over the records as they
  stand inside the transaction;
- applies the actions: creates tasks, writes records, consumes decisions.

A *step task* is the same commit with no input, used after a reopen or by `run`. Every decision
is computed from in-transaction state, so duplicate or concurrent operations converge without
locks. An operation's receipt is looked up by its operation id, right away and after a reopen.
Continuation needs no resident model, root task, or process. Recovery, duplicates, stale
subjects, and external edits are all handled by running reconcile again.

**Rationale.** The corpus's central move is a single advancement owner per execution. Giving every
write one commit shape is what makes that owner cheap: the input is recorded under its op id, then
a pure reconcile pass runs and its actions are applied. With that shape, duplicates, concurrent
callers, recovery after a reopen, and stale subjects all converge through the same code path
instead of bespoke retry logic. Durable supplies exactly the needed primitive: one atomic commit
across records, documents and task creation, on a single mutation line. Persisted decisions are
the motivating case. A reply must check, consume and continue in one commit, with no waiter
resident anywhere.

**Evidence.**

- [workflows § Doors remain; coordination moves](../planning/pi-durable/pi-durable-workflows.md#doors-remain-coordination-moves)
  — the coordinator is the single owner of advancement for an execution, and Python doors request
  rather than advance.
- [workflows § Persisted decisions](../planning/pi-durable/pi-durable-workflows.md#persisted-decisions)
  — a semantic reply checks identity, freshness, cancellation and supersession, then consumes the
  decision and creates one continuation in the same commit. Validation, the short transaction,
  receipt lookup and recovery hide behind semantic operations.
- [workflows § Commit outcomes and recovery](../planning/pi-durable/pi-durable-workflows.md#commit-outcomes-and-recovery)
  — reconcile the stable operation identity and its retained receipt before retrying or advancing.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W1, W11
  — one advancement owner is still required, and the fixture reply protocol reproduced a single
  continuation, duplicate reuse, and receipt recovery after a lost acknowledgement.
- [further avenues § 4.2](../planning/pi-durable-further-avenues.md#42-treat-human-decisions-as-application-operations-with-no-resident-waiter)
  — a reply can validate the current subject and create a conversation-owned continuation in one
  commit, with no resident waiter.
- `packages/durable/docs/spec.md#1. Terms and invariants` invariant 1 — one Session commit is
  atomic across all record and document writes.
- `packages/durable/docs/spec.md#4. Transactions and storage ownership` — a commit callback owns
  the mutation line, and `Tx` reads documents and creates conversations and tasks inside it.
- `packages/durable/README.md#Concepts` — all changes go through one line of atomic commits, and
  one commit can append entries, edit documents and create tasks together.
- `pi-durable.md#Durable application state` — documents change in the same atomic commits as the
  transcript.

### P2. Reconcile never performs I/O; observation precedes the commit

**Reconcile never performs I/O; observation precedes the commit.** Authority reads happen
outside commits: a git ref now, a backend or GitHub state later. An operation that depends on
the authority's current state observes it first and passes the observation as an input to its
reconcile commit. In this objective, `start`, `run`, and `reply` resolve the tracked ref this
way.

- Authorization holds as of that freshly recorded observation. Later changes are caught by the
  next observation.
- If the observation fails, the operation is refused with a typed `observation_failed` and
  nothing is recorded.
- `status` never observes and only reports how old the latest observation is.

**Rationale.** Durable forbids awaiting external work inside a commit callback, and reads inside a
commit must go through `tx`. Authority facts must therefore be read before the commit and enter it
as data. Because the observation is an input record, authorization is checked against a retained
fact that can be inspected later. A change after the observation is caught by the next
observation, never by polling inside a commit. The same rule keeps reconcile pure (§7). Verifying a
snapshot also reads files, so it too runs outside the commit, immediately before it (§5).

**Evidence.**

- [workflows § Each fact keeps one owner](../planning/pi-durable/pi-durable-workflows.md#each-fact-keeps-one-owner)
  — Durable does not observe backend edits, so revalidation must precede advancement. Backend
  mutations stay outside the atomic commit.
- [further avenues § 4.4](../planning/pi-durable-further-avenues.md#44-make-observation-explicit-about-what-has-actually-been-retained)
  — retained commits are kept apart from live views, and only a retained receipt authorizes
  continuation.
- `packages/durable/docs/spec.md#1. Terms and invariants` invariant 4 — external effects do not
  run inside the Session mutation transaction.
- `packages/durable/docs/spec.md#12. API footguns` "Long transactions" — never await models, tools,
  processes, network calls or humans inside a commit callback.
- `packages/durable/docs/spec.md#12. API footguns` "Reads inside a commit" — Session reads inside a
  commit callback can hang, so read through `tx`.
- `packages/durable/docs/spec.md#5.2 Effect sandwich` — Durable's own split: an intent commit, then
  the external effect, then an outcome commit.

### P3. Content-addressed, immutably materialized subjects

**Subjects are content-addressed and materialized immutably; staleness is derived.** Every
assignment, outcome, and decision binds to a *subject*: a canonical digest of exactly what is
judged.

- For the fixture review, the subject is the git tree of the commit at the tracked ref.
  Uncommitted edits are not part of it.
- Before admission, the host materializes the subject into the store as read-only files with a
  sha256 manifest. Workers read only that snapshot, never a live checkout.
- The snapshot is verified before each attempt and before acceptance. The accepted report
  records the digest it verified.
- An outcome authorizes only its exact subject. Changed work is a new subject and needs a new
  assignment. No "stale" flag is ever stored.

**Rationale.** A subject's identity is its content. Each execution kind declares a subject kind,
and the fixture's is `git-tree`: the tree oid at the tracked ref. A changed tree is a new subject.
A commit with the same tree is a **new observation of the same subject**, not a new subject: an
empty commit, a metadata-only amend, or some merges produce one. Such a commit invalidates nothing:
assignment and decision keys are reused, and subject-bound outcomes stay valid. A kind that needs
commit identity declares a `git-commit` subject through the four-question recipe (§13). Workers
read an immutable snapshot rather than a live checkout for two reasons. Durable rebuilds a
recovered tool's environment from the conversation's *current* working directory. And it cannot
force-terminate code that ignores cancellation, so a rerun or a straggler must never see different
bytes.

**Evidence.**

- [workflows § Execution identity and retained evidence](../planning/pi-durable/pi-durable-workflows.md#execution-identity-and-retained-evidence)
  — a change to the plan revision, the relevant base or head, the workspace state, or the evidence
  bundle requires revalidation or a new assignment. Retained artifacts need provenance and digest
  checks.
- [further avenues § 1](../planning/pi-durable-further-avenues.md#1-executive-reassessment)
  item 7 — recovering an existing assignment and starting a new review are different operations.
- [further avenues § 4.1](../planning/pi-durable-further-avenues.md#41-make-retained-evidence-the-first-useful-application)
  — recovery keeps the original subject, while a new review mints fresh identity.
- `packages/durable/docs/spec.md#12. API footguns` "Environment on recovery" — a tool rerun after
  recovery builds its environment again with the conversation's current `cwd`.
- `packages/durable/docs/spec.md#13. Non-goals` — Durable cannot force-terminate non-cooperative
  extension code inside one process. The snapshot is what keeps a stray reader harmless.
- `git rev-parse 3e9977d6^{tree} 2768e837^{tree}` in this checkout prints `7ad7a27f…` twice: two
  commits with one tree, the counterexample to commit identity.

### P4. Perk mints identity, deterministically

**Perk mints identity, deterministically.** The hierarchy is execution → assignment (kind +
role + subject + capability set) → attempt (ordinal). The role tells apart assignments of the
same kind over the same subject, such as the two fixture reviewers. Operation identities derive
deterministically from these; they are the record keys and the Durable `requestId`s. A retry
after an uncertain commit therefore converges on the same receipt. Durable task, conversation,
and submission IDs are *mapped to* Perk identities in the commit that creates them, never used
*as* them.

**Rationale.** Durable ids are sequence numbers minted by storage. After an uncertain commit they
cannot be recomputed from Perk inputs, so they cannot be identity. A deterministic op id lets a
retry find its own receipt: the retry derives the same id and looks it up. Durable's `requestId`
deduplication compares only the submission type, so Perk itself must decide whether a repeated
operation means the same thing. That is the replay rule's payload comparison (§4). An
observation's op id is the next store-local observation ordinal, assigned inside the commit that
records it (§5), so every observation is a new fact (P5). It is the verb's own op id that
converges on a retry.

**Evidence.**

- [workflows § Execution identity and retained evidence](../planning/pi-durable/pi-durable-workflows.md#execution-identity-and-retained-evidence)
  — execution → assignment → attempt, with runtime ids mapped to these identities, never replacing
  them.
- [workflows § Admission and conversation identity](../planning/pi-durable/pi-durable-workflows.md#admission-and-conversation-identity)
  — persist the assignment→conversation mapping in the creation transaction. Request
  deduplication checks the type, not an equivalent payload, so Perk must enforce meaning before
  submission.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W5 —
  request deduplication validates neither subject nor authorization. Retain the mapping and the
  stable operation identity.
- `packages/durable/docs/spec.md#6. Submissions and inbox` — "`requestId` deduplicates within one
  conversation before any write".
- `packages/durable/README.md#Errors` rule 1 — after a reopen, resubmitting with the same
  `requestId` finds the submission that was already admitted.
- `packages/durable/src/harness/submissions.ts::admitSubmission` — `tx.submissionByRequest` returns
  the existing submission when only the type matches.
- `packages/durable/src/storage/memory.ts::MemoryStorage.mintId` and
  `packages/durable/src/storage/sqlite/storage.ts::SqliteStorage.mintId` — ids are sequence numbers
  minted by storage. `packages/durable/src/ids.ts::idFromNumber` only brands them, so nothing
  derives them from Perk inputs.
- `pi-durable.md#Survives crashes` — a `requestId` makes a submission exactly-once.

### P5. Three tiers, one writer each

**Three tiers, one writer each.** Authorities (the issue backend, Git, GitHub) own canonical
facts. v2 retains two kinds of state as session-scoped Durable documents with an explicit
`checkpointWhen`:

- *observations* of authority facts;
- *its own records*: assignments, attempts, accepted outcomes, decisions, replies,
  cancellation, and the execution manifest.

Everything else, including status and views, is derived. Accepted outcomes are immutable and
accepted at most once per key; corrections are appended. Task checkpoints, memos, and
task-scoped documents are disposable runtime state. None of them is ever the only copy of a
record.

**Rationale.** Each fact has exactly one writer, so no copy can drift from another. v2 keeps what
it must survive in session-scoped documents, which outlive tasks and worker conversations.
Anything Durable discards when a task ends is disposable: task checkpoints, memos and task-scoped
documents. The principle's three tiers map onto §6's five rows. The authority tier is row 1. The
retained-v2-state tier is rows 2 and 3, observations and records. The derived tier is rows 4 and
5, disposable runtime state and derived views. Every family declares `checkpointWhen` explicitly,
and watches are never an audit source.

**Evidence.**

- [workflows § Each fact keeps one owner](../planning/pi-durable/pi-durable-workflows.md#each-fact-keeps-one-owner)
  — the authority table: backends, Git and GitHub own their facts, and Perk application state owns
  assignments, attempts, accepted reports, decisions and cancellation.
- [workflows § Store and record policy](../planning/pi-durable/pi-durable-workflows.md#store-and-record-policy)
  — the record-lifetime table. Application records are session-scoped documents and accepted
  outcomes are immutable. Checkpoints, memos and progress are disposable, never the sole copy.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W2, W4,
  W14:
  - accepted evidence is retained and corrections are appended;
  - `checkpointWhen` is required at definition time, and `() => false` is only an experimental
    choice;
  - watches coalesce, so retained evidence is built from persisted facts.
- `packages/durable/docs/spec.md#3.2 Records and lifetimes` — document records are scoped to the
  session, a conversation, or a task, and families are identified by their `key`.
- `packages/durable/docs/spec.md#5.2 Effect sandwich` — memos disappear in the terminal
  replacement.
- `packages/durable/docs/spec.md#5.3 Terminal tasks` — the terminal record is the result receipt.
  The checkpoint and memos disappear, and task-scoped documents retire.
- `packages/durable/docs/spec.md#12. API footguns` "Checkpoint starvation", "Buffered watches",
  "Large terminal results" — the three footguns: unbounded replay growth, coalesced watch frames,
  and keeping large results out of task outcomes.
- `packages/durable/src/documents.ts::defineDoc` / `::defineDocFamily` — a document can be
  session-scoped, and `checkpointWhen` is part of its definition.
- `pi-durable.md#Hooks` — a memo is a small value stored with the task, where the first write
  wins.

### P6. Acceptance is semantic

**Acceptance is semantic, never runtime status.** A run that is `done`, a task that is
`completed`, or final prose never establishes an outcome. A typed report is accepted only after
validation against its assignment: schema, subject digest as verified against the snapshot,
capability set, and attempt. It is accepted once, in its reconcile commit. Aggregate
completeness is a reconciler rule. Missing or invalid reports stay visible as incomplete
coverage and never imply a clean result.

**Rationale.** Runtime status reports what the runtime did, not what the domain accepted. A run can
end `done` after a tool error or a token limit, and final prose is not a typed report. The report
tool's structured output is the result, and `control.terminate` ends the run without asking for a
recap. Acceptance is therefore a reconcile commit over a validated report. Completeness is a rule
over accepted records, and an incomplete set stays visible as incomplete.

**Evidence.**

- [workflows § Accepting work and continuing](../planning/pi-durable/pi-durable-workflows.md#accepting-work-and-continuing)
  — neither a `done` run, an error result, nor final prose establishes an outcome. Independent
  reports join with `allSettled`, and incomplete coverage must be exposed.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W10 —
  typed reports, completeness, subject identity and tool-controlled termination are validated
  independently of any model recap.
- `packages/durable/README.md#Tools` — `structuredOutputSchema` output is validated, and
  `control: { terminate: true }` ends the run without another model request only when every result
  of the round asks for it.
- `packages/durable/docs/spec.md#5.3 Terminal tasks` — the terminal task record is a runtime
  receipt, not a domain acceptance.

### P7. Capabilities bind to the assignment and are enforced at the operation

**Capabilities bind to the assignment and are enforced at the operation.** At admission an
assignment records its resolved capability set: tools, extensions, instructions, read/write
posture, workspace root.

- Worker conversations are configured explicitly from it. Fresh context means an explicit
  `configure`, never an inherited agent.
- Enforcement lives in the Perk execution environment and in Perk tools, on **every attempt,
  including replay**. This matters because Durable's recovered safe tools skip `beforeTool`.
- Enforcement fails closed when code or a capability is missing.
- A capability that cannot be enforced at the operation does not exist. In this objective no
  worker can spawn a subprocess. A future subprocess capability requires the containment
  mechanism that node 1.4 binds.

**Rationale.** Hooks do not form a complete boundary. A recovered `replay: "safe"` tool reaches
`execute` without running `beforeTool` again. Selections can also silently omit a guard
extension, or copy an owner's agent. Enforcement must therefore live where the effect happens: the
`ExecutionEnv` every built-in and Perk tool goes through. The capability set itself is recorded
at admission, so a replay meets the same limits as the first attempt. The pinned
`NodeExecutionEnv` tracks spawned children only in memory. That is why no subprocess capability
exists until node 1.4 binds a containment mechanism.

**Evidence.**

- [workflows § Resuming safely](../planning/pi-durable/pi-durable-workflows.md#resuming-safely)
  — a recovered safe tool skips argument validation and `beforeTool`, and its environment is
  rebuilt. Restrictions are enforced at the operation boundary on every attempt, and missing
  extension code fails closed.
- [workflows § Admission and conversation identity](../planning/pi-durable/pi-durable-workflows.md#admission-and-conversation-identity)
  — fresh context needs an explicit capability selection, because a child can copy its parent's
  agent configuration.
- [further avenues § 4.5](../planning/pi-durable-further-avenues.md#45-bind-capabilities-at-execution-including-replay)
  — required policy must hold in the actual tool or environment operation on every attempt.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W7 —
  recovered safe tools still bypass `beforeTool`, and nested calls add paths to enforce.
- `packages/durable/src/harness/tool.ts` — `execute` is reached only by recovery. It reruns the
  tool when the stored and the current replay policy are both `safe`, without `beforeTool`.
- `packages/durable/docs/spec.md#12. API footguns` "Guards left out of a selection", "Selection
  edits and copies", "Copies are one-time", "Environment on recovery" — the four ways a
  selection-level guard fails to reach a worker.
- `packages/durable/src/env/index.ts::ExecutionEnv` — `ExecutionEnv extends FileSystem, Shell` is
  the enforcement seam:
  - the write methods (`writeFile`, `appendFile`, `truncateFile`, `renameFile`, `createDir`,
    `remove`, `createTempDir`, `createTempFile`) and `Shell.exec` are refused;
  - `canonicalPath` resolves symlinks for containment.
- `packages/durable/src/tools/read.ts::createReadTool` — the built-in `read` reads through
  `requireEnv(api)` and `env.openBinaryReader`, so it reads only through the call's environment.
- `packages/durable/src/env/node.ts::NodeExecutionEnv.activeChildPids` — child PIDs are tracked in
  a private in-memory `Set<number>`, so owner death loses them.
- `pi-durable.md#Malleable` — conversations store extension and tool names, never code.

### P8. Ownership before open; compatibility before resume; residence is policy

**Ownership before open; compatibility before resume; residence is policy.**

- The host takes an exclusive **store owner lock** before it opens storage. The lock carries a
  monotonically increasing *owner epoch*. It is distinct from the existing submit-conflict
  *execution lock*.
- The host then opens the Harness. Before `resume()`, it verifies the execution manifest. For
  this objective the manifest must match exactly: v2 record and task definition versions, policy
  version, Durable version, and workspace identity.
- Incompatible resume is refused with an actionable outcome; migrations are later work.
- Once subprocess capabilities exist, the same pre-resume gate fences effects left by earlier
  epochs, as node 1.4's verdict specifies.
- A host run is *open → gate → run until quiescent → close*. Quiescent means no work is runnable
  and a domain *wait reason* has been recorded. The same code serves a one-shot door, a daemon,
  or a future wakeable host.

**Rationale.** Durable provides no cross-process locking, and `Harness.open` may write, through
storage initialization and recovery bookkeeping. Ownership must therefore come first, and the lock
protocol itself must preserve exclusivity (§10). The compatibility gate must come before
`resume()`, because submitting and waiting also start the scheduler. `wake().active === false`
does not mean completion: it can mean a sleep, parked work, or no eligible work. So the host
derives a domain wait reason. In the statement above, "recorded" means derivable from retained
records plus `inspect()`. The wait reason itself is never a stored flag (§10 step 8). Residence is
policy because the same open → gate → run → close code runs whether the host lives for one call or
for days.

**Evidence.**

- [workflows § Resuming safely](../planning/pi-durable/pi-durable-workflows.md#resuming-safely)
  — acquire ownership before `Harness.open`, because storage initialization and recovery may write.
  Validate against task and tool code, policy and workspace before enabling the scheduler, and
  refuse an incompatible resume. Store ownership does not fence surviving processes.
- [workflows § Attaching, stopping, and moving machines](../planning/pi-durable/pi-durable-workflows.md#attaching-stopping-and-moving-machines)
  — graceful close stops scheduling without cancelling, and one owning process holds a store.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W8, W9,
  W13:
  - an ordinary open recovers work;
  - a real `SIGKILL` left a child running;
  - close is not cancellation, and background work must be scoped explicitly.
- [further avenues § 4.3](../planning/pi-durable-further-avenues.md#43-revisit-hosting-as-three-separate-responsibilities)
  — running, placement and presentation are separate responsibilities. A wakeable host is a later
  residence.
- [further avenues § 4.6](../planning/pi-durable-further-avenues.md#46-use-diagnostics-to-explain-waiting-not-only-running)
  — `wake().active === false` is not workflow completion, so retain the domain reason for a wait.
- [further avenues § 4.8](../planning/pi-durable-further-avenues.md#48-treat-compatibility-and-rollback-as-data-operations)
  — an application-owned execution manifest decides whether a resume is compatible.
- `packages/durable/README.md#Storage` — "One process owns a storage at a time; there is no
  cross-process locking".
- `packages/durable/README.md#Persist and Resume` — "`resume()` starts the task scheduler;
  submitting or waiting starts it too".
- `packages/durable/docs/spec.md#2.2 Public Harness surface` — `inspect()`, task, submission and
  document reads never enable scheduling.
- `packages/durable/docs/spec.md#5.6 Sleeping, timers, and wakeups` "Wakeups" — `wake().active`
  says whether some task can run now or is running.
- `packages/durable/docs/spec.md#5.4 Scheduler, abort, and ownership` — a task cut off
  `restartLimit` times parks as `restart_limit`. The blocked reason is derived runtime state, and a
  blocked task is not active in `wake()`.
- `packages/durable/src/harness/types.ts::Wake` (`{active, at?}`) and
  `packages/durable/src/harness/scheduler.ts::BlockedReason`
  (`"missing_task" | "task_too_old" | "migration_failed" | "restart_limit"`).
- `packages/durable/docs/spec.md#12. API footguns` "Schema stability" — document kinds are
  persisted protocol. Changing a kind needs an explicit copy, which is why execution
  manifests carry definition versions.
- `pi-durable.md#Long runs anywhere` — one process owns a storage, and other clients attach to it.

### P9. Storage failure means uncertainty; application failure means refusal

**Storage failure means uncertainty; application failure means refusal.** Durable 1.4.0 handles
the two differently, and so does v2:

- A storage commit failure ends the Harness (`StorageRejected` no longer exists). The caller
  sees `uncertain`. Recovery reopens under Principle 8 and reconciles by operation identity.
- A throw inside a commit callback rolls back only that commit and leaves the Harness open.
  Kernel validation, stale-subject, and refusal checks throw this way. The caller sees a
  definite, typed refusal, and nothing was recorded.

Callers never compose raw transactions or retry rules. The binding hides them behind semantic
operations.

**Rationale.** Once Durable admits a batch, a storage error leaves its outcome unknown, so the only
honest answer is `uncertain`, followed by a reopen and a receipt lookup. An exception thrown by
Perk's own code inside the callback is different. Durable rolls that commit back and keeps
running, so the refusal is definite and nothing was recorded. One refusal is detected just before
the commit rather than inside it: snapshot verification is I/O (P2), so `snapshot_tampered` is
reported before the guarded commit runs. It is equally definite, and it also records nothing (§9).
The corpus's earlier protocol was
written against `StorageRejected`. That class is gone, but the protocol's intent survives:
reconcile by identity before retrying.

**Evidence.**

- [workflows § Commit outcomes and recovery](../planning/pi-durable/pi-durable-workflows.md#commit-outcomes-and-recovery)
  — written against `StorageRejected`, which is now superseded. Its rule to reconcile the
  operation identity and receipt before retrying survives.
- [further avenues § 1](../planning/pi-durable-further-avenues.md#1-executive-reassessment) item 2
  and [§ 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) W12 — rewrite the
  storage-failure protocol: `StorageRejected` no longer exists, and the read-only
  `StorageRequestError` exemption is not a safe-to-retry write category.
- `packages/durable/README.md#Errors` rules 1–3:
  - a storage error ends the Harness, and reopening recovers;
  - an invalid read fails only that call, but any `commit()`/`mintId()` error ends the Harness;
  - a throwing commit callback rolls back that commit.
- `packages/durable/docs/spec.md#10.1 Failures` — "An error from `commit()` or `mintId()` is never
  exempt: once a batch is admitted, whether it committed is unknown". "A commit callback … that
  throws rolls its commit back and rejects it".
- `packages/durable/src/errors.ts::SessionFailed`, `::StorageRequestError` — no `StorageRejected`
  exists anywhere under `src/`.
- `packages/durable/src/session/session.ts::GuardedStorage` — every Session storage call goes
  through the failure guard. A throwing `commit()` fails the Session, and later calls get
  `SessionFailed`.
- `packages/durable/test/harness-storage-failure.test.ts::"ends everything with the first error…"`
  and
  `packages/durable/test/session-documents.test.ts::"aborts every change when the callback fails"`
  — the two behaviors node 1.3 re-proves.
- `packages/durable/test/harness-lifecycle.test.ts` — open, close, and close after failure.

### P10. Doors remain; layers are enforced; deferred obligations keep their shape

**Doors remain; layers are enforced; deferred obligations keep their shape.**

- Python doors invoke the host through a versioned JSON envelope with typed outcomes:
  `owner_busy`, `incompatible`, `observation_failed`, `refused`, `pending_decision`,
  `uncertain`. Python never touches the store.
- Inside `extension/pi/v2/`, the domain kernel imports nothing from Durable. Durable vocabulary
  stays in the binding layer and the host entry. Inside v2, `kernel/` imports only `kernel/`, and
  `durable/` imports only `kernel/` and `durable/`; the host entry composes both (node 1.2's
  `layeringGuard.test.ts`).
- v1 and v2 never import each other. v2 can reach v1 only through an exact-file allowlist of
  verified host-independent modules. The production allowlist starts empty, and each addition
  is reviewed. The only dev-only entry is `extension/testing/importGraph.ts`, reused by v2's
  guards.
- External effects follow *intent → effect → reconciled observation*, outside commits. Each
  route gets its own reconciler (incremental submit vs the stacked journal).
- Budgets are admission reservations owned by Perk, never telemetry. A budget design must
  define its units, how reservations are made and released across children, retries, and
  compaction, and what happens when spend is unknown.
- The first objective that needs effects or budgets builds them.

**Rationale.** The session boundary between the Python exterior and the TypeScript interior stays.
v2 revises only *who advances* an execution, and that revision is recorded in the contract by the
node that builds the door. Layering keeps the kernel testable without Durable and keeps v1 safe
from v2's dependencies, and import guards enforce it rather than convention. Effects and budgets
are not built here. Their shape is fixed now so the objective that needs them cannot quietly
weaken it.

**Evidence.**

- [v2 § Source layout and ownership](../planning/pi-durable/pi-durable-v2.md#source-layout-and-ownership)
  — neither integration imports the other, and Durable objects stay outside shared feature
  interfaces. Use named module interfaces, never one universal host interface.
- [v2 § Package and verification isolation](../planning/pi-durable/pi-durable-v2.md#package-and-verification-isolation)
  — v2 gets its own dependencies, typecheck and test target, and is excluded from the published
  files and the v1 source guards. Each guard keeps an equivalent check.
- [workflows § Doors remain; coordination moves](../planning/pi-durable/pi-durable-workflows.md#doors-remain-coordination-moves)
  — Python doors stay and coordination moves to the coordinator, which requires a cross-plane
  contract revision.
- [workflows § Each fact keeps one owner](../planning/pi-durable/pi-durable-workflows.md#each-fact-keeps-one-owner)
  — record intent before a remote mutation, and prove each publication route's recovery
  separately.
- [workflows § Budget admission and usage](../planning/pi-durable/pi-durable-workflows.md#budget-admission-and-usage)
  — recorded usage, reserved work and uncertain spend are different facts. A budget needs units,
  reservations across children, retries and compaction, and an unknown-spend rule.
- [further avenues § 3](../planning/pi-durable-further-avenues.md#3-existing-plan-audit) V1, V2,
  W10 — the workspace location and dependency isolation need explicit proof, and usage telemetry
  is never an admission budget.
- [further avenues § 5](../planning/pi-durable-further-avenues.md#5-recommended-planning-agenda)
  — the delivery order: one retained report/decision operation first, with publication, objectives
  and learning later.
- `packages/durable/docs/spec.md#5.2 Effect sandwich` — intent, effect, outcome.
- `packages/durable/src/harness/usage.ts::UsageDoc` — the `pi.usage` totals, the only budget fact v2
  records.
- [extension/testing/importGraph.ts](../../extension/testing/importGraph.ts) — the dev-only
  import-graph substrate that v2's guards reuse.
- [first-principles/cli-vs-pi.md](./first-principles/cli-vs-pi.md) — boundary = the session, and
  authority follows the actor.

## 4. The identity model

| Identity | Minted by | Composition |
|---|---|---|
| **execution** | the door, via [`src/perk/state/run_id.py::mint`](../../src/perk/state/run_id.py) (a ULID) | the only random identity; one execution owns one store |
| **assignment** | derived | `kind` + `role` + subject digest + capability-set digest |
| **attempt** | derived | the assignment id + a 1-based ordinal |
| **decision** | derived | the execution id + subject digest + decision kind |
| **operation** | derived | the scope id it belongs to + `op-kind` (+ `op-key`) — one per semantic operation |

The pinned grammar:

```
execution     v2/<execution-id>
assignment    v2/<execution-id>/<kind>/<role>/<subject-digest>/<capset-digest>
attempt       <assignment-id>/<ordinal>
operation     <scope-id>/<op-kind>[/<op-key>]      scope-id ∈ {execution, assignment, attempt, decision}
decision      v2/<execution-id>/decision/<subject-digest>/<decision-kind>
```

**Fixture operation kinds.** The set is closed for this objective and extended only by amendment:

| `op-kind` | Scope | `op-key` | Duplicate-compared payload |
|---|---|---|---|
| `observe` | execution | `<seq>`: the next observation ordinal, assigned in the recording commit | the observation record (always a fresh key, never a duplicate) |
| `admit` | assignment | — | `{capabilitySet}` |
| `submit` | attempt | — | `{conversationId}`. This op id is the Durable `requestId`. |
| `accept-report` | attempt | — | the report + the verified digest |
| `aggregate` | execution | `<subject-digest>` | the accepted-outcome ids |
| `open-decision` | decision | — | `{allowedActions, actor}` |
| `reply` | decision | — | `{decisionId, action, actor}` (one reply per decision) |
| `continuation` | decision | — | the Durable task id mapped under it |
| `cancel` | execution | — | `{reason}` |

**Replay rule.** If an operation's key already exists with an equal payload, the operation returns
the existing receipt. This lookup runs *before* any freshness, cancellation or supersession check.
For example, a committed reply returns its continuation id even if the tracked ref moved or the
execution was cancelled afterwards. The same key with a different payload is refused
`duplicate_conflict`. The fresh observation a verb takes is a separate input record and is never
part of the compared payload.

**Rules.**

- `<kind>`, `<role>`, `<decision-kind>` and `<op-kind>` match `[a-z][a-z0-9-]*`, and digests are
  lowercase hex.
- The segment after `v2/<execution-id>/` tells an assignment apart from execution-scope ids. So
  `decision` and every execution-scope `op-kind` (`observe`, `aggregate`, `cancel`) are reserved
  and never name an assignment `<kind>`.
- An attempt's `<ordinal>` is all digits and an `op-kind` starts with a letter, so the two never
  collide under an assignment id.
- The capability-set digest is the sha256 of the canonical JSON (RFC 8785 key order, no
  whitespace) of the resolved capability set
  `{model, extensions[], tools[], instructionsDigest, posture: "read-only", workspaceRoot: "subject-snapshot"}`.
  The workspace root is symbolic, never an absolute path, so the digest is the same in every store.

**Durable ids are mapped, never adopted.** A Durable task, conversation or submission id is mapped
to its Perk id in the commit that creates it. The mapping lives in the `perk.v2.durable-map`
family, keyed by the Perk id the Durable object was created for (§6). A Durable id is never used
as a Perk identity, because storage `mintId` allocates sequence numbers. A retry after an
uncertain commit re-derives the same operation id and finds its receipt.

## 5. The subject rule

**Subject kinds are declared per execution kind.** The fixture's subject is
`{kind: "git-tree", digest: <tree-oid>}`: the tree of the commit at the tracked ref. Uncommitted
edits are never part of it.

**A changed tree is a new subject; a commit with the same tree is a new observation of the same
subject.** Assignment and decision keys are reused, and subject-bound outcomes stay valid. So "the
ref advanced" alone never invalidates an approval, but "the tree changed" does. No "stale" flag is
ever stored. Staleness is derived by comparing a record's subject digest with the digest of the
latest observation. An observation record is
`{seq, repo, ref, commit, tree, manifestDigest, observedAt}`.

**Observation order.** Observations are ordered by `seq`, never by wall-clock time:

- `seq` is one more than the highest `seq` among the observation records in the transaction
  (1 for the first). The recording commit assigns it from in-transaction records, and the op id
  is `v2/<execution-id>/observe/<seq>`.
- The owner lock admits one host at a time, and one host commits on one mutation line, so two
  observations never receive the same `seq`. A refused commit rolls its observation back, so the
  sequence has no gaps.
- `seq` derives from retained records, so it continues unchanged across reopen and owner epochs.
- The **latest observation** is the one with the highest `seq`. Stale-subject checks (§12) and
  every other freshness rule read only this.
- `observedAt` is wall-clock time (epoch milliseconds). It is display data, used only for the age
  `status` reports. Nothing orders, keys or authorizes by it, so equal timestamps or a clock
  rollback cannot collide two observations or select an older one.

**Snapshot manifest.** The snapshot manifest is derived from the git tree, never from walking the
snapshot. It has one line per `git ls-tree -r` entry:

```
<kind> <sha256|-> <git-mode> <oid> <path>
```

- `<kind>` is `blob`, `link` or `gitlink`.
- `<sha256>` is the sha256 of the blob's content, or of the link-target text for a link. A gitlink
  carries `-` instead.
- `<git-mode>` is the git mode: `100644`/`100755`, `120000`, or `160000`.
- `<oid>` is the git object id, which for a gitlink is its commit oid.
- `<path>` is the POSIX relative path.

Lines are sorted bytewise by path, LF-terminated, and UTF-8. A tree with an entry path that
contains LF or is not valid UTF-8 cannot be represented, and observation refuses it with
`observation_failed`. `manifestDigest` is the sha256 of the manifest bytes. The snapshot manifest is
stored at `<store>/subjects/<tree-oid>.manifest`.

**Snapshot.** The snapshot `<store>/subjects/<tree-oid>/` is written to a temp dir and then
renamed, so it is idempotent per tree. Content rules:

- a blob (`100644`/`100755`) becomes a regular file with mode `0444`;
- a symlink entry (`120000`) becomes a regular file with mode `0444` that holds the link-target
  text;
- a gitlink (`160000`) becomes an empty directory with mode `0555`;
- directories get mode `0555`.

The filesystem does not carry modes or gitlink oids; the snapshot manifest does. Snapshots and
snapshot manifests are a content-addressed cache, not v2 records. One left behind by a failed or
refused operation records nothing, and the next observation of that tree reuses it after
verification.

**Verifier.** The verifier runs three checks, and any extra, missing or altered path fails it:

1. It recomputes the sha256 of the stored manifest file and compares it with the `manifestDigest`
   recorded in the observation the operation relies on.
2. It walks the snapshot and compares paths with the manifest. The regular files plus the gitlink
   directories must be exactly the manifest's paths, and every other directory must be an ancestor
   of one of those paths.
3. For every `blob`/`link` line it compares the file's content sha256 with the line's value. For
   every `gitlink` line it requires an empty directory.

The verifier never re-derives modes or gitlink oids from disk. The manifest digest authenticates
them.

**Verification points.** Verification reads files, so it always runs outside the commit,
immediately before it (P2). It runs at three points:

- after materialization (node 2.4), where a failure is an observation failure
  (`observation_failed`);
- at every attempt start (node 3.1);
- inside the accept-report tool, before the accept-once commit (node 3.1).

At the last two points a failure is the refusal `snapshot_tampered` (§9). The accepted outcome
records the digest it verified. An outcome authorizes only its exact subject. Node 2.4's proof
list includes a symlink entry and a gitlink entry.

## 6. Record tiers

| Tier | Examples | Sole writer | Lifetime | Who reads |
|---|---|---|---|---|
| **Authority facts** | issue backend, git refs + trees, GitHub | their owners. v2 writes none in this objective. | the authority's | observation, outside commits |
| **Observations** | the `perk.v2.observation` family, keyed by op id | the reconcile commit that takes the observation as an input | session-scoped, immutable: one record per observation | reconcile, the status view |
| **v2 records** | the `perk.v2.manifest` singleton and the families `perk.v2.assignment`, `perk.v2.attempt`, `perk.v2.outcome`, `perk.v2.decision`, `perk.v2.reply`, `perk.v2.cancellation`, `perk.v2.durable-map` | reconcile commits only | session-scoped, `checkpointWhen: () => true` on every family, immutable once written, corrections appended | reconcile, the gate, receipt lookup, the status view |
| **Disposable runtime state** | Durable task checkpoints, memos, task-scoped documents, `pi.*` documents, transcripts, inbox, `pi.usage`, SQLite schema | Durable | until the task ends, or Durable's own policy | Durable, plus diagnostics via `inspect()` |
| **Derived views** | status snapshot, wait reason, door payloads, `inspect()` | nobody: computed on read | never stored | the door, the status view |

**Record keys.** v2 documents come in three key shapes, and each family has exactly one:

| Family | Shape | Key | Written by | Holds |
|---|---|---|---|---|
| `perk.v2.manifest` | singleton | none | `start`'s commit, once | the execution manifest (§10) |
| `perk.v2.observation` | operation record | the `observe` op id | the observing verb's commit | the observation record (§5) |
| `perk.v2.assignment` | operation record | the `admit` op id | admission | the §4 payload |
| `perk.v2.attempt` | operation record | the `submit` op id | submission | the §4 payload |
| `perk.v2.outcome` | operation record | the `accept-report` or `aggregate` op id | acceptance, aggregation | the §4 payload |
| `perk.v2.decision` | operation record | the `open-decision` op id | opening a decision | the §4 payload |
| `perk.v2.reply` | operation record | the `reply` op id | the reply | the §4 payload |
| `perk.v2.cancellation` | operation record | the `cancel` op id | cancellation | the §4 payload |
| `perk.v2.durable-map` | identity mapping | the Perk id the Durable object was created for | the commit that creates the Durable object | `{durableKind: task \| conversation \| submission, durableId}` |

- **Operation records.** An operation record is keyed by its op id and holds the operation's
  duplicate-compared payload (§4). The op id's `op-kind` names its family, so receipt lookup by op
  id addresses exactly one family.
- **Identity mappings.** A `perk.v2.durable-map` row is keyed by the Perk id the Durable object was
  created for. The fixture's rows are:
  - the worker conversation, under its attempt id;
  - the Durable submission, under the `submit` op id;
  - the continuation task, under the `continuation` op id.

  The `continuation` op kind has no family of its own: its record is its durable-map row. The step
  task is input-less and idempotent and is created for no Perk identity, so it has no row.
- **The singleton.** `perk.v2.manifest` has no key and no op id, and `start` is not an operation
  kind. A repeated `start` is caught by the gate (`already_started`, §10), never by receipt
  lookup.

**Receipt lookup.** For op id *X*, read the family that *X*'s `op-kind` names (durable-map for
`continuation`). The receipt is that record plus the durable-map rows for the result ids *X*
derives:

- `submit`: the submission row under *X*;
- `reply`: the continuation row under `<decision-id>/continuation`. That continuation task id is
  the reply's receipt.

**Binding constraint (node 2.2).** Durable's `Tx` cannot enumerate a document family, and
`tx.doc()` is get-or-create (`packages/durable/docs/spec.md#3.3 Access and creation`). A family
acquisition seeded with the input therefore performs §7 step 2's "look up or record" in a single
call. How the binding presents every record to the kernel without a family scan, the highest
observation `seq` included, is node 2.2's to pin, as an amendment to this section.

Every v2 task name and document kind starts with `perk.v2.`, because Durable reserves `pi.`
(`packages/durable/docs/spec.md#12. API footguns` "Reserved `pi.` names"). A record family
checkpoints on every write. Each record is written once and is small, so reconstruction is
trivial and replay cannot grow without bound ("Checkpoint starvation").

Disposable runtime state is never the only copy of a record and never counts as "recorded".
**Watches are not an audit source**: slow watches coalesce committed frames
(`packages/durable/docs/spec.md#12. API footguns` "Buffered watches"), so every fact a reader must
audit is a record.

## 7. The write contract

`operate(input?)` is one commit with four steps:

1. **Table reads.** Any table reads the binding needs, such as an existing conversation for an
   assignment, happen first. A table read after the first table write throws `ReadAfterWrite`
   (`packages/durable/docs/spec.md#4. Transactions and storage ownership`, table rules).
2. **Receipt lookup.** If the input's op id exists with an equal payload, return its receipt and
   stop: the commit records nothing, not even the observation the verb took. If the op id exists
   with a different payload, throw `duplicate_conflict`. Otherwise record the input under its op
   id. An observation has no caller-derived op id; it is recorded here under the next `seq`
   (§5).
3. **Reconcile.** Run the pure kernel `reconcile(records) → actions` over the v2 documents as they
   stand in the transaction. Documents stay readable after table writes.
4. **Apply.** Apply the actions in the same commit: write records, create tasks and conversations,
   consume decisions.

**Kernel properties**, proved as `K1`–`K6` in
[`extension/pi/v2/kernel/reconcile.test.ts`](../../extension/pi/v2/kernel/reconcile.test.ts):

- deterministic;
- idempotent: apply the actions, reconcile again, and no new actions appear;
- cancellation dominates admission;
- a stale subject is refused;
- incomplete coverage stays visible;
- recording a reply and reconciling in one commit yields exactly one continuation.

**The step task.** `perk.v2.step` is `operate()` with no input: the shape reconcile takes when
there is no new fact, as after a reopen.

**Receipts.** A receipt is the recorded operation record plus the durable-map rows for the result
ids it derives (§6), such as a reply's continuation id. It is looked up by op id, both
immediately and after a reopen. Callers never compose raw transactions or retry rules.

**Task ownership.** Continuation and step tasks are **conversation-owned on the execution
conversation and created with `background: true`**. The execution conversation is the store's
Durable root conversation, which reopen finds by its reserved id. These tasks are never owned by
the requesting task, which may already be terminal
([workflows § Persisted decisions](../planning/pi-durable/pi-durable-workflows.md#persisted-decisions)).
The run-to-quiescence driver waits on `wake().active`, so it never misses background work. No
abort cascade from a worker conversation reaches these tasks
(`packages/durable/docs/spec.md#12. API footguns` "Owned work holds its owner").

**No bootstrap exception.** `start` is `operate({manifest, observation, admissions})`. The
execution manifest, the first observation and the admissions are written in that one commit, and
no v2 write happens outside a reconcile commit.

## 8. The observation policy

**Which verbs observe.** `start`, `run` and `reply` observe the tracked ref first. Each resolves
the ref, materializes or verifies the snapshot, and passes the observation as an input record
alongside the verb's own input. `run`'s observation commit is itself a full reconcile pass.
Authorization is valid as of that observation.

**What a failure records.** An observation failure returns `observation_failed`, and **no v2
record is written**. Schema initialization by `Harness.open` is disposable runtime state, not a
record (§6). Snapshot files left under `<store>/subjects/` are cache, not records (§5).

**Status and cancel.** `status` never observes; it reports the age of the latest observation.
`cancel` does not observe either: it must succeed whatever state the subject is in. It is a
reconcile commit with the cancellation record as its input.

**Where observation runs.** Observation is I/O, so it runs outside the commit but inside the owner
lock, because it writes under `<store>/subjects/`.

**Refusals.** A kernel refusal rolls back the whole commit, the observation input included, so a
refused operation leaves no record (node 2.2's proof). A replayed operation also records nothing:
its receipt is returned before anything is written (§7 step 2).

## 9. The outcome taxonomy

| Situation | Durable mechanism | Caller sees | Recovery |
|---|---|---|---|
| Storage commit failure | the Harness closes; every later call gets `SessionFailed` | `uncertain` | reopen under §10, then let the step task and receipt lookup decide whether the input landed |
| Kernel refusal | the kernel throws inside the commit callback; that commit rolls back and the Harness stays open | `refused` with a typed reason; nothing recorded | fix the input, or accept the refusal |
| Snapshot verification failure at attempt start or acceptance | detected outside the commit, immediately before it (§5); the guarded commit never runs | `refused` (`snapshot_tampered`); nothing recorded | repair: the attempt stays incomplete |
| Observation failure | none; it happens before any commit | `observation_failed`; nothing recorded | fix the ref or repo, then re-run the verb |
| Lock busy | none; it happens before storage opens | `owner_busy` | retry after the live owner exits |
| Execution-manifest mismatch, or no execution manifest on a non-`start` verb | none; the gate refuses before any task phase runs | `incompatible`, naming the field (`manifest_missing` when absent) | a migration (deferred), or `start` on a store whose first commit never landed |
| `start` on a store that already has an execution manifest | none; the gate refuses (§10 step 4) | `refused` (`already_started`) | use `run`/`status` |

**Refusal reasons.** The vocabulary is closed for this objective and extended only by amendment:

- `invalid_input`;
- `unknown_decision`;
- `stale_subject`;
- `superseded`;
- `cancelled`;
- `duplicate_conflict`;
- `invalid_report`;
- `snapshot_tampered`;
- `already_started`.

## 10. The host lifecycle

1. Take the **store owner lock** (protocol below).
2. Fence effects left by earlier owner epochs, as *Containment and fencing verdict* below
   specifies. Stopping is by construction: the earlier owner's supervisor died with it. This step
   runs the report-only sweep and kills nothing.
3. Open storage and `Harness.open`, without resuming.
4. **Exact-match execution-manifest gate**, for every verb except `start`. The
   `perk.v2.manifest` session document is:

   ```
   {recordVersion, definitions: {<perk.v2.* name>: version}, policyVersion, durableVersion,
    chordVersion, workspace: {repoIdentity, executionId}, executionKind, createdAt}
   ```

   `repoIdentity` is the canonical git common-dir path. The gate compares every field except
   `createdAt` for equality, before any task phase runs. On the first mismatching field it
   refuses `incompatible` and names that field. An absent manifest is `incompatible`
   (`manifest_missing`). That is also how a store interrupted during `start` before its first
   commit presents: nothing was recorded, and `start` may be re-run. `start` on a store that
   already has a manifest is `refused` (`already_started`).
5. Observe, for the observing verbs (§8).
6. `operate(input)`. For `start`, this one commit writes the manifest, the observation and the
   admissions (§7).
7. `resume()`, then wait until `wake().active === false`.
8. Derive the **wait reason** from records plus `inspect()`. The vocabulary is closed:
   `pending_decision`, `unmet_prerequisite`, `assignment_incomplete`, `repair_required`,
   `parked`, `blocked`, `sleeping`, `cancelled`, `completed`.
9. `close()`, then release the lock. The epoch directory stays behind as the record of that epoch.

**Status** runs lock → open → gate → read records + `inspect()` → close → release. It never calls
`resume()` or any other call that enables progress. Submit and wait enable scheduling, while
`inspect()` and reads do not (`packages/durable/docs/spec.md#2.2 Public Harness surface`).

**Quiescence** means no runnable work **and** a derivable wait reason. The same code serves a
one-shot door, a daemon, or a wakeable host: residence is policy.

### Store owner lock protocol

Durable provides no cross-process locking, so the protocol itself must preserve exclusivity. It
uses no OS advisory locks. **The epoch is the name of the lock.**

**Layout.**

- `<store>/owner/<epoch>/` is one directory per acquisition. `<epoch>` is a decimal integer ≥ 1
  with no leading zeros.
- Each holds `meta.json` `{epoch, pid, host, startedAt (process start time), nonce}`.
- A released epoch also holds a `released` marker.
- Temp directories are named `<store>/owner/.tmp.<nonce>/`. Any name that is not a decimal epoch
  is ignored when listing.

**Acquire.**

1. List `<store>/owner/` and let *n* be the highest epoch (0 if there is none).
2. If *n* > 0, classify `owner/<n>`. A `released` marker means free. Otherwise ask the liveness
   seam: a live holder means `owner_busy`, and a dead one means free.
3. When free, write `meta.json` with `epoch = n + 1` into a fresh `owner/.tmp.<nonce>/`, then
   `rename(tmp → owner/<n+1>)`.

A directory rename onto an existing non-empty directory fails (`ENOTEMPTY`/`EEXIST`). So exactly
one contender creates each epoch, and an epoch directory never exists without complete metadata.
The protocol never leaves an empty epoch directory. A contender whose rename fails removes its temp
directory and starts again from step 1. After at most 3 rounds it returns `owner_busy`.

**Why this is race-safe.** The classifications "released" and "dead" are permanent. A marker is
never removed, and a process with a given pid and start time never comes back. So creating *n*+1
on the strength of that observation stays safe however late the rename lands. The rename fails if
any other contender created *n*+1 first. And while the holder of *n* is live and unreleased, no
contender can observe it as free.

Each epoch number therefore names exactly one acquisition, and epochs strictly increase. That is
the property fencing keys on. There is no reclaim rename: a design that renames the one lock
directory aside cannot bind that rename to the epoch it observed.

**Liveness.** The holder of an unreleased epoch is dead exactly when its `host` is this host and
either the recorded pid does not exist or that process's start time differs from `startedAt`.
Looking up the start time is a host seam (Linux `/proc/<pid>/stat`). Two cases are treated as
**live**, so the result is `owner_busy` and the epoch is never treated as free:

- a host where the seam is unsupported;
- a lock recorded by a different host.

Liveness fails closed.

**Release.** `close()` the Harness, then write `owner/<epoch>/released` as a temp file in the
epoch directory followed by a rename. A crash before release leaves an unreleased epoch whose
process is dead, and the next host classifies it as free.

**Retention.** Epoch directories are never deleted while the store exists. Deleting one could let
a contender working from an older listing re-create it. Abandoned temp directories are ignored.
Both are cleaned up by store retention/GC, which is deferred (§14).

**Node 2.3 proves:**

- a second live owner is refused;
- two concurrent acquirers after a dead owner: exactly one creates the next epoch, and the other
  sees `owner_busy`;
- epochs are unique and strictly increasing across acquisitions;
- a crash between acquisition and the first commit leaves an unreleased epoch that the next host
  treats as free, plus a `manifest_missing` store;
- a liveness seam that is unsupported, or on a different host, never treats an unreleased epoch as
  free.

### Containment and fencing verdict

**Containment and fencing verdict (node 1.4): supervised execution.** Worker commands run through a
pi-env daemon on the same machine (`RemoteExecutionEnv` over `Connection({ command: ["setsid",
localDaemon()] })` where `setsid(1)` exists, else the plain daemon), never through
`NodeExecutionEnv.exec` directly. The daemon puts every command in its own session and kills every
session it started when its stdin — the owner's pipe — closes; owner death therefore stops the group
set of every running command without the owner recording anything first, and a held, un-reaped child
cannot have its pid reused. Every spawn carries `PERK_V2_STORE` and `PERK_V2_EPOCH` as labels.
**Step 2 at open kills nothing**: it runs the report-only sweep (Linux: `/proc/*/environ` labels of
earlier epochs with their start times; elsewhere `not_observable`) and surfaces survivors in the
status snapshot. **Graceful close** (step 9, and any planned stop) runs `env.cleanup()`, awaits
every running `exec`'s settlement, and only then calls `connection.close()`: `close()` SIGTERMs the
daemon, which has no handler, so closing first leaves every running command alive (measured on both
hosts). **Residuals, recorded and measured:** `setsid` escapes; background work that outlives its
command's leader; owner-and-daemon group kills on a host without `setsid(1)`, and any terminating
signal sent to the daemon itself; the daemon's own spawn→register window (an owner dying within
microseconds of sending an `exec` frame leaked the whole tree in 2 of 400 local trials). They are
**isolated** by the obligation that every attempt's environment is rooted at its own workspace and
an earlier epoch's workspace is never reused before it is discarded. **One residual is not isolated,
and closing it is a prerequisite:** a reaped leader's pid stays registered for as long as any
process that inherited the command's output keeps writing (settlement waits for 100 ms *without*
output), so a group kill — at owner death, on a timeout or abort, or from `cleanup()` — can signal
an unrelated process that reused that pid. Before any worker gets a subprocess capability, the
implementing objective closes that window — a re-verified pi-env pin that stops signalling a reaped
leader's pid, or a Perk-side leader that stays alive, holding its pid, until its descendants exit —
and measures the fix on both hosts. **Filesystem view and network policy are not provided** (no
namespace sandbox is available unprivileged on either measured host: `unshare -Ur`, `unshare -Ur
--pid --fork` and `unshare -Urn` are refused by the AppArmor user-namespace restriction locally and
on `ubuntu-latest`, and bubblewrap is installed on neither); the read-only reviewer snapshot and any
network policy remain P7 environment-policy obligations, and reviewers get no subprocess capability.
Not chosen, with measured reasons: PID namespaces (unavailable unprivileged on both hosts — every
`pidns/availability` row), a spawn journal (stop set = the registered process only; owner-written
state), a cgroup fence (Linux-only, cgroup writability varies by host — writable locally, `EACCES`
on `ubuntu-latest` — cooperative escape). Evidence:
`archive/pi-durable-v2-containment-characterization.md`.

## 11. The door envelope

```text
{ "envelope": 1, "outcome": <vocab>, "executionId", "epoch", "status": <snapshot | null>,
  "refusal": {reason, detail} | null, "mismatch": {field, expected, found} | null,
  "error": {message} | null }
```

**Fields.**

- `epoch` is the owner epoch this call held. For `owner_busy` it is the live holder's epoch.
- `refusal.reason` uses the §9 vocabulary, and `mismatch.field` names the first mismatching
  execution-manifest field (or `manifest_missing`).

**Outcomes.** The vocabulary is closed:

- `ok`;
- `pending_decision`;
- `owner_busy`;
- `incompatible`;
- `observation_failed`;
- `refused`;
- `uncertain`.

`ok` describes the door call. Whether the execution is waiting or completed is a field of the
status snapshot. `pending_decision` is returned by `start`, `run` and `reply` when quiescence's
wait reason is `pending_decision`. `status` returns `ok` with the snapshot, or `owner_busy` while a
run holds the lock, or `incompatible`.

**Status snapshot.** `state` is one of:

- `running`: work is runnable and no wait reason applies. A status open never runs it.
- `waiting(<wait reason>)`, for the non-terminal wait reasons;
- `completed` and `cancelled`, which appear as states of their own and never as `waiting(…)`;
- `incompatible`;
- `uncertain`.

The snapshot also carries the age of the latest observation, the assignments with their attempt
and acceptance state, and the open decision. Python validates the envelope with a strict Pydantic
boundary model (node 3.3) and never touches the store.

## 12. The fixture-review execution kind (a fixture)

**This is a fixture.** Real execution kinds replace it; nothing here is product behavior.

- **Kind:** `fixture-review`. The subject kind is `git-tree` per §5. The door takes `--ref`,
  which defaults to `HEAD`.
- **Assignments:** two of kind `fixture-report`, with roles `a` and `b` and an identical
  capability set:
  - model: the faux model;
  - extensions: the Perk report extension;
  - tools: Durable `read` plus Perk `ls`/`grep`/`find`;
  - posture: read-only;
  - workspace root: the snapshot.
- **Report schema:** `{subjectDigest, summary, findings: [{path, note}]}`.
- **Rules:**
  - admit both assignments over the observed subject;
  - accept each report at most once;
  - completeness, meaning both reports accepted for the same subject, produces an aggregate
    outcome;
  - open one decision of kind `fixture-approval`, with allowed actions `approve | reject` and actor
    `human:cli`;
  - a reply creates exactly one continuation (`perk.v2.continuation`), which records the
    execution's completion;
  - cancellation blocks all admission;
  - a subject (tree) that differs from the latest observation's refuses admission, acceptance and
    reply (`stale_subject`). A ref move with the same tree does not.

**Rule precisions (node 2.1).** The kernel (`extension/pi/v2/kernel/`) settles what the rules
above left open:

- **The current subject.** Every rule reads the latest observation's tree. A new tree starts a
  fresh round: reconcile admits both roles over it, under new assignment ids, and records over
  earlier trees stay inert. They are stale only by derivation (§5). A same-tree observation
  changes nothing.
- **Attempts.** Reconcile starts attempt 1 of each admitted assignment in the commit that admits
  it. The attempt record carries Perk ids only. Its Durable conversation and submission are
  durable-map rows (§6), so §4's `submit` payload is the binding's to compare (node 2.2). The
  fixture never starts a second attempt, and an incomplete attempt stays visible.
- **Terminal states.** Once a cancellation is recorded or a continuation exists, reconcile emits
  no action of any kind. Observations are still recorded, and `cancel` is still accepted.
- **The policy.** The fixture rules take a host-resolved policy `{capabilitySet}`, so the kernel
  signature is `reconcile(records, policy)`. The policy is code-owned, and the execution
  manifest's `policyVersion` versions it.
- **Refusal order.** Receipt lookup comes first (§4). Then identity (`unknown_decision`,
  `invalid_input`), freshness (`stale_subject`), cancellation (`cancelled`), supersession
  (`superseded`), and last the report content (`invalid_report`).
- **Supersession.** A reply or a report acceptance is `superseded` once the execution has consumed
  a decision, i.e. once a continuation exists.
- **Report validity.** `invalid_report` covers the strict report schema (non-empty `summary` and
  notes, snapshot-relative finding paths, no extra keys), a report subject other than the
  assignment's, and a verified digest other than the latest observation's manifest digest.
- **Well-formed text.** Every caller-supplied string the kernel records is well-formed Unicode (no
  lone surrogates), so every recorded payload has a canonical form and its operation replays
  (§4). Ill-formed report text is `invalid_report`; any other ill-formed input is
  `invalid_input`.
- **Tracked ref.** Every observation names the repo and ref of the execution's first observation;
  any other is `invalid_input`.
- **Record integrity.** The kernel refuses to decide over a record set whose references do not
  resolve, for example a reply without its decision or an outcome that disagrees with its
  attempt. That is a binding fault, not a refusal. Presenting every record is the binding's
  obligation (§6, node 2.2).

## 13. The four-question extension recipe

A new v2 capability is added by answering four questions, and nothing else should be needed:

1. What is its **subject**, and how is the subject materialized?
2. Which **observations and records** does it add?
3. Which **reconcile rules** decide its next actions?
4. Which **assignment kinds or action executors** carry those actions out, with which capability
   sets?

| Question | The fixture's answer |
|---|---|
| 1. Subject | `git-tree`: the tree oid at the tracked ref, materialized as the read-only snapshot with its tree-derived snapshot manifest (§5) |
| 2. Observations and records | the `perk.v2.observation` family, plus the §6 families (manifest, assignment, attempt, outcome, decision, reply, cancellation, durable-map) |
| 3. Reconcile rules | §12's rules |
| 4. Executors | the `fixture-report` assignment task, with the §12 capability set, and the `perk.v2.continuation` task |

Question 1 is where a kind chooses content identity or commit identity (`git-tree` vs
`git-commit`, §5). A capability that needs a fifth question is a principle amendment, not a
feature.

## 14. Deferrals

| Item | Why deferred | Owning future objective |
|---|---|---|
| Real execution kinds | the fixture proves the principles; product behavior needs real subjects | the plan-workflow objective |
| Effect ledger: intent → effect → reconciled observation, with incremental submit and the stacked journal each getting its own reconciler | no effect is needed at fixture level; P10 fixes the shape | the plan-workflow objective |
| Budget admission: units, reservations across children, retries and compaction, unknown spend | only `pi.usage` totals are recorded; P10 fixes the shape | the plan-workflow objective |
| Subprocess capability for workers | no worker in this objective spawns; the §10 verdict binds how one may (supervised execution, the graceful-close order, the report-only sweep, and the per-attempt workspace isolation obligation) and the prerequisite before any may (closing the reaped-leader pid-reuse window) | the plan-workflow objective |
| Real provider, auth and settings composition | the faux model only | the plan-workflow objective |
| Extracting shared report definitions from v1 | v2 copies no v1 report-wave policy until real reviewer reports arrive | the plan-workflow objective |
| Record and task migrations (execution-manifest matches that are not exact) | this objective refuses any mismatch | the first objective that bumps an execution-manifest version |
| Store retention and GC of `.perk/executions/`, including owner epoch directories and abandoned temp directories | fixture executions are disposable | the first objective that produces non-fixture executions |
| Durable pin bump, including HEAD features (read-only Harness, deferred commits) | exact 1.4.0 only | a Durable adoption objective (the [pi-1.4.0 adoption](./archive/pi-1.4.0-adoption.md) pattern) |
| Objective coordination: multi-node eligibility, backend observations | needs the plan workflow first | the objective-coordination objective |
| `/learn` continuity | needs retained evidence from real executions | the learning-continuity objective |
| Chord or browser transport, multiple clients, wakeable or daemon host, status during a run | `status` during a run returns `owner_busy` | the shared-workspace objective |
| User docs and the `perk-expert` mirror | v2 is hidden | the objective that makes v2 end-user usable |
| v1 migration and switching the default | v2 is experimental | an adoption objective after the plan workflow |

## 15. Consumers and reconciliation

| Node | Sections consumed |
|---|---|
| 1.2 | §2 location and verification; P10 layering |
| 1.3 | §3 evidence pointers, one test per Durable behavior, each naming its principle. A failure amends this record before dependents proceed. |
| 1.4 | §10 step 2 and its verdict subsection; P7, P8 |
| 2.1 | §4 including the replay rule; §5 digests and observation order; §6; §7 kernel; §9 refusal reasons; §10 wait reasons; §12 rules |
| 2.2 | §6 families, record keys, receipt lookup, checkpoint policy and the binding constraint; §7 `operate`, receipt-first lookup and task ownership; §9 |
| 2.3 | §10 lifecycle, the lock protocol and its proof list; §11 outcomes |
| 2.4 | §5 snapshot-manifest grammar, verifier and the symlink/gitlink proofs; §8. Its proof "a new commit at the ref yields a new subject" reads as "a new *tree* at the ref yields a new subject, and a commit with the same tree yields a new observation of the same subject". |
| 3.1 | P7 enforcement seam; §5 verification points; §12 |
| 3.2 | §4 reply payload and replay rule; §7 reply and continuation; §8; §9 |
| 3.3 | §10 status; §11 envelope, plus the `shared/contracts.md` v2 section |
| 3.4 | §13 as exercised; appends §16 |

**Reconciliation rule.** Two kinds of change force re-verification: a bump of
`@earendil-works/pi-durable`, `chord` or `pi-env` in `extension/pi/v2/package.json`, and any change to
P1–P10. Re-verification means re-running node 1.3's characterization suite and the containment
probes (`just test-v2-slow`, on a local host and `ubuntu-latest`), re-checking every Source-pins
pointer (§1), and amending this record in the same PR. A runner-image or kernel-line change also
re-runs the containment probes. A principle change is an
explicit, reviewed amendment, recorded in the log below.

**Amendment log.**

| Change | Where |
|---|---|
| Record created: P1–P10 with evidence; identity, subject, tier, write, observation, outcome, lifecycle (epoch-named owner directories), envelope, fixture, recipe, deferral and consumer sections | node 1.1 |
| Containment and fencing verdict recorded (§10): GO supervised, with closing the reaped-leader pid-reuse window as a prerequisite before workers spawn; pi-env 1.4.0 joins the pin family; evidence archive/pi-durable-v2-containment-characterization.md | node 1.4 |
| §12 rule precisions — current-subject rounds, attempt 1 started with admission, terminal cancellation and completion, the policy parameter, the refusal order, `superseded` as a spent decision, report validity, well-formed text, the tracked ref, record integrity | node 2.1 |

## 16. Measured evidence (reserved — node 3.4)

Node 3.4 appends here the MEASURED vs SOURCE-DERIVED exit assessment (work retained, work
repeated, manual recovery steps, obligations added and removed, the recipe as exercised) and the
hand-off list for the plan-workflow objective.
