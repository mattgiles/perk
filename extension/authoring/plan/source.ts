// The plan-source feature: where saved/reviewed plan bytes come from. The FILE-FIRST resolution
// law both save surfaces and the review door share: the validated `plan-draft.md` artifact wins;
// the explicit `plan` param is the fallback; the transcript scrape is the universal last resort
// FOR SAVES ONLY — the review surface never sees a transcript tier (an approval auto-saves the
// reviewed bytes, and scraped conversation bytes must never be those).
//
// Pi-free (guard Rule D): the tiers arrive as plain values/thunks — the ADAPTER reads the draft
// through the session seam and binds the transcript scrape over its branch.

/** Where the saved plan bytes came from (the file-first resolution order). */
export type PlanSource = "plan-draft" | "param" | "transcript";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The joined text of a message's content blocks (fail-open: malformed blocks contribute ""). */
function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) =>
      isRecord(block) && block.type === "text" && typeof block.text === "string" ? block.text : "",
    )
    .filter(Boolean)
    .join("\n");
}

/**
 * Best-effort, deterministic: the whole text of the latest assistant message, or null. This is
 * the universal fail-open transcript FALLBACK behind the validated plan-draft artifact (see
 * `resolvePlanSource`) — never a review source. Inherently fragile (it cannot tell a clean plan
 * from conversation): keep the working draft current with `plan_draft` so the validated
 * artifact wins. (There is no tag/marker convention to extract — the borrowed plan-mode package
 * emits no structured plan, only free-form prose.) Fail-open by construction: entries are
 * UNTRUSTED session history, so every field is proven before dereference — a null/sparse entry,
 * a primitive, or a malformed content block is skipped, never thrown on.
 */
export function extractPlanMarkdown(entries: readonly unknown[]): string | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (!isRecord(entry) || entry.type !== "message") continue;
    const message = entry.message;
    if (!isRecord(message) || message.role !== "assistant") continue;
    const text = textOf(message.content).trim();
    if (!text) continue;
    return text;
  }
  return null;
}

/**
 * The shared plan-source resolver every plan surface uses. Resolution order: (1) a non-blank
 * validated draft (the caller has already collapsed absent/invalid reads to `null`); (2) a
 * non-blank explicit param; (3) — save mode only — the transcript scrape thunk; else null.
 *
 * `paramMismatch` is true iff the artifact won AND a non-blank explicit param was passed whose
 * trimmed bytes differ from the artifact's — surfaced by the save rendering, never silently
 * dropped and never a hard-fail. Review mode NEVER sees a transcript tier (the review-surface
 * law): a caller that passes a transcript thunk in review mode still resolves null.
 */
export function resolvePlanSource(
  tiers: { draft: string | null; explicit?: string; transcript?: () => string | null },
  mode: "save" | "review",
): { plan: string; source: PlanSource; paramMismatch: boolean } | null {
  if (tiers.draft !== null && tiers.draft.trim().length > 0) {
    const param = tiers.explicit?.trim() ?? "";
    return {
      plan: tiers.draft,
      source: "plan-draft",
      paramMismatch: param.length > 0 && param !== tiers.draft.trim(),
    };
  }
  if (tiers.explicit !== undefined && tiers.explicit.trim().length > 0) {
    return { plan: tiers.explicit, source: "param", paramMismatch: false };
  }
  if (mode === "save" && tiers.transcript !== undefined) {
    const scraped = tiers.transcript();
    if (scraped !== null) return { plan: scraped, source: "transcript", paramMismatch: false };
  }
  return null;
}
