// The read-only gate's bash verdict: a pure, offline policy over one command string — the
// whole-string destructive veto plus the per-command-position allowlist (contracts.md §8.3).

import { commandPositions, REFUSAL_REASONS } from "./commandPositions.ts";

// --- pure policy (perk-owned and self-contained; it began as a copy of plan-mode/utils.ts) -------
//
// Two layers. (1) A whole-string destructive veto over the walker's veto view (`vetoText`): every
// substitution, `${…}` and heredoc body collapsed out of the text that holds it, each substitution's
// own text appended on a line of its own — so an argument walk crosses `$(a; b)`, a heredoc body is
// data to the command that reads it, and what bash executes inside a substitution is judged
// exactly like top-level text. (2) An allowlist at every command position (`commandPositions.ts`).
// Destructive wins.
//
// The argument-level rule: an allowlisted command whose argument can turn the read into a write or
// select another program gets a scoped veto row, reading through a leading quote or escape on the
// option word. Argument-sensitive Git commands are admitted only in a list form (enumerated options
// plus positionals with a list-implying option among them, or bare with display modifiers and no
// positional); positional-only write forms (`git branch <name>`, `git tag <name>`, `git config
// <key> <value>`, `git symbolic-ref <ref> <target>`) are closed by the allowlist shape. Interpreters
// (`python`, `node`, `uv run`, `sh -c`) are never allowlisted.
//
// Accepted leniencies, recorded rather than chased:
//  1. In-program writers inside allowlisted commands' program text — `awk 'BEGIN{system(…)}'`,
//     `awk -f prog.awk`, `sed 'w f'`/`sed 'e cmd'`, `sed -f script`, `sed -f - <<'EOF'` (the
//     quoted-`>` veto catches `awk '{print > "f"}'` only incidentally).
//  2. Run-time supplied arguments — `xargs`, `find -exec … {}` and `fd -x` append trailing words
//     the gate never sees (`… | xargs git branch --list` could receive a positional from stdin),
//     the class already recorded as `fd -x env`; an expansion (`$X`, `$(…)`) likewise supplies
//     words the rows read only as their source text.
//  3. A quote or escape INSIDE a flag word (`-\i`, `-'i'`, `-""i`) — only a LEADING one
//     (`'-i'`, `\-i`) is read through; and abbreviated long options (`--del`, `--in-pl`,
//     `--out=f` — git's option parser and getopt_long accept unambiguous prefixes) in the veto rows.
//  4. The arg-blind admitted commands `curl -o/-O` and `agent-browser --output`.
//  5. Whole-string vetoes read quoted prose (`echo "git branch -D x"`, `printf '->'`) and flag
//     clusters (`rg -ln` via `\bln\b`) — over-strict by design; heredoc data is the one carve-out.
//  6. Over-strict exact-form rows: quoted, clustered, abbreviated or unlisted options in a list
//     form (`git branch '--list'`, `-av`, `--lis`), a substitution among a list form's words (its
//     inner words read as the command's own: `git branch -a --contains $(git rev-list …)`; quote a
//     variable instead), `git config` keys with non-`[\w-]` subsections (`url.https://…`), a quoted
//     single `symbolic-ref` ref, a ref-first `git reflog <ref>`.
//  7. Existing exported variables, variables populated dynamically (`read`, `printf -v`), and
//     interactive less/more/top input; the walker governs submitted assignment words and `for`
//     names, not the process environment or future input.
//  8. Git helpers selected implicitly by existing config/attributes (fsmonitor, diff/textconv/clean
//     filters), fixed ripgrep decompressors selected through inherited `PATH`, and option
//     abbreviations outside the explicitly-scoped veto spellings.

/**
 * Between the words of ONE command: blanks and `\`-newline continuations, never a bare newline — an
 * argument walk must not cross into the next command. At least one real blank is required because
 * Bash removes a continuation; `a\\⏎b` is the single word `ab`, while `a \\⏎b` remains two words.
 */
const SEP = String.raw`(?=(?:[ \t]|\\\n)*[ \t])(?:[ \t]|\\\n)+`;
/**
 * One shell word as the argument-level rows read it: an escaped character (`\;`), a whole quoted
 * span (`\"` stays inside a double-quoted one) or a single unquoted character — one per iteration
 * and the alternatives disjoint, so backtracking stays linear — never an unescaped operator.
 */
const WORD = String.raw`(?:\\[^\n]|'[^']*'|"(?:[^"\\]|\\[\s\S])*"|[^\s'"|;&\\])+`;
/** An input redirection and its operand; unlike shell words, the operand may be adjacent. */
const INPUT_REDIRECT = String.raw`\d*(?:<<<|<<-|<<|<>|<&|<)(?:[ \t]|\\\n)*${WORD}`;
/**
 * The argument walk: further words or adjacent input redirections of the same command. Output
 * redirects either become spaces in the sanitized veto view (`/dev/null`/fd duplication) or meet
 * the destructive redirect veto first.
 */
const WORDS = `(?:(?:${SEP}${WORD})|${INPUT_REDIRECT})*`;
/**
 * An optional opening quote or escape before a flag word (`'-i.bak'`, `"-w"`, `$'-D'`, `\-i`): bash
 * removes it, so a veto reads through it.
 */
const Q = String.raw`(?:\$?['"]|\\)?`;
/**
 * The end of a flag word in the whole-string scan: a blank or newline, `=`, a closing quote or
 * backtick, an operator or the end — `$` alone is the end of the whole scanned text, not of the
 * command.
 */
const END = String.raw`(?=(?:\\\n)*(?:[\s='"\x60|;&()<>]|$))`;
/**
 * The end of a command or subcommand word in an allowlist row: a blank, an adjacent redirection
 * (`git diff>/dev/null`) or the end of the simple command, after any `\`-newline continuations
 * (bash removes them without ending the word — `show\⏎-x` is `show-x`). Never `=`, `-`, `.` or other
 * text inside the word, so `rg=payload`, `rg-extra`, `git show-x` or `gh pr view-x` never reads as
 * the admitted word. Operators never reach a row: they end the simple-command text.
 */
const TOKEN_END = String.raw`(?=(?:\\\n)*(?:[ \t]|[<>](?!\()|&>|$))`;
/**
 * git's admitted global options. Never `-c key=value` (`-c alias.x='!cmd' x` runs any command),
 * never `--git-dir`/`--work-tree`.
 */
const GIT_OPTIONS = `(?:${SEP}(?:-C${SEP}${WORD}|--no-pager|-P))*`;
/** A `git` command word and its admitted global options, up to the subcommand. */
const GIT = `git${GIT_OPTIONS}${SEP}`;
/**
 * The trailing redirections an exact-form (`$`-anchored) row tolerates: the veto has already
 * reduced them to fd duplication, `/dev/null` and input.
 */
const TAIL = String.raw`(?:${SEP}(?:\d*>&\d+|(?:\d+|&)?>>?[ \t]*/dev/null|\d*<{1,3}[ \t]*${WORD}))*[ \t]*$`;
/** A positional word — never an option, not even a quoted or escaped one (`'--no-list'`). */
const POSITIONAL = `(?!${Q}-)${WORD}`;

/**
 * A list-form row: every word an enumerated option (a value-taking one consumes its value, so
 * `--format --list` is no list flag) or a positional, and at least one list-implying option — so a
 * negation (`--no-list`), an abbreviation or any other unlisted option never passes as list mode.
 * Each word parses one way only (a list option's separate commit is just a positional), and the
 * witness is a lookahead, so a failing match backtracks linearly.
 */
function listForm(subcommand: string, options: string, list: string): string {
  const word = `(?:${options}|${list}|${POSITIONAL})`;
  return String.raw`${subcommand}${TOKEN_END}(?=(?:${SEP}${word})*?${SEP}(?:${list})(?=\s|$))(?:${SEP}${word})*${TAIL}`;
}

/** `git branch`'s display modifiers (a value-taking one with its value). */
const BRANCH_DISPLAY = String.raw`-v|-vv|--verbose|-q|--quiet|-i|--ignore-case|--no-color|--color(?:=\S+)?|--column(?:=\S+)?|--no-column|--abbrev(?:=\d+)?|--no-abbrev|--omit-empty|(?:--sort|--format)(?:=|${SEP})${WORD}`;
/** Its list-implying options: `-a`/`-r` refuse a branch name; the filters imply list mode. */
const BRANCH_LIST = `-l|--list|-a|--all|-r|--remotes|--show-current|(?:--contains|--no-contains|--merged|--no-merged|--points-at)(?:=${WORD})?`;
/** `git tag`'s display modifiers. */
const TAG_DISPLAY = String.raw`-i|--ignore-case|--no-color|--color(?:=\S+)?|--column(?:=\S+)?|--no-column|--omit-empty|(?:--sort|--format)(?:=|${SEP})${WORD}`;
/** Its list-implying options: `-n` and the filters imply list mode. */
const TAG_LIST = String.raw`-l|--list|-n\d*|(?:--contains|--no-contains|--merged|--no-merged|--points-at)(?:=${WORD})?`;
/** `git config`'s scope, type and display options (a value-taking one with its value). */
const CONFIG_OPTIONS = String.raw`--local|--global|--system|--worktree|--show-origin|--show-scope|--name-only|-z|--null|--includes|--no-includes|--bool|--int|--bool-or-int|--path|--expiry-date|--type=\S+|(?:--default|--file|-f|--blob)(?:=|${SEP})${WORD}`;
/** Its getter/list actions — git refuses mixing one with any other action. */
const CONFIG_GET = "--get(?:-all|-regexp|-urlmatch|-color|-colorbool)?|--list|-l";

/**
 * An allowlist row for one `git` subcommand shape (case-sensitive: git flag case is meaningful).
 */
function git(body: string): RegExp {
  return new RegExp(String.raw`^\s*${GIT}${body}`);
}

/**
 * A command-keyed allowlist row: the command word and any enumerated subcommand words, the last one
 * ending at TOKEN_END (the earlier ones already end at the whitespace that follows them).
 */
function keyed(words: string, flags = ""): RegExp {
  return new RegExp(String.raw`^\s*${words}${TOKEN_END}`, flags);
}

/**
 * A whole-string veto row; the lookbehind keeps another command's `--sort`/`--tree`-style flag from
 * reading as the command.
 */
function veto(body: string): RegExp {
  return new RegExp(String.raw`(?<![\w-])${body}`);
}

const DESTRUCTIVE_PATTERNS = [
  /\brm\b/i,
  /\brmdir\b/i,
  /\bmv\b/i,
  /\bcp\b/i,
  /\bmkdir\b/i,
  /\btouch\b/i,
  /\bchmod\b/i,
  /\bchown\b/i,
  /\bchgrp\b/i,
  /\bln\b/i,
  /\btee\b/i,
  /\btruncate\b/i,
  /\bdd\b/i,
  /\bshred\b/i,
  /(^|[^<])>(?!>)/,
  />>/,
  /\bnpm\s+(install|uninstall|update|ci|link|publish)/i,
  /\byarn\s+(add|remove|install|publish)/i,
  /\bpnpm\s+(add|remove|install|publish)/i,
  /\bpip\s+(install|uninstall)/i,
  /\bapt(-get)?\s+(install|remove|purge|update|upgrade)/i,
  /\bbrew\s+(install|uninstall|upgrade)/i,
  // git: whole-subcommand mutators (the word ends there — `merge-base` is a read), then one row per
  // argument-level writer of an admitted subcommand.
  veto(
    String.raw`${GIT}(?:add|commit|push|pull|fetch|merge|rebase|reset|checkout|switch|restore|cherry-pick|revert|init|clone|am|apply|notes|update-ref|reflog${SEP}(?:expire|delete|drop))(?![\w-])`,
  ),
  // Anywhere among branch's words, clusters (`-rd`) included: git does not refuse every mix with a
  // list flag (`git branch -a -D foo` deletes). The safe shorts `a r l v i q` carry none of these.
  veto(
    String.raw`${GIT}branch\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*[dDmMcCuft][a-zA-Z]*|--(?:delete|move|copy|set-upstream-to|unset-upstream|edit-description|force|track|create-reflog))${END}`,
  ),
  veto(
    String.raw`${GIT}tag\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*[adefFmsu][a-zA-Z]*|--(?:annotate|sign|local-user|delete|force|message|file|edit|create-reflog|cleanup|trailer))${END}`,
  ),
  // Every stash form but `list`/`show` — bare `git stash` is `push`.
  veto(String.raw`${GIT}stash\b(?!${SEP}(?:list|show)\b)`),
  veto(
    String.raw`${GIT}remote(?:${SEP}(?:-v|--verbose))*${SEP}(?:add|remove|rm|rename|set-url|set-head|set-branches|prune|update)\b`,
  ),
  veto(String.raw`${GIT}worktree${SEP}(?:add|remove|move|prune|lock|unlock|repair)\b`),
  veto(String.raw`${GIT}symbolic-ref\b${WORDS}${SEP}${Q}(?:-d|--delete|-m)${END}`),
  veto(
    String.raw`${GIT}config\b(?:${SEP}(?:set|unset|rename-section|remove-section|edit)\b|${WORDS}${SEP}${Q}(?:--(?:add|unset|unset-all|replace-all|rename-section|remove-section|edit)|-e)${END})`,
  ),
  // `-w` writes the object database; attached spellings (`-wt blob`) included.
  veto(String.raw`${GIT}hash-object\b${WORDS}${SEP}${Q}-[a-zA-Z]*w`),
  // `git diff/log/show --output=<file>` writes a file.
  veto(String.raw`git\b${WORDS}${SEP}${Q}--output${END}`),
  // Explicit helper switches on the reads that take diff/log options: `--ext-diff` runs the
  // configured external diff and `--textconv` the configured converters (`reflog` and `stash
  // show|list` take them too; these options never abbreviate). `--no-ext-diff`/`--no-textconv` pass.
  veto(
    String.raw`${GIT}(?:diff|log|show|range-diff|reflog|stash|shortlog)\b${WORDS}${SEP}${Q}--(?:ext-diff|textconv)${END}`,
  ),
  // Exec flags of admitted subcommands: `git grep -O<cmd>` runs its pager through the shell and
  // `git ls-remote --upload-pack=<cmd>` (hidden alias `--exec`) runs a local command for a local
  // path — prefixes included, as git accepts unambiguous abbreviations.
  veto(String.raw`${GIT}grep\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*O|--op)`),
  veto(String.raw`${GIT}ls-remote\b${WORDS}${SEP}${Q}--(?:up|exe)`),
  // Converters and filters named by path: `grep --textconv`, `cat-file --textconv|--filters`,
  // `hash-object --path|--filters|--stdin-paths` — run the path's configured helpers. Whole
  // positive option words only: `--no-filters` and a bare `--stdin` pass.
  veto(String.raw`${GIT}grep\b${WORDS}${SEP}${Q}--textconv${END}`),
  veto(String.raw`${GIT}cat-file\b${WORDS}${SEP}${Q}--(?:textconv|filters)${END}`),
  veto(String.raw`${GIT}hash-object\b${WORDS}${SEP}${Q}--(?:path|filters|stdin-paths)${END}`),
  // Argument-level writers of the admitted text utilities.
  veto(String.raw`find\b${WORDS}${SEP}${Q}-(?:delete|fprint0?|fprintf|fls)${END}`),
  // `-i` anywhere among sed's words (GNU sed permutes options after operands), clustered or with a
  // suffix (`-ni`, `-i.bak`, `-i''`), BSD `-I`, `--in-place[=SUF]`; `--silent`/`--posix` start with
  // `--` and never reach the cluster arm.
  veto(String.raw`sed\b${WORDS}${SEP}${Q}-(?:[a-zA-Z]*[iI]|-in-place\b)`),
  // `-o` is sort's only short flag with an `o`; an attached operand (`-o./out.txt`) included.
  veto(String.raw`sort\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*o|--output)`),
  veto(String.raw`tree\b${WORDS}${SEP}${Q}-[a-zA-Z]*o`),
  // Program selectors of the admitted readers. `sort --compress-program=<cmd>` (and its
  // unambiguous `--comp…` abbreviation), ripgrep's preprocessor and hostname helper, bat's pager.
  veto(String.raw`sort\b${WORDS}${SEP}${Q}--comp`),
  veto(String.raw`rg\b${WORDS}${SEP}${Q}--(?:pre|hostname-bin)${END}`),
  veto(String.raw`bat\b${WORDS}${SEP}${Q}--pager${END}`),
  // less (and macOS more, the same binary): the dangerous leading startup commands shell out
  // (`!`, `#`, `|`), edit (`v`) or save (`s`); `--cmd` likewise; a lesskey file or source can set
  // the environment. Searches (`+/pattern`) and ordinary motion (`+G`) pass.
  veto(String.raw`(?:less|more)\b${WORDS}${SEP}${Q}\+\+?[!#|vs]`),
  veto(
    String.raw`(?:less|more)\b${WORDS}${SEP}${Q}(?:-[a-zA-Z]*k|--(?:cmd|lesskey-file|lesskey-src|lesskey-context)${END})`,
  ),
  // In more's compatibility mode `-p` names a startup command: every spelling is refused.
  veto(String.raw`more\b${WORDS}${SEP}${Q}-[a-zA-Z]*p`),
  new RegExp(String.raw`\bnpm${SEP}audit${SEP}fix\b`, "i"),
  /\bsudo\b/i,
  /\bsu\b/i,
  /\bkill\b/i,
  /\bpkill\b/i,
  /\bkillall\b/i,
  /\breboot\b/i,
  /\bshutdown\b/i,
  /\bsystemctl\s+(start|stop|restart|enable|disable)/i,
  /\bservice\s+\S+\s+(start|stop|restart)/i,
  /\b(vim?|nano|emacs|subl)\b/i,
];

const SAFE_PATTERNS = [
  // `cd` mutates nothing — it is the common prefix for scoping a read-only query
  // (`cd repo && perk objective show …`). Safe because every other command position is
  // independently validated and the whole-string destructive veto is unchanged.
  keyed("cd"),
  keyed("cat"),
  keyed("head"),
  keyed("tail"),
  keyed("less"),
  keyed("more"),
  keyed("grep"),
  keyed("find"),
  keyed("ls"),
  keyed("pwd"),
  keyed("echo"),
  keyed("printf"),
  keyed("wc"),
  keyed("sort"),
  keyed("uniq"),
  keyed("diff"),
  keyed("file"),
  keyed("stat"),
  keyed("du"),
  keyed("df"),
  keyed("tree"),
  keyed("which"),
  keyed("whereis"),
  keyed("type"),
  keyed("env"),
  keyed("printenv"),
  keyed("uname"),
  keyed("whoami"),
  keyed("id"),
  keyed("date"),
  keyed("cal"),
  keyed("uptime"),
  keyed("ps"),
  keyed("top"),
  keyed("htop"),
  keyed("free"),
  // git's read-only plumbing. Pure reads take any arguments (their writer flags are vetoed); an
  // argument-sensitive subcommand is admitted in its list form only — enumerated options plus
  // positionals with a list-implying option among them (positionals are then patterns/commits),
  // or bare with display modifiers and no positional — so `git branch <name>` / `git tag <name>` /
  // `git config <key> <value>` / `git symbolic-ref <ref> <target>` fail the shape.
  git(
    `(?:status|log|diff|show|blame|grep|check-ignore|merge-base|rev-list|rev-parse|cat-file|describe|name-rev|ls-files|ls-tree|ls-remote|for-each-ref|show-ref|shortlog|count-objects|range-diff|patch-id|hash-object|var|version|--version)${TOKEN_END}`,
  ),
  git(listForm("branch", BRANCH_DISPLAY, BRANCH_LIST)),
  git(`branch${TOKEN_END}(?:${SEP}(?:${BRANCH_DISPLAY}))*${TAIL}`),
  git(listForm("tag", TAG_DISPLAY, TAG_LIST)),
  git(`tag${TOKEN_END}(?:${SEP}(?:${TAG_DISPLAY}))*${TAIL}`),
  git(
    `remote${TOKEN_END}(?:${SEP}(?:-v|--verbose)${TOKEN_END})*(?:${SEP}(?:show|get-url)${TOKEN_END}|${TAIL})`,
  ),
  git(`worktree${SEP}list${TOKEN_END}`),
  git(`stash${SEP}(?:list|show)${TOKEN_END}`),
  // Exactly one `<ref>`.
  git(
    String.raw`symbolic-ref${TOKEN_END}(?:${SEP}(?:-q|--quiet|--short|--no-recurse|--recurse))*${SEP}[^-\s'"]\S*${TAIL}`,
  ),
  // A positive list: bare (= show), `show …`, `list`, `exists <ref>`, flag-first; every other
  // action (`expire`/`delete`/`drop`, and any future one) falls outside it.
  git(`reflog${TOKEN_END}(?:${SEP}(?:show|list|exists)${TOKEN_END}|${SEP}-|${TAIL})`),
  // A getter/list action present (`--file --get` gives `--get` to `--file`), the git ≥ 2.46
  // subcommand form, or exactly one dotted key.
  git(listForm("config", CONFIG_OPTIONS, CONFIG_GET)),
  git(`config${SEP}(?:get|list)${TOKEN_END}`),
  git(
    String.raw`config${TOKEN_END}(?:${SEP}(?:${CONFIG_OPTIONS}))*${SEP}[A-Za-z][\w-]*(?:\.[\w-]+)+${TAIL}`,
  ),
  keyed(`npm${SEP}(?:list|ls|view|info|search|outdated|audit)`, "i"),
  keyed(`yarn${SEP}(?:list|info|why|audit)`, "i"),
  keyed(`node${SEP}--version`, "i"),
  keyed(`python${SEP}--version`, "i"),
  /^\s*curl\s/i,
  keyed(`wget${SEP}(?:-O-|-O${SEP}-)`, "i"),
  keyed("jq"),
  // `sed` in every form (`-i` is vetoed).
  keyed("sed"),
  keyed("awk"),
  // Everyday read-only utilities — none has an output-file flag.
  keyed(
    "(?:nl|shasum|sha1sum|sha224sum|sha256sum|sha384sum|sha512sum|md5|md5sum|readlink|realpath|basename|dirname|test|true|false|read|set|column|tr|cut|paste|comm|tac|rev|od|strings|sleep|fold|cmp)",
  ),
  // `[ -f x ]` (`[[` stays refused by the walker).
  keyed(String.raw`\[`),
  // `command -v NAME`: the walker yields the query itself as the command.
  keyed(`command${SEP}-[pvV]+`),
  // xxd's second positional is an output file: flag-only switches, the count-taking flags with
  // their number, and at most ONE file operand.
  new RegExp(
    String.raw`^\s*xxd(?:${SEP}(?:-[abeEiprCu]+|-[cglos][ \t]*[+-]?(?:0x)?[0-9a-fA-F]+))*(?:${SEP}(?!-)${WORD})?${TAIL}`,
  ),
  keyed("rg"),
  keyed("fd"),
  keyed("ast-grep"),
  // Browser-automation skill (.agents/skills/agent-browser): a command-keyed entry mirroring
  // `ast-grep` — it gates the command, not its args. Two invocation forms: the bare global
  // install on PATH, and the `npx` fallback anchored to `agent-browser` so bare `npx <anything>`
  // stays blocked. Accepted known leniency: the command-position model checks command words, not
  // their arguments, so agent-browser's own output flags (screenshot/video `--output`) can write
  // files and its actions can mutate external sites — outside the gate's granularity. This is
  // accepted and documented, consistent with the allowlisted `curl` / `fetch_content`
  // GitHub-clone cache-write precedent (both write outside the gate). The whole-string
  // `>`-redirect destructive veto still applies.
  keyed("agent-browser"),
  keyed(`npx${SEP}agent-browser`),
  keyed("bat"),
  keyed("eza"),
  // perk's own read-only objective queries (show/next + their s/n aliases, plus the non-mutating
  // node-engagement read the objective-plan factory needs). The complete-word ending keeps the `n`
  // alias from matching the mutating `node` subcommand; node-engagement allowed; create/node/reconcile
  // stay blocked. node-engagement materializes a present refinement under the run scratch dir —
  // the same accepted leniency as `perk pr review-context` below (the CLI writes its own
  // gitignored scratch file; the destructive veto still blocks `> file` redirects).
  keyed(`perk${SEP}(?:objective|obj)${SEP}(?:show|s|next|n|node-engagement)`, "i"),
  // Report children need exactly these query forms, not arbitrary PR operations: plan-bound
  // children (`/pr-review`, `/address`) use the `--expected-pr` form; the human-triage doors'
  // adversarial children use the foreign `--pr` / `--pr --stack` forms (a read-only parent would
  // otherwise block the doors' children outright); the stack-review flow's lanes AND its routing
  // step run the PINNED `--pr N --stack --pin-base <sha> --pin-head <pr>=<sha>…` form the door
  // rendered (`pinnedReviewContextCommand` — full 40-hex lowercase shas, at least two heads; the
  // CLI re-validates the grammar and topology). ONE anchored alternation: `--json` last, nothing
  // else; the flagless form stays out (only the write-capable foreground conflict-resolver uses
  // it, outside the gate). The destructive veto still blocks `> file` redirects — the CLI writes
  // its own scratch files.
  /^\s*perk\s+pr\s+review-context\s+(?:--expected-pr\s+[1-9][0-9]*|--pr\s+[1-9][0-9]*(?:\s+--stack(?:\s+--pin-base\s+[0-9a-f]{40}(?:\s+--pin-head\s+[1-9][0-9]*=[0-9a-f]{40}){2,})?)?)\s+--json\s*$/,
  /^\s*perk\s+pr\s+feedback\s+--json\s*$/,
  // The perk library workers' deterministic `--json` forms (contracts.md §8.75(f)). The CLI mutates
  // only the gitignored `docs/library/` cache and refuses unless its representative ignore probes
  // pass and nothing under the library is tracked (the probes run before its lock, except
  // `remove`'s entry probe): the `perk pr review-context` leniency, made operational by the CLI's
  // cache-only preflight. The three network verbs — `check` (the only freshness probe),
  // `refresh` and `add source` — mutate only that same cache behind the same preflight, and
  // their git operations run config-pinned (no global/system config, hooks disabled), so nothing
  // a cloned tree or the user's global config selects can execute (env config and a checkout's
  // repo-local config stay trusted, §8.75(i)). `add docs` is not admitted.
  // `--json` last, any whitespace-separated arguments before it; the destructive veto still
  // blocks real-file redirects and chained mutations. The trailing `--json` must be a real
  // argument: the simple-command text keeps a trailing comment and redirection operands, so an
  // argument word may not start a comment (`#`) or hold a redirection (`<`/`>`) — otherwise
  // `refresh <slug> # --json` or `refresh <slug> <<< --json` would run the human form, which on
  // a docs entry is the write-capable refresh door (§8.75(k)).
  /^\s*perk\s+librarian\s+(?:list|record|remove|check|refresh|add\s+source)\b(?:\s+(?!#)[^\s<>]+)*\s+--json\s*$/,
  // Read-only `gh` queries — the guidance in the managed AGENTS block ("GitHub access goes
  // through gh") must be followable in read-only sessions. Query-shaped subcommands only;
  // `gh api` stays blocked (it can POST/PATCH), as do all mutating subcommands (create/edit/
  // merge/close/comment/clone/...). Destructive-wins still blocks `> file` redirects.
  keyed(`gh${SEP}(?:issue|pr|repo|run|release|label)${SEP}(?:view|list|diff|status|checks)`, "i"),
  keyed(`gh${SEP}search${SEP}(?:issues|prs|code|commits|repos)`, "i"),
  keyed(`gh${SEP}auth${SEP}status`, "i"),
  // `perk --help`, `perk <group> --help`, `perk <group> <verb> --help`: only bare lowercase
  // identifier words precede the help flag, so no option can consume it as a value — Click's
  // eager help then exits before any command body runs (no perk command disables it). Never `-h`:
  // perk registers only `--help`, so `-h` reaches a command body as an ordinary argument.
  /^\s*perk(?:\s+[a-z][\w-]*){0,3}\s+--help(?:\s|$)/,
  // Version stamps + the learned-docs verifier (it writes nothing).
  keyed(`perk${SEP}--version`),
  keyed(`perk${SEP}learn${SEP}docs-check`),
  keyed(`pi${SEP}--version`),
];

/** The read-only gate's bash verdict; a refusal carries the one-line reason the block message shows. */
export type ReadOnlyBashVerdict = { allowed: true } | { allowed: false; reason: string };

/**
 * Whether a bash command is allowed under read-only mode — first hit wins:
 *  1. NOT destructive: a WHOLE-STRING scan against DESTRUCTIVE_PATTERNS (destructive-wins — content
 *     anywhere in the string, incl. command substitutions, still vetoes) over the walker's veto
 *     view: every substitution, `${…}` and heredoc body collapsed out of the text that holds it
 *     and each substitution's own text appended on a line of its own, so an argument walk crosses
 *     `$(a; b)`, a `>` or `git add` in `<<'EOF' … EOF` is not a write, and `$(echo x > out)` in an
 *     unquoted body is judged exactly like top-level text. Two redirect carve-outs are neutralized first:
 *     FD duplications (`2>&1`, `1>&2`) and redirects to `/dev/null` (`>/dev/null`, `2>/dev/null`,
 *     `&>/dev/null`, `>>/dev/null`) — both discard output and write nothing to the filesystem.
 *     Redirects to a REAL path (`> file`, `&> file`, `>> file`) are NOT carved out and stay
 *     destructive.
 *  2. SAFE at every command position (`commandPositions.ts`): the start of input and the word after
 *     an unquoted `;` `|` `|&` `&&` `||`, a lone `&` or a newline; inside `$(…)`/backticks (also
 *     within double quotes) and `<(…)`/`>(…)`; after `NAME=value` prefixes, leading redirections,
 *     the keywords `for…in`/`do`/`done`/`while`/`until`/`if`/`then`/`elif`/`else`/`fi`/`{`/`}`/`!`
 *     and the wrappers `env`/`timeout N`/`xargs`/`nice`/`time`/`command`/`nohup`; and at
 *     `find -exec`/`fd -x` — EVERY simple command there must match a SAFE_PATTERNS entry. A dynamic
 *     command word (`$VAR`, quoted, escaped, substituted), an unterminated quote/substitution/heredoc,
 *     an unmodeled wrapper flag or unmodeled syntax is refused, as is a command with nothing to
 *     run. The allowlist matches the simple-command text (command word to the end of that simple
 *     command), so the anchored `perk pr … --json\s*$` rows still see the full argument tail;
 *     every command word inside a heredoc body's substitutions is allowlisted like any other.
 * Pure → unit-testable offline.
 */
export function readOnlyBashVerdict(command: string): ReadOnlyBashVerdict {
  const positions = commandPositions(command);
  const scanned = positions.vetoText
    .replace(/\d*>&\d+/g, " ")
    .replace(/(?:\d+|&)?>>?\s*\/dev\/null\b/g, " ");
  const veto = DESTRUCTIVE_PATTERNS.find((p) => p.test(scanned));
  if (veto !== undefined) return { allowed: false, reason: `matches the destructive veto ${veto}` };
  if (!positions.ok) return { allowed: false, reason: REFUSAL_REASONS[positions.refusal] };
  if (positions.commands.length === 0)
    return {
      allowed: false,
      reason: "no command to run (only assignments, comments or whitespace)",
    };
  const unlisted = positions.commands.find((c) => !SAFE_PATTERNS.some((p) => p.test(c)));
  if (unlisted === undefined) return { allowed: true };
  const line = unlisted.split("\n")[0] ?? "";
  return {
    allowed: false,
    reason: `not allowlisted: ${line.length > 100 ? `${line.slice(0, 100)}…` : line}`,
  };
}

/** The boolean form of `readOnlyBashVerdict`. */
export function isReadOnlyBashCommand(command: string): boolean {
  return readOnlyBashVerdict(command).allowed;
}
