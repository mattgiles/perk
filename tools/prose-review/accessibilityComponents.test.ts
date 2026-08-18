// The keyboard & accessibility contract over the rendered components (the contract
// tables live in docs/design/prose-review-stack.md): F6 pane cycling, tree arrow
// navigation, search panel keys, drawer focus policy, the review-gated Mod+S save,
// Compare change traversal, and the never-suppress-outline source-scan guard.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as React from "react";
import { tsImport } from "tsx/esm/api";
import {
  buttonByLabel,
  buttonByText,
  buttonStartingWith,
  installDom,
  itemAt,
  normalizedText,
  type RenderHarness,
  response,
  stubFetch,
} from "./componentHarness.ts";
import type {
  ComparisonChoice,
  ComparisonOptions,
  ComparisonPlacement,
  SelectedComparison,
} from "./src/comparison.ts";
import type { ComparisonLoadState } from "./src/comparisonLoad.ts";
import { EditWorkspace } from "./src/editWorkspace.ts";
import type { SourceTarget, UnitSelection } from "./src/selection.ts";
import type { SourceView, UnitSource } from "./src/source.ts";
import type { CapabilityTree, SessionShape, TreeUnit, UnitRef } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");
const { CenterPane, WorkspaceProvider } = (await tsImport(
  "./src/CenterPane.tsx",
  import.meta.url,
)) as typeof import("./src/CenterPane.tsx");

const WORKSPACE = path.dirname(fileURLToPath(import.meta.url));
const HASH = "0123456789abcdef".repeat(4);

const UNIT_A: TreeUnit = {
  id: "unit:a",
  kind: "markdown",
  path: "a.md",
  fragments: [{ id: "body", label: "Body" }],
};
const UNIT_B: UnitRef = { id: "unit:b", kind: "markdown", path: "b.md" };
const WARM: SessionShape = {
  id: "shape:warm",
  label: "Warm shape",
  delivery: "warm",
  assembly: "test-assembly",
  layers: [
    { position: 1, optional: false, label: "System boundary", unit: null, boundary: "pi-system" },
    { position: 2, optional: false, label: "Warm layer", unit: UNIT_A, boundary: null },
  ],
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "planning",
      label: "Planning",
      units: [UNIT_A],
      session_shapes: [WARM],
      children: [],
    },
  ],
};

function wholeUnitSource(unit: UnitRef, focus: string): UnitSource {
  return {
    file: { path: unit.path, mode: 0o644, newline_style: "lf", load_hash: HASH },
    view: {
      unit: unit.id,
      fragment: null,
      kind: unit.kind,
      before: "",
      focus,
      after: "",
      editable: false,
      read_only_reason: "whole-unit",
    },
  };
}

function editableView(target: SourceTarget, text: string, focus: string): SourceView {
  assert.ok(target.fragment !== null);
  const start = text.indexOf(focus);
  assert.notEqual(start, -1);
  return {
    unit: target.unit.id,
    fragment: target.fragment,
    kind: target.unit.kind,
    before: text.slice(0, start),
    focus,
    after: text.slice(start + focus.length),
    editable: true,
    read_only_reason: null,
  };
}

function load(target: SourceTarget, text: string, view: SourceView): UnitSource {
  assert.equal(view.before + view.focus + view.after, text);
  return {
    file: { path: target.unit.path, mode: 0o644, newline_style: "lf", load_hash: HASH },
    view,
  };
}

function activeElement(harness: RenderHarness): Element | null {
  return harness.window.document.activeElement;
}

function paneByClass(harness: RenderHarness, selector: string): HTMLElement {
  const pane = harness.container.querySelector<HTMLElement>(selector);
  assert.ok(pane !== null, `missing pane: ${selector}`);
  return pane;
}

/** The read-only App fixture: catalog tree, 404 inspector, whole-unit sources. */
function readOnlyRoutes(url: string): Response {
  if (url === "/api/catalog/tree") {
    return response(200, TREE);
  }
  if (url === "/api/git/status") {
    return response(500, {});
  }
  if (url.startsWith("/api/inspect?")) {
    return response(404, { detail: "unknown unit" });
  }
  if (url.startsWith("/api/source?")) {
    return response(200, wholeUnitSource(UNIT_A, "same\n"));
  }
  if (url.startsWith("/api/compare?")) {
    return response(404, { detail: "unknown comparison subject" });
  }
  throw new Error(`unexpected request: ${url}`);
}

test("F6 cycles pane focus with wrap, reverse, and the drawer only while open", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => readOnlyRoutes(url));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const body = harness.window.document.body;
    const header = paneByClass(harness, "header.app-header");
    const tree = paneByClass(harness, "nav.tree-pane");
    const center = paneByClass(harness, "main.center-pane");
    const inspector = paneByClass(harness, "aside.inspector-pane");

    const first = await harness.keydown(body, "F6");
    assert.equal(first.defaultPrevented, true, "F6 must suppress browser chrome cycling");
    assert.equal(activeElement(harness), header, "outside-focus F6 enters the first pane");
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), tree);
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), center);
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), inspector);
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), header, "closed-drawer cycle wraps past the inspector");

    await harness.keydown(body, "F6", { shiftKey: true });
    assert.equal(activeElement(harness), inspector, "Shift+F6 reverses with wrap");
    await harness.keydown(body, "F6", { shiftKey: true });
    assert.equal(activeElement(harness), center);

    await harness.click(buttonByText(harness.container, "Workspace (0)"));
    const drawer = paneByClass(harness, "section.workspace-drawer");
    inspector.focus();
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), drawer, "the open drawer joins the cycle");
    await harness.keydown(body, "F6");
    assert.equal(activeElement(harness), header);
    await harness.keydown(body, "F6", { shiftKey: true });
    assert.equal(activeElement(harness), drawer);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("tree arrow keys move focus between visible tree buttons with clamping", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => readOnlyRoutes(url));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const tree = paneByClass(harness, "nav.tree-pane");
    const buttons = [...tree.querySelectorAll("button")];
    assert.equal(buttons.length, 5, "capability toggle, shape toggle+entry, unit toggle+entry");

    tree.focus();
    await harness.keydown(tree, "ArrowDown");
    assert.equal(activeElement(harness), buttons[0], "container-focused ArrowDown enters first");
    await harness.keydown(itemAt(buttons, 0), "ArrowDown");
    assert.equal(activeElement(harness), buttons[1]);
    await harness.keydown(itemAt(buttons, 1), "End");
    assert.equal(activeElement(harness), buttons[4]);
    const clamped = await harness.keydown(itemAt(buttons, 4), "ArrowDown");
    assert.equal(activeElement(harness), buttons[4], "ArrowDown clamps at the last button");
    assert.equal(clamped.defaultPrevented, true, "clamped arrows never scroll the pane");
    await harness.keydown(itemAt(buttons, 4), "Home");
    assert.equal(activeElement(harness), buttons[0]);
    await harness.keydown(itemAt(buttons, 0), "ArrowUp");
    assert.equal(activeElement(harness), buttons[0], "ArrowUp clamps at the first button");
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("the selected tree entry carries aria-current and yields it on reselection", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => readOnlyRoutes(url));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const unitEntry = buttonByText(harness.container, "unit:a");
    const shapeEntry = buttonByText(harness.container, "Warm shape warm");
    assert.equal(unitEntry.getAttribute("aria-current"), null);

    await harness.click(unitEntry);
    assert.equal(unitEntry.getAttribute("aria-current"), "true");
    assert.equal(shapeEntry.getAttribute("aria-current"), null);

    await harness.click(shapeEntry);
    assert.equal(unitEntry.getAttribute("aria-current"), null, "reselection clears the old entry");
    assert.equal(shapeEntry.getAttribute("aria-current"), "true");

    // Boundary entries carry the same current marker.
    await harness.click(buttonByLabel(harness.container, "Expand layers for Warm shape"));
    const boundaryEntry = buttonStartingWith(harness.container, "System boundary");
    assert.equal(boundaryEntry.getAttribute("aria-current"), null);
    await harness.click(boundaryEntry);
    assert.equal(boundaryEntry.getAttribute("aria-current"), "true");
    assert.equal(shapeEntry.getAttribute("aria-current"), null);
    await harness.click(unitEntry);
    assert.equal(boundaryEntry.getAttribute("aria-current"), null, "the boundary yields too");
    assert.equal(unitEntry.getAttribute("aria-current"), "true");
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("search keys: ArrowDown enters results, ArrowUp returns, Esc closes and refocuses", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => {
    if (url.startsWith("/api/search?")) {
      return response(200, {
        total: 2,
        results: [UNIT_A, UNIT_B].map((unit) => ({
          kind: "unit",
          id: unit.id,
          label: unit.id,
          breadcrumb: [{ id: "planning", label: "Planning" }],
          unit: { id: unit.id, kind: unit.kind, path: unit.path },
          matched: ["unit-id"],
        })),
      });
    }
    return readOnlyRoutes(url);
  });
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const input = harness.container.querySelector<HTMLInputElement>("input.search-input");
    assert.ok(input !== null);

    input.focus();
    await harness.keydown(input, "ArrowDown");
    assert.equal(activeElement(harness), input, "a closed panel leaves ArrowDown alone");

    await harness.input(input, "unit");
    await harness.settle();
    const results = [
      ...harness.container.querySelectorAll<HTMLElement>(".search-panel button.search-result"),
    ];
    assert.equal(results.length, 2);

    // Modified and composing arrows keep their native behavior (text selection,
    // IME candidate navigation) — never claimed for result navigation.
    const shifted = await harness.keydown(input, "ArrowDown", { shiftKey: true });
    assert.equal(shifted.defaultPrevented, false, "Shift+ArrowDown stays native");
    assert.equal(activeElement(harness), input);
    const composing = await harness.keydown(input, "ArrowDown", { isComposing: true });
    assert.equal(composing.defaultPrevented, false, "composing ArrowDown stays native");
    assert.equal(activeElement(harness), input);

    await harness.keydown(input, "ArrowDown");
    assert.equal(activeElement(harness), results[0], "ArrowDown enters the first result");
    await harness.keydown(itemAt(results, 0), "ArrowDown");
    assert.equal(activeElement(harness), results[1]);
    await harness.keydown(itemAt(results, 1), "ArrowDown");
    assert.equal(activeElement(harness), results[1], "clamped at the last result");
    await harness.keydown(itemAt(results, 1), "ArrowUp");
    assert.equal(activeElement(harness), results[0]);
    await harness.keydown(itemAt(results, 0), "ArrowUp");
    assert.equal(activeElement(harness), input, "ArrowUp from the first result returns");

    await harness.keydown(input, "ArrowDown");
    const escapeEvent = await harness.keydown(itemAt(results, 0), "Escape");
    assert.equal(escapeEvent.defaultPrevented, true);
    assert.equal(harness.container.querySelector(".search-panel"), null, "Esc closes the panel");
    assert.equal(activeElement(harness), input, "focus returns to the search input");
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("drawer Esc closes the drawer and returns focus to the Workspace button", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => readOnlyRoutes(url));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const workspaceButton = buttonByText(harness.container, "Workspace (0)");
    await harness.click(workspaceButton);
    const drawer = paneByClass(harness, "section.workspace-drawer");
    drawer.focus();
    const escapeEvent = await harness.keydown(drawer, "Escape");
    assert.equal(escapeEvent.defaultPrevented, true);
    assert.equal(harness.container.querySelector(".workspace-drawer"), null);
    assert.equal(activeElement(harness), workspaceButton);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

/** The editable App fixture: CSRF-tagged DOM plus project/save routes for unit:a. */
function editableRoutes(saveBodies: string[]): (url: string, init?: RequestInit) => Response {
  const text = "before A after";
  return (url, init) => {
    if (url.startsWith("/api/source?")) {
      const fragment = new URL(url, "http://127.0.0.1").searchParams.get("fragment");
      const target: SourceTarget = {
        unit: UNIT_A,
        fragment: fragment === "body" ? (UNIT_A.fragments[0] ?? null) : null,
      };
      return response(200, load(target, text, editableView(target, text, "A")));
    }
    if (url === "/api/source/project") {
      const body = JSON.parse(String(init?.body)) as { fragment: string | null; text: string };
      const target: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[0] ?? null };
      return response(200, editableView(target, body.text, "saved A"));
    }
    if (url === "/api/source/save") {
      const body = JSON.parse(String(init?.body)) as { text: string };
      saveBodies.push(body.text);
      return response(200, {
        status: "saved",
        source: {
          unit: UNIT_A.id,
          kind: UNIT_A.kind,
          file: { path: UNIT_A.path, mode: 0o644, newline_style: "lf", load_hash: "a".repeat(64) },
        },
        materialized: [],
        checks: [],
        catalog_refreshed: true,
        refresh_detail: null,
      });
    }
    return readOnlyRoutes(url);
  };
}

test("Mod+S review-gates the save: review first, save second, no-op otherwise", async () => {
  const harness = installDom({ csrfToken: "test-token" });
  const saveBodies: string[] = [];
  const restoreFetch = stubFetch(editableRoutes(saveBodies));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    const body = harness.window.document.body;

    // No reviewable source: suppressed browser default, no action.
    const idle = await harness.keydown(body, "s", { ctrlKey: true });
    assert.equal(idle.defaultPrevented, true, "the save-page dialog is suppressed app-wide");
    assert.equal(harness.container.querySelector(".save-review"), null);

    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Body"));
    await harness.settle();
    const textarea = harness.container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(textarea !== null);
    await harness.input(textarea, "saved A");

    // Alt-modified chords stay unclaimed.
    const alted = await harness.keydown(body, "s", { ctrlKey: true, altKey: true });
    assert.equal(alted.defaultPrevented, false);
    assert.equal(harness.container.querySelector(".save-review"), null);

    // A held chord's auto-repeat never acts — the review gate needs distinct presses.
    await harness.keydown(body, "s", { ctrlKey: true, repeat: true });
    assert.equal(harness.container.querySelector(".save-review"), null);

    // First press: opens the full-file save review (the beginSaveReview arm).
    const first = await harness.keydown(body, "s", { ctrlKey: true });
    assert.equal(first.defaultPrevented, true);
    assert.ok(harness.container.querySelector(".save-review") !== null);
    assert.equal(saveBodies.length, 0, "the first press never skips the review gate");

    // Second press (the Cmd spelling): posts the reviewed save.
    const second = await harness.keydown(body, "s", { metaKey: true });
    assert.equal(second.defaultPrevented, true);
    await harness.settle();
    await harness.settle();
    assert.deepEqual(saveBodies, ["before saved A after"]);
    assert.match(harness.container.textContent ?? "", /Saved/);

    // A clean (non-dirty) source is not reviewable: Mod+S is a no-op again.
    await harness.keydown(body, "s", { ctrlKey: true });
    assert.equal(harness.container.querySelector(".save-review"), null);
    assert.equal(saveBodies.length, 1);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("the drawer Open action moves focus to the center pane container", async () => {
  const harness = installDom({ csrfToken: "test-token" });
  const restoreFetch = stubFetch(editableRoutes([]));
  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Body"));
    await harness.settle();
    const textarea = harness.container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(textarea !== null);
    await harness.input(textarea, "edited A");
    await harness.settle();

    await harness.click(buttonByText(harness.container, "Workspace (1)"));
    const drawer = paneByClass(harness, "section.workspace-drawer");
    await harness.click(buttonByText(drawer, "Open"));
    assert.equal(harness.container.querySelector(".workspace-drawer"), null);
    assert.equal(
      activeElement(harness),
      paneByClass(harness, "main.center-pane"),
      "focus lands on the center pane, never an unmounted drawer node",
    );
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

// ── Compare change traversal ─────────────────────────────────────────────────

function comparisonPlacement(unit: UnitRef): ComparisonPlacement {
  return {
    provenance: "canonical",
    unit,
    breadcrumb: [{ id: "planning", label: "Planning" }],
    shape: null,
    assembly: null,
    position: null,
    label: unit.id,
  };
}

function compareElement(workspace: EditWorkspace, target: UnitRef): React.ReactNode {
  const choice: ComparisonChoice = {
    label: "Target unit",
    detail: "Traversal target",
    target: comparisonPlacement(target),
  };
  const options: ComparisonOptions = {
    origin: comparisonPlacement(UNIT_A),
    groups: [{ relation: "concern-relative", label: "Concern relatives", choices: [choice] }],
  };
  const state: ComparisonLoadState = { status: "loaded", options };
  const selected: SelectedComparison = { relation: "concern-relative", choiceIndex: 0, choice };
  const selection: UnitSelection = {
    type: "unit",
    target: { unit: UNIT_A, fragment: null },
    placement: null,
  };
  return React.createElement(
    WorkspaceProvider,
    { workspace },
    React.createElement(CenterPane, {
      mode: "compare",
      onModeChange: () => undefined,
      selection,
      comparisonState: state,
      selectedComparison: selected,
      assemblyState: { status: "idle" },
      assemblyCallbacks: {
        chooseScenario: () => undefined,
        setOverride: () => undefined,
        rerender: () => undefined,
      },
      checkActive: false,
      onRunCheck: () => undefined,
    }),
  );
}

test("Compare renders del/ins chunks and traverses changes by button and n/p keys", async () => {
  const harness = installDom();
  const sources = new Map([
    [UNIT_A.id, wholeUnitSource(UNIT_A, "same1\nchanged A\nsame2\nend A\n")],
    [UNIT_B.id, wholeUnitSource(UNIT_B, "same1\nchanged B\nsame2\nend B\n")],
  ]);
  const restoreFetch = stubFetch((url) => {
    const unitId = new URL(url, "http://127.0.0.1").searchParams.get("unit");
    const body = unitId === null ? undefined : sources.get(unitId);
    assert.ok(body !== undefined, `unexpected request: ${url}`);
    return response(200, body);
  });
  const workspace = new EditWorkspace();
  try {
    await harness.render(compareElement(workspace, UNIT_B));
    await harness.settle();

    const dels = [...harness.container.querySelectorAll<HTMLElement>("del.comparison-removed")];
    const inss = [...harness.container.querySelectorAll<HTMLElement>("ins.comparison-added")];
    assert.deepEqual(
      dels.map((chunk) => chunk.dataset.changeIndex),
      ["1", "4"],
    );
    assert.deepEqual(
      inss.map((chunk) => chunk.dataset.changeIndex),
      ["2", "5"],
    );
    assert.ok(dels.every((chunk) => chunk.tabIndex === -1));

    // Both comparison panes are keyboard-scrollable, labeled regions.
    const panes = [...harness.container.querySelectorAll<HTMLElement>("section.comparison-pane")];
    assert.deepEqual(
      panes.map((pane) => [pane.tabIndex, pane.getAttribute("aria-label")]),
      [
        [0, "Origin source"],
        [0, "Target source"],
      ],
    );

    const counter = harness.container.querySelector(".comparison-change-counter");
    assert.ok(counter !== null);
    const previous = buttonByText(harness.container, "Previous change");
    const next = buttonByText(harness.container, "Next change");
    assert.equal(normalizedText(counter), "Change 0 of 4");
    assert.equal(previous.disabled, true);
    assert.equal(next.disabled, false);

    await harness.click(next);
    assert.equal(activeElement(harness), dels[0]);
    assert.equal(normalizedText(counter), "Change 1 of 4");
    assert.equal(previous.disabled, true, "the first change clamps Previous");

    await harness.click(next);
    assert.equal(activeElement(harness), inss[0]);
    assert.equal(normalizedText(counter), "Change 2 of 4");
    assert.equal(previous.disabled, false);

    // Unmodified n/p on the comparison result are the same actions.
    await harness.keydown(itemAt(inss, 0), "n");
    assert.equal(activeElement(harness), dels[1]);
    await harness.keydown(itemAt(dels, 1), "n");
    assert.equal(activeElement(harness), inss[1]);
    assert.equal(normalizedText(counter), "Change 4 of 4");
    assert.equal(next.disabled, true, "the last change clamps Next");
    await harness.keydown(itemAt(inss, 1), "n");
    assert.equal(activeElement(harness), inss[1], "n clamps at the last change");
    assert.equal(normalizedText(counter), "Change 4 of 4");
    await harness.keydown(itemAt(inss, 1), "p");
    assert.equal(activeElement(harness), dels[1]);
    assert.equal(normalizedText(counter), "Change 3 of 4");
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("a zero-change comparison disables the traversal controls", async () => {
  const harness = installDom();
  const restoreFetch = stubFetch((url) => {
    assert.ok(url.startsWith("/api/source?"), `unexpected request: ${url}`);
    return response(200, wholeUnitSource(UNIT_A, "same\n"));
  });
  const workspace = new EditWorkspace();
  try {
    await harness.render(compareElement(workspace, UNIT_A));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /No differences in current content/);
    assert.equal(buttonByText(harness.container, "Previous change").disabled, true);
    assert.equal(buttonByText(harness.container, "Next change").disabled, true);
    const counter = harness.container.querySelector(".comparison-change-counter");
    assert.ok(counter !== null);
    assert.equal(normalizedText(counter), "Change 0 of 0");
    assert.equal(harness.container.querySelectorAll("del, ins").length, 0);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

// ── The focus-visibility invariant (source-scan guard) ───────────────────────

test("app.css never suppresses focus outlines", () => {
  const css = readFileSync(path.join(WORKSPACE, "src", "app.css"), "utf-8");
  // Vacuousness self-check: the authored focus rules must be present, so an empty
  // or misrooted read fails loudly instead of passing.
  assert.ok(css.includes(".app-header:focus"), "scan missed the authored focus rules");
  assert.doesNotMatch(css, /outline\s*:\s*(none|0)/);
});
