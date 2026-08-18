"""The strict plan-plus-``--`` launcher grammar shared by ``perk implement`` and
``perk pr address`` (+ the flat ``perk address`` alias).

Before the first bare ``--``, Click accepts only perk options plus at most one positional
``PLAN``; the separator is consumed and every following token is delivered to ``pi`` verbatim.
Extra or unknown pre-separator tokens are rejected with usage guidance — ``perk address 1699``
is a plan *selector*, never a first user message, while
``perk address 1699 -- --model provider/model`` stays explicit.
"""

import click
from click.shell_completion import CompletionItem

# Appended to a pre-separator usage error so the rejection teaches the grammar instead of
# merely refusing.
_GRAMMAR_HINT = (
    "perk accepts only its own options plus one optional PLAN before the first bare '--'; "
    "pass pi arguments after it (e.g. `-- --model provider/model`)."
)

# The shared help epilog naming the grammar (Click renders it under the options).
PI_PASSTHROUGH_EPILOG = (
    "Pass-through grammar: before the first bare `--`, perk accepts only its own options plus "
    "at most one positional PLAN; the separator is consumed and every following token is "
    "delivered to pi verbatim, in order. Unknown or extra pre-separator tokens are rejected."
)

# The context attribute `parse_args` sets when it consumed the `--` separator. Presence of the
# separator (not tail emptiness) is the signal: `perk impl -- <TAB>` with an empty tail is
# already in the pi pass-through region and must offer no perk completions.
_SEPARATOR_ATTR = "_perk_pi_separator_seen"


class PlanLauncherCommand(click.Command):
    """A launcher command with the strict plan-plus-``--`` grammar.

    ``parse_args`` splits argv at the first bare ``--``: the head is parsed **strictly**
    (unknown options and extra positionals are usage errors carrying the grammar hint), the
    separator is consumed, and the tail is delivered verbatim as ``ctx.params["pi_args"]`` —
    the command callback declares ``pi_args`` without a Click parameter (deliberate: an
    ``UNPROCESSED`` catch-all would silently swallow mistyped perk options as pi args).
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if "--" in args:
            index = args.index("--")
            head, tail = args[:index], args[index + 1 :]
        else:
            head, tail = args, []
        try:
            remaining = super().parse_args(ctx, head)
        except click.UsageError as exc:
            exc.message = f"{exc.message}\n{_GRAMMAR_HINT}"
            raise
        ctx.params["pi_args"] = tuple(tail)
        if "--" in args:
            setattr(ctx, _SEPARATOR_ATTR, True)
        return remaining

    def get_params(self, ctx: click.Context) -> list[click.Parameter]:
        """Completion-routing assist for the post-``--`` suppression: once the separator marker
        is set (only ever AFTER the strict head parse completed — real parsing and help
        rendering see the full list), the positional arguments are withheld so Click's
        completion resolver cannot pick the unfilled PLAN argument for the pi pass-through
        region (the tail lives only in ``ctx.params["pi_args"]``, invisible to the resolver);
        resolution then falls through to :meth:`shell_complete`, which suppresses."""
        params = super().get_params(ctx)
        if getattr(ctx, _SEPARATOR_ATTR, False):
            return [param for param in params if not isinstance(param, click.Argument)]
        return params

    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[CompletionItem]:
        """No completions in the pi pass-through region: everything after the first bare ``--``
        belongs to pi (perk cannot know pi's flags, and offering perk plan ids there would be
        wrong). Pre-separator completion (the PLAN argument, perk option names) delegates to
        Click unchanged."""
        if getattr(ctx, _SEPARATOR_ATTR, False):
            return []
        return super().shell_complete(ctx, incomplete)
