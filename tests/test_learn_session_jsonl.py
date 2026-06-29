"""The Pi session-log JSONL parser (`contracts.md` §8.35, node 3.2)."""

import json
from pathlib import Path

from perk.learn.session_jsonl import SessionEntryModel, parse_session_jsonl


def _entry(line: str):
    return SessionEntryModel.model_validate(json.loads(line)).to_domain(index=0)


def test_parse_user_message():
    e = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "u1",
                "parentId": None,
                "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            }
        )
    )
    assert e.kind == "message" and e.role == "user"
    assert e.text == "hello" and e.thinking == "" and e.tool_calls == ()


def test_parse_assistant_with_thinking_text_toolcall():
    e = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "a1",
                "parentId": "u1",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "ponder"},
                        {"type": "text", "text": "answer"},
                        {"type": "toolCall", "name": "bash", "arguments": {"command": "ls"}},
                    ],
                },
            }
        )
    )
    assert e.role == "assistant"
    assert e.thinking == "ponder" and e.text == "answer"
    assert len(e.tool_calls) == 1
    assert e.tool_calls[0].name == "bash"
    assert e.tool_calls[0].args_text == '{"command": "ls"}'


def test_parse_toolresult_with_is_error():
    e = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "t1",
                "message": {
                    "role": "toolResult",
                    "toolName": "bash",
                    "isError": True,
                    "content": [{"type": "text", "text": "boom"}],
                },
            }
        )
    )
    assert e.role == "toolResult" and e.tool_name == "bash"
    assert e.is_error is True and e.text == "boom"


def test_parse_bash_execution():
    e = _entry(
        json.dumps(
            {
                "type": "bashExecution",
                "id": "b1",
                "command": "echo hi",
                "output": "hi",
                "exitCode": 0,
            }
        )
    )
    assert e.kind == "bashExecution"
    assert e.command == "echo hi" and e.output == "hi" and e.exit_code == 0


def test_parse_compaction_with_details():
    e = _entry(
        json.dumps(
            {
                "type": "compaction",
                "id": "c1",
                "summary": "compacted",
                "tokensBefore": 1234,
                "details": {"readFiles": ["/a", "/b"], "modifiedFiles": ["/c"]},
            }
        )
    )
    assert e.kind == "compaction" and e.summary == "compacted"
    assert e.read_files == ("/a", "/b") and e.modified_files == ("/c",)


def test_parse_branch_summary():
    e = _entry(
        json.dumps({"type": "branch_summary", "id": "s1", "fromId": "x9", "summary": "branched"})
    )
    assert e.kind == "branch_summary"
    assert e.from_id == "x9" and e.summary == "branched"


def test_parse_custom_and_custom_message():
    c = _entry(json.dumps({"type": "custom", "id": "x1", "customType": "perk:workflow-state"}))
    cm = _entry(
        json.dumps(
            {
                "type": "custom_message",
                "id": "x2",
                "customType": "perk:binding-context",
                "content": "ctx",
            }
        )
    )
    assert c.kind == "custom" and c.custom_type == "perk:workflow-state"
    assert cm.kind == "custom_message" and cm.custom_type == "perk:binding-context"


def test_parse_unknown_type_tolerated():
    e = _entry(json.dumps({"type": "active_long_running", "id": "z1"}))
    assert e.kind == "active_long_running"


def test_parse_file_counts_malformed_and_header(tmp_path: Path):
    log = tmp_path / "s.jsonl"
    lines = [
        json.dumps({"type": "session", "id": "S", "cwd": "/repo", "version": 3}),
        json.dumps({"type": "message", "id": "u1", "message": {"role": "user", "content": []}}),
        "not json at all",
        json.dumps([1, 2, 3]),  # non-object
        json.dumps({"no": "type"}),  # type-less
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert parsed.header is not None
    assert parsed.header.session_id == "S" and parsed.header.cwd == "/repo"
    assert parsed.header.version == 3
    assert len(parsed.entries) == 1
    assert parsed.entries[0].index == 0 and parsed.entries[0].role == "user"
    assert parsed.malformed_lines == 3


def test_parse_missing_file_is_empty(tmp_path: Path):
    parsed = parse_session_jsonl(tmp_path / "nope.jsonl")
    assert parsed.header is None and parsed.entries == () and parsed.malformed_lines == 0


def test_parse_entries_keep_file_order(tmp_path: Path):
    log = tmp_path / "s.jsonl"
    lines = [
        json.dumps({"type": "session", "id": "S"}),
        json.dumps({"type": "message", "id": "a", "message": {"role": "user", "content": []}}),
        json.dumps({"type": "message", "id": "b", "message": {"role": "assistant", "content": []}}),
    ]
    log.write_text("\n".join(lines), encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert [e.entry_id for e in parsed.entries] == ["a", "b"]
    assert [e.index for e in parsed.entries] == [0, 1]
