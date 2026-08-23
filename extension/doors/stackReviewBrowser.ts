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
// THE COMBINED DIFF is rendered by plannotator itself: the cold checkout worker materializes a
// detached checkout of the TOP stack head, and the door opens plannotator in local mode with
// `{diffType: "since-base", defaultBranch: "origin/<stack base>"}` — the REMOTE-TRACKING ref the
// checkout actually materializes (plannotator trusts an explicit base verbatim and degrades a
// failed merge-base to HEAD, which would render an empty review — a bare branch name that only
// exists on the remote would do exactly that).
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
// can aim the flow anywhere. Single-use per session; it runs the SAME extracted lifecycle core
// and returns the rendered stack.md guidance as its ok text.

import { existsSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../substrate/bindingDelivery.ts";
import { readHandoff } from "../substrate/cache.ts";
import { type ColdJson, runColdDoor } from "../substrate/coldDoor.ts";
import { registerPerkCommand } from "../substrate/command.ts";
import { render } from "../substrate/prompts.ts";
import { failFor, ok } from "../substrate/result.ts";
import { branchOf, rebuildWorkflowState } from "../substrate/workflowState.ts";
import { report } from "../surfaces/report.ts";
import { type CheckoutOk, decodeCheckout, PR_URL_RE } from "./hunkHandoff.ts";
import {
  LOCAL_REVIEW_DIFF_TYPE,
  plannotatorPresent,
  stackRespondMessage,
} from "./plannotatorHandoff.ts";
import { openReviewBrowserCore } from "./prReviewBrowser.ts";

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
 * (`base_ref` IS the combined-diff/stack base on the stack envelope — no separate field). */
export interface StackCheckoutOk extends CheckoutOk {
  stack: StackSnapshotRow[];
  stack_notes: string[];
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

/** Strict decode of the `--stack` checkout envelope (the pinned snapshot the door reads). */
export function decodeStackCheckout(payload: ColdJson): StackCheckoutOk | null {
  const base = decodeCheckout(payload);
  if (base === null) return null;
  const stack = decodeSnapshotRows(payload.stack);
  const stackNotes = decodeStringArray(payload.stack_notes);
  if (stack === null || stackNotes === null) return null;
  return { ...base, stack, stack_notes: stackNotes };
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

/** Open the stack browser session through the extracted lifecycle core (both entry paths). */
async function openStackBrowser(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  opts: {
    checkoutPath: string;
    stackBaseRef: string;
    guidance: string;
    injectGuidance: boolean;
  },
): Promise<boolean> {
  return await openReviewBrowserCore(pi, ctx, {
    scope: SCOPE,
    browserOpts: {
      cwd: opts.checkoutPath,
      diffType: LOCAL_REVIEW_DIFF_TYPE,
      // The remote-tracking ref the checkout materialized — an explicit base plannotator
      // trusts verbatim (a bare branch name would degrade to an empty HEAD diff).
      defaultBranch: `origin/${opts.stackBaseRef}`,
    },
    guidance: opts.guidance,
    degradeNotice: STACK_DEGRADE_NOTICE,
    respondMessageFor: stackRespondMessage,
    injectGuidance: opts.injectGuidance,
  });
}

// ------------------------------------------------------------------------ the warm door

/** Register the warm `/stack-review-browser` command (posting rides submit_pr_review). */
export function registerStackReviewBrowser(pi: ExtensionAPI): void {
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
        // The no-target ladder: the session's active objective, passed EXPLICITLY; else the
        // worker's own cache.plan-ref arm (bare --stack).
        const active = rebuildWorkflowState(branchOf(ctx)).active_objective;
        if (typeof active === "string" && active.trim() !== "") {
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
      await openStackBrowser(pi, ctx, {
        checkoutPath: data.path,
        stackBaseRef: data.base_ref,
        guidance:
          stackReviewGuidance({
            topPr: data.pr,
            checkout: data.path,
            stackBase: data.base_ref,
            members: data.stack,
            notes: data.stack_notes,
            ...(parsed.directive ? { directive: parsed.directive } : {}),
          }) + bindingSuffix(ctx.cwd, `command:${SCOPE}`),
        injectGuidance: true,
      });
    },
  });
}

// ------------------------------------------------------------------------ the cold-launch tool

/** The decoded `stack_review` launch binding (the launcher's `handoff_extra` blob) — exactly
 * what the tool consumes: the pinned snapshot rows, the checkout path, the notes, and the
 * focus. The top PR and the stack base are DERIVED from the ordered rows (last row's `pr`;
 * first row's `base_ref`), never carried redundantly. */
export interface StackReviewBinding {
  stack: StackSnapshotRow[];
  checkout_path: string;
  notes: string[];
  focus: string | null;
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
 * no-flag arm).
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
  return {
    stack,
    checkout_path: b.checkout_path,
    notes,
    focus: typeof b.focus === "string" && b.focus.trim() !== "" ? b.focus : null,
  };
}

/** Recover the launch binding: rebuilt workflow-state run_id → the run's handoff blob (the
 * `audit_bundle_dir` recovery seam). Null when absent — i.e. in every session that is not a
 * claimed `perk objective stack review` launch. */
export function stackReviewBindingOf(ctx: ExtensionContext): StackReviewBinding | null {
  const runId = rebuildWorkflowState(branchOf(ctx)).run_id;
  if (runId === undefined || runId === "") return null;
  const raw = readHandoff(ctx.cwd, runId)?.stack_review;
  if (raw === undefined) return null;
  return decodeStackReviewBinding(raw);
}

const TOOL_GUIDELINES = [
  "Call open_stack_review ONCE, with no arguments, inside the perk objective stack review session — the stack snapshot is bound to the session by the cold door (launch handoff), never passed by you.",
  "Follow the returned guidance exactly: launch the reviewer wave with stack: true, stream findings via push_annotations, and run the judgment-routed per-PR posting protocol through submit_pr_review (dry-run ALL batches first, bottom→top, only what the human approves).",
  "The tool is single-use per session; a bad_state failure means this session is not a stack-review launch (or the checkout is gone) — re-run perk objective stack review.",
];

/** The single-use latch (registration-scoped state, injectable for the execute-core tests). */
export interface OpenLatch {
  opened: boolean;
}

/** The injectable browser-open seam (the execute-core tests force the failure arm). */
type StackBrowserOpen = typeof openStackBrowser;

/**
 * The `open_stack_review` execute core (exported for direct tests — the `executeStartReviewWave`
 * posture): every gate in registration order, then the shared browser open.
 */
export async function executeOpenStackReview(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  latch: OpenLatch,
  open: StackBrowserOpen = openStackBrowser,
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
  // cold door bound into this session's launch handoff.
  const binding = stackReviewBindingOf(ctx);
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
  if (!plannotatorPresent(pi)) {
    return fail(
      "the plannotator extension is not loaded (its /plannotator-review command was not " +
        "found) — select the plannotator plan provider, run `perk init`, then restart pi",
      "plannotator_missing",
    );
  }
  const guidance = stackReviewGuidance({
    topPr: bindingTopPr(binding),
    checkout: binding.checkout_path,
    stackBase: bindingBaseRef(binding),
    members: binding.stack,
    notes: binding.notes,
    ...(binding.focus !== null ? { directive: binding.focus } : {}),
  });
  const started = await open(pi, ctx, {
    checkoutPath: binding.checkout_path,
    stackBaseRef: bindingBaseRef(binding),
    guidance,
    injectGuidance: false,
  });
  if (!started) {
    return fail(
      "could not start the plannotator review server (no free local port) — see the " +
        "error report",
      "browser_failed",
    );
  }
  latch.opened = true;
  return ok(guidance, {
    top_pr: bindingTopPr(binding),
    checkout_path: binding.checkout_path,
    member_count: binding.stack.length,
  });
}

/**
 * Register the parameterless `open_stack_review` tool (the `run_audit_wave` posture) and reset
 * its single-use latch (a fresh registration is a fresh session).
 */
export function registerOpenStackReview(pi: ExtensionAPI): void {
  const latch: OpenLatch = { opened: false };

  pi.registerTool({
    name: "open_stack_review",
    label: "Open stack review",
    description:
      "Open the launch-bound stacked-PR browser review (the perk objective stack review " +
      "session's ONE opener): starts the plannotator browser over the combined stack diff, " +
      "primes the annotation surface, and returns the full flow guidance. No parameters: the " +
      "stack snapshot comes only from the launch handoff. Single-use per session.",
    promptSnippet: "Open the launch-bound stacked-PR browser review",
    promptGuidelines: TOOL_GUIDELINES,
    executionMode: "sequential",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {},
    },
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      return await executeOpenStackReview(pi, ctx, latch);
    },
  });
}
