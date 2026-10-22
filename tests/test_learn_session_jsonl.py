"""The Pi session-log JSONL parser (`contracts.md` §8.35)."""

import json
from pathlib import Path

from perk.learn.session_jsonl import (
    NestedCall,
    NestedCalls,
    SectionChange,
    SessionEntryModel,
    SystemState,
    parse_session_jsonl,
)

# The released nested-call grammar (pi-ai 0.99.2 `NestedToolCallRecord` / `NestedToolCalls`),
# attached by Pi at the calling tool's `message.nestedCalls`: an ok call, an error call, and a
# call whose arguments were omitted over budget (`argumentsBytes` set instead) — so the block is
# incomplete.
_NESTED_CALLS_FIXTURE: dict[str, object] = {
    "calls": [
        {
            "id": "tc1/1",
            "name": "read",
            "arguments": {"path": "a.ts"},
            "status": "ok",
            "durationMs": 12,
        },
        {
            "id": "tc1/2",
            "name": "write",
            "arguments": {"path": "b.ts"},
            "status": "error",
            "durationMs": 3,
            "error": "write is blocked (read-only)",
        },
        {"id": "tc1/3", "name": "read", "argumentsBytes": 9000, "status": "ok"},
    ],
    "complete": False,
}


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


def test_parse_tool_call_id_projection():
    # The grammar's pairing ids ride the projection: a toolCall content item's `id` lands on
    # ToolCall.call_id and a toolResult message's `toolCallId` on SessionEntry.tool_call_id.
    call = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "a1",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call_7",
                            "name": "bash",
                            "arguments": {"command": "ls"},
                        }
                    ],
                },
            }
        )
    )
    assert call.tool_calls[0].call_id == "call_7"
    assert call.tool_call_id is None
    result = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "t1",
                "message": {
                    "role": "toolResult",
                    "toolName": "bash",
                    "toolCallId": "call_7",
                    "content": [{"type": "text", "text": "ok"}],
                },
            }
        )
    )
    assert result.tool_call_id == "call_7"


def test_parse_absent_tool_call_ids_stay_none():
    call = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "a1",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "toolCall", "name": "bash", "arguments": {}}],
                },
            }
        )
    )
    assert call.tool_calls[0].call_id is None
    result = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "t1",
                "message": {"role": "toolResult", "toolName": "bash", "content": []},
            }
        )
    )
    assert result.tool_call_id is None


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
    assert cm.content == "ctx"


def test_parse_custom_entry_projects_data_and_content():
    # The audit census reads `perk:workflow-state` payloads (top-level `data`) and warm-injected
    # context text (top-level `content`) straight off the projection.
    c = _entry(
        json.dumps(
            {
                "type": "custom",
                "id": "w1",
                "customType": "perk:workflow-state",
                "data": {"run_id": "01ABC", "stage": "implement", "mode": "read-write"},
            }
        )
    )
    assert c.data == {"run_id": "01ABC", "stage": "implement", "mode": "read-write"}
    assert c.content is None


def test_parse_absent_data_and_content_stay_none():
    e = _entry(json.dumps({"type": "message", "id": "u1", "message": {"role": "user"}}))
    assert e.content is None and e.data is None


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
    assert parsed.header.timestamp is None
    assert len(parsed.entries) == 1
    assert parsed.entries[0].index == 0 and parsed.entries[0].role == "user"
    assert parsed.malformed_lines == 3


def test_parse_header_timestamp_projects(tmp_path: Path):
    log = tmp_path / "s.jsonl"
    log.write_text(
        json.dumps(
            {"type": "session", "id": "S", "cwd": "/repo", "timestamp": "2026-01-02T03:04:05Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    parsed = parse_session_jsonl(log)
    assert parsed.header is not None
    assert parsed.header.timestamp == "2026-01-02T03:04:05Z"


def test_parse_raw_chars_reconcile(tmp_path: Path):
    # The raw-chars metric reconciles exactly: per-entry raw_chars + the header's +
    # malformed_chars cover the whole transcript (code points of decoded lines, newlines
    # excluded) — unprojected fields (message.details) included. The 🎉 (non-BMP) pins the
    # unit as code points: len() counts it once where UTF-16 units would count 2 and
    # UTF-8 bytes 4.
    header_line = json.dumps({"type": "session", "id": "S", "cwd": "/repo"})
    entry_lines = [
        json.dumps(
            {
                "type": "message",
                "id": "u1",
                "message": {"role": "user", "content": [{"type": "text", "text": "hello 🎉"}]},
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "type": "message",
                "id": "t1",
                "message": {"role": "toolResult", "toolName": "bash", "content": []},
                "details": {"unprojected": "payload counted by raw_chars"},
            }
        ),
        # A nested-call record is part of the line, so raw_chars counts it too.
        _tool_result_line(_NESTED_CALLS_FIXTURE, entry_id="t2"),
    ]
    # One line per malformed arm — non-JSON, non-object JSON, and type-less — each has its
    # own accumulation site in the parse loop; the sum assertion catches a dropped arm.
    malformed_lines = [
        "not json at all",
        json.dumps([1, 2, 3]),
        json.dumps({"no": "type"}),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text(
        "\n".join([header_line, *entry_lines, *malformed_lines]) + "\n", encoding="utf-8"
    )
    parsed = parse_session_jsonl(log)
    assert parsed.header is not None
    assert parsed.header.raw_chars == len(header_line)
    assert [e.raw_chars for e in parsed.entries] == [len(line) for line in entry_lines]
    assert parsed.malformed_lines == 3
    assert parsed.malformed_chars == sum(len(line) for line in malformed_lines)


def test_parse_raw_chars_default_zero():
    # to_domain's keyword defaults to 0 — the additive field never churns direct call sites.
    e = _entry(json.dumps({"type": "message", "id": "u1", "message": {"role": "user"}}))
    assert e.raw_chars == 0


def test_parse_missing_file_is_empty(tmp_path: Path):
    parsed = parse_session_jsonl(tmp_path / "nope.jsonl")
    assert parsed.header is None and parsed.entries == () and parsed.malformed_lines == 0
    assert parsed.malformed_chars == 0


def test_parse_invalid_utf8_is_empty_never_raises(tmp_path: Path):
    # A valid header line followed by undecodable bytes: the whole-file read fails, and the
    # never-raises contract degrades it to an empty parse (one damaged historical log must
    # not abort a corpus-wide consumer).
    log = tmp_path / "s.jsonl"
    head = json.dumps({"type": "session", "id": "S", "cwd": "/repo"}).encode("utf-8")
    log.write_bytes(head + b"\n\xff\xfe not utf-8 \xff\n")
    parsed = parse_session_jsonl(log)
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


# --- nested-call evidence (message.nestedCalls) ---------------------------------------------------


def _tool_result_line(nested: object = None, *, absent: bool = False, entry_id: str = "t1") -> str:
    """A toolResult line (the parent `codemode` call succeeded) carrying `nested` verbatim."""
    message: dict[str, object] = {
        "role": "toolResult",
        "toolName": "codemode",
        "toolCallId": "tc1",
        "isError": False,
        "content": [{"type": "text", "text": "Script completed"}],
    }
    if not absent:
        message["nestedCalls"] = nested
    return json.dumps({"type": "message", "id": entry_id, "message": message})


def _nested(line: str) -> NestedCalls:
    nested = _entry(line).nested_calls
    assert nested is not None
    return nested


def test_nested_calls_project_the_released_grammar():
    e = _entry(_tool_result_line(_NESTED_CALLS_FIXTURE))
    assert e.nested_calls == NestedCalls(
        calls=(
            NestedCall(
                call_id="tc1/1",
                name="read",
                status="ok",
                args_text='{"path": "a.ts"}',
                arguments_bytes=None,
                duration_ms=12,
                error=None,
            ),
            NestedCall(
                call_id="tc1/2",
                name="write",
                status="error",
                args_text='{"path": "b.ts"}',
                arguments_bytes=None,
                duration_ms=3,
                error="write is blocked (read-only)",
            ),
            NestedCall(
                call_id="tc1/3",
                name="read",
                status="ok",
                args_text=None,  # omitted by Pi over budget — never invented
                arguments_bytes=9000,
                duration_ms=None,
                error=None,
            ),
        ),
        complete=False,
        malformed=0,
        dropped=0,
    )
    # The parent's own flag is untouched by a failed child.
    assert e.is_error is False
    assert e.text == "Script completed"


def test_nested_calls_status_kept_verbatim_or_unknown():
    calls = [
        {"id": "x/1", "name": "read", "status": "unfinished"},
        {"id": "x/2", "name": "read", "status": "someday"},
        {"id": "x/3", "name": "read", "status": 7},
        {"id": "x/4", "name": "read"},
    ]
    nested = _nested(_tool_result_line({"calls": calls, "complete": False}))
    assert [c.status for c in nested.calls] == ["unfinished", "someday", "unknown", "unknown"]


def test_nested_calls_empty_arguments_render_as_empty_object():
    nested = _nested(
        _tool_result_line(
            {"calls": [{"id": "x/1", "name": "ls", "arguments": {}}], "complete": True}
        )
    )
    assert nested.calls[0].args_text == "{}"
    assert nested.complete is True


def test_nested_calls_absent_and_null_are_none():
    assert _entry(_tool_result_line(absent=True)).nested_calls is None
    assert _entry(_tool_result_line(None)).nested_calls is None


def test_nested_calls_malformed_block_degrades_explicitly():
    assert _nested(_tool_result_line("nope")) == NestedCalls(
        calls=(), complete=False, malformed=1, dropped=0
    )
    assert _nested(_tool_result_line([1, 2])) == NestedCalls(
        calls=(), complete=False, malformed=1, dropped=0
    )
    # A non-list `calls` still reads the grammar's `complete`.
    assert _nested(_tool_result_line({"calls": {}, "complete": True})) == NestedCalls(
        calls=(), complete=True, malformed=1, dropped=0
    )


def test_nested_calls_unreadable_records_counted_siblings_kept():
    calls = [
        "not a record",
        {"id": "x/2", "status": "ok"},  # no name
        {"id": 3, "name": "read"},  # non-string id
        {"id": "x/4", "name": "read", "status": "ok"},
    ]
    nested = _nested(_tool_result_line({"calls": calls, "complete": True}))
    assert [c.call_id for c in nested.calls] == ["x/4"]
    assert nested.malformed == 3
    assert nested.complete is True


def test_nested_calls_complete_true_only_when_literally_true():
    record = [{"id": "x/1", "name": "read", "status": "ok"}]
    assert _nested(_tool_result_line({"calls": record})).complete is False
    assert _nested(_tool_result_line({"calls": record, "complete": "true"})).complete is False
    assert _nested(_tool_result_line({"calls": record, "complete": 1})).complete is False


def test_nested_calls_counts_round_finite_floats():
    nested = _nested(
        _tool_result_line(
            {
                "calls": [
                    {
                        "id": "x/1",
                        "name": "read",
                        "status": "ok",
                        "durationMs": 12.0,
                        "argumentsBytes": 8999.6,
                    }
                ],
                "complete": False,
            }
        )
    )
    assert nested.calls[0].duration_ms == 12
    assert nested.calls[0].arguments_bytes == 9000


def test_nested_calls_non_finite_and_non_numeric_counts_degrade_to_none():
    # `json.loads` accepts the NaN / Infinity / -Infinity tokens and turns 1e309 into inf; int()
    # of any of them raises — the projection must not.
    raw = (
        '{"type": "message", "id": "t1", "message": {"role": "toolResult", "toolName": "codemode",'
        ' "content": [], "nestedCalls": {"complete": false, "calls": ['
        '{"id": "x/1", "name": "read", "status": "ok", "durationMs": 1e309},'
        '{"id": "x/2", "name": "read", "status": "ok", "durationMs": NaN},'
        '{"id": "x/3", "name": "read", "status": "ok", "durationMs": -Infinity},'
        '{"id": "x/4", "name": "read", "status": "ok", "argumentsBytes": "big"},'
        '{"id": "x/5", "name": "read", "status": "ok", "argumentsBytes": true, "durationMs": 4}'
        "]}}}"
    )
    nested = _nested(raw)
    assert [c.call_id for c in nested.calls] == ["x/1", "x/2", "x/3", "x/4", "x/5"]
    assert [c.duration_ms for c in nested.calls] == [None, None, None, None, 4]
    assert [c.arguments_bytes for c in nested.calls] == [None, None, None, None, None]
    assert nested.malformed == 0


def test_nested_calls_cap_drops_the_excess():
    calls = [{"id": f"x/{n}", "name": "read", "status": "ok"} for n in range(300)]
    nested = _nested(_tool_result_line({"calls": calls, "complete": False}))
    assert len(nested.calls) == 256
    assert nested.calls[-1].call_id == "x/255"
    assert nested.dropped == 44
    assert nested.malformed == 0


def test_parse_file_nested_calls_never_make_the_line_malformed(tmp_path: Path):
    # A full-file regression: the projection runs outside the parser's per-line except arm, so a
    # non-finite count or an unreadable sibling must degrade inside it — never raise, never cost
    # the line or the entries after it.
    nested_line = (
        '{"type": "message", "id": "t1", "parentId": "a1", "message": {"role": "toolResult",'
        ' "toolName": "codemode", "toolCallId": "tc1", "isError": false,'
        ' "content": [{"type": "text", "text": "Script completed"}],'
        ' "nestedCalls": {"complete": false, "calls": ['
        '{"id": "tc1/1", "name": "read", "status": "ok", "durationMs": 1e309},'
        '"garbage",'
        '{"id": "tc1/3", "name": "write", "status": "error", "error": "blocked"}'
        "]}}}"
    )
    lines = [
        json.dumps({"type": "session", "id": "S", "cwd": "/repo", "version": 3}),
        json.dumps(
            {"type": "message", "id": "a1", "message": {"role": "assistant", "content": []}}
        ),
        nested_line,
        json.dumps(
            {
                "type": "message",
                "id": "u2",
                "parentId": "t1",
                "message": {"role": "user", "content": [{"type": "text", "text": "next"}]},
            }
        ),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 0
    assert [e.entry_id for e in parsed.entries] == ["a1", "t1", "u2"]
    nested = parsed.entries[1].nested_calls
    assert nested is not None
    assert [(c.call_id, c.status, c.duration_ms) for c in nested.calls] == [
        ("tc1/1", "ok", None),
        ("tc1/3", "error", None),
    ]
    assert nested.malformed == 1
    assert parsed.entries[1].raw_chars == len(nested_line)
    assert parsed.entries[2].text == "next"
    assert parsed.entries[0].nested_calls is None


# --- system entries (Pi's persisted `SystemMessage` grammar) --------------------------------------

# Modelled on the real leading entry Pi >= 0.99 writes: the prompt lives in `sections`, the tool
# set in `toolsAdded`, and `content` is the empty string.
_SYSTEM_SNAPSHOT_FIXTURE: dict[str, object] = {
    "type": "message",
    "id": "s1",
    "parentId": "c0",
    "message": {
        "role": "system",
        "content": "",
        "sections": {"preamble": "You are an expert coding assistant.", "rules": "Be concise."},
        "toolsAdded": [
            {"name": "read", "description": "Read a file.", "parameters": {"type": "object"}}
        ],
        "timestamp": 1,
    },
}


def _message_line(entry_id: str, parent_id: str | None, message: dict[str, object]) -> str:
    return json.dumps(
        {"type": "message", "id": entry_id, "parentId": parent_id, "message": message}
    )


def _system_delta(entry_id: str, parent_id: str | None, **fields: object) -> str:
    return _message_line(entry_id, parent_id, {"role": "system", "content": "", **fields})


def test_parse_system_snapshot_projects_ancestry_and_empty_text():
    e = _entry(json.dumps(_SYSTEM_SNAPSHOT_FIXTURE))
    assert e.kind == "message" and e.role == "system"
    assert e.text == "" and e.thinking == "" and e.tool_calls == ()
    assert e.entry_id == "s1" and e.parent_id == "c0"
    assert e.content is None and e.data is None and e.tool_name is None


def _state(
    *,
    content: str = "",
    sections: tuple[SectionChange, ...] = (),
    tools_added: tuple[str, ...] = (),
    tools_removed: tuple[str, ...] = (),
    malformed: int = 0,
    dropped: int = 0,
) -> SystemState:
    return SystemState(
        content=content,
        sections=sections,
        tools_added=tools_added,
        tools_removed=tools_removed,
        malformed=malformed,
        dropped=dropped,
    )


def test_system_snapshot_projects_sections_and_tool_names():
    e = _entry(json.dumps(_SYSTEM_SNAPSHOT_FIXTURE))
    assert e.system_state == _state(
        sections=(
            SectionChange("preamble", "You are an expert coding assistant."),
            SectionChange("rules", "Be concise."),
        ),
        tools_added=("read",),
    )
    assert e.text == "" and e.entry_id == "s1" and e.parent_id == "c0"
    # Modelled on the real mid-session delta: changed sections plus full `Tool` records, of which
    # only the names are projected (descriptions and parameter schemas never are).
    delta = _entry(
        _system_delta(
            "s2",
            "s1",
            sections={
                "tools": "<tools>\n- push_annotations\n</tools>",
                "rules": "<rules>r</rules>",
            },
            toolsAdded=[
                {
                    "name": "collect_draft_review_wave",
                    "description": "Collect the wave.",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
                {
                    "name": "push_annotations",
                    "description": "Push annotations.",
                    "parameters": {"type": "object", "properties": {}},
                },
            ],
            timestamp=2,
        )
    )
    assert delta.system_state == _state(
        sections=(
            SectionChange("tools", "<tools>\n- push_annotations\n</tools>"),
            SectionChange("rules", "<rules>r</rules>"),
        ),
        tools_added=("collect_draft_review_wave", "push_annotations"),
    )
    removal = _entry(
        _system_delta("s3", "s2", sections={"rules": None}, toolsRemoved=[{"name": "edit"}])
    )
    assert removal.system_state == _state(
        sections=(SectionChange("rules", None),), tools_removed=("edit",)
    )


def test_system_state_is_none_without_the_grammar_fields():
    content_only = _entry(_message_line("s1", None, {"role": "system", "content": "You are."}))
    assert content_only.system_state is None and content_only.text == "You are."
    # A non-system role carrying the grammar fields is tolerated, never projected: a `<user>`
    # block must never carry tool declarations.
    user = _entry(
        _message_line(
            "u1",
            "s1",
            {
                "role": "user",
                "content": "hi",
                "sections": {"rules": "obey"},
                "toolsAdded": [{"name": "bash"}],
            },
        )
    )
    assert user.system_state is None and user.text == "hi"
    messages: tuple[dict[str, object], ...] = (
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "toolResult", "toolName": "ls", "toolCallId": "c1", "content": []},
    )
    for message in messages:
        assert _entry(_message_line("m1", None, message)).system_state is None
    assert _entry(json.dumps({"type": "custom", "id": "x1"})).system_state is None


def test_parse_system_delta_tolerates_section_and_tool_deltas():
    e = _entry(
        _system_delta(
            "s2",
            "s1",
            sections={"rules": None, "tools": "Use the read tool."},
            toolsAdded=[{"name": "bash", "description": "Run.", "parameters": {}}],
            toolsRemoved=[{"name": "edit"}],
            timestamp=2,
        )
    )
    assert e.role == "system" and e.text == "" and e.entry_id == "s2" and e.parent_id == "s1"
    # Hostile shapes of the grammar fields never fail the line: they degrade inside the
    # projection into explicit `malformed` counts.
    hostile = _entry(
        _system_delta("s3", "s2", sections=42, toolsAdded="x", toolsRemoved={}, timestamp="t")
    )
    assert hostile.role == "system" and hostile.entry_id == "s3" and hostile.parent_id == "s2"
    assert hostile.system_state == _state(malformed=3)


def test_system_state_unreadable_parts_counted_siblings_kept():
    sections = _entry(_system_delta("s2", "s1", sections={"rules": 7, "tools": "ok", "docs": None}))
    assert sections.system_state == _state(
        sections=(SectionChange("tools", "ok"), SectionChange("docs", None)), malformed=1
    )
    tools = _entry(
        _system_delta(
            "s3",
            "s2",
            toolsAdded=[{"name": 3}, "bash", {"description": "no name"}, {"name": "ok"}],
        )
    )
    assert tools.system_state == _state(tools_added=("ok",), malformed=3)
    assert tools.entry_id == "s3" and tools.parent_id == "s2"


def test_system_state_caps_drop_the_excess():
    sections = {f"s{i:02d}": f"text {i}" for i in range(40)}
    capped = _entry(_system_delta("s1", None, sections=sections))
    assert capped.system_state is not None
    assert [c.name for c in capped.system_state.sections] == [f"s{i:02d}" for i in range(32)]
    assert capped.system_state.dropped == 8 and capped.system_state.malformed == 0
    tools = _entry(
        _system_delta(
            "s2",
            "s1",
            sections=sections,
            toolsAdded=[{"name": f"t{i}"} for i in range(300)],
            toolsRemoved=[{"name": f"r{i}"} for i in range(10)],
        )
    )
    state = tools.system_state
    assert state is not None
    assert state.tools_added == tuple(f"t{i}" for i in range(256))
    assert state.tools_removed == tuple(f"r{i}" for i in range(10))
    assert state.dropped == 8 + 44
    # Oversized text and names are projected verbatim: bounding is the renderer's step.
    big = _entry(
        _system_delta(
            "s3", "s2", sections={"rules": "r" * 50_000}, toolsAdded=[{"name": "n" * 5000}]
        )
    )
    assert big.system_state == _state(
        sections=(SectionChange("rules", "r" * 50_000),), tools_added=("n" * 5000,)
    )


def test_parse_string_content_is_the_text_for_any_role():
    system = _entry(_message_line("s1", None, {"role": "system", "content": "You are perk."}))
    assert system.role == "system" and system.text == "You are perk."
    user = _entry(_message_line("u1", "s1", {"role": "user", "content": "You are perk."}))
    assert user.role == "user" and user.text == "You are perk."
    assert user.thinking == "" and user.tool_calls == ()


def test_parse_system_text_blocks_join():
    e = _entry(
        _message_line(
            "s1",
            None,
            {
                "role": "system",
                "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
            },
        )
    )
    assert e.text == "a\n\nb"


def test_parse_null_content_is_empty_never_malformed():
    system = _entry(_message_line("s1", "c0", {"role": "system", "content": None}))
    assert system.text == "" and system.entry_id == "s1" and system.parent_id == "c0"
    user = _entry(_message_line("u1", "s1", {"role": "user", "content": None}))
    assert user.role == "user" and user.text == ""
    assert user.entry_id == "u1" and user.parent_id == "s1"


def test_parse_file_malformed_content_counts_the_line(tmp_path: Path):
    # A content shape outside the union (a number, an object) still fails the line — the
    # existing malformed posture, which loses the line's id/parent.
    bad_lines = [
        _message_line("m1", "u0", {"role": "system", "content": 42}),
        _message_line("m2", "m1", {"role": "user", "content": {"type": "text", "text": "x"}}),
    ]
    good_before = _message_line("u0", None, {"role": "user", "content": "hi"})
    good_after = _message_line("a1", "m2", {"role": "assistant", "content": []})
    log = tmp_path / "s.jsonl"
    log.write_text(
        "\n".join([json.dumps({"type": "session", "id": "S"}), good_before, *bad_lines, good_after])
        + "\n",
        encoding="utf-8",
    )
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 2
    assert parsed.malformed_chars == sum(len(line) for line in bad_lines)
    assert [e.entry_id for e in parsed.entries] == ["u0", "a1"]
    # The survivor keeps the dangling parent string; the branch walk stops there by design.
    assert parsed.entries[1].parent_id == "m2"


def test_parse_file_mixed_historical_and_system_entries(tmp_path: Path):
    lines = [
        json.dumps({"type": "session", "id": "S", "version": 3}),
        _message_line("u1", None, {"role": "user", "content": [{"type": "text", "text": "hi"}]}),
        _message_line(
            "a1",
            "u1",
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "c1", "name": "ls", "arguments": {}}],
            },
        ),
        _message_line(
            "t1",
            "a1",
            {
                "role": "toolResult",
                "toolName": "ls",
                "toolCallId": "c1",
                "content": [{"type": "text", "text": "a.py"}],
            },
        ),
        json.dumps({**_SYSTEM_SNAPSHOT_FIXTURE, "parentId": "t1"}),
        _system_delta("s2", "s1", sections={"rules": "Be terse."}),
        _system_delta("s3", "s2", toolsRemoved=[{"name": "read"}]),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 0
    assert [(e.entry_id, e.kind, e.role) for e in parsed.entries] == [
        ("u1", "message", "user"),
        ("a1", "message", "assistant"),
        ("t1", "message", "toolResult"),
        ("s1", "message", "system"),
        ("s2", "message", "system"),
        ("s3", "message", "system"),
    ]
    assert [e.index for e in parsed.entries] == list(range(6))
    assert parsed.entries[0].text == "hi"
    assert parsed.entries[1].tool_calls[0].name == "ls"
    assert parsed.entries[2].text == "a.py" and parsed.entries[2].tool_call_id == "c1"
    assert [e.system_state for e in parsed.entries[:3]] == [None, None, None]
    snapshot, delta, removal = (e.system_state for e in parsed.entries[3:])
    assert snapshot is not None and snapshot.tools_added == ("read",)
    assert [c.name for c in snapshot.sections] == ["preamble", "rules"]
    assert delta == _state(sections=(SectionChange("rules", "Be terse."),))
    assert removal == _state(tools_removed=("read",))


def test_parse_file_resume_tree_compaction_with_system_entries(tmp_path: Path):
    lines = [
        json.dumps({"type": "session", "id": "S", "cwd": "/repo", "version": 3}),
        json.dumps({"type": "model_change", "id": "c0", "parentId": None, "modelId": "m"}),
        json.dumps(_SYSTEM_SNAPSHOT_FIXTURE),
        _message_line("u1", "s1", {"role": "user", "content": [{"type": "text", "text": "go"}]}),
        _message_line(
            "a1",
            "u1",
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "k1", "name": "read", "arguments": {}}],
            },
        ),
        _message_line(
            "t1",
            "a1",
            {"role": "toolResult", "toolName": "read", "toolCallId": "k1", "content": []},
        ),
        # A fork: two assistant children of the same toolResult.
        _message_line("a2", "t1", {"role": "assistant", "content": "abandoned"}),
        _message_line(
            "a3", "t1", {"role": "assistant", "content": [{"type": "text", "text": "kept"}]}
        ),
        json.dumps(
            {
                "type": "compaction",
                "id": "k0",
                "parentId": "a3",
                "summary": "compacted so far",
                "tokensBefore": 4321,
                "firstKeptEntryId": "a3",
                "systemMessage": {
                    "role": "system",
                    "content": "snapshot prompt",
                    "sections": {"preamble": "You are an expert coding assistant."},
                },
            }
        ),
        _system_delta("s2", "k0", toolsRemoved=[{"name": "edit"}]),
        json.dumps({"type": "branch_summary", "id": "b1", "parentId": "s2", "summary": "fork"}),
        _message_line(
            "a4", "b1", {"role": "assistant", "content": [{"type": "text", "text": "leaf"}]}
        ),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 0
    assert parsed.header is not None and parsed.header.version == 3
    assert len(parsed.entries) == len(lines) - 1
    by_id = {e.entry_id: e for e in parsed.entries}
    compaction = by_id["k0"]
    assert compaction.kind == "compaction"
    assert compaction.summary == "compacted so far" and compaction.tokens_before == 4321
    # The compaction's system snapshot projects through the same record, `content` included.
    assert compaction.system_state == _state(
        content="snapshot prompt",
        sections=(SectionChange("preamble", "You are an expert coding assistant."),),
    )
    assert compaction.text == ""
    assert by_id["s2"].system_state == _state(tools_removed=("edit",))
    assert by_id["s1"].parent_id == "c0" and by_id["s2"].parent_id == "k0"
    assert by_id["a2"].text == "abandoned" and by_id["a3"].text == "kept"


def _compaction_line(entry_id: str, parent_id: str | None, system_message: object) -> str:
    return json.dumps(
        {
            "type": "compaction",
            "id": entry_id,
            "parentId": parent_id,
            "summary": "compacted",
            "tokensBefore": 99,
            "systemMessage": system_message,
        }
    )


def test_compaction_system_snapshot_degrades_locally():
    not_an_object = _entry(_compaction_line("k1", "a1", "nope"))
    assert not_an_object.system_state == _state(malformed=1)
    assert not_an_object.summary == "compacted" and not_an_object.tokens_before == 99
    assert not_an_object.entry_id == "k1" and not_an_object.parent_id == "a1"

    bad_content = _entry(
        _compaction_line("k2", "k1", {"content": 5, "toolsAdded": [{"name": "read"}]})
    )
    assert bad_content.system_state == _state(tools_added=("read",), malformed=1)

    text_blocks = _entry(
        _compaction_line(
            "k3", "k2", {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
        )
    )
    assert text_blocks.system_state == _state(content="a\n\nb")

    # pi-ai's list arm is `TextContent[]`: every other member is a malformed instruction record,
    # counted one each, with the readable siblings kept.
    mixed = _entry(
        _compaction_line(
            "k4",
            "k3",
            {
                "content": [
                    {"type": "text", "text": 7},
                    "x",
                    {"type": "image"},
                    {"type": "text", "text": "kept"},
                ]
            },
        )
    )
    assert mixed.system_state == _state(content="kept", malformed=3)

    all_invalid = _entry(_compaction_line("k5", "k4", {"content": [{"type": "text", "text": 7}]}))
    assert all_invalid.system_state == _state(malformed=1)

    absent = _entry(_compaction_line("k6", "k5", None))
    assert absent.system_state is None

    # A `systemMessage` on a non-compaction entry is tolerated, never projected.
    on_message = _entry(
        json.dumps(
            {
                "type": "message",
                "id": "m1",
                "message": {"role": "assistant", "content": "ok"},
                "systemMessage": {"content": "prompt", "toolsAdded": [{"name": "bash"}]},
            }
        )
    )
    assert on_message.system_state is None and on_message.text == "ok"


def test_parse_file_system_state_never_makes_the_line_malformed(tmp_path: Path):
    # A full-file regression: the projection runs outside the parser's per-line except arm, so
    # every hostile shape must degrade inside it — never raise, never cost the line, its ancestry
    # or the entries after it.
    system_lines = [
        _system_delta("s1", None, sections=42, toolsAdded="x", toolsRemoved={}),
        _system_delta(
            "s2",
            "s1",
            sections={"rules": 7, "tools": "ok", "docs": None},
            toolsAdded=[{"name": 3}, "bash", {"description": "no name"}, {"name": "ok"}],
        ),
        _compaction_line("k1", "s2", "nope"),
        _compaction_line(
            "k2",
            "k1",
            {
                "content": [{"type": "text", "text": 7}, "x", {"type": "text", "text": "kept"}],
                "sections": [1, 2],
                "toolsRemoved": [None],
            },
        ),
    ]
    lines = [
        json.dumps({"type": "session", "id": "S", "version": 3}),
        *system_lines,
        _message_line("u1", "k2", {"role": "user", "content": "next"}),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 0
    assert [(e.entry_id, e.parent_id) for e in parsed.entries] == [
        ("s1", None),
        ("s2", "s1"),
        ("k1", "s2"),
        ("k2", "k1"),
        ("u1", "k2"),
    ]
    assert [e.raw_chars for e in parsed.entries[:4]] == [len(line) for line in system_lines]
    assert [e.system_state.malformed for e in parsed.entries[:4] if e.system_state] == [3, 4, 1, 4]
    assert parsed.entries[3].system_state is not None
    assert parsed.entries[3].system_state.content == "kept"
    assert parsed.entries[4].text == "next" and parsed.entries[4].system_state is None
