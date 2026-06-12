// Mint perk run ids in the TS plane (contracts.md §8.2 mint doctrine).
// Warm sessions with no identity (decideClaim's `none` path) mint their own ULID;
// cold launches still mint in Python (perk/run_id.py) and hand off via PERK_RUN_ID.
//
// Hand-rolled spec-conformant ULID (no npm dependency): a 48-bit `Date.now()` timestamp
// + 80 bits of `randomBytes(10)`, Crockford base32, 26 chars (10 time + 16 randomness).
// Per-process monotonicity is NOT required — one mint per session.

import { randomBytes } from "node:crypto";

/** Crockford base32 alphabet (no I/L/O/U) — the ULID character set. */
export const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** Mint a spec-conformant ULID: 10 time chars (48-bit ms) + 16 randomness chars (80 bits). */
export function mintRunId(): string {
  // Time component: most-significant-first base32 of Date.now() (2^48 ms ≈ year 10889).
  let ms = Date.now();
  const time = new Array<string>(10);
  for (let i = 9; i >= 0; i--) {
    time[i] = CROCKFORD[ms % 32] as string;
    ms = Math.floor(ms / 32);
  }
  // Randomness component: 10 bytes → 16 five-bit chunks, standard bit-walk.
  const bytes = randomBytes(10);
  let rand = "";
  let acc = 0;
  let bits = 0;
  for (const byte of bytes) {
    acc = (acc << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      rand += CROCKFORD[(acc >> bits) & 31];
      acc &= (1 << bits) - 1;
    }
  }
  return time.join("") + rand;
}

/** Decode the first 10 chars of a ULID to epoch milliseconds (test aid). */
export function decodeTime(runId: string): number {
  let ms = 0;
  for (const ch of runId.slice(0, 10)) {
    const value = CROCKFORD.indexOf(ch);
    if (value < 0) throw new Error(`invalid ULID time character: ${ch}`);
    ms = ms * 32 + value;
  }
  return ms;
}
