// Rendered coverage for the check surfaces: the CenterPane suggested-check Run
// buttons and the workspace drawer's Checks section (notice line, running/terminal
// rows, lazy output mount, hostile output as literal text). The session mechanics
// themselves are covered in checkSession.test.ts; here the real App wiring runs
// against a stubbed fetch.

import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { tsImport } from "tsx/esm/api";
import {
  buttonByLabel,
  buttonByText,
  installDom as installSharedDom,
  type RenderHarness,
  response,
  stubFetch,
} from "./componentHarness.ts";
import type { CheckRun } from "./src/checks.ts";
import type { SourceTarget } from "./src/selection.ts";
import type { SourceView, UnitSource } from "./src/source.ts";
import type { CapabilityTree, TreeUnit } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");

const UNIT_A: TreeUnit = {
  id: "unit:a",
  kind: "markdown",
  path: "shared.md",
  fragments: [{ id: "a", label: "Fragment A" }],
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "foundation",
      label: "Foundation",
      units: [UNIT_A],
      session_shapes: [],
      children: [],
    },
  ],
};
const HOSTILE_OUTPUT = 'error: <script>alert(1)</script><img src="x" onerror="alert(2)">\n';

function installDom(): RenderHarness {
  return installSharedDom({ csrfToken: "test-token" });
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

function load(target: SourceTarget, view: SourceView): UnitSource {
  return {
    file: {
      path: target.unit.path,
      mode: 0o644,
      newline_style: "lf",
      load_hash: "0123456789abcdef".repeat(4),
    },
    view,
  };
}

function runPayload(overrides: Partial<CheckRun>): CheckRun {
  return {
    run: "run-A",
    check: "prose-map",
    label: "Prose map check",
    command: "uv run --no-sync perk-dev prose-map check",
    status: "running",
    exit_code: null,
    output: "",
    next_offset: 0,
    truncated: false,
    ...overrides,
  };
}

function textarea(container: ParentNode): HTMLTextAreaElement {
  const editor = container.querySelector<HTMLTextAreaElement>("textarea");
  assert.ok(editor !== null, "missing source textarea");
  return editor;
}

function drawer(container: ParentNode): HTMLElement {
  const element = container.querySelector<HTMLElement>(".workspace-drawer");
  assert.ok(element !== null, "the drawer is not open");
  return element;
}

function checkRows(container: ParentNode): HTMLElement[] {
  return [...drawer(container).querySelectorAll<HTMLElement>("li.check-run")];
}

function rowByText(container: ParentNode, needle: string): HTMLElement {
  const row = checkRows(container).find((candidate) =>
    (candidate.textContent ?? "").includes(needle),
  );
  assert.ok(row !== undefined, `missing check row containing: ${needle}`);
  return row;
}

async function openOutput(harness: RenderHarness, row: HTMLElement): Promise<HTMLElement> {
  const summary = row.querySelector("summary");
  assert.ok(summary !== null);
  await harness.click(summary);
  // jsdom queues the details toggle task beyond setImmediate: poll briefly until
  // React's onToggle has run and the lazy <pre> mounted.
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const output = row.querySelector<HTMLElement>(".check-run-output");
    if (output !== null) {
      return output;
    }
    await React.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  assert.fail("output did not mount after opening");
}

test("suggested-check Run buttons and the drawer Checks section cover the run lifecycle", async () => {
  const harness = installDom();
  const text = "before A after";
  const startResponses: Response[] = [];
  const startBodies: unknown[] = [];
  let startHeaders: Record<string, string> | undefined;
  let cancelHeaders: Record<string, string> | undefined;
  let pollResponse: () => Response = () =>
    response(200, runPayload({ status: "running", output: "", next_offset: 6 }));
  const restoreFetch = stubFetch(async (url, init): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/source?")) {
      const target: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[0] ?? null };
      return response(200, load(target, editableView(target, text, "A")));
    }
    if (url === "/api/source/project") {
      const body = JSON.parse(String(init?.body)) as { text: string };
      const target: SourceTarget = { unit: UNIT_A, fragment: UNIT_A.fragments[0] ?? null };
      return response(200, editableView(target, body.text, "saved A"));
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
            load_hash: "a".repeat(64),
          },
        },
        materialized: [],
        checks: [{ id: "prose-map", command: "uv run --no-sync perk-dev prose-map check" }],
        catalog_refreshed: true,
        refresh_detail: null,
      });
    }
    if (url === "/api/checks/latest") {
      return response(200, { run: null });
    }
    if (url === "/api/checks/run" && init?.method === "POST") {
      startHeaders = init.headers as Record<string, string>;
      startBodies.push(JSON.parse(String(init.body)));
      const next = startResponses.shift();
      assert.ok(next !== undefined, "unexpected check start");
      return next;
    }
    if (url === "/api/checks/run/run-A/cancel") {
      cancelHeaders = init?.headers as Record<string, string>;
      // The acknowledgment body is ignored by the session.
      return response(200, runPayload({ status: "cancelled", output: "IGNORED" }));
    }
    if (url.startsWith("/api/checks/run/run-A?")) {
      return pollResponse();
    }
    throw new Error(`unexpected request: ${url}`);
  });

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
    assert.match(harness.container.textContent ?? "", /Suggested checks/);
    assert.equal(harness.container.querySelector(".workspace-drawer"), null);

    // A refused start opens the drawer and shows the notice with an empty history.
    startResponses.push(response(409, { detail: "check already running" }));
    await harness.click(buttonByText(harness.container, "Run"));
    await harness.settle();
    assert.deepEqual(startBodies.at(-1), { check: "prose-map" });
    assert.equal(startHeaders?.["X-Prose-Review-Csrf"], "test-token");
    assert.match(drawer(harness.container).textContent ?? "", /A check is already running\./);
    assert.equal(checkRows(harness.container).length, 0);
    assert.equal(buttonByText(harness.container, "Run").disabled, false);

    // A successful start adopts the running row: Cancel, no Run again, notice cleared.
    startResponses.push(
      response(200, runPayload({ status: "running", output: "hello\n", next_offset: 6 })),
    );
    await harness.click(buttonByText(harness.container, "Run"));
    await harness.settle();
    assert.doesNotMatch(drawer(harness.container).textContent ?? "", /already running/);
    const runningRow = rowByText(harness.container, "Prose map check");
    assert.match(runningRow.textContent ?? "", /Running/);
    assert.match(runningRow.textContent ?? "", /uv run --no-sync perk-dev prose-map check/);
    buttonByText(runningRow, "Cancel");
    assert.equal(
      [...runningRow.querySelectorAll("button")].some(
        (button) => button.textContent === "Run again",
      ),
      false,
    );
    assert.equal(buttonByText(harness.container, "Run").disabled, true);

    // The output <pre> mounts only once the details row is opened.
    assert.equal(runningRow.querySelector(".check-run-output"), null);
    const runningOutput = await openOutput(harness, runningRow);
    assert.equal(runningOutput.textContent, "hello\n");

    // Cancel posts with the CSRF header; the polling loop retires the run.
    pollResponse = () =>
      response(200, runPayload({ status: "cancelled", output: "", next_offset: 6 }));
    await harness.click(buttonByText(runningRow, "Cancel"));
    await harness.settle();
    assert.equal(cancelHeaders?.["X-Prose-Review-Csrf"], "test-token");
    await React.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 650));
    });
    await harness.settle();
    const cancelledRow = rowByText(harness.container, "Cancelled");
    buttonByText(cancelledRow, "Run again");
    assert.doesNotMatch(cancelledRow.textContent ?? "", /IGNORED/);
    assert.equal(buttonByText(harness.container, "Run").disabled, false);

    // Run again re-posts; a terminal response lands straight in history with its
    // exit code, the truncation marker, and hostile output as literal text.
    startResponses.push(
      response(
        200,
        runPayload({
          run: "run-B",
          status: "failed",
          exit_code: 3,
          output: HOSTILE_OUTPUT,
          next_offset: HOSTILE_OUTPUT.length,
          truncated: true,
        }),
      ),
    );
    await harness.click(buttonByText(cancelledRow, "Run again"));
    await harness.settle();
    assert.deepEqual(startBodies.at(-1), { check: "prose-map" });
    assert.equal(checkRows(harness.container).length, 2);
    const failedRow = rowByText(harness.container, "exit 3");
    assert.match(failedRow.textContent ?? "", /Failed/);
    assert.match(failedRow.textContent ?? "", /Output truncated\./);
    const failedOutput = await openOutput(harness, failedRow);
    assert.equal(failedOutput.textContent, HOSTILE_OUTPUT);
    assert.equal(drawer(harness.container).querySelectorAll("script").length, 0);
    assert.equal(drawer(harness.container).querySelectorAll("img").length, 0);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});
