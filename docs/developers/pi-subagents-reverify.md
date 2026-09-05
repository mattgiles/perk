# How to re-verify the pi-subagents compatibility baseline

This page is a **how-to guide**. Use it when perk's borrowed `pi-subagents` engine has moved
under the guidance — the package is deliberately **unpinned** (owner-affirmed; a future pin is a
separate one-line decision that this recorded-baseline procedure makes trivial), so compatibility
rests on a *tested baseline* plus this re-verify ritual, never on a version constraint.

**When to re-verify:**

- `perk doctor`'s `subagent-compat` check **warns** (a probe marker or file vanished, or the
  `validateWorkflowScript` behavior arm reported an invalid script);
- the check is `ok` but its detail carries the *installed ≠ guidance-verified* note (a version
  bump with a still-matching surface — mechanics beyond the markers are source-read-derived and
  unverified at the new version);
- you are about to **build on new engine mechanics** (anything the probes don't cover: wait/wake
  semantics, the supervisor channel, workflow child launch policy).

**Prerequisites:** a checkout of the perk repository with both toolchains installed
(`just setup`). The live smoke additionally needs model credentials (the parent session's
default model and the `[models.subagents] objective-explorer` child model).

## Repo-local development host baseline

The development host pins **five** packages together at `0.85.1`: `@earendil-works/pi-coding-agent`,
`pi-ai`, `pi-tui`, `pi-server`, and `pi-client` (all with the same scope). Server/client are
explicit dev dependencies because Pi's published host does not supply the background runner's
full runtime peer graph. This is a **repo-local workaround**, not certification or automatic
repair of consumers' global Pi installs. Do not patch node_modules, reinstall globally, change
child mode, or pin pi-subagents to make a failing baseline pass. `just bump-pi VERSION` maintains
all five dev pins; published wildcard peers, zero runtime dependencies, and doctor report-only
behavior are unchanged.

Install **in the worktree under test** (`npm install`), not just its ancestor checkout. Check
`npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-server @earendil-works/pi-client --depth=0`,
then `npm run typecheck`, `node --test extension/piAiCompatGuard.test.ts`, and
`uv run pytest tests/test_packaging.py::test_pi_toolchain_pin_lockstep -q`. Commit before live probes.

Probe the installed engine using its own jiti and the absolute **repo-local** Pi package root:

```bash
node <<'JS'
const { createRequire } = require('node:module');
const path = require('node:path');
const engine = path.resolve('.pi/npm/node_modules/pi-subagents');
const engineRequire = createRequire(path.join(engine, 'package.json'));
const { createJiti } = engineRequire('jiti');
const jiti = createJiti(path.join(engine, 'package.json'));
const { resolveHostPeerAliases } = jiti(path.join(engine, 'src/runs/background/runner-aliases.ts'));
const host = path.resolve('node_modules/@earendil-works/pi-coding-agent');
const result = resolveHostPeerAliases(host);
console.log(JSON.stringify({ host, ...result }, null, 2));
if (result.missing.length) process.exitCode = 1;
JS
```

Require `missing: []`, record every resolved path and any supplemental aliases, then run the
existing `just subagents-smoke` from the clean commit. Inspect the child receipt/artifact metadata
for a real background runner process: a PASS under a foreground override is not this baseline.
Stop on install, resolution, or launch failure and retain run/status/cwd/ref and clean-state or
diff evidence; another version or execution protocol requires owner direction.

Use a **fresh process** for live review doors: put `$PWD/node_modules/.bin` first on PATH for
normal `uv run perk plan` draft handoffs, or launch `$PWD/node_modules/.bin/pi` directly for a
bare interactive probe after removing inherited `PERK_RUN_ID` and `PI_SESSION_FILE`. Keep Pi
open between model turns. The implementing session predates its dependencies/bindings and is
not a valid live host. See the scoped [native streaming record](../design/archive/pi-subagents-native-streaming-dogfood.md)
for the background baseline and the five human-operated streaming legs; unobserved legs are not passes.

## Steps

1. **Read the installed version.**

   ```bash
   node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version"
   ```

   Compare against `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` in
   `src/perk/convergence/doctor/checks.py`.

2. **Run the doctor probes.**

   ```bash
   just perk doctor
   ```

   The `subagent-compat` check runs the substring probes over the installed source AND the
   behavior arm: the installed engine's `validateWorkflowScript` over the shared representative
   wave script (`shared/subagents/representative-wave-script.js`). A skip note in the detail
   (`behavior probe skipped (…)`) means the behavior arm could not evaluate — investigate the
   named reason; it is never a divergence by itself.

3. **Run the live smoke from a clean committed tree.**

   ```bash
   just subagents-smoke
   ```

   Opt-in, dev-only, never part of `just ci` — it drives a real headless `pi --mode json -p`
   session through one `explore_objective_node` report-wave lifecycle on the installed engine.
   Run it from a **clean committed tree** so the recorded `perk @ <commit>` identifies the code
   actually exercised (the report flags a dirty tree).

4. **Source-re-verify the deeper mechanics.** The probes are surface tripwires; the mechanics
   perk's guidance actually leans on are enumerated in `docs/learned/pi/subagents.md` under its
   version anchor (supervisor-channel delivery and wakes, the typed child runtime config, the
   omitted-async semantics, the in-process async workflow host, structured output, the v1 RPC
   envelope). Read the installed source at
   `.pi/npm/node_modules/pi-subagents/src/` and confirm each claim still holds.

5. **Update the probe table.** Reconcile `_SUBAGENT_COMPAT_PROBES` per the tripwire-marker
   pattern (pin the positive literal whose *disappearance* signals the architectural change —
   the pattern is spelled out at the table's header comment and in
   `docs/learned/pi/subagents.md`), bump `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, and update the
   exact-pin test in `tests/test_doctor.py`
   (`test_subagent_compat_acceptance_probe_is_pinned_exactly`) plus the superset file-list and
   divergence-anchor tests as needed.

6. **Reconcile the learned docs' version anchors.** `docs/learned/pi/subagents.md` (the version
   anchor blockquote + any mechanics that moved) and `docs/learned/workflow/report-waves.md`
   (the doc-boundary name list and any currency notes).

7. **Update the user-docs probe listing.** The `subagent-compat` paragraph in
   `docs/user-docs/reference/cli/setup-and-health.md` enumerates the probed surfaces — keep it
   in lockstep with the table (and `shared/contracts.md`'s doctor-groups bullet if the check's
   shape changed).

8. **For a full baseline re-verify, record the evidence.** Author a dated evidence note in
   `docs/design/archive/` (the archive location is the status signal) naming the baseline
   matrix — perk @ the smoke-run commit, the pinned Pi version, the installed pi-subagents
   version — the smoke run's verbatim facts, and the re-verified mechanics. The 0.65.1
   baseline record (`docs/design/archive/pi-subagents-native-baseline-dogfood.md`) is the
   template.

## The standing pin decision

pi-subagents stays **unpinned** (owner-affirmed): perk tracks the engine's latest and pays for
it with this early-warning + re-verify discipline instead of a pin/upgrade lifecycle. If drift
ever becomes too expensive, pinning is a one-line `.pi/settings.json` change — and the recorded
baseline names exactly which version to pin.
