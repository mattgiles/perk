"""JSON-Schema golden-snapshot + drift harness for perk's boundary models.

perk's cross-plane contracts — the shared-YAML parse contracts, the machine batch
inputs, and the ``--json`` output envelopes — are Pydantic boundary models. This
harness snapshots each model's ``model_json_schema()`` as a committed golden artifact
under ``shared/schemas/`` and guards it against unreviewed drift (the snapshots'
function: machine-surface shape changes stay reviewable in PRs).

The schema *mode* is per category: parse/input contracts describe what perk
**accepts** (``mode="validation"``, the default); output envelopes describe what
``--json`` consumers **receive** (``mode="serialization"``). The registry fixes the
mode per file so each artifact is the correct contract direction.

Regen by running a drift test with ``PERK_UPDATE_SCHEMAS`` set in the environment.
The helper **always** re-reads the committed file and asserts equality afterward, so
a regen that produced garbage still fails loudly rather than silently pinning it.

This module has no ``test_`` prefix, so pytest does not collect it (mirrors
``tests/_golden.py``).
"""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from perk.cli.commands.learn.capture_cmd import LearnCaptureOut
from perk.cli.commands.learn.skip_cmd import LearnSkipOut
from perk.cli.commands.objective.doctor_cmd import ObjectiveDoctorOut
from perk.cli.commands.objective.stack.land_cmd import ObjectiveStackLandOut
from perk.cli.commands.objective.stack.recover_cmd import ObjectiveStackRecoverOut
from perk.cli.commands.objective.stack.status_cmd import ObjectiveStackStatusOut
from perk.cli.commands.objective.stack.sync_cmd import ObjectiveStackSyncOut
from perk.cli.commands.plan.save_cmd import PlanSaveOut
from perk.cli.commands.pr.feedback_cmd import PrFeedbackOut
from perk.cli.commands.pr.land_cmd import PrLandOut
from perk.cli.commands.pr.ready_cmd import PrReadyOut
from perk.cli.commands.pr.resolve_threads_cmd import ResolveThreadsBatch
from perk.cli.commands.pr.review.checkout_cmd import PrReviewCheckoutOut
from perk.cli.commands.pr.review.cleanup_cmd import PrReviewCleanupOut
from perk.cli.commands.pr.review_context_cmd import PrReviewContextOut
from perk.cli.commands.pr.review_post_cmd import ReviewBatchInput
from perk.cli.commands.pr.review_submit_cmd import PrReviewSubmitOut, ReviewSubmitBatchInput
from perk.cli.commands.pr.submit_cmd import PrSubmitOut
from perk.cli.commands.state.new_run_cmd import HandoffArgInput
from perk.convergence.doctor import DoctorReportOut
from perk.convergence.init.report import InitReportOut
from perk.objective._models import StructuredRoadmapNode
from perk.substrate.bindings import BindingsFile
from perk.substrate.providers import ProvidersFile
from perk.substrate.registry import RegistryFile

SchemaMode = Literal["validation", "serialization"]

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "shared" / "schemas"


@dataclass(frozen=True)
class SchemaEntry:
    """One snapshotted schema: its committed path (subdir + file), model, and mode."""

    path: str
    model: type[BaseModel]
    mode: SchemaMode


# The single source of truth for "what is snapshotted", grouped by category in
# declaration order. The per-file drift tests and the coverage test both derive
# from it. Parse/input contracts snapshot their accepted-input shape (validation);
# output envelopes snapshot their emitted ``--json`` shape (serialization).
SCHEMAS: tuple[SchemaEntry, ...] = (
    # Shared-YAML parse contracts.
    SchemaEntry("contracts/registry.schema.json", RegistryFile, "validation"),
    SchemaEntry("contracts/bindings.schema.json", BindingsFile, "validation"),
    SchemaEntry("contracts/providers.schema.json", ProvidersFile, "validation"),
    # Machine batch inputs.
    SchemaEntry("inputs/review-post-batch.schema.json", ReviewBatchInput, "validation"),
    SchemaEntry("inputs/review-submit-batch.schema.json", ReviewSubmitBatchInput, "validation"),
    SchemaEntry("inputs/resolve-threads-batch.schema.json", ResolveThreadsBatch, "validation"),
    SchemaEntry("inputs/handoff-arg.schema.json", HandoffArgInput, "validation"),
    SchemaEntry("inputs/structured-roadmap-node.schema.json", StructuredRoadmapNode, "validation"),
    # ``--json`` output envelopes.
    SchemaEntry("outputs/plan-save.schema.json", PlanSaveOut, "serialization"),
    SchemaEntry("outputs/pr-submit.schema.json", PrSubmitOut, "serialization"),
    SchemaEntry("outputs/pr-ready.schema.json", PrReadyOut, "serialization"),
    SchemaEntry("outputs/pr-land.schema.json", PrLandOut, "serialization"),
    SchemaEntry("outputs/pr-feedback.schema.json", PrFeedbackOut, "serialization"),
    SchemaEntry("outputs/pr-review-context.schema.json", PrReviewContextOut, "serialization"),
    SchemaEntry("outputs/pr-review-checkout.schema.json", PrReviewCheckoutOut, "serialization"),
    SchemaEntry("outputs/pr-review-cleanup.schema.json", PrReviewCleanupOut, "serialization"),
    SchemaEntry("outputs/pr-review-submit.schema.json", PrReviewSubmitOut, "serialization"),
    SchemaEntry("outputs/learn-capture.schema.json", LearnCaptureOut, "serialization"),
    SchemaEntry("outputs/learn-skip.schema.json", LearnSkipOut, "serialization"),
    SchemaEntry("outputs/init-report.schema.json", InitReportOut, "serialization"),
    SchemaEntry("outputs/doctor-report.schema.json", DoctorReportOut, "serialization"),
    SchemaEntry(
        "outputs/objective-stack-status.schema.json", ObjectiveStackStatusOut, "serialization"
    ),
    SchemaEntry("outputs/objective-stack-sync.schema.json", ObjectiveStackSyncOut, "serialization"),
    SchemaEntry(
        "outputs/objective-stack-recover.schema.json", ObjectiveStackRecoverOut, "serialization"
    ),
    SchemaEntry("outputs/objective-stack-land.schema.json", ObjectiveStackLandOut, "serialization"),
    SchemaEntry("outputs/objective-doctor.schema.json", ObjectiveDoctorOut, "serialization"),
)


def render(model: type[BaseModel], mode: SchemaMode) -> str:
    """Render a model's JSON Schema as committed bytes (declaration order, 2-space indent).

    No ``sort_keys``: pydantic emits fields in declaration order, which is
    deterministic and meaningful — matching ``_golden.py``'s formatting.
    """
    return json.dumps(model.model_json_schema(mode=mode), indent=2) + "\n"


def iter_schema_files() -> Iterator[Path]:
    """Every committed ``*.schema.json`` under ``shared/schemas/`` (recursive)."""
    return SCHEMAS_DIR.rglob("*.schema.json")


def assert_schema(entry: SchemaEntry) -> None:
    """Assert the committed schema for ``entry`` matches its freshly-generated bytes.

    When ``PERK_UPDATE_SCHEMAS`` is set, (re)write the file from the live model
    first — then still re-read and assert, so a regen against a non-roundtrippable
    schema fails loudly.
    """
    path = SCHEMAS_DIR / entry.path
    actual = render(entry.model, entry.mode)
    if os.environ.get("PERK_UPDATE_SCHEMAS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, f"schema drift for {entry.path}: regen with PERK_UPDATE_SCHEMAS=1"
