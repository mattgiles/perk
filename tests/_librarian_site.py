"""Fake-site helpers for the `librarian` skill's crawl script
(``skills/librarian/scripts/copy_docs_to_markdown.py``).

The script ships as a standalone stdlib file (never imported by perk), so it is loaded by path.
The network and the converter are faked at the script's own seams (``fetch_html`` /
``convert_html`` / ``which``); the filesystem stays real.
"""

import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "librarian" / "scripts" / "copy_docs_to_markdown.py"


# A stand-in crawl script for the docs doors' and the `prepare` worker's dry-run and seed probe.
# Modes (FAKE_EXIT): an exit code, `signal`, `3` (the seed-redirect blocker) or `3-hostile` (a
# blocker naming a `javascript:` target). A trailing `--dry-run` is required; the seed probe's
# `--max-pages 1` before it is tolerated.
FAKE_DRY_RUN_SCRIPT = """\
import json
import os
import signal
import sys

url, out = sys.argv[1], sys.argv[2]
assert sys.argv[-1] == "--dry-run", sys.argv
mode = os.environ.get("FAKE_EXIT", "0")
if mode.startswith("3"):
    target = "javascript:alert(1)" if mode == "3-hostile" else "https://d.example/0.5.4/"
    blocker = {
        "blocker": "seed-redirect",
        "seed_url": url,
        "fetched_url": url,
        "redirect_url": target,
        "scope_prefix": "/0.5.4/",
    }
    print(json.dumps(blocker, sort_keys=True))
    print(f"ERROR: the seed {url} is only an HTML redirect page to {target}", file=sys.stderr)
    sys.exit(3)
print(f"Would copy 2 page(s) into {out}")
print(f"{url} -> docs-home.md")
print(f"{url}/guide -> guide.md")
print("WARNING: skipped https://d.example/x: path collision", file=sys.stderr)
if mode == "2":
    print("ERROR: refusing to crawl (fake)", file=sys.stderr)
sys.stdout.flush()
sys.stderr.flush()
if mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
sys.exit(int(mode))
"""


@dataclass(frozen=True)
class Redirect:
    """A page served from another URL after curl followed a redirect."""

    to: str
    html: str


type SiteValue = str | Redirect | subprocess.CalledProcessError


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("copy_docs_to_markdown", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_script(script: ModuleType, argv: list[str]) -> int:
    try:
        return script.main(argv)
    except SystemExit as exc:
        assert isinstance(exc.code, int)
        return exc.code


def page(title: str, *hrefs: str) -> str:
    links = "".join(f'<a href="{href}">{href}</a>' for href in hrefs)
    return f"<html><body><h1>{title}</h1><p>{title} body.</p>{links}</body></html>"


def redirect_stub(to: str) -> str:
    """The mike version-alias page (a `/latest/`-style stub) served `200`: a `<noscript>` meta
    refresh, a `location.replace` split over lines, and one fallback anchor — the live shape."""
    return (
        "<!DOCTYPE html><html><head><title>Redirecting</title>"
        f'<noscript><meta http-equiv="refresh" content="1; url={to}" /></noscript>'
        "<script>window.location.replace(\n"
        f'  "{to}" + window.location.search + window.location.hash\n'
        ");</script></head>"
        f'<body>Redirecting to <a href="{to}">{to}</a>...</body></html>'
    )


def http_error(url: str, status: int = 404) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        22, ["curl", url], stderr=f"curl: (22) The requested URL returned error: {status}\n"
    )


def stub_markdown(html_text: str) -> str:
    """A deterministic stand-in for html2markdown: `<h1>` → `# …`, `<a href>` → `[…](…)`."""
    text = re.sub(r"<h1>(.*?)</h1>", r"# \1\n\n", html_text)
    text = re.sub(r'<a href="([^"]*)">(.*?)</a>', r"[\2](\1)\n", text)
    text = re.sub(r"<p>(.*?)</p>", r"\1\n\n", text)
    return re.sub(r"<[^>]+>", "", text)


def fake_site(
    monkeypatch: pytest.MonkeyPatch,
    script: ModuleType,
    pages: Mapping[str, SiteValue],
    *,
    on_convert: Callable[[int], None] | None = None,
) -> list[str]:
    """Serve ``pages`` through the script's seams; returns the log of fetched URLs."""
    fetched: list[str] = []
    conversions = [0]

    def fetch_html(url: str) -> object:
        fetched.append(url)
        value = pages.get(url, http_error(url))
        if isinstance(value, subprocess.CalledProcessError):
            raise value
        if isinstance(value, Redirect):
            return script.Fetched(html=value.html, url=value.to)
        return script.Fetched(html=value, url=url)

    def convert_html(html_text: str) -> str:
        index = conversions[0]
        conversions[0] += 1
        if on_convert is not None:
            on_convert(index)
        return stub_markdown(html_text)

    monkeypatch.setattr(script, "fetch_html", fetch_html)
    monkeypatch.setattr(script, "convert_html", convert_html)
    monkeypatch.setattr(script, "which", lambda tool: f"/usr/bin/{tool}")
    return fetched
