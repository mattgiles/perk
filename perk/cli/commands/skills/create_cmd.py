"""``perk skills create NAME`` — pre-scaffold a repo skill, then launch a session to author it.

A **dedicated** write-capable cold door (not a registry stage), mirroring the ``plan replan`` /
``plan from`` / ``learn docs`` cold doors: it borrows the ``save`` stage descriptor for launch
(``mode: read-write``, ``worktree: none`` → the **main checkout**, ``cold_local: true``) and
overrides ``binding_trigger="command:skills-create"`` so ``stage:save`` does not fire and the
``perk-skill-author`` skill is delivered instead. Borrowing ``save`` injects no save-stage behavior
— the extension's authoring-context injection is gated on ``mode: read-only``.

The door pre-scaffolds ``.pi/skills/NAME/`` (the same write ``perk skills scaffold`` performs) and
then launches an authoring session seeded to follow ``perk-skill-author``. There is no structural
write-sandbox; the "scoped to ``.pi/skills/NAME/**``" instruction is a **soft scope** carried in the
seed prompt. Committing is left to the user.

``--dry-run`` does NOT pre-scaffold (no tracked-file mutation): it prints the seed + intended path
and launches nothing. The existence-refusal still runs on every path (incl. ``--dry-run``).
"""

import json

import click

from perk.cli.commands.skills.shared import (
    REPO_SKILLS_REL,
    perform_scaffold,
    repo_skills_root,
    skills_fail,
    validate_skill_name,
)
from perk.cli.context import require_config
from perk.cli.ensure import UserFacingCliError
from perk.prompts import render
from perk.run import launch
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import Stage, load_registry


def _save_stage() -> Stage:
    """The borrowed write-capable launch descriptor (``mode: read-write``, ``worktree: none``)."""
    return next(s for s in load_registry().stages if s.id == "save")


def _seed_prompt(skill_path: str, skill_name: str) -> str:
    """The initial prompt for the write-capable authoring session."""
    return render(
        "stages/skills/create.md",
        {
            "repo_skills_rel": REPO_SKILLS_REL,
            "skill_name": skill_name,
            "skill_path": skill_path,
        },
    )


@click.command("create", context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.option(
    "--dry-run", is_flag=True, help="Print the seed + intended path; scaffold + launch nothing."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def create_skill(
    ctx: click.Context,
    *,
    name: str,
    dry_run: bool,
    as_json: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Scaffold a repo-authored skill at `.pi/skills/NAME/`, then launch a session to author it.

    \b
    Examples:
      perk skills create my-skill            # scaffold + launch an authoring session
      perk skills create my-skill --dry-run  # print the seed + intended path, launch nothing
    """
    try:
        root = repo_skills_root(ctx)
        config = require_config(ctx)
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
                f"{REPO_SKILLS_REL}/{skill_name} already exists \u2014 use "
                f"`perk skills refine {skill_name}` to re-author an existing skill."
            ),
        )
        return

    skill_path = str(target / "SKILL.md")
    seed = _seed_prompt(skill_path, skill_name)

    if dry_run:
        if as_json:
            machine_output(
                json.dumps(
                    {
                        "success": True,
                        "error_type": None,
                        "name": skill_name,
                        "path": f"{REPO_SKILLS_REL}/{skill_name}",
                        "dry_run": True,
                    }
                )
            )
        else:
            user_output(click.style("skills create --dry-run (no scaffold; no launch)", dim=True))
            user_output(f"  name={skill_name}  path={REPO_SKILLS_REL}/{skill_name}")
            user_output(click.style("── seed prompt ──", fg="bright_black"))
            user_output(seed)
        return

    # Pre-scaffold the skill (offline-failable reconverge rides non-fatally), then surface its
    # warnings/errors before launching (mirrors `scaffold`).
    outcome = perform_scaffold(root, skill_name)
    if as_json:
        user_output(f"scaffolded {REPO_SKILLS_REL}/{skill_name}; launching authoring session")
    else:
        for warning in outcome.warnings:
            user_output(f"warning: {warning}")
        for error in outcome.errors:
            user_output(f"reconverge error: {error}")

    # launch_stage exec's pi with the seeded prompt + a fresh run_id (cold_local mints). The
    # borrowed `save` stage is write-capable; binding_trigger delivers perk-skill-author, not save.
    launch.launch_stage(
        repo_root=root,
        config=config,
        stage=_save_stage(),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=list(pi_args),
        prompt_override=seed,
        binding_trigger="command:skills-create",
    )
