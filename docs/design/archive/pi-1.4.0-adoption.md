# Record: perk adopts Pi 1.4.0 + pi-subagents 0.81.0

**Status:** dated evidence record. Measured and authored 2026-10-24 on branch `plan-2768` (base
`33398129`). It implements plan #2768 (Objective #2767, node 1.1): perk's adopted pair moves from
**Pi 1.1.0 + pi-subagents 0.76.1** to **Pi 1.4.0 + pi-subagents 0.81.0** in one change. The ledger
of record is [`../../planning/pi-and-subagents-assessment-2026-10-24.md`](../../planning/pi-and-subagents-assessment-2026-10-24.md);
the shape follows [`pi-1.1.0-dev-pins.md`](pi-1.1.0-dev-pins.md) and
[`pi-subagents-0.76.1-pin.md`](pi-subagents-0.76.1-pin.md).

**Verdict: ADOPTED, not certified.** The pair is adopted on characterization + offline evidence
(the assessment plus the gates below). This record certifies nothing: the live certification of
Pi 1.4.0 + pi-subagents 0.81.0 is owed, and the previous certification record
([`pi-1.1.0-certification.md`](pi-1.1.0-certification.md)) holds 3 required FAILs (W4, W6, W7a),
so the support claim stays held. The doctor guidance stamp
(`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`) is untouched at **0.75.0**; `subagent-compat` keeps
warning by design. `BRIDGE_SCHEMA` and `NATIVE_SDK_CENSUS` are unchanged.

## The five version facts

| Fact | Before | After |
|---|---|---|
| Dev pins (`package.json`) | `@earendil-works/{pi-coding-agent,pi-ai,pi-tui,pi-agent-core}` 1.1.0 | the same four at 1.4.0; `typebox` 1.3.27 unchanged |
| Host floor (`shared/host-floor.yaml`) | `pi.min_version: "1.1.0"` | `"1.4.0"`; Node lines unchanged |
| Adopted Pi pin + pinned install set | 1.1.0; seven companions incl. `chord`; eight exact specs | 1.4.0; six companions (`pi-agent-core`, `pi-ai`, `pi-codemode`, `pi-mcp`, `pi-telemetry`, `pi-tui`); ONE exact spec — `npm install -g @earendil-works/pi-coding-agent@1.4.0` |
| Supplier pin (`SUBAGENTS_PACKAGE`) | `npm:pi-subagents@0.76.1` | `npm:pi-subagents@0.81.0` |
| Guidance stamp | 0.75.0 | 0.75.0 (untouched) |

The single spec rests on Pi ≥ 1.3.0 declaring its companions at exact versions;
`tests/test_pi_host.py::test_the_family_declares_itself_exactly_in_the_characterized_lockfile`
pins that premise separately from the closed-names test.

## The lockfile

`just bump-pi 1.4.0`; `npm` 11.20.0, Node v26.12.1. The delta (51 insertions / 51 deletions):

- the four root devDependency pins → 1.4.0;
- every top-level `@earendil-works/*` entry → 1.4.0 (version, resolved, integrity); pi-agent-core,
  pi-ai and pi-coding-agent's internal declarations move from `^1.1.0` to exact `1.4.0`;
- `node_modules/@earendil-works/chord` removed — by the install itself;
- `node_modules/marked-cjk-friendly@0.1.2` added (a new pi-tui dependency).

No incidental re-resolution occurred (no `@aws-sdk/*`, `@smithy/*`, `ws` or `@babel/runtime`
moves), so **nothing was trimmed**. `npm prune` printed `up to date in 818ms` (no orphan left to
remove). Validation: `npm install --package-lock-only` byte-identical; `npm ci` green (525
packages); the `npm ls` gate exit 0; `npm ls` reports nothing `extraneous`; `npm ls
@earendil-works/chord` → `(empty)`; the lockfile's top-level `node_modules/@earendil-works/*` keys
are exactly the seven family names. Committed lockfile SHA-256 prefix `df5ff7ff92eb852c`.

## The forced repairs

`npm run typecheck` after the bump reported exactly the three diagnostics the assessment
predicted, and zero after the repairs:

1. `extension/pi/v1/contextInjection.ts(183,15)`: TS2339 `prompt` does not exist on
   `BeforeAgentStartCustomEvent`;
2. `extension/substrate/bindingDelivery.ts(256,15)`: the same;
3. `tools/prose-map/selector.ts(58,3)`: TS1360 — `reachesTools` missing from the
   `TOOL_FIELD_POLICIES` `satisfies` record.

- **R1** — both `before_agent_start` hooks scan `event.prompt` only on a user start
  (`event.messageType === "user"`); a custom start (pi-subagents' completion wake) proceeds to the
  projection dedup. New pure-hook tests drive a custom event WITHOUT a `prompt` property; reverting
  either guard to an unconditional scan fails 5 tests (contextInjection) and 2 tests
  (bindingDelivery) — measured by a temporary revert.
- **R2** — `reachesTools` classified `non-prose`.
- **R4** — the harness calls the typed two-argument `emitBeforeAgentStart(trigger,
  systemPromptOptions)` (passing `{ cwd }`: 1.4.0's `BuildSystemPromptOptions` requires `cwd`) and
  gains `emitBeforeAgentStartCustom`; `btw.test.ts` strips Pi's two fake-cursor APC markers
  (pinned to `renderFakeCursor`) from the overlay's input row only — the 6 BTW failures the
  assessment measured are the 6 observed before the repair.

## The host install shape

A real global single-spec install into a scratch prefix (`npm install -g --prefix <tmp>
@earendil-works/pi-coding-agent@1.4.0`, 119 packages) placed ONE top-level global package with the
six companions nested inside it (`lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/*`)
and linked only `bin/pi` (no `pi-ai` bin, unlike the 1.1.0 eight-spec install). The real
`probe_pi_host` on it answered `admitted`, observed `1.4.0` — the family check resolves the
nested layout.

## Convergence

`uv run perk init --no-interactive`, run in the worktree with the isolated Pi first on PATH, wrote
exactly the three expected managed files: `.pi/settings.json` (`npm:pi-subagents@0.76.1` →
`@0.81.0` in place), `.github/actions/perk-remote-setup/action.yml` (the `Install pi` line → the one
exact spec; `perk-run.yml` byte-identical) and `.perk/managed-state.toml` (the `settings-wiring`
and `remote-setup-action` hashes only). Init then stopped at its skills-delivery step
(`skills update --sync` reported `conflict` for every skill — the worktree's `.agents/skills`
symlinks point into the main checkout's skills cache; environmental, unrelated to the bump) after
creating the gitignored `.perk/local.toml` scaffold. No other tracked file moved. Bare
`uv run perk doctor`: `pi` ok `1.4.0 (floor >= 1.4.0)`, `settings-wiring` and `runner-workflow`
converged, `subagent-compat` warn (installed 0.76.1 at that point, stamp 0.75.0).

## The supplier

The worktree's `.pi/npm` was an independent clonefile stage (inode of `package.json` 482991377 in
the worktree vs 481703563 in the main checkout). With no `/reload` in the session:
`rm -rf .pi/npm/node_modules/pi-subagents`, then `npm install pi-subagents@0.81.0 --prefix .pi/npm
--legacy-peer-deps` → installed `0.81.0`. The main checkout's four `.pi/npm` metadata files were
hashed before and after and are unchanged (SHA-256 prefixes: `package.json` `5008364f3880`,
`package-lock.json` `1bc6af5bb460`, `node_modules/.package-lock.json` `d5095cb4d3da`,
`node_modules/pi-subagents/package.json` `6302e37ac9dc` — still 0.76.1 there).
`node --test extension/substrate/nativeSdkBridge.test.ts`: 32/32, the census drift guard RAN
(not skipped) and passed with the unchanged eight specifiers.

## Gates (the isolated environment)

PATH `pi` = `/tmp/perk-pi-1.4.0/node_modules/.bin/pi`, `pi --version` 1.4.0 (the global 1.1.0
untouched); Node v26.12.1; supplier 0.81.0 under the worktree's `.pi/npm`.

| Gate | Result |
|---|---|
| `npm run typecheck` | PASS (0 diagnostics) |
| targeted node:test (contextInjection, bindingDelivery, btw, hostAdmission, hostFloor, selfcheck, index, entryAdmission, nativeSdkBridge, piAiCompatGuard) | PASS 210/210 |
| targeted pytest (pi_host, host_floor, env, doctor, init_onboarding, init_idempotent, npm, workflow_artifacts, packaging, launch, launch_materialize, native_sdk_bridge_live, subagent_agents, repo_local_agents, native_sdk_bridge_parity, the three session refusal suites) | PASS 985, 1 skip (the designed below-floor control) |
| `tests/test_native_sdk_bridge_live.py` | `test_the_installed_pi_subagents_is_the_managed_pin` PASSED; `test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded` PASSED; `test_a_below_floor_real_pi_refuses_to_load_perk` SKIPPED by design ("needs a below-floor PATH pi (this one is admitted)") |
| `just prose-review-test` / `just prose-review-check` | PASS (560 pytest; 367 node:test; typecheck + build green) |
| `just test-js-slow` | PASS |
| run-all `run_ci` | the final pre-submit gate; its result is recorded in the PR body |

Fresh-process `/perk-selfcheck` (`pi --approve --mode json -p /perk-selfcheck` from the worktree,
the live module's env: `PI_OFFLINE=1`, `PERK_SKIP_VERSION_CHECK=1`, a placeholder
`ANTHROPIC_API_KEY`, the scrubbed `PERK_*`/`PI_SUBAGENT_CHILD*` vars, a scratch agent dir), exit 0:

```
perk: selfcheck — 4.1.0: ok; shared=ok; ambient=reached (append=5376c); agents=reached (files=1); bridge=installed
    per source: ..=37 (39956c); builtin=5 (3327c); npm:@ff-labs/pi-fff=2 (3134c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents@0.81.0=1 (428c); npm:pi-web-access=1 (314c)
  host sdk: 1.4.0 (floor >= 1.4.0)
  native sdk bridge: installed (roots=2, specifiers=8)
```

No report wave was launched from the implement session (the pre-swap supplier is Chord-dependent
on this host; the post-swap supplier needs a fresh process).

## Falsified planning-time assumptions

- `npm prune` was expected to remove the Chord orphan; the bump's own `npm install` removed it, and
  prune was a no-op.
- A lockfile trim was expected; npm produced no incidental churn, so none was needed.
- The harness call's options were planned as `{}`; 1.4.0 types `cwd` as required, so the harness
  passes `{ cwd }`.
- The global single-spec install nests the companions under the package rather than placing
  top-level siblings (the 1.1.0 eight-spec shape); the probe resolves either.

## The post-land cutover (operator, fresh process)

0. **Prerequisite:** finish or cancel every outstanding wave/child and close every perk session on
   the machine — a running 0.76.1 session resolves the host package by path at its next
   background-runner launch and breaks once the global prefix holds 1.4.0.
1. `npm install -g @earendil-works/pi-coding-agent@1.4.0` (= `PI_INSTALL_COMMAND`; or
   `perk doctor --fix` from the main checkout); `perk doctor`'s `pi` row then reads
   `1.4.0 (floor >= 1.4.0)`. Optionally `npm uninstall -g @earendil-works/chord
   @earendil-works/pi-agent-core @earendil-works/pi-ai @earendil-works/pi-codemode
   @earendil-works/pi-mcp @earendil-works/pi-telemetry @earendil-works/pi-tui` to drop the stale
   1.1.0 siblings.
2. The main checkout: `npm ci`; its supplier walks forward to 0.81.0 at the next Pi launch via the
   committed `.pi/settings.json` pin.
3. Sibling worktrees on pre-bump branches are rebased onto main before waves run there, or closed;
   perk keeps no separate old-host prefix.
4. Remove `/tmp/perk-pi-1.4.0`.

## Owed

- The live certification of Pi 1.4.0 + pi-subagents 0.81.0 — node 3.1.
- The W4/W6/W7a cells' repair or re-specification — node 2.1.
- `/learn` follow-ups: `docs/learned/pi/subagents.md` § Sources / § History (pin 0.81.0; the
  custom-message wake), `docs/learned/workflow/borrowed-packages.md` and
  `docs/learned/workflow/report-waves.md` (their pin statements),
  `docs/learned/toolchain/worktree-node-modules.md` § "Pi pin-bump mechanics" (the single-spec
  shape, the login-shell PATH fact, the shared-host cutover prerequisite).
