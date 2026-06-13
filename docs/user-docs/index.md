# perk user docs

This tree is the documentation for the **operator** — someone using perk on their own
repository. It is never for perk contributors: perk's internal research and planning record
lives in [`docs/planning/`](../planning/), [`docs/guiding-principles/`](../guiding-principles/),
and [`shared/contracts.md`](../../shared/contracts.md), and is never duplicated here.

## How this tree is organized

The tree follows the [Divio documentation system](https://docs.divio.com/documentation-system/):
documentation is not one thing but **four distinct kinds**, each answering a different reader
need — learning, achieving a goal, looking something up, and understanding. Mixing them is the
system's named failure mode ("the tendency to collapse"): a tutorial that digresses into
rationale stops being learnable; a reference that instructs stops being trustworthy. Each kind
gets its own directory, and every page belongs to exactly one.

| Quadrant | Directory | Read this when … |
|---|---|---|
| [Tutorials](./tutorials/index.md) | `tutorials/` | you are learning perk for the first time and want a guided, completable lesson |
| [How-to guides](./how-to/index.md) | `how-to/` | you know what you want to accomplish and need the steps to do it |
| [Reference](./reference/index.md) | `reference/` | you need to look up how something works — a command, a tool, a config key |
| [Explanation](./explanation/index.md) | `explanation/` | you want to understand why perk is shaped the way it is |

New to perk? Start with [Get started with perk](./tutorials/get-started.md).
