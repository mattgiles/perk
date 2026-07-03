Perfect! No staged files. Now let me generate my review report.

## Correctness Review Summary

I've completed a thorough correctness review of this PR focusing on security, edge cases, error paths, and changed call contracts.

<untrusted_diff>
The diff introduces:
- **Deleted `resolve_resume_stage`** → replaced with `resolve_next_action` returning a `NextAction` enum
- **Moved `needs_address`** from `run_cmd.py` to `resume.py` 
- **New gate arms** for draft PRs, awaiting review, and closed PRs that report instead of launching
- **New payload shapes** with `next_action` field across both surfaces
</untrusted_diff>

### Findings

**BLOCKER (1 finding):**

| File | Line | Issue |
|------|------|-------|
| `src/perk/cli/commands/plan/resume_cmd.py` | 109 | Production `assert pr is not None` statement. While the logic guarantees `pr` cannot be None at this point, using `assert` in production code is dangerous: (1) asserts can be disabled with `python -O`, (2) if logic changes this becomes a silent crash, (3) `AssertionError` is not user-friendly. Should be replaced with a proper error check that raises a user-facing error. |
| `src/perk/cli/commands/objective/run_cmd.py` | 241 | Same issue: production `assert pr is not None`. Same rationale as above - should be proper error handling, not an assert. |

**Otherwise the implementation is sound:**
- ✓ Error handling for `GitHubError` is correct - caught at appropriate boundaries in both `resume_cmd.py` and `run_cmd.py`
- ✓ Lazy evaluation of `get_feedback` callback is correct - only called on OPEN non-draft arm after all None checks
- ✓ NULL handling in `needs_address` timestamp comparison is correct (`submitted_at or ""` properly sorts None as oldest)
- ✓ The seven-arm classification matrix is logically complete and correct
- ✓ All contract changes are properly documented
- ✓ Test coverage is comprehensive including the new parity test

```json
{
  "angle": "correctness",
  "verdict": "actionable",
  "findings": [
    {
      "path": "src/perk/cli/commands/plan/resume_cmd.py",
      "line": 109,
      "body": "**Production `assert` is a correctness issue.** `assert pr is not None` can be disabled with `python -O` and produces an unfriendly `AssertionError`. While the logic guarantees `pr` cannot be None (gate verdicts require a resolved PR), this should be defensive error handling:\n```python\nif pr is None:\n    raise UserFacingCliError(\"gate verdict with no PR — this is a bug\", error_type=\"internal_error\")\n```"
    },
    {
      "path": "src/perk/cli/commands/objective/run_cmd.py",
      "line": 241,
      "body": "**Production `assert` is a correctness issue.** Same as resume_cmd.py: `assert pr is not None` should be proper error handling. Replace with:\n```python\nif pr is None:\n    raise UserFacingCliError(\"non-implement verdict with no PR — this is a bug\", error_type=\"internal_error\")\n```"
    }
  ],
  "fyi": [
    "String literal comparison `stage_id in (\"implement\", \"address\")` at run_cmd.py:229 could be more type-safe using verdict enum comparison instead, but functionally correct.",
    "Unknown PR states treated as OPEN (fallthrough in resolve_next_action) is a reasonable design choice for forward compatibility."
  ]
}
```