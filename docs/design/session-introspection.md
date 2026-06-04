# Design: session introspection as a capability

**Status:** design sketch (unbuilt)
**Motivation:** perk can drive a workflow but cannot *look back at what happened in a session*. Two
consumers want this: `learn` (the knowledge loop — see
[`docs/bugs/learn-is-a-stub.md`](../bugs/learn-is-a-stub.md) Tier 3) and **planning** (point at bad
behavior in a session and turn it into a bug or a fix-plan — which is exactly what
[`docs/bugs/plan-updates.md`](../bugs/plan-updates.md) and
[`docs/bugs/learn-is-a-stub.md`](../bugs/learn-is-a-stub.md) were, written by hand).

## The framing: a substrate, not a feature

Today perk reads only the **current, live** session — `ctx.sessionManager.getBranch()` rebuilt into
`perk:workflow-state` via last-write-wins over `custom` entries (`extension/workflowState.ts`). It
never reads a session as *data*: there is no way to open a past session, ask "what actually
happened," or address a specific moment in it.

The capability is a **read-only reader over pi session JSONL** that turns a session into structured,
queryable facts — and then `learn`, `plan`, and even `docs/bugs/*` sit on top of it. One substrate,
multiple consumers (the same shape the repo already uses for the GitHub gateway and the
`pi-subagents` engine). The LLM only enters at the *consumer* layer; the reader itself is a
deterministic projection.

## The raw material is already well-structured

pi sessions are JSONL trees at `~/.pi/agent/sessions/--<cwd>--/<ts>_<uuid>.jsonl`
(`pi/reference/session-format.md`). The entry types already carry almost everything an introspector
wants:

- **The path taken** — `message` entries: `user` / `assistant` (with `model`, `usage`, `cost`,
  `stopReason`) / `toolResult` (`toolName`, **`isError`**, `details`).
- **What the agent ran** — `bashExecution` (`command`, `exitCode`, `cancelled`, `truncated`);
  non-zero exits are bad-behavior signals.
- **perk's own narrative** — the `custom` entries perk already writes: `perk:workflow-state` (stage
  transitions, run_id), `perk:checkpoint`, `perk:objective-budget`, `perk:mode-context`,
  `perk:plan-context`. So perk can correlate *its* lifecycle against the model's actions.
- **Where it went sideways** — `compaction` (context pressure), `branch_summary` (abandoned
  approaches), `stopReason: "aborted"/"error"`, `toolResult.isError`.
- **Cost/efficiency** — `usage` rollups per assistant turn.

An introspector is therefore mostly a *projection*, not an analysis engine.

## Architecture — three layers across perk's two planes

### Layer 1 — discovery + authoritative parse (the borrow)

The canonical parser is pi's own `SessionManager` (TS): `SessionManager.open(path)`, `list(cwd)`,
`listAll()`, `getBranch()`, `buildSessionContext()`. It handles version migration (v1→v3) and the
tree walk. **Do not re-implement the parser in Python** — it would drift from pi as the format
evolves. A thin TS worker opens a session and emits a stable JSON **digest**. perk already does
in-process `SessionManager` work in `extension/readOnlySession.ts`, so this is a natural extension,
not new machinery.

### Layer 2 — the digest schema (the queryable product; perk-owned, deterministic)

This is where the Python plane fits — pure, offline-testable against fixture digests, mirroring
`perk/plan.py` / `perk/objective.py`. A `SessionDigest` (illustrative):

```
SessionDigest:
  header:   { session_id, file, cwd, name, version, models[], started, ended, entry_count }
  timeline: [ { id, parent_id, ts, role, tool?, summary, is_error?, exit_code? } ]   # addressable, not raw
  tools:    { <toolName>: { calls, errors } }
  bash_failures: [ { id, command, exit_code } ]
  signals:  [ { id, kind, detail } ]   # aborts, tool errors, retries, compactions, abandoned branches
  usage:    { input, output, total_tokens, cost }
  perk:     { stages[], transitions[], checkpoints[], run_id }   # from perk:* custom entries
```

Key property: the `timeline` is **entry-id-addressable** and summarized — a projection with
addresses, never the raw transcript. That is what makes "point at *this* entry as a bug" precise and
keeps the digest context-efficient.

### Layer 3 — consumers

`learn`, `plan`, a `perk session show <selector>` cold door, and a `/session` warm surface — all read
the **digest**, never the raw JSONL.

## The missing link to build first: provenance (plan → session)

Sessions are filed by **cwd**, not by plan/PR. Nothing today records *which session implemented plan
#N*. So before introspection is useful for `learn`, perk must **stamp the session file/id into the
plan-ref** (or a `perk:workflow-state` field) at implement/submit time — perk already has
`ctx.sessionManager.getSessionFile()` in hand. That single provenance write is what lets `learn`
resolve `plan → session → digest` deterministically. (erk reaches the same place via session markers
+ bundling session XMLs into the learn PR.)

**Recommendation:** a `session_ref` field on the plan-ref — it is the most durable store and already
flows to `learn`. Alternatives: a `perk:workflow-state` entry (session-scoped, rebuilds with the
branch) or a pi `label` (user-addressable but fragile).

## Safety — session text is the worst-case input

- **Untrusted DATA, always.** A digest fed to any LLM (learn synthesis, bug framing) carries
  arbitrary model/tool output — wrap it in an `<untrusted_session>` treat-as-DATA preamble (the same
  discipline as `<untrusted_objective>` in `/objective-plan`).
- **Redaction + caps.** Strip env/secrets, truncate large `bashExecution.output` / tool results. The
  digest is a projection, not a dump — route, don't relay (the spawned-child double-delivery rule).
- **Read-only by construction** — it only opens JSONL. Fits a new `session.introspect` capability
  key: local, offline, no GitHub, no network.
- **Branch vs. tree.** Default to the **branch** (root→leaf — the path actually taken, what
  `buildSessionContext()` uses); offer `--full-tree`, since bad behavior can live on an abandoned
  branch.

## Consumer surface A — `learn` (Tier 3, finally tractable)

With provenance in place, `learn` resolves the implement session, gets the digest, and synthesizes
*what happened vs. the plan* — deviations, the bash failures it fought, retries, residual risk — not
just the code diff. The digest's `signals` are the seeds for durable learnings. This is erk's
"analyze the sessions" half without re-implementing their session-XML extraction pipeline.

## Consumer surface B — "point at bad behavior as a bug" (during planning)

The more novel surface, and the one we have been doing **by hand** (writing the two `docs/bugs/*.md`).
Made first-class:

1. You point at a session — `perk session show <selector>` or `/session` in a planning turn. Selector
   = a `/name`d session, the current branch, or `plan/PR → session` via provenance.
2. The digest renders the timeline with **entry ids** (and honors pi `label`s — you can bookmark the
   bad moment live via `/tree`).
3. You (or the agent) select the offending slice — a tool-call + its error result + surrounding
   intent. perk extracts it into a structured **bug seed** (command/tool + args + error + the model's
   stated intent), wrapped as untrusted DATA.
4. That seed feeds the plan factory (a "fix this behavior" plan) *or* auto-drafts a
   `docs/bugs/<slug>.md` in the format we have been using. "I saw the agent do X wrong → a plan to fix
   it" becomes a one-command path with the evidence attached.

## Open decisions

- **Where the digest worker runs.** A TS worker invoked by the Python cold door (Python shells to
  node — inverting the usual `extension → perk` direction), vs. discovery in Python and only the
  parse in TS. *Lean: TS parse (authoritative) → JSON digest → Python owns schema/queries/consumers.*
- **Provenance storage.** `session_ref` on the plan-ref vs. a `perk:workflow-state` entry vs. a
  session `label`. *Lean: plan-ref (durable + already flows to `learn`).*
- **Digest granularity / redaction policy.** What is in the default projection vs. behind `--full`
  (cost vs. completeness).
- **Cross-repo / cross-cwd.** `SessionManager.listAll()` enables "find the session where I saw this,"
  but widens the trust + privacy surface — gate it explicitly.
- **Format-version coupling.** We borrow pi's parser (migration-safe), but the *digest schema* is
  perk-owned and must fail loud on an unknown session version rather than silently mis-projecting.

## Suggested phasing

1. **Provenance write (tiny, ships with `learn` Tier 1+2).** Stamp `session_ref` into the plan-ref at
   implement/submit. No reader yet — just the durable link, so nothing has to be back-filled later.
2. **The reader + `SessionDigest` (the substrate).** The TS digest worker + the Python schema/queries
   + `perk session show <selector>` cold door, fully offline against fixture sessions. This is the
   capability proper.
3. **Consumer A — `learn` digest.** Wire the digest into the `learn` synthesis (Tier 3 of the learn
   doc).
4. **Consumer B — session → bug/plan.** The `/session` warm surface + slice-to-bug-seed + the plan
   factory / `docs/bugs/` draft path.

Phases 2–4 are each plausible objective nodes; phase 1 is a one-line addition that should ride the
`learn` fix so the provenance link exists before anything needs it.

## References

- pi: `pi/reference/session-format.md` (entry types, `SessionManager` API), `pi/start-here/sessions.md`,
  `pi/programmatic-usage/sdk.md`.
- perk: `extension/workflowState.ts` (the live `getBranch` rebuild), `extension/readOnlySession.ts`
  (in-process `SessionManager` precedent), `extension/index.ts` (`getSessionFile()`),
  the `perk:*` custom entry types (`perk:workflow-state` / `perk:checkpoint` /
  `perk:objective-budget` / `perk:mode-context` / `perk:plan-context`).
- related perk docs: `docs/bugs/learn-is-a-stub.md` (Tier 3 consumes this),
  `docs/bugs/plan-updates.md` (a hand-written instance of consumer B).
- erk prior art: `src/erk/cli/commands/land_learn.py` (session-XML bundling on land),
  `.claude/commands/erk/learn.md` (multi-agent session analysis),
  `erk_shared/learn/extraction/session_schema.py` (their session-digest analogue).
