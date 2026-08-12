---
title: In-place adoption of a pre-existing issue / Linear project
read_when: You are adopting an existing issue or Linear project as a perk plan/objective in place (`plan from`, `objective author --from`), seeding authoring from a file/URL, or byte-preserving a foreign field.
cluster: backends-and-integrations
---

# In-place adoption of a pre-existing issue / Linear project

Adoption turns a **human-authored** issue (or Linear project) into a perk plan/objective **in
place** — stamping perk's metadata additively into the same object rather than minting a second
one, and preserving the human's title/body verbatim. This is the durable reasoning from building
the plan-adoption (`plan from`) and objective-adoption (`objective author --from`) writers.

## The in-place-writer family

Adoption adds the **third and fourth** in-place writers (after node-unification's `save_node_plan`
and `create_plan_issue`): stamp perk metadata **additively into the same object**, never minting a
second. Routing mirrors the replan cold door:

- `perk plan from <issue>` → a fresh-run-id read-only `plan` stage → `plan save --adopt-from`.
- `objective author --from <source>` → a read-only author stage → `objective create`.

In both, the adoption link is recovered via the run handoff (below), not carried as a save param.

## Seed-from-file mode (a sibling to in-place adoption, NOT an in-place writer) (#862)

Both adoption doors also accept a **local file path** (`plan from <file>` /
`objective author --from <file>`) that seeds a fresh authoring session from the file's contents.
This is distinct from in-place adoption — there is no foreign object to stamp — and the distinction
is the whole design axis:

- **"A file has no backend identity to stamp" is the design axis.** Because there is nothing to
  adopt-in-place, file mode reuses the **bare authoring** path verbatim: it **omits the `adopt_from`
  handoff** (saving mints a fresh issue) and **skips `require_github`** (the only read is local; the
  backend write happens in-session at save time), while still keeping `require_repo`/`require_config`
  (scratch dir + launch config) and the `resolve_target` `--remote` rejection (local-only).
  Generalize: when an arg variant performs only a local read, **gate auth at the point of network
  use**, not up front.
- **Detection-before-parsing is the ordering contract.** The file disambiguator
  (`Path(arg).expanduser().is_file()` → `.resolve()` else fall through) runs at the **TOP** of both
  doors, **before** `require_github` and id parsing, because the id parser is hostile to path syntax
  (`/` → `invalid_input`). "Existing readable file wins, else fall through unchanged" needs zero
  new path-shape heuristics — a non-existent path just hits the existing resolver and errors as
  today (`adopt_not_found`).
- **Clean leaf separation.** The neutral wrapper (`<untrusted_seed_file>`) + the slash-free scratch
  filename scheme (`seed-file-<safe-stem>-<sha1(abspath)[:8]>.md`) live in one **backend-free** leaf
  (`perk/cli/seed_file.py`: `detect_seed_file` / `read_seed_file` / `render_seed_file_scratch`);
  only the plan/objective-specific seed-prompt verbs live in each door's seed prompt. Both doors
  render failures via the shared `perk.cli.emit.fail` and mirror each other except the stage
  descriptor and the seed verbs — keeping the leaf truly backend-free.
- **Test gotcha: `CliRunner().isolated_filesystem()` already `chdir`s.** Adding `monkeypatch.chdir(d)`
  on top makes monkeypatch record the temp dir as the cwd-to-restore; `isolated_filesystem` deletes
  it on exit, then teardown `os.chdir`s to a now-deleted dir → `FileNotFoundError` in teardown (the
  test reports as both passed AND errored — easy to misread the count). For cwd-relative file
  detection, rely on the runner's own chdir — write the file as `Path(d, "notes.md")` and invoke
  with the bare relative name; do **not** add `monkeypatch.chdir`.

### Third consumer + a URL sub-mode (#988)

`skills create --from <file|url>` is the **THIRD** seed-from-source consumer (after `plan from` /
`objective author --from`), keeping `perk/cli/seed_file.py` a backend-free / stdlib-only leaf. It adds
a **URL sub-mode** and confirms the per-artifact adoption asymmetry once more:

- **A new pure scheme-gate `detect_seed_url(arg) -> str | None` (http/https only)** — the same idiom
  as the `_id_from_url` URL detector (`urlsplit(arg.strip()).scheme.lower() in {"http", "https"}`). It
  does NOT fetch or validate reachability; the in-session **read-write, non-tool-restricted** agent
  owns the fetch of the `SKILL.md` + sibling `references/` / `scripts/` / linked files. URL sub-mode
  is **offline-at-the-door** (zero Python network; no `require_github`; no scratch materialized —
  contrast file mode, which materializes a gitignored `<untrusted_seed_file>` scratch even on
  `--dry-run`). `detect_seed_file` / `read_seed_file` / `render_seed_file_scratch` are reused
  UNCHANGED for file mode.
- **Detection ORDER diverges by door** (record per-door, matching `contracts.md §8.33`): `plan from` /
  `objective author --from` detect **file-first then fall through to an id**; `skills create --from`
  is **URL-first, then file, else a hard seed-file error** — no id/adoption fall-through because a
  skill has no backend identity.
- **No in-place adoption for skills** — both modes always mint a FRESH skill (no `adopt_from`
  handoff, no `adopted_from` provenance, no metadata stamping; a skill is not a backend object). This
  is the **4th** surface confirming the "adoption surface shape decided per-artifact" rule: skills got
  the seed-from-source half but NOT the in-place-adoption half.
- **Byte-identity discipline:** the no-`--from` dry-run JSON payload is asserted with exact `==`;
  keep it byte-identical by **branching** (a `--from` path ADDS `"from"` (+ file-mode `"scratch_path"`)
  keys; the no-`--from` path is untouched) and by isolating all seed complexity in a **NEW conditional
  prompt template** (`create-from.md`) so the existing `create.md` renders byte-for-byte unchanged.
  The conditional template uses the frozen mini-jinja `{% if seed_url %}` over a bare ident with both
  vars always passed (one empty); `live.yaml` needs BOTH arms (file + URL) for the coverage guard; a
  `prompts/`-only diff skips `node:test` under `[[ci.checks]]` → run the prompt-grammar / prompts node:tests
  manually.
- **Test/CI mechanics:** `--json --dry-run` prints ONLY the JSON payload (machine_output); the
  human-readable seed prompt prints only in non-JSON mode (user_output→stderr) — so a test asserting
  the seed text references the URL + fetch instruction must invoke TWICE (once `--json` for payload
  shape, once non-`--json` for the printed seed). `CliRunner().isolated_filesystem()` already chdirs,
  so relative `--from` paths resolve there (see the chdir gotcha above).

## Surface shape is decided per-node, asymmetrically (#711)

The two adoption surfaces deliberately differ in shape:

- Plan adoption is a `plan from` **verb**.
- Objective adoption is a `--from` **flag on `objective author`** — keeps the single authoring
  entry point, matches the roadmap node's title, and leaves the door byte-unchanged when absent.

**Lesson:** when mirroring a sibling adoption seam, **re-decide the surface shape** — don't assume
the verb form carries over to the sibling.

## Don't borrow a mutator that touches the preserved field — compose from primitives (#708)

This was the central deviation. Adoption's invariant is a **byte-preserved** human title/body, but
`update_plan_issue` PATCHes the title. So adoption got **dedicated** writers:

- **GitHub** folds the body stamp + callout prepend into **one** body PATCH (read-modify-write) and
  upserts the plan-body comment via the existing finder (patch-if-found else POST) — **never** the
  title.
- **Linear** mirrors `save_node_plan` + an additive `labelIds` union.

**General lesson:** if a write must preserve a foreign field verbatim, **compose from the
lower-level primitives** rather than reusing a higher mutator that touches the field.

## `read_issue` is a genuinely new third issue-read shape (#708)

Neither `get_plan` (needs a plan-header) nor `get_plan_body` can read a *non-perk* issue's raw
title+body+state. `read_issue(*, issue_id) -> AdoptableIssue | None` is that primitive; state is
normalized to `OPEN | CLOSED` at the adapter. Conform every `IssueBackend` fake (ty is the oracle).

## Additive labels: GitHub vs Linear divergence

- **Linear** `issueUpdate.labelIds` **REPLACES** the set → read the existing label ids and **union**
  the perk label in (same pattern as `close_and_label_consolidated`).
- **GitHub** `add_issue_label` POSTs to `/labels` (natively additive — never replaces).
- The **absent-plan-header** branch composes **inline-code** (Linear-safe), never the lossy-HTML
  `replace_metadata_block` append.

## Carry per-node adoption metadata in a SEPARATE side-map (#711)

`adopt_issue` (node→existing-issue) rides a pure `objective.parse_adopt_mapping(raw)` extracted from
the same raw roadmap JSON — **NOT** a field on `ObjectiveNode` (which is used pervasively in
rendering/manifest/drift; keep it pristine).

**Cross-plane gatekeeping for a new per-node roadmap field:** it needs the **TS
`ROADMAP_PARAM_SCHEMA` edit and nothing in the Python validator** — the `additionalProperties:false`
TS schema rejects unknown keys at the tool boundary, while Python's `validate_roadmap` ignores
extras (`roadmap` flows as `unknown[]`). **TS schema gatekeeps; Python parse is lenient.**

## Verbatim preservation differs by tier (#711)

- **Plan adoption** preserves the body **in place**.
- **Objective adoption** authors NEW Reconcilable prose and **archives** the source's original
  overview verbatim into an immutable `Adopted-from` note — a perk HTML-comment marker
  round-tripping through `to_linear_markdown` → inline-code — appended below the closing
  Reconcilable marker. An empty original → `""`.

## Handoff-rides-the-link (the 3rd/4th instance of THE pattern)

A save surface forwards only a fixed param set (`/plan-save` → `{plan, title}`; `objective_save` →
`{prose, roadmap, title, base, run-id}`), so the adoption link must survive via the **run handoff**,
not a tool param: stash `adopt_from` at launch, recover it at save (`_adopt_from_handoff`; explicit
flag wins, best-effort, `OSError`/`ValueError` swallowed). Same shape as `_link_from_handoff` /
`_consumed_learn_from_handoff` / `objective_id`. **No TS tool change.**

The two in-place writers must not mix: `--adopt-from` is **mutually exclusive** with
`--objective-id` / `--node-id`.

## `adopted_from` provenance is self-referential by construction (#708)

Its **presence** in the plan-header is the canonical "this is an adopted plan; title/body are
verbatim human content" signal (added to `PlanHeader` + `to_data()` + `PLAN_HEADER_FIELDS`).

## Backend-discriminated OPEN refusal at the cold door (#711)

The neutral source shape carries **no `state` field** (Linear projects have no open/closed). The
GitHub-only `adopt_not_open` refusal reaches into the ISSUE tier
(`issues.resolve_issue_backend(...).read_issue(...).state`) **only when
`store.backend_id == "github"`**. Keep the objective-store read state-free; branch the OPEN
discriminator on `backend_id` **at the door**.

## Protocol-growth + no-op family (#711)

New `ObjectiveStore` methods (`read_objective_source` / `adopt_source_as_objective`) extend the
no-op-return family (`→ None` = "no project surface" / "doesn't adopt"); `dry_run → None` (resolving
the source is a network read, so the offline `--dry-run` falls through to the offline
compose-preview).

## Linear project-backed writer mechanics (#711)

- Adopt in place = `update_project_content`, **NOT** `create_project`.
- Milestones de-duped against existing (`project_milestones`-seeded `known` map vs the empty seed on
  a fresh create).
- A new title-carrying **sibling** query `project_issues_for_adoption` (the byte-stable
  `project_issues` left untouched — the established sibling-query rule).
- **Two-pass node/relation ordering:** materialize ALL node UUIDs (mapped + freshly-minted) first,
  THEN create `depends_on` relations, so a relation never references a not-yet-created node; capture
  UUIDs from the create/existing payload (no extra lookup).

## "doctor note" can mean prose-only (#708)

A "doctor awareness note" deliverable was satisfied by a **docstring** note in the doctor command —
explicitly **not** a new validating check. Don't over-build a "note" into a gate.

## Residual

Both surfaces are **offline-covered only** (scripted fakes + cold-door/save/handoff). Live Linear
field-selectability and the end-to-end stamp against a real human issue are deferred to the
objective's live-validation node — consistent with the missing-`LINEAR_API_KEY` implement env.

## Cross-references

- `plan-save-surfaces.md` — the handoff-rides-the-link carriers and the save-param fixed set
- `objective-store.md` — the adoption Protocol-growth + no-op family
- `linear-backend.md` — the project-backed writer + the `_FakeLinear` substring footgun
- `issue-backend.md` — `read_issue` as the third issue-read shape
- `github-gateway.md` — the GitHub body-PATCH + label primitives
