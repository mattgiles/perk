---
title: "How to review in the browser from a remote machine"
description: "Run perk on a remote Linux box and open every Plannotator review in your local browser through an SSH tunnel or a Tailscale tailnet."
sidebar:
  order: 2305
sidebarGroup: "Providers & backends"
---

# How to review in the browser from a remote machine

Run perk on a remote box (for example an EC2 instance you reach over ssh or mosh, inside tmux) and
open every Plannotator review — `plan_review`, `/plan-review-browser`, `/objective-review-browser`,
`/pr-review-browser`, and `/stack-review-browser` — in the browser on your own machine.

perk's browser doors take their port from Plannotator's own selection rule, so one set of
Plannotator environment variables on the remote box decides every review's port. You pick a
**lane** — the network route from your local browser to the remote Plannotator server — with those
variables; there is no perk configuration for it.

## Before you start

- perk runs on the remote box with `[providers] plan = "plannotator-plan"`, and you have a browser
  on your local machine.
- Every variable below is read by the same `pi` process `perk` launches. Set them in the shell that
  runs `perk` — in `~/.bashrc`, or with `tmux set-environment -g NAME value` followed by a fresh tmux
  window.
- Always set `PLANNOTATOR_REMOTE=1` explicitly. Plannotator also detects SSH from `SSH_TTY` /
  `SSH_CONNECTION`, but mosh and tmux do not reliably carry those variables.
- In remote mode Plannotator never opens a browser. It prints `[Plannotator] http://…` in the TUI,
  and perk's browser doors report `plannotator is up at http://127.0.0.1:<port> — reach it from your
  machine through your tunnel or tailnet`.

## Lane A — SSH or mosh with a port range

1. **Give Plannotator a port range on the remote box.** Reserve one port per review you run at the
   same time across all your perk sessions; widen the range if you run more:

   ```sh
   export PLANNOTATOR_REMOTE=1
   export PLANNOTATOR_PORT=19432-19435
   ```

2. **Forward the same ports from your local machine.** Add a host block to your local
   `~/.ssh/config`:

   ```ssh-config
   Host ec2
     HostName ec2-203-0-113-10.compute.amazonaws.com
     ExitOnForwardFailure yes
     ServerAliveInterval 30
     LocalForward 19432 localhost:19432
     LocalForward 19433 localhost:19433
     LocalForward 19434 localhost:19434
     LocalForward 19435 localhost:19435
   ```

3. **Keep the tunnel open.** Run `ssh -N ec2` in a local terminal beside your ssh or mosh session.
   mosh forwards no ports, so the tunnel is always its own connection.
4. **Open the review.** Start any review on the remote box, then open the URL Plannotator printed
   (`http://localhost:19432`, or the next port of the range) in your local browser.

## Lane B — Tailscale

1. **Join both machines to your tailnet.** Install Tailscale on the remote box and on your local
   machine.
2. **Advertise the tailnet name on the remote box.**

   ```sh
   export PLANNOTATOR_REMOTE=1
   export PLANNOTATOR_URL_HOST=auto
   ```

   `"urlHost": "auto"` in `~/.plannotator/config.json` does the same. You need no
   `PLANNOTATOR_PORT`: each review takes its own port.
3. **Open the review.** Plannotator prints `http://<magicdns-name>:<port>`; open it directly in
   your local browser.

In remote mode Plannotator binds `0.0.0.0`. Keep the review ports closed in the EC2 security group
(the default), and if you run a host firewall, admit them on the `tailscale0` interface only.

## Several reviews at once

Two perk sessions take two ports — from the range in Lane A, automatically in Lane B — and both
tabs stay live. Inside one session perk keeps one current review: a second `/plan-review-browser`
supersedes the first, whose tab stays open but whose verdict is ignored with a warning.

A single fixed `PLANNOTATOR_PORT` (no range) allows one browser review at a time. An abandoned tab
in the same session is replaced by the next review; a review started in another session fails with
`Port 19432 in use`. Decide the open review first, or switch to a range.

## Troubleshooting

- **Wrong port.** `plannotator is up at …` names the port perk actually used. A mistyped
  `PLANNOTATOR_PORT` falls back silently to `19432` (remote) or a random port, exactly as in
  Plannotator.
- **Port already taken.** `ss -ltnp | grep 1943` on the remote box shows which process holds a
  port.
- **Tunnel died.** A review that loads nothing locally usually means the forward is gone —
  restart `ssh -N ec2`.
- **`PLANNOTATOR_PORT range … is exhausted`.** Every port of the range is in use: decide the open
  reviews or widen the range.

## Related

- **Do:** [How to select a provider](./select-a-provider.md) — select `plannotator-plan` so the browser doors exist.
- **Look up:** [Plannotator draft-review transport](../reference/providers-and-backends.md#plannotator-draft-review-transport) — the port rule and the review guards.
- **Look up:** [Browser draft review](../reference/in-session/review-and-authoring.md#browser-draft-review) — what one current review per session means.
