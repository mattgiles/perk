Perfect! All tests pass. Now let me complete my review with structured findings.

---

## Test Coverage Review — **tests** angle

I've reviewed test coverage and validation adequacy for the new next-action resolution behavior. Here's what I found:

### ✅ **Strong Coverage Areas**

The implementation has **excellent coverage** of the core happy paths:

1. **Seven-verdict matrix** — `test_resolve_next_action_matrix` comprehensively parametrizes all 7 verdicts (IMPLEMENT, ADDRESS, LEARN, READY_FOR_REVIEW, AWAITING_REVIEW, PR_CLOSED, DONE) including the §8.36 merged-arm variants (learn_state header vs marker fallback)

2. **Laziness guard** — `_boom_feedback` stub properly verifies feedback is **never fetched** except on the OPEN-non-draft arm (offline-testable constraint)

3. **Gate arms never launch** — All three gate verdicts (draft→ready_for_review, clean→awaiting_review, closed→pr_closed) tested with `_gate_case` helper that asserts launching is forbidden + no ref written

4. **Parity guarantee** — `tests/test_next_action_parity.py` validates both `plan resume --dry-run` and `objective run --dry-run` report the **same** `next_action` for all 7 states (the node's acceptance criterion made executable)

5. **needs_address coverage** — Unresolved threads, latest-review-per-author logic (CHANGES_REQUESTED superseded by APPROVED), discussion-comments-ignored

6. **All verdicts exercised via CLI** — Each of the 7 verdicts has at least one CLI integration test in both resume and objective run suites

### ⚠️ **Actionable Gaps (error boundaries)**

Three **error-handling paths are untested** despite explicit exception handlers in the code:

<untrusted_diff>
In `src/perk/cli/commands/plan/resume_cmd.py` lines 88-95:
```python
except (IssueBackendError, GitHubError) as exc:
    _fail(ctx, as_json=as_json, error_type="github_error", message=f"resume failed\n{exc}")
    return
```
</untrusted_diff>

**Missing:**

1. **GitHubError boundary** — No test exercises the path where `github.get_pr_feedback` or `github.check_auth` raises `GitHubError`; the error envelope/exit-code/message could be malformed

2. **IssueBackendError boundary** — No test exercises `backend.get_plan` raising `IssueBackendError`; same risk

3. **get_pr_feedback failure on OPEN-non-draft arm** — The laziness guard verifies feedback is never fetched on non-applicable arms, but the **failure path when it IS fetched** (OPEN non-draft) is not tested

These are real risks: the error-handling code exists but is never executed by tests.

### 📌 **Moderate Gap (verdict coverage)**

**PR_CLOSED in objective run** — The verdict is handled in `run_cmd.py` (line mapped to `action="pr_closed"` + render message) but `tests/test_objective_run_cmd.py` has no explicit test for this arm. The parity suite covers it, but the individual objective-run suite doesn't.

### 🔍 **Minor Gaps (edge cases within tested functions)**

- **None submitted_at** — `needs_address` coerces `None` to `""` for comparison but no test explicitly exercises reviews with `None` submitted_at
- **Multi-author edge case** — No test for alice's latest=APPROVED + bob's latest=CHANGES_REQUESTED → should return True (only same-author supersession is tested)

These are genuinely minor — the core logic is tested; these are edge cases that would be nice-to-have.

---

## Verdict: **`actionable`**

The **error boundaries are untested** — a binary "the author should act before landing" issue. While the happy paths have excellent coverage (seven verdicts, parity guarantee, laziness guard), the error-handling code could be completely broken and tests wouldn't catch it. Error payloads, exit codes, and messages are all at risk.

**Recommendation:** Add 3 tests to `tests/test_resume.py`:
1. `test_backend_error_exits_1` — monkeypatch `plans.get_plan` to raise `IssueBackendError`, assert exit 1 + `error_type="github_error"` in JSON
2. `test_github_error_exits_1` — monkeypatch `github.get_pr_feedback` to raise `GitHubError`, assert same
3. Optionally: `test_pr_closed_in_objective_run` in `test_objective_run_cmd.py` for completeness (moderate priority)

---

```json
{
  "angle": "tests",
  "verdict": "actionable",
  "findings": [
    {
      "path": "tests/test_resume.py",
      "line": null,
      "body": "**Missing: GitHubError boundary test.** `resume_cmd.py` lines 88-95 catch `GitHubError` and render it as `error_type=\"github_error\"`, but no test exercises this path. If `github.get_pr_feedback()` or `github.check_auth()` raises `GitHubError`, the error envelope/exit-code/message could be malformed and tests wouldn't catch it. Add a test that monkeypatches one of these calls to raise `GitHubError` and asserts exit 1 + correct JSON payload."
    },
    {
      "path": "tests/test_resume.py",
      "line": null,
      "body": "**Missing: IssueBackendError boundary test.** Same handler catches `IssueBackendError` (line 88) but no test exercises `backend.get_plan()` raising it. Add a test that monkeypatches `plans.get_plan` to raise `IssueBackendError` and asserts the error is properly caught and rendered."
    },
    {
      "path": "tests/test_resume.py",
      "line": null,
      "body": "**Missing: get_pr_feedback failure on OPEN non-draft arm.** The laziness guard (`_boom_feedback`) verifies feedback is never fetched on non-applicable arms, but the **failure path when feedback IS fetched** (OPEN non-draft PR) is not tested. When `get_pr_feedback` raises `GitHubError` on the one arm that calls it, the exception should be caught by the boundary handler — but this integration isn't verified."
    }
  ],
  "fyi": [
    "Minor: No explicit test for `None` submitted_at in needs_address (line 53-56 handles it but not exercised)",
    "Minor: No test for multi-author review edge case (alice approved, bob requested changes → should return True)",
    "Moderate: PR_CLOSED verdict not explicitly tested in test_objective_run_cmd.py (covered by parity suite only)"
  ]
}
```