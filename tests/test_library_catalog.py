"""The ``catalog.json`` envelope: round trip, parse + content pass, derived status
(contracts.md §8.74(b))."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from perk.library import catalog as cat
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)

DOCS = cat.Entry(
    kind="docs",
    slug="pi",
    source="https://pi.dev/docs",
    path="documentation/pi",
    added_at="2026-09-01T00:00:00Z",
    stale_after=1_209_600,
    upstream=cat.DocsUpstream(
        pages=(
            cat.PageMarker(
                url="https://pi.dev/docs/intro",
                etag='"abc"',
                last_modified="Tue, 01 Sep 2026 00:00:00 GMT",
                sitemap_lastmod="2026-08-30",
            ),
            cat.PageMarker(url="https://pi.dev/docs/api"),
        ),
        fingerprint="sha256:0f",
    ),
    checked_at="2026-09-20T00:00:00Z",
    evidence="strong",
)
SOURCE = cat.Entry(
    kind="source",
    slug="click",
    source="https://github.com/pallets/click",
    path="source-code/github.com/pallets/click",
    added_at="2026-09-02T00:00:00Z",
    stale_after=86_400,
    upstream=cat.SourceUpstream(branch="main", head_sha="0123abcd"),
    ref="8.1.7",
)


def _layout(tmp_path: Path) -> LibraryLayout:
    root = tmp_path / "docs" / "library"
    root.mkdir(parents=True)
    return LibraryLayout(main_root=tmp_path, root=root)


def _write_raw(layout: LibraryLayout, raw: object) -> None:
    layout.catalog_path.write_text(json.dumps(raw), encoding="utf-8")


def _raw_entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "docs",
        "slug": "pi",
        "source": "https://pi.dev/docs",
        "path": "documentation/pi",
        "ref": None,
        "added_at": "2026-09-01T00:00:00Z",
        "checked_at": None,
        "upstream": {"kind": "docs", "pages": [], "fingerprint": None},
        "evidence": "none",
        "drifted": False,
        "stale_after": 1_209_600,
    }
    base.update(overrides)
    return base


def test_round_trip_is_full_equality(tmp_path):
    layout = _layout(tmp_path)
    catalog = cat.Catalog(entries=(DOCS, SOURCE))
    cat.write_catalog(layout, catalog)
    assert cat.load_catalog(layout) == catalog
    rendered = json.loads(layout.catalog_path.read_text(encoding="utf-8"))
    assert rendered["version"] == 1
    assert list(rendered["entries"][0]) == [
        "kind",
        "slug",
        "source",
        "path",
        "ref",
        "added_at",
        "checked_at",
        "upstream",
        "evidence",
        "drifted",
        "stale_after",
    ]
    assert rendered["entries"][0]["upstream"]["kind"] == "docs"
    assert rendered["entries"][1]["upstream"] == {
        "kind": "source",
        "branch": "main",
        "head_sha": "0123abcd",
    }
    assert cat.render_catalog(catalog).endswith("\n")


def test_absent_catalog_is_empty(tmp_path):
    assert cat.load_catalog(_layout(tmp_path)) == cat.Catalog()


def test_unknown_sibling_keys_are_ignored(tmp_path):
    layout = _layout(tmp_path)
    _write_raw(layout, {"version": 1, "future": True, "entries": [_raw_entry(extra="x")]})
    loaded = cat.load_catalog(layout)
    assert loaded.get("pi") is not None


def _assert_malformed(layout: LibraryLayout, *needles: str) -> None:
    with pytest.raises(LibraryError) as excinfo:
        cat.load_catalog(layout)
    assert excinfo.value.error_type == "catalog_malformed"
    for needle in needles:
        assert needle in str(excinfo.value)


def test_malformed_json(tmp_path):
    layout = _layout(tmp_path)
    layout.catalog_path.write_text("{not json", encoding="utf-8")
    _assert_malformed(layout, "not valid JSON")


def test_wrong_version(tmp_path):
    layout = _layout(tmp_path)
    _write_raw(layout, {"version": 2, "entries": []})
    _assert_malformed(layout, "version 2")


def test_schema_violation(tmp_path):
    layout = _layout(tmp_path)
    _write_raw(layout, {"version": 1, "entries": [{"slug": "pi"}]})
    _assert_malformed(layout, "docs/library/catalog.json")


@pytest.mark.parametrize(
    ("entries", "needles"),
    [
        ([_raw_entry(), _raw_entry(path="documentation/pi2")], ("'pi'", "duplicate slug")),
        (
            [_raw_entry(upstream={"kind": "source", "branch": None, "head_sha": None})],
            ("'pi'", "disagrees"),
        ),
        (
            [_raw_entry(), _raw_entry(slug="pi2")],
            ("'pi2'", "also"),
        ),
        ([_raw_entry(path="documentation")], ("'pi'", "not of the form documentation/<slug>")),
        ([_raw_entry(path="documentation/a/b")], ("'pi'", "not of the form")),
        (
            [
                _raw_entry(
                    kind="source",
                    path="source-code/github.com/org",
                    upstream={"kind": "source", "branch": None, "head_sha": None},
                )
            ],
            ("'pi'", "source-code/<host>/<org>/<repo>"),
        ),
        ([_raw_entry(added_at="2026-09-01")], ("'pi'", "malformed added_at")),
        ([_raw_entry(checked_at="yesterday")], ("'pi'", "malformed checked_at")),
        ([_raw_entry(slug="Pi")], ("'Pi'", "slug grammar")),
    ],
)
def test_content_pass_refusals_name_the_slug(tmp_path, entries, needles):
    layout = _layout(tmp_path)
    _write_raw(layout, {"version": 1, "entries": entries})
    _assert_malformed(layout, *needles)


def test_derive_status_arms():
    fresh_check = "2026-09-27T00:00:00Z"
    stale_check = "2026-09-01T00:00:00Z"
    assert cat.derive_status(SOURCE, now=NOW) == "pinned"
    assert (
        cat.derive_status(replace(DOCS, drifted=True, checked_at=fresh_check), now=NOW) == "drifted"
    )
    assert cat.derive_status(replace(DOCS, checked_at=None), now=NOW) == "unknown"
    assert cat.derive_status(replace(DOCS, checked_at=stale_check), now=NOW) == "stale"
    assert (
        cat.derive_status(replace(DOCS, checked_at=fresh_check, evidence="none"), now=NOW)
        == "unverifiable"
    )
    assert (
        cat.derive_status(replace(DOCS, checked_at=fresh_check, evidence="weak"), now=NOW)
        == "fresh"
    )
    # Precedence pairs.
    assert cat.derive_status(replace(SOURCE, drifted=True), now=NOW) == "pinned"
    assert (
        cat.derive_status(replace(DOCS, drifted=True, checked_at=stale_check), now=NOW) == "drifted"
    )
    assert cat.derive_status(
        replace(DOCS, drifted=False, checked_at=None, evidence="none"), now=NOW
    ) == ("unknown")
    assert (
        cat.derive_status(replace(DOCS, checked_at=stale_check, evidence="none"), now=NOW)
        == "stale"
    )
    # A source entry without a ref follows the docs arms.
    assert cat.derive_status(replace(SOURCE, ref=None), now=NOW) == "unknown"
    # The stale boundary is inclusive.
    edge = cat.format_ts(NOW.replace(day=26))
    assert cat.derive_status(replace(DOCS, checked_at=edge, stale_after=86_400), now=NOW) == "stale"


def test_default_stale_after_and_timestamps():
    assert cat.DEFAULT_STALE_AFTER == {"docs": 1_209_600, "source": 86_400}
    assert cat.format_ts(NOW) == "2026-09-27T12:00:00Z"
    assert cat.parse_ts("2026-09-27T12:00:00Z") == NOW
    with pytest.raises(ValueError):
        cat.parse_ts("2026-09-27 12:00:00")


def test_catalog_helpers():
    catalog = cat.Catalog(entries=(DOCS,))
    assert catalog.owner_of("documentation/pi") == DOCS
    assert catalog.owner_of("documentation/other") is None
    grown = catalog.with_entry(SOURCE)
    assert [entry.slug for entry in grown.entries] == ["pi", "click"]
    refreshed = grown.with_entry(replace(DOCS, source="https://pi.dev/v2"))
    assert [entry.slug for entry in refreshed.entries] == ["pi", "click"]
    pi = refreshed.get("pi")
    assert pi is not None and pi.source == "https://pi.dev/v2"
    assert [entry.slug for entry in refreshed.without("pi").entries] == ["click"]
