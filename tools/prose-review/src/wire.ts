// The shared wire vocabulary: closed literal arrays + type guards mirroring
// perk_dev.prose_map.models (the summary.ts local-mirror posture — a vocabulary change
// here is a deliberate wire-contract change, never a silent widening). The parser
// modules consume these guards, so unknown strings are rejected and a successful parse
// is sound for its declared TypeScript type.

export const PROSE_KINDS = [
  "markdown",
  "python-symbol",
  "typescript-tool",
  "typescript-model-call",
  "typescript-symbol",
  "managed-prose",
  "ambient-routing",
] as const;

export type ProseKind = (typeof PROSE_KINDS)[number];

export const DELIVERY_MODES = ["cold", "warm", "headless", "ambient", "subagent"] as const;

export type DeliveryMode = (typeof DELIVERY_MODES)[number];

export const AUDIENCES = ["shipped", "self-development", "both"] as const;

export type Audience = (typeof AUDIENCES)[number];

export const PROSE_ROLES = [
  "launch",
  "context",
  "adapter",
  "skill-detail",
  "ambient-discovery",
  "tool-contract",
  "subagent-instruction",
  "control-guidance",
] as const;

export type ProseRole = (typeof PROSE_ROLES)[number];

export const BOUNDARY_KINDS = [
  "pi-system",
  "borrowed-prompt",
  "user-content",
  "runtime-state",
] as const;

export type BoundaryKind = (typeof BOUNDARY_KINDS)[number];

export function isProseKind(value: unknown): value is ProseKind {
  return typeof value === "string" && (PROSE_KINDS as readonly string[]).includes(value);
}

export function isDeliveryMode(value: unknown): value is DeliveryMode {
  return typeof value === "string" && (DELIVERY_MODES as readonly string[]).includes(value);
}

export function isBoundaryKind(value: unknown): value is BoundaryKind {
  return typeof value === "string" && (BOUNDARY_KINDS as readonly string[]).includes(value);
}

export function isAudience(value: unknown): value is Audience {
  return typeof value === "string" && (AUDIENCES as readonly string[]).includes(value);
}

export function isProseRole(value: unknown): value is ProseRole {
  return typeof value === "string" && (PROSE_ROLES as readonly string[]).includes(value);
}
