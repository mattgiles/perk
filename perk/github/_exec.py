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
from typing import Any

# Reads are quick; writes (issue/comment create) are slower — a longer ceiling (D5).
_READ_TIMEOUT = 15
_WRITE_TIMEOUT = 30


class GitHubError(Exception):
    """The ``gh`` binary is missing or produced unparseable output."""


def _run(
    args: list[str], *, cwd: Path | None = None, timeout: int = _READ_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` capturing output. ``gh`` missing / a timeout -> ``GitHubError``."""
    try:
        return subprocess.run(
            ["gh", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise GitHubError("gh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHubError(f"gh {' '.join(args)} timed out") from exc


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
    """Did a failed ``gh`` call report a missing resource (a 404 / "not found" lookup miss)?"""
    haystack = (proc.stderr + proc.stdout).lower()
    return "not found" in haystack or "404" in haystack


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
