import { createTwoFilesPatch } from "diff";
import type { NewlineStyle } from "./source.ts";

const encoder = new TextEncoder();

export type BufferMetadata = Readonly<{
  bytes: number;
  newlineStyle: NewlineStyle;
  finalNewline: boolean;
  bom: boolean;
}>;

export type SaveReview = Readonly<{
  path: string;
  unit: string;
  loadHash: string;
  loadText: string;
  currentText: string;
  revision: number;
  diff: string;
  loaded: BufferMetadata;
  current: BufferMetadata;
}>;

function newlineStyle(text: string): NewlineStyle {
  const withoutCrlf = text.replaceAll("\r\n", "");
  const styles = [
    text.includes("\r\n") ? "crlf" : null,
    withoutCrlf.includes("\n") ? "lf" : null,
    withoutCrlf.includes("\r") ? "cr" : null,
  ].filter((style): style is "crlf" | "lf" | "cr" => style !== null);
  const [only] = styles;
  if (only === undefined) {
    return "none";
  }
  return styles.length === 1 ? only : "mixed";
}

function metadata(text: string): BufferMetadata {
  return Object.freeze({
    bytes: encoder.encode(text).byteLength,
    newlineStyle: newlineStyle(text),
    finalNewline: text.endsWith("\n") || text.endsWith("\r"),
    bom: text.startsWith("\uFEFF"),
  });
}

export function createSaveReview(input: {
  path: string;
  unit: string;
  loadHash: string;
  loadText: string;
  currentText: string;
  revision: number;
}): SaveReview {
  const review = {
    ...input,
    diff:
      createTwoFilesPatch(
        `a/${input.path}`,
        `b/${input.path}`,
        input.loadText,
        input.currentText,
        "loaded",
        "current",
        { context: Number.MAX_SAFE_INTEGER },
      ) ?? "",
    loaded: metadata(input.loadText),
    current: metadata(input.currentText),
  };
  return Object.freeze(review);
}
