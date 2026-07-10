{{ marker }}
You are in perk read-only mode — a structurally enforced exploration mode (not advisory):

- edit/write are blocked; bash is restricted to an allowlist of read-only commands.
- plan_draft is the sole sanctioned write: it writes only the working-plan artifact in the
  session data dir.
- For GitHub data use read-only `gh` subcommands (view/list/diff/status/checks/search) —
  never raw curl/fetch against github.com (private repos reject unauthenticated requests).

Do not attempt to make changes.