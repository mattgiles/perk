"""Shared gh-CLI fake substrate for the `test_github*` suite.

`_Proc`/`_GhRecorder`/`_GhDispatch`/`_has`/`_header`/`ROOT` are the scripted fakes reused by
every `test_github*` split file (auth/workflows/plans/prs/issues, reviews, objectives,
engagement); `FakeGitHubIssues` is the STATEFUL fake (one repository's issues + comments behind
`subprocess.run`) the refinement gate drives the real store/adapter/service over. Leading
underscore so pytest does not collect this module.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from perk import objective, plan


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


# ===========================================================================
# The stateful `gh` fake: one repository's issues + comments behind `subprocess.run`.
#
# `perk.substrate.proc.run_captured` resolves `subprocess.run` at call time, so a global patch
# intercepts `gh` AND `git`: the fake captures the real `subprocess.run` at construction and
# passes every non-`gh` argv through (a gate scaffolding a temp git repo keeps working under the
# patch). Routes mirror the real call shapes the GitHub substrate issues; the body file named by
# `-F body=@…` is read at call time (the `_GhDispatch` pattern).
# ===========================================================================

# GitHub's real HTTP 422 shape for an over-long issue comment (stdout JSON + gh's stderr).
_TOO_LONG_MESSAGE = "Body is too long (maximum is 65536 characters)"


def _too_long_proc() -> _Proc:
    return _Proc(
        1,
        stdout=json.dumps(
            {
                "message": "Validation Failed",
                "errors": [
                    {
                        "resource": "IssueComment",
                        "code": "unprocessable",
                        "field": "data",
                        "message": _TOO_LONG_MESSAGE,
                    }
                ],
            }
        ),
        stderr=f"gh: Validation Failed (HTTP 422)\n{_TOO_LONG_MESSAGE}",
    )


def _not_found_issue_proc(number: int) -> _Proc:
    return _Proc(
        1,
        stdout=json.dumps(
            {"data": {"repository": {"issue": None}}, "errors": [{"type": "NOT_FOUND"}]}
        ),
        stderr=f"Could not resolve to an Issue with the number of {number}.",
    )


# The first minted comment id sits past the signed 32-bit range a GraphQL `Int` can carry: real
# GitHub comment ids already exceed it, which is why the identity is `fullDatabaseId` (`BigInt`).
_FIRST_COMMENT_ID = 2**31 + 1000


class FakeGitHubIssues:
    """A stateful `gh` fake over ONE repository's issues + comments (installed with
    ``monkeypatch.setattr(subprocess, "run", fake)``).

    State: ``issues[number] = {title, body, state, url}``; ``comments[number]`` = ordered rows
    ``{id, body, created_at, edited_at, login, bot}`` where ``id`` is the integer database key
    (the ONE comment identity — REST list ``id`` == GraphQL ``fullDatabaseId`` (a ``BigInt``,
    encoded as a decimal string) == the PATCH path id); ids are minted past the signed 32-bit
    range so every scan exercises the full-width identity. ``page_size`` (default 2) chunks BOTH
    the GraphQL comments connection and the REST ``--paginate`` census so three comments exercise
    both cursor loops. ``comment_max_chars`` is GitHub's 65,536-character issue-comment cap (a
    longer POST/PATCH body is the real 422). ``calls`` records every `gh` argv (sans ``gh``).

    ``faults`` is the additive fault hook: a ``(predicate, proc)`` entry short-circuits routing
    for any matching `gh` argv (e.g. ``(_has("api", "graphql"), _Proc(1, stderr="gh: HTTP 401:
    Bad credentials"))``), consulted AFTER the call is recorded so the transcript still shows
    the attempt. Tests append and clear entries themselves — there is no second dispatch path
    and no sleeping.
    """

    def __init__(self, *, page_size: int = 2, comment_max_chars: int = 65_536) -> None:
        self._real_run = subprocess.run
        self.page_size = page_size
        self.comment_max_chars = comment_max_chars
        self.issues: dict[int, dict[str, object]] = {}
        self.comments: dict[int, list[dict[str, object]]] = {}
        self.calls: list[list[str]] = []
        self.faults: list[tuple[Callable[[list[str]], bool], _Proc]] = []
        self._next_comment_id = _FIRST_COMMENT_ID
        self._clock = 0

    # ------------------------------------------------------------------ seeding

    def add_issue(self, number: int, *, title: str, body: str, state: str = "OPEN") -> None:
        self.issues[number] = {
            "title": title,
            "body": body,
            "state": state,
            "url": f"https://github.com/octo/repo/issues/{number}",
        }
        self.comments.setdefault(number, [])

    def _now(self) -> str:
        self._clock += 1
        return f"2026-03-01T00:{self._clock // 60:02d}:{self._clock % 60:02d}Z"

    def add_comment(
        self, number: int, body: str, *, login: str = "alice", bot: bool = False
    ) -> int:
        if number not in self.issues:
            raise AssertionError(f"no issue #{number} to comment on")
        comment_id = self._next_comment_id
        self._next_comment_id += 1
        self.comments[number].append(
            {
                "id": comment_id,
                "body": body,
                "created_at": self._now(),
                "edited_at": None,
                "login": login,
                "bot": bot,
            }
        )
        return comment_id

    def seed_objective(
        self,
        number: int,
        *,
        run_id: str,
        nodes: list[objective.ObjectiveNode],
        prose: str,
        title: str = "Obj",
        delivery: str | None = None,
        objective_comment_id: bool = True,
    ) -> None:
        """Seed a perk objective issue exactly as ``create_objective_issue`` composes it (steps
        3/5/6): the header + roadmap blocks as the body, the ``objective-body`` comment (callout +
        rendered table + prose) as a perk-authored comment, and the header's
        ``objective_comment_id`` backfilled (``objective_comment_id=False`` leaves it ``null`` —
        the post-succeeded/backfill-failed window)."""
        body_comment = plan.prepend_callout(
            objective.render_body_comment(list(nodes), prose=prose.strip()),
            objective.objective_callout(str(number)),
            command=f"perk objective plan {number}",
        )
        self.add_issue(number, title=title, body="")
        comment_id = self.add_comment(number, body_comment, login="perk-bot", bot=True)
        header = objective.ObjectiveHeader(
            run_id=run_id,
            created=plan.now_iso(),
            objective_comment_id=comment_id if objective_comment_id else None,
            status="active",
            delivery=delivery,
            delivery_lineage="01LINEAGE" if delivery == "stacked" else None,
        )
        header_block = plan.render_metadata_block(
            objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header)
        )
        roadmap_block = plan.render_metadata_block(
            objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(list(nodes))
        )
        self.issues[number]["body"] = f"{header_block}\n\n{roadmap_block}\n"

    # ------------------------------------------------------------------ observation

    def mutations(self, start: int = 0) -> list[str]:
        """Every mutating `gh` argv since ``calls[start]``, rendered as
        ``"POST issues/252/comments"`` / ``"PATCH issues/comments/3"`` / ``"PATCH issues/252"``."""
        out: list[str] = []
        for gh in self.calls[start:]:
            if "-X" not in gh:
                continue
            method = gh[gh.index("-X") + 1]
            if method not in ("POST", "PATCH"):
                continue
            path = gh[1].removeprefix("repos/{owner}/{repo}/")
            out.append(f"{method} {path}")
        return out

    def graphql_calls(self, start: int = 0) -> list[list[str]]:
        return [gh for gh in self.calls[start:] if gh[:2] == ["api", "graphql"]]

    def comment_by_id(self, comment_id: int) -> dict[str, object] | None:
        for rows in self.comments.values():
            for row in rows:
                if row["id"] == comment_id:
                    return row
        return None

    # ------------------------------------------------------------------ dispatch

    def __call__(self, args, **kwargs):
        if not args or args[0] != "gh":
            return self._real_run(args, **kwargs)
        gh = list(args[1:])
        self.calls.append(gh)
        return self._dispatch(gh)

    @staticmethod
    def _flag(gh: list[str], flag: str) -> list[str]:
        """Every value following ``flag`` (``-f``/``-F`` may repeat)."""
        return [gh[i + 1] for i, tok in enumerate(gh[:-1]) if tok == flag]

    @staticmethod
    def _field(gh: list[str], name: str) -> str | None:
        prefix = f"{name}="
        for flag in ("-f", "-F"):
            for value in FakeGitHubIssues._flag(gh, flag):
                if value.startswith(prefix):
                    return value[len(prefix) :]
        return None

    def _body_arg(self, gh: list[str]) -> str | None:
        raw = self._field(gh, "body")
        if raw is None:
            return None
        if raw.startswith("@"):
            return Path(raw[1:]).read_text(encoding="utf-8")
        return raw

    @staticmethod
    def _method(gh: list[str]) -> str:
        return gh[gh.index("-X") + 1] if "-X" in gh else "GET"

    def _dispatch(self, gh: list[str]) -> _Proc:
        for predicate, proc in self.faults:
            if predicate(gh):
                return proc
        if gh[:3] == ["repo", "view", "--json"]:
            return _Proc(0, "octo/repo\n")
        if gh[:2] == ["issue", "view"]:
            return self._issue_view(gh)
        if gh[:2] == ["api", "graphql"]:
            return self._graphql(gh)
        if gh[:1] == ["api"]:
            return self._rest(gh)
        return _Proc(1, stderr="unhandled: " + " ".join(gh))

    def _issue_view(self, gh: list[str]) -> _Proc:
        number = int(gh[2])
        issue = self.issues.get(number)
        if issue is None:
            return _Proc(
                1, stderr=f"GraphQL: Could not resolve to an Issue with the number of {number}."
            )
        fields = gh[gh.index("--json") + 1].split(",")
        payload: dict[str, object] = {}
        for field in fields:
            if field == "number":
                payload["number"] = number
            elif field == "comments":
                payload["comments"] = [{"body": c["body"]} for c in self.comments[number]]
            else:
                payload[field] = issue[field]
        return _Proc(0, json.dumps(payload))

    def _graphql(self, gh: list[str]) -> _Proc:
        query = next(v for v in self._flag(gh, "-f") if v.startswith("query="))
        number = int(self._field(gh, "number") or "0")
        cursor = self._field(gh, "cursor")
        if number not in self.issues:
            return _not_found_issue_proc(number)
        if "comments(first" in query:
            rows = self.comments[number]
            start = int(cursor.removeprefix("CUR")) if cursor else 0
            page = rows[start : start + self.page_size]
            has_next = start + self.page_size < len(rows)
            nodes = [
                {
                    "fullDatabaseId": str(c["id"]),  # BigInt: a decimal string on the wire
                    "body": c["body"],
                    "createdAt": c["created_at"],
                    "lastEditedAt": c["edited_at"],
                    "author": {
                        "login": c["login"],
                        "__typename": "Bot" if c["bot"] else "User",
                        "databaseId": 900 if c["bot"] else 100,
                    },
                }
                for c in page
            ]
            connection = {
                "nodes": nodes,
                "pageInfo": {
                    "hasNextPage": has_next,
                    "endCursor": f"CUR{start + self.page_size}" if has_next else None,
                },
            }
            return _Proc(
                0, json.dumps({"data": {"repository": {"issue": {"comments": connection}}}})
            )
        if "userContentEdits(first" in query:
            connection = {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}
            return _Proc(
                0,
                json.dumps({"data": {"repository": {"issue": {"userContentEdits": connection}}}}),
            )
        return _Proc(1, stderr="unhandled graphql: " + query[:80])

    def _rest(self, gh: list[str]) -> _Proc:
        path = gh[1].removeprefix("repos/{owner}/{repo}/")
        method = self._method(gh)
        jq = gh[gh.index("--jq") + 1] if "--jq" in gh else None
        parts = path.split("/")
        # issues/<n>/comments
        if len(parts) == 3 and parts[0] == "issues" and parts[2] == "comments":
            number = int(parts[1])
            if number not in self.issues:
                return _Proc(1, stderr="gh: Not Found (HTTP 404)")
            if method == "POST":
                body = self._body_arg(gh)
                if body is None:
                    return _Proc(1, stderr="unhandled: comment POST without body")
                if len(body) > self.comment_max_chars:
                    return _too_long_proc()
                comment_id = self.add_comment(number, body, login="perk-bot", bot=True)
                return _Proc(0, json.dumps({"id": comment_id}))
            rows = [{"id": c["id"], "body": c["body"]} for c in self.comments[number]]
            if "--paginate" in gh and "--slurp" in gh:
                pages = [
                    rows[i : i + self.page_size] for i in range(0, len(rows), self.page_size)
                ] or [[]]
                return _Proc(0, json.dumps(pages))
            return _Proc(0, json.dumps(rows))
        # issues/comments/<id>
        if len(parts) == 3 and parts[0] == "issues" and parts[1] == "comments":
            comment = self.comment_by_id(int(parts[2]))
            if comment is None:
                return _Proc(1, stderr="gh: Not Found (HTTP 404)")
            if method == "PATCH":
                body = self._body_arg(gh)
                if body is None:
                    return _Proc(1, stderr="unhandled: comment PATCH without body")
                if len(body) > self.comment_max_chars:
                    return _too_long_proc()
                comment["body"] = body
                comment["edited_at"] = self._now()
                return _Proc(0, "{}")
            if jq == ".body":
                return _Proc(0, str(comment["body"]))
            return _Proc(0, json.dumps({"id": comment["id"], "body": comment["body"]}))
        # issues/<n>
        if len(parts) == 2 and parts[0] == "issues":
            number = int(parts[1])
            issue = self.issues.get(number)
            if issue is None:
                return _Proc(1, stderr="gh: Not Found (HTTP 404)")
            if method == "PATCH":
                body = self._body_arg(gh)
                if body is not None:
                    issue["body"] = body
                title = self._field(gh, "title")
                if title is not None:
                    issue["title"] = title
                state = self._field(gh, "state")
                if state is not None:
                    issue["state"] = state.upper()
                return _Proc(0, "{}")
            if jq == ".body":
                return _Proc(0, str(issue["body"]))
            return _Proc(
                0,
                json.dumps(
                    {
                        "number": number,
                        "title": issue["title"],
                        "body": issue["body"],
                        "state": str(issue["state"]).lower(),
                        "html_url": issue["url"],
                    }
                ),
            )
        return _Proc(1, stderr="unhandled: " + " ".join(gh))
