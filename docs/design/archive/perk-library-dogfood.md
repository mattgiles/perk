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

**Record settled (2026-09-28).** Every live leg ran; every criteria row is **observed-live** (no
waivers). One leg needed an operator decision — L5's `/latest/` seed had become a redirect alias
page, so it was reissued at `/0.5.4/` (B.6 V1). Routed: the crawl's HTML-redirect gap as objective
node 2551/3.4, the stage-less warm `/plan` binding gap as plan-scoped gist #2613; everything else
record-only (B.7). The teardown is attested (B.8).

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
  result is recorded with the named door and the leg stops — no workaround. **Run note
  (2026-09-28):** `/latest/` had become a mike version-alias redirect page, so the child stopped
  before mutation (B.7 D1); L5 was reissued at `url: "https://prek.j178.dev/0.5.4/"`,
  `scope_prefix: "/0.5.4/"` (B.6 V1). A rerun first resolves the alias (`curl -sS
  https://prek.j178.dev/versions.json`) and uses the version path it names — here and in C2.
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

  Expect `README.md` only, and absolute paths under `/tmp/perk-library-fixture/docs/library/`
  (macOS prints `/private/tmp/…` — git reports the resolved path).
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
| Date | 2026-09-28, 14:48Z (P0) → 17:55Z (L8); local time is UTC−4 |
| Run SHA (`<main>` HEAD at P0.1) | `33bf73cde10c8a315d583b99226a47a86bb64f62` (`main`, one local commit "Check in planning doc" ahead of `origin/main` `dc00eb2e`) |
| `perk --version` + interpreter | before P0.3: `perk 3.7.0`, `#!/Users/mattgiles/.local/share/uv/tools/perk/bin/python3` (PyPI build); after: `perk 3.7.0`, `#!/Users/mattgiles/.local/share/uv/tools/perk/bin/python` (editable, `perk==3.7.0 (from file:///Users/mattgiles/dev/github/mattgiles/perk)`, CPython 3.13.9) |
| `pi --version` | `0.87.1` |
| pi-subagents `<V>` | `0.71.0` (P0.6) |
| Child model (`[models.subagents] librarian`) | `openai/gpt-6-sol` (`<main>/.perk/config.toml`) |

Blob pins at the run SHA for every file a finding cites (`git rev-parse 33bf73cd:<path>`; each
also equals this branch's blob — the gate changed no runtime code):

| Path | Blob | Cited by |
| --- | --- | --- |
| `skills/librarian/scripts/copy_docs_to_markdown.py` | `db98a2095cf148f3d48e05cc1eb0d3123dfc9e31` | D1 |
| `skills/perk-plan/SKILL.md` | `2291718297699df06445d138e02ba83a2a5952f1` | L7, S2 |
| `extension/substrate/bindingDelivery.ts` | `fb010f818ef8daae2dc4b8bee2bbed8ab0bd0d5f` | G1 |
| `extension/substrate/toolGating.ts` | `aeaf89394d566d9d7f220b3dd9f2115ff40514a1` | L1b, G1 |
| `extension/pi/v1/contextInjection.ts` | `6ddb5f9a759e90dec57ac545b594adb742db380d` | G1 |
| `src/perk/convergence/init/settings.py` | `a35d8e92609005820d1326ae9dd2eb7bb713ac81` | V2, V4, O5 |
| `src/perk/convergence/doctor/checks.py` | `adaed77ba8568d32de043753c8287c487902eb89` | F3 |
| `src/perk/library/ops.py` | `314a8cfa41d5008bb8a88f0d1361da11094ed85f` | O3, O4 |
| `src/perk/library/check.py` | `710b709f1efb300b8e422fb45d5e41584f9b5d87` | L4, L8 |
| `src/perk/library/docs_session.py` | `a1fe6320c90792cc87d1b044cd3c4be46445231c` | O1 |

### B.2 Session stores

| Actor | Store | Session file (header `cwd`, timestamp) |
| --- | --- | --- |
| S1 | `<main>/.pi/agent/sessions/` | `--Users-mattgiles-dev-github-mattgiles-perk--/2026-09-28T14-54-04-711Z_01a0e882-3da6-7148-b9df-31f6ebe6a5ce.jsonl` (cwd `<main>`, 14:54:04Z); its `perk.librarian` children under the sibling directory: `42c543d8-…/run-0/session.jsonl` (L5 first attempt, 14:58:04Z) and `93027ef3-…/run-0/session.jsonl` (L5 reissue, 15:07:36Z), both cwd `<main>` |
| S2 | `<main>/.pi/agent/sessions/` | `--Users-mattgiles-dev-github-mattgiles-perk--/2026-09-28T15-41-03-527Z_01a0e8ad-40a6-729c-bbc4-67f9ddfaf66e.jsonl` (cwd `<main>`, 15:41:03Z) |
| C2 | `~/.pi/agent/sessions/` | `--private-tmp-perk-library-fixture--/2026-09-28T15-53-56-809Z_01a0e8b9-0d48-76e9-aa37-31d1cf5bab61.jsonl` (cwd `/private/tmp/perk-library-fixture`, 15:53:56Z); child `cc04161c-…/run-0/session.jsonl` (cwd the fixture's main checkout, 15:55:21Z) |
| C3 | `~/.pi/agent/sessions/` | `--private-tmp-perk-library-fixture-wt--/2026-09-28T17-31-06-510Z_01a0e912-018e-74a3-9094-4cdf86ed08ce.jsonl` (cwd `/private/tmp/perk-library-fixture-wt`, 17:31:06Z); child `d7564d13-…/run-0/session.jsonl` (cwd `/private/tmp/perk-library-fixture` — the fixture's main checkout, 17:32:09Z) |
| implement | `<main>/.pi/agent/sessions/` | `--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2612--/2026-09-28T14-31-04-511Z_01a0e86d-2e3e-7111-ba1c-7844f41d4ec3.jsonl` (cwd `<main>/.worktrees/plan-2612`, 14:31:04Z; `PI_CODING_AGENT_DIR=<main>/.pi/agent`); the W2 child `660c70e3-…/run-0/session.jsonl` (cwd `<main>`, 15:25:01Z) |

### B.3 Criteria

| Requirement | Leg(s) | Offline pin | State |
| --- | --- | --- | --- |
| `list` reports uncatalogued directories with executable hints | L1 | `tests/test_library_dogfood.py::test_flat_mirrors_adopt_by_the_printed_hints` | **observed-live** (2026-09-28) |
| The read-only gate's admission shape | L1b | `extension/substrate/toolGating.test.ts` ("perk librarian workers are admitted only in their --json-last forms") | **observed-live** (2026-09-28) |
| `record --adopt` catalogs the flat mirrors | L2 | `tests/test_library_dogfood.py::test_flat_mirrors_adopt_by_the_printed_hints` | **observed-live** (2026-09-28) |
| Reuse-first + pinned `add source` | P0.6, L3 | `tests/test_library_dogfood.py::test_source_pin_throttle_drift_and_refresh_sequence` | **observed-live** (2026-09-28) |
| `check`: throttle, `pinned`, source drift via `ls-remote` | L4, L8 (drift capture-if-fired) | `tests/test_library_dogfood.py::test_source_pin_throttle_drift_and_refresh_sequence` | **observed-live** (2026-09-28) — throttle and `pinned` at L4; drift **fired** at L8 (`j178/prek` `master` moved to `bb2d545f` at 15:09:23Z, after the 14:56:48Z clone) |
| `check`: docs evidence tiers incl. `unverifiable` | L4, L6 | `tests/test_librarian_cmd.py::test_check_probes_over_the_transport_seam` (both cases), `tests/test_library_check.py::test_a_validator_less_site_is_unverifiable_never_fresh` | **observed-live** (2026-09-28) — all three tiers: `strong` (6 docs entries), `weak` (`linear`, `starlight`), `none` → `unverifiable` (`pi`) |
| `run_librarian` add-docs from a read-only main-checkout parent | L5 | `extension/pi/v1/librarian.test.ts` | **observed-live** (2026-09-28) — at `/0.5.4/` after the `/latest/` stop (B.6 V1, B.7 D1) |
| Consumer first use from its main checkout | C2 | `extension/pi/v1/librarian.test.ts` case (5) | **observed-live** (2026-09-28) |
| Consumer first use from a linked worktree | C3 | `extension/pi/v1/librarian.test.ts` case (6); `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree` (the CLI path) | **observed-live** (2026-09-28) |
| A worktree's README → the main library's absolute paths | W1 | `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree` | **observed-live** (2026-09-28) |
| `perk doctor --fix` converges the committed README | C2 | `tests/test_library_dogfood.py::test_first_use_from_a_consumer_main_checkout_and_linked_worktree`, `tests/test_doctor.py::test_library_readme_managed_check_and_fix` | **observed-live** (2026-09-28) |
| `run_librarian` refresh-docs from a linked worktree | W2 | `extension/pi/v1/librarian.test.ts` case (6) | **observed-live** (2026-09-28) |
| `remove` deletes exactly the leaf | L8 | `tests/test_library_ops.py::test_remove_a_source_entry_deletes_only_its_leaf`; story 2 | **observed-live** (2026-09-28) |
| The pointer: cold `perk plan` (a), warm `/plan` in a cold session (b) | L7 | `tests/test_skill_semantic_contracts.py`; `extension/substrate/bindingDelivery.test.ts` | **observed-live** (2026-09-28) |
| The pointer: stage-less warm `/plan` (c) | S2 | `extension/substrate/bindingDelivery.test.ts` ("Mechanism A is a no-op when no stage is launched") | **observed-live** (2026-09-28) — the gap confirmed (no delivery) and routed (B.7 G1) |
| The pointer: `perk objective plan` (d) | the authoring session; P0.4 | `tests/test_skill_semantic_contracts.py` | **observed-live** (2026-09-28): the authoring session delivered only `perk-objective-plan`; after P0.4 the skill is delivered |
| The explanation page's `add source` sentence is true | — | `tests/test_explanation_boundary.py` (quadrant guard) | n/a (a docs change, not a live leg) — corrected in this branch; the truth-sweep grep (`rg -n "pins it to\|pinned to the version\|pin to the version" docs skills shared CONTEXT.md`) re-run: the remaining hits are the instructions to pass `--ref` and the explanation page's example of something worth curating, all true |
| Every gap routed | B.7 | — | done — gist #2613, objective node 2551/3.4; the rest record-only |

### B.4 Pre-run findings

| Id | Observed | Finding | Remediation |
| --- | --- | --- | --- |
| F1 | planning session; confirm at P0.3 | The `perk` on `PATH` is the non-editable PyPI 3.7.0 uv tool install, which predates the group: `perk librarian list --json` → `No such command 'librarian'`, exit 2 — even though the read-only gate admitted the command. | `just install-cli` (`uv tool install --editable . --force`). |
| F2 | planning session; confirmed at P0.2, fixed at P0.4 | `<main>/.agents/skills/` symlinks into the skills-CLI cache at `87c1514d` (synced 2026-09-26 13:15), which predates the `librarian` skill: no `librarian`, the retired `copy-docs-to-markdown` still linked. `run_librarian` and the docs doors would refuse `skill_missing`, and the planning session's available skills carried no `librarian`. P0.2: `".agents/skills/librarian": No such file or directory (os error 2)`. | `perk init` re-syncs `.agents/skills/` from `github.com/mattgiles/perk@main` — P0.4: `.agents/skills/: synchronized via skills update --sync`; the links now resolve into the cache at `dc00eb2e`. |
| F3 | P0.2 | P0.2 runs whichever `perk` is on `PATH` — here the pre-library PyPI build, so its doctor is the old build's view: three version-skew drift failures (`runner-workflow`, `gitignore-block`, `skills-manifest`, each `updated`) and a **green** `skills-delivery` while `.agents/skills/librarian` was absent (that build's managed skill set has no `librarian`). Not a doctor blind spot: the checkout's doctor over the same stale-link shape (the implement worktree's `.agents/skills/`, materialized from `<main>`'s links before P0.4) fails it — `✗ skills-delivery: 2 perk skill(s) not delivered — delivered set stale — .agents/skills/ lacks librarian, perk-simplify present on origin/main`. After P0.3 + P0.4, P0.5's doctor is healthy with no drift. | Record-only (operator environment). |
| F4 | implement session | The implement worktree's `.agents/skills/` was materialized at worktree creation (2026-09-28 10:30) from `<main>`'s then-stale links, so this implementing session's available skills carry no `librarian` even though its `stages:` include `implement`; P0.4 fixed `<main>` only. | Record-only (operator environment; a fresh worktree after P0.4 carries the skill). |

### B.5 Per-leg excerpts

**P0 (human, 2026-09-28 10:48–10:50 local = 14:48–14:50Z, logs `/tmp/perk-library-dogfood/p0.*.log`).**

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

**S1 (cold `perk plan`, 14:54:04Z; excerpts are the tool results in the S1 JSONL).** The session
confirmed `stage: plan`, `mode: read-only` (the first `perk:workflow-state` entry).

- L1 (14:54:43Z) — `"library_root": "/Users/mattgiles/dev/github/mattgiles/perk/docs/library",
  "catalog_present": false, "entries": []`, eight `uncatalogued` items (`dbt-duckdb`, `diffs`,
  `divio-documentation`, `hunk`, `linear`, `pi`, `plannotator`, `starlight`), each with
  `"hint": "perk librarian record --adopt /Users/mattgiles/dev/github/mattgiles/perk/docs/library/<name> --kind docs --source <url>"`,
  `"staging": []`.
- L1b — both refused by the gate, verbatim:

  ```text
  perk read-only mode: command blocked (not allowlisted).
  Command: perk librarian list --json 2>&1 | head
  Reason: not allowlisted: perk librarian list --json 2>&1
  ```

  ```text
  perk read-only mode: command blocked (not allowlisted).
  Command: perk librarian add docs https://prek.j178.dev/latest/ --dry-run
  Reason: not allowlisted: perk librarian add docs https://prek.j178.dev/latest/ --dry-run
  ```

- L2 (14:55:04–14:55:45Z) — eight adoptions, each
  `{"success": true, …, "action": "adopt", "entry": {"kind": "docs", "slug": "<name>", …, "path": "/Users/mattgiles/dev/github/mattgiles/perk/docs/library/documentation/<name>", "present": true, …, "status": "unknown"}, "replaced_previous": false, "warnings": []}`;
  then `list --json` → eight entries, `"uncatalogued": [], "staging": []`; `ls
  docs/library/documentation` → the eight names; the `plannotator` marker count → `48` (the
  inventory seeded one marker per page; the others hold none).
- L3 — `<V>` = `0.71.0`; `add source nicobailon/pi-subagents --ref v0.71.0 --json` (11 s) →
  `"action": "cloned"`, `"source": "https://github.com/nicobailon/pi-subagents.git"`,
  `"path": "…/docs/library/source-code/github.com/nicobailon/pi-subagents"`, `"ref": "v0.71.0"`,
  `"stale_after": 86400`, `"status": "pinned"`; `git … describe --tags --exact-match` →
  `v0.71.0`; the rerun → `"action": "reused"`, still `"ref": "v0.71.0"`, `"status": "pinned"`;
  `add source j178/prek --slug prek-source --json` → `"action": "cloned"`,
  `"path": "…/source-code/github.com/j178/prek"`, `"ref": null`, `"status": "unknown"`.
- L4 — first `check --json` (wall clock `Mon Sep 28 14:56:59 UTC 2026` → result 14:57:17Z;
  every `checked_at` `2026-09-28T14:57:07Z`), no `failed` results and `"warnings": []`:

  | Entry | `action` | `evidence` | status |
  | --- | --- | --- | --- |
  | `dbt-duckdb`, `diffs`, `divio-documentation`, `hunk`, `plannotator` | `probed` | `strong` | `fresh` |
  | `linear`, `starlight` | `probed` | `weak` | `fresh` |
  | `pi` | `probed` | `none` | `unverifiable` |
  | `pi-subagents` | `pinned` (`"detail": "pinned at v0.71.0 — never probed"`) | `none` | `pinned` |
  | `prek-source` | `probed` | `strong` | `fresh` |

  Second `check --json` (`Mon Sep 28 14:57:23 UTC 2026`) → every probed entry `recent`, e.g.
  `"detail": "checked 23s ago, window 14d — pass --force to probe anyway"` (docs) and `"checked
  23s ago, window 1d — pass --force to probe anyway"` (`prek-source`); `pi-subagents` still
  `pinned`. `check plannotator --force --json` → `"action": "probed"`, `"checked_at":
  "2026-09-28T14:57:38Z"`, `strong` / `fresh`.
- L5, first attempt (14:57:57Z) — `ls docs/library/.staging` → `No such file or directory`;
  `run_librarian {action: "add-docs", url: "https://prek.j178.dev/latest/", scope_prefix: "/latest/"}`
  → `run_librarian failed: The perk.librarian child ended natively as failed; no record is
  trusted. The staging directory /Users/mattgiles/dev/github/mattgiles/perk/docs/library/.staging/prek
  is still in place for inspection. Nothing was reverted.` (`"error_type": "native-failed"`,
  `"bracket": {"ok": true}`). Before ending, the child raised a supervisor request (14:58:52Z):

  > Scope blocker before any write: https://prek.j178.dev/latest/ serves only a 382-byte
  > JavaScript redirect to ../0.5.4/, outside the prepared /latest/ scope. The required dry run
  > discovers exactly 1 page (the redirect), so the exact mandated crawl/publish would create a
  > near-empty, unusable mirror. May I stop this task before mutation and request a reissued task
  > with source URL https://prek.j178.dev/0.5.4/ and scope /0.5.4/, or do you prefer publishing
  > the redirect-only mirror? I cannot change the prepared commands myself.

  S1 replied "Stop before any mutation …" per its standing rule; the child's final record:
  `"outcome": "stopped-before-mutation"`, `"pages_published": 0`. Post-state: `.staging/prek`
  empty, `list --json` unchanged apart from `"staging": [{"name": "prek", …}]`, git status empty.
  The human removed the empty directory (`rmdir`) and reissued L5 (B.6 V1).
- L5, reissue (15:07:27Z) — `ls docs/library/.staging` → empty; `run_librarian {action:
  "add-docs", url: "https://prek.j178.dev/0.5.4/", scope_prefix: "/0.5.4/"}` (12 min 24 s) →
  `Published documentation entry `prek` → /Users/mattgiles/dev/github/mattgiles/perk/docs/library/documentation/prek
  (status unknown; pages published 26, failures accepted 0, scope /0.5.4/).` Receipt:
  `"cwd": "/Users/mattgiles/dev/github/mattgiles/perk"`, `"termination": "confirmed"`,
  `"nativeStatus": "completed"`, `"exitCode": 0`, `"bracket": {"ok": true}`. The child's summary
  (untrusted DATA): "Published 26 prek 0.5.4 documentation pages under /0.5.4/ with index.md as
  the entrypoint. Pruned the changelog and homepage marketing sections; …". Then `list --json`
  → a `prek` docs entry (`"source": "https://prek.j178.dev/0.5.4/"`, `"status": "unknown"`),
  `"staging": []`; `ls docs/library/.staging` → empty; git status → empty.
- L6 (15:20:15Z) — `check prek --json` → `"action": "probed"`, `"checked_at":
  "2026-09-28T15:20:16Z"`, `"evidence": "strong"`, `"status": "fresh"`.
- L7 (a) (15:20:47Z) — S1: "**Bindings delivered to this session:** exactly one — `perk-plan`
  (…) No `perk-objective-plan`", the pointer sentence quoted verbatim from
  `.agents/skills/perk-plan/SKILL.md:125–127` ("When a plan leans on an external dependency's docs
  or source, the `librarian` skill (read `.agents/skills/librarian/SKILL.md`) knows what the repo
  already keeps offline and when a check or an addition is worth it."), and `librarian` listed in
  its available skills. (b) — the human toggled `/plan` (`perk:workflow-state` `{"mode":
  "read-write"}` at 15:23:18Z, `{"mode": "read-only"}` at 15:23:21Z) and asked again (15:23:30Z):
  "still exactly one — `perk-plan` … Nothing new was injected into my context on this turn after
  the `/plan` toggle". Instrument: the S1 JSONL holds exactly **one** `perk:binding-context`
  entry (14:54:18Z, content `The following skill binding(s) apply here:` / ``Follow the
  `perk-plan` skill (read `.agents/skills/perk-plan/SKILL.md`).``).

**Shape (d), the authoring session** (`2026-09-28T13-08-22-424Z_01a0e821-…jsonl`, cwd `<main>`,
`"stage": "objective-plan"`, node claim 2551/3.3): its cold prompt carried `The following skill
binding(s) apply here:` / ``Follow the `perk-objective-plan` skill (…)`` and no `perk-plan`; the
missing `librarian` skill is that session's own report (the plan's pre-run findings — the
system prompt's skill list is not persisted). After P0.4,
`<main>/.agents/skills/librarian/SKILL.md` exists (8606 bytes, 10:50 local).

**S2 (plain `perk` + `/plan`, 15:41:03Z).** The workflow state: `{"run_id": "01M3MATVTW5FDVDFNFY5S6GZNC", …, "perk_version": "3.7.0"}` (no
`stage`), then `{"mode": "read-only"}` at 15:41:27Z (the `/plan` toggle); `perk:mode-context`,
`perk:plan-context` and `perk:plan-adapter-plannotator` injected; **no** `perk:binding-context`
entry. Asked the three-part question, S2 read `skills/perk-plan/SKILL.md` and
`shared/bindings.yaml` itself and answered "(1) … This is a `plan`-stage session, so the one
binding that fires at session entry is **`stage:plan` → `perk-plan` (mode: nudge)**" — an
inference from the bindings file, not a delivery (the JSONL has none; the session is
stage-less); "(2) Yes — listed at `/Users/mattgiles/dev/github/mattgiles/perk/.agents/skills/librarian/SKILL.md`";
"(3) The command was **allowed** by the read-only bash gate." (`perk librarian list --json` →
`"success": true`, 10 entries).

**W1 (implement, 15:02:58Z, from `<main>/.worktrees/plan-2612`).** `ls -la docs/library` →
`README.md` only (943 bytes, byte-equal to `LIBRARY_README`; `git ls-files docs/library` →
`docs/library/README.md`); `perk librarian list --json` → `"library_root":
"/Users/mattgiles/dev/github/mattgiles/perk/docs/library"`, `"catalog_present": true`, the `pi`
entry `"path": "/Users/mattgiles/dev/github/mattgiles/perk/docs/library/documentation/pi"`,
`"present": true`; reading `<that path>/index.md` by the absolute path → `# Pi Documentation
Index` / `Source: https://pi.dev/docs/latest (Version: Latest)`.

**W2 (implement, 15:24:51Z → 15:32:11Z).** Before: `<main>` status empty, HEAD `33bf73cd`,
`.staging/` empty, the `prek` entry `strong` / `fresh`, its `sources.json` `scope_prefix`
`/0.5.4/`. `run_librarian {action: "refresh-docs", slug: "prek"}` → `Published documentation
entry `prek` → /Users/mattgiles/dev/github/mattgiles/perk/docs/library/documentation/prek (status
unknown; pages published 26, failures accepted 0, scope /0.5.4/).` Receipt: `"action":
"refresh-docs"`, `"cwd": "/Users/mattgiles/dev/github/mattgiles/perk"` (the child ran in the
main checkout), `"parentSessionId": "01a0e86d-2e3e-7111-ba1c-7844f41d4ec3"` (this worktree
session), `"termination": "confirmed"`, `"exitCode": 0`, `"bracket": {"ok": true}`. After:
`<main>` status empty and HEAD unchanged, `.staging/` empty, `list --json` still exactly one
`prek` docs entry (now `"checked_at": null`, `"evidence": "none"`, `"status": "unknown"` — a
republish records the new revision with fresh markers), the worktree's `docs/library` still
`README.md` only, the worktree status empty.

**C1 (human, `/tmp/perk-library-fixture`, logs `c1-*.log`).** `perk init --no-interactive` →
`✓ perk init (consumer)` with `Converged:` including `.pi/settings.json: added
npm:@mgiles/perk@3.7.0, …`, `.agents/skills/: synchronized via skills update --sync` and
`.pi/npm/node_modules/@mgiles/perk: installed @mgiles/perk@3.7.0 (perk-owned)` (no remote-related
warning in the init output; doctor later reports `⚠ github-repo: no GitHub repo — no git remotes
found`). After the in-place `jq` swap and the commit (`8667ee1 perk init wiring (local perk
extension)`): status empty; `.agents/skills/librarian/scripts/copy_docs_to_markdown.py` present;
`absent`; `.packages` = `["/Users/mattgiles/dev/github/mattgiles/perk", "npm:@tombell/pi-diff",
"npm:pi-subagents", "npm:@ff-labs/pi-fff", "npm:@juicesharp/rpiv-ask-user-question",
"npm:@juicesharp/rpiv-todo", {"source": "npm:@dietrichgebert/ponytail", …}, {"source":
"npm:pi-web-access"}]` (exactly one perk entry); doctor `✗ settings-wiring: settings-wiring drift
— .pi/settings.json: added npm:@mgiles/perk@3.7.0; moved npm:@mgiles/perk@3.7.0 before
npm:pi-subagents` (V2), `✓ library (2 checks)`, `✗ 1 check(s) failed`.

**C2 (plain `perk` in the fixture, 15:53:56Z).** `run_librarian {action: "add-docs", url:
"https://prek.j178.dev/0.5.4/", scope_prefix: "/0.5.4/"}` (5 min 31 s) → `Published
documentation entry `prek` → /private/tmp/perk-library-fixture/docs/library/documentation/prek
(status unknown; pages published 25, failures accepted 0, scope /0.5.4/).` Receipt: `"cwd":
"/private/tmp/perk-library-fixture"`, `"termination": "confirmed"`, `"exitCode": 0`, `"bracket":
{"ok": true}`; the child model `openai/gpt-6-sol` (the fixture configures none — the default).
The tool exists only in the checkout's extension (`git grep run_librarian v3.7.0 -- extension` is
empty), so the local-path package entry is what loaded (V3). Terminal:

- `ls docs/library` → `documentation` / `catalog.json` (no README); status empty; doctor
  `✗ library-readme: library-readme drift — docs/library/README.md: created` with remediation
  `perk doctor --fix`.
- `perk doctor --fix` → `Fixed` / `- .pi/settings.json: added npm:@mgiles/perk@3.7.0; moved
  npm:@mgiles/perk@3.7.0 before npm:pi-subagents` / `- docs/library/README.md: created`, and
  `⚠ library: docs/library/README.md is not committed — readme: docs/library/README.md is
  untracked`.
- After deleting the re-added npm entry (V4): `.packages` again has exactly one perk entry (the
  local path); status `?? docs/library/README.md` only (the re-edited settings are byte-equal to
  the committed ones); doctor `⚠ library: docs/library/README.md is not committed`.
- `git commit` (`e0d4b4b library README`, `docs/library/README.md | 18 ++++`) → doctor
  `✓ library (2 checks)`, `settings-wiring` still the accepted deviation.

**C3 (the fixture's linked worktree `/tmp/perk-library-fixture-wt`).** Before: `ls -la
docs/library` → `README.md` (943 bytes) only; `cat` → the managed README; `perk librarian list`
→ `library: /private/tmp/perk-library-fixture/docs/library` / `unknown docs prek
/private/tmp/perk-library-fixture/docs/library/documentation/prek never checked`; the committed
single-perk-entry `.packages`. The plain `perk` session (17:31:06Z; its first launch populated the
worktree's own `.pi/npm/node_modules`) → `run_librarian {action: "refresh-docs", slug: "prek"}`
(7 min 43 s) → `Published documentation entry `prek` →
/private/tmp/perk-library-fixture/docs/library/documentation/prek (status unknown; pages published
25, failures accepted 0, scope /0.5.4/).` Receipt: `"cwd": "/private/tmp/perk-library-fixture"`
(the child ran in the fixture's main checkout), `"parentSessionId":
"01a0e912-018e-74a3-9094-4cdf86ed08ce"` (the worktree session), `"bracket": {"ok": true}`.
After: the worktree's `docs/library` still `README.md` only; worktree and main status both empty.

**C4 (teardown).** `"/tmp/perk-library-fixture": No such file or directory (os error 2)` /
`"/tmp/perk-library-fixture-wt": No such file or directory (os error 2)`; `<main>` status empty.

**L8 (S1, 17:55:18Z).**

- `check prek-source --force --json` → `"action": "probed"`, `"checked_at":
  "2026-09-28T17:55:24Z"`, `"evidence": "strong"`, `"drifted": true`, `"status": "drifted"` —
  capture-if-fired: `j178/prek` `master` had moved (`gh api repos/j178/prek/commits/master` →
  `bb2d545f2c475d6cf731affb9351af0c8e835efa 2026-09-28T15:09:23Z`, after the L3 clone).
- `refresh prek-source --json` → `"action": "fast_forwarded"`, `"previous_head":
  "77c4056ce76b600de77d5d425e52844a76652a58"`, `"drifted": false`, `"status": "fresh"`.
- `remove prek-source --json` → `{"success": true, …, "slug": "prek-source", "kind": "source",
  "path": "/Users/mattgiles/dev/github/mattgiles/perk/docs/library/source-code/github.com/j178/prek",
  "content_removed": true}`; `ls docs/library/source-code/github.com/j178` → empty (the empty
  `j178` parent remains, O4); `list --json` → no `prek-source` entry (slugs `dbt-duckdb`,
  `diffs`, `divio-documentation`, `hunk`, `linear`, `pi`, `pi-subagents`, `plannotator`, `prek`,
  `starlight`), `"uncatalogued": []`, `"staging": []`.

### B.6 Fixture deviations

| Id | Deviation | Why | Accepted? |
| --- | --- | --- | --- |
| V1 | L5 reissued at `url: "https://prek.j178.dev/0.5.4/"`, `scope_prefix: "/0.5.4/"` instead of `/latest/`; the empty `.staging/prek` the stopped run left was removed by hand (`rmdir`) first. | `/latest/` is now a mike version-alias redirect page (`last-modified: Mon, 28 Sep 2026 04:57:06 GMT`; `<meta http-equiv="refresh" content="1; url=../0.5.4/" />` inside `<noscript>` plus a `window.location.replace("../0.5.4/" …)` script); `versions.json` lists `0.5.4` with `"aliases": ["latest"]`. The planning-time sitemap count still holds (the root `sitemap.xml` lists 27 `<loc>` entries, all under `/0.5.4/`); what the plan missed is that `/latest/` is an alias page, not a copy of the docs. | Yes — operator decision, 2026-09-28 (chosen over `/0.4.14/`, the locally installed `prek 0.4.14`, and over waiving L5/L6/W2/C2/C3). |
| V2 | The fixture's doctor fails `settings-wiring` throughout. | The consumer convergence requires `npm:@mgiles/perk@3.7.0`, and the fixture replaced it with the checkout's absolute path because the published package predates the library. | Yes — planned, fixture-only. |
| V3 | `perk init` installed the published `@mgiles/perk@3.7.0` into the fixture's `.pi/npm`, so `extension-install` passed, but the session loaded the local-path package. | pi loads the packages `settings.json` lists; the npm copy is unused. Proof the checkout's extension loaded: `run_librarian` does not exist at `v3.7.0` yet both fixture sessions called it. | Yes — fixture-only. |
| V4 | After `perk doctor --fix` the npm perk entry was deleted again before any further launch. | `--fix` re-converges every drifted managed piece, `settings-wiring` included, and `_merge_static_packages` treats the local path as a different identity. | Yes — planned (Part A C2). |
| V5 | The fixture's paths print as `/private/tmp/…`, not `/tmp/…`. | macOS `/tmp` is a symlink; git reports the resolved main-worktree path. | Yes — cosmetic; Part A's C3 expectation now says so. |

### B.7 Defect / gap log

| Id | Leg | Observation | Disposition |
| --- | --- | --- | --- |
| D1 | L5 | A seed URL that is an HTML redirect page (a mike version alias: meta-refresh + script, served `200`) is not followed — the crawl follows HTTP redirects only (`curl --location --max-redirs 5`) — so the dry run discovers one page, the redirect stub. The judgment layer caught it (the child stopped before mutation and asked for a reissue), but the cost is a failed `run_librarian` run and a leftover empty staging claim the human removes by hand. | Objective node **2551/3.4** (`crawl-seed-html-redirects`, pending, depends on 3.3) — `perk objective node-add 2551 --phase 3 --depends-on 3.3 --slug crawl-seed-html-redirects …` → `"node": "3.4"`. |
| G1 | S2 | The stage-less warm `/plan` receives no `stage:plan` binding — no `perk-plan`, so no `librarian` pointer — while it does receive the plan-authoring context (the S2 excerpt). A bindings-subsystem gap, outside the library. | Plan-scoped gist **#2613** "Deliver the stage:plan skill bindings to a stage-less warm /plan" (`perk gist create … --scope plan --run-id 01M3MJR8CGEPRNV7DK0E2BJGWZ` → `"id": "2613"`). |
| O1 | L5 | A stopped or failed docs run leaves its (empty) staging claim; the door never deletes a staging directory, and `list` / doctor surface it. | Record-only (by design). |
| O2 | W2 | A refresh republish resets the entry's `checked_at` / `evidence` (status back to `unknown`) — the new revision carries new markers. | Record-only (by design: markers are the mirror's revision). |
| O3 | L2 | Adoption accepted `dbt-duckdb`, a mirror with no `index.md` (one `README.md` file); publish would refuse it. | Record-only (by design; pinned by story 1). |
| O4 | L8 | `remove` left the empty `source-code/github.com/j178/` parent. | Record-only (leaf-only deletion is the design). |
| O5 | C2 | The consumer convergence re-adds the npm perk entry beside a local-path override (V4). | Record-only (a fixture-only shape — consumers run the published package). |
| O6 | P0.2 | Doctor run by a pre-library `perk` reports version-skew drift and cannot see the missing `librarian` skill (F3). | Record-only (operator environment; Part A's P0.2 now says so). |

### B.8 Teardown proof

- The fixture is gone (C4: both paths `No such file or directory`; its worktree was registered to
  the fixture repository only, so `<main>`'s `git worktree list` never carried it).
- `<main>` after L8: `git status --porcelain --untracked-files=all` empty, HEAD still
  `33bf73cde10c8a315d583b99226a47a86bb64f62` — identical to P0.1.
- What the run deliberately leaves in `<main>`'s gitignored library: the eight adopted mirrors now
  under `documentation/`, the `prek` docs entry (`/0.5.4/`, refreshed by W2) and the pinned
  `pi-subagents` checkout (`v0.71.0`); `prek-source` removed; `.staging/` empty. Outside the
  repository: `~/.local/bin/perk` is now the editable install of `<main>` (P0.3), and the fixture's
  sessions remain under `~/.pi/agent/sessions/--private-tmp-perk-library-fixture{,-wt}--/` as
  evidence.
