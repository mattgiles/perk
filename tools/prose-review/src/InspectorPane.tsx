import { useEffect, useState } from "react";
import type { Mode, Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import { comparisonChoiceKey, type SelectedComparison } from "./comparison.ts";
import type { ComparisonLoadState } from "./comparisonLoad.ts";
import type { CapabilityRef, UnitInspect } from "./inspect.ts";
import { createInspectLoader, type InspectLoadState } from "./inspectLoad.ts";
import { placedShapeLayerSelection, type SourceTarget, wholeUnitTarget } from "./selection.ts";

type SelectSource = (target: SourceTarget) => void;
type SelectSelection = (selection: Selection) => void;

function joinBreadcrumb(breadcrumb: CapabilityRef[]): string {
  return breadcrumb.map((capability) => capability.label).join(" / ");
}

// Every relation section is omitted when empty (no "Consumers (0)" noise); the
// identity block always renders.
function Relationships({ detail, onSelect }: { detail: UnitInspect; onSelect: SelectSource }) {
  return (
    <>
      {detail.capability_children.length > 0 && (
        <section className="inspector-section">
          <h3>Child capabilities</h3>
          <ul className="inspector-list">
            {detail.capability_children.map((capability) => (
              <li key={capability.id}>{capability.label}</li>
            ))}
          </ul>
        </section>
      )}
      {detail.consumers.length > 0 && (
        <section className="inspector-section">
          <h3>Consumers</h3>
          <ul className="inspector-list">
            {detail.consumers.map((consumer) => (
              <li key={`${consumer.assembly}:${consumer.position}`} className="consumer-row">
                <span className="consumer-assembly">{consumer.assembly}</span>
                <span className="layer-position">#{consumer.position}</span>
                {consumer.label !== null && <span>{consumer.label}</span>}
                {consumer.optional && <span className="optional-badge">optional</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {detail.shapes.length > 0 && (
        <section className="inspector-section">
          <h3>Consumed by shapes</h3>
          {detail.shapes.map((shape) => (
            <div key={shape.id} className="inspector-block">
              <p className="inspector-block-title">
                {shape.label} <span className="delivery-badge">{shape.delivery}</span>
              </p>
              <p className="inspector-breadcrumb">{joinBreadcrumb(shape.breadcrumb)}</p>
              {shape.siblings.length > 0 && (
                <>
                  <h4>Delivery siblings</h4>
                  <ul className="inspector-list">
                    {shape.siblings.map((sibling) => (
                      <li key={sibling.id}>
                        {sibling.label} <span className="delivery-badge">{sibling.delivery}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ))}
        </section>
      )}
      {detail.concerns.length > 0 && (
        <section className="inspector-section">
          <h3>Concerns</h3>
          {detail.concerns.map((concern) => (
            <div key={concern.id} className="inspector-block">
              <p className="inspector-block-title">{concern.label}</p>
              <p>{concern.summary}</p>
              <p className="concern-standing">
                This unit: {concern.canonical ? "canonical" : (concern.relation ?? "related")}
              </p>
              {concern.members.length > 0 && (
                <ul className="inspector-list">
                  {concern.members.map((member) => (
                    <li key={member.unit.id}>
                      <button
                        type="button"
                        className="relation-entry"
                        onClick={() => onSelect(wholeUnitTarget(member.unit))}
                      >
                        {member.unit.id}
                      </button>{" "}
                      <span className="relation-note">
                        {member.canonical ? "canonical" : (member.relation ?? "related")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      )}
      {detail.lineage.length > 0 && (
        <section className="inspector-section">
          <h3>Lineage</h3>
          {detail.lineage.map((rule) => (
            <div key={rule.id} className="inspector-block">
              <p className="inspector-block-title">
                <span className="kind-badge">{rule.relationship}</span>
              </p>
              <ul className="inspector-list">
                {rule.targets.map((target) => (
                  <li key={target} className="lineage-target">
                    {target}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

function ComparisonPicker({
  state,
  selected,
  onSelect,
}: {
  state: ComparisonLoadState;
  selected: SelectedComparison | null;
  onSelect: (selection: SelectedComparison) => void;
}) {
  if (state.status === "idle" || state.status === "loading") {
    return <p className="pane-hint">Loading comparison options…</p>;
  }
  if (state.status === "refused") {
    return <p className="pane-hint">Comparison unavailable: {state.detail}</p>;
  }
  if (state.status === "failed") {
    return <p className="pane-hint">Failed to load comparison options.</p>;
  }
  if (state.options.groups.length === 0) {
    return <p className="pane-hint">No graph-backed comparison targets for this unit.</p>;
  }
  return (
    <section className="inspector-section comparison-picker">
      <h3>Compare with</h3>
      {state.options.groups.map((group) => (
        <div key={group.relation} className="inspector-block">
          <h4>{group.label}</h4>
          <ul className="inspector-list">
            {group.choices.map((choice) => {
              const candidate = { relation: group.relation, choice };
              const key = comparisonChoiceKey(group.relation, choice);
              const active =
                selected !== null &&
                comparisonChoiceKey(selected.relation, selected.choice) === key;
              return (
                <li key={key}>
                  <button
                    type="button"
                    className={active ? "relation-entry selected" : "relation-entry"}
                    onClick={() => onSelect(candidate)}
                  >
                    {choice.label}
                  </button>
                  <span className="relation-note">{choice.detail}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}

// Relationship data remains unit-scoped. The component remounts only when the unit
// changes, so fragment changes preserve the loaded relationship state.
function UnitInspector({
  target,
  mode,
  comparisonState,
  selectedComparison,
  onComparisonSelect,
  onSelect,
}: {
  target: SourceTarget;
  mode: Mode;
  comparisonState: ComparisonLoadState;
  selectedComparison: SelectedComparison | null;
  onComparisonSelect: (selection: SelectedComparison) => void;
  onSelect: SelectSource;
}) {
  const { unit } = target;
  const [state, setState] = useState<InspectLoadState>({ status: "loading" });
  const [loader] = useState(() => createInspectLoader(setState));

  useEffect(() => {
    loader.select(unit.id);
  }, [loader, unit.id]);

  useEffect(() => () => loader.dispose(), [loader]);

  const detail = state.status === "loaded" ? state.detail : null;
  return (
    <div>
      <div className="identity-block">
        <h2>{unit.id}</h2>
        <dl>
          <dt>Kind</dt>
          <dd>{unit.kind}</dd>
          <dt>Path</dt>
          <dd>{unit.path}</dd>
          {target.fragment !== null && (
            <>
              <dt>Fragment</dt>
              <dd>{target.fragment.id}</dd>
              <dt>Fragment label</dt>
              <dd>{target.fragment.label}</dd>
            </>
          )}
          {detail !== null && (
            <>
              <dt>Selector</dt>
              <dd>{detail.selector}</dd>
            </>
          )}
        </dl>
        {detail !== null && (
          <>
            <p className="badge-row">
              <span className="kind-badge">{detail.kind}</span>{" "}
              <span className="audience-badge">{detail.audience}</span>{" "}
              <span className="role-badge">{detail.role}</span>
            </p>
            <p className="inspector-breadcrumb">{joinBreadcrumb(detail.breadcrumb)}</p>
          </>
        )}
      </div>
      {mode === "compare" && (
        <ComparisonPicker
          state={comparisonState}
          selected={selectedComparison}
          onSelect={onComparisonSelect}
        />
      )}
      {state.status === "loading" && <p className="pane-hint">Loading relationships…</p>}
      {state.status === "refused" && (
        <p className="pane-hint">Relationships unavailable: {state.detail}</p>
      )}
      {state.status === "failed" && <p className="pane-hint">Failed to load relationships.</p>}
      {detail !== null && <Relationships detail={detail} onSelect={onSelect} />}
    </div>
  );
}

// The inspector pane: the identity block plus the relationship sections for a unit
// selection; a boundary selection keeps its owner/explanation block (no fetch).
export function InspectorPane({
  mode,
  selection,
  comparisonState,
  selectedComparison,
  onComparisonSelect,
  onSelection,
  onSelect,
}: {
  mode: Mode;
  selection: Selection | null;
  comparisonState: ComparisonLoadState;
  selectedComparison: SelectedComparison | null;
  onComparisonSelect: (selection: SelectedComparison) => void;
  onSelection: SelectSelection;
  onSelect: SelectSource;
}) {
  if (selection === null) {
    return <p className="pane-hint">Select a unit or boundary to inspect it.</p>;
  }
  if (selection.type === "boundary") {
    const info = BOUNDARY_INFO[selection.boundary];
    return (
      <div className="identity-block">
        <h2>{selection.label}</h2>
        <dl>
          <dt>Owner</dt>
          <dd>{info.owner}</dd>
          <dt>Boundary</dt>
          <dd>{selection.boundary}</dd>
        </dl>
        <p>{info.explanation}</p>
      </div>
    );
  }
  if (selection.type === "shape") {
    const layers = selection.shape.layers.filter((layer) => layer.unit !== null);
    return (
      <div>
        <div className="identity-block">
          <h2>{selection.shape.label}</h2>
          <p className="badge-row">
            <span className="delivery-badge">{selection.shape.delivery}</span>
          </p>
          <p className="inspector-breadcrumb">{joinBreadcrumb(selection.breadcrumb)}</p>
        </div>
        {mode === "compare" ? (
          <section className="inspector-section">
            <h3>Choose an origin layer</h3>
            <ol className="inspector-list">
              {layers.map((layer) => {
                const unit = layer.unit;
                if (unit === null) {
                  return null;
                }
                return (
                  <li key={layer.position}>
                    <button
                      type="button"
                      className="relation-entry"
                      onClick={() =>
                        onSelection(
                          placedShapeLayerSelection(selection.shape, layer.position, unit),
                        )
                      }
                    >
                      #{layer.position} · {layer.label ?? unit.id}
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        ) : (
          <p className="pane-hint">
            {mode === "edit"
              ? "This shape has no singular source. Select a source-bearing assembly layer."
              : "Assembly mode does not render a shape preview yet."}
          </p>
        )}
      </div>
    );
  }
  return (
    <UnitInspector
      key={selection.target.unit.id}
      target={selection.target}
      mode={mode}
      comparisonState={comparisonState}
      selectedComparison={selectedComparison}
      onComparisonSelect={onComparisonSelect}
      onSelect={onSelect}
    />
  );
}
