# perk TUI charter — the binding visual design charter for perk's pi-TUI presence

**Objective #251, node 1.1.** This is the *binding* charter for everything perk renders inside a
pi session: the inventory of what exists today (§2), the surface taxonomy and placement rules
(§3), the height + width budgets (§4), the glyph + severity vocabulary (§5), the richer pi
surfaces perk adopts or declines (§6), and the map from each charter law to the roadmap node that
implements it (§7). Decisions D1–D10 (recorded inline below) were user-confirmed during planning
(plan #260) and are charter law, not open questions. Nodes 2.1–3.1 implement the charter; this
document only decides and records it.

**Status note (2026-08, Objective #1416):** the checkpoints surface is retired. The
`checkpoints.ts` status/widget rows in §2's standing-surfaces table and the **D1** windowing
decision describe a deleted surface; `setStandingWidget` and the widget line cap are gone (no
standing widget consumer remains). The composed `perk` status is now **single-value** (objective
only — `createPerkStatus` kept its name, lost the segment map). Implement progress is the borrowed
`@juicesharp/rpiv-todo` checklist.

## §1 Scope

- **Governs the pi-TUI interior only** — the TypeScript extension (`extension/`). The Python
  CLI's stdout (the session exterior) is **out of scope**: the objective is "perk's *pi TUI*
  presence," not terminal output generally.
- **Reference surfaces only.** The checkpoints surface steps aside entirely when a foreign
  `[providers] todo` is selected (`isPerkCheckpointsReferenceSelected` in
  `extension/checkpoints.ts`); the charter governs only the perk-owned reference surface, never a
  foreign provider's rendering.
- **Report-routed terminal ownership is recorded law.** `hasUI` is authoritative: a headless
  target receives the complete prefixed report on stderr exactly once; every headful mode receives
  a one-line Pi-managed notify. Only an explicitly mirrored RPC report may additionally write its
  complete value to stderr. Headful TUI, print, json, and missing-mode contexts never raw-log through
  `report()`. A warm command's multiline detail is persisted in a display-only
  `perk:report-detail` transcript entry; the equivalent model tool keeps complete detail in its
  Result. This boundary governs `report()` only — it does not claim every direct first-party stderr
  write has been migrated.

## §2 Inventory (the audit)

Every UI emission in `extension/` at charter time, re-verified against the working tree
(`grep 'ctx\.ui\.' extension/*.ts` + `report(` call sites). "Via `report()`" rows inherit the
`perk: <scope> — <message>` grammar; "direct notify" rows bypass it (the inconsistency node 2.1
fixes).

### The `report()` seam (one-line managed headline + complete diagnostic projection)

| Call site (file · function/handler) | Surface | Trigger | Lifetime | Size |
|---|---|---|---|---|
| `report.ts` · `report()` | notify / stderr / attached detail entry | (the seam itself) | transient headline / durable command detail | 1-line headline / complete detail |
| `planMode.ts` · plan-mode toggles | notify via `report()` (info) | `/plan`, gate enter/exit | transient | 1 line |
| `objective.ts` · `/objective` handler + `reportError` | notify via `report()` (info/error) | `/objective [<id>\|clear]`, render failures | transient | 1 line |
| `lifecycleGates.ts` · dirty gate + `/implement` handoff | notify via `report()` (warning/info) | `session_before_switch`/`fork`, `/implement` | transient | 1 line |
| `planSave.ts` · save outcomes | notify via `report()` (varies) | `plan_save` tool / `/plan-save` | transient | 1 line |
| `learnDocs.ts` · gather failure paths | notify via `report()` (warning/error) | `/learn-docs` gather errors | transient | 1 line |
| `checkpoints.ts` · `/checkpoints` provider deferral | notify via `report()` (info) | `/checkpoints` with foreign todo provider | transient | 1 line |
| `address.ts` · error path | notify via `report()` (error, `alsoLog`) | `/address` failure | transient | 1 line |
| `index.ts` · workflow-state linkage error | notify via `report()` (error, `alsoLog`) | `session_start` linkage failure | transient | 1 line |
| `result.ts` · `failFor` | notify via `report()` (error, `alsoLog`) | any soft-result tool path | transient | 1-line headline |
| `objectivePlan.ts` · no-objective warnings | notify via `report()` (warning) | `/objective-plan`, `/objective-reconcile` arg errors | transient | 1 line |
| `objectiveSave.ts` · failure path | notify via `report()` | `/objective-save` errors | transient | 1 line |

Every `registerPerkCommand` handler attaches a detail sink to its exact command-context object
before the `running…` report and before the handler runs. A multiline report therefore projects to
one managed headline plus one complete `perk:report-detail` entry. The WeakMap attachment remains
available to background work launched by that command. Tool and lifecycle contexts without a
command sink append no transcript-detail entry: tools carry complete detail in Results. A headful
lifecycle/event report emits the managed headline; when a headful RPC caller also sets `alsoLog`, it
additionally mirrors the complete diagnostic to stderr.

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

*(Retired with Objective #1416 — see the status note above.)*

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
| `report()` | `console.error` | headless complete fallback; explicitly mirrored RPC diagnostic | log block | complete report |
| direct first-party writes outside `report()` | `console.error` / stderr | cache/config/session-data fallbacks, objective callbacks, binding warnings, worker/headless code | log | caller-owned |

### Not used today

`setWorkingIndicator` (declined — D5 rescinded in node 3.1, see §6), `renderCall`/`renderResult`
tool renderers. *(Charter-time entries since adopted: themed widget factories + `theme.fg` +
`truncateToWidth`/`visibleWidth` + `placement: "belowEditor"` in node 2.2; `setFooter`/`footerData`
in node 3.1; entry renderers — the generic full-report entry plus collapsed transition-marker
families — in the pi 0.80.4+ audit §2.3 adoption, see §6.)*

### Bounded exceptions / permitted text-only surfaces (vendored extensions)

| Surface | Owner | Status | Note |
|---|---|---|---|
| `ctx.ui.custom` overlay | `vendor/btw/btw.ts` (`BtwOverlay`) | **Sanctioned exception** (§6 D6) | The **one** `ctx.ui.custom` use — `/btw`'s human-only side-chat popover. Human-invoked only, `hasUI`-gated, no model tool, not a stage/door → never machine-reachable. `ctx.ui.custom` stays **declined for all workflow surfaces**. |
| `setWorkingMessage` | `vendor/whimsical/whimsical.ts` (via the `setWorkingMessage` surfaces seam) | **Permitted** (never declined) | Text-only label on pi's existing default spinner; the new seam no-ops headless. Distinct from the still-declined `setWorkingIndicator` (D5). |
| `ctx.ui.select` | `vendor/btw/btw.ts` close flow | Already adopted | `confirm`/`select`/`input` are charter-permitted interactive prompts (§3). |

## §3 Surface taxonomy + placement rules

Every perk emission belongs to exactly one message class; each class is allowed exactly the
surfaces below. **D7 — notify policy: transitions only.** Notify carries moments of change —
never standing state.

| Message class | Allowed surface | Severity | Examples |
|---|---|---|---|
| Door announce | notify (via `report()`) | info | `/address`, `/pr-review`, `/objective-plan` start |
| Door result | notify (via `report()`); multiline warm-command detail also uses `perk:report-detail` | info on success, error on failure | `/submit`, `/ready`, `/land`, `/learn` outcomes |
| Gate / deferral | notify (via `report()`) | warning | dirty-tree gate, provider deferral, handoff cancel |
| Error | notify (via `report()`); `alsoLog` is only a headless/RPC diagnostic mirror | error | linkage failures, fail-soft tool paths |
| Standing progress | footer segment / `belowEditor` widget | n/a (themed glyphs, §5) | checkpoint progress, objective budget |
| Standing identity/state | footer | n/a | perk version, active objective, branch, model |
| Interactive prompt | `confirm` / `select` / `input` | n/a | CI scope confirmation, `ask_user_question` |
| Headless / RPC mirror | `console.error` | n/a | complete report when `!hasUI`; explicit `alsoLog` only when headful RPC |

Placement rules:

- **Notify is never standing state.** The `perk ${version} loaded` session-start banner is
  reclassified as standing identity → it moves to the footer; the toast is dropped (node 3.1).
- **Every notify goes through `report()`** and its `perk: <scope> — <message>` grammar. The
  direct-notify call sites in §2 are routed through the seam in node 2.1 (the seam grows into the
  surfaces module).
- **D4 — widget placement: `belowEditor`** for all perk widgets. Progress is peripheral
  awareness, adjacent to the perk footer — it never pushes the conversation up.
- Details never belong in toasts (see the D8 1-line notify budget, §4). Model tools keep complete
  detail in their Result; multiline warm commands append the complete display-only
  `perk:report-detail` entry below the headline.

## §4 Height + width budgets

### Height (D8)

- **Notify = 1 line.** Tool detail belongs in Result text; multiline warm-command detail belongs in
  the full `perk:report-detail` transcript entry. (The retired `/checkpoints` multi-line list was the
  charter-time violator.)
- **Footer = 1 line.**
- **`perk-checkpoints` widget ≤ ~4 lines** — see the D1 windowing rule below.
- **`perk-objective` widget ≤ 2 lines** — and it is expected to fold into the footer per D2; the
  charter notes the widget may be retired in node 2.3. (Resolved in node 2.3: the widget **is**
  retired; the objective surface lives as the 🎯 segment of the composed `perk` status.)

*(Retired with Objective #1416 — see the status note above.)*

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
- **Footer segment-priority overflow order**: when the footer line overflows, drop whole
  segments — guest extension statuses first (rightmost-first), then thinking, then model, then
  branch, then cache, then context usage, then the checkpoints segment (the node-3.1 extension
  for the new segments, plus the audit-§2.6 cache segment);
  **never** drop perk identity + objective — if still over after all drops, `truncateToWidth`
  as the last resort.
- **Widgets truncate with ellipsis rather than wrap.** One logical line = one rendered line.

## §5 Glyph + severity vocabulary

**D3 — glyph vocabulary.** Emoji serve as **identity marks in the footer only**; everywhere else
perk uses themed single-width glyphs. The vocabulary governs perk's **standing surfaces +
notify/tool-result text**; the **`btw` exception overlay** (§6) follows the same themed-glyph set
where it draws glyphs (its charter-time `❌` error glyph → themed `✗` `error`, its running `⚙` →
themed `▸` `accent`; `✓` `success` / `✗` `error` kept).

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
  `info | warning | error`. A headful notify uses the first non-empty logical message row, trimmed
  and horizontally normalized; the complete prefixed bytes remain the diagnostic projection.
  Severity semantics: *info* = expected transition (announce, success result); *warning* = gate,
  deferral, degraded-but-continuing; *error* = failure the user must see. Routing every notify
  through it is node 2.1.
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
  `surfaces.ts createPerkStatus`; node 3.1 lifted that composition into `setFooter` —
  `surfaces.ts perkFooter`/`installPerkFooter`, installed on every headful `session_start` under
  pi's now-explicit dispose contract (verified at pi 0.84.1: `setExtensionFooter` disposes a
  replaced footer factory, and `resetExtensionUI` restores the built-in footer on `/reload` and
  before session replacement — the earlier once-only guard existed only while dispose-on-replace
  was unverified). The composed `perk` slot **keeps publishing**: it is the RPC-visible surface,
  since `setFooter` is an RPC no-op.)

**Node-3.1 amendments (user-confirmed in the node-3.1 planning session):**

- **Context-usage segment.** The footer gains a context segment after model (extending the D2
  list above between items 5 and 6): `<percent.toFixed(1)>%/<window>` mirroring pi's default
  footer (e.g. `42.3%/200k`; `?/<window>` when percent is unknown), via `ctx.getContextUsage()`,
  colored `error` when >90, `warning` when >70, else dim.
- **Split layout.** The one footer line is split: perk segments left (identity · 🎯 objective ·
  📋 checkpoints, two-space-joined, segments verbatim), system info right-aligned (branch ·
  model · context · guests, two-space-joined, ≥2 spaces of padding between the groups, dim):

  ```
  perk v0.0.1  🎯 251 · 10.0k tok · 5m  📋 1/3 · ▸2   main  gpt-5  high  CH42.3%  42.3%/200k  ◆ g
  └─────────┘  └─────────────────────┘  └─────────┘   └──┘  └───┘  └──┘  └─────┘  └────────┘  └─┘
   identity       objective segment     checkpoints  branch model think   cache    context   guest
  ◀════════ left group (charter order 1–3) ══▶  ◀══ right group (4, 5, +context, 6) ══▶
  ```

- **Thinking-level segment.** The footer gains a thinking segment immediately after model: the
  session thinking level rendered as bare level text (dim; `off`/`minimal`/…/`xhigh`), with no
  glyph or label. Always shown when a model is present (including `off`); omitted when there is no
  model. Read **live** in `render()` via `pi.getThinkingLevel()` (D10 stateless render, render-driven
  reactivity — no event subscription); pi's clamp to model capabilities means non-reasoning models
  render `off`.
- **Cache-hit segment** (the pi 0.80.4+ audit §2.6 adoption — restores the always-on cache
  surface the sole-owner law displaced). The footer gains a prompt-cache-hit segment between
  thinking and context (pi's stats adjacency): pi's default-footer `CH` computation mirrored
  locally in `surfaces.ts latestCacheHitRate` (pi's cache-stats helpers are unexported — the
  `sanitizeGuestStatus` precedent), rendered `CH<rate.toFixed(1)>%` (e.g. `CH42.3%`), dim.
  Display-gated on cache activity: absent until the session's total cacheRead/cacheWrite > 0
  AND the latest usage-bearing assistant message has prompt tokens > 0 (a trailing
  zero-prompt-token assistant message resets it — exactly pi's behavior). Read **live** in
  `render()` via `ctx.sessionManager.getEntries()` (D10 stateless render — no subscription).
- **Extended D9 drop order.** With the new segments, overflow drops whole segments in order:
  guests (rightmost-first) → thinking → model → branch → cache → context → checkpoints; identity +
  objective are truncate-only, never dropped (see §4).

**Themed widget factories (D3/D10).** Widgets adopt the `(tui, theme) => ({ render, invalidate })`
factory form so glyphs are theme-colored without pre-baking (§5).

**`belowEditor` placement (D4).** All perk widgets render below the editor (§3).

**Entry renderers (`pi.registerEntryRenderer`) — adopted for display-only full reports and
transition markers.** The generic full-detail family is `perk:report-detail`; transition-marker
families are `perk:workflow-state`, `perk:objective-budget`, and btw's `btw-thread-entry` /
`btw-thread-reset` (historical `perk:checkpoint` entries are no longer rendered). The policy
answer remains: **a transcript renderer IS a rich-UI surface the surfaces module owns** — renderer
bodies live in `surfaces.ts`; registration is wiring via the `registerTranscriptRenderer` seam,
which carries the one `typeof` feature-detect (pre-0.80.4 hosts lack the method and stay inert; in
json/RPC mode pi never invokes renderers, so registration is inert-safe everywhere).

The two renderer shapes are intentionally distinct:

- A **collapsed transition marker** is exactly one dim, width-truncated line in the
  `perk: <scope> — <message>` grammar. Its expanded view is human-requested scrollback and may add
  detail. The workflow-state marker vocabulary remains deliberately bounded: run claim/fork, mode
  flip, objective set/clear, plan link, and a SET `objective_node_claim`; bookkeeping deltas stay
  invisible.
- A **full `perk:report-detail` entry** always renders every logical row, regardless of Pi's
  expanded flag. The first row uses the report severity color (`error`, `warning`, or dim for
  info); continuation rows are dim; blank interior rows stay blank. Terminal escape and control
  sequences are stripped only from the display projection, leaving the persisted payload exact.
  Every displayed row passes through `truncateToWidth`, and styling is computed in `render()` so
  theme changes are never cached.
  Its payload is exactly `{ text, severity }`, validated as a plain object with non-blank text and
  a known severity; malformed data renders nothing. These durable entries remain excluded from
  model context.

### Declined

- **`setWorkingIndicator` (D5): RESCINDED** — a node-3.1 user decision (this entry moved from
  Adopted; D5 originally committed to a branded working indicator). The API rationale: indicator
  frames are rendered **verbatim** — pre-baked strings whose colors perk would have to bake in
  itself, which collides with the D10 never-pre-bake-theme-colors law, and no theme-change hook
  exists to rebuild them against. Perk keeps pi's default spinner; perk never calls
  `setWorkingIndicator`.
- **`ctx.ui.custom` components/overlays (D6): declined for all workflow surfaces.** The existing
  `confirm`/`select`/`input` prompts suffice for machine-driven surfaces. The **purpose** of the
  decline is to keep every perk surface **machine-executable**: perk's workflow runs cold (the
  Python CLI launches `pi`), headless, and over RPC/`--json`, driven by model **tools** and
  stage/door transitions — a focus-owning interactive overlay cannot be driven by a machine, so
  workflow surfaces must never depend on one.

  **Exception criteria (the exception that proves the rule).** A `ctx.ui.custom` overlay is
  permitted **only** when it is, in full: (1) **human-invoked only** — no model tool, no stage, no
  door, no cold/headless/RPC entry point; (2) **`ctx.hasUI`-gated** — never opens outside an
  interactive TUI; (3) outside the machine-driven workflow entirely; and it must still obey (4) the
  §4 D9 width law, (5) the §5 D10 stateless-render law, and (6) the §5 themed-glyph vocabulary.
  Anything reachable by a machine stays bound by this D6 decline. The exception's boundary **is** the
  rule's own criterion (machine-unreachability), so it proves the rule rather than eroding it.

  **`btw` is the named, sole sanctioned instance.** `/btw`'s entire UI is a `ctx.ui.custom` overlay
  (`BtwOverlay`) — a live side-chat transcript + input that cannot be expressed via
  `confirm`/`select`/`input`. It is invoked **only** by a human typing `/btw`, exposes **no model
  tool**, is **not** a stage or door, and its overlay is **`ctx.hasUI`-gated** (never opens cold /
  headless / RPC). Because it sits entirely outside machine reach it cannot threaten the
  machine-executability this decline protects — which is exactly why it is a *sanctioned exception*
  and `ctx.ui.custom` **remains declined for all workflow surfaces**. (Recorded as a bounded
  exception, **not** a charter adoption.)

- **`setWorkingMessage` (text-only): permitted, not a reversal of D5.** `setWorkingMessage` was
  never declined — only `setWorkingIndicator` was (D5: indicator frames render verbatim with
  pre-baked colors, the D10 conflict). `setWorkingMessage` sets only a plain **text** label on pi's
  existing default indicator — no frames, no colors, no theming — and the new surfaces seam
  **no-ops headless**. perk still keeps pi's default spinner; `whimsical` only flavors its label
  through the seam. Brought under the surfaces seam + guard as governance; `setWorkingIndicator`
  stays declined.
- **`renderCall`/`renderResult` tool renderers: not adopted.** Not needed yet — recorded as
  future-eligible (a later objective may render perk tool calls richly; nothing here forecloses
  it).

### Recorded gaps (node 3.1) — what the pi API can't express

1. **`setFooter` (and `setWorkingIndicator`) are no-ops in RPC mode.** The composed `perk` status
   slot (`setStatus`, dual-published by `createPerkStatus`) remains the RPC-visible surface —
   this is why the slot keeps publishing even though the TUI footer renders the segments
   directly.
2. **Guest-status freshness is best-effort.** Pi gives no repaint guarantee on a guest
   `setStatus` change reaching a custom footer (already charter-accepted under D2; restated here
   as the gap it is).
3. **Model/context reactivity is render-driven.** No model-change or context-usage event exists
   for extensions; the footer reads `ctx.model`/`ctx.getContextUsage()` live per render and
   catches up on the next repaint.
4. **Working-indicator theming.** `setWorkingIndicator` frames render verbatim with pre-baked
   colors and cannot be live-themed — the D10 conflict that motivated declining D5.
5. **Direct stderr outside `report()`.** Cache/config/session-data fallbacks, objective callbacks,
   binding warnings, and worker/headless code still contain first-party direct writes. They are
   outside the report-routing fix and remain an explicit interactive-layout residual risk; this
   charter does not pretend the broader logging system has been migrated.

## §7 Implementation map

| Node | What it implements from this charter |
|---|---|
| 2.1 | Surfaces module: `report()` grows into the one routing seam; every direct-notify call site in §2 conforms to the §3/§5 grammar + D7 policy. |
| 2.2 | Checkpoints convergence: D1 windowing (≤ ~4 lines), D3 glyphs (retire `☑ ▶ ☐`), themed factories + D10, D9 truncation; amends the `shared/contracts.md` checkpoints render spec in the same turn. |
| 2.3 | Status coordination: the two `setStatus` keys become ordered footer segments; the `perk-objective` widget may be retired (D2/D8). *(Implemented: the two per-feature status slots collapsed into one composed `perk` slot — objective → checkpoints order, two-space join — and the `perk-objective` widget is retired; the checkpoints widget keeps slot `perk-checkpoints`.)* |
| 3.1 | Footer adoption (shipped): `setFooter` with the D2 segment spec + the node-3.1 context segment + split layout, ownership law, and reactivity contract; the extended D9 overflow order; the `perk ${version} loaded` toast retired — identity is a standing footer segment (D7). D5 **rescinded** (no `setWorkingIndicator`); the API gaps recorded in §6. |
| vendored (`btw`/`whimsical`) | The bounded `ctx.ui.custom` exception (§2/§6: `btw`, human-only, machine-unreachable — the exception that proves the D6 rule) and the permitted text-only `setWorkingMessage` surface (§2/§6: `whimsical`, headless-no-op, distinct from the declined `setWorkingIndicator`), both routed through the surfaces module + guard. |
| 4.1 | Regression guard: tests pinning the charter's budgets and vocabulary so drift fails CI. *(Implemented: the budget/vocabulary pins already live in `extension/surfaces.test.ts` (node 2.1 — slot keys, `GLYPHS`, `*_MAX_LINES`); this node added the call-site regression guard `extension/surfacesGuard.test.ts` — rich-UI calls (`ui.notify`/`setStatus`/`setWidget`/`setFooter`) allowlisted to surfaces.ts + report.ts, `setWorkingIndicator` banned everywhere — plus the discipline records in AGENTS.md and `shared/contracts.md` §8.3. The audit §2.3 adoption extended the guard with two rules: the raw `.registerEntryRenderer(` call is confined to the surfaces module (the `registerTranscriptRenderer` seam), and pi-tui imports are confined to the surfaces module + the named `vendor/btw` D6 exception, with a pattern-matches-the-seam self-check.)* |
