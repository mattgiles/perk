// The typed fetch boundary for /api/inspect: a local mirror of the UnitInspectOut
// wire shape plus a structural runtime check (the tree.ts posture). The accepted
// language is closed: every field must be present and correctly typed, enumerated
// strings must satisfy the wire.ts guards, and every nested array is parsed
// entry-wise. Any defect rejects the whole payload with null.

import { parseUnitRef, type UnitRef } from "./tree.ts";
import {
  type Audience,
  type DeliveryMode,
  isAudience,
  isDeliveryMode,
  isProseKind,
  isProseRole,
  type ProseKind,
  type ProseRole,
} from "./wire.ts";

// The lineage relationship vocabulary is endpoint vocabulary (the authored literal
// set served by LineageOut), not a models.py vocabulary mirror — hence module-local.
export const LINEAGE_RELATIONSHIPS = ["generated-from", "materializes-to", "bundled-as"] as const;

export type LineageRelationship = (typeof LINEAGE_RELATIONSHIPS)[number];

function isLineageRelationship(value: unknown): value is LineageRelationship {
  return typeof value === "string" && (LINEAGE_RELATIONSHIPS as readonly string[]).includes(value);
}

export type CapabilityRef = {
  id: string;
  label: string;
};

export type Consumer = {
  assembly: string;
  position: number;
  label: string | null;
  optional: boolean;
};

export type ShapeRef = {
  id: string;
  label: string;
  delivery: DeliveryMode;
};

export type ConsumingShape = {
  id: string;
  label: string;
  delivery: DeliveryMode;
  breadcrumb: CapabilityRef[];
  siblings: ShapeRef[];
};

export type ConcernMember = {
  unit: UnitRef;
  relation: string | null;
  canonical: boolean;
};

export type Concern = {
  id: string;
  label: string;
  summary: string;
  canonical: boolean;
  relation: string | null;
  members: ConcernMember[];
};

export type Lineage = {
  id: string;
  relationship: LineageRelationship;
  targets: string[];
};

export type UnitInspect = {
  id: string;
  kind: ProseKind;
  path: string;
  selector: string;
  audience: Audience;
  role: ProseRole;
  breadcrumb: CapabilityRef[];
  capability_children: CapabilityRef[];
  consumers: Consumer[];
  shapes: ConsumingShape[];
  concerns: Concern[];
  lineage: Lineage[];
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

export function parseCapabilityRef(value: unknown): CapabilityRef | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.label !== "string") {
    return null;
  }
  return { id: value.id, label: value.label };
}

function parseConsumer(value: unknown): Consumer | null {
  if (!isRecord(value)) {
    return null;
  }
  const { assembly, position, label, optional } = value;
  if (typeof assembly !== "string") {
    return null;
  }
  if (typeof position !== "number" || !Number.isInteger(position) || position < 1) {
    return null;
  }
  if (label !== null && typeof label !== "string") {
    return null;
  }
  if (typeof optional !== "boolean") {
    return null;
  }
  return { assembly, position, label, optional };
}

function parseShapeRef(value: unknown): ShapeRef | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    !isDeliveryMode(value.delivery)
  ) {
    return null;
  }
  return { id: value.id, label: value.label, delivery: value.delivery };
}

function parseConsumingShape(value: unknown): ConsumingShape | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    !isDeliveryMode(value.delivery)
  ) {
    return null;
  }
  const breadcrumb = parseArray(value.breadcrumb, parseCapabilityRef);
  const siblings = parseArray(value.siblings, parseShapeRef);
  if (breadcrumb === null || siblings === null) {
    return null;
  }
  return { id: value.id, label: value.label, delivery: value.delivery, breadcrumb, siblings };
}

function parseConcernMember(value: unknown): ConcernMember | null {
  if (!isRecord(value)) {
    return null;
  }
  const unit = parseUnitRef(value.unit);
  if (unit === null) {
    return null;
  }
  if (value.relation !== null && typeof value.relation !== "string") {
    return null;
  }
  if (typeof value.canonical !== "boolean") {
    return null;
  }
  return { unit, relation: value.relation, canonical: value.canonical };
}

function parseConcern(value: unknown): Concern | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string" ||
    typeof value.summary !== "string" ||
    typeof value.canonical !== "boolean"
  ) {
    return null;
  }
  if (value.relation !== null && typeof value.relation !== "string") {
    return null;
  }
  const members = parseArray(value.members, parseConcernMember);
  if (members === null) {
    return null;
  }
  return {
    id: value.id,
    label: value.label,
    summary: value.summary,
    canonical: value.canonical,
    relation: value.relation,
    members,
  };
}

export function parseLineage(value: unknown): Lineage | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isLineageRelationship(value.relationship)
  ) {
    return null;
  }
  const targets = parseArray(value.targets, (entry) => (typeof entry === "string" ? entry : null));
  if (targets === null) {
    return null;
  }
  return { id: value.id, relationship: value.relationship, targets };
}

/** Structurally validate an unknown JSON payload as a UnitInspect (null on any defect). */
export function parseUnitInspect(value: unknown): UnitInspect | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProseKind(value.kind) ||
    typeof value.path !== "string" ||
    typeof value.selector !== "string" ||
    !isAudience(value.audience) ||
    !isProseRole(value.role)
  ) {
    return null;
  }
  const breadcrumb = parseArray(value.breadcrumb, parseCapabilityRef);
  const capabilityChildren = parseArray(value.capability_children, parseCapabilityRef);
  const consumers = parseArray(value.consumers, parseConsumer);
  const shapes = parseArray(value.shapes, parseConsumingShape);
  const concerns = parseArray(value.concerns, parseConcern);
  const lineage = parseArray(value.lineage, parseLineage);
  if (
    breadcrumb === null ||
    capabilityChildren === null ||
    consumers === null ||
    shapes === null ||
    concerns === null ||
    lineage === null
  ) {
    return null;
  }
  return {
    id: value.id,
    kind: value.kind,
    path: value.path,
    selector: value.selector,
    audience: value.audience,
    role: value.role,
    breadcrumb,
    capability_children: capabilityChildren,
    consumers,
    shapes,
    concerns,
    lineage,
  };
}
