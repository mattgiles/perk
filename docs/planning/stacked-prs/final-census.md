# Final delivery census — the convergence-audit record

The node 5.1 one-time record: the final import-and-delivery-mechanism census over the completed
`perk.delivery` migration (nodes 1.1–4.2), the export-ceiling verification, the retained-wording
table, and the per-node three-dimension verification matrix. Everything here was re-enumerated at
implementation time on this branch (evidence, not a CI guard — the one durable enforcement point
stays `tests/test_delivery_facade.py::test_public_export_cut_is_exact`).

## The export ceiling (read-only verification)

`perk.delivery.__all__` holds exactly the canonical **20 names**: 1 `Delivery` +
1 `resolve_delivery` + 1 `DeliveryError` + 3 authority ABCs (`DeliveryPersistence`,
`DeliveryGit`, `DeliveryGitHub`) + 14 request/result pairs (`Status`/`Prepare`/`Publish`/
`Sync`/`Transfer`/`Recover`/`Land` × Request+Result). `test_public_export_cut_is_exact` pins the
exact set (`exported == _NEW_EXPORTS`, `len(__all__) == 20`) and asserts every retired name
absent — the pin subsumes every per-node export cut.

## The import census

Enumeration: `grep -rn "from perk.delivery\|import perk.delivery" src/perk --include='*.py'`
filtered to paths outside `src/perk/delivery/`.

**Root-path imports** (the canonical surface; all names are among the 20):
`cli/commands/plan/save_cmd.py`, `cli/commands/objective/replan_cmd.py`,
`cli/commands/objective/create_cmd.py`, `cli/commands/objective/plan_cmd.py`,
`cli/commands/objective/stack/sync_cmd.py`, `cli/commands/objective/stack/recover_cmd.py`,
`cli/commands/pr/submit_cmd.py`, `run/launch/worktree.py`, `run/run_worker.py`, plus the root
halves of the mixed imports below. `pr/submit_cmd.py` additionally aliases
`from perk.delivery import SyncResult as DeliverySyncResult` — a root-path import kept aliased
because the `PrSubmitResult.delivery` *field* shadows the `delivery` module name inside the
dataclass body (this node deleted its former `perk.delivery.facade` bypass path).

**Submodule-path references** (deliberate; presentation and design-recorded internals stay
outside the façade):

| Reference | Consumers | Classification | Anchoring record |
|---|---|---|---|
| `delivery.train` types (`DeliveryTrain`, `TrainLayer`, `TrainFinding`, `BuildReadiness`, `LayerPublication`, `LayerMembership`, `LayerWriter`, `STRUCTURAL_BLOCKER_CODES`, `TrainReconstructionError`) | `cli/commands/objective/shared.py`, `objective/doctor_cmd.py`, `objective/stack/status_cmd.py`, `objective/stack/land_cmd.py` | Accepted — nested render vocabulary | Variant/detail types are deliberately non-root (architecture.md "One deep module"); §8.44 read-path projection |
| `delivery.land` (`LandReadiness`, `LandLayerReadiness`, `LandPlan`) + `delivery.landing` (`LandedLayer`, `LandEvidence`) | `objective/stack/land_cmd.py` | Accepted — nested render vocabulary | The §8.55 projection is embedded in `LandResult.Objective` as-is |
| `train.resolve_active_objective` | `objective/shared.py`, `objective/doctor_cmd.py`, `objective/stack/shared.py` | Accepted — retained read-only helper | The `superseded_by` forward walk deliberately lives in train reconstruction so every stack command redirects identically (`stack/shared.py` docstring; §8.44 names `stack/shared.py` a migrated façade consumer) |
| `recover.observe_orphans` | `objective/stack/status_cmd.py` | Accepted — retained read-only helper | The objective-recorded retained read-only orphan classifier |
| `continuation.pending_continuation` | `objective/stack/status_cmd.py` | Accepted — retained read-only helper | The read-only §8.49 continuation probe for status rendering |
| `diagnostics.classify_finding` | `objective/doctor_cmd.py` | Accepted — retained read-only helper | The §8.54 finding-policy read; the only mutation path is `Delivery.recover`'s cancellation-metadata variant (`diagnostics.py` module docstring) |
| `layer.LayerContext` / `layer.LayerContextOut` | `state/cache.py`, `run/launch/worktree.py` (`run/run_worker.py` consumes via `cache.write_layer_context`) | Accepted — retained internal layer core | §8.46 ("none is exported from `perk.delivery`") |

**Fixed by this node:**

| Finding | Disposition |
|---|---|
| `pr/submit_cmd.py`: `from perk.delivery.facade import SyncResult as DeliverySyncResult` | FIXED — re-imported from the package root (aliased for the field-shadowing reason above) |
| Dead compatibility chain: `observe.TrainReads`, `observe.resolve_train_reads`, `observe.reconstruct_repo_train`, `transfer.resolve_transfer_seams` | DELETED — reached only through `resolve_transfer_seams`'s default argument, itself caller-less (the façade constructs `TransferSeams` directly in `facade.py`, binding `self._reconstruct_train_status` for both transfer and recover roll-forward); no test exercised any of the four symbols. contracts.md §8.53 rewords the deleted symbol to the surviving behavior |

## The mechanism census

Production outside `src/perk/delivery/` contains **zero** references to any retired delivery
mechanism: `publish_layer`, `synchronize_train`, `run_transfer`, `recover_operations`,
`RecoverError`, `land_train`, `LandError`, `preflight_stacked_authoring`,
`probe_atomic_push_urls`, `finalize_landed_plan`, `squash_commit_message`,
`_stacked_layer_identity`, `GhaRemoteWriterProbe` (`perk/run/writer_probe.py` is deleted), and
`reconstruct_train` has no out-of-package caller. `github.mark_pr_ready` is defined and exported
by `perk.github` and invoked only by the delivery GitHub adapter
(`RepoDeliveryGitHub.mark_pr_ready`). The TS extension has zero `perk.delivery` references.
**No production caller invokes delivery mechanics — journal/persistence writes, `oplock`
acquisition, the publication/sync/transfer/recover/land engines, or authority assembly — outside
a façade operation.**

Tests: no test imports, constructs, or calls a retired seam. The sanctioned grep hits are
(a) the retired-name *strings* in `test_delivery_facade.py`'s absence assertions
(`_RETIRED_EXPORTS` + the module-level `hasattr` checks), (b) local fixture-helper names there
(`_real_publish_layer`/`_cascade_publish_layer`, which construct `PublishResult.Layer`), and
(c) `tests/test_delivery_finalize.py`, which imports the **package-internal**
`perk.delivery.finalize` module by path to pin the retained per-layer finalizer (§8.56's
package-internal machinery — a retained internal under test, not a retired seam).

## The retained-wording table (runtime semantics, not migration residue)

| Location | Wording | Why it stays |
|---|---|---|
| `delivery/landing.py` | "the CLOSE is deferred", "objective close deferred until the completed outcome is journaled" (×2) | Genuine runtime deferral: closing before the completion is durable would strand the record |
| `delivery/landing.py` | "cannot yet exclude a live merge request" | Genuine runtime uncertainty in the handle-evidence message |
| `delivery/recover.py` | "a deferred completed append", "convergence close deferred: LAND operation(s)…" | Runtime journal semantics |
| `delivery/layer.py` | "deferred publication" (×2) | Publication invokes the layer core later through injected closures — current design (§8.46) |
| `delivery/sync.py` | "the private named sync refusal retained for deferred recovery consumers"; "the deferred record-recovery seam" | The Node-2.1-retained internal record-recovery core replays sync records later — current design |
| `shared/contracts.md` §8.43 | "the deferred 'later node's concern' this sentence originally named" | Past-tense historical record |
| `shared/contracts.md` §8.45 | "in-place adoption of a stacked objective is deferred — no roadmap node owns it" | A current runtime refusal recording an explicitly-flagged deferral (still true) |
| `shared/contracts.md` §8.49 | "consumed by sync, publish routing, transfer, and deferred recovery" | "Deferred recovery" names the runtime concept — recover replays sync/transfer records later through the retained record-recovery seam |
| `shared/contracts.md` §8.44 | the "61-name `perk.delivery.__all__` of that era" passage | Sanctioned past-tense historical record |
| `architecture.md` | the retirement narrative ("…whose only public purpose was the unmigrated landing path") | Sanctioned past-tense historical record |

Reconciled to final-state wording by this node: the `facade.py` authority-ABC and `_fakes.py`
docstrings (sync-era family lists → all seven families), the `test_delivery_facade.py` module
docstring, `delivery/__init__.py` (dropped "compatibility readers"), `observe.py` (docstring
rewrite with the chain deletion), `land_plan.py`/`recover.py` ("temporarily retained" →
"package-internal"), contracts.md §8.53 (deleted-symbol reword), §8.56 ("temporarily retained" →
"package-internal"), §8.44's status paragraph (doctor findings have since landed — §8.54),
§8.49's preflight parenthetical (adoption has since landed as `--adopt`), and architecture.md's
two "temporarily retained per-layer finalizer" runtime descriptions.

## The per-node verification matrix

Three dimensions per node. **Surface removal**: the retired-name production greps return empty
outside the package and `test_public_export_cut_is_exact` passes (the exact root pin subsumes
every per-node cut). **Test retirement**: the `tests/` grep's only hits are the sanctioned ones
above. **Docs**: `shared/contracts.md` §8.42–§8.56 (+ the §8.4 land record) and
`architecture.md` describe the final façade state —
`grep -n "temporary export\|until Node\|unmigrated\|temporarily retained\|[0-9]\+ exports"` over
both returns only the sanctioned historical survivors.

| Node | Family migrated | Surface removal | Test retirement | Docs |
|---|---|---|---|---|
| 1.1 | Façade + status (`resolve_delivery`, train reads internal) | PASS | PASS | PASS |
| 1.2 | Authoring Prepare (`preflight_stacked_authoring` retired) | PASS | PASS | PASS |
| 1.3 | Plan-identity + layer-start Prepare (`LayerContext` core internal) | PASS | PASS | PASS |
| 2.1 | Sync (`synchronize_train`, `probe_atomic_push_urls` retired) | PASS | PASS | PASS |
| 2.2 | Publish (`publish_layer` retired) | PASS | PASS | PASS |
| 3.1 | Transfer (`run_transfer` retired) | PASS | PASS | PASS |
| 3.2 | Recover conclusion (`recover_operations`, `RecoverError` retired) | PASS | PASS | PASS |
| 3.3 | Cancellation-metadata repair (report-only recover variant) | PASS | PASS | PASS |
| 4.1 | Incremental Land (`finalize_landed_plan` et al. internal) | PASS | PASS | PASS |
| 4.2 | Objective Land (`land_train`, `LandError` deleted; readiness/journal/persistence exports retired) | PASS | PASS | PASS |
