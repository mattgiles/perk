"""`perk.cli.paged_files` — the shared byte-exact paged-file writer + pointer measurement.

Small on purpose: the atomic primitive underneath (`atomic_write_text`) is pinned by its own
suite (`tests/test_cache.py::test_atomic_write_text_*`) and is NOT re-tested here — only the
measurement arithmetic and the writer's delegation/byte-exactness."""

from pathlib import Path

from perk.cli.paged_files import TextFileRef, TextFileRefOut, measure_text, write_text_file

# Pi's per-line ``read`` bound the consumers compare ``max_line_bytes`` against.
_PI_LINE_BOUND = 51_200


def test_measure_text_empty_is_all_zero(tmp_path: Path):
    ref = measure_text(tmp_path / "x.md", "")
    assert ref == TextFileRef(path=tmp_path / "x.md", bytes=0, lines=0, max_line_bytes=0)


def test_measure_text_counts_lines_without_a_trailing_newline():
    ref = measure_text(Path("/p"), "a\nbb\nccc")
    assert (ref.bytes, ref.lines, ref.max_line_bytes) == (8, 3, 3)


def test_measure_text_trailing_newline_does_not_add_a_line():
    assert measure_text(Path("/p"), "a\nbb\n").lines == 2


def test_measure_text_uses_utf8_bytes_not_characters():
    ref = measure_text(Path("/p"), "é\n日本")
    assert ref.bytes == len("é\n日本".encode())
    assert ref.max_line_bytes == len("日本".encode())


def test_measure_text_reports_a_line_above_the_pi_bound():
    ref = measure_text(Path("/p"), "x" * 60_000)
    assert ref.max_line_bytes == 60_000 > _PI_LINE_BOUND
    assert ref.lines == 1


def test_write_text_file_is_byte_exact_and_returns_the_written_pointer(tmp_path: Path):
    text = "  leading\n\n日本\ntrailing-no-newline"
    path = tmp_path / "out.md"
    ref = write_text_file(path, text)
    assert ref.path == path
    assert path.read_bytes() == text.encode("utf-8")
    assert ref == measure_text(path, text)


def test_write_text_file_does_not_normalize_a_trailing_newline(tmp_path: Path):
    path = tmp_path / "out.md"
    write_text_file(path, "a\n")
    assert path.read_bytes() == b"a\n"
    write_text_file(path, "a")
    assert path.read_bytes() == b"a"


def test_write_text_file_overwrites_a_previous_file(tmp_path: Path):
    path = tmp_path / "out.md"
    write_text_file(path, "long long long content\n")
    ref = write_text_file(path, "short\n")
    assert path.read_text(encoding="utf-8") == "short\n"
    assert ref.bytes == len(b"short\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.md"]


def test_text_file_ref_out_maps_path_to_str(tmp_path: Path):
    ref = TextFileRef(path=tmp_path / "f.md", bytes=3, lines=1, max_line_bytes=3)
    out = TextFileRefOut.from_domain(ref)
    assert out.model_dump(mode="json") == {
        "path": str(tmp_path / "f.md"),
        "bytes": 3,
        "lines": 1,
        "max_line_bytes": 3,
    }
