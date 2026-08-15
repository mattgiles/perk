"""The Prose Review Workbench security envelope: guard, containment, header stamping."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review import web
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.web import create_app

ROOT = Path(__file__).parents[1]

ALLOWED_HOST = "127.0.0.1:5"
TOKEN = "test-token"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
INDEX_HTML = (
    "<!doctype html><html><head>"
    '<meta name="csrf-token" content="__PROSE_REVIEW_CSRF__">'
    '</head><body><div id="root"></div></body></html>'
)


@pytest.fixture(scope="module")
def snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


@pytest.fixture(scope="module")
def outside(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Escape targets that live OUTSIDE every per-test repo root."""
    escape = tmp_path_factory.mktemp("prose-review-escape")
    (escape / "secret.txt").write_text("outside the repo\n", encoding="utf-8")
    (escape / "app.js").write_text("console.log('outside');\n", encoding="utf-8")
    (escape / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    escape_dist = escape / "dist"
    (escape_dist / "assets").mkdir(parents=True)
    (escape_dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (escape_dist / "assets" / "app.js").write_text("console.log('outside');\n", encoding="utf-8")
    return escape


def _populate_dist(dist: Path) -> None:
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok');\n", encoding="utf-8")


def _client(
    snapshot: CatalogSnapshot,
    repo_root: Path,
    *,
    dist_dir: Path | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(
        snapshot=snapshot,
        repo_root=repo_root,
        dist_dir=dist_dir if dist_dir is not None else repo_root / "dist",
        allowed_host=ALLOWED_HOST,
        csrf_token=TOKEN,
    )
    return TestClient(
        app,
        base_url=f"http://{ALLOWED_HOST}",
        raise_server_exceptions=raise_server_exceptions,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _populate_dist(tmp_path / "dist")
    return tmp_path


def _assert_security_headers(response: Response) -> None:
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_index_substitutes_the_token_and_carries_security_headers(
    snapshot: CatalogSnapshot, repo: Path
) -> None:
    response = _client(snapshot, repo).get("/")
    assert response.status_code == 200
    assert TOKEN in response.text
    assert "__PROSE_REVIEW_CSRF__" not in response.text
    _assert_security_headers(response)


def test_catalog_summary_serves_the_snapshot_dto(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/api/catalog/summary")
    assert response.status_code == 200
    payload = response.json()
    assert list(payload.keys()) == [
        "units",
        "fragments",
        "session_shapes",
        "assemblies",
        "scenarios",
        "concerns",
        "lineage_rules",
        "capabilities",
    ]
    assert payload["units"] == len(snapshot.units)
    assert payload["capabilities"][0]["label"] == "Foundation"
    _assert_security_headers(response)


def test_catalog_tree_serves_the_fixed_order_tree(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/api/catalog/tree")
    assert response.status_code == 200
    payload = response.json()
    assert list(payload.keys()) == ["capabilities"]
    assert payload["capabilities"][0]["label"] == "Foundation"
    _assert_security_headers(response)


def test_source_serves_the_on_disk_file(snapshot: CatalogSnapshot, tmp_path: Path) -> None:
    # The repo root of trust is the real checkout for the source read; the dist dir
    # stays a tmp fixture (the /api/source path never touches built assets).
    _populate_dist(tmp_path / "dist")
    client = _client(snapshot, ROOT, dist_dir=tmp_path / "dist")
    response = client.get("/api/source", params={"unit": "managed:repo-agents"})
    assert response.status_code == 200
    payload = response.json()
    assert list(payload.keys()) == ["unit", "path", "kind", "content"]
    assert payload["unit"] == "managed:repo-agents"
    assert payload["path"] == "AGENTS.md"
    assert payload["kind"] == "managed-prose"
    assert payload["content"] == (ROOT / "AGENTS.md").read_bytes().decode("utf-8")
    _assert_security_headers(response)


def test_source_unknown_unit_is_a_fixed_404(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/api/source", params={"unit": "markdown:missing.md"})
    assert response.status_code == 404
    assert response.json() == {"detail": "unknown unit"}
    _assert_security_headers(response)


def test_source_missing_file_is_a_fixed_404(snapshot: CatalogSnapshot, repo: Path) -> None:
    # The tmp repo root carries no AGENTS.md, so the known unit's containment-checked
    # read misses — the route must translate not_found into its fixed 404 shape.
    response = _client(snapshot, repo).get("/api/source", params={"unit": "managed:repo-agents"})
    assert response.status_code == 404
    assert response.json() == {"detail": "source not found"}
    _assert_security_headers(response)


def test_source_non_utf8_file_is_a_fixed_404(snapshot: CatalogSnapshot, repo: Path) -> None:
    (repo / "AGENTS.md").write_bytes(b"\xff\xfe\x00\x01")
    response = _client(snapshot, repo).get("/api/source", params={"unit": "managed:repo-agents"})
    assert response.status_code == 404
    assert response.json() == {"detail": "source is not utf-8 text"}
    _assert_security_headers(response)


def test_source_missing_unit_param_is_a_stamped_422(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/api/source")
    assert response.status_code == 422
    _assert_security_headers(response)


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("app.js", "text/javascript"),
        ("app.css", "text/css"),
        ("app.js.map", "application/json"),
        ("logo.svg", "image/svg+xml"),
        ("font.woff2", "font/woff2"),
        ("blob.wasm", "application/octet-stream"),
    ],
)
def test_asset_route_serves_the_whole_content_type_map(
    snapshot: CatalogSnapshot, repo: Path, filename: str, content_type: str
) -> None:
    (repo / "dist" / "assets" / filename).write_bytes(b"payload")
    response = _client(snapshot, repo).get(f"/assets/{filename}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    _assert_security_headers(response)


@pytest.mark.parametrize("host", ["localhost:5", "evil.example:5", "127.0.0.1"])
def test_host_rejection(snapshot: CatalogSnapshot, repo: Path, host: str) -> None:
    response = _client(snapshot, repo).get("/", headers={"Host": host})
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden host"}
    _assert_security_headers(response)


def test_origin_exact_match_passes_and_foreign_origin_is_rejected(
    snapshot: CatalogSnapshot, repo: Path
) -> None:
    client = _client(snapshot, repo)
    ok = client.get("/", headers={"Origin": f"http://{ALLOWED_HOST}"})
    assert ok.status_code == 200
    rejected = client.get("/", headers={"Origin": "http://evil.example"})
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "forbidden origin"}
    _assert_security_headers(rejected)


def test_csrf_all_four_arms(snapshot: CatalogSnapshot, repo: Path) -> None:
    client = _client(snapshot, repo)
    header = "X-Prose-Review-Csrf"

    missing = client.post("/api/catalog/summary")
    assert missing.status_code == 403
    _assert_security_headers(missing)

    wrong = client.post("/api/catalog/summary", headers={header: "wrong-token"})
    assert wrong.status_code == 403

    duplicated = client.post("/api/catalog/summary", headers=[(header, TOKEN), (header, TOKEN)])
    assert duplicated.status_code == 403

    # Exactly one correct header passes the guard; 405 proves the equality check ran
    # (the route genuinely has no POST), not that a route swallowed the request.
    passed = client.post("/api/catalog/summary", headers={header: TOKEN})
    assert passed.status_code == 405
    _assert_security_headers(passed)


def test_percent_encoded_traversal_is_contained(snapshot: CatalogSnapshot, repo: Path) -> None:
    (repo / "secret.txt").write_text("inside repo, outside dist\n", encoding="utf-8")
    response = _client(snapshot, repo).get("/assets/%2e%2e/secret.txt")
    assert response.status_code == 404
    _assert_security_headers(response)


def test_os_invalid_asset_path_is_a_contained_404(snapshot: CatalogSnapshot, repo: Path) -> None:
    # Uvicorn/Starlette percent-decode the path, so an encoded NUL reaches Path.resolve()
    # as an embedded null byte — it must degrade to the contained 404, never a 500.
    response = _client(snapshot, repo).get("/assets/%00.js")
    assert response.status_code == 404
    _assert_security_headers(response)


def test_child_symlink_escaping_the_dist_root_is_contained(
    snapshot: CatalogSnapshot, repo: Path, outside: Path
) -> None:
    (repo / "dist" / "assets" / "escape.js").symlink_to(outside / "secret.txt")
    response = _client(snapshot, repo).get("/assets/escape.js")
    assert response.status_code == 404
    _assert_security_headers(response)


def test_escaping_assets_directory_symlink_is_contained(
    snapshot: CatalogSnapshot, tmp_path: Path, outside: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets").symlink_to(outside, target_is_directory=True)
    response = _client(snapshot, tmp_path).get("/assets/app.js")
    assert response.status_code == 404
    _assert_security_headers(response)


def test_escaping_dist_root_symlink_is_contained(
    snapshot: CatalogSnapshot, tmp_path: Path, outside: Path
) -> None:
    (tmp_path / "dist").symlink_to(outside / "dist", target_is_directory=True)
    client = _client(snapshot, tmp_path)
    asset = client.get("/assets/app.js")
    assert asset.status_code == 404
    _assert_security_headers(asset)
    index = client.get("/")
    assert index.status_code == 500
    assert index.json() == {"detail": "frontend not built or not contained"}
    _assert_security_headers(index)


def test_escaping_index_symlink_is_contained(
    snapshot: CatalogSnapshot, tmp_path: Path, outside: Path
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").symlink_to(outside / "index.html")
    response = _client(snapshot, tmp_path).get("/")
    assert response.status_code == 500
    assert response.json() == {"detail": "frontend not built or not contained"}
    _assert_security_headers(response)


def test_plain_asset_miss_is_404(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/assets/missing.js")
    assert response.status_code == 404
    _assert_security_headers(response)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_framework_doc_surfaces_are_disabled(
    snapshot: CatalogSnapshot, repo: Path, path: str
) -> None:
    response = _client(snapshot, repo).get(path)
    assert response.status_code == 404
    _assert_security_headers(response)


def test_unknown_route_is_404_with_security_headers(snapshot: CatalogSnapshot, repo: Path) -> None:
    response = _client(snapshot, repo).get("/api/unknown")
    assert response.status_code == 404
    _assert_security_headers(response)


def test_unhandled_exception_response_is_still_header_stamped(
    snapshot: CatalogSnapshot, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Boom:
        @staticmethod
        def from_domain(_snapshot: CatalogSnapshot) -> None:
            raise RuntimeError("deliberate handler failure")

    # Create the client BEFORE patching: route registration needs the real response
    # model; the handler body resolves the module global at call time.
    client = _client(snapshot, repo, raise_server_exceptions=False)
    monkeypatch.setattr(web, "CatalogSummaryOut", Boom)
    response = client.get("/api/catalog/summary")
    assert response.status_code == 500
    _assert_security_headers(response)
