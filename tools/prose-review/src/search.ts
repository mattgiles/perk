// The typed fetch boundary for /api/search: a local mirror of the SearchOut wire
// shape plus a structural runtime check (the tree.ts posture). The result-kind and
// matched-field vocabularies are endpoint vocabulary (the search module's closed
// literal sets), not models.py mirrors — hence module-local. Any defect rejects the
// whole payload with null.

import { type CapabilityRef, parseCapabilityRef } from "./inspect.ts";
import { parseUnitRef, type UnitRef } from "./tree.ts";

export const SEARCH_RESULT_KINDS = [
  "capability",
  "session-shape",
  "unit",
  "fragment",
  "concern",
] as const;

export type SearchResultKind = (typeof SEARCH_RESULT_KINDS)[number];

export const MATCH_FIELDS = [
  "capability-label",
  "shape-label",
  "unit-id",
  "source-path",
  "tool-name",
  "fragment-label",
  "concern-label",
] as const;

export type MatchField = (typeof MATCH_FIELDS)[number];

function isSearchResultKind(value: unknown): value is SearchResultKind {
  return typeof value === "string" && (SEARCH_RESULT_KINDS as readonly string[]).includes(value);
}

function isMatchField(value: unknown): value is MatchField {
  return typeof value === "string" && (MATCH_FIELDS as readonly string[]).includes(value);
}

export type SearchResult = {
  kind: SearchResultKind;
  id: string;
  label: string;
  breadcrumb: CapabilityRef[];
  unit: UnitRef | null;
  matched: MatchField[];
};

export type SearchResults = {
  total: number;
  results: SearchResult[];
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

function parseResult(value: unknown): SearchResult | null {
  if (
    !isRecord(value) ||
    !isSearchResultKind(value.kind) ||
    typeof value.id !== "string" ||
    typeof value.label !== "string"
  ) {
    return null;
  }
  const breadcrumb = parseArray(value.breadcrumb, parseCapabilityRef);
  // An empty matched array is valid: a filter-only browse matches no field.
  const matched = parseArray(value.matched, (entry) => (isMatchField(entry) ? entry : null));
  if (breadcrumb === null || matched === null) {
    return null;
  }
  const unit = value.unit === null ? null : parseUnitRef(value.unit);
  if (value.unit !== null && unit === null) {
    return null;
  }
  return { kind: value.kind, id: value.id, label: value.label, breadcrumb, unit, matched };
}

/** Structurally validate an unknown JSON payload as SearchResults (null on any defect). */
export function parseSearch(value: unknown): SearchResults | null {
  if (
    !isRecord(value) ||
    typeof value.total !== "number" ||
    !Number.isInteger(value.total) ||
    value.total < 0
  ) {
    return null;
  }
  const results = parseArray(value.results, parseResult);
  if (results === null) {
    return null;
  }
  return { total: value.total, results };
}
