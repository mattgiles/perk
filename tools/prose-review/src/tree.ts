// The typed fetch boundary for /api/catalog/tree: a local mirror of the wire shape
// plus a structural runtime check (the summary.ts posture — dependency-free so
// node:test can exercise it directly). The accepted language is closed: every field
// must be present and correctly typed, enumerated strings must satisfy the wire.ts
// guards, and a layer must carry exactly one of unit/boundary non-null (the catalog
// invariant, enforced at parse even though the wire types are nullable). Any defect
// rejects the whole payload with null.

import {
  type BoundaryKind,
  type DeliveryMode,
  isBoundaryKind,
  isDeliveryMode,
  isProseKind,
  type ProseKind,
} from "./wire.ts";

export type UnitRef = {
  id: string;
  kind: ProseKind;
  path: string;
};

export type AssemblyLayer = {
  position: number;
  optional: boolean;
  label: string | null;
  unit: UnitRef | null;
  boundary: BoundaryKind | null;
};

export type SessionShape = {
  id: string;
  label: string;
  delivery: DeliveryMode;
  layers: AssemblyLayer[];
};

export type CapabilityNode = {
  id: string;
  label: string;
  units: UnitRef[];
  session_shapes: SessionShape[];
  children: CapabilityNode[];
};

export type CapabilityTree = {
  capabilities: CapabilityNode[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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

/** Parse one unit reference (shared by the inspect/search parse boundaries). */
export function parseUnitRef(value: unknown): UnitRef | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProseKind(value.kind) ||
    typeof value.path !== "string"
  ) {
    return null;
  }
  return { id: value.id, kind: value.kind, path: value.path };
}

function parseLayer(value: unknown): AssemblyLayer | null {
  if (!isRecord(value)) {
    return null;
  }
  const { position, optional, label } = value;
  if (typeof position !== "number" || !Number.isInteger(position) || position < 1) {
    return null;
  }
  if (typeof optional !== "boolean") {
    return null;
  }
  if (label !== null && typeof label !== "string") {
    return null;
  }
  const unit = value.unit === null ? null : parseUnitRef(value.unit);
  if (value.unit !== null && unit === null) {
    return null;
  }
  const boundary = value.boundary;
  if (boundary !== null && !isBoundaryKind(boundary)) {
    return null;
  }
  // The catalog invariant: exactly one of unit/boundary is set.
  if ((unit === null) === (boundary === null)) {
    return null;
  }
  return { position, optional, label, unit, boundary };
}

function parseShape(value: unknown): SessionShape | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    !isDeliveryMode(value.delivery)
  ) {
    return null;
  }
  const layers = parseArray(value.layers, parseLayer);
  if (layers === null) {
    return null;
  }
  return { id: value.id, label: value.label, delivery: value.delivery, layers };
}

function parseNode(value: unknown): CapabilityNode | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.label !== "string") {
    return null;
  }
  const units = parseArray(value.units, parseUnitRef);
  const sessionShapes = parseArray(value.session_shapes, parseShape);
  const children = parseArray(value.children, parseNode);
  if (units === null || sessionShapes === null || children === null) {
    return null;
  }
  return { id: value.id, label: value.label, units, session_shapes: sessionShapes, children };
}

/** Structurally validate an unknown JSON payload as a CapabilityTree (null on any defect). */
export function parseTree(value: unknown): CapabilityTree | null {
  if (!isRecord(value)) {
    return null;
  }
  const capabilities = parseArray(value.capabilities, parseNode);
  if (capabilities === null) {
    return null;
  }
  return { capabilities };
}
