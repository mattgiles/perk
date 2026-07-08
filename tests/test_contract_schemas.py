"""Drift + coverage guard for the boundary-model JSON Schema golden snapshots.

The committed ``shared/schemas/**/*.schema.json`` artifacts are regenerated only via
``PERK_UPDATE_SCHEMAS=1 uv run pytest tests/test_contract_schemas.py``; these tests
fail CI on any un-regenerated drift, so a schema change is always reviewed.
"""

import pytest
from _schemas import SCHEMAS, SchemaEntry, assert_schema, iter_schema_files


@pytest.mark.parametrize("entry", SCHEMAS, ids=lambda e: e.path)
def test_schema_matches_committed(entry: SchemaEntry) -> None:
    # Per-model drift signal: the committed file equals the freshly-generated schema.
    assert_schema(entry)


def test_no_orphan_or_missing_schema_files() -> None:
    # The set of committed schema files is exactly the set of registered output paths:
    # a registered model with no committed file, or a stale file with no registered
    # model, both fail here.
    committed = {p.name for p in iter_schema_files()}
    registered = {entry.path.rsplit("/", 1)[-1] for entry in SCHEMAS}
    # Names are unique across subdirs; compare full relative paths for total coverage.
    from _schemas import SCHEMAS_DIR

    committed_rel = {str(p.relative_to(SCHEMAS_DIR)) for p in iter_schema_files()}
    registered_rel = {entry.path for entry in SCHEMAS}
    assert committed_rel == registered_rel, {
        "orphans": committed_rel - registered_rel,
        "missing": registered_rel - committed_rel,
    }
    assert committed == registered  # filenames coincide (no cross-subdir collisions)


def test_mode_matches_category() -> None:
    # The per-category mode invariant (dignified-pydantic §32): parse/input contracts
    # snapshot their accepted-input shape (validation); output envelopes snapshot their
    # emitted ``--json`` shape (serialization). Guards against a model registered under
    # the wrong category with the wrong mode.
    for entry in SCHEMAS:
        subdir = entry.path.split("/", 1)[0]
        expected = "serialization" if subdir == "outputs" else "validation"
        msg = f"{entry.path}: {subdir}/ implies {expected}, got {entry.mode}"
        assert entry.mode == expected, msg
