// The closed refusal vocabulary (docs/design/pi-durable-v2-foundations.md §9). A refusal is an
// application outcome: the commit that raised it rolls back and records nothing. The list is
// extended only by amending the record.

export const REFUSAL_REASONS = [
  "invalid_input",
  "unknown_decision",
  "stale_subject",
  "superseded",
  "cancelled",
  "duplicate_conflict",
  "invalid_report",
  "snapshot_tampered",
  "already_started",
] as const;

export type RefusalReason = (typeof REFUSAL_REASONS)[number];

export function isRefusalReason(value: string): value is RefusalReason {
  return (REFUSAL_REASONS as readonly string[]).includes(value);
}

export type Refusal = { readonly reason: RefusalReason; readonly detail: string };

/** The throwable form of a refusal, raised inside the commit callback so the commit rolls back. */
export class KernelRefusal extends Error {
  readonly reason: RefusalReason;
  readonly detail: string;

  constructor(refusal: Refusal) {
    super(`${refusal.reason}: ${refusal.detail}`);
    this.name = "KernelRefusal";
    this.reason = refusal.reason;
    this.detail = refusal.detail;
  }
}
