"""The five deterministic session-audit checkers + their registry.

Each checker is a pure function ``ParsedSession -> CheckResult`` over the session JSONL
read edge's flat projection. Semantics are **sound, not complete**: a ``violated`` result
is proof-grade (a decidable clause of the catalog's evidence demonstrably failed);
``satisfied`` means every *deterministically decidable* clause held — each checker's
docstring names its undecidable residue, left to the judgment tier.

Ordering and gate attribution are **branch-aware, not file-order**: a session file is a
branch tree (``entry_id``/``parent_id``), so "X before Y" requires X on Y's ancestor
chain, and gate state for an entry is the nearest workflow-state ``mode`` value among its
ancestors. Presence-shaped checks (nudge uptake, classifier evidence, raw-fetch
detection) stay file-wide by design — the content entered the session regardless of
branch. Degenerate entries (missing ``entry_id``, or ``parent_id`` pointing nowhere)
bridge to the immediately preceding file-order entry — the lenient fallback for quirky
data.

Call/result pairing is exact by tool-call id (``ToolCall.call_id`` ==
``SessionEntry.tool_call_id``), with FIFO-by-name only as the fallback for id-less lines.
The corpus includes **live, still-appending sessions**, so a call whose result has not
landed yet is a *pending* execution, never dropped silently: an absence-shaped verdict
that a pending relevant execution could flip returns ``unchecked`` (the in-flight arm)
instead of a definitive ``violated``. Presence-shaped violations (a successful mutation,
a successful raw fetch) stay decisive — a pending call cannot un-happen them.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from perk.learn.session_jsonl import ParsedSession, SessionEntry, ToolCall
from perk_dev.audit.corpus import NUDGE_PATTERN, TRANSCLUDE_PATTERN, WORKFLOW_STATE_TYPE
from perk_dev.audit.gate_policy import is_read_only_bash_command, split_top_level_segments


@dataclass(frozen=True)
class CheckResult:
    """One checker's verdict over one session.

    ``status`` is ``satisfied`` / ``violated`` / ``not-exercised`` (the checker's
    precondition was absent) / ``unchecked`` (the in-flight arm: a decisive execution is
    still unpaired, so no definitive verdict is derivable). ``entries`` are
    ``SessionEntry.index`` citations (file order, header excluded) — non-empty whenever
    ``status == "violated"``.
    """

    status: str
    entries: tuple[int, ...]
    detail: str


Checker = Callable[[ParsedSession], CheckResult]


# ----------------------------------------------------------------- shared helpers


@dataclass(frozen=True)
class _Execution:
    """One paired tool execution: the call entry, its result entry, the decoded call
    args (raw ``args_text`` kept beside — decode failure degrades to ``{}``), the
    result's display text, and the result's error flag."""

    call_index: int
    result_index: int
    args: dict[str, object]
    args_text: str
    result_text: str
    is_error: bool


@dataclass(frozen=True)
class _PendingCall:
    """One tool call with no paired result — a live session's in-flight execution (or a
    truncated/aborted one). Decisive for nothing; blocks absence-shaped verdicts."""

    call_index: int
    args: dict[str, object]
    args_text: str


def _tool_calls(parsed: ParsedSession) -> list[tuple[int, SessionEntry, ToolCall]]:
    """Every assistant tool call, flattened in file order."""
    out: list[tuple[int, SessionEntry, ToolCall]] = []
    for entry in parsed.entries:
        if entry.kind == "message" and entry.role == "assistant":
            out.extend((entry.index, entry, call) for call in entry.tool_calls)
    return out


def _tool_results(parsed: ParsedSession) -> list[tuple[int, SessionEntry]]:
    """Every toolResult entry, in file order."""
    return [(e.index, e) for e in parsed.entries if e.kind == "message" and e.role == "toolResult"]


def _decode_args(args_text: str) -> dict[str, object]:
    """The decoded call arguments (a non-dict / undecodable payload degrades to ``{}``)."""
    try:
        obj = json.loads(args_text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _pair_executions(
    parsed: ParsedSession, tool_name: str
) -> tuple[list[_Execution], list[_PendingCall]]:
    """Pair ``tool_name`` calls with their results; keep the unpaired calls visible.

    Pairs by ``ToolCall.call_id == SessionEntry.tool_call_id`` when both ids are present;
    id-less leftovers fall back to FIFO-by-name (id-less calls x id-less results, file
    order). A call with no result — an id miss or a FIFO leftover — is returned as a
    :class:`_PendingCall`, never dropped: the corpus includes live sessions, and an
    unfinished execution must be able to block an absence-shaped verdict.
    """
    calls = [(i, c) for i, _e, c in _tool_calls(parsed) if c.name == tool_name]
    results = [(i, e) for i, e in _tool_results(parsed) if e.tool_name == tool_name]
    result_by_id: dict[str, tuple[int, SessionEntry]] = {}
    for i, e in results:
        if e.tool_call_id is not None and e.tool_call_id not in result_by_id:
            result_by_id[e.tool_call_id] = (i, e)

    executions: list[_Execution] = []
    pending: list[_PendingCall] = []
    used: set[int] = set()
    idless_calls: list[tuple[int, ToolCall]] = []
    for call_index, call in calls:
        if call.call_id is None:
            idless_calls.append((call_index, call))
            continue
        hit = result_by_id.get(call.call_id)
        if hit is not None and hit[0] not in used:
            r_index, r_entry = hit
            executions.append(
                _Execution(
                    call_index=call_index,
                    result_index=r_index,
                    args=_decode_args(call.args_text),
                    args_text=call.args_text,
                    result_text=r_entry.text,
                    is_error=r_entry.is_error,
                )
            )
            used.add(r_index)
        else:
            pending.append(
                _PendingCall(
                    call_index=call_index,
                    args=_decode_args(call.args_text),
                    args_text=call.args_text,
                )
            )
    idless_results = [(i, e) for i, e in results if e.tool_call_id is None and i not in used]
    paired = min(len(idless_calls), len(idless_results))
    for (call_index, call), (r_index, r_entry) in zip(
        idless_calls[:paired], idless_results[:paired], strict=True
    ):
        executions.append(
            _Execution(
                call_index=call_index,
                result_index=r_index,
                args=_decode_args(call.args_text),
                args_text=call.args_text,
                result_text=r_entry.text,
                is_error=r_entry.is_error,
            )
        )
    pending.extend(
        _PendingCall(call_index=i, args=_decode_args(c.args_text), args_text=c.args_text)
        for i, c in idless_calls[paired:]
    )
    executions.sort(key=lambda ex: ex.call_index)
    pending.sort(key=lambda p: p.call_index)
    return executions, pending


def _paired_executions(parsed: ParsedSession, tool_name: str) -> list[_Execution]:
    """The paired executions only (the common read when pending calls are irrelevant)."""
    return _pair_executions(parsed, tool_name)[0]


# ------------------------------------------------------------- branch machinery


def parents_table(parsed: ParsedSession) -> tuple[int | None, ...]:
    """Per-entry parent resolution: ``parent_id`` -> the (earlier) entry with that
    ``entry_id``. A missing/unknown parent — or one pointing forward — bridges to the
    immediately preceding file-order entry; the first entry is the root. Computed ONCE
    per checker invocation and threaded through — the branch machinery's memo.

    Public seam: the evidence bundler (``perk_dev.audit.bounding``) reuses the same
    parent resolution for its branch-aware follow windows + packet lineage markers."""
    id_to_index: dict[str, int] = {}
    parents: list[int | None] = []
    for entry in parsed.entries:
        i = entry.index
        if i == 0:
            parent: int | None = None
        else:
            hit = id_to_index.get(entry.parent_id) if entry.parent_id is not None else None
            parent = hit if hit is not None else i - 1
        parents.append(parent)
        if entry.entry_id is not None:
            id_to_index[entry.entry_id] = i
    return tuple(parents)


def _ancestors(parents: tuple[int | None, ...], index: int) -> tuple[int, ...]:
    """The entry-index chain from ``index`` back to the root, inclusive, nearest first
    (over a precomputed ``parents_table`` — never rebuilt per lookup)."""
    chain = [index]
    while (p := parents[chain[-1]]) is not None:
        chain.append(p)
    return tuple(chain)


def _gate_engagement(parsed: ParsedSession) -> tuple[bool, ...]:
    """Per-entry gate state (the whole-session memo of the ancestor walk): the nearest
    ``perk:workflow-state`` custom entry carrying a non-empty string ``data["mode"]`` on
    the entry's own chain decides (``"read-only"`` -> True); no such ancestor -> False.
    One O(n) pass — every parent index precedes its child."""
    parents = parents_table(parsed)
    engaged: list[bool] = []
    for entry in parsed.entries:
        mode = _own_mode(entry)
        if mode is not None:
            engaged.append(mode == "read-only")
        else:
            parent = parents[entry.index]
            engaged.append(engaged[parent] if parent is not None else False)
    return tuple(engaged)


def _own_mode(entry: SessionEntry) -> str | None:
    if entry.kind == "custom" and entry.custom_type == WORKFLOW_STATE_TYPE:
        mode = (entry.data or {}).get("mode")
        if isinstance(mode, str) and mode:
            return mode
    return None


# ----------------------------------------------------------------- the checkers


_AUTHORING_TOOLS = ("plan_draft", "plan_review")


def _check_warm_claim_before_authoring(parsed: ParsedSession) -> CheckResult:
    """``objective-plan.warm-claim-before-authoring``.

    Precondition: >=1 ``plan_draft`` or ``plan_review`` toolCall. Decidable clause: a
    **claim** — a paired ``objective_node`` execution whose call args carry
    ``status == "planning"`` and whose result has ``is_error`` False (args-validated,
    deliberately NOT matched against the extension's pinned success render
    ``Updated objective #<id>: node <id> → <status>.``) — has its *result entry* on the
    ancestor chain of the first authoring toolCall entry. A *pending* planning-args
    ``objective_node`` call on that chain (result not yet landed — a live session) blocks
    the absence verdict -> ``unchecked``. Violated cites the first authoring entry (the
    precondition anchor).

    Undecidable residue: two sequential factory invocations in one *linear* branch cannot
    be told apart (invocation identity is not deterministically reconstructable) — an
    earlier same-branch claim satisfies; a claim on an abandoned fork does not.
    """
    authoring = [i for i, _e, c in _tool_calls(parsed) if c.name in _AUTHORING_TOOLS]
    if not authoring:
        return CheckResult(status="not-exercised", entries=(), detail="no authoring occurred")
    first = authoring[0]
    chain = set(_ancestors(parents_table(parsed), first))
    executions, pending = _pair_executions(parsed, "objective_node")
    claimed = any(
        ex.result_index in chain
        for ex in executions
        if not ex.is_error and ex.args.get("status") == "planning"
    )
    if claimed:
        return CheckResult(
            status="satisfied",
            entries=(),
            detail="a successful planning claim precedes the first authoring call on its branch",
        )
    if any(p.call_index in chain and p.args.get("status") == "planning" for p in pending):
        return CheckResult(
            status="unchecked",
            entries=(),
            detail=(
                "an objective_node planning execution is still unpaired — "
                "the transcript may be in flight"
            ),
        )
    return CheckResult(
        status="violated",
        entries=(first,),
        detail=(
            f"authoring began (entry {first}) with no successful objective_node planning "
            "claim on its ancestor chain"
        ),
    )


_DENIED_PREFIX = "plan DENIED"


def _check_draft_before_review(parsed: ParsedSession) -> CheckResult:
    """``plan.draft-before-review``.

    Precondition: >=1 ``plan_review`` toolCall. Decidable clauses, per review call: (a)
    a ``plan_draft`` call precedes it — a same-entry ``plan_draft`` counts only at an
    earlier tool-call *position* (one assistant message can batch multiple calls), else
    the nearest strict ancestor carrying a ``plan_draft`` call; and (b) no denied
    ``plan_review`` toolResult — text beginning ``plan DENIED``, the
    extension-test-pinned denial render — sits nearer on the chain than that draft (a
    denied review re-reviewed without a redraft). Violated cites each offending
    ``plan_review`` call entry.

    Undecidable residue: whether a redraft actually addressed the denial feedback is
    judgment-tier.
    """
    reviews: list[tuple[int, int]] = []  # (entry index, tool-call position)
    for entry in parsed.entries:
        if entry.kind == "message" and entry.role == "assistant":
            reviews.extend(
                (entry.index, position)
                for position, call in enumerate(entry.tool_calls)
                if call.name == "plan_review"
            )
    if not reviews:
        return CheckResult(
            status="not-exercised", entries=(), detail="no plan_review call occurred"
        )
    parents = parents_table(parsed)
    offenders: list[int] = []
    for review_index, position in reviews:
        review_entry = parsed.entries[review_index]
        drafted = any(c.name == "plan_draft" for c in review_entry.tool_calls[:position])
        if not drafted:
            for idx in _ancestors(parents, review_index)[1:]:  # strict ancestors
                entry = parsed.entries[idx]
                if (
                    entry.kind == "message"
                    and entry.role == "assistant"
                    and any(c.name == "plan_draft" for c in entry.tool_calls)
                ):
                    drafted = True
                    break
                if _is_denied_review_result(entry):
                    break  # the denial is nearer than any draft — re-review without a redraft
        if not drafted:
            offenders.append(review_index)
    if offenders:
        return CheckResult(
            status="violated",
            entries=tuple(dict.fromkeys(offenders)),
            detail="plan_review with no (or no post-denial) preceding plan_draft on its branch",
        )
    return CheckResult(
        status="satisfied",
        entries=(),
        detail="every plan_review call follows a plan_draft on its branch",
    )


def _is_denied_review_result(entry: SessionEntry) -> bool:
    return (
        entry.kind == "message"
        and entry.role == "toolResult"
        and entry.tool_name == "plan_review"
        and entry.text.startswith(_DENIED_PREFIX)
    )


_READER_COMMANDS = frozenset({"cat", "head", "tail", "less", "more", "bat"})


def _check_nudge_skill_read(parsed: ParsedSession) -> CheckResult:
    """``bindings.nudge-skill-read``.

    Precondition: >=1 delivered skill pointer (``NUDGE_PATTERN`` / ``TRANSCLUDE_PATTERN``
    over the ``extract_signals`` scan scope: user-role message text + custom entries'
    content). Uptake evidence per delivered skill is **presence-anywhere** (file-wide, per
    the amended catalog evidence), any of:

    - a successful paired ``read`` execution whose ``path`` argument ends with the exact
      suffix ``.agents/skills/<skill>/SKILL.md``;
    - a successful paired ``bash`` execution with a reader-led segment
      (``cat``/``head``/``tail``/``less``/``more``/``bat``, plus ``sed -n``) whose some
      whitespace-delimited token (shell quotes stripped) ends with that exact suffix;
    - any user-role entry text containing ``<skill name="<skill>"`` — pi's ``/skill:``
      expansion (prompt-hidden skills stay human-invocable, so this route must count);
    - the skill was transclude-delivered (the body arrived inlined — no read exists to
      demand).

    A *pending* ``read``/``bash`` call whose args would be uptake for an otherwise-unread
    skill (a live session mid-read) blocks the absence verdict -> ``unchecked``. Violated
    cites the unread skills' delivery entries. Undecidable residue: whether the read body
    actually informed the flow is judgment-tier.
    """
    deliveries: dict[str, list[int]] = {}
    transcluded: set[str] = set()
    for index, text in _delivery_texts(parsed):
        for skill in NUDGE_PATTERN.findall(text):
            deliveries.setdefault(skill, []).append(index)
        for skill in TRANSCLUDE_PATTERN.findall(text):
            deliveries.setdefault(skill, []).append(index)
            transcluded.add(skill)
    if not deliveries:
        return CheckResult(status="not-exercised", entries=(), detail="no nudge delivered")

    read_execs, pending_reads = _pair_executions(parsed, "read")
    bash_execs, pending_bashes = _pair_executions(parsed, "bash")
    reads = [ex for ex in read_execs if not ex.is_error]
    bashes = [ex for ex in bash_execs if not ex.is_error]
    user_texts = [
        e.text for e in parsed.entries if e.kind == "message" and e.role == "user" and e.text
    ]
    unread: dict[str, list[int]] = {}
    in_flight: list[str] = []
    for skill, indices in sorted(deliveries.items()):
        if skill in transcluded:
            continue
        suffix = f".agents/skills/{skill}/SKILL.md"
        read_hit = any(
            isinstance(path := ex.args.get("path"), str) and path.endswith(suffix) for ex in reads
        )
        bash_hit = any(_bash_reads_suffix(ex.args.get("command"), suffix) for ex in bashes)
        skill_hit = any(f'<skill name="{skill}"' in text for text in user_texts)
        if read_hit or bash_hit or skill_hit:
            continue
        pending_hit = any(
            isinstance(path := p.args.get("path"), str) and path.endswith(suffix)
            for p in pending_reads
        ) or any(_bash_reads_suffix(p.args.get("command"), suffix) for p in pending_bashes)
        if pending_hit:
            in_flight.append(skill)
        else:
            unread[skill] = indices
    if unread:
        cited = tuple(sorted({i for idxs in unread.values() for i in idxs}))
        return CheckResult(
            status="violated",
            entries=cited,
            detail="nudged skill(s) never read: " + ", ".join(sorted(unread)),
        )
    if in_flight:
        return CheckResult(
            status="unchecked",
            entries=(),
            detail=(
                "uptake execution(s) still unpaired for: "
                + ", ".join(in_flight)
                + " — the transcript may be in flight"
            ),
        )
    return CheckResult(
        status="satisfied",
        entries=(),
        detail="every delivered skill shows an uptake route",
    )


def _delivery_texts(parsed: ParsedSession) -> list[tuple[int, str]]:
    """The ``extract_signals`` scan scope: user-role message text + custom content."""
    out: list[tuple[int, str]] = []
    for entry in parsed.entries:
        if entry.kind == "message" and entry.role == "user" and entry.text:
            out.append((entry.index, entry.text))
        if entry.kind in ("custom", "custom_message") and entry.content:
            out.append((entry.index, entry.content))
    return out


def _bash_reads_suffix(command: object, suffix: str) -> bool:
    """Whether a bash command demonstrably reads a path ending with ``suffix``: some
    segment led by a pinned reader command carries a token (shell quotes stripped) ending
    with the exact suffix. An ``ls``/``stat``/``echo`` of the path is NOT uptake."""
    if not isinstance(command, str):
        return False
    for segment in split_top_level_segments(command):
        words = segment.split()
        if not words:
            continue
        reader_led = words[0] in _READER_COMMANDS or (
            words[0] == "sed" and len(words) > 1 and words[1] == "-n"
        )
        if reader_led and any(w.strip("'\"").endswith(suffix) for w in words[1:]):
            return True
    return False


_GH_API_REVIEW_PATH = re.compile(r"/(pulls|issues)/[^\s]*/(reviews|comments)")
_REVIEW_JSON_FLAG = re.compile(r"--json\s+\S*(reviews|comments)")


def _is_review_fetch(command: str) -> bool:
    """Whether a bash command actually EXECUTES a review-feedback fetch: per top-level
    segment, the leading command must be ``gh api`` (with a review/comment path segment)
    or ``gh pr view`` (with a reviews/comments ``--json`` selection). A mention inside
    another command's arguments (``echo``/``grep`` of an example) is not a fetch."""
    for segment in split_top_level_segments(command):
        words = segment.split()
        if len(words) < 2 or words[0] != "gh":
            continue
        if words[1] == "api" and _GH_API_REVIEW_PATH.search(segment):
            return True
        if (
            words[1] == "pr"
            and len(words) > 2
            and words[2] == "view"
            and _REVIEW_JSON_FLAG.search(segment)
        ):
            return True
    return False


# The classifier launch signature, matched in AGENT POSITION only: the direct-execution
# form (args {"agent": "perk.review-classifier", ...}) or a workflowScript whose
# runs.run options carry agent: "perk.review-classifier" — a task string merely
# *mentioning* the name never matches.
_CLASSIFIER_AGENT = re.compile(r"agent\s*:\s*[\"']perk\.review-classifier[\"']")


def _launches_classifier(args: dict[str, object]) -> bool:
    if args.get("agent") == "perk.review-classifier":
        return True
    script = args.get("workflowScript")
    return isinstance(script, str) and _CLASSIFIER_AGENT.search(script) is not None


def _shows_classifier_evidence(result_text: str) -> bool:
    """Best-effort, era-aware structural validation of a classifier run's returned value.

    A workflowScript result renders a ``Return:`` JSON payload; when one is decodable,
    require ``ok`` truthy-True plus one of the two sanctioned success shapes:

    - **Modern** (engine-validated structured output; ``report: … ?? null``): a non-null
      object ``report``. An explicit null/non-dict report means the child produced no
      schema-valid report — not classifier evidence.
    - **Legacy** (the pre-structured-output workflowScript era — ``{key, ok, error,
      output}``): NO ``report`` field at all, with the classification riding a string
      ``output``. Demanding ``report`` there false-violated live transition-window
      sessions (a dogfood false-verdict find); accepting a bare missing field without the
      legacy ``output`` shape would over-accept, so both halves are required.

    A result with no decodable payload (e.g. the historical direct-execution rendering)
    falls back to the ``is_error`` gate alone.
    """
    payload = _return_payload(result_text)
    if payload is None:
        return True
    if payload.get("ok") is not True:
        return False
    if "report" in payload:
        return isinstance(payload.get("report"), dict)
    return isinstance(payload.get("output"), str)


def _return_payload(text: str) -> dict[str, object] | None:
    """The first JSON object after a ``Return:`` marker, else ``None`` (never raises)."""
    marker = text.find("Return:")
    if marker == -1:
        return None
    brace = text.find("{", marker)
    if brace == -1:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text, brace)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _check_classifier_child_first(parsed: ParsedSession) -> CheckResult:
    """``address.classifier-child-first``.

    Precondition: >=1 assistant toolCall (the session did work). Two decidable clauses,
    both file-wide:

    - **Raw-fetch veto**: any successful paired ``bash`` execution whose leading command
      (per top-level segment) actually executes a review-feedback fetch — ``gh api`` with
      a ``/(pulls|issues)/…/(reviews|comments)`` path segment, or ``gh pr view`` with a
      reviews/comments ``--json`` selection — violates, even when a classifier also ran
      (the raw payload entered the parent). Cites those executions' result entries.
    - **Classifier evidence**: a successful paired ``subagent`` execution whose call
      names ``perk.review-classifier`` in agent position (direct args or inside the
      workflowScript's ``runs.run`` options — a task-string mention never counts) and
      whose rendered ``Return:`` payload, when decodable, shows ``ok: true`` with an
      era-valid success shape — a non-null ``report`` object (modern) or, with no
      ``report`` field, a string ``output`` (the pre-structured-output legacy shape; see
      ``_shows_classifier_evidence``). Absent -> violated, citing the first assistant toolCall
      entry (the precondition anchor); a *pending* classifier launch (result not yet
      landed — a live session) blocks the absence verdict -> ``unchecked``.

    Undecidable residue: "the parent applies fixes only *after* the report returns"
    (fix-timing) is judgment-tier, and a workflow that fabricates a plausible
    ``ok``/``report`` return value is not deterministically detectable.
    """
    calls = _tool_calls(parsed)
    if not calls:
        return CheckResult(
            status="not-exercised", entries=(), detail="no assistant tool calls occurred"
        )
    fetches = [
        ex
        for ex in _paired_executions(parsed, "bash")
        if not ex.is_error
        and isinstance(command := ex.args.get("command"), str)
        and _is_review_fetch(command)
    ]
    executions, pending = _pair_executions(parsed, "subagent")
    classified = any(
        not ex.is_error and _shows_classifier_evidence(ex.result_text)
        for ex in executions
        if _launches_classifier(ex.args)
    )
    pending_classifier = any(_launches_classifier(p.args) for p in pending)
    offenders: list[int] = []
    details: list[str] = []
    if fetches:
        offenders.extend(ex.result_index for ex in fetches)
        details.append("raw review-feedback fetch entered the parent session")
    if not classified and not pending_classifier:
        offenders.append(calls[0][0])
        details.append("no successful perk.review-classifier subagent run")
    if offenders:
        return CheckResult(
            status="violated",
            entries=tuple(dict.fromkeys(offenders)),
            detail="; ".join(details),
        )
    if not classified:
        return CheckResult(
            status="unchecked",
            entries=(),
            detail=(
                "a perk.review-classifier execution is still unpaired — "
                "the transcript may be in flight"
            ),
        )
    return CheckResult(
        status="satisfied",
        entries=(),
        detail="classifier child ran; no raw review fetch",
    )


def _check_no_worktree_mutation(parsed: ParsedSession) -> CheckResult:
    """``read-only.no-worktree-mutation``.

    Precondition: >=1 gate-engaged entry (else "gate never engaged"). Decidable clauses:
    any ``edit``/``write`` toolResult with ``is_error`` False at a gate-engaged entry, and
    any successful paired ``bash`` execution whose *result entry* is gate-engaged and
    whose command fails ``is_read_only_bash_command``. Cites every offending result
    entry. Both clauses are presence-shaped (a successful mutation happened), so pending
    calls never flip a verdict here — an unpaired call has no successful result to judge.

    Canary scoping (from the catalog): the gate's accepted, documented leniencies —
    arg-blind curl/agent-browser, unscoped subagent children — are out of scope by
    construction; they pass the policy copy too. A hit here indicts the gate or the
    audit's session classification, not the model.
    """
    engaged = _gate_engagement(parsed)
    if not any(engaged):
        return CheckResult(status="not-exercised", entries=(), detail="gate never engaged")
    offenders: list[int] = []
    for index, entry in _tool_results(parsed):
        if entry.tool_name in ("edit", "write") and not entry.is_error and engaged[index]:
            offenders.append(index)
    for ex in _paired_executions(parsed, "bash"):
        if ex.is_error or not engaged[ex.result_index]:
            continue
        command = ex.args.get("command")
        if isinstance(command, str) and not is_read_only_bash_command(command):
            offenders.append(ex.result_index)
    if offenders:
        return CheckResult(
            status="violated",
            entries=tuple(sorted(set(offenders))),
            detail="successful edit/write or non-allowlisted bash under the engaged gate",
        )
    return CheckResult(
        status="satisfied",
        entries=(),
        detail="no successful mutation while the gate was engaged",
    )


# The registry: exactly the committed catalog's tier-deterministic ids (self-checked by
# tests against load_catalog()).
CHECKERS: dict[str, Checker] = {
    "objective-plan.warm-claim-before-authoring": _check_warm_claim_before_authoring,
    "plan.draft-before-review": _check_draft_before_review,
    "bindings.nudge-skill-read": _check_nudge_skill_read,
    "address.classifier-child-first": _check_classifier_child_first,
    "read-only.no-worktree-mutation": _check_no_worktree_mutation,
}
