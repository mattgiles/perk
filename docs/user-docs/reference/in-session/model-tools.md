---
title: "Model-facing tools"
description: "The guarded census of perk-owned tools, the provenance posture table for foreign tools, and the gating and stage-scoping rules."
sidebar:
  order: 3024
---

# Model-facing tools

A model tool is a typed operation the agent can call. Tool registration is distinct from command
registration and from stage-door availability. The marked tables below are guarded against the
live extension authorities.

## Perk-owned tools

These tools are registered by perk itself. Command-specific semantics live in
[Workflow commands](./workflow-commands.md) and
[Review and authoring](./review-and-authoring.md).

<!-- BEGIN perk tool census -->
| Family | Tool | Kind | Under the gate |
| --- | --- | --- | --- |
| Plan authoring | `plan_review` | terminal | allowed, mode-over-stage |
| Plan authoring | `plan_save` | terminal | blocked |
| Plan authoring | `plan_draft` | action | carve-out, mode-over-stage |
| Objective authoring | `objective_save` | terminal | blocked |
| Objective workflow | `objective_node` | action | carve-out |
| Objective workflow | `reconcile_objective` | action | blocked |
| Objective workflow | `add_objective_node` | action | blocked |
| Objective authoring | `objective_draft` | action | carve-out |
| Gist authoring | `gist_draft` | action | carve-out |
| Gist authoring | `gist_save` | terminal | blocked |
| Refinement authoring | `objective_refinement_draft` | action | carve-out |
| Learn lifecycle | `learn` | terminal | blocked |
| Learn lifecycle | `run_learn_wave` | orchestration | blocked |
| Developer analysis | `run_audit_wave` | orchestration | carve-out |
| Learn factories | `run_harvest_wave` | orchestration | allowed |
| Learn factories | `run_dream_wave` | orchestration | carve-out |
| PR lifecycle | `land` | terminal | blocked |
| Automated review | `post_pr_review` | action | blocked |
| PR lifecycle | `ready` | terminal | blocked |
| Address loop | `classify_review_feedback` | orchestration | blocked |
| Address loop | `finalize_address` | terminal | blocked |
| Objective workflow | `explore_objective_node` | orchestration | allowed |
| Read-only investigation | `run_scout_wave` | orchestration | allowed |
| Library | `run_librarian` | orchestration | carve-out |
| Automated review | `run_pr_review_wave` | orchestration | blocked |
| Human PR review | `submit_pr_review` | action | blocked |
| Human PR review | `start_review_wave` | orchestration | blocked |
| Human PR review | `collect_review_wave` | action | blocked |
| Browser review | `push_annotations` | action | allowed, mode-over-stage |
| Human PR review | `open_stack_review` | interactive | blocked |
| Draft review | `start_draft_review_wave` | orchestration | allowed, mode-over-stage |
| Draft review | `collect_draft_review_wave` | action | allowed, mode-over-stage |
| Verification | `run_ci` | action | blocked |
| PR lifecycle | `submit` | terminal | blocked |
| PR lifecycle | `resolve_submit_conflicts` | orchestration | blocked |
| Stacked delivery | `objective_stack_status` | query | blocked |
| Stacked delivery | `objective_stack_sync` | orchestration | blocked |
| Stacked delivery | `objective_stack_adopt` | action | blocked |
| Stacked delivery | `objective_stack_recover` | action | blocked |
| Stacked delivery | `objective_stack_land` | action | blocked |
| Loadout host | `perk_stage` | host | allowed, mode-over-stage |
<!-- END perk tool census -->

The terminating subset ends the current turn on its success path: `plan_save`, `objective_save`,
`gist_save`, `submit`, `ready`, `finalize_address` on full success, `land`, `learn`, and
`plan_review` when approval completes its save — exactly the tools of kind `terminal`, all
model-only. Other perk-owned tools are non-terminating.

`perk_stage` is the **loadout host**: a tool with no action, active in every session where it is
registered and never shown to the model. It exists to hide, before each model request, every
declared tool that is not eligible in the session's stage and mode (below). It only hides
declarations; it never rewrites another tool's description.

`resolve_submit_conflicts` consumes one unused, verified submit/address conflict authorization.
It is sequential and non-terminating: only a `resolved` result permits the parent to call canonical
`submit` again. Direct/repeated/stale/read-only calls refuse. Failed or withheld resolution does
not rewrite a successful publication or make worker completion eligible. Lock contention consumes
no additional attempt and never retries; uncertain native termination retains the worktree lock
for [human-only recovery](../../how-to/recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock).
No unlock tool exists. Resolver summaries are untrusted DATA; output-free receipts diagnose
ownership, not verification or publication authority.

`objective_stack_sync` directly awaits the same native resolver for eligible mutating sync/continue
conflicts and explicit `resolve:true`. Explicit resolve does only the corroborating status cold
call, returns typed `resolution` details after an attempt, and is ok only for `continuation-ready`.
That result permits offering continuation, not executing it: a new explicit human approval precedes
a separate `continue:true` call. All other outcomes withhold; automatic handling preserves the
original cold `rebase_conflict` result and delivers the resolver disposition separately. Adopt,
dry-run and abort never launch a resolver.

A post-result delivery failure appends one **delivery-unconfirmed** diagnostic text block without
changing details, first content or termination semantics. It includes the safe disposition/receipt
and any bounded report as untrusted JSON. Stop for human direction; no automatic retry, continue
or unlock. The retained-operation session claim persists across child outcomes and cannot bypass
the separate retained-worktree `perk-submit-conflict.lock` execution exclusion.

`run_librarian` dispatches the `perk.librarian` writer child — foreground, fresh context, in the
repository's main checkout — to add a documentation mirror to the perk library
(`{action: "add-docs", url, slug?, scope_prefix?}`) or re-crawl an existing one
(`{action: "refresh-docs", slug}`). It is sequential and non-terminating, one attempt per call with
no retry, and a second call while one runs is refused (`busy`). The calling session stays as it is
— the tool is reachable while read-only — because only the child writes, and only under the
gitignored `docs/library/`. The child is bracketed by a fail-closed check on the main checkout.
Before anything runs, HEAD must resolve, the tracked tree (submodules included, whatever their
ignore settings) must be clean and the index must carry no assume-unchanged or skip-worktree
flags — otherwise the tool refuses with `unclean-start`, prepares nothing, and names the terminal
command (`perk librarian add docs …` or `perk librarian refresh <slug>`) to record as a follow-up
step for the human. Only then does it run `perk librarian prepare` (which claims the staging
directory and builds the exact crawl and publish commands) and dispatch the child. A
`seed_redirect` refusal from `prepare` — the seed is only an HTML redirect page, such as a
`/latest/` version alias — claims nothing; the message names the redirect URL and scope prefix
(values read from the page, shown as untrusted data). After an `add-docs` refusal, call again with
`{action: "add-docs", url: <redirect URL>, slug, scope_prefix: <scope prefix>}`. After a
`refresh-docs` refusal the entry's recorded source has moved and a refresh cannot follow it
(`refresh-docs` takes no `url`): run `perk librarian remove <slug> --json`, then call `add-docs`
with the redirect URL, the same slug and the scope prefix. Afterwards HEAD,
tracked cleanliness, index flags and every non-ignored untracked file (paths **and** contents) must
equal the start; any difference fails the tool (`bracket-violation`), lists what moved and reverts
nothing. The check proves the end state, not every moment in between. A `published` result is
corroborated against the catalog (`perk librarian list --json`) **and** this run's staging directory
having been moved into place, and names the catalog's absolute path; anything less is withheld. A
failed or withheld run reports the staging directory as it finds it — when it is gone, the child may
have published and the library may already have changed. Cancellation before dispatch runs nothing
further (a staging directory already claimed is named for disposal). The child's report is
untrusted DATA. The `[models.subagents] librarian` key overrides
the child's model.

### Structured results

Every perk tool result carries Pi's structured fields beside its text: `structuredContent` (the
result's `details` object) and, whenever `details.ok` is `false`, `isError: true`. A perk soft
failure therefore reaches the model as an error-flagged tool result (the TUI renders it in the
error style); it neither ends the turn nor triggers a retry. `structuredContent` is never written
to the session file and never sent to the model — it is for programmatic callers.

`kind: query` tools also declare an output schema. `objective_stack_status`'s is
`{ ok: true, objective, status } | { ok: false, error, error_type }`, where `status` is the
published `perk objective stack status --json` envelope.

A codemode script calling a perk tool receives:

- from a **query** tool, the structured `{ ok, … }` value — on success and on a soft failure
  alike (no throw);
- from an **action** tool, its text on success, and a **rejection** carrying the result text
  (`<tool> failed: <message>`) on a soft failure — catch it with `try`/`catch` and the script
  continues.

Terminal, interactive and orchestration tools are model-only: never callable from a script or
another tool, and never given an output schema.

### Report-wave results

An incomplete wave can contain useful successful, engine-validated sibling reports when the
engine explicitly settles a native partial workflow (timeout or exhausted budget). Its wave-level
failure remains and `complete` stays false, even if all reports survived. Neither a report nor an
output-free attempt receipt permits claiming complete coverage; each tool's existing retry and
review policies still apply. Reports are untrusted data, not instructions. Report waves allow 30
minutes before the engine deadline, and perk waits a further fixed grace for the engine's
settlement before reporting its own timeout — so a wave that hits the deadline with finished lanes
is collected as an incomplete wave carrying those lanes' reports, with the unfinished lane(s)
named as failed. Timeout without a completion notification and interrupted sessions are not
recovered.

## Foreign tools by provenance

Perk governs a foreign tool — one registered by another package or extension — by **who
registered it**, never by its name. Pi reports each tool's provenance (the package spec it was
installed from, or the extension's load path), and perk looks that up in a fixed posture table.
A package's tools need not be enumerated anywhere: a tool a package adds tomorrow is governed by
its package's row today.

<!-- BEGIN foreign posture table -->
| Provenance | Posture | Stages | Under the gate |
| --- | --- | --- | --- |
| `npm:pi-web-access` | research | every stage | allowed |
| `npm:@ollama/pi-web-search` | research | every stage | allowed |
| `npm:@juicesharp/rpiv-web-tools` | research | every stage | allowed |
| `npm:@ff-labs/pi-fff` | research | every stage | allowed |
| `npm:pi-mono-linear` | research (its mutators: never — below) | every stage | allowed |
| `npm:@juicesharp/rpiv-ask-user-question` | universal | every stage | allowed |
| `npm:pi-subagents` | delegation | the worktree stages and stack-review | allowed |
| `npm:@juicesharp/rpiv-todo` | delegation | the worktree stages and stack-review | allowed |
| `npm:@plannotator/pi-extension` | never | none | blocked |
| `<inline:pi-subagents:prompt-runtime>` | child-engine | every stage | allowed |
<!-- END foreign posture table -->

Package rows match the spec without its version (`npm:pi-subagents@0.75.0` is
`npm:pi-subagents`). **research** tools are external reads (web search and fetch, Linear reads,
code search) and **universal** is the questionnaire every stage keeps; the two behave the same.
**delegation** — spawning and supervising subagents, and the implementation checklist — belongs to
the worktree flow. **never** tools are hidden in every stage session and blocked under the gate:
perk bridges plan review to Plannotator's event API and never drives its plan phases. The one
in-package exception is Linear's writers, which are `never` (Linear mutations stay in perk's
Python plane; `linear_configure_auth` writes your Pi auth file):

<!-- BEGIN linear exception -->
| Tool |
| --- |
| `linear_create_issue` |
| `linear_update_issue` |
| `linear_create_comment` |
| `linear_upload_file` |
| `linear_upload_file_to_issue_comment` |
| `linear_configure_auth` |
<!-- END linear exception -->

**Unknown provenance.** A tool from any package or extension without a row — an MCP bridge, an
ad-hoc extension, a package perk does not install — passes every stage diet but is hidden and
blocked under the read-only gate. Only the exact paths in the table count: another
`<inline:…>` extension is unknown.

**perk never deactivates a foreign tool.** A package's own choices stand: the questionnaire
removes `ask_user_question` in a headless session, pi-subagents hides `subagent` until the model
calls `subagents_enable` (and restores that selection when you navigate the session tree), and
perk neither re-enables nor drops either. Where a foreign tool is ineligible, perk only **hides**
it from the model (below). Pi's `--tools`/`--exclude-tools` remove tools from the session
altogether: an excluded perk tool is never activated and is refused if called under the gate;
excluding `perk_stage` turns off the hiding (perk still deactivates its own ineligible tools, and
the read-only gate still blocks). Any other removal of an eligible perk tool — another
extension's `setActiveTools` — is undone at perk's next reconciliation.

For package selection, registration timing, and provider fallback behavior, use the
[Providers reference](../providers-and-backends/providers.md).

## Spawned-child tools

pi-subagents registers its engine tools — `structured_output` (schema-validated completion),
`contact_supervisor` (child-to-parent coordination) and `wait` — inside every spawned child through
its prompt runtime, the `<inline:pi-subagents:prompt-runtime>` row above. They are allowed in every
stage and under an inherited read-only gate, so a gated child can always complete its report.
perk's own waves spawn with the pi-subagents intercom bridge off, so their children never have
`contact_supervisor` (review waves are completion-only). perk's report children run with a tool
allowlist (`read`, `grep`, `find`, `ls`, `bash`), so no perk tool exists in them at all.

## Gating and stage scoping

Every perk tool registers with a **policy descriptor** — the stages it belongs to, its posture under
the read-only gate (`allowed`, `blocked`, or a named carve-out — one bounded write), whether a mode
gesture needs it regardless of stage, and its kind (`terminal`, `interactive`, `orchestration`,
`query`, `action`, or `host` for `perk_stage`). Each tool's Kind and Under-the-gate posture appear in the census above.
Everything perk installs is derived from those descriptors through one **eligibility formula**: a
tool is eligible in a session when its stage is one of the tool's stages and the mode allows it
(read-write always does; read-only does unless the tool is gate-blocked), or when the session is
read-only and the tool is **mode-over-stage**. A session with no stage (or an unknown one) is
eligible for every tool the mode allows. Foreign tools get the same treatment through the posture
table above, and Pi's builtins through their own rows: `read`/`grep`/`find`/`ls` and `tool_search`
allowed, `bash` under the read-only verdict, `edit`/`write` and `codemode` blocked. The full
stage-by-tool result is committed as `shared/fixtures/tool-matrix.json`.

Perk applies all of this in three separate ways. **Activation:** perk switches on and off only
its own tools — at every session start and tree navigation, when the gate turns on or off, after
every extension has started, and when each new prompt starts (not between the model requests
inside one prompt) — and never activates or deactivates a foreign or builtin tool, with one
exception: under the read-only gate perk switches `codemode` off, and back on when the gate turns
off. **Presentation:** before every model request, `perk_stage` hides every ineligible tool's
declaration (and its prompt-snippet line) from the model; a hidden tool stays active and
callable.
**Enforcement:** under the read-only gate the tool-call check below blocks every ineligible call,
whatever the model was shown.

The mode-over-stage tools are exactly the `/plan` toggle's flow — `plan_draft`, `plan_review`, and
the reviewer-wave companions `start_draft_review_wave`, `collect_draft_review_wave` and
`push_annotations` — so toggling `/plan` in any session (a worktree session included) leaves the
whole draft → review → reviewer-wave flow reachable.

Terminal, interactive and orchestration tools are declared to the model as **model-only**: Pi never
lets another tool (for example a `codemode` script) call them through `ctx.executeTool()`, so no
nested call can end the turn or open a human surface.

### Structural read-only gate

Effective read-only gating is the existing workflow mode **or** a captured runner restriction
floor. Perk activates the stage's own tools that are eligible read-only there and hides every
other ineligible declaration: `edit` and `write` stay active but are not declared to the model
(their prompt-snippet lines disappear too, and return when the gate turns off), and so are
`never` and unknown-provenance foreign tools. `codemode` is switched off while the gate is on and
back on when it turns off: its description would list the write tools' schemas, and in `only`
mode it hides every direct tool itself, so a hidden-but-active codemode would leave the session
without `read`, `bash` or perk's tools. Each stage therefore sees its own tools: an `objective-refine`
session, for instance, gets read/research/question, `plan_review`, `objective_refinement_draft`
and the mode-over-stage set — no node claim, no objective or gist draft, no save tool, no
delegation. Because the `/plan` flow's tools are mode-over-stage, `plan_draft` is reachable there
too and can write a plan draft, but that draft can never be reviewed or saved from a refinement
session (`plan_review` reviews only the refinement draft, and every save command refuses). The
hidden guidance names the stage's sanctioned bounded writers (its carve-out tools) under a
`[READ-ONLY MODE] (stage <id>)` marker, or `[READ-ONLY MODE] (unscoped)` in a session with no
stage. Independently of what was shown, every call is checked: a tool not registered in the
session is refused (`perk read-only mode: <name> is blocked (tool not registered).`), and every
ineligible tool is denied, including `edit`, `write`, save/delivery tools, `codemode` and unknown
or late-registered foreign mutators — even if activation or presentation failed. Allowlisted `bash` retains a textual command-position sub-allowlist. It first applies the
whole-command destructive veto, then walks every command position — after sequencing operators and
newlines, inside substitutions, after shell keywords/redirections/wrappers, and at `find -exec`/
`fd -x` — then matches every emitted command against `SAFE_PATTERNS` in
`extension/substrate/readOnlyBash.ts` (the inventory). A refusal names its reason beneath the echoed
command. Heredoc data remains data while substitutions in an expanding heredoc are commands.

The walker distinguishes three kinds of position. A shell position may parse assignment prefixes
and keywords; `env` parses environment entries; `timeout`/`nice`/`nohup`/`xargs`/`command`, an
external `time`, and `find`/`fd` exec forms take a literal program word. A submitted shell prefix or
`env` entry may be only plain, byte-exact `LC_ALL=C` or `GIT_OPTIONAL_LOCKS=0`. Generic prefixes
such as `X=1 grep`, quoted/expanded variants, and `env X=1 grep` are refused. At an external
position even `LC_ALL=C` is a program name and is refused; a later `env` can intentionally switch
back (`timeout 5 env LC_ALL=C sort`).

Standalone scratch assignments and ordinary loops still work, but cannot assign exec-bearing
names. This reserves `GIT_*` (apart from exact `GIT_OPTIONAL_LOCKS=0`), `LD_*`, `DYLD_*`,
`LESS*`, `BAT_*`, `PYTHON*`, `PERL*`, `XDG_*`, and known path/pager/editor/shell-startup names
including `PATH`, `HOME`, `PAGER`, `NODE_OPTIONS`, `RIPGREP_CONFIG_PATH`, `BASH_ENV`, `PS4`,
`SSH_ASKPASS`, `AWKPATH` and `AWKLIBPATH`. The same check applies to a `for` iterator: `for f …`
is allowed; `for PATH …` is not. Names assigned dynamically through `read` and inherited
environment are outside this submitted-text check.

At the first shell position of a pipeline, before any assignment/redirection, `time [-p]` is Bash's
keyword and may precede a safe shell prefix (`time LC_ALL=C sort`). After an earlier assignment,
`env`/another wrapper, `!`, or a pipe, `time` is the external program, so `env time LC_ALL=C sort`
and `echo x | time LC_ALL=C sort` are refused. Unknown distinctions fail closed. Command and
subcommand rows also require a complete token: `git show --stat`, `git diff>/dev/null` and an `rg`
continued onto a `--glob` word pass; `git show-x`, `show-branch`, `rg=payload`, `rg-extra` and `gh
pr view-x` do not.

Argument-level writers remain vetoed. Exec-bearing selector options are also refused within their
command: `rg --pre|--hostname-bin`, `sort --compress-program` (`--comp…` abbreviations), `bat
--pager`, dangerous leading less/more `+cmd`/`++cmd` commands, less `--cmd`/`-k`/`--lesskey-*`,
and `more -p`. Git helper switches are refused on the admitted reads that accept them:
`--ext-diff`/`--textconv` for diff/log/show/range-diff/reflog/stash/shortlog, `git grep
--textconv`, `git cat-file --textconv|--filters`, and `git hash-object
--path|--filters|--stdin-paths`. Neighboring read flags (`rg --pre-glob`, `less +G`, `less -p`,
`--no-ext-diff`, `--no-textconv`, `--no-filters`) remain available.

This is a structural text check, not a shell, environment, repository-config, interactive-input or
process sandbox. It does not prove inherited variables safe, see names assigned dynamically,
suppress Git helpers selected implicitly by existing config/attributes, or inspect argv appended at
run time by `xargs`/`find`/`fd`. Program text inside admitted tools, unusual/expanded exec-flag
spellings, internal flag quoting and unhandled option abbreviations remain limits. Other listed
tools still undergo their ordinary authority checks; artifact/review/research/delegation carve-outs
do not become OS-sandboxed or argument-level certified.

**Guidance lifetime versus the structural gate.** While the gate is on, perk also injects a hidden
`[READ-ONLY MODE]` guidance message once per session-tree branch: the whole branch history decides,
so a copy that compaction has summarized out of the model's context is not re-injected, while a
branch that never carried it receives one. That is deliberate — the guidance is advisory prose, and
the tool-call gate above enforces regardless of whether the model can still read it. The other
hidden guidance perk injects (authoring and provider contexts, stage bindings, agent scratch) has
the opposite lifetime: it is re-delivered whenever Pi's own context projection no longer carries
it, because those messages exist to be read, not to enforce.

The bash gate admits these exact whitespace-separated review-context query forms (optional
surrounding whitespace, N matching `[1-9][0-9]*`, `--json` last): the plan-bound
`perk pr review-context --expected-pr N --json`, the human-triage doors' foreign
`perk pr review-context --pr N --json` and `perk pr review-context --pr N --stack --json`, the
stack review flow's pinned `perk pr review-context --pr N --stack --pin-base <sha> --pin-head
<pr>=<sha> … --json` (full 40-hex lowercase SHAs, at least two bottom→top `--pin-head` pairs —
exactly what the stack door renders), and `perk pr feedback --json`. `cd … && query` works because
every command position is checked. This does not admit the flagless context form, other argument orders,
extra arguments, lookalike verbs, `review-post`, `gh api`, real-file redirects, or a mutation
chained after a query.

The gate also admits the perk library workers in their `--json` forms: `perk librarian list …
--json`, `perk librarian record … --json`, `perk librarian remove … --json`,
`perk librarian add source … --json`, `perk librarian check … --json`, and
`perk librarian refresh … --json`, with `--json` last and any whitespace-separated arguments
before it — none of which may start a comment (`#`) or contain a redirection (`<` or `>`), so the
final `--json` is always a real argument. They write only the gitignored `docs/library/` cache: the CLI itself refuses unless
its representative ignore probes (the catalog, the lock file, and each directory the operation
changes) pass and nothing under the library is tracked. The probes run before the lock is taken,
except the probes of `remove`'s entry directory and `refresh`'s checkout, which need the catalog
(see [Librarian commands](../cli/librarian.md)). The network verbs (`add source`, `check`,
`refresh`) run their git operations without global or system git config and with hooks
disabled, so nothing a cloned repository's content or that config selects can execute (git
config from environment variables and a checkout's own repository-local config stay trusted —
see [Librarian commands](../cli/librarian.md)). A form without `--json` or with
`--json` not last, `perk librarian add docs`, other `perk librarian` verbs, real-file redirects
and chained mutations stay blocked.

Perk-owned report waves deliver the constant `perk.parent-restrictions/1 = {readOnly: true}`
packet and `worktree: false` to every native runner child. The packet — or a malformed /
unsupported-version one — establishes a read-only floor before lifecycle work that gate exit, later
input or tree navigation cannot clear; failed mode persistence is loud and leaves the floor active.
No packet is never a write grant. `structured_output` and `contact_supervisor` stay allowlisted;
`/btw` mirrors the gate. Manual launches and foreground children are outside this channel.

### Stage tool diet

With the gate off and a known stage active, perk activates the stage's **diet** — its own tools
eligible read-write there — and hides foreign tools whose posture excludes the stage. Each stage
receives its own authoring/lifecycle tools plus the research family. The five worktree stages —
implement, submit, address, land, and learn — share the whole PR-loop family so a later warm
command cannot dead-end in an earlier worktree session. That shared family includes submission,
readiness, CI, review/address, land/learn, reconciliation, and stack-control operations, plus
delegation and the checklist.

The diet is presentation for foreign tools: a `subagent` the model enabled in a `plan` session
stays active but is not declared to the model, and a late-registering tool (the delegation
supervisor) is shown or hidden by its posture the moment it appears. In a discovery-cohort session (below), a deferred perk tool that
`tool_search` activates stays while it is eligible; where it is not, it is hidden from the very
next request and switched off when the next prompt starts (until then it stays callable — the
read-write diet has no call-time check). Pi restores such activations only when you navigate
the session tree, not on resume or fork; perk keeps what Pi restored and adds nothing.

On Pi 1.0, tools Pi restores after `/reload` or tree navigation survive perk's reconciliation —
for example an MCP server's tools that reconnect before your next prompt. Until that prompt starts,
perk only adds tools; anything it would switch off (a tool the new stage or mode does not allow,
the deferred discovery tools, a suspended `codemode`) waits for the next prompt. Meanwhile that
tool is not declared to the model and, in read-only mode, is blocked; its usage notes can still
appear in the system prompt of that one prompt.

One composition limit: `codemode` writes its own description from every callable tool, so in a
read-write stage session with codemode active, that description may name a tool the diet hides.
This affects only what the model reads; under the gate codemode is switched off.

### Native tool discovery (default)

Perk turns on Pi's native tool discovery for a repo's interactive sessions with one entry in its
tracked `.pi/settings.json`:

```json
"defaultTools": ["+tool_search"]
```

`perk init` writes it. It only ever appends to an existing `defaultTools` list; it never reorders
or removes your entries. A list with no string entries (such as `[]`, which on its own means "no
builtin tools") or a value that is not a list is left alone; if you want discovery on an empty
selection, write `["tool_search"]` yourself. Leaving an empty list alone only stops perk from
seeding it — it is not an opt-out: Pi adds an empty project list onto your user-scope list, so a
user-scope `+tool_search` still turns discovery on. `perk doctor` reports a missing entry as
`settings-wiring` drift and `perk doctor --fix` appends it. **A new entry applies at the next launch
or `/reload`.**

To opt out, commit `"-tool_search"` in the repo's tracked `.pi/settings.json` (for example
`"defaultTools": ["-tool_search"]`). It must be the project file: Pi applies project entries after
user-scope ones, so a `-tool_search` in your user `~/.pi/agent/settings.json` is overridden by the
project entry. **Opting out applies at the next launch only** — `/reload` keeps `tool_search`
active, and the session re-joins. One layering consequence: if your user settings carry an
explicit `"defaultTools": []` and the repo has no entry of its own, the seeded project entry
resolves to Pi's four default tools plus `tool_search`; commit a project `[]` to keep that repo's
empty selection.

A session whose Pi has its builtin `tool_search` registered **and** active at startup joins
the **discovery cohort**: perk re-registers four optional, schema-heavy tools as deferred and
switches them off once — `objective_stack_status`, `collect_review_wave`,
`collect_draft_review_wave` and `push_annotations`. Their schemas, snippets and guidelines leave
every request until something activates them; `tool_search` itself is declared instead.

They come back in two ways:

- **Primed activation.** The door or launcher whose guidance names a deferred tool activates it
  before that guidance reaches the model: `/pr-review-browser`, `/stack-review-browser` and
  `open_stack_review` (the review-wave collector and `push_annotations`); `/pr-review-terminal`
  with a PR (the collector); `/plan-review-browser`, `/objective-review-browser` and the
  draft-review chooser's wave arms (the draft collector and `push_annotations`);
  `/objective-sync` and `/objective-land` (`objective_stack_status`); and a successful
  `start_review_wave` / `start_draft_review_wave` (its collector). A failed launch activates
  nothing.
- **Search.** The model can find any of them with `tool_search`; the match is declared from the
  next model call.

An activated tool stays only while the stage and mode allow it, exactly like any perk tool.
Resume and fork start without it (re-run the door or search again); `/reload` deactivates the
four again when your next prompt starts; navigating the session tree restores whatever the transcript had and perk keeps it.
`/perk-selfcheck` reports `discovery: cohort (family: …)` or `discovery: nonparticipant`.

Who never participates: a session of a repo that opted out with `-tool_search` (or whose resolved
selection is empty), a session whose `tool_search` comes from some other extension, the headless worker, `/btw`'s side
session and spawned subagent children — they keep every perk tool declared as before. The pilot's measurements and its adopt/retire decision are
recorded in `docs/design/native-discovery-pilot.md`.

Pi owns its builtins (`read`, `edit`, `write`, `bash`, `grep`, `find`, and related host tools); this
reference does not redefine them. Stage scoping is fail-open at compatibility boundaries: a bare
session (perk changes nothing there — only `perk_stage` is hidden), an unknown stage id, and an
unknown-provenance tool are not filtered. Read-only mode is the opposite safety posture for
worktree mutation: its tool-call backstop fails closed on internal errors.

## Bash scan timeout

Perk caps **gitignore-blind scans** issued through Pi's `bash` tool at a **30-second default
`timeout`**. Recursive `grep -r…` and `find` without `-maxdepth` ignore `.gitignore`, so from a
checkout that carries `node_modules/`, `.venv/` or `.worktrees/` they walk everything and can run for
minutes to the better part of an hour; legitimately scoped searches finish in seconds.

A `bash` call is capped when it carries **no** `timeout` and its command is a recursive grep or an
unbounded find — in any pipeline stage, on any line of a multi-line command, and behind wrapper
prefixes or nested shells. Examples of capped commands:

- `grep -rn "foo" .` (any short cluster containing `r`/`R` — `-rniE`, `-Rl`, `-nr` — or
  `--recursive`, `--directories=recurse`, `rgrep`)
- `find . -name '*.py'` (no `-maxdepth`; `-prune` and `-not -path` do **not** exempt it)
- `cd repo && LC_ALL=C grep -rn foo . | head`
- `sh -c 'grep -rn foo .'`, `sh -c 'find . -type f; find . -maxdepth 1'` (each `find` needs its
  own `-maxdepth`)

Not capped: `grep -n foo file`, `find . -maxdepth 2 …`, `rg`, `fd`, `ast-grep`, and a `-r` that
belongs to a later pipeline stage (`grep -n foo f | sort -r`).

**The explicit `timeout` on the call is the override.** Any value the model passes — larger or
smaller — is honored as-is and never rewritten. When a capped (or explicitly timed) scan expires,
Pi's partial output is kept and perk appends a short note to the result naming the kind of scan,
the timeout it hit, the gitignore-aware alternatives (the `grep`/`find` tools, `rg`/`fd`) and the
explicit-`timeout` override. Successful scans get no note.

The cap applies in **every** perk session — read-only or read-write, any stage or none, spawned
subagent children included — and never blocks a call: it is a performance guard, so an internal
error is reported and the call proceeds unmodified (the opposite of the read-only gate's
fail-closed posture). A few fast commands are deliberately over-capped because they look like
scans (`git grep -r…`, `echo grep -r`); the 30s cap is harmless for them. The value is **not
configurable**; it is the extension's `SCAN_TIMEOUT_SECONDS` constant, mirrored in the managed
`AGENTS.md` block that `perk init` writes — the ambient steer every perk session reads, which now
routes literal text search to the `grep`/`find` tools or `rg`/`fd` and names the cap.

## Related

- **Look up:** [Stages and doors](./stages-and-doors.mdx) — see which stage/door posture activates
  these rules.
- **Look up:** [Review and authoring](./review-and-authoring.md) — follow the review-tool lifecycles.
- **Look up:** [In-session commands & tools](../in-session.md) — return to the complete surface map.
