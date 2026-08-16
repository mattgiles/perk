import { useState } from "react";
import type { Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import {
  fragmentTarget,
  type SourceTarget,
  sameSourceTarget,
  wholeUnitTarget,
} from "./selection.ts";
import type {
  AssemblyLayer,
  CapabilityNode,
  CapabilityTree,
  SessionShape,
  TreeUnit,
} from "./tree.ts";

type SelectProps = {
  selection: Selection | null;
  onSelect: (selection: Selection) => void;
};

function isActive(selection: Selection | null, target: SourceTarget): boolean {
  return (
    selection !== null && selection.type === "unit" && sameSourceTarget(selection.target, target)
  );
}

function SourceButton({
  target,
  display,
  fragment,
  selection,
  onSelect,
}: {
  target: SourceTarget;
  display: string;
  fragment: boolean;
} & SelectProps) {
  const active = isActive(selection, target);
  return (
    <button
      type="button"
      className={`${active ? "tree-entry selected" : "tree-entry"}${fragment ? " fragment" : ""}`}
      onClick={() => onSelect({ type: "unit", target })}
    >
      {display}
    </button>
  );
}

function UnitBranch({
  unit,
  display,
  selection,
  onSelect,
}: { unit: TreeUnit; display: string } & SelectProps) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="tree-unit-branch">
      <div className="tree-unit-row">
        <button
          type="button"
          className="tree-fragment-toggle"
          aria-label={`${expanded ? "Collapse" : "Expand"} fragments for ${display}`}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="toggle-marker">{expanded ? "▾" : "▸"}</span>
        </button>
        <SourceButton
          target={wholeUnitTarget(unit)}
          display={display}
          fragment={false}
          selection={selection}
          onSelect={onSelect}
        />
      </div>
      {expanded && (
        <ul className="tree-branch fragment-branch">
          {unit.fragments.map((fragment) => (
            <li key={fragment.id}>
              <SourceButton
                target={fragmentTarget(unit, fragment)}
                display={fragment.label}
                fragment={true}
                selection={selection}
                onSelect={onSelect}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BoundaryButton({ layer, selection, onSelect }: { layer: AssemblyLayer } & SelectProps) {
  if (layer.boundary === null) {
    return null;
  }
  const boundary = layer.boundary;
  const display = layer.label ?? boundary;
  const active =
    selection !== null &&
    selection.type === "boundary" &&
    selection.boundary === boundary &&
    selection.label === display;
  return (
    <button
      type="button"
      className={active ? "tree-entry boundary selected" : "tree-entry boundary"}
      onClick={() => onSelect({ type: "boundary", boundary, label: display })}
    >
      {display} <span className="boundary-owner">{BOUNDARY_INFO[boundary].owner}</span>
    </button>
  );
}

function LayerEntry({ layer, selection, onSelect }: { layer: AssemblyLayer } & SelectProps) {
  return (
    <li className="tree-layer">
      <span className="layer-position">{layer.position}</span>
      {layer.unit !== null ? (
        <UnitBranch
          unit={layer.unit}
          display={layer.label ?? layer.unit.id}
          selection={selection}
          onSelect={onSelect}
        />
      ) : (
        <BoundaryButton layer={layer} selection={selection} onSelect={onSelect} />
      )}
    </li>
  );
}

function ShapeEntry({ shape, selection, onSelect }: { shape: SessionShape } & SelectProps) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li>
      <button
        type="button"
        className="tree-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        <span className="toggle-marker">{expanded ? "▾" : "▸"}</span> {shape.label}{" "}
        <span className="delivery-badge">{shape.delivery}</span>
      </button>
      {expanded && (
        <ol className="tree-branch">
          {shape.layers.map((layer) => (
            <LayerEntry
              key={layer.position}
              layer={layer}
              selection={selection}
              onSelect={onSelect}
            />
          ))}
        </ol>
      )}
    </li>
  );
}

function CapabilityEntry({
  node,
  defaultExpanded,
  selection,
  onSelect,
}: { node: CapabilityNode; defaultExpanded: boolean } & SelectProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <li>
      <button
        type="button"
        className="tree-toggle capability"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        <span className="toggle-marker">{expanded ? "▾" : "▸"}</span> {node.label}
      </button>
      {expanded && (
        <ul className="tree-branch">
          {node.children.map((child) => (
            <CapabilityEntry
              key={child.id}
              node={child}
              defaultExpanded={false}
              selection={selection}
              onSelect={onSelect}
            />
          ))}
          {node.session_shapes.map((shape) => (
            <ShapeEntry key={shape.id} shape={shape} selection={selection} onSelect={onSelect} />
          ))}
          {node.units.map((unit) => (
            <li key={unit.id}>
              <UnitBranch unit={unit} display={unit.id} selection={selection} onSelect={onSelect} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function TreePane({ tree, selection, onSelect }: { tree: CapabilityTree } & SelectProps) {
  return (
    <ul className="tree-root">
      {tree.capabilities.map((node) => (
        <CapabilityEntry
          key={node.id}
          node={node}
          defaultExpanded={true}
          selection={selection}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
