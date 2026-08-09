---
name: perk-grill
description: Grill the user relentlessly about a plan or design — a one-question-at-a-time interview that stress-tests every decision before building. Use when stress-testing a plan, design, or objective before requesting review or implementing, or when the user says "grill me" or uses any other 'grill' trigger phrase.
stages: [plan, objective-plan, objective-author]
---

# Grilling (the relentless pre-review interview)

*Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) (MIT).*

Interview the user relentlessly about every aspect of the plan until you reach a shared
understanding. Walk down each branch of the design tree, resolving dependencies between decisions
one-by-one. For each question, provide your recommended answer.

Ask the questions **one at a time**, waiting for feedback on each question before continuing.
Asking multiple questions at once is bewildering. When the `ask_user_question` tool is available,
ask through it — one focused question per call, with your recommended answer as the first option.

If a **fact** can be found by exploring the codebase, look it up rather than asking. The
**decisions**, though, are the user's — put each one to them and wait for their answer.

Do not proceed to review or save until the user confirms you have reached a shared understanding.

## Keep the domain model current

As decisions crystallize, keep the project's domain model current by following the
`perk-domain-modeling` skill (read `.agents/skills/perk-domain-modeling/SKILL.md`) — challenge
terms against the glossary, sharpen fuzzy language, and record glossary terms and escalation-worthy
decisions as they resolve, honoring that skill's read-only-session mode (in a read-only session,
record them in the plan/objective draft rather than writing files).
