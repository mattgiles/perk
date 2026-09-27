"""A thin ``cloc``-shelling gateway — counts the lines of caller-chosen file pairs.

One implementation per plane (cli-vs-pi §3), in the ``git`` / ``npm`` gateway mold: argv and
list-file construction, JSON parse → typed counts, zero policy. The caller (the change-stats
module) owns which files are compared; cloc only counts. Failures raise ``ClocError`` with a
typed ``kind`` the caller maps to its own degrade posture.

The invocation is pinned so nothing outside the call can change the counts (verified against
cloc 2.10's source):

- ``--diff-list-file`` turns on diff mode with no positional targets and hands cloc the exact
  pairs, bypassing its own file alignment (which would otherwise re-pair renames itself).
- ``--config <os.devnull>`` pins an inert configuration: cloc auto-loads
  ``~/.config/cloc/options.txt`` (able to add ``--report-file`` / ``--include-lang`` /
  ``--by-file``), and an explicit ``--config`` also disables its alternate-config lookup
  beside the list file.
- ``--show-errors`` keeps per-file errors visible under ``--quiet`` — cloc otherwise drops a
  failed file's lines silently and still exits 0. The ``N errors:`` block goes to **stderr**
  (cloc's ``print_errors`` uses ``warn``), ahead of the JSON on stdout.
- ``--diff-timeout 0`` lifts cloc's 10 s per-file diff limit (a timed-out file is an error), so
  the only timeout is this gateway's process-level one; ``--hide-rate`` keeps output
  deterministic.

The list file carries paths relative to ``workdir`` (cloc's cwd): cloc silently skips any file
with a ``.git`` / ``.config`` / ``.venv`` / … component anywhere in the path it is given, so an
absolute path under such an ancestor (a ``TMPDIR`` inside ``~/.config``) would vanish from the
counts.
"""

import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from perk.boundary import LenientParseModel, ValidationError
from perk.substrate.fs import atomic_write_text
from perk.substrate.proc import ProcFailure, run_captured

INSTALL_HINT = (
    "Install cloc: brew install cloc (macOS), npm install -g cloc, or your distro package "
    "(https://github.com/AlDanial/cloc)."
)

_TIMEOUT_SECONDS = 120
_ERROR_EXCERPT_CHARS = 300
_PAIRS_FILENAME = "pairs.txt"
# Characters cloc's list-file grammar cannot carry inside a path: `|` splits a compared pair,
# `;` ends the path, a line break ends the record.
_UNREPRESENTABLE = ("|", ";", "\n", "\r")
# cloc's `print_errors` header (`\n1 error:\n` / `\n3 errors:\n`) and its list-file parse
# warning — either means some file's lines are missing from the report.
_ERRORS_RE = re.compile(r"^\s*\d+ errors?:\s*$|parse failure", re.MULTILINE)

type ClocErrorKind = Literal["missing", "spawn", "timeout", "exit", "errors", "parse"]


class ClocError(Exception):
    """cloc could not produce a complete count; ``kind`` classifies why."""

    def __init__(self, kind: ClocErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ClocErrorKind = kind
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Counts:
    files: int
    blank: int
    comment: int
    code: int


@dataclass(frozen=True)
class LanguageDiff:
    """One language's diff counts: lines in added/removed files AND lines added/removed/modified
    inside compared pairs (cloc folds both into the same buckets)."""

    added: Counts
    removed: Counts
    modified: Counts
    same: Counts


@dataclass(frozen=True)
class DiffReport:
    """Per-language rows only (cloc's ``header`` / ``SUM`` are dropped)."""

    languages: Mapping[str, LanguageDiff]


@dataclass(frozen=True)
class DiffPairs:
    """Absolute paths into caller-materialized trees."""

    added: Sequence[Path] = ()
    removed: Sequence[Path] = ()
    compared: Sequence[tuple[Path, Path]] = ()


class _ClocCounts(LenientParseModel):
    files: int = Field(default=0, alias="nFiles")
    blank: int = 0
    comment: int = 0
    code: int = 0

    def to_domain(self) -> Counts:
        return Counts(files=self.files, blank=self.blank, comment=self.comment, code=self.code)


class _ClocDiffJson(LenientParseModel):
    added: dict[str, _ClocCounts] = Field(default_factory=dict)
    removed: dict[str, _ClocCounts] = Field(default_factory=dict)
    modified: dict[str, _ClocCounts] = Field(default_factory=dict)
    same: dict[str, _ClocCounts] = Field(default_factory=dict)


def diff_pairs(pairs: DiffPairs, *, workdir: Path) -> DiffReport:
    """Count ``pairs`` with cloc's diff mode; ``workdir`` holds the list file and is cloc's cwd.

    Raises ``ClocError``: ``missing`` (no ``cloc`` on PATH — never spawns), ``parse`` (a path the
    list grammar cannot carry, or output with no JSON object), ``spawn`` / ``timeout`` /
    ``exit`` (the process failed), ``errors`` (cloc reported per-file errors, so the counts
    would be partial).
    """
    if shutil.which("cloc") is None:
        raise ClocError("missing", f"cloc is not installed. {INSTALL_HINT}")
    workdir.mkdir(parents=True, exist_ok=True)
    list_file = workdir / _PAIRS_FILENAME
    atomic_write_text(list_file, render_list_file(pairs, workdir=workdir))
    argv = [
        "cloc",
        "--diff-list-file",
        str(list_file),
        "--json",
        "--quiet",
        "--show-errors",
        "--hide-rate",
        "--ignore-whitespace",
        "--diff-timeout",
        "0",
        "--config",
        os.devnull,
    ]
    try:
        proc = run_captured(argv, cwd=workdir, timeout=_TIMEOUT_SECONDS)
    except ProcFailure as exc:
        kind: ClocErrorKind = "timeout" if exc.kind == "timeout" else "spawn"
        raise ClocError(kind, str(exc)) from exc
    if proc.returncode != 0:
        raise ClocError("exit", proc.stderr.strip() or f"cloc exited {proc.returncode}")
    return parse_diff_output(proc.stdout, proc.stderr)


def render_list_file(pairs: DiffPairs, *, workdir: Path) -> str:
    """cloc's ``--diff-list-file`` grammar (``file_pairs_from_file``), paths relative to
    ``workdir``. The trailing `` ; -`` is required by cloc's added/removed regex
    (``^\\s*[+-]\\s+(.*?)\\s+;``) and ignored by its language logic."""
    lines = [f"Files added: {len(pairs.added)}"]
    lines += [f"+ {_listed(path, workdir)} ; -" for path in pairs.added]
    lines += ["", f"Files removed: {len(pairs.removed)}"]
    lines += [f"- {_listed(path, workdir)} ; -" for path in pairs.removed]
    lines += ["", f"File pairs compared: {len(pairs.compared)}"]
    lines += [
        f"!= {_listed(left, workdir)} | {_listed(right, workdir)} ; -"
        for left, right in pairs.compared
    ]
    return "\n".join(lines) + "\n"


def representable(path: str) -> bool:
    """Whether cloc's list-file grammar can carry ``path`` unchanged: no ``|`` / ``;`` / line
    break, and no leading/trailing whitespace (cloc trims both)."""
    return not any(char in path for char in _UNREPRESENTABLE) and path == path.strip()


def _listed(path: Path, workdir: Path) -> str:
    if not representable(str(path)):
        raise ClocError("parse", f"path cannot be expressed in a cloc list file: {str(path)!r}")
    return os.path.relpath(path, workdir)


def parse_diff_output(stdout: str, stderr: str = "") -> DiffReport:
    """Parse cloc's ``--json`` diff output. Reported per-file errors (stderr's ``N errors:``
    block) or any text outside the JSON object raise ``errors`` — partial counts are never
    reported as complete. A bare ``{}`` (cloc's empty report) is an empty ``DiffReport``."""
    errors = _ERRORS_RE.search(stderr)
    if errors is not None:
        raise ClocError("errors", _excerpt(stderr[errors.start() :]))
    start = stdout.find("{")
    if start == -1:
        raise ClocError("parse", f"cloc printed no JSON: {_excerpt(stdout) or '(empty)'}")
    end = stdout.rfind("}") + 1
    outside = (stdout[:start] + stdout[end:]).strip()
    if outside:
        raise ClocError("errors", _excerpt(outside))
    try:
        parsed = _ClocDiffJson.model_validate_json(stdout[start:end])
    except ValidationError as exc:
        raise ClocError("parse", f"unexpected cloc JSON: {_excerpt(str(exc))}") from exc
    zero = _ClocCounts()
    names = sorted({*parsed.added, *parsed.removed, *parsed.modified, *parsed.same})
    return DiffReport(
        languages={
            name: LanguageDiff(
                added=parsed.added.get(name, zero).to_domain(),
                removed=parsed.removed.get(name, zero).to_domain(),
                modified=parsed.modified.get(name, zero).to_domain(),
                same=parsed.same.get(name, zero).to_domain(),
            )
            for name in names
        }
    )


def _excerpt(text: str) -> str:
    return text.strip()[:_ERROR_EXCERPT_CHARS]
