# perk developer docs

This tree is the developer-facing product documentation for **perk's own repository**. It covers
surfaces that exist only in the self-repo, including `perk-dev` maintainer tooling and repo-local
agents. It is distinct from [`docs/user-docs/`](../user-docs/index.mdx), which documents perk for
operators using it on their own repositories, and from the internal research and design record
indexed by [`docs/index.md`](../index.md).

## How this tree is organized

The pages follow the [Divio documentation system](https://docs.divio.com/documentation-system/),
and each page states its kind. The tree stays flat while it is small rather than creating one
subdirectory per kind.

| Page | Kind | Read this when … |
|---|---|---|
| [Session audit reference](./session-audit.md) | Reference | you need to look up the session-audit catalog, corpus, verdicts, commands, artifacts, stage, or wave tool |
| [How to audit recorded sessions](./auditing-sessions.md) | How-to | you want to audit perk's recorded Pi sessions and triage the resulting leads |
| [Why perk audits sessions](./why-session-audit.md) | Explanation | you want to understand why the audit exists and why it favors honest degradation over enforcement |
