# Dogfood: the consumer-repo remote drive (Objective #1142, Node 2.1)

**Status:** validation record (the `provider-smoke-*` / `remote-runner-e2e-dogfood` genre) for the
**consumer-repo** remote execution chain — a real remote `implement` run and a real remote
`address` run driven through the published distributions (PyPI `perk`, npm `@mgiles/perk`) in a
scratch consumer repo, resolving the **`consumer-npm`** worker entry. Part A is the repeatable
procedure; Part B is the captured evidence + defect log from the first execution.

This record closes the one honest residue in `remote-runner-e2e-dogfood.md`'s scope notes: the
consumer path (`consumer-npm` worker entry + the pinned `@mgiles/perk` install) was wired and
unit-tested but never run live. The chain under proof is the same as the e2e record's — dispatch →
`perk-run.yml` → composite setup → `perk run-worker` → the Node headless worker → tools registered →
terminating door → terminal reporting — with the consumer-specific arms swapped in: the
exact-version-pinned PyPI/npm installs, and the `consumer-npm` worker-entry rung.

Scope notes (what this record does *not* prove): the fully **canonical** published-registry path.
Two defects (B-pre-c, B8 below) were fixed in perk during this dogfood and delivered to the scratch
repo as **labeled deviations** (Part A step 10's fix-class table); the canonical rendered
template + released CLI pick the fixes up at the next release, after which a `perk init` re-run
re-converges the scratch repo and the first canonical dispatch re-proves the path implicitly
(mirroring the e2e record's env-1 branch-ref precedent, where the canonical arm's re-proof was
likewise deferred to post-merge). No release is cut by this node; release timing is the human's
call.

## Part A — the repeatable procedure

Each step names its actor: **(human)** for actions a session cannot take, **(session)** for
everything automatable. **Released-CLI convention:** every perk command in the scratch repo runs
the *released* distribution via `uvx --from 'perk==<released>' perk …` — never the dev checkout's
perk — so the proof claim stays "a consumer on the published version, both planes" (the runner side
installs from PyPI/npm per the rendered composite regardless). All dispatches run from the scratch
repo's main checkout.

1. **Scratch repo (session).** `gh repo create <owner>/perk-consumer-dogfood --private`, clone it
   beside the perk checkout, seed a README commit. The repo is a reusable fixture — created once,
   kept across executions.
2. **Init + commit (session).** `uvx --from 'perk==<released>' perk init` in the clone; commit +
   push **everything** init wrote (settings, `.perk/`, workflow + composite, agents, gitignore,
   AGENTS block) to the default branch — `workflow_dispatch` only sees workflows on the default
   branch.
3. **Preconditions (human).** Configure the runner prerequisites on the scratch repo:
   - Repo secret `PERK_GH_PAT` — a PAT **covering the scratch repo** (contents + pull-requests +
     issues write). A PAT minted for another repo does not carry over; fine-grained PATs need the
     scratch repo in their repository list.
   - Repo secret `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) — secret values only the human holds.
   - Repo variable `PERK_ENABLED` unset or not `'false'`.
4. **Verify (session).** `uvx … perk doctor workflow check --verbose` — `runner-enabled` /
   `runner-pat-secret` / `runner-model-secret` green (`runner-workflow-permissions` stays advisory
   `info` under the PAT-push model).
5. **Wiring proof (session).** `uvx … perk doctor workflow smoke-test --wait` — the zero-spend
   smoke short-circuit, per-repo (the self-repo's smoke proves nothing about this repo). Record the
   run URL.
6. **Sacrificial plan (session).** Save a minimal bounded hello-note plan through the deterministic
   cold save door: `uvx … perk plan save --json --plan-file <file>`; note its issue number `<N>`.
   Prove the branch is fresh: `git ls-remote origin plan-<N>` returns nothing.
7. **Remote implement (session).** `uvx … perk implement <N> --remote`. Record the dispatch JSON;
   poll with `gh run watch <run-ref>` and/or `uvx … perk workflow run list`.
8. **Verify + capture (session).** Map each verification point to a concrete artifact (the Part B
   checklist): composite setup log (the pinned consumer installs), the
   `run-worker: worker entry=… (consumer-npm)` line, tools registered (no `no_extension_tools`),
   the model line, the submitted PR (head `plan-<N>` in the scratch repo), the `RunOutcome` JSON,
   the run-report comment + job summary, the discovery row, the `perk-run-<run_id>` artifact
   (`events.ndjson` at the artifact root), and the pi-web-access load observation.
9. **Remote address (session).** Self-post one review thread on a changed line of the sacrificial
   PR (`gh api repos/{owner}/{repo}/pulls/<pr>/comments` with a diff anchor); verify it reads back
   unresolved (`reviewThreads` via GraphQL — the `gh pr view` JSON field list has no
   `reviewThreads`). Then `gh pr ready <pr>` (drafts route to `ready_for_review`, never `address`),
   and `uvx … perk plan resume <N> --remote --json` — capture the classifier payload
   (`stage: "address"`), then the same poll/verify/capture loop.
10. **Cleanup (session).** Close the sacrificial PR unmerged, delete `plan-<N>`, close the plan
    issue — in the scratch repo. **Keep the scratch repo** (the reusable fixture the human
    preconditions paid for). After a release ships the fixes, a `perk init` re-run re-converges any
    hand-applied deviations back to the canonical rendering.
11. **Failure loop.** Any failed run is **evidence, not a restart**: capture the step-log excerpts
    (+ the `perk-run-<run_id>` artifact when the worker got far enough to write events — a worker
    that dies at spawn writes no `events.ndjson`; the step log is the evidence), log the defect in
    Part B (B-series numbering, continuing the e2e record's), fix it in perk on the node's PR when
    in-perk, document it when environmental, and re-dispatch.

    **The consumer fix-delivery asymmetry.** In a consumer repo NO fix rides any branch of the
    consumer repo: the worker code comes from the published npm tarball, the CLI from PyPI, and the
    workflow/composite from the consumer's own committed tree (rendered at `perk init` time by the
    installed CLI). The e2e record's "worker-code fixes can ride the plan branch" is **self-repo
    mechanics only** — committing worker code to the scratch repo's plan branch would flip the
    entry resolution to `self` and destroy the proof. The pre-release deviation mechanisms, per fix
    class (each hand-applied to the scratch repo's committed files, explicitly labeled, and
    re-converged canonically at the next release + `perk init`):

    | Fix class | Pre-release delivery into the consumer repo |
    |---|---|
    | workflow/composite template | hand-apply the fixed step to the committed `.github/actions/perk-remote-setup/action.yml` / `.github/workflows/perk-run.yml` (ordinary files in the consumer tree) |
    | worker code (extension, npm-delivered) | point the worker-deps install at the fix branch: `npm install github:mattgiles/perk#plan-<N> --prefix .pi/npm --legacy-peer-deps` (the perk repo is public; the package.json `files` filter applies to git installs; the branch's version string stays the released one, keeping the settings pin coherent) |
    | Python CLI | `uv tool install git+https://github.com/mattgiles/perk@plan-<N>` in the composite's perk-install step |

## Part B — the captured evidence

Executed **2026-07-06** in the session-created private scratch repo
**`mattgiles/perk-consumer-dogfood`** on the released **perk 1.1.0**, both planes (`uvx --from
'perk==1.1.0'` locally; PyPI/npm installs on the runner). Bootstrap: README seed commit `fe3f195`;
`uvx … perk init` (consumer) commit `8e4269a` — the rendered composite carried the canonical pins
(`uv tool install perk==1.1.0`; `npm install -g @earendil-works/pi-coding-agent`;
`npm install @mgiles/perk@1.1.0 --prefix .pi/npm --legacy-peer-deps`). Preconditions green
(`uvx … perk doctor workflow check --verbose` → `runner-enabled` default-on, `runner-pat-secret`,
`runner-model-secret` (ANTHROPIC_API_KEY), `runner-workflow-permissions` advisory info).

### The smoke run (wiring proof)

- Dispatch: `uvx … perk doctor workflow smoke-test --wait` → run_id `01KWVMN1W1HWK87T5WWTX2Z3F4`,
  run <https://github.com/mattgiles/perk-consumer-dogfood/actions/runs/28789787748>.
- Result: `✓ smoke run succeeded` — this repo's secrets validated, runner reachable, zero spend.

### Canonical dispatch #1 — the live probe (failed; evidence for B8)

The first remote implement dispatched the **untouched canonical** path to capture the predicted
worker-spawn failure live, at ~zero model spend.

- **Sacrificial plan** — issue **#1** ("Add a hello note describing the perk remote runner
  (consumer dogfood)", saved via `uvx … perk plan save --json --plan-file …`). Fresh-branch proof:
  `git ls-remote origin plan-1` empty, nothing seeded it.
- **Dispatch** — `uvx … perk implement 1 --remote` → `{"success": true, "stage": "implement",
  "run_id": "01KWVMQANXH0MBGHGSEP5EQQKZ", "run_handle": {"kind": "github-actions", "run_ref":
  "28789852871", …}}`; run
  <https://github.com/mattgiles/perk-consumer-dogfood/actions/runs/28789852871> — **failed** at
  `Drive the stage headlessly`.
- **The create arm in a consumer repo** (corroborating evidence) — the checkout step:
  `plan branch plan-1 not found; creating it from origin/main`.
- **Composite setup log (canonical pins, live)** — `uv tool install perk==1.1.0`; global pi install
  `added 131 packages`; worker-deps `npm install @mgiles/perk@1.1.0 --prefix .pi/npm
  --legacy-peer-deps` → **`added 1 package in 879ms`** — the install-layer corroboration of
  B-pre-c's premise: `@mgiles/perk` ships zero runtime `dependencies` and `--legacy-peer-deps`
  skips peers, so *only* `@mgiles/perk` landed under `.pi/npm/node_modules/`.
- **Worker entry** — `run-worker: worker entry=/home/runner/work/perk-consumer-dogfood/
  perk-consumer-dogfood/.pi/npm/node_modules/@mgiles/perk/extension/workerMain.ts (consumer-npm)` —
  the pre-fix in-place rung-3 path.
- **Spawn death (B8, live-found)** — after the started report, the worker died before any model
  turn (Node.js v22.23.1):

  ```text
  Error [ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING]: Stripping types is currently unsupported
  for files under node_modules, for "…/.pi/npm/node_modules/@mgiles/perk/extension/workerMain.ts"
  ```

  `run-worker: worker exited 1`. This fails **earlier** than B-pre-c's statically-predicted
  `ERR_MODULE_NOT_FOUND` — Node refuses to even type-strip a `.ts` entry under `node_modules`, so
  the unresolvable-imports failure never got the chance to fire (B-pre-c's runtime symptom was
  masked, its premise corroborated at the install layer above).
- **Failure-loop reporting worked as designed** — terminal run-report comment on issue #1
  (`<!-- perk:run-report:01KWVMQANXH0MBGHGSEP5EQQKZ -->`, `Status: failed (no structured outcome on
  disk)`); the diagnostics upload found nothing
  (`No files were found with the provided path: .perk/workflow/scratch/runs/…`) — a spawn-death run
  writes no `events.ndjson`, exactly the predicted evidence shape; zero model spend.

### The fixes + the labeled deviations

Both defects were fixed in perk on this node's PR and delivered to the scratch repo pre-release via
the Part A step 11 deviation table (commit `caa8836` on the scratch repo's default branch, both
hand-edits labeled `DEVIATION` inline):

- **B-pre-c fix (template class)** — `_WORKER_DEPS_CONSUMER`
  (`src/perk/run/workflow_artifacts.py`) gains the **unpinned** SDK spec:
  `npm install @mgiles/perk@{__version__} @earendil-works/pi-coding-agent --prefix .pi/npm
  --legacy-peer-deps`. The SDK's real `dependencies` (pi-ai, pi-tui, typebox) close the worker
  graph's bare-import set; unpinned matches the composite's evergreen global pi install posture.
  Deviation: the fixed worker-deps line hand-applied to the scratch repo's committed `action.yml`.
- **B8 fix (Python CLI class)** — `resolve_worker_entry`'s `consumer-npm` arm
  (`src/perk/run/run_worker.py::_stage_consumer_entry`) stages a fresh full-package copy at
  `.pi/npm/perk-worker/` and spawns the staged `extension/workerMain.ts`: outside `node_modules`
  Node type-strips it, the full-package copy keeps package-root-relative resources (`shared/`,
  `prompts/`, `package.json`) reachable, and bare imports resolve by walking up to
  `.pi/npm/node_modules`. Deviation: the composite's perk-install step hand-switched to
  `uv tool install git+https://github.com/mattgiles/perk@plan-1155`. Note what this deviation does
  *not* touch: the worker code executed on the runner is still the **published npm tarball**
  (`@mgiles/perk@1.1.0`) — the staged copy is a byte copy of it — so the npm-distribution proof
  stays honest.

Test pins: `tests/test_workflow_artifacts.py` (consumer worker-deps carries the SDK spec, unpinned;
self arm still `npm ci`) and `tests/test_run_worker.py` (staging outside `node_modules`,
resource ride-along, nested-`node_modules` exclusion, per-resolve refresh). contracts.md §8.14's
false "and its runtime deps" sentence rewritten to the corrected two-spec story, and the run-worker
spec's rung 3 now describes the staging — both in the same turn as the fix.

### The remote `implement` run (the full consumer proof)

Re-dispatch of the same sacrificial plan (the failed probe left `plan-1` created-but-empty; a
failed run is evidence, not a restart).

- **Dispatch** — `uvx … perk implement 1 --remote` → `{"success": true, "stage": "implement",
  "run_id": "01KWVN6SGE80ZMTCCS4MPEFNYQ", "run_handle": {"run_ref": "28790325662", …}}`; run
  <https://github.com/mattgiles/perk-consumer-dogfood/actions/runs/28790325662>, job green in ~3m.
- **Composite setup log (deviation installs, live)** —
  `uv tool install git+https://github.com/mattgiles/perk@plan-1155` (the B8 CLI fix); worker-deps
  `npm install @mgiles/perk@1.1.0 @earendil-works/pi-coding-agent --prefix .pi/npm
  --legacy-peer-deps` → **`added 132 packages in 7s`** (contrast the probe's 1 — the SDK's dep
  closure landed, B-pre-c fixed).
- **The staged worker entry (B8 fix, live)** — `run-worker: worker entry=/home/runner/work/
  perk-consumer-dogfood/perk-consumer-dogfood/.pi/npm/perk-worker/extension/workerMain.ts
  (consumer-npm)`. Non-fatal observation: a `MODULE_TYPELESS_PACKAGE_JSON` warning on the staged
  entry (Node reparses as ESM; performance-only — the shipped `package.json` has no
  `"type": "module"`).
- **pi's session-construction auto-installs** — the drive log shows pi installing the missing
  borrowed `.pi/settings.json` packages into `.pi/npm` at session construction (`added 1 package`,
  `added 11 packages`, `added 21 packages` — `@tombell/pi-diff`, `pi-subagents`, `pi-web-access` at
  current releases).
- **Model** — `perk worker: model anthropic/claude-opus-4-8` (the SDK-resolved default).
- **Tools registered** — no `no_extension_tools`; the drive ended on the terminating `submit` tool.
- **pi-web-access observation (env-1 not reproduced)** — **no** `extension load error` line: the
  consumer path installs no repo devDeps (`npm ci` never runs), and the auto-installed current
  releases resolve cleanly. Incidental (same as the e2e record): the non-fatal
  `perk: skill binding: skill 'perk-implement' … is not installed` pointer warning.
- **The submitted PR** — <https://github.com/mattgiles/perk-consumer-dogfood/pull/2>, head
  `plan-1`, base `main`, draft, containing the model-authored `notes/perk-remote-hello.md`.
- **`RunOutcome` JSON** — `{"run_id":"01KWVN6SGE80ZMTCCS4MPEFNYQ","stage":"implement","status":
  "completed","terminal_signal":"submit_tool","pr":{"number":2,"url":"https://github.com/mattgiles/
  perk-consumer-dogfood/pull/2"},"budget":{"turns":7,"tokens":896,"elapsed_ms":162768},
  "error":null}`; `run-worker: worker exited 0`.
- **Terminal reporting** — the marker-keyed comment on issue #1
  (`<!-- perk:run-report:01KWVN6SGE80ZMTCCS4MPEFNYQ -->`: Status completed, `submit_tool`, budget,
  `Opened PR #2`, run link) + the `## perk remote implement` job summary on the run page.
- **Discovery row** — `uvx … perk workflow run list`:
  `01KWVN6SGE80ZMTCCS4MPEFNYQ  implement  dispatched  completed  success  #1  #2(OPEN)` (the failed
  probe listed beneath it as `failure` — discovery sees both).
- **The diagnostics artifact** — `perk-run-01KWVN6SGE80ZMTCCS4MPEFNYQ` downloaded via
  `gh run download`; contents at the artifact root: `events.ndjson` (15 lines, one JSON object per
  line), `session-pointers.json`, `data/plan-steps.json`. First/last lines:

  ```text
  {"kind":"run_started","run_id":"01KWVN6SGE80ZMTCCS4MPEFNYQ","stage":"implement","seq":0,"t":15899}
  …
  {"kind":"run_finished","outcome":{"run_id":"01KWVN6SGE80ZMTCCS4MPEFNYQ","stage":"implement","status":"completed","terminal_signal":"submit_tool","pr":{"number":2,"url":"https://github.com/mattgiles/perk-consumer-dogfood/pull/2"},"budget":{"turns":7,"tokens":896,"elapsed_ms":162768},"error":null},"seq":14,"t":162768}
  ```

### The remote `address` run

- **Actionable feedback** — a self-posted review thread on `notes/perk-remote-hello.md` line 3
  (comment id `3528731930`, "Please reword \"simply to demonstrate\" …"); read back
  `isResolved: false` via GraphQL `reviewThreads`.
- **Ready gate** — `gh pr ready 2` (the e2e record's proc-1 correction, applied as procedure).
- **Classification evidence** — `uvx … perk plan resume 1 --remote --json` →
  `{"success": true, "stage": "address", "run_id": "01KWVNGQ9AM7AZ2ZP04N7MY0KY",
  "run_handle": {"run_ref": "28790630006", …}}`; run
  <https://github.com/mattgiles/perk-consumer-dogfood/actions/runs/28790630006>, green in ~3m20s —
  the staged `consumer-npm` entry line again, model `anthropic/claude-opus-4-8`, no extension load
  error.
- **The fix commit** — `aff0912` "Drop filler adverb 'simply' from note (review feedback)" pushed
  to `plan-1` by the drive.
- **Threads resolved** — the thread carries the worker's reply ("Done — reworded to …") and reads
  back `isResolved: true`.
- **`RunOutcome`** — `{"run_id":"01KWVNGQ9AM7AZ2ZP04N7MY0KY","stage":"address","status":
  "completed","terminal_signal":"address_resolved","pr":null,"budget":{"turns":8,"tokens":1826,
  "elapsed_ms":196663},"error":null}`; exit 0.
- **Terminal reporting + discovery** — the marker-keyed run-report comment on #1
  (`<!-- perk:run-report:01KWVNGQ9AM7AZ2ZP04N7MY0KY -->`, Status completed) + the job summary;
  discovery row `01KWVNGQ9AM7AZ2ZP04N7MY0KY  address  dispatched  completed  success  #1  #2(OPEN)`.

### Cleanup + fixture state

PR #2 closed unmerged, remote branch `plan-1` deleted (`git ls-remote` empty again), issue #1
closed. The scratch repo is **kept** as the reusable fixture, in its deviation state (commit
`caa8836`, both hand-edits labeled inline): after the next release ships the fixes, a
`uvx --from 'perk==<next>' perk init` re-run re-converges `action.yml` to the canonical rendering,
and the first canonical dispatch re-proves the published-registry path.

### Defect log

B-series numbering continuing the e2e record's (B-pre-a/B-pre-b, B7, env-1, proc-1).

| # | Defect | Diagnosis artifacts | Disposition |
|---|--------|---------------------|-------------|
| B‑pre‑c | *(statically found, pre-execution)* the consumer worker cannot resolve its SDK imports: `@mgiles/perk` ships zero runtime `dependencies` (pi packages are peers) and `--legacy-peer-deps` makes npm skip peer installation, so the worker-deps step lands only `@mgiles/perk` under `.pi/npm/node_modules/` — and ESM resolution has no global-folder fallback, so the composite's global pi install does not help | static reads of `package.json` (peers `*`, no deps — pinned by `test_no_runtime_dependencies`), `npm view @mgiles/perk@1.1.0` / `@earendil-works/pi-coding-agent@0.80.3`; live install-layer corroboration on run 28789852871 (`added 1 package in 879ms`); the predicted runtime `ERR_MODULE_NOT_FOUND` was masked by B8 (which dies earlier in the same spawn) | fixed in this PR: `_WORKER_DEPS_CONSUMER` gains the unpinned `@earendil-works/pi-coding-agent` spec, whose real deps (pi-ai, pi-tui, typebox) close the worker's import set; pinned in `test_composite_action_worker_deps_is_repo_kind_aware`; contracts §8.14 amended; delivered to the fixture as a template-class deviation; proven by run 28790325662 (`added 132 packages`, drive completed) |
| B8 | *(live-found)* the `consumer-npm` worker entry is a `.ts` file under `node_modules`, and Node's built-in type stripping hard-refuses those — plain `node <entry>` dies at spawn with `ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING` before any import resolution (pi's extension-loader aliasing only applies when pi hosts the extension in-session, never to the spawned worker) | run 28789852871 step log (the spawn traceback, Node.js v22.23.1); terminal report `failed (no structured outcome on disk)`; no diagnostics artifact (spawn-death writes no `events.ndjson`) | fixed in this PR: `run_worker._stage_consumer_entry` re-homes the npm-installed package as a fresh full-package copy at `.pi/npm/perk-worker/` and spawns the staged entry (type-strippable; package-root resources ride along; bare imports walk up to `.pi/npm/node_modules`); pinned in `test_run_worker.py`; contracts §8.14 run-worker spec amended; delivered to the fixture as a CLI-class deviation (`uv tool install git+…@plan-1155`); proven by runs 28790325662 + 28790630006 (staged entry line, both drives completed) |
| obs‑1 | *(observation, not a defect)* `MODULE_TYPELESS_PACKAGE_JSON` warning on the staged entry — the shipped `package.json` declares no `"type"`, so Node reparses the ESM-syntax `.ts` files, a performance-only overhead | run 28790325662 drive log | documented only; a future `"type": "module"` in `package.json` would silence it (not landed here — it changes the in-session extension-loading surface too, and nothing misbehaves) |
