import { useEffect, useState } from "react";
import type { Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import type { CapabilityRef, UnitInspect } from "./inspect.ts";
import { createInspectLoader, type InspectLoadState } from "./inspectLoad.ts";
import type { UnitRef } from "./tree.ts";

type SelectUnit = (unit: UnitRef) => void;

function joinBreadcrumb(breadcrumb: CapabilityRef[]): string {
  return breadcrumb.map((capability) => capability.label).join(" / ");
}

// Every relation section is omitted when empty (no "Consumers (0)" noise); the
// identity block always renders.
function Relationships({ detail, onSelect }: { detail: UnitInspect; onSelect: SelectUnit }) {
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
                        onClick={() => onSelect(member.unit)}
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

// The relationship inspector for a unit selection: the identity block renders
// immediately from the selection; the relationships arrive through the latest-wins
// loader (one loader per mount, selected on every unit change, disposed on unmount —
// a late response never updates a superseded view).
function UnitInspector({ unit, onSelect }: { unit: UnitRef; onSelect: SelectUnit }) {
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
  selection,
  onSelect,
}: {
  selection: Selection | null;
  onSelect: SelectUnit;
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
  return <UnitInspector unit={selection.unit} onSelect={onSelect} />;
}
