"""``perk pr review`` — ephemeral PR-head review worktrees (the `/review` checkout substrate).

The `/review` flow needs a detached checkout of a foreign PR's head so reviewer children can
investigate real surrounding code at head (not just the diff) and the hunk surface can diff
inside it. The head is **untrusted foreign code, not just untrusted text**: the checkout is
structurally read-only investigation material — the doors never run `[worktree] setup` and never
install anything (a foreign ``package.json``'s install scripts are arbitrary code execution).

Checkouts live at ``<worktree_root>/review-<n>`` — outside the ``plan-<N>`` namespace, so
``worktree wipe`` never touches them; ``perk worktree list``/``remove`` remain the manual
fallback. ``checkout`` refreshes to the current head and reaps stale siblings; ``cleanup`` is
single-PR and idempotent.
"""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.pr.review.checkout_cmd import checkout_review
from perk.cli.commands.pr.review.cleanup_cmd import cleanup_review


@click.group("review", cls=AliasGroup)
def review_group() -> None:
    """Ephemeral PR-head review worktrees: checkout / cleanup."""


register_with_aliases(review_group, checkout_review)
register_with_aliases(review_group, cleanup_review)
