"""The server-integration round-trip proof: real build, real uvicorn, real DTO.

Everything short of executing browser JS — the browser leg is the plan's manual
acceptance step. The frontend is built unconditionally, once per module, into a
fixture-owned temp directory (existence is not freshness, and no two processes may
ever write one output dir), so this suite never touches the launcher's real ``dist/``.
"""

import re
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.cli import build_frontend
from perk_dev.prose_review.dto import (
    CapabilityTreeOut,
    CatalogSummaryOut,
    SearchOut,
    UnitInspectOut,
)
from perk_dev.prose_review.search import build_search_index, search
from perk_dev.prose_review.web import create_app

ROOT = Path(__file__).parents[1]

# One xdist worker: the module fixture builds the frontend and owns a live server.
pytestmark = pytest.mark.xdist_group("prose_review_frontend")


@dataclass(frozen=True)
class _RunningServer:
    base_url: str
    token: str
    snapshot: CatalogSnapshot


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_RunningServer]:
    trust_root = tmp_path_factory.mktemp("prose-review-integration")
    dist_dir = trust_root / "dist"
    build_frontend(ROOT, out_dir=dist_dir)
    assert (dist_dir / "index.html").is_file()

    # Real Markdown and YAML candidates copied to their catalog-relative paths under
    # the fixture trust root. Pointing repo_root at the checkout would break the
    # asset-containment proof above.
    (trust_root / "AGENTS.md").write_bytes((ROOT / "AGENTS.md").read_bytes())
    clusters = trust_root / "docs/learned/clusters.yaml"
    clusters.parent.mkdir(parents=True)
    clusters.write_bytes((ROOT / "docs/learned/clusters.yaml").read_bytes())

    snapshot = CatalogSnapshot.from_catalog(build_catalog(ROOT))
    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    app = create_app(
        snapshot=snapshot,
        repo_root=trust_root,
        dist_dir=dist_dir,
        allowed_host=f"127.0.0.1:{port}",
        csrf_token=token,
    )
    # Pins the assumptions this plan refuses to trust: Server.run serves a pre-bound
    # listening socket, and skips signal-handler installation off the main thread.
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    failures: list[Exception] = []

    def run() -> None:
        try:
            server.run(sockets=[sock])
        except Exception as exc:  # surfaced by the startup poll below
            failures.append(exc)

    thread = threading.Thread(target=run, name="prose-review-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive():
            if failures:
                raise failures[0]
            pytest.fail("uvicorn thread exited before startup")
        if time.monotonic() > deadline:
            pytest.fail("uvicorn did not report started within 30s")
        time.sleep(0.05)

    yield _RunningServer(base_url=f"http://127.0.0.1:{port}", token=token, snapshot=snapshot)

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive(), "uvicorn thread did not exit within 10s"


def test_served_page_carries_the_real_token_and_its_own_built_assets(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert server.token in page.text
        assert "__PROSE_REVIEW_CSRF__" not in page.text

        # The built page's own hashed module script is servable from the same origin.
        match = re.search(r'<script[^>]+src="(/assets/[^"]+\.js)"', page.text)
        assert match is not None, page.text
        asset = client.get(match.group(1))
        assert asset.status_code == 200
        assert asset.headers["content-type"].startswith("text/javascript")


def test_summary_endpoint_serves_the_snapshot_dto_over_real_http(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/api/catalog/summary")
    assert response.status_code == 200
    assert response.json() == CatalogSummaryOut.from_domain(server.snapshot).model_dump(mode="json")


def test_tree_endpoint_serves_the_fixed_order_tree_over_real_http(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/api/catalog/tree")
    assert response.status_code == 200
    payload = response.json()
    assert payload == CapabilityTreeOut.from_domain(server.snapshot).model_dump(mode="json")
    assert payload["capabilities"][0]["label"] == "Foundation"


def test_inspect_endpoint_serves_the_snapshot_dto_over_real_http(
    server: _RunningServer,
) -> None:
    unit = server.snapshot.get_unit("typescript-tool:plan_review")
    assert unit is not None
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/api/inspect", params={"unit": unit.candidate.id})
    assert response.status_code == 200
    assert response.json() == UnitInspectOut.from_domain(server.snapshot, unit).model_dump(
        mode="json"
    )


def test_search_endpoint_serves_the_snapshot_dto_over_real_http(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/api/search", params={"q": "plan_review"})
    assert response.status_code == 200
    index = build_search_index(server.snapshot)
    assert response.json() == SearchOut.from_domain(search(index, "plan_review")).model_dump(
        mode="json"
    )


def test_source_endpoint_serves_whole_and_fragment_focus_over_real_http(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        whole_response = client.get("/api/source", params={"unit": "managed:repo-agents"})
        markdown_response = client.get(
            "/api/source",
            params={
                "unit": "managed:repo-agents",
                "fragment": "section:agents/developing-perk",
            },
        )
        yaml_response = client.get(
            "/api/source",
            params={
                "unit": "ambient:learned-routing",
                "fragment": "cluster:pi-extension",
            },
        )

    assert whole_response.status_code == 200
    whole = whole_response.json()
    assert whole["unit"] == "managed:repo-agents"
    assert whole["fragment"] is None
    assert whole["focus"] == (ROOT / "AGENTS.md").read_bytes().decode("utf-8")
    assert whole["read_only_reason"] == "whole-unit"

    assert markdown_response.status_code == 200
    markdown = markdown_response.json()
    assert markdown["fragment"]["id"] == "section:agents/developing-perk"
    assert markdown["editable"] is True
    assert markdown["before"] + markdown["focus"] + markdown["after"] == whole["focus"]

    assert yaml_response.status_code == 200
    yaml_source = yaml_response.json()
    assert yaml_source["fragment"]["id"] == "cluster:pi-extension"
    assert yaml_source["editable"] is True
    assert "Pi SDK/extension substrate craft" in yaml_source["focus"]


def test_wrong_host_is_rejected_over_real_http(server: _RunningServer) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden host"}
