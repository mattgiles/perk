"""The provenance-posture table's cross-plane parity (contracts.md §8.40).

The TS plane governs every foreign tool by WHO registered it — a package row keyed on the
normalized package spec, an exact synthetic-path row, or the unknown fallback — and renders that
table into the shared golden matrix (`shared/fixtures/tool-matrix.json`, drift-guarded by
`extension/substrate/toolMatrix.test.ts`). The Python plane is what `perk init` wires into a
repo's `packages`. This pins the two vocabularies together: every tool-registering package perk
can install has a posture row, and every row names a package perk can install — so a new borrow
must get a row (or join the known tool-less set) in the same change.
"""

import json
from pathlib import Path

from perk.convergence.init.settings import BORROWED_PACKAGES, LINEAR_PACKAGE
from perk.substrate.providers import load_providers

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((REPO_ROOT / "shared" / "fixtures" / "tool-matrix.json").read_text("utf-8"))
POSTURES = MATRIX["postures"]

# Packages perk installs that register no model-facing tool (ponytail is installed with its
# extensions filtered out), so they need no posture row.
ZERO_TOOL_PACKAGES = frozenset(
    {"npm:@tombell/pi-diff", "npm:@dietrichgebert/ponytail", "npm:@tombell/pi-plan"}
)

# The seams whose providers register tools; footer providers are a separate, tool-less seam.
TOOL_SEAMS = ("web", "plan")

FOREIGN_POSTURES = {"research", "universal", "delegation", "never", "child-engine"}


def normalize(spec: str) -> str:
    """The identity both planes key packages by: an `npm:` spec without its version/range."""
    if not spec.startswith("npm:"):
        return spec
    body = spec[len("npm:") :]
    at = body.rfind("@")
    return f"npm:{body[:at]}" if at > 0 else spec  # at == 0 is a scope's leading @


def installable_tool_packages() -> set[str]:
    providers = load_providers().providers
    provider_packages = {
        p.package for p in providers if p.seam in TOOL_SEAMS and p.package is not None
    }
    every = {*BORROWED_PACKAGES, LINEAR_PACKAGE, *provider_packages}
    return {normalize(spec) for spec in every} - ZERO_TOOL_PACKAGES


def test_normalize_matches_the_ts_rule() -> None:
    assert normalize("npm:pi-subagents@0.73.1") == "npm:pi-subagents"
    assert normalize("npm:@scope/name@^1") == "npm:@scope/name"
    assert normalize("npm:@scope/name") == "npm:@scope/name"
    assert normalize("builtin") == "builtin"


def test_every_installable_tool_package_has_exactly_one_posture_row() -> None:
    assert set(POSTURES["packages"]) == installable_tool_packages()


def test_the_zero_tool_set_is_installable_and_carries_no_row() -> None:
    providers = {p.package for p in load_providers().providers if p.package is not None}
    installable = {normalize(spec) for spec in {*BORROWED_PACKAGES, *providers}}
    assert installable >= ZERO_TOOL_PACKAGES
    assert not (ZERO_TOOL_PACKAGES & set(POSTURES["packages"]))


def test_rows_are_well_formed() -> None:
    for spec, row in POSTURES["packages"].items():
        assert normalize(spec) == spec, f"{spec}: keys are normalized specs"
        assert row["posture"] in FOREIGN_POSTURES, spec
        if "except" in row:
            assert row["except"]["posture"] in FOREIGN_POSTURES, spec
            assert row["except"]["names"], f"{spec}: an exception names its tools"


def test_the_exact_path_rows_and_the_unknown_fallback() -> None:
    assert set(POSTURES["paths"]) == {"<inline:pi-subagents:prompt-runtime>"}
    assert POSTURES["paths"]["<inline:pi-subagents:prompt-runtime>"]["posture"] == "child-engine"
    assert POSTURES["unknown"] == {"stages": "all", "gated": "blocked"}


def test_the_matrix_tools_carry_no_foreign_name() -> None:
    owners = {entry["owner"] for entry in MATRIX["tools"].values()}
    assert owners <= {"perk", "builtin"}
