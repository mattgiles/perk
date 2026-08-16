import type { SearchResult } from "./search.ts";
import type { UnitRef } from "./tree.ts";

export type FragmentRef = {
  id: string;
  label: string;
};

export type SourceTarget = {
  unit: UnitRef;
  fragment: FragmentRef | null;
};

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

export function sameSourceTarget(left: SourceTarget, right: SourceTarget): boolean {
  return sourceTargetKey(left) === sourceTargetKey(right);
}
