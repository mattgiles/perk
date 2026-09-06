// Transient physical-session identity only; persisted pi_session_id retains its basename contract.

export interface NativeSessionKey {
  sessionId: string;
  sessionFile: string | null;
}

export interface NativeSessionSource {
  sessionManager: {
    getSessionId(): string;
    getSessionFile(): string | null | undefined;
  };
}

export type NativeSessionKeyRead =
  | { status: "known"; key: NativeSessionKey }
  | { status: "unreadable" };

/** No basename, cwd, Perk run id or invented token may stand in for an unreadable SDK key. */
export function readNativeSessionKey(source: NativeSessionSource): NativeSessionKeyRead {
  try {
    const sessionId = source.sessionManager.getSessionId();
    const sessionFile = source.sessionManager.getSessionFile();
    if (typeof sessionId !== "string" || sessionId.length === 0) return { status: "unreadable" };
    if (sessionFile !== undefined && sessionFile !== null && typeof sessionFile !== "string") {
      return { status: "unreadable" };
    }
    return { status: "known", key: { sessionId, sessionFile: sessionFile ?? null } };
  } catch {
    return { status: "unreadable" };
  }
}

export function nativeSessionKeysEqual(a: NativeSessionKey, b: NativeSessionKey): boolean {
  return a.sessionId === b.sessionId && a.sessionFile === b.sessionFile;
}
