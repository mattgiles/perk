---
title: The read-only bash gate — command-position walker, veto view, allowlist/veto row craft, the bypass-class checklist
read_when: You are extending SAFE_PATTERNS or a veto row, admitting a networked or write-capable CLI worker, changing commandPositions.ts, debugging a blocked read-only bash call, or probing for bypasses.
cluster: pi-extension
---

# The read-only bash gate

## Distillation

- Two layers, two files: a whole-string destructive veto over the walker's **veto view**, then
  `SAFE_PATTERNS` at **every command position**; destructive wins. The inventory is `SAFE_PATTERNS`
  in `readOnlyBash.ts` — never mirror it into prose — "Orientation — two layers, two files".
- Lexing is separate from policy: refusals ride on tree nodes, so the fail-closed gate and the
  fail-open scan-timeout classifier share one lexer — "Lexing is separate from policy".
- The same word means different things at shell / env / external positions; refuse an unmodeled
  distinction, and check grammar claims against the oldest bash (3.2) — "Command-position
  provenance".
- The environment can launch programs: prefixes/`env` entries are allowlisted pairs, standalone/`for`
  assignments a reserved-name denylist; audit every admitted reader's program-selector options —
  "The environment can launch programs".
- Veto rows read a lexer-built normalized view, never raw text patched with span edits; never carve
  out a whole expanding heredoc body — "The veto view".
- Enumerate verbs; one veto per writer/exec flag; argument-sensitive Git commands pass `$`-anchored
  list-form or display-only rows; command-keyed rows use `keyed()`/`TOKEN_END`, never `\b` —
  "Allowlist policy"; paired rows share separators, and free words in anchored-suffix rows refuse
  comment/redirection tokens — "Cross-row regex rules".
- The bypass classes are the checklist for any shell-model change — "The bypass-class checklist".
- Record shapes a model would not reach by accident; pin every leniency as an allowed test; a gate's
  contract and user docs name its limits — "Leniency vs fix".
- Replay verdicts to estimate yield, verify tool behavior empirically, budget an adversarial PR-review
  lane — "Planning lessons for gate nodes".
- A gate change moves the whole lockstep list (production, tests, §8.3, `model-tools.md`, this doc,
  `CONTEXT.md`, the two source comments, quoting design docs) — "The lockstep list".
- A def-taught shell recipe needs a gate-admissibility test AND a byte-semantics test — "A
  def-taught shell recipe needs two tests".
- The Python audit copy is three nodes behind (#2579) — "Residuals and census follow-ups"; the
  PR-by-PR evolution is "History (dated by PR)".

## Orientation — two layers, two files

The gate decides whether a `bash` call may run in a read-only (`mode: read-only`) session:

1. a **whole-string destructive veto** over the walker's **veto view** (`vetoText`, see "The veto
   view"), then
2. `SAFE_PATTERNS` applied at **every command position** — every entry of `commandPositions()`'s
   `commands` must match a row.

**Destructive wins**: a safe prefix never rescues a veto match (`git status && rm file` is blocked).

- `extension/substrate/commandPositions.ts` — the pure lexer + dispatcher. The provenance comment at
  its head is the "what" carrier for command positions, their provenance and the walker's accepted
  limits; `REFUSAL_REASONS` holds one human-readable line per refusal.
- `extension/substrate/readOnlyBash.ts` — `readOnlyBashVerdict`, `SAFE_PATTERNS`,
  `DESTRUCTIVE_PATTERNS`, the row builders `git()`/`keyed()`/`listForm()`/`veto()`, the regex
  vocabulary (each constant with its own explanatory comment) and the numbered accepted-leniency
  comment. The verdict moved here from `toolGating.ts` byte-identically (#2644), so every
  recorded leniency still holds; `toolGating.ts` only *consumes* it (it imports
  `readOnlyBashVerdict` for the `tool_call` backstop).
- The block message keeps its two-line head (the
  `perk read-only mode: command blocked (not allowlisted).` line + `Command:`) and adds a `Reason:`
  line — a `REFUSAL_REASONS` line, `matches the destructive veto <regex>`, or
  `not allowlisted: <simple-command text>`.
- Contract: `shared/contracts.md` §8.3. User-facing: `docs/user-docs/reference/in-session/model-tools.md`
  § "Structural read-only gate" ("a structural text check, not a sandbox"). Vocabulary: `CONTEXT.md`
  § "Read-only bash gate" (Command position, Simple-command text, Argument-level writer,
  Exec-bearing input, List form, Veto view).

**Never mirror the inventory into prose — it drifts.** `SAFE_PATTERNS` is the authoritative list of
what passes; the doc that used to host this material carried a snapshot that went stale.

**The `gh` allowlist is subcommand-shaped, never verb-inferred.** `gh api` stays blocked even for
GET-shaped calls — inferring GET-vs-mutation by regex is fragile — so the rows name query
*subcommands* (`view|list|diff|status|checks`, `gh search`, `gh auth status`). Extending it is a
deliberate per-subcommand act judged by what the subcommand does, not its verb shape: `gh release
download` is NOT read-only (it writes files).

**Fix the allowlist, not cold-door seed-injection.** A cold door injects only minimal context (an
objective's title + one node description), so an agent legitimately needs the read-only query to
read the rest. Plan factories still **prefer** the materialized inbox (the cold door fetches via
`gh` and writes a file before launch — deterministic and token-cheap), but since the `gh` query rows
landed the inbox is no longer structurally forced (`workflow/plan-factories.md`).

## Lexing is separate from policy — a fail-closed and a fail-open consumer share one lexer

`commandPositions.ts` runs two phases. The **lexer** knows only bash's token rules and builds a token
tree; the **dispatcher** knows only command-position rules and walks it. Lexical refusals are
attached to tree nodes and never stop the lexer, so `segments` (the scan-timeout classifier's view)
always covers the whole input — a gate refusal never truncates it. Backtick bodies and expanding
heredoc bodies are re-lexed as their own inputs, the way bash re-parses them. Pathological nesting
throws: the gate's `tool_call` try/catch fails **closed**, the classifier fails **open**
(`pi/context-system.md` § "The bash scan-timeout guard").

Every heredoc body is a classifier segment — a quoted delimiter only stops the *outer* shell from
expanding the body; `bash <<'EOF'` still runs it as a script — while the gate treats a literal body
as data. The two views differ on purpose; the harmless 30 s cap on `cat <<'EOF' … find …` is a pinned
over-match.

**Reusable pattern:** when a fail-closed and a fail-open consumer read the same text, keep lexing
separate from policy and record refusals as data on the nodes — the strict consumer acts on them,
the lenient one ignores them.

## Command-position provenance — the same word means different things

The shell / env / external position taxonomy is stated in `commandPositions.ts`'s header comment —
read it there. The rules it implies for anyone extending the walker:

- **An unmodeled distinction is refused, never guessed to be grammar.** A `for` name that is a
  keyword, `time`, or an invalid identifier is `unmodeled-syntax`.
- **A shell assignment or redirection before the command word turns reserved words into program
  names** (`X=1 if`, `>f time`) — the word is no longer at a grammar position.
- **Check shell-grammar claims against the *oldest* bash the gate meets.** macOS `/bin/bash` 3.2.57
  (Pi's default shell there) runs the **external** `time` after `if`/`elif`/`while`/`until`/`!` and
  treats `time` as its keyword only at a pipeline start and after `then`/`else`/`do`/`{`
  (`TIME_OPENERS`); the bash 5 manual alone was wrong. Where versions disagree, take the
  conservative external reading.

## The environment can launch programs — two sinks, two policies

An environment entry reaches whatever program runs next (`GIT_EXTERNAL_DIFF`, `PAGER`, `LD_PRELOAD`,
`PERL5OPT`, `PS4` under `set -x`), so:

- **Prefixes and `env` entries** use an *allowlist* of byte-exact plain pairs — `REFUSAL_REASONS`
  names the two admitted pairs.
- **Standalone and `for` assignments** use a *denylist* of reserved names (`RESERVED_NAME` — never
  copy it into a doc), because scratch variables (`EVID=$(cat x)`) are useful. They matter because
  `set -a` exports them to every later command, `for` re-assigns its variable each iteration, `PS4`
  runs under an admitted `set -x`, and Perl-script tools (`shasum`) read `PERL5OPT`.

**How to audit program-selector options.** For every admitted reader, read its `--help`/man page for
options whose *value* is a command or program — not only output/writer flags. Found this way:
`rg --pre`, `sort --compress-program`, `bat --pager`, less/more startup-command options, Git
`--ext-diff`/`--textconv` across the diff family, `cat-file`/`hash-object` `--filters`/`--path`.
Pair each veto with the nearby harmless spelling as an allowed case (`--pre-glob`, `--no-pre`,
`--no-ext-diff`).

## The veto view

A whole-string regex veto reads a **normalized view built by the same lexer**: every substitution and
`${…}` collapses to one stand-in word (word count preserved, so argument walks cross them), every
heredoc body collapses to nothing, and each substitution's own text is appended on its own line
(inner before outer) and scanned exactly like top-level text.

Why: raw-text argument walks stopped at nested or escaped operators — `find … -exec … \; -delete`
and `git hash-object $(a; b) -w` hid the writer flag behind the operator. **Rule:** never patch raw
text with ad-hoc span edits; normalize through the syntax model.

- Redirect carve-outs (fd duplication, `/dev/null`) become blanks in the view; a redirect to a real
  path stays destructive.
- **Do not carve out whole expanding heredoc bodies** — a substitution inside one runs (`$(echo x >
  f)` inside an unquoted-delimiter body writes the file). Only literal bodies are data; an expanding
  body's substitutions are appended and scanned.

## Allowlist policy — enumerate verbs, model arguments, close writes by shape

- **Subcommand-shaped rows.** Enumerate the allowed verbs (`perk objective show|next|node-engagement`
  plus the `s`/`n` aliases), never `perk objective .*`; add a block-side test for each sibling verb an alias could bleed
  into (`perk objective node 2.3 --status done`).
- **The argument-level rule.** An admitted command whose argument can turn a read into a write or
  select a program gets **one scoped veto row per writer/exec flag**, reading through a leading quote
  or escape on the flag word.
- **Argument-sensitive Git commands are admitted through `$`-anchored exact shapes of two kinds.**
  - `listForm()` rows: every word is an enumerated option (a value-taking option consumes its
    value) or a positional, and at least one list-implying option is present. "A list flag is
    present" was bypassable by negation (`git tag --list --no-list v1`), by a list flag consumed as
    another option's value (`--format --list`), and by abbreviation — and git's `--format` does NOT
    refuse outside list mode (`git tag --format -l v9` creates the tag).
  - **Bare display-only rows**: `git branch`/`git tag` with display modifiers and no positional,
    exactly one `symbolic-ref` ref, single-key `git config` reads and their `--get`/`--list` forms.
    `readOnlyBash.test.ts` pins `git branch`, `git tag`, `git symbolic-ref HEAD` and
    `git config core.hooksPath` as allowed.

  Both kinds make positional-only writes (`git branch <name>`, `git tag <name>`,
  `git config <k> <v>`, `git symbolic-ref <ref> <target>`) fail the shape, so the Reason reads
  `not allowlisted` rather than `destructive veto`. Git rows are case-sensitive (`-d`/`-D`,
  `git grep -o` is not the pager flag `-O`).
- **Interpreters are never allowlisted** (`python`, `node`, `uv run`, `sh -c`).
- **`-h` is not `--help` for perk's Click commands.** They register only `--help`; under
  `ignore_unknown_options` a `-h` reaches the command body as an ordinary argument
  (`perk skills create x -h` would scaffold).
- **Command-keyed rows go through `keyed()`/`TOKEN_END`.** `\b` never ends a command word — it
  matches before `=`, `-` and `.` — and it *was* the bypass (`rg=payload`, `rg-extra`, `git show-x`,
  and the accidental `show-branch`/`diff-tree` admissions). Every new command-keyed row gets denied
  `name=…`/`name-x`/`name.x` cases. The `ast-grep` row is `keyed("ast-grep")`.
- **The dead-arm rule.** A bare `\bword\b` veto silently kills allowlist arms: the old editor veto
  once made `gh search code` unreachable (that `code` row is now **deleted** — an editor at a command
  position is refused by the allowlist alone), and the old git veto's `tag|stash|branch -[dD]` would
  have dead-armed the new list forms, so they moved to dedicated rows. Check every new word-boundary
  veto against each `SAFE_PATTERNS` arm whose text can contain the word.
- The `agent-browser` and `curl -o` arg-blind admissions are **recorded leniencies**, not a model
  limit — several rows now inspect arguments.
- **Networked workers.** A networked CLI worker joins `SAFE_PATTERNS` only when its own CLI
  preflight confines every write to the gitignored cache; keep the exact `--json`-last grammar and
  exclude the write-capable sibling explicitly (`perk librarian add source` admitted, `add docs`
  not). Pair the admission with worker-level refusal tests — removed ignore rules, tracked library
  content, redirected roots → a typed refusal with no clone/fetch/ls-remote/HTTP, a byte-identical
  tree and no lock file — so that removing the worker's preflight turns them red.
- **Reach a mutating worker through a tool, not the gate.** `perk librarian prepare docs|refresh …
  --json` stays blocked; `run_librarian` reaches it through the extension's own exec
  (`runColdDoor`), and negative gate cases in `readOnlyBash.test.ts` pin both forms.

## Cross-row regex rules

The per-constant semantics of `SEP`, `WORD`, `INPUT_REDIRECT`, `WORDS`, `Q`, `END` and `TOKEN_END`
are documented beside each constant in `readOnlyBash.ts` — read them there. The rules that span rows:

- **Argument walks never cross a bare newline** — a walk must not read into the next command.
- **An allowlist row and its paired veto must share separator vocabulary.** The npm row accepted
  `npm \⏎audit fix` while its veto still read `\s+`; any spelling the allowlist accepts and the veto
  cannot read is a bypass.
- **Mechanical boundary tightening breaks attached-operand spellings** (`wget -O-`, `-o./x`) — list
  and pin them when converting rows.
- **State describing "the next word" must be closed by every token kind that can intervene** — a
  redirect after keyword `time` left the walker scanning `time`'s options, so `time </dev/null if ls`
  skipped `if` as grammar.
- **Anchored-suffix rows with free arguments must exclude comment-start and redirection tokens.**
  The gate matches each simple command's text, and `commandPositions` keeps trailing comments and
  redirection operands in that text although bash never passes them as arguments. A row accepting
  free words before an anchored `--json` therefore admitted `perk librarian refresh pi # --json`,
  `refresh pi #x --json`, `refresh pi <<< --json` and `refresh pi < --json`, where bash never passed
  `--json`. Harmless while every non-`--json` form was read-only; a real hole once a human `refresh`
  of a docs entry launched a write-capable session — caught in PR review, not by the plan's "no gate
  change needed" reading of the regex. The fix: each free-argument word must not start with `#` and
  must not contain `<` or `>` (a `#` inside a word, such as a URL fragment, stays admitted) — the
  librarian row in `extension/substrate/readOnlyBash.ts`, regressions in `readOnlyBash.test.ts`. The
  deeper fix (the walker drops trailing comments) was rejected: it changes pinned `commandPositions`
  behavior and leaves the redirection case open.

## The bypass-class checklist

The classes, each found live by a review of a gate change:

1. **Interior syntax leaking from an unmodeled construct** (`#` inside `${…}` read as a comment hid
   the next command) — consume an unmodeled construct as one opaque unit, or refuse it.
2. **A lexical word is not one argv element** (`env -u $PAYLOAD ls`) — every word the dispatcher
   *skips* rather than checks must be static.
3. **Run-time-supplied commands** (`… | xargs -0 env`) — after `xargs` the fallback text starts at the
   innermost `xargs`.
4. **Never fall back to the raw spelling** when a value cannot be computed (`<<$'echo'`) — refuse.
5. **A removed line continuation is not quoting** — track the two flags separately.
6. **A bare-wrapper fallback lasts until a command word opens an entry** (`env -i FOO=bar` once
   yielded zero commands).
7. **A continuation joins words, never separates them** (`git stash\⏎show` is `stashshow`).
8. **Word/option ends must look past continuations** (`git diff --ext-diff\⏎ HEAD` runs the option).
9. **Scoped argument scans cross adjacent input redirections** (`rg</dev/null --pre=cmd`).
10. **"Next word" state is closed by every intervening token kind**, not only words.
11. **An allowlist row and its paired veto share separator vocabulary.**
12. **Boundary tightening vs attached operands** — list and pin the attached spellings.
13. **The same word at different positions** — refuse the unmodeled distinction.
14. **`\b` never ends a command word** — `keyed()`/`TOKEN_END`.
15. **A previously harmless form turned write-capable** (`refresh pi # --json` once `refresh` of a
    docs entry launched a write-capable session) — re-probe adversarially against real bash argument
    semantics whenever a change makes a previously harmless command form write-capable.

**Use this list as the review checklist for any shell-model change.**

## Leniency vs fix — and pin every leniency

The inventory of accepted leniencies lives in `readOnlyBash.ts`'s numbered comment and
`commandPositions.ts`'s header — read them there. The rules:

- **Record shapes a model would not reach by accident; don't ship a fix that closes one spelling of
  a class.** Canonical example: `find . $'-exec' …` — a partial fix for escape-free `$'…'` would
  still leave `$'\x2dexec'` open, and closing the class would refuse ordinary `find "$dir"`.
- **Every recorded leniency is an allowed test case** (the "recorded leniencies stay as recorded"
  block in `readOnlyBash.test.ts`), so tightening one is a deliberate change.
- **A gate's contract and user docs must name its accepted limits** — §8.3 and `model-tools.md` list
  them; a review flagged the earlier universal-checking promise.
- Known, accepted performance notes: one quadratic regex shape (a command word repeated thousands of
  times inside one simple command) takes 160–260 ms at 20 k chars; veto Reason lines print the
  expanded regex (~400 chars for the git rows).

## Planning lessons for gate nodes

- **Estimate a carve-out's yield by replaying verdicts** over the bash tool-results in
  `~/.pi/agent/sessions/**/*.jsonl`, not by a leading-word histogram. The heredoc carve-out predicted
  ~104 cleared refusals; the replay cleared 1 — heredoc refusals are interpreter bodies.
- **Verify tool-behavior claims empirically before freezing a policy table** — a scratch git repo
  for git (`--format` outside list mode creates a tag), the same Click decorators for perk (`-h`), the
  oldest bash for grammar (`time`).
- **A plan-reviewed gate plan still yields PR-review bypasses — three nodes running**: PR review
  found 5 walker bypasses on #2546, 4 more on #2549 (after 8 at draft review) and 4 P1 + 2 P2 on
  #2558. Plan-time review cannot evaluate regexes that don't exist yet:
  budget an adversarial correctness lane at PR review, and have the implementer run probe + replay
  harnesses first (they caught three issues before review on one node).
- **Squash-merge drops commit-message evidence.** Measured evidence goes to a carrier that survives
  (`workflow/doc-reconciliation.md` § "Validation-record reconciliation", its "Sequencing around
  `/submit`" part); the three learn issues (#2547, #2550, #2572) are where the census and residual
  shapes now live.

## The lockstep list (was "five surfaces")

A gate change moves every carrier in the same turn:

- **Production** — `SAFE_PATTERNS`/`DESTRUCTIVE_PATTERNS` in `readOnlyBash.ts`; `commandPositions.ts`
  for grammar changes.
- **Tests** — the paired allowed/blocked lists in `readOnlyBash.test.ts` (including a `cd repo && <cmd>`
  case, redirect-veto cases and the pinned-leniencies block); `commandPositions.test.ts`.
- **`shared/contracts.md` §8.3** and **`docs/user-docs/reference/in-session/model-tools.md`** §
  "Structural read-only gate".
- **This doc** and **`CONTEXT.md`** § "Read-only bash gate" (the glossary).
- **The source "what" carriers** — `readOnlyBash.ts`'s numbered accepted-leniency comment and
  `commandPositions.ts`'s provenance comment.
- **Design docs that quote a gated command** — widening the reviewer children's
  `perk pr review-context` row to one anchored alternation walked the five surfaces and missed a
  sixth: `docs/design/pi-subagents-child-execution-policy.md` stated the old exact form. Grep design
  records for the old spelling.

**Mechanism-choice lesson:** perk **cannot own `grep`** — it's a Pi builtin, not a perk-registered
tool, so there is nothing to swap or remove. Steering toward structural search is therefore the
managed `AGENTS.md` bullet (ambient every session) + a bundled ambient skill + the read-only
allowlist row — no custom tool, no tool-policy/active-tools change, no default binding.

## A def-taught shell recipe needs two tests — gate admissibility AND byte semantics

Pi's own oversized-line hint — `sed -n 'Np' <path> | head -c 51200` — is **not a slicer**: it
re-exposes the same first 51,200 bytes of the line on every call. The offset-capable, gate-admitted
form the review defs teach is `sed -n 'Np' <path> | tail -c +<offset> | head -c 51200` (offsets `+1`,
`+51201`, …). A `readOnlyBash.test.ts` case pins that exact pipeline as allowed (and its
`> slice.txt` redirect as blocked), so the allowlist cannot silently drop a pipeline segment out from
under the defs. Rule: when an agent def teaches a shell recipe, test both that the gate admits it and
that it does what the prose claims byte-for-byte — a recipe that passes the gate but pages nothing
fails silently in every lane.

## Residuals and census follow-ups

- **The Python audit copy is three nodes behind** (routed, #2579).
  `packages/perk-dev/src/perk_dev/audit/gate_policy.py` still runs the per-segment model: it reports
  admitted loops, wrappers and list forms as violations, and misses shapes the TS gate refuses — its
  `env` row admits `env X=1 grep foo f`, its `\b`-ended rows admit `rg=payload`, and program-selector
  options are unmodeled. A bare `X=1 grep` is refused by both, so it is not a discriminating case.
- **Still-refused read-only shapes worth a census replay:** `perk pr review-context … --json 2>&1`;
  perk read verbs (`objective prose|roadmap|stack status`, `plan list|show`, `learn pending`,
  `doctor` without `--fix`); version/help stamps for `uv`/`npm`/`gh`/`just`/`ty`, `pi --help`,
  `git help`; `unzip -l`/`zipinfo -1`/`tar -xOf`. The largest class is quoted-`>` false positives
  (`sed 's/<[^>]*>//'`), then flag clusters such as `grep -ln`.
- **The next replay should also measure the new refusals** — generic env prefixes, `git show-branch`,
  `more -p`, `less -k`.
- The census regex's 160-char `Command:` window now runs into the `Reason:` line.

## History (dated by PR)

- **#485** — the safe check moved from the leading command to every top-level `;`/`&&`/`||`/`|`
  segment's leading word (unblocked `cd`-prefixed chains; a non-safe command anywhere became
  blocked).
- **#416** — read-only `gh` query subcommands allowlisted so the ambient "GitHub access goes through
  `gh`" guidance is followable in read-only sessions.
- **#67** — read-only `perk objective` verbs, enumerated rather than wildcarded (later widened with
  `node-engagement` for the objective-plan factory's engagement reads).
- **#617** — the command-keyed `ast-grep` row (gates the command, language-agnostic).
- **#663** — the `agent-browser` rows (and the anchored `npx agent-browser`); arg-blind output
  flags recorded as a leniency.
- **#2546** — the command-position walker (`commandPositions.ts`); loops, assignments, heredocs,
  leading redirections and wrappers pass when every command word is allowlisted; the `code` veto row
  deleted; the `Reason:` line.
- **#2549** — census-driven allowlist widening, argument-level writer vetoes, the veto view, the
  `listForm()` rows.
- **#2558** — environment and program-selector closure (`RESERVED_NAME`, the safe pairs,
  `keyed()`/`TOKEN_END`, `TIME_OPENERS`).
- **#2563 / #2588 / #2601** — the `perk librarian` worker row in `--json`-last form
  (`list|record|remove`, then the networked `add source`/`check`/`refresh`); #2601 excluded
  comment-start and redirection tokens from its free-argument words after PR review.

## Cross-references

- `extension/substrate/commandPositions.ts` — the lexer + dispatcher; `commandPositions()`,
  `splitTopLevelSegments`, `REFUSAL_REASONS`, `TIME_OPENERS`, `RESERVED_NAME`, the provenance comment
- `extension/substrate/readOnlyBash.ts` — `readOnlyBashVerdict`, `SAFE_PATTERNS`,
  `DESTRUCTIVE_PATTERNS`, the row builders, the regex vocabulary comments, the leniency block
- `extension/substrate/readOnlyBash.test.ts` + `extension/substrate/commandPositions.test.ts` — the
  paired allowed/blocked lists and the pinned leniencies
- `extension/substrate/toolGating.ts` — the gate that consumes the verdict (the `tool_call`
  backstop); `docs/learned/pi/tool-loadout.md` — the rest of the gate (activation, presentation,
  enforcement)
- `shared/contracts.md` §8.3 — the gate contract and its accepted limits
- `docs/user-docs/reference/in-session/model-tools.md` § "Structural read-only gate"
- `CONTEXT.md` § "Read-only bash gate" — the glossary
- `docs/learned/pi/context-system.md` — the scan-timeout guard (the fail-open consumer) and the gate
  engagement latch
- `docs/learned/workflow/plan-factories.md` — the inbox-over-`gh` pattern
- `docs/learned/workflow/doc-reconciliation.md` — evidence carriers that survive the squash
