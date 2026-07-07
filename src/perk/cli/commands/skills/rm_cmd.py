"""`perk skills remove` — remove a skill from this repo (the single reimplementation).

The upstream `skills` CLI has no removal command, so perk owns the manifest edit: it removes the
skill from the user's main `.agents/manifest.yaml` (refusing perk-managed sources), then runs
`skills sync` to reconcile the now-undeclared link.
"""

import shutil

import click

from perk.cli.alias import alias
from perk.cli.commands.skills.shared import (
    SKILLS_TIMEOUT_S,
    managed_source_aliases,
    remove_skill_from_manifest_text,
)
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import user_output
from perk.substrate.proc import ProcFailure, run_captured


@alias("rm")
@click.command("remove")
@click.option("--source", required=True, help="The source alias the skill is declared under.")
@click.option("--skill", required=True, help="The skill name to remove.")
@click.pass_context
def remove_skill(ctx: click.Context, *, source: str, skill: str) -> None:
    """Remove a skill from this repo (drops its source when no skills remain).

    Edits `.agents/manifest.yaml` directly (the upstream `skills` CLI has no removal command), then
    runs `skills sync` to drop the now-undeclared symlink. Refuses perk-managed sources.
    """
    root = require_repo(ctx)
    manifest = root / ".agents" / "manifest.yaml"

    if source in managed_source_aliases(root):
        raise UserFacingCliError(
            f"source `{source}` is managed by `perk init` "
            f"(declared in `.agents/manifest.d/perk.yaml`) and cannot be removed here.\n"
            "Edit perk's source set and re-run `perk init` if this is intended.",
            error_type="skills_managed",
        )

    if not manifest.is_file():
        raise UserFacingCliError(
            "no `.agents/manifest.yaml` — run `perk init` first.",
            error_type="skills_no_manifest",
        )

    original = manifest.read_text(encoding="utf-8")
    outcome = remove_skill_from_manifest_text(original, source, skill)
    if not outcome.skill_removed:
        raise UserFacingCliError(
            f"skill `{skill}` from source `{source}` is not declared in `.agents/manifest.yaml`.",
            error_type="skills_not_declared",
        )

    manifest.write_text(outcome.new_text, encoding="utf-8")

    if shutil.which("skills") is None:
        manifest.write_text(original, encoding="utf-8")
        raise UserFacingCliError(
            "the `skills` CLI is not on PATH — install it (see github.com/mattgiles/skills), "
            "then re-run.",
            error_type="skills_missing",
        )
    try:
        proc = run_captured(["skills", "sync"], cwd=root, timeout=SKILLS_TIMEOUT_S)
    except ProcFailure as exc:
        manifest.write_text(original, encoding="utf-8")
        if exc.kind == "timeout":
            raise UserFacingCliError(
                f"`skills sync` timed out after {SKILLS_TIMEOUT_S}s — manifest restored.",
                error_type="skills_timeout",
            ) from exc
        raise UserFacingCliError(
            f"could not run `skills sync`: {exc.cause_text} — manifest restored.",
            error_type="skills_failed",
        ) from exc
    if proc.returncode != 0:
        manifest.write_text(original, encoding="utf-8")
        stderr = "\n".join((proc.stderr or "").strip().splitlines()[:5]) or "(no stderr)"
        raise UserFacingCliError(
            f"`skills sync` exited {proc.returncode} — manifest restored:\n{stderr}",
            error_type="skills_sync_failed",
        )

    user_output(f"removed skill `{skill}` from source `{source}` in .agents/manifest.yaml")
    if outcome.source_removed:
        user_output(f"removed source `{source}` (no skills remained)")
