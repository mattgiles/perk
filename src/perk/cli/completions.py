"""Shell-completion callbacks for plan- and objective-id arguments (``shell_complete=``).

A neutral ``perk/cli/``-level leaf beside ``plan_selection.py``: the callbacks Click invokes
mid-TAB. Each TAB costs one bounded live backend read (``list_plan_completion_candidates`` /
``list_objective_completion_candidates`` — one page per query; no caching, by decision): the
candidates are the open plan/objective ids, newest-created-first, each carrying a sanitized,
truncated title as the per-candidate description (rendered by zsh/fish; bash shows bare ids).

The callbacks are silent by construction — no ``io_step``, no ``user_output`` — and resolve the
repo from ``Path.cwd()`` (never ``ctx.obj``: the root group callback does not run during
completion).
"""

from collections.abc import Callable, Iterable
from pathlib import Path

import click
from click.shell_completion import CompletionItem

from perk.backends import resolve
from perk.cli import plan_selection

# The pinned per-candidate help bound: a title of <= 60 characters passes through verbatim; a
# longer one becomes title[:59] + "…" (U+2026) — the final string is always <= 60 characters,
# ellipsis included.
_HELP_MAX_CHARS = 60


def _sanitize_title(title: str) -> str:
    """Normalize a backend-controlled title to a printable single line before it reaches the
    shell: titles are remote-authored DATA, a newline corrupts Click's line-framed completion
    response, and C0/ESC control characters can render as terminal control sequences. Every
    non-printable character (controls, ESC, CR/LF/TAB) becomes a space; whitespace runs
    collapse."""
    cleaned = "".join(char if char.isprintable() else " " for char in title)
    return " ".join(cleaned.split())


def _truncate_title(title: str) -> str:
    title = _sanitize_title(title)
    if len(title) <= _HELP_MAX_CHARS:
        return title
    return title[: _HELP_MAX_CHARS - 1] + "…"


def _complete(
    incomplete: str, list_candidates: Callable[[Path], Iterable[tuple[str, str]]]
) -> list[CompletionItem]:
    """The shared completion body: resolve the main root from the cwd, run the bounded backend
    list read, prefix-filter, and shape the ``CompletionItem``s (input order preserved —
    newest-created-first from the list read)."""
    # Deliberate deviation from the report-your-errors boundary rule: a completion callback has
    # no reporting surface — any stderr output or traceback mid-TAB garbles the user's prompt —
    # so the WHOLE body fail-softs to "no candidates". The backend list reads themselves stay
    # fail-loud (raise on infra failure) per the list-read contract; only this boundary swallows.
    try:
        main_root = plan_selection.main_repo_root(Path.cwd())
        prefix = incomplete.strip().lstrip("#").strip()
        return [
            CompletionItem(candidate_id, help=_truncate_title(title))
            for candidate_id, title in list_candidates(main_root)
            if candidate_id.startswith(prefix)
        ]
    except Exception:
        return []


def _open_plans(main_root: Path) -> Iterable[tuple[str, str]]:
    backend = resolve.resolve_issue_backend(main_root)
    return ((row.id, row.title) for row in backend.list_plan_completion_candidates())


def _open_objectives(main_root: Path) -> Iterable[tuple[str, str]]:
    store = resolve.resolve_objective_store(main_root)
    return ((row.id, row.title) for row in store.list_objective_completion_candidates())


def complete_plan_id(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """TAB completion for a plan-id argument: the open plans from the configured issue backend
    (bare ids as values; truncated titles as the description column). Fail-soft to no candidates
    when offline/unauthenticated/outside a repo."""
    return _complete(incomplete, _open_plans)


def complete_objective_id(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """TAB completion for an objective-id argument: the open objectives from the configured
    objective store (bare ids as values; truncated titles as the description column). Fail-soft
    to no candidates when offline/unauthenticated/outside a repo."""
    return _complete(incomplete, _open_objectives)
