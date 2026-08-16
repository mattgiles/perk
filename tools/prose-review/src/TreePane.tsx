import { useState } from "react";
import type { Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import {
  canonicalFragmentSelection,
  canonicalUnitSelection,
  placedFragmentSelection,
  placedShapeLayerSelection,
  shapeSelection,
  sourceSelectionKey,
  type UnitSelection,
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

type Breadcrumb = Pick<CapabilityNode, "id" | "label">[];

type Placement = {
  shape: SessionShape;
  position: number;
};

function isUnitActive(selection: Selection | null, candidate: UnitSelection): boolean {
  return (
    selection !== null &&
    selection.type === "unit" &&
    sourceSelectionKey(selection) === sourceSelectionKey(candidate)
  );
}

function SourceButton({
  candidate,
  display,
  fragment,
  selection,
  onSelect,
}: {
  candidate: UnitSelection;
  display: string;
  fragment: boolean;
} & SelectProps) {
  const active = isUnitActive(selection, candidate);
  return (
    <button
      type="button"
      className={`${active ? "tree-entry selected" : "tree-entry"}${fragment ? " fragment" : ""}`}
      onClick={() => onSelect(candidate)}
    >
      {display}
    </button>
  );
}

function UnitBranch({
  unit,
  display,
  placement,
  selection,
  onSelect,
}: { unit: TreeUnit; display: string; placement: Placement | null } & SelectProps) {
  const [expanded, setExpanded] = useState(false);
  const unitSelection =
    placement === null
      ? canonicalUnitSelection(unit)
      : placedShapeLayerSelection(placement.shape, placement.position, unit);
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
          candidate={unitSelection}
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
                candidate={
                  placement === null
                    ? canonicalFragmentSelection(unit, fragment)
                    : placedFragmentSelection(placement.shape, placement.position, unit, fragment)
                }
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

function LayerEntry({
  layer,
  shape,
  selection,
  onSelect,
}: { layer: AssemblyLayer; shape: SessionShape } & SelectProps) {
  return (
    <li className="tree-layer">
      <span className="layer-position">{layer.position}</span>
      {layer.unit !== null ? (
        <UnitBranch
          unit={layer.unit}
          display={layer.label ?? layer.unit.id}
          placement={{ shape, position: layer.position }}
          selection={selection}
          onSelect={onSelect}
        />
      ) : (
        <BoundaryButton layer={layer} selection={selection} onSelect={onSelect} />
      )}
    </li>
  );
}

function ShapeEntry({
  shape,
  breadcrumb,
  selection,
  onSelect,
}: { shape: SessionShape; breadcrumb: Breadcrumb } & SelectProps) {
  const [expanded, setExpanded] = useState(false);
  const active =
    selection !== null && selection.type === "shape" && selection.shape.id === shape.id;
  return (
    <li>
      <div className="tree-shape-row">
        <button
          type="button"
          className="tree-fragment-toggle"
          aria-label={`${expanded ? "Collapse" : "Expand"} layers for ${shape.label}`}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="toggle-marker">{expanded ? "▾" : "▸"}</span>
        </button>
        <button
          type="button"
          className={active ? "tree-entry selected" : "tree-entry"}
          onClick={() => onSelect(shapeSelection(shape, breadcrumb))}
        >
          {shape.label} <span className="delivery-badge">{shape.delivery}</span>
        </button>
      </div>
      {expanded && (
        <ol className="tree-branch">
          {shape.layers.map((layer) => (
            <LayerEntry
              key={layer.position}
              layer={layer}
              shape={shape}
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
  breadcrumb,
  defaultExpanded,
  selection,
  onSelect,
}: {
  node: CapabilityNode;
  breadcrumb: Breadcrumb;
  defaultExpanded: boolean;
} & SelectProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const authoredBreadcrumb = [...breadcrumb, { id: node.id, label: node.label }];
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
              breadcrumb={authoredBreadcrumb}
              defaultExpanded={false}
              selection={selection}
              onSelect={onSelect}
            />
          ))}
          {node.session_shapes.map((shape) => (
            <ShapeEntry
              key={shape.id}
              shape={shape}
              breadcrumb={authoredBreadcrumb}
              selection={selection}
              onSelect={onSelect}
            />
          ))}
          {node.units.map((unit) => (
            <li key={unit.id}>
              <UnitBranch
                unit={unit}
                display={unit.id}
                placement={null}
                selection={selection}
                onSelect={onSelect}
              />
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
          breadcrumb={[]}
          defaultExpanded={true}
          selection={selection}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
