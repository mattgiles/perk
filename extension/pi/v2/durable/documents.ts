// The v2 document definitions and the key-shape lookups over them
// (docs/design/pi-durable-v2-foundations.md §6 record keys and record presentation).
//
// Invariants:
// - Every v2 document is session-scoped, version 1, and checkpoints on every write: each record is
//   written once and is small, so a member is always one complete base.
// - Every kind starts with `perk.v2.` (Durable reserves `pi.`).
// - Each operation-record family holds the record types its op kind names, so receipt lookup by op
//   id addresses exactly one family; `continuation` and `launch` have no family of their own — their
//   record is their durable-map row.
// - Both lookups are total over their closed domains (checked by the mapped types below), and
//   `opKindOf` is pure string inspection: a garbage id yields `null` or a key that simply misses.

import {
  defineDoc,
  defineDocFamily,
  type JsonObject,
  type SessionDocFamilyToken,
  type SessionDocToken,
} from "@earendil-works/pi-durable";
import type { OpKind } from "../kernel/identity.ts";
import type { OperationRecord } from "../kernel/records.ts";

export const MANIFEST_KIND = "perk.v2.manifest";
export const CATALOG_KIND = "perk.v2.catalog";
export const OBSERVATION_KIND = "perk.v2.observation";
export const ASSIGNMENT_KIND = "perk.v2.assignment";
export const ATTEMPT_KIND = "perk.v2.attempt";
export const OUTCOME_KIND = "perk.v2.outcome";
export const DECISION_KIND = "perk.v2.decision";
export const REPLY_KIND = "perk.v2.reply";
export const CANCELLATION_KIND = "perk.v2.cancellation";
export const DURABLE_MAP_KIND = "perk.v2.durable-map";

/** The eight family kinds, in the order the record catalog lists them. */
export const FAMILY_KINDS = [
  OBSERVATION_KIND,
  ASSIGNMENT_KIND,
  ATTEMPT_KIND,
  OUTCOME_KIND,
  DECISION_KIND,
  REPLY_KIND,
  CANCELLATION_KIND,
  DURABLE_MAP_KIND,
] as const;

export type FamilyKind = (typeof FAMILY_KINDS)[number];

/**
 * The record catalog: whether the manifest exists, and every family member's key in write order.
 * Every family kind is listed from creation, so a missing kind is corruption, never "no members".
 */
export type CatalogValue = { manifest: boolean; members: { [kind: string]: string[] } };

/** A fresh, empty catalog listing all eight family kinds. */
export function emptyCatalog(): CatalogValue {
  const members: { [kind: string]: string[] } = {};
  for (const kind of FAMILY_KINDS) members[kind] = [];
  return { manifest: false, members };
}

/** A v2 operation-record or durable-map family: members keyed by op id or Perk id, seeded whole. */
export type RecordFamily = SessionDocFamilyToken<JsonObject, JsonObject>;

/** The execution manifest singleton; `initial` is empty until `start` assigns its fields. */
export const ManifestDoc: SessionDocToken<JsonObject> = defineDoc<JsonObject>({
  kind: MANIFEST_KIND,
  version: 1,
  scope: "session",
  initial: () => ({}),
  checkpointWhen: () => true,
});

export const CatalogDoc: SessionDocToken<CatalogValue> = defineDoc<CatalogValue>({
  kind: CATALOG_KIND,
  version: 1,
  scope: "session",
  initial: emptyCatalog,
  checkpointWhen: () => true,
});

/** A record family whose new member is exactly its seed (an existing member ignores the seed). */
function recordFamily(kind: FamilyKind): RecordFamily {
  return defineDocFamily<JsonObject, JsonObject>({
    kind,
    version: 1,
    scope: "session",
    family: true,
    initial: (seed) => seed,
    checkpointWhen: () => true,
  });
}

export const ObservationFamily = recordFamily(OBSERVATION_KIND);
export const AssignmentFamily = recordFamily(ASSIGNMENT_KIND);
export const AttemptFamily = recordFamily(ATTEMPT_KIND);
export const OutcomeFamily = recordFamily(OUTCOME_KIND);
export const DecisionFamily = recordFamily(DECISION_KIND);
export const ReplyFamily = recordFamily(REPLY_KIND);
export const CancellationFamily = recordFamily(CANCELLATION_KIND);
export const DurableMapFamily = recordFamily(DURABLE_MAP_KIND);

/** The seven operation-record families, in catalog order (the durable-map family is not one). */
export const RECORD_FAMILIES: readonly RecordFamily[] = [
  ObservationFamily,
  AssignmentFamily,
  AttemptFamily,
  OutcomeFamily,
  DecisionFamily,
  ReplyFamily,
  CancellationFamily,
];

export type V2DocumentToken =
  | SessionDocToken<JsonObject>
  | SessionDocToken<CatalogValue>
  | RecordFamily;

/** Every v2 document definition: the two singletons, then the eight families in catalog order. */
export const V2_DOCUMENTS: readonly V2DocumentToken[] = [
  ManifestDoc,
  CatalogDoc,
  ObservationFamily,
  AssignmentFamily,
  AttemptFamily,
  OutcomeFamily,
  DecisionFamily,
  ReplyFamily,
  CancellationFamily,
  DurableMapFamily,
];

/** The operation-record types that live in a family (a continuation is a projected durable-map row). */
export type FamilyRecordType = Exclude<OperationRecord["type"], "continuation">;

const FAMILY_BY_RECORD_TYPE: { readonly [T in FamilyRecordType]: RecordFamily } = {
  observation: ObservationFamily,
  assignment: AssignmentFamily,
  attempt: AttemptFamily,
  "report-outcome": OutcomeFamily,
  "aggregate-outcome": OutcomeFamily,
  decision: DecisionFamily,
  reply: ReplyFamily,
  cancellation: CancellationFamily,
};

const FAMILY_BY_OP_KIND: { readonly [K in OpKind]: RecordFamily } = {
  observe: ObservationFamily,
  admit: AssignmentFamily,
  submit: AttemptFamily,
  launch: DurableMapFamily,
  "accept-report": OutcomeFamily,
  aggregate: OutcomeFamily,
  "open-decision": DecisionFamily,
  reply: ReplyFamily,
  continuation: DurableMapFamily,
  cancel: CancellationFamily,
};

export function isFamilyRecordType(type: unknown): type is FamilyRecordType {
  return typeof type === "string" && Object.hasOwn(FAMILY_BY_RECORD_TYPE, type);
}

/** The family that holds records of `type`. */
export function familyForRecordType(type: FamilyRecordType): RecordFamily {
  return FAMILY_BY_RECORD_TYPE[type];
}

/** The family an op id of `kind` is keyed in. */
export function familyForOpKind(kind: OpKind): RecordFamily {
  return FAMILY_BY_OP_KIND[kind];
}

/** Op kinds that end their op id. */
const SUFFIX_KINDS: readonly OpKind[] = [
  "admit",
  "submit",
  "launch",
  "accept-report",
  "open-decision",
  "reply",
  "continuation",
  "cancel",
];

/** Op kinds followed by an op-key segment. */
const KEYED_KINDS: readonly OpKind[] = ["observe", "aggregate"];

/** The op kind an op id names, or `null` when it names none. */
export function opKindOf(opId: string): OpKind | null {
  if (typeof opId !== "string") return null;
  const segments = opId.split("/");
  const last = segments.at(-1);
  const suffix = SUFFIX_KINDS.find((kind) => kind === last);
  if (suffix !== undefined) return suffix;
  const keyed = segments.at(-2);
  return KEYED_KINDS.find((kind) => kind === keyed) ?? null;
}

/**
 * The seed every catalog-driven read passes. A cataloged member always exists, so a read that
 * comes back equal to this seed means the member was absent — the get-or-create acquisition just
 * created it — which the boundary guards report as corruption.
 */
export const MISSING_SEED: JsonObject = Object.freeze({ "perk.v2.missing": true });
