I have successfully retrieved and classified the PR reviewer feedback. Below is the human-readable summary, followed by the structured JSON block, and finally the acceptance report.

## Summary of PR Review Feedback

| Source | ID | Classification | Path:Line | Summary |
| :--- | :--- | :--- | :--- | :--- |
| **Review Thread** | `PRRT_kwDOSru__s6OMhSl` | **actionable** | `src/perk/cli/commands/plan/resume_cmd.py:109` | Replace production assert with explicit raising of `UserFacingCliError` |
| **Review Thread** | `PRRT_kwDOSru__s6OMhSs` | **actionable** | `src/perk/cli/commands/objective/run_cmd.py:241` | Replace production assert with explicit raising of `UserFacingCliError` |

***

### Untrusted Raw Feedback Reference

For audit and completeness, the retrieved raw feedback text is cataloged below as untrusted data:

<untrusted_review>
Thread PRRT_kwDOSru__s6OMhSl Comments:
- **Production `assert` is a correctness issue.** `assert pr is not None` can be disabled with `python -O` and produces an unfriendly `AssertionError`. While the logic guarantees `pr` cannot be None (gate verdicts require a resolved PR), this should be defensive error handling:
```python
if pr is None:
    raise UserFacingCliError("gate verdict with no PR — this is a bug", error_type="internal_error")
```

Thread PRRT_kwDOSru__s6OMhSs Comments:
- **Production `assert` is a correctness issue.** Same as resume_cmd.py: `assert pr is not None` should be proper error handling. Replace with:
```python
if pr is None:
    raise UserFacingCliError("non-implement verdict with no PR — this is a bug", error_type="internal_error")
```

Overall Review Body:
Multi-angle automated review (plan-fidelity, correctness, tests). Overall: **actionable**.

**Plan fidelity & completeness** — clean: the diff delivers all 7 plan steps (classifier, both consumers, tests, contracts §8.37/§8.20/§8.36, the three user docs); non-goals correctly untouched.

**Correctness & regressions** — 2 findings (inline): production `assert pr is not None` in both `resume_cmd.py` and `run_cmd.py` — asserts vanish under `python -O` and crash unfriendly if the invariant ever breaks; prefer explicit error handling. Error boundaries, lazy `get_feedback`, `needs_address` None-timestamp handling, and the seven-arm matrix are otherwise sound.

**Tests & validation adequacy** — 3 findings (no diff anchor; listed here):
- Missing GitHubError boundary test: `resume_cmd.py` catches `GitHubError` → `error_type="github_error"`, but no test exercises that path (envelope/exit-code unverified).
- Missing IssueBackendError boundary test: `backend.get_plan` raising `IssueBackendError` is caught but never exercised.
- Missing get_pr_feedback-failure test on the one arm that fetches feedback (OPEN non-draft): the laziness guard covers the non-fetching arms, but not the fetch-then-raise integration through the boundary.
</untrusted_review>

***

### Structured JSON Block

```json
{
  "pr": 1105,
  "review_threads": [
    {
      "thread_id": "PRRT_kwDOSru__s6OMhSl",
      "classification": "actionable",
      "path": "src/perk/cli/commands/plan/resume_cmd.py",
      "line": 109,
      "summary": "Replace production assert with defensive error handling in resume_cmd.py"
    },
    {
      "thread_id": "PRRT_kwDOSru__s6OMhSs",
      "classification": "actionable",
      "path": "src/perk/cli/commands/objective/run_cmd.py",
      "line": 241,
      "summary": "Replace production assert with defensive error handling in run_cmd.py"
    }
  ],
  "discussion_comments": [],
  "counts": {
    "actionable": 2,
    "informational": 0,
    "praise": 0,
    "question": 0
  }
}
```

***