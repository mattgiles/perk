# Why perk audits sessions

This page is **explanation** documentation. It describes the reasoning and trade-offs behind the
session-audit system. There are no steps here; the operational surface belongs in the
[reference](./session-audit.md) and the procedure belongs in the
[how-to guide](./auditing-sessions.md).

## Tests stop at the code boundary

perk's framework test suites can prove that a prompt was rendered, a tool was registered, a gate
rejected a forbidden call, or a state transition produced the expected artifact. They cannot
prove that a model followed the rendered guidance in a real session.

That gap matters because much of perk's product is behavioral: prompts shape reasoning, skills
carry procedures, doors define sequencing, and agents decide how to use the available tools. A
unit test can establish that those surfaces exist without showing whether sessions actually use
them as intended. Before the audit, that layer had no regression coverage at all.

The session audit extends observation past the code boundary. It reads recorded Pi sessions and
asks whether a small set of important behaviors left the expected evidence. It does not replace
framework tests; it watches the layer they cannot see.

## Prose-only enforcement is the soft underbelly

Most catalog entries have `enforcement: prose-only`. Their behavior depends on instruction
following: grill planning decisions before review, treat untrusted engagement as data, route an
explorer's compact report rather than replaying its transcript. No structural mechanism makes
those behaviors impossible to violate, so ordinary tests can verify only the words that request
them. The audit is the sole observer of whether those words shaped a recorded session.

The catalog's one `structural` expectation,
`read-only.no-worktree-mutation`, has a different role. It is a calibration canary over the
read-only gate's direct backstop. A genuine hit would indict the gate or the audit's session
classification—not ordinary model disobedience. Keeping this structurally enforced behavior in
the same report checks whether the measurement system can distinguish a model-level lead from a
mechanism-level impossibility, while preserving the gate's documented leniencies.

## Why the audit reports but never gates

A session transcript is richer and less stable than a test fixture. Sessions may still be
appending, behavior may be absent because a precondition never occurred, and a mechanical
signature can become stale when the surrounding workflow changes. Judgment lanes introduce a
second fallible reader. Turning those signals into CI failures would give uncertain evidence the
authority of a proof.

Instead, the audit produces leads for a human to triage. It does not auto-file issues, maintain a
trend store, or decide that a violation is worth acting on. A successfully generated report exits
0 even when it contains violations. The operator retains the decision about whether a finding is
a real behavioral regression, an audit-machinery defect, or an expectation that needs
recalibration.

## Honest degradation is the governing principle

The audit is designed to say what it could not establish. `not-exercised`, `not-applicable`, and
`unchecked` are first-class outcomes rather than awkward exceptions:

- `not-exercised` means the history did not contain the relevant workflow behavior or
  precondition. No evidence is not a pass.
- `not-applicable` means the known session vintage predates the expectation. Old behavior is not
  judged against a newer rule.
- `unchecked` names why no definitive verdict was possible: an unparsed or malformed session, an
  in-flight absence, an unsampled or unboundable packet, a failed lane, or an unclear auditor.

Vintage reckoning exists for the same reason. Exact forward stamps are preferred, timestamp-based
release estimates err conservatively, and uncertainty remains visible. A genuinely unknown
vintage does not suppress grading: the deterministic checker or judgment packet may still produce
a verdict, with the unknown basis kept visible for human discounting. The estimate and explicit
degradation arms—not unknown vintage itself—bias uncertainty toward missing coverage rather than a
false accusation.

## Judgment verdicts are leads, not proofs

Some expectations require interpretation that a deterministic checker cannot safely encode.
Fresh-context auditor lanes read bounded transcript slices and can distinguish, for example, a
directive inside an untrusted block from an independently mandated action in trusted guidance.
That flexibility is also fallible.

The fold therefore preserves confidence, rationale, and entry-index citations and labels the
result a judgment lead. A claimed violation without a citation becomes `unchecked`, and an
`unclear` verdict remains `unchecked`. The rendering repeats “lead, not proof” because the
limitation is part of the data model, not a disclaimer added after the fact.

## Sessions are untrusted evidence

The corpus contains model and user text, shell output, tool results, and potentially hostile
prompt-like directives. The audit treats all transcript content as data describing what happened,
never as instructions for the auditor. Evidence packets are explicitly fenced as untrusted. The
repo-local auditor definition gives the lane read/search tools plus `bash` and instructs it never
to write files, post, or spawn children. That prohibition is behavioral rather than a complete
sandbox: the read-only gate's documented argument-blind shell allowances can still mutate or post
if the lane ignores its instructions.

The orchestrator stage is also read-only over session history. Its intentional bundle write goes
through `run_audit_wave`, whose destination is structurally bound to the launch-created scratch
bundle rather than chosen from transcript text. The same general shell leniencies still apply;
the binding prevents evidence from redirecting this particular writer, not every possible shell
side effect.

## Smallness is a curation discipline

A large catalog would create the appearance of coverage while accumulating low-value or
unmaintained rules. Every expectation therefore needs a durable source, a clear evidence and
violation signature, an applicability floor, and a reason to justify ongoing checker or judgment
cost. The committed id set is pinned exactly so catalog growth and shrinkage are reviewable
choices.

The first live dogfood pass demonstrated that discipline: all eight entries were triaged, four
were sharpened against real evidence, and none were culled. The point is not that catalog entries
are permanent; it is that each one must continue to earn its place. The full calibration record
is [`docs/design/archive/session-audit-dogfood.md`](../design/archive/session-audit-dogfood.md).

---

← Back to the [developer docs router](./index.md).
