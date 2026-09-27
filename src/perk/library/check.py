"""``check`` — the library's only freshness probe (contracts.md §8.75(i)).

Lock-free probing, one locked apply. Each selected entry is classified first — ``pinned``
(never probed), ``missing`` (no directory), ``recent`` (inside its ``stale_after`` window,
unless ``force``) — and every other entry is probed over the network: a source entry by
``git ls-remote`` of its default branch, a docs entry by bounded conditional requests plus the
sitemap/``llms.txt`` inventory fingerprint. The observations are then applied under the library
lock, each only when the catalogued entry still equals the snapshot it was probed from (so an
older observation never overwrites a newer one).

Markers are the mirror's revision: a probe baselines a marker the catalog did not yet hold and
never overwrites a recorded one; ``drifted`` is recomputed when the probe yields evidence,
retained when an earlier comparison was not re-observed, and kept when there is no evidence.
"""

import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx

from perk.library.catalog import (
    Catalog,
    Clock,
    DocsUpstream,
    Entry,
    Evidence,
    PageMarker,
    SourceUpstream,
    format_ts,
    load_catalog,
    parse_ts,
    utc_now,
    write_catalog,
)
from perk.library.errors import LibraryError, translating_io
from perk.library.guard import require_ignored, require_no_tracked_content, require_real_roots
from perk.library.layout import LibraryLayout
from perk.library.lock import library_lock
from perk.library.ops import EntryView, entry_view
from perk.library.probe import (
    DOCS_ENTRY_BUDGET,
    DOCS_PAGE_PROBE_LIMIT,
    PAGE_ERROR_STOP,
    SITEMAP_CHILD_LIMIT,
    HttpProbe,
    PageResponse,
    ProbeError,
    TextResponse,
    inventory_fingerprint,
    parse_sitemap,
)
from perk.library.source import hooks_dir
from perk.substrate import git

type CheckAction = Literal["probed", "pinned", "recent", "missing", "failed"]

_CHANGED_MEANWHILE = "entry changed or was checked meanwhile — rerun"


@dataclass(frozen=True)
class CheckResult:
    action: CheckAction
    detail: str | None
    notes: tuple[str, ...]
    view: EntryView


@dataclass(frozen=True)
class CheckOutcome:
    results: tuple[CheckResult, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _Probed:
    """One entry's probe: ``updated is None`` means the probe failed (``detail``)."""

    updated: Entry | None
    detail: str | None
    notes: tuple[str, ...]


def check_entries(
    repo_root: Path,
    *,
    slugs: Sequence[str],
    force: bool,
    now: Clock | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CheckOutcome:
    """Probe the selected entries (every entry when ``slugs`` is empty) and record the
    observations. A completed run reports per-entry ``failed`` results rather than raising;
    only whole-command refusals raise."""
    with translating_io("check"):
        layout = LibraryLayout.for_repo(repo_root)
        catalog = load_catalog(layout) if layout.root.is_dir() else Catalog()
        selected = _select(catalog, slugs)
        if not selected:
            return CheckOutcome(results=(), warnings=())
        require_real_roots(layout)
        require_no_tracked_content(layout)
        require_ignored(layout, [])
        moment = (now or utc_now)()
        results: list[CheckResult] = []
        updates: dict[int, tuple[Entry, Entry, tuple[str, ...]]] = {}
        with HttpProbe(transport=transport) as http, hooks_dir() as hooks:
            for index, entry in enumerate(selected):
                skipped = _classify(layout, entry, moment, force=force)
                if skipped is not None:
                    results.append(skipped)
                    continue
                checkout = layout.root / entry.path
                probed = (
                    _probe_source(entry, checkout, hooks, moment)
                    if entry.kind == "source"
                    else _probe_docs(entry, http, moment)
                )
                view = entry_view(layout, probed.updated or entry, moment)
                if probed.updated is None:
                    results.append(CheckResult("failed", probed.detail, probed.notes, view))
                    continue
                results.append(CheckResult("probed", probed.detail, probed.notes, view))
                updates[index] = (entry, probed.updated, probed.notes)
        warnings = _apply(repo_root, layout, updates, results, moment) if updates else []
        return CheckOutcome(results=tuple(results), warnings=tuple(warnings))


def _select(catalog: Catalog, slugs: Sequence[str]) -> list[Entry]:
    """The named entries in the given order (deduplicated), else every entry by slug."""
    if not slugs:
        return sorted(catalog.entries, key=lambda entry: entry.slug)
    names = list(dict.fromkeys(slugs))
    unknown = [name for name in names if catalog.get(name) is None]
    if unknown:
        raise LibraryError("entry_not_found", f"no library entry named {', '.join(unknown)}")
    return [entry for name in names if (entry := catalog.get(name)) is not None]


def _classify(
    layout: LibraryLayout, entry: Entry, now: datetime, *, force: bool
) -> CheckResult | None:
    """The lock-free skip classification (``None`` = probe it)."""
    view = entry_view(layout, entry, now)
    if entry.kind == "source" and entry.ref is not None:
        return CheckResult("pinned", f"pinned at {entry.ref} — never probed", (), view)
    if not view.present:
        detail = (
            f"the checkout is missing — `perk librarian add source {entry.source}` re-clones it"
            if entry.kind == "source"
            else "the mirror is missing — re-crawl and `perk librarian record --publish <dir> "
            f"--slug {entry.slug} --source {entry.source} --replace`"
        )
        return CheckResult("missing", detail, (), view)
    if not force and entry.checked_at is not None:
        age = int((now - parse_ts(entry.checked_at)).total_seconds())
        if age < entry.stale_after:
            detail = (
                f"checked {_duration(max(age, 0))} ago, window {_duration(entry.stale_after)} — "
                "pass --force to probe anyway"
            )
            return CheckResult("recent", detail, (), view)
    return None


def _duration(seconds: int) -> str:
    """``seconds`` floored to its largest whole unit (``3d``, ``5h``, ``12m``, ``40s``)."""
    for unit, size in (("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _probe_source(entry: Entry, checkout: Path, hooks: Path, now: datetime) -> _Probed:
    """``ls-remote`` the recorded upstream's default branch against the recorded HEAD."""
    recorded = entry.upstream if isinstance(entry.upstream, SourceUpstream) else SourceUpstream()
    branch = recorded.branch or git.detect_trunk_branch(checkout)
    try:
        # The catalogued URL, not the checkout's own `origin`: the catalog is the authority.
        sha = git.remote_branch_head(checkout, branch, remote=entry.source, pinned=hooks)
    except git.GitError as exc:
        return _Probed(updated=None, detail=str(exc), notes=())
    checked_at = format_ts(now)
    if sha is None:
        note = f"refs/heads/{branch} absent on origin"
        return _Probed(
            updated=replace(entry, checked_at=checked_at, evidence="none"),
            detail=None,
            notes=(note,),
        )
    if recorded.head_sha is None:
        upstream = SourceUpstream(branch=branch, head_sha=sha)
        return _Probed(
            updated=replace(
                entry, upstream=upstream, checked_at=checked_at, evidence="strong", drifted=False
            ),
            detail=None,
            notes=(),
        )
    return _Probed(
        updated=replace(
            entry, checked_at=checked_at, evidence="strong", drifted=sha != recorded.head_sha
        ),
        detail=None,
        notes=(),
    )


@dataclass
class _DocsRun:
    """One docs entry's request accounting: the wall-clock budget, notes and errors."""

    http: HttpProbe
    started: float
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests: int = 0
    exhausted: bool = False

    def within_budget(self) -> bool:
        if not self.exhausted and self.http.clock() - self.started > DOCS_ENTRY_BUDGET:
            self.exhausted = True
            self.notes.append(
                f"entry budget of {DOCS_ENTRY_BUDGET:g}s exceeded — remaining requests skipped"
            )
        return not self.exhausted

    def text(self, url: str) -> TextResponse | None:
        """``None`` when skipped for the budget or the request raised (noted)."""
        if not self.within_budget():
            return None
        self.requests += 1
        try:
            response = self.http.text(url)
        except ProbeError as exc:
            self.errors.append(str(exc))
            self.notes.append(str(exc))
            return None
        if response.status == 200 and response.body is None:
            self.notes.append(f"{url}: body over the inventory size limit — not read")
        return response

    def page(self, marker: PageMarker) -> PageResponse | None:
        """``None`` when the request raised (noted)."""
        self.requests += 1
        try:
            return self.http.page(marker.url, etag=marker.etag, last_modified=marker.last_modified)
        except ProbeError as exc:
            self.errors.append(str(exc))
            self.notes.append(str(exc))
            return None


def _site_root(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _inventory(run: _DocsRun, root: str) -> tuple[dict[str, str | None], str | None]:
    """The sitemap's ``loc → lastmod`` map and the inventory fingerprint — ``None`` unless every
    inventory request answered definitively (a partial inventory is never compared)."""
    definitive = True
    urls: list[tuple[str, str | None]] = []
    response = run.text(f"{root}sitemap.xml")
    if response is not None and response.status == 404:
        response = run.text(f"{root}sitemap-index.xml")
    definitive &= _definitive(response)
    if response is not None and response.status == 200 and response.body is not None:
        doc = parse_sitemap(response.body)
        if doc is None:
            run.notes.append(f"{root}: the sitemap is not parseable — ignored")
        else:
            urls.extend(doc.urls)
            if len(doc.children) > SITEMAP_CHILD_LIMIT:
                run.notes.append(
                    f"sitemap index lists {len(doc.children)} sitemaps — only the first "
                    f"{SITEMAP_CHILD_LIMIT} are read"
                )
            for child in doc.children[:SITEMAP_CHILD_LIMIT]:
                child_response = run.text(child)
                definitive &= _definitive(child_response)
                if child_response is None or child_response.body is None:
                    continue
                child_doc = parse_sitemap(child_response.body)
                if child_doc is None:
                    run.notes.append(f"{child}: the sitemap is not parseable — ignored")
                else:
                    urls.extend(child_doc.urls)
    llms = run.text(f"{root}llms.txt")
    definitive &= _definitive(llms)
    llms_body = llms.body if llms is not None and llms.status == 200 else None
    fingerprint = inventory_fingerprint(urls, llms_body) if definitive else None
    return {loc: lastmod for loc, lastmod in urls}, fingerprint


def _definitive(response: TextResponse | None) -> bool:
    """A readable 200, or a 404/410 absence."""
    if response is None:
        return False
    if response.status == 200:
        return response.body is not None
    return response.status in (404, 410)


@dataclass(frozen=True)
class _PageVerdict:
    marker: PageMarker
    moved: bool
    strong: bool
    observed: bool


def _apply_page(
    marker: PageMarker, response: PageResponse, observed_lastmod: str | None
) -> _PageVerdict:
    """Compare one page's response with its recorded marker, baselining absent fields."""
    if response.status == 304:
        return _PageVerdict(marker, moved=False, strong=True, observed=True)
    if response.status in (404, 410):
        return _PageVerdict(marker, moved=True, strong=True, observed=True)
    if response.status != 200:
        return _PageVerdict(marker, moved=False, strong=False, observed=False)
    baselined = marker
    moved = strong = False
    for name, observed in (
        ("etag", response.etag),
        ("last_modified", response.last_modified),
        ("sitemap_lastmod", observed_lastmod),
    ):
        if observed is None:
            continue
        strong = True
        recorded = getattr(marker, name)
        if recorded is None:
            baselined = replace(baselined, **{name: observed})
        elif recorded != observed:
            moved = True
    return _PageVerdict(baselined, moved=moved, strong=strong, observed=True)


def _has_marker(marker: PageMarker) -> bool:
    return any(
        value is not None for value in (marker.etag, marker.last_modified, marker.sitemap_lastmod)
    )


def _probe_docs(entry: Entry, http: HttpProbe, now: datetime) -> _Probed:
    """Bounded conditional page requests + the inventory fingerprint → evidence and drift."""
    recorded = entry.upstream if isinstance(entry.upstream, DocsUpstream) else DocsUpstream()
    seed = entry.source.rstrip("/")
    pages = list(recorded.pages)
    if not any(page.url.rstrip("/") == seed for page in pages):
        pages.insert(0, PageMarker(url=entry.source))
    probed, rest = pages[:DOCS_PAGE_PROBE_LIMIT], pages[DOCS_PAGE_PROBE_LIMIT:]
    run = _DocsRun(http=http, started=http.clock())
    lastmods, fingerprint = _inventory(run, _site_root(entry.source))

    markers: list[PageMarker] = []
    moved = strong = False
    unobserved = 0
    consecutive_errors = 0
    for position, marker in enumerate(probed):
        stop = None
        if consecutive_errors >= PAGE_ERROR_STOP:
            stop = f"{PAGE_ERROR_STOP} consecutive page errors"
        elif not run.within_budget():
            stop = "the entry budget"
        if stop is not None:
            remaining = probed[position:]
            run.notes.append(f"{len(remaining)} page(s) not probed ({stop})")
            markers.extend(remaining)
            unobserved += sum(1 for page in remaining if _has_marker(page))
            break
        response = run.page(marker)
        if response is None:
            consecutive_errors += 1
            markers.append(marker)
            unobserved += 1 if _has_marker(marker) else 0
            continue
        consecutive_errors = 0
        verdict = _apply_page(marker, response, lastmods.get(marker.url))
        if not verdict.observed:
            run.notes.append(f"{marker.url}: HTTP {response.status} — not observed")
            unobserved += 1 if _has_marker(marker) else 0
        markers.append(verdict.marker)
        moved |= verdict.moved
        strong |= verdict.strong

    if run.requests and len(run.errors) == run.requests:
        return _Probed(updated=None, detail=run.errors[0], notes=tuple(run.notes))

    baseline_fingerprint = recorded.fingerprint
    if fingerprint is not None:
        if recorded.fingerprint is None:
            baseline_fingerprint = fingerprint
        elif recorded.fingerprint != fingerprint:
            moved = True
    elif recorded.fingerprint is not None:
        unobserved += 1

    evidence: Evidence = "strong" if strong else "weak" if fingerprint is not None else "none"
    drifted = entry.drifted
    if evidence != "none":
        drifted = moved or (entry.drifted and unobserved > 0)
        if entry.drifted and not moved and unobserved:
            run.notes.append(f"drift retained: {unobserved} comparison(s) not re-observed")
    updated = replace(
        entry,
        upstream=DocsUpstream(pages=(*markers, *rest), fingerprint=baseline_fingerprint),
        checked_at=format_ts(now),
        evidence=evidence,
        drifted=drifted,
    )
    return _Probed(updated=updated, detail=None, notes=tuple(run.notes))


def _apply(
    repo_root: Path,
    layout: LibraryLayout,
    updates: dict[int, tuple[Entry, Entry, tuple[str, ...]]],
    results: list[CheckResult],
    now: datetime,
) -> list[str]:
    """Write every observation whose entry is unchanged since its snapshot; the rest become
    ``failed`` results (with the pre-probe snapshot view) and warnings."""
    warnings: list[str] = []
    with library_lock(repo_root):
        catalog = load_catalog(layout)
        applied = False
        for index, (original, updated, notes) in updates.items():
            if catalog.get(original.slug) == original:
                catalog = catalog.with_entry(updated)
                applied = True
                continue
            results[index] = CheckResult(
                "failed", _CHANGED_MEANWHILE, notes, entry_view(layout, original, now)
            )
            warnings.append(f"{original.slug}: {_CHANGED_MEANWHILE}")
        if applied:
            write_catalog(layout, catalog)
    return warnings
