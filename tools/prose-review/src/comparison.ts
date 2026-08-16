import type { CapabilityRef, ShapeRef } from "./inspect.ts";
import type { UnitSelection } from "./selection.ts";
import { parseUnitRef, type UnitRef } from "./tree.ts";
import { isDeliveryMode } from "./wire.ts";

export const COMPARISON_RELATIONS = [
  "delivery-sibling",
  "adjacent-layer",
  "alias-consumer",
  "concern-relative",
  "capability-parent-child",
] as const;

export type ComparisonRelation = (typeof COMPARISON_RELATIONS)[number];

export type ComparisonPlacement = {
  unit: UnitRef;
  breadcrumb: CapabilityRef[];
  shape: ShapeRef | null;
  assembly: string | null;
  position: number | null;
  label: string;
};

export type ComparisonChoice = {
  label: string;
  detail: string;
  target: ComparisonPlacement;
};

export type ComparisonGroup = {
  relation: ComparisonRelation;
  label: string;
  choices: ComparisonChoice[];
};

export type ComparisonOptions = {
  origin: ComparisonPlacement;
  groups: ComparisonGroup[];
};

export type SelectedComparison = {
  relation: ComparisonRelation;
  choice: ComparisonChoice;
};

export type ComparisonRequest =
  | { unit: string; shape: null; position: null }
  | { unit: string; shape: string; position: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function parseArray<T>(value: unknown, parseEntry: (entry: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const entries: T[] = [];
  for (const entry of value) {
    const parsed = parseEntry(entry);
    if (parsed === null) {
      return null;
    }
    entries.push(parsed);
  }
  return entries;
}

function parseCapability(value: unknown): CapabilityRef | null {
  if (!isRecord(value) || !nonEmpty(value.id) || !nonEmpty(value.label)) {
    return null;
  }
  return { id: value.id, label: value.label };
}

function parseShape(value: unknown): ShapeRef | null {
  if (
    !isRecord(value) ||
    !nonEmpty(value.id) ||
    !nonEmpty(value.label) ||
    !isDeliveryMode(value.delivery)
  ) {
    return null;
  }
  return { id: value.id, label: value.label, delivery: value.delivery };
}

function parsePlacement(value: unknown): ComparisonPlacement | null {
  if (!isRecord(value) || !nonEmpty(value.label)) {
    return null;
  }
  const unit = parseUnitRef(value.unit);
  const breadcrumb = parseArray(value.breadcrumb, parseCapability);
  if (unit === null || breadcrumb === null || breadcrumb.length === 0) {
    return null;
  }
  const shape = value.shape === null ? null : parseShape(value.shape);
  if (value.shape !== null && shape === null) {
    return null;
  }
  const assembly = value.assembly;
  if (assembly !== null && !nonEmpty(assembly)) {
    return null;
  }
  const position = value.position;
  if (
    position !== null &&
    (typeof position !== "number" || !Number.isInteger(position) || position < 1)
  ) {
    return null;
  }
  const canonical = shape === null && assembly === null && position === null;
  const assemblyPlacement = assembly !== null && position !== null;
  if (!canonical && !assemblyPlacement) {
    return null;
  }
  return { unit, breadcrumb, shape, assembly, position, label: value.label };
}

function isComparisonRelation(value: unknown): value is ComparisonRelation {
  return typeof value === "string" && (COMPARISON_RELATIONS as readonly string[]).includes(value);
}

function parseChoice(value: unknown): ComparisonChoice | null {
  if (!isRecord(value) || !nonEmpty(value.label) || !nonEmpty(value.detail)) {
    return null;
  }
  const target = parsePlacement(value.target);
  if (target === null) {
    return null;
  }
  return { label: value.label, detail: value.detail, target };
}

function parseGroup(value: unknown): ComparisonGroup | null {
  if (!isRecord(value) || !isComparisonRelation(value.relation) || !nonEmpty(value.label)) {
    return null;
  }
  const choices = parseArray(value.choices, parseChoice);
  if (choices === null || choices.length === 0) {
    return null;
  }
  return { relation: value.relation, label: value.label, choices };
}

/** Validate one complete comparison-options response; null rejects any malformed member. */
export function parseComparisonOptions(value: unknown): ComparisonOptions | null {
  if (!isRecord(value)) {
    return null;
  }
  const origin = parsePlacement(value.origin);
  const groups = parseArray(value.groups, parseGroup);
  if (origin === null || groups === null) {
    return null;
  }
  return { origin, groups };
}

export function comparisonRequest(selection: UnitSelection): ComparisonRequest {
  if (selection.placement === null) {
    return { unit: selection.target.unit.id, shape: null, position: null };
  }
  return {
    unit: selection.target.unit.id,
    shape: selection.placement.shape.id,
    position: selection.placement.position,
  };
}

export function comparisonOptionsMatchRequest(
  options: ComparisonOptions,
  request: ComparisonRequest,
): boolean {
  if (options.origin.unit.id !== request.unit) {
    return false;
  }
  if (request.shape === null) {
    return (
      options.origin.shape === null &&
      options.origin.assembly === null &&
      options.origin.position === null
    );
  }
  return options.origin.shape?.id === request.shape && options.origin.position === request.position;
}

export function comparisonPlacementKey(placement: ComparisonPlacement): string {
  return JSON.stringify([
    placement.unit.id,
    placement.shape?.id ?? null,
    placement.assembly,
    placement.position,
  ]);
}

export function comparisonChoiceKey(
  relation: ComparisonRelation,
  choice: ComparisonChoice,
): string {
  return JSON.stringify([
    relation,
    choice.label,
    choice.detail,
    comparisonPlacementKey(choice.target),
  ]);
}
