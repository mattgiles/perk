// Cooperative machine-local exclusion. No retries, reclamation, or cleanup on process death.
// Resource wrappers own paths and metadata; this module owns descriptor/token identity fencing.
import { randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  fsyncSync,
  lstatSync,
  openSync,
  readSync,
  type Stats,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute } from "node:path";

const OWNER_LIMIT = 16 * 1024;

export type ClaimFinish = {
  kind: "released" | "retained" | "ownership-error" | "io-error";
  path: string;
};
export interface ExclusiveFileClaim {
  readonly path: string;
  check(): "owned" | "ownership-error" | "io-error";
  /** First choice wins, locally idempotent. Retain closes resources but never removes metadata. */
  finish(disposition: "release" | "retain"): ClaimFinish;
}
export type ExclusiveFileAcquisition<Owner> =
  | { kind: "acquired"; claim: ExclusiveFileClaim }
  | { kind: "busy"; path: string; owner?: Owner }
  | { kind: "io-error"; path: string; residue: boolean };

/** Only deterministic filesystem fault tests substitute these operations. */
export interface ExclusiveFileFs {
  open: typeof openSync;
  close: typeof closeSync;
  fstat: (fd: number) => Stats;
  lstat: (path: string) => Stats;
  read: (fd: number, buffer: Buffer, offset: number, length: number, position: number) => number;
  write: (fd: number, data: string) => void;
  sync: (fd: number) => void;
  unlink: (path: string) => void;
}
export interface ClaimRecordCodec<Owner> {
  encode(token: string): unknown;
  /** Return a fresh diagnostic owner without the token; unknown records remain busy. */
  decode(raw: unknown): { token: string; owner: Owner } | null;
}
const realFs: ExclusiveFileFs = {
  open: openSync,
  close: closeSync,
  fstat: fstatSync,
  lstat: lstatSync,
  read: readSync,
  write: (fd, data) => writeFileSync(fd, data, "utf8"),
  sync: fsyncSync,
  unlink: unlinkSync,
};
function code(error: unknown): unknown {
  return typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
}
function sameFile(a: Stats, b: Stats): boolean {
  return a.isFile() && b.isFile() && a.dev === b.dev && a.ino === b.ino;
}
function readRecord<Owner>(fs: ExclusiveFileFs, fd: number, codec: ClaimRecordCodec<Owner>) {
  const size = fs.fstat(fd).size;
  if (size <= 0 || size > OWNER_LIMIT) return null;
  const bytes = Buffer.alloc(size);
  let read = 0;
  while (read < size) {
    const n = fs.read(fd, bytes, read, size - read, read);
    if (n === 0) return null;
    read += n;
  }
  try {
    return codec.decode(JSON.parse(bytes.toString("utf8")));
  } catch {
    return null;
  }
}
function incumbent<Owner>(
  fs: ExclusiveFileFs,
  path: string,
  codec: ClaimRecordCodec<Owner>,
): ExclusiveFileAcquisition<Owner> {
  let fd: number | undefined;
  try {
    const stat = fs.lstat(path);
    if (!stat.isFile() || stat.size > OWNER_LIMIT) return { kind: "busy", path };
    fd = fs.open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    if (!sameFile(stat, fs.fstat(fd))) return { kind: "busy", path };
    const record = readRecord(fs, fd, codec);
    return { kind: "busy", path, ...(record ? { owner: record.owner } : {}) };
  } catch (error) {
    // A disappearing incumbent doesn't invite a retry; ELOOP never follows a new symlink.
    if (code(error) === "ENOENT" || code(error) === "ELOOP") return { kind: "busy", path };
    return { kind: "io-error", path, residue: true };
  } finally {
    if (fd !== undefined) fs.close(fd);
  }
}

export function acquireExclusiveFileClaim<Owner>(
  path: string,
  codec: ClaimRecordCodec<Owner>,
  overrides: Partial<ExclusiveFileFs> = {},
): ExclusiveFileAcquisition<Owner> {
  if (!isAbsolute(path)) return { kind: "io-error", path, residue: false };
  const fs = { ...realFs, ...overrides };
  let fd: number;
  try {
    fd = fs.open(path, "wx", 0o600);
  } catch (error) {
    if (code(error) === "EEXIST") {
      try {
        return incumbent(fs, path, codec);
      } catch {
        return { kind: "io-error", path, residue: true };
      }
    }
    return { kind: "io-error", path, residue: false };
  }
  let stat: Stats | undefined;
  let token: string;
  try {
    stat = fs.fstat(fd);
    if (!stat.isFile()) throw new Error("not a regular file");
    token = randomUUID();
    const encoded = `${JSON.stringify(codec.encode(token))}\n`;
    fs.write(fd, encoded);
    fs.sync(fd);
  } catch {
    let residue = true;
    try {
      if (stat && sameFile(stat, fs.lstat(path))) {
        fs.unlink(path);
        residue = false;
      }
    } catch {
      /* Report residue; never remove an unidentified or successor file. */
    }
    try {
      fs.close(fd);
    } catch {
      residue = true;
    }
    return { kind: "io-error", path, residue };
  }
  const acquiredStat = stat;
  let finished: ClaimFinish | undefined;
  function check(): "owned" | "ownership-error" | "io-error" {
    if (finished) return "ownership-error";
    try {
      if (!sameFile(acquiredStat, fs.lstat(path)) || !sameFile(acquiredStat, fs.fstat(fd)))
        return "ownership-error";
      const reader = fs.open(
        path,
        constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
      );
      try {
        if (!sameFile(acquiredStat, fs.fstat(reader))) return "ownership-error";
        return readRecord(fs, reader, codec)?.token === token ? "owned" : "ownership-error";
      } finally {
        fs.close(reader);
      }
    } catch (error) {
      return code(error) === "ENOENT" ? "ownership-error" : "io-error";
    }
  }
  return {
    kind: "acquired",
    claim: {
      path,
      check,
      finish(disposition) {
        if (finished) return finished;
        let kind: ClaimFinish["kind"] = "retained";
        try {
          if (disposition === "release") {
            const ownership = check();
            if (ownership === "owned") {
              fs.unlink(path);
              kind = "released";
            } else kind = ownership;
          }
        } catch {
          kind = "io-error";
        } finally {
          try {
            fs.close(fd);
          } catch {
            kind = "io-error";
          }
        }
        finished = { kind, path };
        return finished;
      },
    },
  };
}
