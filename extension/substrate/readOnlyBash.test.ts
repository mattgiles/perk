// The read-only gate's bash verdict: the pure allow/refuse matrix over command strings (fully
// offline). See readOnlyBash.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { REFUSAL_REASONS } from "./commandPositions.ts";
import { isReadOnlyBashCommand, readOnlyBashVerdict } from "./readOnlyBash.ts";

test("isReadOnlyBashCommand: allows read-only commands", () => {
  for (const cmd of [
    "cat README.md",
    "grep -r foo .",
    "ls -la",
    "git status",
    "git log --oneline -5",
    "git diff HEAD",
    "rg pattern src",
    "ast-grep run --pattern 'console.log($A)' --lang js .", // structural code search
    "ast-grep run --pattern 'print($A)' --lang python .", // language-agnostic: the allowlist gates the `ast-grep` command, not its --lang
    "ast-grep scan --inline-rules 'id: x\nlanguage: ts\nrule: {pattern: $A}'",
    "agent-browser snapshot", // browser-automation skill (command-keyed like ast-grep)
    "agent-browser navigate https://example.com",
    "npx agent-browser skills get core", // npx fallback anchored to agent-browser
    "cd repo && agent-browser screenshot", // every command position allowlisted, cd prefix
    "find . -name '*.ts'",
    "wc -l file",
    "sed -n '1,10p' file",
    "cat x 2>&1", // fd duplication is not a file write
    "grep foo bar 2>&1",
    "ls -la 1>&2",
    "cat foo 2>/dev/null", // /dev/null redirect is not a file write
    'grep -rn "user-docs" README.md 2>/dev/null',
    "cd /tmp && grep foo bar", // cd prefix + every command position safe
    "cd repo && perk objective show 453 2>&1 | head -200", // reported example 1
    `ls tests/ | grep -iE 'doc|user|cli|link'; echo "---"; grep -rl "user-docs" tests/ 2>/dev/null`, // reported example 3 (quoted | does not split; 2>/dev/null allowed)
    `find tests -name '*.py' | grep -iE 'doc|user|cli' ; echo --- ; grep -rl "user-docs" tests 2>/dev/null`, // reported example 4
    "perk objective show", // perk's read-only objective queries
    "perk objective show 7 --full", // the body read rides the same read-only verb
    "perk objective next",
    "perk obj show 42",
    "perk objective s", // s/n aliases
    "perk obj n",
    "perk objective node-engagement 7 --node 2.1 --json", // non-mutating engagement read
    "gh issue view 12 --json body", // read-only gh queries
    "gh pr view 7 --json title --jq .title",
    "gh pr diff 7",
    "gh pr checks 7",
    "gh run list --limit 5",
    "gh search prs perk",
    "gh search code registerTool --repo x/y", // `code` as a gh-search noun is not an editor invocation
    "gh auth status",
    // every command position is checked, so loops, assignment prefixes, substitutions, keywords,
    // wrappers, exec forms and heredocs pass when every command word is allowlisted
    "for f in a b c; do echo $f; done",
    'for f in agents/*.md; do wc -l "$f"; done',
    'EVID=$(cat x); echo "$EVID"',
    "env | grep PERK",
    "timeout 30 rg foo src",
    "find . -exec grep -l foo {} \\;",
    "find . -exec env LC_ALL=C grep -l foo {} \\;",
    'cd "$(cat .perk/root)" && rg foo', // the structural stand-in for `cd $(git rev-parse …) && …`
    "cd /repo\ngit ls-files docs | head -5; echo ---; sed -n '1,5p' README.md",
    'f=$(ls dist/*.js); grep -n "x" "$f"',
    'f="/a b/c"; sed -n \'1p\' "$f"',
    "LC_ALL=C sort file",
    "LC_ALL=C GIT_OPTIONAL_LOCKS=0 grep foo f",
    "cat <<'EOF' | wc -c\nline one\nline two\nEOF",
    "cat <<EOF\n$(echo hi)\nEOF",
    'echo "$(pwd)"',
    "echo `pwd`",
    "diff <(sort a) <(sort b)",
    "< README.md wc -l",
    '<<< "text" wc -c',
    "2>/dev/null ls",
    "echo $'a\\'b'; ls",
    "rg foo \\\n  --glob '*.ts'",
    "# list files\nls -la",
    "ls # trailing comment",
    "while grep -q x f; do cat f; done",
    "if grep -q x f; then cat f; fi",
    "! grep -q x f",
    "{ cat a; cat b; }",
    "nice -n 5 rg foo",
    "time rg foo",
    "nohup rg foo",
    "command rg foo",
    "xargs -0 -n1 grep -l foo",
    "find . -name '*.py' | xargs -I{} wc -l {}",
    "env -i LC_ALL=C grep foo f",
    "timeout -k 5 30s rg foo",
    "fd -e py -x wc -l",
    "cat a |& grep b",
    "echo ok & ls",
    "env -i LC_ALL=C", // a wrapper chain with no command word is its own command
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "echo ${x/;/,}; ls", // ${…} is one unit: its `;` is not an operator
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("the reviewer defs' oversized-line byte-slice recipe passes the gate; its redirect does not", () => {
  // The agent defs teach `sed -n 'Np' <path> | tail -c +<offset> | head -c 51200` to page a line
  // over Pi's per-line `read` bound. Every segment must stay allowlisted or the defs' recipe
  // silently stops working for read-only children; a real-file redirect stays vetoed.
  const path = "/repo/.perk/workflow/scratch/runs/RUN/review-context/pr-42-0123456789ab/diff.patch";
  for (const offset of ["+1", "+51201", "+102401"])
    assert.equal(
      isReadOnlyBashCommand(`sed -n '12p' ${path} | tail -c ${offset} | head -c 51200`),
      true,
      offset,
    );
  assert.equal(isReadOnlyBashCommand(`sed -n '12p' ${path} | head -c 51200`), true);
  assert.equal(isReadOnlyBashCommand(`grep -n '^diff --git' ${path}`), true);
  assert.equal(isReadOnlyBashCommand(`wc -lc ${path}`), true);
  assert.equal(
    isReadOnlyBashCommand(`sed -n '12p' ${path} | tail -c +51201 | head -c 51200 > slice.txt`),
    false,
  );
});

const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);
const SHA_0 = "0".repeat(40);
/** The pinned stack form exactly as `pinnedReviewContextCommand` renders it (+ `--json`). */
const PINNED_QUERY = `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`;

test("plan-bound review queries allow only the exact argument forms", () => {
  // The plan-bound `--expected-pr` form, the human-triage doors' foreign `--pr` / `--pr --stack`
  // forms, the stack flow's PINNED form, and the feedback query — each gets the same
  // whitespace/`cd`-prefix/redirect matrix.
  const queries = [
    "perk pr review-context --expected-pr 42 --json",
    "perk pr review-context --pr 42 --json",
    "perk pr review-context --pr 42 --stack --json",
    PINNED_QUERY,
    `perk pr review-context --pr 43 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --pin-head 43=${SHA_0} --json`,
    "perk pr feedback --json",
  ];
  for (const query of queries) {
    for (const command of [
      query,
      `  ${query}  `,
      query.replaceAll(" ", "\t"),
      `cd repo && ${query}`,
    ])
      assert.equal(isReadOnlyBashCommand(command), true, command);
    for (const command of [
      `${query} --extra`,
      `${query} > report.json`,
      `${query} >> report.json`,
      `${query} && perk pr review-post`,
      `${query}; rm file`,
      `${query} | gh api user`,
    ])
      assert.equal(isReadOnlyBashCommand(command), false, command);
  }
  for (const command of [
    "perk pr review-context",
    "perk pr review-context --json",
    "perk pr review-context --expected-pr 42",
    "perk pr review-context --json --expected-pr 42",
    "perk pr review-context --expected-pr 42 --json --stack",
    "perk pr review-context --expected-pr 42 --stack --json",
    "perk pr review-context --pr 42",
    "perk pr review-context --pr 42 --stack",
    "perk pr review-context --pr 42 --json --stack",
    "perk pr review-context --stack --pr 42 --json",
    "perk pr review-context --json --pr 42",
    "perk pr review-context --pr 42 --local --json",
    "perk pr review-context --pr 42 --json --pr 43 --json",
    "perk pr review-context --pr 42 --expected-pr 42 --json",
    "perk pr review-contextual --expected-pr 42 --json",
    "perk pr review-contexts --pr 42 --json",
    // The pinned form: only WITH --stack, base + at least two heads, full lowercase 40-hex shas,
    // `<pr>=<sha>` pairs, --json last — every deviation stays blocked.
    `perk pr review-context --pr 42 --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --json`,
    `perk pr review-context --pr 42 --stack --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0.slice(0, 39)} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A.toUpperCase()} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B}x --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 0=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --pin-base ${SHA_0} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --local --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B}`,
    `perk pr review-context --expected-pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    "perk pr feedback",
    "perk pr feedback --pr 42 --json",
    "perk pr feedback-extra --json",
    "perk pr review-post --json",
    "gh api user",
    ...["0", "01", "-1", "1.5", "+1", "N", "42x"].flatMap((n) => [
      `perk pr review-context --expected-pr ${n} --json`,
      `perk pr review-context --pr ${n} --json`,
      `perk pr review-context --pr ${n} --stack --json`,
    ]),
  ])
    assert.equal(isReadOnlyBashCommand(command), false, command);
});

test("perk librarian workers are admitted only in their --json-last forms", () => {
  // The CLI's cache-only preflight backs the admission (it refuses before touching a
  // non-ignored or tracked path); the gate only pins the verb set and `--json` last.
  for (const command of [
    "perk librarian list --json",
    "cd repo && perk librarian list --json",
    "perk librarian record --publish docs/library/.staging/pi-01ARZ --slug pi --source https://pi.dev/docs --json",
    "perk librarian record --adopt docs/library/pi --kind docs --source https://pi.dev/docs --json",
    "perk librarian record --publish docs/library/.staging/pi-01ARZ --slug pi --source https://pi.dev/docs --replace --accept-failures --json",
    "perk librarian remove pi --json",
    "perk librarian add source foo/bar --json",
    "perk librarian add source https://github.com/pallets/click --ref 8.1.7 --slug click --json",
    "perk librarian check --json",
    "perk librarian check pi click --force --json",
    "cd repo && perk librarian check --json",
    "perk librarian refresh pi --json",
    // A `#` inside a word is literal, not a comment.
    "perk librarian record --publish docs/library/.staging/pi --slug pi --source https://pi.dev/docs#intro --json",
  ])
    assert.equal(isReadOnlyBashCommand(command), true, command);
  for (const command of [
    "perk librarian list",
    "perk librarian list --json --verbose",
    "perk librarian record --adopt docs/library/pi --kind docs --source https://x --json > out.txt",
    "perk librarian remove pi --json && git add .",
    "perk librarian add docs https://pi.dev/docs --json",
    "perk librarian add --json",
    "perk librarian check",
    "perk librarian refresh pi --json > out.txt",
    "perk librarian check --json && git add .",
    "perk librarian addsource foo/bar --json",
    "perk librarian checkx --json",
    "perk librarianx list --json",
    // The `run_librarian` tool's worker is the extension's own exec, never a gated bash command.
    "perk librarian prepare docs https://pi.dev/docs --json",
    "perk librarian prepare refresh pi --json",
  ])
    assert.equal(isReadOnlyBashCommand(command), false, command);
});

test("perk librarian admission needs a real trailing --json, never a comment or a redirection operand", () => {
  // Bash drops a comment and hands a redirection its operand, so each of these runs the human
  // form — on a docs entry the write-capable refresh door (§8.75(k)) — and must stay blocked.
  for (const command of [
    "perk librarian refresh pi # --json",
    "perk librarian refresh pi\t# --json",
    "perk librarian refresh pi #x --json",
    "perk librarian refresh pi #--json",
    "perk librarian refresh pi \\\n# --json",
    "perk librarian refresh pi <<< --json",
    "perk librarian refresh pi < --json",
    "perk librarian refresh pi 0< --json",
    "perk librarian list # --json",
    "perk librarian add source foo/bar # --json",
    "perk librarian record --publish x --slug pi --source https://x <<< --json",
  ]) {
    const verdict = readOnlyBashVerdict(command);
    assert.equal(verdict.allowed, false, command);
    assert.ok(!verdict.allowed && verdict.reason.startsWith("not allowlisted"), command);
  }
});

test("isReadOnlyBashCommand: blocks destructive / non-allowlisted commands", () => {
  for (const cmd of [
    "rm -rf /tmp/x",
    "mv a b",
    "cp a b",
    "echo hi > file.txt", // redirection write
    "cat a >> file.txt", // append redirection
    "cat a &> file.txt", // &> writes both streams to a file (still destructive)
    "git commit -m wip",
    "git push origin main",
    "npm install left-pad",
    "sudo reboot",
    "chmod +x script.sh",
    "some-unknown-binary --flag", // not in the safe table at all
    "git status && rm file", // destructive wins over a safe prefix
    "git status && some-unknown-binary", // a non-safe command at a later command position
    "ls | rm -rf x", // pipe whose second segment is destructive
    "perk objective create foo", // mutating objective subcommands stay blocked
    "perk objective node 1.1",
    "perk objective node 2.3 --status done", // sibling mutating verb stays blocked
    "perk objective node-engagement 7 --node 2.1 > f", // destructive-wins blocks the redirect
    "perk objective reconcile",
    "perk init", // would allow scaffolding writes
    "perk obj node 2.3", // the `n` alias must not match `node`
    "gh api repos/{owner}/{repo}/issues -f title=x", // gh api blocked (can POST/PATCH)
    "gh api user", // even GET-shaped gh api stays blocked
    "gh pr create --fill", // mutating gh subcommands stay blocked
    "gh issue edit 12",
    "gh pr merge 7",
    "gh repo clone o/r",
    "gh issue view 12 > out.txt", // destructive-wins blocks the redirect
    "npx some-other-pkg", // npx entry is anchored to agent-browser — bare npx stays blocked
    "agent-browser screenshot > shot.png", // >-redirect destructive veto wins over the safe entry
    "code file.ts", // the `code` editor at a command position: refused by the allowlist alone
    "ls; code .", // …after a `;` sequencer
    "echo hi && code .", // …after `&&`
    "cat $(code y)", // …inside a command substitution
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a non-allowlisted command at ANY command position is blocked", () => {
  for (const cmd of [
    // positions the leading-word check never saw
    "echo hi\nnode -e \"require('fs').writeFileSync('x','y')\"",
    "echo $(python -c \"open('x','w').write('y')\")",
    "echo ok & python -c \"open('x','w')\"",
    'echo "a\\"" ; python -c "open(\'x\',\'w\')"',
    "env X=1 node -e \"require('fs').writeFileSync('x','y')\"",
    "echo `python -c x`",
    'echo "$(python -c x)"',
    "X=$(python -c x)",
    "diff <(python -c x) f",
    "<echo python -c pass", // a leading redirection's operand is never the command
    "<<< echo python -c pass",
    "< $(python -c x) cat",
    "echo $'a\\'b'; python -c \"print(42)\" # '", // ANSI-C `\'` does not close the quote
    "echo $'\\''; python -c pass # '",
    // exec forms, incl. a wrapper at the exec position
    "find . -exec rm {} \\;",
    "find . -exec python -c x {} \\;",
    "find . -execdir python {} \\;",
    "find . -ok python {} \\;",
    "find . -okdir python {} \\;",
    "find . -exec env python -c pass {} \\;",
    "find . -maxdepth 0 -exec env python -c pass \\;",
    "find . -exec timeout 5 python {} \\;",
    "find . -exec env {} \\;", // `{}` is the command word after `env`: running the found file
    "fd -x python",
    "fd --exec python",
    "fd -X python",
    "fd --exec-batch python",
    "fd -x env python",
    // wrappers reach the wrapped command; a bare non-allowlisted wrapper is its own command
    "timeout 5 python -c x",
    "timeout 30",
    "xargs python -c x",
    "find . | xargs",
    "nice python",
    "time python",
    "nohup python",
    "command python",
    "env -i python",
    // keywords
    "if python; then ls; fi",
    "while python; do ls; done",
    'for f in x; do python "$f"; done',
    "for f in $(python -c x); do ls; done",
    "{ python; }",
    "! python",
    // an expanding heredoc body is scanned; lines after the terminator are commands
    "cat <<EOF\n$(python -c x)\nEOF",
    "cat <<EOF\nbody\nEOF\npython -c x",
    "cat <<EOF\nEO\\\nF\npython -c pass\nEOF", // bash joins `EO\⏎F` into the terminator
    "echo `echo \\`python -c pass\\``", // nested backquote escape: refused
    // a `#` inside ${…} is not a comment, so the later command is still checked
    `echo \${x:-a #b}; node -e "require('fs').writeFileSync('x','y')"`,
    // a wrapper operand's expansion could split into the command itself
    `PAYLOAD='DROP node -e x'; env -u $PAYLOAD ls`,
    // xargs supplies the bare env's command from its input
    `printf '%s\\0' node -e x | xargs -0 env`,
    // a delimiter whose quote-removed value is unknown, and one whose `\`-newline is not quoting
    "cat <<$'echo'\necho\nnode -e x\n$'echo'",
    "cat <<E\\\nOF\n$(node -e x)\nEOF",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: what the walker does not model is refused", () => {
  for (const cmd of [
    "$CMD",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "${CMD} x",
    '"$CMD" x',
    "ls; $EDITOR x",
    "$(cat cmd)",
    "echo 'a",
    'echo "a',
    "echo $(ls",
    "ls )",
    "cat <",
    "cat <<EOF\nbody",
    "env -S 'python -c x' echo",
    "time -o out rg foo",
    "timeout rg foo",
    "xargs -a list grep foo",
    "(cd x && ls)",
    "foo() { ls; }; foo",
    "A=(1 2); ls",
    "echo $((1+1))",
    "case x in a) ls;; esac",
    "[[ -f x ]] && cat x",
    "ls \\",
    "A=1", // nothing to run
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: the census-driven read-only forms are allowed", () => {
  for (const cmd of [
    // git's pure reads, any arguments, behind the admitted global options
    "git rev-parse HEAD",
    "git rev-parse --show-toplevel",
    "cd $(git rev-parse --show-toplevel) && rg foo",
    "git status --short && git rev-parse HEAD && git log -1 --format='%H %s'",
    "git worktree list --porcelain",
    "git blame -L 1,5 f",
    "git grep -n foo -- src",
    "git grep -o -e foo", // `-o` (only-matching) is not the pager flag `-O`
    "git check-ignore -v p",
    "git merge-base --is-ancestor a HEAD",
    "git rev-list --count HEAD",
    "git cat-file -t abc",
    "git describe --tags",
    "git name-rev HEAD",
    "git ls-files docs",
    "git ls-tree -r HEAD",
    "git ls-remote origin",
    "git for-each-ref --format='%(refname)' refs/heads",
    "git show-ref --heads",
    "git shortlog -sn",
    "git count-objects -v",
    "git range-diff a^..a b^..b",
    "git show abc --pretty=format: | git patch-id --stable",
    "git show 4a71:skills/x/SKILL.md | git hash-object --stdin",
    "git hash-object f",
    "git diff -Oorder.txt", // diff's `-O<orderfile>` only reads
    "git --version",
    "git version",
    "git -C /other/repo diff --stat v1 v2 -- p",
    'git -C "$(pwd)" status',
    "git --no-pager log -1",
    "git -P log -1",
    // symbolic-ref: exactly one ref
    "git symbolic-ref HEAD",
    "git symbolic-ref --short -q HEAD",
    "git symbolic-ref HEAD 2>/dev/null",
    // reflog: the positive list
    "git reflog",
    "git reflog show --format='%h %gs' -12 plan-2354",
    "git reflog -12 --date=iso-strict",
    "git reflog --all",
    "git reflog list",
    "git reflog exists refs/heads/main",
    // tag: a list-implying flag, or bare with display modifiers
    "git tag",
    "git tag --list",
    "git tag -l 'v*'",
    "git tag --contains HEAD",
    "git tag -n5",
    "git tag --sort=-v:refname",
    "git tag --points-at HEAD",
    "git tag --merged main",
    "git branch --all --contains HEAD && git tag --contains HEAD | head -20",
    // branch: a list-implying flag, or bare with display modifiers
    "git branch",
    "git branch -v",
    "git branch -vv",
    "git branch --show-current",
    "git branch -a",
    "git branch --all",
    "git branch -r",
    "git branch -l",
    "git branch --list 'plan-*'",
    "git branch -a --contains abc",
    "git branch --merged main",
    "git branch --no-merged",
    "git branch --points-at HEAD",
    "git branch --format='%(refname:short)' --sort=-committerdate",
    "git branch --format '%(refname)' -a",
    "git branch -v 2>&1",
    "git branch \\\n  --list 'x*'", // a continued line is one command
    // remote, stash, config: the read forms
    "git remote",
    "git remote -v",
    "git remote --verbose",
    "git remote show origin",
    "git remote get-url origin",
    "git remote -v show origin",
    "git stash list",
    "git stash show -p stash@{0}",
    "git stash list --format='%gd %s'",
    "git config --get user.name",
    "git config --get-regexp '^alias\\.'",
    "git config --list",
    "git config -l",
    "git config --list --show-origin",
    "git config --local --get core.hooksPath",
    "git config core.hooksPath",
    "git config --show-origin diff.renames",
    "git config get user.name",
    "git config list",
    "git config --global --get user.email",
    // everyday read-only utilities
    "nl -ba shared/contracts.md | sed -n '736,757p'",
    "shasum -a 256 f",
    "sha256sum f",
    "sha1sum f",
    "md5 f",
    "md5sum f",
    "readlink /usr/local/bin/pi",
    "realpath .",
    'basename "$f"',
    'dirname "$f"',
    "test -f x && cat x",
    "[ -f x ] && cat x",
    "[ -d dir ]",
    "true",
    "false",
    "ls x 2>/dev/null || true",
    "read -r line < f",
    'while read -r l; do echo "$l"; done < f',
    "set -eu\nprintf '%s\\n' '--- pi ---'\ncommand -v pi || true",
    "set -o pipefail; rg foo | head",
    "column -t f",
    "tr ',' '\\n' < f",
    "cut -c1-200 f",
    "cut -d: -f1 f",
    "paste a b",
    "comm -12 a b",
    "tac f",
    "rev f",
    "od -c f | head",
    "xxd f | head",
    "xxd -l 16 -s 0x10 f",
    "xxd -r -p f",
    "xxd -p f",
    "strings f | grep foo",
    "sleep 1",
    "fold -w 180 f",
    "cmp a b",
    "command -v pi",
    "command -V pi",
    "command -pv pi",
    // sed in every form but -i
    "sed -n '1,10p' f",
    "sed 's/a/b/' f",
    "sed -E 's/(a)/\\1/' f",
    "sed -e 's/a/b/' -e 's/c/d/' f",
    "sed '1d;$d' f",
    "sed -n '/^```markdown$/,/^```$/p' d.md | sed '1d;$d' | wc -c",
    "sed 's/x/y/' f 2>/dev/null",
    "sed -n '/-i/p' f", // a quoted `-i` INSIDE a script word is not the flag
    // perk / pi read verbs
    "perk --version",
    "perk --help",
    "perk plan --help",
    "perk objective node --help",
    "perk skills create --help",
    "perk objective --help 2>&1",
    "perk init --help", // Click's eager help exits before the command body runs
    "perk learn docs-check",
    "perk learn docs-check --json",
    "pi --version",
    "pi --version 2>/dev/null | head -1",
    // already admitted — regression pins
    "date -u +%Y-%m-%dT%H:%M:%SZ",
    "stat -f '%Sm %N' f",
    "npm audit",
    "npm audit --json",
    "find . -name '*.ts' -print",
    "find . -type f -print0 | xargs -0 grep -l foo",
    "sort -k1,1 f",
    "sort -r f",
    "tree -L 2",
    "tree -a",
    // a `--sort`/`--tree` flag is not the `sort`/`tree` command
    "rg --sort path -o 'x' f",
    "eza --tree -o",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: an argument walk never crosses into the next command", () => {
  // Each later command's flag would match the earlier command's writer row if the walk crossed
  // the newline or the operator.
  for (const cmd of [
    "git branch\nwc -c README.md",
    "git config --get user.name\nrg -e needle README.md",
    "git tag\nsed -n 1p f",
    "git remote -v; sort -k1 f",
    "git branch -a; rg -m 1 foo f",
    "git hash-object f\nrg -w x f",
    "sed -n 1p f\nrg -i x f",
    "find . -name x\nrg --fixed-strings -delete f",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: heredoc data is data", () => {
  for (const cmd of [
    "wc -c <<'EOF'\na `git add` here and a > here and rm -rf and `npm ci`\nEOF",
    "cat <<EOF\n-> arrow => fat arrow git push\nEOF",
    "cat <<-EOF | wc -l\n\t> quoted\n\tEOF",
    "cat <<'EOF' | wc -c\nsed -i x\nEOF",
    "echo $(cat <<X\n> inside a substitution's heredoc\nX\n)",
    "wc -c <<'EOF'\n---\ntitle: x\n---\nEOF",
    "cat <<A <<'B' | wc -c\nrm a\nA\nmv b\nB",
    "cat <<EOF\nrm in prose, $(git rev-parse HEAD) -> here\nEOF", // a read-only substitution beside vetoable data
    "cat <<EOF\n`pwd` > prose\nEOF",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: argument-level writers and non-list forms are blocked", () => {
  for (const cmd of [
    // branch: a positional without a list-implying flag, or any writer flag anywhere
    "git branch foo",
    "git branch -v foo",
    "git branch foo main",
    "git branch -m old new",
    "git branch -M new",
    "git branch -c a b",
    "git branch -C a b",
    "git branch -u origin/main",
    "git branch --set-upstream-to=origin/main",
    "git branch --unset-upstream",
    "git branch --move a b",
    "git branch --copy a b",
    "git branch --edit-description",
    "git branch -d foo",
    "git branch -D foo",
    "git branch '-D' foo",
    'git branch "-D" foo',
    "git branch \\-D foo",
    "git branch --delete foo",
    "git branch -rd origin/foo",
    "git branch -a -D foo",
    "git branch -f foo HEAD",
    "git branch --force foo",
    "git branch -t foo origin/foo",
    "git branch --track foo origin/foo",
    "git branch --create-reflog foo",
    "git branch --no-track foo",
    "git branch --list -D foo",
    "git branch --format=%(refname) foo",
    "git branch \\\n  -D foo", // a continued line is one command
    // remote
    "git remote add o url",
    "git remote remove o",
    "git remote rm o",
    "git remote rename a b",
    "git remote set-url o url",
    "git remote set-head o -a",
    "git remote set-branches o main",
    "git remote prune o",
    "git remote update",
    "git remote -v add o url",
    "git remote 'add' o url",
    // worktree
    "git worktree add /tmp/x",
    "git worktree remove x",
    "git worktree move a b",
    "git worktree prune",
    "git worktree lock x",
    "git worktree unlock x",
    "git worktree repair",
    "git worktree",
    // tag
    "git tag v1",
    "git tag v1 HEAD",
    "git tag -a v1 -m msg",
    "git tag -am msg v1",
    "git tag '-a' v1 -m msg",
    "git tag -s v1",
    "git tag -u key v1",
    "git tag -d v1",
    "git tag --delete v1",
    "git tag -f v1",
    "git tag --force v1",
    "git tag -F msgfile v1",
    "git tag -e v1",
    "git tag -l -d v1",
    "git tag --sort=x v1",
    // stash: every form but list/show
    "git stash",
    "git stash push",
    "git stash save x",
    "git stash pop",
    "git stash apply",
    "git stash drop",
    "git stash clear",
    "git stash branch b",
    "git stash -u",
    "git stash -q",
    "git stash create",
    "git stash store x",
    // notes, refs, reflog actions, the remaining whole-subcommand mutators
    "git notes add -m x",
    "git notes",
    "git update-ref refs/heads/x abc",
    "git update-ref -d refs/heads/x",
    "git symbolic-ref HEAD refs/heads/x",
    "git symbolic-ref -d refs/x",
    "git symbolic-ref --delete refs/x",
    "git symbolic-ref -m msg HEAD refs/heads/x",
    "git symbolic-ref",
    "git reflog expire --all",
    "git reflog delete HEAD@{1}",
    "git reflog drop --all",
    "git reflog drop refs/heads/x",
    "git reflog plan-2354", // ref-first — over-strict, pinned
    "git fetch",
    "git switch main",
    "git restore f",
    "git am p",
    "git apply p",
    // config: action flags, the subcommand-form writers, the legacy `<key> <value>` set
    "git config user.name x",
    "git config --global user.name x",
    "git config --add x y",
    "git config --unset x",
    "git config --unset-all x",
    "git config --replace-all x y",
    "git config --rename-section a b",
    "git config --remove-section a",
    "git config --edit",
    "git config -e",
    "git config set user.name x",
    "git config unset x",
    "git config edit",
    "git config rename-section a b",
    "git config remove-section a",
    "git config 'set' k v",
    // hash-object -w, --output
    "git hash-object -w f",
    "git hash-object -wt blob f",
    "git hash-object '-w' f",
    "git hash-object -w --stdin",
    "git diff --output=x.patch",
    "git log --output x",
    "git show --output=f HEAD",
    // global options: `-c`/`--git-dir` never admitted; `-C` keeps every writer veto
    "git -c alias.x='!python -c 1' x",
    "git -c core.pager=cat log",
    "git --git-dir=/x status",
    "git -C /x branch -D foo",
    "git -C /x stash pop",
    "git -C /x tag v1",
    "git -C /x remote add o u",
    // find's writers
    "find . -name '*.log' -delete",
    "find . -delete",
    "find . '-delete'",
    "find . -fprint out.txt",
    "find . -fprint0 out",
    "find . -fprintf out '%p\\n'",
    "find . -fls out",
    // sed -i, in every spelling the veto reads through
    "sed -i 's/a/b/' f",
    "sed -i.bak 's/a/b/' f",
    "sed '-i.bak' 's/a/b/' f",
    "sed \"-i\" 's/a/b/' f",
    "sed \\-i 's/a/b/' f",
    "sed -i'' 's/a/b/' f",
    "sed -ni 's/a/b/p' f",
    "sed -Ei 's/a/b/' f",
    "sed -e 's/a/b/' -i f",
    "sed --in-place 's/a/b/' f",
    "sed --in-place=.bak 's/a/b/' f",
    "sed -n '1p' f -i",
    "sed -I 's/a/b/' f",
    // npm audit fix, sort -o, tree -o, xxd's output operand
    "npm audit fix",
    "npm audit fix --force",
    "npm \\\naudit fix", // a continued separator still names the destructive audit action
    "sort -o out f",
    "sort -o./out.txt f",
    "sort -ro out f",
    "sort '-o' out f",
    "sort --output=out f",
    "sort --output out f",
    "tree -o out.txt",
    "tree -ao out",
    "tree -oout",
    "xxd in out",
    "xxd -r in out",
    "xxd -p f out",
    "xxd -l 16 f out",
    // an admitted utility never admits the next command
    "command -v python && python -c 1",
    "test -f x && rm x",
    "true && python -c 1",
    "set -e; python -c 1",
    "read -r x < f && python -c 1",
    "sleep 5; rm x",
    "tr a b < f > g",
    "nl f > out",
    "git rev-parse HEAD > sha",
    // perk / pi: only the enumerated read verbs
    "perk init",
    "perk learn docs-sync",
    "perk learn docs",
    "perk plan 12",
    "perk --version && perk init",
    "perk objective node-add 2544 --phase 1 --description --help", // an option consumes `--help` as its value
    "perk plan --force --help",
    "perk plan 12 --help", // over-strict on non-identifier words — pinned
    "perk objective node 2.3 --status done --help",
    "perk plan -- --help",
    // perk registers only `--help`: `-h` reaches the command body as an ordinary argument
    "perk -h",
    "perk skills create review-probe -h",
    'pi -p "x"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a list form holds only when git's effective mode is list mode", () => {
  // each creates the named branch/tag or writes a config file in a real repository
  for (const cmd of [
    // a negation cancels the list flag (abbreviated too)
    "git branch --list --no-list b1",
    "git branch --show-current --no-show-current b2",
    "git branch --points-at HEAD --no-points-at b3",
    "git branch --list --no-lis b9",
    "git tag --points-at HEAD --no-points-at t2",
    // a list-flag lookalike consumed as a value-taking option's value
    "git branch --format --list b4",
    "git branch --sort --list b5",
    "git tag --format -l t3",
    "git config --file --get a.b c",
    "git config -f --list a.b c",
    // a quoted or escaped option is still an option, never a positional
    "git branch --list '--no-list' b6",
    "git branch --list \\--no-list b7",
    // an unlisted option in a list form
    "git branch -a --bogus foo",
    // a flag lookalike inside a quoted value is no list flag
    'git branch --format "x\\" -a \\"" b8',
    // over-strict, pinned: a substitution's inner words read as the command's own
    "git branch -a --contains $(git rev-list --all -1)",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  // …while list forms with values, attached filters and display options still pass
  for (const cmd of [
    "git branch --contains=HEAD --no-color",
    "git branch --merged=main -v 'plan-*'",
    "git tag -l --sort=-v:refname --format '%(refname)' 'v*'",
    "git config --get-regexp --file x.cfg 'a\\.' ",
    "git config --show-origin --get-all remote.origin.fetch",
    'c=$(git rev-list --all -1); git branch -a --contains "$c"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: an argument walk crosses escaped operators, substitutions and backticks", () => {
  for (const cmd of [
    // the writer flag follows an escaped `;`, a nested operator or a `${…}` holding one
    "find victim -exec echo {} \\; -delete",
    "git hash-object $(echo input.txt; echo) -w",
    "git hash-object `echo input.txt; echo` -w",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "find . ${x/;/,} -delete",
    'sed "s/a/b/; s/c/d/" -i f',
    // a closing backtick ends the flag word, top-level and inside an expanding heredoc
    "echo `find victim -delete`",
    "cat <<EOF\n`find victim -delete`\nEOF",
    "echo `git branch -D foo`",
    // a nested substitution's own writer flag is judged in its own text
    "cat <<EOF\n$(git hash-object $(echo a; echo) -w)\nEOF",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: exec flags of admitted git subcommands and flag words ending at an operator are blocked", () => {
  for (const cmd of [
    // `git grep -O<cmd>` runs its pager through the shell; `git ls-remote --upload-pack=<cmd>`
    // (hidden alias `--exec`) runs a local command — abbreviations included
    "git grep -Opython x",
    "git grep -O'python3 -c 1' x",
    "git grep -nO x",
    "git grep --open-files-in-pager=python x",
    "git grep --open x",
    "git ls-remote --upload-pack=python .",
    "git ls-remote --upload-pack python .",
    "git ls-remote --up=python .",
    "git ls-remote --exec=python .",
    // a writer flag's word ends at an operator, a newline or a closing `)` as well as a blank
    "find . -delete; ls",
    "find . -delete\nls",
    "find . -delete&& ls",
    "echo $(find . -delete)",
    "git branch -a --unset-upstream; ls",
    "git branch -a --edit-description\nls",
    "git tag -l -d v1; ls",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

// Exec-bearing input: an environment entry, a program word or an option that makes an otherwise
// admitted read launch another program. The payloads are strings under test — never run.
test("isReadOnlyBashCommand: exec-bearing environment is refused in every sink", () => {
  for (const cmd of [
    // a shell prefix: only the literal safe pairs
    "GIT_EXTERNAL_DIFF=python git diff",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=python git log",
    "GIT_SSH_COMMAND=python git ls-remote origin",
    "GIT_PROXY_COMMAND=python git ls-remote git://example.com/r",
    "GIT_PAGER=python git log",
    "PAGER=python git log",
    "GH_PAGER=python gh pr view 1",
    "LESSOPEN='|python %s' less f",
    "LESSCLOSE=python less f",
    "BAT_PAGER=python bat f",
    "LD_PRELOAD=/tmp/x.so ls",
    "DYLD_INSERT_LIBRARIES=/tmp/x.dylib ls",
    "PERL5OPT=-Mx shasum f",
    "PERL5LIB=/tmp shasum f",
    "PYTHONPATH=/tmp perk --version",
    "NODE_OPTIONS='--require /tmp/x.js' pi --version",
    "RIPGREP_CONFIG_PATH=/tmp/rc rg foo",
    "XDG_CONFIG_HOME=/tmp git log",
    "HOME=/tmp git log",
    "PATH=/tmp:$PATH git log",
    "EDITOR=python git log",
    "SSH_ASKPASS=python git ls-remote origin",
    "AWKPATH=/tmp awk -f x f",
    "PS4='$(python -c 1)' ls",
    "X=1 grep foo f", // no generic prefix either
    "LC_ALL=C X=1 sort f",
    "LC_ALL=POSIX sort f",
    "LC_ALL='C' sort f",
    // an env entry: the same safe pairs, under a wrapper and at exec positions too
    "env GIT_EXTERNAL_DIFF=python git diff",
    "env -i PAGER=python git log",
    "env PERL5OPT=-Mx shasum f",
    "env LD_PRELOAD=/tmp/x.so ls",
    "env X=1 grep foo f",
    "timeout 5 env GIT_PAGER=python git log",
    "find . -exec env PAGER=python git log \\;",
    "fd -x env PS4=x git log",
    // a standalone assignment then a read: `set -a` exports it, `set -x` expands PS4
    "PS4='$(python -c 1)'; set -x; ls",
    "set -x; PS4='$(python -c 1)'; ls",
    "set -a; GIT_EXTERNAL_DIFF=python; git diff",
    "set -a; PERL5OPT=-Mx; shasum f",
    "set -a; PERL5LIB=/tmp; shasum f",
    "set -a; GIT_CONFIG_COUNT=1; GIT_CONFIG_KEY_0=core.pager; GIT_CONFIG_VALUE_0=python; git log",
    "set -a; GIT_SSH_COMMAND=python; git ls-remote origin",
    "set -a; LESSOPEN='|python %s'; less f",
    "set -a; LD_PRELOAD=/tmp/x.so; ls",
    "set -a\nPAGER=python\ngit log",
    "PATH=/tmp; ls",
    "GIT_OPTIONAL_LOCKS=1; git status",
    // a for variable is assigned like a standalone one, whatever the loop's words
    "for PATH in /tmp; do git log; done",
    "set -a; for GIT_EXTERNAL_DIFF in python; do git diff; done",
    "for GIT_OPTIONAL_LOCKS in 0; do git status; done",
    "for PS4 in x; do set -x; ls; done",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  for (const cmd of [
    "LC_ALL=C sort f",
    "GIT_OPTIONAL_LOCKS=0 git status",
    "LC_ALL=C GIT_OPTIONAL_LOCKS=0 git log --oneline -1",
    "env LC_ALL=C sort f",
    "env -i GIT_OPTIONAL_LOCKS=0 git status",
    "env -i git status",
    "env | grep PATH",
    "timeout 5 env LC_ALL=C sort f",
    "find . -exec env LC_ALL=C grep -l foo {} \\;",
    "GIT_OPTIONAL_LOCKS=0; git status",
    "set -a; EVID=x; git log",
    "set -x; ls",
    'for f in a b; do git log -1 "$f"; done',
    'x=$(git rev-parse HEAD); git show "$x"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a NAME=value or suffixed word is never the admitted command", () => {
  for (const cmd of [
    // a program's literal argv: an assignment-shaped word is the program's name
    "timeout 5 rg=payload foo",
    "nice LC_ALL=C sort f",
    "env rg=payload",
    "find . -exec rg=payload {} \\;",
    "fd -x rg=payload",
    "rg=payload foo",
    // a command-keyed row covers the complete command word
    "rg-extra foo",
    "rg.foo foo",
    "ast-grep-x run",
    "npx agent-browser-x snapshot",
    "sort.x f",
    "env-x",
    "cat=x f",
    // …and the complete subcommand word
    "git show-x",
    "git show=payload",
    "git show.payload",
    "git diff-x HEAD",
    "git-show-x",
    "git show-branch", // never admitted — only a prefix accident matched it
    "git show\\\n-x", // a continuation joins `show-x`
    'git show"-x"',
    "git diff2>/dev/null",
    "git stash list-x",
    "git stash show.x",
    "git stash\\\nshow", // a continuation alone joins `stashshow`
    "git worktree\\\nlist",
    "git config\\\nget user.name",
    "git reflog show-x",
    "git remote show-x origin",
    "git worktree list-x",
    "git config get-x a.b",
    "gh pr view-x 1",
    "gh pr view=1",
    "gh pr\\\nview 1", // a continuation alone joins `prview`
    "npm\\\nls", // joins the executable word
    "gh auth status-x",
    "gh search prs-x q",
    "npm ls-x",
    "npm lsx",
    "yarn why-x x",
    "perk objective show-x 7",
    "perk objective node-engagement-x 7",
    "perk --version-x",
    "perk learn docs-check-x",
    "pi --version-x",
    "node --version-x",
    "wget -O -foo https://example.com",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  for (const cmd of [
    "git show --stat",
    "git -C repo show HEAD",
    "git diff>/dev/null",
    "git diff 2>/dev/null",
    "git status&>/dev/null",
    "git show\\\n  --stat",
    "git stash \\\nshow",
    "git worktree \\\nlist",
    "git config \\\nget user.name",
    "rg \\\n--glob '*.ts' foo",
    "gh \\\npr \\\nview 1",
    "npm \\\nls",
    "perk \\\nobjective \\\nshow 7",
    "perk \\\n--version",
    "timeout 5 rg foo",
    "env rg foo",
    "gh pr view 1",
    "npm ls",
    "perk objective show 7",
    "perk --version",
    "pi --version",
    "git stash list",
    "git stash show -p",
    "git reflog show",
    "git remote show origin",
    "git worktree list",
    "git config get user.name",
    "wget -O - https://example.com",
    "wget -O- https://example.com",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: shell keywords and `time` follow bash's reading of the position", () => {
  for (const cmd of [
    // a reserved word after a wrapper or at an exec position is a program name
    "timeout 5 if true; then ls; fi",
    "nice { ls; }",
    "nohup ! ls",
    "find . -exec ! \\;",
    "fd -x done",
    // only the keyword `time` (a pipeline's start, before any prefix) takes a prefix after it
    "env time LC_ALL=C sort f",
    "echo x | time LC_ALL=C sort f",
    "time </dev/null if ls",
    "time 2>/dev/null ! ls",
    "time </dev/null -p ls",
    "time </dev/null time LC_ALL=C sort f",
    "LC_ALL=C time LC_ALL=C sort f",
    "! time LC_ALL=C sort f",
    "if time LC_ALL=C sort f; then ls; fi",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  for (const cmd of [
    "time LC_ALL=C sort f",
    "time -p LC_ALL=C sort f",
    "time </dev/null LC_ALL=C sort f",
    "time -p </dev/null LC_ALL=C sort f",
    "time rg foo",
    "echo x | time rg foo",
    "env time -p rg foo",
    "if grep -q x f; then time LC_ALL=C sort f; fi",
    "timeout 5 env LC_ALL=C sort f",
    "! grep -q x f",
    'time for f in a b; do wc -l "$f"; done',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a direct program selector is vetoed beside its allowed neighbor", () => {
  for (const cmd of [
    "rg --pre python foo",
    "rg --pre=python foo",
    "rg '--pre=python' foo",
    "rg -n --hostname-bin=python foo",
    "rg --hostname-bin python foo",
    "rg</dev/null --pre=python foo",
    "rg 3<host.txt --hostname-bin python foo",
    "timeout 5 rg --pre python foo",
    "find . -exec rg --pre python foo {} \\;",
    "sort --compress-program=python f",
    "sort --compress-program python f",
    "sort --comp=python f",
    "sort</dev/null --compress-program=python f",
    'sort -k1 "--compress-program=python" f',
    "bat --pager=python f",
    "bat --pager python f",
    "bat '--pager=python' f",
    "bat</dev/null --pager=python f",
    "less +!python f",
    "less '+!python' f",
    "less '+#python' f",
    "less '+|python' f",
    "less +v f",
    "less +sout f",
    "less ++!python f",
    "less '++|python' f",
    "less ++v f",
    "less --cmd=x f",
    "less -k keys f",
    "less -kkeys f",
    "less --lesskey-file=x f",
    "less --lesskey-src=x f",
    "less --lesskey-context=x f",
    "more -p python f",
    "more -ppython f",
    "more -sp python f",
    "more</dev/null -p python f",
    "more '+!python' f",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  for (const cmd of [
    "rg --pre-glob '*.gz' foo",
    "rg --pre-glob=x foo",
    "rg --no-pre foo",
    "sort -k1,1 f",
    "sort -r f",
    "sort --co python f", // only the planned `--comp…` abbreviation family is vetoed
    "bat --paging=never f",
    "bat -p f",
    "less +G f",
    "less +G!python f", // only the planned dangerous leading startup command is scoped
    "less +50 f",
    "less +/pattern f",
    "less +/save f", // a search pattern's text is inert
    "less -p pattern f",
    "less -N f",
    "more f",
    "more +G f",
    "more +/x f",
    // the option walk stays inside its own command
    "rg foo f; echo --pre x",
    "sort f\necho --compress-program",
    "bat f && echo --pager",
    "more f | wc -c; echo -p",
    "less f; echo +!x",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: explicit git helper switches are vetoed on every read that takes them", () => {
  for (const cmd of [
    "git diff --ext-diff",
    "git diff --textconv",
    "git diff</dev/null --ext-diff",
    "git diff 3<input --textconv",
    "git log -p --ext-diff",
    "git log --textconv -p",
    "git show --ext-diff HEAD",
    "git show --textconv HEAD:f",
    "git range-diff --ext-diff a b",
    "git reflog --ext-diff",
    "git reflog show --textconv",
    "git reflog -3 --ext-diff",
    "git stash show --ext-diff",
    "git stash list -p --textconv",
    "git shortlog --ext-diff",
    "git -C repo diff --ext-diff",
    'git -C "$(pwd)" diff --ext-diff',
    "git --no-pager log --textconv",
    "git diff '--ext-diff'",
    "git diff \\--textconv",
    "git diff $(echo a) --ext-diff",
    "rg $(echo foo) --pre python",
    "sort $(echo f) --comp=python",
    "git diff \\\n  --ext-diff",
    "git diff --ext-diff\\\n HEAD",
    "git grep --textconv foo",
    "git cat-file --textconv HEAD:f",
    "git cat-file --filters HEAD:f",
    "git cat-file</dev/null --filters HEAD:f",
    "git hash-object --path=f f",
    "git hash-object --path f --stdin",
    "git hash-object --filters f",
    "git hash-object --stdin-paths",
    "git hash-object</dev/null --path=f f",
    "rg --pre=python\\\n foo",
    "bat --pager=python\\\n f",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  for (const cmd of [
    "git diff --no-ext-diff",
    "git diff --no-textconv",
    "git log --no-ext-diff -p",
    "git show --no-textconv HEAD",
    "git diff -Oorder.txt",
    "git grep -o foo",
    "git grep --text foo",
    "git hash-object --no-filters f",
    "git hash-object --stdin",
    // abbreviations are outside this scoped closure (the full helper option words above are closed)
    "git grep --textc foo",
    "git cat-file --textc HEAD:f",
    "git hash-object --pa=f f",
    "git hash-object --stdin-p",
    "git cat-file -p HEAD",
    "git reflog show -3",
    "git reflog",
    "git stash show -p",
    "git stash list",
    "git range-diff a b",
    "git shortlog -sn",
    "git -C repo log -1",
    "git diff; echo --ext-diff",
    "git log\necho --textconv",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: heredoc code is still code", () => {
  for (const cmd of [
    "cat <<EOF > out\nx\nEOF",
    "cat <<'EOF' >> out\nx\nEOF",
    "cat <<EOF\n$(echo x > out)\nEOF",
    "cat <<EOF\n$(printf x > out)\nEOF",
    "cat <<EOF\n$(> out echo x)\nEOF", // a leading redirection inside the substitution
    "cat <<EOF\n$(find . -delete)\nEOF",
    "cat <<EOF\n$(sort -o out f)\nEOF",
    "cat <<EOF\n`sed -i s/a/b/ f`\nEOF",
    "cat <<EOF\n`rm x`\nEOF",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "cat <<EOF\n${x:-$(git branch -D foo)}\nEOF",
    "cat <<EOF\n$(rm -rf x)\nEOF",
    "cat <<EOF\n$(python -c 1)\nEOF",
    "bash <<'EOF'\nrm -rf x\nEOF",
    "python <<'PY'\nprint(1)\nPY",
    "sh <<EOF\nls\nEOF",
    "xargs -0 env <<EOF\nX=1 python\nEOF", // a bare `env` after `xargs` is xargs's own command
    "awk '{print > \"f\"}' in", // quoted `>` elsewhere stays vetoed on purpose
    'echo "a > b"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

// The policy comment's accepted leniencies, pinned so a future tightening is a deliberate change.
test("isReadOnlyBashCommand: recorded leniencies stay as recorded", () => {
  for (const cmd of [
    "sed -f script.sed f", // an in-program writer in a program file is invisible
    "awk -f prog.awk f",
    "find . -type f -print0 | xargs -0 git branch --list", // run-time appended arguments
    "sed -f - f <<'EOF'\nw out\nEOF", // a program read from a literal heredoc
    "sed -'i' 's/a/b/' f", // a quote INSIDE the flag word
    // names assigned at run time are not the submitted text's assignments
    "read -r PATH < f; git log",
    "printf -v PAGER %s cat; git log",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed (recorded leniency): ${cmd}`);
  }
});

test("readOnlyBashVerdict: argument-level and heredoc reasons", () => {
  const reason = (cmd: string) => {
    const verdict = readOnlyBashVerdict(cmd);
    return verdict.allowed ? "allowed" : verdict.reason;
  };
  const VETO = "matches the destructive veto /";
  // explicit writer flags and writer subcommands are vetoed…
  for (const cmd of [
    "git branch -D foo",
    "git stash",
    "find . -delete",
    "sed -i 's/a/b/' f",
    "git reflog drop --all",
  ])
    assert.ok(reason(cmd).startsWith(VETO), cmd);
  // …positional-only write forms fail the allowlist shape
  assert.equal(reason("git branch foo"), "not allowlisted: git branch foo");
  assert.equal(reason("git tag v1"), "not allowlisted: git tag v1");
  // heredoc code meets the redirect row; heredoc data meets nothing
  assert.equal(
    reason("cat <<EOF\n$(echo x > out)\nEOF"),
    "matches the destructive veto /(^|[^<])>(?!>)/",
  );
  assert.deepEqual(readOnlyBashVerdict("wc -c <<'EOF'\nrm -rf x\nEOF"), { allowed: true });
});

test("readOnlyBashVerdict: a refusal names its reason", () => {
  const reason = (cmd: string) => {
    const verdict = readOnlyBashVerdict(cmd);
    return verdict.allowed ? "allowed" : verdict.reason;
  };
  assert.ok(reason("git status && rm f").startsWith("matches the destructive veto /\\brm\\b/i"));
  assert.equal(reason("echo 'a"), "unterminated quote");
  assert.equal(reason("cd x && python -c 1"), "not allowlisted: python -c 1");
  assert.equal(reason("A=1"), "no command to run (only assignments, comments or whitespace)");
  assert.equal(reason("$CMD"), REFUSAL_REASONS["dynamic-command-word"]);
  assert.equal(reason("env -Q ls"), REFUSAL_REASONS["wrapper-usage"]);
  assert.equal(reason("(ls)"), REFUSAL_REASONS["unmodeled-syntax"]);
  assert.equal(reason("timeout 5 if true; then ls; fi"), REFUSAL_REASONS["unmodeled-syntax"]);
  // exec-bearing environment: one stable refusal for every sink
  for (const cmd of [
    "X=1 git log",
    "env PAGER=python git log",
    "timeout 5 rg=payload",
    "PATH=/tmp; ls",
    "for PATH in /tmp; do ls; done",
  ])
    assert.equal(reason(cmd), REFUSAL_REASONS["unsafe-environment-assignment"], cmd);
  // the destructive veto still reads first, walker refusal or not
  assert.ok(reason("X=1 rm -rf x").startsWith("matches the destructive veto /\\brm\\b/i"));
  assert.ok(reason("PATH=/tmp; git diff --ext-diff").startsWith("matches the destructive veto /"));
  // only the first line of the offending command, cut to 100 characters
  assert.equal(
    reason(`ls; python -c '${"x".repeat(200)}'\nmore`),
    `not allowlisted: python -c '${"x".repeat(89)}…`,
  );
  assert.deepEqual(readOnlyBashVerdict("git status"), { allowed: true });
});
