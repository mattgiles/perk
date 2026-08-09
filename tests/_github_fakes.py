"""Shared gh-CLI fake substrate for the `test_github*` suite.

`_Proc`/`_GhRecorder`/`_GhDispatch`/`_has`/`_header`/`ROOT` are reused by every
`test_github*` split file (auth/workflows/plans/prs/issues, reviews, objectives,
engagement). Leading underscore so pytest does not collect this module.
"""

from pathlib import Path

from perk import plan


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


ROOT = Path("/repo")


class _GhRecorder:
    """Records `gh` argv and returns a configured `_Proc` per HTTP method."""

    def __init__(self, *, get: _Proc | None = None, post: _Proc | None = None) -> None:
        self._get = get or _Proc(0, "[]")
        self._post = post or _Proc(0, "{}")
        self.calls: list[list[str]] = []
        self.body_files: list[str] = []  # body content read from `-F body=@<path>` at call time

    def __call__(self, args, **_):
        gh_args = args[1:]  # drop "gh"
        self.calls.append(gh_args)
        for tok in gh_args:
            if tok.startswith("body=@"):
                self.body_files.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
        is_post = "POST" in gh_args
        return self._post if is_post else self._get

    def posted(self) -> bool:
        return any("POST" in c for c in self.calls)


def _header(run_id: str) -> str:
    return plan.render_metadata_block(
        plan.PLAN_HEADER_KEY,
        plan.render_plan_header_fields(plan.PlanHeader(run_id=run_id, created="t")),
    )


class _GhDispatch:
    """Route `gh` argv to a `_Proc` via (predicate, proc) handlers; record calls + body files."""

    def __init__(self, handlers) -> None:
        self.handlers = handlers
        self.calls: list[list[str]] = []
        self.body_files: list[str] = []

    def __call__(self, args, **_):
        gh = args[1:]
        self.calls.append(gh)
        for tok in gh:
            if tok.startswith("body=@"):
                self.body_files.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
        for pred, proc in self.handlers:
            if pred(gh):
                return proc
        return _Proc(1, stderr="unhandled: " + " ".join(gh))

    def method_calls(self, method: str) -> int:
        return sum(1 for c in self.calls if method in c)


def _has(*tokens):
    # substring match per token (gh endpoints are like "repos/{owner}/{repo}/pulls").
    return lambda gh: all(any(t in tok for tok in gh) for t in tokens)
