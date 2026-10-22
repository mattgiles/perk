"""The Pi session-log JSONL grammar parser (`contracts.md` §8.35).

A Pi session is an append-only JSONL log: **line 1 is the header** (``{type:"session", …}``) and
each later line is one entry. A ``parentId`` tree threads the entries; the in-memory leaf always
advances to the most-recently appended entry, so the last entry is the active leaf and the active
branch is the ``parentId`` walk from it to the root. (Branch *selection* is
:mod:`perk.learn.normalize`'s concern — this module only parses each line into a flat projection in
file order.)

This is the **lenient read-edge** over the grammar (§8.34 boundary discipline): an untrusted
``SessionEntryModel`` (:class:`~perk.boundary.LenientParseModel`, ``extra="ignore"``) → a frozen
:class:`SessionEntry` projection via ``to_domain``. The projected field list is module-owned (not
contract-pinned): custom entries' top-level ``content`` (warm-injected context text, e.g.
``perk:mode-context`` / ``perk:binding-context``) and ``data`` (structured payloads, e.g.
``perk:workflow-state``) are projected alongside the message fields, the header projects its
``timestamp``, and the tool-call pairing ids ride along (a toolCall content item's ``id`` →
``ToolCall.call_id``; a toolResult message's ``toolCallId`` → ``SessionEntry.tool_call_id``).
The parser **never raises** (mirroring
``read_session_pointers`` / ``export_session_jsonl``): a missing/unreadable/undecodable file → an
empty :class:`ParsedSession`; a non-JSON / non-object / type-less line → counted in
``malformed_lines``, never raised. Real logs already carry entry ``type`` values absent from the
installed type union (``active_long_running`` / ``needs_attention``), so any unknown ``type``
parses fine — the classifier downstream treats it as boilerplate.

**Nested-call evidence.** Pi ≥ 0.99 records the tool calls a tool made through
``ctx.executeTool`` (codemode scripts and other nested callers) on the CALLING tool's toolResult
message as ``message.nestedCalls`` — the pi-ai ``NestedToolCalls`` grammar
``{calls: NestedToolCallRecord[], complete: boolean}`` with records
``{id, name, status: ok|error|unfinished, arguments?, argumentsBytes?, durationMs?, error?}``
(``arguments`` omitted over budget, ``argumentsBytes`` then set; nested results never recorded).
:func:`_project_nested_calls` projects it into :class:`NestedCalls` leniently: it never invents
(omitted arguments stay ``None``; absence never claims completeness), never raises (it runs
outside the parser's per-line ``except`` arm — a raise would abort the whole parse), and degrades
an unreadable block or record into an explicit ``malformed`` count rather than a malformed line.

**System entries.** Pi ≥ 0.99 (session format version 3) persists the pi-ai ``SystemMessage``
grammar ``{role: "system", content: string | TextContent[], sections?: Record<string,
string|null>, toolsAdded?: Tool[], toolsRemoved?: ToolReference[], timestamp}`` as ordinary
``type:"message"`` entries: the leading snapshot (``content: ""``, the prompt in ``sections``, the
tool set in ``toolsAdded``) and later prompt-section / tool-set deltas; a compaction entry also
carries a ``systemMessage`` snapshot. The parser accepts them as context/tool evidence with their
ancestry intact (a rejected line would lose its ``id``/``parentId`` and cut the active branch
short). The string ``content`` arm is role-agnostic — it is the message's display text verbatim
for any role. The grammar is identical at Pi 0.99.2, 1.0.0 and 1.1.0.

**System-state evidence.** What the model was told projects into one bounded, lenient
:class:`SystemState` on ``SessionEntry.system_state``: a system message's ``sections`` (each
name → its new text, or ``None`` when the grammar's ``null`` removed it) and the tool NAMES of
``toolsAdded`` / ``toolsRemoved`` (descriptions and parameter schemas are never projected), and a
compaction entry's ``systemMessage`` snapshot — the same fields plus its instruction
``content`` (a string verbatim, or the text blocks of a ``TextContent[]`` list joined by blank
lines). The projection is keyed on entry kind + role: the message fields only when
``role == "system"``, ``systemMessage`` only on a ``compaction`` entry — other carriers are
tolerated and dropped, so a ``<user>`` block never carries tool declarations. Malformed optional
metadata degrades LOCALLY (the nested-call precedent): the fields are typed ``object`` so no
shape of them fails the line, and the projection counts what it could not read in ``malformed``
(a non-object ``sections`` map, a non-string/non-null section value, a non-list tool list, a
tool record without a string ``name``, a snapshot ``content`` of another shape, each member of a
snapshot ``content`` list that is not a text block with a string ``text``, a non-object snapshot)
and the entries past the caps in ``dropped`` — an otherwise readable entry is never discarded
and branch ancestry is never cut. System state is context/tool evidence: never a user turn, never
user authorization, never a workflow terminal event.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import Field

from perk.boundary import LenientParseModel
from perk.substrate.output import user_output


@dataclass(frozen=True)
class ToolCall:
    """One assistant tool call: the tool ``name`` + its arguments rendered as compact JSON
    (``args_text``) + the grammar's call ``id`` (``call_id``; ``None`` when the line carries
    none). A parsed projection, not a behavioral entity."""

    name: str
    args_text: str
    call_id: str | None


# Mirrors Pi's recorder cap (`NESTED_CALL_LIMITS.maxCalls`), so honest records never hit it.
_MAX_NESTED_CALLS = 256
# System-state projection caps. Pi has no cap of its own (a real session has 8 sections and
# <= ~70 tools; the tool-reference cap reuses Pi's nested-call cap). Together with the renderer's
# text/name caps they fix the record's retained pre-escape content at a known worst case — not its
# total size (each truncation pointer repeats the uncapped entry id and source path), and they do
# NOT make a chunk unsplittable-proof: the chunk splitter is entry-level by design.
_MAX_SECTIONS = 32
_MAX_TOOL_REFS = 256


@dataclass(frozen=True)
class NestedCall:
    """One nested tool call recorded on its caller's toolResult (``message.nestedCalls``).

    ``status`` keeps the grammar's string verbatim (``ok`` / ``error`` / ``unfinished``, or any
    other string a later Pi writes); a non-string status is ``"unknown"``. ``args_text`` is the
    compact JSON of ``arguments`` when recorded, ``None`` when Pi omitted them (over budget) —
    never invented; ``arguments_bytes`` is Pi's size of the omitted arguments, when given.
    """

    call_id: str
    name: str
    status: str
    args_text: str | None
    arguments_bytes: int | None
    duration_ms: int | None
    error: str | None


@dataclass(frozen=True)
class NestedCalls:
    """The projected ``message.nestedCalls`` block. ``complete`` is ``True`` only when the
    grammar's flag is literally ``true``; ``malformed`` counts the records (or the whole block:
    1) the projection could not read; ``dropped`` counts the records beyond the projection cap."""

    calls: tuple[NestedCall, ...]
    complete: bool
    malformed: int
    dropped: int


@dataclass(frozen=True)
class SectionChange:
    """One ``sections`` entry of a system message: ``text`` is the section's new text verbatim,
    ``None`` when the grammar's ``null`` removed it. A parsed projection, never invented."""

    name: str
    text: str | None


@dataclass(frozen=True)
class SystemState:
    """The prompt/tool state a system message declares at one point of the transcript — a
    snapshot on the leading entry and on a compaction, a delta elsewhere.

    ``content`` is the snapshot's instruction text: always ``""`` for a message entry (whose text
    is ``SessionEntry.text``); only a compaction snapshot's ``content`` lands here.
    ``tools_added`` / ``tools_removed`` are tool NAMES only (descriptions and parameter schemas are
    never projected). ``malformed`` counts the parts the projection could not read — a
    non-object ``sections`` map (1), a non-string/non-null section value (1 each), a non-list tool
    list (1 each), a tool record that is not an object with a string ``name`` (1 each), a snapshot
    ``content`` that is neither a string nor a list nor absent (1), each member of a snapshot
    ``content`` list that is not an object with ``type == "text"`` and a string ``text`` (1 each),
    or a non-object snapshot as a whole (1); ``dropped`` counts section entries and tool
    references past the caps. A frozen record of hashable fields, so it compares and hashes
    field-wise (dedup relies on that)."""

    content: str
    sections: tuple[SectionChange, ...]
    tools_added: tuple[str, ...]
    tools_removed: tuple[str, ...]
    malformed: int
    dropped: int


@dataclass(frozen=True)
class SessionEntry:
    """One flat, frozen projection of a Pi session-log entry — the fields the normalization
    pipeline + renderer need, nothing more. ``index`` is the entry's position in file order
    (header excluded); ``kind`` is the JSONL ``type``. ``raw_chars`` is the entry's raw JSONL
    line size in code points (the decoded line, newline excluded) — complete by construction:
    unprojected fields (e.g. ``message.details``) are counted. ``nested_calls`` is a toolResult's
    projected nested-call record (``None`` when the line carries none). ``system_state`` is a
    system entry's / compaction's projected prompt-tool state (``None`` when the line carries
    none)."""

    index: int
    kind: str
    entry_id: str | None
    parent_id: str | None
    role: str | None
    custom_type: str | None
    content: str | None
    data: dict[str, object] | None
    text: str
    thinking: str
    tool_calls: tuple[ToolCall, ...]
    tool_name: str | None
    tool_call_id: str | None
    is_error: bool
    command: str | None
    output: str | None
    exit_code: int | None
    summary: str | None
    tokens_before: int | None
    read_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    from_id: str | None
    raw_chars: int = 0
    nested_calls: NestedCalls | None = None
    system_state: SystemState | None = None


@dataclass(frozen=True)
class SessionHeader:
    """The projected session-header line (``type:"session"``). All fields best-effort.
    ``raw_chars`` is the header line's size in code points (decoded line, newline excluded)."""

    session_id: str | None
    cwd: str | None
    version: int | None
    timestamp: str | None
    raw_chars: int = 0


@dataclass(frozen=True)
class ParsedSession:
    """The full parse result: the header (when present), the entries in file order, and the count
    of malformed (non-JSON / non-object / type-less) lines. ``malformed_chars`` sums those
    lines' sizes in code points (decoded lines, newlines excluded), so per-line ``raw_chars``
    plus the header's plus ``malformed_chars`` reconciles to the whole transcript — modulo
    whitespace-only lines, which the parser skips uncounted."""

    header: SessionHeader | None
    entries: tuple[SessionEntry, ...]
    malformed_lines: int
    malformed_chars: int = 0


class _ContentItem(LenientParseModel):
    """One item of an ``AgentMessage.content`` array (text / thinking / toolCall blocks)."""

    type: str | None = None
    text: str | None = None
    thinking: str | None = None
    id: str | None = None
    name: str | None = None
    arguments: dict[str, object] | None = None


class _MessageModel(LenientParseModel):
    """The nested ``AgentMessage`` of a ``message`` entry (role + content + tool-result fields).

    A system message's ``sections`` / ``toolsAdded`` / ``toolsRemoved`` are typed ``object`` so a
    malformed form degrades inside the projection, never fails the line; they are projected only
    for ``role == "system"``. Every message's ``timestamp`` stays undeclared (``extra="ignore"``
    drops it; never projected).
    """

    role: str | None = None
    # The released `AgentMessage` content union. A `str` is the message's display text verbatim
    # (system instructions, or an SDK-authored user message); the tuple is the block form; `null`
    # (which Pi's own session loader maps to empty) and an absent key both project as empty. Any
    # other shape (a number, a bool, an object) fails validation — the line stays malformed.
    content: str | tuple[_ContentItem, ...] | None = None
    tool_name: str | None = Field(default=None, alias="toolName")
    tool_call_id: str | None = Field(default=None, alias="toolCallId")
    is_error: bool = Field(default=False, alias="isError")
    # Typed `object` so NO shape of the record can fail the line's validation: a malformed block
    # must degrade inside the projection, never turn a readable toolResult into a malformed line.
    nested_calls: object | None = Field(default=None, alias="nestedCalls")
    # The system-message grammar fields, typed `object` for the same reason; projected only for
    # `role == "system"` (see `_project_system_message`).
    sections: object | None = None
    tools_added: object | None = Field(default=None, alias="toolsAdded")
    tools_removed: object | None = Field(default=None, alias="toolsRemoved")

    def blocks(self) -> tuple[_ContentItem, ...]:
        """The block-form content, or ``()`` for the string / ``None`` arms."""
        if isinstance(self.content, tuple):
            return self.content
        return ()


class _CompactionDetails(LenientParseModel):
    """A compaction entry's ``details`` payload (perk stamps read/modified file lists)."""

    read_files: tuple[str, ...] = Field(default=(), alias="readFiles")
    modified_files: tuple[str, ...] = Field(default=(), alias="modifiedFiles")


class SessionEntryModel(LenientParseModel):
    """The untrusted read-edge over one session-log line. Only ``type`` is required; every other
    field is optional so a quirky entry degrades gracefully rather than raising. Camel-cased
    grammar keys map through ``Field(alias=…)`` (the base sets ``populate_by_name``). A compaction
    entry's ``systemMessage`` snapshot is typed ``object`` (no shape of it can fail the line) and
    projected only on a ``compaction`` entry."""

    type: str
    id: str | None = None
    parent_id: str | None = Field(default=None, alias="parentId")
    from_id: str | None = Field(default=None, alias="fromId")
    message: _MessageModel | None = None
    summary: str | None = None
    tokens_before: int | None = Field(default=None, alias="tokensBefore")
    details: _CompactionDetails | None = None
    custom_type: str | None = Field(default=None, alias="customType")
    content: str | None = None
    data: dict[str, object] | None = None
    command: str | None = None
    output: str | None = None
    exit_code: int | None = Field(default=None, alias="exitCode")
    system_message: object | None = Field(default=None, alias="systemMessage")

    def to_domain(self, *, index: int, raw_chars: int = 0) -> SessionEntry:
        """Project this validated line into a frozen :class:`SessionEntry` at file position
        ``index`` (header excluded). Joins display text, extracts assistant thinking + tool calls,
        and lifts compaction file lists — degrading every absent field to its empty value.
        ``raw_chars`` is the source line's size in code points (decoded, newline excluded)."""
        role = self.message.role if self.message is not None else None
        text = self._joined_text()
        thinking = self._joined_thinking()
        tool_calls = self._tool_calls()
        tool_name = self.message.tool_name if self.message is not None else None
        tool_call_id = self.message.tool_call_id if self.message is not None else None
        is_error = self.message.is_error if self.message is not None else False
        nested_calls = (
            _project_nested_calls(self.message.nested_calls) if self.message is not None else None
        )
        read_files = self.details.read_files if self.details is not None else ()
        modified_files = self.details.modified_files if self.details is not None else ()
        return SessionEntry(
            index=index,
            kind=self.type,
            entry_id=self.id,
            parent_id=self.parent_id,
            role=role,
            custom_type=self.custom_type,
            content=self.content,
            data=self.data,
            text=text,
            thinking=thinking,
            tool_calls=tool_calls,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            is_error=is_error,
            command=self.command,
            output=self.output,
            exit_code=self.exit_code,
            summary=self.summary,
            tokens_before=self.tokens_before,
            read_files=read_files,
            modified_files=modified_files,
            from_id=self.from_id,
            raw_chars=raw_chars,
            nested_calls=nested_calls,
            system_state=self._system_state(),
        )

    def _system_state(self) -> SystemState | None:
        """The projected prompt/tool state, keyed on entry kind + role on purpose: a
        ``systemMessage`` on a non-compaction entry and ``sections``/tool lists on a non-system
        role are tolerated and dropped (the grammar never writes them; a ``<user>`` block must
        never carry tool declarations that could read as user authorization)."""
        if self.type == "compaction":
            return _project_system_snapshot(self.system_message)
        if self.message is not None:
            return _project_system_message(self.message)
        return None

    def _joined_text(self) -> str:
        """The message's display text — the string ``content`` verbatim, else every ``text``
        content block joined by blank lines (``""`` for ``null``/absent content)."""
        if self.message is None:
            return ""
        if isinstance(self.message.content, str):
            return self.message.content
        parts = [c.text for c in self.message.blocks() if c.type == "text" and c.text]
        return "\n\n".join(parts)

    def _joined_thinking(self) -> str:
        """The assistant's reasoning — every ``thinking`` content block joined by blank lines."""
        if self.message is None:
            return ""
        parts = [c.thinking for c in self.message.blocks() if c.type == "thinking" and c.thinking]
        return "\n\n".join(parts)

    def _tool_calls(self) -> tuple[ToolCall, ...]:
        """The assistant's tool calls, each with ``arguments`` rendered as compact JSON."""
        if self.message is None:
            return ()
        calls: list[ToolCall] = []
        for c in self.message.blocks():
            if c.type != "toolCall":
                continue
            args_text = json.dumps(c.arguments, sort_keys=True) if c.arguments else "{}"
            calls.append(ToolCall(name=c.name or "", args_text=args_text, call_id=c.id))
        return tuple(calls)


_EMPTY = ParsedSession(header=None, entries=(), malformed_lines=0, malformed_chars=0)


def parse_session_jsonl(path: Path) -> ParsedSession:
    """Parse a Pi session-log JSONL file into a :class:`ParsedSession` (never raises).

    A missing/unreadable/undecodable (invalid UTF-8) file → an empty :class:`ParsedSession`.
    Each non-empty line is JSON-decoded
    then validated through :class:`SessionEntryModel`; a non-JSON / non-object / type-less line is
    counted in ``malformed_lines`` (never raised) with its size accumulated in
    ``malformed_chars``. The first ``type:"session"`` line projects into
    the header (excluded from ``entries`` and from the entry index); every other valid line becomes
    a :class:`SessionEntry` in file order, carrying its raw line size (``raw_chars``: code points
    of the decoded line, newline excluded).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _EMPTY

    header: SessionHeader | None = None
    entries: list[SessionEntry] = []
    malformed = 0
    malformed_chars = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed += 1
            malformed_chars += len(line)
            continue
        if not isinstance(obj, dict):
            malformed += 1
            malformed_chars += len(line)
            continue
        try:
            model = SessionEntryModel.model_validate(obj)
        except ValueError:
            malformed += 1
            malformed_chars += len(line)
            continue
        if model.type == "session" and header is None:
            header = SessionHeader(
                session_id=_opt_str(obj.get("id")),
                cwd=_opt_str(obj.get("cwd")),
                version=_opt_int(obj.get("version")),
                timestamp=_opt_str(obj.get("timestamp")),
                raw_chars=len(line),
            )
            continue
        entries.append(model.to_domain(index=len(entries), raw_chars=len(line)))

    if malformed:
        user_output(f"warning: {malformed} malformed line(s) in session log {path}")
    return ParsedSession(
        header=header,
        entries=tuple(entries),
        malformed_lines=malformed,
        malformed_chars=malformed_chars,
    )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _opt_count(value: object) -> int | None:
    """A recorded count/duration as an ``int``: a finite number rounds; anything else (a bool, a
    string, ``inf``/``-inf``/``nan`` — which ``json.loads`` accepts) is ``None``. Never raises."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return round(value)
    return None


def _json_object(value: object) -> dict[str, object] | None:
    """A decoded JSON object (string keys by construction), else ``None``."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _project_nested_call(raw: object) -> NestedCall | None:
    """One readable record, or ``None`` when it is not an object or its ``id``/``name`` are not
    strings."""
    record = _json_object(raw)
    if record is None:
        return None
    call_id = record.get("id")
    name = record.get("name")
    if not isinstance(call_id, str) or not isinstance(name, str):
        return None
    status = record.get("status")
    arguments = record.get("arguments")
    error = record.get("error")
    return NestedCall(
        call_id=call_id,
        name=name,
        status=status if isinstance(status, str) else "unknown",
        # `json.dumps` over a `json.loads` product cannot raise: keys are strings and non-finite
        # floats serialize.
        args_text=json.dumps(arguments, sort_keys=True) if isinstance(arguments, dict) else None,
        arguments_bytes=_opt_count(record.get("argumentsBytes")),
        duration_ms=_opt_count(record.get("durationMs")),
        error=error if isinstance(error, str) else None,
    )


def _project_nested_calls(raw: object) -> NestedCalls | None:
    """Project a toolResult's ``message.nestedCalls`` (see the module docstring). Total by
    construction: absent/``null`` → ``None``; a non-object block → no calls with
    ``malformed=1``; a non-list ``calls`` → no calls with ``malformed=1`` (``complete`` still
    read); an unreadable record → counted, its siblings kept; records past the cap → ``dropped``."""
    if raw is None:
        return None
    block = _json_object(raw)
    if block is None:
        return NestedCalls(calls=(), complete=False, malformed=1, dropped=0)
    complete = block.get("complete") is True
    records = block.get("calls")
    if not isinstance(records, list):
        return NestedCalls(calls=(), complete=complete, malformed=1, dropped=0)
    calls: list[NestedCall] = []
    malformed = 0
    for record in records[:_MAX_NESTED_CALLS]:
        call = _project_nested_call(record)
        if call is None:
            malformed += 1
        else:
            calls.append(call)
    dropped = max(len(records) - _MAX_NESTED_CALLS, 0)
    return NestedCalls(calls=tuple(calls), complete=complete, malformed=malformed, dropped=dropped)


def _project_tool_names(raw: object) -> tuple[tuple[str, ...], int, int]:
    """A ``toolsAdded`` / ``toolsRemoved`` list as ``(names, malformed, dropped)``: ``None`` →
    nothing; a non-list → ``malformed=1``; over the first ``_MAX_TOOL_REFS`` records, an object
    whose ``name`` is a string → the name, anything else → counted; records past the cap →
    ``dropped``."""
    if raw is None:
        return (), 0, 0
    if not isinstance(raw, list):
        return (), 1, 0
    names: list[str] = []
    malformed = 0
    for record in raw[:_MAX_TOOL_REFS]:
        obj = _json_object(record)
        name = obj.get("name") if obj is not None else None
        if isinstance(name, str):
            names.append(name)
        else:
            malformed += 1
    return tuple(names), malformed, max(len(raw) - _MAX_TOOL_REFS, 0)


def _project_system_state(
    *,
    content: str,
    sections: object,
    tools_added: object,
    tools_removed: object,
    malformed: int = 0,
) -> SystemState:
    """Project the three system-message grammar fields (see the module docstring). Total by
    construction — it runs outside the parser's per-line ``except`` arm, so it never raises:
    ``sections`` absent → none, a non-object → counted, an object → its first
    ``_MAX_SECTIONS`` items in file order (a ``str``/``None`` value kept, any other value counted
    with its siblings kept; the excess → ``dropped``); each tool list via
    :func:`_project_tool_names`."""
    changes: list[SectionChange] = []
    dropped = 0
    if sections is not None:
        section_map = _json_object(sections)
        if section_map is None:
            malformed += 1
        else:
            items = list(section_map.items())
            for name, value in items[:_MAX_SECTIONS]:
                if value is None or isinstance(value, str):
                    changes.append(SectionChange(name=name, text=value))
                else:
                    malformed += 1
            dropped += max(len(items) - _MAX_SECTIONS, 0)
    added, added_malformed, added_dropped = _project_tool_names(tools_added)
    removed, removed_malformed, removed_dropped = _project_tool_names(tools_removed)
    return SystemState(
        content=content,
        sections=tuple(changes),
        tools_added=added,
        tools_removed=removed,
        malformed=malformed + added_malformed + removed_malformed,
        dropped=dropped + added_dropped + removed_dropped,
    )


def _project_system_message(message: _MessageModel) -> SystemState | None:
    """The message-entry arm: ``None`` unless the role is ``system`` AND at least one grammar
    field is present — so a content-only system entry, and every other role, projects nothing
    (and renders byte-identically to a transcript predating the projection)."""
    if message.role != "system":
        return None
    if message.sections is None and message.tools_added is None and message.tools_removed is None:
        return None
    return _project_system_state(
        content="",
        sections=message.sections,
        tools_added=message.tools_added,
        tools_removed=message.tools_removed,
    )


def _snapshot_content(raw_content: object) -> tuple[str, int]:
    """A snapshot's ``content`` as ``(text, malformed)``: a string verbatim; absent/``None`` →
    ``""``; a list → its text blocks (an object with ``type == "text"`` and a string ``text``)
    joined by blank lines, every other member counted (pi-ai's list arm is ``TextContent[]``, so
    there is no valid non-text member to ignore); any other shape → ``("", 1)``."""
    if raw_content is None:
        return "", 0
    if isinstance(raw_content, str):
        return raw_content, 0
    if not isinstance(raw_content, list):
        return "", 1
    parts: list[str] = []
    malformed = 0
    for member in raw_content:
        block = _json_object(member)
        text = block.get("text") if block is not None else None
        if block is not None and block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
        else:
            malformed += 1
    return "\n\n".join(parts), malformed


def _project_system_snapshot(raw: object) -> SystemState | None:
    """The compaction arm: absent/``None`` → ``None``; a non-object snapshot → an empty state
    with ``malformed=1``; an object → its ``content`` (:func:`_snapshot_content`) plus its
    ``sections`` / ``toolsAdded`` / ``toolsRemoved`` through :func:`_project_system_state`."""
    if raw is None:
        return None
    snapshot = _json_object(raw)
    if snapshot is None:
        return SystemState(
            content="", sections=(), tools_added=(), tools_removed=(), malformed=1, dropped=0
        )
    content, malformed = _snapshot_content(snapshot.get("content"))
    return _project_system_state(
        content=content,
        sections=snapshot.get("sections"),
        tools_added=snapshot.get("toolsAdded"),
        tools_removed=snapshot.get("toolsRemoved"),
        malformed=malformed,
    )
