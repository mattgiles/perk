// The warm `/stack-review-browser` door + the `open_stack_review` cold-launch tool: the BROWSER
// entry into human-in-the-loop adversarial review of an ENTIRE PR stack (contracts §8.4) — one
// plannotator session over the combined diff (stack base → top head), one reviewer wave over
// that combined diff (`start_review_wave` with `stack: true`), and the judgment-routed per-PR
// posting protocol through `submit_pr_review`.
//
// TARGET GRAMMAR (explicit, no error-conditioned fallback probing):
//   /stack-review-browser [target] [focus note]
// where target is an objective id (`77` / `#77` / an issue URL — bare numbers are objective ids
// BY DEFINITION of the grammar), `pr:<n>` or a PR URL (the non-perk chain arm), or absent. The
// no-target ladder: the session's rebuilt workflow-state `active_objective` (passed explicitly
// as the objective id) → else the checkout worker with no id (its `cache.plan-ref` arm) → a
// `no_objective` failure is a typed usage refusal naming the explicit forms.
//
// THE COMBINED DIFF is a PINNED STATIC PATCH: the cold checkout worker materializes a detached
// checkout of the TOP stack head AND writes `git diff <base_sha> <top head>` over the exact
// fetched objects to `<checkout>.patch` beside it (`patchPathFor` — the TS half of the
// two-plane derived-path convention; nothing carries the path), reporting its SHA-256. The door
// verifies the digest against the file bytes at TWO points (`verifyStackPatch` — a refreshed
// checkout is a `mismatch`, a gone checkout a `missing`): the pre-open refusal gate, and again
// inside the browser-operation owner's start immediately before the request is emitted (the
// owner may first wait out a predecessor's retirement — a refresh in that window refuses at
// launch). It opens plannotator's static-patch mode `{cwd: <checkout>, patchFile:
// <checkout>.patch}`: no repository context, no merge-base fallback, no live refresh — moving
// refs cannot change the displayed diff. On a launched open the verified `PinnedStack` (base
// commit + every member head) is bound into the per-activation `StackPinState`, so the reviewer
// lanes (`start_review_wave` with `stack: true`) and the guidance's routing step read the ONE
// pinned `perk pr review-context --stack --pin-base … --pin-head …` command rendered from the
// same snapshot — browser, lanes and routing share one commit identity by construction. The
// former live `since-base` vs `origin/<stack base>` mode (and its merge-base→HEAD empty-review
// trap) is gone; exploration keeps the detached checkout.
//
// THE POSTING CONTRACT (the delta from /pr-review-browser): a local-diff session has NO attached
// PR, so the browser has no platform-posting path — ALL GitHub posting is perk-side after the
// human triage, judgment-routed per member PR (dry-run ALL batches first, bottom→top, per-PR
// confirm for formal events). The stack respond mapper (`stackRespondMessage`) and the stack
// degrade notice both carry that framing.
//
// `open_stack_review` is the cold-launch twin (the `run_audit_wave` posture): NO parameters —
// the pinned stack snapshot comes ONLY from the `perk objective stack review` launch handoff
// (`stack_review`, recovered via the rebuilt workflow-state run_id), so no model-relayed path
// can aim the flow anywhere. Single-use per session; it runs the SAME code-review open over the
// activation's browser-operation owner (`openReviewBrowserCore`, contracts §8.23) and returns the
// rendered stack.md guidance as its ok text. Like every browser door, a later open of any browser
// door replaces this review (its tab is marked detached); a turn abort or a session reload
// detaches it the same way.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../../session/branchWorkflowSession.ts";
import type { WorkflowSession } from "../../../session/workflowSession.ts";
import { bindingSuffix } from "../../../substrate/bindingDelivery.ts";
import { readHandoff } from "../../../substrate/cache.ts";
import { type ColdJson, runColdDoor } from "../../../substrate/coldDoor.ts";
import { registerPerkCommand } from "../../../substrate/command.ts";
import { render } from "../../../substrate/prompts.ts";
import { failFor, ok } from "../../../substrate/result.ts";
import { report } from "../../../surfaces/report.ts";
import {
  type PinnedStack,
  pinnedReviewContextCommand,
} from "../../../waves/adversarialReviewWave.ts";
import { registerPerkTool } from "../../perkTool.ts";
import { type BrowserOperationOwner, BrowserStartRefusal } from "../browserOperation.ts";
import { plannotatorPresent, stackRespondMessage } from "../providers/plannotatorHandoff.ts";
import { openReviewBrowserCore, type ReviewBrowserOpenResult } from "./browser.ts";
import { type CheckoutOk, decodeCheckout, PR_URL_RE } from "./checkout.ts";
import { type StackPinState, samePinnedStack } from "./reviewWave.ts";

/** The door's report scope — also the `command:<id>` binding trigger id. */
const SCOPE = "stack-review-browser";

// ------------------------------------------------------------------------ the target grammar

/** A parsed `/stack-review-browser` target: objective arm, chain arm, or the no-target ladder. */
export type StackReviewTarget =
  | { kind: "objective"; id: string }
  | { kind: "pr"; pr: number }
  | { kind: "auto" };

export interface StackReviewArgs {
  target: StackReviewTarget;
  directive: string;
}

/** Extracts the issue number from a GitHub issue URL (the objective-id URL form). */
const ISSUE_URL_RE = /\/issues\/(\d+)(?:\/|$|#|\?)/;

/** A backend-native objective id (Linear's `ENG-123` shape — the Python `parse_objective_id`
 * ident grammar, mirrored so an explicit target never silently degrades to a focus note). */
const NATIVE_ID_RE = /^[A-Za-z0-9]+-\d+$/;

/** Peel a Linear issue/project URL down to its opaque objective id (null = not one). */
function linearIdFromUrl(token: string): string | null {
  let url: URL;
  try {
    url = new URL(token);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  const host = url.hostname;
  if (host !== "linear.app" && !host.endsWith(".linear.app")) return null;
  const segments = url.pathname.split("/").filter((s) => s !== "");
  for (let i = 0; i < segments.length - 1; i++) {
    const seg = segments[i];
    const next = segments[i + 1];
    if (next === undefined) break;
    if (seg === "issue" && NATIVE_ID_RE.test(next)) return next;
    if (seg === "project") return next;
  }
  return null;
}

/**
 * Parse the explicit target grammar (pure, offline-tested). Bare numbers (and `#n`,
 * backend-native ids like `ENG-123`, GitHub issue URLs, and Linear issue/project URLs — the
 * Python `parse_objective_id` grammar) are OBJECTIVE ids by definition; the chain arm is
 * `pr:<n>` or a PR URL. A first token that is none of these makes the WHOLE string the focus
 * note (target absent — the ladder). Null only on a malformed `pr:` token (a usage failure,
 * never silently a focus note).
 */
export function parseStackReviewArgs(args: string): StackReviewArgs | null {
  const trimmed = args.trim();
  if (trimmed.length === 0) return { target: { kind: "auto" }, directive: "" };
  const split = trimmed.match(/^(\S+)(?:\s+([\s\S]*))?$/);
  const first = split?.[1] ?? "";
  const rest = (split?.[2] ?? "").trim();
  if (/^pr:/i.test(first)) {
    const prToken = first.match(/^pr:(\d+)$/i);
    if (prToken?.[1] === undefined) return null;
    return { target: { kind: "pr", pr: Number(prToken[1]) }, directive: rest };
  }
  const prUrl = first.match(PR_URL_RE);
  if (prUrl?.[1] !== undefined) {
    return { target: { kind: "pr", pr: Number(prUrl[1]) }, directive: rest };
  }
  const bare = first.match(/^#?(\d+)$/);
  if (bare?.[1] !== undefined) {
    return { target: { kind: "objective", id: bare[1] }, directive: rest };
  }
  const issueUrl = first.match(ISSUE_URL_RE);
  if (issueUrl?.[1] !== undefined) {
    return { target: { kind: "objective", id: issueUrl[1] }, directive: rest };
  }
  const linearId = linearIdFromUrl(first);
  if (linearId !== null) {
    return { target: { kind: "objective", id: linearId }, directive: rest };
  }
  if (NATIVE_ID_RE.test(first)) {
    return { target: { kind: "objective", id: first }, directive: rest };
  }
  return { target: { kind: "auto" }, directive: trimmed };
}

// ------------------------------------------------------------------------ the snapshot decode

/** One pinned stack-snapshot row (the checkout envelope's `stack[]` / the handoff's rows). */
export interface StackSnapshotRow {
  pr: number;
  url: string;
  branch: string;
  head_sha: string;
  base_ref: string;
  node_id: string | null;
  plan_id: string | null;
}

/** The `perk pr review checkout --stack --json` ok-arm: the single-PR fields + the snapshot
 * (`base_ref` IS the combined-diff/stack base on the stack envelope — no separate field) + the
 * combined patch's SHA-256 (the patch itself is at the derived `patchPathFor(path)`). */
export interface StackCheckoutOk extends CheckoutOk {
  stack: StackSnapshotRow[];
  stack_notes: string[];
  patch_sha256: string;
}

const SHA256_HEX_RE = /^[0-9a-f]{64}$/;
const SHA1_HEX_RE = /^[0-9a-f]{40}$/;

/** The stack checkout's combined-patch sibling — the TS half of the `<checkout>.patch`
 * convention (`review_patch_path` in Python): a pure function of the checkout path, so both
 * planes derive it and nothing carries a path that could disagree with the checkout. */
export function patchPathFor(checkoutPath: string): string {
  return `${checkoutPath}.patch`;
}

/** The pre-open digest check over the derived patch: the file at `patchPathFor(checkoutPath)`
 * must exist, be readable, and hash (SHA-256) to the snapshot's `expectedSha256` — a
 * `mismatch` means the checkout was refreshed since this snapshot was taken. */
export function verifyStackPatch(
  checkoutPath: string,
  expectedSha256: string,
):
  | { ok: true; patchPath: string }
  | {
      ok: false;
      patchPath: string;
      reason: "missing" | "unreadable" | "mismatch";
      detail: string;
    } {
  const patchPath = patchPathFor(checkoutPath);
  let bytes: Buffer;
  try {
    bytes = readFileSync(patchPath);
  } catch (error) {
    const code = (error as { code?: unknown }).code;
    if (code === "ENOENT") {
      return {
        ok: false,
        patchPath,
        reason: "missing",
        detail: `the stack's combined patch is missing at '${patchPath}' — re-run the stack review`,
      };
    }
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      patchPath,
      reason: "unreadable",
      detail: `the stack's combined patch at '${patchPath}' could not be read: ${message}`,
    };
  }
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expectedSha256) {
    return {
      ok: false,
      patchPath,
      reason: "mismatch",
      detail:
        `the stack's combined patch at '${patchPath}' does not match this snapshot's digest ` +
        "— the stack checkout was refreshed since this snapshot was taken — re-run the stack review",
    };
  }
  return { ok: true, patchPath };
}

/** The `PinnedStack` of a snapshot (envelope or binding rows, bottom→top). */
export function pinnedStackOf(
  topPr: number,
  checkoutPath: string,
  baseSha: string,
  rows: readonly StackSnapshotRow[],
): PinnedStack {
  return {
    topPr,
    checkout: checkoutPath,
    baseSha,
    heads: rows.map((row) => ({ pr: row.pr, headSha: row.head_sha })),
  };
}

function decodeSnapshotRow(item: unknown): StackSnapshotRow | null {
  if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
  const raw = item as Record<string, unknown>;
  const { pr, url, branch, head_sha, base_ref, node_id, plan_id } = raw;
  if (typeof pr !== "number" || !Number.isInteger(pr)) return null;
  if (typeof url !== "string" || typeof branch !== "string") return null;
  if (typeof head_sha !== "string" || typeof base_ref !== "string") return null;
  if (node_id !== null && typeof node_id !== "string") return null;
  if (plan_id !== null && typeof plan_id !== "string") return null;
  return { pr, url, branch, head_sha, base_ref, node_id, plan_id };
}

function decodeSnapshotRows(raw: unknown): StackSnapshotRow[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const rows: StackSnapshotRow[] = [];
  for (const item of raw) {
    const row = decodeSnapshotRow(item);
    if (row === null) return null;
    rows.push(row);
  }
  return rows;
}

function decodeStringArray(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.every((n) => typeof n === "string") ? (raw as string[]) : null;
}

/** Strict decode of the `--stack` checkout envelope (the pinned snapshot the door reads);
 * `patch_sha256` is REQUIRED (64 lowercase hex) — an older CLI without it fails decode. */
export function decodeStackCheckout(payload: ColdJson): StackCheckoutOk | null {
  const base = decodeCheckout(payload);
  if (base === null) return null;
  const stack = decodeSnapshotRows(payload.stack);
  const stackNotes = decodeStringArray(payload.stack_notes);
  if (stack === null || stackNotes === null) return null;
  const patchSha256 = payload.patch_sha256;
  if (typeof patchSha256 !== "string" || !SHA256_HEX_RE.test(patchSha256)) return null;
  return { ...base, stack, stack_notes: stackNotes, patch_sha256: patchSha256 };
}

// ------------------------------------------------------------------------ guidance

/** The guidance inputs (the pinned snapshot slice both entry paths render from). */
export interface StackReviewGuidanceOpts {
  topPr: number;
  checkout: string;
  stackBase: string;
  /** Ordered bottom→top. */
  members: StackSnapshotRow[];
  notes: string[];
  /** The verified pins — renders the ONE `review_context_command` the routing step reads. */
  pinned: PinnedStack;
  directive?: string;
}

/**
 * The seed guidance both entry paths share verbatim (the warm door injects it; the cold-launch
 * tool returns it as ok text). Pure + exported for offline tests. The member table and notes
 * are pre-rendered here (the frozen mini-jinja subset has no loops).
 */
export function stackReviewGuidance(opts: StackReviewGuidanceOpts): string {
  const table = opts.members
    .map((member, index) => {
      const node = member.node_id === null ? "" : ` · node ${member.node_id}`;
      const plan = member.plan_id === null ? "" : ` · plan #${member.plan_id}`;
      return (
        `${index + 1}. PR #${member.pr} \`${member.branch}\` ← \`${member.base_ref}\`` +
        `${node}${plan} — ${member.url}`
      );
    })
    .join("\n");
  const notes = opts.notes.map((note) => `- ${note}`).join("\n");
  return render("stages/stack-review-browser/stack.md", {
    top_pr: String(opts.topPr),
    checkout: opts.checkout,
    stack_base: opts.stackBase,
    member_count: String(opts.members.length),
    stack_table: table,
    notes,
    review_context_command: pinnedReviewContextCommand(opts.pinned),
    directive: opts.directive ?? "",
  });
}

// ------------------------------------------------------------------------ the degrade notice

/**
 * The stack degrade notice (browser never ready): findings render in-session and the triage
 * runs conversationally; the routing + per-PR posting protocol is unchanged — it never
 * depended on the browser.
 */
export const STACK_DEGRADE_NOTICE =
  "The plannotator browser review is unavailable (the review server never became ready) — " +
  "degrade in-session: render the reviewers' reconciled findings as a table in your reply and " +
  "run the same triage loop conversationally. The annotation surface is cleared — " +
  "`push_annotations` now refuses (`no_surface`); render findings in-session. The routing + " +
  "per-PR posting protocol is unchanged (it never depended on the browser): dry-run ALL " +
  "per-PR batches first, then post bottom→top via `submit_pr_review` — only what the human " +
  "approves.";

// ------------------------------------------------------------------------ the shared open

/**
 * The supersession guard both entry paths run BEFORE opening: while a stack wave launched
 * against a different pin is still pending (uncollected), a new open would re-prime the shared
 * annotation surface for another stack while the lanes keep reviewing the old commits — their
 * findings could then be pushed/routed against the wrong patch. Returns the refusal text, or
 * null when the open may proceed (no pending stack wave, or the SAME pin — a stale-session
 * reopen of the open review). It runs before the browser-operation owner is reached, so a
 * refusal registers nothing there and detaches no live review.
 */
export function pinSupersedeRefusal(stackPin: StackPinState, next: PinnedStack): string | null {
  const inFlight = stackPin.inFlight;
  if (inFlight === null || samePinnedStack(inFlight, next)) return null;
  return (
    `a stack review wave is still pending against the open stack review (top PR #${inFlight.topPr} ` +
    `at ${inFlight.checkout}) — collect it with collect_review_wave (or wait for its native ` +
    "completion) before opening another stack review"
  );
}

/** The stack open's result: the door result, or the launch-time digest refusal. */
export type StackOpenResult = ReviewBrowserOpenResult;

/** The stack open's inputs — the snapshot slice both entry paths open from. */
export interface StackOpenOpts {
  checkoutPath: string;
  /** The snapshot's digest of the derived `<checkout>.patch` (re-verified at launch). */
  patchSha256: string;
  guidance: string;
}

/**
 * Open the stack browser review through the activation's browser-operation owner (both entry
 * paths): the code-review open over plannotator's static-patch mode on the derived
 * `<checkout>.patch`, the stack degrade notice and the stack respond mapper. The patch digest is
 * verified at TWO points: the caller's pre-open refusal gate (`verifyStackPatch`, then
 * `pinSupersedeRefusal` — an early refusal reaches no owner and detaches nothing), and again
 * inside the owner's start, immediately before the request is emitted (`beforeStart`): the owner
 * may first wait for a predecessor's retirement, and a `perk pr review checkout --stack` refresh
 * in that window must refuse (`refused`, reported verbatim) rather than show a refreshed patch
 * under the old pins — a launch-time refusal leaves no browser review (the predecessor was
 * already retired). Binding the pins is the caller's, on `launched` only; a later open of any
 * browser door replaces this review (the owner detaches it). The server port is picked by the
 * owner (mirroring Plannotator's own port selection — see plannotatorHandoff.ts).
 */
export async function openStackBrowser(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  owner: BrowserOperationOwner,
  opts: StackOpenOpts,
): Promise<StackOpenResult> {
  return await openReviewBrowserCore(pi, ctx, owner, {
    scope: SCOPE,
    browserOpts: {
      cwd: opts.checkoutPath,
      source: { mode: "patch", patchFile: patchPathFor(opts.checkoutPath) },
    },
    guidance: opts.guidance,
    degradeNotice: STACK_DEGRADE_NOTICE,
    respondMessageFor: stackRespondMessage,
    beforeStart: () => {
      const patch = verifyStackPatch(opts.checkoutPath, opts.patchSha256);
      if (!patch.ok) throw new BrowserStartRefusal(`${patch.reason}: ${patch.detail}`);
    },
  });
}

// ------------------------------------------------------------------------ the warm door

/** Register the warm `/stack-review-browser` command (posting rides submit_pr_review). */
function registerStackReviewBrowser(
  pi: ExtensionAPI,
  owner: BrowserOperationOwner,
  stackPin: StackPinState,
): void {
  registerPerkCommand(pi, SCOPE, {
    description:
      "Review a whole PR stack human-in-the-loop in the plannotator browser UI over the " +
      "combined diff: no arg reviews the session/plan-ref objective's delivery train; an " +
      "objective id (42, #42, ENG-123) or issue/project URL targets that objective; pr:<n> or " +
      "a PR URL walks the base-ref chain. Any other text is a focus note. Posting is " +
      "perk-side, judgment-routed per member PR.",
    handler: async (args, ctx: ExtensionContext) => {
      // Entry gates, in order — nothing executed on refusal, each a loud error.
      const parsed = parseStackReviewArgs(args ?? "");
      if (parsed === null) {
        report(
          ctx,
          SCOPE,
          "error",
          "usage: /stack-review-browser [objective id|issue URL|pr:<n>|PR URL] [focus note]",
        );
        return;
      }
      if (!ctx.hasUI) {
        report(
          ctx,
          SCOPE,
          "error",
          "/stack-review-browser requires an interactive session — the plannotator browser " +
            "surface and the human are constitutive",
        );
        return;
      }
      if (!plannotatorPresent(pi)) {
        report(
          ctx,
          SCOPE,
          "error",
          "the plannotator extension is not loaded (its /plannotator-review command was not " +
            "found) — select the plannotator plan provider (`[providers] plan = " +
            '"plannotator-plan"`), run `perk init`, then restart pi',
        );
        return;
      }

      const argv = ["pr", "review", "checkout", "--stack"];
      if (parsed.target.kind === "pr") {
        argv.push("--pr", String(parsed.target.pr));
      } else if (parsed.target.kind === "objective") {
        argv.push("--objective", parsed.target.id);
      } else {
        // The no-target ladder: the session's active objective (the seam's fail-open read),
        // passed EXPLICITLY; else the worker's own cache.plan-ref arm (bare --stack).
        const active = openBranchWorkflowSession(pi, ctx).activeObjective();
        if (active !== null && active.trim() !== "") {
          argv.push("--objective", active.trim());
        }
      }
      argv.push("--json");

      const checkout = await runColdDoor<StackCheckoutOk>(pi, ctx, argv, {
        label: "perk pr review checkout --stack",
        decode: decodeStackCheckout,
      });
      if (!checkout.ok) {
        if (checkout.errorType === "no_objective") {
          report(
            ctx,
            SCOPE,
            "error",
            "no stack target: pass an objective id / issue URL, pr:<n> / a PR URL, or run " +
              "from a session/worktree linked to a stacked objective",
          );
          return;
        }
        report(
          ctx,
          SCOPE,
          "error",
          `perk pr review checkout --stack failed (${checkout.errorType}): ${checkout.message}`,
          { alsoLog: true },
        );
        return;
      }

      const data = checkout.data;
      // The pre-open digest check (the owner's start re-verifies at launch): the browser must
      // show exactly the patch the checkout envelope describes (a refresh between the two is a
      // loud refusal, never a wrong diff).
      const patch = verifyStackPatch(data.path, data.patch_sha256);
      if (!patch.ok) {
        report(ctx, SCOPE, "error", `${patch.reason}: ${patch.detail}`, { alsoLog: true });
        return;
      }
      const pinned = pinnedStackOf(data.pr, data.path, data.base_sha, data.stack);
      const supersede = pinSupersedeRefusal(stackPin, pinned);
      if (supersede !== null) {
        report(ctx, SCOPE, "error", supersede);
        return;
      }
      report(
        ctx,
        SCOPE,
        "info",
        `stack of ${data.stack.length} PRs (base ${data.base_ref}, top #${data.pr})` +
          (parsed.directive
            ? ` → adversarial reviewers (focus: ${parsed.directive})`
            : " → adversarial reviewers") +
          " → plannotator browser triage → judgment-routed per-PR posting",
      );
      const opened = await openStackBrowser(pi, ctx, owner, {
        checkoutPath: data.path,
        patchSha256: data.patch_sha256,
        guidance:
          stackReviewGuidance({
            topPr: data.pr,
            checkout: data.path,
            stackBase: data.base_ref,
            members: data.stack,
            notes: data.stack_notes,
            pinned,
            ...(parsed.directive ? { directive: parsed.directive } : {}),
          }) + bindingSuffix(ctx.cwd, `command:${SCOPE}`),
      });
      // `unlaunched` / `refused` were reported by the owner; `retired` yields to the newer open.
      if (opened.kind !== "launched") return;
      // Bind the pins BEFORE the guidance reaches the model (its first step is the stack wave).
      stackPin.pinned = pinned;
      pi.sendUserMessage(opened.guidance);
    },
  });
}

// ------------------------------------------------------------------------ the cold-launch tool

/** The decoded `stack_review` launch binding (the launcher's `handoff_extra` blob) — exactly
 * what the tool consumes: the pinned snapshot rows, the checkout path, the notes, the focus,
 * and the pinned identity (`base_sha` — the combined-diff base commit; `patch_sha256` — the
 * digest of the derived `<checkout_path>.patch`). The top PR and the stack base REF are
 * DERIVED from the ordered rows (last row's `pr`; first row's `base_ref`), never carried
 * redundantly. */
export interface StackReviewBinding {
  stack: StackSnapshotRow[];
  checkout_path: string;
  notes: string[];
  focus: string | null;
  base_sha: string;
  patch_sha256: string;
}

/** The derived stack endpoints (the binding's rows are ordered bottom→top, never empty). */
export function bindingTopPr(binding: StackReviewBinding): number {
  const top = binding.stack[binding.stack.length - 1];
  return top === undefined ? 0 : top.pr;
}

export function bindingBaseRef(binding: StackReviewBinding): string {
  return binding.stack[0]?.base_ref ?? "";
}

/**
 * Strict decode of the handoff's `stack_review` blob; null on ANY drift (⇒ bad_state). Every
 * field is REQUIRED — `stack` a non-empty row array, `checkout_path` a non-empty string,
 * `notes` a string array, `focus` present as a string or null (the one normalization: a
 * blank/whitespace-only focus string decodes to null — "no focus", matching the launcher's
 * no-flag arm), `base_sha` 40 lowercase hex, `patch_sha256` 64 lowercase hex.
 */
export function decodeStackReviewBinding(raw: unknown): StackReviewBinding | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const b = raw as Record<string, unknown>;
  const stack = decodeSnapshotRows(b.stack);
  const notes = decodeStringArray(b.notes);
  if (stack === null || notes === null) return null;
  if (typeof b.checkout_path !== "string" || b.checkout_path === "") return null;
  if (!("focus" in b)) return null;
  if (b.focus !== null && typeof b.focus !== "string") return null;
  if (typeof b.base_sha !== "string" || !SHA1_HEX_RE.test(b.base_sha)) return null;
  if (typeof b.patch_sha256 !== "string" || !SHA256_HEX_RE.test(b.patch_sha256)) return null;
  return {
    stack,
    checkout_path: b.checkout_path,
    notes,
    focus: typeof b.focus === "string" && b.focus.trim() !== "" ? b.focus : null,
    base_sha: b.base_sha,
    patch_sha256: b.patch_sha256,
  };
}

/** Recover the launch binding: the session seam's run identity → the run's handoff blob (the
 * `audit_bundle_dir` recovery seam). Null when absent — i.e. in every session that is not a
 * claimed `perk objective stack review` launch. */
export function stackReviewBindingOf(
  ctx: ExtensionContext,
  session: WorkflowSession,
): StackReviewBinding | null {
  const runId = session.runId;
  if (runId === null || runId === "") return null;
  const raw = readHandoff(ctx.cwd, runId)?.stack_review;
  if (raw === undefined) return null;
  return decodeStackReviewBinding(raw);
}

const TOOL_GUIDELINES = [
  "Call open_stack_review ONCE, with no arguments, inside the perk objective stack review session — the stack snapshot is bound to the session by the cold door (launch handoff), never passed by you.",
  "Follow the returned guidance exactly: launch the reviewer wave with stack: true, stream findings into the browser as it directs, and run the judgment-routed per-PR posting protocol through submit_pr_review (dry-run ALL batches first, bottom→top, only what the human approves).",
  "The tool is single-use per session; a bad_state failure means this session is not a stack-review launch, or the checkout / its pinned combined patch is gone or was refreshed since the launch — re-run perk objective stack review.",
];

/** The single-use latch (registration-scoped state, injectable for the execute-core tests). */
export interface OpenLatch {
  opened: boolean;
}

/** The injectable browser-open seam (the registration binds `openStackBrowser` over the owner). */
export type StackBrowserOpen = (
  ctx: ExtensionContext,
  opts: StackOpenOpts,
) => Promise<StackOpenResult>;

/** The `retired` arm's ok text: nothing opened, and the single-use latch is consumed. */
const RETIRED_OPEN_TEXT =
  "a newer browser review replaced this open before it started — nothing was opened; follow " +
  "that review's guidance and do not call open_stack_review again (single-use)";

/**
 * The `open_stack_review` execute core (exported for direct tests — the `executeStartReviewWave`
 * posture): every gate in registration order, then the shared browser open through `open`. The
 * result arms: `launched` consumes the latch, binds the pins and returns the guidance;
 * `unlaunched` is `browser_failed` with the latch CLOSED (retryable); `refused` (the launch-time
 * digest re-check) is `bad_state` with the latch CLOSED; `retired` consumes the latch and returns
 * a non-terminating ok naming the newer review — never a fallback, never a retry path that
 * could retire the human's newer review.
 */
export async function executeOpenStackReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  latch: OpenLatch,
  stackPin: StackPinState,
  open: StackBrowserOpen,
): Promise<ReturnType<typeof ok> | ReturnType<ReturnType<typeof failFor>>> {
  const fail = failFor(ctx, "open_stack_review");
  if (!ctx.hasUI) {
    return fail(
      "open_stack_review requires an interactive session — the plannotator browser " +
        "surface and the human are constitutive",
      "headless",
    );
  }
  if (latch.opened) {
    return fail(
      "the stack review browser was already opened in this session (single-use) — " +
        "continue the flow from the earlier guidance",
      "bad_state",
    );
  }
  // The structural binding: no param exists, so the ONLY reachable snapshot is the one the
  // cold door bound into this session's launch handoff (the branch session constructed at the
  // execute site — identity through the seam, never a direct state read).
  const binding = stackReviewBindingOf(ctx, openBranchWorkflowSession(pi, ctx));
  if (binding === null) {
    return fail(
      "no stack_review binding in this session's launch state — open_stack_review runs " +
        "only inside a perk objective stack review session",
      "bad_state",
    );
  }
  if (!existsSync(binding.checkout_path)) {
    return fail(
      `the stack checkout is missing at '${binding.checkout_path}' — re-run perk ` +
        "objective stack review",
      "bad_state",
    );
  }
  // The pre-open digest check (the warm door's twin; the owner's start re-verifies at launch):
  // the browser shows exactly the patch the launch snapshot describes, or nothing.
  const patch = verifyStackPatch(binding.checkout_path, binding.patch_sha256);
  if (!patch.ok) {
    return fail(patch.detail, "bad_state");
  }
  if (!plannotatorPresent(pi)) {
    return fail(
      "the plannotator extension is not loaded (its /plannotator-review command was not " +
        "found) — select the plannotator plan provider, run `perk init`, then restart pi",
      "plannotator_missing",
    );
  }
  const pinned = pinnedStackOf(
    bindingTopPr(binding),
    binding.checkout_path,
    binding.base_sha,
    binding.stack,
  );
  const supersede = pinSupersedeRefusal(stackPin, pinned);
  if (supersede !== null) {
    return fail(supersede, "bad_state");
  }
  const guidance = stackReviewGuidance({
    topPr: bindingTopPr(binding),
    checkout: binding.checkout_path,
    stackBase: bindingBaseRef(binding),
    members: binding.stack,
    notes: binding.notes,
    pinned,
    ...(binding.focus !== null ? { directive: binding.focus } : {}),
  });
  const opened = await open(ctx, {
    checkoutPath: binding.checkout_path,
    patchSha256: binding.patch_sha256,
    guidance,
  });
  const snapshot = {
    top_pr: bindingTopPr(binding),
    checkout_path: binding.checkout_path,
    member_count: binding.stack.length,
  };
  switch (opened.kind) {
    case "unlaunched":
      return fail(
        "could not start the plannotator review server (no free local port) — see the " +
          "error report",
        "browser_failed",
      );
    case "refused":
      return fail(opened.detail, "bad_state");
    case "retired":
      latch.opened = true;
      return ok(RETIRED_OPEN_TEXT, { status: "retired", ...snapshot });
    case "launched":
      latch.opened = true;
      stackPin.pinned = pinned;
      return ok(opened.guidance, snapshot);
  }
}

/**
 * Register the parameterless `open_stack_review` tool (the `run_audit_wave` posture) over a
 * registration-owned single-use latch (a fresh activation is a fresh session).
 */
function registerOpenStackReview(
  pi: ExtensionAPI,
  owner: BrowserOperationOwner,
  stackPin: StackPinState,
): void {
  const latch: OpenLatch = { opened: false };
  const open: StackBrowserOpen = (ctx, opts) => openStackBrowser(pi, ctx, owner, opts);

  registerPerkTool(
    pi,
    {
      name: "open_stack_review",
      label: "Open stack review",
      description:
        "Open the launch-bound stacked-PR browser review (the perk objective stack review " +
        "session's ONE opener): verifies the pinned combined patch's digest, starts the " +
        "plannotator browser over that static patch, primes the annotation surface, binds the " +
        "pinned stack for start_review_wave, and returns the full flow guidance. No parameters: " +
        "the stack snapshot comes only from the launch handoff. Single-use per session.",
      promptSnippet: "Open the launch-bound stacked-PR browser review",
      promptGuidelines: TOOL_GUIDELINES,
      executionMode: "sequential",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {},
      },
      async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
        return await executeOpenStackReview(pi, ctx, latch, stackPin, open);
      },
    },
    { stages: ["stack-review"], gated: "blocked", kind: "interactive" },
  );
}

/**
 * Install the Delivery-train review surface: the warm `/stack-review-browser` door + its
 * cold-launch twin (`open_stack_review`). Both open through the activation's browser-operation
 * owner (`owner` — it primes the annotation surface and, through its gating, the deferred tools
 * the guidance names, and carries the port selection) via `openReviewBrowserCore`, and share the
 * per-activation `StackPinState` with `installReviewWaveBindings` (both openers bind the
 * verified pins on a launched open; `start_review_wave`'s stack mode reads them).
 */
export function installStackReviewBindings(
  pi: ExtensionAPI,
  owner: BrowserOperationOwner,
  stackPin: StackPinState,
): void {
  registerStackReviewBrowser(pi, owner, stackPin);
  registerOpenStackReview(pi, owner, stackPin);
}
