// The command-position walker: the `commands` matrix (every simple command at every command
// position), the refusal matrix, and the `segments` matrix (incl. lenient continuation past a
// refusal). TS literals: "\n" is a real newline, "\\" one backslash. See commandPositions.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type CommandRefusal,
  commandPositions,
  REFUSAL_REASONS,
  splitTopLevelSegments,
} from "./commandPositions.ts";

function commandsOf(input: string): readonly string[] | string {
  const result = commandPositions(input);
  return result.ok ? result.commands : `refused: ${result.refusal}`;
}

const COMMANDS: [string, string[]][] = [
  // sequencing + redirections carrying their operand
  ["ls -la", ["ls -la"]],
  ["a; b && c || d | e", ["a", "b", "c", "d", "e"]],
  ["cat a |& grep b", ["cat a", "grep b"]],
  ["cd x\nls", ["cd x", "ls"]],
  ["echo ok & ls", ["echo ok", "ls"]],
  ["cat x 2>&1", ["cat x 2>&1"]],
  ["cat x &>/dev/null", ["cat x &>/dev/null"]],
  ["echo x >&2", ["echo x >&2"]],
  // leading redirections: the operand is never the command
  ["< README.md wc -l", ["wc -l"]],
  ['<<< "text" wc -c', ["wc -c"]],
  ["2>/dev/null ls", ["ls"]],
  ["<echo python -c pass", ["python -c pass"]],
  ["<<< echo python -c pass", ["python -c pass"]],
  ["< $(pwd)/f cat", ["pwd", "cat"]],
  ["timeout 30 <in rg foo", ["rg foo"]],
  ["echo 2 > f", ["echo 2 > f"]],
  // substitutions: nested text stays inside the enclosing command's text
  [
    "cd $(git rev-parse --show-toplevel) && rg foo",
    ["cd $(git rev-parse --show-toplevel)", "git rev-parse --show-toplevel", "rg foo"],
  ],
  ["echo `pwd`", ["echo `pwd`", "pwd"]],
  ['echo "$(pwd)"', ['echo "$(pwd)"', "pwd"]],
  ['echo "$(echo "a")"', ['echo "$(echo "a")"', 'echo "a"']],
  ["diff <(sort a) <(sort b)", ["diff <(sort a) <(sort b)", "sort a", "sort b"]],
  ["echo '$(pwd)'", ["echo '$(pwd)'"]],
  ["echo \\`", ["echo \\`"]],
  // ANSI-C quoting: `\'` does not close; no ANSI-C inside double quotes
  ["echo $'a\\'b'; ls", ["echo $'a\\'b'", "ls"]],
  ["echo $'\\''; python -c pass # '", ["echo $'\\''", "python -c pass # '"]],
  ["echo \"$'a'\"; ls", ["echo \"$'a'\"", "ls"]],
  // assignment prefixes
  ['EVID=$(cat x); echo "$EVID"', ["cat x", 'echo "$EVID"']],
  ['f="/a b/c"; sed -n \'1p\' "$f"', ["sed -n '1p' \"$f\""]],
  ["F=~/x; wc -l $F", ["wc -l $F"]],
  ["X=1 Y=2 grep foo f", ["grep foo f"]],
  ["A=1", []],
  ["A+=b ls", ["ls"]],
  // keywords
  ['for f in agents/*.md; do wc -l "$f"; done', ['wc -l "$f"']],
  ['for f in $(ls); do cat "$f"; done', ["ls", 'cat "$f"']],
  ["for n in 1 2\ndo\necho $n\ndone", ["echo $n"]],
  ["for f; do ls; done", ["ls"]],
  ["while grep -q x f; do cat f; done", ["grep -q x f", "cat f"]],
  [
    "if grep -q x f; then cat f; elif ls; then pwd; else id; fi",
    ["grep -q x f", "cat f", "ls", "pwd", "id"],
  ],
  ["! grep -q x f", ["grep -q x f"]],
  ["{ cat a; cat b; }", ["cat a", "cat b"]],
  ["while read l; do echo; done < f", ["read l", "echo"]],
  // wrappers: the entry starts at the wrapped word; a bare wrapper is its own entry
  ["env X=1 rg foo", ["rg foo"]],
  ["env", ["env"]],
  ["env -i", ["env -i"]],
  ["env -u X -- rg", ["rg"]],
  ["env | grep PERK", ["env", "grep PERK"]],
  ["timeout 30 rg foo", ["rg foo"]],
  ["timeout 30", ["timeout 30"]],
  ["timeout -k 5 30s rg", ["rg"]],
  ["timeout --signal=KILL 1.5m rg", ["rg"]],
  ["xargs -0 -n1 grep -l foo", ["grep -l foo"]],
  ["xargs -I{} wc -l {}", ["wc -l {}"]],
  ["xargs -rn1 -- wc", ["wc"]],
  ["find . | xargs", ["find .", "xargs"]],
  ["nice -n 5 rg", ["rg"]],
  ["nice -5 rg", ["rg"]],
  ["nice --adjustment=5 rg", ["rg"]],
  ["time rg", ["rg"]],
  ["time -p rg", ["rg"]],
  ["nohup rg", ["rg"]],
  ["command rg foo", ["rg foo"]],
  ["command -p rg foo", ["rg foo"]],
  ["command -v python", ["command -v python"]],
  ["command -pV x", ["command -pV x"]],
  ["env X=1 timeout 5 rg", ["rg"]],
  ["env - rg", ["rg"]],
  ["env timeout 5 nice -n 1 time -p nohup command rg foo", ["rg foo"]],
  // a wrapper chain that reaches no command word is its own command, also past assignments…
  ["env -i FOO=bar", ["env -i FOO=bar"]],
  ["env X=1 timeout 5", ["timeout 5"]],
  // …and once xargs is in the chain it is xargs's own: its input supplies the command
  ["ls | xargs env", ["ls", "xargs env"]],
  ["ls | xargs env X=1", ["ls", "xargs env X=1"]],
  ["env xargs env", ["xargs env"]],
  // exec forms: the exec'd text runs to the enclosing command's end
  ["find . -exec grep -l foo {} \\;", ["find . -exec grep -l foo {} \\;", "grep -l foo {} \\;"]],
  [
    "find . -exec grep x {} \\; -execdir wc -l {} +",
    [
      "find . -exec grep x {} \\; -execdir wc -l {} +",
      "grep x {} \\; -execdir wc -l {} +",
      "wc -l {} +",
    ],
  ],
  ["find . -ok rm {} \\;", ["find . -ok rm {} \\;", "rm {} \\;"]],
  ["find . -okdir rm {} \\;", ["find . -okdir rm {} \\;", "rm {} \\;"]],
  ["fd -e py -x wc -l", ["fd -e py -x wc -l", "wc -l"]],
  ["fd --exec-batch grep foo", ["fd --exec-batch grep foo", "grep foo"]],
  ["fd -X grep foo", ["fd -X grep foo", "grep foo"]],
  ["fd --exec grep foo", ["fd --exec grep foo", "grep foo"]],
  [
    "find . -exec env python -c pass {} \\;",
    ["find . -exec env python -c pass {} \\;", "python -c pass {} \\;"],
  ],
  [
    "find . -exec env X=1 grep -l foo {} \\;",
    ["find . -exec env X=1 grep -l foo {} \\;", "grep -l foo {} \\;"],
  ],
  [
    "find . -exec timeout 5 python {} \\;",
    ["find . -exec timeout 5 python {} \\;", "python {} \\;"],
  ],
  ["fd -x env python", ["fd -x env python", "python"]],
  // `{}` after a wrapper is a plain word at a command position, so it opens the entry (find
  // substitutes a path there — the allowlist then refuses running the found file)…
  ["find . -exec env {} \\;", ["find . -exec env {} \\;", "{} \\;"]],
  // …and a bare wrapper at an exec position is its own entry, to the enclosing command's end
  ["find . -exec env", ["find . -exec env", "env"]],
  [
    "find . -exec nice -n 5 wc -l {} \\; -exec cat {} \\;",
    [
      "find . -exec nice -n 5 wc -l {} \\; -exec cat {} \\;",
      "wc -l {} \\; -exec cat {} \\;",
      "cat {} \\;",
    ],
  ],
  // exec flags are recognized after quote removal (what find receives)
  ["find . '-exec' grep x {} \\;", ["find . '-exec' grep x {} \\;", "grep x {} \\;"]],
  // heredocs: a literal body is data; an expanding body's substitutions are command positions
  ["cat <<'EOF'\nline one\n$(python -c x)\nEOF", ["cat <<'EOF'"]],
  ["cat <<EOF\n$(echo hi)\nEOF", ["cat <<EOF", "echo hi"]],
  ["cat <<-EOF\n\tbody\n\tEOF\nls", ["cat <<-EOF", "ls"]],
  ["cat <<'EOF' | wc -c\nbody\nEOF", ["cat <<'EOF'", "wc -c"]],
  ["cat <<A <<'B'\na\nA\nb\nB\nls", ["cat <<A <<'B'", "ls"]],
  ['cat <<"EOF"\n$(python -c x)\nEOF', ['cat <<"EOF"']],
  ["cat <<\\EOF\n$(python -c x)\nEOF", ["cat <<\\EOF"]],
  // bash joins `\`-newline in an expanding body BEFORE the terminator comparison
  ["cat <<EOF\nEO\\\nF\npython -c pass\nEOF", ["cat <<EOF", "python -c pass", "EOF"]],
  ["cat <<'EOF'\nEO\\\nF\npython -c pass\nEOF", ["cat <<'EOF'"]],
  ["cat <<EOF\nline \\\ncontinued $(echo hi)\nEOF", ["cat <<EOF", "echo hi"]],
  ["cat <<EOF\n\\$(pwd)\nEOF", ["cat <<EOF"]],
  // a `\`-newline in the delimiter is removed, not quoting: the body still expands
  ["cat <<E\\\nOF\n$(pwd)\nEOF", ["cat <<E\\\nOF", "pwd"]],
  ["cat <<EOF\n'$(pwd)'\nEOF", ["cat <<EOF", "pwd"]],
  ["echo $(cat <<EOF\nhi\nEOF\n)", ["echo $(cat <<EOF\nhi\nEOF\n)", "cat <<EOF"]],
  // comments / escapes / continuation
  ["# list\nls -la", ["ls -la"]],
  ["ls # note; python", ["ls # note; python"]],
  ["echo a#b; ls", ["echo a#b", "ls"]],
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["echo ${#x}", ["echo ${#x}"]],
  // ${…} is one unit: no word splitting, operators or comments inside
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["echo ${x:-a #b}; python", ["echo ${x:-a #b}", "python"]],
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["echo ${x/;/,}; ls", ["echo ${x/;/,}", "ls"]],
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["V=${x:-a $(pwd)} ls", ["pwd", "ls"]],
  ["echo $(#c\nls)", ["echo $(#c\nls)", "ls"]],
  ['echo "a\\"" ; ls', ['echo "a\\""', "ls"]],
  ["echo a\\;b", ["echo a\\;b"]],
  ["rg foo \\\n  --glob '*.ts'", ["rg foo \\\n  --glob '*.ts'"]],
  ["ls \\\n-la", ["ls \\\n-la"]],
  ["ls; \\\nwc", ["ls", "wc"]],
  [
    "ast-grep scan --inline-rules 'id: x\nlanguage: ts\nrule: {pattern: $A}'",
    ["ast-grep scan --inline-rules 'id: x\nlanguage: ts\nrule: {pattern: $A}'"],
  ],
  ["echo 'a|b'; echo \"c&&d\"", ["echo 'a|b'", 'echo "c&&d"']],
  // empty commands (bash syntax errors — nothing runs) are skipped, not refused
  ["ls;;", ["ls"]],
  ["& ls", ["ls"]],
  ["ls | ", ["ls"]],
  ["", []],
  ["# only a comment", []],
];

test("commandPositions: every simple command at every command position", () => {
  for (const [input, expected] of COMMANDS) assert.deepEqual(commandsOf(input), expected, input);
});

const REFUSALS: [string, CommandRefusal][] = [
  ["echo 'a", "unterminated-quote"],
  ['echo "a', "unterminated-quote"],
  ["echo $'a\\'", "unterminated-quote"],
  // a backtick substitution ends at the first unescaped backtick, quotes notwithstanding
  ["echo `true '`; python -c x #'`", "unterminated-quote"],
  ["echo $(ls", "unterminated-substitution"],
  ["echo `ls", "unterminated-substitution"],
  ["diff <(sort a", "unterminated-substitution"],
  ["cat <<EOF\nbody", "unterminated-heredoc"],
  ["echo $(cat <<EOF)\nx\nEOF", "unterminated-heredoc"],
  ["ls )", "unbalanced-close"],
  ["$CMD", "dynamic-command-word"],
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["${CMD} x", "dynamic-command-word"],
  ['"$CMD" x', "dynamic-command-word"],
  ["'ls'", "dynamic-command-word"],
  ["\\ls", "dynamic-command-word"],
  ["$(cat cmd)", "dynamic-command-word"],
  ["`cat cmd`", "dynamic-command-word"],
  ["foo$(bar)", "dynamic-command-word"],
  ["$'ls'", "dynamic-command-word"],
  ["ls; $EDITOR x", "dynamic-command-word"],
  ["find . -exec $X {} \\;", "dynamic-command-word"],
  ["env $X", "dynamic-command-word"],
  ["<in $CMD", "dynamic-command-word"],
  // a continuation inside a word makes it non-plain
  ["pyth\\\non -c x", "dynamic-command-word"],
  ["env -S 'python -c x' echo", "wrapper-usage"],
  ["env -S'python -c x' echo", "wrapper-usage"],
  ["env -C dir ls", "wrapper-usage"],
  ["time -o out rg", "wrapper-usage"],
  ["timeout rg foo", "wrapper-usage"],
  ["timeout -k 5", "wrapper-usage"],
  ["xargs -a list grep foo", "wrapper-usage"],
  ["nice -n", "wrapper-usage"],
  ["find . -exec env -S x {} \\;", "wrapper-usage"],
  // the words a wrapper consumes must be static: an expansion could split into the command
  ["env -u $PAYLOAD ls", "wrapper-usage"],
  ["env -u$X ls", "wrapper-usage"],
  ['nice -n "$N" rg', "wrapper-usage"],
  ["env FOO=$(cat x) rg", "wrapper-usage"],
  ["(cd x && ls)", "unmodeled-syntax"],
  ["foo() { ls; }", "unmodeled-syntax"],
  ["A=(1 2)", "unmodeled-syntax"],
  ["echo $((1+1))", "unmodeled-syntax"],
  ["case x in a) ls;; esac", "unmodeled-syntax"],
  ["select x in a; do ls; done", "unmodeled-syntax"],
  ["[[ -f x ]] && cat x", "unmodeled-syntax"],
  ["for in x; do ls; done", "unmodeled-syntax"],
  ["for f x; do ls; done", "unmodeled-syntax"],
  // a `for` header ends only at `;` or a newline — also when it sits at an exec position
  ["for", "unmodeled-syntax"],
  ["find . -exec for x in \\; -exec python {} \\;", "unmodeled-syntax"],
  ["ls \\", "unmodeled-syntax"],
  ["echo (a)", "unmodeled-syntax"],
  ["cat <", "unmodeled-syntax"],
  ["ls > ", "unmodeled-syntax"],
  ["cat <<\nx", "unmodeled-syntax"],
  // a delimiter whose quote-removed value this lexer cannot compute
  ["cat <<$'EOF'\nx\nEOF", "unmodeled-syntax"],
  ["cat <<$X\nx\n$X", "unmodeled-syntax"],
  // bash reads `'` inside a double-quoted ${…} per operator and POSIX mode
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  ["echo \"${x:-'}'}\"", "unmodeled-syntax"],
  ["echo ${x", "unterminated-substitution"],
  ["echo `echo \\`python -c pass\\``", "unmodeled-syntax"],
  ["echo `echo \\$(ls)`", "unmodeled-syntax"],
];

test("commandPositions: refusals", () => {
  for (const [input, refusal] of REFUSALS) {
    const result = commandPositions(input);
    assert.equal(result.ok ? "ok" : result.refusal, refusal, input);
  }
});

test("REFUSAL_REASONS: one non-empty line per refusal", () => {
  const all: CommandRefusal[] = [
    "unterminated-quote",
    "unterminated-substitution",
    "unterminated-heredoc",
    "unbalanced-close",
    "dynamic-command-word",
    "wrapper-usage",
    "unmodeled-syntax",
  ];
  assert.deepEqual(Object.keys(REFUSAL_REASONS).sort(), [...all].sort());
  for (const refusal of all) {
    const reason = REFUSAL_REASONS[refusal];
    assert.ok(reason.length > 0 && !reason.includes("\n"), refusal);
  }
});

const SEGMENTS: [string, string[]][] = [
  ["a; b && c || d | e", ["a", "b", "c", "d", "e"]],
  ["cat a &> f", ["cat a &> f"]],
  ["grep -iE 'a|b' f", ["grep -iE 'a|b' f"]],
  ['echo "x && y"; ls', ['echo "x && y"', "ls"]],
  ["  ls ;; ; ", ["ls"]],
  ["", []],
  ["cd x\nls", ["cd x", "ls"]],
  ["echo ok & ls", ["echo ok", "ls"]],
  ["cat a |& grep b", ["cat a", "grep b"]],
  ["find . -exec grep x {} \\;", ["find . -exec grep x {} \\;"]],
  ["echo $(ls; ls)", ["echo $(ls; ls)"]],
  ["rg foo \\\n --glob x", ["rg foo \\\n --glob x"]],
  // every heredoc body is its own segment (a quoted one may be a nested shell's script)
  ["cat <<'EOF'\nls\nEOF\nwc", ["cat <<'EOF'", "ls", "wc"]],
  ["bash <<'EOF'\nfind . -type f\nEOF", ["bash <<'EOF'", "find . -type f"]],
  ["cat <<EOF\n$(ls)\nEOF\nwc", ["cat <<EOF", "$(ls)", "wc"]],
  ["sh -c 'find . -type f; find . -maxdepth 1'", ["sh -c 'find . -type f; find . -maxdepth 1'"]],
  // lenient continuation: a refusal never truncates the view
  ["echo 'a; b", ["echo 'a; b"]],
  ["env -Q x; grep -rn foo .", ["env -Q x", "grep -rn foo ."]],
  ["$CMD; find . -type f", ["$CMD", "find . -type f"]],
  ["(find . -type f)", ["(find . -type f)"]],
  ["echo `echo \\`ls\\`` ; grep -rn foo .", ["echo `echo \\`ls\\``", "grep -rn foo ."]],
  ["cat <<EOF\nbody", ["cat <<EOF", "body"]],
  ["A=(1 2); find . -type f", ["A=(1 2)", "find . -type f"]],
];

test("segments: top-level slices, identical through splitTopLevelSegments", () => {
  for (const [input, expected] of SEGMENTS) {
    assert.deepEqual(commandPositions(input).segments, expected, input);
    assert.deepEqual(splitTopLevelSegments(input), expected, input);
  }
});

test("segments: a later scan survives an earlier unmodeled construct", () => {
  const input = "case x in a) ls;; esac\nfind . -type f";
  assert.equal(commandPositions(input).ok, false);
  assert.equal(splitTopLevelSegments(input).at(-1), "find . -type f");
});

// The module header's accepted leniencies — shapes a model would not reach by accident — pinned
// so any tightening is a deliberate change.
test("accepted leniencies stay as recorded", () => {
  // a command fd supplies at run time is invisible: `env` runs each found path
  assert.deepEqual(commandsOf("fd -x env"), ["fd -x env", "env"]);
  // only the exact exec words of the simple command's own find/fd open a position…
  assert.deepEqual(commandsOf("fd -Hx python"), ["fd -Hx python"]);
  assert.deepEqual(commandsOf("find . -exec fd -x python \\;"), [
    "find . -exec fd -x python \\;",
    "fd -x python \\;",
  ]);
  // …as they read before expansion (ANSI-C quoting or `$X` hides one)
  assert.deepEqual(commandsOf("find . $'-exec' python -c pass \\;"), [
    "find . $'-exec' python -c pass \\;",
  ]);
});
