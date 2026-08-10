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
``perk:workflow-state``) are projected alongside the message fields, and the header projects its
``timestamp``. The parser **never raises** (mirroring
``read_session_pointers`` / ``export_session_jsonl``): a missing file → an empty
:class:`ParsedSession`; a non-JSON / non-object / type-less line → counted in ``malformed_lines``,
never raised. Real logs already carry entry ``type`` values absent from the installed type union
(``active_long_running`` / ``needs_attention``), so any unknown ``type`` parses fine — the
classifier downstream treats it as boilerplate.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from perk.boundary import LenientParseModel
from perk.substrate.output import user_output


@dataclass(frozen=True)
class ToolCall:
    """One assistant tool call: the tool ``name`` + its arguments rendered as compact JSON
    (``args_text``). A parsed projection, not a behavioral entity."""

    name: str
    args_text: str


@dataclass(frozen=True)
class SessionEntry:
    """One flat, frozen projection of a Pi session-log entry — the fields the normalization
    pipeline + renderer need, nothing more. ``index`` is the entry's position in file order
    (header excluded); ``kind`` is the JSONL ``type``."""

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
    is_error: bool
    command: str | None
    output: str | None
    exit_code: int | None
    summary: str | None
    tokens_before: int | None
    read_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    from_id: str | None


@dataclass(frozen=True)
class SessionHeader:
    """The projected session-header line (``type:"session"``). All fields best-effort."""

    session_id: str | None
    cwd: str | None
    version: int | None
    timestamp: str | None


@dataclass(frozen=True)
class ParsedSession:
    """The full parse result: the header (when present), the entries in file order, and the count
    of malformed (non-JSON / non-object / type-less) lines."""

    header: SessionHeader | None
    entries: tuple[SessionEntry, ...]
    malformed_lines: int


class _ContentItem(LenientParseModel):
    """One item of an ``AgentMessage.content`` array (text / thinking / toolCall blocks)."""

    type: str | None = None
    text: str | None = None
    thinking: str | None = None
    name: str | None = None
    arguments: dict[str, object] | None = None


class _MessageModel(LenientParseModel):
    """The nested ``AgentMessage`` of a ``message`` entry (role + content + tool-result fields)."""

    role: str | None = None
    content: tuple[_ContentItem, ...] = ()
    tool_name: str | None = Field(default=None, alias="toolName")
    is_error: bool = Field(default=False, alias="isError")


class _CompactionDetails(LenientParseModel):
    """A compaction entry's ``details`` payload (perk stamps read/modified file lists)."""

    read_files: tuple[str, ...] = Field(default=(), alias="readFiles")
    modified_files: tuple[str, ...] = Field(default=(), alias="modifiedFiles")


class SessionEntryModel(LenientParseModel):
    """The untrusted read-edge over one session-log line. Only ``type`` is required; every other
    field is optional so a quirky entry degrades gracefully rather than raising. Camel-cased
    grammar keys map through ``Field(alias=…)`` (the base sets ``populate_by_name``)."""

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

    def to_domain(self, *, index: int) -> SessionEntry:
        """Project this validated line into a frozen :class:`SessionEntry` at file position
        ``index`` (header excluded). Joins display text, extracts assistant thinking + tool calls,
        and lifts compaction file lists — degrading every absent field to its empty value."""
        role = self.message.role if self.message is not None else None
        text = self._joined_text()
        thinking = self._joined_thinking()
        tool_calls = self._tool_calls()
        tool_name = self.message.tool_name if self.message is not None else None
        is_error = self.message.is_error if self.message is not None else False
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
            is_error=is_error,
            command=self.command,
            output=self.output,
            exit_code=self.exit_code,
            summary=self.summary,
            tokens_before=self.tokens_before,
            read_files=read_files,
            modified_files=modified_files,
            from_id=self.from_id,
        )

    def _joined_text(self) -> str:
        """The message's display text — every ``text`` content block joined by blank lines."""
        if self.message is None:
            return ""
        parts = [c.text for c in self.message.content if c.type == "text" and c.text]
        return "\n\n".join(parts)

    def _joined_thinking(self) -> str:
        """The assistant's reasoning — every ``thinking`` content block joined by blank lines."""
        if self.message is None:
            return ""
        parts = [c.thinking for c in self.message.content if c.type == "thinking" and c.thinking]
        return "\n\n".join(parts)

    def _tool_calls(self) -> tuple[ToolCall, ...]:
        """The assistant's tool calls, each with ``arguments`` rendered as compact JSON."""
        if self.message is None:
            return ()
        calls: list[ToolCall] = []
        for c in self.message.content:
            if c.type != "toolCall":
                continue
            args_text = json.dumps(c.arguments, sort_keys=True) if c.arguments else "{}"
            calls.append(ToolCall(name=c.name or "", args_text=args_text))
        return tuple(calls)


_EMPTY = ParsedSession(header=None, entries=(), malformed_lines=0)


def parse_session_jsonl(path: Path) -> ParsedSession:
    """Parse a Pi session-log JSONL file into a :class:`ParsedSession` (never raises).

    A missing/unreadable file → an empty :class:`ParsedSession`. Each non-empty line is JSON-decoded
    then validated through :class:`SessionEntryModel`; a non-JSON / non-object / type-less line is
    counted in ``malformed_lines`` (never raised). The first ``type:"session"`` line projects into
    the header (excluded from ``entries`` and from the entry index); every other valid line becomes
    a :class:`SessionEntry` in file order.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return _EMPTY

    header: SessionHeader | None = None
    entries: list[SessionEntry] = []
    malformed = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed += 1
            continue
        if not isinstance(obj, dict):
            malformed += 1
            continue
        try:
            model = SessionEntryModel.model_validate(obj)
        except ValueError:
            malformed += 1
            continue
        if model.type == "session" and header is None:
            header = SessionHeader(
                session_id=_opt_str(obj.get("id")),
                cwd=_opt_str(obj.get("cwd")),
                version=_opt_int(obj.get("version")),
                timestamp=_opt_str(obj.get("timestamp")),
            )
            continue
        entries.append(model.to_domain(index=len(entries)))

    if malformed:
        user_output(f"warning: {malformed} malformed line(s) in session log {path}")
    return ParsedSession(header=header, entries=tuple(entries), malformed_lines=malformed)


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
