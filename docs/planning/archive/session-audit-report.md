# Perk Pi session-corpus audit

**Snapshot:** 2026-08-07 18:36:41 UTC  
**Audit run:** `01KZER3DS94TP1VWSR9A5A69PE`  
**Scope:** one machine's persisted perk-repository Pi sessions, frozen read-only  
**Outcome:** observational report only; no session replay, code/config mutation, issue filing, or workflow mutation

## 1. Executive summary

This audit found strong evidence that perk's immediate execution surfaces usually return a usable,
typed result and that several higher-level behaviors work well in observed sessions. It did **not**
find enough independently validated evidence to promote a current workflow-product defect. That is
not a clean bill of health: lifecycle specialist coverage was lost, the post-repair privacy validator
could not independently finish, and several safety-critical outcomes are not persisted well enough
to audit.

### Strongest supported strengths

1. **Immediate orchestration tools are mechanically reliable.** Across 1,464 parent orchestration
   calls in the bounded G rollup, 1,456 returned non-error results (99.45%), six returned errors, and
   two lacked a result. All 161 automated/human review-post calls and all 38 thread-resolution calls
   returned non-error results. This proves tool-boundary completion, not semantic correctness
   [G-WELL-002].
2. **Observed automated review waves recover failed lanes.** Nine reconstructed three-angle waves
   contained 27 final angle outputs across 31 attempts. Four failed attempts were each followed by a
   matching successful retry; every reconstructed final angle set was complete. Parent deduplication,
   verdict correctness, and post ordering remain unobserved [G-WELL-003].
3. **Observed learn fan-out is complete and nonduplicative.** Six reconstructed learn waves contained
   19 analyst artifacts; all 19 completed, with distinct angle labels in each three- or four-lane wave.
   Parent reconciliation and final capture/skip remain unjoined [G-WELL-004].
4. **CI and warm binding surfaces show useful bounded signals.** All 723 `run_ci` invocations returned
   a report at the tool layer; 181 of 426 CI-using sessions ran it at least twice. Warm binding context
   appeared exactly once in each of 1,581 carrying sessions. Neither result proves check success,
   fix causality, or eligible-delivery completeness [F-002, F-004].
5. **Current examples show good planning and handoffs.** H independently confirmed four v2.1/v2.2
   examples of source-grounded planning and five current completed-session examples of concrete,
   validation-aware handoffs. The eligible denominators are unknown, so these are recurrent examples,
   not prevalence claims [E-POS-001, E-POS-002].

### Strongest supported weaknesses and risks

1. **The orchestration join is missing.** Child artifacts have no canonical parent orchestration id,
   requested-lane manifest, attempt ordinal, or reconciliation id. Child `run_id` does not reliably
   identify a wave; the audit's heuristic mislabeled 11 reviewer artifacts as learn analysis. This is
   a direct audit/instrumentation defect, not a demonstrated workflow defect [G-OBS-001].
2. **Safety-critical parent decisions are not auditable.** Human confirmation before review posting,
   objective-explorer use, conflict-resolver activation/attempt caps, child-report acknowledgment,
   and parent reconciliation are absent or only partially persisted. No violation was observed, but
   absence is not proof of compliance [G-GAP-005, G-GAP-007, G-GAP-008].
3. **Nearly half of product packets lack an exact pointer join.** 1,106 of 2,111 product sessions had
   an exact run-pointer join; 1,005 did not. Plain-Pi, fork, warm-minted, and pruned cases make some
   absence expected, so this limits auditability rather than proving broken linkage [F-005].
4. **Aggregate errors are not attributable.** The corpus contains 3,645 persisted tool-error results
   across 84,074 product tool calls, including 2,751 of 34,958 shell calls. Without stage, mode,
   reason, and chronology joins, those counts mix correct gates, expected probes, agent mistakes,
   external failures, and possible product defects [F-001].
5. **Recent agent behaviors warrant hardening, not defect promotion.** Two v2.1 sessions visibly used
   informal step narration where exact checkpoint syntax may have been eligible, and one v2.1 review
   episode included a false test count plus overbroad coverage language. Eligibility/current recurrence
   is insufficient for a v2.2 defect claim [E-WF-004, E-REV-005].
6. **Historical causal closure was costly when it occurred.** Two of 97 sampled sessions, both legacy,
   made recommendations before checking the authoritative state model and later reversed after user or
   empirical correction. Current counterexamples are stronger, so this remains a historical lesson
   [E-HIST-006].

### Bottom line

Perk's persisted evidence is strongest at **tool invocation and child-artifact completion** and weakest
at **semantic handoff between those events**. The next investment should be structured orchestration
and outcome telemetry, not a composite quality score or an undifferentiated campaign against error
counts. No recommendation below is automatically a bug report; each is classified as Fix, Test,
Instrument, Document-as-expected, Investigate, or No action.

## 2. Corpus and methodology

### 2.1 Snapshot and cohorts

The lead froze every discovered JSONL file at T0 by recording its private source path, header working
directory, modification time, byte length through the last complete line, and SHA-256 of that complete-
line prefix. Only the frozen prefix was parsed. The audit's own parent session was explicitly excluded;
children created later were excluded by T0.

| Bucket | Files | Treatment |
|---|---:|---|
| Perk product cohorts | 2,111 | Full deterministic packet; eligible for sampling |
| Test harness (`faux`/`faux-1`) | 4,410 | Census-light only; excluded from product findings |
| Other repositories | 583 | Exclusion bucket only |
| Audit parent | 1 | Excluded by construction |
| **Total discovered** | **7,105** | Exactly one snapshot-manifest row each |

Product cohorts were mutually exclusive:

| Product cohort | Files | Share of product corpus |
|---|---:|---:|
| Perk-stage | 1,664 | 78.8% |
| Repo-local plain-Pi control | 444 | 21.0% |
| Fork/clone | 3 | 0.1% |
| Temp directory with real provider | 0 | none quarantined |

Every included file used format version 3. The raw pass found zero malformed lines, zero unknown format
versions, and zero snapshot-hash drift. The installed Pi SDK parsed and migrated all 2,111 product
files; its node count, active leaf, active-branch length, and branch-point count exactly matched the raw
pass in all 2,111 cases.

### 2.2 Behavior eras

Release boundaries were inferred from local release tags/history. A persisted artifact did not pin the
running perk version, so **all era joins are inferred**, even where the release date is exact.

| Era | Product files | Test-harness files |
|---|---:|---:|
| pre-v1 | 855 | 2,177 |
| v1.0 | 551 | 942 |
| v1.1 | 608 | 1,147 |
| v2.0 | 26 | 24 |
| v2.1 | 33 | 60 |
| v2.2 | 38 | 60 |

The current-era denominator is therefore small and observational: 38 product files, split between 18
perk-stage and 20 plain-Pi controls. Historical recurrence cannot establish a current defect by itself.

### 2.3 Packet and privacy boundary

Common quantitative packets contain header facts, topology, event metadata, bounded/redacted tool
arguments, result status, usage, custom-entry metadata, exact joins, and anomaly addresses. They do not
contain thinking. Qualitative packets exist only for sampled sessions and contain redacted user/visible
assistant text bounded to 8,000 characters per message, including the truncation marker. Tool-result
bodies and thinking are absent.

Opaque ids are `S-` plus twelve hex characters derived from session id and an audit-private salt. The
salt and private mapping remain in gitignored scratch. The committed report contains no raw transcript,
full prompt, full tool output, private absolute path, raw session filename, credential, or reasoning
block.

Agent C independently checked 24 representative snapshots, all 2,111 packet schemas, all 97 sample
packets, SDK topology, and seeded synthetic canaries. It correctly blocked the first packet set for:

- three generic local-session-root fragments in one qualitative sample; and
- 21 messages whose truncation markers placed them 12–14 characters over the declared bound.

The lead widened redaction, added normalized/encoded-path canaries, made the full emitted string fit the
bound, regenerated the same deterministic sample, and exhaustively rechecked all 97 packets: zero path
fragment matches, zero canary survivors, and zero bound violations. Independent post-repair C
confirmation is nevertheless **uncovered**: one child was terminated by SIGTERM and its one permitted
retry misresolved a manifest-relative path. The repaired data are usable, but this report does not call
the validator gate independently clean.

Children were instructed to read only their packet directories; they were not filesystem-sandboxed.
That is a method limitation. Redaction bounded what entered child context by default and what could be
committed; it was not an OS security boundary.

### 2.4 Deterministic sample

The qualitative cap was 120. To fit the era × class product without silently dropping classes, adjacent
eras were merged before selection:

- pre-v1 + v1.0 → `legacy-pre-v1+v1.0`;
- v1.1 + v2.0 → `middle-v1.1+v2.0`;
- v2.1 and v2.2 remained separate.

Nine populated strata produced 97 sampled sessions. Strata with at most 12 sessions were fully reviewed;
larger strata used four SHA-256 seeded-random sessions, four highest-friction candidates, and four
lowest-friction controls preferring stage/model attributes represented among the high-friction set.
The sample seed is `perk-session-audit-1387-sample-v1`. Missing fields among 2,111 eligible sessions:
era 0, model 0, stage 447.

The 20% overlap seed is `perk-session-audit-1387-overlap-v1`; it selected 19 sessions. The independent
coder read all 19 without E's findings. E returned aggregate findings rather than per-session labels,
so a numeric inter-rater agreement would be false precision. Reconciliation instead tightened the
coding guide: termination is not failure; canonical handoff is required for observable outcome;
automated-clean followed by deeper findings is review-depth counterevidence, not tool failure; and
unsupported causal claims are distinct from useful user-driven empirical recovery.

### 2.5 Evidence, units, and promotion

The audit kept file, branch, turn, session class, run, and artifact outcome separate. Workflow success,
task success, interaction success, and efficiency were never collapsed into one score.

Evidence grades:

- **Direct:** persisted event or canonical artifact states it.
- **Corroborated:** two independent sources agree.
- **Inferred:** timing/content supports it without explicit linkage.
- **Not observable:** the required surface is not persisted; this is an instrumentation finding.

A current-product conclusion required at least two independent current-era sessions or one direct
invariant violation corroborated by current code/canonical state. H verified every candidate record,
not merely the required high/current/seeded subset: 16 confirmed, six narrowed, zero reclassified, and
zero rejected.

### 2.6 Coverage failures

Coverage was not silently upgraded:

- **A:** produced a valid 37-row expectation matrix; the harness rejected it on an irrelevant inferred
  implementation-acceptance check. Its one validation retry failed on unavailable bare `python`; the
  original structured result was retained after parent validation.
- **C post-repair:** uncovered after SIGTERM plus one path-resolution retry failure, as described above.
- **D lifecycle/outcomes:** uncovered. Its initial run failed in an ad-hoc script; its one retry omitted
  `.json` from a packet path. Deterministic lifecycle tables remain descriptive, but no D specialist
  finding was promoted.
- **E, F, G:** completed on their one allowed retries/first run as applicable.
- **H and second coder:** completed fully.

Because C and D are incomplete, this audit is not a clean verdict on perk's lifecycle. It is an
evidence-graded report with explicit uncovered surfaces.

## 3. Intent and observability matrix

Agent A mapped 37 expectations from the stage registry, contracts, user docs, learned docs, release
history, and emitting symbols. The compact matrix below groups them; historical sessions are judged
only against the first applicable era.

| Surface | Intended durable boundary | Persisted evidence available | Important non-observable/confounder | Primary lane |
|---|---|---|---|---|
| gist-author | Read-only problem-space draft | workflow state, draft artifact pointer | content quality, human rationale | D/E |
| gist-save | Exactly one backend gist keyed by run | save result, backend header | review may be bypassed by manual failsafe | D |
| objective-author | Read-only objective draft | workflow state, draft/review entries | authoring quality and rationale | D/E |
| objective-save | Backend objective/project + terminal result | save result, backend identity | secondary linkage may fail open | D |
| objective-plan | Bounded node exploration then saved plan | plan artifact, node link, workflow state | optional child execution/acknowledgment | D/G |
| plan | Read-only evidence-grounded plan | plan draft/review, mode/context entries | human review UI partly persisted | D/E |
| save | Plan issue/ref + implementation handoff | save result, plan header, run pointers | old pointers can be stale/shadowed | D |
| implement | Cold-only read-write worktree session | workflow state, plan ref, checkpoint entries | no terminal local outcome before submit | D/E/F |
| submit/ready | PR created/pushed, then deliberate review gate | PR/ref fields, submit/ready result | task correctness requires CI/review evidence | D |
| address | Classify → parent fixes → resolve | classifier artifact, resolution result | fix-before-resolve chain not joined | D/G |
| land | Approved PR merged; pending-learn set | merge result, marker | secondary objective bookkeeping may fail open | D |
| learn | Evidence bundle → analysts → capture/skip | bundle manifest, analyst artifacts, learn result | parent reconciliation not joined | D/G |
| read-only gating | Only sanctioned draft writes in planning | blocked tool result, stage/mode state | error reason/attempt intent needed | F |
| stage-scoped tools | Tool diet matches active stage | tool name + workflow state | missing tool vs expected absence needs chronology | F |
| checkpoints | Exact machine-readable progress | checkpoint custom entries/markers | model-authored exact prose is brittle | E/F |
| CI loop | Run → report → parent fix → verify | `run_ci` results | check verdict and intervening edit not joined | D/F |
| context injection | One relevant live copy; stale copy stripped | custom entry history | whole-session multiplicity ≠ live duplication | F |
| skills/bindings | Single cold/warm delivery, compaction-aware | binding context entry | cold delivery/completeness/model use not observable | F |
| cache transitions | Noncanonical, prunable acceleration | usage/cache counters, pointers | cache notice UI not persisted; no-join may be expected | F |
| compaction | Threshold/explicit summary preserving state | compaction entry + token count | eligible objective-active denominator absent | F |
| subagents | Bounded read-only children; parent owns judgment | child metadata, parent tool result | parent wave/ack/reconcile id absent | G |
| review doors | No posting before required human/coverage gate | post result, child artifacts | confirmation and browser-native order partial | G |
| conflict resolution | Definitive conflict → max two drives → clean resubmit | attempt state should join child + submit | no observed resolver chain | G |

Two doc/contract mismatches surfaced in A's matrix but were not session-grounded product findings:
user docs describe `/ready` as running project CI while current emitters only mark the PR ready, and a
skill-binding stage list omits gist despite the registry/defaults including it. These are candidates
for direct documentation reconciliation, not conclusions about observed session behavior.

## 4. Stage and door scorecard

This scorecard deliberately has no composite score. “Tool result” means the invocation returned a
non-error result; it does not mean the durable artifact was correct. Session stage is the last distinct
workflow-state stage in a product packet. Save/review tools may execute while the authoring stage remains
active, so tool and stage denominators are separate.

| Surface | Observed denominator | Workflow signal | Task signal | Interaction / efficiency signal | Confidence |
|---|---:|---|---|---|---|
| gist-author/save | 1 product gist-author session | Too small to score | No D outcome verification | No qualitative pattern | insufficient |
| objective-author/save | 48 final-stage sessions; 64 draft calls; 15 save calls | 58 draft and 11 save calls returned non-error results | Backend correctness not joined by D | Six draft and four save errors are mostly historical and unattributed | low |
| objective-plan | 319 final-stage sessions | 48 exact pointer joins; 271 without | Plan quality appears in positive E examples, not a rate | Optional explorer use unobservable [G-GAP-007] | low–medium |
| plan | 216 final-stage sessions | 47 exact joins; 169 without | Four H-verified current examples are source-grounded | Historical causal closure in 2/97 sample [E-HIST-006] | medium for examples, low for rate |
| save / review | 48 `plan_save`; 525 `plan_review`; 578 `plan_draft` calls | review 520 non-error; draft 574; save only 3 non-error, 39 errors, 6 missing | Error-heavy plan-save surface is pre-v1 dominated and not currently attributable | Manual failsafe/review UI confounds | low |
| implement | 1,075 final-stage sessions | 667 exact joins; 408 without | Five H-verified current completion handoffs | Two v2.1 potential marker-syntax misses [E-WF-004] | medium for examples; D uncovered |
| CI | 723 calls in 426 sessions | 723 reports returned; 181 sessions reran | Pass/fix causality not persisted | Report boundary reliable; redundant vs verify unknown [F-002] | high for tool, low for task |
| submit | 523 calls | 523 non-error results | PR fidelity/merge outcome not verified by D | Immediate door mechanically reliable | high for tool only |
| automated review post | 144 calls; 9 reconstructed three-angle waves | 144 post calls non-error; 27/27 final angles after retry | Verdict correctness not joined | Recovery behavior strong [G-WELL-003] | medium–high artifact layer |
| human review post | 17 calls; 13 reviewer artifacts | 17 post calls and 13 artifacts completed | Human-curated correctness unknown | Confirmation-before-post not auditable [G-GAP-005] | low for governance |
| address | 2 classifiers; 38 resolution calls | 2/2 artifacts; 38/38 calls completed | Fix-before-resolve not joined | Mechanical endpoints reliable [G-WELL-006] | high endpoint, low chain |
| ready | 2 calls | 2 non-error results | No CI linkage | Very small denominator; doc/implementation mismatch noted | insufficient |
| land | 2 calls | 2 non-error results | Merge/marker correctness not D-verified | Very small denominator | insufficient |
| learn | 351 calls; 6 reconstructed waves/19 analysts | 350 non-error calls; 19/19 analyst outputs | Reconciled decision/capture not joined | Fanout complete/distinct [G-WELL-004] | high fanout, low reconciliation |
| objective reconciliation | 131 calls | 126 non-error, four errors, one missing | Canonical prose/node correctness not assessed | Error concentration deserves typed reasons | medium tool layer |

The scorecard answers a narrower question than “did perk succeed?”: persisted immediate boundaries are
usually present, but end-to-end durable outcomes are under-observed and the lifecycle specialist lane
is missing.

## 5. Interaction findings

### 5.1 Current positive patterns

**Evidence-grounded planning [E-POS-001, narrowed].** H verified four current examples where the agent
inspected an upstream behavior, command lifecycle, agent census, or compatibility surface before
presenting decisions (`S-53168acd837d`, `S-39d8892ba498`, `S-552c9fc5a4ce`,
`S-0fed59884fed`). The eligible visible-planning denominator within 22 sampled current perk-stage
sessions is unknown. The defensible conclusion is “recurrent current examples,” not “dominant.”

**Concrete completion handoffs [E-POS-002, narrowed].** H verified five current completed-session
examples that separate delivered scope, validation, deviations, and next state
(`S-55d6c988e10a`, `S-3b6d5003ee02`, `S-8183298c1d62`, `S-80aab83260d4`,
`S-7147042a9d52`). Interrupted sessions are ineligible, not negative examples. Standardizing this
closure shape would preserve an observed strength without asserting a rate.

### 5.2 Friction is a sampler, not a quality label

The matched-tail design contained 28 highest-friction and 28 matched-low-friction sessions across seven
large strata. H confirmed heterogeneous outcomes in both tails: high-friction work could finish with a
specific validated handoff, while low-friction work could be a concise success or simply stop before an
observable outcome [E-METRIC-003]. The audit does not compute a correlation because no structured
interaction/task outcome exists for all 56 units.

### 5.3 Recent hardening candidates

**Exact checkpoint syntax [E-WF-004, narrowed].** Two v2.1 implementation sessions visibly narrated
numbered starts/completions without the exact token form. The packet does not expose a qualifying plan
`## Steps` precondition, and blank entries may contain additional markers; other sessions show correct
syntax. Treat this as a recent agent/prompt reliability candidate. A deterministic checkpoint tool or
syntax normalizer is safer than machine-sensitive free prose.

**Review calibration [E-REV-005, narrowed].** One v2.1 review episode contained a false test count,
absolute coverage language, and a parent correction. A second reviewer referred to the same surface,
so this is one corroborated episode/root mechanism, not multiple independent defects. Require counts to
come from a cited artifact and replace “100% covered” with enumerated arms plus residual unknowns.

### 5.4 Historical lesson

Two legacy sampled sessions made causal recommendations before checking authoritative state, later
reversing after user or empirical correction [E-HIST-006]. Both eventually recovered. Current
counterexamples use a stronger evidence ladder. The durable practice is: observed symptom → authoritative
state source → competing hypotheses → discriminating check → recommendation.

### 5.5 Interaction observability

Blank assistant entries are pervasive because thinking and tool-result bodies are excluded. They cannot
be coded as silence, thrashing, retry, or failure [E-OBS-007]. A privacy-safe event projection—event
category, tool category, success/failure class, and whether a user-visible status was emitted—would make
interaction analysis more reproducible without retaining sensitive content.

## 6. Tools, CI, context, cache, compaction, and efficiency

### 6.1 Tool calls and error attribution

Product packets contain 84,074 tool calls and 3,645 persisted error results. Highest-volume tools:

| Tool | Calls | Persisted errors | What the count means |
|---|---:|---:|---|
| `bash` | 34,958 | 2,751 | mixed expected probes, command failures, gates, misuse, environment |
| `read` | 21,130 | 122 | unreadable/missing/invalid requests; attribution absent |
| `edit` | 7,379 | 432 | may include correct read-only blocks and exact-match failures |
| `grep` | 6,085 | 91 | search-result/tool failures; reason absent |
| `todo` | 5,561 | 2 | immediate tool errors rare |
| `ask_user_question` | 1,709 | 153 | cancellation/input/surface causes not joined |

The most important result is negative: no aggregate error rate supports a product defect without
current era, stage/mode, reason, and retry chronology [F-001]. Existing expected-control-flow errors
must not be “fixed” away.

### 6.2 CI

All 723 `run_ci` calls returned a report. The 426 CI-using sessions include 181 with at least two calls,
and 170 with at least one identical-argument retry group [F-002]. This shows a reliable reporting
surface and frequent opportunity for verification. It does not show whether checks passed or a fix
occurred between calls. Persist check verdict, HEAD/diff identity, and intervening change class to prove
Run → Report → Fix → Verify without retaining command output.

### 6.3 Context and bindings

Whole-session multiplicity is not live-context duplication. Repeated workflow-state, mode, plan, adapter,
and objective-author entries can represent legitimate state transitions or reinjection after compaction
[F-003]. A valid duplicate test must follow the active branch and count the maximum simultaneous relevant
copy by marker flavor.

Warm binding delivery is cleaner: 1,581 carrying product sessions contain 1,581 binding entries—no
whole-session repeats [F-004]. This does not cover cold delivery, eligible sessions missing an entry,
missing targets, byte identity, transclusion, or model use. Preserve the observed one-entry behavior and
instrument delivery arms rather than adding more prompt text.

### 6.4 Linkage and cache

Exact pointer coverage is 1,106/2,111. The 1,005 unjoined sessions include potentially ineligible
plain-Pi, fork, warm-minted, and pruned cases [F-005]. Stratify by cohort, stage, handoff eligibility,
fork status, and GC reason before treating absence as a defect.

Persisted usage totals across product packets are:

- input: 90,742,426 tokens;
- output: 51,125,292;
- cache read: 6,415,951,960;
- cache write: 295,542,255;
- total: 6,853,361,933;
- recorded cost: 8,331.9015 in provider-reported currency units.

Cache-read tokens dominate accounting, but that can mean useful reuse, long repeated contexts, or both.
Model labels overlap within sessions and outcomes are unjoined, so this audit makes no model quality,
price-performance, or era-efficiency ranking [F-006].

### 6.5 Compaction

The corpus contains 34 persisted objective-threshold compactions: 28 pre-v1, two v1.0, one v1.1, one
v2.0, two v2.1, and zero v2.2 [F-007]. The true denominator is objective-active turns that crossed the
configured threshold; it is absent. Global Pi compaction and human commit-and-compact are separate.
Zero v2.2 events therefore prove neither inactivity nor failure.

## 7. Subagents, review, and learn

### 7.1 Artifact inventory and grouping defect

The pre-T0 inventory contains 73 child-artifact attempts grouped under 49 raw child run ids. Sixty-four
completed with output; nine failed and eight lacked output. This raw grouping is not a wave model:
children in one parent fanout can have separate run ids. The family heuristic also mislabeled 11
reviewer artifacts as learn analysis [G-OBS-001].

A durable parent orchestration record should contain:

- parent orchestration id and family;
- requested lane/angle set;
- child role and attempt ordinal;
- child artifact id and schema status;
- parent acknowledgment/disposition;
- reconciliation id and terminal action.

Without it, width, retry, cost, coverage, and deduplication rates are reconstructions.

### 7.2 Automated review

Nine semantically reconstructed three-angle waves yielded 27 final angle reports from 31 attempts. One
wave retried one failed lane; another retried all three; the final reconstructed sets were complete
[G-WELL-003]. This is good evidence that bounded targeted retry works where artifacts persist. It does
not prove the parent unioned/deduplicated findings correctly or blocked clean/post on missing schema.
Machine-checking requested-vs-terminal coverage at the parent boundary would turn this observed pattern
into an enforceable invariant.

### 7.3 Learn

Six reconstructed learn waves had widths 3, 3, 3, 3, 4, and 3; all 19 analysts completed with distinct
angles [G-WELL-004]. Recorded metadata alone cannot show fresh-context independence, evidence use,
reconciliation quality, or final capture/skip. Persist the closed-vocabulary decision and target under
the same orchestration id as the requested/received lanes.

### 7.4 Human review governance

Thirteen guest/adversarial reviewer artifacts and 17 review-submit calls all completed at their immediate
boundaries. There is no joined record of child findings → human keep/drop/reword → confirmation → post,
and browser-native writes may bypass perk's record [G-GAP-005]. No early post was observed; the ordering
is simply not verifiable. Require a human-confirmed curated-batch hash/token for perk-owned posting and
a separate marker for native-browser posting.

### 7.5 Address

Both persisted feedback classifiers completed, and all 38 thread-resolution calls returned non-error
results [G-WELL-006]. The critical middle is absent: classifier item → parent fix/disposition → commit or
diff evidence → reply/resolution. Endpoint reliability must not be confused with “every actionable item
was fixed before resolution.”

### 7.6 Objective exploration and conflict resolution

No child artifact was canonically identified as an objective explorer; 319 objective-plan sessions and
248 objective-node calls are adjacent context, not an eligible explorer-request denominator
[G-GAP-007]. Explorer execution is optional/guidance-driven, so absence is not failed spawn.

Likewise, 523 submit calls provide no denominator for conflict resolution. The eligible unit is a
definitive unmergeable result with conflicted paths. No joined resolver attempt, cap state, branch-head
change, or clean follow-up submit exists in the audit packet [G-GAP-008]. This safety path needs a
persisted bounded state machine.

## 8. Current vs historical findings

### 8.1 Current-supported

- Four current examples of evidence-grounded planning [E-POS-001, narrowed].
- Five current examples of concrete completion handoffs [E-POS-002, narrowed].
- Current audit instrumentation directly misgroups child families/waves [G-OBS-001].
- Current human-review, objective-explorer, conflict-resolver, and parent-reconciliation invariants are
  not observable [G-GAP-005/007/008].

The only direct current “defect” is in this audit/orchestration telemetry, not demonstrated user-facing
workflow behavior.

### 8.2 Recent but not current-promoted

- Two v2.1 potential checkpoint-syntax adherence misses [E-WF-004].
- One v2.1 review-calibration episode with a false count and absolute coverage language [E-REV-005].

Neither has independent v2.2 recurrence or a direct current invariant violation.

### 8.3 Historical

- Two legacy cases of premature causal closure [E-HIST-006].
- Many `plan_save`, draft, and objective-save errors occur in old cohorts and cannot be projected onto
  current behavior.

### 8.4 Improvement/regression evidence

The audit supports **example-level improvement**, not a causal release claim: legacy bad-causal-model
examples coexist with current evidence-first examples, and later review/learn waves show complete
artifact sets after targeted retry. It cannot prove that a particular perk release caused those changes.
No validated regression pattern survived H.

## 9. Prioritized follow-up candidates

No issue or fix was created during the audit.

### 1 — Fix

1. **Make checkpoint progress deterministic**: emit/update structured checkpoint state through a tool or
   normalize exact marker syntax at the boundary; retain prose only for humans [E-WF-004].
2. **Calibrate review proof language**: exact counts must derive from a cited artifact; replace absolute
   coverage claims with enumerated arms and residual unknowns [E-REV-005].
3. **Fix the audit's family/wave classifier before reusing it**: child run id and task-keyword family are
   not authoritative [G-OBS-001].

### 2 — Test

1. Add current-era tests for exact checkpoint eligibility/emission, including todo-adapter takeover.
2. Add a branch-live context test that distinguishes transition/compaction reinjection from duplicate
   simultaneous context [F-003].
3. Add review tests that reject unsupported exact counts/“100%” proof wording when evidence is partial.
4. Add end-to-end address evidence tests: actionable classification cannot resolve without explicit
   parent disposition/fix evidence [G-WELL-006].
5. Reconcile and test the `/ready` docs/implementation claim and the gist skill-binding stage list.

### 3 — Instrument

1. Parent orchestration id/requested-lane/attempt/reconciliation record [G-OBS-001].
2. Human-confirmed curated-batch token and post-order record [G-GAP-005].
3. Objective explorer request/skip/spawn/report/ack record [G-GAP-007].
4. Conflict eligibility/attempt/head/follow-up-submit state machine [G-GAP-008].
5. CI check verdict + HEAD + intervening-change class [F-002].
6. Eligible-arm telemetry for cold/warm binding delivery [F-004].
7. Linkage eligibility and GC/prune reason [F-005].
8. Privacy-safe interaction event projection without content [E-OBS-007].
9. Objective-active threshold eligibility and pre/post usage for compaction [F-007].

### 4 — Document as expected

1. Error counts include correct gates, probes, user actions, and external failures; `isError` is not defect
   attribution [F-001].
2. Whole-session context multiplicity can be expected after state changes/compaction [F-003].
3. No pointer join is valid for some plain/fork/warm/pruned sessions [F-005].
4. Cache/cost volume is not a quality score [F-006].
5. Friction ranking is a sampler only [E-METRIC-003].

### 5 — Investigate

1. Rebuild a current-era, reason-coded error denominator by stage/mode/tool and retry chronology [F-001].
2. Determine the eligible current objective-compaction denominator before interpreting zero v2.2 events
   [F-007].
3. Stratify the 1,005 no-join product sessions by expected eligibility [F-005].
4. Re-audit durable lifecycle outcomes after restoring an independent D lane and canonical backend joins.
5. Re-run independent privacy/schema validation against the repaired packet set before reusing qualitative
   derivatives outside this report.

### 6 — No action

1. Do not “optimize” model/provider selection from aggregate token/cost totals [F-006].
2. Do not treat absent child persistence as failed spawning [G-GAP-007/008].
3. Preserve the observed one-entry warm binding behavior [F-004].
4. Preserve targeted retry for failed required review lanes [G-WELL-003].
5. Keep historical causal-closure cases as training/guidance examples; current defect promotion is not
   supported [E-HIST-006].

## 10. Appendix

### A. Finding index

| ID | H result | Classification | Final bounded conclusion |
|---|---|---|---|
| E-POS-001 | narrowed | working well | Four verified current source-grounded planning examples; rate unknown |
| E-POS-002 | narrowed | working well | Five verified current completion handoffs; eligible closure denominator unknown |
| E-METRIC-003 | narrowed | measurement | Heterogeneous outcomes in both friction tails; no correlation estimate |
| E-WF-004 | narrowed | recent candidate | Two visible v2.1 potential syntax misses; eligibility/v2.2 recurrence unknown |
| E-REV-005 | narrowed | recent candidate | One corroborated v2.1 overconfidence episode; no v2.2 defect |
| E-HIST-006 | confirmed | historical | Two clear legacy premature-causal-closure cases in 97-sample |
| E-OBS-007 | confirmed | observability | Blank/excluded entries cannot support tool/status/retry coding |
| F-001 | narrowed | unattributed signal | Aggregate tool errors are not product-defect evidence; 6,085 tool is `grep` |
| F-002 | confirmed | working-well signal | 723/723 CI calls reported; fix/pass causality absent |
| F-003 | confirmed | observability | Historical repeated context entries do not prove live duplicates |
| F-004 | confirmed | working-well signal | 1,581 warm binding entries in 1,581 carrying sessions |
| F-005 | confirmed | observability | 1,106 joined / 1,005 unjoined product packets; eligibility unknown |
| F-006 | confirmed | telemetry | Usage/cost totals cannot rank quality or efficiency |
| F-007 | confirmed | observability | 34 objective compactions; eligible denominator absent |
| G-OBS-001 | confirmed | audit instrumentation defect | Family/wave grouping needs canonical parent id |
| G-WELL-002 | confirmed | working well | 1,456/1,464 immediate orchestration results non-error |
| G-WELL-003 | confirmed | working well | Nine reconstructed review waves finished all 27 required angles after retry |
| G-WELL-004 | confirmed | working well | Six reconstructed learn waves, 19/19 distinct-angle outputs |
| G-GAP-005 | confirmed | observability | Human confirmation/post ordering not joined |
| G-WELL-006 | confirmed | working well | 2/2 classifiers and 38/38 resolution endpoints completed |
| G-GAP-007 | confirmed | observability | Objective exploration has no eligible/request/artifact join |
| G-GAP-008 | confirmed | observability | Conflict-resolution eligibility/attempt/follow-up chain absent |

### B. Metric definitions

- **Product packet:** frozen session in perk main/worktree cohort, excluding faux test harness.
- **Final stage:** last distinct workflow-state stage in one product packet.
- **Tool non-error:** a persisted result exists and `isError` is false; no semantic success implied.
- **Tool error:** persisted `isError` true; missing result is separate.
- **Retry group:** same tool name plus identical bounded-argument fingerprint repeated in one session.
- **Friction score:** deterministic sampler weight from tool errors, nonzero shell, repeated equivalent calls,
  error/aborted stops, compaction, and correction candidates; not a quality score.
- **Exact join:** verified filename/session identifier in run pointers; no timestamp/prose matching.
- **Current era:** v2.2 inferred from header timestamp after the release boundary.
- **Artifact completion:** exit code zero plus nonempty output; does not imply parent use.
- **Wave:** semantic reconstruction from role/angle/shared-bundle/timing; child run id alone is invalid.

### C. Sampling and change points

- Sample seed: `perk-session-audit-1387-sample-v1`.
- Second-coder seed: `perk-session-audit-1387-overlap-v1`.
- Query: merged-era × exclusive cohort; review all when ≤12, else four seeded-random + four
  highest-friction + four low-friction controls preferring high-set stage/model attributes.
- Sample: 97/2,111 product sessions; test harness excluded.
- Second-code overlap: 19/97.
- Era boundaries: local release dates for v1.0.1, v1.1.0, v2.0.0, v2.1.0, v2.2.0; every join
  remains inferred unless a persisted artifact pins a version (none used for final rates).

### D. Opaque evidence references

Opaque references are stable only while the private salt/map remains in scratch. The report includes
examples but no mapping. Entry ids appear only when needed to identify a persisted event. Reported
aggregate findings can be reproduced from packet metadata without qualitative text.

### E. Reproducibility spot-check

Before commit, the lead independently re-derived:

1. the snapshot partition: 7,105 = 6,521 included + 583 other-repo + 1 audit-self; and
2. the deterministic sample/overlap sets from the frozen census and seeds: 97 selected and 19 overlap,
   with exact opaque-id set equality.

The reproducibility script returned zero mismatches. All prefix hashes remain in private scratch; no raw
session derivative is committed.

### F. Leakage scan

Before commit, a repository-local gate scanned this report for seeded canaries, the private user/home
path, the local session-store fragment, normalized/encoded private path forms, credential/auth/private-key
patterns, raw sampled filenames, and raw JSONL filename shapes. It returned zero matches. This is a
deterministic pattern gate, not proof against every conceivable nonstandard secret.

### G. Acceptance checklist

- [x] Every discovered file appears once in snapshot census or documented exclusion.
- [x] Product, plain control, fork, and test-harness cohorts remain labeled.
- [x] Every behavior expectation names durable source and earliest applicable era in the private matrix.
- [x] Every promoted finding has denominator, currentness, evidence grade, and counterevidence.
- [x] Working-well patterns receive independent H scrutiny.
- [x] Active/abandoned topology is SDK-validated; the learn normalizer was not treated as a full parser.
- [x] Tool errors, CI reports, interruption, cache transitions, and external/control-flow events are not
  counted as perk defects without attribution.
- [x] All 22 findings survived H as confirmed or narrowed; no rejected record was promoted.
- [x] Missing C/D coverage is explicit; this is not called a clean lifecycle audit.
- [x] Reproducibility and leakage gates pass while private scratch exists.
- [x] No session, repository code, config, backend state, issue, PR review, or workflow was mutated by the
  audit itself.

### H. Worktree-wipe inventory

Landing removes these worktree-local, gitignored artifacts:

- `.perk/workflow/scratch/session-audit/01KZER3DS94TP1VWSR9A5A69PE/`: T0, salt/private map,
  snapshot/census/manifests, disposable tools, quantitative packets, qualitative samples, expectation
  matrix, coding/method logs, lane manifests/summaries, and finding/verification records;
- worktree-local `.pi-subagents/artifacts/` records created by Agents A, C, D, E, F, G, H, and the
  second coder, including failed-attempt diagnostics.

The worktree wipe does not claim to delete Pi's external append-only logs; those audit-created sessions
were excluded by T0/self identity and are not committed. The only committed artifact from this audit is
this report.
