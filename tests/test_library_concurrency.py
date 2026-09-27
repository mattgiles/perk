"""Cross-process library lock semantics with real subprocesses (contracts.md §8.75(c)).

(a) a held lock refuses a second writer with the typed ``library_busy`` (staging intact, nothing
written) and the same command succeeds once released; (b) six concurrent publishers, each
retrying on ``library_busy``, lose no update; (c) a reader looping over ``load_catalog`` while
they run never sees a torn catalog and observes a non-decreasing entry count.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from perk.library import catalog as cat
from perk.library import lock
from perk.library.layout import LibraryLayout

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(lock.fcntl is None, reason="the lock is a no-op without fcntl"),
]

SOURCE = "https://example.com/docs"

_HOLDER = """
import sys, time
from pathlib import Path
from perk.library.lock import library_lock
repo, ready, release = (Path(arg) for arg in sys.argv[1:4])
with library_lock(repo):
    ready.touch()
    deadline = time.monotonic() + 60
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
"""

_RETRYING_PUBLISHER = """
import json, subprocess, sys, time
argv = [sys.executable, "-m", "perk", "librarian", "record", "--publish", sys.argv[1],
        "--slug", sys.argv[2], "--source", sys.argv[3], "--json"]
for _ in range(100):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    payload = json.loads(proc.stdout)
    if payload.get("error_type") != "library_busy":
        print(proc.stdout.strip())
        sys.exit(proc.returncode)
    time.sleep(0.025)
print(json.dumps({"success": False, "error_type": "retries_exhausted"}))
sys.exit(1)
"""


def _env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "PERK_RUN_ID"}
    env["PERK_SKIP_VERSION_CHECK"] = "1"
    return env


def _stage(repo: Path, name: str) -> Path:
    staging = LibraryLayout.for_repo(repo).staging / name
    staging.mkdir(parents=True)
    (staging / "index.md").write_text(f"# {name}\n", encoding="utf-8")
    return staging


def _publish_argv(staging: Path, slug: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "perk",
        "librarian",
        "record",
        "--publish",
        str(staging),
        "--slug",
        slug,
        "--source",
        SOURCE,
        "--json",
    ]


def _wait_for(path: Path, *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.02)


def test_a_held_lock_refuses_a_second_writer(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    signals = tmp_path_factory.mktemp("signals")
    ready, release = signals / "ready", signals / "release"
    staging = _stage(repo, "pi-01")
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(repo), str(ready), str(release)], env=_env()
    )
    try:
        _wait_for(ready)
        busy = subprocess.run(
            _publish_argv(staging, "pi"),
            cwd=repo,
            env=_env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert busy.returncode == 1, busy.stderr
        assert json.loads(busy.stdout)["error_type"] == "library_busy"
        assert (staging / "index.md").is_file()
        assert not LibraryLayout.for_repo(repo).catalog_path.exists()
    finally:
        release.touch()
        holder.wait(timeout=60)
    done = subprocess.run(
        _publish_argv(staging, "pi"),
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["success"] is True


def test_concurrent_publishers_lose_no_update_and_readers_see_no_torn_catalog(
    scaffolded_perk_repo,
):
    repo = scaffolded_perk_repo
    layout = LibraryLayout.for_repo(repo)
    slugs = [f"mirror-{index}" for index in range(6)]
    stagings = [_stage(repo, f"{slug}-crawl") for slug in slugs]
    observed: list[int] = []
    failures: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            for _ in range(200):
                observed.append(len(cat.load_catalog(layout).entries))
                if stop.is_set():
                    break
                time.sleep(0.005)
        except BaseException as exc:  # surfaced to the main thread below
            failures.append(exc)

    thread = threading.Thread(target=reader)
    thread.start()
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", _RETRYING_PUBLISHER, str(staging), slug, SOURCE],
            cwd=repo,
            env=_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for staging, slug in zip(stagings, slugs, strict=True)
    ]
    results = [writer.communicate(timeout=300) for writer in writers]
    stop.set()
    thread.join(timeout=60)
    assert not failures, failures
    for writer, (stdout, stderr) in zip(writers, results, strict=True):
        assert writer.returncode == 0, stdout + stderr
    final = cat.load_catalog(layout)
    assert sorted(entry.slug for entry in final.entries) == sorted(slugs)
    for slug in slugs:
        assert (layout.docs_entry_dir(slug) / "index.md").is_file()
    assert observed, "the reader never ran"
    assert observed == sorted(observed)
