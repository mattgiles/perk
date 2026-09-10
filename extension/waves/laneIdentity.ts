// The routing-token fence for report-wave lane identity. A ROUTING TOKEN is any producer-owned
// identity rendered into a report child's task prose so the child can select its lane byte-exact
// against the manifest, or echo it verbatim into its typed report — untrusted DATA, never an
// instruction. Usually that is the SEMANTIC LANE ID (a harvest `<category>-<n>`, a dream cluster
// id, an audit `expectation_id`); the audit wave additionally renders a second, pair-level token
// — the `session_basename` the child echoes verbatim — which is a routing token but not a lane
// id. Because a token must survive byte-exact matching against the manifest (and byte-exact echo
// back), the fence is a REFUSAL rule, never an escaping rule: any escaping breaks selection by
// construction, so an accepted token renders byte-identical and an unacceptable one is refused
// (strict decoders) or degraded (the lenient audit planner) upstream, before any task is composed.
//
// Refused: the empty token; C0 controls U+0000–U+001F (a newline or carriage return would let a
// producer-owned id read as further task instructions); DEL U+007F; C1 controls U+0080–U+009F
// (NEL U+0085 included); the Unicode line/paragraph separators U+2028/U+2029; and the double
// quote `"` (every task quotes the id in double quotes). Nothing else — spaces, `@`, `/`, `:`,
// backticks, `${}`, astral characters and any length are admitted. There is deliberately NO
// length bound: an oversized id fails as availability (a transport or model-context limit
// surfacing as a wave-level failure), never as a silent success or an injection — the ceiling is
// the transport's, not perk's. (contracts.md §8.35)
//
// The module has exactly two concerns: the routing-token FENCE above (`isRoutingToken` +
// `renderRoutingToken`) and the fixed ORCHESTRATION-KEY format (`orchestrationKey`). The
// vocabulary split (contracts.md §8.35): the SEMANTIC LANE ID is the producer-owned identity a
// typed outcome reports; a ROUTING TOKEN is that identity (or a pair-level token) rendered into
// task prose for byte-exact selection/echo; an ORCHESTRATION KEY is the opaque code-owned
// `runs.all` item key a producer-lane wave gives one lane — never derived from producer bytes,
// never surfaced as a lane identity.

/**
 * The refused character classes as one reviewable single-line statement. No `g`/`u` flags: every
 * member is a single BMP code unit, so UTF-16 iteration is exact and astral characters (two
 * surrogate code units, neither inside any listed range) can never match.
 */
// biome-ignore lint/suspicious/noControlCharactersInRegex: refusing control characters is the point
const UNSAFE = /[\u0000-\u001f\u007f-\u009f\u2028\u2029"]/;

/**
 * The fence predicate: `true` iff `token` is non-empty and carries none of the refused classes.
 * Decoders and planners call this to refuse or degrade an unsafe id BEFORE a lane is planned.
 */
export function isRoutingToken(token: string): boolean {
  return token !== "" && !UNSAFE.test(token);
}

/**
 * The asserting identity render helper for a `laneTask` interpolation site: returns `token`
 * UNCHANGED when it passes the fence (the fenced form of an accepted token IS the raw token —
 * every existing task-prose pin stays valid), otherwise throws. A throw here is a programmer
 * error — a caller composed a task from a token it never fenced upstream — in the
 * `validateAssignments` posture of `reportWave.ts`: never an operational failure arm, and
 * unreachable on the production path (the strict decoders refuse, the audit planner degrades).
 */
export function renderRoutingToken(token: string): string {
  if (!isRoutingToken(token)) {
    throw new Error(
      `renderRoutingToken: routing token ${JSON.stringify(token)} failed the fence — refuse or degrade it upstream`,
    );
  }
  return token;
}

/**
 * The ONE fixed orchestration-key format the producer-lane learn waves — harvest, audit, and
 * the dream analyst tier, whose lanes are drawn from a producer-owned manifest — use for their
 * `runs.all` item keys: `lane.<ordinal>` — opaque, code-owned, never derived from producer
 * bytes. (Waves over a closed slug enum — the learn analyst angles, the dream reducer angles —
 * key by the slug itself and never need it.) There is deliberately NO sanitizer: uniqueness
 * lives in the caller's ordinal, and the semantic lane id rides `label` and the task text.
 * `ordinal` is the caller's global 1-based counter in lane-plan order. The format is trivially inside `RUN_KEY_PATTERN`, so `validateAssignments`' run-key
 * throw is unreachable for any planned lane. The key is never surfaced as a lane identity — it
 * appears only in attempt receipts (`requestedKeys`, `children[*].key`) and failure `detail`s;
 * typed outcomes join rows back to the SEMANTIC id through each flow's module-private lane plan,
 * never by parsing keys.
 */
export function orchestrationKey(ordinal: number): string {
  return `lane.${ordinal}`;
}
