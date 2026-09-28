"""The docs doors through the real CLI: ``perk librarian add docs`` and the human
``perk librarian refresh <slug>`` of a documentation entry (contracts.md §8.75(k)).

``CliRunner`` over a scaffolded consumer repo (it carries the managed gitignore block) with only
the launch seam stubbed (a kwargs sink) and the converter probe faked at
``docs_session.which``; the crawl script is planted at the skill's delivery read path — a fake
one where a dry-run must run it. The seed probe (a subprocess) is stubbed to pass except under
``live_probe``, which runs it over the fake script. Expected commands are rebuilt here from the
inputs, never read back from the door's own plan object.
"""

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _librarian_site import FAKE_DRY_RUN_SCRIPT
from _library_upstream import REPO_REF, upstream
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.library import docs_session
from perk.library.layout import LibraryLayout
from perk.run import launch
from perk.substrate.proc import ProcFailure

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

SCRIPT_REL = Path(".agents/skills/librarian/scripts/copy_docs_to_markdown.py")
URL = "https://d.example/docs/start"
PI_SOURCE = "https://pi.dev/docs/"
REAL_PROBE_SEED = docs_session.probe_seed
REDIRECT = "https://d.example/0.5.4/"
REISSUE = f"perk librarian add docs {REDIRECT} --slug d --scope-prefix /0.5.4/"


def _pointer(skill: str) -> str:
    """The path-carrying nudge pointer line the binding renderer emits for ``skill``."""
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _run(args: list[str]):
    return CliRunner().invoke(cli, ["librarian", *args])


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _plant_script(repo: Path, body: str = "# the crawl script\n") -> Path:
    script = repo / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    return script


def _expected_crawl(repo: Path, url: str, staging: Path, scope: str | None = None) -> str:
    main = _layout(repo).main_root
    argv = [sys.executable, str(main / SCRIPT_REL), url, str(staging)]
    if scope is not None:
        argv += ["--scope-prefix", scope]
    return shlex.join(argv)


def _expected_publish(staging: Path, slug: str, url: str, *, replace: bool = False) -> str:
    argv = ["perk", "librarian", "record", "--publish", str(staging), "--slug", slug]
    argv += ["--source", url, *(["--replace"] if replace else []), "--json"]
    return shlex.join(argv)


@pytest.fixture
def converters(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    found: dict[str, str | None] = {"curl": "/usr/bin/curl", "html2markdown": "/usr/bin/h2m"}
    monkeypatch.setattr(docs_session, "which", lambda tool: found.get(tool))
    return found


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sink: list[dict[str, Any]] = []
    monkeypatch.setattr(launch, "launch_stage", lambda **kwargs: sink.append(kwargs))
    return sink


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch, converters, launches) -> Path:
    monkeypatch.chdir(scaffolded_perk_repo)
    _plant_script(scaffolded_perk_repo)
    monkeypatch.setattr(docs_session, "probe_seed", lambda plan: ())
    return scaffolded_perk_repo


@pytest.fixture
def live_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docs_session, "probe_seed", REAL_PROBE_SEED)


def _publish_pi(repo: Path, *, scope_prefix: str | None = None) -> Path:
    staging = _layout(repo).staging / "pi-src"
    staging.mkdir(parents=True)
    (staging / "index.md").write_text("# pi\n", encoding="utf-8")
    if scope_prefix is not None:
        inventory = {"seed_url": PI_SOURCE, "scope_prefix": scope_prefix, "pages": []}
        (staging / "sources.json").write_text(json.dumps(inventory), encoding="utf-8")
    result = _run(["record", "--publish", str(staging), "--slug", "pi", "--source", PI_SOURCE])
    assert result.exit_code == 0, result.stderr
    return _layout(repo).docs_entry_dir("pi")


def _staging_children(repo: Path) -> list[str]:
    staging = _layout(repo).staging
    return sorted(child.name for child in staging.iterdir()) if staging.exists() else []


# --- add docs: the launch --------------------------------------------------------------------


def test_add_docs_launches_the_seeded_session(repo, launches):
    result = _run(["add", "docs", URL, "--scope-prefix", "/docs/", "--model", "x/y"])
    assert result.exit_code == 0, result.output
    [kwargs] = launches
    layout = _layout(repo)
    staging = layout.staging / "d"
    assert kwargs["stage"].id == "save"
    assert kwargs["worktree"] is None
    assert kwargs["remote"] is None
    assert kwargs["dry_run"] is False
    assert kwargs["binding_trigger"] == "command:librarian-add"
    assert kwargs["repo_root"] == layout.main_root
    assert kwargs["pi_args"] == ["--model", "x/y"]
    assert staging.is_dir() and list(staging.iterdir()) == []
    seed = kwargs["prompt_override"]
    assert URL in seed and "`d`" in seed and str(staging) in seed
    assert _expected_crawl(repo, URL, staging, "/docs/") in seed
    assert _expected_publish(staging, "d", URL) in seed
    assert "(scope `/docs/`)" in seed
    # The read-path pointer is the binding nudge's alone (the script path legitimately carries
    # `.agents/skills/librarian`).
    assert _pointer("librarian") not in seed
    assert "Follow the" not in seed
    assert f"adding documentation entry d from {URL}" in result.stderr
    assert str(staging) in result.stderr


def test_add_docs_defaulted_scope_has_no_scope_clause(repo, launches):
    result = _run(["add", "docs", URL])
    assert result.exit_code == 0, result.output
    seed = launches[0]["prompt_override"]
    assert "(scope `" not in seed
    assert "--scope-prefix" not in seed
    assert _expected_crawl(repo, URL, _layout(repo).staging / "d") in seed


def test_add_docs_root_scope_is_accepted(repo, launches):
    result = _run(["add", "docs", URL, "--scope-prefix", "/"])
    assert result.exit_code == 0, result.output
    seed = launches[0]["prompt_override"]
    assert "(scope `/`)" in seed
    assert _expected_crawl(repo, URL, _layout(repo).staging / "d", "/") in seed


def test_two_doors_before_any_crawl_claim_distinct_staging_dirs(repo, launches):
    assert _run(["add", "docs", URL, "--slug", "d"]).exit_code == 0
    assert _run(["add", "docs", URL, "--slug", "d"]).exit_code == 0
    staging = _layout(repo).staging
    first, second = (kwargs["prompt_override"] for kwargs in launches)
    assert _expected_publish(staging / "d", "d", URL) in first
    assert _expected_publish(staging / "d-2", "d", URL) in second
    assert _staging_children(repo) == ["d", "d-2"]
    assert all(list((staging / name).iterdir()) == [] for name in ("d", "d-2"))


def test_add_docs_from_a_linked_worktree_targets_the_main_checkout(
    repo, launches, tmp_path, monkeypatch
):
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt", str(linked)],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=60,
    )
    monkeypatch.chdir(linked)
    result = _run(["add", "docs", URL])
    assert result.exit_code == 0, result.output
    main = _layout(repo).main_root
    [kwargs] = launches
    assert kwargs["repo_root"] == main
    staging = main / "docs" / "library" / ".staging" / "d"
    assert staging.is_dir()
    assert str(staging) in kwargs["prompt_override"]
    assert not (linked / "docs" / "library" / ".staging").exists()


def test_the_seeded_commands_survive_a_spaced_checkout_and_a_query_url(
    scaffolded_perk_repo, tmp_path, monkeypatch, converters, launches
):
    spaced = tmp_path / "my repo"
    shutil.copytree(scaffolded_perk_repo, spaced, symlinks=True)
    _plant_script(spaced)
    monkeypatch.chdir(spaced)
    url = "https://d.example/docs/start?x=1&y=2"
    result = _run(["add", "docs", url, "--scope-prefix", "/docs/"])
    assert result.exit_code == 0, result.output
    seed = launches[0]["prompt_override"]
    staging = _layout(spaced).staging / "d"
    crawl = _expected_crawl(spaced, url, staging, "/docs/")
    publish = _expected_publish(staging, "d", url)
    assert crawl in seed and publish in seed
    assert shlex.split(crawl) == [
        sys.executable,
        str(_layout(spaced).main_root / SCRIPT_REL),
        url,
        str(staging),
        "--scope-prefix",
        "/docs/",
    ]
    assert shlex.split(publish)[4] == str(staging)
    assert "'" in crawl  # the space and the `&` are quoted


# --- add docs: refusals ----------------------------------------------------------------------


def _assert_refused(result, fragment: str, launches, repo: Path) -> str:
    """A human-form refusal (the error type is not printed; each refusal's message is pinned by
    a fragment): exit 1, no launch, no staging directory, nothing on stdout."""
    assert result.exit_code == 1, result.output
    assert launches == []
    assert _staging_children(repo) == []
    assert result.stdout == ""
    assert "Error: " in result.stderr
    assert fragment in result.stderr
    return result.stderr


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        (["ftp://d.example/docs"], "invalid URL 'ftp://d.example/docs'"),  # invalid_source
        (["d.example/docs"], "use an absolute http(s) URL"),  # invalid_source
        ([URL, "--slug", "Bad"], "invalid slug 'Bad'"),  # invalid_slug
        (["https://-bad.example/docs"], "— pass --slug"),  # invalid_slug (derived)
        ([URL, "--scope-prefix", "../x"], "invalid --scope-prefix '../x'"),  # invalid_input
        ([URL, "--scope-prefix", " "], "it is blank"),  # invalid_input
    ],
)
def test_add_docs_input_refusals(repo, launches, args, fragment):
    _assert_refused(_run(["add", "docs", *args]), fragment, launches, repo)


def test_add_docs_refuses_a_catalogued_slug(repo, launches):
    _publish_pi(repo)
    before = _staging_children(repo)
    result = _run(["add", "docs", PI_SOURCE])
    assert result.exit_code == 1
    assert launches == []
    assert _staging_children(repo) == before
    assert "already catalogued" in result.stderr
    assert "perk librarian refresh pi" in result.stderr


def test_add_docs_refuses_an_uncatalogued_mirror(repo, launches):
    _layout(repo).docs_entry_dir("d").mkdir(parents=True)
    result = _run(["add", "docs", URL])
    assert result.exit_code == 1
    assert launches == []
    assert "record --adopt" in result.stderr
    assert not _layout(repo).staging.exists()


def test_add_docs_refuses_when_the_skill_is_missing(repo, launches):
    (repo / SCRIPT_REL).unlink()
    stderr = _assert_refused(_run(["add", "docs", URL]), "skill is not installed", launches, repo)
    assert "perk init" in stderr


def test_add_docs_refuses_a_directory_at_the_script_path(repo, launches):
    script = repo / SCRIPT_REL
    script.unlink()
    script.mkdir()
    _assert_refused(_run(["add", "docs", URL]), "skill is not installed", launches, repo)


@pytest.mark.parametrize("dry_run", [False, True])
def test_add_docs_refuses_a_missing_converter(repo, launches, converters, dry_run):
    converters["html2markdown"] = None
    args = ["add", "docs", URL, *(["--dry-run"] if dry_run else [])]
    stderr = _assert_refused(_run(args), "`html2markdown` is not on PATH", launches, repo)
    assert "brew install html2markdown" in stderr


def test_add_docs_refuses_when_the_library_is_not_ignored(repo, launches):
    (repo / ".gitignore").write_text("", encoding="utf-8")
    stderr = _assert_refused(_run(["add", "docs", URL]), "are not gitignored", launches, repo)
    assert "perk init" in stderr


def test_add_docs_outside_a_repo_exits_2(tmp_path, monkeypatch, converters, launches):
    monkeypatch.chdir(tmp_path)
    result = _run(["add", "docs", URL])
    assert result.exit_code == 2
    assert launches == []


# --- add docs --dry-run ----------------------------------------------------------------------


@pytest.fixture
def fake_script(repo) -> Path:
    return _plant_script(repo, FAKE_DRY_RUN_SCRIPT)


@pytest.mark.parametrize("code", ["0", "1"])
def test_dry_run_relays_the_map_and_the_exit(repo, launches, fake_script, monkeypatch, code):
    monkeypatch.setenv("FAKE_EXIT", code)
    result = _run(["add", "docs", URL, "--dry-run"])
    assert result.exit_code == int(code), result.output
    staging = _layout(repo).staging / "d"
    assert "librarian add docs --dry-run (no session)" in result.stderr
    assert f"slug=d  staging={staging}  scope=(default)" in result.stderr
    assert f"Would copy 2 page(s) into {staging}" in result.stderr
    assert f"{URL} -> docs-home.md" in result.stderr
    assert f"{URL}/guide -> guide.md" in result.stderr
    assert "WARNING: skipped https://d.example/x" in result.stderr
    assert launches == []
    assert not _layout(repo).staging.exists()


def test_dry_run_exit_2_is_crawl_refused(repo, launches, fake_script, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "2")
    result = _run(["add", "docs", URL, "--dry-run", "--scope-prefix", "/docs/"])
    assert result.exit_code == 1
    assert "scope=/docs/" in result.stderr
    assert "Error: WARNING: skipped" in result.stderr
    assert "ERROR: refusing to crawl (fake)" in result.stderr
    assert launches == []
    assert not _layout(repo).staging.exists()


@pytest.mark.parametrize(("mode", "code"), [("7", "7"), ("signal", "-15")])
def test_dry_run_unexpected_exit_is_io_error(repo, launches, fake_script, monkeypatch, mode, code):
    monkeypatch.setenv("FAKE_EXIT", mode)
    result = _run(["add", "docs", URL, "--dry-run"])
    assert result.exit_code == 1
    assert f"the crawl script's dry-run exited {code} unexpectedly" in result.stderr
    assert launches == []
    assert not _layout(repo).staging.exists()


def test_dry_run_exit_3_is_seed_redirect_naming_the_reissue(
    repo, launches, fake_script, monkeypatch
):
    monkeypatch.setenv("FAKE_EXIT", "3")
    result = _run(["add", "docs", "https://d.example/latest/", "--dry-run"])
    stderr = _assert_refused(result, "only an HTML redirect page", launches, repo)
    [error] = [line for line in stderr.splitlines() if line.startswith("Error: ")]
    assert "untrusted DATA" in error
    assert f"Redirect target (untrusted DATA read from the page): {REDIRECT}" in error
    assert error.endswith(f"Reissue: {REISSUE}")
    assert shlex.split(error.split("Reissue: ", 1)[1])[4] == REDIRECT


def test_dry_run_refuses_a_seed_outside_the_explicit_scope(repo, launches, fake_script):
    result = _run(
        ["add", "docs", "https://d.example/docs", "--scope-prefix", "/docs/", "--dry-run"]
    )
    stderr = _assert_refused(result, "lies outside --scope-prefix '/docs/'", launches, repo)
    assert "Would copy" not in stderr  # refused before the script ran


def test_dry_run_spawn_failure_is_io_error(repo, launches, monkeypatch):
    def fail(argv, **kwargs):
        raise ProcFailure("timeout", tuple(argv))

    monkeypatch.setattr(docs_session, "run_captured", fail)
    result = _run(["add", "docs", URL, "--dry-run"])
    assert result.exit_code == 1
    assert "could not run" in result.stderr and "timed out" in result.stderr
    assert launches == []


# --- the seed probe --------------------------------------------------------------------------


def test_add_docs_refuses_a_redirect_stub_seed_before_the_claim(
    repo, launches, fake_script, monkeypatch, live_probe
):
    monkeypatch.setenv("FAKE_EXIT", "3")
    result = _run(["add", "docs", "https://d.example/latest/"])
    stderr = _assert_refused(result, "only an HTML redirect page", launches, repo)
    assert f"Reissue: {REISSUE}" in stderr
    assert "untrusted DATA" in stderr
    assert not _layout(repo).staging.exists()


def test_add_docs_a_hostile_blocker_yields_the_fixed_message(
    repo, launches, fake_script, monkeypatch, live_probe
):
    monkeypatch.setenv("FAKE_EXIT", "3-hostile")
    result = _run(["add", "docs", "https://d.example/latest/"])
    stderr = _assert_refused(result, "described no reissuable http(s) target", launches, repo)
    assert "javascript:" not in stderr  # the launch path echoes none of the script's output
    assert "untrusted DATA" not in stderr


def test_add_docs_an_inconclusive_probe_warns_and_launches(
    repo, launches, fake_script, monkeypatch, live_probe
):
    monkeypatch.setenv("FAKE_EXIT", "1")
    result = _run(["add", "docs", URL])
    assert result.exit_code == 0, result.output
    assert len(launches) == 1
    assert "warning: the seed probe did not complete (exit 1)" in result.stderr
    assert (_layout(repo).staging / "d").is_dir()


def test_refresh_refuses_a_source_that_now_redirects(
    repo, launches, fake_script, monkeypatch, live_probe
):
    _publish_pi(repo, scope_prefix="/docs/")
    before = _staging_children(repo)
    monkeypatch.setenv("FAKE_EXIT", "3")
    result = _run(["refresh", "pi"])
    assert result.exit_code == 1, result.output
    assert launches == []
    assert _staging_children(repo) == before
    assert "a refresh cannot follow it" in result.stderr
    assert "perk librarian remove pi --json" in result.stderr
    assert f"perk librarian add docs {REDIRECT} --slug pi --scope-prefix /0.5.4/" in result.stderr


# --- refresh (human) of a docs entry: the refresh door ---------------------------------------


def test_refresh_docs_entry_launches_the_refresh_session(repo, launches):
    current = _publish_pi(repo, scope_prefix="/docs/")
    result = _run(["refresh", "pi"])
    assert result.exit_code == 0, result.output
    [kwargs] = launches
    staging = _layout(repo).staging / "pi"
    assert kwargs["binding_trigger"] == "command:librarian-refresh"
    assert kwargs["stage"].id == "save"
    assert kwargs["worktree"] is None
    assert kwargs["pi_args"] == []
    assert staging.is_dir() and list(staging.iterdir()) == []
    seed = kwargs["prompt_override"]
    assert _expected_publish(staging, "pi", PI_SOURCE, replace=True) in seed
    assert _expected_crawl(repo, PI_SOURCE, staging, "/docs/") in seed
    assert "(scope `/docs/` — the prior crawl's)" in seed
    assert str(current) in seed
    assert _pointer("librarian") not in seed
    assert f"refreshing documentation entry pi ({PI_SOURCE})" in result.stderr


def test_refresh_docs_entry_recovers_a_root_scope(repo, launches):
    _publish_pi(repo, scope_prefix="/")
    assert _run(["refresh", "pi"]).exit_code == 0
    seed = launches[0]["prompt_override"]
    assert _expected_crawl(repo, PI_SOURCE, _layout(repo).staging / "pi", "/") in seed


def test_refresh_docs_entry_warns_on_an_unusable_recorded_scope(repo, launches):
    _publish_pi(repo, scope_prefix="../x")
    result = _run(["refresh", "pi"])
    assert result.exit_code == 0, result.output
    assert "warning: the prior crawl's recorded scope prefix '../x'" in result.stderr
    seed = launches[0]["prompt_override"]
    assert "--scope-prefix" not in seed
    assert _expected_crawl(repo, PI_SOURCE, _layout(repo).staging / "pi") in seed


def test_refresh_docs_entry_claims_past_a_leftover(repo, launches):
    _publish_pi(repo)
    leftover = _layout(repo).staging / "pi"
    leftover.mkdir()
    (leftover / "half.md").write_text("half\n", encoding="utf-8")
    assert _run(["refresh", "pi"]).exit_code == 0
    seed = launches[0]["prompt_override"]
    assert _expected_publish(leftover.with_name("pi-2"), "pi", PI_SOURCE, replace=True) in seed
    assert (leftover / "half.md").read_text(encoding="utf-8") == "half\n"


def test_refresh_docs_entry_refuses_a_missing_converter(repo, launches, converters):
    _publish_pi(repo)
    converters["curl"] = None
    result = _run(["refresh", "pi"])
    assert result.exit_code == 1
    assert "`curl` is not on PATH" in result.stderr
    assert launches == []
    assert _staging_children(repo) == []


def test_refresh_json_of_a_docs_entry_stays_needs_session(repo, launches):
    _publish_pi(repo)
    result = _run(["refresh", "pi", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "needs_session"
    assert "perk librarian refresh pi" in payload["message"]
    assert launches == []
    assert _staging_children(repo) == []


def test_refresh_of_a_source_entry_is_unchanged_on_both_forms(repo, launches, upstream):
    assert _run(["add", "source", REPO_REF]).exit_code == 0
    human = _run(["refresh", "widget"])
    assert human.exit_code == 0, human.output
    assert "up to date widget" in human.stderr
    machine = _run(["refresh", "widget", "--json"])
    assert machine.exit_code == 0
    assert json.loads(machine.stdout)["action"] == "up_to_date"
    assert launches == []


def test_refresh_of_an_unknown_slug_is_entry_not_found(repo, launches):
    result = _run(["refresh", "ghost"])
    assert result.exit_code == 1
    assert "no library entry named ghost" in result.stderr
    assert launches == []
