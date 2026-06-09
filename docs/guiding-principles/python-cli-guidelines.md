# Python CLI guidelines (Click)

perk's CLI — the session *exterior* (see [cli-vs-pi.md](./cli-vs-pi.md)) — is built with
**[Click](https://click.palletsprojects.com/)**. These are the conventions every `perk`
command follows. They are distilled from the erk prior-art
(`.prior-art/erk/docs/learned/cli/*`, `.prior-art/erk/docs/learned/architecture/click-*`),
which paid for them in production.

> Status: **implemented.** perk's CLI was migrated from the T1 `argparse` scaffold to Click.
> Live today: `perk/cli/` (the root group + `init`), `perk/cli/ensure.py`
> (`UserFacingCliError` + `Ensure`), and `perk/output.py` (`user_output`/`machine_output`/
> `user_confirm`). The DI context (`PerkContext` + `require_*()`, §2/§9) lands with the first
> command that takes a git/GitHub dependency; no current command needs it. Tooling is uv-only
> on Python 3.13 (see the repo `justfile`).

---

## 1. Layers: decorator → DI helper → implementation

Every command is three layers. The Click decorator is a thin shell; the business logic is a
Click-free function that takes typed dependencies.

```python
# perk/cli/commands/plan/save_cmd.py
import click
from perk.cli.context import require_github, PerkContext

@click.command("save")
@click.option("--plan", default=None, help="Plan ref to save (omit to infer from branch).")
@click.pass_context
def save_plan(ctx: click.Context, *, plan: str | None) -> None:
    """Save the current plan to its canonical store."""
    github = require_github(ctx)
    _save_plan_impl(github=github, plan=plan)


def _save_plan_impl(*, github: GitHubGateway, plan: str | None) -> None:
    """Pure logic. No Click, no I/O framework — trivially testable."""
    ...
```

Rules:
- **Keep `@click.command` callbacks tiny**: resolve dependencies, then call `_impl(...)`.
- **`_impl` takes keyword-only typed args** (`*,`) — never a `click.Context`. This is what
  makes logic testable without Click.
- **Star-args everywhere** (`def cmd(ctx, *, ...)`) so option order never matters.

---

## 2. Dependency injection via the Click context

Shared dependencies (the GitHub gateway, git, cwd, config) hang off `ctx.obj`, accessed
through **typed `require_*()` helpers** — never `ctx.obj.foo` directly.

```python
# perk/cli/context.py
def require_github(ctx: click.Context) -> GitHubGateway:
    """Extract the GitHub gateway from the Click context, narrowed and checked."""
    if ctx.obj is None:
        click.echo("Error: context not initialized", err=True)
        raise SystemExit(1)
    if not isinstance(ctx.obj, PerkContext):
        click.echo("Error: context must be PerkContext", err=True)
        raise SystemExit(1)
    return ctx.obj.github
```

- Provide one `require_*()` per dependency (`require_github`, `require_git`, `require_cwd`,
  `require_config`).
- Helpers give **type narrowing** + **clear errors**, instead of `AttributeError` deep in a
  command.
- `PerkContext` exposes a `for_test(...)` constructor that injects fakes (see §9).
- Prefer `@click.pass_obj` when a command only needs `ctx.obj`; use `@click.pass_context`
  when you also need Click's context (e.g. `ctx.exit`, subcommand invocation).

*(Source: `architecture/click-context-di-pattern.md`.)*

---

## 3. Options & flags

### 3.1 `default=None` for value options — the three-state rule

Optional value options use `default=None` so you can tell **omitted** from **explicitly
set**:

```python
@click.option("--plan", default=None, help="...")   # None | "" | "#123"
```

| Value    | Meaning             | CLI            |
| -------- | ------------------- | -------------- |
| `None`   | not provided        | (omitted)      |
| `""`     | explicitly cleared  | `--plan ""`    |
| `"#123"` | explicitly set      | `--plan "#123"`|

Without `default=None` you cannot distinguish "flag absent" from "flag given an empty value".

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

Boolean flags are two-state and exempt from the `default=None` rule — `is_flag=True` carries
an implicit `default=False`, which is correct:

```python
@click.option("-f", "--force", is_flag=True, help="Skip confirmation.")
```

### 3.4 Optional-value flags

A flag that works both bare and with a value:

```python
@click.option(
    "--remote", type=str, default=None, is_flag=False, flag_value="",
    help="Run on a remote runner (default runner if no name given).",
)
# absent -> None ; "--remote" -> "" (use default) ; "--remote ci-large" -> "ci-large"
```

### 3.5 Keep `IntRange` in sync

When an interactive menu grows, bump the bound (`click.IntRange(1, 3)` → `(1, 4)`), or the
new choice is rejected at parse time.

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

### 5.2 Message format

- **Action-oriented, specific, concise.** Tell the user what's wrong *and* what to do.
- **No `"Error: "` prefix** — the framework adds it.
- **Multi-line** = primary line, single `\n`, remediation line. **Never `\n\n`** (the error
  formatter handles spacing).

```python
raise UserFacingCliError(
    "No .pi/workflow/ cache found in this repo\n"
    "Run 'perk init' to scaffold it."
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
@click.command("doctor")
def doctor() -> None:
    """Check that the repo is healthy for perk.

    Examples:

    \b
      # condensed
      perk doctor
      # all checks
      perk doctor --verbose
    """
```

- Use `\b` before bulleted/numbered lists and code/example blocks.
- Do **not** use `\b` for normal prose (let Click wrap it responsively).
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

Never call raw `click.confirm()` after `user_output()` (stderr isn't flushed → hang). Use the
context-aware console (testable) or `user_confirm()` (flushes first):

```python
user_output("This is destructive.")
if ctx.console.confirm("Proceed?"):   # FakeConsole in tests
    ...
```

*(Source: `cli/output-styling.md`.)*

---

## 8. Command groups & the machine surface

### 8.1 Structure & naming

```
perk/cli/commands/
├── plan/
│   ├── __init__.py        # group def + subcommand registration
│   ├── save_cmd.py        # {verb}_cmd.py
│   └── list_cmd.py
└── doctor.py              # top-level command
```

| Element | Pattern | Example |
| --- | --- | --- |
| group function | `{noun}_group` | `plan_group` |
| command file | `{verb}_cmd.py` | `save_cmd.py` |
| command function | `{verb}_{noun}` | `save_plan` |

Define groups with a shared base class for consistent help, register in the CLI entry point.
perk additionally **generates stage subcommands from the stage registry** (foundational #3):
the registry is the source of truth for which `perk <stage>` commands exist; the group wiring
is mechanical.

### 8.2 The machine surface stays narrow (perk-specific)

erk made *every* command dual-surface (`--json`, `schema`, MCP) so Claude could consume the
CLI as a tool. **perk does not** — the agent uses extension tools natively, so that surface
**dissolves** ([cli-vs-pi.md](./cli-vs-pi.md) §3.2). Therefore:

- **`--json` + stable exit codes / `{success, error_type, message}`** only on commands a
  **supervisor/headless** driver consumes: `init`, `doctor`, stage launchers, `workflow run`,
  status/list.
- Do **not** rebuild a `schema`/MCP agent affordance.
- When a command has both a human and a machine surface, keep logic in a transport-independent
  `*_operation.py` and make the machine path a thin adapter over it — never duplicate logic.

*(Source: `cli/json-command-decorator.md`, reconciled with `cli-vs-pi.md`.)*

---

## 9. Testing

Use Click's `CliRunner` with an injected test context; assert on exit codes and output.

```python
from click.testing import CliRunner
from perk.cli.context import PerkContext

def test_save_plan_requires_repo():
    runner = CliRunner()
    result = runner.invoke(
        save_plan, ["--plan", "#1"],
        obj=PerkContext.for_test(github=FakeGitHub()),
    )
    assert result.exit_code == 0

def test_invalid_timeout_rejected():
    result = CliRunner().invoke(cmd, ["--timeout", "0"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output   # Click parse-time error
```

- Inject fakes via `PerkContext.for_test(...)`; the three-layer split (§1) means most logic is
  tested directly on `_impl(...)` without Click at all.
- Test **both** paths: success and each validation failure (with its message).
- `UserFacingCliError` surfaces through `CliRunner` exactly as in production (styled, exit 1).

*(Source: `testing/cli-testing.md`, `cli/cli-options-validation.md`.)*

---

## 10. Checklists

**Adding an option**
1. Value option → `default=None` (three-state); flag → `is_flag=True`.
2. Omit redundant `required=False`/`default=None`.
3. API-shape constraint → Click type; domain constraint → `Ensure.*` (one tier only).
4. Help string ends with a period; add `\b` if it includes a list/example.
5. Add/extend a test for the new behavior.

**Adding a command**
1. `perk/cli/commands/{group}/{verb}_cmd.py`, function `{verb}_{noun}`.
2. Thin callback → `require_*()` → `_impl(*, ...)`.
3. Register in the group `__init__.py`; group registered in the CLI entry point.
4. Human output via `user_output`/Rich; machine surface only if supervisor-driven.
5. Errors via `Ensure`/`UserFacingCliError`, never `RuntimeError` for user errors.
6. Test in `tests/commands/{group}/` with `CliRunner` + `PerkContext.for_test`.
