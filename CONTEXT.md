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

### Objective delivery

**Incremental delivery**:
The default objective delivery policy in which each plan integrates independently when it is
ready.
_Avoid_: serial delivery, ordinary delivery

**Stacked delivery**:
An objective delivery policy in which plans remain separate review units but integrate together at
the objective boundary.
_Avoid_: stack mode, chained delivery

**Delivery train**:
The ordered set of layers belonging to one stacked-delivery lineage, including across objective
replans.
_Avoid_: stack, branch chain

**Layer** (of a delivery train):
The delivery unit formed by one non-skipped roadmap node and its plan.
_Avoid_: commit, phase, arbitrary pull request

**Published prefix**:
The contiguous initial portion of a delivery train whose layers have established review artifacts.
_Avoid_: open plans, published set

**Delivery lineage**:
The stable identity of a delivery train across superseding objectives.
_Avoid_: objective lineage, stack number

**Dynamic singleton**:
A delivery train reduced by later cancellation to one remaining layer after having been validly
authored with multiple layers.
_Avoid_: one-node stacked objective, standalone plan
