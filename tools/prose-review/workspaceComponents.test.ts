import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import { JSDOM } from "jsdom";
import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { tsImport } from "tsx/esm/api";
import type {
  ComparisonChoice,
  ComparisonOptions,
  ComparisonPlacement,
  SelectedComparison,
} from "./src/comparison.ts";
import type { ComparisonLoadState } from "./src/comparisonLoad.ts";
import { EditWorkspace, type WorkspaceTransport } from "./src/editWorkspace.ts";
import {
  CATALOG_STALE_DETAIL,
  CLIPBOARD_FAILURE_DETAIL,
  CONFLICT_DETAIL,
  GENERATED_LINEAGE_DETAIL,
  INDETERMINATE_DETAIL,
  NOT_SENT_DETAIL,
  UNRESOLVED_RECONCILIATION_DETAIL,
} from "./src/save.ts";
import type { SourceSaveLoadOutcome } from "./src/saveLoad.ts";
import type { Selection, SourceTarget, UnitSelection } from "./src/selection.ts";
import type { ReadOnlyReason, SourceView, UnitSource } from "./src/source.ts";
import type { SourceLoadOutcome, SourceProjectionOutcome } from "./src/sourceLoad.ts";
import type { CapabilityTree, TreeUnit, UnitRef } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");
const { CenterPane, WorkspaceProvider } = (await tsImport(
  "./src/CenterPane.tsx",
  import.meta.url,
)) as typeof import("./src/CenterPane.tsx");

const HASH = "0123456789abcdef".repeat(4);
const UNIT_A: TreeUnit = {
  id: "unit:a",
  kind: "markdown",
  path: "shared.md",
  fragments: [
    { id: "a", label: "Fragment A" },
    { id: "b", label: "Fragment B" },
  ],
};
const UNIT_ALIAS: TreeUnit = {
  id: "unit:alias",
  kind: "markdown",
  path: "shared.md",
  fragments: [{ id: "alias", label: "Alias fragment" }],
};
const UNIT_PYTHON: TreeUnit = {
  id: "unit:python",
  kind: "python-symbol",
  path: "sample.py",
  fragments: [{ id: "function", label: "Function" }],
};
const UNIT_TYPESCRIPT: TreeUnit = {
  id: "typescript-tool:mixed",
  kind: "typescript-tool",
  path: "mixed.ts",
  fragments: [
    { id: "description", label: "Description" },
    { id: "indirect", label: "Indirect expression" },
  ],
};
const UNIT_OTHER: TreeUnit = {
  id: "unit:other",
  kind: "markdown",
  path: "other.md",
  fragments: [{ id: "other", label: "Other fragment" }],
};
const TARGET_A: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[0] ?? null };
const TARGET_B: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[1] ?? null };
const TARGET_PYTHON: SourceTarget = {
  unit: UNIT_PYTHON,
  fragment: UNIT_PYTHON.fragments[0] ?? null,
};
const TARGET_ALIAS: SourceTarget = {
  unit: UNIT_ALIAS,
  fragment: UNIT_ALIAS.fragments[0] ?? null,
};
const TARGET_TYPESCRIPT_DIRECT: SourceTarget = {
  unit: UNIT_TYPESCRIPT,
  fragment: UNIT_TYPESCRIPT.fragments[0] ?? null,
};
const TARGET_TYPESCRIPT_INDIRECT: SourceTarget = {
  unit: UNIT_TYPESCRIPT,
  fragment: UNIT_TYPESCRIPT.fragments[1] ?? null,
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "foundation",
      label: "Foundation",
      units: [UNIT_A, UNIT_ALIAS, UNIT_OTHER],
      session_shapes: [],
      children: [],
    },
  ],
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

type RenderHarness = {
  window: JSDOM["window"];
  container: HTMLElement;
  render: (node: React.ReactNode) => Promise<void>;
  click: (element: Element) => Promise<void>;
  input: (element: HTMLTextAreaElement, value: string) => Promise<void>;
  settle: () => Promise<void>;
  cleanup: () => Promise<void>;
};

function installDom(): RenderHarness {
  const dom = new JSDOM(
    "<!doctype html><html><head><meta name='csrf-token' content='test-token'></head><body><div id='root'></div></body></html>",
    { url: "http://127.0.0.1/" },
  );
  const previous = new Map<string, PropertyDescriptor | undefined>();
  const globals: Record<string, unknown> = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Element: dom.window.Element,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    InputEvent: dom.window.InputEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
    React,
  };
  for (const [name, value] of Object.entries(globals)) {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }

  const container = dom.window.document.querySelector<HTMLElement>("#root");
  assert.ok(container !== null);
  const root: Root = createRoot(container);
  return {
    window: dom.window,
    container,
    async render(node: React.ReactNode): Promise<void> {
      await React.act(async () => {
        root.render(node);
        await tick();
      });
    },
    async click(element: Element): Promise<void> {
      await React.act(async () => {
        element.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await tick();
      });
    },
    async input(element: HTMLTextAreaElement, value: string): Promise<void> {
      const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      assert.ok(setter !== undefined);
      const previousValue = element.value;
      await React.act(async () => {
        setter.call(element, value);
        const tracked = element as HTMLTextAreaElement & {
          _valueTracker?: { setValue: (next: string) => void };
        };
        tracked._valueTracker?.setValue(previousValue);
        element.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true }));
        element.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        await tick();
      });
    },
    async settle(): Promise<void> {
      await React.act(async () => {
        await tick();
        await tick();
      });
    },
    async cleanup(): Promise<void> {
      await React.act(async () => root.unmount());
      dom.window.close();
      for (const [name, descriptor] of previous) {
        if (descriptor === undefined) {
          Reflect.deleteProperty(globalThis, name);
        } else {
          Object.defineProperty(globalThis, name, descriptor);
        }
      }
    },
  };
}

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
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

function readOnlyView(target: SourceTarget, text: string, reason: ReadOnlyReason): SourceView {
  return {
    unit: target.unit.id,
    fragment: target.fragment,
    kind: target.unit.kind,
    before: "",
    focus: text,
    after: "",
    editable: false,
    read_only_reason: reason,
  };
}

function load(target: SourceTarget, text: string, view: SourceView): UnitSource {
  assert.equal(view.before + view.focus + view.after, text);
  return {
    file: {
      path: target.unit.path,
      mode: 0o644,
      newline_style: text.includes("\r") ? "mixed" : "lf",
      load_hash: HASH,
    },
    view,
  };
}

function buttonByText(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (candidate) => (candidate.textContent ?? "").replaceAll(/\s+/g, " ").trim() === text,
  );
  assert.ok(button !== undefined, `missing button: ${text}`);
  return button;
}

function buttonByLabel(container: ParentNode, label: string): HTMLButtonElement {
  const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  assert.ok(button !== null, `missing labeled button: ${label}`);
  return button;
}

function textarea(container: ParentNode): HTMLTextAreaElement {
  const editor = container.querySelector<HTMLTextAreaElement>("textarea");
  assert.ok(editor !== null, "missing source textarea");
  return editor;
}

function center(
  workspace: EditWorkspace,
  mode: "edit" | "compare" | "assembly",
  selection: Selection,
  comparisonState: ComparisonLoadState = { status: "idle" },
  selectedComparison: SelectedComparison | null = null,
): React.ReactNode {
  return React.createElement(
    WorkspaceProvider,
    { workspace },
    React.createElement(CenterPane, {
      mode,
      onModeChange: () => undefined,
      selection,
      comparisonState,
      selectedComparison,
    }),
  );
}

function placement(unit: UnitRef, label = unit.id): ComparisonPlacement {
  return {
    provenance: "canonical",
    unit,
    breadcrumb: [{ id: "foundation", label: "Foundation" }],
    shape: null,
    assembly: null,
    position: null,
    label,
  };
}

test("focused textarea preserves raw boundaries, escaped context, aliases, Compare, and mode state", async () => {
  const harness = installDom();
  const text = "<script>context</script>\r\nline1\r\nline2\rtail <b>context</b>";
  let loads = 0;
  const transport: WorkspaceTransport = {
    load: (target) => {
      loads += 1;
      return Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "line1\r\nline2\r")),
      });
    },
    project: (target, current) =>
      Promise.resolve({ status: "loaded", view: editableView(target, current, "line2") }),
  };
  const workspace = new EditWorkspace(transport);
  const selection: UnitSelection = { type: "unit", target: TARGET_A, placement: null };

  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    assert.equal(harness.container.querySelectorAll("textarea").length, 1);
    assert.equal(harness.container.querySelectorAll(".source-edit-regions > pre").length, 2);
    assert.equal(harness.container.querySelectorAll("script").length, 0);
    assert.equal(harness.container.querySelectorAll("b").length, 0);
    assert.match(harness.container.textContent ?? "", /<script>context<\/script>/);
    assert.equal(textarea(harness.container).value, "line1\nline2\n");

    await harness.input(textarea(harness.container), "line1\nCHANGED\n");
    assert.equal(
      workspace.snapshot("shared.md")?.currentText,
      "<script>context</script>\r\nline1\r\nCHANGED\rtail <b>context</b>",
    );
    assert.match(harness.container.textContent ?? "", /Dirty/);
    assert.doesNotMatch(harness.container.textContent ?? "", /Save/);

    const alias = await workspace.ensure({ unit: UNIT_ALIAS, fragment: null });
    assert.equal(alias.status, "loaded");
    assert.equal(
      alias.status === "loaded" ? alias.source.view.focus : null,
      workspace.snapshot("shared.md")?.currentText,
    );
    assert.equal(loads, 1, "different unit ids on one path cannot issue another canonical load");

    const choice: ComparisonChoice = {
      label: "Alias",
      detail: "Same path alias",
      target: placement(UNIT_ALIAS),
    };
    const options: ComparisonOptions = {
      origin: placement(UNIT_A),
      groups: [{ relation: "alias-consumer", label: "Aliases", choices: [choice] }],
    };
    const state: ComparisonLoadState = { status: "loaded", options };
    const selected: SelectedComparison = {
      relation: "alias-consumer",
      choiceIndex: 0,
      choice,
    };
    await harness.render(center(workspace, "compare", selection, state, selected));
    assert.match(harness.container.textContent ?? "", /No differences in current content/);
    assert.equal(loads, 1);

    await harness.render(center(workspace, "assembly", selection));
    assert.match(harness.container.textContent ?? "", /Assembly mode is not built yet/);
    await harness.render(center(workspace, "edit", selection));
    assert.equal(textarea(harness.container).value, "line1\nCHANGED\n");
  } finally {
    await harness.cleanup();
  }
});

test("an empty mapped focus remains a usable textarea", async () => {
  const harness = installDom();
  const text = "context";
  const emptyView: SourceView = {
    unit: TARGET_A.unit.id,
    fragment: TARGET_A.fragment,
    kind: TARGET_A.unit.kind,
    before: "con",
    focus: "",
    after: "text",
    editable: true,
    read_only_reason: null,
  };
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve({ status: "loaded", source: load(target, text, emptyView) }),
    project: () => Promise.resolve({ status: "failed" }),
  });
  const selection: UnitSelection = { type: "unit", target: TARGET_A, placement: null };
  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    assert.equal(textarea(harness.container).value, "");
    assert.match(harness.container.textContent ?? "", /This mapped fragment is empty/);
    await harness.input(textarea(harness.container), "inserted");
    assert.equal(workspace.snapshot("shared.md")?.currentText, "coninsertedtext");
  } finally {
    await harness.cleanup();
  }
});

test("protected temporary-invalid focus survives navigation and adapter retry is explicit", async () => {
  const harness = installDom();
  const text = "A then B";
  let projectionCalls = 0;
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(TARGET_A, text, "A")),
      }),
    project: (target, current) => {
      projectionCalls += 1;
      if (target.fragment?.id === "b") {
        return Promise.resolve({
          status: "loaded",
          view: readOnlyView(target, current, "invalid-source"),
        });
      }
      if (projectionCalls < 4) {
        return Promise.resolve({
          status: "loaded",
          view: readOnlyView(target, current, "adapter-unavailable"),
        });
      }
      return Promise.resolve({ status: "loaded", view: editableView(target, current, "B") });
    },
  });
  const selectionA: UnitSelection = { type: "unit", target: TARGET_A, placement: null };
  const selectionB: UnitSelection = { type: "unit", target: TARGET_B, placement: null };
  const aliasSelection: UnitSelection = { type: "unit", target: TARGET_ALIAS, placement: null };

  try {
    await harness.render(center(workspace, "edit", selectionA));
    await harness.settle();
    await harness.input(textarea(harness.container), "INVALID {{{");
    await harness.render(center(workspace, "edit", selectionB));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Invalid source/);
    await harness.render(center(workspace, "edit", selectionA));
    assert.equal(textarea(harness.container).value, "INVALID {{{");

    await harness.render(center(workspace, "edit", aliasSelection));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Adapter unavailable/);
    assert.equal(projectionCalls, 2);
    await harness.settle();
    assert.equal(projectionCalls, 2, "transient failure must not start an automatic retry loop");
    await harness.click(buttonByText(harness.container, "Retry adapter"));
    await harness.settle();
    assert.equal(projectionCalls, 3);
    assert.match(harness.container.textContent ?? "", /Adapter unavailable/);
    await harness.render(center(workspace, "edit", selectionA));
    await harness.render(center(workspace, "edit", aliasSelection));
    await harness.settle();
    assert.equal(
      projectionCalls,
      4,
      "reselection retries after the target was navigated away from",
    );
    assert.equal(textarea(harness.container).value, "B");
  } finally {
    await harness.cleanup();
  }
});

test("stale helper overlap keeps the latest target unavailable until explicit retry", async () => {
  const harness = installDom();
  const held = deferred<SourceProjectionOutcome>();
  const text = "A then B";
  let projectionCalls = 0;
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(TARGET_A, text, "A")),
      }),
    project: (target, current) => {
      projectionCalls += 1;
      if (projectionCalls === 1) {
        return held.promise;
      }
      if (projectionCalls === 2) {
        return Promise.resolve({
          status: "loaded",
          view: readOnlyView(target, current, "adapter-unavailable"),
        });
      }
      return Promise.resolve({ status: "loaded", view: editableView(target, current, "B") });
    },
  });
  const selectionA: UnitSelection = { type: "unit", target: TARGET_A, placement: null };
  const aliasSelection: UnitSelection = { type: "unit", target: TARGET_ALIAS, placement: null };

  try {
    await harness.render(center(workspace, "edit", selectionA));
    await harness.settle();
    await harness.render(center(workspace, "edit", aliasSelection));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Loading source/);

    await harness.render(center(workspace, "edit", selectionA));
    await harness.input(textarea(harness.container), "AA");
    await harness.render(center(workspace, "edit", aliasSelection));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Adapter unavailable/);

    held.resolve({ status: "loaded", view: editableView(TARGET_ALIAS, text, "B") });
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Adapter unavailable/);
    assert.equal(workspace.inspect(TARGET_ALIAS), null);

    await harness.click(buttonByText(harness.container, "Retry adapter"));
    await harness.settle();
    assert.equal(textarea(harness.container).value, "B");
    assert.equal(workspace.snapshot("shared.md")?.currentText, "AA then B");
    assert.equal(projectionCalls, 3);
  } finally {
    await harness.cleanup();
  }
});

test("save review renders escaped full-file diff, byte metadata, and read-only handoffs", async () => {
  const harness = installDom();
  const text = "\ufeffhead\r\nA\r\n";
  let submittedText: string | null = null;
  const workspace = new EditWorkspace({
    load: (target) => {
      const source = load(target, text, editableView(target, text, "A"));
      return Promise.resolve({
        status: "loaded",
        source: { ...source, file: { ...source.file, newline_style: "crlf" as const } },
      });
    },
    project: (target, current) =>
      Promise.resolve({
        status: "loaded",
        view: editableView(target, current, "<script>changed</script>"),
      }),
    save: (target, _loadHash, current) => {
      submittedText = current;
      return Promise.resolve({
        status: "loaded",
        result: {
          status: "saved",
          source: {
            unit: target.unit.id,
            kind: target.unit.kind,
            file: {
              path: target.unit.path,
              mode: 0o640,
              newline_style: "crlf",
              load_hash: "f".repeat(64),
            },
          },
          materialized: [
            {
              id: "<script>lineage</script>",
              relationship: "materializes-to",
              targets: ["<b>generated.md</b>"],
            },
          ],
          checks: [{ id: "prose-map", command: "<img src=x onerror=alert(1)>" }],
          catalog_refreshed: true,
          refresh_detail: null,
        },
      });
    },
  });
  const selection: UnitSelection = { type: "unit", target: TARGET_A, placement: null };

  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    await harness.input(textarea(harness.container), "<script>first</script>");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    assert.equal(harness.container.querySelectorAll("script").length, 0);
    assert.match(harness.container.textContent ?? "", /<script>first<\/script>/);
    assert.match(harness.container.textContent ?? "", /Loaded.*bytes.*crlf.*BOM yes/s);
    assert.match(harness.container.textContent ?? "", /Current.*bytes.*crlf.*BOM yes/s);
    assert.match(
      harness.container.querySelector(".save-diff")?.textContent ?? "",
      /--- a\/shared\.md/,
    );

    await harness.input(textarea(harness.container), "<script>changed</script>");
    assert.equal(harness.container.querySelector(".save-review"), null);
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();

    assert.equal(submittedText, "\ufeffhead\r\n<script>changed</script>\r\n");
    assert.match(harness.container.textContent ?? "", /Saved/);
    assert.match(harness.container.textContent ?? "", /Materialization handoff/);
    assert.match(harness.container.textContent ?? "", /<script>lineage<\/script>/);
    assert.match(harness.container.textContent ?? "", /<b>generated\.md<\/b>/);
    assert.equal(harness.container.querySelectorAll("script, b, img").length, 0);
    assert.equal(workspace.snapshot("shared.md")?.mode, 0o640);
    assert.equal(workspace.snapshot("shared.md")?.dirty, false);
    assert.equal(workspace.writeState().catalogEpoch, 1);
  } finally {
    await harness.cleanup();
  }
});

test("conflict and indeterminate UI preserve Copy Edits, exact failures, and destructive reload confirmation", async () => {
  const harness = installDom();
  const text = "before A after";
  let reloadCalls = 0;
  let copied = "";
  let clipboardFails = true;
  Object.defineProperty(harness.window.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: (value: string) => {
        if (clipboardFails) {
          return Promise.reject(new Error("denied"));
        }
        copied = value;
        return Promise.resolve();
      },
    },
  });
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "A")),
      }),
    project: (target, current) =>
      Promise.resolve({ status: "loaded", view: editableView(target, current, "external") }),
    save: () =>
      Promise.resolve({
        status: "loaded",
        result: { status: "conflict", detail: CONFLICT_DETAIL },
      }),
    reload: (target) => {
      reloadCalls += 1;
      const external = "before external after";
      return Promise.resolve({
        status: "loaded",
        source: load(target, external, editableView(target, external, "external")),
      });
    },
  });
  const selection: UnitSelection = { type: "unit", target: TARGET_A, placement: null };

  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    await harness.input(textarea(harness.container), "edited A");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    assert.ok((harness.container.textContent ?? "").includes(CONFLICT_DETAIL));
    assert.equal(
      [...harness.container.querySelectorAll("button")].some(
        (button) => button.textContent === "Discard file",
      ),
      false,
    );
    await harness.click(buttonByText(harness.container, "Copy Edits"));
    await harness.settle();
    assert.ok((harness.container.textContent ?? "").includes(CLIPBOARD_FAILURE_DETAIL));
    clipboardFails = false;
    await harness.click(buttonByText(harness.container, "Copy Edits"));
    await harness.settle();
    assert.equal(copied, "before edited A after");

    let confirmation = "";
    harness.window.confirm = (message) => {
      confirmation = String(message);
      return false;
    };
    await harness.click(buttonByText(harness.container, "Reload from disk"));
    assert.equal(reloadCalls, 0);
    assert.equal(confirmation, "Reload shared.md from disk and replace all in-memory edits?");
    harness.window.confirm = () => true;
    await harness.click(buttonByText(harness.container, "Reload from disk"));
    await harness.settle();
    assert.equal(reloadCalls, 1);
    assert.equal(workspace.snapshot("shared.md")?.currentText, "before external after");
  } finally {
    await harness.cleanup();
  }

  const indeterminateHarness = installDom();
  const heldReload = deferred<SourceLoadOutcome>();
  const indeterminate = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "A")),
      }),
    project: () => Promise.resolve({ status: "failed" }),
    save: () => Promise.resolve({ status: "indeterminate" }),
    reload: () => heldReload.promise,
  });
  try {
    await indeterminateHarness.render(center(indeterminate, "edit", selection));
    await indeterminateHarness.settle();
    await indeterminateHarness.input(textarea(indeterminateHarness.container), "uncertain A");
    await indeterminateHarness.click(
      buttonByText(indeterminateHarness.container, "Review full-file diff"),
    );
    await indeterminateHarness.click(
      buttonByText(indeterminateHarness.container, "Save reviewed file"),
    );
    await indeterminateHarness.settle();
    assert.equal(
      (indeterminateHarness.container.textContent ?? "").includes(INDETERMINATE_DETAIL),
      true,
    );
    assert.equal(textarea(indeterminateHarness.container).disabled, true);
    assert.equal(indeterminate.discard(UNIT_A.path), false);
    heldReload.resolve({ status: "failed" });
    await indeterminateHarness.settle();
    assert.equal(
      (indeterminateHarness.container.textContent ?? "").includes(UNRESOLVED_RECONCILIATION_DETAIL),
      true,
    );
    buttonByText(indeterminateHarness.container, "Retry reconciliation");
    buttonByText(indeterminateHarness.container, "Copy Edits");
  } finally {
    await indeterminateHarness.cleanup();
  }
});

test("successful App save refreshes catalog and inspector without replacing workspace state", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const text = "before A after";
  let treeRequests = 0;
  let inspectRequests = 0;
  globalThis.fetch = async (input, init): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/catalog/tree") {
      treeRequests += 1;
      return treeRequests === 1 ? response(200, TREE) : response(500, { detail: "failed" });
    }
    if (url.startsWith("/api/inspect?")) {
      inspectRequests += 1;
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/source?")) {
      const parsed = new URL(url, "http://127.0.0.1");
      const fragment = UNIT_A.fragments.find(
        (candidate) => candidate.id === parsed.searchParams.get("fragment"),
      );
      const target: SourceTarget = { unit: UNIT_A, fragment: fragment ?? null };
      return response(200, load(target, text, editableView(target, text, "A")));
    }
    if (url === "/api/source/project") {
      const body = JSON.parse(String(init?.body)) as {
        fragment: string | null;
        text: string;
      };
      const fragment = UNIT_A.fragments.find((candidate) => candidate.id === body.fragment);
      const target: SourceTarget = { unit: UNIT_A, fragment: fragment ?? null };
      return response(200, editableView(target, body.text, "saved A"));
    }
    if (url === "/api/source/save") {
      const body = JSON.parse(String(init?.body)) as {
        unit: string;
        text: string;
      };
      assert.equal(body.text, "before saved A after");
      return response(200, {
        status: "saved",
        source: {
          unit: body.unit,
          kind: UNIT_A.kind,
          file: {
            path: UNIT_A.path,
            mode: 0o644,
            newline_style: "lf",
            load_hash: "a".repeat(64),
          },
        },
        materialized: [],
        checks: [],
        catalog_refreshed: true,
        refresh_detail: null,
      });
    }
    throw new Error(`unexpected request: ${url}`);
  };

  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Fragment A"));
    await harness.settle();
    await harness.input(textarea(harness.container), "saved A");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    await harness.settle();

    assert.equal(treeRequests, 2);
    assert.match(harness.container.textContent ?? "", /prior tree remains available/);
    buttonByLabel(harness.container, `Collapse fragments for ${UNIT_A.id}`);
    assert.ok(inspectRequests >= 2, "the retained selection is re-inspected after catalog refresh");
    assert.match(harness.container.textContent ?? "", /Saved/);
    assert.match(harness.container.textContent ?? "", /Workspace \(0\)/);
    assert.equal(buttonByText(harness.container, "Edit").ariaPressed, "true");
    assert.equal(textarea(harness.container).value, "saved A");
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});

test("catalog refresh failure freezes App writes with exact recovery guidance", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const text = "before A after";
  globalThis.fetch = async (input, init): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/source?")) {
      return response(200, load(TARGET_A, text, editableView(TARGET_A, text, "A")));
    }
    if (url === "/api/source/project") {
      const body = JSON.parse(String(init?.body)) as { text: string };
      return response(200, editableView(TARGET_A, body.text, "saved A"));
    }
    if (url === "/api/source/save") {
      return response(200, {
        status: "saved",
        source: {
          unit: UNIT_A.id,
          kind: UNIT_A.kind,
          file: {
            path: UNIT_A.path,
            mode: 0o644,
            newline_style: "lf",
            load_hash: "9".repeat(64),
          },
        },
        materialized: [],
        checks: [],
        catalog_refreshed: false,
        refresh_detail: CATALOG_STALE_DETAIL,
      });
    }
    throw new Error(`unexpected request: ${url}`);
  };

  try {
    await harness.render(React.createElement(App));
    await harness.settle();
    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Fragment A"));
    await harness.settle();
    await harness.input(textarea(harness.container), "saved A");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();

    const warning = harness.container.querySelector(".write-state-warning");
    assert.equal(warning?.textContent, CATALOG_STALE_DETAIL);
    assert.ok((harness.container.textContent ?? "").includes(CATALOG_STALE_DETAIL));
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});

test("dirty Python sources expose the shared full-file review affordance", async () => {
  const harness = installDom();
  const text = "def function():\n    pass\n";
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "pass")),
      }),
    project: () => Promise.resolve({ status: "failed" }),
  });
  const selection: UnitSelection = {
    type: "unit",
    target: TARGET_PYTHON,
    placement: null,
  };
  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    await harness.input(textarea(harness.container), "return None");
    assert.match(harness.container.textContent ?? "", /Review full-file diff/);
  } finally {
    await harness.cleanup();
  }
});

test("TypeScript review controls follow the current direct or indirect presentation", async () => {
  const harness = installDom();
  const text = 'const tool = { description: "direct", prompt: indirect };\n';
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "direct")),
      }),
    project: (target, current) =>
      Promise.resolve({
        status: "loaded",
        view:
          target.fragment?.id === "indirect"
            ? readOnlyView(target, current, "unsupported-source-shape")
            : editableView(target, current, "reviewed direct"),
      }),
  });
  const directSelection: UnitSelection = {
    type: "unit",
    target: TARGET_TYPESCRIPT_DIRECT,
    placement: null,
  };
  const indirectSelection: UnitSelection = {
    type: "unit",
    target: TARGET_TYPESCRIPT_INDIRECT,
    placement: null,
  };

  try {
    await harness.render(center(workspace, "edit", directSelection));
    await harness.settle();
    await harness.input(textarea(harness.container), "reviewed direct");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    assert.ok(harness.container.querySelector(".save-review") !== null);
    buttonByText(harness.container, "Save reviewed file");

    await harness.render(center(workspace, "edit", indirectSelection));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Unsupported source shape/);
    assert.equal(harness.container.querySelector("textarea"), null);
    assert.equal(harness.container.querySelector(".save-review"), null);
    assert.equal(
      [...harness.container.querySelectorAll("button")].some((button) =>
        /Review full-file diff|Save reviewed file/.test(button.textContent ?? ""),
      ),
      false,
    );
    const indirect = workspace.inspect(TARGET_TYPESCRIPT_INDIRECT);
    assert.equal(indirect?.review, null);
    assert.equal(indirect?.canReview, false);
    assert.equal(indirect?.canSave, false);

    await harness.render(center(workspace, "edit", directSelection));
    assert.equal(textarea(harness.container).value, "reviewed direct");
    assert.ok(harness.container.querySelector(".save-review") !== null);
    buttonByText(harness.container, "Save reviewed file");
  } finally {
    await harness.cleanup();
  }
});

test("validation and generated-lineage refusal are rendered without implicit retry", async () => {
  const harness = installDom();
  const text = "before A after";
  const outcomes: SourceSaveLoadOutcome[] = [
    { status: "not-sent" },
    {
      status: "loaded" as const,
      result: {
        status: "validation-failed" as const,
        diagnostics: [
          {
            code: "selector-not-found",
            message: "missing heading",
            selector: "heading:missing",
            line: null,
            column: null,
          },
          {
            code: "syntax-error",
            message: "bad token",
            selector: null,
            line: 4,
            column: 7,
          },
        ],
      },
    },
    {
      status: "loaded" as const,
      result: {
        status: "refused" as const,
        reason: "unsafe-lineage" as const,
        detail: GENERATED_LINEAGE_DETAIL,
      },
    },
  ];
  const workspace = new EditWorkspace({
    load: (target) =>
      Promise.resolve({
        status: "loaded",
        source: load(target, text, editableView(target, text, "A")),
      }),
    project: () => Promise.resolve({ status: "failed" }),
    save: () => Promise.resolve(outcomes.shift() ?? { status: "indeterminate" }),
  });
  const selection: UnitSelection = { type: "unit", target: TARGET_A, placement: null };
  try {
    await harness.render(center(workspace, "edit", selection));
    await harness.settle();
    await harness.input(textarea(harness.container), "edited A");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    assert.ok((harness.container.textContent ?? "").includes(NOT_SENT_DETAIL));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /heading:missing missing heading/);
    assert.match(harness.container.textContent ?? "", /shared\.md:4:7 bad token/);
    assert.doesNotMatch(harness.container.textContent ?? "", /Review full-file diff/);

    await harness.input(textarea(harness.container), "fixed A");
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    assert.ok((harness.container.textContent ?? "").includes(GENERATED_LINEAGE_DETAIL));
    assert.doesNotMatch(harness.container.textContent ?? "", /Review full-file diff/);
  } finally {
    await harness.cleanup();
  }
});

test("App drawer, confirmed discard, last-target Open, manual reversion, and unload guard are file-based", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const sourceTexts = new Map([
    ["shared.md", "head\r\nA\r\ntail"],
    ["other.md", "other B end"],
  ]);
  const getCounts = new Map<string, number>();
  let projectCalls = 0;
  globalThis.fetch = async (input, init): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url === "/api/source/project") {
      projectCalls += 1;
      assert.equal((init?.headers as Record<string, string>)["X-Prose-Review-Csrf"], "test-token");
      const body = JSON.parse(String(init?.body)) as {
        unit: string;
        fragment: string | null;
        text: string;
      };
      const unit = [UNIT_A, UNIT_ALIAS, UNIT_OTHER].find((candidate) => candidate.id === body.unit);
      assert.ok(unit !== undefined);
      const fragment = unit.fragments.find((candidate) => candidate.id === body.fragment);
      const target: SourceTarget = { unit, fragment: fragment ?? null };
      const focus = body.fragment === "other" ? "B" : body.fragment === "b" ? "tail" : "A";
      return response(200, editableView(target, body.text, focus));
    }
    if (url.startsWith("/api/source?")) {
      const parsed = new URL(url, "http://127.0.0.1");
      const unitId = parsed.searchParams.get("unit");
      const fragmentId = parsed.searchParams.get("fragment");
      const unit = [UNIT_A, UNIT_ALIAS, UNIT_OTHER].find((candidate) => candidate.id === unitId);
      assert.ok(unit !== undefined);
      const fragment = unit.fragments.find((candidate) => candidate.id === fragmentId);
      const target: SourceTarget = { unit, fragment: fragment ?? null };
      const text = sourceTexts.get(unit.path);
      assert.ok(text !== undefined);
      getCounts.set(unit.path, (getCounts.get(unit.path) ?? 0) + 1);
      const focus = fragmentId === "other" ? "B" : fragmentId === "b" ? "tail" : "A";
      return response(200, load(target, text, editableView(target, text, focus)));
    }
    if (url.startsWith("/api/compare?")) {
      return response(404, { detail: "unknown comparison subject" });
    }
    throw new Error(`unexpected request: ${url}`);
  };

  const beforeUnloadListeners: EventListener[] = [];
  const removedBeforeUnloadListeners: EventListener[] = [];
  const realAdd = harness.window.addEventListener.bind(harness.window);
  const realRemove = harness.window.removeEventListener.bind(harness.window);
  harness.window.addEventListener = ((
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ) => {
    if (type === "beforeunload" && typeof listener === "function") {
      beforeUnloadListeners.push(listener);
    }
    realAdd(type, listener, options);
  }) as typeof harness.window.addEventListener;
  harness.window.removeEventListener = ((
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ) => {
    if (type === "beforeunload" && typeof listener === "function") {
      removedBeforeUnloadListeners.push(listener);
    }
    realRemove(type, listener, options);
  }) as typeof harness.window.removeEventListener;

  try {
    await harness.render(React.createElement(App));
    assert.equal(buttonByText(harness.container, "Workspace (0)").ariaExpanded, "false");
    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Fragment A"));
    await harness.settle();
    await harness.input(textarea(harness.container), "edited A");
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Workspace \(1\)/);
    assert.match(harness.container.textContent ?? "", /Dirty/);
    assert.equal(beforeUnloadListeners.length, 1);
    let prevented = false;
    const fakeBeforeUnload = {
      preventDefault: () => {
        prevented = true;
      },
      returnValue: false,
    } as unknown as BeforeUnloadEvent;
    beforeUnloadListeners[0]?.(fakeBeforeUnload);
    assert.equal(prevented, true);
    assert.equal(fakeBeforeUnload.returnValue, true);

    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_OTHER.id}`));
    await harness.click(buttonByText(harness.container, "Other fragment"));
    await harness.settle();
    await harness.input(textarea(harness.container), "edited B");
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Workspace \(2\)/);
    assert.equal(getCounts.get("shared.md"), 1);
    assert.equal(getCounts.get("other.md"), 1);

    await harness.click(buttonByText(harness.container, "Workspace (2)"));
    assert.equal(buttonByText(harness.container, "Workspace (2)").ariaExpanded, "true");
    const drawer = harness.container.querySelector<HTMLElement>(".workspace-drawer");
    assert.ok(drawer !== null);
    assert.match(
      drawer.textContent ?? "",
      /shared\.md · unit:a · Unsaved edits · Fragment A \(a\)/,
    );
    assert.match(
      drawer.textContent ?? "",
      /other\.md · unit:other · Unsaved edits · Other fragment \(other\)/,
    );
    assert.doesNotMatch(drawer.textContent ?? "", /· idle/);

    harness.window.confirm = () => false;
    const sharedRow = [...drawer.querySelectorAll("li")].find((row) =>
      (row.textContent ?? "").includes("shared.md"),
    );
    assert.ok(sharedRow !== undefined);
    await harness.click(buttonByText(sharedRow, "Discard file"));
    assert.match(harness.container.textContent ?? "", /Workspace \(2\)/);

    await harness.click(buttonByText(harness.container, "Assembly"));
    await harness.click(buttonByText(sharedRow, "Open"));
    assert.equal(harness.container.querySelector(".workspace-drawer"), null);
    assert.equal(buttonByText(harness.container, "Assembly").ariaPressed, "true");
    await harness.click(buttonByText(harness.container, "Edit"));
    assert.equal(textarea(harness.container).value, "edited A");

    harness.window.confirm = () => true;
    await harness.click(buttonByText(harness.container, "Discard file"));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Workspace \(1\)/);
    assert.equal(textarea(harness.container).value, "A");
    assert.equal(getCounts.get("shared.md"), 1, "discard must not reread canonical disk content");
    assert.ok(projectCalls >= 1, "visible source re-projects after discard");

    await harness.click(buttonByText(harness.container, "Workspace (1)"));
    const remainingOpen = buttonByText(harness.container, "Open");
    await harness.click(remainingOpen);
    assert.equal(textarea(harness.container).value, "edited B");
    await harness.input(textarea(harness.container), "B");
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Workspace \(0\)/);
    assert.equal(removedBeforeUnloadListeners.length, 1);

    await harness.click(buttonByText(harness.container, "Workspace (0)"));
    assert.match(harness.container.textContent ?? "", /No files need attention\./);
    assert.doesNotMatch(harness.container.textContent ?? "", /Save/);
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});
