---
title: CLI startup tiers — deferred root registration, the tiered-import rule, seam extraction, and the fresh-process import matrix
read_when: You are touching perk/cli/cli.py's module-level imports, SectionedGroup's deferred registration, perk.run.pi_exec, a module move that tests monkeypatch, or tests/test_cli_import_tiers.py.
cluster: doors-and-launch
---

# CLI startup tiers

Normative homes: `shared/contracts.md` §8.72(j) (startup cost) and
`docs/design/first-principles/python-cli-guidelines.md` §8.3 (the tiered-import rule) — this doc
records the craft that made them hold and the traps that recur. Measurements are event stamps —
re-measure, never copy.

## One-unit deferred registration on the Group subclass

`perk/cli/alias.py::SectionedGroup` takes an optional `deferred_registration` hook. Hooking
`get_command`/`list_commands` is complete because:

- eager options (`--version`) exit during parsing, before any subcommand lookup;
- `invoke_without_command=True` runs the bare arm (and a lone `--`) through the group callback
  without either hook;
- `Group.resolve_command` calls `get_command` first and only then raises
  `NoSuchCommand(possibilities=…)`, so "Did you mean" comes from the populated map for free.

Idiom: clear the hook reference before invoking it, so the hook's own `add_command` calls cannot
re-enter; a group built without the kwarg is the eager group it always was. Test consequence: read
`list_commands(ctx)`/`get_command(ctx, name)`, never `group.commands` directly; zero
expected-value edits plus a before/after `--help` byte-diff is the success signal.

Deferred as ONE unit deliberately: a light subcommand still pays the whole surface (measured; gist
#2498 tracks per-group laziness). Build finer laziness only after a measurement names a light-verb
cost.

## The tiered-import lint shape

- The CLI root is the ONE source file where in-function imports are the norm (`pyproject.toml`'s
  `per-file-ignores` `PLC0415` row for `src/perk/cli/cli.py`).
- A leaf reaching a heavy dependency imports inside the function with a
  `# noqa: PLC0415 — tiered import (…)` reason; type-only heavy imports sit behind
  `if TYPE_CHECKING:` with quoted annotations.
- Fakes patching the module OBJECT keep working, because the call-time import reads the same
  module.
- `ruff check` (`F401`) is the completeness oracle for a slimmed facade.
- `perk.substrate.config` (pydantic) legitimately stays on the bare tier — it owns `[pi] agent_dir`
  and the `local.toml` key; don't chase pydantic-free config reading without a measurement.

## Move-vs-re-export policy on a seam extraction

Re-export PUBLIC names from the old home (`from x import name as name` marks the re-export for
`F401`), so consumers and test pins stay untouched. NEVER re-export the PRIVATE seams a test
patches: the extracted function reads them as its own module's globals, so a patch against the
re-export is a silent no-op — drop them from the old `__all__` so stale patches fail loudly. Patch
the module that READS the name; callers needing patchability read `pi_exec.<name>` as attributes
at call time. The general rule is `toolchain/python-package-splits.md` § name-binding patches.

## The fresh-process import matrix

`tests/test_cli_import_tiers.py` — import-tier claims are provable only in a fresh interpreter:

- **Drive**: `python -X importtime -m perk …` under a PTY, reusing the perk-dev harness
  (`spawn_pty` + `parse_importtime`) rather than a second driver; hermetic env — a `pi` stub first
  on `PATH`, scratch `HOME`, `PI_CODING_AGENT_DIR` set, `PERK_SKIP_VERSION_CHECK=1`,
  `PERK_RUN_ID`/`PERK_PROFILE_HANDOFF` stripped. `PERK_PROFILE_HANDOFF=<file>` proves the bare arm
  reached `exec_pi` without exec'ing.
- **Assert by module prefix.** `perk.cli.cli` present is the parse floor (an empty module set is a
  capture failure, never a pass); `--help` is the positive control (it loads the whole surface —
  every heavy prefix must appear).
- **Tier the forbidden sets to the tiers**: a strictly lighter row (`--version`) needs its own
  stricter set, with the next-heavier row asserting those prefixes present. "Reads no registry" is
  proven by the absence of the root-level registry readers.
- **Mutation proof at implementation time**: plant a heavy import at the top of `cli.py` → the
  `--version` row fails; revert. Every row is `@pytest.mark.slow` and PTY-bound.

## Import-direction source guards must be AST-based

Once function-local imports are the sanctioned mechanism, a `startswith`/indentation-sensitive
textual import scan has a hole exactly where the regression lands. Walk the AST (`ast.walk` over
`Import`/`ImportFrom`), record `node.module` AND `f"{module}.{alias}"` (a submodule-binding
`from x import y`), and ship a scanner self-test on a synthetic nested-import source
(`tests/test_session_resume.py`'s `pi_exec` direction guard is the precedent). A textual import
scan is a reviewable smell (`source-scan-guards.md` § "Import-graph guard vacuity holes").

## Residual risks (dated, at landing)

- Light subcommands still import the whole surface (~490 ms over `--version` at the #2500
  measurement — re-measure, never copy).
- A module-level heavy import added to a callback-arm target (e.g. `perk/cli/plain_session.py`) is
  caught only by the matrix's bare row.
- `launch.__all__` still exports `exec_pi`/`LaunchAgentDir`/`resolve_launch_agent_dir` for the
  staged path's adapter, so patching `launch.exec_pi` works for the staged path only — the plain and
  resume paths patch `pi_exec`.

## Cross-references

- `perk/cli/cli.py`, `perk/cli/alias.py`, `perk/cli/context.py`, `perk/run/pi_exec.py`,
  `tests/test_cli_import_tiers.py`
- `docs/learned/workflow/startup-profiling.md` — the measurement instrument
- `docs/learned/workflow/cli-command-groups.md` — the root-level bare launch (Playbook 2)
- `docs/learned/workflow/cold-door-launch.md` — the one Pi exec pipeline
- `docs/learned/toolchain/python-package-splits.md` — name-binding patches across a move
