# Docs-site content & IA blueprint

This is the **binding reader/content blueprint** for the local, content-first Starlight
documentation site (Objective #1622, node 1.1). It commits the reader hierarchy, the
route/sidebar map, the page-by-page migration inventory with editorial intent, the hub/anchor
migration rules, the Divio/voice/metadata authoring contract, the objective's acceptance
matrices, and the credential/Actions readiness record. Later nodes consume it as input:
node 1.2 (bridge spike), node 1.3 (visual blueprint), nodes 2.1–2.4 (site foundation),
nodes 3.1–4.6 (content migration), and node 5.2 (final gate). It makes no change under
`docs/user-docs/` and finalizes no Starlight-coupled visuals or bridge mechanics.

The corpus this blueprint binds is the 47 Markdown files under `docs/user-docs/`
(~54,600 words) as of the blueprint's commit date, **2026-08-12**. The corpus selector for
every table and check in this document is:

```sh
git ls-files docs/user-docs | grep '\.md$'
```

Do **not** use `git ls-files 'docs/user-docs/**/*.md'` — the `**/` glob misses the root
`index.md` and returns only 46 files.

*Amendment (2026-08-12, node 2.4):* the corpus has since grown by one file —
`how-to/send-feedback-from-hunk-watch.md` (the hunk-watch feedback bridge, shipped after this
blueprint's commit) — now recorded in the §2 route table, the §3 Core workflow list, and the
§4 inventory. Corpus-wide totals shift by one accordingly (48 current files; 71 routed pages;
66 enumerated sidebar entries).

*Amendment (2026-08-13, node 2.1, objective #1698):* the corpus has grown by three files — the
stacked-delivery teaching quadrant: `tutorials/drive-a-stacked-objective.md` (the third,
advanced tutorial), `how-to/review-a-stacked-train.md` (Core workflow), and
`how-to/recover-a-stacked-train.md` (Objectives & learnings) — now recorded in the §2 route
tables, the §3 sidebar map, and the §4 inventory. Corpus-wide totals shift by three
accordingly (51 current files, re-derived with the corpus selector above; 74 routed pages;
69 enumerated sidebar entries).

## §1 Purpose & binding scope

### What this blueprint binds

Later plans treat the following as decided input, not as open design questions:

- the five-section **reader hierarchy** and the **route convention + complete route table** (§2);
- the explicitly curated **sidebar map** — grouping, ordering, and insertion positions (§3);
- the **per-page dispositions with editorial intent** for all 47 current files, including the
  four split shapes and their family lists (§4);
- the **hub stability rule and anchor migration map** (§5);
- the **Divio/voice/metadata authoring contract** (§6) that seeds `_authoring.md`;
- the **acceptance matrices** with executing-node assignments (§7);
- the **credential/Actions readiness record and preflight definition** (§8).

Changing a binding decision recorded here requires an explicit **objective reconciliation**
(the same rule Objective #1622 applies to the node 1.2 bridge selection). The one sanctioned
route-detail escape hatch: node 1.3 may *"reconcile any implementation-constrained route detail
without changing the reader IA or acceptance matrices."* This blueprint's one designed
post-commit mutation surface is the §8 readiness-evidence table, which receives dated appended
rows from the node 3.2 and 3.6 preflights.

### Out of scope (owned by later nodes)

- **Astro/Starlight version and the content bridge** — node 1.2 selects them through the
  compatibility spike; nothing here presumes a bridge mechanism.
- **Visual compositions, design tokens, fonts, the diagram legend, and the component-override
  budget** — node 1.3, after the spike proves the toolchain.
- **Frontmatter *enforcement* mechanics** — schema validation, `src/perk/learn/docs_scan.py`
  frontmatter support, legacy fallback — node 2.3. §6 binds the *what*, not the *how*.
- **All file moves and splits** — nodes 2.3–4.5 execute the dispositions; this node moves
  nothing.

Seed material for the objective (an untracked PRD under `docs/planning/`) is not a runtime or
planning dependency; this blueprint is self-contained and does not reference it.

## §2 Reader hierarchy & route map

### The reader hierarchy

Five top-level sections, in this order:

1. **Home** — the splash/router page.
2. **Tutorials** — learn a workflow by doing it.
3. **How-to guides** — complete one bounded task.
4. **Reference** — look up an exact fact.
5. **Explanation** — understand a relationship or trade-off.

The canonical Divio names are retained as the section names; short reader-language subtitles
(e.g. "learn by doing", "look up exact behavior") are allowed in landing copy and sidebar
group descriptions.

### Route convention

- Site route = source path relative to `docs/user-docs/`, minus `.md`, directory-style:
  `how-to/resume-a-plan.md` → `/how-to/resume-a-plan/`.
- Quadrant `index.md` → the section root: `tutorials/index.md` → `/tutorials/`, and likewise
  for `how-to/`, `reference/`, `explanation/`.
- Root `index.md` → `/` (home).
- **Split hubs keep their existing file paths** (`reference/cli.md` → `/reference/cli/`), with
  children as siblings under a same-named directory (`reference/cli/plan.md` →
  `/reference/cli/plan/`). No `index.md` is created inside a split directory, so the hub file
  and the child directory coexist without a route collision.

### Route table

One row per routed page: the current 47 files (post-disposition all remain routed), all 17
split children, and all 6 new pages — 70 routed pages. Columns: source path → route →
sidebar owner. Split children and new pages do not exist yet; their rows name the executing
node that creates them.

#### Home

| Source path | Route | Sidebar owner |
|---|---|---|
| `docs/user-docs/index.md` | `/` | Home |

#### Tutorials

| Source path | Route | Sidebar owner |
|---|---|---|
| `docs/user-docs/tutorials/index.md` | `/tutorials/` | Tutorials (landing) |
| `docs/user-docs/tutorials/get-started.md` | `/tutorials/get-started/` | Tutorials |
| `docs/user-docs/tutorials/drive-an-objective.md` | `/tutorials/drive-an-objective/` | Tutorials |
| `docs/user-docs/tutorials/drive-a-stacked-objective.md` *(added 2026-08-13)* | `/tutorials/drive-a-stacked-objective/` | Tutorials |

#### How-to guides

| Source path | Route | Sidebar owner |
|---|---|---|
| `docs/user-docs/how-to/index.md` | `/how-to/` | How-to guides (landing) |
| `docs/user-docs/how-to/drive-the-full-spine.md` | `/how-to/drive-the-full-spine/` | How-to › Core workflow |
| `docs/user-docs/how-to/resume-a-plan.md` | `/how-to/resume-a-plan/` | How-to › Core workflow |
| `docs/user-docs/how-to/address-review-feedback.md` | `/how-to/address-review-feedback/` | How-to › Core workflow |
| `docs/user-docs/how-to/review-a-foreign-pr.md` | `/how-to/review-a-foreign-pr/` | How-to › Core workflow |
| `docs/user-docs/how-to/review-a-stacked-train.md` *(added 2026-08-13)* | `/how-to/review-a-stacked-train/` | How-to › Core workflow |
| `docs/user-docs/how-to/replan-an-open-plan.md` | `/how-to/replan-an-open-plan/` | How-to › Core workflow |
| `docs/user-docs/how-to/adopt-an-existing-issue.md` | `/how-to/adopt-an-existing-issue/` | How-to › Core workflow |
| `docs/user-docs/how-to/capture-a-gist.md` | `/how-to/capture-a-gist/` | How-to › Core workflow |
| `docs/user-docs/how-to/adopt-an-existing-project.md` | `/how-to/adopt-an-existing-project/` | How-to › Core workflow |
| `docs/user-docs/how-to/target-a-non-default-base-branch.md` | `/how-to/target-a-non-default-base-branch/` | How-to › Core workflow |
| `docs/user-docs/how-to/run-ci-in-session.md` | `/how-to/run-ci-in-session/` | How-to › Core workflow |
| `docs/user-docs/how-to/configure-and-verify-ci-checks.md` *(new — node 3.4)* | `/how-to/configure-and-verify-ci-checks/` | How-to › Core workflow |
| `docs/user-docs/how-to/recover-a-dirty-worktree.md` | `/how-to/recover-a-dirty-worktree/` | How-to › Core workflow |
| `docs/user-docs/how-to/diagnose-a-perk-repo.md` *(new — node 3.4)* | `/how-to/diagnose-a-perk-repo/` | How-to › Core workflow |
| `docs/user-docs/how-to/run-a-worktree-setup-hook.md` | `/how-to/run-a-worktree-setup-hook/` | How-to › Core workflow |
| `docs/user-docs/how-to/track-implement-progress.md` | `/how-to/track-implement-progress/` | How-to › Core workflow |
| `docs/user-docs/how-to/send-feedback-from-hunk-watch.md` *(added 2026-08-12)* | `/how-to/send-feedback-from-hunk-watch/` | How-to › Core workflow |
| `docs/user-docs/how-to/author-a-roadmap.md` | `/how-to/author-a-roadmap/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/replan-an-objective.md` | `/how-to/replan-an-objective/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/advance-or-skip-nodes.md` | `/how-to/advance-or-skip-nodes/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/reconcile-an-objective.md` | `/how-to/reconcile-an-objective/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/check-an-objective-for-drift.md` | `/how-to/check-an-objective-for-drift/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/recover-a-stacked-train.md` *(added 2026-08-13)* | `/how-to/recover-a-stacked-train/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/run-the-learn-docs-factory.md` | `/how-to/run-the-learn-docs-factory/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/run-the-learn-code-factory.md` | `/how-to/run-the-learn-code-factory/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/run-the-learn-harvest-factory.md` | `/how-to/run-the-learn-harvest-factory/` | How-to › Objectives & learnings |
| `docs/user-docs/how-to/set-up-the-remote-runner.md` | `/how-to/set-up-the-remote-runner/` | How-to › Headless & remote |
| `docs/user-docs/how-to/dispatch-a-stage-to-ci.md` | `/how-to/dispatch-a-stage-to-ci/` | How-to › Headless & remote |
| `docs/user-docs/how-to/supervise-dispatched-runs.md` | `/how-to/supervise-dispatched-runs/` | How-to › Headless & remote |
| `docs/user-docs/how-to/advance-an-objective-headlessly.md` | `/how-to/advance-an-objective-headlessly/` | How-to › Headless & remote |
| `docs/user-docs/how-to/attach-a-skill-to-a-stage.md` | `/how-to/attach-a-skill-to-a-stage/` | How-to › Customization |
| `docs/user-docs/how-to/author-a-repo-skill.md` | `/how-to/author-a-repo-skill/` | How-to › Customization |
| `docs/user-docs/how-to/write-a-custom-subagent.md` | `/how-to/write-a-custom-subagent/` | How-to › Customization |
| `docs/user-docs/how-to/scope-pi-resources-per-project.md` | `/how-to/scope-pi-resources-per-project/` | How-to › Customization |
| `docs/user-docs/how-to/select-a-provider.md` | `/how-to/select-a-provider/` | How-to › Providers & backends |
| `docs/user-docs/how-to/switch-to-linear.md` | `/how-to/switch-to-linear/` | How-to › Providers & backends |

#### Reference

| Source path | Route | Sidebar owner |
|---|---|---|
| `docs/user-docs/reference/index.md` | `/reference/` | Reference (landing) |
| `docs/user-docs/reference/requirements-and-compatibility.md` *(new — node 3.2)* | `/reference/requirements-and-compatibility/` | Reference |
| `docs/user-docs/reference/cli.md` | `/reference/cli/` | Reference › CLI (hub) |
| `docs/user-docs/reference/cli/setup-and-health.md` *(split child — node 4.1)* | `/reference/cli/setup-and-health/` | Reference › CLI |
| `docs/user-docs/reference/cli/plan.md` *(split child — node 4.1)* | `/reference/cli/plan/` | Reference › CLI |
| `docs/user-docs/reference/cli/objective.md` *(split child — node 4.1)* | `/reference/cli/objective/` | Reference › CLI |
| `docs/user-docs/reference/cli/pr.md` *(split child — node 4.1)* | `/reference/cli/pr/` | Reference › CLI |
| `docs/user-docs/reference/cli/learn-and-gist.md` *(split child — node 4.1)* | `/reference/cli/learn-and-gist/` | Reference › CLI |
| `docs/user-docs/reference/cli/remote-and-utility.md` *(split child — node 4.1)* | `/reference/cli/remote-and-utility/` | Reference › CLI |
| `docs/user-docs/reference/in-session.md` | `/reference/in-session/` | Reference › In-session (hub) |
| `docs/user-docs/reference/in-session/stages-and-doors.md` *(split child — node 4.2)* | `/reference/in-session/stages-and-doors/` | Reference › In-session |
| `docs/user-docs/reference/in-session/workflow-commands.md` *(split child — node 4.2)* | `/reference/in-session/workflow-commands/` | Reference › In-session |
| `docs/user-docs/reference/in-session/review-and-authoring.md` *(split child — node 4.2)* | `/reference/in-session/review-and-authoring/` | Reference › In-session |
| `docs/user-docs/reference/in-session/model-tools.md` *(split child — node 4.2)* | `/reference/in-session/model-tools/` | Reference › In-session |
| `docs/user-docs/reference/configuration.md` | `/reference/configuration/` | Reference › Configuration (hub) |
| `docs/user-docs/reference/configuration/repository-layout.md` *(split child — node 4.3)* | `/reference/configuration/repository-layout/` | Reference › Configuration |
| `docs/user-docs/reference/configuration/workflow-and-ci.md` *(split child — node 4.3)* | `/reference/configuration/workflow-and-ci/` | Reference › Configuration |
| `docs/user-docs/reference/configuration/backends.md` *(split child — node 4.3)* | `/reference/configuration/backends/` | Reference › Configuration |
| `docs/user-docs/reference/configuration/models-and-compaction.md` *(split child — node 4.3)* | `/reference/configuration/models-and-compaction/` | Reference › Configuration |
| `docs/user-docs/reference/configuration/skills-and-bindings.md` *(split child — node 4.3)* | `/reference/configuration/skills-and-bindings/` | Reference › Configuration |
| `docs/user-docs/reference/objectives.md` | `/reference/objectives/` | Reference |
| `docs/user-docs/reference/providers-and-backends.md` | `/reference/providers-and-backends/` | Reference › Providers & issue backends (hub) |
| `docs/user-docs/reference/providers-and-backends/providers.md` *(split child — node 4.4)* | `/reference/providers-and-backends/providers/` | Reference › Providers & issue backends |
| `docs/user-docs/reference/providers-and-backends/issue-backends.md` *(split child — node 4.4)* | `/reference/providers-and-backends/issue-backends/` | Reference › Providers & issue backends |
| `docs/user-docs/reference/json-schemas.md` | `/reference/json-schemas/` | Reference |
| `docs/user-docs/reference/glossary.md` *(new — node 4.4)* | `/reference/glossary/` | Reference |

#### Explanation

| Source path | Route | Sidebar owner |
|---|---|---|
| `docs/user-docs/explanation/index.md` | `/explanation/` | Explanation (landing) |
| `docs/user-docs/explanation/how-perk-thinks.md` | `/explanation/how-perk-thinks/` | Explanation |
| `docs/user-docs/explanation/gists-plans-and-objectives.md` *(new — node 4.5)* | `/explanation/gists-plans-and-objectives/` | Explanation |
| `docs/user-docs/explanation/human-gates-and-trust.md` *(new — node 4.5)* | `/explanation/human-gates-and-trust/` | Explanation |
| `docs/user-docs/explanation/headless-and-remote.md` | `/explanation/headless-and-remote/` | Explanation |
| `docs/user-docs/explanation/perk-in-zed.md` | `/explanation/perk-in-zed/` | Explanation |

### New pages

The six new pages required by the objective, with quadrant, source path, and route:

| New page | Quadrant | Source path | Route | Executing node |
|---|---|---|---|---|
| Requirements and compatibility | Reference | `docs/user-docs/reference/requirements-and-compatibility.md` | `/reference/requirements-and-compatibility/` | 3.2 |
| Operator glossary | Reference | `docs/user-docs/reference/glossary.md` | `/reference/glossary/` | 4.4 |
| Gists, plans, and objectives | Explanation | `docs/user-docs/explanation/gists-plans-and-objectives.md` | `/explanation/gists-plans-and-objectives/` | 4.5 |
| Human gates and trust | Explanation | `docs/user-docs/explanation/human-gates-and-trust.md` | `/explanation/human-gates-and-trust/` | 4.5 |
| Diagnose a perk repo (doctor diagnosis) | How-to | `docs/user-docs/how-to/diagnose-a-perk-repo.md` | `/how-to/diagnose-a-perk-repo/` | 3.4 |
| Configure and verify CI checks | How-to | `docs/user-docs/how-to/configure-and-verify-ci-checks.md` | `/how-to/configure-and-verify-ci-checks/` | 3.4 |

### Excluded sources

| Source path | Why excluded | Executing node |
|---|---|---|
| `docs/user-docs/_authoring.md` | Maintainer-facing authoring governance (seeded from §6). **Never routed, never indexed by search.** | Created by node 2.3 |

## §3 Sidebar map

The sidebar is **explicitly curated — never autogenerated**. Rules that bind every entry:

- **Home** is first — the sidebar's first entry links `/` (the root `index.md`).
- **Section labels are non-linking group headings; each landing page is its group's
  position-0 entry** (labeled by its title), not repeated elsewhere — Tutorials opens with
  `/tutorials/`, How-to guides with `/how-to/`, Reference with `/reference/`, Explanation
  with `/explanation/`.

  *Reconciliation note (node 2.4, 2026-08-12):* this bullet originally bound section labels
  as themselves the links to their landing pages. That shape is not realizable in stock
  Starlight 0.41 — sidebar group entries carry `label`/`collapsed`/`items` only (see
  `@astrojs/starlight/schemas/sidebar.ts`; group labels cannot link) — and the visual
  blueprint binds an **empty** component-override set, so no override may synthesize it.
  The bullet above records the realized stock-Starlight shape instead. A later node may
  restore label-links only via an authorized component-override decision or upstream
  Starlight support.
- The reader's current section renders expanded; unrelated large groups are collapsible.
- Labels favor reader vocabulary but keep exact command names visible. The default label is
  the page title; a shorter display-label override is allowed only under §6's label-override
  rule (recorded at migration time).
- Every routed page appears in the sidebar or is explicitly recorded here as a
  non-navigation page. **There are no non-navigation pages: all 74 routed pages appear in
  the sidebar** — Home, the four section landings, and the 69 entries enumerated below
  (70/65 as originally committed; +1 per the §1 corpus amendment of 2026-08-12; +3 per the
  §1 amendment of 2026-08-13).

### Tutorials (pedagogical order)

1. Get started with perk
2. Drive a multi-plan goal with an objective
3. Drive a stacked objective to one atomic landing *(added 2026-08-13)*

### How-to guides (the five existing operator groups, current `how-to/index.md` order)

The two new guides are inserted at decided positions: `diagnose-a-perk-repo` immediately
after `recover-a-dirty-worktree` (both failure-recovery); `configure-and-verify-ci-checks`
immediately after `run-ci-in-session` (both CI). Every other relative order is the current
index order.

1. **Core workflow** — drive-the-full-spine, resume-a-plan, address-review-feedback,
   review-a-foreign-pr, *review-a-stacked-train* (added 2026-08-13), replan-an-open-plan,
   adopt-an-existing-issue, capture-a-gist,
   adopt-an-existing-project, target-a-non-default-base-branch, run-ci-in-session,
   *configure-and-verify-ci-checks* (new), recover-a-dirty-worktree,
   *diagnose-a-perk-repo* (new), run-a-worktree-setup-hook, track-implement-progress,
   *send-feedback-from-hunk-watch* (added 2026-08-12).
2. **Objectives & learnings** — author-a-roadmap, replan-an-objective, advance-or-skip-nodes,
   reconcile-an-objective, check-an-objective-for-drift,
   *recover-a-stacked-train* (added 2026-08-13), run-the-learn-docs-factory,
   run-the-learn-code-factory, run-the-learn-harvest-factory.
3. **Headless & remote** — set-up-the-remote-runner, dispatch-a-stage-to-ci,
   supervise-dispatched-runs, advance-an-objective-headlessly.
4. **Customization** — attach-a-skill-to-a-stage, author-a-repo-skill, write-a-custom-subagent,
   scope-pi-resources-per-project.
5. **Providers & backends** — select-a-provider, switch-to-linear.

### Reference (product-surface order)

1. Requirements & compatibility
2. **CLI** — hub, then children: Setup & health, Plan, Objective, PR, Learn & gist,
   Remote & utility.
3. **In-session commands & tools** — hub, then children: Stages & doors, Workflow commands,
   Review & authoring, Model-facing tools.
4. **Configuration** — hub, then children: Repository layout, Workflow & CI, Backends,
   Models & compaction, Skills & bindings.
5. Objectives
6. **Providers & issue backends** — hub, then children: Providers, Issue backends.
7. JSON Schemas
8. Glossary

### Explanation (core mental model → specialized)

1. How perk thinks
2. Gists, plans, and objectives
3. Human gates and trust
4. Headless and remote
5. perk in Zed

## §4 Page-by-page migration inventory

### Editorial-intent vocabulary (binding)

Every `keep-and-polish` row carries the **uniform polish checklist**, executed by the row's
batch node:

- **(a)** strip contributor provenance/maturity residue per the §6 voice rules;
- **(b)** verify exact claims against code / `--help` / schemas;
- **(c)** add the §6 metadata;
- **(d)** add ≤3 intent-labeled related links.

Rows with page-specific intent beyond the checklist get it pinned explicitly in the table
("checklist + …"); **no other bespoke notes exist** — nothing in the intent column is
executor-invented.

### Disposition summary

| Disposition | Count | Notes |
|---|---|---|
| `replace` | 5 | Root `index.md` + the four quadrant `index.md` pages — all rewritten by node 3.1 |
| `split` | 4 | The three reference monoliths + providers-and-backends — nodes 4.1–4.4 |
| `keep-and-polish` | 38 | Everything else — batch nodes 3.2–3.6, 4.4, 4.5 |
| `merge` | 0 | Every page was audited in planning and answers a distinct reader question |
| `retire` | 0 | Same |

**Inventory completeness rule:** every file in `git ls-files docs/user-docs | grep '\.md$'`
at the blueprint's commit has exactly one row below. The table is a point-in-time record
dated **2026-08-12**; nodes 2.3–4.5 mutate the tree it describes, and the routed-or-excluded
accounting becomes a build check from node 2.3 on.

### The five `replace` rows (all executed by node 3.1)

`replace` = rewritten as a reader-facing landing page: a one-sentence statement of the reader
need, 2–3 recommended entry points, and curated goal/surface-grouped lists. All
authoring-governance prose relocates to the excluded `_authoring.md`. Node 2.3 only creates
and seeds `_authoring.md` and does metadata/source accounting — it performs **no** editorial
dispositions; the landing rewrites are 3.1's.

| Source path | Quadrant | Disposition | Target route | Editorial intent | Node |
|---|---|---|---|---|---|
| `docs/user-docs/index.md` | Home | replace | `/` | Home-route source. Rewritten as the reader-facing home page; its six-band splash composition is a node 3.1 concern this blueprint only names. Governance prose → `_authoring.md`. | 3.1 |
| `docs/user-docs/tutorials/index.md` | Tutorials | replace | `/tutorials/` | Reader-facing tutorials landing (reader need, recommended entry point, pedagogical list). Governance prose → `_authoring.md`. | 3.1 |
| `docs/user-docs/how-to/index.md` | How-to | replace | `/how-to/` | Reader-facing task router. **Keeps the five operator group headings** (their anchors survive — §5). Governance prose → `_authoring.md`. | 3.1 |
| `docs/user-docs/reference/index.md` | Reference | replace | `/reference/` | Reader-facing reference router in product-surface order. Governance prose → `_authoring.md`. | 3.1 |
| `docs/user-docs/explanation/index.md` | Explanation | replace | `/explanation/` | Reader-facing explanation router (core mental model → specialized). Governance prose → `_authoring.md`. | 3.1 |

### The four `split` rows

Each split page becomes a **real orientation hub** at its existing path plus family children
(route shape per §2). The family lists below are binding: they drive both the child page
contents and the §5 anchor family-assignment rule.

| Source path | Quadrant | Disposition | Hub + children | Editorial intent | Node |
|---|---|---|---|---|---|
| `docs/user-docs/reference/cli.md` | Reference | split | Hub `/reference/cli/` + 6 children | Hub keeps: orientation; the **stage-launcher spine entries** (`perk implement`, `perk submit`, `perk address`, `perk land`, `perk ready` stay on the hub as the command-map's spine); the command-group map; shared conventions (aliases, `--json`). Children by family: `cli/setup-and-health.md` (`perk init`, `perk doctor`, `perk doctor workflow` + `check`/`smoke-test`); `cli/plan.md` (the `perk plan` group); `cli/objective.md` (the `perk objective` group incl. `stack`); `cli/pr.md` (the `perk pr` group; cross-links the flat spine verbs on the hub); `cli/learn-and-gist.md` (the `perk learn` + `perk gist` groups); `cli/remote-and-utility.md` (`perk workflow`, `perk worktree`, `perk state`, `perk registry`, `perk skills`, `perk release-notes`). | 4.1 |
| `docs/user-docs/reference/in-session.md` | Reference | split | Hub `/reference/in-session/` + 4 children | Hub keeps: orientation; the complete surface map; ancillary in-session features. Children by family: `in-session/stages-and-doors.md` (the stage/door model); `in-session/workflow-commands.md` (spine commands `/plan` `/plan-save` `/implement-here` `/implement` `/submit` `/ready` `/address` `/land` `/learn`, objective doors, gist doors, utility commands `/ci` `/commit-and-compact` `/perk-selfcheck` `/learn-docs` `/learn-code`); `in-session/review-and-authoring.md` (`/pr-review`, `/pr-review-dynamic`, `/pr-review-terminal`, `/pr-review-browser`, `/plan-review-browser`, `/objective-review-browser`); `in-session/model-tools.md` (the universal model-facing tools). | 4.2 |
| `docs/user-docs/reference/configuration.md` | Reference | split | Hub `/reference/configuration/` + 5 children | Hub keeps: orientation; file precedence + overlay semantics; the table map; value types. Children by family: `configuration/repository-layout.md` (the dot-directory contract); `configuration/workflow-and-ci.md` (`[worktree]`, `[workflow]`, `[ci]`, `[[ci.checks]]`); `configuration/backends.md` (`[providers]`, `[issues]`, `[linear]`); `configuration/models-and-compaction.md` (`[models]`, `[models.stages.<id>]`, `[models.subagents]`, `[compaction]`); `configuration/skills-and-bindings.md` (`[skills]`, `[[bindings]]`, repo-authored skills under `.perk/skills/`). **The fifth `backends` family is a deliberate blueprint refinement of node 4.3's four-name list** — the config tables `[providers]`/`[issues]`/`[linear]` fit none of the four named families; recorded here as a blueprint decision so 4.3's plan inherits it without re-deciding. | 4.3 |
| `docs/user-docs/reference/providers-and-backends.md` | Reference | split | Hub `/reference/providers-and-backends/` + 2 children | Hub keeps: the supported-set overview + comparison; known caveats & maturity. Children by family: `providers-and-backends/providers.md` (the provider seam: postures, what selection does, fallback semantics); `providers-and-backends/issue-backends.md` (GitHub/Linear: auth, config, labels, identifiers, doctor groups, project-backed objectives, native footprint). User-confirmed split; satisfies node 4.4's "split only if the committed inventory requires it" and the `Linear` search-matrix row. | 4.4 |

### The 38 `keep-and-polish` rows

All carry the uniform checklist; pinned page-specific intents are spelled out where they
exist. Batch nodes: tutorials → 3.2; core-workflow guides → 3.3; repository-operations
guides → 3.4; objectives & learnings guides → 3.5; headless/remote + customization +
providers/backends guides → 3.6; explanation pages → 4.5; the two focused reference
singles → 4.4. A guide named in a §7 walkthrough row must pass that walkthrough in its
batch node.

| Source path | Quadrant | Disposition | Target route | Editorial intent | Node |
|---|---|---|---|---|---|
| `docs/user-docs/tutorials/get-started.md` | Tutorials | keep-and-polish | `/tutorials/get-started/` | checklist + inventory outcomes completed at 3.2 with live-run evidence per the §7 walkthrough matrix (Get-started row) | 3.2 |
| `docs/user-docs/tutorials/drive-an-objective.md` | Tutorials | keep-and-polish | `/tutorials/drive-an-objective/` | checklist + inventory outcomes completed at 3.2 with live-run evidence per the §7 walkthrough matrix (Objective-tutorial row) | 3.2 |
| `docs/user-docs/tutorials/drive-a-stacked-objective.md` *(added 2026-08-13)* | Tutorials | keep-and-polish | `/tutorials/drive-a-stacked-objective/` | checklist (satisfied at creation) + live-run accuracy gate executed by the creating node | 2.1 (obj. #1698) |
| `docs/user-docs/how-to/drive-the-full-spine.md` | How-to | keep-and-polish | `/how-to/drive-the-full-spine/` | checklist | 3.3 |
| `docs/user-docs/how-to/resume-a-plan.md` | How-to | keep-and-polish | `/how-to/resume-a-plan/` | checklist | 3.3 |
| `docs/user-docs/how-to/address-review-feedback.md` | How-to | keep-and-polish | `/how-to/address-review-feedback/` | checklist | 3.3 |
| `docs/user-docs/how-to/review-a-foreign-pr.md` | How-to | keep-and-polish | `/how-to/review-a-foreign-pr/` | checklist | 3.3 |
| `docs/user-docs/how-to/review-a-stacked-train.md` *(added 2026-08-13)* | How-to | keep-and-polish | `/how-to/review-a-stacked-train/` | checklist (satisfied at creation) | 2.1 (obj. #1698) |
| `docs/user-docs/how-to/replan-an-open-plan.md` | How-to | keep-and-polish | `/how-to/replan-an-open-plan/` | checklist | 3.3 |
| `docs/user-docs/how-to/adopt-an-existing-issue.md` | How-to | keep-and-polish | `/how-to/adopt-an-existing-issue/` | checklist | 3.3 |
| `docs/user-docs/how-to/capture-a-gist.md` | How-to | keep-and-polish | `/how-to/capture-a-gist/` | checklist | 3.3 |
| `docs/user-docs/how-to/adopt-an-existing-project.md` | How-to | keep-and-polish | `/how-to/adopt-an-existing-project/` | checklist | 3.3 |
| `docs/user-docs/how-to/target-a-non-default-base-branch.md` | How-to | keep-and-polish | `/how-to/target-a-non-default-base-branch/` | checklist | 3.4 |
| `docs/user-docs/how-to/run-ci-in-session.md` | How-to | keep-and-polish | `/how-to/run-ci-in-session/` | checklist + must pass the §7 CI configuration/verification walkthrough in its batch node | 3.4 |
| `docs/user-docs/how-to/recover-a-dirty-worktree.md` | How-to | keep-and-polish | `/how-to/recover-a-dirty-worktree/` | checklist + must pass the §7 dirty-worktree recovery walkthrough in its batch node | 3.4 |
| `docs/user-docs/how-to/run-a-worktree-setup-hook.md` | How-to | keep-and-polish | `/how-to/run-a-worktree-setup-hook/` | checklist | 3.4 |
| `docs/user-docs/how-to/track-implement-progress.md` | How-to | keep-and-polish | `/how-to/track-implement-progress/` | checklist | 3.4 |
| `docs/user-docs/how-to/send-feedback-from-hunk-watch.md` *(added 2026-08-12)* | How-to | keep-and-polish | `/how-to/send-feedback-from-hunk-watch/` | checklist | 3.4 |
| `docs/user-docs/how-to/author-a-roadmap.md` | How-to | keep-and-polish | `/how-to/author-a-roadmap/` | checklist | 3.5 |
| `docs/user-docs/how-to/replan-an-objective.md` | How-to | keep-and-polish | `/how-to/replan-an-objective/` | checklist | 3.5 |
| `docs/user-docs/how-to/advance-or-skip-nodes.md` | How-to | keep-and-polish | `/how-to/advance-or-skip-nodes/` | checklist | 3.5 |
| `docs/user-docs/how-to/reconcile-an-objective.md` | How-to | keep-and-polish | `/how-to/reconcile-an-objective/` | checklist | 3.5 |
| `docs/user-docs/how-to/check-an-objective-for-drift.md` | How-to | keep-and-polish | `/how-to/check-an-objective-for-drift/` | checklist | 3.5 |
| `docs/user-docs/how-to/recover-a-stacked-train.md` *(added 2026-08-13)* | How-to | keep-and-polish | `/how-to/recover-a-stacked-train/` | checklist (satisfied at creation) | 2.1 (obj. #1698) |
| `docs/user-docs/how-to/run-the-learn-docs-factory.md` | How-to | keep-and-polish | `/how-to/run-the-learn-docs-factory/` | checklist | 3.5 |
| `docs/user-docs/how-to/run-the-learn-code-factory.md` | How-to | keep-and-polish | `/how-to/run-the-learn-code-factory/` | checklist | 3.5 |
| `docs/user-docs/how-to/run-the-learn-harvest-factory.md` | How-to | keep-and-polish | `/how-to/run-the-learn-harvest-factory/` | checklist | 3.5 |
| `docs/user-docs/how-to/set-up-the-remote-runner.md` | How-to | keep-and-polish | `/how-to/set-up-the-remote-runner/` | checklist + must pass the §7 remote-runner setup walkthrough in its batch node | 3.6 |
| `docs/user-docs/how-to/dispatch-a-stage-to-ci.md` | How-to | keep-and-polish | `/how-to/dispatch-a-stage-to-ci/` | checklist | 3.6 |
| `docs/user-docs/how-to/supervise-dispatched-runs.md` | How-to | keep-and-polish | `/how-to/supervise-dispatched-runs/` | checklist | 3.6 |
| `docs/user-docs/how-to/advance-an-objective-headlessly.md` | How-to | keep-and-polish | `/how-to/advance-an-objective-headlessly/` | checklist | 3.6 |
| `docs/user-docs/how-to/attach-a-skill-to-a-stage.md` | How-to | keep-and-polish | `/how-to/attach-a-skill-to-a-stage/` | checklist | 3.6 |
| `docs/user-docs/how-to/author-a-repo-skill.md` | How-to | keep-and-polish | `/how-to/author-a-repo-skill/` | checklist | 3.6 |
| `docs/user-docs/how-to/write-a-custom-subagent.md` | How-to | keep-and-polish | `/how-to/write-a-custom-subagent/` | checklist | 3.6 |
| `docs/user-docs/how-to/scope-pi-resources-per-project.md` | How-to | keep-and-polish | `/how-to/scope-pi-resources-per-project/` | checklist | 3.6 |
| `docs/user-docs/how-to/select-a-provider.md` | How-to | keep-and-polish | `/how-to/select-a-provider/` | checklist + must pass the §7 provider-selection (`pi-default`) walkthrough in its batch node | 3.6 |
| `docs/user-docs/how-to/switch-to-linear.md` | How-to | keep-and-polish | `/how-to/switch-to-linear/` | checklist | 3.6 |
| `docs/user-docs/explanation/how-perk-thinks.md` | Explanation | keep-and-polish | `/explanation/how-perk-thinks/` | checklist + explanation's no-steps/no-reference boundary enforced at 4.5 | 4.5 |
| `docs/user-docs/explanation/headless-and-remote.md` | Explanation | keep-and-polish | `/explanation/headless-and-remote/` | checklist + explanation's no-steps/no-reference boundary enforced at 4.5 | 4.5 |
| `docs/user-docs/explanation/perk-in-zed.md` | Explanation | keep-and-polish | `/explanation/perk-in-zed/` | checklist + explanation's no-steps/no-reference boundary enforced at 4.5 | 4.5 |
| `docs/user-docs/reference/objectives.md` | Reference | keep-and-polish | `/reference/objectives/` | checklist + keep as a focused single page — the inventory explicitly records **no** split | 4.4 |
| `docs/user-docs/reference/json-schemas.md` | Reference | keep-and-polish | `/reference/json-schemas/` | checklist + keep as a focused single page — the inventory explicitly records **no** split | 4.4 |

## §5 Hub & anchor migration map

### Hub stability rule

The four split pages **keep their file paths and site routes as real orientation hubs** —
never redirect stubs. Every existing repo-local link to the hub paths therefore stays valid,
including:

- all four `skills/perk-expert/references/*` canonical-source breadcrumbs
  (to `reference/configuration.md`, `reference/providers-and-backends.md`, and the
  `reference/{cli,in-session}.md` orientations);
- the `README.md` operator-docs links and the `docs/index.md` router link;
- the hub-path mentions across `docs/learned/`, `docs/design/`, and `docs/developers/`.

No perk-expert edits happen in this node; nodes 4.3/4.4 re-verify the breadcrumbs when they
execute the splits.

### Anchor map

Two binding parts. There is deliberately **no H2-inheritance rule**: the monoliths are not
grouped at H2 granularity (`reference/cli.md` puts every command-group H3 under one
`## Command groups`; `reference/configuration.md` puts every config-table H3 under one
`## Tables`; `reference/in-session.md` mixes workflow, review, and learn H3s under
`## Utility commands & tools`), so H3s are assigned by **family**, never by their current H2
parent.

#### Part 1 — explicit rows for every inbound-referenced anchor

Derived from the repo-wide sweep (re-runnable by the executing nodes):

```sh
grep -rnoE '[A-Za-z0-9./_-]+\.md#[A-Za-z0-9_-]+' docs README.md skills shared src extension
```

Every hit targeting one of the four split pages (as of 2026-08-12, all such hits live inside
`docs/user-docs/` itself) gets a row — H2 and H3 alike. Slugs are kept on the child page per
the Part 2 rule. "Stays on hub" rows need no link updates at all.

**`reference/cli.md` (46 referenced anchors):**

| Old anchor | New home |
|---|---|
| `cli.md#perk-implement-plan-alias-impl` | stays on hub (stage-launcher spine) |
| `cli.md#perk-submit` | stays on hub (stage-launcher spine) |
| `cli.md#perk-address` | stays on hub (stage-launcher spine) |
| `cli.md#perk-land` | stays on hub (stage-launcher spine) |
| `cli.md#perk-init` | `cli/setup-and-health.md#perk-init` |
| `cli.md#perk-doctor` | `cli/setup-and-health.md#perk-doctor` |
| `cli.md#perk-doctor-workflow-check` | `cli/setup-and-health.md#perk-doctor-workflow-check` |
| `cli.md#perk-doctor-workflow-smoke-test` | `cli/setup-and-health.md#perk-doctor-workflow-smoke-test` |
| `cli.md#perk-plan` | `cli/plan.md#perk-plan` |
| `cli.md#perk-plan-save` | `cli/plan.md#perk-plan-save` |
| `cli.md#perk-plan-resume-plan` | `cli/plan.md#perk-plan-resume-plan` |
| `cli.md#perk-plan-replan-plan` | `cli/plan.md#perk-plan-replan-plan` |
| `cli.md#perk-plan-from-issue` | `cli/plan.md#perk-plan-from-issue` |
| `cli.md#perk-objective-author` | `cli/objective.md#perk-objective-author` |
| `cli.md#perk-objective-save` | `cli/objective.md#perk-objective-save` |
| `cli.md#perk-objective-plan-number` | `cli/objective.md#perk-objective-plan-number` |
| `cli.md#perk-objective-show-number-alias-s` | `cli/objective.md#perk-objective-show-number-alias-s` |
| `cli.md#perk-objective-node-number` | `cli/objective.md#perk-objective-node-number` |
| `cli.md#perk-objective-node-add-number` | `cli/objective.md#perk-objective-node-add-number` |
| `cli.md#perk-objective-node-engagement-number` | `cli/objective.md#perk-objective-node-engagement-number` |
| `cli.md#perk-objective-engagement-number` | `cli/objective.md#perk-objective-engagement-number` |
| `cli.md#perk-objective-reconcile-number-alias-rec` | `cli/objective.md#perk-objective-reconcile-number-alias-rec` |
| `cli.md#perk-objective-replan-number` | `cli/objective.md#perk-objective-replan-number` |
| `cli.md#perk-objective-next-number-alias-n` | `cli/objective.md#perk-objective-next-number-alias-n` |
| `cli.md#perk-objective-run-number-alias-r` | `cli/objective.md#perk-objective-run-number-alias-r` |
| `cli.md#perk-objective-doctor-number-alias-doc` | `cli/objective.md#perk-objective-doctor-number-alias-doc` |
| `cli.md#perk-objective-stack-status-objective` | `cli/objective.md#perk-objective-stack-status-objective` |
| `cli.md#perk-objective-stack-sync-objective` | `cli/objective.md#perk-objective-stack-sync-objective` |
| `cli.md#perk-objective-stack-recover-objective` | `cli/objective.md#perk-objective-stack-recover-objective` |
| `cli.md#perk-pr-submit` | `cli/pr.md#perk-pr-submit` |
| `cli.md#perk-learn` | `cli/learn-and-gist.md#perk-learn` |
| `cli.md#perk-learn-pending` | `cli/learn-and-gist.md#perk-learn-pending` |
| `cli.md#perk-learn-docs` | `cli/learn-and-gist.md#perk-learn-docs` |
| `cli.md#perk-learn-code` | `cli/learn-and-gist.md#perk-learn-code` |
| `cli.md#perk-learn-harvest` | `cli/learn-and-gist.md#perk-learn-harvest` |
| `cli.md#perk-gist` | `cli/learn-and-gist.md#perk-gist` |
| `cli.md#perk-gist-author` | `cli/learn-and-gist.md#perk-gist-author` |
| `cli.md#perk-gist-list` | `cli/learn-and-gist.md#perk-gist-list` |
| `cli.md#perk-skills-alias-sk` | `cli/remote-and-utility.md#perk-skills-alias-sk` |
| `cli.md#perk-state-show-alias-s` | `cli/remote-and-utility.md#perk-state-show-alias-s` |
| `cli.md#perk-worktree-remove-name-alias-rm` | `cli/remote-and-utility.md#perk-worktree-remove-name-alias-rm` |
| `cli.md#perk-worktree-wipe` | `cli/remote-and-utility.md#perk-worktree-wipe` |
| `cli.md#perk-workflow-run-list-alias-ls` | `cli/remote-and-utility.md#perk-workflow-run-list-alias-ls` |
| `cli.md#perk-workflow-run-cancel-run_id` | `cli/remote-and-utility.md#perk-workflow-run-cancel-run_id` |
| `cli.md#perk-workflow-run-retry-run_id` | `cli/remote-and-utility.md#perk-workflow-run-retry-run_id` |
| `cli.md#perk-release-notes` | `cli/remote-and-utility.md#perk-release-notes` |

**`reference/in-session.md` (9 referenced anchors):**

| Old anchor | New home |
|---|---|
| `in-session.md#implement-here` | `in-session/workflow-commands.md#implement-here` |
| `in-session.md#land` | `in-session/workflow-commands.md#land` |
| `in-session.md#objective` | `in-session/workflow-commands.md#objective` |
| `in-session.md#objective-plan` | `in-session/workflow-commands.md#objective-plan` |
| `in-session.md#objective-reconcile` | `in-session/workflow-commands.md#objective-reconcile` |
| `in-session.md#objective-save` | `in-session/workflow-commands.md#objective-save` |
| `in-session.md#learn-docs` | `in-session/workflow-commands.md#learn-docs` |
| `in-session.md#learn-code` | `in-session/workflow-commands.md#learn-code` |
| `in-session.md#pr-review-terminal` | `in-session/review-and-authoring.md#pr-review-terminal` |

**`reference/configuration.md` (8 referenced anchors):**

| Old anchor | New home |
|---|---|
| `configuration.md#local-overrides--overlay-semantics` | stays on hub (precedence/overlay is hub content) |
| `configuration.md#workflow` | `configuration/workflow-and-ci.md#workflow` |
| `configuration.md#providers` | `configuration/backends.md#providers` |
| `configuration.md#issues` | `configuration/backends.md#issues` |
| `configuration.md#modelssubagents` | `configuration/models-and-compaction.md#modelssubagents` |
| `configuration.md#skills` | `configuration/skills-and-bindings.md#skills` |
| `configuration.md#bindings` | `configuration/skills-and-bindings.md#bindings` |
| `configuration.md#repo-authored-skills-piskills` | `configuration/skills-and-bindings.md#repo-authored-skills-perkskills` — the inbound link (`how-to/author-a-repo-skill.md`) is **already stale**: the live slug is `#repo-authored-skills-perkskills`. Node 4.3 fixes the inbound link to the child's true anchor as part of the migration. |

**`reference/providers-and-backends.md` (4 referenced anchors):**

| Old anchor | New home |
|---|---|
| `providers-and-backends.md#provider-seam--the-supported-set` | stays on hub (supported-set overview is hub content; its H3 details migrate to `providers-and-backends/providers.md`) |
| `providers-and-backends.md#known-caveats--maturity` | stays on hub (caveats/maturity is hub content) |
| `providers-and-backends.md#postures` | `providers-and-backends/providers.md#postures` |
| `providers-and-backends.md#issue-backend--linear-reference` | `providers-and-backends/issue-backends.md#linear` — the Linear reference lands on the child under a `## Linear` heading; this row is the final, binding mapping, and node 4.4 executes it by updating the inbound links (`how-to/switch-to-linear.md`, `reference/configuration.md`). |

#### Part 2 — family-assignment rule for all remaining anchors

Every H3 entry (a command, a config table, or a tool) not listed above migrates to the owner
of its family **per the §4 family lists** — deterministic, since §4 enumerates which
command groups, config tables, and tool families belong to which child **and which content
each hub keeps** — **keeping its slug on the owning page**. The hub is a family owner too:
an H3 in a §4 "hub keeps" list stays on the hub unchanged (e.g. `cli.md#perk-ready`, the one
stage-launcher spine entry with no Part 1 row above). Child examples:
`cli.md#perk-plan-watch-plan` → `cli/plan.md#perk-plan-watch-plan`;
`configuration.md#compaction` → `configuration/models-and-compaction.md#compaction`;
`providers-and-backends.md#fallback-semantics` →
`providers-and-backends/providers.md#fallback-semantics`.

#### Hub-retained H2 anchors (explicit list)

Broad H2 anchors that span children stay on the hub as orientation headings:

- `reference/cli.md#orientation`
- `reference/cli.md#stage-launchers-the-earned-flat-names` (the spine stays on the hub)
- `reference/cli.md#command-groups` (becomes the command-group map)
- `reference/in-session.md#orientation`
- `reference/in-session.md#utility-commands--tools` (spans the workflow-commands and
  review-and-authoring children; retained as an orientation heading pointing into both)
- `reference/in-session.md#ancillary-in-session-features`
- `reference/configuration.md#orientation`
- `reference/configuration.md#local-overrides--overlay-semantics`
- `reference/configuration.md#tables` (becomes the table map)
- `reference/configuration.md#a-note-on-value-types`
- `reference/providers-and-backends.md#orientation`
- `reference/providers-and-backends.md#provider-seam--the-supported-set`
- `reference/providers-and-backends.md#known-caveats--maturity`

H2 sections that belong wholly to one family migrate to that child under the Part 2 rule
(none of these span children): `cli.md#setup--health` → `cli/setup-and-health.md`;
`cli.md#other` → `cli/remote-and-utility.md`; `in-session.md#the-stagedoor-model` →
`in-session/stages-and-doors.md`; `in-session.md#warm-commands-by-stage-the-spine`,
`in-session.md#objective-doors-warm`, `in-session.md#gist-doors-warm` →
`in-session/workflow-commands.md`; `in-session.md#universal-model-facing-tools` →
`in-session/model-tools.md`; `configuration.md#repository-layout--the-dot-directory-contract`
→ `configuration/repository-layout.md`; `providers-and-backends.md#issue-backend--linear-reference`
→ `providers-and-backends/issue-backends.md` (explicit row above).

#### Group anchors on the how-to landing

The five `how-to/index.md` group anchors — `#core-workflow`, `#objectives--learnings`,
`#headless--remote`, `#customization`, `#providers--backends` — **survive** because the §4
landing rewrite keeps the five operator group headings.

### Migration policy

Restated from the objective: **stable hub paths outrank individual anchors.** When an anchor
cannot stay meaningful, all repository-local links are updated and the migration is recorded
in this map. This map already records every migration the blueprint anticipates — executed by
nodes 4.1–4.4, each re-running the Part 1 sweep for its page before it lands. If an executing
node hits an unanticipated anchor break, amending this map is a binding-decision change under
the §1 reconciliation rule (the §8 evidence table remains the only *designed* post-commit
mutation surface).

## §6 Divio/voice/metadata authoring contract

This section is self-contained: node 2.3 seeds the excluded `docs/user-docs/_authoring.md`
from it, and the five landing rewrites (node 3.1) relocate all remaining authoring-governance
prose there.

### Divio editorial contracts

- **Tutorial** — one live-run path with observable results at each stage and a recap of what
  the reader accomplished. The reader follows; the tutorial guarantees the outcome.
- **How-to** — one bounded goal per guide; imperative, ordered steps; refusal states
  documented at the step where they occur, with the recovery move.
- **Reference** — exact names, defaults, precedence, and failure modes, verified against
  code / `--help` / schemas; parallel structure across entries of the same kind.
- **Explanation** — relationships and trade-offs; no ordered steps, no reference tables that
  belong in the reference quadrant.

Cross-cutting: **one primary intent per page** (a page serves exactly one quadrant), and
**routed-or-excluded accounting** (every canonical source file is routed exactly once or
explicitly excluded — no orphans).

### Voice rules

- Second person, present tense, result first.
- `perk` and `Pi` spelling; exact case and punctuation for commands, file paths, config
  tables, and warm doors (`/plan-save`, `[[ci.checks]]`, `perk objective plan`).
- Define a term once (the glossary is the durable home); after that, use it.
- **No contributor provenance or plan-history language in reader copy** — no node/phase/PR
  numbers, no maturity confessions in the reader's path (maturity caveats live in clearly
  scoped caveat sections, e.g. the providers hub).
- Sparing callouts — a callout must earn its interruption.
- Descriptive link text; never "here".

### Metadata contract

Every routed page carries frontmatter:

- **`title` (required)** — byte-equal to the page's standalone `#` H1 text, which every
  source file keeps.
- **`description` (required)** — one sentence, unique corpus-wide.
- **Navigation ownership/order (required)** — every routed page's sidebar position is
  intentionally recorded through the selected metadata/sidebar mechanism (the objective's
  binding "intentional navigation ownership/order"); the §3 map is the source of truth for
  what those recordings must express.
- **Display label (optional)** — the only optional field: a sidebar label override, used when
  the full title is too long for the sidebar.

Titles and routes are unique corpus-wide. **Plain Markdown is the default**; MDX is admitted
only where a content component materially improves comprehension, stays reviewable, and is
explicitly accounted for in source inventory and learn-evidence scans. Enforcement mechanics
(schema validation, `docs_scan.py` frontmatter support, legacy fallback) are node 2.3's — this
contract binds the *what*, not the *how*.

### Dual-presentation rule

Canonical Markdown stays pleasant and structurally correct on GitHub: one visible H1 and a
readable body. The site renders one semantic H1 from metadata, with first-source-H1
suppression in the rendered body only (mechanics = nodes 1.2/2.2). Acceptance covers both
presentations.

## §7 Acceptance matrices

Copied verbatim from Objective #1622's "Durable acceptance matrices" (its reconcilable
prose; `objective_comment_id: 5262523975` — readable via `perk objective show 1622` or
`gh issue view 1622 --comments`), so later plans have a repository-local acceptance record.
Blueprint annotations (executing-node assignments) are marked as such and sit outside the
copied content.

### Search relevance

In a built local preview, each query must return the named destination among the first useful results:

| Query | Required destination |
|---|---|
| `install perk` | Get-started tutorial or Requirements and compatibility |
| `resume plan` | How to resume a plan at its current stage |
| `/land` | In-session `/land` reference |
| `perk objective plan` | Objective CLI reference |
| `[[ci.checks]]` | CI configuration reference and CI how-to |
| `dirty worktree` | Dirty-worktree recovery guide |
| `Linear` | Switch-to-Linear guide and issue-backend reference |
| `remote runner` | Remote-runner setup guide and headless/remote explanation |
| `plan vs objective` | Gists, plans, and objectives explanation |
| `doctor` | Repository-diagnosis how-to and doctor CLI reference |

This is a relevance test, not proof that a token occurs somewhere in the index.

*Blueprint annotation:* executed by **node 4.6** (the ten query-to-destination cases) and
re-run in the **5.2** gate.

### Cold-context usability

Run at least three separately reset, no-coaching evaluations. An evaluator may be a human or an isolated agent session, but the record names the evaluator type and proves it had no maintainer context. Across the three sessions, cover all six tasks:

1. Explain perk’s workflow in the evaluator’s own words from the home page.
2. Find prerequisites and begin the first tutorial.
3. Find how to resume an in-flight plan.
4. Find the exact default or precedence for one configuration key.
5. Choose correctly whether proposed work belongs in a gist, plan, or objective.
6. Find the safe next action for a dirty worktree or failed doctor check.

A task passes when the evaluator chooses the intended section/page and can state the correct next action or governing fact without coaching. Confusion, a wrong destination, or dependence on unpublished knowledge is a content/IA defect.

*Blueprint annotation:* executed at **node 5.2**.

### Executable content walkthroughs

The objective operator owns required credentials, disposable repositories, evidence capture, and cleanup. Secrets are never committed. Node 1.1 records environment readiness and blocks the dependent live walkthrough rather than silently substituting weaker evidence.

*Blueprint annotation:* the **Executing node** column is added by this blueprint; the other
three columns are the objective's verbatim matrix.

| Surface | Mode and starting state | Required result and evidence | Executing node |
|---|---|---|---|
| Get-started tutorial | Live, external: authenticated `gh`, model/Pi auth, and permission to create/delete a private disposable GitHub repo | Follow the tutorial end to end; record dated repo URL, plan issue, merged PR, learning result, expected outputs, and cleanup | 3.2 |
| Objective tutorial | Live, external: same prerequisites, fresh private repo | Author a two-node incremental objective and land Node 1.1; record objective/plan/PR identifiers, node auto-done/reconcile evidence, expected outputs, and cleanup | 3.2 |
| Dirty-worktree recovery | Hermetic local disposable git/perk repo with intentionally dirty worktrees in separate keep/discard cases | The keep path preserves work and unblocks the operation; the destructive path warns and removes only expendable work; record commands, status/diff before and after | 3.4 |
| Doctor diagnosis | Hermetic local disposable perk-wired repo with one safe, reversible managed-artifact drift | The guide identifies the correct doctor group and bounded repair path; record finding, repair, and clean recheck | 3.4 |
| CI configuration/verification | Live local disposable perk-wired repo with harmless pass, fail-then-fix, and glob-skipped checks | `/ci` reports each state accurately, never fixes, and the rerun goes green; record config, trust mode, outputs, and rerun | 3.4 |
| Provider selection | Live local disposable perk-wired repo selecting `footer = "pi-default"` | `perk init` removes any foreign footer package and `perk doctor` reports the selection; record config, settings diff, and doctor output without requiring a provider service | 3.6 |
| Remote-runner setup | Live, external: disposable GitHub repo, Actions capacity, operator-provided masked `PERK_GH_PAT`, and runner-enable variable | Static workflow check and `perk doctor workflow smoke-test --wait` pass; record sanitized outputs and Actions run URL, prove no durable dispatch record, then remove the repo/secret | 3.6 |

An executable walkthrough passes only when the documented starting state can be created and the published steps reach the expected result or documented refusal without unpublished intervention. Missing credentials or service capacity is a blocked prerequisite, never a pass. The GitHub credential/Actions preflight is performed before the tutorial and remote-content nodes; failures stop those nodes before late visual/final-gate work.

## §8 Credential/Actions readiness record

### Owner

**`mattgiles` (repository owner)** — both the credential provisioner and the preflight
runner. The owner provisions authenticated `gh`, model/Pi auth, disposable private GitHub
repos, the masked `PERK_GH_PAT`, and Actions capacity, and ensures the runner enable gate is
not disabled (`PERK_ENABLED` is an **opt-out** repo variable — `false` disables, absence
defaults on — so there is nothing to provision unless it was set); captures
and sanitizes evidence; and performs cleanup. An owner assignment is **not** readiness —
only a `confirmed` row below is.

### As-of-commit readiness state (2026-08-12)

Statically checkable rows come from a fresh, non-mutating `perk doctor workflow check` run in
this repository (sanitized output below); the disposable-repo permission, Actions capacity,
and model/Pi auth rows are owner-attested statuses obtained from the owner in this node's
implementation session. The check ran in **this** repo — the disposable-repo instances of the
PAT is provisioned — and the enable gate re-proven — by the preflight itself.

| Prerequisite | Status | Evidence |
|---|---|---|
| Authenticated `gh` | `confirmed` | `github-auth: ok — authenticated as mattgiles`; `github-repo: ok — push access to mattgiles/perk` |
| Model/Pi auth | `confirmed` | Owner-attested (local live-run auth works); repo-secret side: `runner-model-secret: ok — model credential configured (ANTHROPIC_API_KEY)` |
| Permission to create/delete private disposable repos | `confirmed` | Owner-attested (2026-08-12) |
| `PERK_GH_PAT` availability | `confirmed` | `runner-pat-secret: ok — PERK_GH_PAT configured` (this repo); owner provisions the masked PAT in each disposable repo at preflight |
| Runner enable gate | `confirmed` | Effective state: **enabled**. `PERK_ENABLED` is an opt-out variable (`false` disables; absence defaults on), so readiness means no disabling value is set — nothing to provision. Evidence: `runner-enabled: info — remote runner enabled (PERK_ENABLED unset → default-on)` (this repo); the preflight re-proves the gate in the disposable repo. |
| Actions capacity | `confirmed` | Owner-attested (2026-08-12) |

Sanitized check summary (2026-08-12): 5 ok, 2 info-level advisories (`runner-enabled`
default-on; `runner-workflow-permissions` — Actions may create PRs, advisory because perk's
runner pushes with a PAT, not `github.token`), 0 failed; overall healthy.

### Preflight definition

Before nodes **3.2** and **3.6** start their live walkthroughs, the owner runs, in the
disposable repo:

1. `perk doctor workflow check` — static readiness: auth, managed workflow, enable gate,
   PAT, model credential, advisory permissions;
2. `perk doctor workflow smoke-test --wait` — live dispatch proof; leaves no durable run
   record.

A failed preflight **blocks** the dependent node — never silently substitute weaker
evidence.

### Readiness evidence

The blueprint's one designed post-commit mutation surface: the as-of-commit row lands now,
and the node 3.2 / 3.6 preflight runs each append a dated, sanitized row via their own PRs
(this table is those nodes' recording surface).

| Date | Event | Evidence (sanitized) |
|---|---|---|
| 2026-08-12 | Node 1.1 as-of-commit readiness | `perk doctor workflow check` in `mattgiles/perk`: 5 ok, 2 info, 0 failed — healthy. Owner attestation recorded for disposable-repo permission, Actions capacity, and model/Pi auth (table above). |
| 2026-08-13 | Node 3.2 disposable-repo preflight | Static check healthy (GitHub/repository passed; runner advisories only); smoke run `31716419148` completed with conclusion `success`; `perk workflow run list` was empty; repository and its secrets were deleted. [Full sanitized evidence](./docs-site-walkthrough-evidence.md#credential-and-actions-preflight--passed). |
