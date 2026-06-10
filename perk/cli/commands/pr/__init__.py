"""``perk pr`` — the PR lifecycle workers (cold doors).

The eight PR verbs the warm TS doors (and spawned children) delegate to: ``submit`` / ``check`` /
``ready`` / ``land`` (the implement → submit → land boundary), ``feedback`` / ``resolve-threads``
(the /address loop), and ``review-context`` / ``review-post`` (the /pr-review loop). Each verb is a
supervisor surface (cli-vs-pi §3.2): ``--json`` → stdout, human text → stderr, stable exit codes
(``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo), ``UserFacingCliError`` with a stable
``error_type``.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.pr.check_cmd import check_pr
from perk.cli.commands.pr.feedback_cmd import feedback_pr
from perk.cli.commands.pr.land_cmd import land_pr
from perk.cli.commands.pr.ready_cmd import ready_pr
from perk.cli.commands.pr.resolve_threads_cmd import resolve_threads_pr
from perk.cli.commands.pr.review_context_cmd import review_context_pr
from perk.cli.commands.pr.review_post_cmd import review_post_pr
from perk.cli.commands.pr.submit_cmd import submit_pr


@click.group("pr", cls=AliasGroup)
def pr_group() -> None:
    """PR lifecycle workers (cold doors): submit, check, ready, land, review + address ops."""


pr_group.add_command(submit_pr)
pr_group.add_command(check_pr)
pr_group.add_command(ready_pr)
pr_group.add_command(land_pr)
pr_group.add_command(feedback_pr)
pr_group.add_command(resolve_threads_pr)
pr_group.add_command(review_context_pr)
pr_group.add_command(review_post_pr)
