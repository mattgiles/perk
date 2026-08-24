# Docs-site modernization hardening walkthrough evidence

## Purpose and evidence contract

This is the integrated hardening rerun assigned by Objective #1898 node 3.1. It records the
finished docs site, not the first rendered proof, against the binding
[`docs-site-visual-blueprint.md`](../docs-site-visual-blueprint.md). The run covers the complete
rendered matrix, diagram no-JS/print/keyboard/reduced-motion behavior, fresh WCAG contrast math,
and a §1–§12 blueprint↔artifact agreement sweep.

Approval is deliberately two-stage:

1. the reviewed plan approved the bound routes, 91-shot matrix, pass protocols, contrast method,
   note shape, and defect policy;
2. the final PR carries the rendered evidence in a
   [durable SHA-pinned comment](https://github.com/mattgiles/perk/pull/1917#issuecomment-5349696465),
   and merge is the approval of this record.

The screenshots and disposable scripts follow the earlier evidence-delivery mechanism: they are
committed under `docs/planning/evidence-1898-3.1/` at
`e101a3f82502e1a43be4b2e78b392ecbffd59a73` so the PR comment can
link immutable raw files, then the directory is removed by the final pre-merge commit. The merged
tree contains this note and its `docs/index.md` row, with zero evidence binaries and zero disposable
scripts.

### Explicit waivers and obsolete checks

These rows are part of the evidence contract: a skipped or obsolete pass must never be inferred to
have happened.

| Item | Date | Binding directive | Recorded outcome |
|---|---|---|---|
| Manual screen-reader spot pass | 2026-08-19 | **SKIPPED entirely — operator-settled during node 3.1 planning. No scripted replacement is added.** | **Waived, not run, and not claimed as a pass.** |
| Dreaming-marker re-check | 2026-08-19 | **Obsolete — operator-settled during node 2.1 because dreaming renders unmarked.** | **Not run.** The settled unmarked rendering is provenance, not a fresh hardening claim. |

## Environment and identity

| Field | Evidence |
|---|---|
| Date | 2026-08-19 local (`2026-08-20T00:19:47Z` final capture timestamp) |
| Operator/executor | Operator-settled protocol; implementing agent executed the scripted and manual sweeps |
| Trunk SHA | `0b7ca80053bf7650fdc0a9c07c4ced38af9cda71` |
| PR evidence SHA | `e101a3f82502e1a43be4b2e78b392ecbffd59a73` (the commit containing the disposable evidence directory) |
| Platform | macOS 26.5 arm64 |
| Browser | Google Chrome 151.0.7922.140, headless CDP |
| Toolchain | Node v26.3.0; npm 11.16.0; Astro 7.2.1; Starlight 0.41.7 |
| Build | `just docs-build` — 76 pages plus Pagefind; expected no-`site` sitemap warning only |
| Serve | `just docs-preview` — built, Pagefind-accurate acceptance surface |
| Mechanical check | Configured `docs-check` selected check passed: docs guards, Biome, TypeScript, controller tests, static build, `built-site.test.mjs`, `a11y.test.mjs`, and Pagefind |

## Rendered acceptance matrix

The base matrix is eight pages × two themes × five review widths: 320, 768, 1280, wide 1600,
and 640 CSS px as the 200%-zoom equivalent. The two configuration routes intentionally cover both
the bound hub (`/reference/configuration/`) and the dense-child intent
(`/reference/configuration/workflow-and-ci/`). The article slot is `/tutorials/get-started/`.
The 11 diagram-specific rows follow the 80 base rows.

Every base-row assertion checked route identity, forced theme, loaded local fonts, complete images,
0px page overflow, and (on home) the expected enhanced disclosure state. All 91 final PNGs were
reviewed as contact sheets and representative full-resolution images; compositions, shell modes,
contained tables/code, source-order linearization, and light/dark finish agreed with the blueprint.
The [durable PR comment](https://github.com/mattgiles/perk/pull/1917#issuecomment-5349696465)
carries galleries grouped by page/state and raw links pinned to
`e101a3f82502e1a43be4b2e78b392ecbffd59a73`.

| # | Shot | Route/state | Theme | Width | Result | Assertion |
|---:|---|---|---|---:|---|---|
| 1 | `hardening--home--light--320.png` | / | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 2 | `hardening--home--light--768.png` | / | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 3 | `hardening--home--light--1280.png` | / | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 4 | `hardening--home--light--1600.png` | / | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 5 | `hardening--home--light--640-zoom200.png` | / | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 6 | `hardening--home--dark--320.png` | / | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 7 | `hardening--home--dark--768.png` | / | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 8 | `hardening--home--dark--1280.png` | / | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 9 | `hardening--home--dark--1600.png` | / | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 10 | `hardening--home--dark--640-zoom200.png` | / | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px; disclosures collapsed |
| 11 | `hardening--tutorials--light--320.png` | /tutorials/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 12 | `hardening--tutorials--light--768.png` | /tutorials/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 13 | `hardening--tutorials--light--1280.png` | /tutorials/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 14 | `hardening--tutorials--light--1600.png` | /tutorials/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 15 | `hardening--tutorials--light--640-zoom200.png` | /tutorials/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 16 | `hardening--tutorials--dark--320.png` | /tutorials/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 17 | `hardening--tutorials--dark--768.png` | /tutorials/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 18 | `hardening--tutorials--dark--1280.png` | /tutorials/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 19 | `hardening--tutorials--dark--1600.png` | /tutorials/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 20 | `hardening--tutorials--dark--640-zoom200.png` | /tutorials/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 21 | `hardening--how-to--light--320.png` | /how-to/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 22 | `hardening--how-to--light--768.png` | /how-to/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 23 | `hardening--how-to--light--1280.png` | /how-to/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 24 | `hardening--how-to--light--1600.png` | /how-to/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 25 | `hardening--how-to--light--640-zoom200.png` | /how-to/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 26 | `hardening--how-to--dark--320.png` | /how-to/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 27 | `hardening--how-to--dark--768.png` | /how-to/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 28 | `hardening--how-to--dark--1280.png` | /how-to/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 29 | `hardening--how-to--dark--1600.png` | /how-to/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 30 | `hardening--how-to--dark--640-zoom200.png` | /how-to/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 31 | `hardening--reference--light--320.png` | /reference/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 32 | `hardening--reference--light--768.png` | /reference/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 33 | `hardening--reference--light--1280.png` | /reference/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 34 | `hardening--reference--light--1600.png` | /reference/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 35 | `hardening--reference--light--640-zoom200.png` | /reference/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 36 | `hardening--reference--dark--320.png` | /reference/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 37 | `hardening--reference--dark--768.png` | /reference/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 38 | `hardening--reference--dark--1280.png` | /reference/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 39 | `hardening--reference--dark--1600.png` | /reference/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 40 | `hardening--reference--dark--640-zoom200.png` | /reference/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 41 | `hardening--explanation--light--320.png` | /explanation/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 42 | `hardening--explanation--light--768.png` | /explanation/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 43 | `hardening--explanation--light--1280.png` | /explanation/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 44 | `hardening--explanation--light--1600.png` | /explanation/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 45 | `hardening--explanation--light--640-zoom200.png` | /explanation/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 46 | `hardening--explanation--dark--320.png` | /explanation/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 47 | `hardening--explanation--dark--768.png` | /explanation/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 48 | `hardening--explanation--dark--1280.png` | /explanation/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 49 | `hardening--explanation--dark--1600.png` | /explanation/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 50 | `hardening--explanation--dark--640-zoom200.png` | /explanation/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 51 | `hardening--reference-configuration--light--320.png` | /reference/configuration/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 52 | `hardening--reference-configuration--light--768.png` | /reference/configuration/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 53 | `hardening--reference-configuration--light--1280.png` | /reference/configuration/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 54 | `hardening--reference-configuration--light--1600.png` | /reference/configuration/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 55 | `hardening--reference-configuration--light--640-zoom200.png` | /reference/configuration/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 56 | `hardening--reference-configuration--dark--320.png` | /reference/configuration/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 57 | `hardening--reference-configuration--dark--768.png` | /reference/configuration/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 58 | `hardening--reference-configuration--dark--1280.png` | /reference/configuration/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 59 | `hardening--reference-configuration--dark--1600.png` | /reference/configuration/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 60 | `hardening--reference-configuration--dark--640-zoom200.png` | /reference/configuration/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 61 | `hardening--reference-configuration-workflow-and-ci--light--320.png` | /reference/configuration/workflow-and-ci/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 62 | `hardening--reference-configuration-workflow-and-ci--light--768.png` | /reference/configuration/workflow-and-ci/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 63 | `hardening--reference-configuration-workflow-and-ci--light--1280.png` | /reference/configuration/workflow-and-ci/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 64 | `hardening--reference-configuration-workflow-and-ci--light--1600.png` | /reference/configuration/workflow-and-ci/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 65 | `hardening--reference-configuration-workflow-and-ci--light--640-zoom200.png` | /reference/configuration/workflow-and-ci/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 66 | `hardening--reference-configuration-workflow-and-ci--dark--320.png` | /reference/configuration/workflow-and-ci/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 67 | `hardening--reference-configuration-workflow-and-ci--dark--768.png` | /reference/configuration/workflow-and-ci/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 68 | `hardening--reference-configuration-workflow-and-ci--dark--1280.png` | /reference/configuration/workflow-and-ci/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 69 | `hardening--reference-configuration-workflow-and-ci--dark--1600.png` | /reference/configuration/workflow-and-ci/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 70 | `hardening--reference-configuration-workflow-and-ci--dark--640-zoom200.png` | /reference/configuration/workflow-and-ci/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 71 | `hardening--tutorials-get-started--light--320.png` | /tutorials/get-started/ | light | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 72 | `hardening--tutorials-get-started--light--768.png` | /tutorials/get-started/ | light | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 73 | `hardening--tutorials-get-started--light--1280.png` | /tutorials/get-started/ | light | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 74 | `hardening--tutorials-get-started--light--1600.png` | /tutorials/get-started/ | light | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 75 | `hardening--tutorials-get-started--light--640-zoom200.png` | /tutorials/get-started/ | light | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 76 | `hardening--tutorials-get-started--dark--320.png` | /tutorials/get-started/ | dark | 320 | **PASS** | route/theme/fonts/images; overflow=0px |
| 77 | `hardening--tutorials-get-started--dark--768.png` | /tutorials/get-started/ | dark | 768 | **PASS** | route/theme/fonts/images; overflow=0px |
| 78 | `hardening--tutorials-get-started--dark--1280.png` | /tutorials/get-started/ | dark | 1280 | **PASS** | route/theme/fonts/images; overflow=0px |
| 79 | `hardening--tutorials-get-started--dark--1600.png` | /tutorials/get-started/ | dark | 1600 | **PASS** | route/theme/fonts/images; overflow=0px |
| 80 | `hardening--tutorials-get-started--dark--640-zoom200.png` | /tutorials/get-started/ | dark | 640-zoom200 | **PASS** | route/theme/fonts/images; overflow=0px |
| 81 | `hardening--band2-expanded--light--320.png` | band 2 — all three disclosures expanded | light | 320 | **PASS** | 3/3 native disclosures open |
| 82 | `hardening--band2-expanded--light--1280.png` | band 2 — all three disclosures expanded | light | 1280 | **PASS** | 3/3 native disclosures open |
| 83 | `hardening--band2-expanded--dark--320.png` | band 2 — all three disclosures expanded | dark | 320 | **PASS** | 3/3 native disclosures open |
| 84 | `hardening--band2-expanded--dark--1280.png` | band 2 — all three disclosures expanded | dark | 1280 | **PASS** | 3/3 native disclosures open |
| 85 | `hardening--band2-nojs--light--1280.png` | band 2 — scripts disabled | light | 1280 | **PASS** | DOM assertion: 3/3 disclosures carry open |
| 86 | `hardening--band2-nojs--dark--1280.png` | band 2 — scripts disabled | dark | 1280 | **PASS** | DOM assertion: 3/3 disclosures carry open |
| 87 | `hardening--band2-print--light--1280.png` | band 2 — print media | light | 1280 | **PASS** | 3/3 disclosures open; manual beforeprint dispatch after media emulation |
| 88 | `hardening--band2-tooltip-focus--light--1280.png` | band 2 — keyboard-focused plan tooltip | light | 1280 | **PASS** | Tab focus; tooltip visible; focus ring captured |
| 89 | `hardening--band2-tooltip-focus--dark--1280.png` | band 2 — keyboard-focused plan tooltip | dark | 1280 | **PASS** | Tab focus; tooltip visible; focus ring captured |
| 90 | `hardening--band2-reduced-motion--light--1280.png` | full home — reduced motion | light | 1280 | **PASS** | prefers-reduced-motion: reduce emulated |
| 91 | `hardening--band2-reduced-motion--dark--1280.png` | full home — reduced motion | dark | 1280 | **PASS** | prefers-reduced-motion: reduce emulated |

## Diagram hardening passes

### No-JS and print

With scripts disabled before navigation, the captured DOM had all three
`[data-core-flow-disclosure]` elements carrying `open` in both themes; rows 85–86 show the
content-complete unenhanced state. Under print-media emulation Chrome did not fire the event, so
the harness dispatched `beforeprint` explicitly, reasserted 3/3 open, and captured row 87. That is
the planned fallback rather than a product deviation.

Hover/tap tooltip paths and print-state restoration were not re-scripted as new acceptance passes.
They remain covered by `core-flow-controller.test.mjs` and the built-site core-flow checks, both
rerun by `docs-check`.

### Keyboard-only transcript

The pass was driven only through CDP `Input.dispatchKeyEvent`: no DOM click or programmatic focus
was used. Focus reached both hero actions, all nine tooltip buttons, and all three summaries in
source order; each focus tooltip appeared; Enter/Space independently toggled disclosures; Escape
proved the dismissal latch; and the 12-stop reverse walk exited the figure.

```text
Keyboard-only hardening pass
Driver: CDP Input.dispatchKeyEvent only (Tab, Shift-Tab, Enter, Space, Escape)

Tab 5: hero-action — Get started
Tab 6: hero-action — Understand the workflow
Tab 8: tooltip-trigger — ○ plan — tooltip visible
Escape: plan tooltip dismissed; focus remained on the plan trigger; latch held
Shift-Tab → Section titled “The workflow”; Tab → plan: focus intent dropped/re-established and tooltip reappeared
Tab 9: tooltip-trigger — ○ save — tooltip visible
Tab 10: tooltip-trigger — ▸ implement (current) — tooltip visible
Tab 11: tooltip-trigger — ○ submit — tooltip visible
Tab 12: tooltip-trigger — ◇ address — tooltip visible
Tab 13: tooltip-trigger — ○ land — tooltip visible
Tab 14: tooltip-trigger — ○ learn — tooltip visible
Tab 15: summary — gist authoring problem statements — plan → save
Enter: summary 1 opened and closed independently; peers stayed unchanged
Tab 16: summary — objective authoring plans of plans — plan → save
Space: summary 2 opened and closed independently; peers stayed unchanged
Tab 17: summary — docs/learned the durable learned-docs cache
Enter: summary 3 opened and closed independently; peers stayed unchanged
Space: summary 3 reopened so its two cache tooltip buttons entered the Tab order
Tab 18: tooltip-trigger — ↻ harvest → objective authoring — tooltip visible
Tab 19: tooltip-trigger — ↻ dreaming — corpus self-curation — tooltip visible

Counts: 2 hero actions; 9 tooltip buttons; 3 summaries; relevant controls reached in source order (0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13).
Shift-Tab reverse walk: left the figure after 12 stops at “Section titled “The workflow””; no focus trap.
Verdict: PASS
```

### Reduced-motion probe

The reduced-motion screenshots are full-home captures in both themes (rows 90–91). The computed
probe also visited the tutorials landing so all three §12 transition-consumer classes were
measured.

```text
Reduced-motion computed-style probe
Emulation: prefers-reduced-motion: reduce
Threshold: every transition-duration <= 0.1ms

/  .perk-band .sl-link-card  count=4  duration=1e-05s  max=0.01ms  PASS
/  .hero .sl-link-button  count=2  duration=1e-05s  max=0.01ms  PASS
/tutorials/  .perk-recommended li  count=2  duration=1e-05s  max=0.01ms  PASS

Verdict: PASS
```

## Contrast recomputation

The disposable script uses WCAG sRGB relative-luminance linearization and the 4.5:1 normal-text
threshold. It resolves the live theme tokens from `tokens.css`, the two live inline-code
backgrounds from `system.css`, and the fresh emitted code palette from every
`docs/site/dist/**/index.html` after `just docs-build`.

### §9 core and inline-code pairs

```text
theme  pair                  fg       bg       ratio  AA
-----  --------------------  -------  -------  -----  ----
light  text/canvas           #18201d  #f7f7f2  15.47  PASS
light  text/surface          #18201d  #ffffff  16.62  PASS
light  muted/canvas          #5f6b66  #f7f7f2  5.17   PASS
light  muted/surface         #5f6b66  #ffffff  5.55   PASS
light  accent/canvas         #126e5a  #f7f7f2  5.74   PASS
light  accent/surface        #126e5a  #ffffff  6.17   PASS
light  accent-strong/canvas  #0a5646  #f7f7f2  8.03   PASS
light  accent-invert/accent  #ffffff  #126e5a  6.17   PASS
light  success/canvas        #176b4d  #f7f7f2  6.02   PASS
light  success/success-low   #176b4d  #e4f3ec  5.65   PASS
light  warning/canvas        #76520a  #f7f7f2  6.55   PASS
light  warning/warning-low   #76520a  #f8ebcb  5.95   PASS
light  danger/canvas         #a33a3a  #f7f7f2  6.06   PASS
light  danger/danger-low     #a33a3a  #fbe8e8  5.52   PASS
dark   text/canvas           #f1f5f0  #101512  16.75  PASS
dark   text/surface          #f1f5f0  #171d19  15.54  PASS
dark   muted/canvas          #aab6af  #101512  8.80   PASS
dark   muted/surface         #aab6af  #171d19  8.17   PASS
dark   accent/canvas         #63d5b0  #101512  10.26  PASS
dark   accent/surface        #63d5b0  #171d19  9.52   PASS
dark   accent-strong/canvas  #8be4c4  #101512  12.30  PASS
dark   accent-invert/accent  #101512  #63d5b0  10.26  PASS
dark   success/canvas        #70d7ad  #101512  10.56  PASS
dark   success/success-low   #70d7ad  #173128  7.97   PASS
dark   warning/canvas        #e8c36a  #101512  10.94  PASS
dark   warning/warning-low   #e8c36a  #342b17  8.28   PASS
dark   danger/canvas         #ff9a9a  #101512  9.09   PASS
dark   danger/danger-low     #ff9a9a  #3b1e1e  7.44   PASS
light  text/inline-code      #18201d  #ecefe9  14.32  PASS
dark   text/inline-code      #f1f5f0  #233029  12.49  PASS

Verdict: PASS (30/30 pairs at or above 4.5:1; the 28 recorded rows also agree to 2 decimals)
```

### §12 hero-wash pairs

```text
theme  pair                     fg       bg       ratio  AA
-----  -----------------------  -------  -------  -----  ----
light  text/accent-low          #18201d  #d9efe7  13.81  PASS
light  muted/accent-low         #5f6b66  #d9efe7  4.61   PASS
light  accent/accent-low        #126e5a  #d9efe7  5.13   PASS
light  text-invert/accent-high  #ffffff  #0a5646  8.63   PASS
dark   text/accent-low          #f1f5f0  #17382e  11.61  PASS
dark   muted/accent-low         #aab6af  #17382e  6.10   PASS
dark   accent/accent-low        #63d5b0  #17382e  7.11   PASS
dark   text-invert/accent-high  #101512  #8be4c4  12.30  PASS

Verdict: PASS (8/8 live pairs agree with §12 to 2 decimals)
```

### §11 emitted code palette and membership reconciliation

```text
theme  foreground  background  ratio  AA    §11
-----  ----------  ----------  -----  ----  -----
dark   #7fdbca     #171d19     10.51  PASS  MATCH
dark   #82aaff     #171d19     7.46   PASS  MATCH
dark   #919f9f     #171d19     6.25   PASS  MATCH
dark   #c5e478     #171d19     12.02  PASS  MATCH
dark   #c789d6     #171d19     6.51   PASS  MATCH
dark   #c792ea     #171d19     7.12   PASS  MATCH
dark   #d6deeb     #171d19     12.65  PASS  MATCH
dark   #d9f5dd     #171d19     14.72  PASS  MATCH
dark   #ecc48d     #171d19     10.48  PASS  MATCH
dark   #f78c6c     #171d19     7.28   PASS  MATCH
dark   #ff6a83     #171d19     6.23   PASS  MATCH
light  #096e72     #ffffff     6.03   PASS  MATCH
light  #111111     #ffffff     18.88  PASS  MATCH
light  #3b61b0     #ffffff     5.96   PASS  MATCH
light  #403f53     #ffffff     10.22  PASS  MATCH
light  #5f636f     #ffffff     6.00   PASS  MATCH
light  #7c5686     #ffffff     5.95   PASS  MATCH
light  #8844ae     #ffffff     6.03   PASS  MATCH
light  #984e4d     #ffffff     5.95   PASS  MATCH
light  #a24848     #ffffff     5.90   PASS  MATCH
light  #aa0982     #ffffff     6.84   PASS  MATCH

Membership reconciliation (fresh docs/site/dist/**/index.html)
occurrences: recorded dated run=1109; fresh=1109; delta=0
dark colors: recorded=11; fresh=11; added=∅; removed=∅
light colors: recorded=10; fresh=10; added=∅; removed=∅
membership verdict: PASS
contrast/table verdict: PASS
```

No §11 membership delta occurred, so the dated blueprint table remains current and no blueprint
amendment was required.

## Blueprint↔artifact agreement

| Blueprint section | Binding claim class | Verification method and artifact anchors | Dated verdict |
|---|---|---|---|
| §1 Binding scope | Themes/tokens/type/compositions/diagrams/responsiveness/override budget are settled input; IA, routes, content, deployment, and cross-plane behavior stay out of this change. | Diff-scope audit found no tracked `docs/site/`, `docs/user-docs/`, command/config/provider/backend, or `shared/` change. The only planned merged artifacts are this evidence record and its `docs/index.md` row. | **PASS — 2026-08-19** |
| §2 Final design tokens | Both palettes, semantic/status colors, ramps, spacing, shape, measure, focus, and low shadow remain value-exact and contrast-safe. | `tests/test_docs_site_tokens.py::test_tokens_css_matches_blueprint`; `tests/test_docs_site_system.py::test_live_tokens_meet_wcag_contrast`; fresh 30-pair recomputation above; rendered light/dark sweep. | **PASS — 2026-08-19** |
| §3 Typography and font decision | Exact Inter Variable/IBM Plex Mono pins and imports; type scale, line heights, mono/UI roles, and 72ch/92ch posture. | Manual pin check against `docs/site/package.json` (`5.3.0` both) and the ordered Fontsource `customCss` in `docs/site/astro.config.mjs`; `test_astro_config_wires_blueprint_custom_css`; `test_system_css_applies_the_type_scale_with_consumers`; rendered local fonts at every width. | **PASS — 2026-08-19** |
| §4 Compositions | Six-band home, quadrant router, configuration hub+dense child, narrow linearization, table/code containment, and realized §12 finish. | Manual review of the complete 80-shot base matrix; `built-site.test.mjs` home/landing/Expressive-Code contracts; `test_system_css_applies_measure_focus_motion_and_containment`; `test_system_css_eyebrows_and_wide_mode_enumerate_the_settled_routes`. | **PASS — 2026-08-19** |
| §5 Diagram legend and contracts | Shared non-color vocabulary, static-SVG naming/equivalents, semantic-HTML core flow, source-open disclosures, container-keyed layout, supplementary tooltips, and keyboard/print/no-JS behavior. | `test_diagram_components_hold_the_label_floor_by_construction`; `test_core_flow_component_holds_the_interactive_source_contract`; `built-site.test.mjs` static parity/core-flow contracts; manual source review of all five `*Diagram.astro` components and `core-flow-controller.mjs`; 11 diagram shots and keyboard transcript. | **PASS — 2026-08-19** |
| §6 Responsive behavior | 320/768/1280/1600 and 640-CSS-px zoom-200 behavior, source order, contained overflow, native shell, visible focus, and effectively-zero reduced motion. | Every base row reports 0px page overflow; all 80 full-page shots were reviewed; keyboard pass proves source order/no trap; computed probe reports 0.01ms for every §12 transition consumer; `test_system_css_applies_measure_focus_motion_and_containment`. | **PASS — 2026-08-19** |
| §7 Component-override budget | Baseline and committed set remain empty under the absolute cap of three. | Manual configuration audit: `docs/site/astro.config.mjs` has no `components` key; all finish remains `customCss` or content components. | **PASS — 2026-08-19** |
| §8 Route-detail reconciliation | No route/IA change; external-corpus MDX retains the exact Starlight-components alias. | All eight routes loaded at every matrix width/theme; `astro.config.mjs` still carries the regex exact-match Vite alias; `built-site.test.mjs` complete-corpus/sidebar/internal-href checks passed. | **PASS — 2026-08-19** |
| §9 Scaffold verification evidence | WCAG method, token evidence, local font/toolchain identity, both themes, width/overflow checks, and no external runtime dependency remain reproducible. | Fresh build; environment table above; 30-pair table; 80-shot base matrix; `a11y.test.mjs`; `built-site.test.mjs` external-origin sweep. | **PASS — 2026-08-19** |
| §10 Simulations and disposal | Disposable machinery/evidence must not become a second source tree or survive in the merged artifact. | Hardening scripts/binaries are isolated under the PR-only evidence directory, with no canonical prose copy; the immutable evidence commit is linked from the durable comment and the directory is removed in the final pre-merge commit. | **PASS — delivery protocol completed before merge** |
| §11 Article-page/shell finish | U1–U9 remain value-exact; emitted syntax colors remain AA and set-equal to the dated evidence membership. | `test_system_css_applies_article_shell_finish`; fresh 1,109 occurrences, 11 dark/10 light colors, no added/removed colors, 21/21 AA and §11 matches; article/hub/dense-child shots. | **PASS — 2026-08-19** |
| §12 Home/landing finish | U10–U19 remain value-exact; hero wash stays AA; card/action transitions collapse under reduced motion. | `test_home_landing_finish_applies_the_section_12_table`; `test_hero_wash_contrast_evidence`; fresh 8/8 table; home/landing shots; reduced-motion probe. | **PASS — 2026-08-19** |

## Defect and rerun log

| ID | Surface | Finding | Resolution and disposition | Re-capture/rerun |
|---|---|---|---|---|
| E1 | Disposable keyboard driver | The first incomplete harness run used `rawKeyDown` without text, which did not activate the first focused `<summary>` in Chrome. No keyboard evidence was accepted from that run. | Changed the disposable driver to CDP `keyDown`/`keyUp` with Enter/Space text while retaining CDP-only input. This is evidence machinery, not a site defect; no blueprint amendment. | Full capture rerun; final transcript passes all three independent summary toggles. |
| E2 | Keyboard no-trap assertion | The next harness revision reached every required control but an early `continue` let the loop Tab beyond the last cache trigger, making the first reverse-walk report vacuous (`0` stops). | Corrected the harness to stop on the last required trigger while focus was still in the figure. This is evidence machinery, not a site defect; no blueprint amendment. | Full capture rerun; final Shift-Tab walk leaves the figure after 12 stops. |
| E3 | Screenshot viewport/framing | Initial PNGs excluded the 15px classic scrollbar gutter (a requested 320 viewport produced a 305px image), and the keyboard-tooltip crop used only the band box, clipping the tooltip's overflow. | Hid headless scrollbars so the emulated CSS viewport and PNG width agree; added a 12px band pad and unioned the visible tooltip box into its crop. This is evidence machinery, not a site defect; no blueprint amendment. | Full 91-shot matrix re-captured after the fix; final PNG widths match 320/768/1280/1600/640 and the tooltip is complete. |
| P1 | Finished docs site | The rendered, interaction, contrast, and blueprint-agreement sweeps found no product artifact disagreement. The fresh emitted palette remained 1,109 occurrences with the same 11 dark and 10 light colors. | No in-envelope CSS/component change, blueprint amendment, or wider-defect disposition was required. | Final 91/91 capture, 30/30 core+inline pairs, 8/8 hero-wash pairs, 21/21 emitted palette rows, and configured `docs-check` all pass. |
