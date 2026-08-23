---
title: "In-session commands & tools"
description: "A stable map of perk's warm slash commands, model-facing tools, workflow families, and ancillary session features."
sidebar:
  order: 3020
---

# In-session commands & tools

This page is the orientation hub for perk's **in-session surface**: the warm `/…` commands you
type inside a running Pi session and the model-facing **tools** the agent calls on your behalf.
It is the interior counterpart to [CLI commands](./cli.md), the session exterior where you run
`perk …` commands in your shell.

## Orientation

A **warm command** is a human gesture inside an existing session. A **model-facing tool** is a
typed operation the agent can call when the current stage and read-only gate allow it. Warm-door
availability, standalone slash-command registration, cold-local launch, and cold-remote
eligibility are separate facts; [Stages and doors](./in-session/stages-and-doors.mdx) defines them
and provides the complete registry matrix.

Use these family references for exact behavior:

- [Stages and doors](./in-session/stages-and-doors.mdx) — modes and warm, cold-local, and
  cold-remote availability.
- [Workflow commands](./in-session/workflow-commands.md) — the spine, objectives, gists,
  factories, CI, and session utilities.
- [Review and authoring](./in-session/review-and-authoring.md) — automated review and the
  terminal/browser human-review doors.
- [Model-facing tools](./in-session/model-tools.md) — the complete perk-owned, borrowed, and
  child-only tool censuses plus gating and stage scoping.

For the conceptual model behind stages, doors, the two planes, and state tiers, read
[How perk thinks](../explanation/how-perk-thinks.md).

### Surface map

The map below lists every default perk-registered slash command exactly once. Commands are grouped
by the family that explains them rather than by whichever stage happens to expose them.

<!-- BEGIN perk command census -->
| Family | Commands | Detailed reference |
| --- | --- | --- |
| Workflow spine | `/plan`, `/plan-save`, `/implement-here`, `/implement`, `/submit`, `/ready`, `/address`, `/land`, `/learn` | [Workflow commands](./in-session/workflow-commands.md#warm-commands-by-stage-the-spine) |
| Objectives | `/objective`, `/objective-plan`, `/objective-reconcile`, `/objective-save`, `/objective-stack`, `/objective-sync`, `/objective-recover`, `/objective-land` | [Workflow commands](./in-session/workflow-commands.md#objective-doors-warm) |
| Gists | `/gist-save` | [Workflow commands](./in-session/workflow-commands.md#gist-doors-warm) |
| Utility and factories | `/ci`, `/commit-and-compact`, `/perk-selfcheck`, `/learn-docs`, `/learn-code` | [Workflow commands](./in-session/workflow-commands.md#utility-commands--factories) |
| Review and authoring | `/pr-review`, `/pr-review-dynamic`, `/pr-review-terminal`, `/pr-review-browser`, `/stack-review-browser`, `/plan-review-browser`, `/objective-review-browser` | [Review and authoring](./in-session/review-and-authoring.md) |
| Ancillary human-only | `/btw` | [Ancillary in-session features](#ancillary-in-session-features) |
<!-- END perk command census -->

## Utility commands & tools

The in-session utility surface spans three families:

- [Workflow commands](./in-session/workflow-commands.md#utility-commands--factories) covers
  `/ci`, `/commit-and-compact`, `/perk-selfcheck`, `/learn-docs`, and `/learn-code`.
- [Review and authoring](./in-session/review-and-authoring.md) covers the six code-review and
  draft-review commands and their companion tools.
- [Model-facing tools](./in-session/model-tools.md) is the guarded index of every tool name,
  including read-only and stage-scoping behavior.

## Ancillary in-session features

Five small first-party features ride along inside the perk extension. None is a workflow stage,
door, or model tool; they are human-facing only.

- **The perk footer** — the one-line footer perk owns in the interactive TUI (it supersedes Pi's
  default footer wholesale): perk identity · 🎯 objective on the left; branch · model · thinking ·
  **cache-hit rate** · context · guest-extension statuses right-aligned. The cache segment
  (`CH42.3%`) restores Pi's default-footer `CH` prompt-cache-hit display and stays absent until the
  session shows cache activity. For per-miss detail, enable Pi's `showCacheMissNotices` setting
  **per-user** via `/settings` (user scope) — an operator diagnostic perk deliberately never
  converges into managed repo settings. Transition misses (stage flips and skill-binding
  deliveries) are expected and bounded; idle-gap misses caused by the provider's cache TTL are not
  perk's doing.
- **`/btw`** — a side-chat popover: a separate in-memory conversation seeded with your main
  conversation context, so it can answer without polluting the main thread. `/btw <text>` asks
  immediately; bare `/btw` opens the thread or offers to continue/start fresh. Closing the popover
  offers to inject a summary into the main chat. Its tools follow perk's read-only mode — read-only
  sessions get `read` only and read-write sessions get the full tool set — so it cannot escape the
  structural gate. It is TUI-only and exposes no model tool.
- **`whimsical`** — replaces Pi's default “Working…” label with a random whimsical phrase each
  turn. It is ambient and cosmetic, with no command or config toggle.
- **The watch feedback receiver** — in an eligible implement session, saved notes from a live
  [`perk plan watch`](./cli/plan.md#perk-plan-watch-plan) review arrive as user messages (see
  [How to send feedback from a hunk watch](../how-to/send-feedback-from-hunk-watch.md)). Only the
  interactive TUI implement session whose active plan matches the worktree consumes feedback;
  headless/RPC sessions and other stages do not. Mid-turn notes steer the running turn; idle notes
  start a new turn. Delivery is acknowledged only after the message appears on the transcript and
  is at-least-once. A single-consumer lease leaves a second matching session passive. Failures are
  reported locally rather than injected into the model conversation.
- **Transcript markers** — workflow moments such as run claims, read-only/read-write flips,
  objective activation and budget start, node claims, and `/btw` exchanges render as durable
  one-line markers in the interactive transcript. They are display-only, TUI-only, and require
  Pi ≥ 0.80.4; older hosts silently omit them.

## Related

- **Look up:** [CLI commands](cli.md) — the exterior command surface that launches these sessions.
- **Do:** [How to drive a change through the full spine](../how-to/drive-the-full-spine.md) — the warm commands in one worked sequence.
- **Understand:** [Human gates and trust](../explanation/human-gates-and-trust.md) — why some tools are gated on a human decision.
