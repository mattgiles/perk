"""Session-corpus + census tests (perk_dev.audit.corpus, `perk-dev audit census`).

All corpus construction drives the injectable seams (explicit `sessions_root` /
`main_root` / `worktree_root` / `catalog` / `bindings`) over synthetic JSONL fixtures —
never the real home dir. The encoding tests pin pi's exact (lossy) session-dir scheme
against real observed shapes.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.audit.corpus import (
    Census,
    CensusOut,
    build_census,
    classify_cwd,
    encode_session_dir,
    enumerate_candidate_dirs,
)
from perk_dev.audit.expectations import Expectation, ExpectationCatalog, ExpectationsError
from perk_dev.cli import cli

from perk.state.session_pointers import (
    SessionClassPointers,
    SessionPointer,
    SessionPointers,
    write_session_pointers,
)
from perk.substrate.bindings import Binding

# ------------------------------------------------------------------------- fixtures


def _catalog(*entries: Expectation) -> ExpectationCatalog:
    return ExpectationCatalog(schema_version=1, expectations=entries)


def _expectation(entry_id: str, applies_to: tuple[str, ...]) -> Expectation:
    return Expectation(
        id=entry_id,
        kind="workflow-shape",
        surface="s",
        source="p.md",
        applies_to=applies_to,
        vintage_floor="1.0.0",
        evidence="e",
        violation="v",
        tier="deterministic",
        enforcement="prose-only",
    )


# A small stand-in for the shipped defaults: two stage bindings, a plain command
# binding, and the one multi-trigger skill (the ambiguous case).
BINDINGS = [
    Binding(trigger="stage:implement", skill="perk-implement", mode="nudge"),
    Binding(trigger="stage:objective-plan", skill="perk-objective-plan", mode="nudge"),
    Binding(trigger="command:learn-docs", skill="perk-learn-docs", mode="nudge"),
    Binding(trigger="command:skills-create", skill="perk-skill-author", mode="nudge"),
    Binding(trigger="command:skills-refine", skill="perk-skill-author", mode="nudge"),
]

BINDING_HEADER = "The following skill binding(s) apply here:"


def _nudge(skill: str) -> str:
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _ws(**data: object) -> dict[str, object]:
    return {"type": "custom", "customType": "perk:workflow-state", "data": data}


def _user(text: str) -> dict[str, object]:
    content = [{"type": "text", "text": text}]
    return {"type": "message", "message": {"role": "user", "content": content}}


def _tool_result(text: str) -> dict[str, object]:
    content = [{"type": "text", "text": text}]
    return {
        "type": "message",
        "message": {"role": "toolResult", "toolName": "read", "content": content},
    }


def _custom(content: str, custom_type: str = "perk:binding-context") -> dict[str, object]:
    return {"type": "custom_message", "customType": custom_type, "content": content}


def _write_session(
    directory: Path,
    name: str,
    *,
    cwd: str | None,
    entries: list[dict[str, object]] | None = None,
    header: bool = True,
    timestamp: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if header:
        session_id = name.removesuffix(".jsonl")
        head: dict[str, object] = {"type": "session", "version": 3, "id": session_id}
        if cwd is not None:
            head["cwd"] = cwd
        if timestamp is not None:
            head["timestamp"] = timestamp
        lines.append(json.dumps(head))
    lines.extend(json.dumps(e) for e in entries or [])
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class Env:
    """A tmp corpus environment: a fake repo + worktrees + encoded session dirs."""

    def __init__(self, tmp_path: Path) -> None:
        self.main_root = tmp_path / "repo"
        self.main_root.mkdir()
        self.worktree_root = self.main_root / ".worktrees"
        self.worktree_root.mkdir()
        (self.worktree_root / "plan-7").mkdir()  # the live worktree; plan-9 stays deleted
        self.sessions_root = tmp_path / "sessions"
        self.sessions_root.mkdir()

    def session_dir(self, cwd: str) -> Path:
        return self.sessions_root / encode_session_dir(cwd)

    def census(
        self,
        catalog: ExpectationCatalog | None = None,
        bindings: list[Binding] | None = None,
    ) -> Census:
        return build_census(
            sessions_root=self.sessions_root,
            main_root=self.main_root,
            worktree_root=self.worktree_root,
            catalog=catalog if catalog is not None else _catalog(),
            bindings=bindings if bindings is not None else BINDINGS,
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def _record(census: Census, basename: str):
    matches = [r for r in census.sessions if r.basename == basename]
    assert len(matches) == 1, f"{basename}: {len(matches)} records"
    return matches[0]


# -------------------------------------------------------------------------- encoding


def test_encode_pins_pi_scheme_against_observed_shapes():
    assert encode_session_dir("/Users/x/repo") == "--Users-x-repo--"
    assert (
        encode_session_dir("/Users/x/repo/.worktrees/plan-7")
        == "--Users-x-repo-.worktrees-plan-7--"
    )
    # `:` is a separator too (pi replaces / \ and :).
    assert encode_session_dir("/Users/x/re:po") == "--Users-x-re-po--"
    # Only ONE leading slash is stripped; backslashes count as separators.
    assert encode_session_dir("\\srv\\repo") == "--srv-repo--"


def test_encode_is_lossy_sibling_collides_with_prefix():
    # A literal `-` is indistinguishable from a separator: the sibling repo encodes into
    # the main repo's prefix family — the header cwd, not the dir name, is the authority.
    main = encode_session_dir("/Users/x/repo")
    sibling = encode_session_dir("/Users/x/repo-foo")
    assert sibling.startswith(main[:-2] + "-")


# ------------------------------------------------------- enumeration + membership


def test_candidate_dirs_prefilter(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    wt_dir = env.session_dir(str(env.worktree_root / "plan-7"))
    lookalike = env.sessions_root / (encode_session_dir(str(env.main_root))[:-2] + "-foo--")
    unrelated = env.sessions_root / "--Users-somewhere-else--"
    for d in (main_dir, wt_dir, lookalike, unrelated):
        d.mkdir(parents=True, exist_ok=True)
    (env.sessions_root / "stray-file.jsonl").write_text("", encoding="utf-8")

    dirs = enumerate_candidate_dirs(
        env.sessions_root, main_root=env.main_root, worktree_root=env.worktree_root
    )
    names = {d.name for d in dirs}
    assert main_dir.name in names and wt_dir.name in names
    assert lookalike.name in names  # lossy prefix — survives to the header check
    assert unrelated.name not in names


def test_candidate_dirs_absent_sessions_root_is_empty(env: Env):
    assert (
        enumerate_candidate_dirs(
            env.sessions_root / "nope", main_root=env.main_root, worktree_root=env.worktree_root
        )
        == ()
    )


def test_candidate_dirs_external_worktree_root_prefix_added(env: Env, tmp_path: Path):
    external = tmp_path / "external-worktrees"
    wt_dir = env.sessions_root / encode_session_dir(str(external / "plan-3"))
    wt_dir.mkdir()
    dirs = enumerate_candidate_dirs(
        env.sessions_root, main_root=env.main_root, worktree_root=external
    )
    assert wt_dir.name in {d.name for d in dirs}


def test_membership_and_location_accounting(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(main_dir, "a-main.jsonl", cwd=str(env.main_root))
    _write_session(main_dir, "b-headerless.jsonl", cwd=None, header=False, entries=[_user("x")])
    _write_session(main_dir, "c-subpath.jsonl", cwd=str(env.main_root / "docs"))
    _write_session(main_dir, "d-cwdless.jsonl", cwd=None)
    # A directory named *.jsonl: opening it raises OSError → the `unreadable` count.
    (main_dir / "e-unreadable.jsonl").mkdir()

    live = env.worktree_root / "plan-7"
    _write_session(env.session_dir(str(live)), "f-live-wt.jsonl", cwd=str(live))
    deleted = env.worktree_root / "plan-9"
    _write_session(env.session_dir(str(deleted)), "g-deleted-wt.jsonl", cwd=str(deleted))

    lookalike_cwd = str(env.main_root) + "-foo"
    _write_session(env.session_dir(lookalike_cwd), "h-foreign.jsonl", cwd=lookalike_cwd)

    census = env.census()
    assert census.totals.candidate_files == 8
    assert census.totals.confirmed == 4
    assert census.totals.unconfirmed == 2  # header-less + cwd-less
    assert census.totals.foreign == 1
    assert census.totals.unreadable == 1

    assert _record(census, "a-main.jsonl").location == "main"
    assert _record(census, "c-subpath.jsonl").location == "subpath"
    live_rec = _record(census, "f-live-wt.jsonl")
    assert live_rec.location == "worktree"
    assert live_rec.worktree_name == "plan-7" and live_rec.worktree_exists is True
    deleted_rec = _record(census, "g-deleted-wt.jsonl")
    assert deleted_rec.location == "worktree"
    assert deleted_rec.worktree_name == "plan-9" and deleted_rec.worktree_exists is False
    assert "h-foreign.jsonl" not in {r.basename for r in census.sessions}


def test_membership_resolves_symlinked_root(tmp_path: Path):
    # The macOS `/private` symlink family: the recorded cwd may be the resolved form while
    # the configured root is a symlink (or vice versa) — membership compares against both.
    real = tmp_path / "real-repo"
    real.mkdir()
    link = tmp_path / "link-repo"
    link.symlink_to(real)
    worktrees = link / ".worktrees"
    loc = classify_cwd(str(real), main_root=link, worktree_root=worktrees)
    assert loc is not None and loc.kind == "main"
    sub = classify_cwd(str(real / "docs"), main_root=link, worktree_root=worktrees)
    assert sub is not None and sub.kind == "subpath"


def test_header_timestamp_recorded(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(main_dir, "t.jsonl", cwd=str(env.main_root), timestamp="2026-01-02T03:04:05Z")
    census = env.census()
    assert _record(census, "t.jsonl").timestamp == "2026-01-02T03:04:05Z"


def test_classify_cwd_worktree_root_itself_is_subpath(env: Env):
    loc = classify_cwd(
        str(env.worktree_root), main_root=env.main_root, worktree_root=env.worktree_root
    )
    assert loc is not None and loc.kind == "subpath"


# ------------------------------------------------------------- signals + identity


def test_cold_stage_session_identity_and_stage_evidence(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "cold.jsonl",
        cwd=str(env.main_root),
        entries=[
            _ws(run_id="01RUN", pi_session_id="cold.jsonl", mode="read-write", stage="implement"),
            # The delivered nudge for the SAME stage: corroboration only, never re-evidenced.
            _user(f"{BINDING_HEADER}\n\n{_nudge('perk-implement')}"),
        ],
    )
    census = env.census()
    rec = _record(census, "cold.jsonl")
    assert rec.identity == "perk-stage"
    assert rec.run_ids == ("01RUN",) and rec.stages == ("implement",)
    assert rec.modes == ("read-write",)
    assert rec.binding_header_seen is True
    assert rec.binding_skills == ("perk-implement",)
    triggers = {e.trigger for e in rec.evidence}
    assert triggers == {"stage:implement"}
    stage_evidence = [e for e in rec.evidence if e.trigger == "stage:implement"]
    assert stage_evidence[0].signal == "workflow-state"
    assert census.identity_counts == {"perk-stage": 1}
    assert census.stage_counts == {"implement": 1}
    assert census.trigger_counts == {"stage:implement": 1}


def test_warm_command_session_derives_command_trigger(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "warm.jsonl",
        cwd=str(env.main_root),
        entries=[
            _ws(run_id="01WARM", pi_session_id="warm.jsonl", mode="read-write"),  # no stage
            _custom(f"{BINDING_HEADER}\n\n{_nudge('perk-objective-plan')}"),
        ],
    )
    census = env.census()
    rec = _record(census, "warm.jsonl")
    assert rec.identity == "perk-warm"
    assert rec.stages == ()
    # stage:objective-plan binding + no observed stage → the warm-slash-command derivation.
    assert {e.trigger for e in rec.evidence} == {"command:objective-plan"}
    marker = rec.evidence[0]
    assert marker.signal == "binding-marker" and marker.skill == "perk-objective-plan"
    assert marker.ambiguous is False


def test_marker_only_and_plain_sessions(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "marker.jsonl",
        cwd=str(env.main_root),
        entries=[_user(f"{BINDING_HEADER}\n\n{_nudge('perk-learn-docs')}")],
    )
    _write_session(main_dir, "plain.jsonl", cwd=str(env.main_root), entries=[_user("hello")])
    census = env.census()
    marker = _record(census, "marker.jsonl")
    assert marker.identity == "marker-only"
    assert {e.trigger for e in marker.evidence} == {"command:learn-docs"}
    assert _record(census, "plain.jsonl").identity == "non-perk"
    assert census.identity_counts == {"marker-only": 1, "non-perk": 1}


def test_marker_scan_ignores_tool_result_quotes(env: Env):
    # Sessions in this repo routinely quote perk's own source in tool results — the scan
    # scope (user text + custom content only) kills that false-positive family.
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "quoted.jsonl",
        cwd=str(env.main_root),
        entries=[_tool_result(f"{BINDING_HEADER}\n\n{_nudge('perk-implement')}\n[READ-ONLY MODE]")],
    )
    census = env.census()
    rec = _record(census, "quoted.jsonl")
    assert rec.identity == "non-perk"
    assert rec.binding_header_seen is False
    assert rec.binding_skills == () and rec.read_only_marker is False


def test_read_only_marker_and_transclude_form(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "ro.jsonl",
        cwd=str(env.main_root),
        entries=[
            _custom("[READ-ONLY MODE]\nYou are in perk read-only mode.", "perk:mode-context"),
            _user("Skill `perk-learn-docs` (inlined for `command:learn-docs`):\n\nbody"),
            _ws(run_id="01RO", mode="read-only"),
        ],
    )
    census = env.census()
    rec = _record(census, "ro.jsonl")
    assert rec.read_only_marker is True
    assert rec.modes == ("read-only",)
    assert rec.binding_skills == ("perk-learn-docs",)
    assert census.mode_counts == {"read-only": 1}


def test_ambiguous_multi_trigger_skill_evidences_each(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "amb.jsonl",
        cwd=str(env.main_root),
        entries=[_user(f"{BINDING_HEADER}\n\n{_nudge('perk-skill-author')}")],
    )
    census = env.census()
    rec = _record(census, "amb.jsonl")
    assert {e.trigger for e in rec.evidence} == {"command:skills-create", "command:skills-refine"}
    assert all(e.ambiguous for e in rec.evidence)


def test_workflow_state_values_are_sets_across_forks(env: Env):
    # A session file can carry multiple branches: the census reports the SET of observed
    # values, never last-write-wins.
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "forks.jsonl",
        cwd=str(env.main_root),
        entries=[
            _ws(run_id="01A", stage="plan", mode="read-only"),
            _ws(run_id="01B", stage="implement", mode="read-write"),
            _ws(objective_node_claim={"node": "2.1"}),  # a delta with none of the keyed fields
        ],
    )
    census = env.census()
    rec = _record(census, "forks.jsonl")
    assert rec.run_ids == ("01A", "01B")
    assert rec.stages == ("implement", "plan")
    assert rec.modes == ("read-only", "read-write")
    assert {e.trigger for e in rec.evidence} == {"stage:implement", "stage:plan"}


# ---------------------------------------------------------------- pointer joins


def test_pointer_joins_by_basename(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(main_dir, "joined.jsonl", cwd=str(env.main_root), entries=[_user("hi")])
    write_session_pointers(
        env.main_root,
        "01RUN",
        SessionPointers(
            run_id="01RUN",
            planning=SessionClassPointers(
                main=SessionPointer(
                    pi_session_id="joined.jsonl", session_file="/x/joined.jsonl", at="t"
                )
            ),
            implementation=SessionClassPointers(
                worker=SessionPointer(
                    pi_session_id="joined.jsonl", session_file="/x/joined.jsonl", at="t"
                )
            ),
        ),
    )
    census = env.census()
    rec = _record(census, "joined.jsonl")
    joins = {(j.run_id, j.session_class, j.site) for j in rec.pointer_joins}
    assert joins == {("01RUN", "planning", "main"), ("01RUN", "implementation", "worker")}
    # A pointer join with no workflow-state entry is a marker-only identification.
    assert rec.identity == "marker-only"
    assert census.pointer_join_counts == {"implementation.worker": 1, "planning.main": 1}


# --------------------------------------------------------- not-exercised accounting


def test_not_exercised_accounting(env: Env):
    main_dir = env.session_dir(str(env.main_root))
    _write_session(
        main_dir,
        "s.jsonl",
        cwd=str(env.main_root),
        entries=[_ws(run_id="01R", stage="implement")],
    )
    catalog = _catalog(
        _expectation("hit", ("stage:implement", "stage:plan")),
        _expectation("miss", ("command:learn-docs",)),
    )
    census = env.census(catalog=catalog)
    by_id = {c.id: c for c in census.expectations}
    assert by_id["hit"].exercising_sessions == 1
    assert by_id["hit"].applies_to == ("stage:implement", "stage:plan")
    assert by_id["miss"].exercising_sessions == 0
    assert census.not_exercised == ("miss",)


def test_empty_corpus_reports_all_not_exercised(env: Env):
    catalog = _catalog(_expectation("a", ("stage:plan",)), _expectation("b", ("stage:implement",)))
    census = env.census(catalog=catalog)
    assert census.totals.candidate_files == 0
    assert census.not_exercised == ("a", "b")


# ------------------------------------------------------------------------------ CLI


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, timeout=60, capture_output=True)


@pytest.fixture
def cli_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    env = Env(tmp_path)
    _git(env.main_root, "init", "-q")
    monkeypatch.chdir(env.main_root)
    return env


def test_cli_census_json_envelope(cli_repo: Env):
    _write_session(
        cli_repo.session_dir(str(cli_repo.main_root)),
        "s.jsonl",
        cwd=str(cli_repo.main_root),
        entries=[_ws(run_id="01R", stage="implement")],
    )
    result = CliRunner().invoke(
        cli, ["audit", "census", "--sessions-root", str(cli_repo.sessions_root), "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == set(CensusOut.model_fields)
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["totals"]["confirmed"] == 1
    assert payload["sessions"][0]["identity"] == "perk-stage"
    assert payload["stage_counts"] == {"implement": 1}
    # The committed catalog is the coverage baseline; nothing here exercises most of it.
    assert payload["not_exercised"]


def test_cli_census_human_render(cli_repo: Env):
    _write_session(
        cli_repo.session_dir(str(cli_repo.main_root)),
        "s.jsonl",
        cwd=str(cli_repo.main_root),
        entries=[_ws(run_id="01R", stage="implement")],
    )
    result = CliRunner().invoke(
        cli, ["audit", "census", "--sessions-root", str(cli_repo.sessions_root)]
    )
    assert result.exit_code == 0, result.output
    out = " ".join(result.stderr.split())  # the human render goes to stderr
    assert "candidate files: 1" in out
    assert "confirmed 1" in out
    assert "identity: perk-stage 1" in out
    assert "stages: implement 1" in out
    assert "not exercised:" in out


def test_cli_census_not_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outside = tmp_path / "no-repo"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = CliRunner().invoke(cli, ["audit", "census", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload == {
        "success": False,
        "error_type": "not_a_repo",
        "message": "not inside a git repository",
    }


def test_cli_census_bad_catalog(cli_repo: Env, monkeypatch: pytest.MonkeyPatch):
    from perk_dev import cli as cli_mod

    def _boom(path=None):
        raise ExpectationsError("catalog is structurally broken")

    monkeypatch.setattr(cli_mod.expectations, "load_catalog", _boom)
    result = CliRunner().invoke(
        cli_mod.cli,
        ["audit", "census", "--sessions-root", str(cli_repo.sessions_root), "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "bad_catalog"
    assert "structurally broken" in payload["message"]
