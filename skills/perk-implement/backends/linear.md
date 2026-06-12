# Reading the plan — Linear issue backend

The saved plan is a Linear issue; the plan body is posted as the **first comment**. Read it with
the pi-mono-linear tools:

1. `linear_get_issue` — `issueId` accepts the identifier from the launch prompt
   (`You are implementing perk plan linear #ENG-123`) or the issue UUID.
2. `linear_list_comments` with the same `issueId` — the plan body is the first comment.

**Fallback:** if the `linear_*` tools are unavailable in this session, open the plan URL from the
launch prompt instead.

**PRs are unaffected by the issue backend.** `/submit` and all `gh pr` work (the pull request, CI,
review) stay on GitHub regardless — only the plan *issue* lives in Linear.
