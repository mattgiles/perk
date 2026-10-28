// The two comparison mechanisms' spawn wrappers (dev-only), as `sh -c` scripts run in front of the
// real command: `sh -c <WRAPPER> sh <arg> <command…>`. Each does its one thing to its own process,
// then `exec`s the command in place, so the pid it acted on IS the command's leader.

/**
 * A spawn journal entry: record `"<pid> <startTime>"` in `$1/registered` (the identity a fence
 * checks before it kills), then become the command. The stop set is that one process.
 */
export const JOURNAL_WRAPPER = `printf '%s %s\\n' "$$" "$(cut -d' ' -f22 /proc/$$/stat)" > "$1/registered"; shift; exec "$@"`;

/**
 * A cooperative cgroup fence: move this process into the fence `$1` (failing closed with 99 when
 * the move is refused), then become the command — every descendant inherits the cgroup.
 */
export const CGROUP_WRAPPER = `echo "$$" > "$1/cgroup.procs" || exit 99; shift; exec "$@"`;
