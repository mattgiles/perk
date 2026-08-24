"""The server-integration round-trip proof: real build, real uvicorn, real DTO.

Everything short of executing browser JS — the browser leg is the plan's manual
acceptance step. The frontend is built unconditionally, once per module, into a
fixture-owned temp directory (existence is not freshness, and no two processes may
ever write one output dir), so this suite never touches the launcher's real ``dist/``.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
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
from perk_dev.prose_review.checks import CheckCommand
from perk_dev.prose_review.cli import build_frontend
from perk_dev.prose_review.comparison import comparison_options
from perk_dev.prose_review.dto import (
    CapabilityTreeOut,
    CatalogSummaryOut,
    ComparisonOptionsOut,
    SearchOut,
    UnitInspectOut,
)
from perk_dev.prose_review.search import build_search_index, search
from perk_dev.prose_review.web import create_app

ROOT = Path(__file__).parents[1]
PYTHON_UNIT_ID = "python-symbol:packages/perk-dev/src/perk_dev/audit/bounding.py:_PREAMBLE"
PYTHON_SOURCE_PATH = Path("packages/perk-dev/src/perk_dev/audit/bounding.py")
TYPESCRIPT_UNIT_ID = "typescript-tool:plan_review"
TYPESCRIPT_SOURCE_PATH = Path("extension/factories/planReview.ts")
# The complete plan-authoring assembly needs these additional canonical files under the
# fixture trust root (planReview.ts is already copied above for the source round trips).
PLAN_CONTEXT_PATH = Path("prompts/contexts/plan-authoring.md")
PLAN_SKILL_PATH = Path("skills/perk-plan/SKILL.md")
PLAN_DRAFT_PATH = Path("extension/factories/planDraft.ts")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)

# One xdist worker: the module fixture builds the frontend and owns a live server.
pytestmark = pytest.mark.xdist_group("prose_review_frontend")

# The injected streaming CheckRunner fake: emits a line every 50ms until killed, so
# the round trip below can observe mid-run growth before cancelling.
_STREAMING_CHECK_SCRIPT = (
    "import itertools, time\n"
    "for index in itertools.count():\n"
    "    print(f'line-{index}', flush=True)\n"
    "    time.sleep(0.05)\n"
)


@dataclass(frozen=True)
class _RunningServer:
    base_url: str
    token: str
    snapshot: CatalogSnapshot
    repo_root: Path
    refresh_observations: list[tuple[bytes, bytes, bytes, bytes]]


def _csrf_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def _assert_security_headers(response: httpx.Response) -> None:
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["cache-control"] == "no-store"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_RunningServer]:
    trust_root = tmp_path_factory.mktemp("prose-review-integration")
    dist_dir = trust_root / "dist"
    build_frontend(ROOT, out_dir=dist_dir)
    assert (dist_dir / "index.html").is_file()

    # Real Markdown, YAML, Python, and TypeScript candidates copied to their catalog-relative
    # paths under the fixture trust root. Pointing repo_root at the checkout would
    # break the asset-containment proof above.
    (trust_root / "AGENTS.md").write_bytes((ROOT / "AGENTS.md").read_bytes())
    clusters = trust_root / "docs/learned/clusters.yaml"
    clusters.parent.mkdir(parents=True)
    clusters.write_bytes((ROOT / "docs/learned/clusters.yaml").read_bytes())
    python_source = trust_root / PYTHON_SOURCE_PATH
    python_source.parent.mkdir(parents=True)
    python_source.write_bytes((ROOT / PYTHON_SOURCE_PATH).read_bytes())
    typescript_source = trust_root / TYPESCRIPT_SOURCE_PATH
    typescript_source.parent.mkdir(parents=True)
    typescript_source.write_bytes((ROOT / TYPESCRIPT_SOURCE_PATH).read_bytes())
    for relative in (PLAN_CONTEXT_PATH, PLAN_SKILL_PATH, PLAN_DRAFT_PATH):
        target = trust_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    snapshot = CatalogSnapshot.from_catalog(build_catalog(ROOT))
    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    refresh_observations: list[tuple[bytes, bytes, bytes, bytes]] = []

    def reload_after_write(root: Path) -> CatalogSnapshot:
        refresh_observations.append(
            (
                (root / "AGENTS.md").read_bytes(),
                (root / "docs/learned/clusters.yaml").read_bytes(),
                (root / PYTHON_SOURCE_PATH).read_bytes(),
                (root / TYPESCRIPT_SOURCE_PATH).read_bytes(),
            )
        )
        return snapshot

    app = create_app(
        snapshot=snapshot,
        repo_root=trust_root,
        selector_root=ROOT,
        dist_dir=dist_dir,
        allowed_host=f"127.0.0.1:{port}",
        csrf_token=token,
        reload_catalog=reload_after_write,
        check_commands={
            "prose-map": CheckCommand(
                label="Streaming fake",
                argv=(sys.executable, "-c", _STREAMING_CHECK_SCRIPT),
                timeout_seconds=60,
            ),
        },
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

    yield _RunningServer(
        base_url=f"http://127.0.0.1:{port}",
        token=token,
        snapshot=snapshot,
        repo_root=trust_root,
        refresh_observations=refresh_observations,
    )

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive(), "uvicorn thread did not exit within 10s"


def test_served_page_carries_the_real_token_and_its_own_built_assets(
    server: _RunningServer,
) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert _csrf_token(page.text) == server.token
        assert "__PROSE_REVIEW_CSRF__" not in page.text
        _assert_security_headers(page)

        # The built page's own hashed module script is servable from the same origin.
        match = re.search(r'<script[^>]+src="(/assets/[^"]+\.js)"', page.text)
        assert match is not None, page.text
        asset = client.get(match.group(1))
        assert asset.status_code == 200
        assert asset.headers["content-type"].startswith("text/javascript")
        _assert_security_headers(asset)


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


def test_compare_endpoint_round_trips_and_targets_the_unchanged_source_path(
    server: _RunningServer,
) -> None:
    options = comparison_options(
        server.snapshot,
        TYPESCRIPT_UNIT_ID,
        shape_id="plan.warm",
        position=5,
    )
    assert options is not None
    sibling = options.groups[0].choices[0]

    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get(
            "/api/compare",
            params={
                "unit": TYPESCRIPT_UNIT_ID,
                "shape": "plan.warm",
                "position": 5,
            },
        )
        source_response = client.get(
            "/api/source",
            params={"unit": sibling.target.unit.candidate.id},
        )

    assert response.status_code == 200
    assert response.json() == ComparisonOptionsOut.from_domain(options).model_dump(mode="json")
    assert source_response.status_code == 200
    loaded = source_response.json()
    assert loaded["file"]["path"] == sibling.target.unit.candidate.path
    source = loaded["view"]
    assert source["unit"] == sibling.target.unit.candidate.id
    assert source["fragment"] is None
    assert source["before"] + source["focus"] + source["after"] == (
        ROOT / TYPESCRIPT_SOURCE_PATH
    ).read_text(encoding="utf-8")


def test_source_endpoint_serves_whole_and_fragment_focus_over_real_http(
    server: _RunningServer,
) -> None:
    projected_text = (
        (ROOT / "AGENTS.md")
        .read_text(encoding="utf-8")
        .replace("Conventions for working", "Browser round-trip conventions for working", 1)
    )
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        page = client.get("/")
        token = _csrf_token(page.text)
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
        python_response = client.get(
            "/api/source",
            params={"unit": PYTHON_UNIT_ID, "fragment": "symbol:_PREAMBLE"},
        )
        typescript_response = client.get(
            "/api/source",
            params={"unit": TYPESCRIPT_UNIT_ID, "fragment": "description"},
        )
        projection_response = client.post(
            "/api/source/project",
            headers={"X-Prose-Review-Csrf": token},
            json={
                "unit": "managed:repo-agents",
                "fragment": "section:agents/developing-perk",
                "text": projected_text,
            },
        )
        unchanged_response = client.get(
            "/api/source",
            params={"unit": "managed:repo-agents"},
        )

    assert whole_response.status_code == 200
    whole_load = whole_response.json()
    assert list(whole_load) == ["file", "view"]
    assert list(whole_load["file"]) == ["path", "mode", "newline_style", "load_hash"]
    whole = whole_load["view"]
    assert whole["unit"] == "managed:repo-agents"
    assert whole["fragment"] is None
    assert whole["focus"] == (ROOT / "AGENTS.md").read_bytes().decode("utf-8")
    assert whole["read_only_reason"] == "whole-unit"

    assert markdown_response.status_code == 200
    markdown = markdown_response.json()["view"]
    assert markdown["fragment"]["id"] == "section:agents/developing-perk"
    assert markdown["editable"] is True
    assert markdown["before"] + markdown["focus"] + markdown["after"] == whole["focus"]

    assert yaml_response.status_code == 200
    yaml_source = yaml_response.json()["view"]
    assert yaml_source["fragment"]["id"] == "cluster:pi-extension"
    assert yaml_source["editable"] is True
    assert "Pi SDK/extension substrate craft" in yaml_source["focus"]

    assert python_response.status_code == 200
    python_source = python_response.json()["view"]
    assert list(python_source) == [
        "unit",
        "fragment",
        "kind",
        "before",
        "focus",
        "after",
        "editable",
        "read_only_reason",
    ]
    assert python_source["unit"] == PYTHON_UNIT_ID
    assert python_source["fragment"]["id"] == "symbol:_PREAMBLE"
    assert python_source["kind"] == "python-symbol"
    assert python_source["editable"] is True
    assert python_source["read_only_reason"] is None
    assert python_source["before"] + python_source["focus"] + python_source["after"] == (
        ROOT / PYTHON_SOURCE_PATH
    ).read_text(encoding="utf-8")

    assert typescript_response.status_code == 200
    typescript_source = typescript_response.json()["view"]
    assert list(typescript_source) == list(python_source)
    assert typescript_source["unit"] == TYPESCRIPT_UNIT_ID
    assert typescript_source["fragment"]["id"] == "description"
    assert typescript_source["kind"] == "typescript-tool"
    assert typescript_source["editable"] is True
    assert typescript_source["read_only_reason"] is None
    assert typescript_source["before"] + typescript_source["focus"] + typescript_source[
        "after"
    ] == (ROOT / TYPESCRIPT_SOURCE_PATH).read_text(encoding="utf-8")

    assert projection_response.status_code == 200
    _assert_security_headers(projection_response)
    projection = projection_response.json()
    assert projection["editable"] is True
    assert projection["before"] + projection["focus"] + projection["after"] == projected_text
    assert "Browser round-trip conventions" in projection["focus"]
    assert unchanged_response.status_code == 200
    _assert_security_headers(unchanged_response)
    unchanged = unchanged_response.json()
    assert unchanged["file"] == whole_load["file"]
    assert unchanged["view"]["focus"] == whole["focus"]


def test_all_editable_families_save_over_real_http_with_exact_atomic_write(
    server: _RunningServer,
) -> None:
    agents_path = server.repo_root / "AGENTS.md"
    agents_path.chmod(0o6751)
    yaml_path = server.repo_root / "docs/learned/clusters.yaml"
    python_path = server.repo_root / PYTHON_SOURCE_PATH
    python_path.chmod(0o764)
    typescript_path = server.repo_root / TYPESCRIPT_SOURCE_PATH
    typescript_path.chmod(0o754)
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        agents_load = client.get("/api/source", params={"unit": "managed:repo-agents"}).json()
        agents_text = agents_load["view"]["focus"].replace(
            "*Conventions for working", "*Real HTTP saved conventions for working", 1
        )
        agents_saved = client.post(
            "/api/source/save",
            headers={"X-Prose-Review-Csrf": server.token},
            json={
                "unit": "managed:repo-agents",
                "load_hash": agents_load["file"]["load_hash"],
                "text": agents_text,
            },
        )
        yaml_load = client.get("/api/source", params={"unit": "ambient:learned-routing"}).json()
        yaml_text = yaml_load["view"]["focus"].replace(
            "Pi SDK/extension substrate craft", "Real HTTP extension substrate craft", 1
        )
        yaml_saved = client.post(
            "/api/source/save",
            headers={"X-Prose-Review-Csrf": server.token},
            json={
                "unit": "ambient:learned-routing",
                "load_hash": yaml_load["file"]["load_hash"],
                "text": yaml_text,
            },
        )
        python_load = client.get(
            "/api/source",
            params={"unit": PYTHON_UNIT_ID, "fragment": "symbol:_PREAMBLE"},
        ).json()
        python_view = python_load["view"]
        python_focus = python_view["focus"].replace("bounded slice", "real HTTP bounded slice", 1)
        python_text = python_view["before"] + python_focus + python_view["after"]
        python_saved = client.post(
            "/api/source/save",
            headers={"X-Prose-Review-Csrf": server.token},
            json={
                "unit": PYTHON_UNIT_ID,
                "load_hash": python_load["file"]["load_hash"],
                "text": python_text,
            },
        )
        typescript_load = client.get(
            "/api/source",
            params={"unit": TYPESCRIPT_UNIT_ID, "fragment": "description"},
        ).json()
        typescript_view = typescript_load["view"]
        typescript_focus = typescript_view["focus"].replace(
            "Present the plan",
            "Present the real HTTP TypeScript plan",
            1,
        )
        assert typescript_focus != typescript_view["focus"]
        typescript_text = typescript_view["before"] + typescript_focus + typescript_view["after"]
        typescript_saved = client.post(
            "/api/source/save",
            headers={"X-Prose-Review-Csrf": server.token},
            json={
                "unit": TYPESCRIPT_UNIT_ID,
                "load_hash": typescript_load["file"]["load_hash"],
                "text": typescript_text,
            },
        )

    assert agents_saved.status_code == 200
    _assert_security_headers(agents_saved)
    agents_payload = agents_saved.json()
    assert agents_payload["status"] == "saved"
    assert (
        agents_payload["source"]["file"]["load_hash"]
        == hashlib.sha256(agents_text.encode()).hexdigest()
    )
    assert agents_payload["source"]["file"]["mode"] == 0o6751
    assert agents_path.read_bytes() == agents_text.encode()
    assert stat.S_IMODE(agents_path.stat().st_mode) == 0o6751

    assert yaml_saved.status_code == 200
    _assert_security_headers(yaml_saved)
    yaml_payload = yaml_saved.json()
    assert yaml_payload["status"] == "saved"
    assert [entry["id"] for entry in yaml_payload["materialized"]] == ["ambient-index"]
    assert [check["id"] for check in yaml_payload["checks"]] == [
        "prose-map",
        "learned-docs",
    ]
    assert yaml_path.read_bytes() == yaml_text.encode()

    assert python_saved.status_code == 200
    _assert_security_headers(python_saved)
    python_payload = python_saved.json()
    assert python_payload["status"] == "saved"
    assert (
        python_payload["source"]["file"]["load_hash"]
        == hashlib.sha256(python_text.encode("utf-8")).hexdigest()
    )
    assert python_payload["source"]["file"]["mode"] == 0o764
    assert [check["id"] for check in python_payload["checks"]] == [
        "prose-map",
        "worker-prompt-pins",
        "ruff",
        "ty",
    ]
    assert python_path.read_bytes() == python_text.encode("utf-8")
    assert stat.S_IMODE(python_path.stat().st_mode) == 0o764

    assert typescript_saved.status_code == 200
    _assert_security_headers(typescript_saved)
    typescript_payload = typescript_saved.json()
    assert typescript_payload["status"] == "saved"
    assert (
        typescript_payload["source"]["file"]["load_hash"]
        == hashlib.sha256(typescript_text.encode("utf-8")).hexdigest()
    )
    assert typescript_payload["source"]["file"]["mode"] == 0o754
    assert [check["id"] for check in typescript_payload["checks"]] == [
        "prose-map",
        "worker-prompt-pins",
        "worker-test-pins",
        "biome",
        "tsc",
    ]
    persisted_typescript = typescript_path.read_text(encoding="utf-8")
    assert persisted_typescript == typescript_text
    assert persisted_typescript.startswith(typescript_view["before"])
    assert persisted_typescript.endswith(typescript_view["after"])
    focus_start = len(typescript_view["before"])
    assert (
        persisted_typescript[focus_start : focus_start + len(typescript_focus)] == typescript_focus
    )
    assert stat.S_IMODE(typescript_path.stat().st_mode) == 0o754

    assert len(server.refresh_observations) == 4
    assert server.refresh_observations[0][0] == agents_text.encode()
    assert server.refresh_observations[1][1] == yaml_text.encode()
    assert server.refresh_observations[2][2] == python_text.encode("utf-8")
    assert all(
        observation[3] == (ROOT / TYPESCRIPT_SOURCE_PATH).read_bytes()
        for observation in server.refresh_observations[:3]
    )
    assert server.refresh_observations[3][3] == typescript_text.encode("utf-8")


def test_wrong_host_is_rejected_over_real_http(server: _RunningServer) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden host"}
    _assert_security_headers(response)


def test_assembly_options_serves_full_scenario_fixtures_over_real_http(
    server: _RunningServer,
) -> None:
    from perk_dev.prose_review.dto import AssemblyOptionsOut

    view = server.snapshot.get_assembly("plan-authoring")
    assert view is not None
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.get("/api/assembly/options", params={"assembly": "plan-authoring"})
        unknown = client.get("/api/assembly/options", params={"assembly": "missing"})
    assert response.status_code == 200
    _assert_security_headers(response)
    payload = response.json()
    assert payload == AssemblyOptionsOut.from_domain(view).model_dump(mode="json")
    assert [scenario["id"] for scenario in payload["scenarios"]] == [
        "plan-github-warm",
        "plan-linear-cold",
    ]
    assert payload["scenarios"][0]["variables"] == {
        "marker": "[PLAN AUTHORING]",
        "provider": "github",
    }
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "unknown assembly"}
    _assert_security_headers(unknown)


def test_guarded_assembly_render_round_trips_workspace_buffers_over_real_http(
    server: _RunningServer,
) -> None:
    prompt_buffer = (
        '{% if provider == "github" %}github arm{% else %}linear arm{% endif %} for {{ marker }}\n'
    )
    typescript_buffer = (
        (ROOT / TYPESCRIPT_SOURCE_PATH)
        .read_text(encoding="utf-8")
        .replace("Present the plan", "Present the unsaved buffer plan", 1)
    )
    review_unit = server.snapshot.get_unit(TYPESCRIPT_UNIT_ID)
    assert review_unit is not None
    disk_before = {
        relative: (server.repo_root / relative).read_bytes()
        for relative in (
            PLAN_CONTEXT_PATH,
            PLAN_SKILL_PATH,
            PLAN_DRAFT_PATH,
            TYPESCRIPT_SOURCE_PATH,
        )
    }
    body = {
        "assembly": "plan-authoring",
        "scenario": "plan-github-warm",
        "presentation": {"include_ambient": None, "include_tools": None},
        "buffers": [
            {"path": PLAN_CONTEXT_PATH.as_posix(), "text": prompt_buffer},
            {"path": TYPESCRIPT_SOURCE_PATH.as_posix(), "text": typescript_buffer},
        ],
    }
    with httpx.Client(base_url=server.base_url, timeout=30) as client:
        token = _csrf_token(client.get("/").text)
        rendered = client.post(
            "/api/assembly/render",
            headers={"X-Prose-Review-Csrf": token},
            json=body,
        )
        overridden = client.post(
            "/api/assembly/render",
            headers={"X-Prose-Review-Csrf": token},
            json={**body, "presentation": {"include_ambient": None, "include_tools": False}},
        )

    assert rendered.status_code == 200
    _assert_security_headers(rendered)
    payload = rendered.json()
    assert list(payload.keys()) == ["assembly", "scenario", "presentation", "layers"]
    assert payload["assembly"] == "plan-authoring"
    assert payload["scenario"]["id"] == "plan-github-warm"
    assert payload["presentation"] == {"include_ambient": True, "include_tools": True}

    # All authored layers/boundaries remain in authored order.
    assert [layer["presentation"]["position"] for layer in payload["layers"]] == [1, 2, 3, 4, 5, 6]
    assert [layer["type"] for layer in payload["layers"]] == [
        "boundary",
        "owned",
        "owned",
        "failure",
        "owned",
        "boundary",
    ]
    assert (payload["layers"][0]["boundary"], payload["layers"][0]["owner"]) == ("pi-system", "pi")
    assert (payload["layers"][5]["boundary"], payload["layers"][5]["owner"]) == (
        "user-content",
        "user",
    )

    # The unsaved prompt buffer chose the github conditional arm through the gate.
    prompt_layer = payload["layers"][1]
    assert prompt_layer["content_kind"] == "rendered-template"
    assert prompt_layer["parts"][0]["text"] == "github arm for [PLAN AUTHORING]\n"

    skill_layer = payload["layers"][2]
    assert skill_layer["content_kind"] == "raw-source"
    assert skill_layer["parts"][0]["text"] == disk_before[PLAN_SKILL_PATH].decode("utf-8")

    # The TypeScript current buffer produced exact ordered fragment parts.
    review_layer = payload["layers"][4]
    assert review_layer["content_kind"] == "source-fragments"
    assert [part["fragment"]["id"] for part in review_layer["parts"]] == [
        fragment.id for fragment in review_unit.candidate.fragments
    ]
    assert len(review_layer["parts"]) == 9
    assert "Present the unsaved buffer plan" in review_layer["parts"][0]["text"]
    for part in review_layer["parts"]:
        assert part["text"]
        assert part["text"] in typescript_buffer

    # Fixture disk bytes are unchanged by the buffered render.
    for relative, before in disk_before.items():
        assert (server.repo_root / relative).read_bytes() == before

    # Overriding tools off echoes in the resolved presentation without changing layers.
    assert overridden.status_code == 200
    _assert_security_headers(overridden)
    assert overridden.json()["presentation"] == {"include_ambient": True, "include_tools": False}
    assert overridden.json()["layers"] == payload["layers"]


def test_assembly_render_rejects_an_unpaired_surrogate_buffer_over_real_http(
    server: _RunningServer,
) -> None:
    body = json.dumps(
        {
            "assembly": "plan-authoring",
            "scenario": "plan-github-warm",
            "presentation": {"include_ambient": None, "include_tools": None},
            "buffers": [{"path": "AGENTS.md", "text": "hostile \ud800 escape"}],
        }
    )
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        token = _csrf_token(client.get("/").text)
        response = client.post(
            "/api/assembly/render",
            headers={
                "X-Prose-Review-Csrf": token,
                "Content-Type": "application/json",
            },
            content=body,
        )
    assert response.status_code == 422
    _assert_security_headers(response)
    assert "\ud800" not in response.text


def test_check_run_streams_and_cancels_over_real_http(server: _RunningServer) -> None:
    deadline = time.monotonic() + 30

    def poll(client: httpx.Client, run_id: str, offset: int) -> dict:
        response = client.get(f"/api/checks/run/{run_id}", params={"offset": offset})
        assert response.status_code == 200
        _assert_security_headers(response)
        return response.json()

    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        token = _csrf_token(client.get("/").text)
        headers = {"X-Prose-Review-Csrf": token, "Content-Type": "application/json"}
        started = client.post("/api/checks/run", headers=headers, json={"check": "prose-map"})
        assert started.status_code == 200
        _assert_security_headers(started)
        payload = started.json()
        assert (payload["check"], payload["status"]) == ("prose-map", "running")
        run_id = payload["run"]

        # Observe mid-run output growth via offset polling: two successive non-empty
        # slices while the run is still running.
        offset = payload["next_offset"]
        growth_observations = 0
        while growth_observations < 2:
            assert time.monotonic() < deadline, "no mid-run output growth observed"
            body = poll(client, run_id, offset)
            assert body["status"] == "running"
            if body["output"]:
                assert body["next_offset"] > offset
                growth_observations += 1
                offset = body["next_offset"]
            time.sleep(0.05)

        cancelled = client.post(f"/api/checks/run/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 204
        assert cancelled.content == b""
        while True:
            assert time.monotonic() < deadline, "cancelled run never went terminal"
            body = poll(client, run_id, offset)
            if body["status"] != "running":
                break
            time.sleep(0.05)
        assert body["status"] == "cancelled"
        assert body["exit_code"] is None
        assert re.match(r"line-\d+", client.get(f"/api/checks/run/{run_id}").json()["output"])


def test_lifespan_shutdown_kills_an_active_check_run(server: _RunningServer) -> None:
    # The launcher-shutdown regression: a dedicated uvicorn instance exits while an
    # injected long-running check is still active; the lifespan-wired
    # `runner.shutdown()` must kill the run's process group and finish the runner
    # threads — deleting or miswiring `create_app`'s lifespan callback fails here.
    pid_then_block = (
        "import os, time\n"
        "print(os.getpid(), flush=True)\n"
        "print('STARTED', flush=True)\n"
        "time.sleep(600)\n"
    )
    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    app = create_app(
        snapshot=server.snapshot,
        repo_root=server.repo_root,
        selector_root=ROOT,
        dist_dir=server.repo_root / "dist",
        allowed_host=f"127.0.0.1:{port}",
        csrf_token=token,
        check_commands={
            "prose-map": CheckCommand(
                label="Blocking fake",
                argv=(sys.executable, "-c", pid_then_block),
                timeout_seconds=600,
            ),
        },
    )
    uv_server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(
        target=lambda: uv_server.run(sockets=[sock]),
        name="prose-review-lifespan-uvicorn",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 30
    while not uv_server.started:
        assert thread.is_alive(), "uvicorn thread exited before startup"
        assert time.monotonic() < deadline, "uvicorn did not report started within 30s"
        time.sleep(0.05)

    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        started = client.post(
            "/api/checks/run",
            headers={"X-Prose-Review-Csrf": token, "Content-Type": "application/json"},
            json={"check": "prose-map"},
        )
        assert started.status_code == 200
        run_id = started.json()["run"]
        child_pid: int | None = None
        while child_pid is None:
            assert time.monotonic() < deadline, "the blocking check never reported its pid"
            output = client.get(f"/api/checks/run/{run_id}").json()["output"]
            lines = output.splitlines()
            if "STARTED" in lines:
                child_pid = int(lines[0])
            time.sleep(0.05)

    # Graceful shutdown with the run still active: the lifespan hook must clean up.
    uv_server.should_exit = True
    thread.join(timeout=30)
    assert not thread.is_alive(), "uvicorn thread did not exit within 30s"
    while True:
        try:
            os.killpg(child_pid, 0)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline, f"check process group {child_pid} still alive"
        time.sleep(0.05)
    while any(
        worker.name.startswith(("check-run-", "check-timer-")) for worker in threading.enumerate()
    ):
        assert time.monotonic() < deadline, "runner threads lingered after lifespan shutdown"
        time.sleep(0.05)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )


def test_git_status_and_diff_round_trip_over_real_http(
    server: _RunningServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture trust root becomes a real dirty repository for this test only:
    # commit the baseline, dirty one catalog file plus one outside file, observe over
    # HTTP, then restore the tree and drop `.git` (status/diff are computed fresh per
    # request, so no other test can observe the interlude).
    # The SERVER phase must be hermetic too: the in-process GitReader spawns with
    # `os.environ`, so a developer's global config (e.g. `core.excludesFile`) must
    # not be able to hide the fixture files during the HTTP round trip.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    repo = server.repo_root
    agents = repo / "AGENTS.md"
    original = agents.read_bytes()
    outside = repo / "outside-the-catalog.xyz"
    _git(repo, "init", "-q")
    try:
        _git(repo, "add", "-A")
        _git(
            repo,
            "-c",
            "user.name=Prose Review",
            "-c",
            "user.email=prose-review@example.invalid",
            "commit",
            "-q",
            "-m",
            "baseline",
        )
        agents.write_bytes(original + b"\nintegration git marker\n")
        outside.write_text("outside\n", encoding="utf-8")

        with httpx.Client(base_url=server.base_url, timeout=10) as client:
            status = client.get("/api/git/status")
            assert status.status_code == 200
            _assert_security_headers(status)
            body = status.json()
            assert body["status"] == "available"
            assert body["reason"] is None
            states = {entry["path"]: entry["state"] for entry in body["entries"]}
            assert states["AGENTS.md"] == "modified"
            assert body["other_change_count"] >= 1

            diff = client.get("/api/git/diff", params={"path": "AGENTS.md"})
            assert diff.status_code == 200
            _assert_security_headers(diff)
            diff_body = diff.json()
            assert diff_body["status"] == "available"
            assert diff_body["reason"] is None
            assert "+integration git marker" in diff_body["diff"]
            assert diff_body["truncated"] is False

            missing = client.get("/api/git/diff", params={"path": "outside-the-catalog.xyz"})
            assert missing.status_code == 404
            assert missing.json() == {"detail": "unknown path"}
            _assert_security_headers(missing)
    finally:
        agents.write_bytes(original)
        outside.unlink(missing_ok=True)
        shutil.rmtree(repo / ".git")
