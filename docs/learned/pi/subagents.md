---
title: perk's subagent orchestration — project vs builtin agents, and the two mutation shapes
read_when: You are spawning a subagent for fresh-context work, configuring a project agent's model, choosing read-only-child-then-parent-mutates vs child-posts-own-mutation, or working on the `/pr-review` / `/address` orchestration.
---

# perk's subagent orchestration

perk delegates fresh-context work (PR review, classification, objective exploration) to subagents
via the `pi-subagents` package. The agent defs live in `.pi/agents/*.md` (hand-committed); the warm
commands (`/pr-review`, `/address`) spawn them. This doc captures the non-obvious rules an agent
can't derive from any single file.

> **One Code Rule.** Everything below names files and describes behavior; it does not reproduce
> source (the one GitHub-API reference is flagged as such). Read the pointers.

## `subagents.agentOverrides` reaches only BUILTIN agents — never project agents

`subagents.agentOverrides` only applies to **builtin** agents; it does **not** reach project agents
loaded from `.pi/agents/`. Proof: `pi-subagents`' `applyBuiltinOverrides`
(`.pi/npm/node_modules/pi-subagents/src/agents/agents.ts`).

**Correction:** a prior `shared/contracts.md` §8.3 note claimed the classifier model is "overridable
via `subagents.agentOverrides`." That was **wrong** and is corrected — do not restate it as
still-true.

## The correct knob for a configurable project-agent model

A committed frontmatter `model` default + a **per-call inline `model` override** on the `subagent`
tool call (the `model` param exists in `pi-subagents`' `schemas.ts` for single runs). `/pr-review`
reads `[pr-review] model` from `perk.toml` (overlaid by `perk.local.toml` for per-user override) and
injects it inline — **no committed-file churn**.

## Two mutation shapes — when the spawned child posts vs. when the parent does

- **`/address`** keeps the spawned child **read-only**; the **parent** applies fixes/mutations.
- **`/pr-review`** deliberately departs: the child **posts its own review**, because the PR is the
  *sole output sink* and there is no parent-side fix — relaying back through the parent would
  reintroduce the session pollution the fresh context exists to avoid.

**Decision rule:** child-posts-own-mutation **iff** the spawned work's only output sink is the
external surface and there's no parent-side action; otherwise read-only child + parent mutates.

**D1 holds in both:** the GitHub mutation stays canonical in Python (`perk pr review-post`); the
child only has `bash` (run the CLI) + `write` (stage the payload file). It never holds a GitHub
token or composes the mutation itself.

## Isolation knob: `context: "fresh"` vs `"fork"`

`context: "fresh"` is a clean session (for independence — reviews want this); `context: "fork"`
branches the parent's history. Pick `fresh` whenever the child's judgment must not be colored by
parent context.

## Flat agent/seam-keyed config pattern

perk uses a flat selection pattern under `[subagents]` in `perk.toml` to map specific agent seams to
selected agents, mirroring the `[providers]` layout. This config is parsed in TypeScript
(`parseSubagentsSelection`) and in Python (`_parse_subagents_selection`) via simple dict comprehension
(or equivalent object mapping) over a fixed, known-keys tuple. Because it maps keys directly without
complex dynamic schemas, there is no specialized doctor validation required for these selections.

## Cross-plane parity literals

For shared subagent subsystems that are executed on both planes (like `review-classifier` in
`extension/worker.ts` and `perk/launch.py`), the model and prompt clauses must remain byte-identical
across TypeScript and Python. This parity must be strictly pinned by reciprocal tests in both test
suites (e.g., `worker.test.ts` asserting `ADDRESS_MODEL_CLAUSE` and
`test_worker_prompt_parity.py` asserting `_ADDRESS_MODEL_CLAUSE` against the same expected prompt
template or model string).

## Guidance testing

To ensure warm-door pure guidance builders (such as `addressGuidance` or `factoryGuidance`) can be
thoroughly verified without launching heavy live sessions, they must be exported from their
defining modules. This makes it possible to unit-test the prompt generation logic offline in standard
test suites.

## TS TOML trailing-backslash continuation restriction

The simplified TOML subset parser implemented in the TypeScript plane does not support trailing-backslash
(`\`) multiline string continuation. When defining strings in `perk.toml` (or any other TOML file parsed
by TS), you must use either a single unbroken line or other narrow subset escapes supported by the parser.

## Resilience for inline-anchored GitHub review submission

`POST .../pulls/{n}/reviews` with `event=COMMENT` + `comments[]` can **422** when a `line` isn't in
the diff. The gateway **falls back** to posting summary + rendered findings as a single discussion
comment (`POST .../issues/{n}/comments`) so a review *always* lands, recording which path it took
(`mode: "review" | "comment_fallback"`). `event=COMMENT` is **hardcoded** so the agent can never
approve / request-changes. (This is an API-behavior reference — see `## Sources`.)

## Agent-def delivery is a known gap

perk's `.pi/agents/*.md` are **hand-committed** and auto-enumerated by doctor's
`subagent-engine` / `subagent-agents` checks — so a new hand-committed agent def needs **no** doctor
edit. But the `@perk/pi` package ships only `extension/` + `shared/`, so delivering perk's agent defs
to *consumer* repos is still **unbuilt**. Flag as a deferral.

## Residual

No workflow-state record of a `/pr-review` (no parent tool turn → no `last_review_batch`-style
record); the posted PR comment is the canonical record. `perk/config.py`'s `pr_review_model` is
parsed-but-unused today (only the TS warm path consumes it — no cold `/pr-review` door yet).

## Sources

- GitHub Pull Request Reviews API: `POST /repos/{owner}/{repo}/pulls/{n}/reviews` (the `event` /
  `comments[].line` shape) and `POST /repos/{owner}/{repo}/issues/{n}/comments` (the comment
  fallback). The 422-on-out-of-diff-line behavior is the documented reason for the fallback.

## Cross-references

- `extension/prReview.ts` — `prReviewGuidance`, `registerPrReview`, the child-posts-own-mutation header
- `.pi/agents/pr-reviewer.md`, `.pi/agents/review-classifier.md` — the hand-committed agent defs
- `perk/cli/commands/pr_review_post_cmd.py` — the canonical Python mutation (D1)
- `shared/contracts.md` §8.3 — the corrected `agentOverrides` note + workflow-state schema
- `docs/learned/workflow/warm-door-commands.md` — the driving-command shape `/pr-review` departs from
- `docs/learned/workflow/skill-bindings.md` — the `command:<id>` binding checklist (`/pr-review` is one)
- the `pi-subagents` skill — single/chain/parallel/forked-context delegation
