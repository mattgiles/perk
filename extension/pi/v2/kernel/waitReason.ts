// The closed wait-reason vocabulary (docs/design/pi-durable-v2-foundations.md §10 step 8): why a
// quiescent execution is not progressing. Vocabulary only — the reason is derived from records
// plus `inspect()` outside the kernel, never stored. Extended only by amending the record.

export const WAIT_REASONS = [
  "pending_decision",
  "unmet_prerequisite",
  "assignment_incomplete",
  "repair_required",
  "parked",
  "blocked",
  "sleeping",
  "cancelled",
  "completed",
] as const;

export type WaitReason = (typeof WAIT_REASONS)[number];

export function isWaitReason(value: string): value is WaitReason {
  return (WAIT_REASONS as readonly string[]).includes(value);
}
