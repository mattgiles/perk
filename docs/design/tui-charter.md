# perk TUI charter — the binding visual design charter for perk's pi-TUI presence

**Objective #251, node 1.1.** This is the *binding* charter for everything perk renders inside a
pi session: the inventory of what exists today (§2), the surface taxonomy and placement rules
(§3), the height + width budgets (§4), the glyph + severity vocabulary (§5), the richer pi
surfaces perk adopts or declines (§6), and the map from each charter law to the roadmap node that
implements it (§7). Decisions D1–D10 (recorded inline below) were user-confirmed during planning
(plan #260) and are charter law, not open questions. Nodes 2.1–3.1 implement the charter; this
document only decides and records it.

## §1 Scope

- **Governs the pi-TUI interior only** — the TypeScript extension (`extension/`). The Python
  CLI's stdout (the session exterior) is **out of scope**: the objective is "perk's *pi TUI*
  presence," not terminal output generally.
- **Reference surfaces only.** The checkpoints surface steps aside entirely when a foreign
  `[providers] todo` is selected (`isPerkCheckpointsReferenceSelected` in
  `extension/checkpoints.ts`); the charter governs only the perk-owned reference surface, never a
  foreign provider's rendering.
- **Headless behavior is recorded law, unchanged.** The `report()` headless-fail-safe invariant —
  `hasUI ? notify : console.error`, every rich-UI call `ctx.hasUI`-guarded — is charter law as it
  stands. This charter redesigns nothing about stderr mirroring.

## §2 Inventory (the audit)

Every UI emission in `extension/` at charter time, re-verified against the working tree
(`grep 'ctx\.ui\.' extension/*.ts` + `report(` call sites). "Via `report()`" rows inherit the
`perk: <scope> — <message>` grammar; "direct notify" rows bypass it (the inconsistency node 2.1
fixes).

### The `report()` seam (grammar-conformant notifies + headless stderr mirror)

| Call site (file · function/handler) | Surface | Trigger | Lifetime | Size |
|---|---|---|---|---|
| `report.ts` · `report()` | notify / stderr | (the seam itself) | transient toast | 1 line |
| `planMode.ts` · plan-mode toggles | notify via `report()` (info) | `/plan`, gate enter/exit | transient | 1 line |
| `objective.ts` · `/objective` handler + `reportError` | notify via `report()` (info/error) | `/objective [<id>\|clear]`, render failures | transient | 1 line |
| `lifecycleGates.ts` · dirty gate + `/implement` handoff | notify via `report()` (warning/info) | `session_before_switch`/`fork`, `/implement` | transient | 1 line |
| `planSave.ts` · save outcomes | notify via `report()` (varies) | `plan_save` tool / `/plan-save` | transient | 1 line |
| `learnDocs.ts` · gather failure paths | notify via `report()` (warning/error) | `/learn-docs` gather errors | transient | 1 line |
| `checkpoints.ts` · `/checkpoints` provider deferral | notify via `report()` (info) | `/checkpoints` with foreign todo provider | transient | 1 line |
| `address.ts` · error path | notify via `report()` (error, `alsoLog`) | `/address` failure | transient | 1 line |
| `index.ts` · workflow-state linkage error | notify via `report()` (error, `alsoLog`) | `session_start` linkage failure | transient | 1 line |
| `result.ts` · `failSoft` | notify via `report()` (error, `alsoLog`) | any fail-soft tool path | transient | 1 line |
| `objectivePlan.ts` · no-objective warnings | notify via `report()` (warning) | `/objective-plan`, `/objective-reconcile` arg errors | transient | 1 line |
| `objectiveSave.ts` · failure path | notify via `report()` | `/objective-save` errors | transient | 1 line |

### Direct `ctx.ui.notify` call sites (bypass `report()` — inconsistent grammar; node 2.1 routes these)

| Call site (file · function/handler) | Surface | Trigger | Lifetime | Size |
|---|---|---|---|---|
| `index.ts` · `session_start` handler | notify (info) | session start | transient toast | 1 line (`perk ${version} loaded`) |
| `address.ts` · `/address` handler | notify (info) | door announce | transient | 1 line |
| `submit.ts` · `/submit` handler | notify (info/error) | door result (raw tool-result text) | transient | 1 line |
| `ready.ts` · `/ready` handler | notify (info/error) | door result (raw tool-result text) | transient | 1 line |
| `land.ts` · `/land` handler | notify (info/error) | door result (raw tool-result text) | transient | 1 line |
| `ciExecutor.ts` · `/ci` handler | notify (info/warning) | CI summary (first line of result) | transient | 1 line |
| `selfcheck.ts` · selfcheck report | notify (report level) | selfcheck summary | transient | 1 line |
| `prReview.ts` · `/pr-review` handler | notify (info) | door announce | transient | 1 line |
| `learn.ts` · `/learn` handler | notify (info/error) | door announce + door result | transient | 1 line |
| `learnDocs.ts` · `/learn-docs` success | notify (info) | gather success announce | transient | 1 line |
| `objectivePlan.ts` · door announces | notify (info) | `/objective-plan`, `/objective-reconcile` | transient | 1 line |
| `objectiveSave.ts` · door announce | notify (info) | `/objective-save` | transient | 1 line |
| `checkpoints.ts` · `/checkpoints` list | notify (info) | `/checkpoints` | transient | 1 + N lines (one per step) |

### Standing surfaces (statuses + widgets)

| Call site | Surface | Trigger | Lifetime | Size |
|---|---|---|---|---|
| `checkpoints.ts` · `renderStatus` | status `perk-checkpoints` | `session_start`, `session_tree`, `turn_end` | standing | `📋 done/total · ▶n` (or `📋 <stage>` coarse fallback) |
| `checkpoints.ts` · `renderStatus` | widget `perk-checkpoints` (plain strings, above-editor, unthemed, **no width truncation**) | same | standing | **one line per plan step, unbounded** (`☑ ▶ ☐` via `stepGlyph`); 1 line on the coarse/prose fallback |
| `objective.ts` · `renderStatus` | status `perk-objective` | `session_start`, `session_tree`, `turn_end`, `/objective` | standing | `🎯 <id> · <tokens> tok · <elapsed>` |
| `objective.ts` · `renderStatus` | widget `perk-objective` (plain strings, above-editor, unthemed) | same | standing | 2 fixed lines (`objective:` / `budget:`) |

### Interactive prompts + headless mirror

| Call site | Surface | Trigger | Lifetime | Size |
|---|---|---|---|---|
| `ciExecutor.ts` · `runCiImpl` scope confirmation | `ctx.ui.confirm` | first CI run without trust/`--allow` | prompt | dialog (title + check list) |
| `askUser.ts` · `runAskUserQuestion` | `ctx.ui.select` / `ctx.ui.input` | `ask_user_question` tool | prompt | dialog |
| everywhere | `console.error` | `report()` headless fallback, `alsoLog`, logged-not-thrown render failures, headless door announces | log line | 1 line |

### Not used today

Themed widget factories, `placement: "belowEditor"`, `setFooter`/`footerData`,
`setWorkingIndicator`, `ctx.ui.custom` components/overlays, `renderCall`/`renderResult` tool
renderers, `theme.fg` anywhere, `truncateToWidth`/`visibleWidth`.

## §3 Surface taxonomy + placement rules

Every perk emission belongs to exactly one message class; each class is allowed exactly the
surfaces below. **D7 — notify policy: transitions only.** Notify carries moments of change —
never standing state.

| Message class | Allowed surface | Severity | Examples |
|---|---|---|---|
| Door announce | notify (via `report()`) | info | `/address`, `/pr-review`, `/objective-plan` start |
| Door result | notify (via `report()`) | info on success, error on failure | `/submit`, `/ready`, `/land`, `/learn` outcomes |
| Gate / deferral | notify (via `report()`) | warning | dirty-tree gate, provider deferral, handoff cancel |
| Error | notify (via `report()`), usually `alsoLog` | error | linkage failures, fail-soft tool paths |
| Standing progress | footer segment / `belowEditor` widget | n/a (themed glyphs, §5) | checkpoint progress, objective budget |
| Standing identity/state | footer | n/a | perk version, active objective, branch, model |
| Interactive prompt | `confirm` / `select` / `input` | n/a | CI scope confirmation, `ask_user_question` |
| Headless mirror | `console.error` | n/a | every class above when `!hasUI` (unchanged law, §1) |

Placement rules:

- **Notify is never standing state.** The `perk ${version} loaded` session-start banner is
  reclassified as standing identity → it moves to the footer; the toast is dropped (node 3.1).
- **Every notify goes through `report()`** and its `perk: <scope> — <message>` grammar. The
  direct-notify call sites in §2 are routed through the seam in node 2.1 (the seam grows into the
  surfaces module).
- **D4 — widget placement: `belowEditor`** for all perk widgets. Progress is peripheral
  awareness, adjacent to the perk footer — it never pushes the conversation up.
- Details belong in tool-result text, not toasts (see the D8 1-line notify budget, §4).

## §4 Height + width budgets

### Height (D8)

- **Notify = 1 line.** Details belong in tool-result text. (The `/checkpoints` multi-line list is
  the one current violator; it conforms when node 2.2 converges the checkpoint surfaces.)
- **Footer = 1 line.**
- **`perk-checkpoints` widget ≤ ~4 lines** — see the D1 windowing rule below.
- **`perk-objective` widget ≤ 2 lines** — and it is expected to fold into the footer per D2; the
  charter notes the widget may be retired in node 2.3. (Resolved in node 2.3: the widget **is**
  retired; the objective surface lives as the 🎯 segment of the composed `perk` status.)

**D1 — checkpoints widget windowing** (the height-bound decision this node was chartered to
make): the per-step checklist gets a **fixed cap of ~4 lines** — a sliding window centered on the
current step, with elision markers (e.g. `… +N earlier` / `… +N later`). Completed history
collapses; local context around the current step stays visible. (Resolved in node 2.2: the cap
counts **step lines** — 4 — with the elision markers rendering *in addition*, ≤ 6 rendered lines
worst case.) The status/footer chip keeps the
full `done/total` summary, so no information is lost — only standing screen height.

### Width (D9)

- **The never-exceed-`width` law**: every perk-rendered line obeys pi's hard rule — "Each line
  from `render()` must not exceed `width`."
- **The only truncation tools** are `truncateToWidth` / `visibleWidth` (from
  `@earendil-works/pi-tui`); no hand-rolled slicing. **Emoji occupy two terminal cells** — all
  width math accounts for it.
- **Footer segment-priority overflow order**: when the footer line overflows, drop guest
  extension statuses first, then model, then branch; **never** drop perk identity + objective.
- **Widgets truncate with ellipsis rather than wrap.** One logical line = one rendered line.

## §5 Glyph + severity vocabulary

**D3 — glyph vocabulary.** Emoji serve as **identity marks in the footer only**; everywhere else
perk uses themed single-width glyphs:

| Glyph | Theme color (`theme.fg`) | Meaning | Where allowed |
|---|---|---|---|
| `📋` | n/a (emoji, 2 cells) | plan-progress identity mark | footer segment only |
| `🎯` | n/a (emoji, 2 cells) | objective identity mark | footer segment only |
| `✓` | `success` | done / completed step | widgets, tool-result text |
| `▸` | `accent` | current / active | widgets, tool-result text |
| `○` | `dim` | pending | widgets, tool-result text |
| `⚠` | `warning` | degraded / deferral | widgets, notify text, tool-result text |
| `✗` | `error` | failure | widgets, notify text, tool-result text |

- **`☑ ▶ ☐` are retired.** (Charter prose; the code change is node 2.2, which also amends the
  `shared/contracts.md` Checkpoints P2.T2c block that specs the current render — contracts move
  with behavior, not with this docs-only node.)
- **Widget lines move from plain strings to theme-callback factories**
  (`(tui, theme) => ({ render, invalidate })`) so the glyph colors above are live-themed.
- **The `report()` grammar is the notify grammar**: `perk: <scope> — <message>`, severity
  `info | warning | error`. Severity semantics: *info* = expected transition (announce, success
  result); *warning* = gate, deferral, degraded-but-continuing; *error* = failure the user must
  see. Routing every notify through it is node 2.1.
- **D10 — theme-invalidation law: perk components never pre-bake theme colors** into stored or
  cached strings (the pi-documented theme-switch trap). The safe patterns — binding on nodes
  2.2/3.1 — are stateless render with theme callbacks, or rebuilding themed content in
  `invalidate()`.

## §6 Richer pi surfaces: adopted / declined

### Adopted

**`setFooter` + `footerData` (D2) — perk owns the footer.** Perk is not one extension among many
in a perk-managed repo — pi is under the hood. The charter commits to a perk-owned footer
composing, in fixed order:

1. perk identity/version,
2. active objective (`🎯` segment — the `perk-objective` status becomes this segment),
3. plan progress (`📋` segment — the `perk-checkpoints` status becomes this segment),
4. git branch (via `footerData.getGitBranch()`),
5. model (via `ctx.model`),
6. other extensions' statuses (via `footerData.getExtensionStatuses()` — perk rules the roost but
   doesn't silence guests).

- **Ownership law**: `setFooter` replaces pi's default footer wholesale and is last-write-wins —
  perk is the **sole** footer owner in perk-managed repos (the charter makes the implicit pi
  assumption explicit). Adopting it means perk owns branch/model/token display too.
- **Reactivity contract**: the footer component drives its own repaints. It re-renders on perk
  state change (objective budget, checkpoint progress) and on branch change
  (`footerData.onBranchChange(() => tui.requestRender())`), and implements the `dispose`
  lifecycle. Guest statuses via `getExtensionStatuses()` are **best-effort fresh** — pi gives no
  repaint guarantee on guest-status change, and the charter records that as acceptable.
- The two `setStatus` keys (`perk-checkpoints`, `perk-objective`) become footer **segments**; the
  separate-status era ends in nodes 2.3/3.1. (Node 2.3 collapsed the two keys into the **single
  composed `perk` status slot** — ordered objective → checkpoints, two-space join, composed by
  `surfaces.ts createPerkStatus`; node 3.1 lifts that composition into `setFooter`.)

**Themed widget factories (D3/D10).** Widgets adopt the `(tui, theme) => ({ render, invalidate })`
factory form so glyphs are theme-colored without pre-baking (§5).

**`belowEditor` placement (D4).** All perk widgets render below the editor (§3).

**`setWorkingIndicator` (D5).** Perk adopts a branded working indicator — a light identity touch,
cheap and reversible; the exact frames are node 3.1's call within the D3 vocabulary. Two pi facts
bind the implementation: frames are rendered **verbatim** (perk must theme them itself via
`ctx.ui.theme.fg(...)`), and only the **streaming spinner** is affected (compaction/retry loaders
keep pi's built-in styling).

### Declined

- **`ctx.ui.custom` components/overlays (D6): not adopted** in this objective. The existing
  `confirm`/`select`/`input` prompts suffice; recorded as out of charter scope.
- **`renderCall`/`renderResult` tool renderers: not adopted.** Not needed yet — recorded as
  future-eligible (a later objective may render perk tool calls richly; nothing here forecloses
  it).

## §7 Implementation map

| Node | What it implements from this charter |
|---|---|
| 2.1 | Surfaces module: `report()` grows into the one routing seam; every direct-notify call site in §2 conforms to the §3/§5 grammar + D7 policy. |
| 2.2 | Checkpoints convergence: D1 windowing (≤ ~4 lines), D3 glyphs (retire `☑ ▶ ☐`), themed factories + D10, D9 truncation; amends the `shared/contracts.md` checkpoints render spec in the same turn. |
| 2.3 | Status coordination: the two `setStatus` keys become ordered footer segments; the `perk-objective` widget may be retired (D2/D8). *(Implemented: the two per-feature status slots collapsed into one composed `perk` slot — objective → checkpoints order, two-space join — and the `perk-objective` widget is retired; the checkpoints widget keeps slot `perk-checkpoints`.)* |
| 3.1 | Footer + indicator adoption: `setFooter` with the D2 segment spec, ownership law, and reactivity contract; D9 overflow order; `setWorkingIndicator` (D5); the version banner moves toast → footer (D7). |
| 4.1 | Regression guard: tests pinning the charter's budgets and vocabulary so drift fails CI. |
