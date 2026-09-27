"""``check`` — the only freshness probe (``perk/library/check.py`` + ``probe.py``, contracts.md
§8.75(i)).

Offline: source entries probe the ``upstream`` fixture's bare repository (env-config
``insteadOf``); docs entries probe an ``httpx.MockTransport`` over a mutable in-memory site.
"""

import contextlib
import functools
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from _library_upstream import REPO_REF, Upstream, run_git, upstream

from perk.library import catalog as cat
from perk.library import check, probe, source
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout
from perk.substrate import git

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
ROOT = "https://docs.example/"
SEED = f"{ROOT}docs"
GUIDE = f"{ROOT}docs/guide"
API = f"{ROOT}docs/api"


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch):
    monkeypatch.chdir(scaffolded_perk_repo)
    return scaffolded_perk_repo


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _catalog(repo: Path) -> cat.Catalog:
    return cat.load_catalog(_layout(repo))


def _head_sha(entry: cat.Entry) -> str | None:
    assert isinstance(entry.upstream, cat.SourceUpstream)
    return entry.upstream.head_sha


def _docs(entry: cat.Entry) -> cat.DocsUpstream:
    assert isinstance(entry.upstream, cat.DocsUpstream)
    return entry.upstream


def _detail(result: check.CheckResult) -> str:
    assert result.detail is not None
    return result.detail


def _set_entry(repo: Path, entry: cat.Entry) -> cat.Entry:
    layout = _layout(repo)
    catalog = cat.load_catalog(layout) if layout.catalog_path.exists() else cat.Catalog()
    cat.write_catalog(layout, catalog.with_entry(entry))
    return entry


def _docs_entry(
    repo: Path,
    slug: str = "pi",
    *,
    pages: tuple[str, ...] = (SEED, GUIDE, API),
    checked_at: str | None = None,
    mirror: bool = True,
) -> cat.Entry:
    if mirror:
        directory = _layout(repo).docs_entry_dir(slug)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.md").write_text("# docs\n", encoding="utf-8")
    return _set_entry(
        repo,
        cat.Entry(
            kind="docs",
            slug=slug,
            source=SEED,
            path=f"documentation/{slug}",
            added_at="2026-09-01T00:00:00Z",
            stale_after=1_209_600,
            upstream=cat.DocsUpstream(pages=tuple(cat.PageMarker(url=url) for url in pages)),
            checked_at=checked_at,
        ),
    )


@dataclass
class Site:
    """A mutable docs site: ``pages`` maps URL → (body, ETag or None)."""

    pages: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    sitemap: str | None = None
    children: dict[str, str] = field(default_factory=dict)
    llms: str | None = None
    statuses: dict[str, int] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    down: set[str] = field(default_factory=set)
    all_down: bool = False
    requests: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if self.all_down or url in self.down:
            raise httpx.ConnectError("connection refused (injected)", request=request)
        if url in self.statuses:
            return httpx.Response(self.statuses[url])
        if url in self.redirects:
            return httpx.Response(301, headers={"Location": self.redirects[url]})
        if url == f"{ROOT}sitemap.xml" and self.sitemap is not None:
            return httpx.Response(200, text=self.sitemap)
        if url in self.children:
            return httpx.Response(200, text=self.children[url])
        if url == f"{ROOT}llms.txt" and self.llms is not None:
            return httpx.Response(200, text=self.llms)
        if url in self.pages:
            body, etag = self.pages[url]
            if etag is not None and request.headers.get("If-None-Match") == etag:
                return httpx.Response(304, headers={"ETag": etag})
            return httpx.Response(200, text=body, headers={"ETag": etag} if etag else {})
        return httpx.Response(404)

    def page_requests(self) -> list[str]:
        return [url for url in self.requests if url in self.pages or url in self.statuses]


def _site(*, etags: bool = True) -> Site:
    return Site(
        pages={
            url: (f"<p>{url}</p>", f'"{index}-v1"' if etags else None)
            for index, url in enumerate((SEED, GUIDE, API))
        }
    )


def _check(
    repo: Path,
    site: Site | None = None,
    *,
    slugs: tuple[str, ...] = (),
    force: bool = False,
    now: datetime = LATER,
) -> check.CheckOutcome:
    transport = httpx.MockTransport(site.handler) if site is not None else _no_network()
    return check.check_entries(repo, slugs=slugs, force=force, now=lambda: now, transport=transport)


def _no_network() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request {request.url}")

    return httpx.MockTransport(handler)


def _only(outcome: check.CheckOutcome) -> check.CheckResult:
    [result] = outcome.results
    return result


def _sitemap(*urls: tuple[str, str | None], index: bool = False) -> str:
    ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    if index:
        body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc, _ in urls)
        return f'<?xml version="1.0"?><sitemapindex xmlns="{ns}">{body}</sitemapindex>'
    body = "".join(
        f"<url><loc>{loc}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>"
        for loc, lastmod in urls
    )
    return f'<?xml version="1.0"?><urlset xmlns="{ns}">{body}</urlset>'


# --- source entries --------------------------------------------------------------------------


def test_source_probe_detects_drift_until_refreshed(repo, upstream: Upstream):
    source.add_source(
        repo, repo_ref=REPO_REF, pin=None, slug=None, stale_after=None, now=lambda: NOW
    )
    result = _only(_check(repo))
    assert result.action == "probed"
    entry = result.view.entry
    assert (entry.evidence, entry.drifted, result.view.status) == ("strong", False, "fresh")
    head = _head_sha(entry)

    upstream.advance_origin()
    drifted = _only(_check(repo, force=True))
    assert drifted.view.entry.drifted is True
    assert _head_sha(drifted.view.entry) == head
    assert drifted.view.status == "drifted"
    assert _only(_check(repo, force=True)).view.entry.drifted is True

    source.refresh_entry(repo, slug="widget", now=lambda: LATER)
    assert _only(_check(repo, force=True)).view.status == "fresh"


def test_source_probe_of_a_vanished_branch_is_unverifiable(repo, upstream):
    source.add_source(
        repo, repo_ref=REPO_REF, pin=None, slug=None, stale_after=None, now=lambda: NOW
    )
    run_git(upstream.seed, "push", "-q", "origin", "HEAD~1:refs/heads/other")
    run_git(upstream.remote, "symbolic-ref", "HEAD", "refs/heads/other")
    run_git(upstream.remote, "branch", "-D", "main")
    result = _only(_check(repo))
    assert result.action == "probed"
    assert result.view.entry.evidence == "none"
    assert result.view.status == "unverifiable"
    assert any("refs/heads/main" in note for note in result.notes)


def test_source_probe_failure_leaves_the_entry_untouched(repo, upstream, monkeypatch):
    source.add_source(
        repo, repo_ref=REPO_REF, pin=None, slug=None, stale_after=None, now=lambda: NOW
    )
    before = _catalog(repo)

    def failing(*_args, **_kwargs):
        raise git.GitError("fatal: unable to access (injected)")

    monkeypatch.setattr(git, "remote_branch_head", failing)
    outcome = _check(repo)
    result = _only(outcome)
    assert (result.action, result.detail) == ("failed", "fatal: unable to access (injected)")
    assert _catalog(repo) == before
    assert outcome.warnings == ()


def test_pinned_and_missing_entries_are_never_probed(repo, upstream, monkeypatch):
    upstream.tag("v1", "HEAD~1")
    source.add_source(
        repo, repo_ref=REPO_REF, pin="v1", slug=None, stale_after=None, now=lambda: NOW
    )
    _docs_entry(repo, mirror=False)
    calls = []
    monkeypatch.setattr(git, "remote_branch_head", lambda *a, **k: calls.append(a))
    outcome = _check(repo)
    by_slug = {result.view.entry.slug: result for result in outcome.results}
    assert by_slug["widget"].action == "pinned"
    assert by_slug["pi"].action == "missing"
    assert "record --publish" in _detail(by_slug["pi"])
    assert calls == []


def test_throttle_skips_recent_entries_without_network(repo, upstream, monkeypatch):
    source.add_source(
        repo, repo_ref=REPO_REF, pin=None, slug=None, stale_after=None, now=lambda: NOW
    )
    _check(repo, now=NOW)
    _docs_entry(repo, checked_at=cat.format_ts(NOW))
    calls = []
    real = git.remote_branch_head
    monkeypatch.setattr(git, "remote_branch_head", lambda *a, **k: calls.append(a) or real(*a, **k))
    outcome = _check(repo, now=NOW + timedelta(hours=1))
    assert [result.action for result in outcome.results] == ["recent", "recent"]
    assert "pass --force" in _detail(outcome.results[0])
    assert calls == []

    site = _site()
    forced = _check(repo, site, force=True, now=NOW + timedelta(hours=1))
    assert [result.action for result in forced.results] == ["probed", "probed"]
    assert len(calls) == 1
    assert site.requests


def test_never_checked_entries_are_never_throttled(repo):
    _docs_entry(repo)
    assert _only(_check(repo, _site())).action == "probed"


def test_unknown_slugs_are_refused_before_any_probe(repo):
    _docs_entry(repo)
    with pytest.raises(LibraryError) as excinfo:
        _check(repo, slugs=("pi", "nope", "gone"))
    assert excinfo.value.error_type == "entry_not_found"
    assert "nope, gone" in str(excinfo.value)


def test_explicit_slugs_keep_their_order(repo):
    _docs_entry(repo, "alpha")
    _docs_entry(repo, "beta")
    outcome = _check(repo, _site(), slugs=("beta", "alpha", "beta"))
    assert [result.view.entry.slug for result in outcome.results] == ["beta", "alpha"]


def test_malformed_catalog_propagates(repo):
    layout = _layout(repo)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.catalog_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LibraryError) as excinfo:
        _check(repo)
    assert excinfo.value.error_type == "catalog_malformed"


def test_absent_library_is_an_empty_outcome(repo):
    assert _check(repo) == check.CheckOutcome(results=(), warnings=())


# --- docs entries ----------------------------------------------------------------------------


def test_a_changed_leaf_validator_drifts_the_entry(repo):
    _docs_entry(repo)
    site = _site()
    first = _only(_check(repo, site))
    entry = first.view.entry
    assert (entry.evidence, entry.drifted, first.view.status) == ("strong", False, "fresh")
    assert [page.etag for page in _docs(entry).pages] == ['"0-v1"', '"1-v1"', '"2-v1"']

    site.pages[API] = ("<p>new api</p>", '"2-v2"')
    second = _only(_check(repo, site, force=True))
    assert second.view.entry.drifted is True
    assert second.view.status == "drifted"
    assert [page.etag for page in _docs(second.view.entry).pages][2] == '"2-v1"'


def test_a_validator_less_site_is_unverifiable_never_fresh(repo):
    _docs_entry(repo)
    site = _site(etags=False)
    first = _only(_check(repo, site))
    assert (first.view.entry.evidence, first.view.status) == ("none", "unverifiable")
    assert first.view.entry.drifted is False
    site.pages[API] = ("<p>new api</p>", None)
    second = _only(_check(repo, site, force=True))
    assert (second.view.entry.evidence, second.view.status) == ("none", "unverifiable")


def test_llms_txt_is_weak_evidence(repo):
    _docs_entry(repo)
    site = _site(etags=False)
    site.llms = "# docs\n- guide\n"
    first = _only(_check(repo, site))
    assert (first.view.entry.evidence, first.view.status) == ("weak", "fresh")
    assert (_docs(first.view.entry).fingerprint or "").startswith("llms=")
    site.llms = "# docs\n- guide\n- api\n"
    second = _only(_check(repo, site, force=True))
    assert second.view.entry.drifted is True
    assert _docs(second.view.entry).fingerprint == _docs(first.view.entry).fingerprint


def test_sitemap_lastmod_is_strong_evidence(repo):
    _docs_entry(repo)
    site = _site(etags=False)
    site.sitemap = _sitemap((SEED, "2026-09-01"), (GUIDE, "2026-09-01"), (API, "2026-09-01"))
    first = _only(_check(repo, site))
    assert first.view.entry.evidence == "strong"
    assert first.view.entry.drifted is False
    assert {page.sitemap_lastmod for page in _docs(first.view.entry).pages} == {"2026-09-01"}
    site.sitemap = _sitemap((SEED, "2026-09-01"), (GUIDE, "2026-09-01"), (API, "2026-09-20"))
    second = _only(_check(repo, site, force=True))
    assert second.view.entry.drifted is True


def test_a_sitemap_index_is_followed_into_its_children(repo):
    _docs_entry(repo)
    site = _site(etags=False)
    child = f"{ROOT}sitemap-docs.xml"
    site.sitemap = _sitemap((child, None), index=True)
    site.children[child] = _sitemap((API, "2026-09-01"))
    result = _only(_check(repo, site))
    assert result.view.entry.evidence == "strong"
    assert _docs(result.view.entry).pages[2].sitemap_lastmod == "2026-09-01"
    assert child in site.requests


def test_a_gone_page_drifts_and_a_server_error_is_not_observed(repo):
    _docs_entry(repo)
    site = _site()
    _check(repo, site)
    site.statuses[GUIDE] = 500
    errored = _only(_check(repo, site, force=True))
    assert errored.view.entry.drifted is False
    assert any("HTTP 500" in note for note in errored.notes)
    del site.statuses[GUIDE]
    del site.pages[GUIDE]
    gone = _only(_check(repo, site, force=True))
    assert gone.view.entry.drifted is True


def test_drift_is_retained_when_the_drifted_page_is_not_re_observed(repo):
    _docs_entry(repo)
    site = _site()
    _check(repo, site)
    site.pages[API] = ("<p>new api</p>", '"2-v2"')
    assert _only(_check(repo, site, force=True)).view.entry.drifted is True
    site.statuses[API] = 500
    retained = _only(_check(repo, site, force=True))
    assert retained.view.entry.drifted is True
    assert any(note.startswith("drift retained: 1 comparison") for note in retained.notes)


def test_drift_is_retained_when_a_recorded_validator_is_not_returned(repo):
    _docs_entry(repo)
    site = _site()
    _check(repo, site)
    site.pages[API] = ("<p>new api</p>", '"2-v2"')
    assert _only(_check(repo, site, force=True)).view.entry.drifted is True
    # The leaf answers 200 without its ETag: the recorded comparison cannot be repeated.
    site.pages[API] = ("<p>new api</p>", None)
    retained = _only(_check(repo, site, force=True))
    assert retained.view.entry.evidence == "strong"
    assert retained.view.entry.drifted is True
    assert any(note.startswith("drift retained: 1 comparison") for note in retained.notes)


@pytest.mark.parametrize("child", [False, True])
def test_an_unparseable_sitemap_is_not_compared(repo, child):
    _docs_entry(repo)
    site = _site(etags=False)
    urlset = _sitemap((SEED, None), (GUIDE, None))
    child_url = f"{ROOT}sitemap-docs.xml"
    if child:
        site.sitemap = _sitemap((child_url, None), index=True)
        site.children[child_url] = urlset
    else:
        site.sitemap = urlset
    site.llms = "# docs\n"
    first = _only(_check(repo, site)).view.entry
    assert first.evidence == "weak"
    recorded = _docs(first).fingerprint
    assert recorded is not None and recorded.startswith("sitemap=")
    broken = "<html><body>502 Bad Gateway</body></html>"
    if child:
        site.children[child_url] = broken
    else:
        site.sitemap = broken
    second = _only(_check(repo, site, force=True))
    assert second.view.entry.drifted is False
    assert second.view.entry.evidence == "none"
    assert _docs(second.view.entry).fingerprint == recorded
    assert any("not parseable" in note for note in second.notes)


def test_every_request_failing_is_a_failed_result(repo):
    _docs_entry(repo)
    site = _site()
    _check(repo, site)
    before = _catalog(repo)
    site.all_down = True
    result = _only(_check(repo, site, force=True))
    assert result.action == "failed"
    assert "ConnectError" in _detail(result)
    assert _catalog(repo) == before


def test_consecutive_page_errors_stop_the_page_loop(repo):
    urls = tuple(f"{ROOT}docs/p{index}" for index in range(5))
    _docs_entry(repo, pages=(SEED, *urls))
    site = Site(pages={url: ("x", None) for url in (SEED, *urls)})
    site.down = {SEED, *urls}
    result = _only(_check(repo, site))
    assert result.action == "probed"
    assert len(site.page_requests()) == probe.PAGE_ERROR_STOP
    assert any("page(s) not probed" in note for note in result.notes)


def test_the_page_bound_limits_requests(repo):
    urls = tuple(f"{ROOT}docs/p{index:02d}" for index in range(30))
    _docs_entry(repo, pages=urls)
    site = Site(pages={url: ("x", f'"{url}"') for url in (SEED, *urls)})
    result = _only(_check(repo, site))
    assert len(site.page_requests()) == probe.DOCS_PAGE_PROBE_LIMIT
    pages = _docs(result.view.entry).pages
    assert pages[0].url == SEED
    assert all(page.etag is not None for page in pages[: probe.DOCS_PAGE_PROBE_LIMIT])
    assert all(page.etag is None for page in pages[probe.DOCS_PAGE_PROBE_LIMIT :])


def test_a_redirect_loop_is_a_noted_probe_error(repo):
    _docs_entry(repo)
    site = _site()
    site.redirects[GUIDE] = GUIDE
    result = _only(_check(repo, site))
    assert result.action == "probed"
    assert any("TooManyRedirects" in note for note in result.notes)


def test_the_entry_budget_skips_the_remaining_requests(repo, monkeypatch):
    _docs_entry(repo)
    site = _site()

    def clock() -> float:
        return 0.0 if len(site.requests) < 1 else probe.DOCS_ENTRY_BUDGET + 1

    monkeypatch.setattr(check, "HttpProbe", functools.partial(probe.HttpProbe, clock=clock))
    result = _only(_check(repo, site))
    assert len(site.requests) == 1
    assert any("entry budget" in note for note in result.notes)
    assert result.view.entry.evidence == "none"


def test_a_second_unchanged_check_changes_only_checked_at(repo):
    _docs_entry(repo)
    site = _site()
    site.llms = "# docs\n"
    first = _only(_check(repo, site)).view.entry
    second = _only(_check(repo, site, force=True, now=LATER + timedelta(days=1))).view.entry
    assert second == replace(first, checked_at=cat.format_ts(LATER + timedelta(days=1)))


def test_a_newer_observation_written_meanwhile_is_never_overwritten(repo, monkeypatch):
    _docs_entry(repo)
    real_lock = check.library_lock
    newer: list[cat.Entry] = []

    @contextlib.contextmanager
    def racing_lock(root):
        layout = _layout(repo)
        catalog = cat.load_catalog(layout)
        current = catalog.get("pi")
        assert current is not None
        entry = replace(current, checked_at="2026-09-28T13:00:00Z", drifted=True)
        cat.write_catalog(layout, catalog.with_entry(entry))
        newer.append(entry)
        with real_lock(root):
            yield

    monkeypatch.setattr(check, "library_lock", racing_lock)
    outcome = _check(repo, _site())
    result = _only(outcome)
    assert result.action == "failed"
    assert "changed or was checked meanwhile" in _detail(result)
    assert outcome.warnings == ("pi: entry changed or was checked meanwhile — rerun",)
    assert _catalog(repo).get("pi") == newer[0]


def test_an_entry_removed_meanwhile_reports_its_snapshot(repo, monkeypatch):
    original = _docs_entry(repo)
    real_lock = check.library_lock

    @contextlib.contextmanager
    def removing_lock(root):
        layout = _layout(repo)
        cat.write_catalog(layout, cat.load_catalog(layout).without("pi"))
        with real_lock(root):
            yield

    monkeypatch.setattr(check, "library_lock", removing_lock)
    outcome = _check(repo, _site())
    result = _only(outcome)
    assert result.action == "failed"
    assert result.view.entry == original
    assert outcome.warnings
    assert _catalog(repo).get("pi") is None


def test_a_check_never_touches_tracked_state(repo):
    _docs_entry(repo)
    _check(repo, _site())
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    assert [line for line in status.splitlines() if line[3:].startswith("docs/")] == []


# --- streaming body bounds -------------------------------------------------------------------


class _CountingStream(httpx.SyncByteStream):
    """A response body that counts the chunks a reader actually pulls."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.consumed = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk


def _streaming(stream: _CountingStream, **headers: str) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _request: httpx.Response(200, headers=headers, stream=stream))


def test_a_page_probe_consumes_no_body():
    stream = _CountingStream([b"x" * 1024] * 4)
    with probe.HttpProbe(transport=_streaming(stream, ETag='"a"')) as http:
        response = http.page(SEED, etag=None, last_modified=None)
    assert response == probe.PageResponse(status=200, etag='"a"', last_modified=None)
    assert stream.consumed == 0


def test_an_inventory_body_at_the_limit_is_read():
    chunk = probe.INVENTORY_BODY_LIMIT // 4
    stream = _CountingStream([b"x" * chunk] * 4)
    with probe.HttpProbe(transport=_streaming(stream)) as http:
        response = http.text(f"{ROOT}llms.txt")
    assert response.status == 200
    assert response.body is not None and len(response.body) == probe.INVENTORY_BODY_LIMIT


def test_an_oversized_inventory_body_is_rejected_without_draining():
    chunk = probe.INVENTORY_BODY_LIMIT // 2
    stream = _CountingStream([b"x" * chunk] * 2 + [b"x"] + [b"x" * chunk] * 3)
    with probe.HttpProbe(transport=_streaming(stream)) as http:
        response = http.text(f"{ROOT}llms.txt")
    assert response == probe.TextResponse(status=200, body=None)
    assert stream.consumed == 3
    assert stream.consumed < len(stream.chunks)


def test_an_oversized_inventory_is_not_baselined_as_evidence(repo):
    _docs_entry(repo)
    site = _site(etags=False)
    site.llms = "x" * (probe.INVENTORY_BODY_LIMIT + 1)
    result = _only(_check(repo, site))
    entry = result.view.entry
    assert (entry.evidence, _docs(entry).fingerprint) == ("none", None)
    assert result.view.status == "unverifiable"
    assert any("over the inventory size limit" in note for note in result.notes)


# --- parse_sitemap ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            b"<urlset><url><loc>https://a/x</loc><lastmod>2026-01-01</lastmod></url>"
            b"<url><loc>https://a/y</loc></url></urlset>",
            probe.SitemapDoc(
                urls=(("https://a/x", "2026-01-01"), ("https://a/y", None)), children=()
            ),
        ),
        (
            _sitemap(("https://a/x", "2026-01-01")).encode(),
            probe.SitemapDoc(urls=(("https://a/x", "2026-01-01"),), children=()),
        ),
        (
            _sitemap(("https://a/s1.xml", None), ("https://a/s2.xml", None), index=True).encode(),
            probe.SitemapDoc(urls=(), children=("https://a/s1.xml", "https://a/s2.xml")),
        ),
        (b"<urlset/>", probe.SitemapDoc(urls=(), children=())),
        (b"<urlset><url><loc>", None),
        (b'<?xml version="1.0" encoding="x-does-not-exist"?><urlset/>', None),
        (b'<?xml version="1.0" encoding="rot13"?><urlset/>', None),
        (b'<?xml version="1.0" encoding="utf-32"?><urlset/>', None),
        (b"", None),
        (b"<html><body>not a sitemap</body></html>", None),
        (
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset>'
            b"<url><loc>&a;</loc></url></urlset>",
            None,
        ),
    ],
)
def test_parse_sitemap(body, expected):
    assert probe.parse_sitemap(body) == expected


def test_inventory_fingerprint_is_order_independent():
    first = probe.inventory_fingerprint([("b", None), ("a", "1")], b"llms")
    second = probe.inventory_fingerprint([("a", "1"), ("b", None)], b"llms")
    assert first == second
    assert first is not None
    assert first.startswith("sitemap=") and ";llms=" in first
    assert probe.inventory_fingerprint([], None) is None
