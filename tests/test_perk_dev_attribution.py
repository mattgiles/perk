"""Transcript-composition attribution tests (perk_dev.audit.attribution,
`perk-dev audit attribution`).

Synthetic JSONL fixtures follow the test_perk_dev_checks.py conventions (explicit
`id`/`parentId`/tool-call ids/`toolCallId`) and parse through the real read edge, so
raw-chars accounting, pairing, and branch selection are exercised end to end.
"""

import json
from pathlib import Path

from click.testing import CliRunner
from perk_dev.audit.attribution import (
    READ_CLASSES,
    TOP_RESULTS,
    AttributionReport,
    AttributionReportOut,
    attribute_session,
    classify_read_path,
)
from perk_dev.cli import cli

from perk.learn.session_jsonl import ParsedSession, parse_session_jsonl

# ------------------------------------------------------------------------- fixtures


def _user(eid: str, parent: str | None, text: str) -> dict[str, object]:
    return {
        "type": "message",
        "id": eid,
        "parentId": parent,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _call(
    eid: str,
    parent: str | None,
    tool: str,
    args: dict[str, object],
    call_id: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {"type": "toolCall", "name": tool, "arguments": args}
    if call_id is not None:
        item["id"] = call_id
    return {
        "type": "message",
        "id": eid,
        "parentId": parent,
        "message": {"role": "assistant", "content": [item]},
    }


def _result(
    eid: str,
    parent: str | None,
    tool: str,
    *,
    call_id: str | None = None,
    is_error: bool = False,
    text: str = "ok",
) -> dict[str, object]:
    msg: dict[str, object] = {
        "role": "toolResult",
        "toolName": tool,
        "isError": is_error,
        "content": [{"type": "text", "text": text}],
    }
    if call_id is not None:
        msg["toolCallId"] = call_id
    return {"type": "message", "id": eid, "parentId": parent, "message": msg}


def _exec(
    prefix: str,
    parent: str | None,
    tool: str,
    args: dict[str, object],
    *,
    is_error: bool = False,
    result_text: str = "ok",
) -> list[dict[str, object]]:
    """One paired execution as a linear call+result pair; the result's id is `<prefix>r`."""
    call_id = f"c-{prefix}"
    return [
        _call(f"{prefix}a", parent, tool, args, call_id=call_id),
        _result(
            f"{prefix}r",
            f"{prefix}a",
            tool,
            call_id=call_id,
            is_error=is_error,
            text=result_text,
        ),
    ]


def _write(tmp_path: Path, entries: list[dict[str, object]], name: str = "s.jsonl") -> Path:
    lines = [json.dumps({"type": "session", "id": "s", "cwd": "/repo"})]
    lines.extend(json.dumps(e) for e in entries)
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _parse(tmp_path: Path, entries: list[dict[str, object]]) -> ParsedSession:
    return parse_session_jsonl(_write(tmp_path, entries))


def _attribute(tmp_path: Path, entries: list[dict[str, object]]):
    return attribute_session(_parse(tmp_path, entries), source="s.jsonl")


def _index_of(parsed: ParsedSession, eid: str) -> int:
    matches = [e.index for e in parsed.entries if e.entry_id == eid]
    assert len(matches) == 1, f"{eid}: {len(matches)} entries"
    return matches[0]


# --------------------------------------------------------------- classify_read_path


def test_classify_docs_learned():
    assert classify_read_path("docs/learned/pi/subagents.md") == "docs/learned/"
    assert classify_read_path("/abs/worktree/docs/learned/workflow/ruff.md") == "docs/learned/"


def test_classify_skills_segment():
    assert classify_read_path(".agents/skills/x/SKILL.md") == "skills/"
    assert classify_read_path("skills/perk-expert/references/config.md") == "skills/"
    assert classify_read_path(".pi/npm/node_modules/p/skills/librarian/SKILL.md") == "skills/"
    assert classify_read_path("/abs/wt/.agents/skills/dignified-python/SKILL.md") == "skills/"


def test_classify_prompts_segment():
    assert classify_read_path("prompts/stages/plan/seed.md") == "prompts/"
    assert classify_read_path("/abs/wt/prompts/stages/audit.md") == "prompts/"


def test_classify_filename_segments_never_match():
    assert classify_read_path("src/perk/prompts.py") == "other"
    assert classify_read_path("docs/skills") == "other"


def test_classify_precedence_docs_learned_first():
    # A path carrying both cues classifies by the fixed precedence.
    assert classify_read_path("docs/learned/skills/x.md") == "docs/learned/"


def test_classify_backslash_separators_normalize():
    assert classify_read_path("docs\\learned\\pi\\subagents.md") == "docs/learned/"


# --------------------------------------------------------------------- kind rows


def test_kind_rows_totals_and_ordering(tmp_path: Path):
    entries: list[dict[str, object]] = [
        _user("u0", None, "x" * 500),
        *_exec("b1", "u0", "bash", {"command": "ls"}),
        {
            "type": "custom",
            "id": "w1",
            "parentId": "b1r",
            "customType": "perk:workflow-state",
            "data": {"mode": "read-write"},
        },
        {"type": "model_change", "id": "m1", "parentId": "w1"},
        {"type": "message", "id": "q1", "parentId": "m1", "message": {"content": []}},
    ]
    parsed = _parse(tmp_path, entries)
    attributed = attribute_session(parsed, source="s.jsonl")
    assert attributed.total_entries == 6
    assert attributed.total_chars == sum(e.raw_chars for e in parsed.entries)
    labels = {row.label for row in attributed.kinds}
    assert labels == {
        "message:user",
        "message:assistant",
        "message:toolResult",
        "custom:perk:workflow-state",
        "model_change",
        "message:?",
    }
    # Per-kind chars sum to the whole transcript (complete by construction).
    assert sum(row.chars for row in attributed.kinds) == attributed.total_chars
    assert sum(row.entries for row in attributed.kinds) == attributed.total_entries
    # Ordering: chars-desc; the fat user entry sorts first.
    assert attributed.kinds[0].label == "message:user"
    ordering = [(-row.chars, row.label) for row in attributed.kinds]
    assert ordering == sorted(ordering)


def test_tool_rows_group_by_tool_name(tmp_path: Path):
    entries: list[dict[str, object]] = [
        _user("u0", None, "go"),
        *_exec("b1", "u0", "bash", {"command": "ls"}, result_text="y" * 400),
        *_exec("b2", "b1r", "bash", {"command": "pwd"}),
        *_exec("g1", "b2r", "grep", {"pattern": "x"}),
        {
            "type": "message",
            "id": "t9",
            "parentId": "g1r",
            "message": {"role": "toolResult", "content": [{"type": "text", "text": "?"}]},
        },
    ]
    attributed = _attribute(tmp_path, entries)
    by_tool = {row.tool: row for row in attributed.tools}
    assert set(by_tool) == {"bash", "grep", "(unknown)"}
    assert by_tool["bash"].entries == 2
    assert by_tool["grep"].entries == 1
    assert by_tool["(unknown)"].entries == 1
    assert attributed.tools[0].tool == "bash"  # the fat result sorts first


# ------------------------------------------------------------------- read classes


def test_read_attribution_exact_id_pairing(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        *_exec("r1", "u0", "read", {"path": "docs/learned/pi/subagents.md"}),
        *_exec("r2", "r1r", "read", {"path": ".agents/skills/x/SKILL.md"}),
        *_exec("r3", "r2r", "read", {"path": "src/perk/prompts.py"}),
    ]
    attributed = _attribute(tmp_path, entries)
    by_class = {row.read_class: row for row in attributed.read_classes}
    assert tuple(row.read_class for row in attributed.read_classes) == READ_CLASSES
    assert by_class["docs/learned/"].entries == 1
    assert by_class["skills/"].entries == 1
    assert by_class["other"].entries == 1
    assert by_class["prompts/"].entries == 0
    assert by_class["unresolved"].entries == 0
    assert by_class["docs/learned/"].chars > 0


def test_read_attribution_fifo_fallback(tmp_path: Path):
    # Id-less call + id-less result pair FIFO-by-name; the path still resolves.
    entries = [
        _user("u0", None, "go"),
        _call("r1", "u0", "read", {"path": "docs/learned/pi/subagents.md"}),
        _result("r1r", "r1", "read"),
    ]
    attributed = _attribute(tmp_path, entries)
    by_class = {row.read_class: row for row in attributed.read_classes}
    assert by_class["docs/learned/"].entries == 1
    assert by_class["unresolved"].entries == 0


def test_unpaired_read_result_is_unresolved(tmp_path: Path):
    # A read result whose toolCallId matches no call: unpaired — class unresolved.
    entries = [
        _user("u0", None, "go"),
        _result("r1r", "u0", "read", call_id="c-orphan"),
    ]
    attributed = _attribute(tmp_path, entries)
    by_class = {row.read_class: row for row in attributed.read_classes}
    assert by_class["unresolved"].entries == 1


def test_missing_or_non_string_path_is_unresolved(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        *_exec("r1", "u0", "read", {}),
        *_exec("r2", "r1r", "read", {"path": 7}),
    ]
    attributed = _attribute(tmp_path, entries)
    by_class = {row.read_class: row for row in attributed.read_classes}
    assert by_class["unresolved"].entries == 2


def test_errored_read_result_still_attributed(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        *_exec("r1", "u0", "read", {"path": "docs/learned/pi/subagents.md"}, is_error=True),
    ]
    attributed = _attribute(tmp_path, entries)
    by_class = {row.read_class: row for row in attributed.read_classes}
    assert by_class["docs/learned/"].entries == 1


# -------------------------------------------------------------------- top results


def test_top_results_ordering_tiebreak_and_cap(tmp_path: Path):
    entries: list[dict[str, object]] = [_user("u0", None, "go")]
    parent = "u0"
    for n in range(12):
        prefix = f"b{n:02d}"
        # Identical result payloads → identical raw chars → the index tie-break decides.
        entries.extend(_exec(prefix, parent, "bash", {"command": "x"}, result_text="same"))
        parent = f"{prefix}r"
    entries.extend(
        _exec("fat", parent, "read", {"path": "docs/learned/x.md"}, result_text="Z" * 999)
    )
    parsed = _parse(tmp_path, entries)
    attributed = attribute_session(parsed, source="s.jsonl")
    assert len(attributed.top_results) == TOP_RESULTS == 10
    # The fat read leads; provenance carries its recovered path, never content.
    assert attributed.top_results[0].tool == "read"
    assert attributed.top_results[0].path == "docs/learned/x.md"
    assert attributed.top_results[0].index == _index_of(parsed, "fatr")
    # Ties (identical raw chars) break by ascending entry index.
    tie_indices = [t.index for t in attributed.top_results[1:]]
    assert tie_indices == sorted(tie_indices)
    assert tie_indices[0] == _index_of(parsed, "b00r")


def test_top_results_carry_is_error_and_non_read_path_none(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        *_exec("b1", "u0", "bash", {"command": "boom"}, is_error=True, result_text="failed"),
    ]
    attributed = _attribute(tmp_path, entries)
    top = attributed.top_results[0]
    assert top.tool == "bash" and top.is_error is True and top.path is None


# ----------------------------------------------------- off-branch + reconciliation


def test_off_branch_accounting_over_forked_parent_ids(tmp_path: Path):
    # a1/a2 fork off u0 and are abandoned; the active branch is u0 → b1 → b2.
    entries = [
        _user("u0", None, "go"),
        _user("a1", "u0", "abandoned one"),
        _user("a2", "a1", "abandoned two"),
        _user("b1", "u0", "kept"),
        _user("b2", "b1", "the leaf"),
    ]
    parsed = _parse(tmp_path, entries)
    attributed = attribute_session(parsed, source="s.jsonl")
    off = {e.entry_id: e for e in parsed.entries if e.entry_id in ("a1", "a2")}
    assert attributed.off_branch_entries == 2
    assert attributed.off_branch_chars == sum(e.raw_chars for e in off.values())
    assert attributed.total_entries == 5


def test_linear_session_has_zero_off_branch(tmp_path: Path):
    entries = [_user("u0", None, "go"), _user("u1", "u0", "on")]
    attributed = _attribute(tmp_path, entries)
    assert attributed.off_branch_entries == 0 and attributed.off_branch_chars == 0


def test_header_and_malformed_chars_reconcile(tmp_path: Path):
    header_line = json.dumps({"type": "session", "id": "s", "cwd": "/repo"})
    entry_line = json.dumps(_user("u0", None, "hello"))
    malformed_line = "{broken json"
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join([header_line, entry_line, malformed_line]) + "\n", encoding="utf-8")
    attributed = attribute_session(parse_session_jsonl(path), source=str(path))
    assert attributed.header_chars == len(header_line)
    assert attributed.total_chars == len(entry_line)
    assert attributed.malformed_lines == 1
    assert attributed.malformed_chars == len(malformed_line)


def test_empty_parse_attributes_to_zeroes():
    attributed = attribute_session(
        ParsedSession(header=None, entries=(), malformed_lines=0, malformed_chars=0),
        source="gone.jsonl",
    )
    assert attributed.total_entries == 0 and attributed.total_chars == 0
    assert attributed.kinds == () and attributed.tools == () and attributed.top_results == ()
    assert tuple(row.read_class for row in attributed.read_classes) == READ_CLASSES


# --------------------------------------------------------------------------- CLI


def _cli_fixture(tmp_path: Path) -> Path:
    entries = [
        _user("u0", None, "go"),
        *_exec("r1", "u0", "read", {"path": "docs/learned/pi/subagents.md"}),
        *_exec("b1", "r1r", "bash", {"command": "ls"}),
    ]
    return _write(tmp_path, entries)


def test_cli_human_render(tmp_path: Path):
    path = _cli_fixture(tmp_path)
    result = CliRunner().invoke(cli, ["audit", "attribution", str(path)])
    assert result.exit_code == 0, result.output
    assert f"session: {path}" in result.output
    assert "entries 5" in result.output
    assert "off-branch 0 entries (0c)" in result.output
    assert "kinds:" in result.output
    assert "message:assistant:" in result.output
    assert "tools:" in result.output
    assert "read paths:" in result.output
    assert "docs/learned/: 1" in result.output
    assert "top 10 results:" in result.output
    assert "docs/learned/pi/subagents.md" in result.output


def test_cli_json_envelope(tmp_path: Path):
    path = _cli_fixture(tmp_path)
    result = CliRunner().invoke(cli, ["audit", "attribution", "--json", str(path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"success", "error_type", "sessions"}
    assert payload["success"] is True and payload["error_type"] is None
    assert len(payload["sessions"]) == 1
    session = payload["sessions"][0]
    assert set(session) == {
        "source",
        "total_entries",
        "total_chars",
        "header_chars",
        "malformed_lines",
        "malformed_chars",
        "off_branch_entries",
        "off_branch_chars",
        "kinds",
        "tools",
        "read_classes",
        "top_results",
    }
    assert session["source"] == str(path)
    assert set(session["kinds"][0]) == {"label", "entries", "chars"}
    assert set(session["tools"][0]) == {"tool", "entries", "chars"}
    assert set(session["read_classes"][0]) == {"read_class", "entries", "chars"}
    assert set(session["top_results"][0]) == {"index", "tool", "chars", "is_error", "path"}


def test_cli_missing_file_fails_bad_arguments(tmp_path: Path):
    missing = tmp_path / "nope.jsonl"
    result = CliRunner().invoke(cli, ["audit", "attribution", "--json", str(missing)])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "bad_arguments"
    assert str(missing) in payload["message"]


def test_cli_directory_argument_fails_bad_arguments(tmp_path: Path):
    result = CliRunner().invoke(cli, ["audit", "attribution", str(tmp_path)])
    assert result.exit_code != 0
    assert "not an existing file" in result.output


def test_cli_multi_file_sessions_array(tmp_path: Path):
    one = _write(tmp_path, [_user("u0", None, "one")], name="one.jsonl")
    two = _write(tmp_path, [_user("u0", None, "two"), _user("u1", "u0", "more")], name="two.jsonl")
    result = CliRunner().invoke(cli, ["audit", "attribution", "--json", str(one), str(two)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [s["source"] for s in payload["sessions"]] == [str(one), str(two)]
    assert [s["total_entries"] for s in payload["sessions"]] == [1, 2]


def test_report_out_roundtrip(tmp_path: Path):
    parsed = _parse(tmp_path, [_user("u0", None, "go")])
    report = AttributionReport(sessions=(attribute_session(parsed, source="s.jsonl"),))
    out = AttributionReportOut.from_domain(report)
    assert out.success is True and out.error_type is None
    assert out.sessions[0].source == "s.jsonl"
    assert out.sessions[0].total_entries == 1
