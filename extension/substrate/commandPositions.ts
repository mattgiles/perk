// The read-only gate's command-position walker. Pure — no Pi imports, registers nothing.
//
// Bash runs a command at every command position, not only after `;` `|` `&&` `||`: after a newline
// or a lone `&`, inside `$(…)`/backticks (also within double quotes) and `<(…)`/`>(…)`, after
// `NAME=value` prefixes and leading redirections, after shell keywords and wrappers, and at
// `find -exec`/`fd -x`. `commandPositions` finds every one and returns the text of the simple
// command there, so the gate can hold each command word to its allowlist.
//
// Two phases. The lexer knows only bash's token rules — quotes (incl. ANSI-C `$'…'`), escapes,
// line continuations, comments, operators, redirections and their operands, heredocs (incl. the
// `\`-newline join in an expanding body), `${…}` as one unit, and substitutions — and builds a
// token tree; a backtick body and an expanding heredoc body are lexed as their own inputs, as bash
// re-parses them. The dispatcher knows only the command-position rules: assignment prefixes, a
// fixed keyword set, the wrapper flag tables, find/fd exec flags. Lexical refusals ride on tree
// nodes and never stop the lexer, so `segments` (the scan-timeout classifier's view) always covers
// the whole input; the first refusal in walk order (a node before its children) wins. The lexer
// also builds the veto view (`vetoText`): every substitution, `${…}` and heredoc body collapsed out
// of the text that holds it, each substitution's own text appended on a line of its own — so the
// destructive veto reads each command's words without a nested operator in the way, reads what
// bash executes inside a substitution exactly like top-level text, and never reads heredoc data.
//
// Not a shell parser: it refuses what it does not model — fail-closed on the unknown, never on the
// modeled — and validates no compound-command structure. Accepted leniencies, recorded rather than
// chased (shapes a model would not reach by accident): in-program writers inside allowlisted
// commands' program text (`awk '{print > "f"}'`, `awk system()`, `sed 'e …'`/`sed 'w …'`);
// `find -fprint*`/`-fls` (argument-level writers for the veto list, beside `find -delete`); a
// command fd supplies at run time (`fd -x env` runs each found path); exec flags other than the
// exact, pre-expansion words of the simple command's own `find`/`fd` (`fd -Hx`, an exec'd
// command's own exec flag, `find . $'-exec' …`); words taken lexically, so an unquoted glob or
// brace expansion counts as one word; `\\` inside backticks (bash halves it before the body
// parses); bash syntax errors that run nothing (empty commands, an unbalanced `if`/`fi`).
// Recursion follows nesting depth: pathological nesting throws, which both consumers contain (the
// gate fails closed, the classifier fails open).

export type CommandRefusal =
  | "unterminated-quote"
  | "unterminated-substitution"
  | "unterminated-heredoc"
  | "unbalanced-close"
  | "dynamic-command-word"
  | "wrapper-usage"
  | "unmodeled-syntax";

/** One human-readable line per refusal — the gate's `Reason:` text. */
export const REFUSAL_REASONS: Readonly<Record<CommandRefusal, string>> = {
  "unterminated-quote": "unterminated quote",
  // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
  "unterminated-substitution": "unterminated $(…), ${…}, <(…), >(…) or backtick substitution",
  "unterminated-heredoc": "heredoc never terminated",
  "unbalanced-close": "unbalanced ) or backtick",
  "dynamic-command-word":
    "a command word must be a plain word ($VAR, quoted, escaped or substituted command words are refused)",
  "wrapper-usage":
    "unsupported wrapper usage (unknown flag, missing flag argument, or missing/invalid timeout duration)",
  "unmodeled-syntax":
    "unsupported shell syntax (subshell, function, array, arithmetic, case/select/[[, redirection without operand, nested backtick escape, trailing backslash, or quoting this gate cannot resolve)",
};

export type CommandPositions =
  | { ok: true; commands: readonly string[]; segments: readonly string[]; vetoText: string }
  | { ok: false; refusal: CommandRefusal; segments: readonly string[]; vetoText: string };

/**
 * A collapsed span's stand-in: one plain word, so the enclosing command keeps its word count and
 * an argument walk crosses it; a heredoc body collapses to nothing (its lines are data).
 */
const COLLAPSED = "_";

/** One pass over the command text: every simple-command text at every command position, the top-level segments and the veto view. */
export function commandPositions(command: string): CommandPositions {
  const lexer = new Lexer(command);
  const top = lexer.frame(null);
  const segments = segmentsOf(top);
  const vetoText = [collapse(command, 0, command.length, lexer.children), ...lexer.pieces].join(
    "\n",
  );
  const dispatch = new Dispatcher();
  dispatch.frame(top);
  return dispatch.refusal === null
    ? { ok: true, commands: dispatch.commands, segments, vetoText }
    : { ok: false, refusal: dispatch.refusal, segments, vetoText };
}

/** The top-level segments only (the scan-timeout classifier's view) — lexing alone, always covering the whole input. */
export function splitTopLevelSegments(command: string): string[] {
  return segmentsOf(new Lexer(command).frame(null));
}

// --- lexing: bash's token rules → a token tree --------------------------------------------------

/** A word, built as it is lexed; its nested command frames and any lexical refusal ride on it. */
class Word {
  start = 0;
  text = "";
  /** No quote, escape or expansion anywhere in the word. */
  plain = true;
  /** The unquoted literal characters before the first non-literal part. */
  prefix = "";
  /** The quote-removed value; null once the word holds an expansion. */
  value: string | null = "";
  /** Any quote or escape — what makes a heredoc delimiter literal. */
  quoted = false;
  frames: Frame[] = [];
  refusal: CommandRefusal | undefined;

  literal(s: string): void {
    if (this.plain) this.prefix += s;
    if (this.value !== null) this.value += s;
  }
  quote(s: string): void {
    this.plain = false;
    this.quoted = true;
    if (this.value !== null) this.value += s;
  }
  expand(frame?: Frame): void {
    this.plain = false;
    this.value = null;
    if (frame !== undefined) this.frames.push(frame);
  }
  /** A `\`-newline inside the word: bash removes it (no quoting), but the word is no longer plain. */
  continued(): void {
    this.plain = false;
  }
  refuse(refusal: CommandRefusal): void {
    this.refusal ??= refusal;
  }
}

type Token =
  | { kind: "word"; word: Word }
  | { kind: "op"; op: string; start: number; end: number }
  | { kind: "redirect"; operand: Word | null }
  | { kind: "body"; end: number; expanding: boolean; content: Word };

/** A command list: the top level, a `$(…)`/`<(…)`/`>(…)` body, a backtick body, a heredoc body's substitution. */
type Frame = { src: string; tokens: Token[]; end: number; refusal?: CommandRefusal };

type Heredoc = { tag: string; strip: boolean; expanding: boolean };

const SEQUENCING = /;;|;|\|\||\|&|\||&&|&(?!>)/y;
/** Longest match first; `<(`/`>(` are process substitutions, not redirections. */
const REDIRECTION = /\d*(?:<<<|<<-|<<|<>|<&|<(?!\()|>>|>\||>&|>(?!\())|&>>?/y;
const VARIABLE = /[A-Za-z_][A-Za-z0-9_]*|[0-9?$#@*!-]/y;

class Lexer {
  src: string;
  i = 0;
  /** `)` while lexing a `$(`/`<(`/`>(` body. */
  closer: ")" | null = null;
  /** The collapsible spans completed at the current nesting level (a substitution swaps its own list in). */
  children: Span[] = [];
  /** Every substitution's own text with its children collapsed, inner before outer — the veto view's appended lines. */
  pieces: string[] = [];
  constructor(src: string) {
    this.src = src;
  }

  private match(re: RegExp): string | null {
    re.lastIndex = this.i;
    return re.exec(this.src)?.[0] ?? null;
  }

  /** Blanks and `\`-newline continuations between words. */
  private skipBlanks(): void {
    for (;;) {
      const c = this.src[this.i];
      if (c === " " || c === "\t") this.i++;
      else if (c === "\\" && this.src[this.i + 1] === "\n") this.i += 2;
      else return;
    }
  }

  frame(closer: ")" | null): Frame {
    const outer = this.closer;
    this.closer = closer;
    const tokens: Token[] = [];
    const heredocs: Heredoc[] = [];
    for (;;) {
      this.skipBlanks();
      const c = this.src[this.i];
      if (c === undefined || (c === ")" && closer === ")")) break;
      if (c === "#") {
        // Words are maximal, so a `#` here starts a word — bash's comment rule.
        const newline = this.src.indexOf("\n", this.i);
        this.i = newline === -1 ? this.src.length : newline;
      } else if (c === "\n") {
        tokens.push({ kind: "op", op: c, start: this.i, end: this.i + 1 });
        this.i++;
        for (const heredoc of heredocs.splice(0)) tokens.push(this.body(heredoc));
      } else {
        const op = this.match(SEQUENCING);
        const redirect = op === null ? this.match(REDIRECTION) : null;
        if (op !== null) {
          tokens.push({ kind: "op", op, start: this.i, end: this.i + op.length });
          this.i += op.length;
        } else if (redirect !== null) {
          this.i += redirect.length;
          const operand = this.operand();
          if (operand !== null && /^\d*<<-?$/.test(redirect)) {
            // Bash ends the body at the quote-removed delimiter; one this lexer cannot compute
            // (an expansion or ANSI-C quoting in it) is refused rather than guessed.
            if (operand.value === null) operand.refuse("unmodeled-syntax");
            heredocs.push({
              tag: operand.value ?? operand.text,
              strip: redirect.endsWith("-"),
              expanding: !operand.quoted,
            });
          }
          tokens.push({ kind: "redirect", operand });
        } else tokens.push({ kind: "word", word: this.word() });
      }
    }
    const frame: Frame = { src: this.src, tokens, end: this.i };
    if (closer === ")" && this.i >= this.src.length) frame.refusal = "unterminated-substitution";
    else if (heredocs.length > 0) frame.refusal = "unterminated-heredoc";
    this.closer = outer;
    return frame;
  }

  /** A redirection's operand: the next word, or null when an operator, a comment or the end follows. */
  private operand(): Word | null {
    this.skipBlanks();
    const c = this.src[this.i];
    if (c === undefined || "\n;|&)#".includes(c)) return null;
    if ((c === "<" || c === ">") && this.src[this.i + 1] !== "(") return null;
    return this.word();
  }

  private word(): Word {
    const word = new Word();
    word.start = this.i;
    for (;;) {
      const c = this.src[this.i];
      if (c === undefined || " \t\n;|&".includes(c)) break;
      if (c === "<" || c === ">") {
        if (this.src[this.i + 1] !== "(") break;
        this.i += 2;
        word.expand(this.subframe());
      } else if (c === ")" && this.closer === ")") break;
      else if (c === "(" || c === ")") {
        // Bare subshells, function definitions, arrays and case patterns are not modeled.
        word.refuse(c === "(" ? "unmodeled-syntax" : "unbalanced-close");
        word.literal(c);
        this.i++;
      } else if (c === "\\") {
        const next = this.src[this.i + 1];
        if (next === undefined) word.refuse("unmodeled-syntax");
        if (next === "\n") word.continued();
        else word.quote(next ?? "");
        this.i += 2;
      } else if (c === "'") this.single(word);
      else if (c === '"') {
        this.i++;
        word.quote("");
        this.double(word, '"');
      } else if (c === "$") this.dollar(word, false);
      else if (c === "`") this.backquote(word);
      else {
        word.literal(c);
        this.i++;
      }
    }
    this.i = Math.min(this.i, this.src.length);
    word.text = this.src.slice(word.start, this.i);
    return word;
  }

  /** `$(`, `<(` or `>(` consumed: lex to the matching `)`. */
  private subframe(): Frame {
    const start = this.i - 2;
    const outer = this.children;
    this.children = [];
    const frame = this.frame(")");
    if (this.i < this.src.length) this.i++;
    this.pieces.push(collapse(this.src, start, this.i, this.children));
    this.children = outer;
    outer.push({ start, end: this.i, stand: COLLAPSED });
    return frame;
  }

  private single(word: Word): void {
    const close = this.src.indexOf("'", this.i + 1);
    if (close === -1) word.refuse("unterminated-quote");
    const end = close === -1 ? this.src.length : close;
    word.quote(this.src.slice(this.i + 1, end));
    this.i = end + 1;
  }

  /** Double-quoted text up to `"`, or (closer null) an expanding heredoc body to its end. */
  double(word: Word, closer: '"' | null): void {
    for (;;) {
      const c = this.src[this.i];
      if (c === undefined) {
        if (closer !== null) word.refuse("unterminated-quote");
        return;
      }
      if (c === closer) {
        this.i++;
        return;
      }
      if (c === "\\") {
        const next = this.src[this.i + 1];
        const escapes = next !== undefined && '$`"\\\n'.includes(next);
        word.quote(escapes ? next.replace("\n", "") : c);
        this.i += escapes ? 2 : 1;
      } else if (c === "$") this.dollar(word, true);
      else if (c === "`") this.backquote(word);
      else {
        word.quote(c);
        this.i++;
      }
    }
  }

  private dollar(word: Word, inDouble: boolean): void {
    const next = this.src[this.i + 1];
    if (next === "(" && this.src[this.i + 2] === "(") {
      word.refuse("unmodeled-syntax"); // arithmetic
      word.expand();
      this.i += 3;
    } else if (next === "(") {
      this.i += 2;
      word.expand(this.subframe());
    } else if (next === "{") {
      this.i += 2;
      this.brace(word, inDouble);
    } else if (next === "'" && !inDouble) {
      this.i += 2;
      this.ansiC(word);
    } else if (next === '"' && !inDouble) {
      this.i += 2;
      word.expand();
      this.double(word, '"');
    } else {
      word.expand();
      this.i++;
      this.i += this.match(VARIABLE)?.length ?? 0;
    }
  }

  /** `${` consumed: one unit up to its `}` — no word splitting, operators or comments inside. */
  private brace(word: Word, inDouble: boolean): void {
    word.expand();
    const start = this.i - 2;
    for (;;) {
      const c = this.src[this.i];
      if (c === undefined) {
        word.refuse("unterminated-substitution");
        this.children.push({ start, end: this.src.length, stand: COLLAPSED });
        return;
      }
      if (c === "}") {
        this.i++;
        this.children.push({ start, end: this.i, stand: COLLAPSED });
        return;
      }
      if (c === "\\") this.i += 2;
      else if (c === "'" && inDouble) {
        // Bash's reading of `'` inside a double-quoted `${…}` depends on the operator and POSIX mode.
        word.refuse("unmodeled-syntax");
        this.i++;
      } else if (c === "'") this.single(word);
      else if (c === '"') {
        this.i++;
        this.double(word, '"');
      } else if (c === "$") this.dollar(word, inDouble);
      else if (c === "`") this.backquote(word);
      else this.i++;
    }
  }

  /** `$'` consumed: ANSI-C quoting — `\` escapes whatever follows, nothing expands. */
  private ansiC(word: Word): void {
    word.quote("");
    word.expand();
    for (;;) {
      const c = this.src[this.i];
      if (c === undefined) {
        word.refuse("unterminated-quote");
        return;
      }
      this.i += c === "\\" ? 2 : 1;
      if (c === "'") return;
    }
  }

  /**
   * Bash ends a backtick substitution at the first unescaped backtick — quotes notwithstanding —
   * strips the backslash from `` \` `` and `\$` in the body (the nested-substitution syntax,
   * refused here), then parses the body as its own input.
   */
  private backquote(word: Word): void {
    let close = this.i + 1;
    while (close < this.src.length && this.src[close] !== "`")
      close += this.src[close] === "\\" ? 2 : 1;
    const body = this.src.slice(this.i + 1, close);
    if (/\\[`$]/.test(body)) word.refuse("unmodeled-syntax");
    if (close >= this.src.length) word.refuse("unterminated-substitution");
    const inner = new Lexer(body);
    word.expand(inner.frame(null));
    const end = Math.min(close + 1, this.src.length);
    // The body is a raw slice, so its spans shift by its offset into this input.
    const offset = this.i + 1;
    const spans = inner.children.map((s) => ({
      ...s,
      start: s.start + offset,
      end: s.end + offset,
    }));
    this.pieces.push(...inner.pieces, collapse(this.src, this.i, end, spans));
    this.children.push({ start: this.i, end, stand: COLLAPSED });
    this.i = end;
  }

  /**
   * A heredoc body, after the newline that ends its operator's line. An expanding body (unquoted
   * delimiter) is joined at `\`-newline before the terminator comparison, as bash does, and lexed
   * as double-quoted text; a literal body is data.
   */
  private body(heredoc: Heredoc): Token {
    const start = this.i;
    let end = this.src.length;
    const lines: string[] = [];
    let terminated = false;
    while (this.i < this.src.length && !terminated) {
      const lineStart = this.i;
      let line = "";
      for (let c = this.src[this.i++]; c !== undefined && c !== "\n"; c = this.src[this.i++]) {
        if (heredoc.expanding && c === "\\" && this.i < this.src.length) {
          const next = this.src[this.i++] as string;
          line += next === "\n" ? "" : c + next;
        } else line += c;
      }
      terminated = (heredoc.strip ? line.replace(/^\t+/, "") : line) === heredoc.tag;
      if (terminated) end = lineStart;
      else lines.push(line);
    }
    this.i = Math.min(this.i, this.src.length);
    const content = new Word();
    content.text = lines.join("\n");
    if (!terminated) content.refuse("unterminated-heredoc");
    if (heredoc.expanding) {
      const inner = new Lexer(content.text);
      inner.double(content, null);
      this.pieces.push(...inner.pieces);
    }
    this.children.push({ start, end, stand: "" });
    return { kind: "body", end: this.i, expanding: heredoc.expanding, content };
  }
}

/** A span of `src` the veto view collapses to `stand`. */
type Span = { start: number; end: number; stand: string };

/**
 * `src[start, end)` with each outermost span inside it replaced by its stand-in. Spans may nest (a
 * substitution inside `${…}` completes first); a span inside an earlier one is already covered.
 */
function collapse(src: string, start: number, end: number, spans: readonly Span[]): string {
  let text = "";
  let at = start;
  for (const span of [...spans].sort((a, b) => a.start - b.start || b.end - a.end)) {
    if (span.start < at || span.start < start || span.end > end) continue;
    text += src.slice(at, span.start) + span.stand;
    at = span.end;
  }
  return text + src.slice(at, end);
}

/**
 * Top-level slices between sequencing operators; every heredoc body is its own segment — a quoted
 * delimiter stops the outer shell's expansion, not an interpreter reading the body as a script.
 */
function segmentsOf(frame: Frame): string[] {
  const segments: string[] = [];
  const push = (text: string) => {
    if (text.trim() !== "") segments.push(text.trim());
  };
  let start = 0;
  for (const token of frame.tokens) {
    if (token.kind === "op") push(frame.src.slice(start, token.start));
    else if (token.kind === "body") push(token.content.text);
    if (token.kind === "op" || token.kind === "body") start = token.end;
  }
  push(frame.src.slice(start, frame.end));
  return segments;
}

// --- dispatch: command-position rules over the tree ---------------------------------------------

type WrapperSpec = {
  /** flag → whether it takes an argument */
  flags: ReadonlyMap<string, boolean>;
  /** `timeout`: one duration word precedes the command. */
  duration?: true;
  /** `command`: a `v`/`V` flag makes it a query (its words are arguments). */
  query?: true;
  /** `nice`: `-N` is a flag. */
  numeric?: true;
  /** `env`: a lone `-` ends the flags. */
  dashEnds?: true;
  /** `xargs`: its input becomes its command's trailing arguments, so a bare chain after it is xargs's own. */
  appends?: true;
};

/** A getopt-style spec: `x` (short, no argument), `x:` (short, with argument), `--long` / `--long:` likewise. */
function wrapper(flags: string, traits: Omit<WrapperSpec, "flags"> = {}): WrapperSpec {
  const table = new Map<string, boolean>();
  for (const flag of flags.split(" ").filter(Boolean))
    table.set(flag.replace(/:$/, ""), flag.endsWith(":"));
  return { flags: table, ...traits };
}

/** Enumerated flags only: an unmodeled one (`env -S`, `time -o`, `xargs -a`, …) is refused. */
const WRAPPERS: ReadonlyMap<string, WrapperSpec> = new Map([
  ["env", wrapper("i u: --ignore-environment --unset:", { dashEnds: true })],
  [
    "timeout",
    wrapper("v s: k: --foreground --preserve-status --verbose --signal: --kill-after:", {
      duration: true,
    }),
  ],
  [
    "xargs",
    wrapper(
      "0 r t x o n: L: P: I: d: s: E: J: R: S: --null --no-run-if-empty --verbose --exit " +
        "--open-tty --max-args: --max-lines: --max-procs: --replace: --delimiter: --max-chars: --eof:",
      { appends: true },
    ),
  ],
  ["nice", wrapper("n: --adjustment:", { numeric: true })],
  ["time", wrapper("p")],
  ["nohup", wrapper("")],
  ["command", wrapper("p v V", { query: true })],
]);

const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*\+?=/;
const DURATION = /^\d+(\.\d+)?[smhd]?$/;
const OPENERS = new Set(["while", "until", "if", "then", "elif", "else", "do", "{", "!"]);
const CLOSERS = new Set(["fi", "done", "}"]);
const REFUSED = new Set(["case", "esac", "select", "function", "coproc", "[[", "]]", "in"]);
const EXEC_FLAGS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["find", new Set(["-exec", "-execdir", "-ok", "-okdir"])],
  ["fd", new Set(["-x", "--exec", "-X", "--exec-batch"])],
]);

type WrapperScan = {
  spec: WrapperSpec;
  start: number;
  pendingArgument: boolean;
  needsDuration: boolean;
  flagsDone: boolean;
};

type SimpleCommand = {
  state: "command" | "args" | "wrapper" | "for-name" | "for-in" | "for-words";
  /** Entries opened in this simple command; each runs to its end. */
  entries: { slot: number; start: number }[];
  /** The command word of its first entry — whose exec flags open further positions. */
  word: string | null;
  wrapper: WrapperScan | null;
  /**
   * Where a wrapper chain's own text starts while no command word has opened an entry: the
   * innermost wrapper, or the innermost `xargs` once one is in the chain (its input supplies the
   * command, so the chain is only as allowed as xargs itself).
   */
  fallback: { start: number; xargs: boolean } | null;
};

class Dispatcher {
  commands: string[] = [];
  refusal: CommandRefusal | null = null;

  refuse(refusal: CommandRefusal | undefined): void {
    if (refusal !== undefined) this.refusal ??= refusal;
  }

  frame(frame: Frame): void {
    this.refuse(frame.refusal);
    let cmd = fresh();
    for (const token of frame.tokens) {
      if (token.kind === "op") {
        this.close(cmd, frame, token.start, token.op);
        cmd = fresh();
      } else if (token.kind === "redirect") {
        // An operand is never the command: the state is left as it was.
        if (token.operand === null) this.refuse("unmodeled-syntax");
        else this.nested(token.operand);
      } else if (token.kind === "body") this.nested(token.content);
      else {
        this.nested(token.word);
        this.word(cmd, token.word);
      }
    }
    this.close(cmd, frame, frame.end, null);
  }

  private nested(word: Word): void {
    this.refuse(word.refusal);
    for (const frame of word.frames) this.frame(frame);
  }

  private close(cmd: SimpleCommand, frame: Frame, end: number, op: string | null): void {
    // A `for` header ends only at `;` or a newline, and only after its name.
    if (cmd.state.startsWith("for-") && (cmd.state === "for-name" || (op !== ";" && op !== "\n")))
      this.refuse("unmodeled-syntax");
    const scan = cmd.wrapper;
    if (scan !== null && (scan.pendingArgument || scan.needsDuration)) this.refuse("wrapper-usage");
    else if (cmd.fallback !== null) this.open(cmd, cmd.fallback.start, null); // a bare chain is its own command
    for (const { slot, start } of cmd.entries)
      this.commands[slot] = frame.src.slice(start, end).trim();
  }

  private open(cmd: SimpleCommand, start: number, word: string | null): void {
    cmd.entries.push({ slot: this.commands.push("") - 1, start });
    if (cmd.entries.length === 1) cmd.word = word;
    cmd.state = "args";
    cmd.wrapper = null;
    cmd.fallback = null;
  }

  private word(cmd: SimpleCommand, word: Word): void {
    const { state } = cmd;
    if (state === "command") this.command(cmd, word);
    else if (state === "wrapper") this.wrapped(cmd, cmd.wrapper as WrapperScan, word);
    else if (state === "args") {
      // An exec flag of the simple command's own find/fd opens a command position in it.
      if (word.value !== null && EXEC_FLAGS.get(cmd.word ?? "")?.has(word.value))
        cmd.state = "command";
    } else if (state === "for-name") {
      if (word.plain) cmd.state = "for-in";
      else this.refuse("unmodeled-syntax");
    } else if (state === "for-in") {
      if (word.plain && word.text === "in") cmd.state = "for-words";
      else this.refuse("unmodeled-syntax");
    }
    // for-words: the loop's words are data (their substitutions were already dispatched).
  }

  /** A word at a command position. */
  private command(cmd: SimpleCommand, word: Word): void {
    const text = word.text;
    if (ASSIGNMENT.test(word.prefix)) {
      // Any number of prefixes; the position stays. After a wrapper it is an argv word, which an
      // expansion could split into the command itself.
      if (cmd.fallback !== null && word.value === null) this.refuse("wrapper-usage");
      return;
    }
    if (!word.plain) this.refuse("dynamic-command-word");
    else if (REFUSED.has(text)) this.refuse("unmodeled-syntax");
    else if (text === "for") cmd.state = "for-name";
    else if (CLOSERS.has(text)) cmd.state = "args";
    else if (!OPENERS.has(text)) {
      const spec = WRAPPERS.get(text);
      if (spec === undefined) this.open(cmd, word.start, text);
      else {
        cmd.state = "wrapper";
        cmd.wrapper = {
          spec,
          start: word.start,
          pendingArgument: false,
          needsDuration: spec.duration === true,
          flagsDone: false,
        };
        if (spec.appends === true || cmd.fallback?.xargs !== true)
          cmd.fallback = { start: word.start, xargs: spec.appends === true };
      }
    }
  }

  /**
   * A word after a wrapper: a flag, a flag's argument, `timeout`'s duration, or the wrapped command.
   * The words a wrapper consumes must be static — an expansion's word count is unknown here, so
   * it could supply the wrapped command itself.
   */
  private wrapped(cmd: SimpleCommand, scan: WrapperScan, word: Word): void {
    const text = word.text;
    const flag = !scan.flagsDone && text.startsWith("-") && text !== "-" && text !== "--";
    if ((scan.pendingArgument || flag) && word.value === null) this.refuse("wrapper-usage");
    if (scan.pendingArgument) scan.pendingArgument = false;
    else if (!scan.flagsDone && text === "--") scan.flagsDone = true;
    else if (!scan.flagsDone && text === "-" && scan.spec.dashEnds === true) scan.flagsDone = true;
    else if (flag) this.flag(cmd, scan, text);
    else if (scan.needsDuration) {
      if (!DURATION.test(text)) this.refuse("wrapper-usage");
      scan.needsDuration = false;
      scan.flagsDone = true;
    } else {
      cmd.state = "command";
      cmd.wrapper = null;
      this.command(cmd, word);
    }
  }

  /** getopt-style: `--long[=value]`, or a short cluster whose with-argument letter takes the rest (or the next word). */
  private flag(cmd: SimpleCommand, scan: WrapperScan, text: string): void {
    const flags = scan.spec.flags;
    if (text.startsWith("--")) {
      const eq = text.indexOf("=");
      const takes = flags.get(eq === -1 ? text : text.slice(0, eq));
      if (takes === undefined || (eq !== -1 && !takes)) this.refuse("wrapper-usage");
      else scan.pendingArgument = takes && eq === -1;
      return;
    }
    if (scan.spec.numeric === true && /^-\d+$/.test(text)) return;
    let query = false;
    for (let k = 1; k < text.length; k++) {
      const letter = text[k] as string;
      const takes = flags.get(letter);
      if (takes === undefined) {
        this.refuse("wrapper-usage");
        return;
      }
      query ||= scan.spec.query === true && (letter === "v" || letter === "V");
      if (takes) {
        scan.pendingArgument = k === text.length - 1;
        break;
      }
    }
    // `command -v NAME`: NAME is an argument; the query itself is the command.
    if (query) this.open(cmd, scan.start, null);
  }
}

function fresh(): SimpleCommand {
  return { state: "command", entries: [], word: null, wrapper: null, fallback: null };
}
