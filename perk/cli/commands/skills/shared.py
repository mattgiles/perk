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

from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import PERK_SKILLS_MANIFEST_DIR, PERK_SKILLS_MANIFEST_FILENAME

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
