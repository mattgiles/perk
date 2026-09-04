---
title: Vacuity-proof test craft — fakes, manufactured collisions, exhaustive matrices, mutation proofs
read_when: Writing or reviewing tests that could pass vacuously — default-miss fakes, dedup assertions, closed-vocabulary matrices, negative-space sweeps, parity fakes, monkeypatched seams
cluster: quality-and-guards
---

# Vacuity-proof test craft

A test is vacuous when it stays green without exercising the distinction named in its claim. This
is broader than an empty source scan: realistic fixtures can also make a uniqueness assertion,
parity comparison, or negative case true by construction. The counter-move is to manufacture the
condition that would make an incorrect implementation fail, then assert the full contract value.

## Distillation

- Wire every plausible fake target with a distinguishable value so a wrong-target read is loud —
  "Default-miss fakes hide targeting errors".
- Fakes never pick the safety posture: keep production fail-closed and repair the fakes — "Fakes
  must not pick the safety posture".
- Seam conversions re-home every observer: audit each stubbed dependency for orphaned pins and
  rebuild both threshold sides — "Seam conversions must re-home every observer".
- Dedup/uniqueness claims need manufactured collisions under the exact contract key —
  "Manufacture collisions for uniqueness and dedup claims".
- Assert positive membership and full payloads; ordered effects flow through ONE recorder with a
  discriminating order — "Assert payloads" / "Order pins need one recorder".
- Write failure matrices from the boundary contract; a fixture for check N must be valid for
  checks 1..N−1 — "Enumerate failure matrices from the contract".
- Cover the whole declared surface: per-field corruption, every enum arm, precedence per
  adjacent pair, throwing cases for fail-open reads — "Parametrize the whole declared surface".
- Capture the exact request each parity fake receives (full argv, staged stdin) — "Capture exact
  requests from parity fakes".
- Discriminating inputs live inside the measured scope; de-coincide coinciding fixture
  identities — "Put discriminating inputs inside the measured scope".
- Negative-space checks prove a live selector and fail under an injected offender; unobservable
  invariants pin structurally in source — "Negative-space checks" / "Structural source pins".
- Keep one real default path through the deepest seam; pin composition via the CAPTURED
  registration, never a hand rebuild — "Keep one real default path and verify delegates".
- Assert where values leave the subsystem, reading back through the production reconstruction
  seam — "Assert where values leave the subsystem".

## Default-miss fakes hide targeting errors

A fake backend whose unmapped key returns `None` makes a wrong-id read look like an ordinary miss.
Wire every plausible target with a distinguishable value, including redirected and predecessor
identities, so choosing the wrong target is loud. Add error cases through exception-valued map
entries that raise when read; do not create a separate fake whose control flow differs from the
normal lookup.

This posture belongs in backend and delivery tests wherever target identity is the behavior under
test. `workflow/issue-backend.md` records the backend form; delivery routing examples live in
`tests/test_delivery_facade.py` and the delivery test family.

## Fakes must not pick the safety posture

- A guard first written fail-open because the test fakes lacked a seam is the tail wagging the
  dog — keep production fail-closed and repair the fakes (give them a readable empty state)
  (#1994).
- When adding an environment probe to a hot path, grep-inventory every monkeypatch seam in the
  plan so the hermeticity sweep is mechanical rather than discovered test-by-test (#2018).
- A test dropped as "non-behavior-bearing" may have a behavior-bearing reframing — pin design
  choices via observable behavior, not implementation echo (#2018).
- Citing this doc doesn't apply it: for each invariant asserted, check the fixture would fail
  the trivial/wrong implementation (#2000).

## Seam conversions must re-home every observer

When a suite converts to a new seam or fixture (a fake replacing an intermediate artifact), every
property observed through the old path needs a new observer:

- A property observed only through an intermediate artifact the new fixture stubs out silently
  loses its pin. Audit every stubbed dependency with: "which deleted assertions were the only
  observer of what this stub now swallows?" (#2192).
- Boundary tests converted through a fake need BOTH threshold sides — deliberately reconstruct
  the non-tripping twin (one-below-limit completing with zero aborts), not only the tripping
  case (#2192).
- Cap boundaries need the N−1 case — seed CAP−1 and prove the last allowed attempt succeeds
  (#2155).
- A contract preserved by doing nothing needs a pin as much as a changed one — "no change"
  claims regress silently without an assertion (#2183).

## Manufacture collisions for uniqueness and dedup claims

A dedup assertion over production-like data that is already pairwise unique cannot distinguish a
correct key from no deduplication at all. Construct two members that collide under the *exact*
contract key while differing in fields that must not determine identity. Assert which occurrence
survives and the resulting order.

The same rule applies to UI occurrence identity. `tools/prose-review/comparisonComponents.test.ts`
uses equal choices as distinct occurrences; a fixture with different labels could not prove the
component avoids value-based identity.

## Assert payloads, not merely silence

A sweep that reports no diagnostics may have selected no files, skipped the relevant arm, or
returned an empty payload. Assert positive corpus membership and the expected output values. When a
filter operates over a live snapshot, prove at least one included member exists and include a
negative member that must be excluded.

Source-adapter and workbench examples live in `tests/test_prose_review_source.py` and
`tests/test_prose_review_checks.py`. For source scans, the sibling recipe is
`workflow/source-scan-guards.md`.

Four sharper payload rules:

- Auth/network stubs record into the SAME shared event list as the other fakes, so
  `events == []` genuinely proves zero network reach; ordering tests assert auth as the first
  network event (#1996).
- Ordering claims need order-recording seams asserting the literal sequence (e.g.
  sync→head→gather), not call counts — and passthrough tests record what the seam receives
  (#1990).
- Prove "aborts before side effect X" with a would-be-mutated artifact's survival — a strictly
  stronger proof than recorder absence (#2018).
- "Byte-identical" tests compare bytes (raw stdout vs the exact expected serialization), never
  top-level key sets (#2029).

## Order pins need one recorder and a discriminating order

- All ordered effects must flow through the SAME event trace — split across two recorders, a
  reordering between them stays green (#2184).
- Order-pin fixtures must be discriminating: shuffle staged order relative to expected order,
  and interleave degraded cases between dispatchable ones, so an order bug and a skip bug are
  separately visible (#2176).

## Enumerate failure matrices from the contract

A fixture generator usually expresses only valid shapes. Deriving negative cases from it therefore
omits malformed JSON, missing discriminators, forbidden extras, and impossible field combinations.
Write the failure matrix from the boundary contract, then choose a transport for each row. A loop
that stringifies Python objects can never send malformed JSON bytes; that row needs a raw payload.

Closed reason vocabularies are exhaustive at every translation boundary. Driving every domain
reason does not prove a DTO or HTTP route maps each one. Mirror the full matrix at domain, wire, and
route boundaries. `tests/test_prose_review_dto.py`, `tests/test_prose_review_web.py`, and
`workflow/prose-review-workbench.md` carry the source-adapter instance.

- A per-cause remediation matrix needs a parameterized test over EVERY wrapped exception type,
  including subclass except-arm ordering (#2024).
- Each new validation branch needs an otherwise-valid fixture that reaches exactly that branch,
  asserted by exact message — an "invalid" fixture tripping an earlier branch never exercises
  the new one (#2024).
- Enumerate blocked/defensive arms and pin each with a forcing fixture, or prove-then-delete the
  unreachable ones (#2029, #2021). Audit plan-time defensive-check inventories against what
  production can actually pass (#2028).
- Ordered-validation-chain negatives: a fixture testing check N must be valid for checks 1..N−1,
  or it pins the wrong refusal (#2182).
- Per-check corruption matrices: N independent field checks need N fixtures, each corrupting
  exactly one field, none rejectable by an earlier tier (#2176).

## Parametrize the whole declared surface

When a validator enumerates N fields, tests cover all N rather than one representative field. A
single-field spot check still passes after another field is accidentally removed from validation.
Build parameter rows from the contract's declared field set and pin its cardinality or exact names.

Assert full values instead of truthiness proxies. `assert result` cannot distinguish the expected
non-empty reason, identifier, or count from an unrelated truthy fallback. The contract value is the
oracle.

- Partial-cohort tests corrupt each NEW field individually — a test that omits only a
  pre-existing field stays green if the new fields drop out of the cohort (#2028).
- Every decoder enum arm needs a positive decode case; pair every cap+1 refusal with an at-cap
  success (#1999).
- Exact-shape manifest tests live in the mode with maximal non-null structure, one non-empty row
  per closed family (#2001).
- "Every open X" claims need a more-than-one-page fixture AND negative argv pins on the bounded
  readers (#2003); a single-candidate negative can't prove sweep continuation — follow a closed
  match with an open one (#2004).
- Precedence chains need a test per adjacent pair; every fail-open read needs its throwing case;
  byte-stable stderr/warning contracts need captured-stream assertions, not null-return proxies
  (#2171).

## Capture exact requests from parity fakes

A fixed-result fake makes two callers appear behaviorally equal even when one sends the wrong id,
mode, or authority facts. Capture and assert the exact request received by each fake, then compare
results. This is especially important when migrating callers behind a façade: discriminant-only
assertions prove output shape, not routing parity.

A validation-shortcut fixture can also bypass the derivation being tested. For every negative case,
verify which production path it reaches; a prefilled "already validated" object cannot prove raw
input validation. The façade patterns are documented in `workflow/objective-delivery.md` and tested
in `tests/test_delivery_facade.py` and its operation-specific siblings.

- Routing-key fakes don't pin the wire — assert full argv adjacency and the exact staged stdin
  rows, not just the routing key (#2184).
- A fake that ignores its inputs unpins the delegation boundary — record argv, assert exactly
  (#2180).
- Compatibility-sensitive false-vs-absent distinctions need both wire forms round-tripped
  (#2180).

## Put discriminating inputs inside the measured scope

Unit-conversion tests must place the distinguishing value inside the interval or region the
implementation actually counts. A boundary value outside the selected scope yields the same result
under correct and incorrect units. Choose a fixture where bytes-versus-characters, seconds-versus-
milliseconds, or inclusive-versus-exclusive boundaries produce different asserted outputs.

`workflow/source-scan-guards.md` applies this to multibyte byte thresholds and newline counting;
that fixture design generalizes to every conversion proof.

- Order pins need shuffled input (a fixture already in manifest order proves nothing), and
  counters must be non-zero to pin pass-through (#1991).
- Cap tests need astral characters — the discriminating assertion is
  `part.length > CAP && codePointLength(part) <= CAP` on at least one part (#1991); byte-length
  contracts need a multibyte fixture where `len(bytes) > len(str)` (#1996).
- Root-anchoring tests are vacuous when invocation root == main root — use a linked worktree
  with distinct roots plus a main-checkout-only marker asserting where the config was actually
  loaded from (#2028).
- De-coincide fixture identities: when an output interpolates an identity present in several
  coinciding fixture sources, thread a divergent alias through one source and pin BOTH the
  presence of the resolved value AND the absence of the alias (#2154).

## Negative-space checks need floors and mutation proofs

"No forbidden thing exists" first proves that its selector discovered a meaningful corpus and known
anchors. Then inject one synthetic offender through the same scanner and assert the check fails with
the expected label. The mutation need not touch production files; a temp corpus or scanner-unit
fixture is enough. Without that arm, a renamed directory, stale regex, or broad exclusion can turn a
repository invariant into an empty scan.

`tests/test_explanation_boundary.py` demonstrates paired scanner directions, while
`workflow/source-scan-guards.md` collects guard-specific non-vacuity techniques.

Mutation-proof ordering pins by temporarily reversing the implementation and watching the pin
fail — but never restore with `git checkout <file>` while carrying uncommitted work (a HEAD
reset wipes it); snapshot/stash first and revert only the temporary mutation (#1922).

## Structural source pins for unobservable invariants

When an invariant is unobservable at the seam and a test-only seam is forbidden, pin the
unobservable half **structurally in source** — exact reference-count/placement assertions over
the source text — and scope the behavioral test's claim to what it can actually falsify. A
behavioral test whose claim covers the unobservable half is quietly vacuous (#2189).

## Keep one real default path and verify delegates

Monkeypatching the same seam in every test leaves the production default constructor undriven. Keep
at least one public-path test that resolves and uses the real default runtime. Likewise, adding an
ABC method requires a production-adapter delegation test; Protocol fakes prove pure-core behavior
but not that the adapter calls the right engine.

Use monkeypatches to prove short circuits by making all substrate reads record or raise, not as a
replacement for every integration path. `workflow/objective-delivery.md` records the façade
migration version of this rule.

- Stub the deepest real seam (the stdlib module singleton) and run the real delegation chain, so
  unit tests double as thin integration tests (#2018).
- Optional injected seams need a product-path composition pin — register with a recording fake,
  inject a fake dep, and invoke the CAPTURED tool definition end-to-end; once a pure helper owns
  the interaction matrix, keep integration tests to boundary behavior plus one smoke (#1922).
- A composition pin that reconstructs the composition by hand pins nothing (optional params make
  loss silent) — load the actual extension root through the harness and drive the registered
  surface end-to-end (#2170).
- Cover the composition point through the registered artifact — a helper-only suite stays green
  when the execute-callback wiring is deleted (#2155).
- Built-output progressive-enhancement mounts need an explicit presence assertion (#1993).

## Assert where values leave the subsystem

Renderer assertions cannot catch dispatch-time mutation. If a wrapper appends a suffix, drops a
field, or selects a different provider arm after rendering, renderer tests remain green. Assert the
value at the send/dispatch boundary as well as in the pure renderer, and include one row per
content-bearing template arm.

The binding-delivery example is in `workflow/skill-bindings.md` and
`extension/substrate/bindingDelivery.test.ts`.

- Choreography tests read writes back through the production reconstruction seam, never a
  test-local reimplementation of the projection — a parallel derivation lets the write side and
  read side drift while green (#2024).
- A renderer has a "purity twin" obligation: it consumes only the composed value, never a module
  constant that happens to match today (#1991).
- A fresh implementation of a scanned read-back needs its own race pin — a sibling's race test
  proves nothing about it (#2021).
- Message-pin-preserving extraction: interpolate the `what` parameter exactly where the old
  literal sat, so byte-identical message pins survive refactors (#2021).

## Review checklist

Before accepting a test claim, ask:

1. What incorrect implementation would still pass this fixture?
2. Does the fixture contain the exact collision, malformed arm, target distinction, or boundary
   needed to separate correct from incorrect?
3. Does the assertion pin the full payload/request, not only truthiness or absence of errors?
4. Does a negative-space check prove its selector is live and fail under an injected offender?
5. Is at least one production adapter/default path driven without replacing the seam under test?
6. Did any fake's missing seam pick the production safety posture (fail-open) instead of being
   repaired?
7. Does every ordering/abort/byte-identity claim assert the literal sequence, artifact survival,
   or raw bytes rather than counts, recorder absence, or key sets?
8. Does each new validation branch have a fixture that reaches exactly it, and each
   blocked/defensive arm a forcing fixture (or a proof it is unreachable)?
9. Do cohort/enum/cap tests corrupt each NEW field individually, decode every enum arm
   positively, and pair each cap+1 refusal with an at-cap success?
10. Do order/cap/byte/root fixtures actually discriminate (shuffled input, astral characters,
    multibyte bytes, distinct worktree roots)?
11. Do read-back assertions flow through the production reconstruction seam, and does each fresh
    scanned read-back carry its own race pin?
12. Does the real default path drive the deepest seam end-to-end, with composition pinned via
    the captured registration?
13. Was every mutation proof restored by reverting only the temporary mutation (never
    `git checkout <file>` over uncommitted work)?

## Cross-references

- `docs/learned/workflow/source-scan-guards.md` — guard-scoped vacuity and mutation proofs
- `docs/learned/workflow/issue-backend.md` — default-miss fake posture
- `docs/learned/workflow/objective-delivery.md` — real-default and adapter-delegation tests
- `docs/learned/workflow/prose-review-workbench.md` — closed adapter matrices and wire boundaries
- `docs/learned/toolchain/jsdom-react-component-harness.md` — component identity and stale-state
  fixtures
