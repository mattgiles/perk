import { useState } from "react";
import {
  type AssemblyRender,
  type AssemblyRenderedLayer,
  type AssemblyScenario,
  concatenatedText,
  type PresentationControl,
  resolvedPresentation,
  visibleLayers,
} from "./assembly.ts";
import type { AssemblySessionState } from "./assemblySession.ts";
import { BOUNDARY_INFO } from "./boundaries.ts";
import type { Selection, ShapeSelection } from "./selection.ts";

// All repository-derived content renders as JSX text interpolation (escaped
// <pre>/text nodes only — the dom-sinks scan and the pinned CSP backstop).

export type AssemblyPaneCallbacks = {
  chooseScenario: (id: string) => void;
  setOverride: (control: PresentationControl, value: boolean | null) => void;
  rerender: () => void;
};

type ReadyState = Extract<AssemblySessionState, { status: "ready" }>;

function joinBreadcrumb(breadcrumb: ShapeSelection["breadcrumb"]): string {
  return breadcrumb.map((capability) => capability.label).join(" / ");
}

// Total under the parse boundary's non-empty scenarios guarantee: the session only
// ever selects ids drawn from the options.
function selectedScenario(state: ReadyState): AssemblyScenario {
  return (
    state.options.scenarios.find((scenario) => scenario.id === state.scenarioId) ??
    state.options.scenarios[0]
  );
}

function layerTitle(layer: AssemblyRenderedLayer): string {
  if (layer.presentation.label !== null) {
    return layer.presentation.label;
  }
  return layer.type === "boundary" ? layer.boundary : layer.unit.id;
}

function LayerCard({ layer }: { layer: AssemblyRenderedLayer }) {
  return (
    <section className="assembly-layer-card">
      <div className="assembly-layer-header">
        <span className="layer-position">#{layer.presentation.position}</span>
        <span className="assembly-layer-title">{layerTitle(layer)}</span>
        {layer.presentation.presence === "varies" && layer.presentation.presence_label !== null && (
          <span className="presence-badge">{layer.presentation.presence_label}</span>
        )}
        {layer.type === "owned" && <span className="kind-badge">{layer.content_kind}</span>}
        {layer.type === "boundary" && <span className="owner-badge">{layer.owner}</span>}
      </div>
      {layer.type === "owned" &&
        layer.parts.map((part, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a static read-only ordered list — never reordered or locally stateful.
          <div key={index} className="assembly-part">
            {part.fragment !== null && (
              <p className="assembly-part-caption">
                {part.fragment.label} ({part.fragment.id})
              </p>
            )}
            <pre className="assembly-part-text">{part.text}</pre>
          </div>
        ))}
      {layer.type === "boundary" && (
        <div className="assembly-boundary-body">
          <p>
            <strong>Owner:</strong> {BOUNDARY_INFO[layer.boundary].owner}
          </p>
          <p>{BOUNDARY_INFO[layer.boundary].explanation}</p>
        </div>
      )}
      {layer.type === "failure" && (
        <div className="assembly-failure-body">
          <h3>Layer failed to render</h3>
          <ol className="assembly-problem-list">
            {layer.problems.map((problem, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a static read-only ordered list — never reordered or locally stateful.
              <li key={index}>
                {problem.fragment !== null && (
                  <span className="assembly-part-caption">
                    {problem.fragment.label} ({problem.fragment.id}){" "}
                  </span>
                )}
                {problem.detail}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function RenderedLayers({
  state,
  render,
  view,
}: {
  state: ReadyState;
  render: AssemblyRender;
  view: "separate" | "concatenated";
}) {
  // The live derivation source is local state (the response echo is parsed for
  // shape-soundness but never rendered): toggles hide layers without a re-POST.
  const resolved = resolvedPresentation(selectedScenario(state), state.overrides);
  const visible = visibleLayers(render.layers, resolved);
  const hidden = render.layers.length - visible.length;
  return (
    <div className="assembly-rendered">
      {hidden > 0 && (
        <p className="assembly-hidden-note">{hidden} layer(s) hidden by visibility toggles.</p>
      )}
      {view === "separate" ? (
        visible.map((layer) => <LayerCard key={layer.presentation.position} layer={layer} />)
      ) : (
        <>
          {visible.some((layer) => layer.presentation.presence === "varies") && (
            <p className="assembly-varies-note">
              Includes optional layers whose presence varies by session shape or runtime.
            </p>
          )}
          <pre className="assembly-concatenated">{concatenatedText(visible)}</pre>
        </>
      )}
    </div>
  );
}

function ControlBar({
  state,
  view,
  onView,
  callbacks,
}: {
  state: ReadyState;
  view: "separate" | "concatenated";
  onView: (view: "separate" | "concatenated") => void;
  callbacks: AssemblyPaneCallbacks;
}) {
  const resolved = resolvedPresentation(selectedScenario(state), state.overrides);
  return (
    <div className="assembly-control-bar">
      <label className="assembly-scenario-picker">
        Scenario{" "}
        <select
          value={state.scenarioId}
          onChange={(event) => callbacks.chooseScenario(event.currentTarget.value)}
        >
          {state.options.scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.label}
            </option>
          ))}
        </select>
      </label>
      <label className="assembly-toggle">
        <input
          type="checkbox"
          checked={resolved.include_ambient}
          onChange={() => callbacks.setOverride("ambient", !resolved.include_ambient)}
        />{" "}
        Ambient skills
      </label>
      <label className="assembly-toggle">
        <input
          type="checkbox"
          checked={resolved.include_tools}
          onChange={() => callbacks.setOverride("tools", !resolved.include_tools)}
        />{" "}
        Tool contracts
      </label>
      <span className="assembly-view-switch">
        <button type="button" aria-pressed={view === "separate"} onClick={() => onView("separate")}>
          Separate layers
        </button>
        <button
          type="button"
          aria-pressed={view === "concatenated"}
          onClick={() => onView("concatenated")}
        >
          Concatenated
        </button>
      </span>
    </div>
  );
}

function RenderSlotPresentation({
  state,
  view,
  rerender,
}: {
  state: ReadyState;
  view: "separate" | "concatenated";
  rerender: () => void;
}) {
  const slot = state.render;
  if (slot.status === "rendering") {
    return <p className="pane-hint">Rendering assembly…</p>;
  }
  if (slot.status === "render-refused") {
    // Deterministic refusals: copy only — identical re-requests cannot repair them;
    // recovery flows through subject/scenario/buffer/epoch changes.
    return <p className="pane-hint">Assembly render unavailable: {slot.detail}</p>;
  }
  if (slot.status === "render-not-sent") {
    return (
      <p className="pane-hint">
        The render request was not sent: the page is missing its security token. Reload the page.
      </p>
    );
  }
  if (slot.status === "render-failed") {
    // Render never mutates, so an identical retry is safe for transient failures.
    return (
      <div className="assembly-render-failed">
        <p className="pane-hint">Failed to render assembly.</p>
        <button type="button" onClick={rerender}>
          Re-render
        </button>
      </div>
    );
  }
  return <RenderedLayers state={state} render={slot.render} view={view} />;
}

export function AssemblyPane({
  selection,
  state,
  callbacks,
}: {
  selection: Selection | null;
  state: AssemblySessionState;
  callbacks: AssemblyPaneCallbacks;
}) {
  const [view, setView] = useState<"separate" | "concatenated">("separate");
  if (selection?.type !== "shape") {
    return <p className="pane-hint">Select a session shape to preview its assembly.</p>;
  }
  const shape = selection.shape;
  return (
    <div className="assembly-preview">
      <div className="assembly-header">
        <h2>
          {shape.label} <span className="delivery-badge">{shape.delivery}</span>
        </h2>
        <p className="inspector-breadcrumb">{joinBreadcrumb(selection.breadcrumb)}</p>
        <p className="assembly-id">{shape.assembly}</p>
        <p className="assembly-scope-note">
          The rendered set is assembly-wide; a session shape is navigation and breadcrumb only.
        </p>
      </div>
      {(state.status === "idle" || state.status === "loading-options") && (
        <p className="pane-hint">Loading assembly options…</p>
      )}
      {state.status === "options-refused" && (
        <p className="pane-hint">Assembly options unavailable: {state.detail}</p>
      )}
      {state.status === "options-failed" && (
        <p className="pane-hint">Failed to load assembly options.</p>
      )}
      {state.status === "ready" && (
        <>
          <ControlBar state={state} view={view} onView={setView} callbacks={callbacks} />
          <RenderSlotPresentation state={state} view={view} rerender={callbacks.rerender} />
        </>
      )}
    </div>
  );
}
