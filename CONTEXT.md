# perk

The plan-oriented agent workflow: a Python CLI (the session exterior) and a Pi extension (the
session interior) drive written, reviewed, durable plans through a staged spine.

## Language

**Gist**:
A rough, problem-space-focused statement of intent ("something we would likely want to do")
tracked in the issue backend — upstream of both plans and objectives, carrying no implementation
detail.
_Avoid_: idea, note, ticket, seed

**Scope** (of a gist):
A gist's intended consumption tier — `plan` (a bounded, single-plan-sized intent) or `objective`
(a long-running, multi-plan-sized goal). A routing hint for the adoption doors: a storage
discriminator on Linear (objective scope stores the gist as a project), a header hint elsewhere.
_Avoid_: kind, type, size
