# Changelog categorizer instruction

The canonical, maintained instruction a classifying agent (or a maintainer working by hand)
follows to turn the deterministic facts from `perk-dev changelog-commits` into a **reviewed**
changelog proposal.

This is a plain instruction doc — **not** a skill or subagent (deferred until repeated agent usage
proves the extra surface worthwhile). It is written agent-agnostically: either the maintainer's
interactive agent or a future subagent can follow it verbatim.

## Placement in the release workflow

This doc is one step in the CHANGELOG accrual loop documented in
[`docs/releasing.md`](../releasing.md) ("CHANGELOG discipline"):

```
perk-dev changelog-commits  →  classify (this doc)  →  human reviews  →  apply + advance marker  →  changelog-check
      (facts)                    (proposal JSON)         (the gate)        (changelog-apply *)        (structural lint)
```

`*` `perk-dev changelog-apply --proposal <file>` applies the approved proposal: it appends each
entry as a bullet under its `### <category>` subsection of `[Unreleased]` (stamping the primary
commit's short hash as the ` (hash)` token) and advances the `<!-- As of <hash> -->` marker to the
proposal's `head_commit`. `--dry-run` prints the intended new `[Unreleased]` section without
writing anything (see [`docs/releasing.md`](../releasing.md)).

The classifier's whole job is the middle box: **facts in, a reviewed proposal out.** It never
mutates `CHANGELOG.md` and never advances the `<!-- As of <hash> -->` marker — those belong to
`changelog-apply` / the maintainer.

## Input contract

The input is the `perk-dev changelog-commits --json` envelope:

```json
{
  "success": true,
  "error_type": null,
  "since_commit": "<full 40-char SHA>",
  "head_commit": "<full 40-char SHA>",
  "since_source": "flag | marker | release-fallback",
  "commits": [
    {
      "hash": "<full 40-char SHA>",
      "subject": "Fix the foo door (#123)",
      "body": "<commit body, ≤500 chars, ends with … on overflow>",
      "files": ["src/perk/cli/foo.py", "..."],
      "pr": 123
    }
  ]
}
```

- `since_commit` / `head_commit` — the resolved commit range (copy both verbatim into the output).
- `since_source` — how the range's start was resolved: `flag` (an explicit `--since`), `marker`
  (the `<!-- As of <hash> -->` cursor), or `release-fallback` (the latest `## [X.Y.Z]` release
  header, when no marker exists).
- `commits` — newest-first. Each carries `hash` (full SHA), `subject`, truncated `body`, the
  changed `files`, and `pr` (the extracted PR number, or `null`).

**The input is UNFILTERED except two lockfiles.** `changelog-commits` drops only `uv.lock` and
`package-lock.json`; it applies **no** other path or semantic judgment. Every other
inclusion/exclusion decision — and all categorization — lives in **this doc**.

If `success` is `false`, stop and surface `error_type` / the message to the maintainer rather than
proposing entries.

## Output contract

The classifier emits a **proposal JSON** object — the pinned shape that
`perk-dev changelog-apply` consumes:

```json
{
  "since_commit": "<copied verbatim from the input>",
  "head_commit": "<copied verbatim from the input>",
  "entries": [
    {
      "category": "Added",
      "text": "the bullet body only",
      "commits": ["<newest SHA>", "<older SHA>"],
      "confidence": "high",
      "backend": null
    }
  ]
}
```

Field semantics:

- `since_commit` / `head_commit` — copied verbatim from the `changelog-commits` envelope.
- `category` — exactly one of the pinned categories (see [Categories](#categories)).
- `text` — **the bullet body only.** No leading `- `. No trailing `(hash)` token (`changelog-apply`
  stamps that on apply). **Includes** any `Linear: ` / `GitHub: ` backend prefix.
- `commits` — the full SHAs rolled into this entry, **newest-first**. The **first** SHA is the
  entry's *primary* commit — its short hash is what `changelog-apply` stamps as the ` (hash)` token.
- `confidence` — `high` or `low`. **Review metadata only** — never written into the bullet.
- `backend` — `null`, `linear`, or `github`. **Review metadata only** — never written into the
  bullet (the *prefix* lives in `text`; this marker just flags the entry for review).

`confidence` and `backend` focus the human review; they are stripped by the time an entry becomes a
CHANGELOG bullet.

## The user-visibility test

The single governing principle:

> **Does a perk user see different behavior?**
>
> - **YES** → maybe an entry (then pick a category).
> - **NO** → filter it out. Always.

A changelog that mixes internal refactors with user-facing changes becomes noise, and users stop
reading it. When in doubt, this test — not the size of the diff — decides.

## Include (user-facing perk surfaces)

Changes to these surfaces are user-visible. Signals (paths are illustrative, not exhaustive):

- **`perk` CLI behavior** — new/changed commands, flags, output (`src/perk/cli/`).
- **Pi-extension behavior** — in-session tools, doors, and stages (`extension/`).
- **Managed wiring** written by `perk init` / `perk doctor --fix` (`src/perk/convergence/`) — the
  files and blocks perk writes into a consumer repo.
- **Doctor checks / reports / fixes** — new checks, changed report fields, new repairs.
- **Remote-runner behavior** — `src/perk/run/`, `.github/workflows/perk-run.yml`, the
  `perk-remote-setup` action.
- **Issue-backend behavior** — GitHub / Linear backend behavior (`src/perk/backends/`).
- **User docs** that document a behavior change (`docs/user-docs/`).

## Potentially user-facing (verify before deciding)

Generated / managed artifacts perk delivers into consumer repos:

- `.github/workflows/perk-run.yml`, the `perk-remote-setup` action.
- `.pi/agents/perk/*.md` (delivered agent definitions).
- Managed manifest fragments; the managed `.gitignore` / AGENTS blocks; `.perk/` files.

**Rule:** include when the change alters *delivered behavior*; filter pure formatting or no-op churn
(a whitespace-only reflow of a delivered workflow is not an entry).

## Filter (never an entry)

- **Internal refactors** with no user-visible change (renames, module moves, consolidations).
- **Tests** — `tests/`, `*.test.ts`, fixtures.
- **Packaging-only work** — `pyproject.toml` / hatchling / npm packaging, lockfiles, wheel/sdist
  plumbing.
- **Learned-doc maintenance** — `docs/learned/`.
- **Release tooling itself** — `packages/perk-dev/`, version bumps, CHANGELOG housekeeping.
- **Internal / design docs** — `docs/design/`, `docs/planning/`, `docs/guiding-principles/`.
- **CI-only workflow changes** — except the *delivered* perk-run / remote artifacts listed under
  [Potentially user-facing](#potentially-user-facing-verify-before-deciding).

## Categories

The pinned set (Keep-a-Changelog plus perk's `Major Changes`):

`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, `Major Changes`.

Any **other** category name is a structural error that `perk-dev changelog-check` will reject.

**The `Major Changes` higher bar.** Not just user-visible — *significantly* user-visible: the kind
of change a user should know about before upgrading (new user-facing systems, breaking changes, CLI
reorganization). **Not every release has one** — never force a roll-up or a pile of fixes into
`Major Changes` just to fill it. Roll all related commits into a single prose entry that states
**what** it does, **why** it was built, and the **value** to the user; never expose implementation
detail.

## Roll-up

Merge a multi-commit feature series into **one** entry — its `commits` list carries all rolled
SHAs, newest-first. The roll-up communicates the finished feature, not the implementation journey.

Detection signals:

- Multiple commits sharing a keyword (e.g. "artifact sync").
- Sequential PR numbers on the same topic.
- Commits referencing the same objective / node.

## Backend-qualified entries

A feature that affects only **one** issue backend gets a `Linear: ` / `GitHub: ` prefix in `text`
**and** the matching `backend` marker (`"linear"` / `"github"`). `backend` is symmetric:

- `null` — applies to both backends / baseline behavior (an unqualified bullet).
- `"linear"` — a Linear-only change; `text` leads with `Linear: `.
- `"github"` — a GitHub-only change; `text` leads with `GitHub: ` (the rare case).

Always set `confidence: "low"` on a backend-qualified entry — flag it for human review.

## Confidence flags

Set `confidence: "low"` when categorization is uncertain:

- The commit message is vague ("update X" — Changed or internal?).
- Scope is unclear (user-facing or internal-only?).
- The category is borderline ("Add X" that is really a refactor).
- A large change might or might not affect users.
- A commit touches both user-facing and internal code.

Low confidence is an honest signal to the reviewer — "verify this" — not a defect.

## Entry shape examples

Each example is shown as **(a)** the proposal-JSON entry the classifier emits and **(b)** the
resulting `CHANGELOG.md` bullet after `changelog-apply` stamps the ` (hash)` token from the
entry's *primary* (first) commit.

### Normal — a single Added/Changed/Fixed entry

(a) proposal entry:

```json
{
  "category": "Added",
  "text": "Add the `/pr-review` door: spawn angle-specialized reviewers and post one verdict",
  "commits": ["abc1234000000000000000000000000000000000"],
  "confidence": "high",
  "backend": null
}
```

(b) resulting bullet under `### Added`:

```markdown
- Add the `/pr-review` door: spawn angle-specialized reviewers and post one verdict (abc1234)
```

### Roll-up — one entry summarizing a feature series

(a) proposal entry (`commits` newest-first; the first SHA is the primary):

```json
{
  "category": "Changed",
  "text": "Rework worktree launch to run the configured `[worktree] setup` hook before exec",
  "commits": [
    "def5678000000000000000000000000000000000",
    "abc1234000000000000000000000000000000000",
    "9990000000000000000000000000000000000000"
  ],
  "confidence": "high",
  "backend": null
}
```

(b) resulting bullet under `### Changed` (only the primary short hash is stamped):

```markdown
- Rework worktree launch to run the configured `[worktree] setup` hook before exec (def5678)
```

### Backend-qualified — `backend: "linear"`

(a) proposal entry (`text` carries the `Linear: ` prefix; `backend` marks it; low confidence):

```json
{
  "category": "Added",
  "text": "Linear: adopt an existing Linear project as a perk objective in place",
  "commits": ["77aa00000000000000000000000000000000000000"],
  "confidence": "low",
  "backend": "linear"
}
```

(b) resulting bullet under `### Added`:

```markdown
- Linear: adopt an existing Linear project as a perk objective in place (77aa000)
```

### Major Changes — what / why / user-value prose

(a) proposal entry:

```json
{
  "category": "Major Changes",
  "text": "**Remote autonomous runs.** perk can now dispatch a plan to a GitHub Actions runner and drive it to a PR unattended. This lets maintainers hand off long implementations without holding a local session open — the run reports back on the plan's PR when it lands.",
  "commits": [
    "cafe123000000000000000000000000000000000",
    "beef456000000000000000000000000000000000"
  ],
  "confidence": "high",
  "backend": null
}
```

(b) resulting bullet under `### Major Changes`:

```markdown
- **Remote autonomous runs.** perk can now dispatch a plan to a GitHub Actions runner and drive it to a PR unattended. This lets maintainers hand off long implementations without holding a local session open — the run reports back on the plan's PR when it lands. (cafe123)
```
