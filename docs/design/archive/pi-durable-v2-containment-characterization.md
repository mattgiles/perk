# pi-durable v2 containment and fencing — characterization record

**Status:** measurement/evidence record, executed **2026-10-28** on branch `plan-2854` (plan
#2854, Objective #2847, node 1.4). It backs the binding record
[`../pi-durable-v2-foundations.md`](../pi-durable-v2-foundations.md) §10 (*Containment and fencing
verdict*), §1/§2 (the pin family) and §14 (*Subprocess capability for workers*).

- **Cited CI run:** [`ubuntu-latest` run 40773234033](https://github.com/mattgiles/perk/actions/runs/40773234033)
  at commit `b74167f315afbe1b7d409dc0c655e90c820fca66`, the last commit that touches the probes.
  The commit that adds this record changes only documentation.
- **local host:** Ubuntu 24.04.5 LTS, kernel `7.0.0-1013-aws`, x64, Node v24.22.1, uid 1000. The
  rows were collected by `just test-v2-slow` at `b74167f3` with a clean tree.
- **github host:** `ubuntu-latest` (`ImageOS` `ubuntu24`, `ImageVersion` `20261026.354.1`),
  Ubuntu 24.04.5 LTS, kernel `7.0.0-1017-azure`, x64, Node v22.23.4, uid 1001. The rows were
  collected by the CI `Test` step (`just test`, which runs the v2 slow tier).
- **Pin family:** `@earendil-works/pi-durable`, `chord`, `pi-ai` and `pi-env`, all exactly 1.4.0.
- **Source mirror:** library slug `pi` at `4a080252f06caf63a525d7873c5d94d3c23887e0` (Release
  v1.4.0). Pointers below are relative to that mirror. The packaged daemon binaries (`bin/`) are
  not in the mirror: they are built at publish time and were read from the installed package.

**Verdict.** **GO: supervised execution.** Every rule-required `supervised` row is `PASS` on both
hosts, and `setsid(1)` exists on both. The binding text is §10 of the foundations record, quoted in
[Verdict](#verdict). Measurement also surfaced two obligations that the plan did not anticipate.
They do not move the rule, and the verdict carries them as obligations:

- a graceful `Connection.close()` leaks every running command unless the owner first runs
  `env.cleanup()` and waits for each `exec` to settle;
- the daemon's spawn→register window is real. An owner that dies within microseconds of sending
  an `exec` frame leaked the whole tree in 2 of 400 ad hoc trials.

## Decision rule (pinned before measuring)

Copied verbatim from the plan, where it was pinned before any probe ran. A result never re-words it.

> Terms: a **host** is {local (this machine, `just test-v2-slow` in the worktree), github
> (`ubuntu-latest`, the PR's CI `just test` step)}. The **group set** of a command is every
> descendant still in the command's session/process group: the leader, its children,
> grandchildren, and environment-scrubbed descendants. The **stop set** of a mechanism is what it
> can kill on owner death; its **residual** is what it provably cannot.
>
> - **GO** iff on **every** host the `supervised` rows `availability`, `crash-A`, `crash-B`,
>   `crash-C`, `descendants` (the group set is dead) and `pid-reuse` are `PASS`, and on every host
>   where `setsid(1)` exists the `group-kill-mitigated` row is `PASS`. The `setsid-escape`,
>   `leader-exited` and `group-kill` rows are **recorded residuals** — expected survivors; they
>   never flip the verdict, and they are named in the §10 text with the isolation obligation that
>   covers them.
> - **NO-GO** iff any required row above is `FAIL` or `unavailable` on any host. The verdict then
>   records NO-GO: workers that spawn subprocesses stay blocked, and the plan-workflow objective
>   must revisit before it gives implementation workers bash (the objective's stop condition).
> - **Filesystem view and network policy** are decided SOURCE-DERIVED and recorded as their own
>   verdict rows, independent of GO/NO-GO: supervised execution provides neither (a cwd is no
>   sandbox); only a namespace sandbox could, and its availability rows decide whether that is
>   "unavailable unprivileged on supported hosts" or "available here, not adopted by this
>   verdict". The read-only reviewer snapshot and any network policy remain P7
>   environment-policy obligations either way.
> - The `pidns`, `pdeathsig`, `bwrap`, `journal`, `cgroup`, `systemd-scope` and `marker` rows are
>   **comparison evidence**: they justify "evaluated, not chosen" and quantify each alternative's
>   stop set and residual. They never move the verdict.
> - The rule, the row vocabulary and both verdict arms are copied verbatim into the record before
>   any measurement is transcribed; a result never re-words the rule.

**Row vocabulary** (verbatim; every probe emits
`t.diagnostic("perk-v2-containment " + JSON.stringify(row))`):

```ts
export type EvidenceRow = {
  kind: "host" | "probe";
  host: "github" | "local";                 // process.env.GITHUB_ACTIONS === "true" ? "github" : "local"
  mechanism?: "repro" | "supervised" | "pidns" | "bwrap" | "pdeathsig" | "journal" | "cgroup" | "systemd-scope" | "marker";
  criterion?: "availability" | "crash-A" | "crash-B" | "crash-C" | "descendants" | "pid-reuse"
    | "setsid-escape" | "leader-exited" | "group-kill" | "group-kill-mitigated" | "report" | "survival";
  result: "PASS" | "FAIL" | "unavailable" | "not_measured" | "recorded";
  detail: string;                            // verbatim stderr / exit status / per-descendant survival map
};
```

`recorded` is the result of a residual row: a survival map, with no pass/fail.

**Verdict arms** (verbatim):

> **GO (supervised execution)** — replace the reserved subsection with:
>
> > **Containment and fencing verdict (node 1.4): supervised execution.** Worker commands run
> > through a pi-env daemon on the same machine (`RemoteExecutionEnv` over `Connection({ command:
> > ["setsid", localDaemon()] })` where `setsid(1)` exists, else the plain daemon), never through
> > `NodeExecutionEnv.exec` directly. The daemon puts every command in its own session and kills
> > every session it started when its stdin — the owner's pipe — closes; owner death therefore
> > stops the group set of every running command without the owner recording anything first, and
> > a held, un-reaped child cannot have its pid reused. Every spawn carries `PERK_V2_STORE` and
> > `PERK_V2_EPOCH` as labels. **Step 2 at open kills nothing**: it runs the report-only sweep
> > (Linux: `/proc/*/environ` labels of earlier epochs with their start times; elsewhere
> > `not_observable`) and surfaces survivors in the status snapshot. **Residuals, recorded and
> > measured:** `setsid` escapes; background work that outlives its command's leader;
> > owner-and-daemon group kills on a host without `setsid(1)`; the daemon's own spawn→register
> > window. They are **isolated** by the obligation that every attempt's environment is rooted at
> > its own workspace and an earlier epoch's workspace is never reused before it is discarded.
> > **Filesystem view and network policy are not provided** (<per-host namespace availability as
> > measured>); the read-only reviewer snapshot and any network policy remain P7
> > environment-policy obligations, and reviewers get no subprocess capability. Not chosen, with
> > measured reasons: PID namespaces (<availability rows>), a spawn journal (stop set = the
> > registered process only; owner-written state), a cgroup fence (Linux-only, cgroup writability
> > varies by host, cooperative escape). Evidence:
> > `archive/pi-durable-v2-containment-characterization.md`.
>
> **NO-GO** — replace with:
>
> > **Containment and fencing verdict (node 1.4): NO-GO.** Supervised execution did not measure
> > crash-safe at the spawn boundary with group-set coverage on every supported host (`<the
> > failing host and rows>`). Step 2 stays a no-op; workers that spawn subprocesses stay blocked;
> > the plan-workflow objective must revisit before it gives implementation workers bash.
> > Evidence: `archive/pi-durable-v2-containment-characterization.md`.
>
> Either arm records, as separate rows, the filesystem-view and network-policy outcomes exactly
> as measured/derived.

## SOURCE-DERIVED

Nothing in this section was measured. Each claim points at the pinned source.

### (a) `NodeExecutionEnv`: why the problem exists

- `packages/durable/src/env/node.ts::NodeExecutionEnv.exec` first `await`s `access(cwd)`. It then
  spawns with `detached: process.platform !== "win32"`, which on POSIX makes the command a session
  and process-group leader, and adds the pid to `activeChildPids`.
- `packages/durable/src/env/node.ts::killProcessTree` sends `SIGKILL` to `-pid`. It falls back to
  `pid` only if the group kill throws.
- `packages/durable/src/env/node.ts::NodeExecutionEnv.cleanup` kills every pid in
  `activeChildPids`. That set is private and lives only in memory: nothing records it, so when the
  owner dies nobody holds the list and nobody kills the group. `packages/coding-agent`'s
  `utils/shell.ts` and `core/tools/bash.ts` follow the same pattern.

### (b) pi-env: what supervised execution stops, and where it cannot

- `packages/env/daemon/src/sys/unix.rs::configure` — the `pre_exec` hook of every command calls
  `libc::setsid()` ("A new session, so a kill reaches every descendant"), resets every signal
  disposition to default and empties the signal mask.
- `packages/env/daemon/src/sys/unix.rs::kill_tree` — `kill(-pid, SIGKILL)`, else
  `kill(pid, SIGKILL)`.
- `packages/env/daemon/src/exec.rs::run`:
  - `groups.lock().unwrap().insert(pid)` runs right after `spawn`.
  - A waiter thread `child.wait()`s, so the daemon reaps its leader as soon as the leader exits.
  - `groups.lock().unwrap().remove(&pid)` runs at settle: once the leader has exited and both
    pipes have ended, or once `EXIT_STDIO_GRACE` (100 ms) has passed.
- `packages/env/daemon/src/main.rs::serve` — when `serve_frames` returns, the daemon runs
  `kill_all(&server.groups)` ("However input ended, the client is gone: stop everything it
  started."). A ping thread runs `kill_all` and then `exit(0)` once no byte has arrived for
  `SILENCE_LIMIT_MS` = 30 000.
- `packages/env/daemon/src/main.rs::serve_frames` — each `exec` request runs on its own thread,
  while the main thread keeps reading frames.
- The daemon installs **no handler for a terminating signal**. The only `signal(…)` calls in
  `daemon/src` reset dispositions inside a child's `pre_exec`. So SIGTERM, SIGINT or SIGHUP kills
  the daemon outright, and `kill_all` never runs.
- `packages/env/src/connection.ts::Connection` — `#start` spawns `<daemon> serve --token <hex>`
  with `stdio: ["pipe","pipe","pipe"]` and **not** detached. The daemon therefore shares the
  owner's process group and session. `close()` ("Stop the daemon; it kills everything it
  started.") and the client's own 30 s silence teardown both run `#teardown`, which calls
  `child.stdin.end()` and then `child.kill()`, sending **SIGTERM**.
- `packages/env/src/remote-env.ts::RemoteExecutionEnv.cleanup` — sends a `kill` cancel for each
  running request and returns without waiting for any of them to settle.
- `packages/env/src/ssh.ts::localDaemon` — returns `packagedDaemon` for `linux | android | darwin |
  windows`, and throws for anything else.
- `packages/env/docs/semantics.md` — "Each command gets a new session (process group), default
  signal dispositions and an empty signal mask. Timeout, abort and `cleanup()` kill the group
  with `SIGKILL`."

**Consequences.**

- **Stop by construction.** The owner holds the daemon's stdin. However the owner dies (SIGKILL, a
  crash, an OOM kill), the kernel closes that pipe, the daemon reads EOF, and `kill_all` sends
  `SIGKILL` to every registered group. The owner writes nothing first.
- **The spawn→register window.** A frame is read on the main thread, but its command is spawned
  and registered on an exec thread. EOF can arrive in between. `kill_all` then iterates a set that
  does not yet hold the pid, the main thread returns and the process exits, and a child that was
  already forked survives. Only an owner that dies within the exec thread's pre-insert work
  (thread start, program resolution, cwd check, fork/exec, sub-millisecond to about a
  millisecond) of writing an `exec` frame can hit it. No retained probe can aim at it. The ad hoc
  measurement under [MEASURED](#measured) hit it 2 times in 400.
- **The settle→remove window (pid reuse).** While a pid is in `groups`, its leader is either an
  un-reaped child of the daemon, so its pid cannot be reused, or reaped but not yet settled, for
  at most about 100 ms of grace plus one loop turn. If `kill_all` lands in that second case and the
  group is empty, `kill(-pid)` fails with ESRCH and the fallback `kill(pid)` could reach a pid
  reused within those 100 ms. This is a bounded, recorded residual.
- **The 30 s silence rule.** A SIGSTOPped owner, or one whose event loop stays blocked for more
  than 30 s, sends no pings, so the daemon kills everything and exits. That costs liveness but
  never leaks. The reverse case does leak: a daemon that stalls makes the client tear the
  connection down with SIGTERM, which kills the daemon without `kill_all`.
- **Group-directed signals.** The plain daemon sits in the owner's process group and session. A
  group kill kills both at once, and so does a terminal's SIGINT or SIGHUP to its foreground group;
  `kill_all` never runs (measured: `group-kill`). util-linux `setsid`, run by a process that is not
  a group leader, calls `setsid()` and execs in place, so the daemon keeps its pid but moves to its
  own session. It then learns of the owner's death only through the pipe (measured:
  `group-kill-mitigated`). A signal sent to the daemon's own pid still kills it without `kill_all`;
  that is a residual.
- **Graceful close.** `Connection.close()` ends the daemon's stdin and then SIGTERMs it. The daemon
  has no handler, so the SIGTERM wins and the running commands survive (measured:
  `supervised/survival` close-only). One close order stops them: `env.cleanup()`, then await every
  running `exec`'s settlement, then `connection.close()`.

### (c) Host policy

- `kernel.apparmor_restrict_unprivileged_userns = 1` on both hosts (see the `host` rows). An
  unprivileged process that creates a user namespace is switched to the `unprivileged_userns`
  profile (local: `/etc/apparmor.d/unprivileged_userns`, `audit deny capability`). Inside the new
  namespace it therefore has no capabilities and cannot write its own `uid_map`, and `unshare -Ur`
  fails with `write failed /proc/self/uid_map: Operation not permitted`. A PID namespace needs
  `CAP_SYS_ADMIN` in its owning user namespace, so `unshare --pid` is out of reach unprivileged.
- cgroup v2 on both hosts.
  - local: the test process runs in a user-owned systemd scope (`…/user@1000.service/…scope`) that
    is writable and has `cgroup.kill`.
  - github: job processes run in `/system.slice/hosted-compute-agent.service`, which is
    root-owned, so a fence there fails with `EACCES`.
  - `systemd-run --user --scope` works on both hosts: the runner has a user manager.
- bubblewrap is not installed on either host.

### (d) Each mechanism against the node's criteria

| Mechanism | Crash safety (A/B/C) | Descendants incl. grandchild, scrubbed, `setsid` | PID reuse | Filesystem view | Network policy | Prerequisites | Fail-closed posture |
|---|---|---|---|---|---|---|---|
| **supervised** (pi-env local daemon) | by construction: the pipe closes on any owner death; spawn→register window residual | the whole group set; not `setsid` escapes, not background work after the leader settles | kills only un-reaped children or live groups; settle→remove window residual | none (a cwd is no sandbox) | none | the packaged daemon for the platform (`localDaemon()`); `setsid(1)` for the group-kill mitigation | `localDaemon()` throws on an unknown platform; a missing daemon fails `exec` (`spawn_error`) |
| **pdeathsig** (`PR_SET_PDEATHSIG`) | the armed process dies with its parent thread | the armed process only; its children are unarmed | kernel-delivered, no pid lookup | none | none | `setpriv` or a prctl seam per spawn | n/a (per-process) |
| **pidns / bwrap** | the namespace init dies with its parent and the kernel kills every member | everything in the namespace, `setsid` escapes included | kernel-scoped | a mount namespace can give a read-only view | a network namespace can deny the network | an unprivileged user namespace, which is **blocked** on both hosts; bwrap is not installed | unavailable means no sandbox; the gate fails closed (`not_measured`) |
| **journal** (intent-first record, start-time identity) | only what the fence kills at the next open, and only if the record was written before death | the registered process only, unless it also kills groups | a start-time match refuses a reused pid | none | none | owner-written state; an fsync'd record before spawn | a missing or stale record kills nothing |
| **cgroup fence / systemd scope** | `cgroup.kill` at the next open kills everything in the fence | everything in the fence, `setsid` escapes included | kernel-scoped (cgroup membership) | none | none | Linux cgroup v2 with a writable own cgroup (local yes, github no), or a systemd user manager | refuses when not writable; joining is cooperative (the wrapper moves itself) |
| **marker sweep** (report-only) | reports, never stops | every process carrying the labels, `setsid` escapes included, but not `env -i` | start time read in the same pass | n/a | n/a | Linux `/proc` | `not_observable` elsewhere; never blocks open |

### (e) The isolation obligation

Durable's model puts the boundary in the environment, chosen per conversation.

- `packages/durable/README.md#Environment`: "one function serves a directory per conversation or a
  container per conversation".
- `packages/durable/test/examples/29-sandbox-per-conversation.ts`: "a hosted product would return
  an ExecutionEnv that runs inside the conversation's container".
- The planning corpus sets the obligation as
  [stop, join, or isolate](../../planning/pi-durable/pi-durable-workflows.md#resuming-safely) the
  earlier attempt before replacement work.
- It names pi-env with "orphan reconciliation" as its gap
  ([further avenues § 4.3](../../planning/pi-durable-further-avenues.md#43-revisit-hosting-as-three-separate-responsibilities))
  and records that "a cwd remains no sandbox"
  ([§ 3](../../planning/pi-durable-further-avenues.md#3-existing-plan-audit) V4).

Supervised execution is the **stop**. The residuals are what **isolate** must cover. Every attempt's
environment is rooted at its own workspace, and a later epoch never reuses an earlier epoch's
workspace before discarding it. A survivor of epoch *n* then writes only where nothing later reads,
until that workspace is discarded, and its labels make it visible to the sweep. A residual is
therefore a **leak** (CPU, memory, files in an abandoned workspace, bounded by the survivor's own
lifetime), not a **conflict** with replacement work.

That holds only inside the workspace. Effects outside it, such as the network, git remotes or the
main checkout, are not isolated by a workspace. Those belong to the P7 environment policy: the
capability set bounds what a command can reach, and reviewers get no subprocess capability at all.

### (f) macOS (NOT MEASURED)

There was no macOS run.

- pi-env ships `pi-env-darwin-{x64,arm64}` (the installed `bin/`), and process groups and sessions
  exist there, so supervised execution is expected to work. That expectation is unmeasured.
- With no `/proc`, the sweep returns `not_observable`.
- macOS ships no `setsid(1)`, so the group-kill mitigation would need a detached-spawn seam in the
  connection command.

## MEASURED

### Results by host

| Row | local | github |
|---|---|---|
| `repro/survival` | PASS | PASS |
| `repro/survival` (control: clean close) | PASS | PASS |
| `supervised/availability` | PASS | PASS |
| `supervised/crash-A` | PASS | PASS |
| `supervised/crash-B` | PASS | PASS |
| `supervised/crash-C` | PASS | PASS |
| `supervised/descendants` | PASS | PASS |
| `supervised/setsid-escape` | recorded | recorded |
| `supervised/leader-exited` | recorded | recorded |
| `supervised/pid-reuse` | PASS | PASS |
| `supervised/group-kill` | recorded | recorded |
| `supervised/group-kill-mitigated` | PASS | PASS |
| `supervised/survival` (graceful close: `close-only`) | recorded | recorded |
| `supervised/survival` (graceful close: `cleanup-settle-close`) | recorded | recorded |
| `pdeathsig/crash-C` | PASS | PASS |
| `pidns/availability` (`unshare -Ur true`) | unavailable | unavailable |
| `pidns/availability` (`unshare -Ur --pid --fork true`) | unavailable | unavailable |
| `pidns/availability` (`unshare -Urn true`) | unavailable | unavailable |
| `pidns/crash-C` | not_measured | not_measured |
| `pidns/descendants` | not_measured | not_measured |
| `bwrap/availability` | unavailable | unavailable |
| `journal/crash-C` | PASS | PASS |
| `journal/descendants` | recorded | recorded |
| `journal/pid-reuse` | PASS | PASS |
| `cgroup/availability` | PASS | unavailable |
| `cgroup/crash-C` | PASS | not_measured |
| `cgroup/descendants` | PASS | not_measured |
| `systemd-scope/availability` | PASS | PASS |
| `marker/report` | PASS | PASS |

What the survival maps say. They are identical on both hosts unless a row names a host.

- **`repro`.** After the owner's SIGKILL, the whole `NodeExecutionEnv` tree keeps running: the
  leader, `child`, `middle`, `grandchild`, `setsid` and `scrubbed`. The control's `env.cleanup()`
  kills everything except the `setsid` escape.
- **`supervised` crash-A/B/C.** The leader and every group-set member are dead, and the `setsid`
  escape is the only survivor. At crash-A and crash-B the kill landed after the daemon had
  spawned the leader: the leader's record appeared and died at once, and `child`, `grandchild`
  and `scrubbed` never got far enough to write theirs.
- **`supervised` residuals.**
  - `leader-exited`: `bg` survives, because the daemon dropped the group at settle.
  - `group-kill`: the whole tree survives, because the daemon died with the owner's group.
  - `group-kill-mitigated`: only `setsid` survives.
- **`supervised/pid-reuse`.** The leader's parent is the daemon, and the leader's pgid and sid both
  equal its pid. Killed while the daemon was SIGSTOPped, the leader stayed a zombie with the same
  start time 200 ms later, so its pid stayed held. Once the daemon was resumed, it was reaped.
- **`supervised/survival`.** With `close-only`, the whole tree survives a graceful close. With
  `cleanup-settle-close`, only `setsid` survives.
- **Comparison rows.**
  - `pdeathsig`: the armed child is dead.
  - `journal`: the fence kills the registered leader, and every descendant survives.
  - `journal/pid-reuse`: a forged start time is refused (the decoy kept ticking), and a matching
    record kills.
  - `cgroup` (local): `cgroup.kill` kills everything, `setsid`, `scrubbed` and the leader-exited
    `bg` included, and the fence is removed.
  - `marker/report`: the sweep lists exactly the leader, `child`, `middle`, `grandchild` and
    `setsid` at epoch 1, each with a matching start time, and never `scrubbed`.

### local rows (verbatim)

```
perk-v2-containment {"kind":"host","host":"local","result":"recorded","detail":"","facts":{"platform":"linux","arch":"x64","release":"7.0.0-1013-aws","osRelease":"Ubuntu 24.04.5 LTS","node":"v24.22.1","uid":"1000","apparmor_restrict_unprivileged_userns":"1","max_user_namespaces":"472022","ownCgroup":"/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/tmux-spawn-52eceb57-801b-4ad3-81ac-da0e9b0a41e0.scope","ownCgroupWritable":"true","cgroupKill":"true","piEnvDaemon":"/home/ubuntu/src/perk/.worktrees/plan-2854/node_modules/@earendil-works/pi-env/bin/pi-env-linux-x64/pi-env","bwrap":"missing","unshare":"present","setpriv":"present","systemd-run":"present","setsid":"present"}}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"repro","criterion":"survival","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; after the owner's exit: {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"repro","criterion":"survival","result":"PASS","detail":"control (clean close): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"availability","result":"PASS","detail":"path=/home/ubuntu/src/perk/.worktrees/plan-2854/node_modules/@earendil-works/pi-env/bin/pi-env-linux-x64/pi-env version=1.4.0 protocol=1 pid=1794433 os=linux arch=x86_64"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"crash-A","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; leader: appeared+0ms dead+0ms; child: never; middle: appeared+0ms dead+0ms; grandchild: never; setsid: appeared+21ms ALIVE; scrubbed: never; daemon 1794499: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"crash-B","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; leader: appeared+0ms dead+0ms; child: never; middle: appeared+0ms dead+0ms; grandchild: never; setsid: appeared+20ms ALIVE; scrubbed: never; daemon 1794785: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 1794832: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"descendants","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 1794832: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"setsid-escape","result":"recorded","detail":"setsid: alive (ticking); sid=1794863 (own session: 1794863)"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"leader-exited","result":"recorded","detail":"settled exit=0; owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"bg\":\"alive (ticking)\"}; daemon 1794897: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"pid-reuse","result":"PASS","detail":"leader 1794965: ppid=1794940 (daemon 1794940) pgid=1794965 sid=1794965; killed with the daemon stopped → zombie=true, still a zombie 200 ms later=true; daemon resumed → reaped=true"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"group-kill","result":"recorded","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}; daemon 1794982: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"group-kill-mitigated","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 1795047: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"survival","result":"recorded","detail":"graceful close (close-only): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}; daemon 1795112: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"supervised","criterion":"survival","result":"recorded","detail":"graceful close (cleanup-settle-close): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 1795178: dead"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pdeathsig","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"child\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Ur\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Urn\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pidns","criterion":"crash-C","result":"not_measured","detail":"gated on [\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"]: argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"pidns","criterion":"descendants","result":"not_measured","detail":"gated on [\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"]: argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"bwrap","criterion":"availability","result":"unavailable","detail":"not installed (bwrap is not on PATH)"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"journal","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; registered={\"pid\":1794600,\"startTime\":\"243669061\"} (leader {\"pid\":1794600,\"startTime\":\"243669061\"}); fence=killed; {\"leader\":\"dead\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"journal","criterion":"descendants","result":"recorded","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; registered={\"pid\":1794600,\"startTime\":\"243669061\"} (leader {\"pid\":1794600,\"startTime\":\"243669061\"}); fence=killed; {\"leader\":\"dead\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"journal","criterion":"pid-reuse","result":"PASS","detail":"forged start time → fence=stale, decoy alive (ticking); matching record → fence=killed, decoy dead=true"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"cgroup","criterion":"availability","result":"PASS","detail":"fence root /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/tmux-spawn-52eceb57-801b-4ad3-81ac-da0e9b0a41e0.scope"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"cgroup","criterion":"crash-C","result":"PASS","detail":"tree: owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; fence {\"unpopulated\":true,\"removed\":true}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"dead\",\"scrubbed\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"cgroup","criterion":"descendants","result":"PASS","detail":"tree: owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; fence {\"unpopulated\":true,\"removed\":true}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"dead\",\"scrubbed\":\"dead\"} | leader-exited: owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; fence {\"unpopulated\":true,\"removed\":true}; {\"bg\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"systemd-scope","criterion":"availability","result":"PASS","detail":"argv=[\"systemd-run\",\"--user\",\"--scope\",\"--quiet\",\"true\"] exit=0 signal=none stderr=\"\""}
perk-v2-containment {"kind":"probe","host":"local","mechanism":"marker","criterion":"report","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; sweep(store, below epoch 2) listed [\"leader@epoch1\",\"child@epoch1\",\"middle@epoch1\",\"setsid@epoch1\",\"grandchild@epoch1\"]; expected [\"leader\",\"child\",\"middle\",\"grandchild\",\"setsid\"]"}
```

### github rows (verbatim)

From the CI log of run 40773234033, filtered with `perk-v2-containment`:

```
perk-v2-containment {"kind":"host","host":"github","result":"recorded","detail":"","facts":{"platform":"linux","arch":"x64","release":"7.0.0-1017-azure","osRelease":"Ubuntu 24.04.5 LTS","node":"v22.23.4","uid":"1001","apparmor_restrict_unprivileged_userns":"1","max_user_namespaces":"58121","ownCgroup":"/sys/fs/cgroup/system.slice/hosted-compute-agent.service","ownCgroupWritable":"false","cgroupKill":"true","piEnvDaemon":"/home/runner/work/perk/perk/node_modules/@earendil-works/pi-env/bin/pi-env-linux-x64/pi-env","bwrap":"missing","unshare":"present","setpriv":"present","systemd-run":"present","setsid":"present","ImageOS":"ubuntu24","ImageVersion":"20261026.354.1","RUNNER_OS":"Linux"}}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"repro","criterion":"survival","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; after the owner's exit: {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"repro","criterion":"survival","result":"PASS","detail":"control (clean close): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"availability","result":"PASS","detail":"path=/home/runner/work/perk/perk/node_modules/@earendil-works/pi-env/bin/pi-env-linux-x64/pi-env version=1.4.0 protocol=1 pid=32209 os=linux arch=x86_64"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"crash-A","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; leader: appeared+0ms dead+21ms; child: never; middle: appeared+0ms dead+21ms; grandchild: never; setsid: appeared+42ms ALIVE; scrubbed: never; daemon 32265: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"crash-B","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; leader: appeared+0ms dead+0ms; child: never; middle: appeared+0ms dead+0ms; grandchild: never; setsid: appeared+20ms ALIVE; scrubbed: never; daemon 32509: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 32566: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"descendants","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 32566: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"setsid-escape","result":"recorded","detail":"setsid: alive (ticking); sid=32597 (own session: 32597)"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"leader-exited","result":"recorded","detail":"settled exit=0; owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"bg\":\"alive (ticking)\"}; daemon 32631: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"pid-reuse","result":"PASS","detail":"leader 32699: ppid=32674 (daemon 32674) pgid=32699 sid=32699; killed with the daemon stopped → zombie=true, still a zombie 200 ms later=true; daemon resumed → reaped=true"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"group-kill","result":"recorded","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}; daemon 32716: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"group-kill-mitigated","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 32781: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"survival","result":"recorded","detail":"graceful close (close-only): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"alive\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}; daemon 32846: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"supervised","criterion":"survival","result":"recorded","detail":"graceful close (cleanup-settle-close): owner exit={\"code\":0,\"signal\":null}; {\"leader\":\"dead\",\"child\":\"dead\",\"middle\":\"dead\",\"grandchild\":\"dead\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"dead\"}; daemon 32912: dead"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pdeathsig","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; {\"child\":\"dead\"}"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Ur\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pidns","criterion":"availability","result":"unavailable","detail":"argv=[\"unshare\",\"-Urn\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pidns","criterion":"crash-C","result":"not_measured","detail":"gated on [\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"]: argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"pidns","criterion":"descendants","result":"not_measured","detail":"gated on [\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"]: argv=[\"unshare\",\"-Ur\",\"--pid\",\"--fork\",\"true\"] exit=1 signal=none stderr=\"unshare: write failed /proc/self/uid_map: Operation not permitted\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"bwrap","criterion":"availability","result":"unavailable","detail":"not installed (bwrap is not on PATH)"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"journal","criterion":"crash-C","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; registered={\"pid\":32418,\"startTime\":\"51183\"} (leader {\"pid\":32418,\"startTime\":\"51183\"}); fence=killed; {\"leader\":\"dead\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"journal","criterion":"descendants","result":"recorded","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; registered={\"pid\":32418,\"startTime\":\"51183\"} (leader {\"pid\":32418,\"startTime\":\"51183\"}); fence=killed; {\"leader\":\"dead\",\"child\":\"alive (ticking)\",\"middle\":\"alive\",\"grandchild\":\"alive (ticking)\",\"setsid\":\"alive (ticking)\",\"scrubbed\":\"alive (ticking)\"}"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"journal","criterion":"pid-reuse","result":"PASS","detail":"forged start time → fence=stale, decoy alive (ticking); matching record → fence=killed, decoy dead=true"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"cgroup","criterion":"availability","result":"unavailable","detail":"own cgroup /sys/fs/cgroup/system.slice/hosted-compute-agent.service not writable: Error: EACCES: permission denied, access '/sys/fs/cgroup/system.slice/hosted-compute-agent.service'"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"cgroup","criterion":"crash-C","result":"not_measured","detail":"preflight: own cgroup /sys/fs/cgroup/system.slice/hosted-compute-agent.service not writable: Error: EACCES: permission denied, access '/sys/fs/cgroup/system.slice/hosted-compute-agent.service'"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"cgroup","criterion":"descendants","result":"not_measured","detail":"preflight: own cgroup /sys/fs/cgroup/system.slice/hosted-compute-agent.service not writable: Error: EACCES: permission denied, access '/sys/fs/cgroup/system.slice/hosted-compute-agent.service'"}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"systemd-scope","criterion":"availability","result":"PASS","detail":"argv=[\"systemd-run\",\"--user\",\"--scope\",\"--quiet\",\"true\"] exit=0 signal=none stderr=\"\""}
perk-v2-containment {"kind":"probe","host":"github","mechanism":"marker","criterion":"report","result":"PASS","detail":"owner exit={\"code\":null,\"signal\":\"SIGKILL\"}; sweep(store, below epoch 2) listed [\"leader@epoch1\",\"child@epoch1\",\"middle@epoch1\",\"setsid@epoch1\",\"grandchild@epoch1\"]; expected [\"leader\",\"child\",\"middle\",\"grandchild\",\"setsid\"]"}
```

### Ad hoc measurements (local only, not retained)

These two scripts lived in the run's scratch directory. Each placed a variant owner beside
`owner.ts` for the length of the run and deleted it afterwards. They bound two windows the
retained matrix cannot target.

- **Spawn→register window (owner death right after the frame).** A supervised owner called
  `env.exec(TREE)` and SIGKILLed itself in the next `setImmediate`, just after the request frame
  had been written. Each trial was then checked after 1.5 s. Over 400 trials (100 + 300):

  | Survivors | Trials |
  |---|---|
  | only `setsid` (the group set was stopped) | 395 |
  | none (killed before the frame was out) | 3 |
  | **the whole tree** (leader, `child`, `middle`, `grandchild`, `setsid`, `scrubbed`) | **2** |

  The window is real, and an owner that dies within microseconds of sending a frame hits it
  about 0.5% of the time. With the retained crash-A injection (an external kill on the `exec`
  line) it never occurred.
- **Graceful close order.** A supervised owner closed once the tree was ready, 20 trials per order:

  | Close order | Survivors |
  |---|---|
  | `connection.close()` alone | the whole tree, 20/20 |
  | `env.cleanup()` then `connection.close()`, without waiting | `setsid` 19/20; the whole tree 1/20 |
  | `env.cleanup()`, await the `exec` settlement, then `connection.close()` | `setsid` 20/20 |

### Instrument notes (where the probes refine the plan's text)

- `TREE` names `middle`, the level-1 shell that runs `grandchild`. It carries the labels, so the
  sweep's visible set can be stated exactly.
- Shell identities are read with `read < /proc/self/stat`. A builtin's `self` is the shell itself,
  and field 1 is procfs's own pid, which stays correct inside a PID namespace whose procfs was not
  remounted. The heartbeat records its pid the same way.
- crash-A and crash-B pass on the **group set**, as the rule defines it. The `setsid` escape is
  excluded from the check, and its fate is recorded in the detail.
- `supervised/pid-reuse` freezes the daemon (SIGSTOP) before killing the leader. The daemon's
  waiter thread reaps instantly, so a zombie is otherwise unobservable.
- The repro teardown kills each recorded identity rather than `-childPid`: the child is not a
  group leader. Every kill checks the start time first.
- `supervised/survival` (graceful close, two orders) is added within the closed vocabulary as
  `recorded`, outside the rule, after the ad hoc close measurement. `owner.ts` gained
  `closeOnStdinEnd` for it.
- The rule-required `supervised` rows assert `PASS` where the lane is available, and the other
  rows assert nothing about outcomes. The comparison rows only report.

### pi-env install facts

- `npm install --workspace extension/pi/v2 @earendil-works/pi-env@1.4.0` reported
  `added 1 package`. `chord` and `pi-durable` dedupe to the existing 1.4.0 copies.
- Lockfile delta (`package-lock.json`, 15 insertions and 1 deletion): the `extension/pi/v2`
  entry's `dependencies` gains `@earendil-works/pi-env: 1.4.0`, and there is one new
  `node_modules/@earendil-works/pi-env` entry (`resolved` `pi-env-1.4.0.tgz`, MIT, dependencies
  `chord` 1.4.0 and `pi-durable` 1.4.0, `engines.node >=22.19.0`).
- `npm ls @earendil-works/pi-env @earendil-works/chord @earendil-works/pi-durable --workspace
  extension/pi/v2`:

  ```
  @mgiles/perk@4.2.0 /home/ubuntu/src/perk/.worktrees/plan-2854
  └─┬ perk-v2@0.0.0 -> ./extension/pi/v2
    ├── @earendil-works/chord@1.4.0
    ├─┬ @earendil-works/pi-durable@1.4.0
    │ └── @earendil-works/chord@1.4.0 deduped
    └─┬ @earendil-works/pi-env@1.4.0
      ├── @earendil-works/chord@1.4.0 deduped
      └── @earendil-works/pi-durable@1.4.0 deduped
  ```

- The installed package is about 18 MB. `bin/` holds `pi-env-{android,darwin,linux,windows}-{x64,arm64}`.
  `bin/pi-env-linux-x64/pi-env` is a static-pie x86-64 ELF of 2,442,048 bytes, sha256
  `46dde0e25b5cf1a327a10ddcb25f746f85b783492f5b225dfaa1a0d84cf5b56a`, and `--version` prints
  `pi-env 1.4.0`.
- Two packaging pins name the new family member: `tests/test_packaging.py` and
  `tests/test_pi_host.py`. The second, `V2_WORKSPACE_FAMILY`, was found by CI, not by the plan.

## Verdict

**The rule selects GO.** On both hosts every required row (`supervised/availability`, `crash-A`,
`crash-B`, `crash-C`, `descendants`, `pid-reuse`) is `PASS`. `setsid(1)` exists on both, and
`group-kill-mitigated` is `PASS` on both. The GO arm's two placeholders are filled from the
per-host availability rows. The arm also carries two measured additions that the rule's outcome
does not depend on: the graceful-close order, and the measured size of the spawn→register window
(with terminating signals to the daemon named as a residual). The §10 text, as written into the
foundations record:

> **Containment and fencing verdict (node 1.4): supervised execution.** Worker commands run through
> a pi-env daemon on the same machine (`RemoteExecutionEnv` over `Connection({ command: ["setsid",
> localDaemon()] })` where `setsid(1)` exists, else the plain daemon), never through
> `NodeExecutionEnv.exec` directly. The daemon puts every command in its own session and kills every
> session it started when its stdin — the owner's pipe — closes; owner death therefore stops the
> group set of every running command without the owner recording anything first, and a held,
> un-reaped child cannot have its pid reused. Every spawn carries `PERK_V2_STORE` and
> `PERK_V2_EPOCH` as labels. **Step 2 at open kills nothing**: it runs the report-only sweep (Linux:
> `/proc/*/environ` labels of earlier epochs with their start times; elsewhere `not_observable`) and
> surfaces survivors in the status snapshot. **Graceful close** (step 9, and any planned stop) runs
> `env.cleanup()`, awaits every running `exec`'s settlement, and only then calls
> `connection.close()`: `close()` SIGTERMs the daemon, which has no handler, so closing first leaves
> every running command alive (measured on both hosts). **Residuals, recorded and measured:**
> `setsid` escapes; background work that outlives its command's leader; owner-and-daemon group kills
> on a host without `setsid(1)`, and any terminating signal sent to the daemon itself; the daemon's
> own spawn→register window (an owner dying within microseconds of sending an `exec` frame leaked
> the whole tree in 2 of 400 local trials). They are **isolated** by the obligation that every
> attempt's environment is rooted at its own workspace and an earlier epoch's workspace is never
> reused before it is discarded. **Filesystem view and network policy are not provided** (no
> namespace sandbox is available unprivileged on either measured host: `unshare -Ur`, `unshare -Ur
> --pid --fork` and `unshare -Urn` are refused by the AppArmor user-namespace restriction locally
> and on `ubuntu-latest`, and bubblewrap is installed on neither); the read-only reviewer snapshot
> and any network policy remain P7 environment-policy obligations, and reviewers get no subprocess
> capability. Not chosen, with measured reasons: PID namespaces (unavailable unprivileged on both
> hosts — every `pidns/availability` row), a spawn journal (stop set = the registered process only;
> owner-written state), a cgroup fence (Linux-only, cgroup writability varies by host — writable
> locally, `EACCES` on `ubuntu-latest` — cooperative escape). Evidence:
> `archive/pi-durable-v2-containment-characterization.md`.

**Filesystem view: not provided by supervised execution.** A namespace sandbox is unavailable
unprivileged on both hosts: `unshare -Ur` is refused by the AppArmor userns restriction, and
bwrap is not installed. The read-only reviewer snapshot remains P7's environment obligation.

**Network policy: not provided by supervised execution.** `unshare -Urn` is unavailable on both
hosts for the same reason, so any network policy remains a P7 environment obligation.

## Consumers and reconciliation

- **The plan-workflow objective**, the first to give a worker a subprocess capability, adopts:
  - supervised execution;
  - the close order (`cleanup()` → await settlements → `close()`);
  - the setsid-wrapped daemon where `setsid(1)` exists;
  - `PERK_V2_STORE`/`PERK_V2_EPOCH` labels on every spawn;
  - the per-attempt workspace obligation;
  - the report-only sweep at open.
- **Node 3.4** carries the residual list and the two unanticipated obligations into its
  hand-off.
- **Upstream (optional).** Two pi-env changes would shrink the residuals: a SIGTERM handler that
  runs `kill_all`, which would make `close()` safe, and an exec thread that re-checks a "stopping"
  flag under the `groups` lock after `spawn`, which would close the spawn→register window. Either
  would be a pin bump, and so a re-verification.
- **Re-verify** by re-running `just test-v2-slow` on both hosts when any of these change:
  - the runner image (`ImageOS`/`ImageVersion`);
  - the kernel line;
  - any pin in the Durable family (`pi-durable`, `chord`, `pi-ai`, `pi-env`);
  - P7 or P8.

## Teardown proof

After the local `just test-v2-slow` at `b74167f3`:

- `pgrep -af perk-v2-containment` printed nothing, and so did `pgrep -af "pi-env serve"`;
- `ls /tmp | grep perk-v2-containment` printed nothing;
- `git status --porcelain` printed nothing.

The ad hoc runs above cleaned up after themselves the same way: they killed each trial's
survivors by start-time-checked identity and removed every directory. After the documentation
commit, `git status --porcelain` prints nothing.
