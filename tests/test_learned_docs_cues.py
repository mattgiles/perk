"""Live-corpus guard: every `docs/learned` `read_when` cue fits the routing budget, the repo
stays pinned to the two-tier cluster-registry mode, and every over-threshold doc opens with its
conformant `## Distillation` header (§8.35).

The ambient routing block (`.pi/APPEND_SYSTEM.md`) renders each cluster's rollup cue + member doc
slugs verbatim into every session's system prompt, so an overlong cue/rollup is a per-session tax
and a plain-scalar hazard silently corrupts the rendered line. `perk learn docs-check` gates on
the same scans on demand; this guard makes the budgets + the registry mode CI invariants.
Freshness deliberately stays out of CI (run `docs-check` on demand).
"""

from pathlib import Path

from perk.learn.docs_scan import read_learned_docs
from perk.learn.docs_sync import (
    CLUSTER_ROLLUP_MAX_CHARS,
    DISTILLATION_THRESHOLD_BYTES,
    READ_WHEN_MAX_CHARS,
    ClusterRegistry,
    load_cluster_registry,
    scan_cues,
    scan_distillation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_corpus_is_non_empty():
    # The non-vacuous self-check: a docs/learned layout change must not silently empty the scan
    # (which would make the budget assertions below pass vacuously).
    docs = read_learned_docs(REPO_ROOT)
    assert len(docs) >= 10, (
        f"only {len(docs)} learned docs found under docs/learned/ — the corpus scan looks broken "
        "(a layout change?); the cue-budget guard would be vacuous"
    )


def test_no_read_when_cue_exceeds_the_budget():
    docs = read_learned_docs(REPO_ROOT)
    findings = scan_cues(REPO_ROOT, docs)
    offenders = ", ".join(f"{cue.doc} ({cue.length} chars)" for cue in findings.overlong)
    assert findings.overlong == (), (
        f"read_when cue(s) over the routing budget: {offenders} — compress each `read_when` cue "
        f"to ≤{READ_WHEN_MAX_CHARS} chars (see `skills/perk-learn-docs/SKILL.md`)"
    )


def test_no_read_when_cue_carries_a_plain_scalar_hazard():
    docs = read_learned_docs(REPO_ROOT)
    findings = scan_cues(REPO_ROOT, docs)
    offenders = ", ".join(f"{h.doc} ({h.hazard})" for h in findings.hazards)
    assert findings.hazards == (), (
        f"read_when cue(s) carrying a YAML plain-scalar hazard: {offenders} — remove ` #` / `: ` "
        "from the plain scalar (or quote it) and keep the cue single-line — see "
        "`skills/perk-learn-docs/SKILL.md`"
    )


# --- the two-tier cluster registry (perk's own repo is pinned to registry mode) -------------------


def _valid_registry() -> ClusterRegistry:
    registry = load_cluster_registry(REPO_ROOT)
    assert isinstance(registry, ClusterRegistry), (
        f"docs/learned/clusters.yaml must exist and load valid (got {registry!r}) — perk's own "
        "repo is pinned to the two-tier registry mode; see `skills/perk-learn-docs/SKILL.md`"
    )
    return registry


def test_cluster_registry_exists_and_loads_valid():
    registry = _valid_registry()
    assert len(registry.clusters) >= 2, "a registry this small looks broken (mass-deletion?)"


def test_every_doc_declares_a_registry_cluster():
    known = {cluster.id for cluster in _valid_registry().clusters}
    docs = read_learned_docs(REPO_ROOT)
    offenders = [f"{d.path} (cluster: {d.cluster!r})" for d in docs if d.cluster not in known]
    assert offenders == [], (
        "learned doc(s) without a valid `cluster:` frontmatter declaration: "
        f"{', '.join(offenders)} — declare an existing id from docs/learned/clusters.yaml "
        "(see `skills/perk-learn-docs/SKILL.md`)"
    )


def test_no_registry_cluster_is_empty():
    declared = {doc.cluster for doc in read_learned_docs(REPO_ROOT)}
    empty = [c.id for c in _valid_registry().clusters if c.id not in declared]
    assert empty == [], (
        f"registry cluster(s) with zero member docs: {', '.join(empty)} — assign a doc or "
        "remove the registry entry"
    )


def test_no_rollup_cue_exceeds_the_budget():
    offenders = [
        f"{c.id} ({len(c.rollup)} chars)"
        for c in _valid_registry().clusters
        if len(c.rollup) > CLUSTER_ROLLUP_MAX_CHARS
    ]
    assert offenders == [], (
        f"rollup cue(s) over the routing budget: {', '.join(offenders)} — compress each rollup "
        f"to ≤{CLUSTER_ROLLUP_MAX_CHARS} chars in docs/learned/clusters.yaml"
    )


# --- the distillation gate (gate #4: big docs open with a bounded `## Distillation` header) -------


def test_every_over_threshold_doc_opens_with_a_conformant_distillation_header():
    findings = scan_distillation(REPO_ROOT, read_learned_docs(REPO_ROOT))
    offenders = ", ".join(f"{i.doc} ({i.problem})" for i in findings.issues)
    assert findings.issues == (), (
        f"learned doc(s) over {DISTILLATION_THRESHOLD_BYTES} raw bytes without a conformant "
        f"`## Distillation` header: {offenders} — the header must be the first `##` body "
        "section, ≤30 lines, fully inside the file's first 80 lines (so `read` with "
        "`limit: 80` captures it); see `skills/perk-learn-docs/SKILL.md`"
    )


def test_the_oversize_advisory_is_non_vacuous_today():
    # The non-vacuity self-check for the gate above: today's corpus has over-threshold docs, so
    # an empty issue tuple means the headers conform — not that nothing was checked. Relax this
    # if the corpus ever legitimately drops fully under the threshold.
    findings = scan_distillation(REPO_ROOT, read_learned_docs(REPO_ROOT))
    assert findings.oversize != (), (
        f"no learned doc is over {DISTILLATION_THRESHOLD_BYTES} raw bytes — the distillation "
        "live-corpus gate is now vacuous; relax this assertion if the corpus legitimately "
        "shrank below the threshold"
    )
