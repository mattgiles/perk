// The perk feedback publisher — the Hunk extension `perk plan watch` loads with `--extension`
// (contracts.md §8.58). Saving a human note in the watched diff appends ONE immutable feedback
// record to the worktree-local outbox (`.perk/workflow/hunk-watch/outbox.ndjson`); the perk Pi
// extension's receiver drains it into the live implement session.
//
// SELF-CONTAINED on purpose: node builtins only, no relative imports — this file is bundled
// alone into the wheel (`perk/_hunk/perkFeedback.ts`) and must load standalone under Hunk's
// runtime. It therefore carries local structural mirrors of the narrow Hunk API slice it uses
// (`hunkdiff` is deliberately NOT a devDependency — its dep tree includes the bun runtime; the
// mirror-a-narrow-slice pattern is the established one for deep-only types) and is the
// hunk-plane's single `.perk/workflow` path construction site (it cannot import the cache
// seam; the two sites are pinned together by a path-parity test).
//
// Publication is synchronous and durable: one appendFileSync per record (O_APPEND — the §8.58
// append-only stream discipline), nothing flushed on shutdown, no daemon queries, no network,
// no shell, no writes to reviewed files.

import { appendFileSync, lstatSync, mkdirSync, realpathSync } from "node:fs";
import { join } from "node:path";

// --- local structural mirrors of the Hunk extension API slice (verified generations) --------

/** The event-context slice every handler receives (`ExtensionEventContext` ⊃ this). */
export interface HunkEventContextSlice {
  cwd: string;
  notify(message: string, type?: "info" | "warning" | "error"): void;
}

/** `ExtensionReviewNote` as both verified generations (v2 types, v4 docs) report it. */
export interface HunkReviewNote {
  id: string;
  fileId: string;
  filePath: string;
  hunkIndex: number;
  side: "old" | "new";
  line: number;
  body: string;
  /** True while the note is still being composed rather than saved. */
  draft: boolean;
}

interface HunkEventPayloadSlices {
  startup: { cwd: string };
  changeset_loaded: { changeset: { id: string } };
  note_created: { note: HunkReviewNote };
  session_reload: { changeset: { id: string } };
}

/** The `HunkExtensionAPI` slice the publisher touches: `apiVersion` + `on` + `log`. */
export interface HunkApiSlice {
  readonly apiVersion: number;
  on<E extends keyof HunkEventPayloadSlices>(
    event: E,
    handler: (payload: HunkEventPayloadSlices[E], ctx: HunkEventContextSlice) => void,
  ): void;
  log(message: string): void;
}

// --- the publisher contract (§8.58 feedback record v1) ---------------------------------------

/**
 * The verified-generation gate: note handlers register only under an `apiVersion` with an
 * examined artifact — v2 (the installed 0.18.1 `.d.ts`) and v4 (the vendored current docs'
 * event table). v3 has NO examined artifact and is deliberately excluded; add a generation
 * only after verifying one. Runtime payload validation guards drift WITHIN a generation.
 * v4 is accepted on documentation evidence ONLY — the resolved binary speaks v2, so no v4
 * payload has ever been observed live; runtime payload validation is the containment. Prove
 * v4 against a real v4 binary on the next hunk upgrade that ships one.
 */
export const SUPPORTED_HUNK_API_VERSIONS: ReadonlySet<number> = new Set([2, 4]);

/** §8.58 bounds: refuse visibly, never truncate or claim queued. */
export const MAX_BODY_BYTES = 16_384;
export const MAX_RECORD_BYTES = 32_768;

/** Feedback record v1 — a local mirror of the receiver's shape (the contract is the FILE). */
export interface FeedbackRecordV1 {
  schema: 1;
  feedback_id: string;
  watch_instance_id: string;
  plan_id: string;
  created_at: string;
  changeset_id: string | null;
  anchor: { file_path: string; hunk_index: number; side: "old" | "new"; line: number };
  body: string;
}

/**
 * This plane's single `.perk/workflow/hunk-watch` construction site (path-parity-tested
 * against the interior cache seam's `hunkWatchDir`/`hunkOutboxPath`).
 */
export function hunkWatchPaths(root: string): { dir: string; outbox: string } {
  const dir = join(root, ".perk", "workflow", "hunk-watch");
  return { dir, outbox: join(dir, "outbox.ndjson") };
}

/** Newline-normalize (`\r\n`→`\n`) and outer-trim a note body. */
export function normalizeBody(body: string): string {
  return body.replaceAll("\r\n", "\n").trim();
}

export type NoteValidation =
  | { ok: true; note: HunkReviewNote }
  /** `draft: true` is an unsaved draft — skipped silently (saving fires another event). */
  | { ok: false; kind: "draft" }
  /** A non-boolean `draft` is anomalous — skipped with a log diagnostic, never published. */
  | { ok: false; kind: "anomalous-draft"; detail: string }
  | { ok: false; kind: "malformed"; detail: string };

/**
 * Structurally validate a `note_created` payload (applied on EVERY event regardless of
 * generation — the guard against shape drift within a verified generation).
 */
export function validateNotePayload(payload: unknown): NoteValidation {
  if (typeof payload !== "object" || payload === null) {
    return { ok: false, kind: "malformed", detail: "payload is not an object" };
  }
  const note = (payload as { note?: unknown }).note;
  if (typeof note !== "object" || note === null) {
    return { ok: false, kind: "malformed", detail: "payload carries no note object" };
  }
  const n = note as Record<string, unknown>;
  if (n.draft !== false) {
    if (n.draft === true) return { ok: false, kind: "draft" };
    return {
      ok: false,
      kind: "anomalous-draft",
      detail: `note.draft is ${JSON.stringify(n.draft)} (expected the boolean false)`,
    };
  }
  const problems: string[] = [];
  if (typeof n.id !== "string" || n.id === "") problems.push("id");
  if (typeof n.filePath !== "string" || n.filePath === "") problems.push("filePath");
  if (typeof n.body !== "string") problems.push("body");
  if (typeof n.hunkIndex !== "number" || !Number.isInteger(n.hunkIndex) || n.hunkIndex < 0) {
    problems.push("hunkIndex");
  }
  if (n.side !== "old" && n.side !== "new") problems.push("side");
  if (typeof n.line !== "number" || !Number.isInteger(n.line) || n.line < 1) problems.push("line");
  if (problems.length > 0) {
    return {
      ok: false,
      kind: "malformed",
      detail: `invalid note field(s): ${problems.join(", ")}`,
    };
  }
  return { ok: true, note: note as HunkReviewNote };
}

/** Build feedback record v1 from a validated note (`feedback_id = <watchId>:<note.id>`). */
export function buildFeedbackRecord(
  note: HunkReviewNote,
  opts: { watchId: string; planId: string; changesetId: string | null; createdAt: string },
): FeedbackRecordV1 {
  return {
    schema: 1,
    feedback_id: `${opts.watchId}:${note.id}`,
    watch_instance_id: opts.watchId,
    plan_id: opts.planId,
    created_at: opts.createdAt,
    changeset_id: opts.changesetId,
    anchor: {
      file_path: note.filePath,
      hunk_index: note.hunkIndex,
      side: note.side,
      line: note.line,
    },
    body: note.body,
  };
}

/** True when `path` exists AND is itself a symlink (a missing path is fine — fresh outbox). */
function isSymlink(path: string): boolean {
  try {
    return lstatSync(path).isSymbolicLink();
  } catch {
    return false;
  }
}

export type PublishResult =
  | { status: "published"; record: FeedbackRecordV1 }
  /** Nothing written, nothing to say aloud (drafts); `log` carries the anomaly diagnostic. */
  | { status: "skipped"; log?: string }
  /** Nothing written; `warning` is shown to the reviewer (never claims queued). */
  | { status: "refused"; warning: string };

export interface PublisherDeps {
  watchId: string;
  planId: string;
  /** The declared worktree root (`PERK_HUNK_WORKTREE_ROOT`) — the only tree we may write. */
  worktreeRoot: string;
  /** One append per record — the injected side-effect seam (production: appendFileSync). */
  append(path: string, line: string): void;
  /** Publisher-assigned `created_at` (ISO-8601). */
  now(): string;
}

export interface Publisher {
  publish(payload: unknown, context: { cwd: string; changesetId: string | null }): PublishResult;
}

export function createPublisher(deps: PublisherDeps): Publisher {
  return {
    publish(payload, context) {
      const validation = validateNotePayload(payload);
      if (!validation.ok) {
        if (validation.kind === "draft") return { status: "skipped" };
        if (validation.kind === "anomalous-draft") {
          return { status: "skipped", log: `perk feedback: skipped a note — ${validation.detail}` };
        }
        return { status: "refused", warning: validation.detail };
      }

      // The event cwd must realpath-equal the DECLARED worktree root before any store path is
      // derived — never write into whatever tree an unexpected event points at.
      let eventRoot: string;
      let declaredRoot: string;
      try {
        eventRoot = realpathSync(context.cwd);
        declaredRoot = realpathSync(deps.worktreeRoot);
      } catch (error) {
        return { status: "refused", warning: `could not resolve the worktree root (${error})` };
      }
      if (eventRoot !== declaredRoot) {
        return {
          status: "refused",
          warning: `the review's cwd (${context.cwd}) is not the watched worktree (${deps.worktreeRoot})`,
        };
      }

      const body = normalizeBody(validation.note.body);
      if (body === "") {
        return { status: "refused", warning: "the note body is empty after trimming" };
      }
      if (Buffer.byteLength(body, "utf8") > MAX_BODY_BYTES) {
        return {
          status: "refused",
          warning: `the note body exceeds ${MAX_BODY_BYTES} bytes — shorten it (it was NOT queued)`,
        };
      }
      const record = buildFeedbackRecord(
        { ...validation.note, body },
        {
          watchId: deps.watchId,
          planId: deps.planId,
          changesetId: context.changesetId,
          createdAt: deps.now(),
        },
      );
      const line = `${JSON.stringify(record)}\n`;
      if (Buffer.byteLength(line, "utf8") > MAX_RECORD_BYTES) {
        return {
          status: "refused",
          warning: `the serialized feedback record exceeds ${MAX_RECORD_BYTES} bytes (it was NOT queued)`,
        };
      }
      const paths = hunkWatchPaths(declaredRoot);
      try {
        mkdirSync(paths.dir, { recursive: true });
        // Symlink fence (§8.58): `declaredRoot` is already canonical, so every component of the
        // store path must resolve to ITSELF — a force-tracked symlink at `.perk`/`workflow`/
        // `hunk-watch` (or a symlinked outbox file) would otherwise redirect this append
        // outside the worktree. Check-then-append TOCTOU is accepted: the threat is static
        // checkout content, not a live same-uid attacker.
        if (realpathSync(paths.dir) !== paths.dir) {
          return {
            status: "refused",
            warning: `the hunk-watch dir is symlinked (${paths.dir} resolves elsewhere) — refusing to write`,
          };
        }
        if (isSymlink(paths.outbox)) {
          return {
            status: "refused",
            warning: `the feedback outbox is a symlink (${paths.outbox}) — refusing to write`,
          };
        }
        deps.append(paths.outbox, line); // the full record in ONE append call
      } catch (error) {
        return { status: "refused", warning: `could not write the feedback outbox: ${error}` };
      }
      return { status: "published", record };
    },
  };
}

// --- the Hunk extension factory (the default export hunk loads) ------------------------------

function readLaunchEnv(
  env: Record<string, string | undefined>,
): { watchId: string; planId: string; worktreeRoot: string } | { missing: string[] } {
  const watchId = (env.PERK_HUNK_WATCH_ID ?? "").trim();
  const planId = (env.PERK_HUNK_PLAN_ID ?? "").trim();
  const worktreeRoot = (env.PERK_HUNK_WORKTREE_ROOT ?? "").trim();
  const missing = [
    ...(watchId === "" ? ["PERK_HUNK_WATCH_ID"] : []),
    ...(planId === "" ? ["PERK_HUNK_PLAN_ID"] : []),
    ...(worktreeRoot === "" ? ["PERK_HUNK_WORKTREE_ROOT"] : []),
  ];
  if (missing.length > 0) return { missing };
  return { watchId, planId, worktreeRoot };
}

/**
 * Wire the publisher into a Hunk session. Feedback fails CLOSED, reviewing stays OPEN: an
 * unsupported API generation or missing launch metadata registers no note handler and says so
 * loudly once at startup — the watched diff stays fully usable either way.
 */
export default function perkFeedback(hunk: HunkApiSlice): void {
  if (!SUPPORTED_HUNK_API_VERSIONS.has(hunk.apiVersion)) {
    const supported = [...SUPPORTED_HUNK_API_VERSIONS].join(", ");
    const message =
      `perk feedback disabled — this hunk speaks extension API v${hunk.apiVersion}, but perk ` +
      `has verified only v{${supported}}; reviewing works normally, saved notes will NOT reach ` +
      "the implementation session (update perk or hunk)";
    hunk.log(message);
    hunk.on("startup", (_payload, ctx) => ctx.notify(message, "warning"));
    return;
  }

  const env = readLaunchEnv(process.env);
  if ("missing" in env) {
    const message =
      `perk feedback disabled — missing launch metadata (${env.missing.join(", ")}); launch ` +
      "the watch via `perk plan watch` to enable feedback (reviewing works normally)";
    hunk.log(message);
    hunk.on("startup", (_payload, ctx) => ctx.notify(message, "warning"));
    return;
  }

  let changesetId: string | null = null;
  const publisher = createPublisher({
    watchId: env.watchId,
    planId: env.planId,
    worktreeRoot: env.worktreeRoot,
    append: (path, line) => appendFileSync(path, line, "utf8"),
    now: () => new Date().toISOString(),
  });

  hunk.on("startup", (_payload, ctx) => {
    ctx.notify(
      "perk feedback active — saving a human note sends it to the implementation session",
      "info",
    );
  });
  hunk.on("changeset_loaded", (payload) => {
    changesetId = typeof payload?.changeset?.id === "string" ? payload.changeset.id : null;
  });
  hunk.on("session_reload", (payload) => {
    changesetId = typeof payload?.changeset?.id === "string" ? payload.changeset.id : null;
  });
  // `note_created` ONLY: `note_edited` fires during composition and agent comments emit
  // neither, so no other event can publish.
  hunk.on("note_created", (payload, ctx) => {
    const result = publisher.publish(payload, { cwd: ctx.cwd, changesetId });
    if (result.status === "published") {
      ctx.notify("Feedback queued for the implementation session", "info");
    } else if (result.status === "refused") {
      ctx.notify(`perk feedback not queued — ${result.warning}`, "warning");
    } else if (result.log !== undefined) {
      hunk.log(result.log);
    }
  });
}
