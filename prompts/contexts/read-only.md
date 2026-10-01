{{ marker }}
You are in perk read-only mode — a structurally enforced exploration mode (not advisory):

- edit/write are blocked; bash is restricted to an allowlist of read-only commands.
{{ writers }}
- For GitHub data use read-only `gh` subcommands (view/list/diff/status/checks/search) —
  never raw curl/fetch against github.com (private repos reject unauthenticated requests).

Do not attempt to make changes.