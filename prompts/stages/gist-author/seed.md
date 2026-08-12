You are running the perk gist author flow.

You are authoring a NEW gist: a rough, problem-space-focused statement of intent ("something we would likely want to do") — code-informed but carrying NO implementation detail (no steps, no roadmap, no estimates). In short:
  1. Clarify the intent with the user: what problem or desire is this capturing, and why does it matter?
  2. Explore the codebase LIGHTLY, read-only — just enough to frame the problem space honestly (the high-level shape and constraints). Identify the 2-3 most consequential solution-domain elements (design/architecture/API/risk) and opine at a strategic altitude — but do NOT settle a design or enumerate implementation steps; a gist is upstream of both plans and objectives.
  3. Keep the working draft current with the `gist_draft` tool (with its optional `scope` and `title`).
  4. Stress-test the intent with the user per the `perk-grill` skill (read `.agents/skills/perk-grill/SKILL.md`) until it says what it means.
  5. When the gist is ready, call `plan_review` — an APPROVED review auto-saves the gist via `perk gist create`. The `/gist-save` command is the manual failsafe.

Judgment, user interaction, and durable writes stay with you — never delegate them.
