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
import { EditWorkspace } from "./src/editWorkspace.ts";
import type { UnitSelection } from "./src/selection.ts";
import type { UnitSource } from "./src/source.ts";
import type { CapabilityTree, SessionShape, TreeUnit, UnitRef } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");
const { CenterPane, WorkspaceProvider } = (await tsImport(
  "./src/CenterPane.tsx",
  import.meta.url,
)) as typeof import("./src/CenterPane.tsx");

const UNIT_A: TreeUnit = {
  id: "unit:a",
  kind: "markdown",
  path: "a.md",
  fragments: [{ id: "body", label: "Body" }],
};
const UNIT_B: TreeUnit = {
  id: "unit:b",
  kind: "markdown",
  path: "b.md",
  fragments: [],
};
const UNIT_C: UnitRef = { id: "unit:c", kind: "markdown", path: "c.md" };
const BOUNDARY_LAYER = {
  position: 1,
  optional: false,
  label: "System boundary",
  unit: null,
  boundary: "pi-system" as const,
};
const WARM_LAYER = {
  position: 2,
  optional: false,
  label: "Warm layer",
  unit: UNIT_A,
  boundary: null,
};
const WARM: SessionShape = {
  id: "shape:warm",
  label: "Warm shape",
  delivery: "warm",
  layers: [BOUNDARY_LAYER, WARM_LAYER],
};
const COLD: SessionShape = {
  ...WARM,
  id: "shape:cold",
  label: "Cold shape",
  delivery: "cold",
  layers: [BOUNDARY_LAYER, { ...WARM_LAYER, label: "Cold layer" }],
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "planning",
      label: "Planning",
      units: [UNIT_A],
      session_shapes: [WARM, COLD],
      children: [],
    },
  ],
};

function wirePlacement(
  unit: UnitRef,
  shape: SessionShape | null = null,
  label = unit.id,
): Record<string, unknown> {
  return {
    unit,
    breadcrumb: [{ id: "planning", label: "Planning" }],
    shape: shape === null ? null : { id: shape.id, label: shape.label, delivery: shape.delivery },
    assembly: shape === null ? null : "test-assembly",
    position: shape === null ? null : 2,
    label,
  };
}

function wireOptions(shape: SessionShape | null = null): Record<string, unknown> {
  const duplicateChoice = {
    label: "Target unit",
    detail: "Same display identity",
    target: wirePlacement(UNIT_B),
  };
  return {
    origin: wirePlacement(UNIT_A, shape, shape === null ? UNIT_A.id : `${shape.label} origin`),
    groups: [
      {
        relation: "concern-relative",
        label: "Concern relatives",
        choices: [duplicateChoice, structuredClone(duplicateChoice)],
      },
    ],
  };
}

function source(unit: UnitRef, focus: string): UnitSource {
  return {
    file: {
      path: unit.path,
      mode: 0o644,
      newline_style: "lf",
      load_hash: "0123456789abcdef".repeat(4),
    },
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

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function itemAt<T>(items: ArrayLike<T>, index: number): T {
  const item = items[index];
  assert.ok(item !== undefined, `missing item at index ${index}`);
  return item;
}

type RenderHarness = {
  container: HTMLElement;
  render: (node: React.ReactNode) => Promise<void>;
  click: (element: Element) => Promise<void>;
  settle: () => Promise<void>;
  cleanup: () => Promise<void>;
};

function installDom(): RenderHarness {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>", {
    url: "http://127.0.0.1/",
  });
  const previous = new Map<string, PropertyDescriptor | undefined>();
  const globals: Record<string, unknown> = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Element: dom.window.Element,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
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

function normalizedText(element: Element): string {
  return (element.textContent ?? "").replaceAll(/\s+/g, " ").trim();
}

function buttonByText(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (candidate) => normalizedText(candidate) === text,
  );
  assert.ok(button !== undefined, `missing button: ${text}`);
  return button;
}

function buttonStartingWith(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find((candidate) =>
    normalizedText(candidate).startsWith(text),
  );
  assert.ok(button !== undefined, `missing button starting with: ${text}`);
  return button;
}

function buttonByLabel(container: ParentNode, label: string): HTMLButtonElement {
  const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  assert.ok(button !== null, `missing labeled button: ${label}`);
  return button;
}

test("App preserves fragment sessions and invalidates changed Compare origins", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const compareRequests: { url: string; request: Deferred<Response> }[] = [];
  const sourceUrls: string[] = [];
  globalThis.fetch = async (input): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/compare?")) {
      const request = deferred<Response>();
      compareRequests.push({ url, request });
      return request.promise;
    }
    if (url.startsWith("/api/source?")) {
      sourceUrls.push(url);
      const unit = url.includes("unit%3Ab") ? UNIT_B : UNIT_A;
      return response(200, source(unit, "same\n"));
    }
    throw new Error(`unexpected request: ${url}`);
  };

  try {
    await harness.render(React.createElement(App));
    await harness.click(buttonByText(harness.container, UNIT_A.id));
    await harness.click(buttonByText(harness.container, "Compare"));
    assert.equal(compareRequests.length, 1);
    assert.match(harness.container.textContent ?? "", /Loading comparison options/);

    itemAt(compareRequests, 0).request.resolve(response(200, wireOptions()));
    await harness.settle();
    const duplicateTargets = harness.container.querySelectorAll<HTMLButtonElement>(
      ".comparison-picker .relation-entry",
    );
    assert.equal(duplicateTargets.length, 2);
    await harness.click(itemAt(duplicateTargets, 1));
    const selectedTargets = harness.container.querySelectorAll<HTMLButtonElement>(
      ".comparison-picker .relation-entry.selected",
    );
    assert.equal(selectedTargets.length, 1);
    assert.equal(selectedTargets[0], duplicateTargets[1]);
    assert.match(harness.container.textContent ?? "", /No differences in current content/);

    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_A.id}`));
    await harness.click(buttonByText(harness.container, "Body"));
    assert.equal(compareRequests.length, 1, "fragment navigation reuses the whole-unit session");
    assert.equal(
      harness.container.querySelectorAll(".comparison-picker .relation-entry.selected").length,
      1,
    );

    await harness.click(buttonByLabel(harness.container, "Expand layers for Warm shape"));
    await harness.click(buttonByText(harness.container, "Warm layer"));
    assert.equal(compareRequests.length, 2);
    assert.equal(
      harness.container.querySelectorAll(".comparison-picker .relation-entry.selected").length,
      0,
    );

    await harness.click(buttonByLabel(harness.container, "Expand layers for Cold shape"));
    await harness.click(buttonByText(harness.container, "Cold layer"));
    assert.equal(compareRequests.length, 3);
    itemAt(compareRequests, 2).request.resolve(response(200, wireOptions(COLD)));
    await harness.settle();
    itemAt(compareRequests, 1).request.resolve(response(200, wireOptions(WARM)));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Cold shape origin/);
    assert.doesNotMatch(harness.container.textContent ?? "", /Warm shape origin/);

    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    assert.equal(compareRequests.length, 3);
    assert.match(
      harness.container.textContent ?? "",
      /Choose a source-bearing assembly layer in the inspector/,
    );

    await harness.click(buttonStartingWith(harness.container, "System boundary"));
    assert.equal(compareRequests.length, 3);
    assert.match(harness.container.textContent ?? "", /Boundaries are not comparison subjects/);

    await harness.click(buttonByText(harness.container, UNIT_A.id));
    assert.equal(compareRequests.length, 4);
    itemAt(compareRequests, 3).request.resolve(response(200, wireOptions()));
    await harness.settle();
    await harness.click(
      itemAt(
        harness.container.querySelectorAll<HTMLButtonElement>(".comparison-picker .relation-entry"),
        0,
      ),
    );
    await harness.click(buttonByText(harness.container, "Edit"));
    await harness.click(buttonByText(harness.container, "Compare"));
    assert.equal(compareRequests.length, 5, "re-entering Compare starts a fresh option load");
    assert.match(harness.container.textContent ?? "", /Loading comparison options/);
    assert.ok(sourceUrls.length >= 2, "selected comparisons and Edit both use source loading");
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});

function placement(
  unit: UnitRef,
  provenance: "canonical" | "shape" = "canonical",
): ComparisonPlacement {
  const common = {
    unit,
    breadcrumb: [{ id: "planning", label: "Planning" }],
    label: provenance === "canonical" ? unit.id : `${unit.id} placed`,
  };
  if (provenance === "canonical") {
    return {
      ...common,
      provenance,
      shape: null,
      assembly: null,
      position: null,
    };
  }
  return {
    ...common,
    provenance,
    shape: { id: "shape:warm", label: "Warm shape", delivery: "warm" },
    assembly: "test-assembly",
    position: 2,
  };
}

function loadedComparison(
  origin: ComparisonPlacement,
  choice: ComparisonChoice,
): {
  state: ComparisonLoadState;
  selected: SelectedComparison;
} {
  const options: ComparisonOptions = {
    origin,
    groups: [{ relation: "alias-consumer", label: "Alias consumers", choices: [choice] }],
  };
  return {
    state: { status: "loaded", options },
    selected: { relation: "alias-consumer", choiceIndex: 0, choice },
  };
}

function centerElement(
  workspace: EditWorkspace,
  selection: UnitSelection,
  state: ComparisonLoadState,
  selected: SelectedComparison,
): React.ReactNode {
  return React.createElement(
    WorkspaceProvider,
    { workspace },
    React.createElement(CenterPane, {
      mode: "compare",
      onModeChange: () => undefined,
      selection,
      comparisonState: state,
      selectedComparison: selected,
    }),
  );
}

test("CenterPane shares equal-unit source and renders native line chunks for distinct units", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const sourceUrls: string[] = [];
  const workspace = new EditWorkspace();
  let sources = new Map([
    [UNIT_A.id, source(UNIT_A, "same\n")],
    [UNIT_B.id, source(UNIT_B, "same\n")],
  ]);
  globalThis.fetch = async (input): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    sourceUrls.push(url);
    const unitId = new URL(url, "http://127.0.0.1").searchParams.get("unit");
    assert.ok(unitId !== null);
    const body = sources.get(unitId);
    assert.ok(body !== undefined);
    return response(200, body);
  };

  const selection: UnitSelection = {
    type: "unit",
    target: { unit: UNIT_A, fragment: null },
    placement: null,
  };
  try {
    const sameChoice: ComparisonChoice = {
      label: "Placed copy",
      detail: "Same canonical source",
      target: placement(UNIT_A, "shape"),
    };
    const same = loadedComparison(placement(UNIT_A), sameChoice);
    await harness.render(centerElement(workspace, selection, same.state, same.selected));
    assert.deepEqual(sourceUrls, ["/api/source?unit=unit%3Aa"]);
    assert.equal(harness.container.querySelectorAll(".comparison-pane").length, 2);
    assert.equal(harness.container.querySelectorAll(".comparison-header").length, 2);
    assert.match(harness.container.textContent ?? "", /No differences in current content/);
    assert.equal(harness.container.querySelectorAll(".comparison-added").length, 0);
    assert.equal(harness.container.querySelectorAll(".comparison-removed").length, 0);

    sourceUrls.length = 0;
    sources = new Map([
      [UNIT_A.id, source(UNIT_A, "before\nleft only\n")],
      [UNIT_B.id, source(UNIT_B, "before\nright only\n")],
    ]);
    const distinctChoice: ComparisonChoice = {
      label: "Different unit",
      detail: "Different canonical source",
      target: placement(UNIT_B),
    };
    const distinct = loadedComparison(placement(UNIT_A), distinctChoice);
    await harness.render(centerElement(workspace, selection, distinct.state, distinct.selected));
    assert.deepEqual(sourceUrls, ["/api/source?unit=unit%3Ab"]);
    assert.equal(harness.container.querySelector(".comparison-removed")?.textContent, "same\n");
    assert.equal(
      harness.container.querySelector(".comparison-added")?.textContent,
      "before\nright only\n",
    );
    const headers = [...harness.container.querySelectorAll(".comparison-header")].map(
      normalizedText,
    );
    assert.match(headers[0] ?? "", /unit:a/);
    assert.match(headers[1] ?? "", /unit:b/);
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});

test("CenterPane preserves independent source failure states", async () => {
  const harness = installDom();
  const previousFetch = globalThis.fetch;
  const sourceUrls: string[] = [];
  const workspace = new EditWorkspace();
  globalThis.fetch = async (input): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    sourceUrls.push(url);
    if (url.includes("unit%3Aa")) {
      return response(404, { detail: "source missing" });
    }
    return response(200, source(UNIT_C, "target survives\n"));
  };
  const selection: UnitSelection = {
    type: "unit",
    target: { unit: UNIT_A, fragment: null },
    placement: null,
  };
  const choice: ComparisonChoice = {
    label: "Surviving target",
    detail: "Independent target load",
    target: placement(UNIT_C),
  };
  const compared = loadedComparison(placement(UNIT_A), choice);

  try {
    await harness.render(centerElement(workspace, selection, compared.state, compared.selected));
    assert.equal(sourceUrls.length, 2);
    const panes = harness.container.querySelectorAll(".comparison-pane");
    assert.equal(panes.length, 2);
    assert.match(panes[0]?.textContent ?? "", /Source unavailable.*source missing/s);
    assert.match(panes[1]?.textContent ?? "", /Source loaded; waiting for the other side/);
  } finally {
    globalThis.fetch = previousFetch;
    await harness.cleanup();
  }
});
