#!/usr/bin/env python3
"""Copy technical documentation pages from a URL into a staging directory of Markdown files.

Stdlib-only (Python 3.10+). External tools required on PATH: `curl` (fetch) and `html2markdown`
(convert). Crawls same-scope documentation links breadth-first from a seed URL, fetching each page
once, writes one Markdown file per page preserving the scoped URL hierarchy, rewrites internal
links to local relative `.md` links, and writes the staging handshakes `perk librarian record
--publish` consumes: `failed-pages.json` (the failure report, always written), `sources.json` (the
per-page inventory) and, last, the `index.md` entrypoint.

Every write is contained in OUTPUT_DIR (symlinked components are refused) and atomic (a temporary
sibling renamed over the target), so no truncated page or artifact can exist, and `index.md`
appears only once the report and inventory are complete — a crawl that did not finish cannot be
published.

Exit codes: 0 — every discovered page copied; 1 — the crawl completed with failures or copied
nothing (dry-run: a discovery fetch failed); 2 — refused or aborted without a usable crawl (bad
arguments, a missing tool, a non-empty or symlinked OUTPUT_DIR, an untrustworthy staging state).
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlparse

SUBPROCESS_TIMEOUT_SECONDS = 120
MAX_REDIRECTS = 5
FILE_MODE = 0o644
HTML2MARKDOWN_INSTALL_HINT = "brew install html2markdown"

INDEX_FILENAME = "index.md"
INVENTORY_FILENAME = "sources.json"
FAILED_PAGES_FILENAME = "failed-pages.json"
HOME_FILENAME = "docs-home.md"
# The generated artifacts own these paths at the output root; no page may occupy one.
RESERVED_ROOT_NAMES = frozenset({INDEX_FILENAME, INVENTORY_FILENAME, FAILED_PAGES_FILENAME})

NON_EMPTY_OUTPUT_REFUSAL = (
    "refusing to write into a non-empty directory — choose a new or empty staging directory"
)

# Resolved at call time through the module attribute so tests can simulate missing tools.
which = shutil.which

ASSET_EXTENSIONS = {
    ".7z",
    ".avif",
    ".css",
    ".csv",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mp4",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".tar",
    ".tgz",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
    ".zip",
}


class UnsafePath(ValueError):
    """A URL path or write target that could escape or alias the output directory."""


class StagingUntrustworthy(Exception):
    """A failed write left a temporary file behind that could not be removed."""


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "link"}:
            return
        for key, value in attrs:
            if key == "href" and value:
                self.links.append(html.unescape(value))


@dataclass(frozen=True)
class Page:
    url: str
    path: Path
    markdown: str


@dataclass(frozen=True)
class Failure:
    """One page the crawl tried and failed to copy — a `failed-pages.json` record."""

    url: str
    stage: Literal["fetch", "convert", "write"]
    reason: str


@dataclass(frozen=True)
class Collision:
    url: str
    path: Path
    first_url: str


@dataclass
class Discovery:
    """What the crawl fetched (URL → HTML, crawl order), failed to fetch, and refused."""

    html: dict[str, str] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def error(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def run_text(command: list[str], stdin_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_text,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout


def fetch_html(url: str) -> str:
    # `--fail` turns an HTTP error status into a fetch failure instead of a mirrored error page.
    return run_text(
        [
            "curl",
            "--no-progress-meter",
            "--fail",
            "--location",
            "--max-redirs",
            str(MAX_REDIRECTS),
            url,
        ]
    )


def convert_html(html_text: str) -> str:
    return run_text(["html2markdown"], stdin_text=html_text)


def describe(exc: BaseException) -> str:
    """One short line naming why a page failed."""
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        first = next((line.strip() for line in stderr.splitlines() if line.strip()), "")
        return f"exit {exc.returncode}: {first}" if first else f"exit {exc.returncode}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {exc.timeout:g}s"
    if isinstance(exc, OSError):
        return exc.strerror or str(exc)
    return str(exc)


def parse_links(base_url: str, html_text: str) -> list[str]:
    parser = LinkParser()
    parser.feed(html_text)
    normalized: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        url, _fragment = urldefrag(urljoin(base_url, href))
        if url not in seen:
            normalized.append(url)
            seen.add(url)
    return normalized


def has_asset_extension(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in ASSET_EXTENSIONS


def normalize_segments(url_path: str) -> tuple[str, ...]:
    """The non-empty `/`-separated segments of ``url_path``; refuses `.`/`..` and NUL segments.

    Segments are never percent-decoded: `%2e%2e` stays a literal (inert) filename.
    """
    segments: list[str] = []
    for segment in url_path.split("/"):
        if not segment:
            continue
        if segment in {".", ".."}:
            raise UnsafePath(f"dot segment {segment!r} in path {url_path!r}")
        if "\x00" in segment:
            raise UnsafePath(f"NUL byte in path {url_path!r}")
        segments.append(segment)
    return tuple(segments)


def normalize_scope_prefix(scope_prefix: str | None, seed_url: str) -> str:
    if scope_prefix:
        segments = normalize_segments(scope_prefix)
        return "/" + "".join(f"{segment}/" for segment in segments)

    parts = normalize_segments(urlparse(seed_url).path)
    if len(parts) >= 2:
        return "/" + "/".join(parts[:-1]) + "/"
    return "/"


def in_scope(url: str, origin: str, scope_prefix: str) -> bool:
    parsed = urlparse(url)
    url_origin = f"{parsed.scheme}://{parsed.netloc}"
    return (
        url_origin == origin
        and parsed.path.startswith(scope_prefix)
        and not has_asset_extension(url)
    )


def markdown_path_for_url(url: str, scope_prefix: str) -> Path:
    """The output-relative Markdown path for ``url``; raises :class:`UnsafePath` for a URL whose
    path could escape or alias the output directory."""
    path = urlparse(url).path
    if path.startswith(scope_prefix):
        path = path[len(scope_prefix) :]
    segments = normalize_segments(path)
    if not segments:
        return Path(HOME_FILENAME)
    relative = Path(*segments).with_suffix(".md")
    if relative.as_posix() == INDEX_FILENAME:
        # The scope root's upstream index page shares the scope root's name; the generated
        # entrypoint owns `index.md`.
        return Path(HOME_FILENAME)
    if relative.as_posix() in RESERVED_ROOT_NAMES:
        raise UnsafePath(f"{relative.as_posix()} is a reserved artifact name")
    if relative.is_absolute() or ".." in relative.parts:
        raise UnsafePath(f"{relative} escapes the output directory")
    return relative


def page_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("[", "!", "-", "*", "`", "#")):
            return stripped[:80]
    return fallback


def page_note(markdown: str) -> str:
    after_title = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            after_title = True
            continue
        if not after_title:
            continue
        if not stripped or stripped.startswith(("[", "!", "-", "*", "`", "#", "|")):
            continue
        if stripped in {"API Documentation", "Search `CtrlK`", "On this page"}:
            continue
        if len(stripped) < 80:
            continue
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        stripped = stripped.replace("`", "")
        stripped = re.sub(r"\s+", " ", stripped)
        if len(stripped) <= 180:
            return stripped
        return stripped[:177].rsplit(" ", 1)[0] + "..."
    return "Reference this page for the topic named by its title."


def build_link_lookup(url_to_path: dict[str, Path]) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for url, path in url_to_path.items():
        parsed = urlparse(url)
        keys = {
            url,
            parsed.path,
            parsed.path.rstrip("/"),
            f"{parsed.path.rstrip('/')}/",
        }
        for key in keys:
            lookup[key] = path
    return lookup


def rewrite_markdown_links(markdown: str, current_path: Path, link_lookup: dict[str, Path]) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        if target.startswith(("#", "mailto:", "tel:", "javascript:")):
            return match.group(0)
        clean_target, fragment = urldefrag(target)
        local_path = link_lookup.get(clean_target)
        if local_path is None:
            return match.group(0)
        relative = os.path.relpath(local_path, start=current_path.parent)
        if fragment:
            relative = f"{relative}#{fragment}"
        return f"[{label}]({relative})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, markdown)


def make_index(seed_url: str, scope_prefix: str, pages: list[Page]) -> str:
    grouped: dict[str, list[Page]] = {}
    for page in pages:
        group = page.path.parts[0] if len(page.path.parts) > 1 else "overview"
        grouped.setdefault(group, []).append(page)

    lines = [
        "# Documentation Index",
        "",
        f"Source seed: {seed_url}",
        f"Scope prefix: `{scope_prefix}`",
        "",
        "Use this index as the entrypoint for the copied documentation. "
        "Links point to local Markdown files.",
        "",
    ]

    for group in sorted(grouped):
        title = group.replace("-", " ").replace("_", " ").title()
        lines.extend([f"## {title}", ""])
        for page in sorted(grouped[group], key=lambda item: str(item.path)):
            title_text = page_title(page.markdown, page.path.stem.replace("-", " ").title())
            note = page_note(page.markdown)
            lines.append(f"- [{title_text}]({page.path.as_posix()}): {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def discover_pages(seed_url: str, scope_prefix: str, max_pages: int) -> Discovery:
    """Crawl breadth-first from ``seed_url``, fetching each in-scope page once.

    A link whose path cannot map safely into the output directory is rejected — never queued or
    fetched — and is not a failed page (a failed page is one the crawl tried to copy).
    """
    parsed_seed = urlparse(seed_url)
    origin = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
    queue: deque[str] = deque([urldefrag(seed_url)[0]])
    seen: set[str] = set()
    discovery = Discovery()

    def admissible(url: str) -> bool:
        if not in_scope(url, origin, scope_prefix):
            return False
        try:
            markdown_path_for_url(url, scope_prefix)
        except UnsafePath as exc:
            if url not in discovery.rejected:
                discovery.rejected[url] = str(exc)
                warn(f"rejected unsafe URL {url}: {exc}")
            return False
        return True

    while queue and len(discovery.html) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not admissible(url):
            continue

        try:
            html_text = fetch_html(url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            failure = Failure(url=url, stage="fetch", reason=describe(exc))
            discovery.failures.append(failure)
            warn(f"failed to fetch {url}: {failure.reason}")
            continue

        discovery.html[url] = html_text
        for linked_url in parse_links(url, html_text):
            if linked_url not in seen and admissible(linked_url):
                queue.append(linked_url)

    return discovery


def claim_paths(urls: list[str], scope_prefix: str) -> tuple[dict[str, Path], list[Collision]]:
    """Assign destinations in crawl order; the first claimant of a path wins.

    A later page collides when its path equals a claimed file, sits beneath a claimed file
    (`a.md/b.md` after `a.md`), or is a parent directory of a claimed file (`a.md` after
    `a.md/b.md`) — so a write never meets a file where it needs a directory.
    """
    claimed: dict[str, Path] = {}
    files: dict[Path, str] = {}
    directories: dict[Path, str] = {}
    collisions: list[Collision] = []
    for url in urls:
        path = markdown_path_for_url(url, scope_prefix)
        parents = [parent for parent in path.parents if parent != Path()]
        first_url = files.get(path) or directories.get(path)
        if first_url is None:
            first_url = next((files[parent] for parent in parents if parent in files), None)
        if first_url is not None:
            collisions.append(Collision(url=url, path=path, first_url=first_url))
            continue
        claimed[url] = path
        files[path] = url
        for parent in parents:
            directories.setdefault(parent, url)
    return claimed, collisions


def discard(path: Path) -> None:
    path.unlink(missing_ok=True)


def write_contained(output_dir: Path, output_root: Path, rel_path: Path, text: str) -> None:
    """Atomically write ``text`` to ``output_dir / rel_path``, refusing any path that is or runs
    through a symlink or resolves outside ``output_root``.

    The text goes to a temporary sibling that is renamed over the target, so the target is either
    absent, its previous content, or complete. On failure the temporary file is removed; when that
    removal fails, :class:`StagingUntrustworthy` names the leftover.
    """
    if rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts:
        raise UnsafePath(f"{rel_path} is not a path inside the output directory")
    current = output_dir
    for part in rel_path.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise UnsafePath(f"{current} is a symlink")
    target = output_dir / rel_path
    if target.is_symlink():
        raise UnsafePath(f"{target} is a symlink")
    try:
        resolved = target.resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise UnsafePath(f"{target} cannot be resolved ({exc})") from exc
    if not resolved.is_relative_to(output_root):
        raise UnsafePath(f"{target} resolves outside {output_root}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            if not temp_path.resolve().is_relative_to(output_root):
                raise UnsafePath(f"{temp_path} resolves outside {output_root}")
            handle.write(text)
        temp_path.chmod(FILE_MODE)
        # `Path.replace` is `os.replace`: an atomic rename over the target.
        temp_path.replace(target)
    except (OSError, UnsafePath):
        if temp_path is None:
            raise
        try:
            discard(temp_path)
        except OSError as cleanup_exc:
            raise StagingUntrustworthy(
                f"could not remove the temporary file {temp_path} ({describe(cleanup_exc)})"
            ) from cleanup_exc
        raise


def output_dir_refusal(output_dir: Path) -> str | None:
    """Why ``output_dir`` cannot receive a crawl, or ``None`` when it is absent or empty."""
    if output_dir.is_symlink():
        return f"{output_dir} is a symlink — choose a real staging directory"
    if not output_dir.exists():
        return None
    try:
        occupied = not output_dir.is_dir() or any(output_dir.iterdir())
    except OSError as exc:
        return f"cannot inspect {output_dir} ({describe(exc)})"
    return f"{NON_EMPTY_OUTPUT_REFUSAL} ({output_dir})" if occupied else None


def print_counts(discovery: Discovery, collisions: list[Collision]) -> None:
    print(f"Rejected unsafe URLs: {len(discovery.rejected)}")
    print(f"Skipped collisions: {len(collisions)}")


def copy_docs(
    seed_url: str, output_dir: Path, scope_prefix: str, max_pages: int, dry_run: bool
) -> int:
    if not dry_run:
        refusal = output_dir_refusal(output_dir)
        if refusal is not None:
            error(refusal)
            return 2

    discovery = discover_pages(seed_url, scope_prefix, max_pages)
    url_to_path, collisions = claim_paths(list(discovery.html), scope_prefix)
    for collision in collisions:
        warn(f"skipped {collision.url}: path collision with {collision.first_url}")
    # A page-vs-page duplicate (`/docs/` and `/docs/index.html`) still links to the written copy.
    link_targets = dict(url_to_path)
    for collision in collisions:
        if url_to_path[collision.first_url] == collision.path:
            link_targets[collision.url] = collision.path
    link_lookup = build_link_lookup(link_targets)

    if dry_run:
        print(f"Would copy {len(url_to_path)} page(s) into {output_dir}")
        for url, path in url_to_path.items():
            print(f"{url} -> {path.as_posix()}")
        print(f"Scope prefix: {scope_prefix}")
        print(f"Failed pages: {len(discovery.failures)}")
        print_counts(discovery, collisions)
        return 1 if discovery.failures else 0

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_root = output_dir.resolve()
    except (OSError, RuntimeError) as exc:
        error(f"cannot create {output_dir} ({describe(exc)})")
        return 2

    failures = list(discovery.failures)
    pages: list[Page] = []
    for url, path in url_to_path.items():
        try:
            markdown = convert_html(discovery.html[url])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            failures.append(Failure(url=url, stage="convert", reason=describe(exc)))
            warn(f"failed to convert {url}: {failures[-1].reason}")
            continue
        try:
            write_contained(
                output_dir,
                output_root,
                path,
                rewrite_markdown_links(markdown, path, link_lookup),
            )
        except (UnsafePath, OSError) as exc:
            failures.append(Failure(url=url, stage="write", reason=describe(exc)))
            warn(f"failed to write {url} to {path.as_posix()}: {failures[-1].reason}")
            continue
        pages.append(Page(url=url, path=path, markdown=markdown))

    inventory = {
        "seed_url": seed_url,
        "scope_prefix": scope_prefix,
        "pages": [{"source_url": page.url, "path": page.path.as_posix()} for page in pages],
    }
    # Report and inventory before the entrypoint: `record --publish` requires `index.md`, so a
    # crawl interrupted before this point is unpublishable.
    artifacts = [
        (FAILED_PAGES_FILENAME, json.dumps([asdict(item) for item in failures], indent=2) + "\n"),
        (INVENTORY_FILENAME, json.dumps(inventory, indent=2) + "\n"),
        (INDEX_FILENAME, make_index(seed_url, scope_prefix, pages)),
    ]
    for name, text in artifacts:
        try:
            write_contained(output_dir, output_root, Path(name), text)
        except (UnsafePath, OSError) as exc:
            error(
                f"could not write {output_dir / name} ({describe(exc)}) — the staging directory "
                f"is not trustworthy; delete {output_dir} before re-crawling"
            )
            return 2

    print(f"Copied {len(pages)} page(s) into {output_dir}")
    print(f"Scope prefix: {scope_prefix}")
    print(f"Index: {output_dir / INDEX_FILENAME}")
    print(f"Failed pages: {len(failures)} (see {output_dir / FAILED_PAGES_FILENAME})")
    print_counts(discovery, collisions)
    return 0 if pages and not failures else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url", help="Seed documentation URL (absolute http/https)")
    parser.add_argument(
        "output_dir", type=Path, help="New or empty staging directory for the Markdown files"
    )
    parser.add_argument("--scope-prefix", help="URL path prefix to keep in scope")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum pages to copy")
    parser.add_argument(
        "--dry-run", action="store_true", help="Discover pages without writing files"
    )
    return parser


def missing_tool_errors(dry_run: bool) -> list[str]:
    errors: list[str] = []
    if which("curl") is None:
        errors.append("curl is not on PATH — install curl")
    if not dry_run and which("html2markdown") is None:
        errors.append(f"html2markdown is not on PATH — install it ({HTML2MARKDOWN_INSTALL_HINT})")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    seed = urlparse(args.url)
    if seed.scheme not in {"http", "https"} or not seed.netloc:
        parser.error(f"URL must be an absolute http(s) URL: {args.url!r}")
    try:
        normalize_segments(seed.path)
    except UnsafePath as exc:
        parser.error(f"unsafe URL {args.url!r}: {exc}")
    try:
        scope_prefix = normalize_scope_prefix(args.scope_prefix, args.url)
    except UnsafePath as exc:
        parser.error(f"unsafe --scope-prefix {args.scope_prefix!r}: {exc}")

    missing = missing_tool_errors(args.dry_run)
    for message in missing:
        error(message)
    if missing:
        return 2

    try:
        return copy_docs(args.url, args.output_dir, scope_prefix, args.max_pages, args.dry_run)
    except StagingUntrustworthy as exc:
        error(
            f"{exc} — the staging directory is not trustworthy; delete {args.output_dir} before "
            "re-crawling"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
