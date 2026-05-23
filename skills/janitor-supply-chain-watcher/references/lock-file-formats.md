# Lock file formats — per-format parser notes

Each parser turns one lock-file path into a stream of `(ecosystem, package, version)` triples. Ecosystem names match the GHSA + OSV conventions (`npm`, `PyPI`, `crates.io`). Every parser must read the file fully into memory and emit deterministic output — no network access during parsing.

## Table of contents

- [Parsers per ecosystem](#parsers-per-ecosystem)
- [Cross-format concerns](#cross-format-concerns)
- [Parser failure mode](#parser-failure-mode)

## Parsers per ecosystem

### package-lock.json (npm v1 / v2 / v3)

Three on-disk shapes coexist. Detect via the top-level `lockfileVersion` field.

- **v1** (npm < 7): `dependencies: { "<name>": { "version": "<x>", "dependencies": { ... } } }`. Walk the tree recursively. Skip entries with no `version` (those are bundled).
- **v2** (npm 7+ default): contains BOTH `dependencies` (legacy) AND `packages`. Parse only `packages`. The `packages` key is a flat map keyed by install path; the root project is `""`. Iterate each non-root entry; the key looks like `"node_modules/<name>"` or `"node_modules/<parent>/node_modules/<child>"`. Strip everything up to the last `node_modules/` to get `<name>`. Take `version` from the value object. Skip entries where `link: true` or where there is no `version`.
- **v3** (npm 7+, no legacy mirror): identical to v2 but without the `dependencies` block. Parse `packages` identically.

The `name` field on a scoped package keeps its `@scope/` prefix. Pass it through unchanged.

### pnpm-lock.yaml

YAML map with a `packages:` top-level key. Each entry is keyed by `/<name>/<version>` for the older format or `/<name>@<version>` for the newer format. Split on the LAST `/` (older) or LAST `@` (newer) so scoped names like `@scope/foo` parse correctly. The version is exactly the suffix; the name is everything before it (preserve the leading `/`-stripped `@scope/`).

The `importers:` block lists direct deps of each workspace project — ignore it. The `packages:` block holds direct + transitive together.

### yarn.lock (classic v1 and berry v2/v3)

- **Classic v1**: text format with `<name>@<spec>:` headers followed by indented `version "<x>"` lines. Multiple comma-separated `<name>@<spec>` aliases can share the same block; emit one triple per RESOLVED `(name, version)` pair (split header on `,`, then extract name from each alias by stripping the LAST `@<spec>` suffix; the `version` line in the body is the authoritative installed version, same for every alias).
- **Berry v2/v3**: YAML format with `<name>@<protocol>:` headers, `version: <x>` inside. Parse as YAML, iterate top-level keys (skip `__metadata`), extract `version` from each value.

Both forms can use the `npm:` protocol prefix (e.g. `foo@npm:1.2.3`); strip the prefix before emitting the name.

### requirements.txt (pip)

Line-oriented; one dep per line. Ignore blank lines and lines starting with `#`. Each useful line is `<name><spec>` where `<spec>` is typically `==<version>`. Strict `==`-pinned lines yield a direct `(PyPI, <name>, <version>)`. For any other operator (`>=`, `~=`, `>`, `<`), the line gives a constraint, NOT an installed version — record the constraint but do not emit a triple unless a sibling `<name>==<x>` line resolves it. Skip `-r <other.txt>`, `-c <file>`, `-e <git+url>`, and `--hash=` continuations.

### uv.lock

TOML format. Top-level `[[package]]` blocks each have a `name` and a `version` key. Emit one triple per block as `(PyPI, <name>, <version>)`. Skip any block with `source.virtual = true` or `source.editable = true` (those are local, not resolvable advisories).

### poetry.lock

TOML format. Same shape as uv.lock: `[[package]]` blocks with `name` and `version`. Emit one triple per block.

### Cargo.lock

TOML format. `[[package]]` blocks with `name`, `version`, and (optionally) `source`. Emit `(crates.io, <name>, <version>)` only when `source` is missing or starts with `"registry+https://github.com/rust-lang/crates.io-index"`. Skip `path` and `git` sources — they are local or forked and cannot match a published advisory.

## Cross-format concerns

### Deduplication across files

After parsing every lock file, deduplicate the combined stream by `(ecosystem, name, version)`. A monorepo can ship both `package-lock.json` and `pnpm-lock.yaml` referencing the same npm package at the same version — emit it once.

### Ecosystem label mapping

| Lock file | Ecosystem label (GHSA / OSV) |
|---|---|
| `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock` | `npm` |
| `requirements.txt`, `uv.lock`, `poetry.lock` | `PyPI` |
| `Cargo.lock` | `crates.io` |

GHSA uses `NPM` / `PIP` / `RUST` enum values for `ecosystem:` in the GraphQL query — see [advisory-sources.md](advisory-sources.md). OSV.dev accepts the plain-text labels above.

## Parser failure mode

Any unrecognized lock-file shape (`lockfileVersion` outside 1/2/3, missing `packages:`, non-TOML content where TOML expected) → emit one diagnostic `[FAILED] cannot parse <path>: <reason>` and exit 4. Do NOT skip silently — a corrupted lock file means the audit cannot see the deps it should be checking.
