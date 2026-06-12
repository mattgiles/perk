# Reading the saved plan — Linear issue backend

The saved plan is a Linear issue; the plan body is posted as the **first comment**. Read it with
the pi-mono-linear tools:

1. `linear_get_issue` — `issueId` accepts the plan-ref UUID or an identifier like `ENG-123`.
2. `linear_list_comments` with the same `issueId` — the plan body is the first comment.

**Fallback:** if the `linear_*` tools are unavailable in this session, open the plan URL instead.

**The merged-PR side stays `gh`.** PRs are GitHub-universal under every issue backend — derive the
merged PR with `gh pr list --head plan-<pr_id> --state merged` exactly as the main skill body says.
