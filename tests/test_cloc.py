"""The cloc gateway: list-file bytes, pinned argv, JSON/stderr parsing, and error kinds."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from perk.substrate import cloc
from perk.substrate.proc import ProcFailure

# cloc 2.10's `--json` diff output shape (key order and the `header`/`SUM` blocks included).
_REAL_JSON = """{"header" : {
  "cloc_url"           : "github.com/AlDanial/cloc",
  "cloc_version"       : "2.10",
  "n_files"            : 4,
  "n_lines"            : 10},
 "added" : {
  "YAML" : {"nFiles" : 0, "code" : 0, "comment" : 0, "blank" : 0},
  "Python" : {"code" : 5, "comment" : 0, "nFiles" : 2, "blank" : 1}
  },
 "same" : {
  "YAML" : {"nFiles" : 0, "code" : 0, "comment" : 0, "blank" : 0},
  "Python" : {"code" : 1, "comment" : 0, "nFiles" : 0, "blank" : 0}
  },
 "modified" : {
  "YAML" : {"nFiles" : 0, "code" : 0, "comment" : 0, "blank" : 0},
  "Python" : {"code" : 1, "comment" : 1, "nFiles" : 1, "blank" : 0}
  },
 "removed" : {
  "YAML" : {"nFiles" : 1, "code" : 1, "comment" : 0, "blank" : 0},
  "Python" : {"code" : 0, "comment" : 0, "nFiles" : 0, "blank" : 0}
  },
  "SUM" : {
  "added" : {"code" : 5, "comment" : 0, "nFiles" : 2, "blank" : 1},
  "same" : {"code" : 1, "comment" : 0, "nFiles" : 0, "blank" : 0},
  "modified" : {"code" : 1, "comment" : 1, "nFiles" : 1, "blank" : 0},
  "removed" : {"code" : 1, "comment" : 0, "nFiles" : 1, "blank" : 0}
} }
"""

# cloc 2.10 under `--quiet --show-errors`: the errors block is `warn`ed to stderr, and stdout
# still carries a (here empty) JSON report with exit 0.
_REAL_ERRORS_STDERR = "\n1 error:\nUnable to read:  ../b/nothere.py\n"


def _pairs(root: Path) -> cloc.DiffPairs:
    return cloc.DiffPairs(
        added=[root / "b" / "tests" / "new.py", root / "b" / "x y.md"],
        removed=[root / "a" / "src" / "gone.yaml"],
        compared=[(root / "a" / "src" / "m.py", root / "b" / "src" / "m.py")],
    )


def test_list_file_bytes_are_pinned(tmp_path):
    workdir = tmp_path / "rest"
    assert cloc.render_list_file(_pairs(tmp_path), workdir=workdir) == (
        "Files added: 2\n"
        "+ ../b/tests/new.py ; -\n"
        "+ ../b/x y.md ; -\n"
        "\n"
        "Files removed: 1\n"
        "- ../a/src/gone.yaml ; -\n"
        "\n"
        "File pairs compared: 1\n"
        "!= ../a/src/m.py | ../b/src/m.py ; -\n"
    )


def test_empty_pairs_render_headers_only(tmp_path):
    assert cloc.render_list_file(cloc.DiffPairs(), workdir=tmp_path) == (
        "Files added: 0\n\nFiles removed: 0\n\nFile pairs compared: 0\n"
    )


@pytest.mark.parametrize("name", ["a|b.py", "a;b.py", "a\nb.py", "trailing.py ", "caf\udce9.py"])
def test_unrepresentable_path_raises_parse(tmp_path, name):
    assert cloc.representable(name) is False
    with pytest.raises(cloc.ClocError) as info:
        cloc.render_list_file(cloc.DiffPairs(added=[tmp_path / name]), workdir=tmp_path)
    assert info.value.kind == "parse"
    assert cloc.representable("src/[id].tsx") is True


def test_argv_and_invocation_are_pinned(monkeypatch, tmp_path):
    calls = []

    def _fake(argv, *, cwd: Path, timeout, **_kwargs):
        calls.append((argv, cwd, timeout, (cwd / "pairs.txt").read_text()))
        return subprocess.CompletedProcess(argv, 0, stdout=_REAL_JSON, stderr="")

    monkeypatch.setattr(cloc.shutil, "which", lambda _name: "/usr/bin/cloc")
    monkeypatch.setattr(cloc, "run_captured", _fake)
    workdir = tmp_path / "work" / "rest"
    report = cloc.diff_pairs(_pairs(tmp_path), workdir=workdir)
    [(argv, cwd, timeout, listed)] = calls
    assert argv == [
        "cloc",
        "--diff-list-file",
        str(workdir / "pairs.txt"),
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
    assert cwd == workdir
    assert timeout == 120
    assert listed.startswith("Files added: 2\n")
    assert set(report.languages) == {"Python", "YAML"}


def test_real_output_parses_to_per_language_rows():
    report = cloc.parse_diff_output(_REAL_JSON)
    assert "SUM" not in report.languages and "header" not in report.languages
    python = report.languages["Python"]
    assert python.added == cloc.Counts(files=2, blank=1, comment=0, code=5)
    assert python.modified == cloc.Counts(files=1, blank=0, comment=1, code=1)
    assert python.same == cloc.Counts(files=0, blank=0, comment=0, code=1)
    assert report.languages["YAML"].removed == cloc.Counts(files=1, blank=0, comment=0, code=1)


def test_empty_report_is_empty():
    assert cloc.parse_diff_output("{}\n") == cloc.DiffReport(languages={})


def test_errors_block_on_stderr_raises_errors_even_on_exit_zero():
    with pytest.raises(cloc.ClocError) as info:
        cloc.parse_diff_output("{}\n", _REAL_ERRORS_STDERR)
    assert info.value.kind == "errors"
    assert "Unable to read" in info.value.message


def test_text_outside_the_json_raises_errors():
    with pytest.raises(cloc.ClocError) as info:
        cloc.parse_diff_output("\n2 errors:\nDiff error, exceeded timeout:  x.py\n" + _REAL_JSON)
    assert info.value.kind == "errors"
    assert info.value.message.startswith("2 errors:")


def test_unrelated_stderr_noise_is_tolerated():
    report = cloc.parse_diff_output("{}\n", "perl: warning: Setting locale failed.\n")
    assert report.languages == {}


def test_no_json_raises_parse():
    with pytest.raises(cloc.ClocError) as info:
        cloc.parse_diff_output("not json at all")
    assert info.value.kind == "parse"


def test_malformed_json_raises_parse():
    with pytest.raises(cloc.ClocError) as info:
        cloc.parse_diff_output('{"added": {"Python": {"code": "many"}}}')
    assert info.value.kind == "parse"


def test_nonzero_exit_raises_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(cloc.shutil, "which", lambda _name: "/usr/bin/cloc")
    monkeypatch.setattr(
        cloc,
        "run_captured",
        lambda argv, **_kw: subprocess.CompletedProcess(argv, 2, stdout="", stderr=""),
    )
    with pytest.raises(cloc.ClocError) as info:
        cloc.diff_pairs(cloc.DiffPairs(), workdir=tmp_path)
    assert (info.value.kind, info.value.message) == ("exit", "cloc exited 2")


@pytest.mark.parametrize(("proc_kind", "kind"), [("spawn", "spawn"), ("timeout", "timeout")])
def test_spawn_and_timeout_map_to_same_kinds(monkeypatch, tmp_path, proc_kind, kind):
    def _fail(argv, **_kw):
        raise ProcFailure(proc_kind, tuple(argv), cause_text="boom")

    monkeypatch.setattr(cloc.shutil, "which", lambda _name: "/usr/bin/cloc")
    monkeypatch.setattr(cloc, "run_captured", _fail)
    with pytest.raises(cloc.ClocError) as info:
        cloc.diff_pairs(cloc.DiffPairs(), workdir=tmp_path)
    assert info.value.kind == kind


def test_missing_binary_never_spawns(monkeypatch, tmp_path):
    def _never(*_args, **_kwargs):
        raise AssertionError("cloc must not be spawned when it is not on PATH")

    monkeypatch.setattr(cloc.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cloc, "run_captured", _never)
    with pytest.raises(cloc.ClocError) as info:
        cloc.diff_pairs(cloc.DiffPairs(), workdir=tmp_path)
    assert info.value.kind == "missing"
    assert cloc.INSTALL_HINT in str(info.value)


@pytest.mark.skipif(shutil.which("cloc") is None, reason="cloc not installed")
def test_real_cloc_counts_a_hand_written_pair_set(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "src").mkdir(parents=True)
    (b / "src").mkdir(parents=True)
    (a / "src" / "m.py").write_text("def f():\n    # c\n    return 1\n", encoding="utf-8")
    (b / "src" / "m.py").write_text("def f():\n    # c2\n    return 2\n\nx = 1\n")
    (b / "dup1.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    (b / "dup2.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    (a / "gone.yaml").write_text("k: v\n", encoding="utf-8")
    pairs = cloc.DiffPairs(
        added=[b / "dup1.py", b / "dup2.py"],
        removed=[a / "gone.yaml"],
        compared=[(a / "src" / "m.py", b / "src" / "m.py")],
    )
    report = cloc.diff_pairs(pairs, workdir=tmp_path / "work")
    python = report.languages["Python"]
    # Identical added files both count; lines added inside a compared pair fold into `added`.
    assert python.added == cloc.Counts(files=2, blank=1, comment=0, code=5)
    assert python.modified == cloc.Counts(files=1, blank=0, comment=1, code=1)
    assert report.languages["YAML"].removed == cloc.Counts(files=1, blank=0, comment=0, code=1)


@pytest.mark.skipif(shutil.which("cloc") is None, reason="cloc not installed")
def test_real_cloc_reports_a_missing_file_as_errors(tmp_path):
    pairs = cloc.DiffPairs(added=[tmp_path / "b" / "nothere.py"])
    with pytest.raises(cloc.ClocError) as info:
        cloc.diff_pairs(pairs, workdir=tmp_path / "work")
    assert info.value.kind == "errors"


@pytest.mark.skipif(shutil.which("cloc") is None, reason="cloc not installed")
def test_real_cloc_empty_pairs_is_an_empty_report(tmp_path):
    assert cloc.diff_pairs(cloc.DiffPairs(), workdir=tmp_path).languages == {}
