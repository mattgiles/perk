"""Target resolution and host invocation for the experimental ``perk v2`` door (contracts.md §8.77).

The door is exterior launch only. It resolves where an execution lives
(``<main checkout>/.perk/executions/<execution-id>/``) and which workspace it belongs to (the
canonical git common dir of the invocation checkout), runs the TypeScript host entry from the
same checkout with every option as one ``--name=value`` token, and validates the one envelope
line the host prints. It never reads or writes the store.

Failures raised before the host runs (``v2_unavailable``, ``not_a_repo``) carry no execution id:
nothing could have been recorded. Every failure ``invoke_host`` raises carries the target's id,
because the host may already have recorded work under it.
"""

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ulid import ULID

from perk.cli.context import main_repo_root
from perk.convergence.init import is_self_repo
from perk.substrate import git, paths, proc
from perk.v2.envelope import Envelope, EnvelopeError, Verb, parse_envelope

HOST_ENTRY_PARTS = ("extension", "pi", "v2", "door", "main.ts")
HOST_TIMEOUT_S = 600
DEFAULT_REF = "HEAD"
DEFAULT_ACTOR = "human:cli"
DEFAULT_CANCEL_REASON = "cancelled via perk v2 cancel"

# The ULID grammar; the twin of `extension/pi/v2/kernel/identity.ts::isExecutionId`.
_EXECUTION_ID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}", re.ASCII)
_STDERR_TAIL_LINES = 20


class DoorError(Exception):
    """A door-level failure with a stable ``error_type``; ``execution_id`` is set once the host
    has been invoked (it may have recorded work)."""

    def __init__(self, error_type: str, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.execution_id = execution_id


@dataclass(frozen=True)
class DoorTarget:
    """Where one host invocation runs and what it addresses."""

    entry: Path
    checkout: Path
    store_dir: Path
    repo_identity: Path
    execution_id: str


def mint_execution_id() -> str:
    """A fresh execution id (a ULID)."""
    return str(ULID())


def is_execution_id(value: str) -> bool:
    """Whether ``value`` has the execution-id (ULID) grammar."""
    return _EXECUTION_ID.fullmatch(value) is not None


def resolve_target(invocation_root: Path, execution_id: str) -> DoorTarget:
    """The host target for ``execution_id`` from the checkout at ``invocation_root``.

    Raises ``DoorError`` (no execution id): ``v2_unavailable`` outside perk's own checkout or
    without the host entry, ``not_a_repo`` when the checkout's git dir cannot be resolved.
    """
    if not is_self_repo(invocation_root):
        raise DoorError(
            "v2_unavailable",
            "perk v2 is experimental and runs only inside perk's own source checkout "
            "([tool.perk] self = true); it is not shipped",
        )
    entry = invocation_root.joinpath(*HOST_ENTRY_PARTS)
    if not entry.is_file():
        raise DoorError("v2_unavailable", f"the v2 host entry {entry} is missing")
    repo_identity = git.git_common_dir(invocation_root)
    if repo_identity is None:
        raise DoorError("not_a_repo", f"{invocation_root} has no resolvable git directory")
    return DoorTarget(
        entry=entry,
        checkout=invocation_root,
        store_dir=paths.execution_store_dir(main_repo_root(invocation_root), execution_id),
        repo_identity=repo_identity,
        execution_id=execution_id,
    )


def host_argv(target: DoorTarget, verb: Verb, verb_options: Sequence[tuple[str, str]]) -> list[str]:
    """The host invocation: every option one ``--name=value`` token, so a value starting with
    ``--`` cannot be misparsed."""
    return [
        "node",
        str(target.entry),
        verb,
        f"--store={target.store_dir}",
        f"--execution={target.execution_id}",
        f"--repo-identity={target.repo_identity}",
        *(f"--{name}={value}" for name, value in verb_options),
    ]


def _run_host(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """The one spawn seam (tests replace it). A timeout kills the host; its unreleased owner
    epoch belongs to a dead process, so the next host frees it."""
    return proc.run_captured(argv, cwd=cwd, timeout=HOST_TIMEOUT_S)


def _stderr_tail(stderr: str) -> str:
    return "\n".join(stderr.strip().splitlines()[-_STDERR_TAIL_LINES:])


def invoke_host(
    target: DoorTarget, verb: Verb, verb_options: Sequence[tuple[str, str]]
) -> Envelope:
    """Run the host for ``verb`` and return its validated envelope.

    Every ``DoorError`` raised here carries ``target.execution_id``: ``node_missing``,
    ``v2_host_timeout``, ``v2_host_failed`` (with the stderr tail) or ``v2_envelope_invalid``.
    """
    execution_id = target.execution_id
    try:
        completed = _run_host(host_argv(target, verb, verb_options), target.checkout)
    except proc.ProcFailure as exc:
        if exc.kind == "timeout":
            raise DoorError(
                "v2_host_timeout",
                f"the v2 host exceeded {HOST_TIMEOUT_S}s and was killed",
                execution_id=execution_id,
            ) from exc
        raise DoorError(
            "node_missing", f"node could not run: {exc.cause_text}", execution_id=execution_id
        ) from exc
    if completed.returncode != 0:
        raise DoorError(
            "v2_host_failed",
            f"the v2 host exited {completed.returncode}: {_stderr_tail(completed.stderr)}",
            execution_id=execution_id,
        )
    try:
        return parse_envelope(completed.stdout, verb=verb, execution_id=execution_id)
    except EnvelopeError as exc:
        raise DoorError("v2_envelope_invalid", str(exc), execution_id=execution_id) from exc


def recovery_hint(execution_id: str) -> str:
    """How to continue an execution a failed host invocation may have advanced."""
    return (
        f"execution {execution_id} may hold recorded work: inspect it with "
        f"`perk v2 status {execution_id}` and continue it with `perk v2 run {execution_id}` "
        "(a new `perk v2 start` mints a different execution)"
    )


def exit_code_for(envelope: Envelope) -> int:
    """``0`` for ``ok``/``pending_decision``, ``1`` for every other outcome."""
    return 0 if envelope.outcome in ("ok", "pending_decision") else 1
