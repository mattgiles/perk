/** Review-surface outcomes shared by provider transport and the first-party Pi editor.
 * Dismissed and implement-here are first-party only; a provider never manufactures them.
 */
export type ReviewOutcome =
  | { status: "unavailable"; warning: string }
  | { status: "aborted" }
  | { status: "dismissed" }
  | { status: "implement-here"; reviewId: string }
  | { status: "completed"; approved: boolean; feedback?: string; reviewId: string };
