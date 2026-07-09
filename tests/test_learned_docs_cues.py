"""Live-corpus guard: every `docs/learned` `read_when` cue fits the routing budget (§8.35).

The ambient routing block (`.pi/APPEND_SYSTEM.md`) renders each cue verbatim into every session's
system prompt, so an overlong cue is a per-session tax and a plain-scalar hazard silently corrupts
the rendered line. `perk learn docs-check` gates on the same scan on demand; this guard makes the
budget a CI invariant. Freshness deliberately stays out of CI (run `docs-check` on demand).
"""

from pathlib import Path

from perk.learn.docs_scan import read_learned_docs
from perk.learn.docs_sync import READ_WHEN_MAX_CHARS, scan_cues

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
