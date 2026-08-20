"""The `perk objective create` dream-transfer arc (contracts.md §8.64).

Recording Protocol fakes pin the D2 ordering (transfer decode → stacked prepare → origin guard →
create → carrier → parts → artifact → header), the refusal ladder (each `invalid_input` BEFORE
anything durable), the fail-closed guard, the converging retry, the byte-positioned
`post_status_update`, and the byte-identical payload/dry-run behavior.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends import resolve
from perk.backends.issue_backend import CommentResult, IssueBackendError
from perk.backends.objective_store import (
    ObjectiveHeaderUpdate,
    ObjectiveRef,
    ObjectiveStoreError,
)
from perk.cli.cli import cli
from perk.cli.commands.objective import create_cmd
from perk.learn import dream_companion as dc
from perk.state import cache

_RUN = "01RIDDREAM0000000000000000"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _transfer_blob(parts: list[str] | None = None, *, run_id: str = _RUN) -> str:
    return json.dumps(
        {"schema_version": "1", "run_id": run_id, "parts": parts or ["part one", "part two"]}
    )


class _RecordingStore:
    """An objective-store fake recording the D2 event order into a shared ``events`` list."""

    backend_id = "fake"

    def __init__(
        self,
        events: list,
        *,
        existed: bool = False,
        conflict: ObjectiveRef | None = None,
        guard_raises: bool = False,
        carrier: str | None = "42",
    ) -> None:
        self.events = events
        self._existed = existed
        self._conflict = conflict
        self._guard_raises = guard_raises
        self._carrier = carrier
        self.created_kwargs: dict | None = None
        self.header_writes: list[dict] = []
        self.status_posts: list[str] = []

    def find_open_objective_by_origin(self, *, origin, exclude_run_id=None):
        self.events.append(("guard", origin, exclude_run_id))
        if self._guard_raises:
            raise ObjectiveStoreError("origin scan failed (page 3 unreachable)")
        return self._conflict

    def create_objective(self, **kwargs):
        self.created_kwargs = kwargs
        self.events.append(("create",))
        return ObjectiveRef(id="42", url="u/42", existed=self._existed)

    def journal_carrier_id(self, *, objective_id):
        self.events.append(("carrier", objective_id))
        return self._carrier

    def update_objective_header(self, *, objective_id, fields, dry_run=False):
        self.events.append(("header", objective_id, dict(fields)))
        self.header_writes.append(dict(fields))
        return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)

    def post_status_update(self, *, objective_id, body, dry_run=False):
        self.events.append(("status_update", objective_id))
        self.status_posts.append(body)
        return True


class _RecordingIssues:
    """An issue-backend fake for the companion writes (records into the shared events list)."""

    backend_id = "fake"

    def __init__(self, events: list) -> None:
        self.events = events
        self.comments: dict[str, list] = {}
        self.post_plan: list[str] = []
        self._seq = 0

    def seed(self, issue_id: str, body: str) -> None:
        self._record(issue_id, body)

    def _record(self, issue_id: str, body: str) -> None:
        from perk.backends import engagement

        self._seq += 1
        self.comments.setdefault(issue_id, []).append(
            engagement.EngagementComment(
                id=f"c{self._seq}",
                body=body,
                created_at=f"2026-01-01T00:00:{self._seq:02d}Z",
                edited_at=None,
                author=engagement.EngagementAuthor(kind="perk", display_name=None, id=None),
            )
        )

    def add_issue_comment(self, *, issue_id: str, body: str, dry_run: bool = False):
        self.events.append(("parts", issue_id))
        behavior = self.post_plan.pop(0) if self.post_plan else "ok"
        if behavior == "raise_lost":
            raise IssueBackendError("boom (write lost)")
        self._record(issue_id, body)
        return CommentResult(posted=True)

    def read_comments(self, *, issue_id: str):
        return tuple(self.comments.get(issue_id, ()))


class _RecordingPublisher:
    def __init__(self, events: list, *, raises: bool = False) -> None:
        self.events = events
        self._raises = raises

    def publish(self, *, objective_id: str, run_id: str, parts) -> None:
        self.events.append(("artifact", objective_id, run_id))
        if self._raises:
            raise IssueBackendError("publish boom")


class _PrepareRecorder:
    def __init__(self, events: list) -> None:
        self.events = events

    def prepare(self, request):
        self.events.append(("prepare",))


def _invoke(
    args,
    *,
    monkeypatch,
    store,
    issues=None,
    publisher=None,
    transfer: str | None = None,
    manifest: bool = True,
    body: str = "# Dream objective\n\nprose",
    run_id: str = _RUN,
):
    _authed(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    if issues is not None:
        monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: issues)
    if publisher is not None:
        monkeypatch.setattr(resolve, "resolve_dream_artifact_publisher", lambda _root: publisher)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        root = Path(d)
        if transfer is not None:
            cache.write_scratch(root, run_id, dc.DREAM_REPORT_TRANSFER_FILENAME, transfer)
        if manifest:
            cache.write_scratch(root, run_id, "dream-manifest.json", "{}")
        bf = root / "obj.md"
        bf.write_text(body, encoding="utf-8")
        return runner.invoke(cli, [*args, "--body", str(bf)])


_ROADMAP = json.dumps([{"id": "1.1", "description": "x"}, {"id": "1.2", "description": "y"}])
_BASE_ARGS = ["objective", "create", "--json", "--run-id", _RUN, "--roadmap", _ROADMAP]


def _first_positions(events: list) -> list[str]:
    """The first-occurrence order of event names (the compressed D2 ordering)."""
    seen: list[str] = []
    for event in events:
        if event[0] not in seen:
            seen.append(event[0])
    return seen


# --- the ordinary path stays byte-identical ---------------------------------------------------


def test_transfer_absent_is_the_byte_identical_create(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(_BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer=None)
    assert result.exit_code == 0, result.output
    assert store.created_kwargs is not None and store.created_kwargs["origin"] is None
    assert _first_positions(events) == ["create", "status_update"]  # no guard, no companion


def test_dry_run_skips_the_whole_transfer_arc(monkeypatch):
    # --dry-run stays fully offline: the transfer arc, the guard, and the companion are all
    # skipped even with a transfer file present; the payload is unchanged.
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(
        [*_BASE_ARGS, "--dry-run"], monkeypatch=monkeypatch, store=store, transfer=_transfer_blob()
    )
    assert result.exit_code == 0, result.output
    assert _first_positions(events) == ["create"]
    assert store.created_kwargs is not None and store.created_kwargs["origin"] is None
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "objective": {"id": "42", "url": "u/42", "existed": False},
        "dry_run": True,
    }


# --- the dream arc: ordering, guard, companion -------------------------------------------------


def test_transfer_present_runs_the_full_d2_ordering(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    issues = _RecordingIssues(events)
    publisher = _RecordingPublisher(events)
    prepare = _PrepareRecorder(events)
    monkeypatch.setattr(create_cmd, "resolve_delivery", lambda _root: prepare)
    result = _invoke(
        [*_BASE_ARGS, "--delivery", "stacked"],
        monkeypatch=monkeypatch,
        store=store,
        issues=issues,
        publisher=publisher,
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 0, result.output
    # The compressed D2 order: stacked prepare (its existing position) → the origin guard →
    # create → carrier → parts → artifact → header — and post_status_update stays LAST
    # (fresh-create bookkeeping, after the whole try-block).
    assert _first_positions(events) == [
        "prepare",
        "guard",
        "create",
        "carrier",
        "parts",
        "artifact",
        "header",
        "status_update",
    ]
    guard = next(e for e in events if e[0] == "guard")
    assert guard[1] is objective.ObjectiveOrigin.LEARN_DREAM
    assert guard[2] == _RUN  # exclude_run_id = the door's own run
    assert store.created_kwargs is not None
    assert store.created_kwargs["origin"] is objective.ObjectiveOrigin.LEARN_DREAM
    assert store.header_writes == [{"dream_report": "42"}]
    # The stored bodies are the canonical marker-keyed renders.
    assert [c.body for c in issues.comments["42"]] == [
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one",
        f"<!-- perk:learn-dream-report:{_RUN}:2 -->\n\npart two",
    ]
    # The payload is byte-identical to a non-dream save (no new machine fields); the narration
    # line rides stderr.
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "objective": {"id": "42", "url": "u/42", "existed": False},
        "dry_run": False,
    }
    assert "Dream report companion converged (2 parts on carrier 42)" in result.stderr


def test_guard_hit_refuses_origin_conflict_naming_the_existing_ref(monkeypatch):
    events: list = []
    store = _RecordingStore(events, conflict=ObjectiveRef(id="9", url="u/existing/9", existed=True))
    result = _invoke(_BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer=_transfer_blob())
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "origin_conflict"
    assert "#9" in payload["message"] and "u/existing/9" in payload["message"]
    assert store.created_kwargs is None  # nothing created


def test_guard_raise_fails_closed(monkeypatch):
    events: list = []
    store = _RecordingStore(events, guard_raises=True)
    result = _invoke(_BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer=_transfer_blob())
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"
    assert store.created_kwargs is None


def test_retry_with_existing_objective_converges_and_skips_status_update(monkeypatch):
    # The converging retry: create finds the existing objective (existed=True); the companion
    # still converges (parts + artifact + header) and post_status_update is skipped permanently
    # (fresh-create-only bookkeeping — asserted, documented).
    events: list = []
    store = _RecordingStore(events, existed=True)
    issues = _RecordingIssues(events)
    issues.seed("42", f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    publisher = _RecordingPublisher(events)
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        issues=issues,
        publisher=publisher,
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["objective"]["existed"] is True
    assert store.header_writes == [{"dream_report": "42"}]
    assert not any(e[0] == "status_update" for e in events)
    # Only the missing part was posted (part 1 converged idempotently).
    assert [c.body for c in issues.comments["42"]][-1].startswith(
        f"<!-- perk:learn-dream-report:{_RUN}:2 -->"
    )


# --- the refusal ladder (each BEFORE anything durable) -----------------------------------------


def test_malformed_transfer_json_refuses_before_create(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(_BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer="{not json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert events == []


def test_transfer_schema_violation_refuses_before_create(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    blob = json.dumps(
        {"schema_version": "1", "run_id": _RUN, "parts": ["ok"], "origin": "learn-dream"}
    )
    result = _invoke(_BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer=blob)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert events == []


def test_cross_run_transfer_refuses(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        transfer=_transfer_blob(run_id="01RIDOTHER0000000000000000"),
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "invalid_input" and "cross-run" in payload["message"]
    assert events == []


def test_transfer_without_manifest_refuses(monkeypatch):
    # The structural launch evidence: a present transfer requires the run-scoped dream
    # manifest — origin stays launch-owned (no --origin flag; manual saves have no transfer).
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(
        _BASE_ARGS, monkeypatch=monkeypatch, store=store, transfer=_transfer_blob(), manifest=False
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "invalid_input" and "manifest" in payload["message"]
    assert events == []


def test_transfer_with_supersedes_refuses(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(
        [*_BASE_ARGS, "--supersedes", "7"],
        monkeypatch=monkeypatch,
        store=store,
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert events == []


def test_invariance_violating_parts_refuse_before_create(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        transfer=_transfer_blob(["fine", "bad <!-- perk:metadata-block:x --> part"]),
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "invalid_input" and "invariance" in payload["message"]
    assert events == []


# --- companion failures fail the save (nothing activates; retry converges) ---------------------


def test_companion_conflict_maps_to_its_error_type(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    issues = _RecordingIssues(events)
    issues.seed("42", f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\nDIFFERENT BYTES")
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        issues=issues,
        publisher=_RecordingPublisher(events),
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "companion_conflict"
    assert store.header_writes == []  # the header reference is only recorded after convergence
    assert not any(e[0] == "status_update" for e in events)


def test_companion_ambiguous_maps_to_its_error_type(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    issues = _RecordingIssues(events)
    issues.post_plan = ["raise_lost", "raise_lost"]
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        issues=issues,
        publisher=_RecordingPublisher(events),
        transfer=_transfer_blob(["only part"]),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "companion_ambiguous"
    assert store.header_writes == []


def test_publisher_failure_fails_the_save(monkeypatch):
    events: list = []
    store = _RecordingStore(events)
    issues = _RecordingIssues(events)
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        issues=issues,
        publisher=_RecordingPublisher(events, raises=True),
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"
    assert store.header_writes == []  # header LAST: never recorded past a failed artifact
    assert not any(e[0] == "status_update" for e in events)


def test_missing_carrier_fails_the_save(monkeypatch):
    events: list = []
    store = _RecordingStore(events, carrier=None)
    result = _invoke(
        _BASE_ARGS,
        monkeypatch=monkeypatch,
        store=store,
        issues=_RecordingIssues(events),
        publisher=_RecordingPublisher(events),
        transfer=_transfer_blob(),
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"
