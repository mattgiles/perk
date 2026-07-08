"""``perk pr`` — the PR lifecycle group.

Sections its ``--help`` (via :class:`SectionedAliasGroup`) into **Launchers** / **Workers**:

- **Launchers** — ``submit`` and ``land`` are merged launcher+worker commands
  (:class:`~perk.cli.stages.MergedCommand`): the bare invocation opens a primed pi session,
  ``--json`` routes to the deterministic worker (the warm-door contract). ``address`` is
  launcher-only (L) —
  it has a launcher half + the warm review flow but no deterministic worker.
- **Workers** — ``check`` / ``feedback`` / ``ready`` / ``resolve-threads`` / ``review-context`` /
  ``review-post`` / ``review-submit`` / ``url`` + the ``review`` subgroup (``checkout``/``cleanup``,
  the ephemeral PR-head review worktrees): deterministic cold doors the warm TS doors delegate
  to. Each is a supervisor surface: ``--json`` → stdout, human text → stderr, stable exit codes
  (``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo).

``submit`` / ``land`` / ``address`` are also exported as the module-level command objects
``pr_submit_command`` / ``pr_land_command`` / ``pr_address_command`` so ``cli.py`` can register the
flat hot-path aliases ``perk submit`` / ``perk land`` / ``perk address`` (the same Command
object under a flat name).
"""

import click

from perk.cli.alias import SectionedAliasGroup, mark_kind
from perk.cli.commands.pr.address_cmd import address_launcher
from perk.cli.commands.pr.check_cmd import check_pr
from perk.cli.commands.pr.feedback_cmd import feedback_pr
from perk.cli.commands.pr.land_cmd import land_pr
from perk.cli.commands.pr.ready_cmd import ready_pr
from perk.cli.commands.pr.resolve_threads_cmd import resolve_threads_pr
from perk.cli.commands.pr.review import review_group
from perk.cli.commands.pr.review_context_cmd import review_context_pr
from perk.cli.commands.pr.review_post_cmd import review_post_pr
from perk.cli.commands.pr.review_submit_cmd import review_submit_pr
from perk.cli.commands.pr.submit_cmd import submit_pr
from perk.cli.commands.pr.url_cmd import url_pr
from perk.cli.stages import make_merged_command
from perk.substrate.registry import RegistryError, load_registry


@click.group("pr", cls=SectionedAliasGroup)
def pr_group() -> None:
    """PR lifecycle group: submit/land launchers, the address launcher, + the review workers.

    Launchers (submit/land) open a primed pi session by default; run with --json for the
    deterministic worker. address is launcher-only. The rest are cold-door workers the warm TS
    doors delegate to.
    """


# Build the merged submit/land commands defensively (mirror LearnGroup's registry-load guard): a
# broken registry must not brick the CLI. The fallback registers the bare worker so the warm-door
# contract (`perk pr submit --json` / `pr land --json`) keeps working; only the bare-launch half is
# lost — the same posture as LearnGroup.
try:
    _stages = {s.id: s for s in load_registry().stages}
    _submit_stage, _land_stage = _stages["submit"], _stages["land"]
except (RegistryError, FileNotFoundError, KeyError):
    pr_submit_command: click.Command = submit_pr
    pr_land_command: click.Command = land_pr
    mark_kind(pr_submit_command, "worker")
    mark_kind(pr_land_command, "worker")
else:
    pr_submit_command = make_merged_command(_submit_stage, submit_pr, name="submit")
    pr_land_command = make_merged_command(_land_stage, land_pr, name="land")
    mark_kind(pr_submit_command, "launcher")
    mark_kind(pr_land_command, "launcher")

# address is launcher-only (L): a launcher half + the warm review flow, no deterministic worker.
pr_address_command: click.Command = address_launcher
mark_kind(pr_address_command, "launcher")

# The deterministic workers the warm doors delegate to.
mark_kind(ready_pr, "worker")
mark_kind(check_pr, "worker")
mark_kind(feedback_pr, "worker")
mark_kind(resolve_threads_pr, "worker")
mark_kind(review_context_pr, "worker")
mark_kind(review_post_pr, "worker")
mark_kind(review_submit_pr, "worker")
mark_kind(url_pr, "worker")
mark_kind(review_group, "worker")

pr_group.add_command(pr_submit_command, name="submit")
pr_group.add_command(pr_land_command, name="land")
pr_group.add_command(pr_address_command, name="address")
pr_group.add_command(check_pr)
pr_group.add_command(ready_pr)
pr_group.add_command(feedback_pr)
pr_group.add_command(resolve_threads_pr)
pr_group.add_command(review_context_pr)
pr_group.add_command(review_post_pr)
pr_group.add_command(review_submit_pr)
pr_group.add_command(url_pr)
pr_group.add_command(review_group)
