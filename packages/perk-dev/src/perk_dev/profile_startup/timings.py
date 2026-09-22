"""Pi's startup-timing report grammar (``PI_TIMING=1``) and the stateful startup marker.

Pi's ``core/timings.js`` prints one group per namespace to **stderr**::

    --- Startup Timings: <namespace> ---
      <label>: <ms>ms
      ...
      TOTAL: <ms>ms
    -----------------------------------

Facts the parser encodes: each row is the delta since the PREVIOUS row of its namespace (the
first row of the ``extensions`` namespace runs from Pi's ``resetTimings("extensions")`` in
``core/resource-loader.js`` — a real measurement, never assumed zero); the ``extensions`` rows
are labelled ``<path> module import`` / ``<path> factory``, so labels carry spaces and paths
and the numeric suffix is matched from the END of the line; rows are kept verbatim. Lines that
are not part of a group (perk's ``opening a plain Pi session…`` announce, npm output, warnings)
are skipped. Pi's totals exclude everything before its ``main()`` entry (``resetTimings()`` runs
there), which is why the harness derives ``pre_pi_remainder_ms`` separately.
"""

import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r"^--- Startup Timings: (?P<namespace>\S+) ---$")
_ROW_RE = re.compile(r"^  (?P<label>.+): (?P<ms>\d+)ms$")
_TOTAL_RE = re.compile(r"^  TOTAL: (?P<ms>\d+)ms$")
_FOOTER_RE = re.compile(r"^-{3,}$")

MAIN_NAMESPACE = "main"


@dataclass(frozen=True)
class TimingRow:
    """One verbatim row of a timing group: its label and its delta since the previous row."""

    label: str
    ms: int


@dataclass(frozen=True)
class TimingGroup:
    """One namespace's group: its rows in print order and the ``TOTAL`` Pi printed."""

    namespace: str
    rows: tuple[TimingRow, ...]
    total_ms: int


def _clean(line: str) -> str:
    return line.rstrip("\r\n")


def parse_pi_timings(text: str) -> dict[str, TimingGroup]:
    """Parse every complete timing group in ``text`` (keyed by namespace, in print order).

    A group is complete once its ``TOTAL`` row has been seen; an unterminated trailing group is
    dropped (a truncated report is not a measurement). A later group with the same namespace
    replaces the earlier one (Pi prints each namespace once per process).
    """
    groups: dict[str, TimingGroup] = {}
    namespace: str | None = None
    rows: list[TimingRow] = []
    for raw in text.splitlines():
        line = _clean(raw)
        header = _HEADER_RE.match(line)
        if header is not None:
            namespace = header["namespace"]
            rows = []
            continue
        if namespace is None:
            continue
        total = _TOTAL_RE.match(line)
        if total is not None:
            groups[namespace] = TimingGroup(
                namespace=namespace, rows=tuple(rows), total_ms=int(total["ms"])
            )
            namespace = None
            rows = []
            continue
        row = _ROW_RE.match(line)
        if row is not None:
            rows.append(TimingRow(label=row["label"], ms=int(row["ms"])))
            continue
        if _FOOTER_RE.match(line):
            namespace = None
            rows = []
    return groups


class TimingsScanner:
    """The stateful startup marker fed one stderr line at a time.

    :meth:`feed` returns ``True`` exactly once — on the ``TOTAL`` row of the ``main`` group —
    and ``False`` for every other line, including the ``TOTAL`` rows of other namespaces. The
    harness stamps ``elapsed_ms`` on that first ``True``.
    """

    def __init__(self) -> None:
        self._namespace: str | None = None
        self.seen = False

    def feed(self, line: str) -> bool:
        line = _clean(line)
        header = _HEADER_RE.match(line)
        if header is not None:
            self._namespace = header["namespace"]
            return False
        if self._namespace is None:
            return False
        if _TOTAL_RE.match(line):
            fired = self._namespace == MAIN_NAMESPACE and not self.seen
            if fired:
                self.seen = True
            self._namespace = None
            return fired
        if _FOOTER_RE.match(line):
            self._namespace = None
        return False
