"""Shared helpers for the `perk skills` group (sugar over the `skills` CLI).

The governing principle: `skills` is the substrate. Every verb is a thin pass-through to the
`skills` binary (:func:`run_skills`) EXCEPT `remove`, which the upstream CLI does not support and
which perk therefore implements by editing `.agents/manifest.yaml` directly
(:func:`remove_skill_from_manifest_text`).
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import click
import yaml

from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import (
    PERK_SKILLS_MANIFEST_DIR,
    PERK_SKILLS_MANIFEST_FILENAME,
    converge_repo_skills_manifest,
)
from perk.substrate import git, paths
from perk.substrate.paths import (
    REPO_SKILLS_REL as REPO_SKILLS_REL,  # re-exported for the skills command modules
)

# Matches `sync_skills`' update timeout — `skills` resolves/syncs git sources, which is slow.
SKILLS_TIMEOUT_S = 180

_SKILLS_MISSING_MSG = (
    "the `skills` CLI is not on PATH — install it (see github.com/mattgiles/skills), then re-run."
)


def run_skills(ctx: click.Context, args: list[str], *, cwd: Path) -> NoReturn:
    """Pass-through to the `skills` binary: inherit stdio, propagate the exit code.

    Stdio is inherited (no ``capture_output``) so the user sees `skills`' native output directly.
    The upstream exit code is propagated via ``ctx.exit`` (0 success, 2 usage, 3 doctor, 1 other).
    """
    if shutil.which("skills") is None:
        raise UserFacingCliError(_SKILLS_MISSING_MSG, error_type="skills_missing")
    try:
        proc = subprocess.run(["skills", *args], cwd=cwd, check=False, timeout=SKILLS_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise UserFacingCliError(
            f"`skills {' '.join(args)}` timed out after {SKILLS_TIMEOUT_S}s.",
            error_type="skills_timeout",
        ) from exc
    except OSError as exc:
        raise UserFacingCliError(
            f"could not run `skills`: {exc}", error_type="skills_failed"
        ) from exc
    ctx.exit(proc.returncode)


@dataclass(frozen=True)
class RemovalOutcome:
    """The result of removing a skill from a manifest's text."""

    skill_removed: bool
    source_removed: bool
    new_text: str


def remove_skill_from_manifest_text(text: str, source: str, skill: str) -> RemovalOutcome:
    """Remove ``(source, skill)`` from a manifest's YAML ``text`` (pure — no I/O).

    Drops every ``skills`` entry whose ``source``+``name`` match ``skill``. When no remaining skill
    still references ``source``, the ``sources[source]`` declaration is dropped too. The manifest is
    re-emitted via ``yaml.safe_dump(sort_keys=False)`` (reformatting is accepted — see the plan's
    Assumptions); ``skills add`` re-parses the reformatted file fine.
    """
    data = yaml.safe_load(text) or {}
    skills = data.get("skills") or []
    kept = [
        entry
        for entry in skills
        if not (
            isinstance(entry, dict) and entry.get("source") == source and entry.get("name") == skill
        )
    ]
    skill_removed = len(kept) != len(skills)
    data["skills"] = kept

    source_removed = False
    sources = data.get("sources")
    if skill_removed and isinstance(sources, dict) and source in sources:
        still_referenced = any(
            isinstance(entry, dict) and entry.get("source") == source for entry in kept
        )
        if not still_referenced:
            del sources[source]
            source_removed = True

    new_text = yaml.safe_dump(data, sort_keys=False)
    return RemovalOutcome(
        skill_removed=skill_removed, source_removed=source_removed, new_text=new_text
    )


def managed_source_aliases(root: Path) -> set[str]:
    """The set of source aliases declared in the perk-managed manifest fragment.

    Source aliases are unique across the base manifest + every fragment, so the fragment's
    ``sources`` keys are the authoritative "is this source perk-managed" check. Returns an empty set
    when the fragment is absent.
    """
    fragment = root / PERK_SKILLS_MANIFEST_DIR / PERK_SKILLS_MANIFEST_FILENAME
    if not fragment.is_file():
        return set()
    data = yaml.safe_load(fragment.read_text(encoding="utf-8")) or {}
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return set()
    return {str(key) for key in sources}


# ---------------------------------------------------------------------------
# Repo-authored-skills lifecycle (`scaffold` / `delete`)
# ---------------------------------------------------------------------------


def repo_skills_root(ctx: click.Context) -> Path:
    """The **main checkout** root that owns ``.perk/skills/`` (the `.perk/skills/` parent).

    Repo-authored skills live in the main working tree, not a linked worktree, so a
    ``perk skills scaffold``/``delete`` invoked from inside a worktree still targets the main
    checkout (mirrors ``config.py``'s ``main_worktree_root(repo_root) or repo_root``).
    """
    repo_root = require_repo(ctx)
    return git.main_worktree_root(repo_root) or repo_root


def validate_skill_name(name: str) -> str:
    """Validate ``NAME`` as a single skill-directory segment, returning the cleaned name.

    ``NAME`` becomes both the ``.perk/skills/<NAME>/`` directory and the frontmatter ``name`` (which
    the convergence requires to be equal), so it must be a single path segment: no ``/`` or ``\\``,
    not ``.``/``..``, no leading ``.``, and non-empty. Raises ``UserFacingCliError`` on a bad name.
    """
    cleaned = name.strip()
    if (
        not cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or cleaned in {".", ".."}
        or cleaned.startswith(".")
    ):
        raise UserFacingCliError(
            f"invalid skill name {name!r} — must be a single directory segment "
            "(no `/` or `\\`, not `.`/`..`, no leading `.`).",
            error_type="skills_invalid_name",
        )
    return cleaned


def todo_skill_md(name: str) -> str:
    """Render the create-only TODO ``SKILL.md`` body for a freshly-scaffolded skill.

    The placeholder ``description`` is intentionally non-empty (so the convergence renders the
    fragment) and self-documenting. ``stages: all`` is declared (well-formed — silences doctor's
    undeclared nudge and engages the exposure model) with a TODO comment prompting a deliberate
    narrowing; YAML comments are legal in frontmatter, so the parsed value is ``all``.
    """
    return (
        "---\n"
        f"name: {name}\n"
        "description: TODO \u2014 describe WHEN to use this skill (concrete trigger phrases and "
        "tasks) so it is discoverable. Replace this placeholder before committing.\n"
        "stages: all  # TODO: narrow \u2014 a stage-id list (e.g. [plan, implement]), all, or [] "
        "(interactive-only)\n"
        "---\n"
        "\n"
        f"# {name}\n"
        "\n"
        "TODO: Replace this scaffold with the skill's guidance.\n"
        "\n"
        "## When to use this skill\n"
        "\n"
        "TODO: Concrete triggers \u2014 the tasks, phrases, or situations that should activate "
        "this skill.\n"
        "\n"
        "## Instructions\n"
        "\n"
        "TODO: The durable, repo-specific guidance an agent should follow.\n"
    )


@dataclass(frozen=True)
class ScaffoldOutcome:
    """The result of scaffolding a repo-authored skill + reconverging the fragment.

    ``fragment`` is the convergence verb (``created``/``updated``/``none``); ``change_line`` is the
    raw ``"<path>: <verb>"`` convergence change (or ``None`` when nothing changed) for the human
    message; ``warnings``/``errors`` ride non-fatally (the offline GitHub read may fail).
    """

    fragment: str
    change_line: str | None
    warnings: list[str]
    errors: list[str]


def perform_scaffold(root: Path, skill_name: str) -> ScaffoldOutcome:
    """Write the TODO ``SKILL.md`` under ``.perk/skills/<skill_name>/`` and reconverge the fragment.

    The shared scaffold step behind both ``perk skills scaffold`` (deterministic create-only) and
    ``perk skills create`` (the authoring cold door's pre-scaffold). The caller owns the
    existence-refusal + name validation; this only writes (the file write is the primary
    deliverable, so a true filesystem failure raises) and reconverges (offline-failable — errors
    ride non-fatally in the outcome). Reconvergence is read through the module namespace so tests
    can stub it.
    """
    target = paths.repo_skills_dir(root) / skill_name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(todo_skill_md(skill_name), encoding="utf-8")

    conv = converge_repo_skills_manifest(root, apply=True)
    change_line = conv.changes[0] if conv.changes else None
    fragment = change_line.split(": ", 1)[1] if change_line else "none"
    return ScaffoldOutcome(
        fragment=fragment,
        change_line=change_line,
        warnings=list(conv.manifest.warnings),
        errors=list(conv.manifest.errors),
    )
