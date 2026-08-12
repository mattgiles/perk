"""The shared fail-closed remote-writer observation seam (contracts.md §8.49/§8.55).

Both the mutating operations (sync/publish/transfer) and the landing-readiness preflight gate
on the same question — does any affected plan have an active remote writer? — so the Protocol
and its typed failure live in this tiny leaf, importable from either side without dragging in
an operation module (``land`` must not import ``sync``: ``sync`` imports ``observe``, which
imports ``land``). The production adapter is ``perk.run.writer_probe.GhaRemoteWriterProbe``;
the CLI wires it.
"""

from collections.abc import Sequence
from typing import Protocol


class WriterObservationError(Exception):
    """A :class:`RemoteWriterProbe` could not observe the active remote writers. Consumers map
    it to their typed ``writer_observation_unavailable`` arm — a gate never treats an
    unreadable observation as "no active writer"."""


class RemoteWriterProbe(Protocol):
    """The narrow remote-writer preflight surface (declared here; wired by the CLI).

    ``active_plan_ids`` returns the subset of ``plan_ids`` that currently have an active
    remote writer (a queued/in-progress remote implementation run). Implementations raise
    :class:`WriterObservationError` on ANY observation failure — never an empty set.
    """

    def active_plan_ids(self, plan_ids: Sequence[str]) -> frozenset[str]: ...
