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

## Default-miss fakes hide targeting errors

A fake backend whose unmapped key returns `None` makes a wrong-id read look like an ordinary miss.
Wire every plausible target with a distinguishable value, including redirected and predecessor
identities, so choosing the wrong target is loud. Add error cases through exception-valued map
entries that raise when read; do not create a separate fake whose control flow differs from the
normal lookup.

This posture belongs in backend and delivery tests wherever target identity is the behavior under
test. `workflow/issue-backend.md` records the backend form; delivery routing examples live in
`tests/test_delivery_facade.py` and the delivery test family.

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

## Enumerate failure matrices from the contract

A fixture generator usually expresses only valid shapes. Deriving negative cases from it therefore
omits malformed JSON, missing discriminators, forbidden extras, and impossible field combinations.
Write the failure matrix from the boundary contract, then choose a transport for each row. A loop
that stringifies Python objects can never send malformed JSON bytes; that row needs a raw payload.

Closed reason vocabularies are exhaustive at every translation boundary. Driving every domain
reason does not prove a DTO or HTTP route maps each one. Mirror the full matrix at domain, wire, and
route boundaries. `tests/test_prose_review_dto.py`, `tests/test_prose_review_web.py`, and
`workflow/prose-review-workbench.md` carry the source-adapter instance.

## Parametrize the whole declared surface

When a validator enumerates N fields, tests cover all N rather than one representative field. A
single-field spot check still passes after another field is accidentally removed from validation.
Build parameter rows from the contract's declared field set and pin its cardinality or exact names.

Assert full values instead of truthiness proxies. `assert result` cannot distinguish the expected
non-empty reason, identifier, or count from an unrelated truthy fallback. The contract value is the
oracle.

## Capture exact requests from parity fakes

A fixed-result fake makes two callers appear behaviorally equal even when one sends the wrong id,
mode, or authority facts. Capture and assert the exact request received by each fake, then compare
results. This is especially important when migrating callers behind a façade: discriminant-only
assertions prove output shape, not routing parity.

A validation-shortcut fixture can also bypass the derivation being tested. For every negative case,
verify which production path it reaches; a prefilled "already validated" object cannot prove raw
input validation. The façade patterns are documented in `workflow/objective-delivery.md` and tested
in `tests/test_delivery_facade.py` and its operation-specific siblings.

## Put discriminating inputs inside the measured scope

Unit-conversion tests must place the distinguishing value inside the interval or region the
implementation actually counts. A boundary value outside the selected scope yields the same result
under correct and incorrect units. Choose a fixture where bytes-versus-characters, seconds-versus-
milliseconds, or inclusive-versus-exclusive boundaries produce different asserted outputs.

`workflow/source-scan-guards.md` applies this to multibyte byte thresholds and newline counting;
that fixture design generalizes to every conversion proof.

## Negative-space checks need floors and mutation proofs

"No forbidden thing exists" first proves that its selector discovered a meaningful corpus and known
anchors. Then inject one synthetic offender through the same scanner and assert the check fails with
the expected label. The mutation need not touch production files; a temp corpus or scanner-unit
fixture is enough. Without that arm, a renamed directory, stale regex, or broad exclusion can turn a
repository invariant into an empty scan.

`tests/test_explanation_boundary.py` demonstrates paired scanner directions, while
`workflow/source-scan-guards.md` collects guard-specific non-vacuity techniques.

## Keep one real default path and verify delegates

Monkeypatching the same seam in every test leaves the production default constructor undriven. Keep
at least one public-path test that resolves and uses the real default runtime. Likewise, adding an
ABC method requires a production-adapter delegation test; Protocol fakes prove pure-core behavior
but not that the adapter calls the right engine.

Use monkeypatches to prove short circuits by making all substrate reads record or raise, not as a
replacement for every integration path. `workflow/objective-delivery.md` records the façade
migration version of this rule.

## Assert where values leave the subsystem

Renderer assertions cannot catch dispatch-time mutation. If a wrapper appends a suffix, drops a
field, or selects a different provider arm after rendering, renderer tests remain green. Assert the
value at the send/dispatch boundary as well as in the pure renderer, and include one row per
content-bearing template arm.

The binding-delivery example is in `workflow/skill-bindings.md` and
`extension/substrate/bindingDelivery.test.ts`.

## Review checklist

Before accepting a test claim, ask:

1. What incorrect implementation would still pass this fixture?
2. Does the fixture contain the exact collision, malformed arm, target distinction, or boundary
   needed to separate correct from incorrect?
3. Does the assertion pin the full payload/request, not only truthiness or absence of errors?
4. Does a negative-space check prove its selector is live and fail under an injected offender?
5. Is at least one production adapter/default path driven without replacing the seam under test?

## Cross-references

- `docs/learned/workflow/source-scan-guards.md` — guard-scoped vacuity and mutation proofs
- `docs/learned/workflow/issue-backend.md` — default-miss fake posture
- `docs/learned/workflow/objective-delivery.md` — real-default and adapter-delegation tests
- `docs/learned/workflow/prose-review-workbench.md` — closed adapter matrices and wire boundaries
- `docs/learned/toolchain/jsdom-react-component-harness.md` — component identity and stale-state
  fixtures
