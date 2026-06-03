# Phase 2 · Turn 7 — the `/address` review loop (new `address` stage)

GitHub plan: #15. The decision-complete plan body (decisions, corrections, prior-art evidence) lives
on the issue; this doc records the turn's design anchors and (below) the as-built outcomes.

## What this turn adds

perk's review-handling stage: **classify-then-act**. The verbose GitHub-feedback fetch +
classification runs inside an **isolated spawned read-only child** (the borrowed `pi-subagents`
engine wired in T6), so raw comment JSON never enters the main session; the **parent** (judgment +
durable writes) applies fixes and resolves threads through a deterministic batched op. First new
stage of Phase 2 (`submit → address → land`), built on the T6 substrate.

## Design anchors (the locked shapes)

- **Graph:** `address` inserted linearly between `submit` and `land` (`shared/registry.yaml`):
  `mode: read-write`, `worktree: reuse`, per-stage I/O filled (`requires: [github.pr]`; reads the
  plan-ref + PR + review-threads + comments; writes review-threads + comments + PR +
  workflow-state). Single initial (`plan`), single terminal (`learn`), symmetric edges preserved.
- **Registry-generated launcher:** `address` is **not** in `DEDICATED_STAGES`; `perk address` is the
  generic launcher, and its session is primed by extending `launch._initial_prompt` (alongside
  `implement`).
- **Classify = a spawned read-only child** running the perk-owned agent `perk.review-classifier`
  (`.pi/agents/review-classifier.md`, namespaced `package: perk`). The child runs
  `perk pr-feedback --json` itself, wraps all GitHub text as untrusted, classifies each item
  (actionable / informational / praise / question), keeps review threads and discussion comments
  separate, and returns double-delivery (compact table + structured block). Cheap model tier
  (`anthropic/claude-haiku-4-5`, fallback `claude-sonnet-4-5`).
- **Act = parent** (never delegate the fix); **resolve = one batched op** (the §8.4
  `resolve_review_threads`: Python `perk pr-resolve-threads --json --batch <file>`; warm TS
  `resolve_review_threads` tool writes a run-scoped scratch file and delegates via `pi.exec`, then
  appends `last_review_batch`).
- **Judgment in a skill** (`skills/perk-address/SKILL.md`): classify → only-actionable → fix →
  resolve, preview, Plan File Mode, untrusted wrapping, never-delegate boundaries.
- **`.agents/` collision mitigation:** namespace (`package: perk`) + explicit-name invocation +
  doctor note. **No** `subagents.disableBuiltins`; **no** attempt to suppress the legacy scan.

## Key changes

- `shared/registry.yaml` — the `address` stage + rewired edges.
- `perk/github.py` — GraphQL constants (verbatim from erk) + `get_pr_feedback` /
  `resolve_review_threads` + frozen dataclasses.
- `perk/cli/commands/pr_feedback_cmd.py`, `pr_resolve_threads_cmd.py` (+ `cli.py` registration).
- `perk/launch.py` — `_initial_prompt` primes `address` (`_address_prompt`).
- `extension/address.ts` (+ `index.ts` `registerAddress`) — the `resolve_review_threads` tool +
  `/address` (+ `--preview`) command.
- `.pi/agents/review-classifier.md`, `skills/perk-address/SKILL.md`.
- `perk/doctor.py` — `_subagent_engine_check` detail note (benign stray legacy `.agents/` agents).
- `shared/contracts.md` — §8.4 authored `resolve_review_threads` + `get_pr_feedback`; §8.3 "Review
  loop (`/address`, P2.T7)" paragraph (+ `last_review_batch` shape now live).
- Tests + `scripts/verify-p2-t7.sh` (wired into `justfile` `verify`).

## Offline-test boundary

The spawned classify child's *live* behavior needs a model → dogfood/manual gate, not CI. CI covers
the Python workers (fake gateway), the registry stage + generated launcher, the TS tool's delegation
(`fakePerk`) + `last_review_batch` write, agent-def + skill presence, and doctor/init wiring.

## Outcomes (as built)

- **Built exactly as planned.** All ten plan decisions landed unchanged: the linear `address` stage,
  the registry-generated launcher primed via `_initial_prompt`, the spawned `perk.review-classifier`
  child, parent-owned fixes, the batched `resolve_review_threads` op (Python worker + warm TS tool),
  the `--preview` variant, Plan File Mode in the skill, the namespace+explicit-name `.agents/`
  mitigation, and the skill/agent split of judgment vs mechanics.
- **`last_review_batch` shape.** The warm tool records `{ pr, counts, resolved_thread_ids, at }`;
  `pr` and `counts` are optional tool params so the parent (which holds the classification) can fill
  them — `threads` is the only required param. A failed/partial batch records **no**
  `last_review_batch` (only a fully-successful resolve is recorded).
- **`/address` warm entry.** The command injects the address-workflow guidance via
  `pi.sendUserMessage` (always triggers a turn); `--preview` injects classification-only guidance.
  Both are headless-safe (`ctx.hasUI`-guarded notify, else stderr). The command's live turn-trigger
  is part of the dogfood gate; CI verifies registration + the tool delegation only.
- **ty narrowing.** The batch-file loader casts the post-`isinstance` `dict` to `dict[str, object]`
  (`typing.cast`) — ty narrows JSON `object` to a `Never`-keyed dict otherwise.
- **Dogfood / manual gate (not yet run live):** on a real perk PR with review feedback, run
  `/address` and confirm (1) the verbose feedback JSON never enters the parent transcript, (2) the
  parent fixes only actionable items, (3) `resolve_review_threads` batch-resolves the threads. To be
  recorded here when exercised (mirrors T6's spike record).
