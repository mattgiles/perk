#!/usr/bin/env python3
"""Copy technical documentation pages from a URL into local Markdown files.

Stdlib-only. External tools required on PATH: `curl` (fetch) and `html2markdown` (convert).
Crawls same-scope documentation links breadth-first from a seed URL, writes one Markdown
file per page preserving the scoped URL hierarchy, rewrites internal links to local
relative `.md` links, and generates an `index.md` entrypoint.
"""

import argparse
import html
import os
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

SUBPROCESS_TIMEOUT_SECONDS = 120

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


def run_text(command: list[str], stdin_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        input=stdin_text,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout


def fetch_html(url: str) -> str:
    return run_text(["curl", "--no-progress-meter", url])


def convert_to_markdown(url: str) -> str:
    return run_text(["html2markdown"], stdin_text=fetch_html(url))


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


def normalize_scope_prefix(scope_prefix: str | None, seed_url: str) -> str:
    if scope_prefix:
        prefix = scope_prefix if scope_prefix.startswith("/") else f"/{scope_prefix}"
        return prefix if prefix.endswith("/") else f"{prefix}/"

    path = urlparse(seed_url).path
    if path.endswith("/"):
        path = path[:-1]
    parts = [part for part in path.split("/") if part]
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
    path = urlparse(url).path
    if path.startswith(scope_prefix):
        path = path[len(scope_prefix) :]
    path = path.strip("/")

    if not path:
        return Path("docs-home.md")

    parsed_path = Path(path)
    if parsed_path.suffix:
        return parsed_path.with_suffix(".md")
    return parsed_path / "index.md" if path.endswith("/") else parsed_path.with_suffix(".md")


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


def discover_pages(seed_url: str, scope_prefix: str, max_pages: int) -> tuple[list[str], list[str]]:
    parsed_seed = urlparse(seed_url)
    origin = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
    queue: deque[str] = deque([urldefrag(seed_url)[0]])
    seen: set[str] = set()
    ordered: list[str] = []
    failures: list[str] = []

    while queue and len(ordered) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not in_scope(url, origin, scope_prefix):
            continue

        try:
            html_text = fetch_html(url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{url} fetch failed: {exc}")
            continue

        ordered.append(url)
        for linked_url in parse_links(url, html_text):
            if linked_url not in seen and in_scope(linked_url, origin, scope_prefix):
                queue.append(linked_url)

    return ordered, failures


def copy_docs(
    seed_url: str, output_dir: Path, scope_prefix: str, max_pages: int, dry_run: bool
) -> int:
    urls, failures = discover_pages(seed_url, scope_prefix, max_pages)
    url_to_path = {url: markdown_path_for_url(url, scope_prefix) for url in urls}
    link_lookup = build_link_lookup(url_to_path)

    if dry_run:
        print(f"Would copy {len(urls)} page(s) into {output_dir}")
        for url in urls:
            print(f"{url} -> {url_to_path[url]}")
        for failure in failures:
            print(f"WARNING: {failure}", file=sys.stderr)
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Page] = []

    for url in urls:
        try:
            markdown = convert_to_markdown(url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{url} conversion failed: {exc}")
            continue
        pages.append(Page(url=url, path=url_to_path[url], markdown=markdown))

    for page in pages:
        markdown = rewrite_markdown_links(page.markdown, page.path, link_lookup)
        target = output_dir / page.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")

    (output_dir / "index.md").write_text(
        make_index(seed_url, scope_prefix, pages), encoding="utf-8"
    )

    print(f"Copied {len(pages)} page(s) into {output_dir}")
    print(f"Scope prefix: {scope_prefix}")
    print(f"Index: {output_dir / 'index.md'}")
    for failure in failures:
        print(f"WARNING: {failure}", file=sys.stderr)
    return 0 if pages else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Seed documentation URL")
    parser.add_argument("output_dir", type=Path, help="Destination directory for Markdown files")
    parser.add_argument("--scope-prefix", help="URL path prefix to keep in scope")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum pages to copy")
    parser.add_argument(
        "--dry-run", action="store_true", help="Discover pages without writing files"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")

    scope_prefix = normalize_scope_prefix(args.scope_prefix, args.url)
    return copy_docs(args.url, args.output_dir, scope_prefix, args.max_pages, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
