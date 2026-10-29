"""The one drive path every ``perk v2`` verb shares (contracts.md §8.77)."""

from collections.abc import Sequence

import click

from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import user_output
from perk.v2.door import (
    DoorError,
    exit_code_for,
    invoke_host,
    is_execution_id,
    mint_execution_id,
    recovery_hint,
    resolve_target,
)
from perk.v2.envelope import Verb
from perk.v2.render import render_lines

JSON_HELP = "Print the v2 door envelope (or the failure JSON) on stdout."


def drive(
    ctx: click.Context,
    *,
    verb: Verb,
    execution_id: str | None,
    verb_options: Sequence[tuple[str, str]],
    as_json: bool,
) -> None:
    """Resolve the target, run the host, and emit its envelope.

    ``execution_id`` ``None`` mints a fresh one (``start``). Under ``--json`` the envelope itself
    is the payload; door failures use the standard failure shape, plus ``execution_id`` once the
    host has been invoked. Exit ``0`` for ``ok``/``pending_decision``, ``1`` for every other
    outcome.
    """
    try:
        root = require_repo(ctx)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "not_a_repo",
            message=exc.format_message(),
        )
        return
    if execution_id is None:
        execution_id = mint_execution_id()
    elif not is_execution_id(execution_id):
        fail(
            ctx,
            as_json=as_json,
            error_type="invalid_execution_id",
            message=f"{execution_id!r} is not an execution id (a 26-character ULID)",
        )
        return
    try:
        envelope = invoke_host(resolve_target(root, execution_id), verb, verb_options)
    except DoorError as exc:
        if exc.execution_id is None:
            fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        else:
            fail(
                ctx,
                as_json=as_json,
                error_type=exc.error_type,
                message=f"{exc.message}\n{recovery_hint(exc.execution_id)}",
                extra={"execution_id": exc.execution_id},
            )
        return

    def render() -> None:
        for line in render_lines(envelope):
            user_output(line)

    emit(as_json=as_json, payload=envelope.model_dump(mode="json", by_alias=True), render=render)
    code = exit_code_for(envelope)
    if code != 0:
        ctx.exit(code)
