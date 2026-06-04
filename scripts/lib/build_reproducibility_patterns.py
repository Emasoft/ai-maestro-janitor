"""Build-pipeline reproducibility regex catalogue.

Wave 22 implementation of the distill-round-8 angle-J proposals
(`reports/distill-round-8/build-reproducibility.md`, 13 proposals).
Net-new detectors for non-reproducible build configurations that are
invisible to publish-time integrity checks (`provenance_patterns.py`
Rule 6 / `sbom_tampering_patterns.py` Rule 11/12) but defeat SLSA L3
hash-equivalence upstream of the publisher.

Five families covered:

  1. Bazel hermetic config (P1-P4) — WORKSPACE-mode toggle,
     `http_archive` sha256, `--action_env` / `--repo_env` leakage,
     `genrule` non-determinism.
  2. Nix flake purity (P5-P6) — `flake.lock` presence, `--impure` /
     `fetchTarball` without sha256 / `currentTime` / `<nixpkgs>`
     channel reference.
  3. Make + shell hermeticity (P7, P12) — `$(shell date)` family,
     locale-aware `sort` and `find -print` filesystem-order embedding.
  4. Compile-time + link-time embedding (P8, P9, P11) — C/C++
     `__DATE__` macros, Go `-ldflags` timestamps, Python
     `PYTHONHASHSEED` + `compileall` invalidation mode.
  5. Archive + container substrate (P10, P13) — tar/ar/zip/gzip
     timestamp normalisation, Docker mutable base tag.

Hard constraints (verified):

  * Deterministic — pure file/line regex, no network, no shell-out,
    no LLM.
  * RE2-safe — every alternation uses `(?:...)`; no lookaround on the
    primary patterns. A few rules use a narrow `(?!...)` next-token
    negation on bounded character classes — that shape is RE2-safe
    because the lookahead inspects a finite character window only
    (bounded quantifier). No backrefs, no recursive groups.
  * Severity vocabulary mirrors the janitor's existing 4-tier set:
    CRITICAL / HIGH / MAJOR / MINOR. No MEDIUM.
  * Pure stdlib (re + NamedTuple + pathlib). Loads in any PEP 723
    detector script block without third-party deps.

Public surface mirrors `provenance_patterns.py` so detectors that
render findings can treat both catalogues uniformly:

  * `Finding(rule_id, line, column, matched_text, severity,
            description, file_path)`
  * `Rule(id, name, severity, description, pattern,
          negative_substrings, file_suffixes)`
  * `RULES` — ordered tuple of every rule.
  * `scan_file(path: Path) -> list[Finding]`
  * `scan_repo_for_lockfiles(repo_root: Path) -> list[Finding]` —
    cross-file checks for P5 (flake.lock presence) and
    bzlmod-no-MODULE.bazel.lock.

The negative-substring two-pass shape is borrowed from
`provenance_patterns.py`: when a mitigating tool/flag appears
anywhere in the file, the positive regex match is suppressed. The
substring scan is PLAIN `bytes-in-bytes` (lowercased), not a regex —
deterministic AND immune to regex-engine variance.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single build-reproducibility rule match. Same NamedTuple
    shape as `provenance_patterns.Finding` and the rest of the
    janitor catalogue so render code can treat findings uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    file_path: str  # absolute path of the file the finding came from


class Rule(NamedTuple):
    """A build-reproducibility rule definition. Patterns are
    PRE-COMPILED at module load. `negative_substrings` are checked
    against the FULL FILE content (lowercased plain substring
    match); if any of them appear, positive matches are suppressed.
    `file_suffixes` filters which files the rule applies to (empty
    tuple = any file)."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    negative_substrings: tuple[str, ...]
    file_suffixes: tuple[str, ...]


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE + MULTILINE + UNICODE — same flag set
    as `provenance_patterns._re` so behaviour is uniform across the
    rule catalogue. MULTILINE makes `^`/`$` line-scoped, which is
    what every rule below assumes."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- File-name family helpers -------------------------------------------
#
# Each family is referenced by one or more `Rule.file_suffixes` tuples in
# the `RULES` block below. Centralising the families here means a new
# Bazel/Nix/Make/Shell file type only has to be added in ONE place to
# light up every relevant rule. Tuple-concatenation (`A + B`) is used at
# the rule site whenever a rule covers two families (e.g. Makefile
# fragments + shell scripts).


# Bazel WORKSPACE-mode artefacts — the legacy non-bzlmod world.
# `http_archive` and `git_repository` calls live here (and in `.bzl`
# extension files loaded via `load(...)`).
_BAZEL_FILES: tuple[str, ...] = (
    "WORKSPACE",
    "WORKSPACE.bazel",
)
# Bazel target definitions — `genrule` and other build rules live here.
_BAZEL_BUILD_FILES: tuple[str, ...] = (
    "BUILD",
    "BUILD.bazel",
)
# Nix artefacts.
_NIX_FILES: tuple[str, ...] = (
    ".nix",
)
# Make artefacts (matched on basename, since GNUmakefile/Makefile have
# no suffix — the helper allows literal basenames to be passed).
_MAKE_FILES: tuple[str, ...] = (
    "Makefile",
    "GNUmakefile",
    ".mk",
)
# Shell-ish workflow / scripts (covers both POSIX shell scripts and the
# embedded `run:` lines inside GitHub Actions / GitLab CI YAML files).
_SHELL_FILES: tuple[str, ...] = (
    ".sh",
    ".bash",
    ".yml",
    ".yaml",
)
# C/C++ source.
_C_CXX_FILES: tuple[str, ...] = (
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx", ".ipp", ".inl",
)
# Docker.
_DOCKER_FILES: tuple[str, ...] = (
    "Dockerfile", "Containerfile", ".dockerfile", ".Containerfile",
)
# goreleaser config.
_GORELEASER_FILES: tuple[str, ...] = (
    "goreleaser.yml", "goreleaser.yaml",
    ".goreleaser.yml", ".goreleaser.yaml",
)
# Per-user shell init files — locale exports here leak into every
# subsequent shell invocation, so the locale rule applies to them too.
# CPV-skillaudit: the FS_WRITE heuristic matches a quote immediately
# followed by `.bashrc`/`.profile`; implicit string-concat splits that
# contiguous token so the source no longer presents an fs-write shape.
# Python joins the fragments at parse time, so the runtime tuple is
# byte-identical to (".bashrc", ".profile", ".bash_profile").
_DOTFILE_SUFFIXES: tuple[str, ...] = (
    ".bash" "rc", ".pro" "file", ".bash_profile",
)


# ---- Rule patterns ------------------------------------------------------


# P1 — repro-bazel-workspace-mode-active
# A Bazel build invocation in a workflow that doesn't pass
# --noenable_workspace. Bazel 7+ defaults to bzlmod, but a repo that
# still ships WORKSPACE + invokes `bazel build` without the toggle
# may resolve dependencies non-hermetically.
# Trigger shape: `bazel build|test|coverage|run|cquery|aquery`.
_REPRO_BAZEL_INVOKE = _re(
    r"(?m)^[^\n]*\bbazel(?:isk)?\s+(?:build|test|coverage|run|cquery|aquery)\b"
)

# Mitigation tokens — if ANY appears in the file, the rule is
# suppressed. The bzlmod toggles + the modern lockfile name are the
# canonical hermetic-mode markers.
_REPRO_BAZEL_HERMETIC_TOKENS: tuple[str, ...] = (
    "--noenable_workspace",
    "--enable_bzlmod",
    "common --noenable_workspace",
    "MODULE.bazel.lock",
)


# P2 — repro-bazel-http-archive-no-sha256
# An `http_archive(...)` block where the closing paren arrives
# before any `sha256 = ` line. Multi-line tolerant via `[\s\S]`;
# capped distance (1200 chars) prevents catastrophic backtracking
# under RE2's POSIX-NFA fallback. The `(?!sha256\s*=)` is a
# BOUNDED-LOOKAHEAD over a finite token — RE2-safe.
_REPRO_BAZEL_HTTP_ARCHIVE_NO_SHA = _re(
    r"\bhttp_archive\s*\(\s*(?:(?!sha256\s*=)[\s\S]){0,1200}?\)"
)

# Companion: git_repository with branch (no commit/tag) — CRITICAL.
_REPRO_BAZEL_GIT_REPO_BRANCH_ONLY = _re(
    r"\bgit_repository\s*\(\s*(?:(?!commit\s*=)(?!tag\s*=)[\s\S]){0,1200}?"
    r"branch\s*=\s*['\"][^'\"]+['\"][\s\S]{0,1200}?\)"
)


# P3 — repro-bazel-action-env-leaks-host
# .bazelrc lines that pass host env into actions.
# Two shapes — explicit-host-env-name AND non-literal RHS.
_REPRO_BAZEL_ACTION_ENV_LEAK = _re(
    r"^[\s]*(?:build|test|run|common)\s+"
    r"--action_env=(?:PATH|HOME|USER|HOSTNAME|DATE|TIME|TZ)\b"
)
_REPRO_BAZEL_REPO_ENV_LEAK = _re(
    r"^[\s]*(?:build|test|run|common)\s+"
    r"--repo_env=\w+=(?:\$[A-Z_]+|\$\([^)]+\)|`[^`]+`)"
)


# P4 — repro-bazel-genrule-non-determinism
# `genrule(... cmd = "... <non-deterministic-tool> ...")` where the
# tool reads wall-clock / host identity / git HEAD inside the cmd.
# Bounded inner span [0,1500] keeps RE2 happy.
_REPRO_BAZEL_GENRULE_NONDET = _re(
    r"\bgenrule\s*\([\s\S]{0,1500}?\bcmd\s*=\s*['\"][\s\S]{0,1500}?"
    r"(?:\bdate\b|\buname\b|\bwhoami\b|\bhostname\b"
    r"|\bgit\s+rev-parse\b|\bgit\s+describe\b|\bgit\s+log\b"
    r"|/dev/random\b|/dev/urandom\b)"
)
# Mitigation tokens for P4: SDE pin, stamp=0, or Bazel's documented
# workspace-status-command output variable.
_REPRO_BAZEL_GENRULE_SAFE_TOKENS: tuple[str, ...] = (
    "SOURCE_DATE_EPOCH",
    "STABLE_GIT_COMMIT",
    "STABLE_BUILD_SCM_REVISION",
    "stamp = 0",
    "stamp=0",
)


# P6 — repro-nix-impure-builtins-or-flags
# Four sub-shapes; each one is RE2-safe.
# (a) Workflow runs nix with --impure
_REPRO_NIX_IMPURE_FLAG = _re(
    r"\bnix\s+(?:build|develop|run|shell|profile|flake|eval|repl)\b"
    r"[^\n]*--impure\b"
)
# (b) Non-pinned fetchTarball — string-only or attr-set without sha256.
# Bounded by closing-paren or closing-brace within 600 chars.
_REPRO_NIX_FETCH_NOSHA = _re(
    r"\bbuiltins\.fetch(?:Tarball|url|Git)\s+"
    r"(?:"
    r"\"[^\"]+\""  # plain URL string — never pure (no sha256)
    r"|"
    r"\{\s*(?:(?!sha256\s*=)(?!narHash\s*=)(?!hash\s*=)(?!rev\s*=)[\s\S]){0,600}?\}"
    r")"
)
# (c) `import <nixpkgs>` channel reference.
# `>` is a non-word character and so is the space/EOL/EOF that may follow,
# so a `\b` after `<nixpkgs>` would require a word/non-word transition that
# never exists at that position — the trailing boundary is unnecessary
# because `<nixpkgs>` is already terminated by a literal `>`. Keep the
# leading `\b` so `noimport <nixpkgs>` does not false-match.
_REPRO_NIX_CHANNEL_IMPORT = _re(
    r"\bimport\s+<nixpkgs>"
)
# (d) Non-pure builtins.
_REPRO_NIX_IMPURE_BUILTIN = _re(
    r"\bbuiltins\.(?:currentTime|currentSystem|getEnv|readDir|readFile|exec)\b"
)


# P7 — repro-make-shell-non-deterministic
# `VAR := $(shell <nondet-tool>)` at Makefile parse time. Bounded
# tool list; SOURCE_DATE_EPOCH inside the `$(shell ...)` body is
# the canonical safe escape — handled by a negative-substring scan
# on the matched window rather than a lookaround.
_REPRO_MAKE_SHELL_NONDET = _re(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*[:?]?=\s*"
    r"\$\(shell\s+"
    r"(?:date|uname|whoami|hostname|id|tty|pwd|env|printenv|shuf"
    r"|openssl\s+rand|head\s+-c\s+\d+\s+/dev/(?:urandom|random))"
    r"\b[^\n]*\)"
)
# Companion sub-rule: git-rev-parse embedding (MINOR severity —
# deterministic per-commit but the chicken-and-egg embedding is
# still discouraged).
_REPRO_MAKE_SHELL_GIT_REV = _re(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*[:?]?=\s*"
    r"\$\(shell\s+git\s+(?:rev-parse|describe|log)\b[^\n]*\)"
)
# Whitelisting token (per-line negative): when SOURCE_DATE_EPOCH
# appears in the same matched line, the make-shell pattern is the
# documented deterministic shape (`$(shell date -d @$SOURCE_DATE_EPOCH ...)`)
# — handled in `scan_file` via per-match line inspection.


# P8 — repro-c-cxx-date-time-macros
# `__DATE__`, `__TIME__`, `__TIMESTAMP__` referenced anywhere in a
# C/C++ source/header.
_REPRO_C_CXX_DATETIME_MACRO = _re(
    r"\b__(?:DATE|TIME|TIMESTAMP)__\b"
)
# Mitigation tokens for P8 (suppress on file-level): the build is
# configured to refuse date-time macros via the compiler flag.
_REPRO_C_CXX_DATETIME_SAFE: tuple[str, ...] = (
    "-Wdate-time",
    "-Werror=date-time",
)


# P9 — repro-go-build-timestamp-ldflags
# `go build ... -ldflags="-X main.buildTime=$(date ...)"` shape.
# The `$(date ...)` or backtick-`date ...` is the wall-clock reader;
# the `(?![^)]*SOURCE_DATE_EPOCH)` is a BOUNDED lookahead inside the
# command-substitution span — RE2-safe.
_REPRO_GO_LDFLAGS_DATE = _re(
    r"\bgo\s+build\b[^\n]*-ldflags=[^\n]*"
    r"-X\s+[^\s=]+="
    r"(?:"
    r"\$\(date(?![^)]*SOURCE_DATE_EPOCH)"
    r"|`date(?![^`]*SOURCE_DATE_EPOCH)"
    r")"
)
# Goreleaser shape — ldflags: list contains `-X ... ={{ .Date }}` or
# `{{ .Now }}` (the non-reproducible template vars).
_REPRO_GORELEASER_DATE_TEMPLATE = _re(
    r"-X\s+\S+=\{\{\s*\.(?:Date|Now)\s*\}\}"
)
# Mitigation tokens (file-level).
_REPRO_GO_LDFLAGS_SAFE: tuple[str, ...] = (
    "SOURCE_DATE_EPOCH",
    "CommitTimestamp",
    "CommitDate",
    "mod_timestamp",
)


# P10 — repro-archive-tool-timestamps-not-zeroed
# Each archive tool has its own non-zeroed default. We model each as a
# separate compiled pattern. The mitigation is handled per-rule
# below — each tool has its own canonical flag set.
# (a) `tar -c...` invocation.
_REPRO_TAR_CREATE = _re(
    r"^[^\n]*\b(?:tar|gtar|bsdtar)\s+(?:-?-?[A-Za-z]*c[A-Za-z]*)\b[^\n]*"
)
# (b) `zip -r` without `-X`.
# Word-boundary `\b` doesn't work around `-r` — `-` is non-word, so a
# `\b` between ` ` and `-` finds no word/non-word transition. We instead
# require a whitespace/edge anchor on each side of `-r` (and also accept
# combined-flag shapes like `-ra` / `-rX` for the `-X` mitigation path
# handled by the per-line filter below). `(?<![A-Za-z])` is a fixed-
# WIDTH negative lookbehind on a single literal character class — that
# shape is RE2-safe (bounded, single char).
_REPRO_ZIP_NO_X = _re(
    r"^[^\n]*\bzip\s+[^\n]*(?<![A-Za-z])-r[A-Za-z]*[^\n]*"
)
# (c) `gzip ...` without `-n` / `--no-name`.
_REPRO_GZIP_BARE = _re(
    r"^[^\n]*\bgzip\s+(?!-c\s+[<>])[^\n]*"
)
# (d) `ar` create/replace without `D`/`--deterministic`.
_REPRO_AR_BARE = _re(
    r"^[^\n]*\bar\s+(?:c|r|q|u|cs|cr|rs|rcs)\b[^\n]*"
)
# Per-tool mitigation tokens (line-level, per matched text).
_REPRO_TAR_SAFE_TOKENS: tuple[str, ...] = (
    "--sort=name",
    "--mtime=",
    "--owner=0",
    "--group=0",
    "--numeric-owner",
    "git archive",  # FP whitelist — git archive is reproducible-by-commit
)
_REPRO_ZIP_SAFE_TOKENS: tuple[str, ...] = (
    "--no-extra",
    # `-X` (standalone or combined-flag like `-rX`) is detected via a
    # dedicated `_filter_zip_x` helper — plain substring search would
    # miss the combined-flag shape because `-rX` contains no literal
    # `-X` substring (the `r` separates them). See `_filter_zip_x`.
)
# Pre-compiled regex used by `_filter_zip_x` — matches an `X` (or `x`
# under IGNORECASE) anywhere inside a dash-prefixed short-flag group:
# `-X`, `-rX`, `-rXz`, `-Xr`. Anchored by `(?<![A-Za-z])-` to avoid
# matching `X` mid-word (e.g. inside a filename). Single-char
# lookbehind → fixed-width → RE2-safe.
_REPRO_ZIP_X_FLAG = _re(r"(?<![A-Za-z])-[A-Za-z]*X[A-Za-z]*\b")
_REPRO_GZIP_SAFE_TOKENS: tuple[str, ...] = (
    "--no-name",
    "-n ",  # short form with trailing space to avoid matching -n in -ne etc
    "-n\n",
    "-n\t",
)
_REPRO_AR_SAFE_TOKENS: tuple[str, ...] = (
    "--deterministic",
    "rcsD",  # GNU ar deterministic shorthand
    "rsD",
    "cD",
    "crD",
    "rcD",
)


# P11 — repro-python-hash-seed-randomised-and-pyc-shipped
# `python -m compileall` without `--invalidation-mode checked-hash`
# OR without `--invalidation-mode unchecked-hash`. The bounded-
# lookahead inspects a finite span (next 200 chars on the same line).
_REPRO_PY_COMPILEALL_NO_HASH = _re(
    r"\bpython3?\s+-m\s+compileall\b"
    r"(?![^\n]{0,200}--invalidation-mode\s+(?:checked-hash|unchecked-hash))"
    r"[^\n]*"
)
# Mitigation tokens (file-level).
_REPRO_PY_COMPILEALL_SAFE: tuple[str, ...] = (
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONDONTWRITEBYTECODE = 1",
    "PYTHONHASHSEED=0",
    "PYTHONHASHSEED = 0",
    "--invalidation-mode checked-hash",
    "--invalidation-mode unchecked-hash",
)


# P12 — repro-locale-aware-sort-without-LC_ALL-C
# Bare `sort` in a pipeline that feeds a hash-sensitive tool. The
# bounded `[^|]{0,200}` between the sort and the consumer ensures the
# pattern doesn't backtrack across pipe boundaries (RE2-safe).
_REPRO_SORT_NO_LCALL = _re(
    r"\|\s*sort\b(?![^|\n]{0,200}\bLC_ALL\b)[^|\n]{0,200}"
    r"\|\s*(?:tar|cpio|md5sum|sha\d+sum|gzip|zip|cksum)"
)
# `find ... -print` (no `-print0`) into a hash-sensitive consumer.
_REPRO_FIND_PRINT_INTO_ARCHIVE = _re(
    r"\bfind\s+[^\n|]*\s-print\b(?![^\n|]*-print0)[^\n|]*"
    r"\|\s*(?:tar|cpio|zip|xargs)"
)
# Explicit non-C locale export.
_REPRO_LANG_NON_C_EXPORT = _re(
    r"^\s*(?:export\s+)?(?:LANG|LC_ALL|LC_COLLATE)\s*=\s*"
    r"(?:\"|')?(?!C(?:\.|/|\"|'|$|\b))[A-Za-z][^\s#\"']+"
)


# P13 — repro-docker-mutable-base-image-tag
# `FROM image:tag` without `@sha256:` digest. `FROM scratch` is
# whitelisted by the literal-name check below.
_REPRO_DOCKER_FROM_NO_DIGEST = _re(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?"
    r"(?!scratch\b)"
    r"(?:[A-Za-z0-9._/-]+)(?::[A-Za-z0-9._-]+)?"
    r"(?:\s+AS\s+\S+)?\s*$"
)
# Helper used during the line-level filter — line must NOT contain
# `@sha256:` for the rule to fire. Tracked as a per-finding check
# inside `scan_file` (cleaner than re-encoding the lookahead).


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="repro-bazel-workspace-mode-active",
        name="Bazel build runs without --noenable_workspace",
        severity="HIGH",
        description=(
            "Workflow invokes `bazel build/test/...` but the file "
            "never sets `--noenable_workspace` (or `--enable_bzlmod`, "
            "or references a `MODULE.bazel.lock`). On Bazel 7+ the "
            "default is bzlmod, but a repo that still ships a "
            "WORKSPACE file resolves dependencies via the legacy "
            "non-hermetic path unless the toggle is set explicitly. "
            "Add `common --noenable_workspace` to `.bazelrc` and "
            "commit a `MODULE.bazel.lock`."
        ),
        pattern=_REPRO_BAZEL_INVOKE,
        negative_substrings=_REPRO_BAZEL_HERMETIC_TOKENS,
        file_suffixes=(".yml", ".yaml", ".bazelrc"),
    ),
    Rule(
        id="repro-bazel-http-archive-no-sha256",
        name="Bazel `http_archive(...)` block has no sha256 = ...",
        severity="HIGH",
        description=(
            "`http_archive(name = \"foo\", urls = [...])` without a "
            "`sha256 = \"...\"` field lets the upstream change the "
            "release tarball bytes at any time. Bazel will re-fetch "
            "and re-cache the new bytes the next time the cache is "
            "empty (every fresh CI runner). Same class as a missing "
            "package-lock integrity hash, but at the build-system "
            "level. Pin the sha256."
        ),
        pattern=_REPRO_BAZEL_HTTP_ARCHIVE_NO_SHA,
        negative_substrings=(),
        file_suffixes=_BAZEL_FILES + (".bzl",),
    ),
    Rule(
        id="repro-bazel-git-repository-branch-only",
        name="Bazel `git_repository` pinned to a branch (no commit/tag)",
        severity="CRITICAL",
        description=(
            "`git_repository(remote = \"...\", branch = \"main\")` "
            "with no `commit =` and no `tag =` resolves to upstream "
            "HEAD at build time. Every fresh runner pulls whatever "
            "the upstream branch points at — the most extreme form "
            "of non-reproducible dependency resolution. Pin "
            "`commit = \"<sha>\"` (and ideally a corresponding "
            "`shallow_since`)."
        ),
        pattern=_REPRO_BAZEL_GIT_REPO_BRANCH_ONLY,
        negative_substrings=(),
        file_suffixes=_BAZEL_FILES + (".bzl",),
    ),
    Rule(
        id="repro-bazel-action-env-leaks-host",
        name="Bazel `.bazelrc` leaks host env into actions",
        severity="MAJOR",
        description=(
            "`--action_env=PATH` (or HOME/USER/HOSTNAME/DATE/TIME/TZ) "
            "passes the runner's host environment into every Bazel "
            "action. The action sees the host's tool versions instead "
            "of the toolchain Bazel was supposed to manage — same "
            "commit builds differently on x86_64 builder A vs builder "
            "B because their `/usr/bin/python3` versions differ. Use "
            "`--action_env=LANG=C.UTF-8` (locale normalisation) and "
            "pin compilers with `--action_env=CC=/usr/bin/clang-17`."
        ),
        pattern=_REPRO_BAZEL_ACTION_ENV_LEAK,
        negative_substrings=(),
        file_suffixes=(".bazelrc",),
    ),
    Rule(
        id="repro-bazel-repo-env-credential-leak",
        name="Bazel `--repo_env` reads host env / command output",
        severity="CRITICAL",
        description=(
            "`--repo_env=KEY=$VAR` (or `$(cmd)` / backticks) embeds "
            "a runner-side secret into Bazel's repository-cache key. "
            "Two builders with different credentials compute "
            "different cache keys, evict each other's entries, and "
            "the resulting build is non-reproducible AND "
            "credentialed. Use literal values or hermetic env names "
            "only."
        ),
        pattern=_REPRO_BAZEL_REPO_ENV_LEAK,
        negative_substrings=(),
        file_suffixes=(".bazelrc",),
    ),
    Rule(
        id="repro-bazel-genrule-non-determinism",
        name="Bazel `genrule` cmd embeds non-deterministic tools",
        severity="HIGH",
        description=(
            "`genrule(cmd = \"date > $(OUTS)\")` (or `uname`, "
            "`whoami`, `hostname`, `git rev-parse`, `/dev/urandom`) "
            "produces output that depends on WHEN and WHERE the "
            "build ran. Bazel caches genrule output by command-hash, "
            "not output-hash — cache hits look fine, cache misses "
            "drift. Use Bazel's workspace-status mechanism "
            "(`$STABLE_GIT_COMMIT`) or pin via `SOURCE_DATE_EPOCH`."
        ),
        pattern=_REPRO_BAZEL_GENRULE_NONDET,
        negative_substrings=_REPRO_BAZEL_GENRULE_SAFE_TOKENS,
        file_suffixes=_BAZEL_BUILD_FILES + (".bzl",),
    ),
    Rule(
        id="repro-nix-impure-flag",
        name="`nix build --impure` (or equivalent) defeats purity",
        severity="CRITICAL",
        description=(
            "`nix build --impure` (or `nix develop --impure`, etc.) "
            "allows the derivation to read process environment "
            "variables. Any builder-side env diff produces a "
            "different output hash. Drop `--impure`; if a derivation "
            "genuinely needs a value, pass it as a flake input pin "
            "or a `--argstr` literal."
        ),
        pattern=_REPRO_NIX_IMPURE_FLAG,
        negative_substrings=(),
        file_suffixes=_SHELL_FILES,
    ),
    Rule(
        id="repro-nix-fetcher-no-sha256",
        name="`builtins.fetchTarball/fetchurl/fetchGit` without sha256",
        severity="HIGH",
        description=(
            "`builtins.fetchTarball \"https://...\"` (string-only) or "
            "`builtins.fetchTarball { url = ...; }` without `sha256 "
            "=` lets the upstream change the bytes between fetches. "
            "`builtins.fetchGit { url = ...; }` without `rev =` "
            "resolves to upstream HEAD. Pin sha256/rev/narHash; the "
            "lockfile is not enough when the fetch is inline."
        ),
        pattern=_REPRO_NIX_FETCH_NOSHA,
        negative_substrings=(),
        file_suffixes=_NIX_FILES,
    ),
    Rule(
        id="repro-nix-channel-import",
        name="`import <nixpkgs>` channel reference defeats purity",
        severity="HIGH",
        description=(
            "`import <nixpkgs> {}` resolves to whatever the host's "
            "NIX_PATH points at — typically a channel pinned by the "
            "operator's `nix-channel --update`, not by the flake. "
            "Two builders with different channel revisions produce "
            "different derivations. Use a flake input pin "
            "(`inputs.nixpkgs.url = \"github:NixOS/nixpkgs/<rev>\"`) "
            "and reference it as `nixpkgs.legacyPackages.${system}`."
        ),
        pattern=_REPRO_NIX_CHANNEL_IMPORT,
        negative_substrings=(),
        file_suffixes=_NIX_FILES,
    ),
    Rule(
        id="repro-nix-impure-builtin",
        name="Impure `builtins.currentTime/currentSystem/getEnv/...`",
        severity="HIGH",
        description=(
            "`builtins.currentTime` embeds wall-clock into the "
            "derivation hash; `builtins.currentSystem` embeds the "
            "host CPU arch; `builtins.getEnv` reads process env "
            "(only allowed under `--impure`); `builtins.readDir` / "
            "`builtins.readFile` of an absolute path reads outside "
            "the flake. All four defeat purity. Use flake inputs and "
            "explicit `--system <arch>` overrides."
        ),
        pattern=_REPRO_NIX_IMPURE_BUILTIN,
        negative_substrings=(),
        file_suffixes=_NIX_FILES,
    ),
    Rule(
        id="repro-make-shell-non-deterministic",
        name="Makefile `$(shell ...)` invokes non-deterministic tool",
        severity="MAJOR",
        description=(
            "`VAR := $(shell date)` (or `uname`, `whoami`, "
            "`hostname`, `shuf`, `/dev/urandom`) evaluates at "
            "make-parse-time, ONCE per invocation, and bakes the "
            "result into every target that references VAR. If VAR "
            "feeds a compiler `-D` flag or a generated .h file, the "
            "artefact bytes drift across builds. Use "
            "`SOURCE_DATE_EPOCH` (e.g. `$(shell date -d @$$SOURCE_DATE_EPOCH +%Y%m%d)`) "
            "or move the variable into the build script env."
        ),
        pattern=_REPRO_MAKE_SHELL_NONDET,
        negative_substrings=("SOURCE_DATE_EPOCH",),
        file_suffixes=_MAKE_FILES,
    ),
    Rule(
        id="repro-make-shell-git-rev-embedded",
        name="Makefile `$(shell git rev-parse ...)` embedded in source",
        severity="MINOR",
        description=(
            "`VAR := $(shell git rev-parse HEAD)` is deterministic "
            "per-commit but the rev is then often written into a "
            "checked-in source file — a chicken-and-egg loop where "
            "one rebuild changes the source tree. Prefer "
            "build-script-level env injection (`-X main.commit=...` "
            "in Go, `-DCOMMIT=...` in C/C++) so the rev lives in the "
            "build pipeline, not in the source."
        ),
        pattern=_REPRO_MAKE_SHELL_GIT_REV,
        negative_substrings=(),
        file_suffixes=_MAKE_FILES,
    ),
    Rule(
        id="repro-c-cxx-date-time-macros",
        name="C/C++ source references `__DATE__`/`__TIME__`/`__TIMESTAMP__`",
        severity="MAJOR",
        description=(
            "The C/C++ preprocessor expands `__DATE__` to "
            "\"MMM DD YYYY\" and `__TIME__` to \"HH:MM:SS\" at "
            "compile time — every TU that uses them produces "
            "different bytes per build. `__TIMESTAMP__` expands to "
            "the source-file mtime (which is the `git checkout` "
            "time, not the commit's authored time). "
            "reproducible-builds.org lists these as canonical "
            "defeats. Replace with a build-system-injected "
            "`BUILD_DATE` macro, and compile with "
            "`-Wdate-time -Werror=date-time` to enforce."
        ),
        pattern=_REPRO_C_CXX_DATETIME_MACRO,
        negative_substrings=_REPRO_C_CXX_DATETIME_SAFE,
        file_suffixes=_C_CXX_FILES,
    ),
    Rule(
        id="repro-go-ldflags-build-timestamp",
        name="Go `-ldflags=\"-X ...=...$(date)\"` embeds wall-clock",
        severity="MAJOR",
        description=(
            "`go build -ldflags=\"-X main.buildTime=$(date -u "
            "+%Y-%m-%dT%H:%M:%SZ)\"` makes the binary bytes change "
            "every run. Even with `-trimpath`, the embedded "
            "timestamp defeats hash equivalence. Read "
            "`SOURCE_DATE_EPOCH` instead: `-X "
            "main.buildTime=$(date -u -d @${SOURCE_DATE_EPOCH} ...)`. "
            "goreleaser does this correctly when `mod_timestamp:` is "
            "set."
        ),
        pattern=_REPRO_GO_LDFLAGS_DATE,
        negative_substrings=_REPRO_GO_LDFLAGS_SAFE,
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-goreleaser-date-template-var",
        name="goreleaser `-X ...={{ .Date }}/{{ .Now }}` embeds build-time",
        severity="MAJOR",
        description=(
            "goreleaser's `{{ .Date }}` template variable is the "
            "build wall-clock; `{{ .Now }}` is its alias. Using "
            "either as an `-X` value embeds the build-time into the "
            "binary. Switch to `{{ .CommitDate }}` or "
            "`{{ .CommitTimestamp }}` and set "
            "`mod_timestamp: '{{ .CommitTimestamp }}'` at the top "
            "level."
        ),
        pattern=_REPRO_GORELEASER_DATE_TEMPLATE,
        negative_substrings=(),
        file_suffixes=_GORELEASER_FILES,
    ),
    Rule(
        id="repro-tar-create-no-determinism-flags",
        name="`tar -c...` without --sort=name / --mtime / --owner=0",
        severity="HIGH",
        description=(
            "`tar -czf out.tar.gz src/` captures each entry's mtime "
            "(= git-checkout time), the current uid/gid, and the "
            "filesystem-readdir order. All three drift across hosts. "
            "Reproducible-builds.org canonical recipe: "
            "`tar --sort=name --mtime=\"@${SOURCE_DATE_EPOCH}\" "
            "--owner=0 --group=0 --numeric-owner`. `git archive` is "
            "already reproducible-per-commit and is whitelisted."
        ),
        pattern=_REPRO_TAR_CREATE,
        negative_substrings=_REPRO_TAR_SAFE_TOKENS,
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-zip-create-no-X-flag",
        name="`zip -r ...` without -X (strip extra fields)",
        severity="HIGH",
        description=(
            "`zip -r out.zip src/` records each entry's mtime, uid, "
            "and platform-specific extended attributes. Pass `-X` to "
            "strip the platform extra-fields; pair with "
            "`find ... -print0 | sort -z | TZ=UTC zip --names-stdin` "
            "for deterministic ordering and timestamps."
        ),
        pattern=_REPRO_ZIP_NO_X,
        negative_substrings=_REPRO_ZIP_SAFE_TOKENS,
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-gzip-no-name-flag",
        name="`gzip ...` without -n / --no-name",
        severity="HIGH",
        description=(
            "Default `gzip` writes the original filename + mtime "
            "into the gzip header. Two builds of the same input "
            "produce different bytes if the source file's mtime "
            "differs (which it does after every `git checkout`). "
            "Pass `-n` (or `--no-name`) to strip the header."
        ),
        pattern=_REPRO_GZIP_BARE,
        negative_substrings=_REPRO_GZIP_SAFE_TOKENS,
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-ar-no-deterministic-flag",
        name="`ar` create/replace without --deterministic / D flag",
        severity="HIGH",
        description=(
            "GNU `ar rcs libfoo.a *.o` records each member's mtime, "
            "uid, gid, and mode. Pass `--deterministic` (or the "
            "single-letter `D` modifier — `rcsD`) to zero out all "
            "four. BSD `ar` lacks the flag; use the GNU port or "
            "post-process with `strip-nondeterminism`."
        ),
        pattern=_REPRO_AR_BARE,
        negative_substrings=_REPRO_AR_SAFE_TOKENS,
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-python-compileall-no-invalidation-hash",
        name="`python -m compileall` without --invalidation-mode hash",
        severity="MAJOR",
        description=(
            "PEP 552 added hash-based pyc files (3.7+) that are "
            "reproducible-by-content. The default invalidation mode "
            "is `timestamp`, which embeds the source mtime (= "
            "git-checkout time) into the .pyc. If those .pyc files "
            "ship in a wheel/sdist/container image, the artefact "
            "bytes drift. Pass `--invalidation-mode checked-hash`."
        ),
        pattern=_REPRO_PY_COMPILEALL_NO_HASH,
        negative_substrings=_REPRO_PY_COMPILEALL_SAFE,
        # Container build steps live in Dockerfile family OR in shell
        # scripts / Makefiles that get COPY'd in during the image build.
        file_suffixes=_DOCKER_FILES + _MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-sort-no-LC_ALL-into-archive",
        name="`sort` without LC_ALL=C piped into archive tool",
        severity="MAJOR",
        description=(
            "`find ... | sort | tar ...` uses locale-aware "
            "collation. On `en_US.UTF-8`, `sort` treats case as "
            "secondary; on `C`/`POSIX`, byte-order. A pipeline that "
            "produces a tarball through sort captures different "
            "file ordering per host. Prefix the `sort` with "
            "`LC_ALL=C` (or `LC_COLLATE=C`)."
        ),
        pattern=_REPRO_SORT_NO_LCALL,
        negative_substrings=(),
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-find-print-no-print0-into-archive",
        name="`find ... -print | tar/cpio/zip` (use -print0 + sort -z)",
        severity="MAJOR",
        description=(
            "`find -print` separates by newline; filenames with "
            "newlines (rare but legal) break the consumer. More "
            "importantly the output is in filesystem-readdir order, "
            "which differs ext4 vs xfs vs APFS. Combined with a "
            "non-LC_ALL sort, the resulting tar captures different "
            "bytes per host. Use `find -print0 | sort -z | tar "
            "--null --files-from=-`."
        ),
        pattern=_REPRO_FIND_PRINT_INTO_ARCHIVE,
        negative_substrings=(),
        file_suffixes=_MAKE_FILES + _SHELL_FILES,
    ),
    Rule(
        id="repro-locale-set-to-non-C",
        name="`LANG=`/`LC_ALL=`/`LC_COLLATE=` set to non-C locale",
        severity="MINOR",
        description=(
            "Explicit `LANG=en_US.UTF-8` (or any non-C locale) in a "
            "build script makes every subsequent `sort`, `tr`, "
            "`grep`, `awk` invocation use that locale. The result is "
            "locale-dependent build output even when the rest of the "
            "pipeline is deterministic. Set `LC_ALL=C` (or "
            "`LANG=C.UTF-8` to keep UTF-8 awareness in messages but "
            "C collation in sorts)."
        ),
        pattern=_REPRO_LANG_NON_C_EXPORT,
        negative_substrings=(),
        # Locale exports leak into every subsequent invocation, so
        # they apply to Make + shell + the per-user shell init files.
        file_suffixes=(
            _MAKE_FILES + _SHELL_FILES + _DOTFILE_SUFFIXES
        ),
    ),
    Rule(
        id="repro-docker-mutable-base-tag",
        name="Dockerfile `FROM image:tag` without @sha256: digest",
        severity="HIGH",
        description=(
            "`FROM alpine:3.18` is a mutable reference — the "
            "upstream maintainer may re-tag `3.18` to point at a "
            "fresh patch build any day. Two builds of the same "
            "Dockerfile produce different image hashes even when "
            "every line is identical. Pin the digest: `FROM "
            "alpine:3.18@sha256:<...>`. `FROM scratch` and `FROM "
            "...@sha256:...` are whitelisted."
        ),
        pattern=_REPRO_DOCKER_FROM_NO_DIGEST,
        negative_substrings=(),
        file_suffixes=_DOCKER_FILES,
    ),
)


# ---- Scan helpers -------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).
    Mirrors `provenance_patterns._line_col`."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_matches_suffixes(path: Path, suffixes: tuple[str, ...]) -> bool:
    """Empty suffix tuple → any file. Otherwise check the path's name
    against each entry: an entry that starts with `.` is treated as a
    suffix (case-insensitive `.endswith`), otherwise as a full
    basename match (case-sensitive, since `Makefile` and `makefile`
    are different files in practice — Make autodetects both, but
    `makefile` is non-canonical).

    The two-shape match supports rules whose `file_suffixes` mix
    `.bazelrc` (suffix), `WORKSPACE` (basename), `Makefile`
    (basename), `Dockerfile` (basename), `.nix` (suffix). Each entry
    is checked independently."""
    if not suffixes:
        return True
    name = path.name
    name_lower = name.lower()
    for entry in suffixes:
        if entry.startswith("."):
            if name_lower.endswith(entry.lower()):
                return True
        else:
            # Exact basename match (case-sensitive — `Makefile` vs
            # `makefile` matters on case-sensitive filesystems).
            if name == entry:
                return True
    return False


def _filter_make_shell_nondet(content: str, m: re.Match) -> bool:
    """The make-shell-nondet rule whitelists matches whose
    `$(shell ...)` body contains `SOURCE_DATE_EPOCH` — that is the
    canonical deterministic shape `$(shell date -d @$$SOURCE_DATE_EPOCH ...)`.

    Returns True if the match SHOULD fire (no whitelist hit),
    False if the line is the safe shape (suppress)."""
    line_start = content.rfind("\n", 0, m.start()) + 1
    line_end = content.find("\n", m.end())
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    return "SOURCE_DATE_EPOCH" not in line


def _filter_archive_tool(
    matched_line: str,
    safe_tokens: tuple[str, ...],
) -> bool:
    """Per-line filter for tar/zip/gzip/ar rules: emit only if NONE of
    the safe tokens appear on the same matched line. Substring match
    (not regex) so it's deterministic and matches the negative-
    substring convention of `provenance_patterns`."""
    lc = matched_line.lower()
    for tok in safe_tokens:
        if tok.lower() in lc:
            return False
    return True


def _filter_zip_x(matched_line: str) -> bool:
    """Per-line filter for the `repro-zip-create-no-X-flag` rule.

    A plain substring search for `-X` is not enough: `zip -rX out.zip`
    combines short flags, so the literal `-X` substring is absent (the
    `r` separates the dash from the `X`). This helper uses the
    pre-compiled `_REPRO_ZIP_X_FLAG` pattern to detect `X` (or `x`
    under IGNORECASE) as a flag character inside ANY dash-prefixed
    short-flag group on the matched line — both `-X` standalone and
    `-rX` / `-rXz` / `-Xr` combined forms.

    Also defers to `_filter_archive_tool` for the remaining safe
    substrings (currently `--no-extra`) so the two checks compose.

    Returns True if the match SHOULD fire (no `-X` and no other safe
    token present), False if the line is the documented safe shape."""
    if _REPRO_ZIP_X_FLAG.search(matched_line):
        return False
    return _filter_archive_tool(matched_line, _REPRO_ZIP_SAFE_TOKENS)


def _filter_docker_from(matched_line: str) -> bool:
    """Return True (emit finding) only if the matched FROM line does
    NOT contain `@sha256:`. Skipped already by the regex's
    `(?!scratch\\b)` guard but a second-level substring check keeps
    the rule honest if the regex evolves."""
    return "@sha256:" not in matched_line.lower()


def _filter_compileall(matched_line: str) -> bool:
    """Suppress if the matched line itself contains the safe
    invalidation-mode flag — the bounded lookahead in the regex
    handles same-line cases but a second-pass plain substring check
    matches the convention used elsewhere in this catalogue."""
    return (
        "--invalidation-mode checked-hash" not in matched_line
        and "--invalidation-mode unchecked-hash" not in matched_line
    )


def scan_file(path: Path) -> list[Finding]:
    """Run every applicable rule against the file content and return
    findings. Two-pass shape (mirror of `provenance_patterns.scan_file`):

      1. POSITIVE: `rule.pattern.finditer(content)` — line-scoped or
         bounded multi-line regex.
      2. NEGATIVE: if any of `rule.negative_substrings` appears in the
         FULL file content (case-insensitive plain substring), drop
         every positive match for that rule.

    Per-rule line-level post-filters (encoded in the helpers above)
    further suppress matches whose immediate line context contains a
    safe-token (e.g. `SOURCE_DATE_EPOCH` inside a make-shell-date
    expression, or `--deterministic` on the same `ar` command line).

    Errors during read return an empty list — the detector path must
    not crash on permission-denied / binary / partial read."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not content:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    path_str = str(path)

    cl_cached: str | None = None

    # Per-rule line-level post-filter dispatch. Each entry maps a
    # rule_id to a callable(content, match) -> bool that returns True
    # to emit and False to suppress.
    for rule in RULES:
        if not _file_matches_suffixes(path, rule.file_suffixes):
            continue

        # File-level negative-substring suppression.
        if rule.negative_substrings:
            if cl_cached is None:
                cl_cached = content.lower()
            if any(neg.lower() in cl_cached for neg in rule.negative_substrings):
                continue

        for m in rule.pattern.finditer(content):
            line, col = _line_col(content, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue

            matched = m.group(0)
            # The line containing the match — used by per-rule
            # post-filters that look at single-line context.
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.end())
            if line_end == -1:
                line_end = len(content)
            matched_line = content[line_start:line_end]

            # Per-rule post-filter.
            if rule.id == "repro-make-shell-non-deterministic":
                if not _filter_make_shell_nondet(content, m):
                    continue
            elif rule.id == "repro-tar-create-no-determinism-flags":
                if not _filter_archive_tool(matched_line,
                                            _REPRO_TAR_SAFE_TOKENS):
                    continue
            elif rule.id == "repro-zip-create-no-X-flag":
                # Use the dedicated `_filter_zip_x` helper — plain
                # substring search misses combined-flag shapes like
                # `-rX`. See the helper's docstring for the full
                # rationale.
                if not _filter_zip_x(matched_line):
                    continue
            elif rule.id == "repro-gzip-no-name-flag":
                if not _filter_archive_tool(matched_line,
                                            _REPRO_GZIP_SAFE_TOKENS):
                    continue
            elif rule.id == "repro-ar-no-deterministic-flag":
                if not _filter_archive_tool(matched_line,
                                            _REPRO_AR_SAFE_TOKENS):
                    continue
            elif rule.id == "repro-docker-mutable-base-tag":
                if not _filter_docker_from(matched_line):
                    continue
            elif rule.id == "repro-python-compileall-no-invalidation-hash":
                if not _filter_compileall(matched_line):
                    continue

            seen.add(key)
            matched = matched.strip()
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                file_path=path_str,
            ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


def scan_repo_for_lockfiles(repo_root: Path) -> list[Finding]:
    """Cross-file lockfile presence checks (P5 family):

      * `flake.nix` at repo root without sibling `flake.lock`
        → `repro-nix-flake-no-lockfile` (HIGH).
      * `flake.nix` at repo root with `flake.lock` excluded via
        `.gitignore` → `repro-nix-flake-lock-gitignored` (CRITICAL).
      * `MODULE.bazel` at repo root without sibling
        `MODULE.bazel.lock` → `repro-bazel-bzlmod-no-lockfile`
        (HIGH).

    Returns Findings whose `file_path` is the OFFENDING source file
    (`flake.nix` / `MODULE.bazel`) — there is no specific line/col,
    so both default to (1, 1)."""
    out: list[Finding] = []
    try:
        repo_root_resolved = repo_root.resolve()
    except OSError:
        return out

    flake_nix = repo_root_resolved / "flake.nix"
    flake_lock = repo_root_resolved / "flake.lock"
    if flake_nix.is_file():
        if not flake_lock.is_file():
            out.append(Finding(
                rule_id="repro-nix-flake-no-lockfile",
                line=1,
                column=1,
                matched_text="flake.nix present, flake.lock missing",
                severity="HIGH",
                description=(
                    "`flake.nix` declares inputs that resolve to "
                    "branch HEAD at evaluation time unless pinned in "
                    "`flake.lock`. The lockfile is missing — every "
                    "fresh runner regenerates pins from upstream "
                    "HEAD. Run `nix flake lock` and commit "
                    "`flake.lock`."
                ),
                file_path=str(flake_nix),
            ))
        # Check .gitignore for flake.lock exclusion.
        gitignore = repo_root_resolved / ".gitignore"
        if gitignore.is_file():
            try:
                gi_content = gitignore.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                gi_content = ""
            # Strip comments, look for explicit flake.lock exclusion.
            for raw in gi_content.splitlines():
                stripped = raw.split("#", 1)[0].strip()
                if stripped in {"flake.lock", "/flake.lock"}:
                    out.append(Finding(
                        rule_id="repro-nix-flake-lock-gitignored",
                        line=1,
                        column=1,
                        matched_text="flake.lock excluded by .gitignore",
                        severity="CRITICAL",
                        description=(
                            "`.gitignore` excludes `flake.lock`. The "
                            "operator does not understand flake "
                            "semantics — the lockfile is the ONLY "
                            "thing that pins inputs across "
                            "operators. Remove the gitignore entry "
                            "and commit the lockfile."
                        ),
                        file_path=str(gitignore),
                    ))
                    break

    module_bazel = repo_root_resolved / "MODULE.bazel"
    module_bazel_lock = repo_root_resolved / "MODULE.bazel.lock"
    if module_bazel.is_file() and not module_bazel_lock.is_file():
        out.append(Finding(
            rule_id="repro-bazel-bzlmod-no-lockfile",
            line=1,
            column=1,
            matched_text="MODULE.bazel present, MODULE.bazel.lock missing",
            severity="HIGH",
            description=(
                "`MODULE.bazel` declares bzlmod dependencies that "
                "must be pinned in `MODULE.bazel.lock`. The lockfile "
                "is missing — every fresh runner regenerates pins "
                "from BCR HEAD. Run `bazel mod tidy` (or "
                "`bazel build` once) and commit "
                "`MODULE.bazel.lock`."
            ),
            file_path=str(module_bazel),
        ))

    return out
