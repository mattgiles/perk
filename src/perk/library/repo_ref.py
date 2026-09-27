"""The repo-ref grammar: the user-facing spelling of a source repository (contracts.md §8.75(i)).

:func:`parse_repo_ref` is pure (no I/O). It normalises one of four accepted shapes to a
:class:`RepoRef` — the ``source-code/<host>/<org>/<repo>`` entry path segments plus the clone URL
the catalog records as the entry's ``source``. The same input always yields the same clone URL,
so a rerun compares equal to the checkout's stored origin URL. Deeper paths (``/tree/main``,
GitLab subgroups), ports, credentials and query strings are refused rather than guessed at.
"""

import re
import urllib.parse
from dataclasses import dataclass

from perk.library.errors import LibraryError
from perk.library.layout import SLUG_GRAMMAR, SOURCE_SEGMENT_RE, source_entry_path, validate_slug

_ACCEPTED_SHAPES = (
    "<org>/<repo> (GitHub), <host>/<org>/<repo>, https://<host>/<org>/<repo>[.git] "
    "(also http:// and ssh://[user@]<host>/<org>/<repo>), or git@<host>:<org>/<repo>[.git]"
)
_SCP_RE = re.compile(r"git@(?P<host>[^:/@]+):(?P<path>[^:]+)")
_URL_SCHEMES = frozenset({"https", "http", "ssh"})


@dataclass(frozen=True)
class RepoRef:
    """A normalised repo-ref: ``host`` lowercased, ``org``/``repo`` case-preserved, ``repo``
    without a trailing ``.git``."""

    host: str
    org: str
    repo: str
    clone_url: str

    @property
    def path(self) -> str:
        """The catalog entry path, ``source-code/<host>/<org>/<repo>``."""
        return source_entry_path(self.host, self.org, self.repo)

    @property
    def default_slug(self) -> str:
        """``repo`` lowercased; ``invalid_slug`` (asking for ``--slug``) outside the grammar."""
        candidate = self.repo.lower()
        try:
            return validate_slug(candidate)
        except LibraryError as exc:
            raise LibraryError(
                "invalid_slug",
                f"the repository name {self.repo!r} does not make a valid slug ({SLUG_GRAMMAR}) "
                "— pass --slug",
            ) from exc


def parse_repo_ref(text: str) -> RepoRef:
    """Normalise ``text`` to a :class:`RepoRef`; anything outside the grammar is
    ``invalid_repo_ref``.

    Shapes, tried in order: scp-like ``git@<host>:<org>/<repo>``; an ``https``/``http``/``ssh``
    URL of exactly ``/<org>/<repo>``; bare ``<org>/<repo>`` (GitHub); bare
    ``<host>/<org>/<repo>`` (the host carries a ``.``).
    """
    stripped = text.strip()
    scp = _SCP_RE.fullmatch(stripped)
    if scp is not None:
        host = scp.group("host").lower()
        org, repo = _two_segments(scp.group("path"), text)
        return _checked(text, host, org, repo, f"git@{host}:{org}/{repo}.git")
    if "://" in stripped:
        return _parse_url(stripped, text)
    if ":" in stripped or "@" in stripped:
        raise _invalid(text)
    segments = _trimmed(stripped).split("/")
    if len(segments) == 2:
        org, repo = segments
        return _checked(text, "github.com", org, repo, f"https://github.com/{org}/{repo}.git")
    if len(segments) == 3 and "." in segments[0]:
        host = segments[0].lower()
        org, repo = segments[1], segments[2]
        return _checked(text, host, org, repo, f"https://{host}/{org}/{repo}.git")
    raise _invalid(text)


def _parse_url(stripped: str, text: str) -> RepoRef:
    try:
        parts = urllib.parse.urlsplit(stripped)
    except ValueError as exc:  # e.g. an unmatched IPv6 bracket
        raise _invalid(text) from exc
    if parts.scheme not in _URL_SCHEMES or not parts.netloc or parts.query or parts.fragment:
        raise _invalid(text)
    userinfo, at, host_part = parts.netloc.rpartition("@")
    if at and parts.scheme != "ssh":
        # Credentials never reach the catalog; only ssh URLs carry a (login) user.
        raise _invalid(text)
    host = host_part.lower()
    netloc = f"{userinfo}@{host}" if at else host
    org, repo = _two_segments(parts.path, text)
    return _checked(text, host, org, repo, f"{parts.scheme}://{netloc}/{org}/{repo}.git")


def _trimmed(path: str) -> str:
    """``path`` without leading/trailing ``/`` and a trailing ``.git``."""
    return path.strip("/").removesuffix(".git")


def _two_segments(path: str, text: str) -> tuple[str, str]:
    segments = _trimmed(path).split("/")
    if len(segments) != 2:
        raise _invalid(text)
    return segments[0], segments[1]


def _checked(text: str, host: str, org: str, repo: str, clone_url: str) -> RepoRef:
    for segment in (host, org, repo):
        if SOURCE_SEGMENT_RE.fullmatch(segment) is None or ".." in segment:
            raise _invalid(text)
    return RepoRef(host=host, org=org, repo=repo, clone_url=clone_url)


def _invalid(text: str) -> LibraryError:
    return LibraryError(
        "invalid_repo_ref", f"invalid repository reference {text!r}: use {_ACCEPTED_SHAPES}"
    )
