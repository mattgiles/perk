Commit the work completed so far — perk will compact this session once your commit is in.

1. Review the working tree (`git status`, `git diff`) and stage exactly the changes that belong to the completed work (`git add <paths>` — avoid a blanket `git add -A` when scratch or unrelated files are present).
2. Commit with a descriptive message that captures what is done and (when useful) what remains. Use one commit, or a few focused commits if the work is genuinely separable. Do NOT push.
3. If nothing belongs in a commit, say so and stop — perk will then skip compaction.

When the run settles with a new commit, perk compacts the session automatically; the compaction summary will reference your commit(s).
