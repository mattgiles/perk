# Phase 2 · Turn 17 — make `/learn` active (seed prompt + capture skill)

> The decision-complete plan lives on GitHub plan **#28** (`plan-body` block). This doc records the
> prior-art pass, the decisions, and — written **after** it lands — the as-built **outcomes**.
>
> **Turn-id note:** the plan body was authored as "P2.T13", but turns 13 (`/plan-save` re-save
> fix, plan #27), 14 (CLI aliases, plan #31), 15 (checkpoint loop, plan #36), and 16 (lockfile
> sweep) landed first. This turn is therefore **P2.T17**.

Closes the Tier-1 + Tier-2 gap documented in `docs/bugs/learn-is-a-stub.md`: perk's `learn` step
was **passive at every layer** — the cold launch opened an unprimed session and a bare warm `/learn`
only cleared the `pending-learn` marker. The capture *mechanism* (`learn` tool + `learn-capture`
worker) already existed; nothing **drove** the agent to investigate the landed change and produce
learnings. This turn adds the driver with the established **seed-prompt + skill + guidance-injection**
pattern (the same one `implement`/`address`/`objective-plan` use) — **no new gateway op**.

## Decisions

- **Reuse the durable-write path; add only the driver.** The `learn` tool's
  `summary`→capture / no-summary→clear contract is correct and unchanged; `learn-capture` already
  creates the idempotent `perk:learn` issue + back-link and clears the marker. Only the **seed
  prompt** and the **warm `/learn` command** behavior change.
- **Prime the cold launch.** `perk/launch.py` gains `_learn_prompt(plan_ref)` and an
  `_initial_prompt` branch for `stage.id == "learn"`, mirroring `_implement_prompt`/`_address_prompt`.
  It derives the merged PR from the `plan-<pr_id>` head branch (because `pr_id` is the **plan-issue**
  number, not the PR), points at the `perk-learn` skill, and stresses untrusted-DATA discipline. A
  learn launch without a resolvable plan-ref stays unprimed (matching implement/address).
- **Make the warm bare `/learn` active.** The `/learn` command handler now dispatches on args:
  `skip` → pure marker-clear; non-empty text → verbatim capture (back-compat); **bare + interactive**
  → inject `perk-learn` guidance via `pi.sendUserMessage` (the agent clears the marker by calling the
  `learn` tool — the command does **not** clear it); **bare + headless** → the safe marker-clear
  (can't drive a turn — honors the AGENTS.md headless-fail-safe rule). `learnGuidance` is exported
  for direct unit testing.
- **`perk-learn` skill is the judgment layer** both surfaces point at — authored in the house style
  of `perk-address`/`perk-objective-reconcile` (inputs as untrusted DATA, what to capture,
  the write, skip-if-nothing, never-delegate boundaries). Auto-discovered via the existing
  `pi.skills: ["./skills"]`.
- **No verify script.** The plan body sketched `scripts/verify-p2-t13.sh`, but plan #33 retired the
  `scripts/verify-*.sh` model and moved regression coverage into the pytest + `node:test` suites.
  Coverage lands as ordinary test cases (`tests/test_launch.py`, `extension/learn.test.ts`) instead.

## Scope

- `perk/launch.py` — `_learn_prompt` + `_initial_prompt` learn branch.
- `extension/learn.ts` — `learnGuidance` + reworked `/learn` command dispatch (tool unchanged).
- `skills/perk-learn/SKILL.md` — new skill.
- `shared/contracts.md` §8.4 + `shared/registry.yaml` `learn` stage — amend to describe the now-active
  capture (primed launch + guided warm door); no new I/O keys.
- Tests: `tests/test_launch.py::test_initial_prompt_primes_learn`; `extension/learn.test.ts` learn
  command + `learnGuidance` cases.

## Out of scope (Tier 3 — separate objective node)

Session-transcript bundling on land, multi-agent session/diff/docs/review analysis behind the
`pi-subagents` seam, and the `docs/learned/*.md` documentation-plan loop (plus the learn-from-a-learn
cycle guard). Needs a session-format design pass and overlaps the Phase-3 headless worker. Flagged,
not built.

## Outcomes (as-built)

- **Python plane** — `_learn_prompt` + the `learn` branch in `_initial_prompt` landed exactly as
  planned; `test_initial_prompt_primes_learn` asserts the skill name, the derived `plan-42` head
  branch, the `gh pr list --head plan-42` command, the `learn` tool drive, `/learn skip`, and the
  `None` (no plan-ref) fallthrough. `test_initial_prompt_primes_implement_and_address` kept its
  `plan → None` assertion.
- **TS plane** — `/learn` command reworked as planned; `learnGuidance` exported. Tests cover
  `/learn skip` (marker-clear), bare headless (safe marker-clear), bare interactive (guidance
  injected + marker kept + notify), and a direct `learnGuidance` unit test. The bare-interactive
  test drives the real bound session through `runCommandHandler`; `pi.sendUserMessage` did not block.
- **Contract/registry** — amended in the same turn (the primed-learn paragraph in §8.4, the learn
  stage comment in the registry). No I/O-key change (no new gateway op).
- **Turn-id reconciliation** — recorded above (plan body's "P2.T13" → actual P2.T17).
