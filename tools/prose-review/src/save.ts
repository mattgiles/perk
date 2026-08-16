import { type Lineage, parseLineage } from "./inspect.ts";
import type { SourceTarget } from "./selection.ts";
import { parseSourceFile, type SourceFile } from "./source.ts";
import { isProseKind, type ProseKind } from "./wire.ts";

export const SOURCE_DIAGNOSTIC_CODES = [
  "syntax-error",
  "unsupported-selector",
  "unsupported-source-shape",
  "selector-not-found",
  "selector-ambiguous",
] as const;
export type SourceDiagnosticCode = (typeof SOURCE_DIAGNOSTIC_CODES)[number];

export const SOURCE_REFUSAL_REASONS = [
  "unsupported-family",
  "unsafe-path",
  "unsafe-lineage",
  "source-unavailable",
  "write-failed",
  "catalog-stale",
] as const;
export type SourceRefusalReason = (typeof SOURCE_REFUSAL_REASONS)[number];

export const SUGGESTED_CHECK_IDS = ["prose-map", "learned-docs"] as const;
export type SuggestedCheckId = (typeof SUGGESTED_CHECK_IDS)[number];

export const UNSUPPORTED_FAMILY_DETAIL = "Save support has not landed for this source family.";
export const GENERATED_LINEAGE_DETAIL =
  "Generated source files cannot be saved from the workbench.";
export const CONFLICT_DETAIL = "Source changed on disk. The workbench did not overwrite it.";
export const CATALOG_STALE_DETAIL =
  "The file was saved, but the catalog could not be refreshed. Further saves are disabled. " +
  "Copy any remaining edits, repair or revert the saved source outside the workbench if the " +
  "catalog is invalid, then relaunch.";
export const INDETERMINATE_DETAIL =
  "The save result could not be confirmed. Further saves are paused while the workbench checks " +
  "the canonical file.";
export const UNRESOLVED_RECONCILIATION_DETAIL =
  "The save result is still unknown. Copy Edits or retry reconciliation before closing the " +
  "workbench.";
export const CLIPBOARD_FAILURE_DETAIL = "Copy Edits failed. The in-memory edits are unchanged.";
export const NOT_SENT_DETAIL =
  "The save request did not leave the browser. The reviewed buffer is unchanged; retry when the workbench session is available.";

export type SavedSource = {
  unit: string;
  kind: ProseKind;
  file: SourceFile;
};

export type SourceDiagnostic = {
  code: SourceDiagnosticCode;
  message: string;
  selector: string | null;
  line: number | null;
  column: number | null;
};

export type SuggestedCheck = {
  id: SuggestedCheckId;
  command: string;
};

export type SourceSaveResult =
  | {
      status: "saved";
      source: SavedSource;
      materialized: Lineage[];
      checks: SuggestedCheck[];
      catalog_refreshed: boolean;
      refresh_detail: string | null;
    }
  | { status: "validation-failed"; diagnostics: SourceDiagnostic[] }
  | { status: "conflict"; detail: string }
  | { status: "refused"; reason: SourceRefusalReason; detail: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseArray<T>(value: unknown, parse: (entry: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const parsed: T[] = [];
  for (const entry of value) {
    const item = parse(entry);
    if (item === null) {
      return null;
    }
    parsed.push(item);
  }
  return parsed;
}

function included<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

function parseSavedSource(value: unknown): SavedSource | null {
  if (!isRecord(value) || typeof value.unit !== "string" || !isProseKind(value.kind)) {
    return null;
  }
  const file = parseSourceFile(value.file);
  if (file === null) {
    return null;
  }
  return { unit: value.unit, kind: value.kind, file };
}

function parseDiagnostic(value: unknown): SourceDiagnostic | null {
  if (
    !isRecord(value) ||
    !included(SOURCE_DIAGNOSTIC_CODES, value.code) ||
    typeof value.message !== "string" ||
    (value.selector !== null && typeof value.selector !== "string") ||
    (value.line !== null && (!Number.isInteger(value.line) || (value.line as number) < 1)) ||
    (value.column !== null && (!Number.isInteger(value.column) || (value.column as number) < 1))
  ) {
    return null;
  }
  if ((value.code === "syntax-error") !== (value.selector === null)) {
    return null;
  }
  return {
    code: value.code,
    message: value.message,
    selector: value.selector,
    line: value.line as number | null,
    column: value.column as number | null,
  };
}

function parseSuggestedCheck(value: unknown): SuggestedCheck | null {
  if (
    !isRecord(value) ||
    !included(SUGGESTED_CHECK_IDS, value.id) ||
    typeof value.command !== "string"
  ) {
    return null;
  }
  return { id: value.id, command: value.command };
}

export function parseSourceSaveResult(value: unknown): SourceSaveResult | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.status === "saved") {
    const source = parseSavedSource(value.source);
    const materialized = parseArray(value.materialized, parseLineage);
    const checks = parseArray(value.checks, parseSuggestedCheck);
    if (
      source === null ||
      materialized === null ||
      checks === null ||
      typeof value.catalog_refreshed !== "boolean" ||
      (value.refresh_detail !== null && typeof value.refresh_detail !== "string") ||
      value.catalog_refreshed !== (value.refresh_detail === null)
    ) {
      return null;
    }
    return {
      status: "saved",
      source,
      materialized,
      checks,
      catalog_refreshed: value.catalog_refreshed,
      refresh_detail: value.refresh_detail,
    };
  }
  if (value.status === "validation-failed") {
    const diagnostics = parseArray(value.diagnostics, parseDiagnostic);
    return diagnostics === null ? null : { status: "validation-failed", diagnostics };
  }
  if (value.status === "conflict") {
    return typeof value.detail === "string" ? { status: "conflict", detail: value.detail } : null;
  }
  if (value.status === "refused") {
    return included(SOURCE_REFUSAL_REASONS, value.reason) && typeof value.detail === "string"
      ? { status: "refused", reason: value.reason, detail: value.detail }
      : null;
  }
  return null;
}

export function supportsSourceSave(target: SourceTarget): boolean {
  const path = target.unit.path.toLowerCase();
  if (
    (target.unit.kind === "markdown" || target.unit.kind === "managed-prose") &&
    path.endsWith(".md")
  ) {
    return true;
  }
  return (
    target.unit.kind === "ambient-routing" && (path.endsWith(".yaml") || path.endsWith(".yml"))
  );
}
