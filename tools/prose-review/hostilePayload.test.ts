// The cross-pane hostile-payload acceptance walk (PRD §11): ONE shared payload
// constant flows through all five named panes of a single mounted App — source
// (editor context + textarea), diff (the full-file save review AND a drawer Git
// diff row through the default literal-text view), error (validation diagnostics
// + refusal detail — wire data is untrusted even when real servers send fixed
// copy), preview (Assembly separate layer card + concatenated view), and check
// output (the lazily-mounted drawer <pre>). At every stop the payload must render
// as literal text and never materialize an element. The scattered per-component
// hostile tests stay untouched; this file is the end-to-end acceptance walk.

import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { tsImport } from "tsx/esm/api";
import {
  buttonByLabel,
  buttonByText,
  buttonStartingWith,
  installDom,
  type RenderHarness,
  response,
  stubFetch,
} from "./componentHarness.ts";
import type { SourceView, UnitSource } from "./src/source.ts";
import type { CapabilityTree, SessionShape, TreeUnit } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");

// One payload, every escaping trap at once: HTML elements with event handlers,
// both template vocabularies, and both quote styles.
// The escaped \${ keeps the ${evil} placeholder literal — it must reach the DOM
// uninterpolated.
const HOSTILE = `<script>alert(1)</script><img src=x onerror=alert(2)> {{ evil }} \${evil} "q" 's'`;

const UNIT_H: TreeUnit = {
  id: "unit:hostile",
  kind: "markdown",
  path: "hostile.md",
  fragments: [{ id: "body", label: "Body" }],
};
const SHAPE: SessionShape = {
  id: "shape:hostile",
  label: "Hostile shape",
  delivery: "warm",
  assembly: "plan-authoring",
  layers: [{ position: 1, optional: false, label: null, unit: UNIT_H, boundary: null }],
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "foundation",
      label: "Foundation",
      units: [UNIT_H],
      session_shapes: [SHAPE],
      children: [],
    },
  ],
};

const BEFORE = `before ${HOSTILE}\n`;
const FOCUS = `focus ${HOSTILE}`;
const AFTER = `\nafter ${HOSTILE}\n`;
const TEXT = BEFORE + FOCUS + AFTER;

const VALIDATION_MESSAGE = `missing heading ${HOSTILE}`;
const REFUSAL_DETAIL = `refused ${HOSTILE}`;
const GIT_DIFF = `+git ${HOSTILE}\n`;
const CHECK_OUTPUT = `check output ${HOSTILE}\n`;
const ASSEMBLY_PART = `part ${HOSTILE}\n`;

const SCENARIO = {
  id: "scenario:one",
  label: "Scenario one",
  variables: {},
  include_ambient: true,
  include_tools: true,
};

// The focus slice is delimited by fixed markers so projections over edited
// current text stay total without duplicating the boundary-map logic.
function viewOf(current: string): SourceView {
  const start = current.indexOf("focus ");
  const end = current.indexOf("\nafter ");
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return {
    unit: UNIT_H.id,
    fragment: UNIT_H.fragments[0] ?? null,
    kind: UNIT_H.kind,
    before: current.slice(0, start),
    focus: current.slice(start, end),
    after: current.slice(end),
    editable: true,
    read_only_reason: null,
  };
}

function sourceBody(current: string): UnitSource {
  return {
    file: {
      path: UNIT_H.path,
      mode: 0o644,
      newline_style: "lf",
      load_hash: "0123456789abcdef".repeat(4),
    },
    view: viewOf(current),
  };
}

function checkRunBody(status: "running" | "passed"): Record<string, unknown> {
  return {
    run: "run-hostile",
    check: "prose-map",
    label: "Prose map check",
    command: "uv run --no-sync perk-dev prose-map check",
    status,
    exit_code: status === "passed" ? 0 : null,
    // The adoption read starts at offset 0 with the full captured output; the
    // terminal poll appends nothing beyond it.
    output: status === "running" ? CHECK_OUTPUT : "",
    next_offset: CHECK_OUTPUT.length,
    truncated: false,
  };
}

function assemblyRenderBody(): Record<string, unknown> {
  return {
    assembly: "plan-authoring",
    scenario: SCENARIO,
    presentation: { include_ambient: true, include_tools: true },
    layers: [
      {
        type: "owned",
        presentation: {
          position: 1,
          label: null,
          presence: "always",
          presence_label: null,
          visibility_control: null,
        },
        unit: UNIT_H,
        content_kind: "rendered-template",
        parts: [{ fragment: { id: "body", label: "Body" }, text: ASSEMBLY_PART }],
      },
    ],
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

async function settleUntil(predicate: () => boolean, message: string): Promise<void> {
  // jsdom queues details toggles and the 500ms check poll beyond setImmediate:
  // poll in short act windows so async state updates land inside act.
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) {
      return;
    }
    await React.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  assert.fail(message);
}

async function openDetailsRow(
  harness: RenderHarness,
  row: HTMLElement,
  selector: string,
): Promise<HTMLElement> {
  const summary = row.querySelector("summary");
  assert.ok(summary !== null);
  await harness.click(summary);
  let mounted: HTMLElement | null = null;
  await settleUntil(() => {
    mounted = row.querySelector<HTMLElement>(selector);
    return mounted !== null;
  }, `${selector} never mounted after opening the row`);
  assert.ok(mounted !== null);
  return mounted;
}

test("one hostile payload stays literal across source, diff, error, preview, and check panes", async () => {
  const harness = installDom({ csrfToken: "test-token" });

  // Vacuousness guard: the same payload, parsed as markup, WOULD materialize
  // elements — so the script/img queries below are able to fail.
  const probe = harness.window.document.createElement("div");
  probe.innerHTML = HOSTILE;
  assert.ok(probe.querySelector("script, img") !== null, "the vacuousness probe found no element");

  function assertLiteral(where: string): void {
    assert.equal(
      harness.container.querySelectorAll("script, img").length,
      0,
      `an element was materialized from the payload at the ${where}`,
    );
  }

  const saveResults: Record<string, unknown>[] = [
    {
      status: "validation-failed",
      diagnostics: [
        {
          code: "selector-not-found",
          message: VALIDATION_MESSAGE,
          // A non-syntax diagnostic must carry its selector (the parse boundary
          // pins that pairing); the hostile payload rides the free-text message.
          selector: "heading:missing",
          line: null,
          column: null,
        },
      ],
    },
    { status: "refused", reason: "unsafe-lineage", detail: REFUSAL_DETAIL },
  ];
  let currentText = TEXT;
  const restoreFetch = stubFetch(async (url, init): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/source?")) {
      return response(200, sourceBody(currentText));
    }
    if (url === "/api/source/project") {
      const body = JSON.parse(String(init?.body)) as { text: string };
      return response(200, viewOf(body.text));
    }
    if (url === "/api/source/save") {
      const result = saveResults.shift();
      assert.ok(result !== undefined, "unexpected save request");
      return response(200, result);
    }
    if (url === "/api/git/status") {
      return response(200, {
        status: "available",
        reason: null,
        entries: [{ path: UNIT_H.path, state: "modified" }],
        other_change_count: 0,
      });
    }
    if (url.startsWith("/api/git/diff?")) {
      return response(200, { status: "available", reason: null, diff: GIT_DIFF, truncated: false });
    }
    if (url === "/api/checks/latest") {
      return response(200, { run: checkRunBody("running") });
    }
    if (url.startsWith("/api/checks/run/run-hostile?")) {
      return response(200, checkRunBody("passed"));
    }
    if (url.startsWith("/api/assembly/options?")) {
      return response(200, { assembly: "plan-authoring", scenarios: [SCENARIO] });
    }
    if (url === "/api/assembly/render") {
      return response(200, assemblyRenderBody());
    }
    throw new Error(`unexpected request: ${url}`);
  });

  try {
    await harness.render(React.createElement(App));
    await harness.settle();

    // 1. Source pane: escaped context regions + the literal focus textarea.
    await harness.click(buttonByLabel(harness.container, `Expand fragments for ${UNIT_H.id}`));
    await harness.click(buttonByText(harness.container, "Body"));
    await harness.settle();
    const contexts = [
      ...harness.container.querySelectorAll<HTMLElement>(".source-edit-regions .source-context"),
    ];
    assert.equal(contexts.length, 2);
    for (const context of contexts) {
      assert.ok((context.textContent ?? "").includes(HOSTILE));
    }
    assert.equal(textarea(harness.container).value, FOCUS);
    assertLiteral("source pane");

    // 2a. Diff pane, save review: the full-file diff renders the payload literally.
    await harness.input(textarea(harness.container), `${FOCUS} EDITED`);
    currentText = `${BEFORE}${FOCUS} EDITED${AFTER}`;
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    const saveDiff = harness.container.querySelector(".save-diff");
    assert.ok(saveDiff !== null);
    assert.ok((saveDiff.textContent ?? "").includes(HOSTILE));
    assertLiteral("save-review diff");

    // 3a. Error pane, validation diagnostics: the wire message is literal text.
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    await harness.settle();
    const validation = harness.container.querySelector(".save-validation");
    assert.ok(validation !== null);
    assert.ok((validation.textContent ?? "").includes(VALIDATION_MESSAGE));
    assertLiteral("validation diagnostics");

    // 3b. Error pane, refusal detail: the wire detail is literal text.
    await harness.input(textarea(harness.container), `${FOCUS} EDITED TWICE`);
    currentText = `${BEFORE}${FOCUS} EDITED TWICE${AFTER}`;
    await harness.click(buttonByText(harness.container, "Review full-file diff"));
    await harness.click(buttonByText(harness.container, "Save reviewed file"));
    await harness.settle();
    await harness.settle();
    const refused = harness.container.querySelector(".save-refused");
    assert.ok(refused !== null);
    assert.ok((refused.textContent ?? "").includes(REFUSAL_DETAIL));
    assertLiteral("refusal detail");

    // 2b. Diff pane, drawer Git row: the default literal-text view.
    await harness.click(buttonStartingWith(harness.container, "Workspace ("));
    const gitRow = [
      ...drawer(harness.container).querySelectorAll<HTMLElement>("li.git-change"),
    ].find((candidate) => (candidate.textContent ?? "").includes(UNIT_H.path));
    assert.ok(gitRow !== undefined, "missing git change row");
    const gitRaw = await openDetailsRow(harness, gitRow, ".git-diff-raw");
    assert.equal(gitRaw.textContent, GIT_DIFF);
    assertLiteral("drawer git diff");

    // 5. Check-output pane: the mount-adopted run's streamed output is literal
    // text in the lazily-mounted <pre>.
    await settleUntil(
      () => (drawer(harness.container).textContent ?? "").includes("Passed"),
      "the adopted check run never reached its terminal status",
    );
    const checkRow = [
      ...drawer(harness.container).querySelectorAll<HTMLElement>("li.check-run"),
    ].find((candidate) => (candidate.textContent ?? "").includes("Prose map check"));
    assert.ok(checkRow !== undefined, "missing check run row");
    const checkOutput = await openDetailsRow(harness, checkRow, ".check-run-output");
    assert.equal(checkOutput.textContent, CHECK_OUTPUT);
    assertLiteral("check output");

    // 4. Preview pane: the Assembly separate layer card and concatenated view.
    await harness.click(buttonByText(harness.container, "Hostile shape warm"));
    await harness.click(buttonByText(harness.container, "Assembly"));
    await harness.settle();
    const partText = harness.container.querySelector(".assembly-layer-card .assembly-part-text");
    assert.ok(partText !== null);
    assert.equal(partText.textContent, ASSEMBLY_PART);
    assertLiteral("assembly layer card");
    await harness.click(buttonByText(harness.container, "Concatenated"));
    assert.equal(
      harness.container.querySelector(".assembly-concatenated")?.textContent,
      ASSEMBLY_PART,
    );
    assertLiteral("assembly concatenated view");

    // The exact payload string reached the page as text.
    assert.ok((harness.container.textContent ?? "").includes(HOSTILE));
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});
