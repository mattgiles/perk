"""The docs doors' deterministic half (``perk/library/docs_session.py``, contracts.md §8.75(k)).

Real filesystem + real git over a scaffolded consumer repo (it carries the managed gitignore
block). The converter probe and the dry-run spawn are faked at the module's own seams
(``docs_session.which`` / ``docs_session.run_captured``); the crawl script is planted at the
skill's delivery read path. The seed probe (a subprocess) is stubbed to pass for every test but
its own, which restore the original captured at import.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _librarian_site import load_script

from perk.library import catalog as cat
from perk.library import docs_session, ops
from perk.library.errors import LibraryError
from perk.library.inventory import read_scope_prefix
from perk.library.layout import LibraryLayout
from perk.substrate.proc import ProcFailure

SCRIPT_REL = Path(".agents/skills/librarian/scripts/copy_docs_to_markdown.py")
URL = "https://d.example/docs/start"
PI_SOURCE = "https://pi.dev/docs/"
REAL_PROBE_SEED = docs_session.probe_seed


def _plant_script(repo: Path) -> Path:
    script = repo / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# the crawl script\n", encoding="utf-8")
    return script


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _publish(repo: Path, slug: str = "pi", *, inventory: object | None = None) -> Path:
    staging = _layout(repo).staging / f"{slug}-src"
    staging.mkdir(parents=True)
    (staging / "index.md").write_text("# docs\n", encoding="utf-8")
    if inventory is not None:
        (staging / "sources.json").write_text(json.dumps(inventory), encoding="utf-8")
    ops.publish(
        repo,
        staging=staging,
        slug=slug,
        source=PI_SOURCE,
        replace=False,
        accept_failures=False,
        stale_after=None,
    )
    return _layout(repo).docs_entry_dir(slug)


@pytest.fixture
def converters(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """Both converters present unless a test sets a tool to ``None``."""
    found: dict[str, str | None] = {"curl": "/usr/bin/curl", "html2markdown": "/usr/bin/h2m"}
    monkeypatch.setattr(docs_session, "which", lambda tool: found.get(tool))
    return found


@pytest.fixture
def repo(
    scaffolded_perk_repo: Path,
    converters: dict[str, str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    _plant_script(scaffolded_perk_repo)
    monkeypatch.setattr(docs_session, "probe_seed", lambda plan: ())
    return scaffolded_perk_repo


def _plan_add(
    repo: Path,
    *,
    url: str = URL,
    slug: str | None = None,
    scope_prefix: str | None = None,
    dry_run: bool = False,
) -> docs_session.DocsCrawlPlan:
    return docs_session.plan_add_docs(
        repo, url=url, slug=slug, scope_prefix=scope_prefix, dry_run=dry_run
    )


# --- the default slug ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://pi.dev/docs", "pi"),
        ("https://docs.astro.build/en/", "astro"),
        ("https://starlight.astro.build/", "starlight"),
        ("https://linear.app/developers", "linear"),
        ("https://www.example.com/x", "example"),
        ("https://www.docs.example.com/x", "example"),
        ("https://Docs.Example.COM/x", "example"),
        ("http://127.0.0.1:8000/docs", "127"),
    ],
)
def test_derive_slug(url, slug):
    assert docs_session.derive_slug(url) == slug


@pytest.mark.parametrize(
    "url", ["https://-bad.example/docs", "http://[::1]/docs", "https://docs./"]
)
def test_derive_slug_refuses_a_label_outside_the_grammar(url):
    with pytest.raises(LibraryError) as excinfo:
        docs_session.derive_slug(url)
    assert excinfo.value.error_type == "invalid_slug"
    assert "--slug" in str(excinfo.value)


# --- the scope prefix ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("docs/x", "/docs/x/"),
        ("/docs//x/", "/docs/x/"),
        ("/docs/", "/docs/"),
        ("/", "/"),
        ("//", "/"),
    ],
)
def test_validate_scope_prefix_normalizes(text, normalized):
    assert docs_session.validate_scope_prefix(text) == normalized


@pytest.mark.parametrize("text", ["../x", "/docs/./x", "/docs/../x", "a\x00b", "/do cs/", " ", ""])
def test_validate_scope_prefix_refuses(text):
    with pytest.raises(LibraryError) as excinfo:
        docs_session.validate_scope_prefix(text)
    assert excinfo.value.error_type == "invalid_input"


def test_validate_scope_prefix_matches_the_crawl_scripts_normalization():
    script = load_script()
    for text in ("docs/x", "/docs//x/", "/", "//", "/a/b/c"):
        assert docs_session.validate_scope_prefix(text) == script.normalize_scope_prefix(text, URL)


# --- prerequisites ---------------------------------------------------------------------------


def test_require_converters_passes_when_both_resolve(converters):
    docs_session.require_converters()


def test_require_converters_names_the_missing_tool_and_its_hint(converters):
    converters["html2markdown"] = None
    with pytest.raises(LibraryError) as excinfo:
        docs_session.require_converters()
    assert excinfo.value.error_type == "missing_converter"
    message = str(excinfo.value)
    assert "`html2markdown` is not on PATH" in message
    assert "brew install html2markdown" in message
    assert "curl" not in message


def test_require_converters_names_every_missing_tool_in_one_refusal(converters):
    converters["curl"] = None
    converters["html2markdown"] = None
    with pytest.raises(LibraryError) as excinfo:
        docs_session.require_converters()
    message = str(excinfo.value)
    assert "`curl` is not on PATH" in message and "install curl" in message
    assert "`html2markdown` is not on PATH" in message


def test_librarian_script_path(tmp_path):
    script = _plant_script(tmp_path)
    assert docs_session.librarian_script_path(tmp_path) == script


def test_librarian_script_path_absent_is_skill_missing(tmp_path):
    with pytest.raises(LibraryError) as excinfo:
        docs_session.librarian_script_path(tmp_path)
    assert excinfo.value.error_type == "skill_missing"
    assert "perk init" in str(excinfo.value)


def test_a_directory_at_the_script_path_is_skill_missing(tmp_path):
    (tmp_path / SCRIPT_REL).mkdir(parents=True)
    with pytest.raises(LibraryError) as excinfo:
        docs_session.librarian_script_path(tmp_path)
    assert excinfo.value.error_type == "skill_missing"


def test_a_dangling_symlink_at_the_script_path_is_skill_missing(tmp_path):
    link = tmp_path / SCRIPT_REL
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "gone.py")
    with pytest.raises(LibraryError) as excinfo:
        docs_session.librarian_script_path(tmp_path)
    assert excinfo.value.error_type == "skill_missing"


# --- staging names ---------------------------------------------------------------------------


def test_fresh_staging_dir_previews_the_first_free_name_and_writes_nothing(scaffolded_perk_repo):
    layout = _layout(scaffolded_perk_repo)
    assert docs_session.fresh_staging_dir(layout, "d") == layout.staging / "d"
    assert not layout.staging.exists()
    (layout.staging / "d").mkdir(parents=True)
    assert docs_session.fresh_staging_dir(layout, "d") == layout.staging / "d-2"
    (layout.staging / "d-2").symlink_to(scaffolded_perk_repo / "nowhere")
    assert docs_session.fresh_staging_dir(layout, "d") == layout.staging / "d-3"
    assert sorted(child.name for child in layout.staging.iterdir()) == ["d", "d-2"]


def test_claim_staging_dir_claims_empty_siblings_and_removes_nothing(scaffolded_perk_repo):
    layout = _layout(scaffolded_perk_repo)
    first = docs_session.claim_staging_dir(layout, "d")
    assert first == layout.staging / "d"
    assert first.is_dir() and list(first.iterdir()) == []
    (first / "page.md").write_text("kept\n", encoding="utf-8")
    second = docs_session.claim_staging_dir(layout, "d")
    assert second == layout.staging / "d-2"
    (layout.staging / "d-3").write_text("a file\n", encoding="utf-8")
    (layout.staging / "d-4").symlink_to(scaffolded_perk_repo / "nowhere")
    third = docs_session.claim_staging_dir(layout, "d")
    assert third == layout.staging / "d-5"
    assert (first / "page.md").read_text(encoding="utf-8") == "kept\n"
    assert (layout.staging / "d-3").is_file()
    assert (layout.staging / "d-4").is_symlink()


# --- the recorded scope ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (json.dumps({"scope_prefix": "/docs/", "pages": []}), "/docs/"),
        (json.dumps({"scope_prefix": "/"}), "/"),
        (json.dumps({"scope_prefix": ""}), None),
        (json.dumps({"scope_prefix": 7}), None),
        (json.dumps({"pages": []}), None),
        (json.dumps(["not", "a", "map"]), None),
        ("{not json", None),
    ],
)
def test_read_scope_prefix(tmp_path, content, expected):
    (tmp_path / "sources.json").write_text(content, encoding="utf-8")
    assert read_scope_prefix(tmp_path) == expected


def test_read_scope_prefix_without_an_inventory(tmp_path):
    assert read_scope_prefix(tmp_path) is None


# --- plan_add_docs ---------------------------------------------------------------------------


def test_plan_add_docs_claims_the_staging_dir_and_builds_the_commands(repo):
    layout = _layout(repo)
    plan = _plan_add(repo, scope_prefix="docs")
    assert plan.slug == "d"
    assert plan.scope_prefix == "/docs/"
    assert plan.staging_dir == layout.staging / "d"
    assert plan.staging_dir.is_dir() and list(plan.staging_dir.iterdir()) == []
    assert plan.main_root == layout.main_root
    assert plan.current_dir is None and plan.replace is False and plan.warnings == ()
    assert plan.crawl_argv == (
        sys.executable,
        str(layout.main_root / SCRIPT_REL),
        URL,
        str(layout.staging / "d"),
        "--scope-prefix",
        "/docs/",
    )
    assert plan.publish_argv == (
        "perk",
        "librarian",
        "record",
        "--publish",
        str(layout.staging / "d"),
        "--slug",
        "d",
        "--source",
        URL,
        "--json",
    )


def test_plan_add_docs_defaulted_scope_carries_no_flag(repo):
    plan = _plan_add(repo)
    assert plan.scope_prefix == ""
    assert "--scope-prefix" not in plan.crawl_argv


def test_plan_add_docs_root_scope_is_carried(repo):
    plan = _plan_add(repo, scope_prefix="/")
    assert plan.crawl_argv[-2:] == ("--scope-prefix", "/")


def test_plan_add_docs_dry_run_claims_nothing(repo):
    layout = _layout(repo)
    plan = _plan_add(repo, dry_run=True)
    assert plan.staging_dir == layout.staging / "d"
    assert not layout.staging.exists()


def test_plan_add_docs_explicit_slug_is_validated(repo):
    assert _plan_add(repo, slug="mine").slug == "mine"
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo, slug="Bad")
    assert excinfo.value.error_type == "invalid_slug"


@pytest.mark.parametrize("kind", ["docs", "source"])
def test_plan_add_docs_refuses_a_catalogued_slug_of_either_kind(repo, kind):
    layout = _layout(repo)
    if kind == "docs":
        _publish(repo, "d")
    else:
        entry = cat.Entry(
            kind="source",
            slug="d",
            source="https://github.com/acme/d.git",
            path="source-code/github.com/acme/d",
            added_at="2026-01-01T00:00:00Z",
            stale_after=86_400,
            upstream=cat.SourceUpstream(branch="main", head_sha=None),
        )
        layout.root.mkdir(parents=True, exist_ok=True)
        cat.write_catalog(layout, cat.Catalog(entries=(entry,)))
    staged_before = sorted(layout.staging.iterdir()) if layout.staging.exists() else []
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo)
    assert excinfo.value.error_type == "slug_exists"
    assert "perk librarian refresh d" in str(excinfo.value)
    staged_after = sorted(layout.staging.iterdir()) if layout.staging.exists() else []
    assert staged_after == staged_before


def test_plan_add_docs_refuses_an_uncatalogued_mirror(repo):
    target = _layout(repo).docs_entry_dir("d")
    target.mkdir(parents=True)
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo)
    assert excinfo.value.error_type == "slug_exists"
    assert "record --adopt" in str(excinfo.value)


def test_plan_add_docs_refuses_a_symlinked_mirror(repo, tmp_path):
    target = _layout(repo).docs_entry_dir("d")
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path)
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo)
    assert excinfo.value.error_type == "slug_exists"


def test_plan_add_docs_propagates_a_malformed_catalog(repo):
    layout = _layout(repo)
    layout.root.mkdir(parents=True)
    layout.catalog_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo)
    assert excinfo.value.error_type == "catalog_malformed"


def test_plan_add_docs_probes_past_a_symlinked_staging_leftover(repo, tmp_path):
    layout = _layout(repo)
    layout.staging.mkdir(parents=True)
    (layout.staging / "d").symlink_to(tmp_path)
    plan = _plan_add(repo)
    assert plan.staging_dir == layout.staging / "d-2"
    assert (layout.staging / "d").is_symlink()


# --- plan_refresh_docs -----------------------------------------------------------------------


def test_plan_refresh_docs_refuses_an_absent_slug(repo):
    with pytest.raises(LibraryError) as excinfo:
        docs_session.plan_refresh_docs(repo, slug="ghost")
    assert excinfo.value.error_type == "entry_not_found"


def test_plan_refresh_docs_refuses_a_source_entry(repo):
    layout = _layout(repo)
    entry = cat.Entry(
        kind="source",
        slug="widget",
        source="https://github.com/acme/widget.git",
        path="source-code/github.com/acme/widget",
        added_at="2026-01-01T00:00:00Z",
        stale_after=86_400,
        upstream=cat.SourceUpstream(branch="main", head_sha=None),
    )
    layout.root.mkdir(parents=True)
    cat.write_catalog(layout, cat.Catalog(entries=(entry,)))
    with pytest.raises(LibraryError) as excinfo:
        docs_session.plan_refresh_docs(repo, slug="widget")
    assert excinfo.value.error_type == "entry_not_found"


def test_plan_refresh_docs_recovers_the_recorded_scope(repo):
    current = _publish(repo, inventory={"scope_prefix": "/docs/", "pages": []})
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    layout = _layout(repo)
    assert plan.url == PI_SOURCE
    assert plan.scope_prefix == "/docs/"
    assert plan.current_dir == current
    assert plan.replace is True
    assert plan.staging_dir == layout.staging / "pi"
    assert plan.staging_dir.is_dir()
    assert plan.publish_argv[-2:] == ("--replace", "--json")
    assert plan.warnings == ()


def test_plan_refresh_docs_recovers_the_root_scope(repo):
    _publish(repo, inventory={"scope_prefix": "/", "pages": []})
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    assert plan.scope_prefix == "/"
    assert plan.crawl_argv[-2:] == ("--scope-prefix", "/")


def test_plan_refresh_docs_without_an_inventory_defaults_the_scope(repo):
    _publish(repo)
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    assert plan.scope_prefix == ""
    assert "--scope-prefix" not in plan.crawl_argv
    assert plan.warnings == ()


def test_plan_refresh_docs_warns_on_an_unusable_recorded_scope(repo):
    _publish(repo, inventory={"scope_prefix": "../x", "pages": []})
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    assert plan.scope_prefix == ""
    [warning] = plan.warnings
    assert "'../x'" in warning


def test_plan_refresh_docs_claims_past_a_leftover(repo):
    _publish(repo)
    layout = _layout(repo)
    (layout.staging / "pi").mkdir(parents=True)
    (layout.staging / "pi" / "half.md").write_text("half\n", encoding="utf-8")
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    assert plan.staging_dir == layout.staging / "pi-2"
    assert (layout.staging / "pi" / "half.md").is_file()


def test_plan_refresh_docs_refuses_a_missing_converter(repo, converters):
    _publish(repo)
    converters["curl"] = None
    with pytest.raises(LibraryError) as excinfo:
        docs_session.plan_refresh_docs(repo, slug="pi")
    assert excinfo.value.error_type == "missing_converter"
    assert not (_layout(repo).staging / "pi").exists()


def test_entry_kind(repo):
    assert docs_session.entry_kind(repo, "pi") is None
    _publish(repo)
    assert docs_session.entry_kind(repo, "pi") == "docs"


# --- shell safety ----------------------------------------------------------------------------


def test_the_commands_round_trip_through_the_shell(scaffolded_perk_repo, tmp_path, converters):
    spaced = tmp_path / "my repo"
    shutil.copytree(scaffolded_perk_repo, spaced, symlinks=True)
    _plant_script(spaced)
    url = "https://d.example/docs/start?x=1&y=2"
    plan = docs_session.plan_add_docs(
        spaced, url=url, slug=None, scope_prefix="/docs/", dry_run=False
    )
    assert shlex.split(plan.publish_command) == list(plan.publish_argv)
    assert shlex.split(plan.crawl_command) == list(plan.crawl_argv)
    assert plan.crawl_argv[0] == sys.executable
    assert " " in plan.crawl_argv[1] and "&" in plan.crawl_argv[2]


# --- the dry-run spawn -----------------------------------------------------------------------


def test_run_dry_run_runs_the_crawl_argv_with_dry_run(repo, monkeypatch):
    plan = _plan_add(repo, dry_run=True)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return subprocess.CompletedProcess(argv, 1, "map\n", "WARNING: x\n")

    monkeypatch.setattr(docs_session, "run_captured", fake_run)
    completed = docs_session.run_dry_run(plan)
    assert completed.returncode == 1
    [(argv, kwargs)] = calls
    assert argv == (*plan.crawl_argv, "--dry-run")
    assert kwargs == {"cwd": plan.main_root, "timeout": docs_session.DRY_RUN_TIMEOUT_SECONDS}


def test_run_dry_run_translates_a_spawn_failure(repo, monkeypatch):
    plan = _plan_add(repo, dry_run=True)

    def fail(argv, **kwargs):
        raise ProcFailure("spawn", tuple(argv), cause_text="no such file")

    monkeypatch.setattr(docs_session, "run_captured", fail)
    with pytest.raises(LibraryError) as excinfo:
        docs_session.run_dry_run(plan)
    assert excinfo.value.error_type == "io_error"
    assert "could not run" in str(excinfo.value)


def test_first_use_creates_the_library_through_the_claim(repo):
    layout = _layout(repo)
    assert not layout.root.exists()
    plan = _plan_add(repo)
    assert plan.staging_dir.is_dir()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout
    assert "docs/library" not in status


# --- the seed inside an explicit scope ---------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "prefix"), [(URL, "/docs/"), (URL, "/"), ("https://d.example/docs/", "/docs/")]
)
def test_require_seed_in_scope_admits_a_seed_beneath_the_prefix(url, prefix):
    docs_session.require_seed_in_scope(url, prefix)


@pytest.mark.parametrize(
    ("url", "prefix"),
    [("https://d.example/docs", "/docs/"), (URL, "/docs/start/"), (URL, "/api/")],
)
def test_require_seed_in_scope_refuses_a_seed_outside_the_prefix(url, prefix):
    with pytest.raises(LibraryError) as excinfo:
        docs_session.require_seed_in_scope(url, prefix)
    assert excinfo.value.error_type == "invalid_input"
    assert f"lies outside --scope-prefix {prefix!r}" in str(excinfo.value)


def test_plan_add_docs_refuses_a_seed_outside_the_explicit_scope(repo):
    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo, url="https://d.example/docs", scope_prefix="/docs/")
    assert excinfo.value.error_type == "invalid_input"
    assert not _layout(repo).staging.exists()


def test_plan_refresh_docs_warns_on_a_recorded_scope_excluding_the_source(repo):
    _publish(repo, inventory={"scope_prefix": "/api/", "pages": []})
    plan = docs_session.plan_refresh_docs(repo, slug="pi")
    assert plan.scope_prefix == ""
    assert "--scope-prefix" not in plan.crawl_argv
    [warning] = plan.warnings
    assert "'/api/'" in warning
    assert "is unusable (it excludes the entry's source URL)" in warning


# --- the seed-redirect blocker -----------------------------------------------------------------

REDIRECT = "https://d.example/0.5.4/"


def _blocker_line(**overrides: object) -> str:
    fields: dict[str, object] = {
        "blocker": "seed-redirect",
        "seed_url": "https://d.example/latest/",
        "fetched_url": "https://d.example/latest/",
        "redirect_url": REDIRECT,
        "scope_prefix": "/0.5.4/",
    }
    fields.update(overrides)
    return json.dumps({key: value for key, value in fields.items() if value is not None})


def test_parse_seed_redirect_reads_the_last_non_blank_line():
    blocker = docs_session.parse_seed_redirect(f"{_blocker_line(extra='ignored')}\n\n  \n")
    assert blocker is not None
    assert (blocker.redirect_url, blocker.scope_prefix) == (REDIRECT, "/0.5.4/")


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param("", id="empty"),
        pytest.param("Would copy 1 page(s)\n", id="not-json"),
        pytest.param("[1, 2]\n", id="not-an-object"),
        pytest.param(_blocker_line(blocker="other"), id="other-blocker"),
        pytest.param(_blocker_line(redirect_url=None), id="missing-field"),
        pytest.param(_blocker_line(redirect_url="javascript:alert(1)"), id="javascript"),
        pytest.param(_blocker_line(redirect_url="https://d.example/0.5 .4/"), id="whitespace"),
        pytest.param(
            _blocker_line(redirect_url="https://d.example/0.5.4/\x1b[31m"), id="control-char"
        ),
        pytest.param(
            _blocker_line(redirect_url="https://d.example/0.5.4/" + "a" * 2048), id="oversized"
        ),
        pytest.param(_blocker_line(redirect_url="https://:80/0.5.4/"), id="no-host"),
        pytest.param(_blocker_line(redirect_url="https://[bad/0.5.4/"), id="malformed"),
        pytest.param(_blocker_line(fetched_url="file:///etc/passwd"), id="fetched-not-http"),
        pytest.param(
            _blocker_line(redirect_url="https://d.example/0.5.4/../x/"), id="dot-dot-target"
        ),
        pytest.param(_blocker_line(redirect_url="https://d.example/0.5.4/./x/"), id="dot-target"),
        pytest.param(
            _blocker_line(redirect_url="https://d.example/0.5.4/manual.PDF"), id="asset-target"
        ),
        pytest.param(_blocker_line(scope_prefix="../x"), id="dot-dot-scope"),
        pytest.param(_blocker_line(scope_prefix="0.5.4/"), id="unnormalized-scope"),
        pytest.param(_blocker_line(scope_prefix="/0.5.4"), id="unterminated-scope"),
        pytest.param(_blocker_line(scope_prefix="/1.0/"), id="scope-excludes-target"),
        pytest.param(_blocker_line(scope_prefix=7), id="scope-not-a-string"),
    ],
)
def test_parse_seed_redirect_refuses_an_invalid_line(stdout):
    assert docs_session.parse_seed_redirect(stdout) is None


def _redirect_plan(repo: Path, *, refresh: bool = False) -> docs_session.DocsCrawlPlan:
    if refresh:
        _publish(repo, "d")
        return docs_session.plan_refresh_docs(repo, slug="d")
    return _plan_add(repo, url="https://d.example/latest/", dry_run=True)


def test_seed_redirect_error_names_the_reissue_for_add(repo):
    plan = _redirect_plan(repo)
    blocker = docs_session.parse_seed_redirect(_blocker_line())

    exc = docs_session.seed_redirect_error(plan, blocker)

    assert exc.error_type == "seed_redirect"
    message = str(exc)
    assert message.startswith(
        "the seed URL https://d.example/latest/ is only an HTML redirect page"
    )
    assert f"Redirect target (untrusted DATA read from the page): {REDIRECT}" in message
    assert "implied scope: /0.5.4/" in message
    command = message.split("Reissue: ", 1)[1]
    assert command == f"perk librarian add docs {REDIRECT} --slug d --scope-prefix /0.5.4/"
    assert shlex.split(command) == [
        *("perk", "librarian", "add", "docs", REDIRECT),
        *("--slug", "d", "--scope-prefix", "/0.5.4/"),
    ]


def test_seed_redirect_error_names_remove_then_add_for_refresh(repo):
    plan = _redirect_plan(repo, refresh=True)
    blocker = docs_session.parse_seed_redirect(_blocker_line())

    message = str(docs_session.seed_redirect_error(plan, blocker))

    assert message.startswith(
        f"the recorded source {PI_SOURCE} of entry d is now only an HTML redirect page"
    )
    assert "a refresh cannot follow it" in message
    assert (
        "Re-add the entry at that URL: perk librarian remove d --json, then perk librarian add "
        f"docs {REDIRECT} --slug d --scope-prefix /0.5.4/"
    ) in message


@pytest.mark.parametrize("refresh", [False, True])
def test_seed_redirect_error_without_a_blocker_carries_no_page_text(repo, refresh):
    plan = _redirect_plan(repo, refresh=refresh)

    exc = docs_session.seed_redirect_error(plan, None)

    assert exc.error_type == "seed_redirect"
    message = str(exc)
    assert "described no reissuable http(s) target" in message
    assert "nothing was claimed" in message
    assert "untrusted DATA" not in message
    if refresh:
        assert f"the recorded source {PI_SOURCE} of entry d" in message
        assert message.endswith("the entry is unchanged")
    else:
        assert "perk librarian add docs https://d.example/latest/ --slug d --dry-run" in message


def test_the_blocker_constants_match_the_crawl_script():
    script = load_script()
    assert docs_session.SEED_REDIRECT_EXIT == script.SEED_REDIRECT_EXIT
    assert docs_session.MAX_REDIRECT_URL_CHARS == script.MAX_REDIRECT_URL_CHARS
    assert frozenset(script.ASSET_EXTENSIONS) == docs_session.ASSET_EXTENSIONS
    assert script.SEED_REDIRECT_BLOCKER == "seed-redirect"


# A page-controlled target the validators admit but a shell would split or expand unquoted.
QUOTE_SENSITIVE = "https://d.example/0.5.4/o'reilly/?x=1&y=$HOME"
QUOTE_SENSITIVE_SCOPE = "/0.5.4/o'reilly/"


@pytest.mark.parametrize("refresh", [False, True])
def test_the_reissue_shell_quotes_page_derived_values(repo, refresh):
    plan = _redirect_plan(repo, refresh=refresh)
    line = _blocker_line(redirect_url=QUOTE_SENSITIVE, scope_prefix=QUOTE_SENSITIVE_SCOPE)
    blocker = docs_session.parse_seed_redirect(line)
    assert blocker is not None

    message = str(docs_session.seed_redirect_error(plan, blocker))

    add_argv = [
        *("perk", "librarian", "add", "docs", QUOTE_SENSITIVE),
        *("--slug", "d", "--scope-prefix", QUOTE_SENSITIVE_SCOPE),
    ]
    if refresh:
        remove, add = message.split("Re-add the entry at that URL: ", 1)[1].split(", then ", 1)
        assert shlex.split(remove) == ["perk", "librarian", "remove", "d", "--json"]
    else:
        add = message.split("Reissue: ", 1)[1]
    assert shlex.split(add) == add_argv
    assert add == shlex.join(add_argv)
    assert QUOTE_SENSITIVE not in add  # quoted, never pasted raw into the command


# --- the seed probe ----------------------------------------------------------------------------


@pytest.fixture
def live_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docs_session, "probe_seed", REAL_PROBE_SEED)


def _fake_probe_run(
    monkeypatch: pytest.MonkeyPatch, code: int, stdout: str = "", stderr: str = ""
) -> list[tuple[tuple[str, ...], dict[str, object]]]:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    monkeypatch.setattr(docs_session, "run_captured", fake_run)
    return calls


def test_probe_seed_runs_the_one_page_dry_run(repo, monkeypatch, live_probe):
    plan = _plan_add(repo, dry_run=True)
    calls = _fake_probe_run(monkeypatch, 0, "Would copy 1 page(s)\n")

    assert docs_session.probe_seed(plan) == ()

    [(argv, kwargs)] = calls
    assert argv == (*plan.crawl_argv, "--max-pages", "1", "--dry-run")
    assert kwargs == {"cwd": plan.main_root, "timeout": docs_session.SEED_PROBE_TIMEOUT_SECONDS}


def test_probe_seed_exit_3_is_seed_redirect(repo, monkeypatch, live_probe):
    plan = _plan_add(repo, dry_run=True)
    _fake_probe_run(monkeypatch, 3, _blocker_line() + "\n", "ERROR: redirect\n")

    with pytest.raises(LibraryError) as excinfo:
        docs_session.probe_seed(plan)

    assert excinfo.value.error_type == "seed_redirect"
    assert "--scope-prefix /0.5.4/" in str(excinfo.value)


@pytest.mark.parametrize("code", [1, 2, 7, -9])
def test_probe_seed_other_exits_are_advisory(repo, monkeypatch, live_probe, code):
    plan = _plan_add(repo, dry_run=True)
    _fake_probe_run(monkeypatch, code, "", "ERROR: SECRET-STDERR\n")

    [warning] = docs_session.probe_seed(plan)

    assert warning.startswith(f"the seed probe did not complete (exit {code})")
    assert "SECRET-STDERR" not in warning


@pytest.mark.parametrize("kind", ["spawn", "timeout"])
def test_probe_seed_a_spawn_failure_or_timeout_is_advisory(repo, monkeypatch, live_probe, kind):
    plan = _plan_add(repo, dry_run=True)

    def fail(argv, **kwargs):
        raise ProcFailure(kind, tuple(argv), cause_text="no such file")

    monkeypatch.setattr(docs_session, "run_captured", fail)

    [warning] = docs_session.probe_seed(plan)

    assert warning.startswith("the seed probe did not complete (")
    assert ("timed out after 180s" if kind == "timeout" else "could not run") in warning


def test_plan_add_docs_probes_before_the_claim(repo, monkeypatch, live_probe):
    _fake_probe_run(monkeypatch, 3, _blocker_line())

    with pytest.raises(LibraryError) as excinfo:
        _plan_add(repo, url="https://d.example/latest/")

    assert excinfo.value.error_type == "seed_redirect"
    assert not _layout(repo).staging.exists()


def test_plan_add_docs_carries_a_probe_warning(repo, monkeypatch, live_probe):
    calls = _fake_probe_run(monkeypatch, 1)

    plan = _plan_add(repo)

    [(argv, _kwargs)] = calls
    assert argv[3] == str(plan.staging_dir)  # the probe ran over the (then free) claimed name
    assert plan.staging_dir.is_dir()
    [warning] = plan.warnings
    assert warning.startswith("the seed probe did not complete (exit 1)")


def test_plan_add_docs_dry_run_never_probes(repo, monkeypatch):
    probed: list[docs_session.DocsCrawlPlan] = []
    monkeypatch.setattr(docs_session, "probe_seed", lambda plan: probed.append(plan) or ())

    _plan_add(repo, dry_run=True)

    assert probed == []


def test_plan_refresh_docs_probes_before_the_claim(repo, monkeypatch, live_probe):
    _publish(repo)
    _fake_probe_run(monkeypatch, 3, _blocker_line())

    with pytest.raises(LibraryError) as excinfo:
        docs_session.plan_refresh_docs(repo, slug="pi")

    assert excinfo.value.error_type == "seed_redirect"
    assert "perk librarian remove pi --json" in str(excinfo.value)
    assert not (_layout(repo).staging / "pi").exists()


def test_plan_refresh_docs_orders_the_probe_warning_after_the_scope_warning(
    repo, monkeypatch, live_probe
):
    _publish(repo, inventory={"scope_prefix": "../x", "pages": []})
    _fake_probe_run(monkeypatch, 2)

    plan = docs_session.plan_refresh_docs(repo, slug="pi")

    scope_warning, probe_warning = plan.warnings
    assert "'../x'" in scope_warning
    assert probe_warning.startswith("the seed probe did not complete (exit 2)")
    assert plan.staging_dir.is_dir()
