---
title: Python CLI command groups — the §8.1 group-dir template, hybrid stage/group coexistence, sectioned help
read_when: You are adding/folding a `perk` CLI command group, resolving a stage-launcher/group name collision, touching the sectioned root `--help` taxonomy, consolidating per-group helpers, or running a structural CLI refactor and want the parity smoke + test patterns.
---

# CLI command groups

The perk CLI's command surface is organized as group directories under `perk/cli/commands/` with a
sectioned root help. This doc is the structure playbook: the group-dir template, the hybrid
default-dispatch recipe for stage-name/group collisions, byte-compat discipline across folds, the
help taxonomy, and the test patterns that made the migrations cheap. Realized shapes to copy:
`perk/cli/commands/objective/`, `perk/cli/commands/pr/`, `perk/cli/commands/learn/`.

## The §8.1 group-dir template

- `commands/{group}/__init__.py` carries: the design docstring (the original module's design prose),
  the `AliasGroup` group def, top-of-file imports of the verb commands, and one
  `register_with_aliases(group, verb)` call per verb at the bottom.
- Verb files are standalone `@click.command("name")` defs (never `@group.command(...)` decorators)
  named `{verb}_{noun}` (e.g. `submit_pr`), with a one-line docstring naming the command.
- Verb-local helpers move with the verb and keep their `_` prefix. Cross-verb helpers go in
  `{group}/shared.py` and **drop the leading underscore** — intentional intra-package API
  (`fail()`, `EXIT_FOR_TYPE`, etc.).
- Each group keeps its **own `fail()` copy**; groups copy, never import, another group's
  `shared.py`. Cross-group consolidation is deliberately deferred.
- Nested groups nest dirs and follow the same pattern recursively (`workflow/run/`,
  `doctor/workflow/`).

## Dissolving Click registration cycles via a sibling render module

When a subgroup needs the parent's helpers, the import cycle is **helper-induced, not
registration-induced** — extract the shared helpers into a sibling leaf module (the
`perk/cli/commands/doctor/render.py` pattern) so both `__init__.py`s import top-of-file normally.
Prefer this over the bottom-of-file `# noqa: E402` import idiom whenever shared helpers cause the
cycle; bottom-of-file imports remain only for genuinely registration-induced cycles (see
`workflow/init-doctor.md`).

## The hybrid default-dispatch group recipe (Click 8.4.x)

When a stage launcher and a command group want the same name (`perk learn` launches the learn stage
AND `perk learn capture|docs` are verbs), the coexistence template is
`perk/cli/commands/learn/__init__.py` (`LearnGroup`):

- Group `context_settings={"ignore_unknown_options": True}` so launcher options (`--worktree`,
  `--dry-run`, `--remote`, pi-args) survive group-level parsing and reach `resolve_command` intact.
- A `parse_args` override: empty args → substitute the hidden launcher name (guard
  `ctx.resilient_parsing` for shell completion, and only when the launcher actually registered).
  This makes bare `perk learn` launch instead of printing group help.
- A `resolve_command` override: if `args[0]` is a registered verb, defer to `super()`; otherwise
  route to the launcher with **ALL args preserved** — Click's default convention strips `args[0]`;
  don't.
- `--help` needs no special diversion: it's a known eager option consumed during the group's own
  parse (even with `ignore_unknown_options`), so group help renders before `resolve_command` runs.
- The hidden launcher comes from the public `make_stage_launcher(stage)` in `perk/cli/stages.py`,
  registered via `add_command` with `hidden = True`, and the stage joins `DEDICATED_STAGES` so the
  generic launcher generator skips it.

This is the template for any future stage-name/group collision.

## Byte-identical JSON across a group migration

Folds must keep JSON shapes, `error_type`s, and exit codes byte-identical:

- The consolidated per-group `shared.py` `fail(..., extra=)` signature preserves exact key order by
  merging `extra` **after** the base keys. Dry-run-capable verbs pass `extra={"dry_run": False}` on
  every failure path.
- When a plan asserts "X is the only divergence" among N near-identical private helpers, **re-grep
  all N bodies before consolidating** — the pr fold found *five of eight* `_fail` copies carried
  `"dry_run": False` (exactly the dry-run-capable verbs), not the one the plan claimed.

## Sectioned root help (`SectionedGroup`)

- `SectionedGroup(AliasGroup)` in `perk/cli/alias.py` is **root-only**: extend-don't-replace keeps
  existing `isinstance(cli, AliasGroup)` assertions green; subgroups stay plain `AliasGroup`. Cheap
  lock: assert `isinstance(cli, SectionedGroup)` for root and the negative for subgroups.
- The `Hidden` section is env-gated default-off — `PERK_SHOW_HIDDEN` with the same truthiness shape
  as `PERK_RUN_ID` (`not in (None, "", "0")`); the section is omitted entirely when empty or when
  the flag is off.
- Help-taxonomy upkeep when adding a group is two lines: `COMMAND_GROUPS` in `perk/cli/alias.py` +
  the groups-section test.

## Testing patterns for CLI structure work

- **Help-slice tests must match the rendered row** (`"objective (obj)"`, `"worktree (wt)"`), never a
  bare-name substring — `objective-author`/`objective-plan`/`objective-save` all contain
  `"objective"` and false-positive a slice assertion.
- **Drift guard:** a regression test walks the live root surface (non-alias, non-hidden) and asserts
  the curated section lists (a) resolve to live commands, (b) are pairwise disjoint, (c) union with
  the `Other` catch-all to the full visible set — catches a new command added without classification.
- **Behavior-parity smoke (~30 seconds) for structural refactors:** dump `--help` for the root and
  every (sub)group via `CliRunner` in both the worktree and main, then diff. Rendering depends only
  on registration, so identical help ⇒ identical command/alias surface. For renaming folds the diff
  should show exactly the planned renames and nothing else.
- **Keep tests driving through the `cli` object** unless they genuinely unit-test a helper — only
  three test files imported command modules directly, which made the six-group migration cheap.
- When renaming a module used in `monkeypatch.setattr(module, ...)`, grep the **bare module name**,
  not just `module.` — a sed rewrite on `module.` misses the no-trailing-dot usage.
- Test files keep their flat names across folds — only invocations and monkeypatch import paths
  change (`perk.cli.commands.pr_X_cmd` → `perk.cli.commands.pr.X_cmd`).

## Mechanical-migration gotchas

- Bash `case` patterns containing spaces must be **quoted** (`"pr submit")`, not `pr submit)` —
  syntax error). The `fakePerkRouter` in `extension/testing/harness.ts` now handles two-token route
  keys generically; new groups only update route keys in tests.
- `git mv` then edit preserves rename detection and blame across a group-dir migration.
- Pre-commit ruff hooks can fail the **first** commit attempt after mechanical string widening
  (line-length overflow; the format hook auto-fixes then reports failure) — re-stage and re-commit,
  don't pre-wrap manually.

## Warm-plane ids are decoupled from cold spellings

A CLI regrouping does not ripple into the warm plane: `/learn-docs`, `command:learn-docs`,
deliverable command targets, and inbox artifact paths/headers all survive a cold rename untouched —
only the `pi.exec` argv arrays in the extension change.

## Residuals

- `docs/guiding-principles/python-cli-guidelines.md` reconciliation against the grouped surface is
  deliberately deferred (a dedicated doc-reconciliation node owns it) — don't "fix" opportunistically.
- Cosmetic asymmetry: `learn capture`'s human dry-run line was respelled to the grouped form, but
  `learn docs`' human gather/dry-run label still prints the old `learn-docs {label}` spelling
  (harmless stderr human text; a future polish pass could align it).

## Cross-references

- `perk/cli/commands/objective/`, `perk/cli/commands/pr/` — realized group-dir shapes
- `perk/cli/commands/learn/__init__.py` — `LearnGroup`, the hybrid default-dispatch template
- `perk/cli/alias.py` — `AliasGroup`, `SectionedGroup`, `COMMAND_GROUPS`, `register_with_aliases`
- `perk/cli/stages.py` — `make_stage_launcher`, `DEDICATED_STAGES`
- `docs/learned/workflow/init-doctor.md` — the bottom-of-file-imports idiom this doc supersedes for
  helper-induced cycles
