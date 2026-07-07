// The tool-gating primitive (the keystone). Structural read-only enforcement, NOT
// prompting. Mirrors pi's authoritative `examples/extensions/plan-mode/` recipe (the
// `setActiveTools` allowlist + `tool_call` bash sub-allowlist + `before_agent_start` injection +
// `context` strip-when-off) and `preset.ts`'s snapshot-then-restore. The gate attaches to the
// existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no new registry stage.
//
// Substrate only: perk-owned plan mode and the read-only CI executor are the consumers of the
// `enter`/`exit` surface; the allowlist-restore is wired into the existing
// `session_start`/`session_tree` rebuild points.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/**
 * Tools available while read-only mode is active (mirrors plan-mode's PLAN_MODE_TOOLS).
 * `plan_review` is the backend-neutral review door (planReview.ts) — allowlisted so the model
 * can request a human plan review INSIDE plan mode (review happens before the gate ever comes
 * off); fail-open everywhere (headless / dismissed soft-skip), so it is safe on every path.
 */
export const READ_ONLY_TOOLS = [
  "read",
  "grep",
  "find",
  "ls",
  "bash",
  "ask_user_question",
  "plan_review",
  // The plan_draft carve-out: plan_draft is structurally limited to the one working-plan
  // artifact in the run-scoped session data dir (gitignored scratch), so the read-only invariant
  // (worktree untouched) holds; the `tool_call` edit/write/bash blocking below is unchanged.
  "plan_draft",
  // The objective_draft twin of the plan_draft carve-out: objective_draft writes only the one
  // working-objective artifact in the session data dir (fixed artifact name, seam-derived
  // path); the gate's edit/write/bash blocking is unchanged.
  "objective_draft",
  // The objective_node carve-out: it never touches the worktree — it delegates a bounded,
  // workflow-owned node transition to the canonical Python plane (`perk objective node`). Both
  // objective-plan factory paths run gated (the cold door hands off `mode: read-only`; the warm
  // `/objective-plan` enters the gate before seeding), and the factory loop's
  // `objective_node_claim` carrier — which the approval-driven save's node-link recovery depends
  // on — can only be written by calling this tool inside the gated session. Excluding it
  // silently breaks the warm `/objective-plan` path: the plan saves unlinked.
  "objective_node",
  // The `web` seam providers' research tools: the UNION of all known web-provider tool
  // names, allowlisted statically and inert when the package is absent (the plan_review precedent
  // — setActiveTools simply has nothing to enable). None mutate the repo — fetch_content's
  // GitHub-clone path writes only to its own cache outside the worktree, morally equivalent to the
  // already-allowlisted curl. perk does NOT normalize names, so all three providers' divergent
  // names are listed: pi-web-access (default: web_search/code_search/fetch_content/
  // get_search_content), @ollama/pi-web-search (ollama_web_search/ollama_web_fetch), and
  // @juicesharp/rpiv-web-tools (web_search shared, web_fetch).
  "web_search",
  "code_search",
  "fetch_content",
  "get_search_content",
  "ollama_web_search",
  "ollama_web_fetch",
  "web_fetch",
  // pi-mono-linear's read-only tools (the [issues] backend = "linear" selection):
  // none mutate Linear or the repo. Foreign names are inert when the package is absent (the
  // pi-web-access precedent above). The mutating/sensitive tools are deliberately excluded:
  // linear_create_issue, linear_update_issue, linear_create_comment, linear_upload_file,
  // linear_upload_file_to_issue_comment, linear_configure_auth (writes ~/.pi/agent/auth.json).
  "linear_whoami",
  "linear_workspace_metadata",
  "linear_list_teams",
  "linear_get_team",
  "linear_list_users",
  "linear_get_user",
  "linear_list_issues",
  "linear_get_issue",
  "linear_search_issues",
  "linear_list_my_issues",
  "linear_list_projects",
  "linear_get_project",
  "linear_list_issue_statuses",
  "linear_get_issue_status",
  "linear_list_labels",
  "linear_list_cycles",
  "linear_list_documents",
  "linear_get_document",
  "linear_list_comments",
];

/** The read-only marker / custom-message type injected into context while active. */
const MODE_CONTEXT_TYPE = "perk:mode-context";
const READ_ONLY_MARKER = "[READ-ONLY MODE]";

/** Exported for tests: the injected read-only mode context (interpolates the allowlist). */
export const READ_ONLY_CONTEXT = `${READ_ONLY_MARKER}
You are in perk read-only mode — a structurally enforced exploration mode.

- You can only use: ${READ_ONLY_TOOLS.join(", ")}.
- You CANNOT use edit or write (file modifications are blocked).
- plan_draft is the sole sanctioned write: it writes only the working-plan artifact in the session data dir.
- bash is restricted to an allowlist of read-only commands.
- For GitHub data use read-only \`gh\` subcommands (view/list/diff/status/checks/search) — never raw curl/fetch against github.com (private repos reject unauthenticated requests).

These restrictions are enforced by perk, not advisory. Do not attempt to make changes.`;

// --- pure policy (copied from plan-mode/utils.ts so this primitive is self-contained; perk-owned
// so retiring the borrowed pi-plan extension leaves no dangling import) -------

const DESTRUCTIVE_PATTERNS = [
  /\brm\b/i,
  /\brmdir\b/i,
  /\bmv\b/i,
  /\bcp\b/i,
  /\bmkdir\b/i,
  /\btouch\b/i,
  /\bchmod\b/i,
  /\bchown\b/i,
  /\bchgrp\b/i,
  /\bln\b/i,
  /\btee\b/i,
  /\btruncate\b/i,
  /\bdd\b/i,
  /\bshred\b/i,
  /(^|[^<])>(?!>)/,
  />>/,
  /\bnpm\s+(install|uninstall|update|ci|link|publish)/i,
  /\byarn\s+(add|remove|install|publish)/i,
  /\bpnpm\s+(add|remove|install|publish)/i,
  /\bpip\s+(install|uninstall)/i,
  /\bapt(-get)?\s+(install|remove|purge|update|upgrade)/i,
  /\bbrew\s+(install|uninstall|upgrade)/i,
  /\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout|branch\s+-[dD]|stash|cherry-pick|revert|tag|init|clone)/i,
  /\bsudo\b/i,
  /\bsu\b/i,
  /\bkill\b/i,
  /\bpkill\b/i,
  /\bkillall\b/i,
  /\breboot\b/i,
  /\bshutdown\b/i,
  /\bsystemctl\s+(start|stop|restart|enable|disable)/i,
  /\bservice\s+\S+\s+(start|stop|restart)/i,
  /\b(vim?|nano|emacs|code|subl)\b/i,
];

const SAFE_PATTERNS = [
  // `cd` mutates nothing — it is the common prefix for scoping a read-only query
  // (`cd repo && perk objective show …`). Safe under the per-segment model: every other
  // segment is still independently validated and the whole-string destructive veto is unchanged.
  /^\s*cd\b/,
  /^\s*cat\b/,
  /^\s*head\b/,
  /^\s*tail\b/,
  /^\s*less\b/,
  /^\s*more\b/,
  /^\s*grep\b/,
  /^\s*find\b/,
  /^\s*ls\b/,
  /^\s*pwd\b/,
  /^\s*echo\b/,
  /^\s*printf\b/,
  /^\s*wc\b/,
  /^\s*sort\b/,
  /^\s*uniq\b/,
  /^\s*diff\b/,
  /^\s*file\b/,
  /^\s*stat\b/,
  /^\s*du\b/,
  /^\s*df\b/,
  /^\s*tree\b/,
  /^\s*which\b/,
  /^\s*whereis\b/,
  /^\s*type\b/,
  /^\s*env\b/,
  /^\s*printenv\b/,
  /^\s*uname\b/,
  /^\s*whoami\b/,
  /^\s*id\b/,
  /^\s*date\b/,
  /^\s*cal\b/,
  /^\s*uptime\b/,
  /^\s*ps\b/,
  /^\s*top\b/,
  /^\s*htop\b/,
  /^\s*free\b/,
  /^\s*git\s+(status|log|diff|show|branch|remote|config\s+--get)/i,
  /^\s*git\s+ls-/i,
  /^\s*npm\s+(list|ls|view|info|search|outdated|audit)/i,
  /^\s*yarn\s+(list|info|why|audit)/i,
  /^\s*node\s+--version/i,
  /^\s*python\s+--version/i,
  /^\s*curl\s/i,
  /^\s*wget\s+-O\s*-/i,
  /^\s*jq\b/,
  /^\s*sed\s+-n/i,
  /^\s*awk\b/,
  /^\s*rg\b/,
  /^\s*fd\b/,
  /^\s*ast-grep\b/,
  // Browser-automation skill (.agents/skills/agent-browser): a command-keyed entry mirroring
  // `ast-grep` — it gates the command, not its args. Two invocation forms: the bare global
  // install on PATH, and the `npx` fallback anchored to `agent-browser` so bare `npx <anything>`
  // stays blocked. Accepted known leniency: the leading-command model cannot inspect args, so
  // agent-browser's own output flags (screenshot/video `--output`) can write files and its actions
  // can mutate external sites — outside the gate's granularity. This is accepted and documented,
  // consistent with the allowlisted `curl` / `fetch_content` GitHub-clone cache-write precedent
  // (both write outside the gate). The whole-string `>`-redirect destructive veto still applies.
  /^\s*agent-browser\b/,
  /^\s*npx\s+agent-browser\b/,
  /^\s*bat\b/,
  /^\s*eza\b/,
  // perk's own read-only objective queries (show/next + their s/n aliases, plus the non-mutating
  // node-engagement read the objective-plan factory needs). The trailing \b keeps the `n` alias
  // from matching the mutating `node` subcommand; node-engagement allowed; create/node/reconcile
  // stay blocked.
  /^\s*perk\s+(objective|obj)\s+(show|s|next|n|node-engagement)\b/i,
  // Read-only `gh` queries — the guidance in the managed AGENTS block ("GitHub access goes
  // through gh") must be followable in read-only sessions. Query-shaped subcommands only;
  // `gh api` stays blocked (it can POST/PATCH), as do all mutating subcommands (create/edit/
  // merge/close/comment/clone/...). Destructive-wins still blocks `> file` redirects.
  /^\s*gh\s+(issue|pr|repo|run|release|label)\s+(view|list|diff|status|checks)\b/i,
  /^\s*gh\s+search\s+(issues|prs|code|commits|repos)\b/i,
  /^\s*gh\s+auth\s+status\b/i,
];

/**
 * Split a command into top-level shell segments for the per-segment safe check. Walks the string
 * character by character tracking single- and double-quote state, splitting only on UNQUOTED
 * sequencing operators `;`, `&&`, `||`, and `|` (`&&`/`||` are two-char operators; a lone `|` is
 * the pipe). Quoted operators must not split — load-bearing: a `|` inside `grep -iE 'a|b'` stays
 * in one segment. Segments are trimmed and empties dropped.
 *
 * Known limitation: backslash-escaped quote characters are not handled. This is acceptable — the
 * whole-string destructive veto in isReadOnlyBashCommand remains the backstop.
 */
function splitTopLevelSegments(command: string): string[] {
  const segments: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < command.length; i++) {
    const ch = command[i];
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === ";" || ch === "|" || ch === "&") {
      const next = command[i + 1];
      if ((ch === "|" && next === "|") || (ch === "&" && next === "&")) {
        // two-char operator (`||` / `&&`)
        segments.push(current);
        current = "";
        i++;
        continue;
      }
      if (ch === ";" || ch === "|") {
        // single-char sequencing operator (`;` / `|`)
        segments.push(current);
        current = "";
        continue;
      }
      // a lone `&` (background / part of `&>`): keep it in the segment so `&>` redirect detection
      // and the destructive veto see it intact.
      current += ch;
      continue;
    }
    current += ch;
  }
  segments.push(current);
  return segments.map((s) => s.trim()).filter((s) => s.length > 0);
}

/**
 * Whether a bash command is allowed under read-only mode. Two independent checks:
 *  - NOT destructive: a WHOLE-STRING scan against DESTRUCTIVE_PATTERNS (destructive-wins — content
 *    anywhere in the string, incl. command substitutions, still vetoes). Two redirect carve-outs
 *    are neutralized first: FD duplications (`2>&1`, `1>&2`) and redirects to `/dev/null`
 *    (`>/dev/null`, `2>/dev/null`, `&>/dev/null`, `>>/dev/null`) — both discard output and write
 *    nothing to the filesystem. Redirects to a REAL path (`> file`, `&> file`, `>> file`) are NOT
 *    carved out and stay destructive.
 *  - SAFE per segment: split into quote-aware top-level segments (on `;`/`&&`/`||`/`|`) and require
 *    EVERY segment's leading command to match a SAFE_PATTERNS entry. This unblocks `cd`-prefixed
 *    chains and tightens the model — a non-safe command anywhere in a chain is now blocked, not
 *    just when it leads.
 * Pure → unit-testable offline.
 */
export function isReadOnlyBashCommand(command: string): boolean {
  const withoutFdRedirects = command
    .replace(/\d*>&\d+/g, " ")
    .replace(/(?:\d+|&)?>>?\s*\/dev\/null\b/g, " ");
  const isDestructive = DESTRUCTIVE_PATTERNS.some((p) => p.test(withoutFdRedirects));
  const segments = splitTopLevelSegments(command);
  const isSafe =
    segments.length > 0 && segments.every((seg) => SAFE_PATTERNS.some((p) => p.test(seg)));
  return !isDestructive && isSafe;
}

// --- the controller -----------------------------------------------------------------------------

/** The API the plan-mode and read-only-stage consumers use + the lifecycle hooks index.ts wires. */
export interface ToolGating {
  /** Reapply the allowlist from a rebuilt `mode` (called on session_start AND session_tree). */
  syncFromState(mode: string | undefined): void;
  /** Enter read-only mode: persist `mode=read-only` + snapshot/restrict tools. (Called by the plan-mode toggle and the objective-plan factory.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + restore tools. (Called by the plan-mode toggle and the save/exit doors.) */
  exit(ctx?: ExtensionContext): void;
  /** Whether the gate is currently active (in-memory source of truth for `tool_call`). */
  isActive(): boolean;
}

function isReadOnlyMode(mode: string | undefined): boolean {
  return mode === "read-only";
}

export function registerToolGating(pi: ExtensionAPI): ToolGating {
  // In-memory gate (mirrors plan-mode's `planModeEnabled`): the authority `tool_call` consults.
  // Fail-closed — a failed sync never opens this; tool_call blocks on any internal error.
  let active = false;
  // Pre-gate tool snapshot, taken once on the off→on transition (preset.ts discipline).
  let snapshot: string[] | null = null;

  function applyActive(next: boolean): void {
    if (next && !active) {
      // off → on: snapshot the current tool set, then restrict.
      snapshot = pi.getActiveTools();
      pi.setActiveTools(READ_ONLY_TOOLS);
    } else if (!next && active) {
      // on → off: restore the pre-gate snapshot. If none exists (near-unreachable — the off→on
      // branch always snapshots first), fall back to the FULL configured tool set
      // (pi.getAllTools()) like plan-mode, never a hardcoded list that would silently drop
      // grep/find/ls and perk's custom tools (plan_save/submit/land/learn).
      pi.setActiveTools(snapshot ?? pi.getAllTools().map((t) => t.name));
      snapshot = null;
    }
    active = next;
  }

  // Structural backstop: block writes + non-allowlisted bash while active. Fail-closed on error.
  pi.on("tool_call", async (event) => {
    try {
      if (!active) return;
      if (event.toolName === "edit" || event.toolName === "write") {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (file modifications disabled).`,
        };
      }
      if (event.toolName === "bash") {
        const command = String((event.input as { command?: unknown }).command ?? "");
        if (!isReadOnlyBashCommand(command)) {
          return {
            block: true,
            reason: `perk read-only mode: command blocked (not allowlisted).\nCommand: ${command}`,
          };
        }
      }
      return;
    } catch {
      // Never let an internal error open the gate — fail closed.
      return { block: true, reason: "perk read-only mode: blocked (internal gating error)." };
    }
  });

  // Inject the hidden read-only mode context while active (display:false → not shown in transcript).
  pi.on("before_agent_start", async () => {
    if (!active) return;
    return {
      message: { customType: MODE_CONTEXT_TYPE, content: READ_ONLY_CONTEXT, display: false },
    };
  });

  // Strip the stale read-only marker from context when the gate is off (so it never lingers).
  pi.on("context", async (event) => {
    if (active) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === MODE_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        const content = msg.content;
        if (typeof content === "string") return !content.includes(READ_ONLY_MARKER);
        if (Array.isArray(content)) {
          return !content.some(
            (c) =>
              (c as { type?: string; text?: string }).type === "text" &&
              ((c as { text?: string }).text ?? "").includes(READ_ONLY_MARKER),
          );
        }
        return true;
      }),
    };
  });

  return {
    syncFromState(mode: string | undefined): void {
      applyActive(isReadOnlyMode(mode));
    },
    enter(_ctx?: ExtensionContext): void {
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-only" });
      applyActive(true);
    },
    exit(_ctx?: ExtensionContext): void {
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-write" });
      applyActive(false);
    },
    isActive(): boolean {
      return active;
    },
  };
}
