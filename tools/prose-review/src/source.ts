import { type FragmentRef, parseFragmentRef } from "./selection.ts";
import { isProseKind, type ProseKind } from "./wire.ts";

export const NEWLINE_STYLES = ["none", "lf", "crlf", "cr", "mixed"] as const;
export type NewlineStyle = (typeof NEWLINE_STYLES)[number];

export const READ_ONLY_REASONS = [
  "whole-unit",
  "unsupported-family",
  "adapter-unavailable",
  "unsupported-selector",
  "unsupported-source-shape",
  "selector-not-found",
  "selector-ambiguous",
  "invalid-source",
] as const;

export type ReadOnlyReason = (typeof READ_ONLY_REASONS)[number];

export const READ_ONLY_PRESENTATION = {
  "whole-unit": {
    badge: "Read-only whole file",
    heading: "Whole-file view",
    explanation:
      "Select a logical fragment to view its focused range. Whole-unit browsing is read-only.",
  },
  "unsupported-family": {
    badge: "Read-only source",
    heading: "Adapter not available",
    explanation: "This source family is readable, but its focused adapter has not landed yet.",
  },
  "adapter-unavailable": {
    badge: "Read-only source",
    heading: "Adapter unavailable",
    explanation: "The source is readable, but its focused adapter could not run safely.",
  },
  "unsupported-selector": {
    badge: "Read-only source",
    heading: "Unsupported selector",
    explanation: "This fragment uses a selector shape the workbench does not edit.",
  },
  "unsupported-source-shape": {
    badge: "Read-only source",
    heading: "Unsupported source shape",
    explanation: "The fragment is readable, but its current source shape cannot be focused safely.",
  },
  "selector-not-found": {
    badge: "Read-only source",
    heading: "Fragment not found",
    explanation: "The catalog fragment no longer resolves in the current source file.",
  },
  "selector-ambiguous": {
    badge: "Read-only source",
    heading: "Fragment is ambiguous",
    explanation: "The catalog fragment resolves more than once in the current source file.",
  },
  "invalid-source": {
    badge: "Read-only source",
    heading: "Invalid source",
    explanation: "The current source cannot be parsed safely enough to resolve this fragment.",
  },
} as const satisfies Record<
  ReadOnlyReason,
  { badge: string; heading: string; explanation: string }
>;

export type SourceFile = {
  path: string;
  mode: number;
  newline_style: NewlineStyle;
  load_hash: string;
};

export type SourceView = {
  unit: string;
  fragment: FragmentRef | null;
  kind: ProseKind;
  before: string;
  focus: string;
  after: string;
  editable: boolean;
  read_only_reason: ReadOnlyReason | null;
};

export type UnitSource = {
  file: SourceFile;
  view: SourceView;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNewlineStyle(value: unknown): value is NewlineStyle {
  return typeof value === "string" && (NEWLINE_STYLES as readonly string[]).includes(value);
}

function isReadOnlyReason(value: unknown): value is ReadOnlyReason {
  return typeof value === "string" && (READ_ONLY_REASONS as readonly string[]).includes(value);
}

export function sourceCurrentText(source: SourceView): string {
  return source.before + source.focus + source.after;
}

/** Structurally validate immutable canonical-file metadata. */
export function parseSourceFile(value: unknown): SourceFile | null {
  if (
    !isRecord(value) ||
    typeof value.path !== "string" ||
    !Number.isInteger(value.mode) ||
    (value.mode as number) < 0 ||
    (value.mode as number) > 0o7777 ||
    !isNewlineStyle(value.newline_style) ||
    typeof value.load_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.load_hash)
  ) {
    return null;
  }
  return {
    path: value.path,
    mode: value.mode as number,
    newline_style: value.newline_style,
    load_hash: value.load_hash,
  };
}

/** Structurally validate one metadata-free source projection. */
export function parseSourceView(value: unknown): SourceView | null {
  if (
    !isRecord(value) ||
    typeof value.unit !== "string" ||
    !isProseKind(value.kind) ||
    typeof value.before !== "string" ||
    typeof value.focus !== "string" ||
    typeof value.after !== "string" ||
    typeof value.editable !== "boolean"
  ) {
    return null;
  }
  const fragment = value.fragment === null ? null : parseFragmentRef(value.fragment);
  if (value.fragment !== null && fragment === null) {
    return null;
  }
  const reason = value.read_only_reason;
  if (reason !== null && !isReadOnlyReason(reason)) {
    return null;
  }
  if (value.editable ? fragment === null || reason !== null : reason === null) {
    return null;
  }
  return {
    unit: value.unit,
    fragment,
    kind: value.kind,
    before: value.before,
    focus: value.focus,
    after: value.after,
    editable: value.editable,
    read_only_reason: reason,
  };
}

/** Structurally validate one nested canonical load response. */
export function parseUnitSource(value: unknown): UnitSource | null {
  if (!isRecord(value)) {
    return null;
  }
  const file = parseSourceFile(value.file);
  const view = parseSourceView(value.view);
  if (file === null || view === null) {
    return null;
  }
  return { file, view };
}
