// The headless worker's model-call policy (contracts.md §8.11 "Model-call policy") — pure, no SDK
// vocabulary (guard Rule F: only `sdkAdapter.ts` carries `@earendil-works/*` specifiers).
//
// Two layers, deliberately unequal:
//
//  - The HARD layer is `WORKER_CODEMODE_MODELS`: the worker-owned codemode factory is constructed
//    without the `models` namespace, so a script in the worker's own codemode cannot reach a
//    classifier or image model at all — however the call is spelled.
//  - The ADVISORY layer is `refusedModelCallIn`: a textual screen the worker's hidden policy
//    extension runs over every `codemode` call before it executes, turning a script that names
//    `models.classify(` / `models.generateImages(` into a typed, actionable refusal instead of a
//    sandbox `ReferenceError`. It is bypassable by construction (`const m = models;
//    m.classify(…)` is not matched) — the hard layer is what holds; the screen only makes the
//    common spelling legible.
//
// Deliberately NOT screened: the catalog reads (`models.getModelsOfType`,
// `models.getAvailableOfType`, `models.getModelOfType`) — they are unmetered and start no model
// call.

/**
 * The `models` option for the worker-owned codemode factory: `false` — a CONSTRAINED CAPABILITY.
 * Pi reports a script's `models.*` usage only when the script ends (mid-script progress carries
 * per-call cost, never tokens), and no public interface bounds or meters a call while a script
 * runs, so a running script cannot be held to the stage token budget. Scope: the factory the
 * worker itself constructs — a codemode a project extension registers is the repo's own choice.
 * The worker does not yet register Pi's builtin factories itself; that registration consumes this
 * constant when it lands.
 *
 * Retirement condition: Pi surfaces a script's per-call `models.*` usage on a public mid-script
 * surface (e.g. `usage` on `tool_execution_update` partials) or offers a public factory-level call
 * bound. The worker e2e tier pins the absence of usage on partials, so it fails loudly when that
 * changes.
 */
export const WORKER_CODEMODE_MODELS = false as const;

/** The model-call kinds the worker refuses from a codemode script. */
export type RefusedModelCall = "image_generation" | "classifier";

/** The stable prefix every refusal reason starts with (followed by the kind and `)`). */
export const MODEL_CALL_REFUSAL_PREFIX = "perk worker: model call refused (";

/** `models.classify(` / `models.generateImages(` with any interior whitespace. */
const MODEL_CALL_PATTERN = /\bmodels\s*\.\s*(classify|generateImages)\s*\(/;

/**
 * The kind of the FIRST metered model call (by position) a codemode script literally names, or
 * `null` when it names none. Heuristic by design (see the header): an aliased `models` is not
 * matched, and catalog reads are never refused.
 */
export function refusedModelCallIn(code: string): RefusedModelCall | null {
  // A non-global pattern: `exec` returns the leftmost match.
  const match = MODEL_CALL_PATTERN.exec(code);
  if (match === null) return null;
  return match[1] === "generateImages" ? "image_generation" : "classifier";
}

/**
 * The worker's tool-call screen (the policy extension's decision, pure): the refusal reason for a
 * `codemode` call (any registrar) whose string `code` names a metered model call, else `null`.
 * Every other tool, and a non-string `code` (left to the tool's own validation), passes.
 */
export function codemodeCallRefusal(
  toolName: string,
  input: Record<string, unknown>,
): string | null {
  if (toolName !== "codemode" || typeof input.code !== "string") return null;
  const kind = refusedModelCallIn(input.code);
  return kind === null ? null : modelCallRefusalReason(kind);
}

/** The typed, actionable reason a refused codemode call returns to the model. */
export function modelCallRefusalReason(kind: RefusedModelCall): string {
  if (kind === "image_generation") {
    return (
      `${MODEL_CALL_REFUSAL_PREFIX}image_generation) — \`models.generateImages\` is refused in ` +
      "the headless worker this release: the stage budget has no count/cost dimension and image " +
      "generation is not reliably token-metered (its reported usage is provider-dependent). " +
      "Finish the task with ordinary tools; do not retry the call."
    );
  }
  return (
    `${MODEL_CALL_REFUSAL_PREFIX}classifier) — \`models.classify\` is not available from ` +
    "scripts in the headless worker this release: Pi reports a script's model usage only when " +
    "the script ends, so a running script cannot be held to the token budget. Finish the task " +
    "with ordinary tools; do not retry the call."
  );
}
