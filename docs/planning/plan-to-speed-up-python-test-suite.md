# Plan to speed up the Python test suite

Research date: 2026-09-08. Source revision:
`9186a1d69321b9189b16cb6b7cabdd2e42fd3a09`. Status: findings and proposed follow-up
work; the suite has not been changed by this memo.

The largest supported opportunity is to stop repeatedly running the entire Doctor
engine when a test owns one finding. Next, extend the existing immutable Git
fixtures to repeated stack and launch setups. Both approaches reduce work while
retaining the cases that exercise different behavior. Removing the seven
duplicates identified below is justified maintenance, but their combined measured
cost is only **0.118 seconds of worker time**.

Expose three commands: `just test-py` for all default Python tests,
`just test-py-fast` for tests without `slow`, and `just test-py-slow` for tests
marked `slow`. The two tiers can run independently or concurrently. Keep
**`just test-py`, `just test`, and all existing Python gates running the full
default suite**, including slow tests. Moving tests out of the default gate would
change regression protection; it is not part of this proposal.

## Current execution and baseline

[The justfile](../../justfile) delegates `test-py` directly to `uv run pytest`.
[Pytest configuration](../../pyproject.toml) selects `tests/` and adds
`-n auto --dist loadgroup`. [The worker hook](../../tests/conftest.py) caps auto at
six usable CPUs; explicit `-n0` and `-n N` override it. The GitHub workflow runs
`just test`, whose Python invocation is separate from the `test-py` recipe.
[Perk's CI configuration](../../.perk/config.toml) invokes `just test-py` directly.
Any future selection change must account for both entrypoints.

The default collection contains **6,842 cases in 221 modules**, representing
5,935 distinct function/method node IDs before parameter suffixes. There is no
registered `slow` marker. Eighteen cases carry `xdist_group`: ten `wheel_build`,
five `source_scan`, and three `upgrade_notice_cli` consumers.

The prose-review and prose-map Python suites are deliberately excluded unless
`PERK_PROSE_REVIEW_TESTS=1`; `just prose-review-test` enables them. Preserve that
existing opt-in boundary. These findings concern the default Python suite.

Local measurements used macOS 26.5 on ARM64, 11 usable CPUs, six workers,
Python 3.13.9, pytest 9.0.3, pytest-xdist 3.8.0, uv 0.12.3, just 1.58.0, and
Node 26.3.0. Every row below passed all 6,842 cases at the revision above.

| Run | Temporary-directory policy | Pytest console duration | External wall time | Summed worker time |
| --- | --- | ---: | ---: | ---: |
| Full A | Default | 105.39 s | 107.59 s | 599.159 s |
| Full B | Default | 98.43 s | 118.40 s | 550.002 s |
| Retention experiment A | `failed` | 105.08 s | 106.16 s | 594.080 s |
| Retention experiment B | `failed` | 143.09 s | 144.17 s | 802.335 s |

External wall time includes interpreter startup and shutdown. Summed worker time
is the sum of JUnit testcase durations with `junit_duration_report=total`, including
setup, call, and teardown. It measures work distributed across workers, not time
saved from the user's wait. Session fixture setup is attributed to its first
consumer. Neither module totals nor nested profiler times can be added to predict
wall-time savings.

The matching [GitHub Actions run](https://github.com/mattgiles/perk/actions/runs/34239450016)
passed 6,842 tests in **57.73 seconds as reported by pytest**, on Ubuntu with four
workers and Python 3.13.15. This is useful CI context, not a controlled comparison
with the Mac. The complete Actions Test step also runs JavaScript and docs checks;
its duration is not the Python duration.

An initial discovery run passed 6,817 cases, but the checkout advanced from
`368678c8` to `9186a1d6` during that investigation. It is excluded from the baseline
table. The subsequent full-suite samples checked HEAD before and after. Two
default samples are enough to identify large costs, not establish a stable
performance distribution. The slower retention sample remains in the evidence;
there is no controlled host-level evidence that justifies discarding it.

### Build on work already done

The [previous performance investigation](archive/python-test-performance.md)
already introduced the worker cap, immutable repository templates, shared source
corpus, shared wheel/sdist build, and narrower Doctor checks. Its 4,223-case,
32-CPU-host measurements are historical, not a baseline for this checkout.

Current shared fixtures include unborn, committed, scaffolded perk, and local
remote Git worlds. They copy mutable files independently, preserve relative
origin URLs, and disable Git maintenance in the templates. The existing
[blueprint isolation tests](../../tests/test_repo_blueprints.py) protect that
design. The opportunity is broader adoption and narrower execution at remaining
hotspots, rather than adding another general fixture framework.

## Priorities

Effort is relative implementation/review scope, not a delivery estimate. Benefits
below distinguish measured cost from an unmeasured improvement.

| Priority | Proposed action | Evidence and expected benefit | Effort | Safety condition / confidence |
| --- | --- | --- | --- | --- |
| 1 | Narrow remaining Doctor case matrices | Doctor consumes 19–20% of summed worker time; avoid unrelated checks and repeated YAML/Git work | Medium | Keep engine composition and repair stories; high confidence in wasted work, savings unmeasured |
| 2 | Reuse specialized immutable Git worlds | Repeated seeding in stack checkout, launch restore, and objective refinement | Medium | Fresh mutable copies and real Git operations remain; strong structural evidence, savings unmeasured |
| 3 | Share guard input and repair an empty-corpus weakness | Several guards rescan independently; one demonstrated vacuity susceptibility | Small–medium | Preserve corpus scope, anchors, and positive controls; high confidence in safety improvement, speed gain unmeasured |
| 4 | Add fast and slow commands alongside the full command | A small cohort pays for builds, Node startup, and real Git cascades; separate commands allow concurrent execution | Small | Full mandatory suite unchanged; candidate costs measured serially once, separate/concurrent savings unmeasured |
| 5 | Remove seven supported duplicates | 0.118 s summed cost in Full A | Small | Named surviving assertions below; high confidence in redundancy, negligible speed benefit |
| 6 | Investigate temporary-directory lifecycle | A measured exit cleanup took 25.43 s; retention experiment was inconsistent | Medium | Preserve isolation and bounded cleanup; no policy change supported yet |
| 7 | Revisit parser, imports, plugins, and scheduling | Promising parser microbenchmark; little evidence for other switches | Variable | Separate experiments after test changes; no suite-level gains established |

### 1. Narrow Doctor tests at the behavior they own

[Doctor's 272 cases](../../tests/test_doctor.py) consumed **117.159 of 599.159
worker seconds** in Full A (19.55%), and **106.147 of 550.002** in Full B (19.30%).
The next largest Full A modules were objective refinement (27.316 s), Git
(25.991 s), launch restore (17.201 s), plan save (16.386 s), stack checkout
(15.129 s), and packaging (14.049 s).

A separate serial Doctor run used `cProfile`, fixture timing hooks, and a
`subprocess.Popen` audit hook. All 272 cases passed. Its approximately 102-second
runtime includes substantial profiling overhead and must not be compared with
the uninstrumented suite. Its counts expose repeated work:

| Operation | Calls in the instrumented Doctor run |
| --- | ---: |
| `run_doctor` | 167 |
| `_build_checks` | 220 |
| `load_registry` | 707 |
| `load_providers` | 952 |
| `yaml.safe_load` | 1,920 |
| Git subprocesses | 2,170 |
| Of those: `rev-parse` / `ls-files` / `check-ignore` | 1,353 / 534 / 218 |
| Node subprocesses | 7 |

Only two Git initializations occurred in that run: existing repository templates
already avoid most initial setup. The remaining cost is largely repeated
observation and convergence. Overlapping cumulative profiler times included
`_build_checks` 59.937 s, YAML loading 33.156 s, `main_worktree_root` 23.559 s, and
`load_registry` 21.587 s. Do not sum these: registry loading includes YAML work,
and checks include both registry and Git work. Fixture-exclusive scaffolded-copy
setup was 8.273 s across 220 uses; test call phases accounted for 89.802 s.

Start with the `test_subagent_bridge_config_*` matrix. For example,
`test_subagent_bridge_config_project_off_is_warn` runs the complete engine to
inspect one finding and overall health. Nearby tests already call
`doctor_checks._subagent_bridge_config_check` directly. Move the value/scope/error
matrix to that check, while retaining a representative full report that proves
registration, warning severity, and healthy exit behavior. Simply deleting
`report.healthy` assertions without retaining that integration would lose a
distinct guarantee.

Next inspect `test_subagent_worktree_default_*`. Several cases run Doctor two or
three times to inspect one managed setting. Exercise
[the actual setting converger](../../src/perk/convergence/init/subagent_config.py)
for absent/false/nonboolean/malformed input, byte preservation, sibling keys,
dry-run behavior, repair, and idempotency. Test generic status mapping at
[`_managed_checks`](../../src/perk/convergence/doctor/checks.py), and keep an
engine-level repair story for this convergence. Preserve environment-versus-config
precedence and linked-worktree resolution cases; these test different inputs and
filesystem relationships.

Retain explicit engine coverage for healthy-after-init, detected drift, fix then
recheck, idempotency, verify gating, error reporting, CLI output/exit status, and
[the dot-directory dogfood story](../../tests/test_dot_directory_dogfood.py).
In particular, `test_healthy_after_init`,
`test_drift_detected_and_fixed_idempotently`, and
`test_dot_directory_fresh_drift_repair_story` anchor different parts of that
contract. [The engine](../../src/perk/convergence/doctor/__init__.py) composes
checks, applies fixes, and rebuilds after changes; check-level tests alone cannot
prove this sequence.

Acceptance evidence: compare serial cohort time and process/load counts before
and after, then compare full-suite wall samples. Preserve every input equivalence
class and map moved assertions to their new owner. Use targeted fault injection
to show that omitting check registration or the post-fix recheck still fails an
engine test. Avoid global mocks that manufacture a healthy report.

### 2. Extend immutable fixture reuse

| Target | Repeated work | Proposed fixture boundary | Regression behavior to keep real |
| --- | --- | --- | --- |
| [Stack checkout](../../tests/test_pr_review_stack_checkout.py) | `_seed_linear_stack` creates three commits/branches and pushes three pull refs for repeated consumers | Immutable three-layer remote world, copied as a complete world | Fetch, topology validation, snapshot refs, drift notes, failed/unknown probes, cleanup |
| [Launch restore](../../tests/test_launch_restore.py) | 22 cases repeatedly seed/push plan branches and construct worktree states | Common published-plan world; create each exceptional state in its own copy | Equal/behind/ahead/divergent branches, unfetchable refs, registrations, checked-out-elsewhere refusals |
| [Objective refinement](../../tests/test_objective_refine_cmd.py) | `_scaffold` initializes/configures/adds/commits a repository repeatedly across 18 cases | Small committed config template with backend-specific state | Resolver selection, typed refusals, sync ordering, launch preparation, actual save/approval integration |

Use the current fixture model: session-scoped immutable preparation and
function-scoped copies. Pytest fixture scope controls reuse, while xdist creates
separate worker processes; a session fixture is not inherently global across all
workers. Keep expensive consumers grouped when global build-once behavior is
needed. [Pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
and [xdist fixture guidance](https://pytest-xdist.readthedocs.io/en/stable/how-to.html)
describe these lifetimes.

The copied local origin must stay inside the copied world. Do not hardlink
mutable Git files, share a mutable checkout, or pre-create linked worktrees whose
administrative paths point back at the template. Extend the blueprint isolation
checks for new worlds: a commit, push, or ref deletion in copy A must not alter
copy B or the template. Derive expected object identities from the fixture's
known setup, without calculating expected business decisions through the same
production function under test.

Keep the real integration in
`test_refinement_loop_end_to_end_over_a_fake_linear_objective`: although its
remote workspace is fake, it exercises the real backend/store, Python worker,
Node approval helper, and cold/warm content. It has additive coverage across
those components. Its 1.650-second serial cost is a reason to classify it, not
remove it. After these focused changes, reprofile the remaining Git, plan-save,
and launch families before expanding the refactor.

### 3. Reuse source input and make guards prove they inspected it

The session `source_corpus` fixture already reads tracked and nonignored untracked
text under `src`, `extension`, `tests`, `shared`, `docs`, `skills`, `agents`, and
`prompts`. Five consumers share the `source_scan` worker group. Other guards,
including [cache](../../tests/test_cache_guard.py),
[write](../../tests/test_write_guard.py),
[boundary discipline](../../tests/test_boundary_discipline.py),
[resolve](../../tests/test_resolve.py), and
[delivery policy](../../tests/test_delivery_policy_guard.py), independently walk
or read source. Reuse an appropriate production-source subset and, where useful,
parsed trees. Measure the expanded group: making one worker parse everything can
create a new scheduling bottleneck.

Do not silently change a guard's corpus while sharing its input. Compare selected
paths before and after; preserve production/package exclusions, suffixes, and
handling of newly created files. Keep domain-specific checkers and diagnostic
messages even when discovery is shared.

A concrete weakness exists in
`tests/test_resolve.py::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly`.
It walks production Python files and asserts an empty offender list, without
asserting that it examined any files. A process-local monkeypatch making
`Path.rglob` return an empty iterator let that test pass. The real tree is
nonempty; this demonstrates susceptibility to vacuity if discovery breaks, not
that the current run inspects nothing.

Repair this guard rather than deleting it: assert a nonempty intended corpus and
known source anchors, and run a synthetic prohibited import through the same
checker to prove detection. Existing boundary-discipline tests offer a useful
model with source anchors and positive/negative checker inputs. Preserve the
independent assertions explained in the repository's
[vacuity guidance](../learned/workflow/vacuity-proof-tests.md) and
[source-scan guidance](../learned/workflow/source-scan-guards.md).

### 4. Provide full, fast, and slow commands

Keep selection opt-in. Proposed command contract:

| Command | Selection |
| --- | --- |
| `just test-py` | Entire default Python suite, including slow cases |
| `just test-py-fast` | Default Python cases without `slow` |
| `just test-py-slow` | Default Python cases marked `slow` |
| `just test`, GitHub CI, perk's Python gate | Entire default Python suite |
| `just prose-review-test` | Existing separate opt-in prose suite |

The future recipes should preserve the full entrypoint and quote the compound
marker expression in the recipe itself:

```just
test-py *args:
    uv run pytest {{args}}

test-py-fast *args:
    uv run pytest -m "not slow" {{args}}

test-py-slow *args:
    uv run pytest -m slow {{args}}
```

Register `slow` in `[tool.pytest.ini_options]` and append `--strict-markers` to
the existing addopts; retain `-n auto --dist loadgroup`. Mark tests or parameter
cases, not fixture definitions: ordinary marks on fixtures have no effect.
Unknown marker spellings should fail collection.
[Pytest's marker documentation](https://docs.pytest.org/en/stable/how-to/mark.html)
supports this configuration. For ad hoc compound marker expressions, use direct
`uv run pytest -m 'not slow'`; variadic recipe interpolation is not a reliable
way to preserve the caller's shell quoting.

Separate commands support focused iteration, independent failure reports, and
concurrent execution. On separate CI runners, the tiers could execute without
competing for the same local CPU and filesystem resources. Any future CI split
must require both jobs to pass and account for their combined collection; the
current proposal keeps the existing full-suite gates.

On one machine, each invocation starts its own xdist pool. With this repository's
cap, two default invocations can create twelve workers, while `just test-py`
already schedules the full suite across six. Extra processes, repeated collection
and session fixtures, and filesystem contention may offset any scheduling gain.
This follows from [xdist's per-worker fixture lifecycle](https://pytest-xdist.readthedocs.io/en/stable/how-to.html);
the concurrent wall-time effect has not been measured here.

Benchmark concurrent tiers with an explicit shared worker budget first: for
example, run `just test-py-fast -n4` and `just test-py-slow -n2` concurrently,
compared with `just test-py -n6`. Four plus two is an experiment, not a calibrated
allocation. Record time until fast feedback and time until **both** commands have
exited, including cleanup, and preserve both exit statuses. Keep report paths
distinct and never assign both invocations the same explicit `--basetemp`.
Retain build grouping within the slow tier and check for duplicated shared setup.

A serial run of 36 selected integration cases passed in 25.15 seconds reported
by pytest. The following are initial slow candidates, subject to repeated serial
measurement after fixture improvements:

| Candidate | Cases | Setup-inclusive serial evidence | Why the case remains valuable |
| --- | ---: | --- | --- |
| All existing `wheel_build` consumers in `test_packaging.py` | 10 | 4.628 s together; first consumer pays 4.571 s | Real wheel/sdist contents, exclusions, and shipping contracts |
| `test_npm_pack_lists_shipped_and_excludes_dev` | 1 | 1.442 s | Actual npm publication file set |
| `test_binding_render_cross_plane_byte_parity` | 1 | 1.291 s | Independent Python/TypeScript rendering, nonempty output, Unicode and CRLF |
| `test_refinement_loop_end_to_end_over_a_fake_linear_objective` | 1 | 1.650 s | Complete refinement save/approval path across implementations |
| `test_amended_bottom_layer_cascades_with_exact_transplants` | 1 | 2.647 s | Real Git transplants and downstream propagation |
| `test_conflicted_cascade_resolves_through_the_real_continue_arc` | 1 | 3.022 s | Real conflict and continue behavior |

These **15 candidates** do not imply a measured fast-suite speedup. Parallel
overlap and collection remain; shared fixture costs move between first consumers.
Confirm classification with repeated isolated timings. A repeatedly expensive
case, or an expensive fixture cohort, is a useful criterion; a single one-second
parallel outlier is not an automatic tagging rule. Document the expensive resource
and the case's regression role when assigning the marker.

Mark all ten build consumers together. Leaving one unmarked still builds the
artifacts in the fast suite. Preserve their `xdist_group("wheel_build")` so a full
run builds once. Keep the remaining cheap packaging/manifest checks fast.
Likewise, retain prompt parity in the fast tier: its two cases totaled only
0.210 s serially. The real orphan-sweep integration was 0.419 s, so do not mark
the entire cascade module slow. Optimize stack seeding before deciding which
checkout cases warrant a slow marker.

Slow is a selection label, not a skip, xfail, quarantine, or nightly-only gate.
CI must continue providing the tools required by packaging and cross-plane
checks. Validate that fast and slow node-ID sets are disjoint and their union
equals the full default collection. Also prove that the fast selection requests
no wheel/sdist build fixture. Update developer command documentation when the
new commands are implemented.

### 5. Delete only cases with a demonstrated surviving owner

Normalized test bodies identified candidates; fixture closures, parameter inputs,
marks, helper implementations, and assertions determined redundancy. The first
five pairs below have identical bodies after ignoring comments and no differing
fixture or marker context. The final two repeat subsets of a broader equality
assertion in the same module.

| ID | Remove this node ID | Retain this node ID | Surviving guarantee |
| --- | --- | --- | --- |
| D1 | `tests/test_workflow_cmd.py::test_cancel_run_not_dispatched` | `tests/test_workflow_cmd.py::test_cancel_both_miss_handleless_record_is_run_not_dispatched` | Same handleless record, auth/discovery setup, CLI cancellation, and `run_not_dispatched` result |
| D2 | `tests/test_cli_help_sections.py::test_aliases_still_parenthetical` | `tests/test_cli_aliases.py::test_help_lists_alias_in_parenthetical_only` | Same successful root help, parenthetical aliases, and absence of standalone alias rows |
| D3 | `tests/test_objective_store.py::TestValueTypes::test_objective_body_update_string_comment_id` | `tests/test_objective_store.py::TestValueTypes::test_objective_body_update_exposes_objective_id` | Same objective/comment identity and frozen-value assertions |
| D4 | `tests/test_linear_objectives.py::TestUpdateObjectiveNode::test_comment_not_found_degrades` | `tests/test_linear_objectives.py::TestEntityNotFoundDiscrimination::test_comment_observed_shape_degrades` | Same missing-comment error, degraded update result, and absence of `commentUpdate` |
| D5 | `tests/test_linear_objectives.py::TestEntityNotFoundDiscrimination::test_read_observed_shape_is_none` | `tests/test_linear_backend.py::TestGetPlan::test_entity_not_found_is_none` | Same shared fake/backend helper, observed error shape, and missing plan returning `None` |
| D6 | `tests/test_cli_parity_smoke.py::test_root_visible_command_set_unchanged` | `tests/test_cli_parity_smoke.py::test_live_surface_matches_canonical_fingerprint` | Full literal fingerprint equality already includes root command names and aliases |
| D7 | `tests/test_cli_parity_smoke.py::test_each_group_verb_set_unchanged` | `tests/test_cli_parity_smoke.py::test_live_surface_matches_canonical_fingerprint` | Full equality already includes every group's verbs and aliases |

Full A charged D1–D7 respectively 0.104, 0.001, 0.003, 0.004, 0.004, 0.001,
and 0.001 seconds. Removing all seven would reduce the current collection from
6,842 to 6,835 before any other additions or changes. That count is an audit
expectation for this revision, not a proposed hardcoded suite invariant. The
benefit is clearer ownership and less maintenance; it is not a meaningful
wall-time optimization.

Before deleting, run each affected module and its surviving owner, and retain
the ledger in the implementation review. No modified-suite coverage comparison
or mutation campaign was performed during this research; static equivalence is
the evidence for these specific proposals.

Several superficially similar cases should **stay**:

- The nonempty-corpus assertions in `test_user_docs_findability.py` and
  `test_user_docs_metadata.py` protect distinct local walkers. An identical
  assertion body does not make those guards interchangeable.
- `test_no_claim_vocabulary` and
  `test_malformed_or_non_positive_resolves_no_number` in `test_issue_backend.py`
  have different parameter domains, including absent versus malformed values.
- Constructor/facade matrices often differ by request type or invalid input even
  when the body is identical. Full A's 291-case delivery-facade module cost only
  0.600 s; high case count alone is a poor optimization target.
- `False` and `None` ancestry/probe inputs preserve negative-versus-unknown
  semantics. Branch overlap does not justify collapsing them.
- A no-exception assertion or a fake that fails on any forbidden subprocess can
  protect fail-soft/no-side-effect behavior without an explicit `assert` line.
- Cross-plane parity tests exercise independent implementations. Replacing one
  side with a fake removes the property they are supposed to check.

## Experiments that do not yet justify a change

### Temporary directories and shutdown

The 36-case serial integration run took **51.92 s externally**, although pytest
reported 25.15 s. Timing hooks observed `pytest.main` return at 25.59 s and an
atexit `cleanup_numbered_dir` call taking **25.43 s**. That cleanup removed older
retained runs, so its cost cannot be charged entirely to those 36 tests. Full B
also had a 17.73-second gap between JUnit file creation and the final timing log.
The latter is evidence of a post-report tail, not proof that all of it was the
same cleanup function.

Pytest normally retains three temporary-directory runs. The `failed` policy
removes passed-test directories and successful session roots earlier. This can
shift deletion into teardown rather than eliminate it, and successful-run
artifacts become unavailable for inspection.
[Pytest's temporary-directory documentation](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
describes retention and warns that a configured `--basetemp` directory is cleared.

The full-suite `failed` samples were 106.16 and 144.17 s versus default samples
107.59 and 118.40 s. **Do not switch retention policy on this evidence.** Repeat
an interleaved comparison with comparable retained-directory populations, host
load, and cleanup accounting. Record temporary bytes/files as well as wall time.
If experimenting with `--basetemp`, allocate a fresh dedicated directory; never
point it at a checkout or an existing general-purpose temporary directory.
Disabling cleanup or allowing unbounded retention would merely defer the cost.

All 6,842 cases request `tmp_path` indirectly through the autouse
`isolated_pi_agent_dir` fixture, including pure value tests. Its redirect prevents
tests from reading or repairing the developer's real pi store. The child
`pi-agent` directory is already lazy; `tmp_path` itself is still allocated.
Retain this isolation. The Doctor profile measured only 0.370 s for 272 tmp-path
setups, 0.016 s in the redirect fixture, and 0.009 s in the prompt guard. A
different safe per-test path allocator is a lower-priority experiment, not a
reason to remove autouse protection or share mutable state.

### YAML loading

The Doctor profile motivates a parser experiment, but first remove unnecessary
engine calls. An in-memory microbenchmark on the actual three shared YAML files
used PyYAML 6.0.3 with libyaml available, 20 parses per trial and three trials.
The parsed objects matched for these files.

| Input | Median `SafeLoader` time per parse | Median `CSafeLoader` time per parse | Ratio |
| --- | ---: | ---: | ---: |
| `shared/registry.yaml` | 9.217 ms | 0.888 ms | 10.4× |
| `shared/providers.yaml` | 3.868 ms | 0.195 ms | 19.8× |
| `shared/bindings.yaml` | 2.150 ms | 0.206 ms | 10.4× |

This is **not a 10–20× suite speedup**, and no production parser was changed.
[PyYAML documents its C bindings and implementation differences](https://pyyaml.org/wiki/PyYAMLDocumentation).
A separate production proposal would need safe-loader semantics, malformed-input
and error-message compatibility, any resolver customization, platforms without
libyaml, and full-suite measurements. Never substitute an unsafe loader or cache
mutable config across tests. Global memoization could hide config-change
regressions; reducing repeated test setup is the safer first intervention.

### Collection, plugins, imports, scheduling, and waits

Serial collection reported 2.58 s, with 3.11 s around `pytest.main`. Three
third-party plugin entrypoints were installed: xdist, xdist looponfail, and anyio.
There is little evidence for large wins from plugin pruning. If measured, disable
autoload in a controlled invocation and explicitly load required plugins; compare
the collection and marker inventory as well as time.
[Pytest documents plugin loading controls](https://docs.pytest.org/en/stable/how-to/plugins.html).
Each xdist worker performs collection, so serial collection alone does not
measure total parallel startup cost.
[Xdist's execution model](https://pytest-xdist.readthedocs.io/en/stable/how-it-works.html)
explains this behavior.

The binding-render parity test already batches three triggers through one Node
child. Its helper reaches the pi SDK through the binding-delivery import graph.
Reducing that import graph might help, but startup attribution was not measured
separately. Keep nonempty byte-parity assertions and real imports at the relevant
boundary; do not manufacture a matching result to avoid startup.

Retain `loadgroup`. `worksteal` is not a drop-in replacement for its group
guarantee, and `loadfile`/`loadscope` can concentrate the large Doctor module on
one worker. After reducing repeated work, compare explicit four-, six-, and
eight-worker runs where the host supports them, holding grouping constant.
Measure artifact-build counts and shutdown as well as wall time.
[Xdist distribution modes](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
and the existing [parallelism note](../learned/toolchain/test-parallelism.md)
explain why grouping and worker count are separate decisions.

Literal sleep searches found a 0.005-second ULID wait and a 0.2-second real
installation-lock race among default tests. The conspicuous longer prose waits
belong to the excluded opt-in suite. Sleeps are not the dominant default cost.
Use deterministic barriers or events when improving concurrency tests, but keep
a real lock-contention integration; replacing all locking with fakes would reduce
regression safety for little measured benefit.

## Evidence required before broader pruning

For each proposed removal or narrowed integration, record the input domain,
behavioral claim, observable assertion, fixture/side-effect requirements, and
named surviving test. Similar names, identical execution coverage, or a shorter
test count do not establish equivalent regression detection.

Per-test coverage can help find candidates. A temporary diagnostic environment
using pytest-cov with `--cov-branch --cov-context=test` can associate execution
with parameterized test IDs and phases. Neither coverage nor pytest-cov is
currently a project dependency; keep profiling separate from timing baselines.
[Pytest-cov contexts](https://pytest-cov.readthedocs.io/en/latest/contexts.html)
and [coverage branch measurement](https://coverage.readthedocs.io/en/latest/branch.html)
provide the relevant mechanisms.

Compare branch arcs and per-test contexts before and after a proposed deletion,
then inspect the assertions. Executing a line does not show that an incorrect
result would fail a test, as explained in
[Google's coverage guidance](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html).
For a consequential boundary, temporarily inject a plausible fault and verify
that the named survivor fails: drop a registered Doctor check, skip its recheck,
misclassify an unknown Git probe, or let a forbidden import through the guard.
Targeted mutation tooling is an optional extension, not a prerequisite to every
small cleanup. [Mutmut](https://mutmut.readthedocs.io/en/latest/) supports focusing
mutation work; no mutation score is claimed here.

Coverage scope needs care. Pytest-cov 7 moved Python subprocess instrumentation
to coverage.py's `patch = ["subprocess"]` configuration. Verify child-process
coverage explicitly; parent-only data cannot justify deleting worker/CLI tests.
Python coverage does not measure TypeScript execution.
[Pytest-cov subprocess support](https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html)
documents the migration. Preserve independent cross-plane integrations and
mandatory packaging checks even when they add few Python lines.

## Reproduction and acceptance protocol

Record HEAD before and after each run, a clean/dirty status, OS/CPU/tool versions,
worker count, selection, and relevant environment overrides. Avoid simultaneous
benchmark workloads or source edits. Keep raw logs/XML outside the checkout so
source-scanning guards do not ingest the measurements.

```sh
research_dir=$(mktemp -d /tmp/perk-pytest-measure.XXXXXX)
git rev-parse HEAD
git status --short
/usr/bin/time -p just test-py -q --durations=0 --durations-min=0 \
  -o junit_duration_report=total \
  --junitxml="$research_dir/full.xml" >"$research_dir/full.log" 2>&1
git rev-parse HEAD
```

Use distinct report names for each sample. The XML contains total test-phase
durations; `real` in the log supplies external wall time. Pytest's console
duration and XML suite duration can differ, particularly during session cleanup;
label the field used consistently. The table above uses console duration.
[Pytest's invocation guide](https://docs.pytest.org/en/stable/how-to/usage.html)
describes duration reporting and selection.

Inspect an expensive family serially before treating a parallel outlier as an
intrinsic cost:

```sh
just test-py -n0 -q tests/test_doctor.py --durations=25
just test-py -n0 -q tests/test_packaging.py tests/test_binding_render_parity.py \
  tests/test_prompt_parity.py tests/test_pr_review_stack_checkout.py \
  tests/test_delivery_sync_integration.py \
  tests/test_objective_refine_cmd.py::test_refinement_loop_end_to_end_over_a_fake_linear_objective \
  --durations=0 --durations-min=0
uv run --locked python -m cProfile -o "$research_dir/doctor.pstats" \
  -m pytest -n0 -q tests/test_doctor.py
```

For process counts, install a temporary `sys.addaudithook` before `pytest.main`
and count `subprocess.Popen` events by executable and Git verb. The research hook
counted invocations, not just time in a particular wrapper. For exit attribution,
wrap pytest's installed `cleanup_numbered_dir` before invoking pytest and time
the wrapper through interpreter exit. These are version-specific diagnostic
hooks, not new test harness dependencies or production instrumentation.

Repeat the retention comparison by adding
`-o tmp_path_retention_policy=failed` to the same timed full command. The policy
changes retained state, so a fresh unique base and a steady-state retained base
answer different questions. Name and control that choice; include deferred
cleanup in the evaluation.

After introducing markers, audit collection with the same opt-in prose setting
for all three invocations:

```sh
just test-py -n0 --collect-only -q
just test-py-fast -n0 --collect-only -q
just test-py-slow -n0 --collect-only -q
```

Compare actual node-ID sets, not just printed totals: `fast ∩ slow = ∅` and
`fast ∪ slow = full`. Run both tiers and verify their outcomes match the full
invocation, including skips and required-tool availability. Ensure none of the
wheel-build consumers leaks into fast selection and that a full parallel run
still performs one shared build.

For each performance change, collect at least three comparable baseline and
three candidate full-suite samples, interleaving configurations where practical.
Report individual samples, median, range, worker-time distribution, and any
startup/shutdown tail. Document host interference instead of silently dropping
unfavorable runs. A change should show a repeatable wall-time improvement beyond
the observed noise, or have a separately stated maintenance/safety benefit.
No percentage or seconds target is promised by the current evidence.

## Proposed implementation sequence

1. **Doctor ownership and narrow execution.** Move single-check matrices to the
   real check/converger seams, retain named engine/CLI/dogfood stories, and
   compare subprocess counts and serial/full timings. Stop broadening this work
   once the measured Doctor hotspot is addressed.
2. **Fixture reuse.** Add only the specialized Git worlds justified above,
   retain real per-case mutations, and extend copy-isolation checks. Reprofile
   before taking on other Git-heavy families.
3. **Guard safety and duplicate cleanup.** Repair empty-corpus susceptibility,
   consolidate discovery where scopes match, and remove D1–D7 with the survivor
   ledger. Treat this as a quality improvement with modest performance upside.
4. **Full, fast, and slow commands.** Recheck the 15 candidate cases after earlier
   changes, implement the three-command/marker contract, document it, and prove
   full collection accounting and build grouping. Compare concurrent tiers with
   the full command using the same total worker budget. Keep the complete Python
   gates.
5. **Only then evaluate remaining runtime experiments.** Investigate retention,
   safe YAML loading, imports, and worker calibration independently. Land a
   production optimization only with its own compatibility and regression proof.

Use targeted checks during implementation. Each future perk phase retains the
repository's dogfood gate before proceeding; submission follows the existing
single run-all `run_ci` convention. Research timing runs are diagnostic evidence,
not replacements for that gate. Preserve summarized before/after results in the
implementation record rather than introducing a machine-specific timing test.

The current evidence includes collection inspection, same-revision full-suite
runs, a serial integration cohort, a Doctor profile/process census, the retention
experiment, the YAML microbenchmark, static duplicate review, and the empty-walk
guard probe. It does **not** include a modified-suite benchmark, a full per-test
branch map, a mutation campaign, or newly calibrated worker counts. Those limits
bound the claims and define what the follow-up changes must demonstrate.
