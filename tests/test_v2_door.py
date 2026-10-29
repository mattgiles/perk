"""The hidden ``perk v2`` door (contracts.md §8.77) through the root CLI, with the host spawn faked.

``perk.v2.door._run_host`` is replaced by a recorder that answers with a committed envelope golden
(re-addressed to the invoked execution), a chosen exit, or a ``ProcFailure`` — so these cases pin
target resolution, the exact host argv, the failure vocabulary, the execution id on
post-invocation failures, and the exit-code map, without node. The real host is exercised by the
TypeScript suite (``extension/pi/v2/door/``).
"""

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.substrate import git
from perk.substrate.proc import ProcFailure
from perk.v2 import door

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "extension" / "pi" / "v2" / "door" / "golden"
EXECUTION = "01HZY3V8Q2M5N7P9R1T3V5X7Z9"
DECISION = "v2/01HZY3V8Q2M5N7P9R1T3V5X7Z9/decision/abc/fixture-approval"
_ULID_CHARS = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def _golden(name: str) -> dict[str, object]:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _token(argv: Sequence[str], name: str) -> str:
    prefix = f"--{name}="
    return next(arg[len(prefix) :] for arg in argv if arg.startswith(prefix))


@dataclass
class FakeHost:
    """The recorded spawn seam: answers with ``golden`` (its execution id rewritten to the
    invoked one) or ``stdout`` (default empty), with ``returncode``/``stderr``; or raises
    ``raises``."""

    golden: str | None = None
    stdout: str | None = None
    returncode: int = 0
    stderr: str = ""
    raises: ProcFailure | None = None
    calls: list[tuple[list[str], Path]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), cwd))
        if self.raises is not None:
            raise self.raises
        stdout = self.stdout or ""
        if self.golden is not None:
            payload = {**_golden(self.golden), "executionId": _token(argv, "execution")}
            stdout = json.dumps(payload) + "\n"
        return subprocess.CompletedProcess(list(argv), self.returncode, stdout, self.stderr)

    @property
    def argv(self) -> list[str]:
        assert len(self.calls) == 1, self.calls
        return self.calls[0][0]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=60,
    )


def _make_self(root: Path, *, entry: bool = True) -> None:
    (root / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    if entry:
        main = root.joinpath(*door.HOST_ENTRY_PARTS)
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_text("// stub host entry\n", encoding="utf-8")


@pytest.fixture
def self_repo(git_repo: Path) -> Path:
    """A git repo marked as perk's own checkout, with a stub host entry, committed."""
    _make_self(git_repo)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "self")
    return git_repo


def _install(monkeypatch: pytest.MonkeyPatch, host: FakeHost) -> FakeHost:
    monkeypatch.setattr(door, "_run_host", host)
    return host


def _invoke(monkeypatch: pytest.MonkeyPatch, cwd: Path, args: list[str]):
    monkeypatch.chdir(cwd)
    return CliRunner().invoke(cli, ["v2", *args])


def _store(root: Path, execution_id: str) -> str:
    return str(root / ".perk" / "executions" / execution_id)


def _identity(root: Path) -> str:
    return str((root / ".git").resolve())


# ── pre-invocation failures ─────────────────────────────────────────────────────────────────────


def test_outside_a_repo_is_not_a_repo(monkeypatch, tmp_path_factory):
    host = _install(monkeypatch, FakeHost(golden="status-ok-running"))
    result = _invoke(monkeypatch, tmp_path_factory.mktemp("bare"), ["status", EXECUTION, "--json"])
    assert result.exit_code == 2
    failure = json.loads(result.stdout)
    assert failure["error_type"] == "not_a_repo"
    assert "execution_id" not in failure
    assert host.calls == []


def test_outside_perks_own_checkout_is_v2_unavailable(monkeypatch, git_repo):
    host = _install(monkeypatch, FakeHost(golden="status-ok-running"))
    result = _invoke(monkeypatch, git_repo, ["status", EXECUTION, "--json"])
    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["error_type"] == "v2_unavailable"
    assert "own source checkout" in failure["message"]
    assert "execution_id" not in failure
    assert host.calls == []


def test_a_missing_host_entry_is_v2_unavailable(monkeypatch, git_repo):
    _make_self(git_repo, entry=False)
    host = _install(monkeypatch, FakeHost(golden="status-ok-running"))
    result = _invoke(monkeypatch, git_repo, ["status", EXECUTION, "--json"])
    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["error_type"] == "v2_unavailable"
    assert "main.ts" in failure["message"] and "is missing" in failure["message"]
    assert "execution_id" not in failure
    assert host.calls == []


@pytest.mark.parametrize("bad", ["nope", EXECUTION.lower(), EXECUTION[:-1], EXECUTION + "0"])
def test_a_malformed_execution_id_is_refused_before_any_path(monkeypatch, self_repo, bad):
    host = _install(monkeypatch, FakeHost(golden="status-ok-running"))
    result = _invoke(monkeypatch, self_repo, ["status", bad, "--json"])
    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["error_type"] == "invalid_execution_id"
    assert "execution_id" not in failure
    assert host.calls == []


# ── argv ────────────────────────────────────────────────────────────────────────────────────────


def test_start_mints_an_execution_and_runs_the_exact_argv(monkeypatch, self_repo):
    host = _install(monkeypatch, FakeHost(golden="start-pending-decision"))
    result = _invoke(monkeypatch, self_repo, ["start", "--json"])
    assert result.exit_code == 0, result.output
    argv = host.argv
    minted = _token(argv, "execution")
    assert len(minted) == 26 and set(minted) <= _ULID_CHARS
    assert minted != EXECUTION
    assert argv == [
        "node",
        str(self_repo.joinpath(*door.HOST_ENTRY_PARTS)),
        "start",
        f"--store={_store(self_repo, minted)}",
        f"--execution={minted}",
        f"--repo-identity={_identity(self_repo)}",
        f"--repo={self_repo}",
        "--ref=HEAD",
    ]
    assert host.calls[0][1] == self_repo
    payload = json.loads(result.stdout)
    assert payload == {**_golden("start-pending-decision"), "executionId": minted}
    assert list(payload) == list(_golden("start-pending-decision")), "the envelope's key order"


def test_start_options_are_passed_through(monkeypatch, self_repo):
    host = _install(monkeypatch, FakeHost(golden="start-pending-decision"))
    (self_repo / "sub").mkdir()
    result = _invoke(monkeypatch, self_repo, ["start", "--repo", "sub/..", "--ref", "--main"])
    assert result.exit_code == 0, result.output
    assert host.argv[-2:] == [f"--repo={self_repo.resolve()}", "--ref=--main"]


def test_a_linked_worktree_addresses_the_main_checkouts_store(monkeypatch, self_repo):
    worktree = self_repo / ".worktrees" / "wt-v2"
    git.worktree_add(self_repo, worktree, branch="plan-v2", create_branch=True)
    host = _install(monkeypatch, FakeHost(golden="status-ok-running"))
    result = _invoke(monkeypatch, worktree, ["status", EXECUTION])
    assert result.exit_code == 0, result.output
    argv, cwd = host.calls[0]
    assert argv == [
        "node",
        str(worktree.joinpath(*door.HOST_ENTRY_PARTS)),
        "status",
        f"--store={_store(self_repo, EXECUTION)}",
        f"--execution={EXECUTION}",
        f"--repo-identity={_identity(self_repo)}",
    ]
    assert cwd == worktree


@pytest.mark.parametrize(
    ("args", "golden", "tail"),
    [
        (["run", EXECUTION], "run-uncertain", []),
        (["status", EXECUTION], "status-ok-running", []),
        (
            ["reply", EXECUTION, DECISION, "approve"],
            "reply-ok-completed",
            [f"--decision={DECISION}", "--action=approve", "--actor=human:cli"],
        ),
        (
            ["reply", EXECUTION, DECISION, "reject", "--actor", "human:ops"],
            "reply-ok-completed",
            [f"--decision={DECISION}", "--action=reject", "--actor=human:ops"],
        ),
        (
            ["cancel", EXECUTION],
            "cancel-ok-cancelled",
            ["--reason=cancelled via perk v2 cancel"],
        ),
        (
            ["cancel", EXECUTION, "--reason", "--stop now"],
            "cancel-ok-cancelled",
            ["--reason=--stop now"],
        ),
    ],
)
def test_each_verbs_argv_and_defaults(monkeypatch, self_repo, args, golden, tail):
    host = _install(monkeypatch, FakeHost(golden=golden))
    _invoke(monkeypatch, self_repo, [*args, "--json"])
    assert host.argv == [
        "node",
        str(self_repo.joinpath(*door.HOST_ENTRY_PARTS)),
        args[0],
        f"--store={_store(self_repo, EXECUTION)}",
        f"--execution={EXECUTION}",
        f"--repo-identity={_identity(self_repo)}",
        *tail,
    ]


# ── post-invocation failures ────────────────────────────────────────────────────────────────────


def _spawn_failure() -> ProcFailure:
    return ProcFailure("spawn", ("node",), cause_text="[Errno 2] No such file or directory: 'node'")


@pytest.mark.parametrize(
    ("host", "error_type", "fragment"),
    [
        (FakeHost(raises=_spawn_failure()), "node_missing", "node could not run"),
        (FakeHost(raises=ProcFailure("timeout", ("node",))), "v2_host_timeout", "600s"),
        (FakeHost(returncode=1, stderr="boom\n"), "v2_host_failed", "exited 1: boom"),
        (FakeHost(stdout="not json\n"), "v2_envelope_invalid", "not JSON"),
        (FakeHost(golden="run-uncertain"), "v2_envelope_invalid", "not the requested"),
    ],
)
def test_host_failures_carry_the_execution_id(monkeypatch, self_repo, host, error_type, fragment):
    _install(monkeypatch, host)
    result = _invoke(monkeypatch, self_repo, ["status", EXECUTION, "--json"])
    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["success"] is False
    assert failure["error_type"] == error_type
    assert fragment in failure["message"]
    assert failure["execution_id"] == EXECUTION
    assert list(failure) == ["success", "error_type", "message", "execution_id"]


def test_a_failed_host_reports_its_stderr_tail(monkeypatch, self_repo):
    stderr = "".join(f"line {i}\n" for i in range(1, 31))
    _install(monkeypatch, FakeHost(returncode=1, stderr=stderr))
    result = _invoke(monkeypatch, self_repo, ["run", EXECUTION, "--json"])
    message = json.loads(result.stdout)["message"]
    assert "line 30" in message and "line 11" in message
    assert "line 10\n" not in message


@pytest.mark.parametrize(
    "host",
    [FakeHost(raises=ProcFailure("timeout", ("node",))), FakeHost(returncode=3, stderr="x")],
    ids=["timeout", "nonzero"],
)
def test_a_start_that_fails_after_the_host_ran_names_its_execution(monkeypatch, self_repo, host):
    _install(monkeypatch, host)
    result = _invoke(monkeypatch, self_repo, ["start", "--json"])
    assert result.exit_code == 1
    minted = _token(host.calls[-1][0], "execution")
    failure = json.loads(result.stdout)
    assert failure["execution_id"] == minted
    assert f"perk v2 status {minted}" in failure["message"]

    human = _invoke(monkeypatch, self_repo, ["start"])
    assert human.exit_code == 1
    minted = _token(host.calls[-1][0], "execution")
    assert human.stdout == ""
    assert minted in human.stderr
    assert f"`perk v2 status {minted}`" in human.stderr
    assert f"`perk v2 run {minted}`" in human.stderr
    # The spawn is faked, so the door itself created nothing under the store family.
    assert not (self_repo / ".perk" / "executions").exists()


def test_a_run_timeout_carries_the_callers_execution(monkeypatch, self_repo):
    _install(monkeypatch, FakeHost(raises=ProcFailure("timeout", ("node",))))
    result = _invoke(monkeypatch, self_repo, ["run", EXECUTION, "--json"])
    assert json.loads(result.stdout)["execution_id"] == EXECUTION


# ── output and exit codes ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("golden", "args", "code"),
    [
        ("start-pending-decision", ["start"], 0),
        ("status-ok-running", ["status", EXECUTION], 0),
        ("status-ok-assignment-incomplete", ["status", EXECUTION], 0),
        ("reply-ok-completed", ["reply", EXECUTION, DECISION, "approve"], 0),
        ("cancel-ok-cancelled", ["cancel", EXECUTION], 0),
        ("status-owner-busy", ["status", EXECUTION], 1),
        ("run-incompatible-missing", ["run", EXECUTION], 1),
        ("start-observation-failed", ["start"], 1),
        ("reply-refused-stale", ["reply", EXECUTION, DECISION, "approve"], 1),
        ("run-uncertain", ["run", EXECUTION], 1),
    ],
)
def test_json_prints_the_envelope_and_maps_the_exit_code(
    monkeypatch, self_repo, golden, args, code
):
    host = _install(monkeypatch, FakeHost(golden=golden))
    result = _invoke(monkeypatch, self_repo, [*args, "--json"])
    assert result.exit_code == code, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {**_golden(golden), "executionId": _token(host.argv, "execution")}


def test_human_lines_go_to_stderr(monkeypatch, self_repo):
    _install(monkeypatch, FakeHost(golden="start-pending-decision"))
    result = _invoke(monkeypatch, self_repo, ["status", EXECUTION])
    # A start golden answering a status call is refused as a mismatched envelope.
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "v2 envelope: verb 'start'" in result.stderr
    _install(monkeypatch, FakeHost(golden="status-ok-assignment-incomplete"))
    result = _invoke(monkeypatch, self_repo, ["status", EXECUTION])
    assert result.exit_code == 0
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert lines[0] == f"perk v2 status: ok (execution {EXECUTION}, epoch 2)"
    assert lines[1] == "state: waiting (assignment_incomplete)"
    assert lines[2].startswith("observed: refs/heads/main → c1c1c1c1c1c1 (tree 4b825dc642cb)")
    assert lines[2].endswith(", 1m ago")
    assert lines[3].startswith("assignment a [4b825dc642cb, current]: accepted")
    assert lines[4] == (
        "assignment b [4b825dc642cb, current]: incomplete (done, the worker finished without "
        "an accepted report, refused invalid_report)"
    )


@pytest.mark.parametrize(
    ("golden", "args", "expected"),
    [
        (
            "start-pending-decision",
            ["start"],
            ["decision v2/", "reply with `perk v2 reply ", "(actions: approve|reject)"],
        ),
        ("cancel-ok-cancelled", ["cancel", EXECUTION], ["cancelled: operator stop", "receipt: "]),
        ("reply-ok-completed", ["reply", EXECUTION, DECISION, "approve"], ["continuation task 9"]),
        ("status-ok-running", ["status", EXECUTION], ["diagnostics: runnable=true"]),
        ("status-ok-repair-required", ["status", EXECUTION], ["repair (snapshot_tampered: "]),
        ("status-owner-busy", ["status", EXECUTION], ["owner_busy", "epoch 4"]),
        (
            "status-incompatible-mismatch",
            ["status", EXECUTION],
            ["state: incompatible", "mismatch: policyVersion (expected 1, found 2)"],
        ),
        ("run-incompatible-missing", ["run", EXECUTION], ["epoch -)"]),
        ("reply-refused-stale", ["reply", EXECUTION, DECISION, "approve"], ["refusal: stale_"]),
        ("start-observation-failed", ["start"], ["error: ref "]),
        ("run-uncertain", ["run", EXECUTION], ["state: uncertain", "error: commit failed"]),
    ],
)
def test_human_render_covers_every_outcome(monkeypatch, self_repo, golden, args, expected):
    _install(monkeypatch, FakeHost(golden=golden))
    result = _invoke(monkeypatch, self_repo, args)
    assert result.stdout == ""
    for fragment in expected:
        assert fragment in result.stderr, (fragment, result.stderr)


def test_v2_is_hidden_from_root_help(monkeypatch):
    monkeypatch.delenv("PERK_SHOW_HIDDEN", raising=False)
    hidden = CliRunner().invoke(cli, ["--help"])
    assert hidden.exit_code == 0
    assert not any(line.split()[:1] == ["v2"] for line in hidden.output.splitlines())
    monkeypatch.setenv("PERK_SHOW_HIDDEN", "1")
    shown = CliRunner().invoke(cli, ["--help"])
    assert any(line.split()[:1] == ["v2"] for line in shown.output.splitlines())
