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
import type { Selection, SourceTarget, UnitSelection } from "./src/selection.ts";
import type { ReadOnlyReason, SourceView, UnitSource } from "./src/source.ts";
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
const UNIT_OTHER: TreeUnit = {
  id: "unit:other",
  kind: "markdown",
  path: "other.md",
  fragments: [{ id: "other", label: "Other fragment" }],
};
const TARGET_A: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[0] ?? null };
const TARGET_B: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[1] ?? null };
const TARGET_ALIAS: SourceTarget = {
  unit: UNIT_ALIAS,
  fragment: UNIT_ALIAS.fragments[0] ?? null,
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
      workspace.currentText("shared.md"),
      "<script>context</script>\r\nline1\r\nCHANGED\rtail <b>context</b>",
    );
    assert.match(harness.container.textContent ?? "", /Dirty/);
    assert.doesNotMatch(harness.container.textContent ?? "", /Save/);

    const alias = await workspace.ensure({ unit: UNIT_ALIAS, fragment: null });
    assert.equal(alias.status, "loaded");
    assert.equal(
      alias.status === "loaded" ? alias.source.view.focus : null,
      workspace.currentText("shared.md"),
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
    assert.equal(workspace.currentText("shared.md"), "coninsertedtext");
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
    assert.match(drawer.textContent ?? "", /shared\.md · unit:a · Fragment A \(a\)/);
    assert.match(drawer.textContent ?? "", /other\.md · unit:other · Other fragment \(other\)/);

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
    assert.match(harness.container.textContent ?? "", /No unsaved files\./);
    assert.doesNotMatch(harness.container.textContent ?? "", /Save/);
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});
