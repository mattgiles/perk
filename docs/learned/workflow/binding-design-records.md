---
title: Binding design records & disposable-scaffold spikes
read_when: You are authoring or reconciling a binding design record, spike, characterization or certification record — instrument proofs, staging, owner legs, NO-GO verdicts, waivers, stale claims
cluster: knowledge-stewardship
---

# Binding design records & disposable-scaffold spikes

A *binding* design record (a blueprint or spike whose decisions later work must honor) has its own
authoring craft, distilled from the docs-site records
(`docs/design/docs-site-blueprint.md`, `docs/design/docs-site-visual-blueprint.md`,
`docs/design/archive/docs-site-bridge-spike.md`) and the curation map
(`docs/design/archive/learned-curation-map.md`). Only the cross-cutting record-authoring patterns live
here — the docs-site–specific discoveries stay bound in those committed records; reuse rather
than re-derive.

## Distillation

- Criteria in the plan → disposable scaffold → text-only evidence → teardown proof → named
  consumers — "The proven record shape"; teardown is two-part — "Disposable spike teardown".
- Pin outcome criteria and resolution rules, not config fragments; carry cross-section arithmetic
  in-doc; readiness tables record effective state — the three middle sections.
- Re-measure at commit; pilots pin criteria first and keep a byte-identical nonparticipant arm —
  "Point-in-time records re-measure at commit", "Pilot shape and contamination".
- Reconcile the whole current-state narrative, not only the named sentences — "Reconcile the
  whole current-state narrative".
- Separate MEASURED from SOURCE-DERIVED; a FAIL or NO-GO can land honestly; instrument claims come
  from session events; prove every instrument before its row; stage from engine events; script
  non-browser owner legs; close audits before teardown — "Characterization and dogfood nodes".
- The evidence records the craft was distilled from are listed in "Cross-references".

## The proven record shape (three confirmations)

Settle the criteria in the plan → verify them in a **disposable untracked scaffold** → commit
**text-only** evidence (verbatim command output, contrast tables, annotated ASCII wireframes) →
close with a teardown `git status --porcelain` proof → bind the decisions with a **named-consumer
list and an explicit reconciliation rule** (who must obey the record, and what event forces a
re-verify). A record built this way is reusable evidence, not an opinion — later work reuses it
instead of re-running the spike.

## Disposable spike teardown is two-part

gitignore covers *generated state* but not scaffold source, untracked fixtures, or temp edits to
tracked files — so teardown = remove the scaffold + restore the tracked edits + remove the
fixtures, and only then commit the porcelain proof. Pre-script the teardown in the plan; an
improvised teardown is what leaves the dangling checkout.

## Pin outcome criteria, not third-party config fragments

An exact prescribed config drifts with upstream deprecations (the remark-plugins key
auto-coercion case was the shipped instance). Encode version selection as a **resolution rule**
("latest patch at spike time"), not a hard pin, and record the *resolved* pair as the binding
selection — the rule survives upstream churn; the frozen fragment doesn't.

## Cross-section reconciliation arithmetic is where verification effort belongs

In a decisions-pinned spec, the actionable review findings were **consistency failures between
the doc's own sections** — not wrong individual decisions. When a doc claims total-coverage rules,
carry the arithmetic **in-doc** so drift self-detects; and a catch-all rule must own its pinned
exceptions as a first-class case, not rely on cross-section memory.

## Readiness tables for opt-out gates record effective state, not provisioning status

A default-on knob phrased as a prerequisite becomes a false requirement — the table must say what
is *effectively* on/off for this record's scope, not whether someone provisioned it.

## Point-in-time records re-measure at commit

Never transcribe planning-time numbers into the committed record — re-measure at commit time, and
verify the counting selectors themselves (the `git ls-files '<glob>'` root-file drop trap: a glob
that misses root-level files undercounts silently). Embedding verbatim tool output couples the
record to the renderer's WORDING — a text-only renderer change forces a re-measure-and-re-author —
so commit the docs-only record last, after review settles (#2519).

## Pilot shape and contamination

- **Live discoverability legs run in the authoring session are contaminated.** The model already
  knows the tool name and the pinned queries, so such a leg proves search → activate → call, not
  naive discoverability. Scored discoverability belongs to pinned offline queries or a fresh
  session.
- **The pilot shape that worked** (`docs/design/archive/native-discovery-pilot-dogfood.md`):
  criteria and a decision rule pinned before measuring, with a written amendment protocol; a
  dedicated baseline commit measured by the same repo-owned test; a preservation cross-check — the
  nonparticipant arm reproduces the baseline byte-for-byte at every later commit, every delta
  explained; and both ADOPT and RETIRE end states fully specified with commit boundaries, so RETIRE
  is a revert.
- **Characterize with matched controls before alleging a regression**: a CONTROL session without
  perk, Pi-deactivating and Pi-additive controls for gesture rows, a classification table fixed
  before measuring, and a throwaway worktree pinned to the subject version — the delayed-MCP matrix
  (`docs/design/archive/pi-1.0.0-mcp-restoration.md`).

## Verification tooling disposed with a scaffold must be rebuilt from prose later

Preserve verbatim outputs + the methodology in the record, because the checks themselves are torn
down with the scaffold. Once the target becomes committed code, prefer making the checks
repo-owned and re-runnable — the docs-site instance resolved exactly that way: the committed
`docs/site/` now carries repo-owned, re-runnable checks (the `docs/site/src/*.test.mjs` unit
suites run in `just test`; the post-build checks — `docs/site/checks/*.test.mjs` +
`src/in-session-reference.test.mjs` — run via the site `check` script, CI-wired as
`npm run docs:check`).

## Reconcile the whole current-state narrative

A plan that names stale statements sets the minimum sweep, not its boundary. Re-read the record's
entire current-state narrative against the merged implementation: neighboring decisions, residuals,
and summaries can restate the same assumption without sharing the named wording.

When an implementation narrows a literal invariant, grep the full record for every phrasing of that
invariant before declaring reconciliation complete. Adjacent bullets often encode it once as a
value, once as a rule, and once as an exception. Fixing only the exact sentence identified by the
plan leaves an internally contradictory binding record.

## Characterization and dogfood nodes: what the record must separate

The pi-subagents native-execution arc (a capability characterization, two dogfood gates, and a
bounded re-verification) added the record disciplines below. The binding record is
`docs/design/pi-subagents-child-execution-policy.md`; the evidence lives in
`docs/design/archive/pi-subagents-child-capability-characterization.md`,
`docs/design/archive/pi-subagents-native-streaming-dogfood.md`, and
`docs/design/archive/pi-subagents-native-baseline-dogfood.md`.

- **Hard-separate the MEASURED pass from SOURCE-DERIVED design.** Source tracing — not the
  measurement matrix — surfaced the warm-parent gap that became the restriction channel. A
  source-established gap gets a documented repair *design* handed to the implementation node,
  never a fictional measured result; negative or absent measurements are evidence, not permission
  to repair in the characterization node.
- **A dogfood gate can legitimately land with a FAIL verdict** when the root cause is precise and
  repair ownership is assigned. The host-peer baseline did exactly that: implementation committed
  first, the smoke run at that clean SHA, the evidence record as a trailing docs-only commit — the
  FAIL recorded, not patched around.
- **An owner redirect of the plan's approval protocol is honored and recorded faithfully.** Leave
  the policy pointer at "Pending human PR review", fabricate no approval attestation, and keep
  experiment/amendment approvals distinct from the final measured-decision approval.
- **When live dogfooding hits an upstream defect**, preserve every failed or unobserved leg in the
  archive as NOT PASSED; prefer a self-disabling, proof-gated in-repo guard over host patches or
  upstream churn; land on a bounded, owner-approved waiver that names the residual gaps. Budget
  for host-level surprises dominating a "swap the guidance" node — the streaming restore tripled
  its scope through three owner-approved amendments.
- **High-stakes deletion sits behind an offline proof gate**: "retain the guard and stop without a
  PR on failed verification", each blocker recorded with exact anchors and hashes, each retry
  separately owner-authorized (one bounded attempt at a time) — no harness growth, no
  proof-weakening to get through.
- **A bounded source/offline re-verification is not a new full certification.** Record a Context
  table, a SHA-256 source census before/after over a fixed closed file list (raw bytes, lowercase
  hex, package-relative paths), semantic-check rows citing durable anchors, and a fixed
  command/disposition table; do not advance the doctor full-baseline stamp on its strength.
- **Gate-record evidence pins a committed revision + per-path blob hashes** (`git rev-parse
  <sha>:<path>` for each cited file), never "base + uncommitted diff" — an uncommitted diff is not
  reproducible evidence, and a bare SHA does not survive a later force-push of the branch.
- **The "offline-proven only" closure genre.** When a node's live check cannot be run in-session,
  close with a criteria table that marks each offline criterion *offline-pinned (test id)* and each
  live check *unobserved — NOT PASSED*, uses the same wording across the design record, contracts,
  and CHANGELOG, and leaves the live run as an explicit named residual. Never let "the tests pass"
  read as "the live behaviour was observed".
- **Instrument claims from session events, never from model self-report.** Asked which bindings
  applied, a stage-less warm `/plan` session said `perk-plan` "fires" — inferred from reading
  `shared/bindings.yaml`; its JSONL held no `perk:binding-context` entry and its workflow state no
  stage. The persisted entry count is the instrument (exactly one in the cold session, zero warm).
- **Know which `perk` the doctor is.** A `perk doctor` run before `just install-cli` was the PyPI
  build: version-skew drifts plus a green `skills-delivery` while a skill was missing looked like a
  doctor blind spot, but the checkout's own doctor (`uv run perk doctor`) fails `skills-delivery`
  naming it. When dogfooding unreleased features: check `perk --version` and its interpreter,
  install the checkout CLI, re-sync skills with `perk init` — and a linked worktree created before
  the re-sync keeps stale skill links.
- **Measurement honesty** (the Python test-suite speed-up records under
  `docs/design/archive/python-test-suite-speedup-*`): classify the change (safety / ownership /
  selection vs speed) **before** measuring, so a non-speed change is never judged by a speed
  metric; pre-commit a validity gate and a closed verdict vocabulary ("faster", "within observed
  noise", "slower") so the verdict cannot be re-worded after the data arrives; re-take a stale seed
  baseline at the current revision rather than comparing against a number measured on another
  tree; run long series detached from the session and budget for laptop-contention outliers; and
  let a "speed" objective close honestly with a **no-speedup verdict** when that is what the series
  shows — the record's value is the measured truth, not the hoped-for headline.

The Pi 1.1.0/1.4.0 certification arc and the 0.81.0 launcher characterization added five groups
(records: `docs/design/archive/pi-subagents-0.81.0-launcher.md`,
`pi-1.4.0-certification.md`, `pi-1.1.0-certification.md`, `pi-1.1.0-characterization.md`,
`pi-1.1.0-headless-print-mode.md`):

- **Instruments.** Prove every instrument and capture path with a pre-row probe — `NOT MEASURED
  (instrument)` is an outcome (a dead `log show` was caught by a B0 probe, which made the
  amendment legitimate). Rebind reused probe instruments that hard-code the previous worktree, and
  prove the rebinding. Plan a second attribution source up front. An honest NO-GO caused by an
  instrument limit is a valid result. macOS seatbelt (`sandbox-exec`) gotchas when it is the
  instrument: `log stream` (not `log show`) returns Sandbox deny lines; the kernel suppresses
  duplicate deny reports and logs nothing for keychain reads; match resolved paths
  (`/private/var`); use `-D` parameters, not text substitution; `(allow process-exec* (with
  report))` attributes pids; `file-read*` includes metadata reads.
- **Staging.** Stage from engine events (`subagent.run.started`), never from a lane obeying a
  directed tool call; a `sleep N` first step stages a deadline partial where output length does
  not; timing-dependent staging proves the overlap, not the order; every live cell has a "not
  staged → re-run, never scored" branch; pre-split decision rules ("stop before the child started"
  vs "during a running child") so nothing is decided after a FAIL.
- **Planning.** Run every literal in a task brief once unfenced at planning (issue/PR numbers
  decay); size iteration caps from how the narrowing actually proceeds; set endpoints per question
  (one question's validity must not gate another's disposition); exact-count oracles fail on
  model-driven turns — write predicates over all entries; schedule issue comments/closes before
  `/submit` or in a later session.
- **Owner-heavy matrices.** Script every non-browser leg through tmux and reserve owner time for
  browser decisions and marker observation; order owner legs by gate weight (stamp-gating supplier
  rows first, INFO rows last); reconfirm every runner secret with a live dispatch before remote
  legs; ask about the `perk:wave` marker while the wave runs; keep verdict and stamp as two
  independent slots; a docs-only source-equivalence allowlist keeps a parallel owner session cheap;
  a parallel session in `$MAIN` contends on the singleton `plan-ref.json`.
- **Audits.** A release-note coverage map assigns every changelog bullet (sibling packages
  included) to a disposing row; close the audit before teardown, or recover witnesses via
  `npm pack` + `dist.shasum`; a failing assertion's successors never ran — credit only the
  assertions before the failure line; version-history claims need a registry/archive check (a
  pointer sweep proves resolution, not truth); reap detached supplier runners by command line
  (`pgrep -f <scratch path>`, TERM→KILL rounds) excluding the reaper's own ancestor chain,
  validated on a planted fake first; request-prefix hashes need a deterministic measurement root
  (`pi/tool-loadout.md` § Test craft).

## Cross-references

- `docs/learned/workflow/doc-reconciliation.md` — the curation-batch measurement rules
  (SHA-stamped, mechanically-derived tables) and the record-completeness bar
- `docs/design/docs-site-blueprint.md`, `docs/design/docs-site-visual-blueprint.md`,
  `docs/design/archive/docs-site-bridge-spike.md` — the binding records this craft was distilled from
- `docs/design/pi-subagents-child-execution-policy.md` (+ the three archive records named above) —
  the characterization/dogfood arc the separation disciplines were distilled from
- `docs/learned/pi/subagents.md` — the `## Sources` provenance convention (re-verify at each pin bump) the re-verification rule serves
