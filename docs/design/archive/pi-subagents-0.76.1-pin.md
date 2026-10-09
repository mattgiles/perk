# Record: perk's pi-subagents supplier pin at exact 0.76.1

**Status:** dated evidence record. Measured and authored 2026-10-09 (UTC) on branch `plan-2713`
(base `a1515020`). It implements plan #2713 (Objective #2707, node 1.3): the one version-carrying
borrow, `SUBAGENTS_PACKAGE`, moves from `npm:pi-subagents@0.75.0` to exact
**`npm:pi-subagents@0.76.1`**, and the `settings-wiring` owner converges this repo's committed
`.pi/settings.json` to it. The precedents are [`pi-1.1.0-dev-pins.md`](pi-1.1.0-dev-pins.md)
(this record keeps its shape) and
[`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md) (the 0.76.1 facts S4/S7/S9/T7/T13
this pin relies on).

**Verdict: the pin, the converged settings and the worktree install sit at exact 0.76.1, and the
pair is proven offline, live and in-process. PASS.** `perk doctor --fix` rewrote exactly the pin
line of `.pi/settings.json` and the owner-generated `settings-wiring` digest in
`.perk/managed-state.toml`; a second `--fix` was a no-op. Pi's own npm command installed 0.76.1 into
the implement worktree's `.pi/npm` on an independent copy of the staged tree, and the main
checkout's npm metadata hashed identically before and after. The census drift guard ran green
against the live install with no `NATIVE_SDK_CENSUS` widening and no `BRIDGE_SCHEMA` bump. The live
bridge smoke passed on both the PATH `pi` and the pinned CLI, with a captured `/perk-selfcheck`
transcript for each. The in-process identity proof drove one blocking `perk.scout` child through
perk's own `dispatchForeground` transport: the child completed, and **zero** SDK resolutions
escaped the facade from the pi-subagents root (1458 traced), while the bridge-off control showed 33.
`perk doctor` warns `subagent-compat` truthfully (installed 0.76.1, stamp 0.75.0).

**No stamp claim.** This record does not move, and gives no grounds to move, the doctor guidance
stamp: `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and its test pin
(`test_subagent_compat_verified_version_stamp_is_pinned`) stay `0.75.0` until the live
certification of 0.76.1. The host floor (`shared/host-floor.yaml`), the remote install pin
(`REMOTE_PI_VERSION`), the managed remote artifacts and the main checkout's `.pi/npm` are
untouched. The pin now **leads** the stamp by design, and the `subagent-compat` warning is the
truthful signal of that gap.

## Registry preflight (Step 0, 2026-10-09T21:10Z)

Both stop gates were green, so the bump proceeded.

- **Gate A — the target.** `npm view pi-subagents dist-tags --json` → `{"latest": "0.76.1"}`.
  No newer release than the target.
- **Manifest delta vs 0.75.0 (S9).** `npm view pi-subagents@<v> version pi peerDependencies
  dependencies --json` for both releases: the `pi` manifest (`skills: ["./skills"]`,
  `prompts: ["./prompts"]`, `extensions: ["./index.js"]`) and `peerDependencies` (`typebox: *`,
  `@earendil-works/pi-ai: >=0.86.1`, `pi-tui: *`, `pi-agent-core: *`, `pi-coding-agent: *`) are
  identical. `dependencies` gains exactly `@js-temporal/polyfill: 0.5.1` (`jiti` 2.7.0, `yaml`
  2.8.3, `acorn` 8.18.0, `undici` 8.10.2 unchanged); `jsbi` arrives as its transitive. This agrees
  with S9.
- **Gate B — the surfaces.** `git status --porcelain` was empty, and the `pi-subagents@0\.75\.0`
  sweep (outside `docs/learned/`, `docs/design/archive/`, `CHANGELOG.md`, `docs/planning/`,
  `.worktrees/`, `node_modules/`, `.pi/npm/`) listed exactly the planned surfaces:
  `.pi/settings.json`, `settings.py`, `shared/contracts.md` (two), the three user-doc pages, the two
  `perk-expert` references, the reverify guide, and the two test literals/comments. No surface was
  added.
- **Rebase.** `git fetch origin && git rebase origin/main` → `Current branch plan-2713 is up to
  date.` Everything below ran on `a1515020` plus this change.

## Snapshot matrix

| Component | Before | After | Provenance |
|---|---|---|---|
| PATH `pi` | 1.1.0 | 1.1.0 | `pi --version` (`~/.local/share/mise/installs/node/26.3.0/bin/pi`) |
| Pinned CLI | 1.1.0 | 1.1.0 | `$WT/node_modules/.bin/pi --version` |
| Root SDK | `@earendil-works/pi-coding-agent` 1.1.0 | unchanged | `$WT/node_modules/@earendil-works/pi-coding-agent/package.json` |
| `$WT` supplier | pi-subagents 0.75.0 (the hard-linked staged copy) | **0.76.1** | `$WT/.pi/npm/node_modules/pi-subagents/package.json` |
| `$MAIN` supplier | pi-subagents 0.75.0 | 0.75.0 (post-merge step) | `$MAIN/.pi/npm/node_modules/pi-subagents/package.json` |
| `.pi/npm` link counts | `$WT` and `$MAIN` `package.json` 29 each (`package-lock.json`, `node_modules/.package-lock.json` 29; `pi-subagents/package.json` 16) | `$WT` 1 on all four; `$MAIN` `package.json` 28, `pi-subagents/package.json` 15 | `stat -f '%l'` |
| `$WT/.pi/npm/package.json` | `"pi-subagents": "^0.75.0"` | `"pi-subagents": "^0.76.1"` | npm's default save prefix; Pi's `needsInstall` reads the installed manifest, so the caret is inert |
| Install summary | — | `added 3 packages in 700ms` | `npm install pi-subagents@0.76.1 --prefix "$WT/.pi/npm" --legacy-peer-deps` |
| S9 additions | — | `@js-temporal/polyfill` 0.5.1, `jsbi` 4.3.2 | their own `package.json` |
| Consumer install root | `node_modules/@earendil-works/` empty, no `typebox` | unchanged; no nested `pi-subagents/node_modules` | `ls` |
| Other consumers | pi-web-access 0.37.0, `@plannotator/pi-extension` 0.28.8 | unchanged | `$WT/.pi/npm/node_modules/**/package.json` |
| `node` / `npm` | v26.3.0 / 11.16.0 | — | `--version` |

The 29-link count is the planning-time 28 plus this plan's own materialized worktree.

## Main-checkout metadata hashes (identical before the copy, after the copy, after the install)

```text
d4f22073171068d1f4eb3c54a20dab4ed818cc6c5a725455fe129e0ea49637b9  $MAIN/.pi/npm/package.json
85c7e5a5b2d71081a191d8fcaf6186b0f49b5eb34fe985c62b020b1722ab2f50  $MAIN/.pi/npm/package-lock.json
ae5ba99e949608f21ea272d2c14ceb47c284f9260bf326e00701c74ea8a77302  $MAIN/.pi/npm/node_modules/.package-lock.json
919f846872963310c648e076a1d6c026bc9e11a13b40a8724c2aa3ead6ac3f3d  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
```

`shasum -a 256 -c` reported `OK` for all four after the independence step and again after the
install. The procedure was `cp -R "$WT/.pi/npm" "$WT/.pi/npm.independent" && rm -rf "$WT/.pi/npm"
&& mv "$WT/.pi/npm.independent" "$WT/.pi/npm"`, then `rm -rf
"$WT/.pi/npm/node_modules/pi-subagents"`, then the install. The hard-linked staged tree shares
npm's metadata inodes with the main checkout and every other materialized worktree (npm writes
manifests and lockfiles in place; only package folders move by rename), so an install on the
linked tree would have rewritten main's metadata. Never `pi update`; never `/reload`.

## Settings convergence (`uv run perk doctor --fix` in `$WT`)

The first run's `Fixed` block:

```text
  - .pi/settings.json: updated npm:pi-subagents@0.75.0 -> npm:pi-subagents@0.76.1; compaction: reserveTokens=65536
  - .perk/local.toml: created
  - .perk/managed-state.toml: updated
```

The `compaction` fragment is reporting only: `_converge_compaction` is write-when-present and
reports its committed keys whenever the settings body changes; `compaction.reserveTokens` was
already 65536 and the byte diff does not touch it. `.perk/local.toml` is gitignored. The tracked
footprint was exactly the two expected files (plus the Step 1 `settings.py`/`checks.py` edits);
no third path was dirtied, so nothing was reverted:

```diff
--- a/.pi/settings.json
+++ b/.pi/settings.json
@@ -2,7 +2,7 @@
   "packages": [
     "..",
     "npm:@tombell/pi-diff",
-    "npm:pi-subagents@0.75.0",
+    "npm:pi-subagents@0.76.1",
     "npm:@ff-labs/pi-fff",
     "npm:pi-web-access",
     {
--- a/.perk/managed-state.toml
+++ b/.perk/managed-state.toml
@@ -36,7 +36,7 @@
 path = ".pi/settings.json"
 kind = "block"
 version = "4.0.0"
-hash = "sha256:e122bd5c802ce7bdce3d3cd789985274d3562cce40f8f5168768befb2ebd3046"
+hash = "sha256:67dc51f74330df187c71bef6197e7e9c9a5975a0818a541dc2ecfd34b1982b8e"
```

Only the `[managed.artifacts.settings-wiring]` hash moved; its `version` stays `4.0.0`, and no
timestamp field exists. The second `--fix`, with both files retained, printed no `Fixed` block
and left `git status --porcelain` byte-identical (idempotent).

Both runs also reported a `Fix failures` entry: `skills delivery failed: \`skills update --sync\`
exited 1` with a `conflict` for every skill in the gitignored, `skills` CLI-managed
`.agents/skills/` of this worktree. It touches no tracked path and is not caused by the pin; it is
named here and left alone.

## Suite ledger (0.76.1 installed in `$WT/.pi/npm`)

| Check | Result |
|---|---|
| `node --test --test-reporter=spec extension/substrate/nativeSdkBridge.test.ts` | **32 / 32**, 0 skipped; `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS` ran. No census widening, no schema bump |
| `node --test … reportWaveRpc.test.ts rpcAdapter.test.ts reportWave.test.ts scoutWave.test.ts waveIsolation.test.ts` | **169 / 169**; `git diff --stat origin/main -- extension/waves extension/testing/fakeSubagents.ts` empty (the `script` wire dialect is untouched) |
| `uv run pytest -n0 -q tests/test_init_idempotent.py tests/test_doctor.py tests/test_managed_state.py tests/test_native_sdk_bridge_parity.py` | **406 passed** (includes the new `test_subagent_compat_on_the_pinned_install_follows_the_stamp`) |
| Live bridge smoke, PATH `pi` 1.1.0 | `tests/test_native_sdk_bridge_live.py`: **2 passed, 1 skipped** (the below-floor arm: "needs a below-floor PATH pi (this one is admitted)") |
| Live bridge smoke, pinned CLI 1.1.0 | **2 passed, 1 skipped** with `PATH="$WT/node_modules/.bin:$PATH"` |
| `just test-js-fast` (explicit; TAP beside `dot`) | **2796 / 2796**, 0 skipped; the census drift guard is `ok 1953`, ran |
| `just test-js-slow` (explicit) | **1001 / 1001**, 0 skipped |
| `uv run perk learn docs-check` | fresh; no `docs/learned` edit |

### Captured `/perk-selfcheck` transcripts

A green pytest run surfaces no transcript, so each host got one explicit launch from `$WT`:
`env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE -u
PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS PI_OFFLINE=1
PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR="$MAIN/.pi/agent"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-perk-live-smoke-placeholder-never-sent}" pi --approve
--mode json -p /perk-selfcheck`, the second with `PATH="$WT/node_modules/.bin:$PATH"`. Both exited
0 with 0 `Failed to load extension` lines. (The pytest smoke itself runs under the suite's
throwaway agent dir; these launches use the main checkout's launch agent dir, which carries no
`packages`.) The PATH-host transcript, after its session header line:

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
  host sdk: 1.1.0 (floor >= 1.0.0)
  native sdk bridge: installed (roots=2, specifiers=8)
    host: ~/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js
    roots: 2 — $WT/.pi/npm/node_modules/pi-subagents, $WT/.pi/npm/node_modules/pi-web-access
```

The pinned-CLI transcript is identical line for line except the `host:` line, which reads
`host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js` (the host root inside the
checkout).

## The in-process identity proof

**Instrument.** A scratch `-e` probe extension registers `/probe-foreground <provider/model>` and
calls perk's own `dispatchForeground(pi.events, …)` — the blocking in-process path
(`async: false, foregroundOnly: true`) that `run_librarian` and the conflict resolver ride. The
foreground child is built in-process by pi-subagents' `loadHostPiCodingAgent`, which `import()`s the
running host's `dist/index.js` by absolute `file:` URL. perk-dev's module tracer
(`packages/perk-dev/src/perk_dev/profile_startup/module_tracer.mjs`, `--import`ed through
`NODE_OPTIONS`) registers its resolve hook before the bridge does, so the bridge's hook runs first
and short-circuits every census specifier from a consumer root to the facade without reaching the
tracer: any `@earendil-works/*`, `typebox` or host-entry resolution the tracer records with a
pi-subagents parent is a module that escaped the facade.

**Setup.** `run-bounded.sh` was extracted byte for byte from
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) § "The watchdog added after A11"
(SHA-256 `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843`).
`AUTHED=$(mktemp -d -t perk-sa076-authed)` held only a copy of the main checkout's
`.pi/agent/auth.json` (`openai` and `anthropic`, both `api_key`). `$MODEL` =
**`anthropic/claude-haiku-4-5`**, the cheapest Anthropic model in the installed catalog.

**The probe** (`$SCRATCH/probe-foreground.ts`, SHA-256
`d1ffd317349f5bf8dab4e7037f3a7862d2617bc5290d04b26ec772215f55a351`; verbatim except that the
absolute worktree path in the import is written `$WT` here):

```ts
// $SCRATCH/probe-foreground.ts — throwaway; drives ONE blocking (in-process) child through perk's
// own foreground-delegation transport, exactly as run_librarian / the conflict resolver do.
//   /probe-foreground <provider/model>
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";

const log = (label: string, value: unknown) =>
  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);
const BRIDGE = Symbol.for("perk.native-sdk-bridge");
const bridge = () => {
  const r = (globalThis as Record<symbol, unknown>)[BRIDGE] as
    | { kind?: string; roots?: Map<string, string> }
    | undefined;
  return { kind: r?.kind ?? null, roots: [...(r?.roots ?? [])] };
};

export default function (pi: ExtensionAPI) {
  pi.registerCommand("probe-foreground", {
    description: "identity probe: one blocking perk.scout child via dispatchForeground",
    handler: async (args) => {
      const model = args.trim();
      if (!model) { log("probe-error", "usage: /probe-foreground <provider/model>"); process.exitCode = 2; return; }
      log("env", { pid: process.pid, ...Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PI_|PERK_|NODE_OPTIONS)/.test(k))) });
      log("bridge-before", bridge());
      try {
        const outcome = await dispatchForeground(
          pi.events,
          {
            agent: "perk.scout",
            task: "Call the structured_output tool exactly once with {\"ok\": true}. Do not read any file and do not run any command.",
            cwd: process.cwd(),
            schema: { type: "object", properties: { ok: { type: "boolean" } }, required: ["ok"], additionalProperties: false },
            model,
          },
          { requestId: "probe-identity-1", ownerRunId: "probe", nodeId: "identity" },
          new AbortController().signal,
        );
        log("bridge-after", bridge());
        log("status", outcome);
      } catch (error) {
        log("probe-error", String(error));
        process.exitCode = 2;
      }
    },
  });
}
```

**Commands** (from `$WT`, PATH `pi` 1.1.0, each a fresh process):

```bash
TRACER="file://$WT/packages/perk-dev/src/perk_dev/profile_startup/module_tracer.mjs"
GRACE=60 CAP=330 "$SCRATCH/run-bounded.sh" "$SCRATCH/P1-on.log" \
  env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
      -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
      PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR="$AUTHED" PI_SUBAGENTS_TEMP_ROOT="$SCRATCH/subagents-tmp" \
      PERK_MODULE_CENSUS_DIR="$SCRATCH/census-on" NODE_OPTIONS="--import=$TRACER" \
  pi --approve --mode json -e "$SCRATCH/probe-foreground.ts" -p "/probe-foreground $MODEL"
```

The control is the same command with `PERK_DISABLE_NATIVE_SDK_BRIDGE=1` added to the `env` list,
`PERK_MODULE_CENSUS_DIR="$SCRATCH/census-off"` and log `$SCRATCH/P1-off.log`.

**The census evaluation** (verbatim; `$1` = the parent's census file, `$2` = `$WT`):

```bash
node -e '
const fs=require("fs");const [file,wt]=process.argv.slice(1);const root=wt+"/.pi/npm/node_modules/pi-subagents/";
let seen=0;const leaks=[];
for(const line of fs.readFileSync(file,"utf8").split("\n")){if(!line)continue;const r=JSON.parse(line);
  if(r.kind!=="resolve"||!(r.parent??"").includes(root))continue;seen++;
  if(/\/node_modules\/(@earendil-works\/|typebox\/)/.test(r.url)||/\/pi-coding-agent\/dist\/index\.js$/.test(r.url))leaks.push({specifier:r.specifier,url:r.url,parent:r.parent});}
console.log(JSON.stringify({file,seen,leaks:leaks.length,sample:leaks.slice(0,10)},null,2));
' "$1" "$2"
```

### Bridge ON (2026-10-09T21:17:29Z)

The probe's `env` line logged `"pid": 31072`; the census directory also held
`census-31104.jsonl`, an `npm root -g` child of that pid. Root states before and after the
child:

```text
probe: bridge-before {"kind": "active", "roots": [["$WT/.pi/npm/node_modules/pi-subagents", "bridged"], ["$WT/.pi/npm/node_modules/pi-web-access", "bridged"]]}
probe: bridge-after  {"kind": "active", "roots": [["$WT/.pi/npm/node_modules/pi-subagents", "bridged"], ["$WT/.pi/npm/node_modules/pi-web-access", "bridged"]]}
```

```text
probe: status {
  "terminal": {
    "status": "completed",
    "value": {
      "ok": true
    },
    "runId": "92bb2162-2533-4172-b864-d2477be45553",
    "agent": "perk.scout",
    "exitCode": 0
  },
  "release": true,
  "termination": "confirmed",
  "observedRunId": "92bb2162-2533-4172-b864-d2477be45553"
}
exit=0 elapsed=25s
```

```json
{
  "file": "$SCRATCH/census-on/census-31072.jsonl",
  "seen": 1458,
  "leaks": 0,
  "sample": []
}
```

### Bridge OFF — the control (2026-10-09T21:18:13Z)

pid 31343 (plus the `npm root -g` child 31375). Root states: `{"kind": "disabled", "roots": []}`
before and after. The child completed too (not a criterion):

```text
probe: status {
  "terminal": {
    "status": "completed",
    "value": {
      "ok": true
    },
    "runId": "e5d91fcc-57a4-480c-bc73-73f98e23525c",
    "agent": "perk.scout",
    "exitCode": 0
  },
  "release": true,
  "termination": "confirmed",
  "observedRunId": "e5d91fcc-57a4-480c-bc73-73f98e23525c"
}
exit=0 elapsed=6s
```

The census evaluation reported `"seen": 1491, "leaks": 33`. Grouped by specifier and target:

| Specifier → resolved URL | Count |
|---|---|
| `@earendil-works/pi-tui` → `$WT/node_modules/@earendil-works/pi-tui/dist/index.js` | 12 |
| `@earendil-works/pi-coding-agent` → `$WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js` | 9 |
| `typebox` → `$WT/node_modules/typebox/build/index.mjs` | 7 |
| `@earendil-works/pi-agent-core` → `$WT/node_modules/@earendil-works/pi-agent-core/dist/index.js` | 2 |
| `typebox/compile` → `$WT/node_modules/typebox/build/compile/index.mjs` | 2 |
| the host-entry `file:` URL → `~/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js` (parent `src/runs/shared/child-session.js`) | 1 |

Unbridged, pi-subagents' bare imports reach the dev-pin copy under the checkout's root
`node_modules` (a second SDK instance: the control's parent census holds 12605 resolutions against
the bridged run's 2345), and the child-session's exact host-entry import resolves directly. In the
bridged run, `child-session.js`'s traced resolutions are its eleven relative and `node:` imports
only: the host-entry import never reached the tracer, i.e. the bridge served it from the facade.
The control's child still completes because the dev-pin copy is the same 1.1.0 as the host, so the
split identity is functionally invisible here — which is exactly why the tracer, not the child's
outcome, is the instrument.

### Verdict

| D1 criterion | Observed | |
|---|---|---|
| (a) child outcome | `completed`, `termination: "confirmed"`, `release: true`, value `{"ok": true}` | PASS |
| (b) no load error / version refusal | 0 `Failed to load extension`, 0 `is installed, but this Pi process still has` in `P1-on.log` (and in `P1-off.log`); `exit=0` | PASS |
| (c) bridged census | `seen` 1458, `leaks` 0 | PASS |
| (d) control observes an escape | `leaks` 33 | PASS |

**PASS on the first run; no re-run was needed.** The watchdog never fired (no `watchdog:` line in
either log).

**Teardown.** `rm -rf "$AUTHED"` (verified gone); `$SCRATCH/subagents-tmp` stayed empty; `git
status --porcelain` showed nothing from the probe; `pgrep -fl probe-foreground` found no process.

## Doctor transcript (`uv run perk doctor --verbose` / `--json` in `$WT`)

```text
   ✓ settings-wiring: settings-wiring converged
   ⚠ subagent-compat: pi-subagents 0.76.1 installed — perk's guidance was verified against 0.75.0 — npm:pi-subagents@0.76.1 is the settings pin (settings-wiring); mechanics perk's guidance leans on are source-read-derived at the verified version and unverified at the installed one
   ✓ artifact-health: 7 managed artifacts up-to-date
✓ healthy (42 ok)
```

Exit 0 both times. The JSON report carries `"healthy": true` and the `settings-wiring`
artifact-health row `up-to-date` with recorded, desired and observed hashes all
`sha256:67dc51f7…2b8e` (the retained managed-state digest). The two `--fix` runs, taken while the
installed supplier was still 0.75.0, reported `healthy (43 ok)`; the one fewer `ok` is the
`subagent-compat` row turning to a warning once 0.76.1 is installed. A new test,
`test_subagent_compat_on_the_pinned_install_follows_the_stamp`, plants
`_npm_version(init.SUBAGENTS_PACKAGE)` and asserts this warning while the pin leads the stamp and
`ok` once they agree.

## Planning-time assumptions the measurement falsified

None that affect the result. Details that differed:

- **The 28-link count.** Measured 29: this plan's own worktree was materialized after planning.
- **The `--fix` change line.** It carried the `compaction` reporting fragment and the gitignored
  `.perk/local.toml` creation beside the expected `updated …` fragment, and both runs reported the
  unrelated `.agents/skills/` sync failure (above). The tracked footprint was as planned.
- **"The captured selfcheck reproduces the test's environment."** The pytest smoke runs under the
  suite's throwaway `PI_CODING_AGENT_DIR` (the conftest autouse fixture), not the main checkout's
  launch agent dir the captured launches used. Both are package-free agent dirs, and both runs
  passed.

## Consequences and residuals

- **Post-merge.** The main checkout's `.pi/npm` lags at 0.75.0 until the next fresh `pi` launch
  there (Pi reinstalls on the range mismatch) or an explicit `npm install pi-subagents@0.76.1
  --prefix .pi/npm --legacy-peer-deps` run there with no Pi process on that checkout. Until then,
  new plan worktrees are staged with the 0.75.0 tree and Pi reinstalls at their launch. `perk
  doctor` on main warns `subagent-compat` by design until the stamp moves.
- **The implement session's supplier boundary.** The implement session used **no** subagent
  surface at all — no `subagent` tool, no wave tool, no `run_librarian`, no conflict-resolver
  dispatch — and no `/reload`, before or after the install: it held 0.75.0's loaded modules while
  0.76.1's files sat on disk. Warm `/submit` is not a process boundary, so the first fresh-process
  dogfood of Pi 1.1.0 + pi-subagents 0.76.1 under perk is credited to the next perk session
  launched on a checkout carrying 0.76.1, never to this session's `/submit`.
- **Unchanged dated observations.** `extension/waves/rpcAdapter.ts`'s header names 0.75.0 as the
  dialect stamp, and `shared/contracts.md`'s tool-loadout ordering note names "pi-subagents
  0.75.0" for the `selectedTools` behaviour; 0.76.1's `src/extension/tool-activation.js` carries
  the same three `selectedTools` lines, so both stay as written.
- **`/learn` candidates.** Not edited here:
  1. `docs/learned/pi/subagents.md` § Sources — "pinned to `npm:pi-subagents@0.75.0`" and "the pin
     walks an older install (0.73.1 …) forward" are now 0.76.1 facts.
  2. `docs/learned/toolchain/worktree-node-modules.md` § "The `.pi/npm` world in perk's own
     checkout", and `materialize.py::_clone_npm_tree`'s "never mutated in place" comment — the
     hard-linked staging shares npm's metadata inodes (npm writes manifests and lockfiles in
     place; only package folders move by rename), so any install in a materialized worktree must
     first make the tree independent.
  3. `docs/learned/pi/native-sdk-bridge.md` could gain the tracer-based identity instrument with
     its bridge-off control as the in-process proof recipe.
- **Owed library refresh.** The `pi-subagents` source mirror in `perk librarian list` is pinned
  at `v0.71.0`; refreshing it is an owner run, unchanged here.
- **Teardown.** The registry outputs, `run-bounded.sh`, the probe, both census directories, both
  probe logs, both selfcheck transcripts, the doctor logs and the TAP reports live under the run's
  gitignored scratch directory (`.perk/workflow/scratch/runs/…/agent/`). Nothing there was
  committed.
