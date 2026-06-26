"""``perk skills refine NAME`` — re-open an existing repo skill, then launch a session to improve.

The near-twin of ``perk skills create`` (the authoring cold door), but for an **existing**
repo-authored skill: it borrows the same ``save`` stage descriptor for launch (``mode: read-write``,
``worktree: none`` → the **main checkout**, ``cold_local: true``) and overrides
``binding_trigger="command:skills-refine"`` so ``stage:save`` does not fire and the
``perk-skill-author`` skill is delivered instead.

Unlike ``create``, ``refine`` never scaffolds and never reconverges the fragment — the skill already
exists (and was converged at create/scaffold time). The door is read-only on the filesystem until
the launched session edits ``SKILL.md`` in place. It refuses (on every path, including
``--dry-run``) when ``.pi/skills/NAME/SKILL.md`` is absent, pointing at ``perk skills create``.

``--dry-run`` prints the seed + intended path and launches nothing; the absent-skill refusal still
runs first.
"""

import json

import click

from perk.cli.commands.skills.shared import (
    REPO_SKILLS_REL,
    repo_skills_root,
    skills_fail,
    validate_skill_name,
)
from perk.cli.context import require_config
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import Stage, load_registry


def _save_stage() -> Stage:
    """The borrowed write-capable launch descriptor (``mode: read-write``, ``worktree: none``)."""
    return next(s for s in load_registry().stages if s.id == "save")


def _seed_prompt(skill_path: str, skill_name: str) -> str:
    """The initial prompt for the write-capable refine session."""
    return (
        "You are running perk skills refine — improving an EXISTING repo-specific skill. Follow "
        "the perk-skill-author skill.\n\n"
        f"  1. Read the existing `SKILL.md` at `{skill_path}` and the relevant repo context.\n"
        "  2. Improve it in place: sharpen the `description` triggers (the entire discovery "
        "surface — name the tasks/phrases, not a vague topic), tighten/restructure the body, "
        "move heavy/reference material into sibling `references/`/`scripts/` files (the delivery "
        "symlink carries them for free), and re-validate the frontmatter (`name` must equal the "
        f"directory segment `{skill_name}`; `description` non-empty).\n"
        f"  3. Stay within the soft scope: `{REPO_SKILLS_REL}/{skill_name}/**` plus any "
        "directly-required docs/bindings (add a binding only if the skill must fire at a "
        "stage/command — reconcile the docs in the same change). Do NOT touch unrelated files.\n\n"
        "  Improve the skill, then STOP — leave committing to the user. NEVER delegate the "
        "judgment, authoring, or the commit decision.\n\n"
        f"  Skill: {REPO_SKILLS_REL}/{skill_name}/SKILL.md"
    )


@click.command("refine", context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Print the seed + intended path; launch nothing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def refine_skill(
    ctx: click.Context,
    *,
    name: str,
    dry_run: bool,
    as_json: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Re-open an existing repo-authored skill (`.pi/skills/NAME/`), then launch a refine session.

    \b
    Examples:
      perk skills refine my-skill            # launch a session to improve the existing skill
      perk skills refine my-skill --dry-run  # print the seed + intended path, launch nothing
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
    if not (target / "SKILL.md").exists():
        skills_fail(
            ctx,
            as_json=as_json,
            error_type="skills_not_found",
            message=(
                f"{REPO_SKILLS_REL}/{skill_name}/SKILL.md does not exist \u2014 use "
                f"`perk skills create {skill_name}` to author a new skill."
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
            user_output(click.style("skills refine --dry-run (no launch)", dim=True))
            user_output(f"  name={skill_name}  path={REPO_SKILLS_REL}/{skill_name}")
            user_output(click.style("── seed prompt ──", fg="bright_black"))
            user_output(seed)
        return

    if as_json:
        user_output(f"refining {REPO_SKILLS_REL}/{skill_name}; launching session")

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
        binding_trigger="command:skills-refine",
    )
