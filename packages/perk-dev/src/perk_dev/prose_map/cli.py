"""Click surface for validating and regenerating the living prose map."""

import difflib
import json
from pathlib import Path

import click

from perk.substrate.fs import atomic_write_text
from perk.substrate.git import repo_root
from perk.substrate.output import machine_output, user_output
from perk_dev.prose_map.catalog import RENDERED_PATH, ProseMapError, build
from perk_dev.prose_map.models import Finding


def _root() -> Path:
    root = repo_root(Path.cwd())
    if root is None:
        raise ProseMapError("not inside a git repository")
    return root


def _emit(
    *,
    as_json: bool,
    success: bool,
    findings: tuple[Finding, ...],
    changed: bool,
    path: Path,
) -> None:
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": success,
                    "error_type": None if success else "prose_map_invalid",
                    "changed": changed,
                    "rendered_path": str(path),
                    "findings": [
                        {"code": finding.code, "message": finding.message} for finding in findings
                    ],
                }
            )
        )
        return
    if findings:
        for finding in findings:
            click.echo(f"{finding.code}: {finding.message}", err=True)
    elif changed and success:
        user_output(f"updated prose map: {path}")
    elif changed:
        user_output(f"prose map is stale: {path}")
    else:
        user_output(f"prose map is valid and current: {path}")


@click.group("prose-map")
def prose_map() -> None:
    """Validate and render perk's living model-facing prose graph."""


@prose_map.command("check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report.")
@click.pass_context
def check(ctx: click.Context, *, as_json: bool) -> None:
    """Validate graph structure, coverage, selectors, relationships, and rendered freshness."""
    try:
        root = _root()
        result = build(root)
    except ProseMapError as exc:
        findings = (Finding(code="load-error", message=str(exc)),)
        _emit(
            as_json=as_json,
            success=False,
            findings=findings,
            changed=False,
            path=RENDERED_PATH,
        )
        ctx.exit(1)
        return
    rendered_path = root / RENDERED_PATH
    current = rendered_path.read_text(encoding="utf-8") if rendered_path.is_file() else ""
    changed = current != result.rendered
    findings = result.catalog.findings
    _emit(
        as_json=as_json,
        success=not findings and not changed,
        findings=findings,
        changed=changed,
        path=rendered_path,
    )
    if findings or changed:
        ctx.exit(1)


@prose_map.command("sync")
@click.option("--dry-run", is_flag=True, help="Show the generated diff without writing it.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report.")
@click.pass_context
def sync(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Validate, then atomically regenerate only the readable Markdown projection."""
    try:
        root = _root()
        result = build(root)
    except ProseMapError as exc:
        findings = (Finding(code="load-error", message=str(exc)),)
        _emit(
            as_json=as_json,
            success=False,
            findings=findings,
            changed=False,
            path=RENDERED_PATH,
        )
        ctx.exit(1)
        return
    rendered_path = root / RENDERED_PATH
    current = rendered_path.read_text(encoding="utf-8") if rendered_path.is_file() else ""
    changed = current != result.rendered
    if result.catalog.findings:
        _emit(
            as_json=as_json,
            success=False,
            findings=result.catalog.findings,
            changed=changed,
            path=rendered_path,
        )
        ctx.exit(1)
        return
    if dry_run:
        if changed and not as_json:
            click.echo(
                "".join(
                    difflib.unified_diff(
                        current.splitlines(keepends=True),
                        result.rendered.splitlines(keepends=True),
                        fromfile=str(rendered_path),
                        tofile=f"{rendered_path} (generated)",
                    )
                ),
                nl=False,
            )
        _emit(
            as_json=as_json,
            success=not changed,
            findings=(),
            changed=changed,
            path=rendered_path,
        )
        if changed:
            ctx.exit(1)
        return
    if changed:
        atomic_write_text(rendered_path, result.rendered)
    _emit(
        as_json=as_json,
        success=True,
        findings=(),
        changed=changed,
        path=rendered_path,
    )
