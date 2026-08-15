// The typed fetch boundary: a local mirror of the /api/catalog/summary wire shape plus
// a structural runtime check. Deliberately dependency-free (no schema library, no DOM)
// so node:test can exercise it directly; OpenAPI generation is out of scope.

export type Capability = {
  id: string;
  label: string;
};

export type CatalogSummary = {
  units: number;
  fragments: number;
  session_shapes: number;
  assemblies: number;
  scenarios: number;
  concerns: number;
  lineage_rules: number;
  capabilities: Capability[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseCapability(value: unknown): Capability | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.label !== "string") {
    return null;
  }
  return { id: value.id, label: value.label };
}

/** Structurally validate an unknown JSON payload as a CatalogSummary (null on any defect). */
export function parseSummary(value: unknown): CatalogSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const { units, fragments, session_shapes, assemblies, scenarios, concerns, lineage_rules } =
    value;
  if (
    typeof units !== "number" ||
    typeof fragments !== "number" ||
    typeof session_shapes !== "number" ||
    typeof assemblies !== "number" ||
    typeof scenarios !== "number" ||
    typeof concerns !== "number" ||
    typeof lineage_rules !== "number"
  ) {
    return null;
  }
  if (!Array.isArray(value.capabilities)) {
    return null;
  }
  const capabilities: Capability[] = [];
  for (const entry of value.capabilities) {
    const capability = parseCapability(entry);
    if (capability === null) {
      return null;
    }
    capabilities.push(capability);
  }
  return {
    units,
    fragments,
    session_shapes,
    assemblies,
    scenarios,
    concerns,
    lineage_rules,
    capabilities,
  };
}
