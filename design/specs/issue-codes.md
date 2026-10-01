---
spec: issue-codes
spec-version: 1.0.0
status: normative
created: 2026-10-01T19:52:33+0200
updated: 2026-10-01T19:52:33+0200
maintainer: ai-maestro-janitor
project-id: ai-maestro-janitor
requested-by: Emasoft (owner directive 2026-10-01, TRDD-DSN035UN)
governs:
  - design/specs/issue-codes.toml
  - scripts/memgrep/src/rules_gen.rs
  - scripts/lib/issue_codes_gen.py
  - docs/ISSUE-CODES.md
implementations:
  - "scripts/lib/issue_catalog.py: the janitor runtime-fault catalog (carried over unchanged into the TOML)"
  - "scripts/memgrep/src/memory.rs: the memgrep lint (page defects), registry-driven after card C20"
  - "scripts/issue_codes_gen.py: the generator (card C10)"
---

# The issue-code SPEC

## Purpose and single source of truth

Every issue the janitor or memgrep can report has exactly one code, defined exactly once, in
`design/specs/issue-codes.toml`. The TOML is DATA. This document is the PROSE: grammar, scales,
fix classes, suppression and configuration. On disagreement this document arbiters the rules and
the TOML arbiters the facts (which codes exist and their attributes).

- The TOML is never edited to match generated output. The generator owns every derived file
  listed under `governs:` (the Rust registry, the Python registry, the docs page) and rewrites them.
- A drift test fails when any derived file differs from what the generator would write
  (`issue_codes_gen.py --check` exits non-zero).
- A consumer that needs a code attribute reads the generated registry; it never keeps its own copy.

## Code grammar, immutability, retirement

- A code matches `^[A-Z][A-Z0-9]{1,9}-\d{3}$`: a family prefix, a hyphen, three digits.
- Every code also has a kebab-case `name`, unique across the file. Selection accepts a code, a
  family prefix or a name.
- Codes are immutable once shipped: never renumbered, never reused, never re-pointed at a different
  condition. Numbers are assigned per family in source emission order and then frozen.
- To retire a code, stop emitting it, remove its `[[issue]]` table and add a `[[retired]]` table
  with the code and the reason. A retired code is never reused.
- Janitor catalog codes were carried over unchanged, including their `kind` (the ticket routing key)
  and `what` fields. The catalog spells severity in lowercase; the TOML spells it uppercase and the
  generator lowercases it for the Python catalog. The set also contains CRITICAL, a janitor-only level.

Fields per `[[issue]]` table: `code`, `name`, `family`, `severity`, `fix` (safe, unsafe or none),
`gate_floor` (bool), `emitter`, `summary`, `why`, `fix_text`; janitor catalog codes add `kind` and `what`.
The `emitter` is `memgrep` or `janitor:<scanner or detector>`.

## Families

| Family | Covers | Emitter |
|---|---|---|
| WMPAGE | page frontmatter and shape, publish-globally | memgrep |
| WMATOM | atoms and superseded atoms | memgrep |
| WMLESS | lessons and footnotes | memgrep |
| WMLINK | links | memgrep |
| WMENC | encoding | memgrep |
| WMSUP | suppression hygiene (unused and blanket noqa) | memgrep |
| HOOK | hook timeouts: harness-reported, near-budget, internal limit | janitor |
| MGPERF | memgrep performance budgets and index rebuilds | memgrep |
| HOST | host load and runaway processes | janitor |
| AICTX BRPROT CRED DAEMON DEP GHCFG MCPSEC MEMCORP MEMGREP PKGPOL SELFINT STATE WFSEC | pre-existing janitor runtime-fault families | janitor |

A new family prefix must not collide with an existing one; the generator rejects a collision.

## Severity scales and mapping

| memgrep | janitor | Meaning |
|---|---|---|
| ERROR | HIGH | must be fixed; may block a write |
| WARN | MEDIUM | should be fixed |
| INFO | LOW | advisory |

ERROR is equivalent to HIGH, WARN to MEDIUM, INFO to LOW. A memgrep code uses the left scale, a janitor
code the right one. Decision D1: `atom-no-ocd` and `atom-no-lmd` are INFO with fix none, because atom dates are
optional and inherited from the page.

## Fix classes

- safe: the fixer is lossless and deterministic. It runs wherever plain `memgrep lint` runs.
- unsafe: a fix that may lose or change meaning. It runs only with `--unsafe-fixes` and only from the repair chore.
- none: no automatic fix; a human or an agent decides.

**SAFE requires a lossless proof asserted in the fixer's unit test** (for example: the original
text is recoverable by unquoting, the keyword set is unchanged, the block multiset is byte-equal,
only the comment was removed), plus an oracle assertion that `lint_page_text` no longer reports the code.

A code with `gate_floor = true` is refused by the write gate when it is an ERROR; the floor and
grandfathered lists in the Rust source are derived from this field.

### The default-fix ruling (verbatim)

From `scripts/detectors/wikimem-syntax.py` lines 98-104, owner ruling 2026-08-29:

"executing a memgrep command/edit on a malformed wikimem page containing errors will corrupt
the file and lose data. This is why fixing both BEFORE and AFTER executing the wikimem page
edit is MANDATORY, NO EXCEPTIONS. --no-fix can only be used for debug or diagnostic use
cases."

So plain `memgrep lint` keeps fixing by default. This is the one deliberate departure from ruff, whose
fixing is opt-in.

## Inline suppression

All forms are HTML comments, which lint already masks.

- `<!-- noqa: WMATOM-010, WMLESS-001 -->` at the end of a line suppresses those codes on that line.
- `<!-- memgrep: noqa: WMLESS-001 -->` on its own line suppresses them for the whole page. Frontmatter
  `lint-ignore: [WMLINK-001]` does the same.
- A bare `<!-- noqa -->` with no codes is reported as WMSUP-002.
- An unmatched suppression is reported as WMSUP-001; its fix (removing it) is SAFE.
- Recall output strips noqa comments.

## Configuration

`.janitor.toml`, taken from the nearest ancestor of the linted path. It extends the file that
`scripts/lib/suppression.py` already reads for `[[suppress]]`.

```toml
[lint]
select = ["WM", "HOOK", "MGPERF"]   # code | family | prefix | name
extend-select = []
ignore = []
fixable = ["ALL"]
unfixable = []
unsafe-fixes = false
[lint.per-file-ignores]
"*/archive/*.md" = ["WMLESS"]
[perf]
recall-budget-ms = 3000
lint-budget-ms = 10000
```

Precedence is CLI over config over defaults. On the janitor side, `suppression.is_suppressed(code, path)`
applies the same rules to ledger and drift output.

## CLI flags

- Selection: `--select`, `--extend-select`, `--ignore`.
- Fixing: `--fix` (default on), `--no-fix` (debug only), `--unsafe-fixes`, `--fixable`, `--unfixable`, `--show-fixes`, `--diff`.
- Reporting: `--statistics`, `--exit-zero`, `--output-format text|json`.
- Config: `--config`, `--isolated`.

## Ruff correspondence

| ruff | memgrep and janitor | Difference |
|---|---|---|
| `select` / `extend-select` | `[lint] select` / `extend-select`, `--select` / `--extend-select` | same semantics; entries are code, family, prefix or name |
| `ignore` | `[lint] ignore`, `--ignore` | same |
| `fixable` / `unfixable` | `[lint] fixable` / `unfixable`, `--fixable` / `--unfixable` | same |
| `unsafe-fixes` | `[lint] unsafe-fixes`, `--unsafe-fixes` | same; unsafe fixes also limited to the repair chore |
| `fix` (opt-in) | `--fix` default ON, `--no-fix` | owner ruling above |
| `per-file-ignores` | `[lint.per-file-ignores]` | glob keys, same |
| `# noqa: CODE` | `<!-- noqa: CODE -->` | HTML comment, since pages are Markdown |
| `RUF100` unused-noqa | WMSUP-001 | fix is SAFE |
| blanket noqa (`PGH004`) | WMSUP-002 | reported, not fixed |
| `--statistics`, `--exit-zero`, `--output-format`, `--config`, `--isolated` | same flags | same |
