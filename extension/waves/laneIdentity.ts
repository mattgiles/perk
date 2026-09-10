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
