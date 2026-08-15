---
title: "Learn and gist commands"
description: "Exact reference for the perk learn group — capture, factories, docs navigation — and the perk gist group."
sidebar:
  order: 3015
---

# Learn and gist commands

This page holds the exact reference for the `perk learn` group (capture, the consolidation
factories, and the docs-navigation workers) and the `perk gist` group. For the full command map
and shared conventions, start at the [CLI commands hub](../cli.md).

## The learn group

### `perk learn`

Capture and consolidate learnings. Bare `perk learn` launches the `learn` stage (a primed `pi`
session); its `capture`, `skip`, `code`, `docs`, and `evidence` verbs are the cold workers the
warm doors delegate to; `harvest` is the cold-only objective factory that mines `docs/learned/`
(it has no warm door); `pending` lists closed plans still awaiting /learn.

**Local-checkout-only.** `learn` reuses the plan's local worktree but is the one reuse launcher
that never restores a missing checkout: it runs after the squash-merge, when GitHub commonly
auto-deletes `origin/plan-<id>`, and its real input — the session evidence under the worktree's
gitignored run artifacts — is machine-local and not on any remote. A missing checkout is a typed
refusal (`worktree_not_found`): run learn on the machine where the plan was implemented, or skip
it (`perk learn skip`).

### `perk learn pending`

List the closed plan issues still awaiting /learn — those whose canonical plan-header
`learn_state` reads `pending` (landed, /learn not yet run). `--limit` bounds the scan window to
the N most recently updated closed plans (default 50, max 100); the pending stamp lands at close
time, so pending plans cluster at the head of that window. Each row prints
`#id  closed-at  title  url`, followed by a `perk plan resume <id>` hint (the resume
classifier's MERGED+pending arm launches the learn stage). `--json` emits a
`{success, error_type, plans:[{id, title, url, closed_at}]}` envelope; an empty list exits 0.
Canonical-field only: legacy pre-field plans (whose pending state lives solely in the local
per-worktree marker) are not listed. Exit `0` ok/empty · `1` backend failure · `2` not-a-repo.

### `perk learn capture`

Create the perk:learn issue from captured learnings and clear pending-learn (land → learn). Reads
the markdown from the required `--body` file; `--dry-run` composes without creating an issue or
clearing. The optional `--decision` (one of `CAPTURE_LEARN`, `SHOULD_BE_CODE`, `UPDATE_EXISTING_DOC`,
`NEW_DOC`, `STALE_DOC`) and `--target` (a routable pointer, e.g. a doc path) persist the reconciled
captured classification onto the perk:learn issue header (both backends); the `--json` envelope is
unchanged (the classification lives on the issue, not the capture result). Capture also stamps the
canonical `learn_state: captured` onto the plan-header — strictly, and before the local marker
clear, so a failed stamp leaves the marker set (the retry signal).

### `perk learn skip`

Record a deliberate learn skip canonically and clear pending-learn (land → learn). Stamps
`learn_state: skipped` onto the plan-header (unless the plan is already `captured` — then a no-op
that reports the kept state), then clears the local marker. The warm no-summary `/learn` arm
(`/learn skip`, the `learn` tool without a summary) delegates here, so a merged-but-skipped plan
reads as done from any machine. `--dry-run` composes offline (no stamp, no marker change); `--json`
emits a machine-readable report.

### `perk learn docs`

Consolidate the **doc-destined** open perk:learn issues into a `docs/learned` plan (a read-only
factory). The cold door partitions the open issues by their captured `decision`: every
classification except a pre-stamped `SHOULD_BE_CODE` (those route to `perk learn code`; legacy /
unclassified default to docs) lands here. The inbox carries each learning's classification line
(`decision` + optional `target`) plus an existing-docs scan (inventory + stale pointers / broken
links / duplicate cues) for cleanup-first placement. The factory remains a **curator and verifier**:
it still emits a `SHOULD_BE_CODE` follow-up step when a doc-destined learning actually belongs in
code/comment/docstring/schema/user-docs, and regenerates the routing via `perk learn docs-sync`
(never by hand). `--gather` materializes the inbox and emits `{inbox_path, learn_numbers}` without
launching (the warm path); `--worktree`, `--dry-run`, `--remote` (local-only), and `--json` are also
accepted. The launcher runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch; `--no-sync` opts out.

### `perk learn code`

Route the pre-stamped `SHOULD_BE_CODE` open perk:learn issues into a code plan (a read-only factory,
the additive sibling of `perk learn docs`). Gathers only the issues `/learn` classified
`SHOULD_BE_CODE` and materializes a **lean** inbox (classification + `target`, no docs scan); the
factory authors a bounded plan that lands each insight in its real code home (a type/constant,
comment, docstring, schema, or user-doc) after verifying the `target` against the codebase. Options
are identical to `perk learn docs` (`--gather`, `--worktree`, `--dry-run`, `--remote` local-only,
`--json`). An empty inbox exits non-zero, cross-hinting `perk learn docs`.

### `perk learn harvest`

Mine `docs/learned/` as lenses into the code and curate ONE bounded improvement objective (a
read-only **objective factory** — it never edits the corpus and never writes code; cold-only, no
warm `/learn-harvest`).

```bash
perk learn harvest [--from <path>]... [--worktree <name>] [--dry-run] [--no-sync] [--json]
```

`--from` takes a file or directory inside `docs/learned/` (repo-root-relative or absolute),
repeatable; the selections are union-deduped in corpus order, and the default is the full corpus.
The shared trailing flags match the sibling factories (`--worktree`, `--dry-run`, `--remote`
local-only, `--json`, `--no-sync`); there is no `--gather` (harvest has no warm feeder).

The door gathers the selection into a run-scoped manifest
(`.perk/workflow/scratch/runs/<run_id>/harvest-manifest.json`) and launches a read-only
objective-authoring session over it. **Sync note:** harvest fast-forwards the checkout you run it
from **before** gathering — a guarded, best-effort sync (a dirty or diverged tree is warned and
skipped; a remote-less checkout is left alone), so the one ordering boundary holds: the manifest's
`commit_sha` is HEAD captured right after the sync (revision context, not a clean-tree
attestation). `--no-sync` skips it, the generic pre-launch sync is suppressed for this command,
and `--dry-run` never syncs but **does** write the manifest.

The gathered selection partitions into lanes (one `docs/learned/<category>/` group of at most
8 docs per lane), and the lane count routes the analysis: a single-lane selection is analyzed
directly by the launched session; a multi-lane selection fans one read-only harvest-analyst per
lane via the in-session `run_harvest_wave` wave — failed lanes are reported honestly with no
retry, and a failed or report-less wave is surfaced as an incomplete harvest recommending a
bounded `--from` re-run.

The `--dry-run --json` payload carries exactly
`{success, error_type, manifest_path, doc_count, lane_count, lane_ids, launched: false}`. The
selection-specific error vocabulary: `invalid_from` (a `--from` outside `docs/learned/` or
nonexistent) and `no_harvest_docs` (an empty selection). The generic door failures ride the same
envelope:
`remote_blocked` (`--remote` on this local-only door), `invalid_input` (no resolvable HEAD commit,
or a `docs/learned` root that resolves outside the repository), `manifest_write_failed` (the
run-scoped manifest could not be written), and `not_a_repo`. Exits: `0` ok · `1`
op-failure/refusal · `2` not-a-repo.

### `perk learn evidence`

Gather a landed plan's session-grounded evidence bundle and emit a stable manifest. Reads the local
plan-ref (no positional arg); resolves the saved plan, the merged PR's metadata/diff, the planning
and implementation session JSONLs (main + worker, labelled distinctly), and a basic existing-docs
inventory, materializing the artifacts under `.perk/workflow/scratch/learn-evidence/`. Each source
carries a `found` / `missing` / `ambiguous` status — a missing or ambiguous source is **surfaced,
never guessed**, and never fails the command. A learn-docs consolidation plan (non-empty
`consumed_learn`) returns a stable skip up front.

The `--json` bundle also carries `docs_findings` — an advisory, deterministic enrichment of the
existing-docs inventory: `stale_pointers` (source pointers like `` `perk/x.py::sym` `` that no
longer resolve), `broken_doc_paths` (doc→doc `.md` links that no longer exist), and
`duplicate_groups` (the rare exact title/`read_when` collision guard). It surfaces doc drift
advisorily (the `/learn` existing-docs analyst weighs it candidate-vs-corpus); it never fixes
anything. `--json` emits the machine-readable bundle (the
default is a compact human summary to stderr). On a gathered (non-skip) bundle the command also
writes the full manifest to `.perk/workflow/scratch/learn-evidence/manifest.json` — the same payload
as `--json` stdout (written unconditionally, so the bundle is self-contained for the `/learn` analyst
children that read it).

`--render` additionally normalizes the **found** session JSONLs into bounded, untrusted-DATA-fenced
Markdown chunks under `.perk/workflow/scratch/learn-evidence/chunks/` (one or more `<stem>[-N].md`
parts per session role) through a deterministic pipeline — branch selection, boilerplate-drop,
dedup, prune, per-payload truncation, then split-by-budget at entry boundaries (no entry is ever
elided). With `--json`, a stable normalization report (per-role counters + chunk paths) rides the
envelope's `render` field (`null` unless `--render`); with the human summary, one `render:` line per
role. `--render` and `--json` are independent.

### `perk learn docs-sync`

Regenerate the `docs/learned/` navigation from each doc's frontmatter (the single source of
truth). Writes two artifacts: the ambient routing block in `.pi/APPEND_SYSTEM.md` (loaded into
every session's system prompt) and the per-doc catalog table in `docs/learned/index.md` (one row
per doc, linking the doc with its single-line *when to read* cue).

The routing block's grain depends on the **cluster registry** `docs/learned/clusters.yaml`:

- **Registry present (the two-tier index).** The registry defines the clusters — a `clusters:`
  list of `{id, rollup}` entries (unique kebab-case ids; one-line rollup cues, ≤ 160 chars);
  each doc declares its membership via a `cluster: <id>` frontmatter field (members are never
  listed in the registry). The ambient block renders **one line per cluster** in registry file
  order — `- **<id>** — <rollup> (<category/slug>, …)`, members sorted by `(category, slug)`,
  no parens when a cluster has no members — followed by a legacy per-doc line for any doc whose
  `cluster` is missing or unknown (it never drops from the ambient tier; `docs-check` flags it).
  The catalog gains a Cluster column (`| Category | Doc | Cluster | When to read |`) and keeps
  the full per-doc `read_when` cues — the on-demand tier.
- **Registry absent (the legacy fallback).** Exactly the historical rendering: one line per doc
  in the ambient block, the 3-column catalog — byte-identical, no cluster gates.
- **Registry invalid** (unreadable, YAML error, wrong shape, empty `clusters`, a
  missing/empty/non-kebab or duplicate id, a missing/empty/multiline rollup) — the command fails
  loudly with the precise reason (`error_type: invalid_cluster_registry`, exit `1`) and **writes
  nothing**, so a broken registry can never silently regress the committed block to per-doc
  grain.

Both artifacts wrap their generated region in `<!-- BEGIN perk docs-sync … -->` /
`<!-- END perk docs-sync -->` markers, leaving a hand-editable preamble outside the markers untouched.
Generation is deterministic and idempotent — only artifacts whose content changed are written, and
re-running on a current tree is a no-op. `--dry-run` reports what would change without writing;
`--json` emits a `{written, unchanged, dry_run}` envelope. Purely local (no GitHub/config). Exit `0`
ok · `1` invalid registry · `2` not-a-repo.

### `perk learn docs-check`

Verify the generated `docs/learned/` navigation is current, and report advisory hygiene. Five
categories **gate the exit**:

- **Freshness** — each artifact's marked region must match a fresh render (absent markers or a
  mismatch ⇒ stale; run `perk learn docs-sync`). The render is registry-aware; when the registry
  itself is invalid, the routing/catalog freshness comparison is skipped in favor of the
  registry finding below — the headline then reads `UNCHECKED` (and the `--json` `fresh` field
  carries the non-compared default `true`; `registry_error` is the authoritative signal).
- **The per-cue budget** — each doc's `read_when` must be ≤ 200 chars and free of the YAML
  plain-scalar hazards that silently corrupt the rendered cue: a ` #` (space-then-hash) starts a
  YAML comment and silently truncates the cue, a `: ` (colon-space) breaks the whole frontmatter
  parse so the cue renders empty, and a multi-line value breaks the one-line routing grammar.
  Quoting the scalar is the sanctioned escape for a cue that needs `: ` or ` #`.
- **The cluster gates** (only when `docs/learned/clusters.yaml` is present) — the registry must
  load valid (`registry invalid: …` reports the same precise reason `docs-sync` refuses with),
  every doc's `cluster` must be declared and name a registry id (`cluster missing/unknown:
  <doc>`), no registry cluster may have zero member docs (`empty cluster: <id>`), and each
  rollup must be ≤ 160 chars (`rollup over budget: <id> — N chars (max 160)`; unlike an invalid
  registry, an overlong rollup still lets `docs-sync` write — parity with the overlong-cue
  posture).
- **The distillation header** — every learned doc strictly over 12,288 raw bytes must open with
  a conformant `## Distillation` section: the first `##` body section (frontmatter, the `# ` H1
  title, and intro prose may precede it), ≤ 30 lines, contained in the file's first 80 lines
  (so `read` with `limit: 80` always captures it). Each violation renders as
  `distillation <problem>: <doc>` with a problem from the closed set `undecodable` (not valid
  UTF-8 — the header cannot be verified) / `missing` / `not-first` / `too-long` /
  `not-contained`. Docs at or under the threshold are never checked.
- **The ambient-block budget** — the **committed** ambient routing region in
  `.pi/APPEND_SYSTEM.md` (the raw bytes between the `docs-sync` markers, excluding the marker
  lines' own line endings — what every session's system prompt actually loads) must be at most
  5,120 bytes. The gate measures **every measurable committed block**, regardless of registry
  presence/validity or freshness — both rendering modes (registry and legacy), under an invalid
  registry, even when the block is stale — and overflow renders one red
  `ambient block over budget: .pi/APPEND_SYSTEM.md — N bytes (max 5120)` line with the
  remediation: curate/compress the routing inputs (cluster rollups, cue assignments), or reset
  the budget constant in a human-reviewed change. The observed total rides `--json` as the
  final `ambient_routing_bytes` field (`null` when the block is unmeasurable — a missing file
  or malformed markers, which the freshness/registry gates already cover; `null` never gates
  here). `docs-sync` stays permissive — it still writes an oversized block; only `docs-check`
  and CI fail.

**Hygiene** is advisory — always printed, never changing the exit — and covers missing
`title`/`read_when` frontmatter, copied-source-looking code blocks (a source-language fence with `≥ 10`
non-blank lines; data-format/CLI fences are ignored), duplicated `read_when` cues, stale source
pointers, broken doc→doc links, and the over-12KB doc count (`over-12KB docs: N` — the raw size
is a note, never a gate; the per-doc byte list rides `--json` as `oversize_docs`). Read-only and
purely local. Exit `0` ok · `1` stale or
cue/cluster/distillation/ambient-budget violation · `2` not-a-repo. Freshness is intentionally **not** wired into `just ci` /
`just test` — run `docs-check` on demand — but the cue budget **is**: a pytest fails CI on the same
overlong-cue / hazard violations (and, in perk's own repo, pins registry mode + the cluster gates,
the over-threshold docs' distillation headers, and the committed ambient block's 5,120-byte
budget — the live-corpus pytest measures the committed block and fails when it is unmeasurable
or over budget, while freshness stays on-demand).

## The gist group

### `perk gist`

The gist group. A **gist** is a rough, problem-space-focused statement of intent ("something we
would likely want to do") tracked in the issue backend — upstream of both plans and objectives,
code-informed but carrying **no implementation detail** (no steps, no roadmap, no estimates).
Help renders **Launchers** (`author`, `save` — each opens a primed `pi` session) and **Workers**
(`create` (`new`), `list`). Bare `perk gist` shows this group help.

A saved gist sits in the backlog until someone consumes it through the **unchanged adoption
doors**: `perk plan from <gist>` (plan scope) or `perk objective author --from <gist>` (objective
scope) — adoption stamps the plan/objective metadata beside the gist's own header in place, which
is what marks it adopted.

### `perk gist author`

Draft a new gist in a read-only authoring session: clarify the intent, explore lightly, keep the
draft current with the `gist_draft` tool, review via `plan_review` (approval auto-saves).
`--scope [plan|objective]` pre-seeds the consumption tier (it rides the run handoff; an explicit
save-time scope wins). Local-only (`cold_remote:false`); adds `--json`. Runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch; `--no-sync` opts out.

### `perk gist save`

Flip a gist-authoring session to read-write to save — the manual hand-off door (the `gist-save`
stage; normally the `plan_review` approval auto-saves instead). Local-only; adds `--json`.

### `perk gist create` (alias `new`)

Mint a `run_id` and persist the gist from authored markdown. Reads the required `--body` file;
`--title`, `--scope [plan|objective]`, `--run-id`, `--dry-run`, and `--json` tune the create.
Scope resolution: explicit `--scope` > the launch handoff's pre-seeded scope > `plan`. Scope
`objective` stores the gist on the project tier when the backend has one (on Linear: a
deliberately light **project**, so `objective author --from` adopts it in place), else falls back
to the issue tier with the scope stamped in the gist's header. Human output prints the
consumption command for the saved scope.

### `perk gist list`

List open gists. The default view **hides adopted gists** (the "what's still unconsumed" backlog
view); `--all` shows everything with an adopted marker. `--json` emits
`{gists: [{id, url, title, scope, adopted, kind}]}` (`kind` is `issue` or `project`). Exits 0 on
an empty list.

## Related

- **Do:** [How to run the learn-docs factory](../../how-to/run-the-learn-docs-factory.md) — consolidate perk:learn issues into committed docs.
- **Do:** [How to capture a gist (a statement of intent)](../../how-to/capture-a-gist.md) — the gist workflow end to end.
- **Understand:** [Gists, plans, and objectives](../../explanation/gists-plans-and-objectives.md) — where gists sit in the intent ladder.
