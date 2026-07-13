"""The Linear attachment-metadata vocabulary (contracts.md §8.21).

Under the Linear backend, perk's issue- and project-scoped bookkeeping blocks (``plan-header``,
``learn-header``, ``objective-node``, ``objective-header``, ``objective-manifest``) are stored as
native Linear **issue attachments** carrying a machine-readable ``metadata`` envelope — never as
inline metadata blocks in body text. This module is the pure vocabulary: the synthetic-URL
builders (the upsert identity + lookup keys), the envelope encoder (metadata + the human card
projection), and the lenient decoder.

The URLs use the honest non-resolving ``https://perk.invalid/...`` scheme (RFC-2606 ``.invalid``:
unambiguously machine bookkeeping, immune to integration URL-claiming; live-verified).
``attachmentCreate`` upserts by ``(url, issueId)`` and the write semantics are REPLACE
(live-verified), so every write sends the complete envelope — no merge op exists or is needed.
"""

import json
from dataclasses import dataclass

from perk.backends.issue_backend import IssueBackendError
from perk.boundary import LenientParseModel

_URL_BASE = "https://perk.invalid"

# The envelope's `kind` vocabulary IS the block-key vocabulary (plan.PLAN_HEADER_KEY etc.) —
# string literals here to keep this module import-light and the vocabulary explicit.
PLAN_HEADER_KIND = "plan-header"
LEARN_HEADER_KIND = "learn-header"
OBJECTIVE_NODE_KIND = "objective-node"
OBJECTIVE_HEADER_KIND = "objective-header"
OBJECTIVE_MANIFEST_KIND = "objective-manifest"

_SCHEMA_VERSION = 1


# ------------------------------------------------------------------ URL builders


def plan_header_url(key: str) -> str:
    """The plan-header attachment URL. ``key`` is the plan's ``run_id`` when non-empty, else the
    issue identifier (a run-id-less plan cannot be found by run_id anyway; the identifier keeps
    the URL unique). Finds only ever query the run_id form."""
    return f"{_URL_BASE}/plan/{key}"


def learn_header_url(key: str) -> str:
    """The learn-header attachment URL (same ``key`` semantics as :func:`plan_header_url`)."""
    return f"{_URL_BASE}/learn/{key}"


def node_url(identifier: str) -> str:
    """The objective-node attachment URL — keyed on the node-**issue's** identifier, NOT
    ``(objective_run_id, node_id)``: the supersede carry path re-stamps a *new node id* onto the
    *same issue*, and an issue-keyed URL upserts in place instead of orphaning a stale
    attachment."""
    return f"{_URL_BASE}/node/{identifier}"


def objective_header_url(run_id: str) -> str:
    """The objective-header attachment URL — run_id-keyed so ``find_objective(run_id)`` is one
    ``attachmentsForURL`` query (consistent with plans/learn)."""
    return f"{_URL_BASE}/objective/{run_id}"


def objective_manifest_url(run_id: str) -> str:
    """The objective-manifest attachment URL (run_id-keyed, beside the header)."""
    return f"{_URL_BASE}/manifest/{run_id}"


# ------------------------------------------------------------------ envelope encode


@dataclass(frozen=True)
class AttachmentCard:
    """One encoded perk attachment write: the human card fields (``title``/``subtitle`` for the
    ``attachmentCreate`` input; ``subtitle`` may carry the ``{created__since}`` template Linear
    date-formats against the metadata's top-level ``created``) plus the complete machine
    ``metadata`` envelope."""

    title: str
    subtitle: str | None
    metadata: dict[str, object]


def _scalar_attributes(fields: dict[str, object]) -> list[dict[str, object]]:
    """The rich-modal ``attributes`` projection: every non-null scalar field, in declaration
    order, as ``{name, value}`` rows (values stringified — the modal renders text)."""
    rows: list[dict[str, object]] = []
    for name, value in fields.items():
        if value is None or not isinstance(value, str | int | float | bool):
            continue
        rows.append({"name": name, "value": str(value)})
    return rows


def _card_title_subtitle(kind: str, fields: dict[str, object]) -> tuple[str, str | None]:
    """The per-kind human card projection. ``{created__since}`` in a subtitle is a Linear
    template rendered against the envelope's top-level ``created`` ISO value."""
    created = fields.get("created")
    since = "created {created__since}" if isinstance(created, str) and created else None
    if kind == PLAN_HEADER_KIND:
        stage = fields.get("lifecycle_stage")
        parts = [str(stage)] if isinstance(stage, str) and stage else []
        if since:
            parts.append(since)
        return "Perk plan", " · ".join(parts) or None
    if kind == LEARN_HEADER_KIND:
        return "Perk learn", since
    if kind == OBJECTIVE_NODE_KIND:
        node_id = fields.get("id")
        status = fields.get("status")
        title = f"Perk node {node_id}" if isinstance(node_id, str) and node_id else "Perk node"
        return title, str(status) if isinstance(status, str) and status else None
    if kind == OBJECTIVE_HEADER_KIND:
        status = fields.get("status")
        parts = [str(status)] if isinstance(status, str) and status else []
        if since:
            parts.append(since)
        return "Perk objective", " · ".join(parts) or None
    if kind == OBJECTIVE_MANIFEST_KIND:
        nodes = fields.get("nodes")
        subtitle = f"{len(nodes)} node(s)" if isinstance(nodes, list) else None
        return "Perk objective manifest", subtitle
    raise IssueBackendError(f"unknown perk attachment kind: {kind!r}")


def encode(kind: str, fields: dict[str, object]) -> AttachmentCard:
    """Encode ``fields`` (the EXACT block-fields dict — lists/nulls round-trip verbatim through
    ``payload_json``) into one complete attachment write. Pure; every write sends the whole
    envelope (REPLACE semantics make partial writes unnecessary)."""
    title, subtitle = _card_title_subtitle(kind, fields)
    metadata: dict[str, object] = {
        "source": "perk",
        "schema_version": _SCHEMA_VERSION,
        "kind": kind,
        "payload_json": json.dumps(fields),
    }
    created = fields.get("created")
    if isinstance(created, str) and created:
        # Top-level so the `{created__since}` subtitle template date-formats it.
        metadata["created"] = created
    metadata["title"] = title
    attributes = _scalar_attributes(fields)
    if attributes:
        metadata["attributes"] = attributes
    return AttachmentCard(title=title, subtitle=subtitle, metadata=metadata)


# ------------------------------------------------------------------ decode


class _PerkAttachmentEnvelope(LenientParseModel):
    """The untrusted read edge of one attachment's ``metadata``. Tolerant defaults: a foreign
    attachment (wrong/absent ``source``/``kind``) simply never matches — only a perk-marked,
    kind-matched attachment with a malformed payload fails loud."""

    source: str = ""
    kind: str = ""
    payload_json: object = None


@dataclass(frozen=True)
class PerkAttachment:
    """A decoded perk attachment: the Linear attachment ``id``, its (upsert-identity) ``url``,
    and the verbatim-round-tripped block-fields ``payload``."""

    id: str
    url: str
    payload: dict[str, object]


def has_perk_attachment(nodes: list[dict[str, object]], *, kind: str) -> bool:
    """Presence-only membership test (envelope match, no payload decode) — the tolerant twin of
    :func:`find_perk_attachment` for classification scans that must not fail loud on a
    malformed payload (mirrors ``plan.has_metadata_block``'s absent-vs-malformed posture)."""
    for node in nodes:
        metadata = node.get("metadata")
        if not isinstance(metadata, dict):
            continue
        envelope = _PerkAttachmentEnvelope.model_validate(metadata)
        if envelope.source == "perk" and envelope.kind == kind:
            return True
    return False


def find_perk_attachment(nodes: list[dict[str, object]], *, kind: str) -> PerkAttachment | None:
    """Find the perk attachment of ``kind`` among raw ``{id, url, metadata}`` attachment nodes.

    Foreign attachments (wrong/absent ``source`` or ``kind``) are skipped; a perk-marked,
    kind-matched attachment with a missing/malformed ``payload_json`` raises a labelled
    ``IssueBackendError`` (absent is valid, present-but-malformed fails loud). ``None`` when no
    attachment matches."""
    for node in nodes:
        metadata = node.get("metadata")
        if not isinstance(metadata, dict):
            continue
        envelope = _PerkAttachmentEnvelope.model_validate(metadata)
        if envelope.source != "perk" or envelope.kind != kind:
            continue
        attachment_id = node.get("id")
        url = node.get("url")
        if not isinstance(attachment_id, str) or not isinstance(url, str):
            raise IssueBackendError(f"malformed perk {kind} attachment node: missing id/url")
        if not isinstance(envelope.payload_json, str):
            raise IssueBackendError(
                f"malformed perk {kind} attachment: payload_json is not a string"
            )
        try:
            payload = json.loads(envelope.payload_json)
        except json.JSONDecodeError as exc:
            raise IssueBackendError(
                f"malformed perk {kind} attachment: invalid payload_json"
            ) from exc
        if not isinstance(payload, dict):
            raise IssueBackendError(f"malformed perk {kind} attachment: payload is not an object")
        return PerkAttachment(id=attachment_id, url=url, payload=payload)
    return None
