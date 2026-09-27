"""The session-backed docs verbs' deterministic half (contracts.md §8.75(k)).

``perk librarian add docs`` and the human ``perk librarian refresh <slug>`` of a documentation
entry are write-capable cold doors: mirroring a site is judgment work (scoping, pruning, artifact
fixes), so each launches a curating session. Everything here runs BEFORE that session is paid for
— input validation, the default slug rule, eligibility, the skill/converter prerequisites, the
cache-only preflight, the staging claim — plus the one construction of the commands the session
runs (:class:`DocsCrawlPlan`), so the dry-run and the seed can never disagree about them.

The staging claim is the door's only write: an atomic ``mkdir`` of an empty
``.staging/<slug>[-N]`` directory the session crawls into. The door never deletes a staging
directory — a leftover is ``list``'s to report and the human's to dispose of.
"""

import shlex
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from perk.library.catalog import load_catalog
from perk.library.errors import LibraryError, translating_io
from perk.library.guard import (
    probe_paths_for,
    require_ignored,
    require_no_tracked_content,
    require_real_roots,
    require_unlinked_components,
)
from perk.library.inventory import read_scope_prefix
from perk.library.layout import INVENTORY_FILENAME, SLUG_GRAMMAR, Kind, LibraryLayout, validate_slug
from perk.library.ops import publish_eligibility
from perk.substrate import proc
from perk.substrate.bindings import SKILLS_DIR
from perk.substrate.proc import ProcFailure

CONVERTERS = ("curl", "html2markdown")
HTML2MARKDOWN_INSTALL_HINT = "brew install html2markdown"
CURL_INSTALL_HINT = "install curl"
DRY_RUN_TIMEOUT_SECONDS = 600
LIBRARIAN_SKILL = "librarian"
CRAWL_SCRIPT_NAME = "copy_docs_to_markdown.py"

_CONVERTER_REMEDIES = {
    "curl": CURL_INSTALL_HINT,
    "html2markdown": f"install it ({HTML2MARKDOWN_INSTALL_HINT})",
}

# Module seams, resolved at call time so tests can simulate a missing converter or a failed spawn.
which = shutil.which
run_captured = proc.run_captured


@dataclass(frozen=True)
class DocsCrawlPlan:
    """Everything a docs door hands its session — and the one construction of its commands.

    ``scope_prefix`` is ``""`` when defaulted (the crawl script then derives the seed URL's
    parent path) and otherwise the normalized prefix, root ``/`` included: ``""`` and ``/`` are
    distinct. ``current_dir`` is the published mirror a refresh replaces (``None`` on add).
    """

    url: str
    slug: str
    scope_prefix: str
    staging_dir: Path
    script_path: Path
    python: str
    main_root: Path
    current_dir: Path | None
    replace: bool
    warnings: tuple[str, ...]

    @property
    def crawl_argv(self) -> tuple[str, ...]:
        scope = ("--scope-prefix", self.scope_prefix) if self.scope_prefix else ()
        return (self.python, str(self.script_path), self.url, str(self.staging_dir), *scope)

    @property
    def publish_argv(self) -> tuple[str, ...]:
        return (
            "perk",
            "librarian",
            "record",
            "--publish",
            str(self.staging_dir),
            "--slug",
            self.slug,
            "--source",
            self.url,
            *(("--replace",) if self.replace else ()),
            "--json",
        )

    @property
    def crawl_command(self) -> str:
        """The crawl as one shell-quoted command line (round-trips through ``shlex.split``)."""
        return shlex.join(self.crawl_argv)

    @property
    def publish_command(self) -> str:
        """The publish as one shell-quoted command line (round-trips through ``shlex.split``)."""
        return shlex.join(self.publish_argv)


def derive_slug(url: str) -> str:
    """The default slug: the URL host lowercased, a leading ``www.`` then a leading ``docs.``
    label stripped, the first remaining label (``https://docs.astro.build/`` → ``astro``)."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    host = host.removeprefix("www.").removeprefix("docs.")
    label = host.split(".", 1)[0]
    try:
        return validate_slug(label)
    except LibraryError as exc:
        raise LibraryError(
            "invalid_slug",
            f"cannot derive a slug from {url!r}: the host label {label!r} is not a valid slug "
            f"({SLUG_GRAMMAR}) — pass --slug",
        ) from exc


def validate_scope_prefix(text: str) -> str:
    """The crawl script's scope-prefix normalization, refusing what it would reject.

    Empty segments collapse; a ``.``/``..`` segment, a NUL or any whitespace is ``invalid_input``;
    zero segments is the root scope ``/`` (valid — the crawler accepts and records it). A blank
    value is ``invalid_input``: ``""`` is never a scope, only the "defaulted" marker.
    """
    if not text.strip():
        raise _invalid_scope(text, "it is blank (omit --scope-prefix for the default scope)")
    if "\x00" in text or any(char.isspace() for char in text):
        raise _invalid_scope(text, "it contains whitespace or a NUL byte")
    segments = [segment for segment in text.split("/") if segment]
    if any(segment in (".", "..") for segment in segments):
        raise _invalid_scope(text, "it contains a '.' or '..' segment")
    return "/" + "".join(f"{segment}/" for segment in segments)


def _invalid_scope(text: str, reason: str) -> LibraryError:
    return LibraryError(
        "invalid_input",
        f"invalid --scope-prefix {text!r}: {reason} — use a URL path prefix such as /docs/ "
        "(or / for the whole site)",
    )


def require_converters() -> None:
    """Every converter the crawl needs must be on PATH; one ``missing_converter`` names them all."""
    missing = [tool for tool in CONVERTERS if which(tool) is None]
    if missing:
        raise LibraryError(
            "missing_converter",
            "; ".join(f"`{tool}` is not on PATH — {_CONVERTER_REMEDIES[tool]}" for tool in missing),
        )


def librarian_script_path(main_root: Path) -> Path:
    """The crawl script at the skill's delivery read path, or ``skill_missing``.

    Skills are delivered by the ``skills`` CLI (never bundled into the wheel), so the door reaches
    the script where the launched session will: ``<main>/.agents/skills/librarian/scripts/``.
    """
    path = main_root / SKILLS_DIR / LIBRARIAN_SKILL / "scripts" / CRAWL_SCRIPT_NAME
    if not path.is_file():
        raise LibraryError(
            "skill_missing",
            f"the `{LIBRARIAN_SKILL}` skill is not installed at {path} — run `perk init` (it "
            "syncs perk's skills), then rerun",
        )
    return path


def _staging_candidates(layout: LibraryLayout, slug: str) -> Iterator[Path]:
    yield layout.staging / slug
    suffix = 2
    while True:
        yield layout.staging / f"{slug}-{suffix}"
        suffix += 1


def fresh_staging_dir(layout: LibraryLayout, slug: str) -> Path:
    """The first free staging name (``<slug>``, ``<slug>-2``, …) — a write-free preview."""
    for candidate in _staging_candidates(layout, slug):
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate
    raise AssertionError("unreachable: the candidate sequence is infinite")


def claim_staging_dir(layout: LibraryLayout, slug: str) -> Path:
    """Atomically claim an empty staging directory for one session.

    ``mkdir`` without ``exist_ok`` over ``<slug>``, ``<slug>-2``, …: whatever already occupies a
    name (a directory, a file, a symlink) is skipped, never removed, so two doors opened before
    either crawl never share a directory.
    """
    layout.staging.mkdir(parents=True, exist_ok=True)
    for candidate in _staging_candidates(layout, slug):
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise AssertionError("unreachable: the candidate sequence is infinite")


def entry_kind(repo_root: Path, slug: str) -> Kind | None:
    """The catalogued kind of ``slug`` (lock-free), or ``None`` when no entry has it."""
    with translating_io("refresh"):
        entry = load_catalog(LibraryLayout.for_repo(repo_root)).get(slug)
        return entry.kind if entry is not None else None


def plan_add_docs(
    repo_root: Path, *, url: str, slug: str | None, scope_prefix: str | None, dry_run: bool
) -> DocsCrawlPlan:
    """Every pre-session check of ``add docs``, then the staging directory: claimed for a launch,
    only previewed on ``dry_run`` (nothing written). ``url`` arrives validated."""
    with translating_io("add docs"):
        chosen = validate_slug(slug) if slug is not None else derive_slug(url)
        prefix = validate_scope_prefix(scope_prefix) if scope_prefix is not None else ""
        layout = LibraryLayout.for_repo(repo_root)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        publish_eligibility(layout, load_catalog(layout), slug=chosen, replace=False)
        script = librarian_script_path(layout.main_root)
        require_converters()
        preview = fresh_staging_dir(layout, chosen)
        # The free name, not `.staging/<slug>`: git refuses to probe beyond a symlinked leftover,
        # and every sibling the claim may land on is the same path class.
        require_ignored(
            layout, probe_paths_for(layout, dirs=[preview, layout.docs_entry_dir(chosen)])
        )
        staging = preview if dry_run else claim_staging_dir(layout, chosen)
        return DocsCrawlPlan(
            url=url,
            slug=chosen,
            scope_prefix=prefix,
            staging_dir=staging,
            script_path=script,
            python=sys.executable,
            main_root=layout.main_root,
            current_dir=None,
            replace=False,
            warnings=(),
        )


def plan_refresh_docs(repo_root: Path, *, slug: str) -> DocsCrawlPlan:
    """Every pre-session check of the docs-refresh door, then the claimed staging directory.

    The prior crawl's scope is recovered advisorily from the published mirror's ``sources.json``;
    an unusable recorded value falls back to the default scope with a warning, so the refresh
    never narrows or widens scope silently.
    """
    with translating_io("refresh"):
        layout = LibraryLayout.for_repo(repo_root)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        entry = load_catalog(layout).get(slug)
        if entry is None:
            raise LibraryError("entry_not_found", f"no library entry named {slug}")
        if entry.kind != "docs":
            raise LibraryError(
                "entry_not_found",
                f"{slug} is a {entry.kind} entry, not a documentation entry — `perk librarian "
                f"refresh {slug} --json` refreshes a source checkout",
            )
        current = require_unlinked_components(layout, entry.path)
        script = librarian_script_path(layout.main_root)
        require_converters()
        preview = fresh_staging_dir(layout, slug)
        require_ignored(layout, probe_paths_for(layout, dirs=[preview, current]))
        prefix, warnings = _recorded_scope(current)
        staging = claim_staging_dir(layout, slug)
        return DocsCrawlPlan(
            url=entry.source,
            slug=slug,
            scope_prefix=prefix,
            staging_dir=staging,
            script_path=script,
            python=sys.executable,
            main_root=layout.main_root,
            current_dir=current,
            replace=True,
            warnings=warnings,
        )


def _recorded_scope(mirror: Path) -> tuple[str, tuple[str, ...]]:
    recorded = read_scope_prefix(mirror)
    if recorded is None:
        return "", ()
    try:
        return validate_scope_prefix(recorded), ()
    except LibraryError:
        return "", (
            f"the prior crawl's recorded scope prefix {recorded!r} ({mirror / INVENTORY_FILENAME}) "
            "is unusable — the refresh crawl uses the default scope (the seed URL's parent path) "
            "unless the session passes --scope-prefix",
        )


def run_dry_run(plan: DocsCrawlPlan) -> subprocess.CompletedProcess[str]:
    """Run the crawl script's own dry-run through the plan's exact crawl argv.

    The script's dry-run never inspects or creates the output directory, so nothing is written.
    Every exit code comes back to the caller; a spawn failure or timeout is ``io_error``.
    """
    try:
        return run_captured(
            (*plan.crawl_argv, "--dry-run"), cwd=plan.main_root, timeout=DRY_RUN_TIMEOUT_SECONDS
        )
    except ProcFailure as exc:
        raise LibraryError("io_error", f"the crawl script's dry-run could not run: {exc}") from exc
