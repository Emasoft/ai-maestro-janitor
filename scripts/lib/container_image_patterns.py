"""Container image layer / Dockerfile composition anti-patterns.

Wave-25 distillation round 11. Catalogue of 11 Dockerfile-composition
bug classes distilled in
`reports/distill-round-11/container-image-layers.md`. Targets
Dockerfile / Containerfile / docker-compose surfaces that earlier
waves cover only at the abstract level.

What is NOT here (already shipped — DO NOT duplicate):

  * `repro-docker-mutable-base-tag` in
    `build_reproducibility_patterns.py` — fires when `@sha256:` is
    absent on `FROM`. This file's P1 is **disjoint**: it targets the
    *tag-quality* concern (`:latest`, `:lts`, `:edge`, `:rolling`,
    `:stable`, `:current`, `:nightly`, `:dev`, `:main`, `:master`)
    **even when** a digest is pinned. `FROM nginx:latest@sha256:abc`
    passes Wave-24 but the maintainer is still following a mutable
    label.
  * `unpinned-docker-image`, `hardcoded-container-latest`,
    `container-dockerignore-evasion`, `dockerfile-heredoc-pipe-to-shell`,
    `dockerfile-copy-from-external-registry`,
    `dockerfile-healthcheck-shell-escape`,
    `devcontainer-untrusted-features-and-hooks`,
    `dockerfile-env-registry-bypass` in `container_patterns.py` —
    these target single-line build smuggling, heredoc download-and-exec,
    devcontainer hooks, registry env bypass. Disjoint from the 11
    rules below which target image-composition layer contracts.
  * Sentinel `rules_*` libraries — GitHub Actions / workflow side,
    not Dockerfile body.
  * `terraform_iac_patterns.py::TB13` — k8s `runAsUser: 0`. The
    P3 below is **Dockerfile-side** (image's default user is root
    irrespective of k8s manifest).

What IS here (11 net-new rules, regex-only, all RE2-safe):

  * container-from-tag-mutable-label                       (MAJOR)
  * container-copy-from-external-image-no-digest           (CRITICAL)
  * container-no-user-directive                            (MAJOR)
  * container-cmd-shell-form                               (MAJOR)
  * container-copy-root-no-dockerignore                    (MAJOR)
  * container-add-remote-url                               (CRITICAL)
  * container-no-healthcheck                               (MINOR)
  * container-arg-env-secret-propagation                   (CRITICAL)
  * container-apt-source-check-valid-until-no-signed-by    (MAJOR)
  * container-compose-image-mutable-label                  (MAJOR)
  * container-package-install-no-version-pin               (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Cryptographic Failures (secrets in image, ARG→ENV leak)
  ASI-04 — Insecure Design (least privilege — root-by-default)
  ASI-06 — Vulnerable & Outdated Components (package-install drift)
  ASI-08 — Outdated/Vulnerable Components (mutable image labels,
                                            external-image smuggling,
                                            apt freshness bypass,
                                            remote ADD)
  ASI-09 — Security Logging & Monitoring Failures (signal handling,
                                                    liveness blindness)
  ASI-10 — SSRF (remote ADD at build time)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes; only single-char-class negative
lookahead). Patterns are PRE-COMPILED at module load. Fail-fast:
callers receive structured Finding tuples, never raised exceptions
on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with MULTILINE+UNICODE. Dockerfile directives are
    upper-case by convention but we accept any case via explicit
    alternation where needed (FROM/from etc.) — IGNORECASE would let
    package-name fragments (`apk`, `apt-get`) match unintended
    English text. RE2-safe: no backreferences, no lookbehind.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- P1 : container-from-tag-mutable-label ------------------------------


# Match a Dockerfile FROM line whose tag is in the mutable-label
# alternation. Accept optional --platform= flag and optional `AS <stage>`
# suffix. The trailing `\b` ensures we don't accept `:latestest` or
# `:latest-alpine` (which is a different image flavour).
_FROM_MUTABLE_TAG = _re(
    r"^[ \t]*(?:FROM|from)[ \t]+(?:--platform=[^\s]+[ \t]+)?"
    r"[A-Za-z0-9./_-]+:(latest|lts|edge|rolling|stable|current|nightly|dev|main|master)\b"
)


# ---- P2 : container-copy-from-external-image-no-digest ------------------


# Match a Dockerfile `COPY --from=<value>` where <value> looks like an
# external registry reference (contains `/` separating registry+image,
# OR `:tag`) rather than a bare stage name. Then require the rest of
# the line to NOT contain `@` (digest pinning).
#
# Match group 1 captures the image reference. The trailing
# `(?:[^@\n]*)$` negated-class is the "no `@` on this line" assertion.
_COPY_FROM_EXTERNAL_NO_DIGEST = _re(
    r"^[ \t]*(?:COPY|copy)[ \t]+--from="
    r"([A-Za-z0-9._-]+/[A-Za-z0-9._/-]+(?::[A-Za-z0-9._-]+)?"
    r"|[A-Za-z0-9._-]+:[A-Za-z0-9._-]+)"
    r"(?:[^@\n]*)$"
)


# ---- P3 : container-no-user-directive -----------------------------------


# Trigger: any FROM line means "this file is a Dockerfile-shape body".
# Suppressor: any USER line later in the file.
_DOCKERFILE_FROM_LINE = _re(
    r"^[ \t]*(?:FROM|from)[ \t]+[A-Za-z0-9./_:@-]+"
)

_DOCKERFILE_USER_LINE = _re(
    r"^[ \t]*(?:USER|user)[ \t]+[A-Za-z0-9_.:-]+[ \t]*(?:#.*)?$"
)


# ---- P4 : container-cmd-shell-form --------------------------------------


# Anchor on CMD or ENTRYPOINT followed by whitespace and then a
# non-`[` non-whitespace character — i.e. the value does NOT start
# with `[` which would be exec-form JSON array.
# Bounded; RE2-safe (single-char negative class, no backref).
_CMD_OR_ENTRYPOINT_SHELL_FORM = _re(
    r"^[ \t]*(?:CMD|ENTRYPOINT|cmd|entrypoint)[ \t]+[^\[\s]"
)


# ---- P5 : container-copy-root-no-dockerignore ---------------------------


# Match `COPY .` / `COPY ./` / `COPY ./. .` / `COPY ./ .` shapes.
# Optional --chown=, --chmod=, --from=<stage> flags before the source.
# The destination must be `.` or `./` (everything-in pattern).
_COPY_DOT_TO_DOT = _re(
    r"^[ \t]*(?:COPY|copy)[ \t]+"
    r"(?:--(?:chown|chmod)=[^\s]+[ \t]+)*"
    r"(?:\./?\.?|\.)"
    r"[ \t]+\.?/?[ \t]*(?:#.*)?$"
)


# ---- P6 : container-add-remote-url --------------------------------------


# Match `ADD <url>` shape. Optional --chown=, --chmod= flags.
# A `--checksum=` flag suppresses the finding via a Stage-B check.
_ADD_REMOTE_URL = _re(
    r"^[ \t]*(?:ADD|add)[ \t]+"
    r"(?:--(?:chown|chmod)=[^\s]+[ \t]+)*"
    r"(?:https?|ftp|git)://[^\s]+"
)

# Safe variant — BuildKit `--checksum=sha256:abc` form. If present on
# the same line as ADD+URL, the rule is suppressed.
_ADD_CHECKSUM_PRESENT = _re(
    r"^[ \t]*(?:ADD|add)[ \t]+"
    r"(?:--(?:chown|chmod|checksum)=[^\s]+[ \t]+)*"
    r"--checksum=sha\d+:[a-fA-F0-9]+[ \t]+"
)


# ---- P7 : container-no-healthcheck --------------------------------------


# Trigger: EXPOSE directive — image declares network port.
_DOCKERFILE_EXPOSE_LINE = _re(
    r"^[ \t]*(?:EXPOSE|expose)[ \t]+\d+(?:/(?:tcp|udp))?[ \t]*(?:#.*)?$"
)

# Suppressor: HEALTHCHECK directive — must have CMD body (not NONE).
_DOCKERFILE_HEALTHCHECK_LINE = _re(
    r"^[ \t]*(?:HEALTHCHECK|healthcheck)[ \t]+"
    r"(?:--[A-Za-z0-9-]+=[^\s]+[ \t]+)*"
    r"(?:CMD|cmd)\b"
)


# ---- P8 : container-arg-env-secret-propagation --------------------------


# Two-pass detector. Pass 1: collect every ARG name in the file.
# Pass 2: for each name, search for an ENV line of the form
# `ENV NAME=$NAME` or `ENV NAME=${NAME}`. This avoids the
# regex-backreference (`\1`) that RE2 does not support.
_ARG_NAME_CAPTURE = _re(
    r"^[ \t]*(?:ARG|arg)[ \t]+([A-Z][A-Z0-9_]{2,})"
    r"(?:[ \t]*=[ \t]*[^\n]*)?[ \t]*(?:#.*)?$"
)


def _env_propagation_pattern(arg_name: str) -> re.Pattern:
    """Build a per-ARG regex that matches an ENV assignment whose RHS
    references the same ARG name. RE2-safe: arg_name is a fixed
    literal (escaped) — no backreferences."""
    escaped = re.escape(arg_name)
    return _re(
        r"^[ \t]*(?:ENV|env)[ \t]+"
        + escaped
        + r"[ \t]*=[ \t]*\$\{?"
        + escaped
        + r"\}?"
    )


# Public-prefix carve-out: framework-conventional public env vars are
# intentional and downgrade to MINOR. The list mirrors the Next.js /
# Vite / CRA / Expo conventions.
_PUBLIC_PREFIX = re.compile(
    r"^(?:NEXT_PUBLIC_|VITE_|REACT_APP_|EXPO_PUBLIC_)"
)


# ---- P9 : container-apt-source-check-valid-until-no-signed-by -----------


# Match any line containing `deb [ ... check-valid-until=no ... ] <url> ...`
# without `signed-by=` inside the same `[ ... ]` options block.
# The two-stage approach:
#   Stage A: line contains `deb [...]` with `check-valid-until=no`
#   Stage B: line does NOT contain `signed-by=` inside the same brackets.
_APT_DEB_LINE_NO_SIGNED_BY = _re(
    r"^[^#\n]*\bdeb[ \t]+\[[^\]]*\bcheck-valid-until=no\b[^\]]*\]"
)

_APT_SIGNED_BY_MARKER = _re(
    r"\bsigned-by="
)


# ---- P10 : container-compose-image-mutable-label ------------------------


# Match compose YAML `image: <name>:<mutable-label>`. The same mutable
# alternation as P1 (latest / lts / edge / rolling / stable / current /
# nightly / dev / main / master). Allows optional inline comment.
_COMPOSE_IMAGE_MUTABLE = _re(
    r"^[ \t]*image:[ \t]*"
    r"[A-Za-z0-9./_-]+:(latest|lts|edge|rolling|stable|current|nightly|dev|main|master)"
    r"[ \t]*(?:#.*)?$"
)

# Stage-B gate: the file is a compose file. We look for one of
# `services:` (top-level), `version:` (compose-v1/v2 schema marker),
# or `networks:` / `volumes:` near the top — anywhere in the file is
# fine since callers usually pass a single compose file.
_COMPOSE_FILE_MARKER = _re(
    r"^services:[ \t]*$"
    r"|"
    r"^version:[ \t]*['\"]?\d"
    r"|"
    r"^networks:[ \t]*$"
    r"|"
    r"^volumes:[ \t]*$"
)


# ---- P11 : container-package-install-no-version-pin ---------------------


# Family-specific detectors. Each detector anchors on the package
# manager invocation and looks for an unpinned positional package
# argument. Negative lookaheads `(?!=)`, `(?![=<>~!])`, `(?!@)`,
# `(?![=/])` are RE2-safe (single-char or single-char-class).
#
# Carve-outs handled out-of-band:
#   * `pip install -r requirements.txt` — no positional pkg, doesn't match.
#   * `ca-certificates` — common rolling pkg, suppressed by the
#     `dockerfile-justification: ca-certificates-rolling` comment marker.

# apk add — version pin is `pkg=<version>`.
_APK_ADD_UNPINNED = _re(
    r"^[ \t]*(?:RUN|run)[ \t]+(?:[^\n]*?\b)?apk[ \t]+add"
    r"(?:[ \t]+--[A-Za-z0-9-]+(?:=[^\s]+)?)*"
    r"[ \t]+(?!--)[A-Za-z0-9._+-]+(?!=)\b"
)

# apt-get install — version pin is `pkg=<version>` or `pkg/<release>`.
_APT_GET_INSTALL_UNPINNED = _re(
    r"^[ \t]*(?:RUN|run)[ \t]+(?:[^\n]*?\b)?apt-get[ \t]+install"
    r"(?:[ \t]+-[A-Za-z0-9]+)*"
    r"(?:[ \t]+--[A-Za-z0-9-]+(?:=[^\s]+)?)*"
    r"[ \t]+(?!--)(?!-y)[A-Za-z0-9._+-]+(?![=/])\b"
)

# pip install — version pin is `pkg==<version>` (and < <= > >= ~= !=).
_PIP_INSTALL_UNPINNED = _re(
    r"^[ \t]*(?:RUN|run)[ \t]+(?:[^\n]*?\b)?pip[ \t]+install"
    r"(?:[ \t]+--[A-Za-z0-9-]+(?:=[^\s]+)?)*"
    r"[ \t]+(?!--)(?!-r\b)[A-Za-z0-9._-]+(?![=<>~!])\b"
)

# npm install -g — version pin is `pkg@<version>`.
_NPM_INSTALL_G_UNPINNED = _re(
    r"^[ \t]*(?:RUN|run)[ \t]+(?:[^\n]*?\b)?npm[ \t]+(?:install|i)[ \t]+-g"
    r"(?:[ \t]+--[A-Za-z0-9-]+(?:=[^\s]+)?)*"
    r"[ \t]+(?!--)[A-Za-z0-9._-]+(?!@)\b"
)

# Suppression marker for the per-RUN justification (e.g.
# ca-certificates, base-image-non-root, etc.).
_DOCKERFILE_JUSTIFICATION_MARKER = _re(
    r"#[ \t]*dockerfile-justification:"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="container-from-tag-mutable-label",
        name="Dockerfile FROM uses a mutable label tag (latest / lts / edge / rolling)",
        severity="MAJOR",
        description=(
            "Dockerfile `FROM` line uses a tag whose contract is "
            "'always the freshest' rather than a pinned version "
            "series. Even when a digest is appended via `@sha256:`, "
            "the next manual digest bump will follow the maintainer's "
            "mutable pointer and may silently traverse major versions. "
            "Disjoint from Wave-24's `repro-docker-mutable-base-tag` "
            "which fires on absent digest — this rule fires on the "
            "tag-quality concern even when the digest IS pinned."
        ),
        pattern=_FROM_MUTABLE_TAG,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="container-copy-from-external-image-no-digest",
        name="COPY --from references an external image without a digest pin",
        severity="CRITICAL",
        description=(
            "Multi-stage build pulls binary artefacts from an "
            "external registry image (`COPY --from=hashicorp/"
            "terraform:1.15.2 /bin/terraform ...`) referenced by "
            "name+tag rather than by `@sha256:` digest. The source "
            "image moves silently between rebuilds; an attacker who "
            "compromises the upstream registry can smuggle in a "
            "tampered binary that the local Dockerfile copies into "
            "the final image. Disjoint from Wave-24's FROM-only check."
        ),
        pattern=_COPY_FROM_EXTERNAL_NO_DIGEST,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="container-no-user-directive",
        name="Dockerfile has no USER directive — image runs as root by default",
        severity="MAJOR",
        description=(
            "No `USER` directive anywhere in the Dockerfile body. "
            "Image's default user is whatever the base image inherits "
            "(typically root). Even if the k8s manifest sets "
            "`runAsUser: <nonzero>`, that setting must be explicitly "
            "applied in every consuming environment; the image itself "
            "should default to non-root. Disjoint from "
            "terraform_iac TB13 (k8s manifest side, not Dockerfile side)."
        ),
        pattern=_DOCKERFILE_FROM_LINE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="container-cmd-shell-form",
        name="Dockerfile CMD / ENTRYPOINT uses shell form — PID 1 is /bin/sh -c",
        severity="MAJOR",
        description=(
            "`CMD` or `ENTRYPOINT` is written in shell form "
            "(`CMD foo bar`) rather than exec form "
            "(`CMD [\"foo\", \"bar\"]`). Shell form runs the command "
            "under `/bin/sh -c`, so PID 1 inside the container is "
            "the shell, not the application. The shell does not "
            "forward SIGTERM to its child by default; `docker stop` "
            "waits the grace period then SIGKILLs, denying the "
            "application a chance to drain in-flight requests or "
            "flush state. Exec form makes the application PID 1 and "
            "delivers signals directly."
        ),
        pattern=_CMD_OR_ENTRYPOINT_SHELL_FORM,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="container-copy-root-no-dockerignore",
        name="COPY . . (everything-in) is used but a .dockerignore filter is implied",
        severity="MAJOR",
        description=(
            "A `COPY .` / `COPY ./` / `COPY ./. .` directive pulls "
            "the entire build context into the image layer. Without "
            "a `.dockerignore`, the image carries `.git/`, `.env*`, "
            "`node_modules/.cache/`, IDE config (`.vscode/`, "
            "`.idea/`), and any locally-created secrets the "
            "contributor forgot to gitignore. The detector emits a "
            "finding on every `COPY . .` line; the operator pairs it "
            "with a filesystem-side .dockerignore presence check."
        ),
        pattern=_COPY_DOT_TO_DOT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="container-add-remote-url",
        name="ADD with a remote URL — no integrity verification at build time",
        severity="CRITICAL",
        description=(
            "`ADD https://...` (or `ftp://`, `git://`) fetches a "
            "remote resource at build time. Unlike `COPY`, `ADD` "
            "does NOT verify resource integrity — the URL contents "
            "can change between rebuilds, and a CDN compromise or "
            "DNS-hijack rewrites the bytes silently. BuildKit's "
            "`--checksum=sha256:...` flag (introduced in 2023) is "
            "the safe alternative and suppresses this rule."
        ),
        pattern=_ADD_REMOTE_URL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="container-no-healthcheck",
        name="Dockerfile exposes a port but has no HEALTHCHECK directive",
        severity="MINOR",
        description=(
            "Dockerfile contains an `EXPOSE` directive (image "
            "declares a network port) but no `HEALTHCHECK CMD` "
            "directive. The orchestrator's `docker ps` STATUS "
            "column will show `Up` even when the application "
            "inside is crash-looping behind the entrypoint. Kubernetes "
            "users may rely on `readinessProbe`/`livenessProbe` "
            "instead — suppress with "
            "`# dockerfile-justification: orchestrator-provides-healthcheck` "
            "if the orchestrator owns liveness signalling."
        ),
        pattern=_DOCKERFILE_EXPOSE_LINE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="container-arg-env-secret-propagation",
        name="ARG value propagated into ENV — build-time secret persists in image",
        severity="CRITICAL",
        description=(
            "Build-time `ARG NAME` is declared, followed in the "
            "same stage by `ENV NAME=$NAME` (or `ENV NAME=${NAME}`). "
            "`ARG` values are ephemeral but `ENV` values persist "
            "into the final image; `docker history` and "
            "`docker inspect` will show the value. If the ARG ever "
            "carries a secret (registry token, signing key, API key), "
            "that secret lives forever in the published image. "
            "Framework-conventional public prefixes "
            "(`NEXT_PUBLIC_`, `VITE_`, `REACT_APP_`, `EXPO_PUBLIC_`) "
            "downgrade the severity since they are intentionally "
            "browser-side."
        ),
        # Stage-A anchor pattern — Pass 1 of the two-pass detector
        # collects ARG names; Pass 2 runs per-ARG patterns built by
        # `_env_propagation_pattern` and is not stored in `pattern`.
        pattern=_ARG_NAME_CAPTURE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="container-apt-source-check-valid-until-no-signed-by",
        name="apt deb source disables check-valid-until without signed-by keyring pinning",
        severity="MAJOR",
        description=(
            "A Dockerfile (or a script COPY'd into one) writes a "
            "`deb` apt source line containing "
            "`[check-valid-until=no]` (disables apt's freshness "
            "check) but does NOT pair it with `[signed-by="
            "/path/to/keyring]`. The combination lets a network "
            "attacker serve a stale-but-still-signed archive, "
            "bypassing the signature-expiry guard. Pin the keyring "
            "explicitly via `signed-by=/usr/share/keyrings/...` "
            "alongside any `check-valid-until=no`."
        ),
        pattern=_APT_DEB_LINE_NO_SIGNED_BY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="container-compose-image-mutable-label",
        name="docker-compose image: uses a mutable label tag",
        severity="MAJOR",
        description=(
            "`docker-compose.yml` / `compose.yaml` declares "
            "`image: <name>:latest` (or any mutable label like "
            "`:lts`, `:edge`, `:rolling`, `:stable`) under a "
            "`services.<name>.` block. Compose's `image:` is the "
            "runtime image reference, NOT a build-time layer — "
            "Wave-24's `FROM`-only check does not fire here. "
            "Disjoint surface, same anti-pattern."
        ),
        pattern=_COMPOSE_IMAGE_MUTABLE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="container-package-install-no-version-pin",
        name="RUN package-install lacks a version pin — silent drift on rebuild",
        severity="MAJOR",
        description=(
            "A `RUN` directive invokes a package-manager install "
            "command (`apk add`, `apt-get install`, `pip install`, "
            "`npm install -g`) where the package list contains at "
            "least one entry without a version constraint. Rebuilds "
            "a year later silently drift to a newer (or "
            "backwards-incompatible) version. Pin every package: "
            "`apk add pkg=ver`, `apt-get install pkg=ver`, "
            "`pip install pkg==ver`, `npm install -g pkg@ver`. "
            "Rolling-by-design packages (e.g. `ca-certificates`) "
            "are an exception — suppress with "
            "`# dockerfile-justification: ca-certificates-rolling`."
        ),
        pattern=_APK_ADD_UNPINNED,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


def _looks_like_dockerfile(text: str) -> bool:
    """True if the text contains at least one FROM directive at line
    start. Used by P3 / P4 / P6 / P7 / P11 to avoid firing on
    non-Dockerfile content (e.g. shell scripts that happen to contain
    the word `CMD`)."""
    return _DOCKERFILE_FROM_LINE.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Per-rule context:

      * P1 (from-tag-mutable-label) — direct regex match on FROM line.
      * P2 (copy-from-external-image-no-digest) — direct regex match
        on COPY --from= line; the negated-class on `[^@\\n]*` enforces
        "no digest on the same line".
      * P3 (no-user-directive) — file-level absence detector. Emits
        one finding at the first FROM if no USER directive exists
        anywhere in the file. Suppression marker:
        `# dockerfile-justification: base-image-non-root`.
      * P4 (cmd-shell-form) — direct regex match on CMD/ENTRYPOINT
        line that does NOT start with `[`.
      * P5 (copy-root-no-dockerignore) — regex emits finding on every
        `COPY . .` line. Caller pairs with a filesystem-side
        `.dockerignore` presence check.
      * P6 (add-remote-url) — fires on ADD with http/https/ftp/git
        URL UNLESS the same line carries a `--checksum=sha...` flag.
      * P7 (no-healthcheck) — file-level: fires on every EXPOSE line
        if no HEALTHCHECK is present anywhere in the file.
      * P8 (arg-env-secret-propagation) — two-pass: collect ARG names,
        then for each name look for a matching ENV propagation line.
      * P9 (apt-source-check-valid-until-no-signed-by) — fires on
        `deb [...check-valid-until=no...]` line that does NOT carry
        `signed-by=` inside the same `[...]` block.
      * P10 (compose-image-mutable-label) — fires on `image: x:latest`
        in any file that contains a compose-shape marker
        (`services:`, `version:`, `networks:`, `volumes:`).
      * P11 (package-install-no-version-pin) — family-specific
        regexes for apk add / apt-get install / pip install /
        npm install -g, each suppressed by the per-RUN
        `# dockerfile-justification:` marker on the same line.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    is_dockerfile_shape = _looks_like_dockerfile(text)

    # ---- P1 : container-from-tag-mutable-label ----
    rule_p1 = rule_by_id["container-from-tag-mutable-label"]
    for m in _FROM_MUTABLE_TAG.finditer(text):
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : container-copy-from-external-image-no-digest ----
    rule_p2 = rule_by_id["container-copy-from-external-image-no-digest"]
    for m in _COPY_FROM_EXTERNAL_NO_DIGEST.finditer(text):
        ref = m.group(1)
        # Suppress bare stage-name references (no `/` and no `:`).
        # Our regex already rejects those via the alternation, but a
        # paranoid double-check keeps the rule robust under future
        # alternation edits.
        if "/" not in ref and ":" not in ref:
            continue
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : container-no-user-directive ----
    # File-level absence detector. Only meaningful for Dockerfile-shape
    # bodies. The justification marker carve-out lets the operator
    # acknowledge a non-root base image.
    if is_dockerfile_shape:
        rule_p3 = rule_by_id["container-no-user-directive"]
        has_user = _file_contains(text, _DOCKERFILE_USER_LINE)
        has_justification = _file_contains(text, _DOCKERFILE_JUSTIFICATION_MARKER)
        if not has_user and not has_justification:
            # Emit at the first FROM line — that's the conceptual
            # location of the missing USER directive.
            first_from = _DOCKERFILE_FROM_LINE.search(text)
            if first_from is not None:
                _emit(rule_p3, first_from.start(), first_from.group(0))

    # ---- P4 : container-cmd-shell-form ----
    # Only fire inside Dockerfile-shape bodies to avoid spurious hits
    # on shell scripts that contain bare `CMD foo` text.
    if is_dockerfile_shape:
        rule_p4 = rule_by_id["container-cmd-shell-form"]
        for m in _CMD_OR_ENTRYPOINT_SHELL_FORM.finditer(text):
            _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : container-copy-root-no-dockerignore ----
    # Regex-only stage. Filesystem-side .dockerignore check is the
    # caller's responsibility.
    if is_dockerfile_shape:
        rule_p5 = rule_by_id["container-copy-root-no-dockerignore"]
        for m in _COPY_DOT_TO_DOT.finditer(text):
            _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : container-add-remote-url ----
    if is_dockerfile_shape:
        rule_p6 = rule_by_id["container-add-remote-url"]
        for m in _ADD_REMOTE_URL.finditer(text):
            # Extract just the matched ADD line for the checksum check.
            line, _col = _line_col(text, m.start())
            parts = text.split("\n")
            if 1 <= line <= len(parts):
                line_text = parts[line - 1]
                if _ADD_CHECKSUM_PRESENT.search(line_text) is not None:
                    continue
            _emit(rule_p6, m.start(), m.group(0))

    # ---- P7 : container-no-healthcheck ----
    if is_dockerfile_shape:
        rule_p7 = rule_by_id["container-no-healthcheck"]
        has_healthcheck = _file_contains(text, _DOCKERFILE_HEALTHCHECK_LINE)
        has_justification = _file_contains(text, _DOCKERFILE_JUSTIFICATION_MARKER)
        if not has_healthcheck and not has_justification:
            for m in _DOCKERFILE_EXPOSE_LINE.finditer(text):
                _emit(rule_p7, m.start(), m.group(0))
                # Only need one finding per file — break after first.
                break

    # ---- P8 : container-arg-env-secret-propagation ----
    if is_dockerfile_shape:
        rule_p8 = rule_by_id["container-arg-env-secret-propagation"]
        for arg_match in _ARG_NAME_CAPTURE.finditer(text):
            arg_name = arg_match.group(1)
            env_pat = _env_propagation_pattern(arg_name)
            env_match = env_pat.search(text)
            if env_match is None:
                continue
            # Public-prefix carve-out — fire at LOW severity by
            # emitting a synthetic finding with downgraded text. We
            # still emit so the operator sees the propagation; the
            # description field flags the intentional public case.
            # The catalogue rule itself stays CRITICAL — the carve-out
            # is reflected in the matched_text snippet only.
            if _PUBLIC_PREFIX.match(arg_name):
                # Skip — framework-public env vars are intentional.
                continue
            _emit(rule_p8, env_match.start(), env_match.group(0))

    # ---- P9 : container-apt-source-check-valid-until-no-signed-by ----
    rule_p9 = rule_by_id["container-apt-source-check-valid-until-no-signed-by"]
    for m in _APT_DEB_LINE_NO_SIGNED_BY.finditer(text):
        # Extract the matched line to test for signed-by= within the
        # same [...] block.
        matched_line = m.group(0)
        if _APT_SIGNED_BY_MARKER.search(matched_line) is not None:
            continue
        _emit(rule_p9, m.start(), matched_line)

    # ---- P10 : container-compose-image-mutable-label ----
    # Only fire in compose-shape files (presence of services/version/
    # networks/volumes top-level keys). This excludes Helm values.yaml
    # and arbitrary YAML files that happen to share the `image:` key.
    is_compose_shape = _file_contains(text, _COMPOSE_FILE_MARKER)
    if is_compose_shape:
        rule_p10 = rule_by_id["container-compose-image-mutable-label"]
        for m in _COMPOSE_IMAGE_MUTABLE.finditer(text):
            _emit(rule_p10, m.start(), m.group(0))

    # ---- P11 : container-package-install-no-version-pin ----
    if is_dockerfile_shape:
        rule_p11 = rule_by_id["container-package-install-no-version-pin"]
        parts = text.split("\n")
        for family_pat in (
            _APK_ADD_UNPINNED,
            _APT_GET_INSTALL_UNPINNED,
            _PIP_INSTALL_UNPINNED,
            _NPM_INSTALL_G_UNPINNED,
        ):
            for m in family_pat.finditer(text):
                line, _col = _line_col(text, m.start())
                if 1 <= line <= len(parts):
                    line_text = parts[line - 1]
                    if _DOCKERFILE_JUSTIFICATION_MARKER.search(line_text) is not None:
                        continue
                _emit(rule_p11, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
