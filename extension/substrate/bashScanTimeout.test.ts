// The bash scan-timeout guard's pure policy: the classifier matrix (incl. the accepted
// over-matches), the terminal-status parse, the note text and the constant pin. The Pi hooks are
// tested beside their adapter in pi/v1/bashScanTimeout.test.ts. See bashScanTimeout.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  classifyScanCommand,
  expiredAfterSeconds,
  SCAN_TIMEOUT_SECONDS,
  scanTimeoutNote,
} from "./bashScanTimeout.ts";

// --- the classifier matrix --------------------------------------------------------------------

const RECURSIVE_GREPS = [
  `grep -rn "foo" .`,
  // a quoted `|` must not split the segment
  `grep -rniE 'a|b' src/`,
  `grep -Rl foo .`,
  `grep -nr foo .`,
  // permuted flag position
  `grep -n foo -r .`,
  `grep -rnA3 foo .`,
  `grep --recursive foo .`,
  `grep --dereference-recursive foo .`,
  `grep -d recurse foo .`,
  `grep --directories=recurse foo .`,
  `egrep -r foo .`,
  `fgrep -R foo .`,
  `rgrep foo .`,
  // chained
  `cd /repo && grep -rn foo . | grep -v test`,
  // newline-separated
  "cd /repo\ngrep -rn foo .",
  // wrapper prefixes
  `LC_ALL=C grep -rn foo .`,
  `env LC_ALL=C grep -rn foo .`,
  `nice -n 5 grep -rn foo .`,
  `time grep -rn foo .`,
  `nohup grep -rn foo .`,
  // nested shells + substitution + alias bypass + path-qualified
  `sh -c 'grep -rn foo .'`,
  `bash -lc "grep -rn foo ."`,
  `echo $(grep -rl foo .)`,
  `\\grep -rn foo .`,
  `/usr/bin/grep -rn foo .`,
  `grep -rn foo . 2>/dev/null | head`,
  // the recursion flag is searched over the grep's FULL tail: a permuted `-r` after a quoted
  // pattern that itself carries a command word (+ `-maxdepth`) is still a recursive grep
  `grep -n "find . -maxdepth 1" -r .`,
];

const UNBOUNDED_FINDS = [
  `find . -name '*.py'`,
  `find /repo -type f -mtime -3`,
  `cd x && find . -name x | head`,
  // a `-not -path` filter still walks the excluded tree
  `find . -name '*.ts' -not -path '*/node_modules/*'`,
  `time find . -type f`,
  // a LATER bounded find inside a quoted nested shell must not exempt an EARLIER unbounded one
  // (the `;` is quoted, so both stay in one top-level segment)
  `sh -c 'find . -type f; find . -maxdepth 1'`,
  `sh -c 'find . -maxdepth 1; find . -type f'`,
  `bash -c "find . -maxdepth 1 && find . -name x"`,
  // a `-maxdepth` after a quoted sequencing operator belongs to the NEXT command
  `sh -c 'find . -type f; echo -maxdepth'`,
  `sh -c 'find . -type f | grep -maxdepth'`,
];

const NOT_SCANS = [
  `grep -n foo file.py`,
  `grep -niE 'a|b' file`,
  `grep -n --color=never foo f`,
  `grep -n --exclude-dir=node_modules foo f`,
  // the `-r` belongs to the NEXT segment — the reason segments are kept
  `grep -n foo f | sort -r`,
  // a quote-adjacent dash is not a flag position
  `grep -n "-r" file`,
  `grep -n 'grep -r' file`,
  `rg -n 'grep -rn' src/`,
  `rg -rn foo`,
  `ast-grep run --pattern 'x' .`,
  `find . -maxdepth 2 -name x`,
  `find src -name x -maxdepth 1`,
  `sh -c 'find . -maxdepth 1 -type f'`,
  `sh -c 'find . -maxdepth 1; find . -maxdepth 2'`,
  `fd foo`,
  `ls -R`,
  `cat docs/find.md`,
  `ls findings/`,
  ``,
];

// The TOLERATED false positives, pinned as accepted: each is a fast command that receives a
// harmless 30s cap. A future "fix" that turns any of these `null` must be a deliberate change.
const ACCEPTED_OVER_MATCHES = [
  `echo grep -r`,
  `git grep -rn foo`,
  `rg -n 'grep -rn foo' src/`,
  `grep -n "x -r y" f`,
  // a quoted sequencing operator BEFORE `-maxdepth` ends the find's exemption window early
  `find . -name 'a;b' -maxdepth 1`,
];

test("classifyScanCommand: recursive greps", () => {
  for (const command of RECURSIVE_GREPS) {
    assert.equal(classifyScanCommand(command), "recursive-grep", command);
  }
});

test("classifyScanCommand: unbounded finds", () => {
  for (const command of UNBOUNDED_FINDS) {
    assert.equal(classifyScanCommand(command), "unbounded-find", command);
  }
});

test("classifyScanCommand: non-scans are null", () => {
  for (const command of NOT_SCANS) {
    assert.equal(classifyScanCommand(command), null, command);
  }
});

test("classifyScanCommand: accepted over-matches stay capped", () => {
  for (const command of ACCEPTED_OVER_MATCHES) {
    assert.notEqual(classifyScanCommand(command), null, command);
  }
});

test("classifyScanCommand: a pipeline carrying both rules classifies (first segment wins)", () => {
  assert.notEqual(classifyScanCommand(`find . -name '*.py' | xargs -0 grep -rn foo`), null);
});

// --- the constant + the note text -------------------------------------------------------------

test("SCAN_TIMEOUT_SECONDS is 30 (mirrored by the managed AGENTS bullet; Python parity test)", () => {
  assert.equal(SCAN_TIMEOUT_SECONDS, 30);
});

test("scanTimeoutNote names the kind and the seconds", () => {
  assert.ok(
    scanTimeoutNote("recursive-grep", "30").startsWith(
      "perk: this recursive grep hit the 30s timeout.",
    ),
  );
  assert.ok(
    scanTimeoutNote("unbounded-find", "45").startsWith(
      "perk: this unbounded find hit the 45s timeout.",
    ),
  );
});

// --- the terminal-status parse ----------------------------------------------------------------

test("expiredAfterSeconds: only Pi's TERMINAL timeout status counts", () => {
  assert.equal(expiredAfterSeconds("partial output\n\nCommand timed out after 30 seconds"), "30");
  // a status-only text (empty partial output)
  assert.equal(expiredAfterSeconds("Command timed out after 600 seconds"), "600");
  assert.equal(expiredAfterSeconds("nothing\n\nCommand exited with code 1"), null);
  // the literal mid-output followed by a different terminal status is NOT a timeout
  assert.equal(
    expiredAfterSeconds("Command timed out after 30 seconds\nmore\n\nCommand exited with code 1"),
    null,
  );
  assert.equal(expiredAfterSeconds(""), null);
});
