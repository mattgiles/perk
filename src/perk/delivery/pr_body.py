"""The shared PR-body kernel — one composition for the incremental and stacked submit routes.

A body is ``lead`` (the closing keyword, the plan link, and whatever route-specific blocks come
before the reports), then ``sections`` (bounded report blocks such as change stats — the whole
"reports on PR bodies" hook), then the best-effort plan embed, then the checkout footer.

GitHub refuses a body above ``PR_BODY_MAX_CHARS`` (``422 body is too long``) on create and on
PATCH alike, so the verbatim plan embed yields to a one-line pointer when it would not fit. The
fit is judged with every section and ``FOOTER_RESERVE`` in place on BOTH passes (the create pass
has no PR number yet), so the create and update passes never disagree about the embed. Sections
are never dropped — they are small and bounded.
"""

from collections.abc import Sequence
from dataclasses import dataclass

PR_BODY_MAX_CHARS = 65_536
# The footer the update pass appends; reserved on the create pass (PR number still unknown).
FOOTER_RESERVE = len("\n\n`gh pr checkout 9999999`")


@dataclass(frozen=True)
class ComposedBody:
    """The composed body; ``plan_embedded`` is true only for the verbatim embed."""

    text: str
    plan_embedded: bool


def plan_embed(*, issue: str, plan_body: str) -> str:
    """The verbatim ``<details>`` embed of the plan markdown."""
    return f"<details><summary>Plan #{issue}</summary>\n\n{plan_body}\n\n</details>"


def compose(
    *,
    issue: str,
    lead: Sequence[str],
    sections: Sequence[str],
    plan_body: str | None,
    pr_number: int | None,
) -> ComposedBody:
    """Join ``lead + sections + [embed] + [footer]`` with blank lines plus a trailing newline.

    ``plan_body`` ``None``/empty → no embed. The footer (``gh pr checkout <pr_number>``) is
    present only once the PR number is known.
    """
    head = [*lead, *sections]
    footer = [f"`gh pr checkout {pr_number}`"] if pr_number is not None else []
    if not plan_body:
        return ComposedBody(_join([*head, *footer]), plan_embedded=False)
    embed = plan_embed(issue=issue, plan_body=plan_body)
    if len(_join([*head, embed])) + FOOTER_RESERVE <= PR_BODY_MAX_CHARS:
        return ComposedBody(_join([*head, embed, *footer]), plan_embedded=True)
    pointer = (
        f"_Plan #{issue} is too large to embed here ({len(plan_body):,} characters; GitHub "
        f"caps a PR body at {PR_BODY_MAX_CHARS:,}) — read it on the plan issue._"
    )
    return ComposedBody(_join([*head, pointer, *footer]), plan_embedded=False)


def _join(parts: Sequence[str]) -> str:
    return "\n\n".join(parts) + "\n"
