"""The borrowed pi-subagents engine's native ``worktree`` default, as a managed convergence."""

import json
import tomllib
from pathlib import Path

from perk.cli.ensure import UserFacingCliError
from perk.substrate.config import ConfigError, launch_pi_agent_dir
from perk.substrate.fs import atomic_write_text


def _converge_subagent_worktree_default(root: Path, *, apply: bool = True) -> list[str]:
    """Pin pi-subagents' native ``worktree`` default to ``false`` in the launch agent dir.

    perk's conflict resolver drives pi-subagents through its structured-delegation API, which
    has no per-request ``worktree`` field — so the engine applies the *native config default*
    (``<agent dir>/extensions/subagent/config.json`` → ``worktree``) to every launch that omits
    it. A ``true`` default would run the resolver child in a separate managed worktree instead of
    the conflicted one, so the engine refuses (``incompatible-worktree-default``) and this
    convergence owns the only lever: the file the resolver actually reads, in exactly the agent
    dir a perk session launches with (:func:`launch_pi_agent_dir` — env → `[pi] agent_dir` →
    ``~/.pi/agent``, the one resolver shared with ``launch_stage``).

    Deliberately narrow: only the ``worktree`` key is rewritten (sibling keys survive
    byte-for-byte in value; the file is re-serialized in pi-subagents' own ``saveConfig`` shape —
    tab indent, trailing newline), only when present and not exactly ``false``, and the file is
    **never created** (an absent file/key is compatible for the engine and pi-subagents' own
    default is no worktree). Setting ``false`` rather than deleting the key is explicit and
    idempotent, and matches the engine's ``"false"`` classification. The write is an atomic
    same-directory replace, so a concurrent reader (perk's engine included) sees old or new
    bytes, never a torn file.

    Fail-open where the resolver is: no resolvable agent dir → nothing to converge; a broken
    main-checkout config → ``[]`` (the ``config`` check owns that complaint — the
    ``_converge_models`` posture). Only a genuinely **missing** path is compatible. Everything
    else perk cannot read as a JSON object — an existing non-file (a directory, which the
    engine reads as ``incompatible`` via EISDIR), an unreadable or non-UTF-8 file, invalid JSON, a
    non-object document — is the one loud arm (the ``_converge_settings`` posture): it raises a
    ``UserFacingCliError`` (``invalid_subagent_config``) naming the absolute path — ``perk init``
    fails, the managed doctor check renders it ``unverifiable``, and ``--fix`` records the refusal
    on ``fix_errors`` and continues — because perk never rewrites a file it cannot parse, and the
    same broken path already breaks the resolver. Every read failure is translated here (not left
    to the callers' nets) so read-only ``doctor`` and ``--fix`` both report instead of aborting.

    The would-be change list is identical for ``apply`` True/False (the managed-convergence
    invariant): the auto-generated ``subagent-worktree-default`` doctor check reports drift and
    ``doctor --fix`` repairs it.
    """
    try:
        resolution = launch_pi_agent_dir(root)
    except (ConfigError, tomllib.TOMLDecodeError):
        return []
    if resolution is None:
        return []
    path = resolution.path / "extensions" / "subagent" / "config.json"
    if not path.exists():
        return []
    if not path.is_file():
        raise UserFacingCliError(
            f"{path} is not a regular file (the engine reads it as an incompatible worktree "
            "default)\nFix or remove it, then re-run 'perk init'.",
            error_type="invalid_subagent_config",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserFacingCliError(
            f"{path} could not be read ({exc})\nFix or remove it, then re-run 'perk init'.",
            error_type="invalid_subagent_config",
        ) from exc
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(
            f"{path} is not valid JSON ({exc})\nFix or remove it, then re-run 'perk init'.",
            error_type="invalid_subagent_config",
        ) from exc
    if not isinstance(config, dict):
        raise UserFacingCliError(
            f"{path} must contain a JSON object\nFix or remove it, then re-run 'perk init'.",
            error_type="invalid_subagent_config",
        )
    if "worktree" not in config:
        return []
    previous = config["worktree"]
    if previous is False:
        return []
    config["worktree"] = False
    if apply:
        atomic_write_text(path, json.dumps(config, indent="\t", ensure_ascii=False) + "\n")
    return [f"{path}: worktree={json.dumps(previous)} → false"]
