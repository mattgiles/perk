"""Delivery-policy absence guard (the failure-hardening ledger's incremental row).

Absent delivery metadata must follow the EXISTING code paths — there is no compatibility
branch. Everything that consumes the objective-header ``delivery`` key routes through ONE
reader, :func:`perk.objective.parse.delivery_policy` (the fail-closed §8.42 classifier);
the other literal-bearing homes only emit or carry the key. This source scan pins that
census: a new quoted ``delivery`` occurrence anywhere else in production code forces the
routed-through-``delivery_policy`` decision consciously; the few homonymous DeliveryError origin
values are an exact stale-failing exemption baseline.

A textual backstop, not a completeness proof (see
``docs/learned/workflow/source-scan-guards.md``): it cannot see a consumer that reads the
key through an alias or a dynamic name — the projection suites own the semantic proofs.
The recipe mirrors ``tests/test_write_guard.py``.
"""

import re
from pathlib import Path

import perk

# Keep the broad literal census so alternate mapping APIs and helper indirection remain loud.
# DeliveryError's required `origin="delivery"` value is a homonym, not an objective-header key;
# exempt only its exact audited value positions instead of weakening the scanner for every file.
DELIVERY_LITERAL_PATTERN = re.compile(r"""["']delivery["']""")
VALUE_EXEMPTIONS: dict[str, tuple[re.Pattern[str], ...]] = {
    "cli/commands/pr/submit_cmd.py": (
        re.compile(r"""\bexc\.origin\s*==\s*["']delivery["']"""),
        re.compile(r"""\bexc\.origin\s+in\s+\{[^}]*["']delivery["'][^}]*\}"""),
    ),
    "delivery/facade.py": (
        re.compile(r"""^\s*type DeliveryOrigin = Literal\[[^]]*["']delivery["'][^]]*\]"""),
        re.compile(r"""\borigin\s+not\s+in\s+\([^)]*["']delivery["'][^)]*\)"""),
        re.compile(r"""\borigin\s*=\s*["']delivery["']"""),
    ),
    "delivery/publish.py": (re.compile(r"""\borigin\s*=\s*["']delivery["']"""),),
}

# The four literal-bearing homes (the corrected census this guard pins). Only `parse.py`
# READS the key — the single `delivery_policy` classifier every consumer routes through
# (seven production call sites: delivery/train.py; cli/commands/objective/create_cmd.py,
# plan_cmd.py, replan_cmd.py, run_cmd.py, shared.py; cli/commands/plan/save_cmd.py).
ALLOWED = frozenset(
    {
        # The single reader: the fail-closed `delivery_policy` header classifier.
        "objective/parse.py",
        # Emission: renders the header key back out (round-trip fidelity).
        "objective/render.py",
        # Field census: the ordered known-header-key list.
        "objective/_models.py",
        # Transfer manifest payloads: carries the predecessor/successor header value.
        "delivery/transfer.py",
    }
)


def _perk_dir() -> Path:
    return Path(perk.__file__).parent


def _is_value_exemption(relative_path: str, line: str) -> bool:
    return any(pattern.search(line) for pattern in VALUE_EXEMPTIONS.get(relative_path, ()))


def _stripped_lines(path: Path) -> list[str]:
    """Per-line source with `#` comments naively stripped. Naive on purpose: a `#` inside
    a string literal truncates the rest of that line (a possible false NEGATIVE on a line
    mixing a `#`-bearing string before the key literal — acceptable for a backstop; today
    no production line does). Docstring lines are NOT stripped: a quoted `delivery` inside one
    still matches, which is the safe direction (loud, reviewed, allowlisted)."""
    text = path.read_text(encoding="utf-8")
    return [line.split("#", 1)[0] for line in text.splitlines()]


class TestDeliveryPolicyGuard:
    def test_no_production_module_touches_the_delivery_key_outside_the_census(self) -> None:
        """Source scan: outside the four literal-bearing homes, no module under perk/ may
        access or emit the ``delivery`` header key — policy consumption routes through
        ``objective.delivery_policy``, never a scattered compatibility branch."""
        perk_dir = _perk_dir()
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
        assert any(p.name == "parse.py" and p.parent.name == "objective" for p in files), (
            "scan missed objective/parse.py — guard is misaimed"
        )
        stale = ALLOWED - {str(p.relative_to(perk_dir)) for p in files}
        assert not stale, f"stale ALLOWED entries (files no longer exist): {sorted(stale)}"
        offenders: list[str] = []
        for path in files:
            if str(path.relative_to(perk_dir)) in ALLOWED:
                continue
            relative = str(path.relative_to(perk_dir))
            for lineno, line in enumerate(_stripped_lines(path), start=1):
                matches = DELIVERY_LITERAL_PATTERN.search(line)
                if matches and not _is_value_exemption(relative, line):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "`delivery` header-key access outside the audited census — absent/present "
            "delivery metadata must route through objective.delivery_policy (the single "
            "fail-closed reader); a genuinely new home gets a justified ALLOWED entry in "
            "tests/test_delivery_policy_guard.py:\n" + "\n".join(offenders)
        )

    def test_every_allowlisted_home_still_matches(self) -> None:
        """Stale-allowlist self-check: every ALLOWED file still carries the literal — an
        entry that stops matching is census drift and must be pruned consciously."""
        perk_dir = _perk_dir()
        unmatched = [
            rel
            for rel in sorted(ALLOWED)
            if not any(
                DELIVERY_LITERAL_PATTERN.search(line) for line in _stripped_lines(perk_dir / rel)
            )
        ]
        assert not unmatched, (
            f"ALLOWED entries no longer match the `delivery` literal: {unmatched} — "
            "prune the census in tests/test_delivery_policy_guard.py"
        )

    def test_every_value_exemption_still_matches(self) -> None:
        """The homonym exceptions are a stale-failing exact baseline, never an open allowlist."""
        perk_dir = _perk_dir()
        stale = [
            f"{relative}: {pattern.pattern}"
            for relative, patterns in VALUE_EXEMPTIONS.items()
            for pattern in patterns
            if not any(pattern.search(line) for line in _stripped_lines(perk_dir / relative))
        ]
        assert not stale, f"stale delivery-value exemptions: {stale}"

    def test_pattern_matches_reader_and_alternate_mapping_uses(self) -> None:
        """The broad selector bites the reader and mapping APIs beyond ``get``/brackets."""
        source = (_perk_dir() / "objective" / "parse.py").read_text(encoding="utf-8")
        reads = [line for line in source.splitlines() if DELIVERY_LITERAL_PATTERN.search(line)]
        assert any("header.get" in line for line in reads), (
            "objective/parse.py no longer reads the `delivery` key via header.get — the "
            "single-reader census moved; re-audit the guard"
        )
        for line in (
            'header.pop("delivery")',
            'header.setdefault("delivery", None)',
            'read_header_key(header, "delivery")',
        ):
            assert DELIVERY_LITERAL_PATTERN.search(line)
            assert not _is_value_exemption("future.py", line)
