import type { SearchResult } from "./search.ts";
import type { CapabilityNode, SessionShape, UnitRef } from "./tree.ts";
import type { BoundaryKind } from "./wire.ts";

export type FragmentRef = {
  id: string;
  label: string;
};

export type SourceTarget = {
  unit: UnitRef;
  fragment: FragmentRef | null;
};

export type CompactShape = Pick<SessionShape, "id" | "label" | "delivery">;

export type ShapePlacement = {
  shape: CompactShape;
  position: number;
};

export type UnitSelection = {
  type: "unit";
  target: SourceTarget;
  placement: ShapePlacement | null;
};

export type ShapeSelection = {
  type: "shape";
  shape: SessionShape;
  breadcrumb: Pick<CapabilityNode, "id" | "label">[];
};

export type Selection =
  | UnitSelection
  | ShapeSelection
  | { type: "boundary"; boundary: BoundaryKind; label: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function parseFragmentRef(value: unknown): FragmentRef | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.label !== "string") {
    return null;
  }
  return { id: value.id, label: value.label };
}

export function wholeUnitTarget(unit: UnitRef): SourceTarget {
  return { unit, fragment: null };
}

export function fragmentTarget(unit: UnitRef, fragment: FragmentRef): SourceTarget {
  return { unit, fragment };
}

export function canonicalSourceSelection(target: SourceTarget): UnitSelection {
  return { type: "unit", target, placement: null };
}

export function canonicalUnitSelection(unit: UnitRef): UnitSelection {
  return canonicalSourceSelection(wholeUnitTarget(unit));
}

export function canonicalFragmentSelection(unit: UnitRef, fragment: FragmentRef): UnitSelection {
  return canonicalSourceSelection(fragmentTarget(unit, fragment));
}

function compactShape(shape: SessionShape): CompactShape {
  return { id: shape.id, label: shape.label, delivery: shape.delivery };
}

export function placedShapeLayerSelection(
  shape: SessionShape,
  position: number,
  unit: UnitRef,
): UnitSelection {
  return {
    type: "unit",
    target: wholeUnitTarget(unit),
    placement: { shape: compactShape(shape), position },
  };
}

export function placedFragmentSelection(
  shape: SessionShape,
  position: number,
  unit: UnitRef,
  fragment: FragmentRef,
): UnitSelection {
  return {
    type: "unit",
    target: fragmentTarget(unit, fragment),
    placement: { shape: compactShape(shape), position },
  };
}

export function shapeSelection(
  shape: SessionShape,
  breadcrumb: Pick<CapabilityNode, "id" | "label">[],
): ShapeSelection {
  return { type: "shape", shape, breadcrumb };
}

export function searchResultTarget(result: SearchResult): SourceTarget | null {
  if (result.unit === null) {
    return null;
  }
  if (result.kind === "fragment") {
    return fragmentTarget(result.unit, { id: result.id, label: result.label });
  }
  if (result.kind === "unit" || result.kind === "concern") {
    return wholeUnitTarget(result.unit);
  }
  return null;
}

export function sourceTargetKey(target: SourceTarget): string {
  return JSON.stringify([
    target.unit.id,
    target.fragment?.id ?? null,
    target.fragment?.label ?? null,
  ]);
}

export function sourceSelectionKey(selection: UnitSelection): string {
  return JSON.stringify([
    sourceTargetKey(selection.target),
    selection.placement?.shape.id ?? null,
    selection.placement?.position ?? null,
  ]);
}

export function comparisonOriginKey(selection: UnitSelection): string {
  return JSON.stringify([
    selection.target.unit.id,
    selection.placement?.shape.id ?? null,
    selection.placement?.position ?? null,
  ]);
}

export function sameSourceTarget(left: SourceTarget, right: SourceTarget): boolean {
  return sourceTargetKey(left) === sourceTargetKey(right);
}
