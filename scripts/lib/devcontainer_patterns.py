"""Devcontainer / GitHub Codespaces configuration security patterns.

Wave-31 distillation round 17, angle: GitHub Codespaces / Devcontainer /
VS Code Dev Container.

Catalogue of 7 devcontainer-specific anti-patterns distilled in
`reports/distill-round-17/devcontainer-codespaces.md`. Targets
`.devcontainer/devcontainer.json` surfaces that existing modules cover only
at the CLI flag layer (shell scripts, docker-compose, Dockerfile syntax).

What is NOT here (already shipped — DO NOT duplicate):

  * `initializeCommand`, `postCreateCommand: "curl-piped-to-bash"`, untrusted
    `features:` registries, `$localEnv:` exfiltration in containerEnv
    values — `container_patterns.py` Rule 5.
  * `docker run --privileged`, `--volume /var/run/docker.sock` at CLI
    layer — `container_runtime_patterns.py`.
  * GitHub Actions GITHUB_TOKEN scope in workflow YAML —
    `gha_tokens_deeper_patterns.py`.
  * `docker-compose.yml` privileged/socket mounts —
    `sandbox_escape_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * dvc-runargs-privileged                       (CRITICAL)
  * dvc-mounts-docker-sock                       (CRITICAL)
  * dvc-forwardports-ssh                         (HIGH)
  * dvc-containerenv-literal-token               (HIGH)
  * dvc-image-unpinned-mutable-tag               (HIGH)
  * dvc-vscode-extension-wildcard-activation     (MEDIUM)
  * dvc-codespaces-secret-broad-scope-env        (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Credential exposure / broken access control (committed secrets,
            docker.sock passthrough, broad-scope tokens)
  ASI-05 — Security misconfiguration (privileged container, SSH forward,
            cross-tenant access)
  ASI-06 — Vulnerable and outdated components (mutable unpinned image tags)
  ASI-08 — Software and data integrity failures (untrusted extension auto-install)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : dvc-runargs-privileged ----------------------------------------

# Matches the `runArgs` JSON array key followed by an array literal containing
# `"--privileged"` as a string element.  Bounded [^\]]{0,600}? prevents
# catastrophic backtracking; the \] stop-char is safe because JSON string
# values cannot contain an unescaped ].
_RUNARGS_PRIVILEGED = _re(
    r'"runArgs"\s*:\s*\[[^\]]{0,600}?"--privileged"[^\]]{0,600}?\]'
)

# ---- D2 : dvc-mounts-docker-sock ----------------------------------------

# Matches the `mounts` JSON array containing /var/run/docker.sock.
# Escaped \. prevents matching /var/run/docker_sock (underscore variant).
# Upper-bounded quantifiers prevent runaway backtracking.
_MOUNTS_DOCKER_SOCK = _re(
    r'"mounts"\s*:\s*\[[^\]]{0,800}?/var/run/docker\.sock[^\]]{0,800}?\]'
)

# ---- D3 : dvc-forwardports-ssh ------------------------------------------

# Matches `forwardPorts` arrays containing the integer 22.
# \b word-boundary anchors prevent matching 22 inside numbers like 2200 or 8022.
_FORWARDPORTS_SSH = _re(
    r'"forwardPorts"\s*:\s*\[[^\]]{0,300}?\b22\b[^\]]{0,300}?\]'
)

# ---- D4 : dvc-containerenv-literal-token --------------------------------

# Matches `containerEnv` or `remoteEnv` blocks containing a key whose name
# matches known secret-bearing variable names, followed by a value that looks
# like a 20+ char token literal (alphanumeric with optional _/+=-).
_CONTAINERENV_LITERAL_TOKEN = _re(
    r'"(?:containerEnv|remoteEnv)"\s*:\s*\{[^}]{0,2000}?'
    r'"(?:GITHUB_TOKEN|GH_TOKEN|NPM_TOKEN|PYPI_TOKEN|AWS_SECRET(?:_ACCESS_KEY)?'
    r'|API_KEY|SECRET_KEY|ACCESS_TOKEN|PRIVATE_KEY)"\s*:\s*'
    r'"[A-Za-z0-9_/+=-]{20,200}"'
)

# ---- D5 : dvc-image-unpinned-mutable-tag --------------------------------

# Primary: `image` field with an explicitly mutable tag (latest, edge, dev,
# main, master, nightly, unstable).
_IMAGE_UNPINNED_MUTABLE_TAG = _re(
    r'"image"\s*:\s*"[^"]{1,300}:(?:latest|edge|dev|main|master|nightly|unstable)"'
)

# ---- D6 : dvc-vscode-extension-wildcard-activation ----------------------

# Suspiciously short publisher namespace (1-2 chars) in the
# `customizations.vscode.extensions` array — resembles typosquat or
# namespace-squatting registrations.
_VSCODE_EXTENSION_SHORT_PUBLISHER = _re(
    r'"extensions"\s*:\s*\[[^\]]{0,1000}?"[a-z]{1,2}\.[a-z][a-z0-9_-]{1,60}"'
    r'[^\]]{0,1000}?\]'
)

# ---- D7 : dvc-codespaces-secret-broad-scope-env -------------------------

# Matches `containerEnv`/`remoteEnv` blocks containing a key whose name
# matches broad-scope token naming patterns (org-admin-level or repo-admin).
_CODESPACES_SECRET_BROAD_SCOPE = _re(
    r'"(?:containerEnv|remoteEnv)"\s*:\s*\{[^}]{0,2000}?'
    r'"(?:GITHUB_TOKEN|GH_TOKEN|ORG_TOKEN|ADMIN_TOKEN|PAT_ALL|REPO_PAT|GH_ADMIN)[^"]{0,60}"'
    r'\s*:\s*"[^"]{1,300}"'
)

# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="dvc-runargs-privileged",
        name="devcontainer.json runArgs contains --privileged flag",
        severity="CRITICAL",
        description=(
            "The `runArgs` array in devcontainer.json includes `--privileged`, "
            "which grants the container full access to all Linux kernel capabilities "
            "and removes the default seccomp, AppArmor, and SELinux profiles. "
            "This effectively makes the container a root shell on the host. Unlike a "
            "rogue `docker run` in a script, this vector persists silently in a JSON "
            "config file that VS Code and GitHub Codespaces execute automatically on "
            "'Reopen in Container' — every team member who opens the repo inherits "
            "the privilege escalation."
        ),
        pattern=_RUNARGS_PRIVILEGED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dvc-mounts-docker-sock",
        name="devcontainer.json mounts /var/run/docker.sock into container",
        severity="CRITICAL",
        description=(
            "The `mounts` array in devcontainer.json binds `/var/run/docker.sock` "
            "into the container, giving any process inside full unauthenticated access "
            "to the host Docker daemon — equivalent to a root shell on the host. "
            "Combined with VS Code extensions and lifecycle hooks running inside the "
            "container, this attack surface is activated automatically every time a "
            "developer opens the project."
        ),
        pattern=_MOUNTS_DOCKER_SOCK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dvc-forwardports-ssh",
        name="devcontainer.json forwardPorts exposes SSH port 22",
        severity="HIGH",
        description=(
            "Port 22 (SSH) is listed in `forwardPorts` in devcontainer.json, "
            "making the container's SSH daemon reachable from the internet via "
            "Codespaces port forwarding (or from the local machine). Codespaces "
            "applies a JWT-gated auth layer, but that protection is removed when "
            "port visibility is set to 'public' — a single UI click with no PR "
            "review required. An SSH server on port 22 with public visibility "
            "is effectively a persistent backdoor."
        ),
        pattern=_FORWARDPORTS_SSH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dvc-containerenv-literal-token",
        name="devcontainer.json containerEnv contains a hardcoded token literal",
        severity="HIGH",
        description=(
            "A known secret-bearing environment variable key (GITHUB_TOKEN, "
            "NPM_TOKEN, AWS_SECRET_ACCESS_KEY, API_KEY, etc.) has a 20+ character "
            "literal value committed inside `containerEnv` or `remoteEnv`. Every "
            "clone, fork, and Codespaces instance created from the repo inherits "
            "the plaintext token. GitHub's recommended pattern for Codespaces secrets "
            "is the Secrets UI (org/repo settings), not hardcoded values in "
            "devcontainer.json."
        ),
        pattern=_CONTAINERENV_LITERAL_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dvc-image-unpinned-mutable-tag",
        name="devcontainer.json image field uses a mutable tag instead of a digest",
        severity="HIGH",
        description=(
            "The `image` field in devcontainer.json references an image with a mutable "
            "tag (`:latest`, `:edge`, `:dev`, `:main`, `:master`, `:nightly`, "
            "`:unstable`) instead of a digest-pinned reference (`@sha256:<hash>`). "
            "Every 'Reopen in Container' or Codespace creation pulls whatever the "
            "registry currently serves under that tag — enabling supply-chain attacks "
            "where a compromised registry push silently replaces the developer "
            "environment with a malicious image."
        ),
        pattern=_IMAGE_UNPINNED_MUTABLE_TAG,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="dvc-vscode-extension-wildcard-activation",
        name="devcontainer.json auto-installs extension with suspiciously short publisher namespace",
        severity="MEDIUM",
        description=(
            "The `customizations.vscode.extensions` array in devcontainer.json "
            "includes an extension whose publisher namespace is 1-2 characters long — "
            "a shape typical of typosquat or namespace-squatting registrations. "
            "Extensions installed in a Codespace have full container filesystem access, "
            "can execute arbitrary shell commands, read environment variables including "
            "tokens from containerEnv, and make network requests. Auto-installed "
            "extensions bypass the user's explicit 'Trust this extension' flow."
        ),
        pattern=_VSCODE_EXTENSION_SHORT_PUBLISHER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="dvc-codespaces-secret-broad-scope-env",
        name="devcontainer.json containerEnv/remoteEnv contains a broad-scope token name",
        severity="HIGH",
        description=(
            "The `containerEnv` or `remoteEnv` block in devcontainer.json sets a key "
            "matching known broad-scope token naming patterns (GITHUB_TOKEN, GH_TOKEN, "
            "ORG_TOKEN, ADMIN_TOKEN, PAT_ALL, REPO_PAT, GH_ADMIN). Lifecycle hooks "
            "(`postCreateCommand`, `onCreateCommand`) and all extensions automatically "
            "inherit every variable in these blocks — meaning a broad-scope token "
            "intended for a single `git clone` step is available to every terminal "
            "session and every auto-installed extension."
        ),
        pattern=_CODESPACES_SECRET_BROAD_SCOPE,
        owasp_asi="ASI-02",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Each rule's compiled pattern is searched directly against the full text.
    Findings are deduped by (rule_id, line, col) and returned in
    (line, column) order.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
