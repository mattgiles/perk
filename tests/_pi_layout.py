"""A fake global-npm Pi install for tests that run the REAL host probe (contracts.md §8.76(c)).

The probe family-checks a ``pi`` answering the adopted version: its realpath must sit inside an
installed ``@earendil-works/pi-coding-agent`` package whose companions resolve (Node's
``node_modules`` walk from the entry) at the adopted version. A bare ``#!/bin/sh`` stub on
``PATH`` is therefore unverifiable at that version; this builder lays out what ``npm install -g``
writes instead. Leading underscore so pytest does not collect this module.
"""

import json
from pathlib import Path

from perk.substrate.pi_host import PI_ADOPTED_VERSION, PI_COMPANION_PACKAGES, PI_NPM_SPEC

CODEMODE = "@earendil-works/pi-codemode"
MCP = "@earendil-works/pi-mcp"
# The broken layout's offenders, as `admit_pi_companions` lists them.
INCIDENT_DETAIL = f"{CODEMODE} does not resolve, {MCP} resolves to 1.4.0"


def _write_manifest(directory: Path, name: str, version: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "package.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


def install_fake_pi(prefix: Path, *, body: str | None = None, broken: bool = False) -> Path:
    """Lay out a global npm prefix with the Pi CLI installed; return the ``<prefix>/bin/pi`` link.

    The CLI entry (``dist/bundle/cli.js``) is a shell script running ``body`` (default: answer the
    adopted version). ``broken`` models the incident host: five companions at the global root,
    ``pi-codemode`` a dangling symlink, ``pi-mcp@1.4.0`` nested under the Pi package only.
    """
    global_root = prefix / "lib" / "node_modules"
    package = global_root / PI_NPM_SPEC
    _write_manifest(package, PI_NPM_SPEC, PI_ADOPTED_VERSION)
    bundle = package / "dist" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    cli = bundle / "cli.js"
    script = body if body is not None else f"echo {PI_ADOPTED_VERSION}"
    cli.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    cli.chmod(0o755)
    bin_dir = prefix / "bin"
    bin_dir.mkdir(exist_ok=True)
    link = bin_dir / "pi"
    link.symlink_to(Path("../lib/node_modules") / PI_NPM_SPEC / "dist/bundle/cli.js")
    for name in PI_COMPANION_PACKAGES:
        if broken and name == CODEMODE:
            (global_root / name).symlink_to(prefix / "gone" / "pi-codemode")
        elif broken and name == MCP:
            _write_manifest(package / "node_modules" / name, name, "1.4.0")
        else:
            _write_manifest(global_root / name, name, PI_ADOPTED_VERSION)
    return link
