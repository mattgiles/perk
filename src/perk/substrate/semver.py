"""A bounded semver 2.0.0 parser and comparator (pure leaf — no I/O, no dependencies).

The host-admission floor (contracts.md §8.76) compares observed host versions (``pi --version``,
``node --version``) against a declared minimum with **semver precedence**: a prerelease of the
floor triple (``1.0.0-rc.1``) is *below* the floor, a later release is admitted, and build
metadata carries no precedence (semver §10). PEP 440's prerelease grammar is not semver's, so
``packaging`` would be the wrong tool even if it were a dependency; this module implements just
the semver.org grammar and §11 ordering.

One leniency beyond the grammar: a single leading ``v``/``V`` is accepted because Node prints
``v22.19.0``. Anything else outside the grammar parses to ``None`` — callers decide what an
unreadable version means (``unverifiable`` at the launch boundary, an outdated row in the
environment checks). ``parse_semver`` never raises.

``perk.cli.version_check._parse_version`` is a separate, stricter ``X.Y.Z`` reader for perk's own
version pin and deliberately stays there.
"""

import re
from dataclasses import dataclass

# semver.org's recommended grammar, minus the leading anchor's ``v`` (handled before matching):
# numeric identifiers carry no leading zeros; prerelease identifiers are dot-separated
# ``[0-9A-Za-z-]`` (numeric ones without leading zeros); build metadata is ``+`` dot-separated.
_NUM = r"0|[1-9]\d*"
_PRE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_BUILD_ID = r"[0-9A-Za-z-]+"
_SEMVER_RE = re.compile(
    rf"(?P<major>{_NUM})\.(?P<minor>{_NUM})\.(?P<patch>{_NUM})"
    rf"(?:-(?P<pre>{_PRE_ID}(?:\.{_PRE_ID})*))?"
    rf"(?:\+(?P<build>{_BUILD_ID}(?:\.{_BUILD_ID})*))?",
    re.ASCII,
)


@dataclass(frozen=True)
class Semver:
    """A parsed semantic version; build metadata is discarded (it has no precedence)."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    def __str__(self) -> str:
        triple = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            return f"{triple}-{'.'.join(self.prerelease)}"
        return triple


def parse_semver(text: str) -> Semver | None:
    """Parse ``text`` as semver 2.0.0 (one optional leading ``v``); ``None`` when it is not one.

    Surrounding whitespace is stripped (``pi --version`` ends in a newline). Never raises.
    """
    candidate = text.strip()
    if candidate[:1] in ("v", "V"):
        candidate = candidate[1:]
    match = _SEMVER_RE.fullmatch(candidate)
    if match is None:
        return None
    pre = match.group("pre")
    return Semver(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=tuple(pre.split(".")) if pre else (),
    )


def _compare_identifier(a: str, b: str) -> int:
    """Semver §11.4 for one prerelease identifier pair: numeric < alphanumeric; numbers as ints."""
    a_numeric = a.isascii() and a.isdigit()
    b_numeric = b.isascii() and b.isdigit()
    if a_numeric and b_numeric:
        return (int(a) > int(b)) - (int(a) < int(b))
    if a_numeric != b_numeric:
        return -1 if a_numeric else 1
    return (a > b) - (a < b)


def compare_semver(a: Semver, b: Semver) -> int:
    """``-1``/``0``/``1`` by semver §11 precedence (build metadata already discarded)."""
    triple_a = (a.major, a.minor, a.patch)
    triple_b = (b.major, b.minor, b.patch)
    if triple_a != triple_b:
        return -1 if triple_a < triple_b else 1
    # A release outranks any prerelease of the same triple.
    if not a.prerelease or not b.prerelease:
        return (not a.prerelease) - (not b.prerelease)
    for left, right in zip(a.prerelease, b.prerelease, strict=False):
        order = _compare_identifier(left, right)
        if order != 0:
            return order
    # All shared identifiers equal: the longer identifier list has higher precedence.
    return (len(a.prerelease) > len(b.prerelease)) - (len(a.prerelease) < len(b.prerelease))


def satisfies_floor(observed: Semver, floor: Semver) -> bool:
    """Whether ``observed`` is at or above ``floor`` (a floor is a minimum, never an equality)."""
    return compare_semver(observed, floor) >= 0
