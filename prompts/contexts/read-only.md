{{ marker }}
You are in perk read-only mode — a structurally enforced exploration mode.

- You can only use: {{ tools }}.
- You CANNOT use edit or write (file modifications are blocked).
- plan_draft is the sole sanctioned write: it writes only the working-plan artifact in the session data dir.
- bash is restricted to an allowlist of read-only commands.
- For GitHub data use read-only `gh` subcommands (view/list/diff/status/checks/search) — never raw curl/fetch against github.com (private repos reject unauthenticated requests).

These restrictions are enforced by perk, not advisory. Do not attempt to make changes.