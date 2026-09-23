"""Cross-plane pin: the managed native consumers are one list in two planes (contracts §8.73).

The extension's `NATIVE_SDK_CONSUMERS` (`extension/substrate/nativeSdkBridge.ts`) names the
consumer roots the host-SDK bridge verifies; the Python plane's `NATIVE_CONSUMER_PACKAGES`
(`perk.convergence.init.settings`) names the packages `perk init` keeps perk's entry ahead of.
Reading the TS literal here is the drift guard (the `SCAN_TIMEOUT_SECONDS` precedent).
"""

import re
from pathlib import Path

from perk.convergence.init.settings import NATIVE_CONSUMER_PACKAGES


def test_native_consumer_lists_match_across_planes():
    repo_root = Path(__file__).resolve().parents[1]
    ts_source = (repo_root / "extension" / "substrate" / "nativeSdkBridge.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"^export const NATIVE_SDK_CONSUMERS = \[(?P<body>[^\]]*)\] as const;$",
        ts_source,
        re.MULTILINE,
    )
    assert match is not None, "NATIVE_SDK_CONSUMERS literal not found in nativeSdkBridge.ts"
    ts_names = tuple(re.findall(r'"([^"]+)"', match.group("body")))
    assert ts_names == NATIVE_CONSUMER_PACKAGES
