// Record presentation: kernel records stored as v2 documents and presented back through the record
// catalog (docs/design/pi-durable-v2-foundations.md §6 record keys, identity mappings and record
// presentation).
//
// Invariants:
// - One writer. Every v2 document write goes through `TxRecordSet`, which appends the key to the
//   catalog in the same commit, so a member and its catalog entry land or roll back together.
// - Acquire only what the catalog names, or the key being written: Durable's `Tx` cannot enumerate
//   a family and `tx.doc()` creates what it misses, so a probe by key would create members. An
//   absent cataloged member, an already-cataloged write, or an uncataloged member holding another
//   value is corruption (`KernelInvariantError`), never a refusal.
// - The presented set is the manifest, every cataloged operation record, and each
//   `<decision-id>/continuation` row projected to its continuation record. Unreferenced records are
//   presented like any other, because the catalog lists keys, not references. An attempt's
//   `launch`, worker-conversation and `submit` rows are bookkeeping the kernel never sees.
// - Every value handed out is a plain copy: drafts are revoked once the commit callback returns.
// - The boundary guards check only what the binding itself wrote (family, type, key); the kernel's
//   `indexRecords` validates every semantic rule over the presented set.

import { type JsonValue as ChordJsonValue, copyJson } from "@earendil-works/chord";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { DocumentReader, JsonObject, Tx } from "@earendil-works/pi-durable";
import { jsonEquals } from "../kernel/canonical.ts";
import {
  type AttemptRecord,
  type ContinuationRecord,
  type ExecutionManifest,
  KernelInvariantError,
  type KernelRecord,
  type OperationRecord,
  type RecordIndex,
} from "../kernel/records.ts";
import {
  CATALOG_KIND,
  CatalogDoc,
  type CatalogValue,
  DURABLE_MAP_KIND,
  DurableMapFamily,
  FAMILY_KINDS,
  familyForRecordType,
  isFamilyRecordType,
  MANIFEST_KIND,
  ManifestDoc,
  MISSING_SEED,
  opKindOf,
  RECORD_FAMILIES,
} from "./documents.ts";

/** A durable-map row: the Durable object created for the Perk id it is keyed by. */
export type DurableMapRow = {
  readonly durableKind: "task" | "conversation" | "submission";
  readonly durableId: number;
};

/** The presented record set as read outside a commit. */
export type ReadRecordSet = {
  readonly records: readonly KernelRecord[];
  readonly durableMap: ReadonlyMap<string, DurableMapRow>;
};

const CONTINUATION_SUFFIX = "/continuation";

function corrupt(kind: string, key: string | null, rule: string): KernelInvariantError {
  return new KernelInvariantError(`${kind}${key === null ? "" : ` ${key}`}: ${rule}`);
}

function isPlainObject(value: unknown): value is { readonly [key: string]: unknown } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/** True iff `value` is the read seed: the cataloged member was absent and has just been created. */
function isMissingSeed(value: { readonly [key: string]: unknown }): boolean {
  const keys = Object.keys(value);
  return keys.length === 1 && keys[0] === "perk.v2.missing" && value["perk.v2.missing"] === true;
}

function asJsonObject(value: ChordJsonValue, kind: string, key: string | null): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw corrupt(kind, key, "not a JSON object");
  }
  return value;
}

/**
 * The attempt whose worker conversation is `conversationId`: the one whose `<attempt-id>` durable-map
 * row is `{conversation, conversationId}`, or `null` when no attempt names it.
 */
export function attemptOfConversation(
  index: RecordIndex,
  durableMap: ReadonlyMap<string, DurableMapRow>,
  conversationId: number,
): AttemptRecord | null {
  for (const attempt of index.attempts.values()) {
    const row = durableMap.get(attempt.attemptId);
    if (row?.durableKind === "conversation" && row.durableId === conversationId) return attempt;
  }
  return null;
}

/** The continuation record a `<decision-id>/continuation` durable-map key projects to. */
export function projectContinuation(perkId: string): ContinuationRecord {
  if (opKindOf(perkId) !== "continuation") {
    throw corrupt(DURABLE_MAP_KIND, perkId, "not a continuation key");
  }
  return {
    type: "continuation",
    opId: perkId,
    decisionId: perkId.slice(0, -CONTINUATION_SUFFIX.length),
  };
}

/** The catalog, checked: a boolean `manifest`, and exactly the eight family kinds as string lists. */
export function asCatalog(value: unknown): CatalogValue {
  if (!isPlainObject(value)) throw corrupt(CATALOG_KIND, null, "not an object");
  if (typeof value.manifest !== "boolean")
    throw corrupt(CATALOG_KIND, null, "manifest is not a boolean");
  const members = value.members;
  if (!isPlainObject(members)) throw corrupt(CATALOG_KIND, null, "members is not an object");
  const kinds = Object.keys(members).sort();
  const expected = [...FAMILY_KINDS].sort();
  if (kinds.length !== expected.length || kinds.some((kind, i) => kind !== expected[i])) {
    throw corrupt(CATALOG_KIND, null, "members does not list exactly the eight family kinds");
  }
  const checked: { [kind: string]: string[] } = {};
  for (const kind of FAMILY_KINDS) {
    const keys = members[kind];
    if (!Array.isArray(keys) || !keys.every((key): key is string => typeof key === "string")) {
      throw corrupt(CATALOG_KIND, null, `${kind} is not a list of keys`);
    }
    checked[kind] = [...keys];
  }
  return { manifest: value.manifest, members: checked };
}

/** A cataloged operation record: a plain object of a type its family holds, keyed by its op id. */
export function asKernelRecord(familyKind: string, key: string, value: unknown): OperationRecord {
  if (!isPlainObject(value)) throw corrupt(familyKind, key, "member is not an object");
  if (isMissingSeed(value)) throw corrupt(familyKind, key, "cataloged member is absent");
  const type = value.type;
  if (!isFamilyRecordType(type) || familyForRecordType(type).definition.kind !== familyKind) {
    throw corrupt(familyKind, key, `record type ${JSON.stringify(type)} is not this family's`);
  }
  if (value.opId !== key) throw corrupt(familyKind, key, "op id is not the member's key");
  // The one assertion: family, type and key agree, and the binding wrote this value from a kernel
  // record; `indexRecords` validates its fields over the whole presented set.
  return value as OperationRecord;
}

/** The manifest singleton: a plain object of type `manifest`. */
export function asManifest(value: unknown): ExecutionManifest {
  if (!isPlainObject(value) || value.type !== "manifest") {
    throw corrupt(MANIFEST_KIND, null, 'cataloged manifest is not of type "manifest"');
  }
  // The one assertion: the binding wrote this value from `start`'s manifest; `indexRecords`
  // validates its fields (`manifestProblem`).
  return value as ExecutionManifest;
}

/** A durable-map row: a known Durable kind and a safe-integer id. */
export function asDurableMapRow(key: string, value: unknown): DurableMapRow {
  if (!isPlainObject(value)) throw corrupt(DURABLE_MAP_KIND, key, "row is not an object");
  if (isMissingSeed(value)) throw corrupt(DURABLE_MAP_KIND, key, "cataloged row is absent");
  const { durableKind, durableId } = value;
  if (durableKind !== "task" && durableKind !== "conversation" && durableKind !== "submission") {
    throw corrupt(DURABLE_MAP_KIND, key, "durableKind is not task, conversation or submission");
  }
  if (typeof durableId !== "number" || !Number.isSafeInteger(durableId)) {
    throw corrupt(DURABLE_MAP_KIND, key, "durableId is not a safe integer");
  }
  return { durableKind, durableId };
}

function keysOf(catalog: CatalogValue, kind: string): string[] {
  const keys = catalog.members[kind];
  if (keys === undefined) throw corrupt(CATALOG_KIND, null, `members does not list ${kind}`);
  return keys;
}

/**
 * The presented record set inside one commit, plus its single writer. Built by `loadRecords`; it
 * holds the commit's catalog draft, so every write appends its key in the same commit.
 */
export class TxRecordSet {
  /** The presented set as loaded; writes do not grow it (the caller derives the set after). */
  readonly records: readonly KernelRecord[];
  /** Every durable-map row, loaded or written in this commit (it grows with `writeRow`). */
  readonly durableMap: ReadonlyMap<string, DurableMapRow>;
  readonly #tx: Tx;
  readonly #catalog: CatalogValue;
  readonly #rows: Map<string, DurableMapRow>;

  constructor(
    tx: Tx,
    catalog: CatalogValue,
    records: readonly KernelRecord[],
    rows: Map<string, DurableMapRow>,
  ) {
    this.#tx = tx;
    this.#catalog = catalog;
    this.records = records;
    this.#rows = rows;
    this.durableMap = rows;
  }

  /** Write one kernel record and catalog its key. A continuation is never written (see `writeRow`). */
  async write(record: KernelRecord): Promise<void> {
    if (record.type === "manifest") return this.#writeManifest(record);
    if (record.type === "continuation") {
      throw corrupt(
        DURABLE_MAP_KIND,
        record.opId,
        "a continuation is a durable-map row, never a record write",
      );
    }
    const kind = familyForRecordType(record.type).definition.kind;
    const keys = keysOf(this.#catalog, kind);
    if (keys.includes(record.opId)) throw corrupt(kind, record.opId, "already cataloged");
    const seed = asJsonObject(copyJson(record), kind, record.opId);
    const draft = await this.#tx.doc(familyForRecordType(record.type), record.opId, seed);
    if (!jsonEquals(copyJson(draft), record)) {
      throw corrupt(kind, record.opId, "an uncataloged member already holds another value");
    }
    keys.push(record.opId);
  }

  /** Write the durable-map row for `perkId` and catalog its key. */
  async writeRow(perkId: string, row: DurableMapRow): Promise<void> {
    const keys = keysOf(this.#catalog, DURABLE_MAP_KIND);
    if (keys.includes(perkId)) throw corrupt(DURABLE_MAP_KIND, perkId, "already cataloged");
    const value: DurableMapRow = { durableKind: row.durableKind, durableId: row.durableId };
    const draft = await this.#tx.doc(DurableMapFamily, perkId, { ...value });
    if (!jsonEquals(copyJson(draft), value)) {
      throw corrupt(DURABLE_MAP_KIND, perkId, "an uncataloged row already holds another value");
    }
    keys.push(perkId);
    this.#rows.set(perkId, value);
  }

  async #writeManifest(manifest: ExecutionManifest): Promise<void> {
    if (this.#catalog.manifest) throw corrupt(MANIFEST_KIND, null, "already cataloged");
    const draft: JsonObject = await this.#tx.doc(ManifestDoc);
    if (!jsonEquals(copyJson(draft), {})) {
      throw corrupt(MANIFEST_KIND, null, "an uncataloged manifest already holds a value");
    }
    for (const [field, value] of Object.entries(manifest)) draft[field] = copyJson(value);
    this.#catalog.manifest = true;
  }
}

/**
 * Load the presented set inside a commit: the catalog, the manifest when cataloged, each cataloged
 * member of the seven record families, then each cataloged durable-map row (continuation rows also
 * projected into `records`). On an unstarted store the catalog acquisition creates an empty
 * catalog; only a commit that writes keeps it, so a refused commit rolls it back.
 */
export async function loadRecords(tx: Tx): Promise<TxRecordSet> {
  const draft: CatalogValue = await tx.doc(CatalogDoc);
  const catalog = asCatalog(copyJson(draft));
  const records: KernelRecord[] = [];
  if (catalog.manifest) records.push(asManifest(copyJson(await tx.doc(ManifestDoc))));
  for (const family of RECORD_FAMILIES) {
    const kind = family.definition.kind;
    for (const key of keysOf(catalog, kind)) {
      const value = copyJson(await tx.doc(family, key, MISSING_SEED));
      records.push(asKernelRecord(kind, key, value));
    }
  }
  const rows = new Map<string, DurableMapRow>();
  for (const key of keysOf(catalog, DURABLE_MAP_KIND)) {
    rows.set(
      key,
      asDurableMapRow(key, copyJson(await tx.doc(DurableMapFamily, key, MISSING_SEED))),
    );
    if (opKindOf(key) === "continuation") records.push(projectContinuation(key));
  }
  return new TxRecordSet(tx, draft, records, rows);
}

/**
 * Read the presented set outside a commit, through `snapshot()` (which never creates anything): the
 * catalog first, then its members. Members are immutable and cataloged in the commit that writes
 * them, so the catalog read first fixes one consistent committed state. No catalog means not
 * started: an empty set.
 */
export async function readRecords(reader: DocumentReader): Promise<ReadRecordSet> {
  const stored = await reader.snapshot(CatalogDoc, BACKGROUND_CONTEXT);
  if (stored === undefined) return { records: [], durableMap: new Map() };
  const catalog = asCatalog(copyJson(stored));
  const records: KernelRecord[] = [];
  if (catalog.manifest) {
    const manifest = await reader.snapshot(ManifestDoc, BACKGROUND_CONTEXT);
    if (manifest === undefined) throw corrupt(MANIFEST_KIND, null, "cataloged manifest is absent");
    records.push(asManifest(copyJson(manifest)));
  }
  for (const family of RECORD_FAMILIES) {
    const kind = family.definition.kind;
    for (const key of keysOf(catalog, kind)) {
      const value = await reader.snapshot(family, key, BACKGROUND_CONTEXT);
      if (value === undefined) throw corrupt(kind, key, "cataloged member is absent");
      records.push(asKernelRecord(kind, key, copyJson(value)));
    }
  }
  const durableMap = new Map<string, DurableMapRow>();
  for (const key of keysOf(catalog, DURABLE_MAP_KIND)) {
    const value = await reader.snapshot(DurableMapFamily, key, BACKGROUND_CONTEXT);
    if (value === undefined) throw corrupt(DURABLE_MAP_KIND, key, "cataloged row is absent");
    durableMap.set(key, asDurableMapRow(key, copyJson(value)));
    if (opKindOf(key) === "continuation") records.push(projectContinuation(key));
  }
  return { records, durableMap };
}
