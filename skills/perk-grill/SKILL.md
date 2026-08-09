---
name: perk-grill
description: Grill the user relentlessly about a plan or design — a one-question-at-a-time interview that stress-tests every decision before building. Use when stress-testing a plan, design, or objective before requesting review or implementing, or when the user says "grill me" or uses any other 'grill' trigger phrase.
stages: [plan, objective-plan, objective-author]
---

# Grilling (the relentless pre-review interview)

Interview the user relentlessly until you reach a shared understanding. Map this as a **design
tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already
settled — the questions you can ask now without guessing at answers you haven't heard yet. Ask
the whole frontier in one round: number each question and give your recommended answer. Then
wait for the user's answers before the next round.

Use the `ask_user_question` tool and thoughtfully include your recommendation.

Each round the user answers reshapes the tree — settled decisions push the frontier outward
and unblock questions that depended on them. Recompute the frontier and ask the next round. A
question whose answer depends on another question still open in this round belongs to a later
round, not this one.

Finding facts is your job, never the user's. When a frontier question needs a fact from the
environment (filesystem, tools, etc.), dispatch a sub-agent to find it — don't ask the user
for anything you could look up yourself. Don't block on it: a running exploration is an
unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report
— ask the rest of the frontier now. The decisions are the user's — put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited,
nothing left silently assumed. Do not act on it until the user confirms you have reached a
shared understanding.

## Keep the domain model current

As decisions crystallize, keep the project's domain model current by following the
`perk-domain-modeling` skill (read `.agents/skills/perk-domain-modeling/SKILL.md`) — challenge
terms against the glossary, sharpen fuzzy language, and record glossary terms and ADR-worthy
decisions as they resolve, honoring that skill's read-only-session mode (in a read-only session,
record them in the plan/objective draft rather than writing files).
