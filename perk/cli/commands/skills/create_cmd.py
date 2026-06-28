"""``perk skills create NAME`` — pre-scaffold a repo skill, then launch a session to author it.

A **dedicated** write-capable cold door (not a registry stage), mirroring the ``plan replan`` /
``plan from`` / ``learn docs`` cold doors: it borrows the ``save`` stage descriptor for launch
(``mode: read-write``, ``worktree: none`` → the **main checkout**, ``cold_local: true``) and
overrides ``binding_trigger="command:skills-create"`` so ``stage:save`` does not fire and the
``perk-skill-author`` skill is delivered instead. Borrowing ``save`` injects no save-stage behavior
— the extension's authoring-context injection is gated on ``mode: read-only``.

The door pre-scaffolds ``.perk/skills/NAME/`` (the same write ``perk skills scaffold`` performs) and
then launches an authoring session seeded to follow ``perk-skill-author``. There is no structural
write-sandbox; the "scoped to ``.perk/skills/NAME/**``" instruction is a **soft scope** carried in
the seed prompt. Committing is left to the user.

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
from perk.cli.seed_file import (
    detect_seed_file,
    detect_seed_url,
    read_seed_file,
    render_seed_file_scratch,
)
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


def _seed_from_prompt(
    skill_path: str, skill_name: str, *, seed_path: str = "", seed_url: str = ""
) -> str:
    """The seed-from-source prompt (file arm or URL arm). Exactly one of ``seed_path`` /
    ``seed_url`` is non-empty; both are always passed so the conditional template stays
    byte-stable."""
    return render(
        "stages/skills/create-from.md",
        {
            "repo_skills_rel": REPO_SKILLS_REL,
            "skill_name": skill_name,
            "skill_path": skill_path,
            "seed_path": seed_path,
            "seed_url": seed_url,
        },
    )


@click.command("create", context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.option(
    "--from",
    "from_source",
    default=None,
    help="Seed authoring from a local file (read as DATA) or an http(s) URL to a SKILL.md "
    "(fetched in-session, with any sibling files); always creates a fresh skill — no in-place "
    "adoption.",
)
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
    from_source: str | None,
    dry_run: bool,
    as_json: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Scaffold a repo-authored skill at `.perk/skills/NAME/`, then launch a session to author it.

    \b
    Examples:
      perk skills create my-skill                  # scaffold + launch an authoring session
      perk skills create my-skill --dry-run         # print the seed + intended path, launch nothing
      perk skills create my-skill --from ./SKILL.md # seed authoring from a local file (DATA)
      perk skills create my-skill --from https://.../SKILL.md  # fetch + seed from a URL in-session
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

    # Resolve the seed source (file materialized to a scratch / URL handed to the session). The
    # scratch is written even on --dry-run (gitignored, no tracked-file mutation), mirroring
    # `plan from` file mode. No `--from` keeps the create.md path byte-identical.
    seed_path = ""
    seed_url = ""
    if from_source is not None:
        try:
            url = detect_seed_url(from_source)
            if url is not None:
                seed_url = url
            else:
                seed_file = detect_seed_file(from_source)
                if seed_file is None:
                    skills_fail(
                        ctx,
                        as_json=as_json,
                        error_type="seed_file_error",
                        message=(
                            f"--from: {from_source} is neither a readable file nor an http(s) URL."
                        ),
                    )
                    return
                content = read_seed_file(seed_file)
                seed_path = str(render_seed_file_scratch(root, seed_file, content))
        except UserFacingCliError as exc:
            skills_fail(
                ctx,
                as_json=as_json,
                error_type=exc.error_type or "seed_file_error",
                message=exc.format_message(),
            )
            return

    if from_source is None:
        seed = _seed_prompt(skill_path, skill_name)
    else:
        seed = _seed_from_prompt(skill_path, skill_name, seed_path=seed_path, seed_url=seed_url)

    if dry_run:
        if as_json:
            payload: dict[str, object] = {
                "success": True,
                "error_type": None,
                "name": skill_name,
                "path": f"{REPO_SKILLS_REL}/{skill_name}",
                "dry_run": True,
            }
            if from_source is not None:
                payload["from"] = from_source
                if seed_path:
                    payload["scratch_path"] = seed_path
            machine_output(json.dumps(payload))
        else:
            user_output(click.style("skills create --dry-run (no scaffold; no launch)", dim=True))
            user_output(f"  name={skill_name}  path={REPO_SKILLS_REL}/{skill_name}")
            if from_source is not None:
                detail = f"  from={from_source}"
                if seed_path:
                    detail += f"  scratch={seed_path}"
                if seed_url:
                    detail += f"  url={seed_url}"
                user_output(detail)
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
