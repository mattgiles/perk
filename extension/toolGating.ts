// P2.T1 — the tool-gating primitive (the keystone). Structural read-only enforcement, NOT
// prompting. Mirrors pi's authoritative `examples/extensions/plan-mode/` recipe (the
// `setActiveTools` allowlist + `tool_call` bash sub-allowlist + `before_agent_start` injection +
// `context` strip-when-off) and `preset.ts`'s snapshot-then-restore. The gate attaches to the
// existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no new registry stage.
//
// Substrate only: T2 (perk-owned plan mode) and T5 (read-only CI executor) are the consumers of
// the `enter`/`exit` surface; this turn ships the mechanism + wires the allowlist-restore into the
// existing `session_start`/`session_tree` rebuild points (see docs/planning/phase-2-turn-1.md).

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/** Tools available while read-only mode is active (mirrors plan-mode's PLAN_MODE_TOOLS). */
export const READ_ONLY_TOOLS = ["read", "grep", "find", "ls", "bash", "ask_user_question"];

/** The read-only marker / custom-message type injected into context while active. */
const MODE_CONTEXT_TYPE = "perk:mode-context";
const READ_ONLY_MARKER = "[READ-ONLY MODE]";

const READ_ONLY_CONTEXT = `${READ_ONLY_MARKER}
You are in perk read-only mode — a structurally enforced exploration mode.

- You can only use: ${READ_ONLY_TOOLS.join(", ")}.
- You CANNOT use edit or write (file modifications are blocked).
- bash is restricted to an allowlist of read-only commands.

These restrictions are enforced by perk, not advisory. Do not attempt to make changes.`;

// --- pure policy (copied from plan-mode/utils.ts so this primitive is self-contained; perk-owned
// so T2's eventual retirement of the borrowed pi-plan extension leaves no dangling import) -------

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
  /^\s*bat\b/,
  /^\s*eza\b/,
  // perk's own read-only objective queries (show/next + their s/n aliases). The trailing \b keeps
  // the `n` alias from matching the mutating `node` subcommand; create/node/reconcile stay blocked.
  /^\s*perk\s+(objective|obj)\s+(show|s|next|n)\b/i,
];

/**
 * Whether a bash command is allowed under read-only mode: it must match a known read-only command
 * AND must not match any destructive pattern (destructive wins). Pure → unit-testable offline.
 */
export function isReadOnlyBashCommand(command: string): boolean {
  // File-descriptor duplications (`2>&1`, `>&2`, `1>&2`) are not file writes — neutralize them so
  // the redirect-detection pattern doesn't false-positive on the `>` they contain. `&>file`
  // (writes both streams to a file) is deliberately NOT carved out: it stays destructive.
  const withoutFdRedirects = command.replace(/\d*>&\d+/g, " ");
  const isDestructive = DESTRUCTIVE_PATTERNS.some((p) => p.test(withoutFdRedirects));
  const isSafe = SAFE_PATTERNS.some((p) => p.test(command));
  return !isDestructive && isSafe;
}

// --- the controller -----------------------------------------------------------------------------

/** The API T2/T5 consume + the lifecycle hooks index.ts wires. */
export interface ToolGating {
  /** Reapply the allowlist from a rebuilt `mode` (called on session_start AND session_tree). */
  syncFromState(mode: string | undefined): void;
  /** Enter read-only mode: persist `mode=read-only` + snapshot/restrict tools. (T2/T5 call site.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + restore tools. (T2/T5 call site.) */
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
