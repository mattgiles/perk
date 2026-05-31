"""Minimal, idempotent ``perk init`` — the init spine begins here (T1).

`init` is **declarative and convergent**: it edits files toward a desired state and
is safe to re-run (re-running on a converged repo is a no-op). It owns *all* Pi
wiring from the first turn (the init-spine principle, docs/phase-0-plan.md).

T1 scope: wire ``.pi/settings.json`` (perk's own extension + the borrowed default
set), create the base ``.pi/workflow/`` dir, manage ``.gitignore``, and write a
managed ``AGENTS.md`` block. Env/GitHub verification, capability tracking, flags,
``--json``, and the post-init handoff are T5; the TOML config scaffold is T4.
"""

import json
import tomllib
from pathlib import Path

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.output import user_output

NPM_PACKAGE = "@perk/pi"

# Borrowed default set (the crossover scaffolding). Independent npm: entries; Pi
# auto-installs them on the next launch.
BORROWED_PACKAGES = [
    "npm:@tombell/pi-plan",
    "npm:@juicesharp/rpiv-todo",
    "npm:@tombell/pi-diff",
    "npm:@tombell/pi-status",
]

GITIGNORE_BEGIN = "# BEGIN perk managed"
GITIGNORE_END = "# END perk managed"
GITIGNORE_BODY = "/.pi/npm/\n/.pi/git/"

AGENTS_BEGIN = "<!-- BEGIN perk managed -->"
AGENTS_END = "<!-- END perk managed -->"


def _agents_inner() -> str:
    return f"""## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring.** Every managed piece — `.pi/settings.json`
  package entries, `.pi/workflow/` dirs, `.gitignore` entries, this block — is
  written by `perk init`. Converge any repo by (re-)running `perk init`; it is
  idempotent (a no-op on an already-converged repo).
- **`init` converges *forward*; `doctor --fix` repairs oddities.** Do not bake
  backwards-compat migrations into `init`.
- **Headless-fail-safe.** In extensions, guard every rich-UI call with `ctx.hasUI`
  and block dangerous operations when `!ctx.hasUI`.
- **State tiers:** GitHub (canonical) / `.pi/workflow/` (cache) / session entries
  (transient). Cross-plane contracts live in `shared/`.

perk version: {__version__}"""


def _is_self_repo(root: Path) -> bool:
    """True if ``root`` is perk's own source tree (``[tool.perk] self = true``)."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    # No LBYL check exists for TOML validity, so parsing may raise; an unparseable
    # pyproject simply means "can't confirm self" -> consumer. A read error (OSError)
    # is genuinely exceptional and is allowed to bubble.
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return False
    return data.get("tool", {}).get("perk", {}).get("self") is True


def _npm_name(entry: str) -> str | None:
    """``npm:@scope/name@1.2.3`` -> ``@scope/name`` (identity for dedup)."""
    if not entry.startswith("npm:"):
        return None
    spec = entry[len("npm:") :]
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec  # at == 0 is a scope's leading @


def _desired_packages(self_repo: bool) -> list[str]:
    own = ".." if self_repo else f"npm:{NPM_PACKAGE}@{__version__}"
    return [own, *BORROWED_PACKAGES]


def _converge_settings(root: Path, self_repo: bool, changes: list[str]) -> None:
    pi_dir = root / ".pi"
    pi_dir.mkdir(parents=True, exist_ok=True)
    settings_path = pi_dir / "settings.json"

    old_text = settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None
    try:
        settings = json.loads(old_text) if old_text else {}
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(
            f".pi/settings.json is not valid JSON ({exc})\n"
            "Fix or remove it, then re-run 'perk init'."
        ) from exc
    if not isinstance(settings, dict):
        raise UserFacingCliError(
            ".pi/settings.json must contain a JSON object\n"
            "Fix or remove it, then re-run 'perk init'."
        )

    packages = settings.get("packages")
    if not isinstance(packages, list):
        packages = []

    have_local = {p for p in packages if isinstance(p, str) and not p.startswith("npm:")}
    have_npm = {n for n in (_npm_name(p) for p in packages if isinstance(p, str)) if n}

    added: list[str] = []
    for want in _desired_packages(self_repo):
        if want.startswith("npm:"):
            name = _npm_name(want)
            if name is None or name in have_npm:
                continue
            packages.append(want)
            have_npm.add(name)
        else:
            if want in have_local:
                continue
            packages.append(want)
            have_local.add(want)
        added.append(want)

    settings["packages"] = packages
    new_text = json.dumps(settings, indent=2) + "\n"
    if new_text != old_text:
        settings_path.write_text(new_text, encoding="utf-8")
        changes.append(
            f".pi/settings.json: added {', '.join(added)}"
            if added
            else ".pi/settings.json: normalized"
        )


def _converge_workflow_dir(root: Path, changes: list[str]) -> None:
    gitkeep = root / ".pi" / "workflow" / ".gitkeep"
    if not gitkeep.is_file():
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        gitkeep.write_text("", encoding="utf-8")
        changes.append(".pi/workflow/: created")


def _apply_managed_block(
    path: Path,
    *,
    begin: str,
    end: str,
    inner: str,
    changes: list[str],
    label: str,
    header_if_new: str = "",
) -> None:
    block = f"{begin}\n{inner.rstrip(chr(10))}\n{end}\n"
    old = path.read_text(encoding="utf-8") if path.is_file() else None

    if old is not None and begin in old and end in old:
        start = old.index(begin)
        stop = old.index(end) + len(end)
        new = old[:start] + block.rstrip("\n") + old[stop:]
        verb = "updated"
    else:
        base = old if old is not None else header_if_new
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        new = base + block
        verb = "created"

    if new != old:
        path.write_text(new, encoding="utf-8")
        changes.append(f"{label}: {verb}")


def run_init(root: Path | None = None) -> int:
    root = (root or Path.cwd()).resolve()
    self_repo = _is_self_repo(root)
    changes: list[str] = []

    _converge_settings(root, self_repo, changes)
    _converge_workflow_dir(root, changes)
    _apply_managed_block(
        root / ".gitignore",
        begin=GITIGNORE_BEGIN,
        end=GITIGNORE_END,
        inner=GITIGNORE_BODY,
        changes=changes,
        label=".gitignore",
    )
    _apply_managed_block(
        root / "AGENTS.md",
        begin=AGENTS_BEGIN,
        end=AGENTS_END,
        inner=_agents_inner(),
        changes=changes,
        label="AGENTS.md",
        header_if_new="# AGENTS\n",
    )

    mode = "self" if self_repo else "consumer"
    if changes:
        user_output(f"perk init ({mode}): converged")
        for change in changes:
            user_output(f"  - {change}")
    else:
        user_output(f"perk init ({mode}): already converged")
    return 0
