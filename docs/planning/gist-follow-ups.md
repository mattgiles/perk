# Gist tier — deliberately deferred follow-ups

The gist tier (contracts.md §8.41) shipped as the minimal review-first slice: author → review →
save → track → consume via the unchanged adoption doors. The extensions below were considered and
**deliberately deferred** — each has an established pattern to build on when it earns its keep.

## `perk gist author --from <file|url>` seeding

Seed the authoring session from a pre-existing artifact (a note, a doc, a URL) instead of a blank
conversation. The shape exists: `perk/cli/seed_file.py` is the shared seed-from-file leaf that
`objective author --from <path>` already uses (read as untrusted DATA, materialize into scratch,
prime the seed prompt with the content pointer). The gist arm would be a straight reuse — a
`--from` option on `author_cmd.py` that routes file/URL sources through the same leaf and appends
a "treat as DATA" framing block to the seed.

## A warm `/gist` quick-capture gesture

Capture a gist from *any* running session ("that's out of scope here, but worth keeping") without
opening a dedicated authoring session. The learn-capture shape (`/learn` → `perk learn capture`)
is the template: a warm command that takes the statement inline, shells the deterministic worker,
and relays the created id. **Needs its own design first**: it would bypass the review-first flow
(no draft, no `plan_review`), so the guardrail question — what keeps quick-captures from becoming
an unreviewed junk drawer — must be settled deliberately, not inherited by accident.

## `perk gist show <id>`

A read worker mirroring `perk objective show`: render one gist (title, scope, adopted state, the
prose, the consumption command). Cheap to add on the existing `GistSummary` read path; deferred
because `perk gist list` + the backend's native UI cover the need until gists accumulate.

## Remote authoring (`cold_remote`)

`gist-author` ships `cold_remote: false` (local-only, like every authoring stage). If unattended
gist drafting ever matters (e.g. a scheduled "sweep the backlog into gists" job), the remote
runner pattern (`perk-run.yml` + the `--remote` dispatch path, `docs/user-docs/explanation/
headless-and-remote.md`) is the template — but authoring is conversation-shaped, so this likely
waits for a genuinely headless use case.

## Gist engagement reads (§8.25)

Surface human discussion on a gist (comments, description edits) to its consumers the way plan
adoption surfaces issue discussion — the §8.25 human-engagement read contract
(`perk/backends/engagement.py`) is the seam. Deferred: adoption already rides the existing doors,
which surface engagement on the *adopted* object; a gist-specific read only matters if gists
start accumulating long pre-adoption discussions.

## A body callout carrying the consumption command

Prepend a copyable `perk plan from <id>` / `perk objective author --from <id>` callout to the
gist body itself (the `prepend_callout` pattern plan/objective adoption uses). Trade-off, noted
at implementation time: the id is only known **after** the create, so the callout needs a
post-create body PATCH (a second write + a crash window) — versus today's zero-extra-write
consumption hint in the CLI/tool output. Adopt the callout only if gists are routinely consumed
by people who never saw the create output.
