"""The v2 door envelope's strict wire models against the committed TypeScript goldens
(contracts.md §8.77).

The goldens under ``extension/pi/v2/door/golden/`` are written and byte-pinned by
``extension/pi/v2/door/envelope.test.ts``; here every one validates, round-trips byte for byte, and
every mutation of a shape or pairing rule is refused.
"""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from perk.v2.envelope import (
    EnvelopeError,
    IncompatibleEnvelope,
    ObservationFailedEnvelope,
    OkEnvelope,
    OwnerBusyEnvelope,
    PendingDecisionEnvelope,
    RefusedEnvelope,
    UncertainEnvelope,
    ViewSnapshot,
    parse_envelope,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "extension" / "pi" / "v2" / "door" / "golden"

EXPECTED = {
    "start-pending-decision": PendingDecisionEnvelope,
    "status-ok-running": OkEnvelope,
    "status-ok-assignment-incomplete": OkEnvelope,
    "status-ok-repair-required": OkEnvelope,
    "reply-ok-completed": OkEnvelope,
    "cancel-ok-cancelled": OkEnvelope,
    "status-owner-busy": OwnerBusyEnvelope,
    "run-incompatible-missing": IncompatibleEnvelope,
    "status-incompatible-mismatch": IncompatibleEnvelope,
    "start-observation-failed": ObservationFailedEnvelope,
    "reply-refused-stale": RefusedEnvelope,
    "run-uncertain": UncertainEnvelope,
}


def _text(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8")


def _raw(name: str) -> dict[str, Any]:
    return json.loads(_text(name))


def _parse(raw: dict[str, Any]):
    return parse_envelope(json.dumps(raw), verb=raw["verb"], execution_id=raw["executionId"])


def _refused(raw: dict[str, Any], pattern: str | None = None) -> None:
    with pytest.raises(EnvelopeError, match=pattern):
        _parse(raw)


def test_the_golden_directory_holds_exactly_the_twelve_goldens():
    assert sorted(p.name for p in GOLDEN_DIR.iterdir()) == sorted(f"{n}.json" for n in EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_golden_validates_and_round_trips_byte_for_byte(name):
    raw = _raw(name)
    envelope = _parse(raw)
    assert isinstance(envelope, EXPECTED[name])
    assert envelope.verb == name.split("-")[0]
    assert envelope.execution_id == raw["executionId"]
    dumped = envelope.model_dump(mode="json", by_alias=True)
    assert json.dumps(dumped, indent=2) + "\n" == _text(name)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_a_wrong_discriminator_an_extra_key_or_a_missing_null_is_refused(name):
    raw = _raw(name)
    _refused({**raw, "outcome": "done"}, "outcome")
    _refused({**raw, "surplus": 1}, "surplus")
    for key in ("status", "receipt", "refusal", "mismatch", "error"):
        missing = {k: v for k, v in raw.items() if k != key}
        _refused(missing, key)


def test_an_extra_nested_key_is_refused():
    raw = _raw("start-pending-decision")
    raw["status"]["diagnostics"]["surplus"] = 0
    _refused(raw, "surplus")
    raw = _raw("start-pending-decision")
    raw["status"]["assignments"][0]["attempts"][0]["ending"]["note"] = "x"
    _refused(raw, "note")


def test_strict_scalars_are_refused():
    raw = _raw("status-owner-busy")
    _refused({**raw, "epoch": "4"}, "epoch")
    _refused({**raw, "epoch": 0}, "epoch")
    _refused({**raw, "envelope": 2}, "envelope")
    aged = _raw("start-pending-decision")
    aged["status"]["observation"]["ageMs"] = -1
    _refused(aged, "ageMs")


Mutation = Callable[[dict[str, Any]], None]


def _set(path: tuple[str | int, ...], value: object) -> Mutation:
    def mutate(raw: dict[str, Any]) -> None:
        target: Any = raw
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


_REPLY_RECEIPT = _raw("reply-ok-completed")["receipt"]
_CANCEL_RECEIPT = _raw("cancel-ok-cancelled")["receipt"]

PAIRING_VIOLATIONS: list[tuple[str, str, Mutation]] = [
    ("ok + status verb + receipt", "cancel-ok-cancelled", _set(("verb",), "status")),
    ("ok + reply without its receipt", "reply-ok-completed", _set(("receipt",), None)),
    ("ok + quiescent run still running", "status-ok-running", _set(("verb",), "run")),
    (
        "ok + a run waiting on a decision",
        "start-pending-decision",
        _set(("outcome",), "ok"),
    ),
    ("pending_decision + cancel", "start-pending-decision", _set(("verb",), "cancel")),
    ("pending_decision + status", "start-pending-decision", _set(("verb",), "status")),
    (
        "pending_decision over a completed snapshot",
        "reply-ok-completed",
        _set(("outcome",), "pending_decision"),
    ),
    (
        "waiting without a reason",
        "status-ok-assignment-incomplete",
        _set(("status", "waitReason"), None),
    ),
    (
        "a reason while not waiting",
        "reply-ok-completed",
        _set(("status", "waitReason"), "assignment_incomplete"),
    ),
    (
        "cancelled without its cancellation",
        "cancel-ok-cancelled",
        _set(("status", "cancellation"), None),
    ),
    (
        "pending_decision without its decision",
        "start-pending-decision",
        _set(("status", "decision"), None),
    ),
    (
        "a reply receipt without a continuation",
        "reply-ok-completed",
        _set(("receipt", "continuation"), None),
    ),
    (
        "the reply golden carrying a cancellation receipt",
        "reply-ok-completed",
        _set(("receipt",), {**_REPLY_RECEIPT, "kind": "cancellation", "continuation": None}),
    ),
    (
        "the cancel golden carrying a reply receipt",
        "cancel-ok-cancelled",
        _set(
            ("receipt",),
            {**_CANCEL_RECEIPT, "kind": "reply", "continuation": _REPLY_RECEIPT["continuation"]},
        ),
    ),
    ("owner_busy with a snapshot", "status-owner-busy", _set(("status",), {"state": "uncertain"})),
    (
        "incompatible with the uncertain marker",
        "run-incompatible-missing",
        _set(("status",), {"state": "uncertain"}),
    ),
    (
        "incompatible with a view snapshot",
        "status-incompatible-mismatch",
        _set(("status",), _raw("status-ok-running")["status"]),
    ),
    ("incompatible without its mismatch", "run-incompatible-missing", _set(("mismatch",), None)),
    (
        "uncertain with the incompatible marker",
        "run-uncertain",
        _set(("status",), {"state": "incompatible"}),
    ),
    ("observation_failed on status", "start-observation-failed", _set(("verb",), "status")),
    ("observation_failed on cancel", "start-observation-failed", _set(("verb",), "cancel")),
    ("refused on status", "reply-refused-stale", _set(("verb",), "status")),
    ("an unknown refusal reason", "reply-refused-stale", _set(("refusal", "reason"), "nope")),
    ("an unknown mismatch field", "status-incompatible-mismatch", _set(("mismatch", "field"), "x")),
]


@pytest.mark.parametrize(
    ("name", "mutate"),
    [(name, mutate) for _, name, mutate in PAIRING_VIOLATIONS],
    ids=[label for label, _, _ in PAIRING_VIOLATIONS],
)
def test_pairing_violations_are_refused(name, mutate):
    raw = copy.deepcopy(_raw(name))
    mutate(raw)
    _refused(raw)


def test_swapped_receipt_kinds_fail_on_the_verb_pairing_itself():
    """Each swapped receipt is a well-formed receipt view — only its kind contradicts the verb."""
    reply = _raw("reply-ok-completed")
    reply["receipt"] = {**_REPLY_RECEIPT, "kind": "cancellation", "continuation": None}
    _refused(reply, "a reply envelope carries a reply receipt, not cancellation")
    cancel = _raw("cancel-ok-cancelled")
    cancel["receipt"] = {
        **_CANCEL_RECEIPT,
        "kind": "reply",
        "continuation": _REPLY_RECEIPT["continuation"],
    }
    _refused(cancel, "a cancel envelope carries a cancellation receipt, not reply")


def test_the_requested_verb_and_execution_are_cross_checked():
    text = _text("status-owner-busy")
    execution_id = json.loads(text)["executionId"]
    assert parse_envelope(text, verb="status", execution_id=execution_id).epoch == 4
    with pytest.raises(EnvelopeError, match="not the requested 'run'"):
        parse_envelope(text, verb="run", execution_id=execution_id)
    with pytest.raises(EnvelopeError, match="execution"):
        parse_envelope(text, verb="status", execution_id="01HZY3V8Q2M5N7P9R1T3V5X7Z8")


@pytest.mark.parametrize(
    ("stdout", "pattern"),
    [
        ("", "not JSON"),
        ("perk v2 host fault", "not JSON"),
        ("[1, 2]", "not a JSON object"),
        ("null", "not a JSON object"),
    ],
)
def test_non_envelope_stdout_is_refused(stdout, pattern):
    with pytest.raises(EnvelopeError, match=pattern):
        parse_envelope(stdout, verb="status", execution_id="01HZY3V8Q2M5N7P9R1T3V5X7Z9")


def test_two_envelope_lines_are_refused():
    line = json.dumps(_raw("status-owner-busy"))
    with pytest.raises(EnvelopeError, match="not JSON"):
        parse_envelope(
            f"{line}\n{line}\n", verb="status", execution_id="01HZY3V8Q2M5N7P9R1T3V5X7Z9"
        )


def test_json_lists_become_tuples():
    envelope = _parse(_raw("start-pending-decision"))
    assert isinstance(envelope, PendingDecisionEnvelope)
    status = envelope.status
    assert isinstance(status, ViewSnapshot)
    assert isinstance(status.assignments, tuple)
    assert isinstance(status.assignments[0].attempts, tuple)
    assert status.decision is not None
    assert status.decision.allowed_actions == ("approve", "reject")
