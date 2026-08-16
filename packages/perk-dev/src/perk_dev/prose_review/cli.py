"""The Prose Review Workbench launcher: build the frontend, then serve it locally.

A foreground server, not a report — failures go through ``perk.cli.emit.fail`` with
``as_json=False`` and the process blocks in uvicorn until Ctrl-C. The frontend is
rebuilt on every launch (a build failure is a typed CLI error and no server starts);
the server binds an OS-assigned loopback port, and that one printed origin is the
only host the security guard accepts.
"""

import secrets
import socket
import webbrowser
from pathlib import Path

import click
import uvicorn

from perk.cli.emit import fail
from perk.substrate.git import repo_root
from perk.substrate.output import io_step, user_output
from perk.substrate.proc import ProcFailure, run_checked
from perk_dev.prose_map.catalog import ProseMapError
from perk_dev.prose_review.catalog import CatalogQueryError, load_catalog
from perk_dev.prose_review.web import SecurityGuardMiddleware, create_app

_DIST_RELATIVE = Path("tools/prose-review/dist")


def build_frontend(root: Path, *, out_dir: Path | None = None) -> None:
    """Run the Vite production build (into ``out_dir`` when given; the real dist otherwise).

    Public on purpose: the server-integration fixture reuses it to build into a
    fixture-owned temp directory, so no two processes ever write one output dir.
    ``ProcFailure`` propagates to the caller's error arm.
    """
    argv = ["npm", "run", "build", "--workspace", "tools/prose-review"]
    if out_dir is not None:
        argv += ["--", "--outDir", str(out_dir), "--emptyOutDir"]
    run_checked(argv, cwd=root, timeout=300)


def _open_browser(url: str) -> bool:
    """Open ``url`` in the default browser — a module-level seam for tests."""
    return webbrowser.open(url)


def _serve(app: SecurityGuardMiddleware, sock: socket.socket) -> None:
    """Run uvicorn on the pre-bound listening socket — a module-level seam for tests."""
    config = uvicorn.Config(app, log_level="warning", access_log=False)
    uvicorn.Server(config).run(sockets=[sock])


@click.command("prose-review")
@click.option("--no-open", "no_open", is_flag=True, help="Print the URL; do not open a browser.")
@click.pass_context
def prose_review(ctx: click.Context, *, no_open: bool) -> None:
    """Build and serve the Prose Review Workbench (foreground; Ctrl-C to stop)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return

    try:
        with io_step("building prose-review frontend"):
            build_frontend(root)
    except ProcFailure as exc:
        fail(ctx, as_json=False, error_type="frontend_build_failed", message=str(exc))
        return
    index_html = root / _DIST_RELATIVE / "index.html"
    if not index_html.is_file():
        fail(
            ctx,
            as_json=False,
            error_type="frontend_build_failed",
            message=f"build completed but {index_html} is missing",
        )
        return

    try:
        snapshot = load_catalog(root)
    except (ProseMapError, CatalogQueryError) as exc:
        fail(ctx, as_json=False, error_type="catalog_invalid", message=str(exc))
        return

    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # The socket is bound before uvicorn starts so the printed URL is the real port;
    # the finally arm covers every path where _serve is never reached or returns.
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = int(sock.getsockname()[1])
        app = create_app(
            snapshot=snapshot,
            repo_root=root,
            selector_root=root,
            dist_dir=root / _DIST_RELATIVE,
            allowed_host=f"127.0.0.1:{port}",
            csrf_token=token,
        )
        url = f"http://127.0.0.1:{port}"
        user_output(f"serving {url}  (Ctrl-C to stop)")
        if not no_open:
            # A deliberate best-effort boundary: ANY opener failure degrades to the
            # warning below (which names the URL) — the server must still start.
            try:
                opened = _open_browser(url)
            except Exception:
                opened = False
            if not opened:
                user_output(f"could not open a browser — visit {url} yourself")
        _serve(app, sock)
    finally:
        sock.close()
