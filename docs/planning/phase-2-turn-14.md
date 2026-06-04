# Phase 2 · Turn 14 — erk-style command aliases across the perk CLI

> The decision-complete plan lives on GitHub plan **#31** (`plan-body` block). This doc records the
> prior-art pass, the decisions, and — written **after** it lands — the as-built **outcomes**. A
> small **CLI-surface turn**: no spine/registry/cross-plane change, just invocation sugar.

## 1. Problem

Every perk command is reachable only by its full name (`perk worktree list`, `perk implement`,
`perk registry check`). There is no alias mechanism (`grep -i alias perk/**/*.py` was empty), so
the day-to-day CLI is verbose compared with erk's `wt ls` / `impl` / `reg ch` ergonomics.

## 2. Prior-art pass (erk, `.prior-art/erk/`)

erk's alias system is two small modules in `erk-shared`:

- `cli_alias.py` — `@alias(*names)` stashes names on the `Command` (attr `_erk_aliases`),
  `get_aliases`, and `register_with_aliases(group, cmd)` which adds the **same Command object**
  under its primary name and every alias. Resolution is then free — Click's resolver finds the
  command under any registered name. **erk does not override `get_command`.**
- `cli_group.py` (`ErkCommandGroup`) — a `click.Group` whose `format_commands` lists each command
  once as `primary (alias, …)` and skips alias names as standalone rows. erk's class also does
  section taxonomy, hidden-command handling, and Graphite gating — perk needs none of that.

## 3. Decisions

- **One cohesive module `perk/cli/alias.py`** (perk has no shared CLI package): `ALIAS_ATTR`
  (`_perk_aliases`), `alias`, `get_aliases`, `register_with_aliases`, and `AliasGroup` (overrides
  only `format_commands`, single flat `Commands` section — perk's help is flat).
- **`@alias` above `@click.command`** (decorators apply bottom-up). Subgroup subcommands are
  defined as module-level `@click.command` + `@alias` and registered via `register_with_aliases`
  (erk's pattern — alias registration in one place), preserving every existing option/argument.
- **Alias table** (final, collision-audited against the live surface): groups `worktree→wt`,
  `objective→obj`, `registry→reg`, `state→st`; top-level `implement→impl`, `objective-plan→oplan`,
  `resume→res`, `learn-capture→lc`, `plan-save→psave`; worktree `create→new`/`list→ls`/`remove→rm`;
  objective `create→new`/`show→s`/`next→n`/`reconcile→rec` (`node` unaliased — too close to `next`);
  registry `check→ch`/`show→s`; state `new-run→nr`/`show→s`.

## 4. Deliberately out of scope (flagged, not silently omitted)

- **`pr-*` family stays unaliased.** Faithful erk adoption would regroup these into a `pr` group
  (`pr submit`/`pr land`/…); cryptic flat prefixes are poor UX. Follow-up: a `pr`-group restructure.
- **Stage launchers (`plan`/`save`/`submit`/`address`/`land`/`learn`) stay unaliased** — already
  short single words; erk does not alias the analogous verbs. (`register_stage_commands` could grow
  a `_STAGE_ALIASES` map later.)
- **`init`/`doctor` stay unaliased** — no natural unambiguous short form.

## 5. Cross-plane / contract impact

**None.** Aliases are CLI-surface sugar: the extension never shells `perk` for these, and the
stage registry / graph is untouched. No `shared/contracts.md` amendment needed.

## 6. Verification

Regression coverage lives in pytest (the retired `scripts/verify-*.sh` convention, #33):
`tests/test_cli_aliases.py` asserts aliases resolve to the same Command object, behavioral
equivalence (`perk wt ls` ≡ `worktree list`), and `--help` dedup into the parenthetical. Gated by
`just test` / `just ci` (stays green).

## 7. Outcomes (as-built)

- Shipped exactly as planned: `perk/cli/alias.py` + `@alias`/`AliasGroup` wiring on the root group
  and the four subgroups, with `register_with_aliases` registering each aliased command.
- **Rebased onto #33** mid-flight, which retired the `scripts/verify-*.sh` convention. Dropped the
  originally-authored `scripts/verify-p2-t14.sh`; the equivalent checks live entirely in
  `tests/test_cli_aliases.py` (the new pytest-based regression discipline).
- `AliasGroup.format_commands` collects alias names into a `set` and skips them as standalone rows
  (the alias→primary map value is unused, so a set is clearer than erk's dict).
- Tests: new `tests/test_cli_aliases.py` — a table-driven `_walk(cli)` guard asserts every declared
  alias registers the **same Command object** as its primary (collision/typo guard), plus
  behavioral-equivalence and help-dedup spot checks. `test_all_stages_are_generated` stayed green
  (stage launchers untouched).
- No deviations from the plan; no contract change.
