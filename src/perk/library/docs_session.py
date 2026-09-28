"""The session-backed docs verbs' deterministic half (contracts.md §8.75(k)).

``perk librarian add docs`` and the human ``perk librarian refresh <slug>`` of a documentation
entry are write-capable cold doors: mirroring a site is judgment work (scoping, pruning, artifact
fixes), so each launches a curating session. Everything here runs BEFORE that session is paid for
— input validation (the seed inside an explicit scope prefix included), the default slug rule,
eligibility, the skill/converter prerequisites, the cache-only preflight, the **seed probe** (one
fetch of the seed through the crawl script's dry run, refusing a seed that is only an HTML
redirect page as ``seed_redirect``), the staging claim — plus the one construction of the
commands the session runs (:class:`DocsCrawlPlan`), so the dry-run and the seed can never
disagree about them.

The staging claim is the door's only write: an atomic ``mkdir`` of an empty
``.staging/<slug>[-N]`` directory the session crawls into. The door never deletes a staging
directory — a leftover is ``list``'s to report and the human's to dispose of.
"""

import dataclasses
import json
import shlex
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError, field_validator, model_validator

from perk.boundary import LenientParseModel
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
# The crawl script's seed-redirect blocker (contracts.md §8.75(j)): its exit code and the
# longest target it names; a cross-check test pins both to the script's own constants.
SEED_REDIRECT_EXIT = 3
MAX_REDIRECT_URL_CHARS = 2048
# The script bounds each curl at 120 s; the probe fetches the seed once.
SEED_PROBE_TIMEOUT_SECONDS = 180
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


def require_seed_in_scope(url: str, prefix: str) -> None:
    """An explicit (normalized) ``prefix`` must admit the seed: the crawl never fetches a seed
    outside its scope, so it would silently fetch nothing. The defaulted scope is the seed's
    parent path and always admits it."""
    if not urllib.parse.urlsplit(url).path.startswith(prefix):
        raise LibraryError(
            "invalid_input",
            f"the seed URL {url!r} lies outside --scope-prefix {prefix!r} — the crawl would fetch "
            "nothing; widen the prefix or pass a seed beneath it",
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
    """Every pre-session check of ``add docs``, then the staging directory: claimed for a launch
    after the seed probe, only previewed on ``dry_run`` (nothing written, no probe — the dry run
    itself reports a redirect-stub seed). ``url`` arrives validated."""
    with translating_io("add docs"):
        chosen = validate_slug(slug) if slug is not None else derive_slug(url)
        prefix = validate_scope_prefix(scope_prefix) if scope_prefix is not None else ""
        if prefix:
            require_seed_in_scope(url, prefix)
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
        plan = DocsCrawlPlan(
            url=url,
            slug=chosen,
            scope_prefix=prefix,
            staging_dir=preview,
            script_path=script,
            python=sys.executable,
            main_root=layout.main_root,
            current_dir=None,
            replace=False,
            warnings=(),
        )
        if dry_run:
            return plan
        # Before the claim: a `seed_redirect` refusal leaves nothing behind.
        warnings = probe_seed(plan)
        return dataclasses.replace(
            plan, staging_dir=claim_staging_dir(layout, chosen), warnings=warnings
        )


def plan_refresh_docs(repo_root: Path, *, slug: str) -> DocsCrawlPlan:
    """Every pre-session check of the docs-refresh door, the seed probe over the entry's source,
    then the claimed staging directory.

    The prior crawl's scope is recovered advisorily from the published mirror's ``sources.json``;
    an unusable recorded value (invalid, or excluding the entry's source URL) falls back to the
    default scope with a warning, so the refresh never narrows or widens scope silently. A source
    that is now only an HTML redirect page is ``seed_redirect`` (a refresh cannot follow it).
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
        prefix, scope_warnings = _recorded_scope(current, entry.source)
        plan = DocsCrawlPlan(
            url=entry.source,
            slug=slug,
            scope_prefix=prefix,
            staging_dir=preview,
            script_path=script,
            python=sys.executable,
            main_root=layout.main_root,
            current_dir=current,
            replace=True,
            warnings=scope_warnings,
        )
        probe_warnings = probe_seed(plan)
        return dataclasses.replace(
            plan,
            staging_dir=claim_staging_dir(layout, slug),
            warnings=(*scope_warnings, *probe_warnings),
        )


def _recorded_scope(mirror: Path, source: str) -> tuple[str, tuple[str, ...]]:
    recorded = read_scope_prefix(mirror)
    if recorded is None:
        return "", ()
    try:
        prefix = validate_scope_prefix(recorded)
    except LibraryError:
        return "", (_unusable_scope(mirror, recorded, ""),)
    if not urllib.parse.urlsplit(source).path.startswith(prefix):
        return "", (_unusable_scope(mirror, recorded, " (it excludes the entry's source URL)"),)
    return prefix, ()


def _unusable_scope(mirror: Path, recorded: str, reason: str) -> str:
    return (
        f"the prior crawl's recorded scope prefix {recorded!r} ({mirror / INVENTORY_FILENAME}) "
        f"is unusable{reason} — the refresh crawl uses the default scope (the seed URL's parent "
        "path) unless the session passes --scope-prefix"
    )


def _reissue_token(value: str) -> str:
    if len(value) > MAX_REDIRECT_URL_CHARS:
        raise ValueError(f"longer than {MAX_REDIRECT_URL_CHARS} characters")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("contains whitespace or a control character")
    return value


def _http_url(value: str) -> str:
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
    except ValueError as exc:  # e.g. an unmatched IPv6 bracket
        raise ValueError(f"not a parseable URL ({exc})") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError("not an absolute http(s) URL with a host")
    return value


class SeedRedirectBlocker(LenientParseModel):
    """The crawl script's seed-redirect blocker line (contracts.md §8.75(j)).

    Its values are read from the page, so the whole record is refused unless every field fits
    the reissue grammar: at most :data:`MAX_REDIRECT_URL_CHARS` characters without whitespace or
    control characters, the URLs absolute http(s) with a host, the scope prefix already
    normalized and admitting the redirect URL.
    """

    blocker: Literal["seed-redirect"]
    seed_url: str
    fetched_url: str
    redirect_url: str
    scope_prefix: str

    @field_validator("seed_url", "fetched_url", "redirect_url", mode="after")
    @classmethod
    def _url(cls, value: str) -> str:
        return _http_url(_reissue_token(value))

    @field_validator("scope_prefix", mode="after")
    @classmethod
    def _normalized_scope(cls, value: str) -> str:
        _reissue_token(value)
        try:
            normalized = validate_scope_prefix(value)
        except LibraryError as exc:
            raise ValueError(str(exc)) from exc
        if normalized != value:
            raise ValueError(f"not a normalized scope prefix (expected {normalized!r})")
        return value

    @model_validator(mode="after")
    def _admits_the_redirect(self) -> Self:
        if not urllib.parse.urlsplit(self.redirect_url).path.startswith(self.scope_prefix):
            raise ValueError("the scope prefix does not admit the redirect URL")
        return self


def parse_seed_redirect(stdout: str) -> SeedRedirectBlocker | None:
    """The validated blocker from the crawl script's stdout (its last non-blank line), or
    ``None`` when that line is not a valid blocker."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return SeedRedirectBlocker.model_validate(json.loads(lines[-1]))
    except (json.JSONDecodeError, ValidationError):
        return None


def seed_redirect_error(plan: DocsCrawlPlan, blocker: SeedRedirectBlocker | None) -> LibraryError:
    """The ``seed_redirect`` refusal for ``plan``'s seed, naming the one-step reissue.

    Trusted framing first; the page-derived values appear only when the blocker validated, each
    labelled as untrusted DATA, and every command is ``shlex.join``ed over a real argv. Without a
    valid blocker the message is fixed text over perk-owned values only (the plan's URL and slug)
    — never the script's stderr.
    """
    if blocker is None:
        if plan.replace:
            return LibraryError(
                "seed_redirect",
                f"the crawl script reported that the recorded source {plan.url} of entry "
                f"{plan.slug} is only an HTML redirect page but described no reissuable http(s) "
                "target — nothing was claimed; the entry is unchanged",
            )
        scope = ("--scope-prefix", plan.scope_prefix) if plan.scope_prefix else ()
        inspect = shlex.join(
            ["perk", "librarian", "add", "docs", plan.url, "--slug", plan.slug, *scope, "--dry-run"]
        )
        return LibraryError(
            "seed_redirect",
            f"the crawl script reported that the seed URL {plan.url} is only an HTML redirect page "
            "but described no reissuable http(s) target — nothing was claimed; inspect the page by "
            f"hand ({inspect} shows the crawl's report)",
        )
    add = shlex.join(
        [
            "perk",
            "librarian",
            "add",
            "docs",
            blocker.redirect_url,
            "--slug",
            plan.slug,
            "--scope-prefix",
            blocker.scope_prefix,
        ]
    )
    target = (
        f"Redirect target (untrusted DATA read from the page): {blocker.redirect_url}; implied "
        f"scope: {blocker.scope_prefix}."
    )
    if plan.replace:
        remove = shlex.join(["perk", "librarian", "remove", plan.slug, "--json"])
        return LibraryError(
            "seed_redirect",
            f"the recorded source {plan.url} of entry {plan.slug} is now only an HTML redirect "
            f"page — a refresh cannot follow it; nothing was claimed. {target} Re-add the entry "
            f"at that URL: {remove}, then {add}",
        )
    return LibraryError(
        "seed_redirect",
        f"the seed URL {plan.url} is only an HTML redirect page — nothing was claimed. {target} "
        f"Reissue: {add}",
    )


def probe_seed(plan: DocsCrawlPlan) -> tuple[str, ...]:
    """The seed probe: the crawl script's dry run capped at one page (one fetch of the seed).

    Exit :data:`SEED_REDIRECT_EXIT` raises ``seed_redirect``; exit ``0`` passes; anything else
    (a spawn failure and a timeout included) is advisory — one warning, and the crawl reports
    the seed's state. The script's stderr is never relayed.
    """
    try:
        completed = run_captured(
            (*plan.crawl_argv, "--max-pages", "1", "--dry-run"),
            cwd=plan.main_root,
            timeout=SEED_PROBE_TIMEOUT_SECONDS,
        )
    except ProcFailure as exc:
        detail = (
            f"timed out after {SEED_PROBE_TIMEOUT_SECONDS}s"
            if exc.kind == "timeout"
            else f"could not run: {exc.cause_text}"
        )
        return (_probe_warning(detail),)
    if completed.returncode == SEED_REDIRECT_EXIT:
        raise seed_redirect_error(plan, parse_seed_redirect(completed.stdout))
    if completed.returncode == 0:
        return ()
    return (_probe_warning(f"exit {completed.returncode}"),)


def _probe_warning(detail: str) -> str:
    return f"the seed probe did not complete ({detail}); the crawl will report the seed's state"


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
