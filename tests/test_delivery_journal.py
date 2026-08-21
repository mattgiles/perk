"""Tests for the pure operation-journal layer (``perk/delivery/journal.py``).

Covers: render→parse round trips in BOTH marker encodings (the canonical HTML form and the
Linear-transcoded inline-code form, proving the logical key + payload are identical across
backends), the fail-closed strict rejections (edited / tampered / malformed / oversized), the
fold rules (dedupe, conflicts, orphans = out-of-band deletion, accepted gating, lineage checks,
unresolved detection), the size cap against a realistic 100-layer land record, the ready-stamp
grammar + routing dispatcher + fold scoping (contracts.md §8.43), and the engagement-exclusion
pins (journal comments classify as perk machinery and never reach the rendered engagement
blocks).
"""

import pytest

from perk.backends import engagement
from perk.backends.linear import to_linear_markdown
from perk.delivery import journal

_ULID = "01JA0000000000000000000000"
_ULID_2 = "01JA0000000000000000000001"
_LINEAGE = "01JB0000000000000000000000"


def _prepared(
    *,
    operation_id: str = _ULID,
    kind: journal.OperationKind = journal.OperationKind.PUBLISH,
    lineage: str = _LINEAGE,
    created: str = "2026-01-01T00:00:00Z",
) -> journal.PreparedRecord:
    return journal.PreparedRecord(
        operation_id=operation_id,
        operation_kind=kind,
        delivery_lineage=lineage,
        objective_id="252",
        run_id="01JC0000000000000000000000",
        created=created,
        affected_plans=("101", "102"),
        before={"refs": {"plan-101": "a" * 40}},
        after={"refs": {"plan-101": "b" * 40}},
    )


def _outcome(
    *,
    operation_id: str = _ULID,
    role: journal.EventRole = journal.EventRole.COMPLETED,
    created: str = "2026-01-02T00:00:00Z",
) -> journal.OutcomeRecord:
    return journal.OutcomeRecord(
        operation_id=operation_id,
        role=role,
        created=created,
        observed={"verified": True},
    )


def _event(
    record: journal.PreparedRecord | journal.OutcomeRecord,
    *,
    comment_id: str = "c1",
    created_at: str = "t1",
    carrier: str = "252",
    transcode: bool = False,
) -> journal.JournalEvent:
    """Parse a rendered record back into a stamped event (through the real grammar)."""
    import dataclasses

    body = journal.render_event(record)
    if transcode:
        body = to_linear_markdown(body)
    parsed = journal.parse_journal_comment(
        body, comment_id=comment_id, created_at=created_at, edited_at=None
    )
    assert parsed is not None
    return dataclasses.replace(parsed, carrier_objective_id=carrier)


_HEAD = "a" * 40
_HEAD_2 = "b" * 40


def _stamp(
    *,
    objective_id: str = "252",
    lineage: str = _LINEAGE,
    plan_id: str = "101",
    node_id: str = "1.1",
    head_sha: str = _HEAD,
) -> journal.ReadyStampRecord:
    return journal.ReadyStampRecord(
        objective_id=objective_id,
        delivery_lineage=lineage,
        plan_id=plan_id,
        node_id=node_id,
        head_sha=head_sha,
    )


def _stamp_event(
    record: journal.ReadyStampRecord,
    *,
    comment_id: str = "s1",
    created_at: str = "t1",
    transcode: bool = False,
) -> journal.ReadyStampEvent:
    """Parse a rendered stamp back into an event (through the real grammar)."""
    body = journal.render_stamp_event(record)
    if transcode:
        body = to_linear_markdown(body)
    parsed = journal.parse_stamp_comment(
        body, comment_id=comment_id, created_at=created_at, edited_at=None
    )
    assert parsed is not None
    return parsed


# ----------------------------------------------------------------- render → parse round trips


class TestRoundTrip:
    @pytest.mark.parametrize("transcode", [False, True], ids=["html", "inline-code"])
    def test_prepared_round_trip(self, transcode: bool) -> None:
        record = _prepared()
        body = journal.render_event(record)
        if transcode:
            body = to_linear_markdown(body)
            assert f"`perk:stack-operation-event:{_ULID}:prepared`" in body
        else:
            assert f"<!-- perk:stack-operation-event:{_ULID}:prepared -->" in body
        parsed = journal.parse_journal_comment(
            body, comment_id="c1", created_at="t1", edited_at=None
        )
        assert parsed is not None
        assert parsed.record == record
        assert parsed.role is journal.EventRole.PREPARED
        assert parsed.operation_id == _ULID

    @pytest.mark.parametrize(
        "role",
        [journal.EventRole.ACCEPTED, journal.EventRole.COMPLETED, journal.EventRole.ABANDONED],
    )
    @pytest.mark.parametrize("transcode", [False, True], ids=["html", "inline-code"])
    def test_outcome_round_trip(self, role: journal.EventRole, transcode: bool) -> None:
        record = _outcome(role=role)
        body = journal.render_event(record)
        if transcode:
            body = to_linear_markdown(body)
        parsed = journal.parse_journal_comment(
            body, comment_id="c1", created_at="t1", edited_at=None
        )
        assert parsed is not None
        assert parsed.record == record
        assert parsed.role is role

    def test_encodings_share_logical_key_and_payload(self) -> None:
        """The Linear-transcoded event is byte-identical to the GitHub event in logical key +
        canonical payload (the cross-backend identity requirement)."""
        record = _prepared()
        html = _event(record)
        inline = _event(record, comment_id="c2", transcode=True)
        assert (html.operation_id, html.role) == (inline.operation_id, inline.role)
        assert html.canonical_payload == inline.canonical_payload

    def test_unrelated_comment_is_ignored(self) -> None:
        assert (
            journal.parse_journal_comment(
                "just a human comment", comment_id="c1", created_at="t1", edited_at=None
            )
            is None
        )

    def test_unrelated_edited_comment_is_ignored(self) -> None:
        """Humans edit their comments freely — the edit check applies to marked bodies only."""
        assert (
            journal.parse_journal_comment(
                "tweaked human comment", comment_id="c1", created_at="t1", edited_at="t2"
            )
            is None
        )

    def test_other_perk_marker_is_ignored(self) -> None:
        body = (
            "<!-- perk:metadata-block:plan-body -->\nstuff\n<!-- /perk:metadata-block:plan-body -->"
        )
        assert (
            journal.parse_journal_comment(body, comment_id="c1", created_at="t1", edited_at=None)
            is None
        )

    def test_mint_operation_id_is_ulid(self) -> None:
        minted = journal.mint_operation_id()
        assert len(minted) == 26
        journal.PreparedRecord(
            operation_id=minted,
            operation_kind=journal.OperationKind.LAND,
            delivery_lineage=_LINEAGE,
            objective_id="1",
            run_id="r",
            created="t",
            affected_plans=(),
            before={},
            after={},
        )


# ----------------------------------------------------------------- strict rejections


class TestStrictRejections:
    def _parse(self, body: str, *, edited_at: str | None = None) -> journal.JournalEvent | None:
        return journal.parse_journal_comment(
            body, comment_id="c1", created_at="t1", edited_at=edited_at
        )

    def test_edited_event_is_corruption(self) -> None:
        body = journal.render_event(_prepared())
        with pytest.raises(journal.JournalCorruptionError, match="edited"):
            self._parse(body, edited_at="2026-02-02T00:00:00Z")

    def test_marker_operation_id_mismatch(self) -> None:
        body = journal.render_event(_prepared()).replace(
            f"stack-operation-event:{_ULID}:", f"stack-operation-event:{_ULID_2}:"
        )
        with pytest.raises(journal.JournalCorruptionError, match="disagrees"):
            self._parse(body)

    def test_marker_role_mismatch(self) -> None:
        body = journal.render_event(_outcome(role=journal.EventRole.COMPLETED)).replace(
            ":completed -->", ":abandoned -->"
        )
        with pytest.raises(journal.JournalCorruptionError, match="disagrees"):
            self._parse(body)

    def test_extra_payload_field(self) -> None:
        body = journal.render_event(_prepared()).replace(
            "event: prepared", "event: prepared\nsneaky: extra"
        )
        with pytest.raises(journal.JournalCorruptionError, match="sneaky"):
            self._parse(body)

    def test_wrong_schema_version(self) -> None:
        body = journal.render_event(_prepared()).replace(
            "schema_version: '1'", "schema_version: '2'"
        )
        with pytest.raises(journal.JournalCorruptionError, match="schema_version"):
            self._parse(body)

    def test_absent_schema_version(self) -> None:
        body = journal.render_event(_prepared()).replace("schema_version: '1'\n", "")
        with pytest.raises(journal.JournalCorruptionError, match="schema_version"):
            self._parse(body)

    def test_unknown_role_in_marker(self) -> None:
        body = journal.render_event(_outcome()).replace(":completed -->", ":exploded -->")
        with pytest.raises(journal.JournalCorruptionError, match="unknown event role"):
            self._parse(body)

    def test_unknown_kind_rejects(self) -> None:
        body = journal.render_event(_prepared()).replace(
            "operation_kind: publish", "operation_kind: teleport"
        )
        with pytest.raises(journal.JournalCorruptionError, match="operation_kind"):
            self._parse(body)

    def test_non_ulid_operation_id_rejects(self) -> None:
        body = journal.render_event(_prepared()).replace(_ULID, "not-a-ulid")
        with pytest.raises(journal.JournalCorruptionError, match="ULID"):
            self._parse(body)

    def test_non_mapping_yaml(self) -> None:
        marker = journal.render_marker(_ULID, journal.EventRole.PREPARED)
        body = f"{marker}\n\n```yaml\n- just\n- a list\n```"
        with pytest.raises(journal.JournalCorruptionError, match="not a YAML mapping"):
            self._parse(body)

    def test_unparseable_yaml(self) -> None:
        marker = journal.render_marker(_ULID, journal.EventRole.PREPARED)
        body = f"{marker}\n\n```yaml\n{{unbalanced\n```"
        with pytest.raises(journal.JournalCorruptionError, match="not parseable"):
            self._parse(body)

    def test_two_markers_in_one_body(self) -> None:
        one = journal.render_event(_prepared())
        two = journal.render_event(_outcome())
        with pytest.raises(journal.JournalCorruptionError, match="more than one event marker"):
            self._parse(one + "\n\n" + two)

    def test_text_outside_marker_and_fence(self) -> None:
        body = journal.render_event(_prepared()) + "\n\ntrailing prose"
        with pytest.raises(journal.JournalCorruptionError, match="outside the marker"):
            self._parse(body)

    def test_unterminated_fence(self) -> None:
        body = journal.render_event(_prepared()).rsplit("```", 1)[0]
        with pytest.raises(journal.JournalCorruptionError, match="unterminated"):
            self._parse(body)

    def test_missing_fence(self) -> None:
        marker = journal.render_marker(_ULID, journal.EventRole.PREPARED)
        with pytest.raises(journal.JournalCorruptionError, match="marker \\+ one yaml fence"):
            self._parse(marker + "\n\nevent: prepared")

    def test_marker_quoted_in_human_prose_is_fail_closed(self) -> None:
        """Marker detection is substring-based like every perk marker: a human comment quoting
        the marker text inside a code block still parses strictly — and is corruption when the
        body is not exactly marker + fence (the fail-closed pin)."""
        body = f"look at this:\n\n```\n<!-- perk:stack-operation-event:{_ULID}:prepared -->\n```\n"
        with pytest.raises(journal.JournalCorruptionError):
            self._parse(body)

    def test_marker_not_on_leading_line(self) -> None:
        body = "prose first\n" + journal.render_event(_prepared())
        with pytest.raises(journal.JournalCorruptionError, match="well-formed"):
            self._parse(body)

    def test_outcome_record_rejects_prepared_role(self) -> None:
        with pytest.raises(ValueError, match="outcome record"):
            journal.OutcomeRecord(
                operation_id=_ULID,
                role=journal.EventRole.PREPARED,
                created="t",
                observed={},
            )

    def test_prepared_record_rejects_non_ulid(self) -> None:
        with pytest.raises(ValueError, match="ULID"):
            _prepared(operation_id="junk")

    def test_negative_model_validate_prepared(self) -> None:
        # Negative tests drive through model_validate (the strict-model testing gotcha).
        with pytest.raises(Exception, match="event"):
            journal.PreparedRecordModel.model_validate({"schema_version": "1"})


# ----------------------------------------------------------------- fold rules


class TestFold:
    def test_byte_identical_duplicate_dedupes(self) -> None:
        record = _prepared()
        a = _event(record, comment_id="c1", created_at="t1")
        b = _event(record, comment_id="c2", created_at="t2")
        fold = journal.fold_events([a, b], expected_lineage=_LINEAGE)
        assert fold.events == (a,)  # first occurrence wins
        assert list(fold.operations) == [_ULID]

    def test_conflicting_duplicate_is_corruption(self) -> None:
        a = _event(_prepared(), comment_id="c1")
        b = _event(_prepared(created="2027-01-01T00:00:00Z"), comment_id="c2", created_at="t2")
        with pytest.raises(journal.JournalCorruptionError, match="conflicting duplicate"):
            journal.fold_events([a, b], expected_lineage=_LINEAGE)

    def test_identical_prepared_on_two_carriers_is_corruption(self) -> None:
        record = _prepared()
        a = _event(record, comment_id="c1", carrier="252")
        b = _event(record, comment_id="c2", created_at="t2", carrier="300")
        with pytest.raises(journal.JournalCorruptionError, match="two carriers"):
            journal.fold_events([a, b], expected_lineage=_LINEAGE)

    def test_orphan_outcome_names_out_of_band_deletion(self) -> None:
        orphan = _event(_outcome(), comment_id="c1")
        with pytest.raises(journal.JournalCorruptionError, match="out-of-band deletion"):
            journal.fold_events([orphan], expected_lineage=_LINEAGE)

    def test_completed_plus_abandoned_is_corruption(self) -> None:
        events = [
            _event(_prepared(), comment_id="c1", created_at="t1"),
            _event(_outcome(role=journal.EventRole.COMPLETED), comment_id="c2", created_at="t2"),
            _event(_outcome(role=journal.EventRole.ABANDONED), comment_id="c3", created_at="t3"),
        ]
        with pytest.raises(journal.JournalCorruptionError, match="more than one terminal"):
            journal.fold_events(events, expected_lineage=_LINEAGE)

    def test_accepted_on_non_land_is_corruption(self) -> None:
        events = [
            _event(_prepared(kind=journal.OperationKind.PUBLISH), comment_id="c1"),
            _event(_outcome(role=journal.EventRole.ACCEPTED), comment_id="c2", created_at="t2"),
        ]
        with pytest.raises(journal.JournalCorruptionError, match="gated to land"):
            journal.fold_events(events, expected_lineage=_LINEAGE)

    def test_accepted_then_completed_on_land_resolves(self) -> None:
        events = [
            _event(_prepared(kind=journal.OperationKind.LAND), comment_id="c1", created_at="t1"),
            _event(_outcome(role=journal.EventRole.ACCEPTED), comment_id="c2", created_at="t2"),
            _event(_outcome(role=journal.EventRole.COMPLETED), comment_id="c3", created_at="t3"),
        ]
        fold = journal.fold_events(events, expected_lineage=_LINEAGE)
        op = fold.operations[_ULID]
        assert op.resolved is True
        assert op.terminal_role is journal.EventRole.COMPLETED
        assert op.accepted is not None
        assert fold.unresolved == ()

    def test_prepared_only_is_unresolved(self) -> None:
        fold = journal.fold_events([_event(_prepared())], expected_lineage=_LINEAGE)
        assert [op.operation_id for op in fold.unresolved] == [_ULID]
        assert fold.operations[_ULID].terminal_role is None

    def test_prepared_plus_accepted_is_still_unresolved(self) -> None:
        events = [
            _event(_prepared(kind=journal.OperationKind.LAND), comment_id="c1", created_at="t1"),
            _event(_outcome(role=journal.EventRole.ACCEPTED), comment_id="c2", created_at="t2"),
        ]
        fold = journal.fold_events(events, expected_lineage=_LINEAGE)
        assert [op.operation_id for op in fold.unresolved] == [_ULID]

    def test_foreign_lineage_prepared_is_corruption(self) -> None:
        foreign = _event(_prepared(lineage="01JZ0000000000000000000000"))
        with pytest.raises(journal.JournalCorruptionError, match="foreign delivery_lineage"):
            journal.fold_events([foreign], expected_lineage=_LINEAGE)

    def test_mixed_lineages_without_expected_is_corruption(self) -> None:
        events = [
            _event(_prepared(), comment_id="c1", created_at="t1"),
            _event(
                _prepared(operation_id=_ULID_2, lineage="01JZ0000000000000000000000"),
                comment_id="c2",
                created_at="t2",
            ),
        ]
        with pytest.raises(journal.JournalCorruptionError, match="more than one delivery lineage"):
            journal.fold_events(events, expected_lineage=None)

    def test_empty_fold(self) -> None:
        fold = journal.fold_events([], expected_lineage=_LINEAGE)
        assert fold.events == ()
        assert fold.operations == {}
        assert fold.unresolved == ()
        assert fold.delivery_lineage == _LINEAGE

    def test_events_ordered_by_created_at_then_comment_id(self) -> None:
        a = _event(_prepared(), comment_id="c9", created_at="t1")
        b = _event(_outcome(), comment_id="c1", created_at="t2")
        fold = journal.fold_events([b, a], expected_lineage=_LINEAGE)
        assert fold.events == (a, b)


# ----------------------------------------------------------------- size cap


class TestSizeCap:
    def test_realistic_100_layer_land_record_fits(self) -> None:
        """A maximal (100-layer) land prepared record — node/plan ids, PR numbers, two 40-hex
        SHAs per layer in before/after — serializes well under the cap."""
        layers = [
            {
                "node_id": f"{i // 10 + 1}.{i % 10 + 1}",
                "plan_id": str(1000 + i),
                "pr": f"#{2000 + i}",
                "base_sha": f"{i:040x}",
                "head_sha": f"{i + 1:040x}",
            }
            for i in range(100)
        ]
        record = journal.PreparedRecord(
            operation_id=_ULID,
            operation_kind=journal.OperationKind.LAND,
            delivery_lineage=_LINEAGE,
            objective_id="252",
            run_id="01JC0000000000000000000000",
            created="2026-01-01T00:00:00Z",
            affected_plans=tuple(str(1000 + i) for i in range(100)),
            before={"layers": layers, "merge_method": "squash", "target_base": "main"},
            after={"layers": layers, "merged": True},
        )
        body = journal.render_event(record)
        assert len(body) < journal.JOURNAL_EVENT_MAX_CHARS
        journal.ensure_event_size(body)  # no raise

    def test_oversized_record_raises(self) -> None:
        record = _prepared()
        record = journal.PreparedRecord(
            operation_id=record.operation_id,
            operation_kind=record.operation_kind,
            delivery_lineage=record.delivery_lineage,
            objective_id=record.objective_id,
            run_id=record.run_id,
            created=record.created,
            affected_plans=record.affected_plans,
            before={"blob": "x" * (journal.JOURNAL_EVENT_MAX_CHARS + 1)},
            after={},
        )
        with pytest.raises(journal.JournalRecordTooLarge):
            journal.ensure_event_size(journal.render_event(record))


# ----------------------------------------------------------------- ready-stamp grammar


class TestStampRoundTrip:
    @pytest.mark.parametrize("transcode", [False, True], ids=["html", "inline-code"])
    def test_stamp_round_trip(self, transcode: bool) -> None:
        record = _stamp()
        body = journal.render_stamp_event(record)
        if transcode:
            body = to_linear_markdown(body)
            assert f"`perk:stack-ready-stamp:252:101:1.1:{_HEAD}`" in body
        else:
            assert f"<!-- perk:stack-ready-stamp:252:101:1.1:{_HEAD} -->" in body
        parsed = journal.parse_stamp_comment(body, comment_id="s1", created_at="t1", edited_at=None)
        assert parsed is not None
        assert parsed.record == record
        assert parsed.key == f"252:101:1.1:{_HEAD}"

    def test_encodings_share_key_and_payload(self) -> None:
        record = _stamp()
        html = _stamp_event(record)
        inline = _stamp_event(record, comment_id="s2", transcode=True)
        assert html.key == inline.key
        assert html.canonical_payload == inline.canonical_payload

    def test_unrelated_comment_is_ignored(self) -> None:
        assert (
            journal.parse_stamp_comment(
                "just a human comment", comment_id="s1", created_at="t1", edited_at=None
            )
            is None
        )


class TestCarrierRouting:
    """The one-grammar-per-comment dispatcher (operation-marker precedence)."""

    def test_operation_payload_mentioning_stamp_text_parses_as_operation(self) -> None:
        # The payload-collision regression: an operation whose opaque payload merely mentions
        # the stamp text is an operation — never reinterpreted as a malformed stamp.
        record = journal.PreparedRecord(
            operation_id=_ULID,
            operation_kind=journal.OperationKind.TRANSFER,
            delivery_lineage=_LINEAGE,
            objective_id="252",
            run_id="01JC0000000000000000000000",
            created="2026-01-01T00:00:00Z",
            affected_plans=("101",),
            before={},
            after={"prose": "user text mentioning perk:stack-ready-stamp markers"},
        )
        parsed = journal.parse_carrier_comment(
            journal.render_event(record), comment_id="c1", created_at="t1", edited_at=None
        )
        assert isinstance(parsed, journal.JournalEvent)
        assert parsed.record == record

    def test_stamp_body_routes_to_the_stamp_grammar(self) -> None:
        record = _stamp()
        parsed = journal.parse_carrier_comment(
            journal.render_stamp_event(record), comment_id="s1", created_at="t1", edited_at=None
        )
        assert isinstance(parsed, journal.ReadyStampEvent)
        assert parsed.record == record

    def test_stamp_body_is_none_under_the_operation_grammar(self) -> None:
        assert (
            journal.parse_journal_comment(
                journal.render_stamp_event(_stamp()),
                comment_id="s1",
                created_at="t1",
                edited_at=None,
            )
            is None
        )

    def test_operation_body_is_none_under_the_stamp_grammar(self) -> None:
        assert (
            journal.parse_stamp_comment(
                journal.render_event(_prepared()),
                comment_id="c1",
                created_at="t1",
                edited_at=None,
            )
            is None
        )

    def test_two_region_body_routes_to_the_operation_grammar_and_raises(self) -> None:
        body = journal.render_stamp_event(_stamp()) + "\n\n" + journal.render_event(_prepared())
        with pytest.raises(journal.JournalCorruptionError, match="stack-operation-event"):
            journal.parse_carrier_comment(body, comment_id="c1", created_at="t1", edited_at=None)

    def test_unrelated_comment_is_none(self) -> None:
        assert (
            journal.parse_carrier_comment(
                "just a human comment", comment_id="c1", created_at="t1", edited_at=None
            )
            is None
        )


class TestStampStrictRejections:
    def _parse(self, body: str, *, edited_at: str | None = None) -> journal.ReadyStampEvent | None:
        return journal.parse_stamp_comment(
            body, comment_id="s1", created_at="t1", edited_at=edited_at
        )

    def test_edited_stamp_is_corruption(self) -> None:
        body = journal.render_stamp_event(_stamp())
        with pytest.raises(journal.JournalCorruptionError, match="edited"):
            self._parse(body, edited_at="2026-02-02T00:00:00Z")

    def test_two_stamp_markers_in_one_body(self) -> None:
        body = journal.render_stamp_event(_stamp())
        with pytest.raises(journal.JournalCorruptionError, match="more than one ready-stamp"):
            self._parse(body + "\n\n" + body.replace(_HEAD, _HEAD_2))

    def test_malformed_marker_line(self) -> None:
        # A three-segment marker never matches the four-segment stamp grammar.
        body = f"<!-- perk:stack-ready-stamp:252:101:{_HEAD} -->\n\n```yaml\nevent: x\n```"
        with pytest.raises(journal.JournalCorruptionError, match="well-formed"):
            self._parse(body)

    def test_marker_not_on_leading_line(self) -> None:
        body = "prose first\n" + journal.render_stamp_event(_stamp())
        with pytest.raises(journal.JournalCorruptionError, match="well-formed"):
            self._parse(body)

    def test_unterminated_fence(self) -> None:
        body = journal.render_stamp_event(_stamp()).rsplit("```", 1)[0]
        with pytest.raises(journal.JournalCorruptionError, match="unterminated"):
            self._parse(body)

    def test_text_outside_marker_and_fence(self) -> None:
        body = journal.render_stamp_event(_stamp()) + "\n\ntrailing prose"
        with pytest.raises(journal.JournalCorruptionError, match="outside the marker"):
            self._parse(body)

    def test_non_mapping_yaml(self) -> None:
        marker = journal.render_stamp_marker(_stamp())
        body = f"{marker}\n\n```yaml\n- just\n- a list\n```"
        with pytest.raises(journal.JournalCorruptionError, match="not a YAML mapping"):
            self._parse(body)

    def test_unparseable_yaml(self) -> None:
        marker = journal.render_stamp_marker(_stamp())
        body = f"{marker}\n\n```yaml\n{{unbalanced\n```"
        with pytest.raises(journal.JournalCorruptionError, match="not parseable"):
            self._parse(body)

    def test_wrong_event_value(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace("event: ready_stamp", "event: stamped")
        with pytest.raises(journal.JournalCorruptionError, match="event"):
            self._parse(body)

    def test_extra_payload_field(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace(
            "event: ready_stamp", "event: ready_stamp\nsneaky: extra"
        )
        with pytest.raises(journal.JournalCorruptionError, match="sneaky"):
            self._parse(body)

    def test_missing_payload_field(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace("node_id: '1.1'\n", "")
        with pytest.raises(journal.JournalCorruptionError, match="node_id"):
            self._parse(body)

    def test_non_40_hex_head_sha(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace(_HEAD, "abc123")
        with pytest.raises(journal.JournalCorruptionError, match="head_sha"):
            self._parse(body)

    def test_colon_carrying_plan_id(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace("plan_id: '101'", "plan_id: '10:1'")
        with pytest.raises(journal.JournalCorruptionError, match="plan_id"):
            self._parse(body)

    @pytest.mark.parametrize("field_line", ["objective_id: '252'", "plan_id: '101'"])
    def test_leading_hash_id_is_rejected_at_parse(self, field_line: str) -> None:
        # The alias rejection: ids are canonical-bare at parse — never normalized at lookup.
        name, value = field_line.split(": ")
        body = journal.render_stamp_event(_stamp()).replace(
            field_line, f"{name}: '#{value.strip(chr(39))}'"
        )
        with pytest.raises(journal.JournalCorruptionError, match=name):
            self._parse(body)

    def test_leading_hash_id_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="canonical-bare"):
            _stamp(objective_id="#252")
        with pytest.raises(ValueError, match="canonical-bare"):
            _stamp(plan_id="#101")

    def test_head_sha_with_trailing_newline_is_rejected(self) -> None:
        # fullmatch, not a $-anchored match: `$` would admit a trailing newline, and rendering
        # such a record would embed the newline in the marker line.
        with pytest.raises(ValueError, match="head_sha"):
            _stamp(head_sha="a" * 40 + "\n")

    @pytest.mark.parametrize("node_id", ["x-->y", "a<!--b", "phase:one", "Phase 1", "a`b"])
    def test_marker_unsafe_node_id_is_a_typed_refusal(self, node_id: str) -> None:
        # The marker-safe allowlist: an id that would break either marker encoding (or the
        # deterministic colon-joined key) cannot construct a stamp — loud, never mangled.
        with pytest.raises(ValueError, match="node_id"):
            _stamp(node_id=node_id)

    def test_marker_objective_mismatch(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace(
            "perk:stack-ready-stamp:252:", "perk:stack-ready-stamp:999:"
        )
        with pytest.raises(journal.JournalCorruptionError, match="disagrees"):
            self._parse(body)

    def test_marker_head_mismatch(self) -> None:
        body = journal.render_stamp_event(_stamp()).replace(f":{_HEAD} -->", f":{_HEAD_2} -->")
        with pytest.raises(journal.JournalCorruptionError, match="disagrees"):
            self._parse(body)


class TestStampFold:
    def test_byte_identical_duplicate_dedupes_first_wins(self) -> None:
        record = _stamp()
        a = _stamp_event(record, comment_id="s1", created_at="t1")
        b = _stamp_event(record, comment_id="s2", created_at="t2")
        fold = journal.fold_events([], expected_lineage=_LINEAGE, stamps=[b, a])
        assert fold.stamps == (a,)

    def test_conflicting_same_key_duplicate_raises(self) -> None:
        # Same 4-segment key, differing payload (the lineage differs — the only non-key field).
        a = _stamp_event(_stamp(), comment_id="s1")
        b = _stamp_event(
            _stamp(lineage="01JZ0000000000000000000000"), comment_id="s2", created_at="t2"
        )
        with pytest.raises(
            journal.JournalCorruptionError, match="conflicting duplicate ready-stamp"
        ):
            journal.fold_events([], expected_lineage=None, stamps=[a, b])

    def test_foreign_lineage_stamp_vs_supplied_lineage_raises(self) -> None:
        foreign = _stamp_event(_stamp(lineage="01JZ0000000000000000000000"))
        with pytest.raises(journal.JournalCorruptionError, match="foreign delivery_lineage"):
            journal.fold_events([], expected_lineage=_LINEAGE, stamps=[foreign])

    def test_foreign_lineage_stamp_vs_operation_inferred_lineage_raises(self) -> None:
        # The mixed inference pin: stamps validate against the lineage the OPERATION records
        # resolve (stamps never contribute to the inference).
        op = _event(_prepared())
        foreign = _stamp_event(_stamp(lineage="01JZ0000000000000000000000"))
        with pytest.raises(journal.JournalCorruptionError, match="foreign delivery_lineage"):
            journal.fold_events([op], expected_lineage=None, stamps=[foreign])

    def test_stamps_only_no_lineage_fold_folds_as_parsed(self) -> None:
        # No expectation, no operations → stamp lineage is unverifiable; folded as parsed.
        stamp = _stamp_event(_stamp())
        fold = journal.fold_events([], expected_lineage=None, stamps=[stamp])
        assert fold.stamps == (stamp,)
        assert fold.delivery_lineage is None

    def test_stamps_never_perturb_operations_or_unresolved(self) -> None:
        op = _event(_prepared())
        stamp = _stamp_event(_stamp())
        with_stamps = journal.fold_events([op], expected_lineage=_LINEAGE, stamps=[stamp])
        without = journal.fold_events([op], expected_lineage=_LINEAGE)
        assert with_stamps.events == without.events
        assert with_stamps.operations == without.operations
        assert with_stamps.unresolved == without.unresolved

    def test_latest_ready_stamp_scopes_by_objective_identity(self) -> None:
        # A predecessor-objective stamp on the SHARED lineage folds (history retained) but
        # never projects under the active identity.
        predecessor = _stamp_event(_stamp(objective_id="111"), comment_id="s1")
        fold = journal.fold_events([], expected_lineage=_LINEAGE, stamps=[predecessor])
        assert fold.stamps == (predecessor,)
        assert fold.latest_ready_stamp(objective_id="252", plan_id="101") is None
        assert fold.latest_ready_stamp(objective_id="111", plan_id="101") == predecessor

    def test_latest_ready_stamp_scopes_by_plan(self) -> None:
        one = _stamp_event(_stamp(plan_id="101"), comment_id="s1")
        two = _stamp_event(_stamp(plan_id="102", node_id="1.2"), comment_id="s2")
        fold = journal.fold_events([], expected_lineage=_LINEAGE, stamps=[one, two])
        assert fold.latest_ready_stamp(objective_id="252", plan_id="101") == one
        assert fold.latest_ready_stamp(objective_id="252", plan_id="102") == two

    def test_latest_ready_stamp_is_latest_wins(self) -> None:
        # An OLDER stamp naming the current head loses to a newer stamp at another head —
        # only the latest stamp decides.
        older = _stamp_event(_stamp(head_sha=_HEAD), comment_id="s1", created_at="t1")
        newer = _stamp_event(_stamp(head_sha=_HEAD_2), comment_id="s2", created_at="t2")
        fold = journal.fold_events([], expected_lineage=_LINEAGE, stamps=[newer, older])
        latest = fold.latest_ready_stamp(objective_id="252", plan_id="101")
        assert latest == newer


# ----------------------------------------------------------------- engagement exclusion pins


class TestEngagementExclusion:
    """Journal comments are recognized and excluded as perk machinery by the existing
    engagement classifier + renderers — pinned here rather than re-implemented."""

    @pytest.mark.parametrize("transcode", [False, True], ids=["html", "inline-code"])
    def test_journal_body_carries_perk_sentinel(self, transcode: bool) -> None:
        body = journal.render_event(_prepared())
        if transcode:
            body = to_linear_markdown(body)
        assert engagement.body_carries_perk_sentinel(body) is True

    def test_classify_author_yields_perk(self) -> None:
        author = engagement.classify_author(
            body=journal.render_event(_prepared()),
            user=engagement.Actor(id="u1", name="alice"),
            bot_actor=None,
        )
        assert author.kind == "perk"

    @pytest.mark.parametrize("transcode", [False, True], ids=["html", "inline-code"])
    def test_stamp_body_carries_perk_sentinel(self, transcode: bool) -> None:
        body = journal.render_stamp_event(_stamp())
        if transcode:
            body = to_linear_markdown(body)
        assert engagement.body_carries_perk_sentinel(body) is True

    def test_classify_author_yields_perk_for_stamps(self) -> None:
        author = engagement.classify_author(
            body=journal.render_stamp_event(_stamp()),
            user=engagement.Actor(id="u1", name="alice"),
            bot_actor=None,
        )
        assert author.kind == "perk"

    def test_engagement_renderer_drops_journal_comments(self) -> None:
        body = journal.render_event(_prepared())
        journal_comment = engagement.EngagementComment(
            id="c1",
            body=body,
            created_at="t1",
            edited_at=None,
            author=engagement.classify_author(body=body, user=None, bot_actor=None),
        )
        assert engagement.render_plan_engagement((journal_comment,), ()) is None
