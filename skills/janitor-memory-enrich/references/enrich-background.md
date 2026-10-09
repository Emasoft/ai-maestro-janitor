# ENRICH — background and rationale

Reasoning moved out of `SKILL.md` to keep the skill short. Nothing here is a step; the
steps are all in the skill.

## Table of contents

- Why there is no `--op enrich`
- Why lint-backed candidates respect janitor#227

## Why there is no `--op enrich`

There is deliberately **no `--op enrich`** in the txn core. An enrich edit has the
identical shape to a repair — exactly ONE write at the page's own path, zero deletes —
and the write gate already proves the four things enrich needs (every `[^N]` lesson
survives, no frontmatter key is dropped, `ocd` is unchanged, `lmd` does not regress).
A second name for one guarantee would only drift.

## Why lint-backed candidates respect janitor#227

Sibling skills say "run the scheduler's predicate, NOT `memgrep lint`". In ENRICH the
candidates CLI *is* lint-backed, and that is the same rule, not an exception to it: #227 is
about the gate and the arbiter DISAGREEING. These defects **are** lint rules — the
thresholds, the phrase splitting and the duplicate normalization all live in Rust — so
deferring to lint is what makes gate and arbiter identical here. Counting keyphrases
yourself in Python would *create* the #227 disagreement, not avoid it.
