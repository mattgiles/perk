// Model-visible output capping (route-don't-relay). The byte-cap helper the stage-execution
// seam and the CI executor bound their model-facing text with: full results stay in scratch
// files; only a capped, notice-carrying slice reaches the model.

/** The model-visible byte cap (matches subagent's PER_TASK_OUTPUT_CAP); overridable per call. */
export const DEFAULT_MODEL_VISIBLE_CAP = 50 * 1024;

export interface CapResult {
  /** The (possibly truncated) text safe to show the model. */
  shown: string;
  /** Total UTF-8 byte length of the original text. */
  bytesTotal: number;
  /** UTF-8 byte length of `shown` (before the truncation notice). */
  bytesShown: number;
  /** Whether truncation occurred. */
  truncated: boolean;
}

/**
 * UTF-8-byte-safe truncation (subagent's byte-trim loop). Under cap ⇒ unchanged, truncated:false.
 * When truncated, a notice points at the scratch file holding the full result; the notice sits at
 * the cut edge (appended in head mode, prepended in tail mode) so a top-down reader immediately
 * knows which side is missing.
 *
 * `keep` mirrors the SDK's truncateHead/truncateTail guidance: "head" (default) for
 * model-authored summaries/handoffs where the beginning matters; "tail" for command/CI logs where
 * failure summaries live at the end. Deliberately perk's own byte-only util (not the SDK's
 * line-count-aware `truncateTail`): `CapResult`'s byte fields and the scratch-pointing notice are
 * load-bearing in `CiCheckResult`. Pure.
 */
export function capForModel(
  text: string,
  cap: number = DEFAULT_MODEL_VISIBLE_CAP,
  scratchPath: string | null = null,
  keep: "head" | "tail" = "head",
): CapResult {
  const bytesTotal = Buffer.byteLength(text, "utf8");
  if (bytesTotal <= cap) {
    return { shown: text, bytesTotal, bytesShown: bytesTotal, truncated: false };
  }
  let trimmed = keep === "head" ? text.slice(0, cap) : text.slice(-cap);
  while (Buffer.byteLength(trimmed, "utf8") > cap) {
    trimmed = keep === "head" ? trimmed.slice(0, -1) : trimmed.slice(1);
  }
  const bytesShown = Buffer.byteLength(trimmed, "utf8");
  const omitted = bytesTotal - bytesShown;
  const where = scratchPath ? ` Full output preserved at ${scratchPath}.` : "";
  const shown =
    keep === "head"
      ? `${trimmed}\n\n[Output truncated: ${omitted} bytes omitted.${where}]`
      : `[Output truncated: ${omitted} bytes omitted.${where}]\n\n${trimmed}`;
  return { shown, bytesTotal, bytesShown, truncated: true };
}
