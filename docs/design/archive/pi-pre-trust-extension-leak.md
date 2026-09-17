# Evidence: pi's pre-trust extension leak — a user-scope pi-subagents duplicate answers perk's wave RPC with `no_active_session`

**Status:** anonymized evidence record — the mechanism behind every perk wave launch failing
with `spawn-failed: no_active_session` *while the wave actually launched*, observed in a consumer
repository whose user-scope pi settings listed `npm:pi-subagents` beside the project entry perk
converges. It motivated the adapter's context-less hold (`shared/contracts.md` §8.35 "RPC reply
selection"), the once-per-activation duplicate-load warning, and the doctor
`subagent-package-scope` check. This repository is public: the record carries no consumer
org/repo names, local paths, session/run identifiers, or exact operational timestamps.

## The matrix

| Component | Version | Provenance |
|---|---|---|
| Pi | `@earendil-works/pi-coding-agent` 0.85.1 | `package.json` devDependencies; `dist/core/resource-loader.js`, `dist/core/extensions/loader.js`, `dist/main.js` read in place |
| pi-subagents | 0.68.0 (npm latest, unpinned) | `.pi/npm/node_modules/pi-subagents/src/extension/rpc.ts` (the package ships TypeScript sources) |
| perk | 3.4.0 (pre-fix) | the wave adapter's first-reply `request()` in `extension/waves/rpcAdapter.ts` |

## The symptom

In the affected repository, every code-owned wave launch — `start_draft_review_wave`,
`start_review_wave`, `run_scout_wave` — returned

```
spawn-failed: no_active_session: No active extension context for subagent RPC.
```

and yet the wave ran: pi-subagents wrote the run directory, the children executed, and the
workflow completed. perk never stored the wave ref (the launch had "failed"), so `collect_*`
answered `no_wave`, the browser's `perk:wave` marker never cleared, and the parent told the
human the wave never launched. Deterministic: every launch, every session, once the user-scope
entry existed.

## The mechanism (pi 0.85.1 / pi-subagents 0.68.0, function anchors)

1. **Two-phase trust load.** For a `worktree: none` stage perk launches `pi` without
   `--approve`, so `dist/main.js::shouldResolveProjectTrust` is true and the resource loader runs
   its two-phase load. `loadProjectTrustExtensions()` forces project-untrusted and loads the
   **user-scope** packages' extensions — the user-scope `pi-subagents` factory runs and registers
   its RPC bridge (`pi.events.on(SUBAGENT_RPC_REQUEST_EVENT, …)`) on the shared event bus.
2. **Dedup without invalidation.** After trust resolves, `loadFinalExtensionSet()` computes the
   deduped final set — pi dedupes packages by identity and the **project** `pi-subagents` wins —
   and loads it with the **same** runtime and bus (`preTrustExtensions.runtime` is reused). The
   user-scope instance is filtered out of `orderedExtensions` but is **not invalidated**: event-bus
   subscriptions are tracked per runtime (`dist/core/extensions/loader.js::trackEventBusSubscription`)
   and cleared only by `runtime.invalidate()`, which this path never calls on the dropped instance.
3. **A context-less responder.** The orphan never receives `session_start`, so in
   `src/extension/rpc.ts::handleRequest` its `getContext()` stays `null` forever. `ping` still
   succeeds (its `pingData` needs no ctx); every other method throws `no_active_session`
   synchronously, **before `executeChecked` does any work**.
4. **First reply wins.** The live (project) instance spawns and replies `success: true` a few
   milliseconds later on the same per-request reply channel. perk's `request()` settled on the
   **first** reply — the ghost's error — every time.

The mechanism is specific to extensions whose factory subscribes on `pi.events` at load (the
pi-subagents RPC bridge does); it is not a property of every duplicated package.

## The ordering proof (relative terms)

The affected workflow's receipt — written by pi-subagents itself — carried an `rpc-spawn-…`
parent tool-call id whose `startedAt` preceded the error tool result of the **same request id**
by tens of milliseconds. The engine had started the run before perk's launch "failed"; the
error could not have come from the instance that spawned it.

## The A/B

Same repository, same day:

- under an agent dir whose user `settings.json` listed `npm:pi-subagents` beside the project
  entry: every launch failed identically, across three sessions;
- under an agent dir without the user-scope entry: the same launches succeeded.

The user-scope entry's addition postdates the last recorded success and predates the first
recorded failure. perk's own repository never sees the defect because `[pi] agent_dir =
".pi/agent"` keeps the user-global settings out of play; a one-brief `run_scout_wave` under that
repo-local agent dir succeeded during the same investigation, consistent with the mechanism.

## Repro protocol

1. In any perk-managed repo (project `.pi/settings.json` carrying `npm:pi-subagents` via
   `perk init`), add `npm:pi-subagents` to the launch-precedence agent dir's user
   `settings.json` (`pi install npm:pi-subagents` against pi's default `~/.pi/agent` store).
2. Launch a perk stage session without `--approve` (any `worktree: none` stage; a warm `pi`
   session in the repo works too) and run a one-brief `run_scout_wave`.
3. Pre-fix: `spawn-failed: no_active_session …` with a run directory nevertheless created under
   pi-subagents' artifact root. Post-fix: the launch returns `workflow accepted … (asyncId …)`,
   one `perk: waves — A duplicate pi-subagents extension is loaded …` warning appears, and
   `perk doctor` warns `subagent-package-scope` naming both files.
4. Remove the user-scope entry (`pi remove npm:pi-subagents`) and **restart** the session —
   `/reload` re-runs the same two-phase load and does not clear the orphan.

## What perk changed (and did not)

- **Hold, not census.** The adapter holds exactly the `no_active_session` reply and keeps
  listening: a later success wins (one fail-open `duplicate-responders` notice), a *different*
  error surfaces immediately, and only the reply timeout surfaces the held error with a suffix.
  No ping settle window, reply count, new knob, or transport-tier types. Accepted cost: a genuine
  single-responder `no_active_session` surfaces only at the reply timeout.
- **`ping` stays first-reply.** The context-less responder cannot fail it, and the advertised
  async-complete channel has been one constant across every verified release — two loaded
  versions advertising different channels would time the wave out loudly, never lose it silently.
- **No `--approve` for `worktree: none` launches.** It would skip the two-phase load but trust a
  project the user has not trusted, and would not cover warm doors in bare `pi` sessions.
- **Duplicate *live* responders are not reconciled.** Two successes ⇒ first wins; perk neither
  stops nor adopts the extra run — the doctor warning is the remedy.

## Deferred follow-ups

- Draft-reviewer lane hardening (bounded searches; a thin schema-valid report on tool timeout) —
  a 5-minute `grep` produced a report-less ponytail failure in the same incident.
- Collect-from-receipt recovery for a wave whose spawn reply times out while the spawn succeeds.
- Upstream: pi-subagents' completion-notice previews and steer-behind-tool-call behavior; a pi
  issue for the leaked pre-trust event-bus subscriptions (the dropped pre-trust instance should be
  invalidated when the final set excludes it).
