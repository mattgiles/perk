# Python CLI guidelines (Click)

perk's CLI — the session *exterior* (see [cli-vs-pi.md](./cli-vs-pi.md)) — is built with
**[Click](https://click.palletsprojects.com/)**. These are the conventions every `perk`
command follows. They are distilled from the erk prior-art
(`.prior-art/erk/docs/learned/cli/*`, `.prior-art/erk/docs/learned/architecture/click-*`),
which paid for them in production.

> Status: **fully implemented + converged** (Objective #225). Live today: `perk/cli/`
> (the root `SectionedGroup` + registry-generated stage launchers, `perk/cli/stages.py`),
> `perk/cli/context.py` (`PerkContext` + `require_repo`/`require_config`/`require_github`),
> `perk/cli/ensure.py` (`UserFacingCliError` + `Ensure`), and `perk/output.py`
> (`user_output`/`machine_output`/`user_confirm`). Tooling is uv-only on Python 3.13 (see
> the repo `justfile`). The detailed structure playbook for group work is
> [docs/learned/workflow/cli-command-groups.md](../learned/workflow/cli-command-groups.md).

---

## 1. Layers: decorator → DI helper → implementation

Every command is three layers. The Click decorator is a thin shell; the business logic is a
Click-free function that takes typed dependencies.

```python
# perk/cli/commands/pr/submit_cmd.py (abridged — the real shipped shape)
import click
from perk.cli.context import require_github, require_repo

@click.command("submit")
@click.option("--dry-run", is_flag=True, help="Compose the plan without pushing or hitting GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def submit_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Open a draft PR for the active plan's branch (the implement → submit boundary)."""
    repo_root = require_repo(ctx)
    if not dry_run:
        require_github(ctx)
    result = _pr_submit_impl(repo_root=repo_root, dry_run=dry_run)
    ...  # render result (human or --json)


def _pr_submit_impl(*, repo_root: Path, dry_run: bool) -> PrSubmitResult:
    """Pure logic. No Click — trivially testable."""
    ...
```

Rules:
- **Keep `@click.command` callbacks tiny**: resolve dependencies, then call `_impl(...)`.
- **`_impl` takes keyword-only typed args** (`*,`) — never a `click.Context`. This is what
  makes logic testable without Click.
- **Star-args everywhere** (`def cmd(ctx, *, ...)`) so option order never matters.

---

## 2. Dependency injection via the Click context

Shared dependencies hang off `ctx.obj` as a **lazily-resolved `PerkContext`**
(`perk/cli/context.py`), accessed through **typed `require_*()` helpers** — never
`ctx.obj.foo` directly. Exactly three helpers exist:

```python
# perk/cli/context.py (abridged)
def _perk(ctx: click.Context) -> PerkContext:
    if not isinstance(ctx.obj, PerkContext):
        raise UserFacingCliError("internal error: CLI context not initialized")
    return ctx.obj


def require_repo(ctx: click.Context) -> Path:
    """The git repo root for this invocation (narrowed + checked)."""
    return _perk(ctx).repo_root()


def require_config(ctx: click.Context) -> Config:
    """The loaded perk config for this invocation."""
    return _perk(ctx).config()


def require_github(ctx: click.Context) -> AuthStatus:
    """Strict GitHub binding for commands that *need* a working GitHub."""
    ...
```

- The root group constructs `PerkContext` **cheaply** (cwd only), so non-repo commands
  (`--version`, `init`, `registry`, `state`) work outside a git repo. `repo_root()` and
  `config()` resolve and cache lazily; a missing dependency raises a clean
  `UserFacingCliError` (with a stable `error_type`, see §5) instead of an `AttributeError`
  deep in a command.
- **`require_repo` *is* the git binding.** git operations are stateless module functions
  over the repo root (`perk/git.py`), so there is no `require_git`/`require_cwd`.
- **`require_github` is strict** — it returns an `AuthStatus` and raises when `gh` isn't
  authenticated. `init`/`doctor` instead call `github.check_*` directly to *report*
  (non-fatally). The GitHub gateway itself is module functions in `perk/github.py`, not a
  context-carried object.
- The `_perk()` isinstance-narrowing helper gives **type narrowing** + **clear errors**;
  the house decorator is `@click.pass_context` + `require_*` (not `@click.pass_obj`).
- `PerkContext.for_test(...)` injects fakes (see §9).

*(Source: `architecture/click-context-di-pattern.md`.)*

---

## 3. Options & flags

### 3.1 The three-state rule for value options

Optional value options are three-state so you can tell **omitted** from **explicitly set**:

| Value    | Meaning             | CLI            |
| -------- | ------------------- | -------------- |
| `None`   | not provided        | (omitted)      |
| `""`     | explicitly cleared  | `--plan ""`    |
| `"#123"` | explicitly set      | `--plan "#123"`|

The rule is about *semantics*, not spelling: `None` **is already Click's default**, so do
**not** write `default=None` explicitly (that's redundant noise — §3.2; the convergence
sweep stripped ~24 of them). The one exception is the §3.4 optional-value quartet, which
keeps the full explicit spelling because the four parameters only make sense together.

### 3.2 Omit redundant defaults

Click already defaults options to `required=False, default=None`. Don't restate them.

```python
# WRONG — noise
@click.option("--status", required=False, default=None, type=click.Choice([...]))
# RIGHT
@click.option("--status", type=click.Choice([...]))
```

Spell out only the **non-default** case: `required=True`, or a real non-None `default="text"`.

### 3.3 `is_flag` carve-out

Boolean flags are two-state and exempt from the three-state rule — `is_flag=True` carries
an implicit `default=False`, which is correct:

```python
@click.option("-f", "--force", is_flag=True, help="Skip confirmation.")
```

### 3.4 Optional-value flags

A flag that works both bare and with a value (the shipped example is the stage launchers'
`--remote`, `perk/cli/stages.py` `make_stage_launcher`):

```python
@click.option(
    "--remote", type=str, default=None, is_flag=False, flag_value="",
    help="Local (default) or a remote runner (dispatch the stage to CI).",
)
# absent -> None ; "--remote" -> "" (use default runner) ; "--remote ci-large" -> "ci-large"
```

This quartet keeps the explicit `default=None` spelling — the four parameters are a unit.

### 3.5 Keep `IntRange` in sync

When an interactive menu grows, bump the bound (`click.IntRange(1, 3)` → `(1, 4)`), or the
new choice is rejected at parse time. (Current reality: perk has no interactive `IntRange`
menus; the one shipped `IntRange` is `workflow run list --limit`, `IntRange(min=1)` — the
rule stands for when a menu arrives.)

*(Source: `cli/click-framework-conventions.md`, `cli/click-patterns.md`.)*

---

## 4. Validation: two tiers

Validate at the layer where the constraint *originates*.

**Tier 1 — API-shape constraints → Click types** (fail fast at parse time):

```python
@click.option("--config", type=click.Path(exists=True, path_type=Path))
@click.option("--format", type=click.Choice(["json", "text"]))
@click.option("--timeout", type=click.IntRange(1, 3600))
```

**Tier 2 — domain/state constraints → runtime `Ensure.*`** (after parse, with context):

```python
from perk.cli.ensure import Ensure

Ensure.not_empty(name, "Worktree name cannot be empty.")
Ensure.path_exists(path, f"Plan cache not found: {path}")
Ensure.invariant("/" not in name, f"Invalid name '{name}' — no path separators.")
plan = Ensure.not_none(lookup_plan(ref), f"No plan found for {ref}.")  # narrows T | None -> T
```

- **Never validate the same constraint at both tiers** — pick one path.
- `Ensure.*` is LBYL (Look Before You Leap): precondition checks at function entry, each with
  a specific, actionable message. Prefer simple sequential checks over a validation framework.
- `Ensure.not_none` / `Ensure.truthy` return the narrowed value, so they double as extractors.

*(Source: `cli/cli-options-validation.md`.)*

---

## 5. Errors

### 5.1 Exception type signals intent

- **`UserFacingCliError`** (extends `click.ClickException`) — for **expected** failures a user
  can trigger (missing file, bad input, precondition violation). Click intercepts it at every
  level, prints `Error: …` in red, exits 1. No stack trace.
- **`RuntimeError`** — only for **impossible states / bugs**. If a user can reach it through
  normal usage, it's a `UserFacingCliError`, not a `RuntimeError`.

```python
from perk.cli.ensure import UserFacingCliError

# precondition at entry  -> Ensure (raises UserFacingCliError internally)
Ensure.invariant(repo.has_github, "Not a GitHub repository.")

# mid-function failure (e.g. consuming a discriminated-union error) -> raise directly
result = github.create_pr(...)
if isinstance(result, GitHubError):
    raise UserFacingCliError(result.message)
```

`Ensure` is for entry preconditions; `UserFacingCliError` is for failures discovered during
execution. Both produce identical styled output and exit code 1.

### 5.2 Stable error codes (`error_type`)

`UserFacingCliError(message, *, error_type=...)` carries an optional **stable error code**
(`perk/cli/ensure.py`) for the machine surface (§8.2): on a `--json` failure path the code
lands in the `{success: false, error_type, message}` payload, and the per-group exit-code
map (`EXIT_FOR_TYPE` in the group's `shared.py`) maps codes to stable exit codes (e.g.
`not_a_repo` → 2). Human output ignores it. Pick short snake_case codes
(`no_plan_ref`, `github_unauthed`, `dirty_tree`) and keep them stable — supervisors branch
on them.

### 5.3 Message format

- **Action-oriented, specific, concise.** Tell the user what's wrong *and* what to do.
- **No `"Error: "` prefix** — the framework adds it.
- **Multi-line** = primary line, single `\n`, remediation line. **Never `\n\n`** (the error
  formatter handles spacing).

```python
raise UserFacingCliError(
    "No .pi/workflow/ cache found in this repo\n"
    "Run 'perk init' to scaffold it.",
    error_type="not_initialized",
)
```

| Good | Bad |
| --- | --- |
| `"Plan #123 not found — run 'perk plan list' to see open plans"` | `"Error: not found"` |
| `"Branch 'main' has uncommitted changes — commit or stash first"` | `"dirty worktree"` |

*(Source: `cli/error-handling-antipatterns.md`, `cli/output-styling.md`.)*

---

## 6. Help text: the `\b` rule

Click rewraps consecutive lines into paragraphs, which **destroys** lists, code, and tables.
Put `\b` on its **own line** before any structural block; everything until the next blank line
is preserved verbatim.

```python
@click.command("submit")
@click.pass_context
def submit_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Open a draft PR for the active plan's branch (the implement → submit boundary).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
```

- Use `\b` before bulleted/numbered lists and code/example blocks.
- Do **not** use `\b` for normal prose (let Click wrap it responsively).
- Click takes the **first paragraph** as the short help shown in group listings — compose
  help as `summary + blank line + long detail` to enrich `--help` bodies without churning
  listing rows (`get_short_help_str()` only reads the first paragraph).
- Verify: `perk <cmd> --help` — if examples collapse onto one line, `\b` is missing.

*(Source: `cli/help-text-formatting.md`.)*

---

## 7. Output: human vs machine, and styling

### 7.1 Two streams

- **`user_output()` → stderr** — all human-facing text: status, progress, errors, success.
- **`machine_output()` → stdout** — script/structured data: JSON, paths for capture, shell
  activation scripts.

This split lets a supervisor parse stdout while progress flows to stderr uncorrupted.

```python
from perk.output import user_output, machine_output

user_output(click.style("✓ ", fg="green") + f"Saved plan {plan_id}")
machine_output(json.dumps(result))
```

### 7.2 Color & emoji conventions

Use `click.style(...)` consistently:

| Element | Style |
| --- | --- |
| branch names | `fg="yellow"` |
| PR numbers | `fg="cyan"` |
| success (`✓`) | `fg="green"` |
| errors | `fg="red"` |
| section headers | `bold=True` |
| dry-run / metadata | `dim=True` / `fg="bright_black"` |

Standard emoji: `✓` success, `❌` error, `📋` plans/lists, `ℹ️` info, `⭕` aborted. Progress
output goes to **stderr** with consistent prefixes; indent details under their action.

### 7.3 Rich tables

> **Status: not yet adopted.** `rich` is **not a perk dependency** (pyproject pins click,
> python-ulid, pyyaml) and nothing currently renders a table —
> `commands/worktree/__init__.py` explicitly defers tables "until a real dashboard". This
> section is forward guidance for that future; don't add the dependency for a one-off list.

For tabular output use Rich tables (not f-string width specifiers — emoji are 2 cells wide and
break fixed widths):

```python
from rich.console import Console
from rich.table import Table
from rich.markup import escape as escape_markup

table = Table(show_header=True, header_style="bold")
table.add_column("plan", style="cyan", no_wrap=True)
table.add_column("title", no_wrap=True)
table.add_row(f"#{plan_id}", escape_markup(title))   # ALWAYS escape user text
Console(stderr=True, width=200).print(table)
```

- **`escape_markup()` every user-provided string** — `[text]` is parsed as a Rich tag and
  vanishes otherwise.
- Lowercase, abbreviated headers (`plan`, `pr`, `chks`, `st`, `wt`); identifier column first,
  location last.
- Clickable IDs via Rich markup `[link=URL]#123[/link]` (or OSC 8 for plain `click.echo`).

### 7.4 Confirmations

Never call raw `click.confirm()` after `user_output()` (stderr isn't flushed → hang). Use
`user_confirm()` (`perk/output.py`), which flushes stderr first and prompts on stderr —
`init.py`'s re-seed prompt is the shipped consumer:

```python
from perk.output import user_confirm

user_output("This is destructive.")
if user_confirm("Proceed?", default=False):
    ...
```

*(Source: `cli/output-styling.md`.)*

---

## 8. Command groups & the machine surface

> The detailed playbook (folds, byte-compat discipline, the parity smoke, test patterns) is
> [docs/learned/workflow/cli-command-groups.md](../learned/workflow/cli-command-groups.md).

### 8.1 Structure & naming

Command **groups are directories**; top-level commands stay flat single files:

```
perk/cli/commands/
├── __init__.py            # package docstring documents this layout
├── pr/                    # a command group
│   ├── __init__.py        # design docstring + AliasGroup def + register_with_aliases calls
│   ├── submit_cmd.py      # {verb}_cmd.py — standalone @click.command def
│   ├── land_cmd.py
│   └── shared.py          # cross-verb helpers (fail(), exit-code map)
├── learn/                 # hybrid stage/group (LearnGroup, see below)
├── doctor/
│   ├── __init__.py
│   ├── render.py          # sibling helper module (dissolves an import cycle)
│   └── workflow/          # nested groups nest dirs
├── workflow/
│   └── run/
└── plan_save_cmd.py       # top-level command: flat {name}_cmd.py
```

| Element | Pattern | Example |
| --- | --- | --- |
| group dir | `{group}/` | `pr/` |
| command file | `{verb}_cmd.py` | `submit_cmd.py` |
| command function | `{verb}_{noun}` | `submit_pr` |

- `{group}/__init__.py` carries the design docstring, the `AliasGroup` group def,
  top-of-file imports of the verb commands, and one `register_with_aliases(group, verb)`
  call per verb at the bottom.
- Verb files define **standalone `@click.command("name")` commands** (never
  `@group.command(...)` decorators). Verb-local helpers keep their `_` prefix; cross-verb
  helpers go in `{group}/shared.py` and drop the underscore (intentional intra-package
  API). Each group keeps its **own `fail()` copy** — groups copy, never import, another
  group's `shared.py`.
- When a subgroup needs the parent's helpers, extract them into a **sibling leaf module**
  (the `doctor/render.py` pattern) rather than bottom-of-file imports — helper-induced
  cycles dissolve; registration-induced ones don't arise from this layout.

**Registration & help rendering** (`perk/cli/alias.py`): subgroups are `AliasGroup`
(renders each command once as `primary (alias, …)`); the **root group only** is
`SectionedGroup`, which renders curated sections — *Stage Launchers / Command Groups /
Setup & Health / Other* (catch-all) / *Hidden* (env-gated by `PERK_SHOW_HIDDEN`).
`register_with_aliases` registers the same `Command` object under its primary name and
every `@alias(...)` name, so resolution is free.

**Stage launchers are generated from the stage registry** (`perk/cli/stages.py`): the
registry is the source of truth for which `perk <stage>` commands exist;
`make_stage_launcher(stage)` builds each one mechanically, and `DEDICATED_STAGES` lists
the stages with a hand-written command the generator must skip. When a stage launcher and
a command group want the **same name**, use the hybrid default-dispatch group
(`commands/learn/__init__.py`, `LearnGroup`): bare `perk learn` routes to a hidden
launcher, `perk learn capture|docs` dispatch to verbs — that file is the template.

### 8.2 The machine surface (perk-specific)

erk made *every* command dual-surface (`--json`, `schema`, MCP) so Claude could consume the
CLI as a tool. **perk does not** rebuild a `schema`/MCP **agent affordance** — the agent
uses extension tools natively ([cli-vs-pi.md](./cli-vs-pi.md) §3.2). What ships instead:

- **`--json` + stable exit codes + `{success, error_type, message}` on every cold
  worker/door** — the pr/learn/objective verbs, `plan-save`, `run-worker`, `replan`,
  registry/state/doctor, the stage launchers, `workflow run`, `init`. The consumers are
  (a) the **supervisor/headless drivers** and (b) the **extension's `pi.exec` delegation**
  (the warm in-session tools shell the cold workers and parse their JSON). Both are
  *machines that launch perk* — the cli-vs-pi §3.2 principle stands unchanged: the agent
  never reads `--json` mid-turn.
- Failure paths go through the per-group `shared.py` `fail(ctx, as_json=..., error_type=...,
  message=..., extra=...)`, which emits the failure JSON (or styled stderr text) and exits
  via the group's exit-code map (`EXIT_FOR_TYPE`).
- The shipped logic split is §1's: transport-independent logic in `_impl(*, ...)`, with the
  callback rendering either surface. *(The erk `*_operation.py` module pattern —
  a dedicated transport-independent module per dual-surface command — was **not adopted**;
  it remains forward guidance if a command's `_impl` ever needs to be shared across
  transports beyond human/`--json`.)*

*(Source: `cli/json-command-decorator.md`, reconciled with `cli-vs-pi.md`.)*

---

## 9. Testing

Use Click's `CliRunner` with an injected test context; assert on exit codes and output.

```python
from pathlib import Path
from click.testing import CliRunner
from perk.cli.context import PerkContext

def test_submit_outside_repo_fails():
    runner = CliRunner()
    result = runner.invoke(
        submit_pr, ["--json"],
        obj=PerkContext.for_test(cwd=Path("/r"), repo_root=None),
    )
    assert result.exit_code == 2  # not_a_repo

def test_invalid_limit_rejected():
    result = CliRunner().invoke(cmd, ["--limit", "0"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output   # Click parse-time error
```

- Inject fakes via `PerkContext.for_test(*, cwd=..., repo_root=..., config=...)` — it marks
  the repo as resolved, so `require_repo` returns the injected root (or raises cleanly when
  `repo_root=None`) without shelling git. The three-layer split (§1) means most logic is
  tested directly on `_impl(...)` without Click at all.
- Test **both** paths: success and each validation failure (with its message).
- `UserFacingCliError` surfaces through `CliRunner` exactly as in production (styled, exit 1).
- For **structure** work (groups, aliases, the sectioned help) reuse the shipped patterns:
  `tests/test_cli_help_sections.py` (the taxonomy drift guard) and
  `tests/test_cli_aliases.py`; prefer driving tests through the `cli` object over importing
  command modules directly.

*(Source: `testing/cli-testing.md`, `cli/cli-options-validation.md`.)*

---

## 10. Checklists

**Adding an option**
1. Value option → three-state semantics, no explicit `default=None` (§3.1/§3.2); flag →
   `is_flag=True`; bare-or-value flag → the §3.4 quartet (explicit spelling).
2. Omit redundant `required=False`/`default=None`.
3. API-shape constraint → Click type; domain constraint → `Ensure.*` (one tier only).
4. Help string ends with a period; add `\b` if it includes a list/example.
5. Add/extend a test for the new behavior.

**Adding a command**
1. Group verb → `perk/cli/commands/{group}/{verb}_cmd.py`, function `{verb}_{noun}`,
   standalone `@click.command`; top-level command → flat `{name}_cmd.py`.
2. Thin callback → `require_*()` → `_impl(*, ...)`.
3. Register via `register_with_aliases` in the group `__init__.py`; new groups also join
   `COMMAND_GROUPS` in `perk/cli/alias.py` (+ the help-sections test).
4. Human output via `user_output`; `--json` + `error_type`/exit codes if it's a cold
   worker/door (§8.2), failing through the group's `shared.py` `fail()`.
5. Errors via `Ensure`/`UserFacingCliError` (with a stable `error_type` on machine-relevant
   failures), never `RuntimeError` for user errors.
6. Test in flat `tests/test_*.py` with `CliRunner` + `PerkContext.for_test`.
