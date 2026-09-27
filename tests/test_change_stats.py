"""The change-stats module: partitioning, routing, range→pairs materialization, aggregation,
range resolution, and the renderers."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from perk.delivery import change_stats as cs
from perk.substrate import cloc, git


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


# --- partitioning + routing -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "partition"),
    [
        ("src/perk/foo.py", "rest"),
        ("README.md", "rest"),
        ("docs/user-docs/x.md", "rest"),
        ("src/perk/testing_helpers.py", "rest"),
        ("tests/test_x.py", "tests"),
        ("extension/foo.test.ts", "tests"),
        ("extension/foo.spec.mjs", "tests"),
        ("extension/testing/fixtures/a.js", "tests"),
        ("conftest.py", "tests"),
        ("pkg/sub/conftest.py", "tests"),
        ("pkg/x_test.go", "tests"),
        ("pkg/x_test.py", "tests"),
        ("pkg/test_thing.py", "tests"),
        ("web/__tests__/a.tsx", "tests"),
        ("docs/learned/pi/x.md", "learned"),
        ("pkg/docs/learned/x.md", "learned"),
        ("docs/learned-not/x.md", "rest"),
    ],
)
def test_partition_of(path, partition):
    assert cs.partition_of(path) == partition


def test_learned_wins_over_tests_by_order():
    assert cs.partition_of("docs/learned/tests/x.md") == "learned"


@pytest.mark.parametrize(
    ("partition", "language", "kind", "row"),
    [
        ("learned", "Markdown", "code", "learned_docs"),
        ("learned", "Python", "comment", "learned_docs"),
        ("tests", "Python", "code", "tests"),
        ("tests", "YAML", "code", "tests"),
        ("tests", "Python", "comment", "comments"),
        ("rest", "YAML", "code", "other"),
        ("rest", "Markdown", "comment", "other"),
        ("rest", "Python", "code", "code"),
        ("rest", "TypeScript", "comment", "comments"),
    ],
)
def test_route(partition, language, kind, row):
    assert cs._route(partition, language, kind) == row


def test_partitions_require_one_trailing_residual():
    with pytest.raises(ValueError, match="residual"):
        cs._check_partitions((cs.Partition("rest", None), cs.Partition("tests", cs.TEST_PATH_RE)))
    with pytest.raises(ValueError, match="residual"):
        cs._check_partitions((cs.Partition("tests", cs.TEST_PATH_RE),))


# --- summarize over a real temporary repository ---------------------------------------------


@dataclass(frozen=True, order=True)
class _File:
    """One materialized file as cloc receives it: its side (``a`` = base, ``b`` = head), its base
    name (what cloc's language detection sees), and its bytes."""

    side: str
    name: str
    data: bytes


def _file(path: Path, root: Path) -> _File:
    return _File(path.relative_to(root).parts[0], path.name, path.read_bytes())


@dataclass(frozen=True)
class _Call:
    added: list[_File]
    removed: list[_File]
    compared: list[tuple[_File, _File]]


class _Recorder:
    """A fake cloc runner: records each partition's pairs (file bytes read at call time, before
    the temporary trees vanish) and returns a canned report per partition."""

    def __init__(self, reports: dict[str, cloc.DiffReport] | None = None) -> None:
        self.reports = reports or {}
        self.calls: dict[str, _Call] = {}

    def __call__(self, pairs: cloc.DiffPairs, *, workdir: Path) -> cloc.DiffReport:
        root = workdir.parent
        self.calls[workdir.name] = _Call(
            added=sorted(_file(p, root) for p in pairs.added),
            removed=sorted(_file(p, root) for p in pairs.removed),
            compared=sorted((_file(a, root), _file(b, root)) for a, b in pairs.compared),
        )
        return self.reports.get(workdir.name, cloc.DiffReport(languages={}))


def _show(repo: Path, spec: str) -> bytes:
    """The committed bytes of ``<rev>:<path>`` (``git cat-file blob`` — no conversions)."""
    return subprocess.run(
        ["git", "cat-file", "blob", spec], cwd=repo, check=True, capture_output=True
    ).stdout


def _matrix_repo(repo: Path) -> tuple[str, str]:
    (repo / "src").mkdir()
    (repo / "src" / "keep.py").write_text("a = 1\n", encoding="utf-8")
    (repo / "src" / "gone.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src" / "helper.py").write_text(
        "".join(f"line_{n} = {n}\n" for n in range(20)), encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _head(repo)
    (repo / "src" / "keep.py").write_text("a = 2\n# note\n", encoding="utf-8")
    (repo / "src" / "gone.py").unlink()
    (repo / "tests").mkdir()
    _git(repo, "mv", "src/helper.py", "tests/helper.py")
    with (repo / "tests" / "helper.py").open("a", encoding="utf-8") as fh:
        fh.write("extra = 1\n")
    (repo / "web").mkdir()
    (repo / "web" / "[id].tsx").write_text("export const x = 1;\n", encoding="utf-8")
    (repo / "src" / "a|b.py").write_text("y = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    return base, _head(repo)


def test_summarize_materializes_and_partitions_every_entry(git_repo):
    base, head = _matrix_repo(git_repo)
    recorder = _Recorder()
    stats = cs.summarize(git_repo, base, head, run_cloc=recorder)

    assert set(recorder.calls) == {"rest", "tests"}  # no learned entries → no learned call
    rest, tests = recorder.calls["rest"], recorder.calls["tests"]
    # Every side is byte-equal to its committed blob and keeps its base name.
    assert rest.added == [_File("b", "[id].tsx", _show(git_repo, f"{head}:web/[id].tsx"))]
    assert rest.removed == [_File("a", "gone.py", _show(git_repo, f"{base}:src/gone.py"))]
    assert rest.compared == [
        (
            _File("a", "keep.py", _show(git_repo, f"{base}:src/keep.py")),
            _File("b", "keep.py", _show(git_repo, f"{head}:src/keep.py")),
        )
    ]
    # The rename with edits is ONE compared pair, owned by its new (tests) path.
    assert (tests.added, tests.removed) == ([], [])
    assert tests.compared == [
        (
            _File("a", "helper.py", _show(git_repo, f"{base}:src/helper.py")),
            _File("b", "helper.py", _show(git_repo, f"{head}:tests/helper.py")),
        )
    ]
    # The `|`-bearing name is unrepresentable in cloc's list grammar — counted nowhere.
    names = [f.name for call in recorder.calls.values() for f in (*call.added, *call.removed)]
    assert "a|b.py" not in names

    assert [row.id for row in stats.rows] == [row_id for row_id, _ in cs.ROWS]
    assert (stats.base, stats.head) == (base, head)


def test_summarize_counts_committed_bytes_despite_archive_attributes(git_repo):
    # `export-ignore`, `export-subst` and eol attributes are archive/checkout policies, not
    # exclusions from a PR's diff: every changed file is counted as the commits store it.
    (git_repo / ".gitattributes").write_text(
        "tests export-ignore\nsrc/v.py export-subst\n*.txt text eol=crlf\n", encoding="utf-8"
    )
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_x.py").write_text("assert 1\n", encoding="utf-8")
    (git_repo / "src").mkdir()
    (git_repo / "src" / "v.py").write_text('VERSION = "$Format:%H$"\n', encoding="utf-8")
    (git_repo / "notes.txt").write_text("a\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "base")
    base = _head(git_repo)
    (git_repo / "tests" / "test_x.py").write_text("assert 1\nassert 2\n", encoding="utf-8")
    (git_repo / "src" / "v.py").write_text('VERSION = "$Format:%H$"\nX = 1\n', encoding="utf-8")
    (git_repo / "notes.txt").write_text("a\nb\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "head")
    head = _head(git_repo)

    recorder = _Recorder()
    cs.summarize(git_repo, base, head, run_cloc=recorder)
    assert recorder.calls["tests"].compared == [
        (
            _File("a", "test_x.py", _show(git_repo, f"{base}:tests/test_x.py")),
            _File("b", "test_x.py", _show(git_repo, f"{head}:tests/test_x.py")),
        )
    ]
    rest = recorder.calls["rest"]
    assert (rest.added, rest.removed) == ([], [])
    assert rest.compared == [
        (
            _File("a", "notes.txt", b"a\n"),
            _File("b", "notes.txt", b"a\nb\n"),
        ),
        (
            _File("a", "v.py", b'VERSION = "$Format:%H$"\n'),
            _File("b", "v.py", b'VERSION = "$Format:%H$"\nX = 1\n'),
        ),
    ]


def test_summarize_skips_a_non_utf8_name_instead_of_failing(git_repo):
    import os

    base = _head(git_repo)

    def _add(path: str, content: bytes) -> None:
        oid = (
            subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=git_repo,
                input=content,
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .strip()
        )
        _git(git_repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},{path}")

    # Index-only: some filesystems refuse the latin-1 name outright.
    _add(os.fsdecode(b"caf\xe9.py"), b"x = 1\n")
    _add("odd;dir/ok.py", b"y = 1\n")  # only the base name reaches cloc: a `;` directory is fine
    _git(git_repo, "commit", "-qm", "names")
    recorder = _Recorder()
    cs.summarize(git_repo, base, _head(git_repo), run_cloc=recorder)
    assert recorder.calls["rest"].added == [_File("b", "ok.py", b"y = 1\n")]


def test_summarize_same_base_and_head_does_no_work(monkeypatch, tmp_path):
    def _never(*_args, **_kwargs):
        raise AssertionError("no git or cloc work for an empty range")

    monkeypatch.setattr(cs.git, "diff_entries", _never)
    stats = cs.summarize(tmp_path, "a" * 40, "a" * 40, run_cloc=_never)
    assert len(stats.rows) == 5 and all(row.is_zero for row in stats.rows)


def test_summarize_no_entries_skips_cloc(monkeypatch, tmp_path):
    def _never(*_args, **_kwargs):
        raise AssertionError("no cloc call for a range with no changed files")

    monkeypatch.setattr(cs.git, "diff_entries", lambda *_a: ())
    stats = cs.summarize(tmp_path, "a" * 40, "b" * 40, run_cloc=_never)
    assert all(row.is_zero for row in stats.rows)


def _counts(code: int = 0, comment: int = 0, blank: int = 0) -> cloc.Counts:
    return cloc.Counts(files=1, blank=blank, comment=comment, code=code)


def _lang(
    added: cloc.Counts | None = None,
    removed: cloc.Counts | None = None,
    modified: cloc.Counts | None = None,
) -> cloc.LanguageDiff:
    zero = cloc.Counts(0, 0, 0, 0)
    return cloc.LanguageDiff(
        added=added or zero, removed=removed or zero, modified=modified or zero, same=_counts(99)
    )


def test_summarize_aggregates_rows_across_languages(git_repo):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "m.py").write_text("a = 1\n", encoding="utf-8")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-qm", "base")
    base = _head(git_repo)
    (git_repo / "src" / "m.py").write_text("a = 2\n", encoding="utf-8")
    (git_repo / "src" / "conf.yaml").write_text("k: v\n", encoding="utf-8")
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_m.py").write_text("# c\nassert 1\n", encoding="utf-8")
    (git_repo / "docs" / "learned").mkdir(parents=True)
    (git_repo / "docs" / "learned" / "x.md").write_text("# X\n", encoding="utf-8")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-qm", "head")
    head = _head(git_repo)

    recorder = _Recorder(
        {
            "rest": cloc.DiffReport(
                {
                    "Python": _lang(
                        added=_counts(code=4, comment=2, blank=7),
                        removed=_counts(code=1),
                        modified=_counts(code=3, comment=1),
                    ),
                    "YAML": _lang(added=_counts(code=5, comment=1)),
                }
            ),
            "tests": cloc.DiffReport(
                {"Python": _lang(added=_counts(code=10, comment=6), removed=_counts(comment=2))}
            ),
            "learned": cloc.DiffReport({"Markdown": _lang(added=_counts(code=8, comment=1))}),
        }
    )
    stats = cs.summarize(git_repo, base, head, run_cloc=recorder)
    assert {row.id: (row.added, row.removed, row.modified) for row in stats.rows} == {
        "code": (4, 1, 3),
        "tests": (10, 0, 0),
        "comments": (2 + 6, 2, 1),  # source + test-file comments; blanks and `same` excluded
        "learned_docs": (9, 0, 0),
        "other": (6, 0, 0),  # YAML under rest
    }


def test_summarize_maps_cloc_missing(git_repo):
    base, head = _matrix_repo(git_repo)

    def _missing(pairs, *, workdir):
        raise cloc.ClocError("missing", "cloc is not installed.")

    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.summarize(git_repo, base, head, run_cloc=_missing)
    assert (info.value.kind, info.value.message) == ("cloc_missing", "cloc is not installed.")


def test_summarize_maps_other_cloc_errors(git_repo):
    base, head = _matrix_repo(git_repo)

    def _errors(pairs, *, workdir):
        raise cloc.ClocError("errors", "1 error: Unable to read x")

    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.summarize(git_repo, base, head, run_cloc=_errors)
    assert (info.value.kind, info.value.message) == (
        "cloc_failed",
        "errors: 1 error: Unable to read x",
    )


def test_summarize_maps_git_errors(git_repo):
    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.summarize(git_repo, "no-such-ref", "HEAD", run_cloc=_Recorder())
    assert info.value.kind == "git_failed"


def test_summarize_maps_blob_read_failures(monkeypatch, git_repo):
    base, head = _matrix_repo(git_repo)

    def _boom(*_args, **_kwargs):
        raise git.GitError("cat-file exploded")

    monkeypatch.setattr(cs.git, "read_blobs", _boom)
    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.summarize(git_repo, base, head, run_cloc=_Recorder())
    assert info.value.kind == "git_failed"
    assert "cat-file exploded" in info.value.message


def test_summarize_symlink_side_degrades_to_add_or_remove(git_repo):
    (git_repo / "flip.py").write_text("a = 1\n", encoding="utf-8")
    (git_repo / "link.py").symlink_to("flip.py")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-qm", "base")
    base = _head(git_repo)
    (git_repo / "flip.py").unlink()
    (git_repo / "flip.py").symlink_to("f.txt")
    (git_repo / "link.py").unlink()
    (git_repo / "link.py").write_text("b = 2\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "head")
    recorder = _Recorder()
    cs.summarize(git_repo, base, _head(git_repo), run_cloc=recorder)
    rest = recorder.calls["rest"]
    # file → symlink: only the old side counts; symlink → file: only the new side counts.
    assert rest.removed == [_File("a", "flip.py", b"a = 1\n")]
    assert rest.added == [_File("b", "link.py", b"b = 2\n")]
    assert rest.compared == []


# --- resolve_range ---------------------------------------------------------------------------


def test_resolve_range_fetch_uses_the_fetched_remote(git_repo_with_remote):
    clone, _remote, advance_origin = git_repo_with_remote
    fork = _head(clone)
    advanced = advance_origin()
    rng = cs.resolve_range(clone, base="main", fetch=True)
    assert rng.base_ref == "origin/main"
    assert rng.head == fork
    assert rng.base == fork  # HEAD is behind the advanced origin: the merge-base is HEAD
    assert git.resolve_commit(clone, "origin/main") == advanced


def test_resolve_range_fetch_failure_is_unresolved(monkeypatch, git_repo):
    def _fail(*_args, **_kwargs):
        raise git.GitError("network down")

    monkeypatch.setattr(cs.git, "fetch_refspecs", _fail)
    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.resolve_range(git_repo, base="main", fetch=True)
    assert info.value.kind == "range_unresolved"
    assert info.value.message == "could not fetch origin/main: network down"


def test_resolve_range_offline_prefers_origin_then_local(git_repo_with_remote, git_repo):
    clone, _remote, _advance = git_repo_with_remote
    rng = cs.resolve_range(clone, base="main", fetch=False)
    assert rng.base_ref == "origin/main"

    branch = _git(git_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    (git_repo / "g.txt").write_text("g\n", encoding="utf-8")
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-qm", "feature")
    local = cs.resolve_range(git_repo, base=branch, fetch=False)
    assert local.base_ref == branch
    assert local.base == _git(git_repo, "rev-parse", branch).strip()
    assert local.head == _head(git_repo)


def test_resolve_range_unresolved_base_and_head(git_repo):
    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.resolve_range(git_repo, base="no-such-branch", fetch=False)
    assert info.value.kind == "range_unresolved"
    assert "no-such-branch" in info.value.message
    with pytest.raises(cs.ChangeStatsUnavailable) as info:
        cs.resolve_range(git_repo, base="main", head_ref="no-such-head", fetch=False)
    assert info.value.kind == "range_unresolved"


# --- renderers -------------------------------------------------------------------------------

_BASE, _HEAD = "1234567" + "0" * 33, "abcdef0" + "f" * 33


def _sample(**rows: tuple[int, int, int]) -> cs.ChangeStats:
    return cs._stats(_BASE, _HEAD, {k: list(v) for k, v in rows.items()})


def test_render_pr_section_table():
    stats = _sample(code=(120, 30, 12), comments=(4, 0, 1), other=(7, 2, 0))
    assert cs.render_pr_section(stats, note=None) == (
        "### Change stats\n"
        "\n"
        "| | + | \u2212 | ~ |\n"
        "| --- | ---: | ---: | ---: |\n"
        "| Code | 120 | 30 | 12 |\n"
        "| Comments | 4 | 0 | 1 |\n"
        "| Other | 7 | 2 | 0 |\n"
        "\n"
        "<sub>Lines counted by cloc (whitespace-insensitive) over 1234567..abcdef0 — added / "
        "removed / modified; blank lines and files cloc does not recognize are excluded; "
        "renames count under their new path.</sub>"
    )


def test_render_pr_section_all_zero():
    assert cs.render_pr_section(_sample(), note=None) == (
        "### Change stats\n\n_No lines counted by cloc over 1234567..abcdef0._"
    )


def test_render_pr_section_unavailable_normalizes_the_note():
    note = "cloc_failed:\n  errors:   " + "x" * 400
    section = cs.render_pr_section(None, note=note)
    head, body = section.split("\n\n")
    assert head == "### Change stats"
    assert body.startswith("_Unavailable: cloc_failed: errors: xxx")
    assert body.endswith("…._")
    assert "\n" not in body
    assert len(cs.normalize_note(note)) == 200
    assert cs.render_pr_section(None, note="cloc is not installed.") == (
        "### Change stats\n\n_Unavailable: cloc is not installed._"
    )


def test_render_pr_section_requires_exactly_one_input():
    with pytest.raises(ValueError):
        cs.render_pr_section(None, note=None)
    with pytest.raises(ValueError):
        cs.render_pr_section(_sample(), note="both")


def test_render_lines_and_compact():
    stats = _sample(code=(120, 30, 12), tests=(80, 5, 3), learned_docs=(9, 0, 0))
    assert cs.render_lines(stats) == [
        "Code          +120    \u221230     ~12",
        "Tests         +80     \u22125      ~3",
        "Learned docs  +9      \u22120      ~0",
    ]
    assert cs.render_compact(stats) == (
        "code +120 \u221230 ~12 · tests +80 \u22125 ~3 · learned docs +9 \u22120 ~0"
    )
    assert cs.render_lines(_sample()) == ["no lines counted by cloc"]
    assert cs.render_compact(_sample()) == "no counted lines"


def test_change_stats_out_carries_every_row_in_order():
    out = cs.ChangeStatsOut.from_domain(_sample(code=(1, 2, 3)))
    dumped = out.model_dump(mode="json")
    assert dumped["base"] == _BASE and dumped["head"] == _HEAD
    assert [row["id"] for row in dumped["rows"]] == [
        "code",
        "tests",
        "comments",
        "learned_docs",
        "other",
    ]
    assert dumped["rows"][0] == {
        "id": "code",
        "label": "Code",
        "added": 1,
        "removed": 2,
        "modified": 3,
    }


# --- the real cloc ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("cloc") is None, reason="cloc not installed")
def test_real_cloc_counts_a_rename_once_under_its_new_path(git_repo):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "helper.py").write_text(
        "".join(f"line_{n} = {n}\n" for n in range(20)), encoding="utf-8"
    )
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-qm", "base")
    base = _head(git_repo)
    (git_repo / "tests").mkdir()
    _git(git_repo, "mv", "src/helper.py", "tests/helper.py")
    text = (git_repo / "tests" / "helper.py").read_text(encoding="utf-8")
    text = text.replace("line_3 = 3\n", "line_3 = 33\n") + "# trailing note\nextra = 1\n"
    (git_repo / "tests" / "helper.py").write_text(text, encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "head")

    stats = cs.summarize(git_repo, base, _head(git_repo))
    rows = {row.id: (row.added, row.removed, row.modified) for row in stats.rows}
    assert rows == {
        "code": (0, 0, 0),  # nothing under rest: the rename is owned by tests/
        "tests": (1, 0, 1),
        "comments": (1, 0, 0),
        "learned_docs": (0, 0, 0),
        "other": (0, 0, 0),
    }
