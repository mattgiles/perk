"""Boundary-discipline source-scan guard: Pydantic stays confined to the edges.

perk's discipline is: Pydantic models live only at the parse/serialize boundary
(the role-named bases in ``perk/boundary.py`` — ``LenientParseModel`` /
``StrictInputModel`` / ``OutputModel`` — plus ``RootModel`` subclasses), and every
internal domain object is a frozen ``@dataclass``. No module subclasses raw
``pydantic.BaseModel`` directly, and the legacy ``StrictBoundaryModel`` base is gone.

This AST scan flags any ``class X(BaseModel)`` / ``class X(StrictBoundaryModel)``
written outside ``perk/boundary.py`` (which legitimately defines the role-named bases
on ``BaseModel``). Role-named bases appear as different base names and ``RootModel[...]``
appears as an ``ast.Subscript`` — neither is flagged. A backstop, not a proof: it
matches written base-class names, not re-exported aliases (consistent with the repo's
other source-scan guards, e.g. ``tests/test_paths_guard.py``).
"""

import ast
from pathlib import Path

import perk

# Base-class names that may NOT be subclassed outside the boundary module: raw Pydantic
# (a domain object should be a frozen dataclass) and the removed legacy strict-as-domain base.
_BANNED_BASES = frozenset({"BaseModel", "StrictBoundaryModel"})

# The only module allowed to define classes on a banned base: it defines the role-named bases.
ALLOWED = frozenset({"boundary.py"})


def _perk_dir() -> Path:
    return Path(perk.__file__).parent


def _banned_base_classes(source: str) -> list[str]:
    """Class names in ``source`` whose direct base is a banned ``ast.Name``.

    A base written as ``ast.Subscript`` (e.g. ``RootModel[...]``) or any other base name
    (the role-named bases, a frozen dataclass) is not flagged.
    """
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in _BANNED_BASES:
                offenders.append(node.name)
    return offenders


class TestBoundaryDiscipline:
    def test_no_module_subclasses_raw_pydantic_outside_boundary(self) -> None:
        """Source scan: outside ``perk/boundary.py`` no class subclasses raw ``BaseModel``
        (or the removed legacy ``StrictBoundaryModel``)."""
        perk_dir = _perk_dir()
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
        assert any(p.name == "boundary.py" for p in files), (
            "scan missed boundary.py — guard is misaimed"
        )
        offenders: list[str] = []
        for path in files:
            if path.name in ALLOWED:
                continue
            for cls in _banned_base_classes(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(perk_dir.parent)}: class {cls}")
        assert not offenders, (
            "domain objects must be frozen @dataclass and parse/serialize models must subclass "
            "the role-named bases (LenientParseModel / StrictInputModel / OutputModel) in "
            "perk/boundary.py — never raw BaseModel or the removed StrictBoundaryModel:\n"
            + "\n".join(offenders)
        )

    def test_positive_raw_basemodel_is_flagged(self) -> None:
        assert _banned_base_classes("class X(BaseModel):\n    pass\n") == ["X"]
        assert _banned_base_classes("class Y(StrictBoundaryModel):\n    pass\n") == ["Y"]

    def test_negative_role_named_and_dataclass_not_flagged(self) -> None:
        assert _banned_base_classes("class A(LenientParseModel):\n    pass\n") == []
        assert _banned_base_classes("class B(StrictInputModel):\n    pass\n") == []
        assert _banned_base_classes("class C(OutputModel):\n    pass\n") == []
        assert _banned_base_classes("class D(RootModel[str]):\n    pass\n") == []
        assert _banned_base_classes("@dataclass\nclass E:\n    pass\n") == []
