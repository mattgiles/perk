// A deliberately strict unified-diff applier for the plannotator "Direct Edits" feedback only
// (`extension/pi/v1/providers/plannotator.ts` extracts the ```diff fence; the plan arm of
// `plan_review` applies it to the exact draft bytes it submitted) — this is NOT a general-purpose
// patch tool.
//
// Why this exists: the extension must stay zero-runtime-dependency (the bare-clone invariant —
// see `miniYaml.ts` / `miniJinja.ts`, the two prior vendored-engine precedents), so it cannot
// import jsdiff at runtime. This module covers exactly the unified-diff subset jsdiff's
// `createTwoFilesPatch(..., { context: 3 })` emits — the generator plannotator uses — pinned by
// generator-parity tests in `unifiedDiff.test.ts` (jsdiff is a dev-only dependency there).
//
// Why it is STRICT (null on ANY anomaly, never throw, never fuzz): the consumer sits on a
// fail-open ladder — a `null` merely falls back to today's behavior (the reviewed bytes are
// saved verbatim and the diff stays in the feedback as guidance). A lenient/fuzzy apply could
// silently save bytes the reviewer never approved, which is worse than declining to apply.
//
// One deliberate leniency, matching the generator: plannotator embeds `patch.trimEnd()` in the
// fence, so trailing WHITESPACE-ONLY context lines of the final hunk may have been trimmed away.
// The applier reconstructs them from the base (they are context — their bytes ARE the base's)
// and still verifies each reconstructed line is whitespace-only (anything else is a genuine
// truncation → null).

/** A parsed `@@ -a[,b] +c[,d] @@` hunk header (counts default to 1 when omitted). */
interface HunkHeader {
  oldStart: number;
  oldLines: number;
  newLines: number;
}

const HUNK_HEADER = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;
const NO_NEWLINE_MARKER = "\\ No newline at end of file";

/** One side's line entry: the text plus whether the file ends WITHOUT a newline at this line. */
interface SideLine {
  text: string;
  noNewline: boolean;
}

/** A fully parsed hunk: the header plus the old/new side projections of its body. */
interface Hunk {
  header: HunkHeader;
  oldSide: SideLine[];
  newSide: SideLine[];
}

/**
 * Split `text` into terminator-free lines plus the trailing-newline flag. An empty string is
 * ZERO lines (not one empty line); `"\n"` is one empty line.
 */
function splitLines(text: string): { lines: string[]; endsWithNewline: boolean } {
  if (text === "") return { lines: [], endsWithNewline: false };
  const endsWithNewline = text.endsWith("\n");
  const lines = text.split("\n");
  if (endsWithNewline) lines.pop();
  return { lines, endsWithNewline };
}

/** True for the optional pre-hunk header lines jsdiff's `formatPatch` emits (labels ignored). */
function isFileHeaderLine(line: string): boolean {
  return (
    line.startsWith("Index: ") ||
    line.startsWith("===") ||
    line.startsWith("--- ") ||
    line.startsWith("+++ ")
  );
}

/**
 * Attach a `\ No newline at end of file` marker to the side(s) the preceding body line belongs
 * to (context → both). False when there is no line to attach to (a leading or doubled marker).
 */
function attachNoNewline(
  lastPrefix: " " | "-" | "+" | null,
  oldSide: SideLine[],
  newSide: SideLine[],
): boolean {
  if (lastPrefix === null) return false;
  const flag = (side: SideLine[]): boolean => {
    const last = side[side.length - 1];
    if (last === undefined) return false;
    last.noNewline = true;
    return true;
  };
  if (lastPrefix === " ") return flag(oldSide) && flag(newSide);
  if (lastPrefix === "-") return flag(oldSide);
  return flag(newSide);
}

/**
 * Parse the diff text into hunks, or null on any anomaly (malformed hunk header, unknown body
 * prefix, a `\` marker with nothing to attach to, an over-long hunk body, an asymmetric or
 * mid-diff shortfall, zero hunks, trailing garbage). The body is projected into old-side /
 * new-side line lists as it parses: ` ` feeds both sides, `-` the old, `+` the new.
 */
function parseHunks(diff: string): Hunk[] | null {
  const { lines } = splitLines(diff.endsWith("\n") ? diff : `${diff}\n`);
  const hunks: Hunk[] = [];
  let i = 0;
  // Optional file-header preamble (Index: / === / --- / +++), before the first hunk only.
  while (i < lines.length && isFileHeaderLine(lines[i] ?? "")) i++;
  while (i < lines.length) {
    const m = HUNK_HEADER.exec(lines[i] ?? "");
    if (m === null) return null; // trailing garbage / malformed hunk header
    const header: HunkHeader = {
      oldStart: Number(m[1]),
      oldLines: m[2] === undefined ? 1 : Number(m[2]),
      newLines: m[4] === undefined ? 1 : Number(m[4]),
    };
    i++;
    const oldSide: SideLine[] = [];
    const newSide: SideLine[] = [];
    let lastPrefix: " " | "-" | "+" | null = null;
    while (
      i < lines.length &&
      (oldSide.length < header.oldLines ||
        newSide.length < header.newLines ||
        lines[i] === NO_NEWLINE_MARKER)
    ) {
      const line = lines[i] ?? "";
      if (line === NO_NEWLINE_MARKER) {
        if (!attachNoNewline(lastPrefix, oldSide, newSide)) return null;
        lastPrefix = null; // a doubled marker is malformed
        i++;
        continue;
      }
      if (HUNK_HEADER.test(line)) break; // a new hunk began before this one's counts filled
      const prefix = line[0];
      const text = line.slice(1);
      if (prefix === " ") {
        oldSide.push({ text, noNewline: false });
        newSide.push({ text, noNewline: false });
        lastPrefix = " ";
      } else if (prefix === "-") {
        oldSide.push({ text, noNewline: false });
        lastPrefix = "-";
      } else if (prefix === "+") {
        newSide.push({ text, noNewline: false });
        lastPrefix = "+";
      } else {
        return null; // unknown body prefix (an empty line included — jsdiff never emits one)
      }
      i++;
    }
    // Over-long sides cannot happen (the loop stops on filled counts); short sides are tolerated
    // ONLY as the generator's `trimEnd()` artifact — an equal shortfall on both sides, at the
    // very end of the diff — and the applier reconstructs the missing context from the base.
    const oldShort = header.oldLines - oldSide.length;
    const newShort = header.newLines - newSide.length;
    if (oldShort !== newShort || oldShort < 0) return null;
    if (oldShort > 0 && i < lines.length) return null; // short mid-diff is a truncation
    hunks.push({ header, oldSide, newSide });
  }
  if (hunks.length === 0) return null;
  return hunks;
}

/**
 * Apply a unified diff (the jsdiff `createTwoFilesPatch` subset — see the module header) to
 * `base`, strictly and cleanly. Returns the patched text, or null on ANY anomaly: a context or
 * `-` line that does not byte-match the base at the hunk's stated old-file offsets, malformed
 * hunk headers, unknown prefixes, zero hunks, out-of-order/overlapping hunks, trailing garbage,
 * or a no-newline marker that contradicts the base. Never throws.
 */
export function applyUnifiedDiff(base: string, diff: string): string | null {
  const hunks = parseHunks(diff);
  if (hunks === null) return null;

  const { lines: baseLines, endsWithNewline: baseEndsWithNewline } = splitLines(base);
  const output: string[] = [];
  // Whether the CURRENT final output line ends without a newline. Every emission checks it:
  // nothing may follow a no-newline line, so a mid-diff `\` marker on the new side (or a
  // no-newline base tail followed by anything) fails strictly instead of mis-joining.
  let resultNoNewline = false;
  const emit = (text: string, noNewline: boolean): boolean => {
    if (resultNoNewline) return false;
    output.push(text);
    resultNoNewline = noNewline;
    return true;
  };
  /** Whether `index` is the base's final line and the base ends without a newline. */
  const baseNoNewlineAt = (index: number): boolean =>
    index === baseLines.length - 1 && !baseEndsWithNewline;

  let cursor = 0; // 0-based index of the next unconsumed base line
  for (const { header, oldSide, newSide } of hunks) {
    // The 0-based old-file start. Unified-diff quirk: a zero-length old range states the line
    // BEFORE the insertion point (0 = insert at the very start), i.e. already the 0-based index.
    const start = header.oldLines === 0 ? header.oldStart : header.oldStart - 1;
    if (start < cursor || start > baseLines.length) return null; // out-of-order / out-of-range
    // Copy the untouched span before this hunk (all mid-file lines — always newline-terminated).
    for (let i = cursor; i < start; i++) {
      if (!emit(baseLines[i] as string, false)) return null;
    }
    cursor = start;
    // Match the old side against the base at the stated offsets; the new side splices in.
    for (const entry of oldSide) {
      const line = baseLines[cursor];
      if (line === undefined || line !== entry.text) return null;
      if (entry.noNewline !== baseNoNewlineAt(cursor)) return null;
      cursor++;
    }
    for (const entry of newSide) {
      if (!emit(entry.text, entry.noNewline)) return null;
    }
    // Reconstruct trailing context the generator's trimEnd() ate (see parseHunks): consume the
    // next shortfall base lines, verifying each is a whitespace-only, newline-terminated line
    // (a non-whitespace or final-no-newline line could never have been trimmed → truncation).
    const shortfall = header.oldLines - oldSide.length;
    for (let i = 0; i < shortfall; i++) {
      const line = baseLines[cursor];
      if (line === undefined || line.trim() !== "" || baseNoNewlineAt(cursor)) return null;
      if (!emit(line, false)) return null;
      cursor++;
    }
  }

  // Copy the untouched tail; its final line inherits the base's trailing-newline behavior.
  for (let i = cursor; i < baseLines.length; i++) {
    if (!emit(baseLines[i] as string, baseNoNewlineAt(i))) return null;
  }

  if (output.length === 0) return "";
  return output.join("\n") + (resultNoNewline ? "" : "\n");
}
