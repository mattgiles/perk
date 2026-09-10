---
title: Borrowed Pi packages — the lockstep-surfaces recipe and the evaluation bar
read_when: You are changing borrowed/filtered Pi packages, package convergence or health equivalence, source-bound reviewer skills, launch exposure, or borrow-vs-provider decisions.
cluster: config-and-convergence
---

# Borrowed Pi packages

perk ships a small set of **borrowed** Pi packages (entries in `BORROWED_PACKAGES` in
`src/perk/convergence/init/settings.py`, converged into every consumer repo's `.pi/settings.json`) —
among them the two **required** borrows the retired askuser/todo seams collapsed into,
`npm:@juicesharp/rpiv-ask-user-question` (the `ask_user_question` questionnaire) and
`npm:@juicesharp/rpiv-todo` (the `todo` checklist overlay). This doc is the recipe
for changing that set without leaving surfaces stale, plus the evaluation bar that decides whether
a capability is a borrow at all.

## Distillation

- Borrow changes update convergence, committed settings, capability summary, contracts, and tests
  in one turn — "The lockstep-surfaces recipe".
- Most borrows are strings; a filtered borrow is an object-form member installed but ambiently
  disabled by all four Pi resource filters — "Filtered borrowed packages".
- Merge/dedup and managed-state health must share one package-entry equivalence relation, or
  convergence manufactures phantom drift — "The provider→borrow reclassification trap".
- Source-bound reviewer skills use an exact installed `skillPath`, inheritance off, and deterministic
  non-retryable preflight failures that remain in coverage — "Source-bound skill isolation".
- Purpose-built subset parsers stay narrow; external manifests get minimal field extraction rather
  than a wider quasi-YAML parser — "The miniYaml reversal".
- Borrow vetting checks singleton UI slots, headless behavior, maintenance/license, and Pi floors;
  repo non-mutation is the read-only bar — "Vetting" and "The read-only bar".
- When upstream surfaces disagree, runtime tool description + code + changelog outrank packaged
  skill/doc prose — "When upstream's own surfaces disagree".
- Lazy install/restart, filter security limits, and attempted-vs-covered bookkeeping remain explicit
  residuals — "Residuals".
- A parser needed by the bare-clone extension would be vendored as a byte-pinned module *closure*,
  not borrowed as a runtime dependency — the one instance (smol-toml) retired with the draft-review
  protocol — "Vendor a parser closure, not a runtime dependency".
- Late-registering borrowed tools are ADMITTED (sticky `snapshot ∪ admitted` baseline + the
  `resources_discover` re-apply), not leaked — "Borrowed-tool stage scoping".
- Read a borrowed engine's config once at activation (fix = quit and resume), refuse-don't-converge
  its private config, and expect builtin-shadowing packages to break other packages' host
  intersections (`PI_FFF_MODE=tools-and-ui`) — "Borrowed-engine stances".

## The lockstep-surfaces recipe

Adding (or removing) a borrowed package touches a fixed set of surfaces **in one turn**:

1. `BORROWED_PACKAGES` in `src/perk/convergence/init/settings.py` — normally a plain unpinned
   `npm:` string plus one rationale line. A borrow that must be installed but ambiently disabled
   uses the filtered object-form exception described below.
2. The committed `.pi/settings.json` in this repo — same entry; never let the committed settings lag
   `BORROWED_PACKAGES`. The edit is **identity-based**: when an object-form entry with the same
   npm identity already exists (a former provider entry), adding the borrow changes nothing in
   `.pi/settings.json` — this surface is satisfied by *identity*, not exact string
   (`_package_identity` dedups by npm name; the two rpiv borrows already sat there object-form
   when the seams retired to borrows). Merge-based convergence preserves the historical shape;
   see the reclassification trap below.
3. The `borrowed-packages` capability summary in `src/perk/convergence/capabilities.py` — **this string drifts
   silently**; check it whenever the borrowed set changes.
4. `shared/contracts.md` — the borrowed-set enumeration (settings-wiring section) plus any behavior
   the package alters (e.g. the tool-gating restricted set).
5. Tests — a membership assert in `tests/test_init_idempotent.py`, plus any behavior anchor (e.g.
   `READ_ONLY_TOOLS` membership in `extension/substrate/toolGating.test.ts`).

## Filtered borrowed packages

Ponytail is the first object-form borrowed member. It is installed for source-bound review waves
but ambiently disabled by setting all four Pi resource filters to empty arrays. Three pieces must
stay coordinated:

1. The dedicated reconciler in `src/perk/convergence/init/settings.py` matches donor identity,
   preserves position, pin, and unrelated keys, forces the four empty filters, removes duplicate
   identities, and appends a canonical entry when absent. This is deterministic convergence, not a
   committed-settings special case.
2. Managed-state health normalizes that exact identity with the same merge/dedup equivalence. If
   convergence and hash/compare disagree about semantic equality, every run creates phantom drift.
3. `src/perk/substrate/skill_exposure.py` excludes the package from cold-launch skill discovery on
   the exact `skills: []` opt-out. It does not reimplement Pi's general filter matching.

The empty filters are a loading boundary, not a security boundary. Explicit source-bound loading is
still possible and is the reason this object exists.

## The provider→borrow reclassification equivalence trap

Reclassifying a package (provider-managed → borrowed) changes the *desired* settings-entry shape
(a plain `npm:` string) while merge-based convergence preserves the repo's historical
`{"source": …}` **object** form by identity. Convergence no-ops cleanly — but the managed-state
health lens hashes *shapes*, so the `settings-wiring` check classifies `locally-modified`
**forever**, unrepairable by `doctor --fix`. The defect can even **pre-date** the change that
surfaces it (an earlier reclassification had already planted a standing warn nobody noticed).

Fix shape: canonicalize merge-equivalence in the health lens — `_canonical_package_entry` in
`src/perk/convergence/managed_state.py` collapses only *bare source-only* objects to their string
spec; filter-carrying objects stay semantically richer and still classify as drift.

General rule: **when two mechanisms (merge/dedup vs hash/compare) observe the same data, they
must share the equivalence relation** — or every reclassification manufactures phantom drift. The
filtered object exception is a second instance: donor merge/dedup and canonical health comparison
must normalize the same identity to the same meaning.

## Source-bound skill isolation

A reviewer lane may load one exact skill from an ambiently disabled package without enabling the
package's other resources. Resolve an invocation-local `skillPath` to the installed file and turn
skill inheritance off. The workflow's `skill:` key remains lookup metadata; it is not the loading
mechanism.

Preflight the package identity, manifest, and skill frontmatter before spawn. A missing or malformed
source is a typed deterministic, non-retryable `skill-unavailable` result. The lane remains in the
requested coverage denominator and never spawns; do not hide installation drift as a generic wave
failure or retry. Doctor carries marker tripwires over the upstream version pins whose mechanics
this path relies on.

## The miniYaml reversal

`miniYaml` remains a dependency-free parser for its purpose-built contract subset. Validating an
external manifest is not a reason to widen it toward general YAML. Extract only the minimal field
needed for identity/frontmatter preflight with a dedicated bounded reader. Expanding a tiny internal
parser to accept foreign-file grammar creates an accidental second YAML implementation.

## A borrowed package's behavior change rides managed convergence — never a hand-edit

Changing how a **borrowed** package behaves (a settings key it reads, a bulk flag) is a **managed**
piece: it must be composed into the settings convergence — the desired-portion writer *and* the
observed/desired-portion twins doctor compares — exactly like the borrowed-set entries themselves.
A hand-edit of perk's *own* `.pi/settings.json` fixes exactly one repo; `BORROWED_PACKAGES` (and the
behavior around it) is delivered to **every** consumer, so a hand-edit silently strands every other
repo. The scoping rule that catches this: **grep `BORROWED_PACKAGES` when scoping any
borrowed-package change** — it lands you in `src/perk/convergence/init/settings.py`, where the
convergence lives, not in the committed settings file.

Concrete instance: `subagents.disableBuiltins` (the bulk disable of pi-subagents' builtin agents) is
converged by `_converge_subagents` in `src/perk/convergence/init/settings.py`, not hand-set. The first
attempt at delivering it died on exactly this scope gap — a hand-edit that looked done but reached
no consumer. (See `init-doctor.md` for the delta-gated change-fragment rule this same
constant-desired convergence forced, and `pi/subagents.md` for the re-enable precedence it
establishes.)

## Vetting: grep for singleton UI slots (the setFooter clobber)

Pi's footer is a **single last-wins slot**, and extensions receive `session_start` in settings
load order — so a later-loaded borrowed package calling `ctx.ui.setFooter` silently clobbers
perk's footer (no error, no log). This is now a contracts.md rule: borrowed packages must never
call `ctx.ui.setFooter`. Before borrowing, grep the candidate's **installed** source for
`setFooter` and other singleton UI slots — and note gitignored `.pi/npm/` defeats ripgrep
evidence: use `--no-ignore` (or `grep -r`) under `.pi/npm/node_modules/`, or the grep comes back
falsely empty.

## When upstream's own surfaces disagree (#2005)

When a borrowed package's packaged skill/doc prose contradicts its runtime behavior, the
authority order is: the runtime tool description + the code + the changelog — never the packaged
skill/doc prose. Verify guidance claims against what the installed version actually executes
before pinning probes or writing perk-side guidance to them.

## The retirement recipe (thrice-affirmed)

Removing a borrowed package (pi-plan, rpiv-todo — since **re-adopted** as a required borrow when
the todo seam retired — and pi-status precedents) touches, in one commit:
remove from `BORROWED_PACKAGES` with an inline rationale comment, edit the committed
`.pi/settings.json`, fix the capability summary string, amend both contracts.md sites
(borrowed-set enumeration + the owning-feature paragraph), and invert the init-idempotency
membership assert. **No `doctor --fix` stale-entry removal** — consumer repos keep the entry as an
unmanaged user extra (precedent thrice-affirmed; a stale-entry doctor check is a plausible future,
deliberately not built).

Fixture subtlety: "borrowed package preserved across provider select/deselect" fixtures must use a
*still-borrowed* package; if a test needs strict "user extra survives" semantics, anchor on
`npm:@me/custom`, not a borrowed entry (init would re-add a borrowed one regardless).

## Foreign tool names are inert when absent

Allowlisting a borrowed package's tool names in `READ_ONLY_TOOLS` needs **no presence detection**:
when the package is absent, `pi.setActiveTools` simply has nothing to enable (the `plan_review`
precedent). Prefer static allowlisting over package-presence gating. The injected read-only notice
interpolates `READ_ONLY_TOOLS`, so it self-updates.

## Borrowed-tool stage scoping (the census, placement, and two invariants)

Stage scoping filters the scoped universe `PERK_TOOLS ∪ BORROWED_TOOLS`
(`extension/substrate/toolGating.ts`): an enumerated static-name census with the same
inert-when-absent posture as `READ_ONLY_TOOLS`; un-enumerated foreign names pass through
(fail-open — enumeration is diet-completeness, not correctness).

Placement matrix: research/web tools are universal; delegation + `todo` are worktree-family only;
Linear-mutating + plannotator-submit tools sit in no stage list.

Two invariants worth knowing before touching the census:

- **Single-governance**: a name is governed ONCE — it lives in exactly one census.
  `ask_user_question` now **IS** in the borrowed census (`BORROWED_TOOLS`): the foreign
  questionnaire is the sole registrant since the first-party tool was deleted, so
  the name lives in the borrowed census, not `PERK_TOOLS` (hygiene-tested). `READ_ONLY_TOOLS`
  and the `STAGE_TOOLS` lists keep it name-keyed/universal.
- **Registration timing — the admission model**: a borrowed package registering tools during its
  own `session_start` *after* perk's sync (perk is the first `packages` entry) is not in the
  first-engagement `getAllTools()` census. `extension/substrate/toolGating.ts` handles this by
  **admission**, not by accepting a leak: the baseline for every gate-OFF reconciliation is
  `snapshot ∪ admitted`; `admitted` grows the first time a gate-OFF path sees an active tool the
  census never had (`admitLate`); and a one-shot `resources_discover` re-apply — Pi fires it after
  EVERY extension's `session_start` — applies the mode/stage diet at the one point where
  startup-late registrants meet it. So pi-subagents' `subagent_supervisor` is inside the diet at
  launch, and admission is **sticky** (first sighting; perk's own filtering never evicts it, so a
  navigation back to an admitting stage restores it). Edges: a late tool its owner deactivated
  before perk ever saw it active is never admitted; a tool the census saw inactive is never
  re-activated; gate-ON paths do no admission bookkeeping (the gate-ON set is by name — an
  accepted residual); the snapshot stays the restore authority.

## The read-only bar is repo non-mutation, not zero side effects

Read-only mode's invariant is that the **repo** isn't mutated — not that the tool has zero side
effects. A tool that writes its own cache outside the worktree (e.g. `fetch_content`'s GitHub-clone
path) is morally equivalent to the already-allowlisted `curl`. Use that bar when evaluating future
allowlist candidates.

## Borrow vs. provider-seam criterion

A **provider seam** is for *owned-surface deferral* with a cross-plane contract (see
`workflow/provider-seam.md`). A borrowed capability that defers no perk-owned surface and produces
no cross-plane contract gets a plain `BORROWED_PACKAGES` entry — not a seam.

Evaluation keys that held up for the borrow decision: zero-config (no API key required — the bar
for a *required* borrowed package), headless-safe (`ctx.hasUI` guards verified in the package's
source), actively maintained, license, and the package's pi-version floor vs perk's pin.

## Vendor a parser *closure*, not a runtime dependency

The bare-clone extension must load with **no `node_modules`**, so a library it needs at load time
cannot be a runtime dependency (`tests/test_packaging.py` pins that invariant). The one realized
instance — a vendored `smol-toml` parse-side closure for the persisted draft-review protocol's
routing-input reader — was **removed with that protocol** (`workflow/plan-review-flow.md` § "Replaced
by four in-memory guards"); no vendored parser closure exists in the tree today. The selection
reasoning stays as a retired precedent for the next one: copy only the needed module closure (parse
side only) plus its `.d.ts`, the upstream `LICENSE`, and a provenance `README.md`; pin the upstream as
a **devDependency** solely so a test can assert byte identity against `node_modules` (provenance
proof, not a runtime edge); exclude the directory from Biome; give the source-scan guards the
widen/carve-out/prove-live treatment (`workflow/source-scan-guards.md`); cover the shipped file set in
`tests/test_packaging.py` and `perk_dev/build.py`. The surviving cross-plane config path needs no
parser at all: `extension/session/saveDestination.ts`'s conservative subset scanner vouches for a
`[issues]` spelling or widens to the verbatim document, with the dialect gap pinned by
`shared/fixtures/issues-table.json` (`workflow/shared-contracts.md`).

## Borrowed-engine stances (config, private state, and builtin shadowing)

Three stances toward a borrowed *engine* (pi-subagents, pi-fff) that go beyond the package-entry
recipe:

- **Read a borrowed engine's config once, at its activation — never per-dispatch.** pi-subagents
  applies its `loadConfig()` once at its own activation, so a mid-session edit to its `config.json`
  is invisible until Pi restarts. perk mirrors that: the conflict-resolver engine reads the native
  `worktree` default once at activation (`readNativeWorktreeDefault`), and the surfaced refusal's
  fix is "quit and resume this Pi session" — not `/reload` (which re-runs perk's factory but not
  the borrowed engine's config load), not a doctor `--fix`.
- **Observe-and-refuse a borrowed tool's private config; never converge it.** perk used to rewrite
  pi-subagents' `config.json` (`worktree: false`) through init/doctor; that arm is gone. The
  refusal (`extension/delivery/conflictResolution.ts::nativeWorktreeRefusal`) names the path, the
  observed value, and a one-line fix for the operator — the operator owns the file
  (`workflow/mergeability-and-conflict-resolution.md`).
- **Vetting a package that shadows a builtin by name has a cross-package consequence.** pi-fff's
  `override` mode re-registers `grep`/`find` as *extension* tools; pi-subagents ≥ 0.67.0 intersects a
  child's declared tools with the host's `sourceInfo.source === "builtin"` tools and reads that as
  "host lacks grep/find" — reviewer/scout lanes fail closed at launch (`pi/subagents.md`). perk
  injects `PI_FFF_MODE=tools-and-ui` at both launch seams (`launch.FFF_MODE_ENV`,
  `workflow/cold-door-launch.md`): additive — the builtins stay beside `fffind`/`ffgrep`, and
  `toolGating.ts::FFF_SEARCH_TOOLS` already enumerates both name-sets. Doctor's
  `subagent-host-tools` row reports the operator-owned remainder (`workflow/init-doctor.md`).

## Residuals

- *(Dated history.)* While the SDK in-process child existed, its strict `SDK_READ_ONLY_TOOLS`
  allowlist was never widened for borrowed tools; the child and the list were deleted with the
  stage-execution confinement (PR #2100), so the rule's live scope is now empty. The conclusion
  stands: widening an SDK child's tool list for borrowed tools would have been — and for any
  future SDK child would be — an **explicit decision, not drift** (spawned pi-subagents children
  already inherit the tools via `.pi/settings.json`).
- Most string-entry packages cannot filter skills. The Ponytail object is the narrow exception;
  future filtered borrows require an explicit convergence and health-equivalence decision.
- npm installation remains lazy and the running Pi session must restart before a newly converged
  package is available. Until then, `ponytail` can report honestly uncovered; this composes with the
  linked-worktree install facts in `toolchain/worktree-node-modules.md`.
- Empty resource filters are a loading boundary, not a security boundary.
- Wave bookkeeping is authoritative: `last_pr_review` records attempted and covered arrays. Any
  future wave-recording door must provide both instead of reconstructing one from the other.

## Cross-references

- `src/perk/convergence/init/settings.py` — `BORROWED_PACKAGES`
- `src/perk/convergence/capabilities.py` — the `borrowed-packages` capability summary
- `docs/learned/workflow/provider-seam.md` — the seam this recipe is *not*; also `package_filter`
- `docs/learned/pi/context-system.md` — the read-only mode whose allowlist this touches
- `docs/learned/workflow/warm-door-commands.md` — the drive-coverage guard over the stage-scoped
  universe
- `docs/learned/pi/tui-surfaces.md` — the perk-owned footer the setFooter rule protects
- `extension/substrate/toolGating.ts` — `admitLate` + the `resources_discover` re-apply; `FFF_SEARCH_TOOLS`
- `docs/learned/pi/subagents.md` — the 0.67.0 host-builtin intersection anchor
- `docs/learned/workflow/cold-door-launch.md` — `FFF_MODE_ENV` at both launch seams
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the native `worktree` refusal
