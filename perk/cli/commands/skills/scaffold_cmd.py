"""`perk skills scaffold NAME` — create a repo-authored skill stub + reconverge the fragment.

Deterministic and create-only: writes a TODO `SKILL.md` under `.pi/skills/NAME/` in the **main
checkout**, refuses if the directory already exists (no overwrite flag), then reconverges the
perk-managed `.agents/manifest.d/perk-repo-skills.yaml` fragment (skipping the heavy all-sources
`skills update --sync`).
"""

import click

from perk.cli.commands.skills.shared import (
    REPO_SKILLS_REL,
    repo_skills_root,
    skills_emit,
    skills_fail,
    todo_skill_md,
    validate_skill_name,
)
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import converge_repo_skills_manifest
from perk.substrate.output import user_output


@click.command("scaffold")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def scaffold_skill(ctx: click.Context, *, name: str, as_json: bool) -> None:
    """Scaffold a repo-authored skill stub at `.pi/skills/NAME/SKILL.md` (create-only).

    Writes a TODO `SKILL.md` in the main checkout and reconverges the `perk-repo-skills.yaml`
    fragment. Refuses if `.pi/skills/NAME/` already exists. Skips the heavy all-sources sync.
    """
    try:
        root = repo_skills_root(ctx)
        skill_name = validate_skill_name(name)
    except UserFacingCliError as exc:
        skills_fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "skills_invalid_name",
            message=exc.format_message(),
        )
        return

    target = root / REPO_SKILLS_REL / skill_name
    if target.exists():
        skills_fail(
            ctx,
            as_json=as_json,
            error_type="skills_exists",
            message=(
                f"{REPO_SKILLS_REL}/{skill_name} already exists \u2014 there is no overwrite flag. "
                f"Edit {REPO_SKILLS_REL}/{skill_name}/SKILL.md directly."
            ),
        )
        return

    # The file write is the primary deliverable; a true filesystem failure is fatal (raises here).
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(todo_skill_md(skill_name), encoding="utf-8")

    # Reconverge the fragment (offline-failable GitHub read); errors/warnings ride non-fatally.
    conv = converge_repo_skills_manifest(root, apply=True)
    fragment = conv.changes[0].split(": ", 1)[1] if conv.changes else "none"
    warnings = list(conv.manifest.warnings)
    errors = list(conv.manifest.errors)

    payload: dict[str, object] = {
        "success": True,
        "error_type": None,
        "name": skill_name,
        "path": f"{REPO_SKILLS_REL}/{skill_name}",
        "fragment": fragment,
        "warnings": warnings,
        "errors": errors,
    }
    human = f"created {REPO_SKILLS_REL}/{skill_name}/SKILL.md"
    if conv.changes:
        human += f"\n{conv.changes[0]}"
    skills_emit(payload, as_json=as_json, human=human)
    if not as_json:
        for warning in warnings:
            user_output(f"warning: {warning}")
        for error in errors:
            user_output(f"reconverge error: {error}")
