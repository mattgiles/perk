// The pi-web-access fixture entry (materialized at dist/index.js): static pi-tui + typebox, and the
// lazy pi-ai/compat + pi-coding-agent imports its fetch paths take.
import * as piTui from "@earendil-works/pi-tui";
import * as typebox from "typebox";

export const statics = { "@earendil-works/pi-tui": piTui, typebox };
export const lazyCompat = () => import("@earendil-works/pi-ai/compat");
export const lazyHost = () => import("@earendil-works/pi-coding-agent");
