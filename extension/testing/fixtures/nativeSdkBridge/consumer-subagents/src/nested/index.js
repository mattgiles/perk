// A nested dependency (materialized under src/nested/node_modules/) imports `typebox` from OUTSIDE
// the consumer root's own graph — the bridge must leave it on ordinary resolution.
export { origin as nestedOrigin } from "nested-dep";
