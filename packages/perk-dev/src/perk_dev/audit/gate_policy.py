"""A plain Python copy of the read-only bash gate's pure policy.

Source of truth: ``extension/substrate/toolGating.ts`` (``DESTRUCTIVE_PATTERNS``,
``SAFE_PATTERNS``, ``splitTopLevelSegments``, ``isReadOnlyBashCommand``). Pattern bodies
are copied verbatim (each TS ``/…/i`` literal becomes ``re.compile(r"…", re.IGNORECASE)``;
no-flag literals compile bare). There is deliberately **no drift guard**: silent drift
between the TS gate and this copy is an accepted trade for simplicity — the audit is a
lead generator, never a CI gate.

Historical-policy note (both drift directions, for the calibration reader):

- A *later-added safe pattern* can never create a false violation on an old session — the
  then-active gate would have blocked the command, so no successful result exists in the
  transcript to judge.
- A *removed safe pattern* or a *later-added destructive pattern* CAN make an old,
  legitimately allowed command look like a violation today — accepted as a lead the human
  discounts during calibration.
"""

import re

DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\b", re.IGNORECASE),
    re.compile(r"\brmdir\b", re.IGNORECASE),
    re.compile(r"\bmv\b", re.IGNORECASE),
    re.compile(r"\bcp\b", re.IGNORECASE),
    re.compile(r"\bmkdir\b", re.IGNORECASE),
    re.compile(r"\btouch\b", re.IGNORECASE),
    re.compile(r"\bchmod\b", re.IGNORECASE),
    re.compile(r"\bchown\b", re.IGNORECASE),
    re.compile(r"\bchgrp\b", re.IGNORECASE),
    re.compile(r"\bln\b", re.IGNORECASE),
    re.compile(r"\btee\b", re.IGNORECASE),
    re.compile(r"\btruncate\b", re.IGNORECASE),
    re.compile(r"\bdd\b", re.IGNORECASE),
    re.compile(r"\bshred\b", re.IGNORECASE),
    re.compile(r"(^|[^<])>(?!>)"),
    re.compile(r">>"),
    re.compile(r"\bnpm\s+(install|uninstall|update|ci|link|publish)", re.IGNORECASE),
    re.compile(r"\byarn\s+(add|remove|install|publish)", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(add|remove|install|publish)", re.IGNORECASE),
    re.compile(r"\bpip\s+(install|uninstall)", re.IGNORECASE),
    re.compile(r"\bapt(-get)?\s+(install|remove|purge|update|upgrade)", re.IGNORECASE),
    re.compile(r"\bbrew\s+(install|uninstall|upgrade)", re.IGNORECASE),
    re.compile(
        r"\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout|branch\s+-[dD]|stash|"
        r"cherry-pick|revert|tag|init|clone)",
        re.IGNORECASE,
    ),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bsu\b", re.IGNORECASE),
    re.compile(r"\bkill\b", re.IGNORECASE),
    re.compile(r"\bpkill\b", re.IGNORECASE),
    re.compile(r"\bkillall\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\bsystemctl\s+(start|stop|restart|enable|disable)", re.IGNORECASE),
    re.compile(r"\bservice\s+\S+\s+(start|stop|restart)", re.IGNORECASE),
    re.compile(r"\b(vim?|nano|emacs|subl)\b", re.IGNORECASE),
    # `code` (the editor) is vetoed in command position only — see the TS source comment.
    re.compile(r"(^|[;&|(]|\$\()\s*code\b", re.IGNORECASE),
)

SAFE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*cd\b"),
    re.compile(r"^\s*cat\b"),
    re.compile(r"^\s*head\b"),
    re.compile(r"^\s*tail\b"),
    re.compile(r"^\s*less\b"),
    re.compile(r"^\s*more\b"),
    re.compile(r"^\s*grep\b"),
    re.compile(r"^\s*find\b"),
    re.compile(r"^\s*ls\b"),
    re.compile(r"^\s*pwd\b"),
    re.compile(r"^\s*echo\b"),
    re.compile(r"^\s*printf\b"),
    re.compile(r"^\s*wc\b"),
    re.compile(r"^\s*sort\b"),
    re.compile(r"^\s*uniq\b"),
    re.compile(r"^\s*diff\b"),
    re.compile(r"^\s*file\b"),
    re.compile(r"^\s*stat\b"),
    re.compile(r"^\s*du\b"),
    re.compile(r"^\s*df\b"),
    re.compile(r"^\s*tree\b"),
    re.compile(r"^\s*which\b"),
    re.compile(r"^\s*whereis\b"),
    re.compile(r"^\s*type\b"),
    re.compile(r"^\s*env\b"),
    re.compile(r"^\s*printenv\b"),
    re.compile(r"^\s*uname\b"),
    re.compile(r"^\s*whoami\b"),
    re.compile(r"^\s*id\b"),
    re.compile(r"^\s*date\b"),
    re.compile(r"^\s*cal\b"),
    re.compile(r"^\s*uptime\b"),
    re.compile(r"^\s*ps\b"),
    re.compile(r"^\s*top\b"),
    re.compile(r"^\s*htop\b"),
    re.compile(r"^\s*free\b"),
    re.compile(r"^\s*git\s+(status|log|diff|show|branch|remote|config\s+--get)", re.IGNORECASE),
    re.compile(r"^\s*git\s+ls-", re.IGNORECASE),
    re.compile(r"^\s*npm\s+(list|ls|view|info|search|outdated|audit)", re.IGNORECASE),
    re.compile(r"^\s*yarn\s+(list|info|why|audit)", re.IGNORECASE),
    re.compile(r"^\s*node\s+--version", re.IGNORECASE),
    re.compile(r"^\s*python\s+--version", re.IGNORECASE),
    re.compile(r"^\s*curl\s", re.IGNORECASE),
    re.compile(r"^\s*wget\s+-O\s*-", re.IGNORECASE),
    re.compile(r"^\s*jq\b"),
    re.compile(r"^\s*sed\s+-n", re.IGNORECASE),
    re.compile(r"^\s*awk\b"),
    re.compile(r"^\s*rg\b"),
    re.compile(r"^\s*fd\b"),
    re.compile(r"^\s*ast-grep\b"),
    re.compile(r"^\s*agent-browser\b"),
    re.compile(r"^\s*npx\s+agent-browser\b"),
    re.compile(r"^\s*bat\b"),
    re.compile(r"^\s*eza\b"),
    re.compile(r"^\s*perk\s+(objective|obj)\s+(show|s|next|n|node-engagement)\b", re.IGNORECASE),
    re.compile(
        r"^\s*gh\s+(issue|pr|repo|run|release|label)\s+(view|list|diff|status|checks)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*gh\s+search\s+(issues|prs|code|commits|repos)\b", re.IGNORECASE),
    re.compile(r"^\s*gh\s+auth\s+status\b", re.IGNORECASE),
)

# The two neutralized redirect carve-outs (see is_read_only_bash_command): FD duplications
# and /dev/null redirects discard output and write nothing to the filesystem.
_FD_REDIRECT = re.compile(r"\d*>&\d+")
_DEV_NULL_REDIRECT = re.compile(r"(?:\d+|&)?>>?\s*/dev/null\b")


def split_top_level_segments(command: str) -> list[str]:
    """Split a command into top-level shell segments for the per-segment safe check.

    Walks the string character by character tracking single- and double-quote state,
    splitting only on UNQUOTED sequencing operators ``;``, ``&&``, ``||``, and ``|``
    (``&&``/``||`` are two-char operators; a lone ``&`` stays in-segment so ``&>`` redirect
    detection and the destructive veto see it intact). Quoted operators must not split —
    a ``|`` inside ``grep -iE 'a|b'`` stays in one segment. Segments are trimmed and
    empties dropped.

    Known limitation (as in the TS source): backslash-escaped quote characters are not
    handled; the whole-string destructive veto remains the backstop.
    """
    segments: list[str] = []
    current = ""
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote is not None:
            current += ch
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            current += ch
            i += 1
            continue
        if ch in (";", "|", "&"):
            nxt = command[i + 1] if i + 1 < len(command) else ""
            if (ch == "|" and nxt == "|") or (ch == "&" and nxt == "&"):
                segments.append(current)
                current = ""
                i += 2
                continue
            if ch in (";", "|"):
                segments.append(current)
                current = ""
                i += 1
                continue
            current += ch
            i += 1
            continue
        current += ch
        i += 1
    segments.append(current)
    return [s for s in (seg.strip() for seg in segments) if s]


def is_read_only_bash_command(command: str) -> bool:
    """Whether a bash command is allowed under read-only mode (pure).

    Two independent checks, exactly as the TS gate:

    - NOT destructive: a WHOLE-STRING scan against ``DESTRUCTIVE_PATTERNS``
      (destructive-wins — content anywhere in the string, incl. command substitutions,
      still vetoes). FD duplications (``2>&1``) and ``/dev/null`` redirects are
      neutralized first — both discard output and write nothing; redirects to a REAL
      path stay destructive.
    - SAFE per segment: every quote-aware top-level segment's leading command must match
      a ``SAFE_PATTERNS`` entry.
    """
    without_fd_redirects = _DEV_NULL_REDIRECT.sub(" ", _FD_REDIRECT.sub(" ", command))
    is_destructive = any(p.search(without_fd_redirects) for p in DESTRUCTIVE_PATTERNS)
    segments = split_top_level_segments(command)
    is_safe = bool(segments) and all(any(p.search(seg) for p in SAFE_PATTERNS) for seg in segments)
    return not is_destructive and is_safe
