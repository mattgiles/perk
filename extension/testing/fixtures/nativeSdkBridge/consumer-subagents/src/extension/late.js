// A module no scenario loads before the bridge statuses are dropped: its census import proves the
// hooks are process-owned, not owned by any status object.
import * as piAgentCore from "@earendil-works/pi-agent-core";

export const origin = piAgentCore.origin;
export const Marker = piAgentCore.Marker;
