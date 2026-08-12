"""The learn evidence-bundle gatherer (contracts.md §8.35)."""

from pathlib import Path

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.learn import docs_scan
from perk.learn.docs_scan import DocFindings, StalePointer
from perk.learn.evidence import gather_evidence, scan_existing_docs
from perk.state.session_pointers import (
    SessionClassPointers,
    SessionPointer,
    SessionPointers,
    write_session_pointers,
)

_FIXTURE_JSONL = (
    '{"type":"session","version":3,"id":"sess-pm","cwd":"/some/worktree"}\n'
    '{"type":"message","role":"user","content":"hello"}\n'
)


def _ref(pr_id: str = "7") -> plan.PlanRef:
    return plan.PlanRef(
        provider="github",
        pr_id=pr_id,
        url="https://gh/o/r/issues/7",
        labels=("perk:plan",),
        objective_id=None,
    )


class _FakeBackend:
    """A minimal IssueBackend stub: get_plan + get_plan_body, recording the plan-fetch calls."""

    def __init__(self, *, header: dict[str, object], body: str | None = "PLAN BODY") -> None:
        self._header = header
        self._body = body
        self.plan_calls = 0

    def get_plan(self, *, issue_id: str) -> PlanState:
        self.plan_calls += 1
        return PlanState(
            id=issue_id, url="u", title="My Feature", header=self._header, pr=None, state="OPEN"
        )

    def get_plan_body(self, *, issue_id: str) -> str | None:
        return self._body


def _patch_backend(monkeypatch, backend: object) -> None:
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: backend)


def _no_pr(monkeypatch) -> None:
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: ())


def _seed_planning_session(repo_root: Path, src: Path, run_id: str = "01RUN_P") -> None:
    write_session_pointers(
        repo_root,
        run_id,
        SessionPointers(
            run_id=run_id,
            planning=SessionClassPointers(
                main=SessionPointer(
                    pi_session_id="sess-pm.jsonl",
                    session_file=str(src),
                    at="2026-06-01T00:00:00Z",
                ),
            ),
        ),
    )


def _git_init(path, factory) -> None:
    factory(path)


def _read(repo_root: Path, artifact: str | None) -> bytes:
    assert artifact is not None
    return (repo_root / artifact).read_bytes()


# --- scan_existing_docs -----------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_existing_docs_kinds_titles_sorted(tmp_path: Path):
    _write(
        tmp_path / "docs/learned/workflow/foo.md",
        "---\ntitle: Foo learning\nread_when: working on foo\n---\n\nBody.\n",
    )
    _write(
        tmp_path / ".perk/skills/my-skill/SKILL.md",
        "---\nname: my-skill\ndescription: Does a thing.\n---\n\n# My skill\n",
    )
    _write(
        tmp_path / "docs/user-docs/reference/cli.md",
        "# CLI reference\n\nThe first paragraph describes the CLI.\n\nMore.\n",
    )

    entries = scan_existing_docs(tmp_path)
    by_path = {e.path: e for e in entries}

    assert [e.path for e in entries] == sorted(by_path)  # deterministic sort by path
    learned = by_path["docs/learned/workflow/foo.md"]
    assert learned.kind == "learned" and learned.title == "Foo learning"
    assert learned.snippet == "working on foo"
    skill = by_path[".perk/skills/my-skill/SKILL.md"]
    assert skill.kind == "skill" and skill.title == "my-skill"
    assert skill.snippet == "Does a thing."
    userdoc = by_path["docs/user-docs/reference/cli.md"]
    assert userdoc.kind == "user-doc" and userdoc.title == "CLI reference"
    assert userdoc.snippet == "The first paragraph describes the CLI."


def test_scan_existing_docs_nonexistent_roots(tmp_path: Path):
    assert scan_existing_docs(tmp_path) == ()


def test_scan_excludes_top_level_skills(tmp_path: Path):
    # Top-level `skills/` is perk's own codebase, not the workflow-managed surface.
    _write(
        tmp_path / "skills/perk-plan/SKILL.md",
        "---\nname: perk-plan\ndescription: A bundled skill.\n---\n",
    )
    assert scan_existing_docs(tmp_path) == ()


def test_scan_malformed_frontmatter_never_raises(tmp_path: Path):
    _write(tmp_path / "docs/learned/bad.md", "---\nthis: : : not yaml\n---\nBody\n")
    entries = scan_existing_docs(tmp_path)
    assert len(entries) == 1
    assert entries[0].title is None and entries[0].snippet is None


def test_scan_user_doc_frontmatter_first(tmp_path: Path):
    _write(
        tmp_path / "docs/user-docs/how-to/foo.md",
        '---\ntitle: "Front title"\ndescription: "Front description."\n---\n\n# H1 title\n\n'
        "First paragraph.\n",
    )
    (entry,) = scan_existing_docs(tmp_path)
    assert entry.title == "Front title"
    assert entry.snippet == "Front description."


def test_scan_user_doc_mdx_inventoried(tmp_path: Path):
    _write(
        tmp_path / "docs/user-docs/how-to/foo.mdx",
        '---\ntitle: "MDX doc"\ndescription: "An MDX page."\n---\n\n# MDX doc\n',
    )
    (entry,) = scan_existing_docs(tmp_path)
    assert entry.path == "docs/user-docs/how-to/foo.mdx"
    assert entry.title == "MDX doc" and entry.snippet == "An MDX page."


def test_scan_user_doc_underscore_and_dot_paths_not_inventoried(tmp_path: Path):
    _write(tmp_path / "docs/user-docs/_authoring.md", "# Authoring the operator docs\n\nBody.\n")
    _write(tmp_path / "docs/user-docs/.hidden.md", "# Hidden\n\nBody.\n")
    _write(tmp_path / "docs/user-docs/.obsidian/note.md", "# Dot dir\n\nBody.\n")
    _write(tmp_path / "docs/user-docs/how-to/real.md", "# Real\n\nBody.\n")
    entries = scan_existing_docs(tmp_path)
    assert [e.path for e in entries] == ["docs/user-docs/how-to/real.md"]


def test_scan_user_doc_per_field_fallback_bad_description(tmp_path: Path):
    # A malformed (non-str) `description` degrades ONLY the snippet to the legacy read; the
    # valid frontmatter `title` is kept.
    _write(
        tmp_path / "docs/user-docs/foo.md",
        '---\ntitle: "Front title"\ndescription: [not, a, string]\n---\n\n# H1 title\n\n'
        "First paragraph.\n",
    )
    (entry,) = scan_existing_docs(tmp_path)
    assert entry.title == "Front title"
    assert entry.snippet == "First paragraph."


def test_scan_user_doc_per_field_fallback_bad_title(tmp_path: Path):
    _write(
        tmp_path / "docs/user-docs/foo.md",
        '---\ntitle: 42\ndescription: "Front description."\n---\n\n# H1 title\n\n'
        "First paragraph.\n",
    )
    (entry,) = scan_existing_docs(tmp_path)
    assert entry.title == "H1 title"
    assert entry.snippet == "Front description."


def test_scan_user_doc_malformed_foreign_key_never_contaminates(tmp_path: Path):
    # A malformed foreign key (a `cluster:` list would fail the whole `_DocFrontmatter` model)
    # cannot nuke the user-doc read: the per-field extraction never reads unknown keys.
    _write(
        tmp_path / "docs/user-docs/foo.md",
        '---\ntitle: "Front title"\ndescription: "Front description."\ncluster: [a, b]\n---\n\n'
        "# H1 title\n\nFirst paragraph.\n",
    )
    (entry,) = scan_existing_docs(tmp_path)
    assert entry.title == "Front title"
    assert entry.snippet == "Front description."


# --- gather_evidence: skip --------------------------------------------------------------------


def test_skip_on_consumed_learn(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    backend = _FakeBackend(header={"consumed_learn": ["12", "13"]})
    _patch_backend(monkeypatch, backend)

    pr_calls: list[str] = []
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: pr_calls.append("called") or ())

    bundle = gather_evidence(tmp_path, _ref())

    assert bundle.skipped is True
    assert bundle.skip_reason and "consumed_learn" in bundle.skip_reason
    assert bundle.sources == () and bundle.existing_docs == ()
    assert bundle.docs_findings == DocFindings()  # empty rich scan on a skip bundle
    assert bundle.bundle_dir is None
    assert pr_calls == []  # no PR gathering on skip


# --- gather_evidence: full --------------------------------------------------------------------


def test_full_gather_materializes_all(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    src = tmp_path / "home" / "sess-pm.jsonl"
    src.parent.mkdir(parents=True)
    src.write_text(_FIXTURE_JSONL, encoding="utf-8")
    _seed_planning_session(tmp_path, src)
    _write(tmp_path / "docs/learned/foo.md", "---\ntitle: Foo\nread_when: x\n---\nBody\n")

    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    merged = github.PullRequest(
        number=42, url="u/42", is_draft=False, state="MERGED", existed=True, base_ref="main"
    )
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: (merged,))
    monkeypatch.setattr(
        github,
        "get_pr_review_context",
        lambda **k: github.PrReviewContext(
            pr_number=42,
            base_ref="main",
            head_ref="plan-7",
            title="t",
            body="b",
            diff="DIFF BYTES",
            plan_body=None,
        ),
    )

    bundle = gather_evidence(tmp_path, _ref())

    assert bundle.skipped is False
    by_cat = {s.category: s for s in bundle.sources}
    assert by_cat["plan"].status == "found"
    assert _read(tmp_path, by_cat["plan"].artifact) == b"PLAN BODY"
    assert by_cat["pr"].status == "found"
    assert _read(tmp_path, by_cat["pr"].artifact) == b"DIFF BYTES"
    assert by_cat["pr"].detail == "#42 MERGED base=main"

    planning = [s for s in bundle.sources if s.category == "planning-session"]
    pmain = next(s for s in planning if s.label == "main")
    assert pmain.status == "found"
    assert _read(tmp_path, pmain.artifact) == src.read_bytes()
    assert next(s for s in planning if s.label == "worker").status == "missing"

    impl = [s for s in bundle.sources if s.category == "implementation-session"]
    assert len(impl) == 1 and impl[0].label == "(none)" and impl[0].status == "missing"

    assert by_cat["existing-docs"].status == "found"
    assert len(bundle.existing_docs) == 1
    assert bundle.docs_findings == DocFindings()  # the planted doc carries no stale pointers


def test_full_gather_populates_docs_findings(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    # `perk/run/launch.py` is a dir here → the cited pointer's file is gone (a phantom).
    (tmp_path / "perk/run/launch").mkdir(parents=True)
    _write(
        tmp_path / "docs/learned/foo.md",
        "---\ntitle: Foo\nread_when: x\n---\nSee `perk/run/launch.py::gone`.\n",
    )
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    _no_pr(monkeypatch)

    bundle = gather_evidence(tmp_path, _ref())

    assert bundle.skipped is False
    assert bundle.docs_findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/foo.md", pointer="perk/run/launch.py::gone", reason="missing-file"
        ),
    )


def test_impl_runs_resolved(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    impl_src = tmp_path / "home" / "impl-main.jsonl"
    impl_src.parent.mkdir(parents=True)
    impl_src.write_text(_FIXTURE_JSONL, encoding="utf-8")
    write_session_pointers(
        tmp_path,
        "01RUN_I",
        SessionPointers(
            run_id="01RUN_I",
            implementation=SessionClassPointers(
                main=SessionPointer(
                    pi_session_id="impl-main.jsonl",
                    session_file=str(impl_src),
                    at="2026-06-01T00:00:00Z",
                ),
            ),
        ),
    )
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": ["01RUN_I"]})
    _patch_backend(monkeypatch, backend)
    _no_pr(monkeypatch)

    bundle = gather_evidence(tmp_path, _ref())

    impl = [s for s in bundle.sources if s.category == "implementation-session"]
    assert {s.label for s in impl} == {"01RUN_I/main", "01RUN_I/worker"}
    main = next(s for s in impl if s.label == "01RUN_I/main")
    assert main.status == "found"
    assert _read(tmp_path, main.artifact) == impl_src.read_bytes()
    assert next(s for s in impl if s.label == "01RUN_I/worker").status == "missing"


def test_pr_diff_read_failure_stays_found_no_artifact(
    tmp_path: Path, monkeypatch, capsys, unborn_git_repo_factory
):
    # A diff-read failure leaves the PR `found` (with a null artifact) + a warning — never raises.
    _git_init(tmp_path, unborn_git_repo_factory)
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    merged = github.PullRequest(
        number=42, url="u/42", is_draft=False, state="MERGED", existed=True, base_ref="main"
    )
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: (merged,))

    def _boom(**_k):
        raise github.GitHubError("diff unavailable")

    monkeypatch.setattr(github, "get_pr_review_context", _boom)

    bundle = gather_evidence(tmp_path, _ref())
    pr = next(s for s in bundle.sources if s.category == "pr")
    assert pr.status == "found" and pr.artifact is None
    assert pr.detail == "#42 MERGED base=main"
    assert "warning" in capsys.readouterr().err


def test_missing_pr_source_still_returns(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    _no_pr(monkeypatch)

    bundle = gather_evidence(tmp_path, _ref())

    by_cat = {s.category: s for s in bundle.sources}
    assert by_cat["pr"].status == "missing"
    assert by_cat["pr"].detail and "no PR for branch" in by_cat["pr"].detail
    assert by_cat["plan"].status == "found"  # other sources still resolve


def test_pr_ambiguous_no_diff(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    two = (
        github.PullRequest(
            number=1, url="u/1", is_draft=False, state="OPEN", existed=True, base_ref="main"
        ),
        github.PullRequest(
            number=2, url="u/2", is_draft=False, state="CLOSED", existed=True, base_ref="main"
        ),
    )
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: two)

    diff_calls: list[str] = []
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: diff_calls.append("x"))

    bundle = gather_evidence(tmp_path, _ref())
    pr = next(s for s in bundle.sources if s.category == "pr")
    assert pr.status == "ambiguous"
    assert pr.artifact is None
    assert pr.detail == "2 PRs match branch plan-7; 0 merged"
    assert diff_calls == []


def test_one_merged_among_closed_is_found(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    prs = (
        github.PullRequest(
            number=1, url="u/1", is_draft=False, state="CLOSED", existed=True, base_ref="main"
        ),
        github.PullRequest(
            number=2, url="u/2", is_draft=False, state="MERGED", existed=True, base_ref="main"
        ),
    )
    monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: prs)
    monkeypatch.setattr(
        github,
        "get_pr_review_context",
        lambda **k: github.PrReviewContext(
            pr_number=2,
            base_ref="main",
            head_ref="plan-7",
            title="t",
            body="b",
            diff="D",
            plan_body=None,
        ),
    )

    bundle = gather_evidence(tmp_path, _ref())
    pr = next(s for s in bundle.sources if s.category == "pr")
    assert pr.status == "found" and pr.detail == "#2 MERGED base=main"


def test_plan_fetch_error_warns_no_skip(
    tmp_path: Path, monkeypatch, capsys, unborn_git_repo_factory
):
    _git_init(tmp_path, unborn_git_repo_factory)

    class _Boom:
        backend_id = "github"

        def get_plan(self, *, issue_id: str) -> PlanState:
            raise IssueBackendError("backend down")

        def get_plan_body(self, *, issue_id: str) -> str | None:
            return None

    _patch_backend(monkeypatch, _Boom())
    _no_pr(monkeypatch)

    bundle = gather_evidence(tmp_path, _ref())

    assert bundle.skipped is False  # a fetch failure is never a learn-docs signal
    plan_src = next(s for s in bundle.sources if s.category == "plan")
    assert plan_src.status == "missing"
    assert "warning" in capsys.readouterr().err


def test_gc_session_slot_missing(tmp_path: Path, monkeypatch, unborn_git_repo_factory):
    _git_init(tmp_path, unborn_git_repo_factory)
    # Pointer references a file that does not exist → export downgrades to missing.
    write_session_pointers(
        tmp_path,
        "01RUN_P",
        SessionPointers(
            run_id="01RUN_P",
            planning=SessionClassPointers(
                main=SessionPointer(
                    pi_session_id="gone.jsonl",
                    session_file=str(tmp_path / "gone.jsonl"),
                    at="2026-06-01T00:00:00Z",
                ),
            ),
        ),
    )
    backend = _FakeBackend(header={"run_id": "01RUN_P", "impl_run_ids": []})
    _patch_backend(monkeypatch, backend)
    _no_pr(monkeypatch)

    bundle = gather_evidence(tmp_path, _ref())
    planning = [s for s in bundle.sources if s.category == "planning-session"]
    assert all(s.status == "missing" for s in planning)


def test_truncate_bounds_snippet(tmp_path: Path):
    long = "x " * 400
    _write(tmp_path / "docs/learned/long.md", f"---\ntitle: T\nread_when: {long}\n---\n")
    entry = scan_existing_docs(tmp_path)[0]
    assert entry.snippet is not None and len(entry.snippet) <= docs_scan._SNIPPET_LEN
