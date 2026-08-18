import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import * as React from "react";
import { tsImport } from "tsx/esm/api";
import {
  buttonByText,
  type Deferred,
  deferred,
  installDom,
  itemAt,
  normalizedText,
  response,
  stubFetch,
} from "./componentHarness.ts";
import type { AssemblyOptions, AssemblyRender, AssemblyScenario } from "./src/assembly.ts";
import { EditWorkspace, type WorkspaceTransport } from "./src/editWorkspace.ts";
import type { SourceTarget } from "./src/selection.ts";
import type { SourceView } from "./src/source.ts";
import type { CapabilityTree, SessionShape, TreeUnit } from "./src/tree.ts";

const { App } = (await tsImport(
  "./src/App.tsx",
  import.meta.url,
)) as typeof import("./src/App.tsx");

const HOSTILE = "<img src=x onerror=alert(1)> <script>alert(2)</script>";

const UNIT_SKILL: TreeUnit = {
  id: "unit:skill",
  kind: "markdown",
  path: "skill.md",
  fragments: [],
};
const UNIT_A: TreeUnit = { id: "unit:a", kind: "markdown", path: "a.md", fragments: [] };
const SHAPE: SessionShape = {
  id: "shape:warm",
  label: "Warm shape",
  delivery: "warm",
  assembly: "plan-authoring",
  layers: [
    { position: 1, optional: false, label: "System boundary", unit: null, boundary: "pi-system" },
    { position: 2, optional: true, label: "Bound skill", unit: UNIT_SKILL, boundary: null },
  ],
};
const TREE: CapabilityTree = {
  capabilities: [
    {
      id: "planning",
      label: "Planning",
      units: [UNIT_A],
      session_shapes: [SHAPE],
      children: [],
    },
  ],
};

const WARM: AssemblyScenario = {
  id: "scenario:warm",
  label: "Warm defaults",
  variables: { objective: "Ship the preview" },
  include_ambient: true,
  include_tools: true,
};
const COLD: AssemblyScenario = {
  id: "scenario:cold",
  label: "Cold minimal",
  variables: {},
  include_ambient: false,
  include_tools: false,
};
const OPTIONS: AssemblyOptions = { assembly: "plan-authoring", scenarios: [WARM, COLD] };

function assemblyRender(scenario: AssemblyScenario): AssemblyRender {
  return {
    assembly: "plan-authoring",
    scenario,
    presentation: {
      include_ambient: scenario.include_ambient,
      include_tools: scenario.include_tools,
    },
    layers: [
      {
        type: "boundary",
        presentation: {
          position: 1,
          label: "System boundary",
          presence: "always",
          presence_label: null,
          visibility_control: null,
        },
        boundary: "pi-system",
        owner: "pi",
      },
      {
        type: "owned",
        presentation: {
          position: 2,
          label: null,
          presence: "varies",
          presence_label: "Presence varies by session shape or runtime.",
          visibility_control: "ambient",
        },
        unit: UNIT_SKILL,
        content_kind: "rendered-template",
        parts: [{ fragment: { id: "body", label: "Body" }, text: HOSTILE }],
      },
      {
        type: "failure",
        presentation: {
          position: 3,
          label: "Tool contract",
          presence: "always",
          presence_label: null,
          visibility_control: "tools",
        },
        unit: { id: "unit:tool", kind: "typescript-tool", path: "tool.ts" },
        problems: [
          {
            fragment: null,
            reason: "adapter-unavailable",
            detail: "The source adapter could not run safely.",
          },
        ],
      },
    ],
  };
}

function toggleByLabel(container: ParentNode, text: string): HTMLInputElement {
  const label = [...container.querySelectorAll<HTMLLabelElement>("label.assembly-toggle")].find(
    (candidate) => normalizedText(candidate).includes(text),
  );
  assert.ok(label !== undefined, `missing toggle: ${text}`);
  const input = label.querySelector<HTMLInputElement>("input[type=checkbox]");
  assert.ok(input !== null, `toggle has no checkbox: ${text}`);
  return input;
}

function scenarioSelect(container: ParentNode): HTMLSelectElement {
  const select = container.querySelector<HTMLSelectElement>(".assembly-scenario-picker select");
  assert.ok(select !== null, "missing scenario picker");
  return select;
}

test("Assembly preview: controls, local visibility, concatenated view, scenario switch, lifecycle", async () => {
  const harness = installDom({ csrfToken: "test-token" });
  const optionsRequests: Deferred<Response>[] = [];
  const renderRequests: { body: unknown; request: Deferred<Response> }[] = [];
  const restoreFetch = stubFetch(async (url, init): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/assembly/options?")) {
      assert.equal(url, "/api/assembly/options?assembly=plan-authoring");
      const request = deferred<Response>();
      optionsRequests.push(request);
      return request.promise;
    }
    if (url === "/api/assembly/render") {
      const request = deferred<Response>();
      renderRequests.push({ body: JSON.parse(String(init?.body)), request });
      return request.promise;
    }
    throw new Error(`unexpected request: ${url}`);
  });

  try {
    await harness.render(React.createElement(App));
    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    await harness.click(buttonByText(harness.container, "Assembly"));
    assert.equal(optionsRequests.length, 1);
    assert.match(harness.container.textContent ?? "", /Loading assembly options…/);
    assert.match(harness.container.textContent ?? "", /navigation and breadcrumb only/);
    assert.match(harness.container.textContent ?? "", /plan-authoring/);

    itemAt(optionsRequests, 0).resolve(response(200, OPTIONS));
    await harness.settle();
    assert.equal(scenarioSelect(harness.container).value, WARM.id);
    assert.equal(scenarioSelect(harness.container).querySelectorAll("option").length, 2);
    assert.match(harness.container.textContent ?? "", /Rendering assembly…/);
    assert.equal(renderRequests.length, 1);
    assert.deepEqual(itemAt(renderRequests, 0).body, {
      assembly: "plan-authoring",
      scenario: WARM.id,
      presentation: { include_ambient: null, include_tools: null },
      buffers: [],
    });

    itemAt(renderRequests, 0).request.resolve(response(200, assemblyRender(WARM)));
    await harness.settle();
    const cards = harness.container.querySelectorAll(".assembly-layer-card");
    assert.equal(cards.length, 3);
    assert.match(normalizedText(itemAt(cards, 0)), /#1.*System boundary.*pi/);
    assert.match(normalizedText(itemAt(cards, 1)), /#2.*unit:skill/);
    assert.match(normalizedText(itemAt(cards, 1)), /Presence varies by session shape or runtime\./);
    assert.match(normalizedText(itemAt(cards, 1)), /rendered-template/);
    assert.match(normalizedText(itemAt(cards, 1)), /Body \(body\)/);
    assert.match(normalizedText(itemAt(cards, 2)), /Layer failed to render/);
    assert.match(normalizedText(itemAt(cards, 2)), /The source adapter could not run safely\./);
    // Hostile repository text is literal text, never markup.
    assert.equal(harness.container.querySelectorAll("img, script").length, 0);
    assert.ok((harness.container.textContent ?? "").includes(HOSTILE));
    // The inspector shows the read-only scenario variables and the assembly identity.
    assert.match(harness.container.textContent ?? "", /Scenario variables \(read-only\)/);
    assert.match(harness.container.textContent ?? "", /objective/);
    assert.match(harness.container.textContent ?? "", /Ship the preview/);

    // Unchecking a visibility toggle hides exactly the matching layers — no POST.
    await harness.click(toggleByLabel(harness.container, "Ambient skills"));
    assert.equal(renderRequests.length, 1, "visibility toggles never re-POST");
    const visibleCards = harness.container.querySelectorAll(".assembly-layer-card");
    assert.equal(visibleCards.length, 2);
    assert.doesNotMatch(normalizedText(itemAt(visibleCards, 1)), /unit:skill/);
    assert.match(
      harness.container.textContent ?? "",
      /1 layer\(s\) hidden by visibility toggles\./,
    );

    // Concatenated view: exact fixed markers, hidden layers excluded.
    await harness.click(buttonByText(harness.container, "Concatenated"));
    assert.equal(
      harness.container.querySelector(".assembly-concatenated")?.textContent,
      "[[ boundary: System boundary · owner: pi ]]\n\n[[ layer failed: unit:tool ]]",
    );

    // Scenario switch: one new POST with reset (null) overrides.
    await harness.selectOption(scenarioSelect(harness.container), COLD.id);
    assert.equal(renderRequests.length, 2);
    assert.deepEqual(itemAt(renderRequests, 1).body, {
      assembly: "plan-authoring",
      scenario: COLD.id,
      presentation: { include_ambient: null, include_tools: null },
      buffers: [],
    });
    itemAt(renderRequests, 1).request.resolve(response(200, assemblyRender(COLD)));
    await harness.settle();
    // Cold defaults hide both controlled layers; the view switch survives.
    assert.equal(
      harness.container.querySelector(".assembly-concatenated")?.textContent,
      "[[ boundary: System boundary · owner: pi ]]",
    );
    assert.match(
      harness.container.textContent ?? "",
      /2 layer\(s\) hidden by visibility toggles\./,
    );

    // Non-shape selection: fixed hint, mode preserved, no new fetches.
    await harness.click(buttonByText(harness.container, UNIT_A.id));
    assert.equal(buttonByText(harness.container, "Assembly").ariaPressed, "true");
    assert.match(
      harness.container.textContent ?? "",
      /Select a session shape to preview its assembly\./,
    );
    assert.equal(optionsRequests.length, 1);
    assert.equal(renderRequests.length, 2);

    // Re-selecting the shape re-opens the session (fresh fetch, defaults restored).
    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    assert.equal(optionsRequests.length, 2);
    itemAt(optionsRequests, 1).resolve(response(200, OPTIONS));
    await harness.settle();
    assert.equal(renderRequests.length, 3);
    itemAt(renderRequests, 2).request.resolve(response(200, assemblyRender(WARM)));
    await harness.settle();
    assert.equal(harness.container.querySelectorAll(".assembly-layer-card").length, 3);

    // The Tool contracts toggle works independently: it hides exactly its
    // control-matching layer, leaves the ambient toggle untouched, and never POSTs.
    await harness.click(toggleByLabel(harness.container, "Tool contracts"));
    assert.equal(renderRequests.length, 3, "the tools toggle never re-POSTs");
    const afterToolsCards = harness.container.querySelectorAll(".assembly-layer-card");
    assert.equal(afterToolsCards.length, 2);
    assert.doesNotMatch(harness.container.textContent ?? "", /Layer failed to render/);
    assert.match(normalizedText(itemAt(afterToolsCards, 1)), /unit:skill/);
    assert.equal(toggleByLabel(harness.container, "Tool contracts").checked, false);
    assert.equal(toggleByLabel(harness.container, "Ambient skills").checked, true);
    assert.match(
      harness.container.textContent ?? "",
      /1 layer\(s\) hidden by visibility toggles\./,
    );

    // Mode exit clears; re-entry refetches.
    await harness.click(buttonByText(harness.container, "Edit"));
    assert.equal(harness.container.querySelectorAll(".assembly-layer-card").length, 0);
    await harness.click(buttonByText(harness.container, "Assembly"));
    assert.equal(optionsRequests.length, 3, "re-entering Assembly starts a fresh session");
    assert.match(harness.container.textContent ?? "", /Loading assembly options…/);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("Re-render retries only transient failures; refusals stay copy-only", async () => {
  const harness = installDom({ csrfToken: "test-token" });
  const renderRequests: Deferred<Response>[] = [];
  const restoreFetch = stubFetch(async (url): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/assembly/options?")) {
      return response(200, OPTIONS);
    }
    if (url === "/api/assembly/render") {
      const request = deferred<Response>();
      renderRequests.push(request);
      return request.promise;
    }
    throw new Error(`unexpected request: ${url}`);
  });

  const noRerenderButton = () =>
    [...harness.container.querySelectorAll("button")].every(
      (button) => normalizedText(button) !== "Re-render",
    );

  try {
    await harness.render(React.createElement(App));
    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    await harness.click(buttonByText(harness.container, "Assembly"));
    await harness.settle();
    assert.equal(renderRequests.length, 1);

    // A transient failure offers exactly one explicit retry affordance.
    itemAt(renderRequests, 0).resolve(response(500, { detail: "boom" }));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Failed to render assembly\./);
    assert.equal(renderRequests.length, 1, "failure alone must not auto-retry");
    await harness.click(buttonByText(harness.container, "Re-render"));
    assert.equal(renderRequests.length, 2, "Re-render issues exactly one new POST");

    // A deterministic refusal is copy-only: no retry button, no further POSTs.
    itemAt(renderRequests, 1).resolve(response(409, { detail: "catalog stale" }));
    await harness.settle();
    assert.match(harness.container.textContent ?? "", /Assembly render unavailable: catalog stale/);
    assert.ok(noRerenderButton(), "refusals must not offer a retry affordance");
    assert.equal(renderRequests.length, 2);
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("a tokenless page reports render-not-sent without POSTing", async () => {
  const harness = installDom();
  let renderPosts = 0;
  const restoreFetch = stubFetch(async (url): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/assembly/options?")) {
      return response(200, OPTIONS);
    }
    if (url === "/api/assembly/render") {
      renderPosts += 1;
      return response(200, assemblyRender(WARM));
    }
    throw new Error(`unexpected request: ${url}`);
  });

  try {
    await harness.render(React.createElement(App));
    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    await harness.click(buttonByText(harness.container, "Assembly"));
    await harness.settle();
    assert.match(
      harness.container.textContent ?? "",
      /The render request was not sent: the page is missing its security token\. Reload the page\./,
    );
    assert.equal(renderPosts, 0, "a missing token must never POST");
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});

test("a workspace buffer edit re-renders the preview exactly once with the updated text", async () => {
  const harness = installDom({ csrfToken: "test-token" });
  const UNIT_DOC: TreeUnit = {
    id: "unit:doc",
    kind: "markdown",
    path: "doc.md",
    fragments: [{ id: "a", label: "Fragment A" }],
  };
  const TARGET_DOC: SourceTarget = { unit: UNIT_DOC, fragment: { id: "a", label: "Fragment A" } };
  const view: SourceView = {
    unit: UNIT_DOC.id,
    fragment: TARGET_DOC.fragment,
    kind: UNIT_DOC.kind,
    before: "line ",
    focus: "A",
    after: " end",
    editable: true,
    read_only_reason: null,
  };
  const transport: WorkspaceTransport = {
    load: () =>
      Promise.resolve({
        status: "loaded",
        source: {
          file: {
            path: UNIT_DOC.path,
            mode: 0o644,
            newline_style: "lf",
            load_hash: "0123456789abcdef".repeat(4),
          },
          view,
        },
      }),
    project: () => Promise.resolve({ status: "failed" }),
  };
  const workspace = new EditWorkspace(transport);

  const renderBodies: unknown[] = [];
  const restoreFetch = stubFetch(async (url, init): Promise<Response> => {
    if (url === "/api/catalog/tree") {
      return response(200, TREE);
    }
    if (url.startsWith("/api/inspect?")) {
      return response(404, { detail: "unknown unit" });
    }
    if (url.startsWith("/api/assembly/options?")) {
      return response(200, { assembly: "plan-authoring", scenarios: [WARM] });
    }
    if (url === "/api/assembly/render") {
      renderBodies.push(JSON.parse(String(init?.body)));
      return response(200, {
        assembly: "plan-authoring",
        scenario: WARM,
        presentation: { include_ambient: true, include_tools: true },
        layers: [],
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });

  try {
    // The decision-12 seam: App renders with exactly this injected instance.
    await harness.render(React.createElement(App, { workspace }));
    await React.act(async () => {
      assert.equal((await workspace.ensure(TARGET_DOC)).status, "loaded");
      await tick();
    });

    await harness.click(buttonByText(harness.container, "Warm shape warm"));
    await harness.click(buttonByText(harness.container, "Assembly"));
    await harness.settle();
    assert.deepEqual(renderBodies, [
      {
        assembly: "plan-authoring",
        scenario: WARM.id,
        presentation: { include_ambient: null, include_tools: null },
        buffers: [{ path: "doc.md", text: "line A end" }],
      },
    ]);

    await React.act(async () => {
      const source = workspace.inspect(TARGET_DOC);
      assert.ok(source?.editor !== null && source?.editor !== undefined);
      assert.deepEqual(
        workspace.editFocus({ target: TARGET_DOC, base: source.editor, nextDisplay: "EDITED" }),
        { status: "applied" },
      );
      await tick();
    });
    await harness.settle();
    assert.equal(renderBodies.length, 2, "one buffer edit issues exactly one re-render");
    assert.deepEqual(renderBodies[1], {
      assembly: "plan-authoring",
      scenario: WARM.id,
      presentation: { include_ambient: null, include_tools: null },
      buffers: [{ path: "doc.md", text: "line EDITED end" }],
    });
  } finally {
    restoreFetch();
    await harness.cleanup();
  }
});
