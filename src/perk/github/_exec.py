"""The shared ``gh``-shelling helper family (the gateway's canonical patch point).

Every submodule binds this **module** (``from perk.github import _exec``) and calls
``_exec._run`` / ``_exec._failed`` / … so there is exactly one patch point per name.
"""

import json
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from perk.substrate.proc import ProcFailure, run_captured

# Reads are quick; writes (issue/comment create) are slower — a longer ceiling (D5).
_READ_TIMEOUT = 15
_WRITE_TIMEOUT = 30


class GitHubError(Exception):
    """The ``gh`` binary is missing or produced unparseable output."""


def _opt_str(value: object) -> str | None:
    """A GraphQL/JSON field read as a string, else ``None`` (tolerant -- never raises)."""
    return value if isinstance(value, str) else None


def _opt_int(value: object) -> int | None:
    """A GraphQL/JSON field read as an int, else ``None`` (tolerant; ``bool`` is rejected since a
    GraphQL ``Int`` is never a bool)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _opt_dict(value: object) -> dict[str, object] | None:
    """A GraphQL/JSON field read as a dict, else ``None`` (tolerant). The ``cast`` confines the
    documented ty isinstance-narrowing quirk to this leaf (mirroring
    ``backends.linear.client._opt_dict``) so the parse modules stay cast-free."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _dicts(value: object) -> list[dict[str, object]]:
    """The dict elements of a list payload (non-dicts skipped); ``[]`` when not a list."""
    if not isinstance(value, list):
        return []
    return [cast("dict[str, object]", n) for n in value if isinstance(n, dict)]


def _run(
    args: list[str], *, cwd: Path | None = None, timeout: int = _READ_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` capturing output. ``gh`` missing / unspawnable / a timeout -> ``GitHubError``.

    Non-zero exits are the callers' policy (``_failed``/``_run_json`` inspect returncode).
    """
    try:
        return run_captured(["gh", *args], cwd=cwd, timeout=timeout)
    except ProcFailure as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise GitHubError("gh not found on PATH") from exc
        raise GitHubError(str(exc)) from exc


@contextmanager
def _body_file(content: str) -> Iterator[str]:
    """Write ``content`` to a temp file for ``-F body=@<path>`` (never inline). Cleaned up."""
    with tempfile.NamedTemporaryFile(
        "w", prefix="perk-body-", suffix=".md", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(content)
        path = handle.name
    try:
        yield path
    finally:
        Path(path).unlink()


def _failed(proc: subprocess.CompletedProcess[str], what: str) -> GitHubError:
    return GitHubError(f"{what}: {(proc.stderr + proc.stdout).strip() or 'no output'}")


def _owner_repo(repo_root: Path) -> tuple[str, str]:
    """The ``(owner, repo)`` pair (for GraphQL variables; REST uses gh's auto-fill placeholders)."""
    proc = _run(
        ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo_root
    )
    if proc.returncode != 0 or "/" not in proc.stdout:
        raise _failed(proc, "failed to resolve owner/repo")
    owner, _, name = proc.stdout.strip().partition("/")
    return owner, name


def _is_not_found(proc: subprocess.CompletedProcess[str]) -> bool:
    """Did a failed ``gh`` call report a missing resource (a lookup miss)?

    Covers both REST 404s (``"not found"`` / ``"404"``) and the GraphQL not-found shape, which
    reports neither: ``gh api graphql`` on a missing node exits non-zero with
    ``Could not resolve to an Issue …`` (stderr) + an ``"errors":[{"type":"NOT_FOUND"…}]`` body
    (stdout) — lowercased ``not_found`` (underscore) / ``could not resolve to``.
    """
    haystack = (proc.stderr + proc.stdout).lower()
    return (
        "not found" in haystack
        or "not_found" in haystack
        or "could not resolve to" in haystack
        or "404" in haystack
    )


def _parse_json(
    proc: subprocess.CompletedProcess[str], *, source: str, default: str | None = None
) -> Any:
    """Parse a ``gh`` call's stdout as JSON (``default`` substitutes an empty stdout when given).

    Unparseable output raises ``GitHubError``; post-parse type narrowing stays with the caller
    (the fallback behavior differs per site: raise vs ``None`` vs ``()``).
    """
    text = proc.stdout if default is None else (proc.stdout or default)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable {source} output: {exc}") from exc


def _run_json(
    args: list[str],
    *,
    what: str,
    source: str,
    cwd: Path | None = None,
    timeout: int = _READ_TIMEOUT,
    default: str | None = None,
    none_on_not_found: bool = False,
) -> Any | None:
    """``_run`` + the shared returncode/not-found/parse pipeline.

    A non-zero exit raises ``_failed(proc, what)`` — except when ``none_on_not_found`` is set and
    the failure is a 404/"not found" lookup miss, which returns ``None`` (the lookup convention:
    lookups return ``... | None``, mutations raise).
    """
    proc = _run(args, cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        if none_on_not_found and _is_not_found(proc):
            return None
        raise _failed(proc, what)
    return _parse_json(proc, source=source, default=default)


def _graphql_proc(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _READ_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a ``gh api graphql`` call. String vars via ``-f``, numeric via ``-F`` (typed). Returns
    the raw proc (callers decide raise-vs-capture)."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in (str_vars or {}).items():
        args += ["-f", f"{key}={value}"]
    for key, value in (int_vars or {}).items():
        args += ["-F", f"{key}={value}"]
    return _run(args, cwd=repo_root, timeout=timeout)


def _graphql(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _READ_TIMEOUT,
    what: str,
) -> dict[str, object]:
    """``_graphql_proc`` + raise-on-failure + parse (the read-op convention)."""
    proc = _graphql_proc(
        query, repo_root=repo_root, str_vars=str_vars, int_vars=int_vars, timeout=timeout
    )
    if proc.returncode != 0:
        raise _failed(proc, what)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable graphql output ({what}): {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"unexpected graphql payload ({what}): {data!r}")
    return data


def _rest_args(
    path: str,
    *,
    method: str,
    fields: dict[str, str] | None = None,
    body_path: str | None = None,
    jq: str | None = None,
) -> list[str]:
    """Build a REST ``gh api`` argv in the gateway's standing shape: ``-X`` after the path,
    ``-f`` fields in order, the body file via ``-F body=@…``, ``--jq`` last."""
    args = ["api", path, "-X", method]
    for key, value in (fields or {}).items():
        args += ["-f", f"{key}={value}"]
    if body_path is not None:
        args += ["-F", f"body=@{body_path}"]
    if jq is not None:
        args += ["--jq", jq]
    return args
