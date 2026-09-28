# Dogfood: the perk library end to end (Objective #2551, Node 3.3)

**Status:** validation record (the `remote-runner-consumer-dogfood.md` / `pr-review-doors-dogfood.md`
genre) — the phase-3 dogfood gate for the perk library. Part A is the repeatable procedure; Part B
is the captured evidence, the deviation table and the defect/gap log.

**What the gate claims.** From real perk sessions, the library works end to end on perk's own
repository and on a fresh consumer: `perk librarian list` reports the flat pre-catalog mirrors as
uncatalogued with executable hints; `record --adopt` catalogs them; `add source` reuses what is
installed first and pins a checkout at an explicit `--ref`; `check` honours the throttle, never
probes a pinned entry, detects source drift by `ls-remote` and grades docs evidence (`strong` /
`weak` / `none` → `unverifiable`); `run_librarian` mirrors a documentation site from a read-only
main-checkout parent and refreshes it from a linked worktree; a consumer's first use from its main
checkout and from a linked worktree works, with `perk doctor --fix` converging the committed
README; `remove` deletes exactly the leaf; and the `perk-plan` awareness pointer reaches the plan
shapes it is bound to. The automatable half is pinned offline by `tests/test_library_dogfood.py`
(three stitched stories) plus the component suites Part B cites.

**Evidence policy (one rule, applied everywhere).** The live legs are a **submit gate**: the
implementing session does not `/submit` until Part B is complete — every criteria row is
**observed-live**, or **offline-pinned only** carrying a dated, verbatim **operator waiver**
naming why that live leg was not run (a declined leg is a waiver; an `unclean-start`-style refusal
the operator chooses not to clear is a waiver plus a defect-log entry). There is **no post-submit
step**: nothing is owed between `/submit` and `/land`, and a waived leg closes as an explicit
named residual in this record.

**Actors.** **(human)** terminal steps and launching the interactive sessions; **(S1)** the cold
planning session (`perk plan` in the main checkout); **(S2)** the stage-less warm `/plan` session
(`perk` then `/plan`); **(implement)** the implementing session in its linked worktree
`.worktrees/plan-2612`; **(fixture)** the throwaway consumer repository under `/tmp`.

**Instruments.** Verbatim terminal logs under `/tmp/perk-library-dogfood/<step>.log`
(`2>&1 | tee`), and each session's persisted JSONL. Session commands carry no pipes or
redirection (the read-only gate refuses them); a session leg's evidence is its JSONL.

**Session-store resolution (per actor, recorded in Part B).** perk resolves the agent dir as
`PI_CODING_AGENT_DIR` → the launching main checkout's `[pi] agent_dir` → `~/.pi/agent`
(`src/perk/substrate/config.py::launch_pi_agent_dir`, injected by `src/perk/run/pi_exec.py`).
This repository's `.perk/config.toml` sets `agent_dir = ".pi/agent"`, so S1, S2 and the implement
session persist under `<main>/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<id>.jsonl`; the
consumer fixture's seeded config leaves `agent_dir` commented out, so its sessions (C2, C3) persist
under `~/.pi/agent/sessions/`. The directory encoding is lossy — match a file by its header `cwd`
and timestamp, never by the directory name alone; the grammar is `src/perk/learn/session_jsonl.py`.

**Evidence pins.** The run's `main` SHA (P0.1) plus `git rev-parse <sha>:<path>` blob hashes for
every file a finding cites. Values that decay (the pi-subagents version `<V>`, the prek sitemap
size, counts, SHAs) are re-measured at run time; Part B carries measured values only.

**Era note.** The published `@mgiles/perk` npm package and the PyPI `perk` 3.7.0 both predate the
library. Every leg below runs the checkout's code: the CLI through an editable install
(`just install-cli`), the extension through the main checkout's own wiring (and, in the fixture,
an absolute local-path package entry).

## Part A — the repeatable procedure

The main checkout is `/Users/mattgiles/dev/github/mattgiles/perk`, written `<main>`. The legs run
in this order: P0 → S1 (L1–L7, then hold) → S2 → C1–C4 → W1–W2 → L8 (S1, last) → teardown proof.

### P0 — preconditions (human, terminal, `<main>`)

Capture everything:

```sh
mkdir -p /tmp/perk-library-dogfood
cd /Users/mattgiles/dev/github/mattgiles/perk
```

- **P0.1** The clean start and the run SHA:

  ```sh
  { git status --porcelain --untracked-files=all; echo "--- HEAD"; git rev-parse HEAD; } 2>&1 | tee /tmp/perk-library-dogfood/p0.1-status.log
  ```

  Expect an empty status.
- **P0.2** `perk doctor` **before anything else** — capture-if-fired: the skills-delivery check is
  expected to report the stale `.agents/skills/` mirror. If doctor is green while
  `.agents/skills/librarian` is absent, that is a doctor blind spot (routed as a gist).

  ```sh
  { perk doctor; echo "--- librarian skill"; ls -la .agents/skills/librarian; } 2>&1 | tee /tmp/perk-library-dogfood/p0.2-doctor.log
  ```

  P0.2 deliberately runs before P0.3, so it runs whichever `perk` is on `PATH`: a pre-library
  build reports its own version-skew drift and cannot know the `librarian` skill. Answer the
  blind-spot question with the checkout's doctor (`uv run perk doctor` in a checkout whose
  `.agents/skills/` is still stale), not with that build.

- **P0.3** The CLI on `PATH`. Expected on this machine: `No such command 'librarian'` (the PyPI
  3.7.0 tool install predates the group). Then install the checkout editable and rerun — the six
  verbs listed:

  ```sh
  { perk --version; head -1 "$(which perk)"; perk librarian --help; } 2>&1 | tee /tmp/perk-library-dogfood/p0.3-before.log
  just install-cli 2>&1 | tee /tmp/perk-library-dogfood/p0.3-install.log
  { perk --version; head -1 "$(which perk)"; perk librarian --help; } 2>&1 | tee /tmp/perk-library-dogfood/p0.3-after.log
  ```

- **P0.4** Re-sync the skills mirror, then verify the delivered crawl script, whether the retired
  `copy-docs-to-markdown` link lingers (remove it by hand if so), and the `perk-plan` pointer
  sentence:

  ```sh
  perk init 2>&1 | tee /tmp/perk-library-dogfood/p0.4-init.log
  { ls -la .agents/skills/librarian/scripts/copy_docs_to_markdown.py; echo "--- copy-docs link"; ls .agents/skills | grep copy-docs; echo "--- pointer"; grep -n librarian .agents/skills/perk-plan/SKILL.md; echo "--- status"; git status --porcelain --untracked-files=all; } 2>&1 | tee /tmp/perk-library-dogfood/p0.4-verify.log
  ```

  Optional housekeeping: `rm -rf .perk/skills/copy-docs-to-markdown` (only a `__pycache__`
  remains). If `perk init` touched tracked files, commit or revert them before S1 (the bracket's
  clean-start policy: tracked tree clean; pre-existing untracked files are inventoried, not
  refused).
- **P0.5** Tools and health:

  ```sh
  { which curl html2markdown; echo "--- doctor"; perk doctor; echo "--- status"; git status --porcelain --untracked-files=all; } 2>&1 | tee /tmp/perk-library-dogfood/p0.5-health.log
  ```

  Expect doctor healthy (the `library` check reports 8 uncatalogued directories as `info`) and an
  empty status.
- **P0.6** Reuse-first facts:

  ```sh
  { jq -r .version .pi/npm/node_modules/pi-subagents/package.json; echo "--- installed"; ls .pi/npm/node_modules/pi-subagents/src .pi/npm/node_modules/pi-subagents/docs; echo "--- prek"; which prek; } 2>&1 | tee /tmp/perk-library-dogfood/p0.6-reuse.log
  ```

  The first line is `<V>` (0.71.0 at planning time — re-read). pi-subagents' source and docs are
  installed, so by the skill's reuse-first rule they answer most questions; the clone in L3 is the
  explicitly wanted retained, pinned reference. `prek` is a binary only (no local source), so its
  clone is justified.

### S1 — the cold planning session (human launches; the session drives)

```sh
cd /Users/mattgiles/dev/github/mattgiles/perk && perk plan
```

(cold, idle, main checkout, read-only gate on, `stage:plan` delivered). Note the session id. The
prompt to type:

> Drive Part A legs L1–L7 of the perk library dogfood exactly as written in plan issue #2612 (read
> it with `gh issue view 2612 --comments`), then wait for me before L8. Run each command verbatim
> and quote each command's output verbatim. Leg L1b deliberately runs two commands the read-only
> gate is expected to refuse: record the refusal text and continue. Any other refusal, error or
> unexpected output: stop and report it — never improvise a fix or a workaround.

- **L1** `perk librarian list --json` → `catalog_present: false`, eight `uncatalogued` entries
  with hints, `staging: []`.
- **L1b** (expected refusals — recorded, then continue): `perk librarian list --json 2>&1 | head`
  (`--json` must be the last argument) and `perk librarian add docs https://prek.j178.dev/latest/
  --dry-run` (the door is not admitted).
- **L2** Adopt all eight:

  ```sh
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/pi --kind docs --source https://pi.dev/docs/latest --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/plannotator --kind docs --source https://docs.plannotator.ai/open-source --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/linear --kind docs --source https://linear.app/docs --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/hunk --kind docs --source https://www.hunk.dev/docs/ --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/starlight --kind docs --source https://starlight.astro.build/getting-started/ --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/divio-documentation --kind docs --source https://docs.divio.com/documentation-system/ --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/diffs --kind docs --source https://diffs.com/docs --json
  perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/dbt-duckdb --kind docs --source https://github.com/duckdb/dbt-duckdb --json
  ```

  Expect `action: adopt`, `status: unknown` each. Then `perk librarian list --json` (eight
  entries, `uncatalogued: []`), `ls docs/library/documentation`, and
  `jq '.entries[] | select(.slug=="plannotator") | .upstream.pages | length' docs/library/catalog.json`
  (the inventory-seeded markers; the others have zero).
- **L3** `perk librarian add source nicobailon/pi-subagents --ref v<V> --json` → `cloned`,
  `entry.ref: v<V>`, `status: pinned`, path `…/source-code/github.com/nicobailon/pi-subagents`;
  `git -C <that path> describe --tags --exact-match` → `v<V>`; rerun the `add source` → `reused`.
  Then `perk librarian add source j178/prek --slug prek-source --json` → `cloned`, `ref: null`,
  `status: unknown` (the docs slug `prek` is reserved for L5 — unique slugs span both kinds).
- **L4** `perk librarian check --json` (record the wall-clock): `pi-subagents` → `pinned` /
  `never probed`; `prek-source` → `probed` / `fresh`; each docs entry → `probed` with its
  `evidence` and status (`fresh` or `unverifiable`), or `failed` with the detail. Immediately
  `perk librarian check --json` again → every entry whose first probe recorded `checked_at` is
  `recent` (`pass --force`); a `failed` entry is retried, not throttled. Then
  `perk librarian check plannotator --force --json` → `probed`.
- **L5** `ls docs/library/.staging` (absent or empty), then the tool call
  `run_librarian {action: "add-docs", url: "https://prek.j178.dev/latest/", scope_prefix: "/latest/"}`
  → `published` with `published_path`, `pages_published`, `failures_accepted`, the bracket clean;
  then `perk librarian list --json` (a `prek` docs entry, `unknown`), `ls docs/library/.staging`
  (no `prek` left), `git status --porcelain --untracked-files=all` (unchanged). An `unclean-start`
  result is recorded with the named door and the leg stops — no workaround.
- **L6** `perk librarian check prek --json` → `probed` (the first baseline) with its evidence tier
  and status.
- **L7** The pointer. Shape (a), cold `perk plan`: ask S1 *"Which skill bindings apply in this
  session, and does the perk-plan skill's 'Ground the plan in evidence' section mention the
  librarian skill?"* — expect `perk-plan` delivered and the sentence quoted. Shape (b), warm
  `/plan` inside the cold session: the human toggles `/plan` off and on and asks again — no second
  delivery (instrument: exactly one `perk:binding-context` entry in the S1 JSONL). S1 then
  **waits** (keep it open).
- **L8** (S1, run **last** — after S2, C1–C4 and W1–W2):
  `perk librarian check prek-source --force --json` → `drifted` if `j178/prek`'s `master` moved
  since L3 (capture-if-fired; `fresh` otherwise), then `perk librarian refresh prek-source --json`
  (`fast_forwarded` or `up_to_date`); finally `perk librarian remove prek-source --json` →
  `ls docs/library/source-code/github.com/j178` shows no `prek` leaf and
  `perk librarian list --json` has no `prek-source` entry (an empty `github.com/j178` parent may
  remain — leaf-only deletion is the design, not a defect).

### S2 — the stage-less warm `/plan` session (human)

```sh
cd /Users/mattgiles/dev/github/mattgiles/perk && perk
```

then `/plan`, then the L7 binding question. Expected: plan mode ON, the plan-authoring context
present, **no** skill binding delivered (no `perk-plan`, no pointer), while `librarian` appears in
the session's available skills (its ambient description); `perk librarian list --json` still
admitted. Instrument: no `perk:binding-context` entry in the S2 JSONL.

**Shape (d), `perk objective plan`.** This plan's own authoring session is the observation:
`perk-objective-plan` delivered, no `perk-plan`, and **no `librarian` skill listed** because of the
stale mirror. After P0.4 the implement session records whether
`<main>/.agents/skills/librarian/SKILL.md` exists (its `stages:` exposure to `objective-plan` is
pinned by `tests/test_skill_semantic_contracts.py`; no further live launch is required).

### C1–C4 — the consumer fixture (human; its sessions persist under `~/.pi/agent/sessions/`)

- **C1** Create and wire the fixture:

  ```sh
  mkdir -p /tmp/perk-library-fixture && cd /tmp/perk-library-fixture && git init -q -b main && git commit -q --allow-empty -m init && perk init --no-interactive 2>&1 | tee /tmp/perk-library-dogfood/c1-init.log
  ```

  Record its warnings (no remote). Then edit `.pi/settings.json`: replace the
  `npm:@mgiles/perk@…` package entry, in place, with the string
  `"/Users/mattgiles/dev/github/mattgiles/perk"` (the published package predates the library).
  Commit the wiring and verify:

  ```sh
  git add -A && git commit -q -m "perk init wiring (local perk extension)"
  { git status --porcelain --untracked-files=all; echo "--- crawl script"; ls .agents/skills/librarian/scripts/copy_docs_to_markdown.py; echo "--- library"; test -e docs/library || echo absent; echo "--- packages"; jq '.packages' .pi/settings.json; echo "--- doctor"; perk doctor; } 2>&1 | tee /tmp/perk-library-dogfood/c1-verify.log
  ```

  Expect an empty status, the script present, `absent`, exactly one perk entry (the local path),
  and doctor's `settings-wiring` failing (the consumer convergence requires the npm entry — an
  accepted, recorded deviation for this fixture; the extension-install finding likewise).
- **C2** First use from the fixture's main checkout. Launch `perk` (a plain session) and ask it to
  call `run_librarian {action: "add-docs", url: "https://prek.j178.dev/latest/", scope_prefix: "/latest/"}`
  → `published`. Then, in the terminal:

  ```sh
  { ls docs/library; echo "--- status"; git status --porcelain --untracked-files=all; echo "--- doctor"; perk doctor; } 2>&1 | tee /tmp/perk-library-dogfood/c2-after-publish.log
  perk doctor --fix 2>&1 | tee /tmp/perk-library-dogfood/c2-fix.log
  ```

  Expect `catalog.json documentation` (no README — the child never writes it), an empty status,
  and doctor's `library-readme` failing with remediation `perk doctor --fix`. **`--fix`
  re-converges every drifted managed piece, `settings-wiring` included, and appends
  `npm:@mgiles/perk@…` beside the local path** (`_merge_static_packages` treats the path as a
  different identity) — so immediately re-edit `.pi/settings.json` to delete the npm entry, before
  any further session launch, and verify:

  ```sh
  { jq '.packages' .pi/settings.json; echo "--- status"; git status --porcelain --untracked-files=all; echo "--- doctor"; perk doctor; } 2>&1 | tee /tmp/perk-library-dogfood/c2-after-fix.log
  git add -A && git commit -q -m "library README"
  perk doctor 2>&1 | tee /tmp/perk-library-dogfood/c2-committed.log
  ```

  Expect exactly one perk entry (the local path); `?? docs/library/README.md` (plus the settings
  edit if `--fix` rewrote it); the `library` check warning "not committed"; then, after the
  commit, `library` ok with `settings-wiring` still the accepted deviation.
- **C3** First use from a linked worktree (the committed wiring travels with it):

  ```sh
  git worktree add -q -b wt ../perk-library-fixture-wt && cd ../perk-library-fixture-wt
  { ls docs/library; echo "--- readme"; cat docs/library/README.md; echo "--- list"; perk librarian list; } 2>&1 | tee /tmp/perk-library-dogfood/c3-worktree.log
  ```

  Expect `README.md` only, and absolute paths under `/tmp/perk-library-fixture/docs/library/`.
  Launch `perk` (a plain session in the worktree — its first launch installs the borrowed packages
  into the worktree's own `.pi/npm`) and ask it to call
  `run_librarian {action: "refresh-docs", slug: "prek"}` → `published` (the child ran in the
  fixture's main checkout; the bracket ran on main). Then `ls docs/library 2>&1 | tee
  /tmp/perk-library-dogfood/c3-after.log` — still `README.md` only.
- **C4** Teardown and the proof that `<main>` is untouched:

  ```sh
  cd /tmp/perk-library-fixture && git worktree remove --force ../perk-library-fixture-wt && cd /tmp && rm -rf perk-library-fixture perk-library-fixture-wt
  git -C /Users/mattgiles/dev/github/mattgiles/perk status --porcelain --untracked-files=all 2>&1 | tee /tmp/perk-library-dogfood/c4-teardown.log
  ```

  Expect the status unchanged from P0.1.

### W1–W2 — from the implement session's linked worktree (implement)

Prerequisites: P0.3–P0.4 done; L2 done for W1; L5 done for W2 (the refresh door refuses an absent
`prek` entry and a missing delivered crawl script before any dispatch).

- **W1** `ls docs/library` (only the committed `README.md`), `cat docs/library/README.md`,
  `perk librarian list --json` → `library_root` is `<main>/docs/library`; read the head of
  `<pi entry path>/index.md` by the printed absolute path.
- **W2** The tool call `run_librarian {action: "refresh-docs", slug: "prek"}` from the worktree →
  `published` (corroborated: the entry present and this run's staging claim moved into place), the
  bracket on `<main>` clean; `perk librarian list --json` still one `prek` docs entry.

## Part B — captured evidence + defect log

_Filled from the run's logs and session JSONL. Excerpts are verbatim; long page lists are trimmed
with an explicit count._

### B.1 Run record

| Field | Value |
| --- | --- |
| Date | 2026-09-28 (P0 at 10:48–10:50 local) |
| Run SHA (`<main>` HEAD at P0.1) | `33bf73cde10c8a315d583b99226a47a86bb64f62` (`main`, one local commit "Check in planning doc" ahead of `origin/main` `dc00eb2e`) |
| `perk --version` + interpreter | before P0.3: `perk 3.7.0`, `#!/Users/mattgiles/.local/share/uv/tools/perk/bin/python3` (PyPI build); after: `perk 3.7.0`, `#!/Users/mattgiles/.local/share/uv/tools/perk/bin/python` (editable, `perk==3.7.0 (from file:///Users/mattgiles/dev/github/mattgiles/perk)`, CPython 3.13.9) |
| `pi --version` | `0.87.1` |
| pi-subagents `<V>` | `0.71.0` (P0.6) |
| Child model (`[models.subagents] librarian`) | `openai/gpt-6-sol` (`<main>/.perk/config.toml`) |

### B.2 Session stores

| Actor | Store | Session file (header `cwd`, timestamp) |
| --- | --- | --- |
| S1 | _pending_ | _pending_ |
| S2 | _pending_ | _pending_ |
| C2 | _pending_ | _pending_ |
| C3 | _pending_ | _pending_ |
| implement | _pending_ | _pending_ |

### B.3 Criteria

| Requirement | Leg(s) | Offline pin | State |
| --- | --- | --- | --- |
| `list` reports uncatalogued directories with executable hints | L1 | `tests/test_library_dogfood.py::test_flat_mirrors_adopt_by_the_printed_hints` | _pending_ |
| The read-only gate's admission shape | L1b | `extension/substrate/toolGating.test.ts` ("perk librarian workers are admitted only in their --json-last forms") | _pending_ |
| `record --adopt` catalogs the flat mirrors | L2 | `tests/test_library_dogfood.py::test_flat_mirrors_adopt_by_the_printed_hints` | _pending_ |
| Reuse-first + pinned `add source` | P0.6, L3 | `tests/test_library_dogfood.py::test_source_pin_throttle_drift_and_refresh_sequence` | _pending_ |
| `check`: throttle, `pinned`, source drift via `ls-remote` | L4, L8 (drift capture-if-fired) | `tests/test_library_dogfood.py::test_source_pin_throttle_drift_and_refresh_sequence` | _pending_ |
| `check`: docs evidence tiers incl. `unverifiable` | L4, L6 | `tests/test_librarian_cmd.py::test_check_probes_over_the_transport_seam` (both cases), `tests/test_library_check.py::test_a_validator_less_site_is_unverifiable_never_fresh` | _pending_ |
| `run_librarian` add-docs from a read-only main-checkout parent | L5 | `extension/pi/v1/librarian.test.ts` | _pending_ |
| Consumer first use from its main checkout | C2 | `extension/pi/v1/librarian.test.ts` case (5) | _pending_ |
| Consumer first use from a linked worktree | C3 | `extension/pi/v1/librarian.test.ts` case (6); `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree` (the CLI path) | _pending_ |
| A worktree's README → the main library's absolute paths | W1 | `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree` | _pending_ |
| `perk doctor --fix` converges the committed README | C2 | `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree`, `tests/test_doctor.py::test_library_readme_managed_check_and_fix` | _pending_ |
| `run_librarian` refresh-docs from a linked worktree | W2 | `extension/pi/v1/librarian.test.ts` case (6) | _pending_ |
| `remove` deletes exactly the leaf | L8 | `tests/test_library_ops.py::test_remove_a_source_entry_deletes_only_its_leaf`; story 2 | _pending_ |
| The pointer: cold `perk plan` (a), warm `/plan` in a cold session (b) | L7 | `tests/test_skill_semantic_contracts.py`; `extension/substrate/bindingDelivery.test.ts` | _pending_ |
| The pointer: stage-less warm `/plan` (c) | S2 | `extension/substrate/bindingDelivery.test.ts` ("Mechanism A is a no-op when no stage is launched") | _pending_ |
| The pointer: `perk objective plan` (d) | the authoring session; P0.4 | `tests/test_skill_semantic_contracts.py` | _pending_ |
| The explanation page's `add source` sentence is true | — | `tests/test_explanation_boundary.py` (quadrant guard) | _pending_ |
| Every gap routed | B.7 | — | _pending_ |

### B.4 Pre-run findings

| Id | Observed | Finding | Remediation |
| --- | --- | --- | --- |
| F1 | planning session; confirm at P0.3 | The `perk` on `PATH` is the non-editable PyPI 3.7.0 uv tool install, which predates the group: `perk librarian list --json` → `No such command 'librarian'`, exit 2 — even though the read-only gate admitted the command. | `just install-cli` (`uv tool install --editable . --force`). |
| F2 | planning session; confirmed at P0.2, fixed at P0.4 | `<main>/.agents/skills/` symlinks into the skills-CLI cache at `87c1514d` (synced 2026-09-26 13:15), which predates the `librarian` skill: no `librarian`, the retired `copy-docs-to-markdown` still linked. `run_librarian` and the docs doors would refuse `skill_missing`, and the planning session's available skills carried no `librarian`. P0.2: `".agents/skills/librarian": No such file or directory (os error 2)`. | `perk init` re-syncs `.agents/skills/` from `github.com/mattgiles/perk@main` — P0.4: `.agents/skills/: synchronized via skills update --sync`; the links now resolve into the cache at `dc00eb2e`. |
| F3 | P0.2 | P0.2 runs whichever `perk` is on `PATH` — here the pre-library PyPI build, so its doctor is the old build's view: three version-skew drift failures (`runner-workflow`, `gitignore-block`, `skills-manifest`, each `updated`) and a **green** `skills-delivery` while `.agents/skills/librarian` was absent (that build's managed skill set has no `librarian`). Not a doctor blind spot: the checkout's doctor over the same stale-link shape (the implement worktree's `.agents/skills/`, materialized from `<main>`'s links before P0.4) fails it — `✗ skills-delivery: 2 perk skill(s) not delivered — delivered set stale — .agents/skills/ lacks librarian, perk-simplify present on origin/main`. After P0.3 + P0.4, P0.5's doctor is healthy with no drift. | Record-only (operator environment). |
| F4 | implement session | The implement worktree's `.agents/skills/` was materialized at worktree creation (2026-09-28 10:30) from `<main>`'s then-stale links, so this implementing session's available skills carry no `librarian` even though its `stages:` include `implement`; P0.4 fixed `<main>` only. | Record-only (operator environment; a fresh worktree after P0.4 carries the skill). |

### B.5 Per-leg excerpts

**P0 (human, 2026-09-28 10:48–10:50, logs `/tmp/perk-library-dogfood/p0.*.log`).**

- P0.1 — status empty; `--- HEAD` `33bf73cde10c8a315d583b99226a47a86bb64f62`.
- P0.2 (the PyPI 3.7.0 build — see F3):

  ```text
  ✗ repository (5/7 checks)
     ✗ runner-workflow: runner-workflow drift — .github/actions/perk-remote-setup/action.yml: updated
     ✗ gitignore-block: gitignore-block drift — .gitignore: updated
  ✓ registry (1 checks)
  ✗ skills (2/3 checks)
     ✗ skills-manifest: skills-manifest drift — .agents/manifest.d/perk.yaml: updated
  …
  ✗ 3 check(s) failed
  --- librarian skill
  ".agents/skills/librarian": No such file or directory (os error 2)
  ```

- P0.3 — before: `perk 3.7.0` / `#!/Users/mattgiles/.local/share/uv/tools/perk/bin/python3` /
  `Error: No such command 'librarian'.`; `just install-cli` → `+ perk==3.7.0 (from
  file:///Users/mattgiles/dev/github/mattgiles/perk)` / `Installed 1 executable: perk`; after:
  `perk librarian --help` lists `add`, `check`, `list`, `prepare`, `record`, `refresh`, `remove`
  (the six worker verbs plus the `prepare` worker the `run_librarian` tool drives).
- P0.4 — `perk init`: `Converged:` / `- .agents/skills/: synchronized via skills update --sync`;
  verify: `.agents/skills/librarian/scripts/copy_docs_to_markdown.py` present (25k); the
  `copy-docs` grep empty (the retired link is gone — no hand removal needed); the pointer
  delivered at `.agents/skills/perk-plan/SKILL.md:125` (`When a plan leans on an external
  dependency's docs or source, the `librarian` skill (read`); status empty (no tracked file
  touched). `.agents/skills/librarian` → `…/perk/dc00eb2e3e14c055116c36a13f630d9c2584c0ca/skills/librarian`.
- P0.5 — `/usr/bin/curl`, `/opt/homebrew/bin/html2markdown`; doctor `✓ healthy (40 ok)` with
  `• library: 8 uncatalogued library directories — uncatalogued: dbt-duckdb, diffs,
  divio-documentation, hunk, linear, pi, plannotator, starlight` (plus the standing
  `subagent-compat` / `cache-gc` warnings, unrelated); status empty.
- P0.6 — `0.71.0`; `.pi/npm/node_modules/pi-subagents/src` (15 directories) and `/docs` (10
  pages) installed; `prek` → `/Users/mattgiles/.local/bin/prek` (a binary, no local source).

### B.6 Fixture deviations

| Deviation | Why | Accepted? |
| --- | --- | --- |
| _pending_ | | |

### B.7 Defect / gap log

| Id | Leg | Observation | Disposition |
| --- | --- | --- | --- |
| _pending_ | | | |

### B.8 Teardown proof

_pending_
