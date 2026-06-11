---
title: The cold-door pi-launch seam and composing --json surfaces
read_when: You are touching launch_stage's argv construction, pi project-trust on ephemeral worktrees, wrapping a last-wins CLI, composing/testing a Python surface that nests a command emitting machine_output, or refactoring launch/run modules behind byte-exact test pins.
---

# The cold-door pi-launch seam

A perk *local* stage launch ends by `execvpe`-ing into `pi`: the perk CLI process **becomes** pi. This
seam (`perk/launch.py`) carries a handful of non-obvious mechanics about argv construction, pi's
project-trust prompt on throwaway worktrees, and what happens when a `--json` surface composes a
launcher that emits its own JSON.

## Build `argv` once, branch only on execute-vs-preview

`launch_stage` builds the full `argv` vector **once, before** the `dry_run` branch, so the dry-run JSON
preview and the real `os.execvpe` stay in lockstep — the `--approve` injection shows up faithfully in
`--dry-run --json`. **Generalize:** build the launch vector once and branch only on
execute-vs-preview, never construct two divergent vectors.

## pi project-trust vs perk's ephemeral worktrees

pi prompts for project trust on a cwd that has trust inputs (`.pi/`, `AGENTS.md`/`CLAUDE.md`,
`.agents/skills` in the cwd or an ancestor) and no saved decision; trust is keyed per canonical cwd and
persisted in `~/.pi/agent/trust.json`. perk `chdir`s into a brand-new `plan-<id>` checkout for every
worktree stage, so pi re-prompted on **every** `implement`/`submit`/`address`/`land`/`learn` launch.

**Fix:** prepend `--approve` for worktree stages —
`trust_args = ["--approve"] if stage.worktree != "none" else []`.

### `--approve` works in *interactive* mode, not just `-p`/`--mode json`

The pi docs describe `--approve` only in non-interactive contexts, which is misleading. Verified
against the pi `dist/`: when the project-trust override is set, the resolve-prompt short-circuits and
trust resolves true regardless of app mode. **Anti-pattern flag:** when pi's docs and its `dist/`
source disagree, trust the dist source.

### `--approve` is run-scoped, not persisted

`--approve` does **not** write `~/.pi/agent/trust.json` — it is run-scoped, which is exactly right for
throwaway `plan-<id>` worktrees (no trust residue accumulates). Don't reach for a persistent trust
write for ephemeral paths.

## Last-wins arg injection

pi parses args last-wins, so perk injects its default **before** `*pi_args`; a user-passed
`--no-approve`/`-na` then naturally wins with zero extra perk code. **General CLI-wrapping pattern:**
when wrapping a last-wins CLI, inject your default *before* pass-through args to leave the user an
override.

## `stage.worktree != "none"` is the canonical worktree-stage predicate

It already gates `_materialize_plan_body` — reuse it rather than enumerating stage ids. `worktree:
none` stages (objective-author/save/plan, plan, save) run in `repo_root`; create/reuse stages run in a
fresh `plan-<id>` worktree.

## The headless worker is NOT subject to this seam

`perk run-worker` spawns `node` against the worker entry and builds its session without pi-CLI arg
parsing or CLI trust resolution — so this is purely **local cold-door launch** mechanics. No
`shared/contracts.md` change accompanies the trust injection.

## A local stage launch never returns

It ends in `os.execvpe("pi", …)` — the CLI *becomes* pi, and nothing after that runs. A supervisor
**cannot** compose a *local* launch (it would never come back); landing therefore stays the
human/interactive path (see `objective-lifecycle.md`).

## Refactoring launch/run behind byte-exact pins

The node-4.3 dignified sweep of `perk/launch.py` / the run worker established three constraints:

- **`perk/cache.py` is a deliberate import-leaf** (it imports only `perk.output`), and
  `github.py` *lazily* imports `cache` for cycle avoidance — so any helper that calls *into*
  `github` cannot live in `cache.py` without creating a real import cycle. When a backlog says
  "move helper X to a shared home", check the candidate home's import posture first:
  **promote-in-place in the consumer-owning module** is the correct move when the shared home is
  a leaf. This is why the public plan-body materializer lives in `launch.py`, with the run worker
  as the documented second consumer, rather than relocated.
- **Frozen-dataclass state transitions**: keep the initial construction, then use
  `dataclasses.replace` for every subsequent status evolution — unchanged fields carry by
  construction and the persisted dicts stay byte-identical.
- **When refactoring behind exact-string test pins, the pins themselves are sufficient proof of
  behavior preservation** — zero test edits is the success signal; don't add helper-level tests.

## Composing a launcher that emits `machine_output` inside a `--json` surface

A composed cold-door launcher (e.g. the remote dispatch path `_drive_remote_target`) writes its own
dispatch JSON to stdout via `machine_output` and returns. A surface that wants a *single* unified
`--json` payload must wrap the call in `contextlib.redirect_stdout(io.StringIO())` and parse the needed
fields (e.g. `run_id`) out of the captured text — otherwise it emits **two** JSON objects and corrupts
the stream. (`user_output`→stderr is unaffected and can flow through.) **General trap:** any Python
surface nesting a command that calls `machine_output` must isolate that inner stdout.

## Testing `--json` surfaces (Click 8.4.1 gotcha)

`CliRunner(mix_stderr=False)` raises `TypeError` on Click 8.4.1 (the kwarg was dropped), and
`result.output` still **mixes** stderr + stdout. So when a command writes human lines to stderr
*before* its `--json` payload, `json.loads(result.output)` fails. Parse the **last non-empty line** of
`result.output`. (Sibling tests that `json.loads(result.output)` directly get away with it only because
those commands emit nothing to stderr ahead of the JSON.)

## Cross-references

- `perk/launch.py` — `launch_stage` argv construction + `--approve` trust injection
- `perk/cli/commands/objective_cmd.py` — the supervisor that composes the remote dispatch launcher
- `docs/learned/workflow/objective-lifecycle.md` — the supervisor design that composes these mechanics
- `docs/learned/workflow/remote-runner.md` — the remote dispatch path that emits the nested `machine_output`
