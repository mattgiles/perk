import type { Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";

// The inspector shell: the minimal identity block only (relationships, consumers,
// and audience/role are later inspector capabilities).
export function InspectorPane({ selection }: { selection: Selection | null }) {
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
  const { unit } = selection;
  return (
    <div className="identity-block">
      <h2>{unit.id}</h2>
      <dl>
        <dt>Kind</dt>
        <dd>{unit.kind}</dd>
        <dt>Path</dt>
        <dd>{unit.path}</dd>
      </dl>
    </div>
  );
}
