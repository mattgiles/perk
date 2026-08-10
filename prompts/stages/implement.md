You are implementing perk plan {{ provider }} #{{ pr_id }} ({{ url }}) on this branch.

First, read the full plan:
    {{ read_cmd }}

Then implement it here. Work in focused steps and keep the tree committable. When the implementation is complete and committed, open the pull request with the /submit command.

Validation: verify as you work — while iterating, prefer narrow, targeted checks: run the relevant configured check(s) by name with the `run_ci` tool, or a direct command such as a single test file (if the repo has no configured checks, use the project's own test/typecheck commands instead). Reserve the full `run_ci` (no arguments) for the end, immediately before submitting: when it reports the full gate green, the implementation is verified — commit and go straight to /submit; do not re-run checks or underlying commands to double-check a green run-all.

Progress tracking: keep a live checklist with the `todo` tool. Seed it from the plan's `## Steps` numbered list before you start — one item per step, in order; for a prose plan (no `## Steps`) derive a short checklist from the plan body yourself. The checklist is yours to keep honest: mark items in progress/complete as you work, and split or add items if the work reveals more — it must always reflect where the implementation actually stands.