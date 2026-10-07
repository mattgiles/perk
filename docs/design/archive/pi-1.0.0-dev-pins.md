# Record: perk's Pi development pins at exact 1.0.0

**Status:** dated evidence record. Measured and authored 2026-10-07 on branch `plan-2676`
(base `e108044d`). It implements plan #2676 (Objective #2656, node 4.2): perk's
`@earendil-works/*` development pins move from exact `0.99.2` to exact **`1.0.0`**, and the two
pins perk never imports, `@earendil-works/pi-client` and `@earendil-works/pi-server`, are
dropped. The precedents are [`pi-0.99.2-baseline-verification.md`](pi-0.99.2-baseline-verification.md)
(the last pin bump and its lockfile trim) and
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) (whose "4.2 fix list" this
record re-measures).

**Verdict: the dev pins and the lockfile sit at exact 1.0.0.** Four `@earendil-works/*`
devDependencies remain (`pi-coding-agent`, `pi-ai`, `pi-tui`, `pi-agent-core`), each `"1.0.0"`;
`typebox` stays `1.3.27`. tsc (root, docs-site, prose-review), ty, ruff, Biome, both node:test
tiers and the full pytest suite are green on the 1.0.0 install. Two test-only repairs were
needed (rung 3, below); no production code changed.

**No floor claim.** This record certifies nothing and gates nothing. The host floor
(`shared/host-floor.yaml`), the remote install pin (`REMOTE_PI_VERSION`), the pi-subagents
supplier pin and the guidance stamp are untouched. 5.1's certification can read this record for
"the dev pins and lockfile sit at exact 1.0.0", with the one floating transitive named below.

## Snapshot matrix

| Component | Version | Provenance |
|---|---|---|
| Dev pins | `@earendil-works/{pi-agent-core,pi-ai,pi-coding-agent,pi-tui}` 1.0.0; `typebox` 1.3.27; `typescript` 6.0.3; `@types/node` 22.19.19; `@biomejs/biome` 2.4.16 | `package.json` `devDependencies`; the lockfile root entry mirrors it |
| Top-level dist on disk | `node_modules/@earendil-works/{pi-coding-agent,pi-ai,pi-tui,pi-agent-core}` 1.0.0; `typebox` 1.3.27 | each package's own `package.json`, read after `npm ci` |
| Floating top-level transitive | `node_modules/@earendil-works/pi-telemetry` **1.0.4** (declared `^1.0.0` by top-level pi-ai). Recorded, not held | its own `package.json`; perk never imports it |
| Nested (shrinkwrapped) dist | `pi-coding-agent/node_modules/@earendil-works/{chord,pi-agent-core,pi-ai,pi-codemode,pi-mcp,pi-telemetry,pi-tui}` 1.0.0; nested `typebox` 1.3.27 | each package's own `package.json`; the lockfile's 146 nested entries match the tarball's `npm-shrinkwrap.json` one for one (0 mismatches) |
| Absent | no `pi-client`, `pi-server`, `pi-protocol`, `chord` or `ignore` at top level | `ls node_modules/@earendil-works/`; `grep -c` in `package-lock.json` = 0 for the first three; `npm ls @earendil-works/pi-client @earendil-works/pi-server @earendil-works/pi-protocol` → `(empty)` |
| `npm ls` gate | exit 0; every copy of pi-coding-agent / pi-ai / pi-tui / pi-agent-core at 1.0.0, every typebox at 1.3.27 (verbatim below) | `npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core typebox` |
| `node` / `npm` | v26.3.0 / 11.16.0 | `node --version`, `npm --version` |
| PATH `pi` | 0.99.2 (the mise global install) | `pi --version` |
| Pinned CLI | 1.0.0 | `node_modules/.bin/pi --version` |
| Registry | `@earendil-works/pi-coding-agent@1.0.0` published; `latest` 1.0.4 (not adopted) | `npm view` |
| Native consumers | pi-subagents 0.75.0, pi-web-access 0.33.0, Plannotator 0.27.21 | `.pi/npm/node_modules/**/package.json` (the worktree's own `.pi/npm`) |
| Toolchain | tsc 6.0.3, Biome 2.4.16, ruff 0.15.15, ty 0.0.40 | `--version` |

The `npm ls` gate output after the trim and `npm ci`:

```text
@mgiles/perk@3.9.0 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2676
├─┬ @earendil-works/pi-agent-core@1.0.0
│ ├── @earendil-works/pi-ai@1.0.0 deduped
│ └── typebox@1.3.27 deduped
├─┬ @earendil-works/pi-ai@1.0.0
│ └── typebox@1.3.27 deduped
├─┬ @earendil-works/pi-coding-agent@1.0.0
│ ├─┬ @earendil-works/pi-agent-core@1.0.0
│ │ ├── @earendil-works/pi-ai@1.0.0 deduped
│ │ └── typebox@1.3.27 deduped
│ ├─┬ @earendil-works/pi-ai@1.0.0
│ │ └── typebox@1.3.27 deduped
│ ├── @earendil-works/pi-tui@1.0.0
│ └── typebox@1.3.27
├── @earendil-works/pi-tui@1.0.0
└── typebox@1.3.27
```

## Census of the dropped pins

```text
rg -n 'pi-client|pi-server' extension src packages tools docs/site tests shared .github \
  justfile package.json tsconfig.json biome.json
```

Four hits in three files, before the edit: `justfile:45` (the `bump-pi` install line),
`package.json:65,67` (the two pins) and `tests/test_packaging.py:96` (the lockstep `names`
tuple). All three owners were edited and no other hit exists. Neither perk nor its native
consumers import either package: `NATIVE_SDK_CENSUS` names neither, and pi-subagents 0.75.0
declares no peer on either. Pi 1.0.0's `pi-coding-agent` does not depend on them either.

## Lockfile delta (base `e108044d` → committed)

The bump (`just bump-pi 1.0.0`: "removed 3 packages, and changed 41 packages") changed 38
`packages` entries: 7 nested under pi-coding-agent and 31 elsewhere. The trim followed the
plan's policy: keep what the `@earendil-works/*` graph forces, revert what is incidental.

**Kept (18 entries):**

- the root entry's `devDependencies` (four pins at 1.0.0, two dropped);
- the four top-level pins, `pi-coding-agent`, `pi-ai`, `pi-tui` and `pi-agent-core`, each
  0.99.2 → 1.0.0;
- the seven nested `@earendil-works/*` entries under pi-coding-agent, each 0.99.2 → 1.0.0
  (`chord`, `pi-agent-core`, `pi-ai`, `pi-codemode`, `pi-mcp`, `pi-telemetry`, `pi-tui`). The
  rest of the 146-entry shrinkwrapped tree did not change between 0.99.2 and 1.0.0;
- top-level `pi-telemetry` 0.99.2 → 1.0.4. Its declared range changed (`^0.99.2` → `^1.0.0`),
  so it floats: recorded, with no lockfile hold and no fifth pin;
- removed by the install: `pi-client`, `pi-server`, `pi-protocol`;
- removed by `npm prune`: top-level `chord` 0.99.2 and `ignore` 7.0.8. pi-agent-core 0.99.2,
  pi-client, pi-server and pi-protocol required them. After the bump nothing required them, but
  `npm install` left both behind as extraneous orphans.

**Reverted to the base entry text (22 entries):** the patch re-resolutions of top-level entries
whose declaring packages did not change. That is 17 `@aws-sdk/*` (e.g. `@aws-sdk/core`
3.978.1 → 3.978.0, including `credential-provider-sso/node_modules/@aws-sdk/token-providers`
3.1138.0 → 3.1129.0), 3 `@smithy/*` (`core` 3.35.1 → 3.34.1, `signature-v4` 5.7.4 → 5.7.3,
`types` 4.19.0 → 4.18.0), `@babel/runtime` 7.29.10 → 7.29.7 and `ws` 8.22.0 → 8.21.0. The
AWS-chain ranges that looked changed were declared only by other members of the same
re-resolved cluster. Top-level pi-ai 1.0.0 still pins `@aws-sdk/client-bedrock-runtime` at
3.1127.0, unchanged. No `"peer": true` annotation or `pi-ai` bin-path rewrite appeared, so none
had to be reverted. A throwaway, uncommitted script did the copying.

**Validation:** `npm install --package-lock-only` leaves the trimmed lockfile byte-identical.
`npm ci` installs it (exit 0, "added 647 packages", 652 before the drop) and leaves it
unchanged. The `npm ls` gate exits 0, and plain `npm ls` reports nothing extraneous, invalid or
missing. `git diff --stat e108044d -- package-lock.json package.json`:
`2 files changed, 49 insertions(+), 129 deletions(-)` (`package-lock.json` 168 lines).

## Suite ledger (1.0.0 install, worktree `node_modules` + `.pi/npm`)

| Check | Result |
|---|---|
| `npm run typecheck` (root tsc) | green, no 1.0.0 type diagnostic |
| `npm run docs:typecheck` (astro sync + tsc) | green |
| `npm run prose-review:typecheck` | green |
| `just typecheck-py` (ty) | green |
| `just lint-py` (ruff) + `just lint-js` (Biome) | green |
| `just test-js-fast` | **2739 / 2739** after the repair (first run: 2738 pass, 1 fail, fix 1 below) |
| `just test-js-slow` (36 files) | **999 / 999**, green on its first run |
| `uv run pytest` (full) | **8362 / 8362**, 0 skipped, after the repair (first run: 8361 pass, 1 fail, fix 2 below) |
| Live bridge smoke, PATH `pi` 0.99.2 | `tests/test_native_sdk_bridge_live.py` 2 / 2 (inside the full run and targeted) |
| Live bridge smoke, pinned CLI 1.0.0 | 2 / 2 with `PATH="$PWD/node_modules/.bin:$PATH"` |
| `/perk-selfcheck`, both hosts | `bridge=installed`; `native sdk bridge: installed (roots=2, specifiers=8)`; per-source rows `npm:pi-subagents@0.75.0=3`, `npm:pi-web-access=1` |
| `extension/substrate/nativeSdkBridge.test.ts` | 32 / 32; **"census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS" ran** (not skipped) against pi-subagents 0.75.0 / pi-web-access 0.33.0 |
| `extension/piAiCompatGuard.test.ts` | 1 / 1 |
| `test_pi_toolchain_pin_lockstep` | passes with the closed four-name set |

**Final gate** at `ff736cc2` (the complete change; this paragraph is the only later edit, and it
is docs-only):

```text
perk CI: all checks passed.
✓ lint-py (2s)
✓ lint-js (5s)
✓ typecheck-py (9s)
✓ typecheck-js (84s)
✓ typecheck-prose-review (23s)
✓ test-py-fast (278s)
✓ test-py-slow (236s)
✓ test-js (132s)
✓ docs-check (365s)
⊘ changelog-check (skipped — no changed files match CHANGELOG.md)
```

In the same state, `just test-js-slow` (TAP summary): `# tests 999`, `# pass 999`, `# fail 0`,
`# cancelled 0`, `# skipped 0`.

## Fixes taken (with triage-ladder rung)

No rung-1 (install staleness), rung-2 (1.0.0 type diagnostics) or rung-4 (production defect)
fix was needed. Both repairs are rung 3: a test expectation that encoded 0.99.2. Each is now
version-honest by branching, and its 0.99.2 arm is kept as it was written.

1. **`extension/worker/sdkAdapter.test.ts`**, "workerBuiltinExtensions: …": the models-off
   control looked for `Model API` in the codemode tool description. Pi 0.99.2 rendered an inline
   `Model API:` typed section (`dist/extensions/codemode/tool.js:218` in the 0.99.2 tarball).
   Pi 1.0.0 replaced it with one Globals line, ``- `models`: classifiers and image generation.
   Read <docs>/codemode.md first.``, and moved the reference to `docs/codemode.md` § Models. The
   test now branches on `hostSdkAtLeast(1, 0, 0)`: the 0.99.2 arm is unchanged, and the 1.0.0
   arm asserts the Globals line on the `models: true` control and its absence on the worker's
   codemode. The production behavior (the worker's codemode is built without `models`) holds on
   1.0.0. This is the second file that needed the version compare, so
   `hostSdkAtLeast(major, minor, patch)` was lifted into `extension/testing/harness.ts`, and
   `restorationWindow.test.ts::hostRestoresPending` now calls it with the same semantics.
2. **`tests/test_pi_host.py::test_a_floor_satisfying_cli_is_admitted_beside_an_older_sdk_dev_pin`**
   asserted `sdk_pin != str(floor)`, a repo-state precondition that held only while the
   committed pin was 0.99.2. It now branches on `satisfies_floor(parse_semver(pin), floor)`. The
   below-floor arm keeps `sdk_pin != str(floor)` as written. The at-floor arm is a new
   expectation with no 0.99.2 counterpart: it asserts the converse independence, that a
   below-floor CLI (`0.99.2`) is refused beside the floor-satisfying pin. The admitted-CLI
   assertions stay unconditional.

The 0.99.2 arms become unreachable once 4.3's SDK-boundary admission lands; retiring them
belongs to 4.3 or 5.1.

## Planning-time assumptions the measurement falsified

- **"The install prunes what the drop orphans."** It removed `pi-client`, `pi-server` and
  `pi-protocol`, but it left top-level `chord` 0.99.2 and `ignore` 7.0.8 as extraneous lockfile
  entries. The plan expected `ignore` to go and the only floating `@earendil-works/*` transitive
  to be `pi-telemetry`. Running `npm prune` delivered both expectations.
- **"The `npm ls` gate fails on extraneous copies."** npm 11.16.0's `npm ls` exits 0 when the
  only problems are extraneous (`lib/commands/ls.js`: `shouldThrow` skips problems that are all
  `extraneous:`). The gate still fails on invalid or missing copies, and the `bump-pi` comment
  now says so and points at `npm prune`.
- **"`typebox` 1.3.27 is deduped in the gate output."** pi-coding-agent's shrinkwrapped tree
  carries its own nested `typebox` 1.3.27, a separate copy that is not deduped. Every copy is
  still 1.3.27.
- **"1.1's 4.2 fix list (empty) still holds at HEAD."** Two rung-3 repairs were needed. The
  codemode-description marker belongs to the worker code developed on 0.99.2. The dev-pin skew
  precondition came from the host-floor work, written while the pin sat below the floor.
- **1.1's lockfile preview.** Re-measured rather than copied. The raw delta is again 38 entries,
  but its composition differs: three removals (`pi-client`, `pi-server`, `pi-protocol`), an
  `@babel/runtime` re-resolution, `ignore` still present before the prune, and `pi-telemetry`
  at 1.0.4.

## Consequences and residuals

- **The self-repo remote worker's SDK moved with the pins.** Its `npm ci` worker-deps step
  installs this lockfile, so its `extension/workerMain.ts` now runs on pi-coding-agent 1.0.0.
  This was not verified live; a self-repo remote drive is 5.1's Worker row.
- **The root checkout stays stale** (`node_modules` at 0.87.0 against the manifest) until the
  operator reinstalls there. Never run the suites from it.
- **`bump-pi` was reduced** to the four packages plus the `npm ls` gate line, and
  `test_pi_toolchain_pin_lockstep` now pins the closed set of `@earendil-works/*`
  devDependency keys.
- **Teardown.** The diff script, the trim script and the unpacked 0.99.2 tarball used for the
  codemode comparison lived under the run's gitignored scratch directory
  (`.perk/workflow/scratch/runs/…/agent/`). Nothing untracked was committed.
