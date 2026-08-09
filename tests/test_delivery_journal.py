"""Tests for the pure operation-journal layer (``perk/delivery/journal.py``).

Covers: render→parse round trips in BOTH marker encodings (the canonical HTML form and the
Linear-transcoded inline-code form, proving the logical key + payload are identical across
backends), the fail-closed strict rejections (edited / tampered / malformed / oversized), the
fold rules (dedupe, conflicts, orphans = out-of-band deletion, accepted gating, lineage checks,
unresolved detection), the size cap against a realistic 100-layer land record, and the
engagement-exclusion pins (journal comments classify as perk machinery and never reach the
rendered engagement blocks).
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
