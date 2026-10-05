"""The session-normalization pipeline + renderer + splitter (`contracts.md` §8.35, node 3.2)."""

import json
from dataclasses import fields, replace
from pathlib import Path

from perk.learn.normalize import (
    _MAX_CHUNK_TOKENS,
    _MAX_FILE_LIST,
    _MAX_PAYLOAD_CHARS,
    _TOOL_RESULT_HEAD_LINES,
    SessionReport,
    escape_xml,
    normalize_session,
    render_entry,
    render_evidence,
    sanitize_surrogates,
    select_active_branch,
    split_to_chunks,
)
from perk.learn.session_jsonl import (
    NestedCall,
    NestedCalls,
    ParsedSession,
    SessionEntry,
    ToolCall,
    parse_session_jsonl,
)


def _entry(
    index: int,
    kind: str,
    *,
    entry_id: str | None = None,
    parent_id: str | None = None,
    role: str | None = None,
    custom_type: str | None = None,
    content: str | None = None,
    data: dict[str, object] | None = None,
    text: str = "",
    thinking: str = "",
    tool_calls: tuple[ToolCall, ...] = (),
    tool_name: str | None = None,
    is_error: bool = False,
    command: str | None = None,
    output: str | None = None,
    exit_code: int | None = None,
    summary: str | None = None,
    tokens_before: int | None = None,
    read_files: tuple[str, ...] = (),
    modified_files: tuple[str, ...] = (),
    from_id: str | None = None,
    nested_calls: NestedCalls | None = None,
) -> SessionEntry:
    return SessionEntry(
        index=index,
        kind=kind,
        entry_id=f"e{index}" if entry_id is None else entry_id,
        parent_id=parent_id,
        role=role,
        custom_type=custom_type,
        content=content,
        data=data,
        text=text,
        thinking=thinking,
        tool_calls=tool_calls,
        tool_name=tool_name,
        tool_call_id=None,
        is_error=is_error,
        command=command,
        output=output,
        exit_code=exit_code,
        summary=summary,
        tokens_before=tokens_before,
        read_files=read_files,
        modified_files=modified_files,
        from_id=from_id,
        nested_calls=nested_calls,
    )


def _parsed(*entries: SessionEntry, malformed: int = 0) -> ParsedSession:
    return ParsedSession(header=None, entries=tuple(entries), malformed_lines=malformed)


def _norm(*entries: SessionEntry, malformed: int = 0, source: str = "s.jsonl"):
    return normalize_session(_parsed(*entries, malformed=malformed), source=source)


def test_branch_selection_drops_off_branch_sibling():
    # root e0 <- e1 (leaf); e2 is an abandoned sibling off the leaf's parent chain.
    root = _entry(0, "message", entry_id="r", parent_id=None, role="user", text="root")
    abandoned = _entry(1, "message", entry_id="x", parent_id="r", role="assistant", text="dead")
    leaf = _entry(2, "message", entry_id="l", parent_id="r", role="assistant", text="live")
    n = _norm(root, abandoned, leaf)
    ids = [e.entry_id for e in n.entries]
    assert "x" not in ids and ids == ["r", "l"]


def test_boilerplate_drop_and_digest_sorted():
    entries = [
        _entry(0, "message", role="user", text="hi", parent_id=None),
        _entry(1, "custom", custom_type="perk:workflow-state", parent_id="e0"),
        _entry(2, "model_change", parent_id="e1"),
        _entry(3, "custom", custom_type="perk:workflow-state", parent_id="e2"),
    ]
    n = _norm(*entries)
    labels = [(b.label, b.count) for b in n.boilerplate]
    assert labels == [("custom:perk:workflow-state", 2), ("model_change", 1)]
    assert n.entries_read == 4 and n.entries_kept == 1


def test_dedup_identical_toolresults():
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    e1 = _entry(1, "message", role="toolResult", tool_name="bash", text="same", parent_id="e0")
    e2 = _entry(2, "message", role="toolResult", tool_name="bash", text="same", parent_id="e1")
    n = _norm(e0, e1, e2)
    assert n.duplicate_groups == 1
    assert n.entries[-1].text == "↑ duplicate of entry e1"


def test_dedup_repeated_assistant_text_before_tool_use():
    e0 = _entry(0, "message", role="assistant", text="thinking out loud", parent_id=None)
    e1 = _entry(
        1,
        "message",
        role="assistant",
        text="thinking out loud",
        tool_calls=(ToolCall(name="bash", args_text="{}", call_id=None),),
        parent_id="e0",
    )
    n = _norm(e0, e1)
    assert n.entries[1].text == "" and len(n.entries[1].tool_calls) == 1


def test_prune_empty_turn():
    e0 = _entry(0, "message", role="user", text="hi", parent_id=None)
    e1 = _entry(1, "message", role="assistant", text="", parent_id="e0")
    n = _norm(e0, e1)
    assert [e.entry_id for e in n.entries] == ["e0"]
    assert n.entries_pruned == 1


def test_truncate_large_assistant_text():
    big = "x" * (_MAX_PAYLOAD_CHARS + 500)
    e0 = _entry(0, "message", role="assistant", text=big, parent_id=None)
    n = _norm(e0, source="planning-main.jsonl")
    assert n.truncations == 1
    rendered = n.entries[0].text
    assert "truncated" in rendered and "see entry e0 in planning-main.jsonl" in rendered
    assert len(rendered) < len(big)


def test_line_prune_tool_result_keeps_error_line():
    lines = [f"line {i}" for i in range(_TOOL_RESULT_HEAD_LINES + 20)]
    lines[-1] = "fatal: boom"
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    e1 = _entry(
        1, "message", role="toolResult", tool_name="bash", text="\n".join(lines), parent_id="e0"
    )
    n = _norm(e0, e1)
    assert n.truncations == 1
    out = n.entries[1].text
    assert "lines omitted" in out and "fatal: boom" in out
    assert "line 0" in out and "line 45" not in out


def test_preserve_compaction_with_file_lists():
    files = tuple(f"/abs/file{i}.py" for i in range(_MAX_FILE_LIST + 5))
    e0 = _entry(0, "message", role="user", text="", parent_id=None)  # would be pruned
    e1 = _entry(
        1,
        "compaction",
        summary="compacted here",
        tokens_before=999,
        read_files=files,
        modified_files=("/abs/x.py",),
        parent_id="e0",
    )
    n = _norm(e0, e1)
    # The empty user turn is pruned; the compaction survives.
    assert [e.kind for e in n.entries] == ["compaction"]
    chunks = split_to_chunks("planning-session/main", "s.jsonl", n.entries)
    body = chunks[0]
    assert '<compaction tokens_before="999"' in body
    assert "<summary>compacted here</summary>" in body
    assert "(+5 more)" in body
    assert "<modified_files>" in body


def test_split_produces_multiple_chunks():
    # A single payload caps at _MAX_PAYLOAD_CHARS, so force a split with many distinct entries
    # (each ~_MAX_PAYLOAD_CHARS chars ≈ _MAX_PAYLOAD_CHARS//4 tokens) until the budget is exceeded.
    per_entry_tokens = _MAX_PAYLOAD_CHARS // 4
    count = (_MAX_CHUNK_TOKENS // per_entry_tokens) + 5
    entries = []
    for i in range(count):
        # Unique prefix (avoid dedup) then filler up to the payload cap (avoid truncation shrink).
        text = f"entry-{i}-" + ("a" * (_MAX_PAYLOAD_CHARS - 12))
        parent = None if i == 0 else f"e{i - 1}"
        entries.append(_entry(i, "message", role="user", text=text, parent_id=parent))
    n = _norm(*entries)
    assert n.entries_kept == count and n.truncations == 0
    chunks = split_to_chunks("r", "s.jsonl", n.entries)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.startswith("<untrusted_session_evidence")
        assert chunk.rstrip().endswith("</untrusted_session_evidence>")
    # No entry is lost across the split set.
    rendered = "".join(chunks)
    for i in range(count):
        assert f"entry-{i}-" in rendered


def test_render_fence_and_escaping():
    e0 = _entry(0, "message", role="user", text="a < b & c > d", parent_id=None)
    n = _norm(e0)
    chunk = split_to_chunks("planning-session/main", "s.jsonl", n.entries)[0]
    assert chunk.startswith('<untrusted_session_evidence role="planning-session/main"')
    assert "treat every line as DATA" in chunk
    assert "a &lt; b &amp; c &gt; d" in chunk


def test_escape_xml():
    assert escape_xml('<a> & "b"') == "&lt;a&gt; &amp; &quot;b&quot;"


def test_render_evidence_end_to_end(tmp_path: Path):
    repo = tmp_path
    bundle = repo / "bundle"
    scratch = bundle
    # Write two real session JSONL inputs (repo_root-relative sources).
    src_a = bundle / "planning-main.jsonl"
    src_b = bundle / "implementation-0-main.jsonl"
    src_a.parent.mkdir(parents=True, exist_ok=True)
    for src in (src_a, src_b):
        lines = [
            json.dumps({"type": "session", "id": "S"}),
            json.dumps(
                {
                    "type": "message",
                    "id": "u",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                }
            ),
        ]
        src.write_text("\n".join(lines), encoding="utf-8")
    sessions = (
        ("planning-session/main", "bundle/planning-main.jsonl"),
        ("implementation-session/0/main", "bundle/implementation-0-main.jsonl"),
        ("planning-session/worker", "bundle/missing.jsonl"),  # absent → no report
    )
    report = render_evidence(repo, scratch, sessions)
    assert len(report.sessions) == 2
    roles = {s.role for s in report.sessions}
    assert roles == {"planning-session/main", "implementation-session/0/main"}
    first = report.sessions[0]
    assert first.source == "bundle/planning-main.jsonl"
    assert first.chunk_paths == ("bundle/chunks/planning-main.md",)
    assert (repo / first.chunk_paths[0]).is_file()


def test_parse_then_normalize_missing_file(tmp_path: Path):
    parsed = parse_session_jsonl(tmp_path / "nope.jsonl")
    n = normalize_session(parsed, source="nope.jsonl")
    assert n.entries == () and n.entries_read == 0


def test_sanitize_surrogates_replaces_lone_surrogate_and_keeps_clean_text():
    # str.encode(errors="replace") substitutes the encoder's replacement char `?`.
    assert sanitize_surrogates("ok \ud800 end") == "ok ? end"
    clean = "plain ascii + caf\u00e9 + \U0001f600"
    assert sanitize_surrogates(clean) == clean


def test_render_evidence_survives_lone_surrogate_in_session(tmp_path: Path):
    # An escaped \ud800 survives json.loads into a str; the chunk write must not raise
    # UnicodeEncodeError — it degrades to a replacement character instead.
    repo = tmp_path
    bundle = repo / "bundle"
    src = bundle / "planning-main.jsonl"
    src.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "session", "id": "S"}),
        # json.dumps (ensure_ascii) emits the lone surrogate as the ASCII escape \ud800,
        # exactly as Pi session JSONL carries it; json.loads round-trips it into a str.
        json.dumps(
            {
                "type": "message",
                "id": "u",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "bad \ud800 char"}],
                },
            }
        ),
    ]
    src.write_text("\n".join(lines), encoding="utf-8")
    report = render_evidence(
        repo, bundle, (("planning-session/main", "bundle/planning-main.jsonl"),)
    )
    assert len(report.sessions) == 1
    chunk = (repo / report.sessions[0].chunk_paths[0]).read_text(encoding="utf-8")
    assert "bad ? char" in chunk


# --- nested-call evidence ------------------------------------------------------------


def _call(
    call_id: str,
    name: str = "read",
    status: str = "ok",
    *,
    args_text: str | None = '{"path": "a.ts"}',
    arguments_bytes: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> NestedCall:
    return NestedCall(
        call_id=call_id,
        name=name,
        status=status,
        args_text=args_text,
        arguments_bytes=arguments_bytes,
        duration_ms=duration_ms,
        error=error,
    )


# The projection of the released grammar fixture (see test_learn_session_jsonl.py).
_FIXTURE_NESTED = NestedCalls(
    calls=(
        _call("tc1/1", duration_ms=12),
        _call(
            "tc1/2",
            "write",
            "error",
            args_text='{"path": "b.ts"}',
            duration_ms=3,
            error="write is blocked (read-only)",
        ),
        _call("tc1/3", args_text=None, arguments_bytes=9000),
    ),
    complete=False,
    malformed=0,
    dropped=0,
)


def _tool_result(
    index: int,
    text: str = "",
    nested: NestedCalls | None = None,
    *,
    is_error: bool = False,
    parent_id: str | None = None,
    tool_name: str = "codemode",
) -> SessionEntry:
    return _entry(
        index,
        "message",
        role="toolResult",
        tool_name=tool_name,
        text=text,
        is_error=is_error,
        parent_id=parent_id,
        nested_calls=nested,
    )


def test_render_nested_calls_inside_the_parent_tool_result():
    e = _tool_result(7, "Script completed; error handled", _FIXTURE_NESTED)
    assert render_entry(e) == "\n".join(
        [
            '<tool_result tool="codemode" error="false" id="e7">Script completed; error handled',
            '<nested_calls complete="false">',
            '<nested_call id="tc1/1" name="read" status="ok" ms="12">'
            "<args>{&quot;path&quot;: &quot;a.ts&quot;}</args></nested_call>",
            '<nested_call id="tc1/2" name="write" status="error" ms="3">'
            "<args>{&quot;path&quot;: &quot;b.ts&quot;}</args>"
            "<error>write is blocked (read-only)</error></nested_call>",
            '<nested_call id="tc1/3" name="read" status="ok" args_omitted_bytes="9000">'
            "</nested_call>",
            "</nested_calls></tool_result>",
        ]
    )


def test_render_without_nested_calls_is_byte_identical():
    e = _tool_result(1, "body", None, tool_name="x")
    assert render_entry(e) == '<tool_result tool="x" error="false" id="e1">body</tool_result>'


def test_render_parent_error_is_the_outer_flag_never_a_childs():
    child_failed = NestedCalls(
        calls=(_call("p/1", status="error", error="boom"),), complete=True, malformed=0, dropped=0
    )
    ok_parent = render_entry(_tool_result(1, "done", child_failed))
    assert ok_parent.startswith('<tool_result tool="codemode" error="false" id="e1">')
    assert 'status="error"' in ok_parent
    clean_child = NestedCalls(calls=(_call("p/1"),), complete=True, malformed=0, dropped=0)
    failed_parent = render_entry(_tool_result(1, "Script failed", clean_child, is_error=True))
    assert failed_parent.startswith('<tool_result tool="codemode" error="true" id="e1">')
    assert '<nested_calls complete="true">' in failed_parent


def test_render_nested_loss_diagnostics_only_when_nonzero():
    lossy = NestedCalls(calls=(_call("p/1"),), complete=False, malformed=2, dropped=44)
    assert '<nested_calls complete="false" malformed="2" dropped="44">' in render_entry(
        _tool_result(1, "", lossy)
    )
    only_dropped = replace(lossy, malformed=0)
    assert '<nested_calls complete="false" dropped="44">' in render_entry(
        _tool_result(1, "", only_dropped)
    )
    unreadable = NestedCalls(calls=(), complete=False, malformed=1, dropped=0)
    assert render_entry(_tool_result(1, "", unreadable)) == (
        '<tool_result tool="codemode" error="false" id="e1">\n'
        '<nested_calls complete="false" malformed="1">\n'
        "</nested_calls></tool_result>"
    )


def test_render_nested_calls_escape_every_value():
    hostile = NestedCalls(
        calls=(
            _call(
                'x/1"<&',
                'na"me<',
                'st<a>t&us"',
                args_text='{"q": "a < b & c"}',
                error='bad <tag> & "quote"',
            ),
        ),
        complete=True,
        malformed=0,
        dropped=0,
    )
    rendered = render_entry(_tool_result(1, "", hostile))
    assert (
        '<nested_call id="x/1&quot;&lt;&amp;" name="na&quot;me&lt;" '
        'status="st&lt;a&gt;t&amp;us&quot;">'
    ) in rendered
    assert "<args>{&quot;q&quot;: &quot;a &lt; b &amp; c&quot;}</args>" in rendered
    assert "<error>bad &lt;tag&gt; &amp; &quot;quote&quot;</error>" in rendered


def test_prune_keeps_empty_text_results_with_nested_calls():
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    with_calls = _tool_result(1, "", _FIXTURE_NESTED, parent_id="e0")
    unreadable_only = _tool_result(
        2,
        "",
        NestedCalls(calls=(), complete=False, malformed=1, dropped=0),
        parent_id="e1",
    )
    bare = _tool_result(3, "", None, parent_id="e2")
    n = _norm(e0, with_calls, unreadable_only, bare)
    assert [e.entry_id for e in n.entries] == ["e0", "e1", "e2"]


def test_dedup_collapses_identical_nested_payloads_ignoring_ids_and_durations():
    first = _FIXTURE_NESTED
    again = replace(
        first,
        calls=tuple(
            replace(c, call_id=c.call_id.replace("tc1", "tc9"), duration_ms=99) for c in first.calls
        ),
    )
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    e1 = _tool_result(1, "Script completed", first, parent_id="e0")
    e2 = _tool_result(2, "Script completed", again, parent_id="e1")
    n = _norm(e0, e1, e2)
    assert n.duplicate_groups == 1
    assert n.entries[1].nested_calls == first, "the first occurrence keeps its calls"
    assert n.entries[2].text == "↑ duplicate of entry e1"
    assert n.entries[2].nested_calls is None


def _no_collapse(a: NestedCalls, b: NestedCalls) -> None:
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    e1 = _tool_result(1, "Script completed", a, parent_id="e0")
    e2 = _tool_result(2, "Script completed", b, parent_id="e1")
    n = _norm(e0, e1, e2)
    assert n.duplicate_groups == 0
    assert [e.nested_calls for e in n.entries[1:]] == [a, b]


def test_dedup_child_status_distinguishes_payloads():
    ok = NestedCalls(calls=(_call("p/1"),), complete=True, malformed=0, dropped=0)
    _no_collapse(ok, replace(ok, calls=(_call("p/1", status="error"),)))


def test_dedup_malformed_distinguishes_payloads():
    base = NestedCalls(calls=(_call("p/1"),), complete=False, malformed=0, dropped=0)
    _no_collapse(base, replace(base, malformed=1))


def test_dedup_dropped_distinguishes_payloads():
    base = NestedCalls(calls=(_call("p/1"),), complete=False, malformed=0, dropped=0)
    _no_collapse(base, replace(base, dropped=3))


def test_dedup_omitted_argument_size_distinguishes_payloads():
    a = NestedCalls(
        calls=(_call("p/1"), _call("p/2", args_text=None, arguments_bytes=9000)),
        complete=False,
        malformed=0,
        dropped=0,
    )
    b = replace(a, calls=(_call("p/1"), _call("p/2", args_text=None, arguments_bytes=9001)))
    _no_collapse(a, b)


def test_truncate_nested_args_and_errors_counted_diagnostics_untouched():
    long_args = json.dumps({"content": "x" * 300})
    nested = NestedCalls(
        calls=(
            _call("p/1", args_text=long_args, arguments_bytes=None),
            _call("p/2", status="error", error="e" * 600),
            _call("p/3", status="error", error="f" * 500),
            _call("p/4", args_text=None, arguments_bytes=9000),
        ),
        complete=False,
        malformed=2,
        dropped=5,
    )
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    n = _norm(e0, _tool_result(1, "Script completed", nested, parent_id="e0"))
    assert n.truncations == 2
    out = n.entries[1].nested_calls
    assert out is not None
    args = out.calls[0].args_text
    assert args is not None and len(args) < len(long_args)
    assert args.startswith(long_args[:100]) and args.endswith(long_args[-100:])
    assert f"…[truncated {len(long_args) - 200} chars]…" in args
    error = out.calls[1].error
    assert error == "e" * 250 + "…[truncated 100 chars]…" + "e" * 250
    assert out.calls[2].error == "f" * 500, "a cap-length error is never clipped"
    assert (out.complete, out.malformed, out.dropped) == (False, 2, 5)
    assert out.calls[3] == nested.calls[3]


def test_render_evidence_renders_nested_calls_and_keeps_the_report_shape(tmp_path: Path):
    src = tmp_path / "bundle" / "planning-main.jsonl"
    src.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"type": "session", "id": "S"}),
        json.dumps(
            {
                "type": "message",
                "id": "t1",
                "message": {
                    "role": "toolResult",
                    "toolName": "codemode",
                    "toolCallId": "tc1",
                    "isError": False,
                    "content": [{"type": "text", "text": "Script completed"}],
                    "nestedCalls": {
                        "calls": [
                            {
                                "id": "tc1/1",
                                "name": "write",
                                "arguments": {"path": "b.ts"},
                                "status": "error",
                                "durationMs": 3,
                                "error": "write is blocked (read-only)",
                            }
                        ],
                        "complete": False,
                    },
                },
            }
        ),
    ]
    src.write_text("\n".join(lines), encoding="utf-8")
    report = render_evidence(
        tmp_path, tmp_path / "bundle", (("planning-session/main", "bundle/planning-main.jsonl"),)
    )
    (session,) = report.sessions
    chunk = (tmp_path / session.chunk_paths[0]).read_text(encoding="utf-8")
    assert '<tool_result tool="codemode" error="false" id="t1">Script completed' in chunk
    assert '<nested_calls complete="false">' in chunk
    assert "<error>write is blocked (read-only)</error></nested_call>" in chunk
    assert [f.name for f in fields(SessionReport)] == [
        "role",
        "source",
        "entries_read",
        "entries_kept",
        "entries_pruned",
        "malformed_lines",
        "duplicate_groups",
        "truncations",
        "boilerplate",
        "chunk_paths",
    ]


# --- system entries ------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _msg(entry_id: str, parent_id: str | None, message: dict[str, object]) -> dict[str, object]:
    return {"type": "message", "id": entry_id, "parentId": parent_id, "message": message}


def _system(entry_id: str, parent_id: str | None, **fields: object) -> dict[str, object]:
    return _msg(entry_id, parent_id, {"role": "system", "content": "", **fields})


# The leading snapshot Pi >= 0.99 persists: empty `content`, the prompt in `sections`, the tool
# set in `toolsAdded`.
def _snapshot(entry_id: str, parent_id: str | None) -> dict[str, object]:
    return _system(
        entry_id,
        parent_id,
        sections={"preamble": "You are an expert coding assistant.", "rules": "Be concise."},
        toolsAdded=[{"name": "read", "description": "Read a file.", "parameters": {}}],
        timestamp=1,
    )


def test_branch_walk_survives_a_system_entry_between_branch_nodes(tmp_path: Path):
    log = tmp_path / "s.jsonl"
    _write_jsonl(
        log,
        [
            {"type": "session", "id": "S", "version": 3},
            {
                "type": "custom",
                "id": "e0",
                "parentId": None,
                "customType": "perk:workflow-state",
                "data": {"stage": "plan"},
            },
            _snapshot("e1", "e0"),
            _msg("e2", "e1", {"role": "user", "content": [{"type": "text", "text": "go"}]}),
            _msg("e3", "e2", {"role": "assistant", "content": [{"type": "text", "text": "dead"}]}),
            _msg("e4", "e2", {"role": "assistant", "content": [{"type": "text", "text": "live"}]}),
        ],
    )
    parsed = parse_session_jsonl(log)
    assert parsed.malformed_lines == 0
    assert parsed.entries[1].role == "system" and parsed.entries[1].text == ""
    assert [e.entry_id for e in select_active_branch(parsed.entries)] == ["e0", "e1", "e2", "e4"]
    n = normalize_session(parsed, source="s.jsonl")
    assert [e.entry_id for e in n.entries] == ["e2", "e4"]
    assert [(b.label, b.count) for b in n.boilerplate] == [("custom:perk:workflow-state", 1)]
    # e0 (boilerplate), e1 (empty system snapshot), e3 (off-branch).
    assert n.entries_read == 5 and n.entries_kept == 2 and n.entries_pruned == 3


def test_system_text_is_bounded_and_rendered_as_system_never_user():
    sys_entry = _entry(0, "message", entry_id="s1", role="system", text="x" * 10_000)
    n = _norm(sys_entry, source="s.jsonl")
    assert n.truncations == 1
    rendered = render_entry(n.entries[0])
    assert rendered.startswith('<message role="system" id="s1">')
    removed = 10_000 - _MAX_PAYLOAD_CHARS
    assert f"… [truncated {removed} chars; see entry s1 in s.jsonl] …" in rendered
    chunk = split_to_chunks("planning-session/main", "s.jsonl", n.entries)[0]
    assert "<user" not in chunk


def test_empty_system_deltas_are_never_dedup_candidates():
    e0 = _entry(0, "message", role="user", text="q", parent_id=None)
    e1 = _entry(1, "message", role="system", text="", parent_id="e0")
    e2 = _entry(2, "message", role="system", text="", parent_id="e1")
    # The same rule retires the dangling pointer for repeated empty historical evidence.
    e3 = _tool_result(3, "", None, parent_id="e2", tool_name="bash")
    e4 = _tool_result(4, "", None, parent_id="e3", tool_name="bash")
    e5 = _entry(5, "message", role="assistant", text="done", parent_id="e4")
    n = _norm(e0, e1, e2, e3, e4, e5)
    assert n.duplicate_groups == 0
    assert [e.entry_id for e in n.entries] == ["e0", "e5"]
    assert not any("↑ duplicate" in e.text for e in n.entries)


def test_historical_transcript_renders_byte_identically_with_a_spliced_system_snapshot(
    tmp_path: Path,
):
    def transcript(*, with_snapshot: bool) -> list[dict[str, object]]:
        user_parent = "s1" if with_snapshot else None
        records: list[dict[str, object]] = [{"type": "session", "id": "S", "version": 3}]
        if with_snapshot:
            records.append(_snapshot("s1", None))
        records += [
            _msg("u1", user_parent, {"role": "user", "content": [{"type": "text", "text": "hi"}]}),
            _msg(
                "a1",
                "u1",
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "listing"},
                        {"type": "toolCall", "id": "k1", "name": "bash", "arguments": {"c": "ls"}},
                    ],
                },
            ),
            _msg(
                "t1",
                "a1",
                {
                    "role": "toolResult",
                    "toolName": "bash",
                    "toolCallId": "k1",
                    "content": [{"type": "text", "text": "a.py"}],
                },
            ),
        ]
        return records

    source = "bundle/planning-main.jsonl"
    role = "planning-session/main"
    reports: list[SessionReport] = []
    chunks: list[bytes] = []
    for name, with_snapshot in (("h", False), ("m", True)):
        repo = tmp_path / name
        _write_jsonl(repo / source, transcript(with_snapshot=with_snapshot))
        (session,) = render_evidence(repo, repo / "bundle", ((role, source),)).sessions
        reports.append(session)
        chunks.append((repo / session.chunk_paths[0]).read_bytes())
    historical, modern = reports
    assert chunks[0] == chunks[1]
    assert historical.malformed_lines == 0 and modern.malformed_lines == 0
    assert modern.entries_read == historical.entries_read + 1
    assert modern.entries_pruned == historical.entries_pruned + 1
    assert (
        replace(
            modern,
            entries_read=historical.entries_read,
            entries_pruned=historical.entries_pruned,
        )
        == historical
    )


def test_render_evidence_system_snapshot_and_incomplete_nested_calls(tmp_path: Path):
    source = "bundle/planning-main.jsonl"
    records: list[dict[str, object]] = [
        {"type": "session", "id": "S", "version": 3},
        _snapshot("s1", None),
        _msg("u1", "s1", {"role": "user", "content": [{"type": "text", "text": "run it"}]}),
        _msg(
            "a1",
            "u1",
            {
                "role": "assistant",
                "content": [
                    {"type": "toolCall", "id": "tc1", "name": "codemode", "arguments": {"s": "x"}}
                ],
            },
        ),
        _msg(
            "t1",
            "a1",
            {
                "role": "toolResult",
                "toolName": "codemode",
                "toolCallId": "tc1",
                "isError": False,
                "content": [{"type": "text", "text": "Script completed"}],
                "nestedCalls": {
                    "calls": [
                        {"id": "tc1/1", "name": "read", "arguments": {"p": "a"}, "status": "ok"},
                        {
                            "id": "tc1/2",
                            "name": "write",
                            "arguments": {"p": "b"},
                            "status": "error",
                            "error": "write is blocked (read-only)",
                        },
                        {"id": "tc1/3", "name": "bash", "arguments": {}, "status": "unfinished"},
                    ],
                    "complete": False,
                },
            },
        ),
        _system("s2", "t1", toolsRemoved=[{"name": "edit"}], sections={"rules": None}),
        _msg("a2", "s2", {"role": "assistant", "content": [{"type": "text", "text": "done"}]}),
    ]
    _write_jsonl(tmp_path / source, records)
    (session,) = render_evidence(
        tmp_path, tmp_path / "bundle", (("planning-session/main", source),)
    ).sessions
    chunk = (tmp_path / session.chunk_paths[0]).read_text(encoding="utf-8")
    assert session.malformed_lines == 0
    assert session.entries_read == len(records) - 1
    assert '<tool_result tool="codemode" error="false" id="t1">Script completed' in chunk
    tool_result = chunk[chunk.index('<tool_result tool="codemode"') : chunk.index("</tool_result>")]
    assert '<nested_calls complete="false">' in tool_result
    assert tool_result.count('status="error"') == 1
    assert "<error>write is blocked (read-only)</error>" in tool_result
    assert tool_result.count('status="unfinished"') == 1
    assert 'id="s1"' not in chunk and 'id="s2"' not in chunk
    assert 'role="system"' not in chunk
    assert chunk.count("<user") == 1 and '<user id="u1">' in chunk
