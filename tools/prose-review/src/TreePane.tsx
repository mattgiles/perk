import { useState } from "react";
import { BOUNDARY_INFO } from "./boundaries.ts";
import { GIT_STATE_LABELS, type GitFileState } from "./git.ts";
import {
  canonicalFragmentSelection,
  canonicalUnitSelection,
  placedFragmentSelection,
  placedShapeLayerSelection,
  type Selection,
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

type GitStates = ReadonlyMap<string, GitFileState>;

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
      aria-current={active ? "true" : undefined}
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
  gitStates,
  selection,
  onSelect,
}: {
  unit: TreeUnit;
  display: string;
  placement: Placement | null;
  gitStates: GitStates;
} & SelectProps) {
  const [expanded, setExpanded] = useState(false);
  const unitSelection =
    placement === null
      ? canonicalUnitSelection(unit)
      : placedShapeLayerSelection(placement.shape, placement.position, unit);
  // The working-tree annotation is a text word (never color-only) and covers
  // canonical and shape-layer placements alike — both render through this branch.
  const gitState = gitStates.get(unit.path);
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
        {gitState !== undefined && <span className="git-badge">{GIT_STATE_LABELS[gitState]}</span>}
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
      aria-current={active ? "true" : undefined}
      onClick={() => onSelect({ type: "boundary", boundary, label: display })}
    >
      {display} <span className="boundary-owner">{BOUNDARY_INFO[boundary].owner}</span>
    </button>
  );
}

function LayerEntry({
  layer,
  shape,
  gitStates,
  selection,
  onSelect,
}: { layer: AssemblyLayer; shape: SessionShape; gitStates: GitStates } & SelectProps) {
  return (
    <li className="tree-layer">
      <span className="layer-position">{layer.position}</span>
      {layer.unit !== null ? (
        <UnitBranch
          unit={layer.unit}
          display={layer.label ?? layer.unit.id}
          placement={{ shape, position: layer.position }}
          gitStates={gitStates}
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
  gitStates,
  selection,
  onSelect,
}: { shape: SessionShape; breadcrumb: Breadcrumb; gitStates: GitStates } & SelectProps) {
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
          aria-current={active ? "true" : undefined}
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
              gitStates={gitStates}
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
  gitStates,
  selection,
  onSelect,
}: {
  node: CapabilityNode;
  breadcrumb: Breadcrumb;
  defaultExpanded: boolean;
  gitStates: GitStates;
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
              gitStates={gitStates}
              selection={selection}
              onSelect={onSelect}
            />
          ))}
          {node.session_shapes.map((shape) => (
            <ShapeEntry
              key={shape.id}
              shape={shape}
              breadcrumb={authoredBreadcrumb}
              gitStates={gitStates}
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
                gitStates={gitStates}
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

export function TreePane({
  tree,
  gitStates,
  selection,
  onSelect,
}: { tree: CapabilityTree; gitStates: GitStates } & SelectProps) {
  return (
    <ul className="tree-root">
      {tree.capabilities.map((node) => (
        <CapabilityEntry
          key={node.id}
          node={node}
          breadcrumb={[]}
          defaultExpanded={true}
          gitStates={gitStates}
          selection={selection}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
