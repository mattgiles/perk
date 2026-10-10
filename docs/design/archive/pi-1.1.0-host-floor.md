# Record: the shared host floor and the remote install pin at Pi 1.1.0

**Status:** dated evidence record. Measured and authored 2026-10-10 (UTC) on branch `plan-2715`
(base `f6664acd`). It implements plan #2715 (Objective #2707, node 1.4): the two Pi version facts
that still named 1.0.0 move to **1.1.0** together — the shared host floor
(`shared/host-floor.yaml` `pi.min_version`) and the remote install pin (`REMOTE_PI_VERSION` in
`src/perk/run/workflow_artifacts.py`, which pins both the consumer global `pi` CLI and the consumer
worker SDK) — and the `runner-workflow` owner regenerates the managed remote artifacts. The
precedents are [`pi-subagents-0.76.1-pin.md`](pi-subagents-0.76.1-pin.md) (this record keeps its
shape), [`pi-1.1.0-dev-pins.md`](pi-1.1.0-dev-pins.md) and
[`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md).

**Verdict: the floor and the remote pin sit at exact 1.1.0, the committed remote artifacts are the
owner's render, and the raised floor is proven offline and live on the real pins. PASS.** `perk
doctor --fix` rewrote exactly one line of `.github/actions/perk-remote-setup/action.yml` and the
owner-generated `remote-setup-action` digest in `.perk/managed-state.toml`; `perk-run.yml` stayed
byte-identical; a second `--fix` was a no-op. A new lockstep test pins both committed self-repo
artifacts to the owner's render. The shipped-floor tests moved to 1.1.0 and the admission suites
gained shipped-floor readings in both planes: the previous floor (1.0.0) and `1.1.0-rc.1` are
refused, 1.1.0 and an unequal later release (1.2.0) are admitted independently of the dev pin.
The live bridge smoke passed on both the PATH `pi` (now exactly at the floor) and the pinned CLI,
each with a captured `/perk-selfcheck` showing `host sdk: 1.1.0 (floor >= 1.1.0)`.

**No certification claim.** Pi 1.1.0 is **adopted** — moved on the characterization record plus
the dev-pin and supplier-pin evidence — not **certified**. Its live certification on landed code
is a later, separate record (`pi-1.1.0-certification.md`, still pending; node 7.1 writes it). The
1.0.0 certification record ([`pi-1.0.0-certification.md`](pi-1.0.0-certification.md), verdict
PENDING) is untouched, stays historical and certifies nothing about 1.1.0. The doctor guidance
stamp (`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, 0.75.0) and its test pin, the four
`@earendil-works/*` dev pins (1.1.0), `SUBAGENTS_PACKAGE` (0.76.1), `node.min_version`
(22.19.0), `engines.node`, TypeBox, `docs/learned/` and `CHANGELOG.md` are untouched. The remote
pin now **leads** its certification by design — the same posture the supplier pin took against
the guidance stamp — and the `REMOTE_PI_VERSION` comment and contracts §8.76(b) say so.

## Registry preflight (Step 0, 2026-10-10T03:44Z)

Both halves of the STOP gate were green, so the move proceeded at 1.1.0.

- **The target.** `npm view @earendil-works/pi-coding-agent dist-tags version --json`:

  ```json
  {
    "dist-tags": {
      "legacy-node20": "0.74.2",
      "latest": "1.1.0"
    },
    "version": "1.1.0"
  }
  ```

- **The caret-floating companions.** The installed pi-coding-agent 1.1.0 declares `^1.1.0` on
  `@earendil-works/chord`, `pi-agent-core`, `pi-ai`, `pi-codemode`, `pi-mcp` and `pi-tui`, and
  pi-ai 1.1.0 declares `^1.1.0` on `@earendil-works/pi-telemetry`. For each of the seven, `npm view
  <pkg> versions --json` was recorded in full (scratch `registry-preflight.log`); the newest
  published version and the satisfier check:

  | Package | Newest published | Other `^1.1.0` satisfiers |
  |---|---|---|
  | `@earendil-works/chord` | 1.1.0 | none |
  | `@earendil-works/pi-agent-core` | 1.1.0 | none |
  | `@earendil-works/pi-ai` | 1.1.0 | none |
  | `@earendil-works/pi-codemode` | 1.1.0 | none |
  | `@earendil-works/pi-mcp` | 1.1.0 | none |
  | `@earendil-works/pi-tui` | 1.1.0 | none |
  | `@earendil-works/pi-telemetry` | 1.1.0 | none |

  Every list ends `…, "1.0.3", "1.0.4", "1.1.0"` (chord, pi-codemode and pi-mcp start at `0.0.0` /
  `0.0.1`, pi-telemetry at `0.84.0`, the others at `0.74.0`). The resolved remote set at this date
  is therefore exactly the characterized one: pi-coding-agent 1.1.0 with all seven companions at
  1.1.0.
- **Surface census (Gate B).** `git status --porcelain` was empty. The `1\.0\.0` sweep (outside
  `.worktrees/`, `node_modules/`, `.pi/npm/`, `docs/library/`, `docs/learned/`,
  `docs/design/archive/`, `docs/planning/`, `CHANGELOG.md`, `package-lock.json`) listed 277 lines:
  the planned surfaces plus unrelated matches classified before editing — perk-version fixtures
  (`tests/test_perk_dev_*`, `test_git.py`, `test_upgrade_notice.py`, `test_json_goldens.py`,
  `tests/golden/`), fake `npm:…@1.0.0` packages (`toolPolicy`, `ownNamesActivation`,
  `toolGating`, `harness.ts`), `buildSelfcheckReport`'s perk `version: "1.0.0"` fixtures, the
  semver grammar comments and tests, the `piAiCompatGuard.test.ts` header, the `settings.py`
  "verified at Pi v1.0.0" comment, the reverify guide, `native-discovery-pilot.md`'s archive file
  name, and the contracts MCP-restoration / `SystemMessage` / "Pi 0.99.2 and 1.0.0 always pass an
  initial active set" observations (historical, left). `tests/test_doctor.py`'s `PiHost(...,
  "1.0.0", ...)` stub is an explicit-argument fixture like `tests/test_env.py`'s rows and was left.
  One shipped-floor reader was misclassified at census and caught by the offline proof (see
  "Planning-time assumptions the measurement falsified").
- **Rebase.** `git fetch origin && git rebase origin/main` → `Current branch plan-2715 is up to
  date.` Everything below ran on `f6664acd` plus this change.

## Snapshot matrix

| Component | Before | After | Provenance |
|---|---|---|---|
| Host floor `pi.min_version` | 1.0.0 | **1.1.0** | `shared/host-floor.yaml` |
| Host floor `node.min_version` | 22.19.0 | unchanged | `shared/host-floor.yaml` |
| `REMOTE_PI_VERSION` | 1.0.0 | **1.1.0** | `src/perk/run/workflow_artifacts.py` |
| PATH `pi` | 1.1.0 | 1.1.0 (now exactly at the floor) | `pi --version` (`~/.local/share/mise/installs/node/26.3.0/bin/pi`) |
| Pinned CLI | 1.1.0 | 1.1.0 | `$WT/node_modules/.bin/pi --version` |
| Root SDK | `@earendil-works/pi-coding-agent` 1.1.0 | unchanged | `$WT/node_modules/@earendil-works/pi-coding-agent/package.json` |
| Dev pins | four `@earendil-works/*` at exact 1.1.0 | unchanged | `package.json` `devDependencies` |
| `$WT` supplier | pi-subagents 0.76.1 | unchanged | `$WT/.pi/npm/node_modules/pi-subagents/package.json` |
| `node` | v26.3.0 | — | `node --version` |

The PATH CLI was already at the new floor, so the floor raise locks out no operator host; the pins
do not upgrade the PATH CLI.

## The owner run (`uv run perk doctor --fix` in `$WT`)

The first run's `Fixed` block:

```text
Fixed
  - .github/actions/perk-remote-setup/action.yml: updated
  - .perk/local.toml: created
  - .perk/managed-state.toml: updated
```

`.perk/local.toml` is gitignored (`.gitignore:18:/.perk/local.toml`). The tracked footprint beyond
Step 1's three source files was exactly the two expected owner outputs; no other managed artifact
and no unmanaged tracked path changed, so the drift policy (retain + record any other managed
change, stop on an unmanaged one) had nothing to act on:

```diff
--- a/.github/actions/perk-remote-setup/action.yml
+++ b/.github/actions/perk-remote-setup/action.yml
@@ -25,7 +25,7 @@ runs:
 
     - name: Install pi
       shell: bash
-      run: npm install -g @earendil-works/pi-coding-agent@1.0.0
+      run: npm install -g @earendil-works/pi-coding-agent@1.1.0
 
     # The npm package wraps cloc's Perl script (the Ubuntu runner ships Perl). Non-fatal at
     # submit time — a missing cloc degrades the PR's change stats to a note — but installed so
--- a/.perk/managed-state.toml
+++ b/.perk/managed-state.toml
@@ -18,7 +18,7 @@ hash = "sha256:b794695bee28c07cee56bfd2c21fd6126f6cd35fdad64d150c72818a6634820b"
 path = ".github/actions/perk-remote-setup/action.yml"
 kind = "file"
 version = "4.0.0"
-hash = "sha256:559c200d0a9882ee7c82f8d31eb261bf436175b057fc6011943aafbbef3423c7"
+hash = "sha256:d09a18aabf9a327d2795a79930a184a200e0e2533d1b6f65d0d18459995410b2"
```

`node-version: "22.19.0"` is unchanged; `git diff --stat -- .github/workflows/perk-run.yml` was
empty (its template carries no Pi version), so the `runner-workflow` digest did not move. Only the
`[managed.artifacts.remote-setup-action]` `hash` moved; its `version` stays `4.0.0`. The new digest
is the file's own SHA-256 (`shasum -a 256` → `d09a18aa…10b2`; the committed 1.0.0 file hashed
`559c200d…23c7`).

The second `--fix`, with every owner output retained, printed no `Fixed` block and left `git
status --porcelain` byte-identical (idempotent). `uv run perk doctor --verbose` then reported:

```text
   ✓ pi: pi ok — 1.1.0 (floor >= 1.1.0)
   ✓ runner-workflow: runner-workflow converged
   ✓ artifact-health: 7 managed artifacts up-to-date
✓ healthy (42 ok)
```

`perk doctor --json` carried `"healthy": true` and the same three rows. `subagent-compat` warns
truthfully (installed 0.76.1, stamp 0.75.0), unchanged by this move.

Both `--fix` runs also reported the known `Fix failures` entry: `skills delivery failed: \`skills
update --sync\` exited 1` with a `conflict` for every skill in this worktree's gitignored,
`skills` CLI-managed `.agents/skills/`. It touches no tracked path and is unrelated to the move.

## Offline proofs

| Check | Result |
|---|---|
| `uv run pytest -n0 -q` over `test_host_floor`, `test_pi_host`, `test_workflow_artifacts`, `test_launch`, `test_launch_materialize`, `test_resume_session_cmd`, `test_plain_session`, `test_session_resume`, `test_env`, `test_managed_state`, `test_doctor`, `test_cli_import_tiers`, `test_packaging` | **755 passed** — including `test_remote_pi_version_is_a_release_at_or_above_the_floor`, `test_pi_toolchain_pin_lockstep`, the default-floor probe test, the four shipped-floor readings and the new `test_committed_self_repo_remote_artifacts_are_the_owners_render` |
| The lockstep test is not vacuous | with the 1.0.0 `action.yml` restored (`git stash push -- …/action.yml`) it **failed**; with the owner output back it passed |
| `node --test --test-reporter=spec` over `hostFloor`, `hostAdmission`, `entryAdmission`, `index`, `pi/v1/selfcheck` | **76 / 76**; the new `the shipped floor: the previous floor and its prerelease are refused; the floor and an unequal later release are admitted` and the `precondition: the installed SDK this suite runs on is admitted by the shipped floor` line both `✔` on the installed 1.1.0. `entryAdmission`'s cold processes refuse the below-floor (`0.95.0`) and `1.1.0-rc.1` fake SDKs before any SDK symbol links, and the at-floor lying SDK (`1.1.0`) is `runtime_init` |
| `just test-js-fast` (explicit; TAP beside `dot`) | **2797 / 2797**, 0 skipped |
| `just test-js-slow` (explicit; TAP beside `dot`) | **1001 / 1001**, 0 skipped |
| `node --test --test-reporter=spec extension/worker/stageExecutionE2e.test.ts` (in the slow tier; the worker admitted at its entry against the shipped floor) | **34 / 34** |
| `run_ci` subset `lint-py,lint-js,typecheck-py,typecheck-js,test-py-fast,test-js` | all ✓ |
| `just docs-check` | green |

**Final gate** at `d32b062c` (the complete change). This paragraph is the only later edit, and it
is docs-only. Eight rows **executed** (`lint-py`, `lint-js`, `typecheck-py`, `typecheck-js`,
`test-py-fast`, `test-py-slow` (which re-runs the live bridge smoke on the PATH `pi`), `test-js`
(the fast node:test tier) and `docs-check`); two were **glob-skipped** and are not runs
(`typecheck-prose-review`, `changelog-check`). The slow node:test tier, which carries
`extension/worker/stageExecutionE2e.test.ts` and is outside the `test-js` row, ran explicitly
above (`just test-js-slow`, 1001 / 1001).

```text
perk CI: all checks passed.
✓ lint-py (2s)
✓ lint-js (10s)
✓ typecheck-py (8s)
✓ typecheck-js (77s)
⊘ typecheck-prose-review (skipped — no changed files match tools/prose-review/**,package.json,package-lock.json)
✓ test-py-fast (320s)
✓ test-py-slow (139s)
✓ test-js (68s)
✓ docs-check (352s)
⊘ changelog-check (skipped — no changed files match CHANGELOG.md)
```

## Live proofs on the real pins

| Host | `tests/test_native_sdk_bridge_live.py` (`-n0 -v -rfEs`) |
|---|---|
| PATH `pi` 1.1.0 (`~/.local/share/mise/installs/node/26.3.0/bin/pi`) | **2 passed, 1 skipped** in 10.73s |
| Pinned CLI 1.1.0 (`PATH="$WT/node_modules/.bin:$PATH"`) | **2 passed, 1 skipped** in 2.36s |

The skip on both is the below-floor arm: `SKIPPED [1] tests/test_native_sdk_bridge_live.py:152:
needs a below-floor PATH pi (this one is admitted)`.

### Captured `/perk-selfcheck` transcripts

A green pytest run surfaces no transcript, so each host got one explicit launch from `$WT` in the
test's own posture — the scrubbed variables, offline mode, the placeholder key and a fresh
throwaway agent dir (what the suite's autouse fixture gives the test):

```bash
AGENT_TMP="$(mktemp -d -t perk-selfcheck-agent)"
env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
    -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
    PI_OFFLINE=1 PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR="$AGENT_TMP" \
    ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-perk-live-smoke-placeholder-never-sent}" \
  pi --approve --mode json -p /perk-selfcheck
```

The second launch ran the same with a fresh `AGENT_TMP` and `PATH="$WT/node_modules/.bin:$PATH"`.
Both exited 0 with 0 `Failed to load extension` lines. The PATH-host transcript, after its
session header line (2026-10-10T04:07:44Z):

```text
perk: perk-selfcheck — running…
perk: selfcheck — 4.0.0: ok; shared=ok; ambient=reached (append=5376c); agents=reached (files=1); bridge=installed
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 5376c
  context-files: 1 file(s), 7039c — $WT/AGENTS.md=7039c
  skills: 16 visible + 23 hidden; prompt-section=8885c
  tools: 50 active / 66 registered; schemas=57880c; guidelines=0c; snippets=4448c
    per source: ..=37 (40160c); builtin=5 (3327c); npm:@ff-labs/pi-fff=2 (3134c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents@0.76.1=3 (5248c); npm:pi-web-access=1 (314c)
  discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
  host sdk: 1.1.0 (floor >= 1.1.0)
  native sdk bridge: installed (roots=2, specifiers=8)
    host: ~/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js
    roots: 2 — $WT/.pi/npm/node_modules/pi-subagents, $WT/.pi/npm/node_modules/pi-web-access
```

The pinned-CLI transcript (2026-10-10T04:07:46Z) is identical line for line except the `host:`
line, which reads `host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`. Node
1.1's T9 selfcheck and T12c doctor row on the same 1.1.0 host printed `1.1.0 (floor >= 1.0.0)`;
both now read `(floor >= 1.1.0)` — the extension loaded from the checkout re-read the raised
bundled floor.

## Planning-time assumptions the measurement falsified

- **The shipped-floor test list was one short.**
  `tests/test_env.py::test_pi_with_undecodable_output_is_an_unverifiable_row_not_a_crash` runs the
  REAL probe (`env._check_pi()` against a script printing `\377`) and so reads the bundled floor;
  it asserted `remediation.startswith("Reinstall Pi (>= 1.0.0 required): ")`. The plan's census —
  and this session's Gate B classification — filed `tests/test_env.py` wholly under the
  explicit-argument rows (the `_pi_host(..., "1.0.0", ...)` stubs, which are explicit and stay).
  The targeted pytest run failed it; it moved to `1.1.0` under the plan's own D3 rule (a
  shipped-floor reader moves), with its comment noting the shipped floor. No test was weakened or
  skipped.
- Nothing else differed: the registry answer, the host state, the owner footprint and the live
  results all matched the planning-time expectation.

## Consequences and residuals

- **The floating remote graph (standing residual).** Only `@earendil-works/pi-coding-agent` is
  exact in either remote install. Pi has shipped no `npm-shrinkwrap.json` since 1.0.1, its seven
  companions are `^1.1.0`, and both remote installs (`npm install -g …@1.1.0` and the consumer
  worker-deps `npm install … --prefix .pi/npm --legacy-peer-deps`) run without a lockfile — so a
  published `1.1.x`/`1.y` companion release would be resolved by a fresh remote install while
  `latest` stays 1.1.0. The registry preflight above is point-in-time protection only. Handed to
  node 7.1 (the consumer live leg of the remote composite) and node 7.2 (the reverify procedure's
  "update every pin surface" step), separately from the deferred consumer live certification. No
  npm mechanism pins a global install's transitives without a shrinkwrap, so it is not fixed here.
  The self-repo worker (`npm ci`) and every local proof above are lockfile-bound and do not see
  it.
- **Dogfood gate.** This implement session ran the pre-change extension loaded at its start and
  proves nothing about the raised floor in a fresh process. The node's dogfood gate — perk driving
  the next plan in a fresh host process whose PATH `pi` is 1.1.0 — is credited to the first
  `/objective-plan` (or any perk door) session launched on `main` after this lands. The planning
  session of this plan (a fresh process on PATH `pi` 1.1.0, root SDK 1.1.0, `.pi/npm` pi-subagents
  0.76.1) is node 1.3's credited dogfood.
- **Residuals for 7.1/7.2.** The "an older host settles as before" clause of the driven-compaction
  docs and seam header now describes an unsupported host; the reverify guide's pin-surface list;
  the true-up ledger's "Current state" column.
- **`CHANGELOG.md`.** No bullet was hand-authored (the release tooling rolls `[Unreleased]` from
  its `<!-- As of … -->` marker). A "Pi 1.1.0 is the minimum host" bullet, if wanted before the
  next release, is a separate follow-up commit stamped with this change's landed hash.
- **`/learn` candidates.** Not edited here:
  1. `docs/learned/workflow/remote-runner.md` calls the SDK spec in `_WORKER_DEPS_CONSUMER`
     "deliberately unpinned" — stale since the floor landed (it is pinned to
     `REMOTE_PI_VERSION`); the remote graph's caret float after the shrinkwrap removal is a new
     fact for that doc.
  2. `docs/learned/workflow/init-doctor.md` "At the 1.0.0 floor raise it regenerated `action.yml`
     and `managed-state.toml`" — the 1.1.0 instance, the never-revert-an-owner-output footprint
     discipline, and the new lockstep test that now catches a forgotten regeneration in CI.
  3. `docs/learned/pi/extension-api.md` § "Host admission at the SDK boundary" — its dated note
     ("the pins are at `1.0.0` and the host floor is `1.0.0`") and the lockout rule's precondition
     (it bites only when the operator host is below the new floor).
  4. `docs/learned/toolchain/worktree-node-modules.md` § "Five version facts" — the remote pin is
     adopted with the floor and certified later; the family-wide registry preflight; a real-probe
     test (`env._check_pi()` with no stub) is a shipped-floor reader even inside a file of
     explicit-argument rows.
- **Teardown.** The registry outputs, the census, the doctor logs, the pytest/node logs, the TAP
  reports and both selfcheck transcripts live under the run's gitignored scratch directory
  (`.perk/workflow/scratch/runs/…/agent/`); the two throwaway agent dirs are under the system temp
  dir. Nothing there was committed.
