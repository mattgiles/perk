---
title: "perk in Zed: the two native paths today"
description: "The two native ways to use perk from Zed today, what each gives you, and the limitation the two share."
sidebar:
  order: 4030
---

# perk in Zed: the two native paths today

Zed's Agent Panel hosts outside agents in two distinct ways. **Terminal Threads** run an agent's
native CLI/TUI in a terminal that Zed organizes as a thread; **External Agents** integrate over
ACP and render as Zed-native agent threads. perk ships no ACP adapter today, so there are exactly
two ways to use perk from Zed right now — one down each of those roads — and this page explains
what each gives you, what each costs, and the limitation the two share. It leans on the vocabulary
from [How perk thinks](./how-perk-thinks.md) — the two planes, the stage spine, the warm and cold
doors — so read that first if you haven't.

## Path 1: Terminal Threads — the real perk TUI in a Zed thread

[Terminal Threads](https://zed.dev/docs/ai/terminal-threads) are the simpler story to tell,
because nothing about perk changes. Zed opens a terminal, runs whatever you run in it — `pi`, a
`perk` cold-door launch, the whole workflow — and files that terminal in the Agent Panel's Threads
sidebar as a thread. It *is* the shell. Everything perk does at a shell works here exactly as it
does outside Zed: stage launches and worktree positioning, the warm doors, the TUI's footer and
status surfaces, the in-TUI plan review editor. The division of labor is clean: Zed owns only the
thread surface — the sidebar entry, grouping threads by project, switching between them — while
the CLI in the terminal owns everything else: auth, models, tools, skills. Zed's own agent
configuration (profiles, permissions, Zed-side skills) simply does not apply.

Zed adds two documented affordances worth knowing by name. The first is the
[Terminal Thread init command](https://zed.dev/docs/ai/terminal-threads#terminal-thread-init-command)
(`agent.terminal_init_command`): a command Zed runs automatically in every shell it creates for a
Terminal Thread — new threads, and saved threads it recreates when a project reopens — which makes
it a natural place to start `pi` (or anything else) without typing it each time. The second is
[Terminal Thread notifications](https://zed.dev/docs/ai/terminal-threads#terminal-thread-notifications):
a terminal bell rung while the terminal is unfocused triggers Zed's standard agent-finished
notification — the pop-up and optional sound governed by Zed's usual agent notification settings.
Pi does not ring that bell on its own, but Zed's page includes a "Pi Notifications" section with a
tiny Pi extension — `zed-bell` — that emits the bell when a Pi turn ends, installable per-project
or globally; the mechanics live in Zed's docs, not here.

The honest residue: Terminal Threads are **closed, not archived**. They never enter Zed's Thread
History and cannot be imported, so when the thread is gone, its record is gone from Zed's side
(perk's canonical record, of course, was never in the thread — it is in the plan). And Zed learns
nothing about what perk is doing inside the terminal: to Zed the thread is an opaque pane of text,
however rich the workflow running within it.

## Path 2: registry Pi + `perk init` — the compatibility story

The second path goes through Zed's
[ACP registry](https://zed.dev/docs/ai/external-agents#registry) — Zed's primary way to install
External Agents — where Pi Coding Agent is a listed agent. Zed's own framing is worth repeating:
Pi is an agent harness, not a Zed LLM subscription; provider auth, models, tools, and
configuration all belong to Pi, and Zed renders the resulting agent thread.

What makes this a *perk* path at all is a fact about how perk is built: perk's session interior is
delivered as Pi packages. `perk init` writes the managed package set into the repo's
`.pi/settings.json`, so any Pi session that loads the repo's project settings — however that
session was started — carries perk's in-session workflow: the stage tools, the warm doors, the
skills. A registry-installed Pi running in a perk-initialized repo is such a session. That is the
entire compatibility story, and it is genuinely load-bearing: perk's interior does not care who
launched the session.

One caveat matters enough to state plainly: **Pi's project trust.** Pi's non-interactive modes —
including the ones editor integrations drive — never show a trust prompt, and in a repo you have
never trusted, Pi silently ignores project resources: no perk extension loads, no perk tools
appear, and no error tells you why. The repair is a one-time act at a terminal — run `pi` (or any
perk launch) in the repo root once and accept the trust prompt; after that, Zed-spawned sessions
in that repo load the project settings like any other. (This is also why the caveat never bites
Path 1: there you *are* at a terminal, and perk's own worktree launches carry the approval
themselves.)

Be clear about the register of this path: it is **compatibility, not a tested integration**.
perk's TUI-only surfaces — the footer, the status widgets, the in-TUI plan review editor — are
absent by design (perk is headless-fail-safe; surfaces that need a terminal simply do not render
elsewhere), and nothing about running perk's interior inside a Zed agent thread has been exercised
as a supported perk surface. It works because the pieces compose, not because the composition is a
product.

## The limitation both paths share

Stated plainly: **neither path surfaces perk's stage state, plan refs, worktrees, or cold doors as
first-class Zed affordances.** In Path 1 everything works — because it is the real terminal — but
Zed sees none of it: no thread history, no import, no Zed-native rendering of the workflow. In
Path 2 Zed renders a generic agent thread: perk's tools appear as ordinary tool calls, and stage
*launches* — the cold doors, the worktree positioning — remain acts you take at a shell. The
thread cannot become the next stage's session; the plan→implement handoff, which perk deliberately
routes through a fresh cold session, stays a shell act however you host the sessions. And Zed's
thread surfaces cannot tell a plan session from an implement session — the stage a thread is in
lives in perk's state tiers, which Zed does not read.

## Choosing between them

The choice is straightforward. **Terminal Threads when you want perk itself** — the full TUI, the
stage launches, the whole workflow, with Zed contributing thread organization and notifications.
**Registry Pi when you want a Zed-native agent thread** and accept the flattening — perk's tools
without perk's surfaces, and the workflow's shell acts still at a shell. Zed's own pages carry the
mechanics for both: [Terminal Threads](https://zed.dev/docs/ai/terminal-threads) and
[External Agents](https://zed.dev/docs/ai/external-agents).

← Back to the [explanation router](index.md).
