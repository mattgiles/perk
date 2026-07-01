"""Doctor's pure data layer: ``Status``/``Check``/``DoctorReport`` + the managed-group map.

A leaf module (imports nothing from the ``doctor`` package) so the check submodules can construct
``Check`` without a circular import. Re-exported by the package facade.
"""

from dataclasses import dataclass, field
from typing import Literal, Self

Status = Literal["ok", "warn", "info", "fail"]

# Render groups for the managed convergences: settings under "package", the workflow-dir/cache
# layout under "state", the rest under "repository".
_MANAGED_GROUP: dict[str, str] = {
    "settings-wiring": "package",
    "workflow-dir": "state",
    "skills-manifest": "skills",
    "runner-workflow": "repository",
}


@dataclass(frozen=True)
class Check:
    """A single health finding — pure data, so the report/render layer needs no monkeypatch."""

    name: str
    group: str
    status: Status
    message: str
    detail: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Structured result of a ``run_doctor`` (rendered human or ``--json`` by the command)."""

    checks: list[Check]
    fixed: list[str]
    self_repo: bool
    error_type: str | None = None
    message: str | None = None
    fix_errors: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.error_type is None and not any(c.status == "fail" for c in self.checks)

    @property
    def exit_code(self) -> int:
        if self.error_type == "not_a_repo":
            return 2
        return 1 if any(c.status == "fail" for c in self.checks) else 0

    @classmethod
    def not_repo(cls) -> Self:
        return cls(
            checks=[],
            fixed=[],
            self_repo=False,
            error_type="not_a_repo",
            message="Not a git repository — run 'perk doctor' inside a git repository.",
        )
