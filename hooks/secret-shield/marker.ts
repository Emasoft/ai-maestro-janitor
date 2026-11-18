// The vault marker, the one grammar of it (TRDD-DSXC9MP9 increment 1): [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>], the uuid naming the vault row that keeps the value.
// WHY it lives in the core: the live mod (known.ts) and the file scan (scripts/shield_scan, which imports it from here) must write and read the same marker. The mod cannot import from scripts/: a hooks module may import only files of its own folder tree, and the test assembly copies only hooks/secret-shield.
// Pure: no `$`, no I/O.

/** A version 4 uuid in lower case, the only form the vault writes (randomUUID). Not anchored, so it can sit inside a larger pattern. */
export const UUID_V4 = String.raw`[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}`

/** The vault marker as a pattern source: group 1 the kind, group 2 the uuid. */
export const SHIELD_MARKER = String.raw`\[REDACTED-BY-SECRET-SHIELD\. Type: ([A-Za-z0-9_-]+)\. ID: (${UUID_V4})\]`

/** The marker of the vault row `uuid`, for a value of kind `kind`. */
export const shieldMarker = (kind: string, uuid: string): string => `[REDACTED-BY-SECRET-SHIELD. Type: ${kind}. ID: ${uuid}]`
