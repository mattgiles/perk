"""`perk skills delete NAME --yes` — remove a repo-authored skill + reconverge the fragment.

Removes `.perk/skills/NAME/` in the **main checkout**, best-effort unlinks a dangling
`.agents/skills/NAME` symlink, then reconverges the `perk-repo-skills.yaml` fragment (skipping the
heavy all-sources `skills update --sync`). Without `--yes`, prompts interactively when a TTY is
present, otherwise refuses and prints the path that would be removed.
"""

import shutil
import sys

import click

from perk.cli.commands.skills.shared import (
    REPO_SKILLS_REL,
    repo_skills_root,
    validate_skill_name,
)
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import converge_repo_skills_manifest
from perk.substrate.output import user_confirm, user_output


@click.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip the interactive confirmation prompt.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def delete_skill(ctx: click.Context, *, name: str, yes: bool, as_json: bool) -> None:
    """Remove a repo-authored skill (`.perk/skills/NAME/`) and reconverge the fragment.

    Operates on the main checkout. Without `--yes`, prompts interactively when a TTY is present;
    under `--json`/non-interactive it refuses. Best-effort unlinks a dangling `.agents/skills/NAME`
    symlink. Skips the heavy all-sources sync.
    """
    try:
        root = repo_skills_root(ctx)
        skill_name = validate_skill_name(name)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "skills_invalid_name",
            message=exc.format_message(),
        )
        return

    rel_path = f"{REPO_SKILLS_REL}/{skill_name}"
    target = root / REPO_SKILLS_REL / skill_name
    if not target.exists():
        fail(
            ctx,
            as_json=as_json,
            error_type="skills_not_found",
            message=f"{rel_path} does not exist \u2014 nothing to remove.",
        )
        return

    if not yes:
        if as_json or not sys.stdin.isatty():
            fail(
                ctx,
                as_json=as_json,
                error_type="confirmation_required",
                message=f"would remove {rel_path} \u2014 re-run with --yes to confirm.",
            )
            return
        if not user_confirm(f"Remove {rel_path}?", default=False):
            user_output("aborted \u2014 nothing removed")
            ctx.exit(1)

    shutil.rmtree(target)

    # Best-effort single-target symlink cleanup (the all-sources sync is deliberately skipped).
    symlink_removed = False
    link = root / ".agents" / "skills" / skill_name
    if link.is_symlink():
        try:
            link.unlink()
            symlink_removed = True
        except OSError:
            symlink_removed = False

    # Reconverge the fragment (prune if last skill, else update); errors/warnings ride non-fatally.
    conv = converge_repo_skills_manifest(root, apply=True)
    fragment = conv.changes[0].split(": ", 1)[1] if conv.changes else "none"
    warnings = list(conv.manifest.warnings)
    errors = list(conv.manifest.errors)

    payload: dict[str, object] = {
        "success": True,
        "error_type": None,
        "name": skill_name,
        "path": rel_path,
        "fragment": fragment,
        "warnings": warnings,
        "errors": errors,
        "symlink_removed": symlink_removed,
    }
    human = f"removed {rel_path}/"
    if conv.changes:
        human += f"\n{conv.changes[0]}"
    if symlink_removed:
        human += f"\nremoved dangling .agents/skills/{skill_name} symlink"
    emit(as_json=as_json, payload=payload, render=lambda: user_output(human))
    if not as_json:
        for warning in warnings:
            user_output(f"warning: {warning}")
        for error in errors:
            user_output(f"reconverge error: {error}")
