"""Tests for the backend-neutral human-engagement contract (Objective #682, Node 1.2).

Pure unit tests for the author-identity classifier + the result dataclass invariants. No network,
no backend — ``engagement.py`` imports nothing from the backend tiers.
"""

import dataclasses

import pytest

from perk.backends import engagement


class TestPerkSentinel:
    def test_html_comment_marker_detected(self) -> None:
        assert engagement.body_carries_perk_sentinel("<!-- perk:metadata-block:plan-body -->")

    def test_inline_code_marker_detected(self) -> None:
        assert engagement.body_carries_perk_sentinel("`perk:metadata-block:plan-header`")

    def test_closing_marker_detected(self) -> None:
        assert engagement.body_carries_perk_sentinel("text\n`/perk:metadata-block:plan-body`\n")

    def test_plain_text_is_not_a_sentinel(self) -> None:
        assert not engagement.body_carries_perk_sentinel("just a normal human comment about perk")

    def test_bare_word_perk_is_not_a_sentinel(self) -> None:
        # The grammar is `perk:<...>` in a marker encoding — a stray "perk:" in prose is not.
        assert not engagement.body_carries_perk_sentinel("see perk: the tool")


class TestClassifyAuthor:
    def test_human_via_user_with_no_bot_actor(self) -> None:
        author = engagement.classify_author(
            body="please rebase this",
            user=engagement.Actor(id="u-1", name="Ada"),
            bot_actor=None,
        )
        assert author.kind == "human"
        assert author.display_name == "Ada"
        assert author.id == "u-1"

    def test_perk_via_body_sentinel(self) -> None:
        author = engagement.classify_author(
            body="<!-- perk:metadata-block:plan-body -->\n## Plan",
            user=engagement.Actor(id="u-1", name="perk-bot"),
            bot_actor=None,
        )
        assert author.kind == "perk"

    def test_perk_via_own_app_bot_actor(self) -> None:
        author = engagement.classify_author(
            body="no marker here",
            user=None,
            bot_actor=engagement.Actor(id="bot-perk", name="perk"),
            perk_bot_ids=("bot-perk",),
        )
        assert author.kind == "perk"
        assert author.display_name == "perk"
        assert author.id == "bot-perk"

    def test_other_agent_via_foreign_bot_actor(self) -> None:
        author = engagement.classify_author(
            body="automated comment",
            user=None,
            bot_actor=engagement.Actor(id="bot-other", name="SomeBot"),
            perk_bot_ids=("bot-perk",),
        )
        assert author.kind == "other_agent"
        assert author.display_name == "SomeBot"
        assert author.id == "bot-other"

    def test_bot_actor_prefers_over_user_for_display(self) -> None:
        # A bot actor present alongside a user → other_agent, display from the bot actor.
        author = engagement.classify_author(
            body="x",
            user=engagement.Actor(id="u-1", name="Ada"),
            bot_actor=engagement.Actor(id="bot-other", name="SomeBot"),
        )
        assert author.kind == "other_agent"
        assert author.display_name == "SomeBot"

    def test_unknown_when_neither_resolvable(self) -> None:
        author = engagement.classify_author(body="x", user=None, bot_actor=None)
        assert author.kind == "unknown"
        assert author.display_name is None
        assert author.id is None

    def test_body_sentinel_wins_even_with_a_human_user(self) -> None:
        # The documented heuristic: a perk sentinel in the body classifies as perk regardless of
        # the user actor (a human who pastes perk output is still flagged perk by the grammar).
        author = engagement.classify_author(
            body="`perk:metadata-block:plan-body`",
            user=engagement.Actor(id="u-1", name="Ada"),
            bot_actor=None,
        )
        assert author.kind == "perk"
        # display still reflects the only present actor (the user)
        assert author.display_name == "Ada"


class TestResultDataclasses:
    def test_dataclasses_are_frozen(self) -> None:
        comment = engagement.EngagementComment(
            id="c1",
            body="hi",
            created_at="t",
            edited_at=None,
            author=engagement.EngagementAuthor(kind="human", display_name="A", id="u"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            comment.body = "tampered"  # ty: ignore[invalid-assignment]

    def test_empty_agent_session_shape(self) -> None:
        assert engagement.EMPTY_AGENT_SESSION.activities == ()
        assert engagement.EMPTY_AGENT_SESSION.stop_signal.stopped is False
        assert engagement.EMPTY_AGENT_SESSION.stop_signal.at is None
