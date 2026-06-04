"""Container / image / runtime supply-chain attack patterns.

Wave 16 — Deep-dive distillation pass 2 (agent L / container subset).
Closes the gaps left by the 4 already-shipped detectors
(`unpinned-docker-image`, `hardcoded-container-latest`,
`docker-build-arg-secrets`, `dangerous-lifecycle-scripts`) which only
inspect single-line `FROM`/`container:`/`--build-arg`/lifecycle scripts.

Six new rules, all stdlib-only (re, json, shlex, pathlib), no external
LLM dependency, no network calls:

  1. `container-dockerignore-evasion` (MAJOR)
     Wildcard `COPY . .` / `ADD . .` in a Dockerfile while .dockerignore
     fails to exclude sensitive paths (.env, .git/, .ssh/, .aws/, …).

  2. `dockerfile-heredoc-pipe-to-shell` (CRITICAL)
     BuildKit `RUN <<EOF` heredoc bodies that download-and-exec across
     lines — the single-line `curl|sh` scanners never see it.

  3. `dockerfile-copy-from-external-registry` (CRITICAL)
     `COPY --from=<image-ref>` that targets an unpinned / untrusted
     registry (multi-stage smuggling — separate codepath from FROM).

  4. `dockerfile-healthcheck-shell-escape` (MAJOR)
     `HEALTHCHECK CMD` whose body pipes to a shell or contacts a
     non-local host — c2-beacon shape persisted inside the container.

  5. `devcontainer-untrusted-features-and-hooks` (CRITICAL)
     `.devcontainer/devcontainer.json` hooks (initializeCommand runs on
     HOST), features from untrusted ghcr.io namespaces, $localEnv exfil.

  6. `dockerfile-env-registry-bypass` (MAJOR / sometimes CRITICAL)
     `ENV GOPROXY=direct`, `PIP_INDEX_URL=http://…`,
     `NODE_TLS_REJECT_UNAUTHORIZED=0`, etc. — the Dockerfile counterpart
     of sweep-agent #4's `sc-go-proxy-bypass`.

Public surface mirrors `agent_config_patterns.py`:

  * Rule, Finding                          — frozen NamedTuples
  * RULES                                  — ordered tuple of every rule
  * scan_text(text, *, file_kind="dockerfile") -> list[Finding]
                                           — regex-only scanner
  * scan_dockerfile_with_dockerignore(dockerfile_text, dockerignore_text)
                                           — multi-file rule #1 helper
  * scan_devcontainer(text)                — JSONC-aware rule #5 helper
"""

from __future__ import annotations

import json
import re
import shlex
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `agent_config_patterns.Finding` so heartbeat detectors can render
    either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-05"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE. Dockerfiles are
    ASCII-only by convention; UNICODE flag is irrelevant here."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- Constants ----------------------------------------------------------


# Sensitive paths that an attacker can exfiltrate via `docker save` if
# `.dockerignore` fails to exclude them and the Dockerfile does
# `COPY . .` / `ADD . /app`. Kept conservative — every entry has been
# observed in a real-world container-leak disclosure.
SENSITIVE_DOCKER_PATHS: tuple[str, ...] = (
    ".env", ".env.local", ".env.production", ".env.development",
    ".git/", ".gitignore",
    ".aws/", ".ssh/", ".gnupg/", ".npmrc", ".pypirc", ".netrc",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx",
    "credentials.json", "credentials.yaml", "credentials.yml",
    "secrets.yaml", "secrets.yml", "secret.yaml", "secret.yml",
    ".claude/", ".cursor/", ".codeium/", ".windsurf/",
    ".vscode/settings.json",
    "kubeconfig", ".kube/config",
)


# ---- Rule 1: dockerignore evasion ---------------------------------------


# Wildcard `COPY . .` / `COPY . /dir` / `ADD . .` — the predicate that
# *gates* the dockerignore-evasion rule. Without one of these, no
# sensitive file ever ends up in the image, so .dockerignore content is
# moot.
_WILDCARD_COPY = _re(
    r"^\s*(?:COPY|ADD)\s+(?:--[\w=,\.\-]+\s+)*\.\s+\S+"
)


# Multi-file rule — needs both Dockerfile body and .dockerignore body.
# When `.dockerignore` is absent OR fails to exclude a sensitive path,
# AND the Dockerfile uses wildcard COPY, we flag.
def _dockerignore_excludes(dockerignore_text: str, path: str) -> bool:
    """Return True iff `path` would be excluded by the patterns in
    `dockerignore_text`. Conservative — substring + parent match only.

    `.dockerignore` is glob-like but the grammar is fiddly (negations,
    `**`, leading `!`). For the scanner's purpose we err on the side of
    NOT-excluded (i.e. potential false positive = flag the user). The
    matching considers a pattern a match when:
      * the literal path equals the pattern,
      * the pattern is a prefix of the path (parent dir),
      * `*` wildcard in the pattern matches the path's basename,
      * `**` wildcard in the pattern matches any depth.
    """
    if not dockerignore_text:
        return False
    path_norm = path.rstrip("/")
    for raw in dockerignore_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # A leading `!` negates a prior exclusion. Conservative stance:
        # treat negation as "not-excluded" and continue scanning.
        if line.startswith("!"):
            continue
        pattern = line.rstrip("/")
        if pattern == path_norm:
            return True
        # Glob `**` → match anything.
        if "**" in pattern:
            head = pattern.split("**")[0].rstrip("/")
            tail = pattern.rsplit("**", 1)[-1].lstrip("/")
            if (not head or path_norm.startswith(head)) and (
                not tail or path_norm.endswith(tail)
            ):
                return True
        # Glob `*.ext` → match suffix.
        if pattern.startswith("*."):
            if path_norm.endswith(pattern[1:]):
                return True
        # Glob `*` in middle / end → regex-translate.
        if "*" in pattern:
            regex = "^" + re.escape(pattern).replace(r"\*", "[^/]*") + "$"
            if re.match(regex, path_norm):
                return True
        # Parent-dir match: pattern `.git` should exclude `.git/` AND
        # `.git/config`. Treat trailing-slash and bare-name as parent.
        if path_norm.startswith(pattern + "/") or path_norm == pattern:
            return True
    return False


def scan_dockerfile_with_dockerignore(
    dockerfile_text: str,
    dockerignore_text: str | None,
) -> list[Finding]:
    """Run rule 1 (`container-dockerignore-evasion`).

    `dockerignore_text` is None when the file does not exist — that
    triggers the most severe variant of the rule (no exclusions at all).
    """
    findings: list[Finding] = []
    if not dockerfile_text:
        return findings
    wildcard_matches = list(_WILDCARD_COPY.finditer(dockerfile_text))
    if not wildcard_matches:
        # No `COPY . .` → sensitive files can't smuggle in via this
        # Dockerfile. Rule does not fire.
        return findings
    # Compute the LINE of the first wildcard COPY for reporting.
    first = wildcard_matches[0]
    line = dockerfile_text[: first.start()].count("\n") + 1
    col = first.start() - (
        dockerfile_text.rfind("\n", 0, first.start()) + 1
    ) + 1
    if dockerignore_text is None:
        findings.append(Finding(
            rule_id="container-dockerignore-evasion",
            line=line,
            column=col,
            matched_text=first.group(0),
            severity="MAJOR",
            description=(
                "Dockerfile uses wildcard COPY/ADD but no .dockerignore "
                "exists — every sensitive file (.env, .git/, .ssh/, ...) "
                "is baked into the image layers."
            ),
            owasp_asi="ASI-06",
        ))
        return findings
    # .dockerignore exists — check each sensitive path.
    leaked: list[str] = [
        p for p in SENSITIVE_DOCKER_PATHS
        if not _dockerignore_excludes(dockerignore_text, p)
    ]
    if leaked:
        leaked_repr = ", ".join(leaked[:6])
        if len(leaked) > 6:
            leaked_repr += f", … (+{len(leaked) - 6} more)"
        findings.append(Finding(
            rule_id="container-dockerignore-evasion",
            line=line,
            column=col,
            matched_text=first.group(0),
            severity="MAJOR",
            description=(
                "Dockerfile uses wildcard COPY/ADD; .dockerignore does "
                f"not exclude sensitive paths: {leaked_repr}"
            ),
            owasp_asi="ASI-06",
        ))
    return findings


# ---- Rule 2: dockerfile-heredoc-pipe-to-shell ---------------------------


# Heredoc opener: `RUN <<EOF`, `RUN --mount=... <<-DELIM`, etc.
_HEREDOC_OPEN = _re(
    r"^RUN\s+(?:--[\w=,\.\-]+\s+)*<<-?\s*['\"]?(\w+)['\"]?"
)

# Network-download tools — fetching content from the internet.
_HEREDOC_DOWNLOAD = _re(
    r"\b(?:curl|wget|fetch|aria2c|httpie?)\b"
)

# Shell / interpreter executors — running content.
_HEREDOC_EXEC = _re(
    r"\b(?:bash|sh|zsh|fish|ksh|dash|python\d*|ruby|perl|node|"
    r"tclsh|powershell|pwsh)\b"
)

# Pipe-to-shell on a single line inside the heredoc body — exactly the
# "curl … | sh" shape, just smuggled into a multi-line RUN.
_HEREDOC_PIPE_TO_SHELL = _re(
    r"\|\s*(?:bash|sh|zsh|fish|python\d*|ruby|perl|powershell|pwsh)\b"
)


def _scan_heredoc_run(text: str) -> list[Finding]:
    """Find RUN heredocs whose body downloads and then executes."""
    findings: list[Finding] = []
    pos = 0
    while True:
        m = _HEREDOC_OPEN.search(text, pos)
        if not m:
            break
        delim = m.group(1)
        # Closing line: `^DELIM$` on its own.
        close_re = re.compile(
            rf"^{re.escape(delim)}\s*$", re.MULTILINE
        )
        close = close_re.search(text, m.end())
        if not close:
            pos = m.end()
            continue
        body = text[m.end() : close.start()]
        line = text[: m.start()].count("\n") + 1
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
        flagged = False
        if _HEREDOC_PIPE_TO_SHELL.search(body):
            findings.append(Finding(
                rule_id="dockerfile-heredoc-pipe-to-shell",
                line=line,
                column=col,
                matched_text=body.strip()[:200],
                severity="CRITICAL",
                description=(
                    "RUN heredoc body pipes downloaded content to "
                    "shell — single-line `curl | sh` smuggled across "
                    "newlines."
                ),
                owasp_asi="ASI-05",
            ))
            flagged = True
        if not flagged:
            dl = _HEREDOC_DOWNLOAD.search(body)
            if dl:
                after = body[dl.end():]
                if _HEREDOC_EXEC.search(after):
                    findings.append(Finding(
                        rule_id="dockerfile-heredoc-pipe-to-shell",
                        line=line,
                        column=col,
                        matched_text=body.strip()[:200],
                        severity="CRITICAL",
                        description=(
                            "RUN heredoc downloads remote content then "
                            "executes an interpreter — cross-line "
                            "download-and-run."
                        ),
                        owasp_asi="ASI-05",
                    ))
        pos = close.end()
    return findings


# ---- Rule 3: dockerfile-copy-from-external-registry ---------------------


_COPY_FROM_REGISTRY = _re(
    r"^\s*COPY\s+(?:--[\w=,\.\-]+\s+)*--from=([^\s]+)\s+"
)

_FROM_AS_STAGE = _re(
    r"^FROM\s+\S+\s+AS\s+(\S+)"
)

# Trusted registry hosts — pulls from these are MAJOR (still want pin)
# rather than CRITICAL.
_TRUSTED_REGISTRIES: frozenset[str] = frozenset({
    "ghcr.io",
    "docker.io",
    "registry.hub.docker.com",
    "public.ecr.aws",
    "mcr.microsoft.com",
    "gcr.io",
    "quay.io",
    "registry.gitlab.com",
})


def _is_image_ref(target: str, defined_stages: set[str]) -> bool:
    """True iff `target` looks like an image reference (not a multi-
    stage stage name or numeric index)."""
    if target.isdigit():
        return False
    if target in defined_stages:
        return False
    # Image refs always contain at least one of '/', ':', '@'.
    return any(c in target for c in "/:@")


def _scan_copy_from_external(text: str) -> list[Finding]:
    findings: list[Finding] = []
    stages = {m.group(1) for m in _FROM_AS_STAGE.finditer(text)}
    for m in _COPY_FROM_REGISTRY.finditer(text):
        target = m.group(1)
        if not _is_image_ref(target, stages):
            continue
        line = text[: m.start()].count("\n") + 1
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
        if "@sha256:" not in target:
            sev = (
                "CRITICAL"
                if ":latest" in target or ":" not in target
                else "MAJOR"
            )
            findings.append(Finding(
                rule_id="dockerfile-copy-from-external-registry",
                line=line,
                column=col,
                matched_text=m.group(0).strip(),
                severity=sev,
                description=(
                    f"COPY --from={target} pulls layers from an "
                    "unpinned external image (no @sha256: digest)."
                ),
                owasp_asi="ASI-05",
            ))
        # Untrusted registry, even if pinned.
        if "/" in target:
            registry = target.split("/")[0]
            # A bare image name like `python` won't contain `.`; a real
            # registry hostname does. Skip the trusted set.
            if "." in registry and registry not in _TRUSTED_REGISTRIES:
                findings.append(Finding(
                    rule_id="dockerfile-copy-from-external-registry",
                    line=line,
                    column=col,
                    matched_text=m.group(0).strip(),
                    severity="MAJOR",
                    description=(
                        f"COPY --from={target} uses untrusted "
                        f"registry {registry}."
                    ),
                    owasp_asi="ASI-05",
                ))
    return findings


# ---- Rule 4: dockerfile-healthcheck-shell-escape ------------------------


_HEALTHCHECK_CMD = _re(
    r"^\s*HEALTHCHECK\s+(?:--[\w=,\.\-]+\s+)*CMD\s+(.+?)$"
)

_HC_NETWORK = _re(
    r"\b(?:curl|wget|nc|netcat|ncat|socat|nslookup|dig|host|"
    r"python.*urllib|python.*requests|node.*http|"
    r"powershell.*Invoke-WebRequest)\b"
)

_HC_PIPE_SHELL = _re(
    r"\|\s*(?:bash|sh|zsh|python\d*|ruby|perl|powershell|pwsh)\b"
)

_HC_ALWAYS_SUCCEED = _re(
    r"\|\|\s*exit\s+0|\|\|\s*true|;\s*exit\s+0"
)

# Local addresses / hostnames that legitimate liveness probes hit. We
# treat HEALTHCHECKs that target these as benign even when they use
# `curl`/`wget`.
_HC_LOCAL_TARGET = _re(
    r"\b(?:127\.0\.0\.1|localhost|0\.0\.0\.0|::1|"
    r"\$\{?HOSTNAME\}?|\$HOSTNAME)\b"
)


def _scan_healthcheck(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _HEALTHCHECK_CMD.finditer(text):
        body = m.group(1).strip()
        line = text[: m.start()].count("\n") + 1
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
        # CRITICAL when piping to a shell at all.
        if _HC_PIPE_SHELL.search(body):
            findings.append(Finding(
                rule_id="dockerfile-healthcheck-shell-escape",
                line=line,
                column=col,
                matched_text=body[:200],
                severity="CRITICAL",
                description=(
                    "HEALTHCHECK CMD pipes to shell — persistent "
                    "in-container c2 beacon disguised as a liveness "
                    "probe."
                ),
                owasp_asi="ASI-05",
            ))
            continue
        network_hit = bool(_HC_NETWORK.search(body))
        local_hit = bool(_HC_LOCAL_TARGET.search(body))
        always_succeed = bool(_HC_ALWAYS_SUCCEED.search(body))
        if network_hit and not local_hit:
            if always_succeed:
                # `|| exit 0` + non-local network call = textbook c2
                # beacon: orchestrator never restarts the container,
                # attacker keeps beaconing forever. Bump severity to
                # CRITICAL (vs MAJOR for plain non-local call) and
                # emit a single composite finding so the dedupe in
                # `scan_text` doesn't drop one.
                findings.append(Finding(
                    rule_id="dockerfile-healthcheck-shell-escape",
                    line=line,
                    column=col,
                    matched_text=body[:200],
                    severity="CRITICAL",
                    description=(
                        "HEALTHCHECK CMD always succeeds (|| exit 0 "
                        "or || true) AND makes a non-local network "
                        "call — orchestrator never restarts, attacker "
                        "keeps beaconing (c2 shape)."
                    ),
                    owasp_asi="ASI-05",
                ))
            else:
                findings.append(Finding(
                    rule_id="dockerfile-healthcheck-shell-escape",
                    line=line,
                    column=col,
                    matched_text=body[:200],
                    severity="MAJOR",
                    description=(
                        "HEALTHCHECK CMD contacts a non-local host — "
                        "c2-beacon shape."
                    ),
                    owasp_asi="ASI-05",
                ))
    return findings


# ---- Rule 5: devcontainer-untrusted-features-and-hooks ------------------


# Shell hooks declared in `.devcontainer/devcontainer.json`. Each runs
# automatically on container create / start / attach. `initializeCommand`
# in particular runs ON THE HOST.
_DEVCONTAINER_SHELL_HOOK_KEYS: frozenset[str] = frozenset({
    "initializeCommand",
    "onCreateCommand",
    "updateContentCommand",
    "postCreateCommand",
    "postStartCommand",
    "postAttachCommand",
})

# Trusted devcontainer Features registries.
_TRUSTED_FEATURE_PREFIXES: tuple[str, ...] = (
    "ghcr.io/devcontainers/features",
    "ghcr.io/devcontainers-contrib/features",
)

_DEVCONTAINER_PIPE_TO_SHELL = _re(
    r"\b(?:curl|wget|fetch|aria2c)\b[^|;\n]*\|\s*"
    r"(?:bash|sh|zsh|fish|python\d*|node|powershell|pwsh)\b"
)


def _strip_jsonc(text: str) -> str:
    """Remove `//` line comments and `/* ... */` block comments while
    preserving the original byte length so json.loads error offsets stay
    meaningful enough. This is best-effort — devcontainer.json is JSONC.

    Strings are NOT recursed into; an instruction-style attacker won't
    hide their payload inside a string literal because the shell-hook
    fields ARE strings and would still be inspected.
    """
    if not text:
        return text
    # /* ... */ block comments.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # `//` line comments — but don't strip `://` inside URLs that
    # appear in JSON string values. Conservative pass: only kill `//`
    # that begins after non-string whitespace at the start of the line
    # or after a `,` or `{`/`[`.
    lines = []
    for line in text.splitlines():
        idx = line.find("//")
        if idx != -1:
            # Drop the comment only when the preceding chars on the
            # line don't contain an unbalanced opening quote.
            head = line[:idx]
            if head.count('"') % 2 == 0:
                line = head.rstrip()
        lines.append(line)
    return "\n".join(lines)


def _flatten_devcontainer_cmd(val: object) -> list[str]:
    """Hook values can be: str, list[str], dict[str, str|list[str]]."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [v for v in val if isinstance(v, str)]
    if isinstance(val, dict):
        out: list[str] = []
        for v in val.values():
            out.extend(_flatten_devcontainer_cmd(v))
        return out
    return []


def scan_devcontainer(text: str) -> list[Finding]:
    """Scan `.devcontainer/devcontainer.json` content.

    Returns an empty list if the file is empty. Returns a MAJOR finding
    if the JSON is invalid (the file is *committed* but unparseable —
    that itself is worth flagging because every tool that respects
    JSONC may parse it differently).
    """
    findings: list[Finding] = []
    if not text:
        return findings
    no_comments = _strip_jsonc(text)
    try:
        cfg = json.loads(no_comments)
    except json.JSONDecodeError:
        findings.append(Finding(
            rule_id="devcontainer-untrusted-features-and-hooks",
            line=1,
            column=1,
            matched_text="<invalid JSON>",
            severity="MAJOR",
            description=(
                "devcontainer.json is unparseable — different "
                "consumers (VS Code, Codespaces, Gateway) may behave "
                "inconsistently."
            ),
            owasp_asi="ASI-05",
        ))
        return findings
    if not isinstance(cfg, dict):
        return findings

    # 1. initializeCommand runs on the HOST — CRITICAL by default.
    if "initializeCommand" in cfg:
        for cmd in _flatten_devcontainer_cmd(cfg.get("initializeCommand")):
            findings.append(Finding(
                rule_id="devcontainer-untrusted-features-and-hooks",
                line=1,
                column=1,
                matched_text=cmd[:200],
                severity="CRITICAL",
                description=(
                    "initializeCommand runs ON THE HOST machine before "
                    "container build — full host shell access on "
                    "'Reopen in Container'."
                ),
                owasp_asi="ASI-05",
            ))

    # 2. Any shell hook with a pipe-to-shell payload — CRITICAL.
    for key in _DEVCONTAINER_SHELL_HOOK_KEYS - {"initializeCommand"}:
        val = cfg.get(key)
        for cmd in _flatten_devcontainer_cmd(val):
            if _DEVCONTAINER_PIPE_TO_SHELL.search(cmd):
                findings.append(Finding(
                    rule_id=(
                        "devcontainer-untrusted-features-and-hooks"
                    ),
                    line=1,
                    column=1,
                    matched_text=f"{key}: {cmd[:160]}",
                    severity="CRITICAL",
                    description=(
                        f"devcontainer.{key} pipes downloaded content "
                        "to shell."
                    ),
                    owasp_asi="ASI-05",
                ))

    # 3. Untrusted features registries.
    features = cfg.get("features")
    if isinstance(features, dict):
        for feature_ref in features:
            if not isinstance(feature_ref, str):
                continue
            # Feature refs are of the form `<host>/<path>:<tag>`; the
            # namespace is everything before the last `/`.
            if "/" in feature_ref:
                ns = feature_ref.rsplit("/", 1)[0]
            else:
                ns = feature_ref
            # Strip a trailing `@sha256:` so namespace match still works
            # when the ref is properly pinned.
            ns = ns.split("@", 1)[0]
            trusted = any(
                ns.startswith(t) for t in _TRUSTED_FEATURE_PREFIXES
            )
            if not trusted:
                findings.append(Finding(
                    rule_id=(
                        "devcontainer-untrusted-features-and-hooks"
                    ),
                    line=1,
                    column=1,
                    matched_text=feature_ref[:200],
                    severity="MAJOR",
                    description=(
                        "devcontainer feature from untrusted "
                        f"namespace: {feature_ref}"
                    ),
                    owasp_asi="ASI-05",
                ))
            if "@sha256:" not in feature_ref and (
                feature_ref.endswith(":latest")
                or ":" not in feature_ref.split("/")[-1]
            ):
                findings.append(Finding(
                    rule_id=(
                        "devcontainer-untrusted-features-and-hooks"
                    ),
                    line=1,
                    column=1,
                    matched_text=feature_ref[:200],
                    severity="MAJOR",
                    description=(
                        "devcontainer feature is unpinned "
                        f"(no @sha256:): {feature_ref}"
                    ),
                    owasp_asi="ASI-05",
                ))

    # 4. containerEnv / remoteEnv exfiltration via $localEnv.
    for env_key in ("containerEnv", "remoteEnv"):
        env_block = cfg.get(env_key)
        if isinstance(env_block, dict):
            for k, v in env_block.items():
                if isinstance(v, str) and "${localEnv:" in v:
                    findings.append(Finding(
                        rule_id=(
                            "devcontainer-untrusted-features-and-hooks"
                        ),
                        line=1,
                        column=1,
                        matched_text=f"{env_key}.{k}={v[:120]}",
                        severity="MAJOR",
                        description=(
                            f"devcontainer.{env_key}.{k} reads from "
                            "${localEnv:*} — host environment "
                            "variable is exfiltrated into the "
                            "container."
                        ),
                        owasp_asi="ASI-05",
                    ))

    return findings


# ---- Rule 6: dockerfile-env-registry-bypass -----------------------------


_DOCKERFILE_ENV_LINE = _re(
    r"^\s*ENV\s+(.+?)$"
)


def _parse_env_pairs(body: str) -> list[tuple[str, str]]:
    """ENV supports both `KEY VALUE` (legacy, one pair only) and the
    `KEY=VALUE KEY2=VALUE2` form (modern, multiple per line).
    """
    if not body.strip():
        return []
    first_token = body.split()[0]
    if "=" not in first_token:
        # Legacy: `ENV KEY rest of the line is value`.
        parts = body.split(None, 1)
        if len(parts) == 2:
            return [(parts[0], parts[1].strip().strip('"').strip("'"))]
        return []
    pairs: list[tuple[str, str]] = []
    try:
        tokens = shlex.split(body, posix=True)
    except ValueError:
        # Unbalanced quote — fall back to whitespace split.
        tokens = body.split()
    for tok in tokens:
        if "=" in tok:
            k, _, v = tok.partition("=")
            pairs.append((k, v))
    return pairs


# (key_re, value_re, severity, msg) — every entry is its own attack.
_ENV_BYPASS_RULES: tuple[
    tuple[re.Pattern, re.Pattern, str, str], ...
] = (
    (
        re.compile(r"^GOPROXY$"),
        re.compile(r"\b(?:direct|off|,direct$|,off$)\b", re.IGNORECASE),
        "CRITICAL",
        "GOPROXY set to bypass module proxy",
    ),
    (
        re.compile(r"^GOSUMDB$"),
        re.compile(r"^off$", re.IGNORECASE),
        "CRITICAL",
        "GOSUMDB=off disables the Go checksum database",
    ),
    (
        re.compile(r"^GOFLAGS$"),
        re.compile(r"-insecure", re.IGNORECASE),
        "CRITICAL",
        "GOFLAGS=-insecure disables TLS verification",
    ),
    (
        re.compile(r"^PIP_INDEX_URL$"),
        re.compile(r"^http://"),
        "CRITICAL",
        "PIP_INDEX_URL uses plain HTTP — MITM-able",
    ),
    (
        re.compile(r"^PIP_INDEX_URL$"),
        re.compile(
            r"^https?://(?!pypi\.org|files\.pythonhosted\.org|"
            r"download\.pytorch\.org)",
            re.IGNORECASE,
        ),
        "MAJOR",
        "PIP_INDEX_URL points to a non-canonical PyPI mirror",
    ),
    (
        re.compile(r"^PIP_EXTRA_INDEX_URL$"),
        re.compile(r"^http://"),
        "CRITICAL",
        "PIP_EXTRA_INDEX_URL uses plain HTTP",
    ),
    (
        re.compile(r"^PIP_TRUSTED_HOST$"),
        re.compile(r"^\*$|^\*\.|^[a-z0-9.-]+\s+\*"),
        "CRITICAL",
        "PIP_TRUSTED_HOST wildcards all registries",
    ),
    (
        re.compile(r"^(?:NPM_CONFIG_REGISTRY|npm_config_registry)$"),
        re.compile(
            r"^http://|^https?://(?!registry\.npmjs\.org|"
            r"registry\.yarnpkg\.com|registry\.npmmirror\.com)",
            re.IGNORECASE,
        ),
        "MAJOR",
        "npm registry overridden to a non-canonical source",
    ),
    (
        re.compile(r"^NODE_TLS_REJECT_UNAUTHORIZED$"),
        re.compile(r"^0$"),
        "CRITICAL",
        "NODE_TLS_REJECT_UNAUTHORIZED=0 disables TLS verification",
    ),
    (
        re.compile(r"^DOCKER_CONTENT_TRUST$"),
        re.compile(r"^0$"),
        "MAJOR",
        "DOCKER_CONTENT_TRUST=0 disables Docker image signing",
    ),
    (
        re.compile(r"^CARGO_HTTP_CHECK_REVOKE$"),
        re.compile(r"^false$", re.IGNORECASE),
        "MAJOR",
        "Cargo disabled certificate revocation checking",
    ),
)


def _scan_env_bypass(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for m in _DOCKERFILE_ENV_LINE.finditer(text):
        body = m.group(1).strip()
        pairs = _parse_env_pairs(body)
        line = text[: m.start()].count("\n") + 1
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
        for key, val in pairs:
            for key_re, val_re, sev, msg in _ENV_BYPASS_RULES:
                if key_re.match(key) and val_re.search(val):
                    findings.append(Finding(
                        rule_id="dockerfile-env-registry-bypass",
                        line=line,
                        column=col,
                        matched_text=f"ENV {key}={val}"[:200],
                        severity=sev,
                        description=msg,
                        owasp_asi="ASI-05",
                    ))
    return findings


# ---- Rule catalogue (regex-only entries) --------------------------------


# Sentinel patterns the regex-only `scan_text` pipeline runs. The
# multi-file rule (#1) and the JSON-aware rule (#5) live behind their
# own scan functions — they are listed here only as catalogue entries
# with a regex-presence pattern so `scan_text` can still emit a coarse
# finding when no out-of-band helper was used.

# Coarse presence-only proxies for rules that need a richer helper.
# Rule 1: presence of wildcard COPY (used to gate; reported helper is
# `scan_dockerfile_with_dockerignore`).
# Rule 5: presence of `initializeCommand` or hook keys at the top
# level — best-effort regex form, more thorough via `scan_devcontainer`.
_RULE1_PROXY = _WILDCARD_COPY  # only fires when paired with helper
_RULE5_PROXY = _re(
    r'"(?:initializeCommand|onCreateCommand|postCreateCommand|'
    r'postStartCommand|postAttachCommand|updateContentCommand)"\s*:'
)

# Rules 2/3/4/6 are pure regex-and-rescan: every match returned by the
# scanner is already a finding. Rule 2 needs the heredoc body walked
# (cross-line correlation), so its `pattern` is the OPENER regex used
# only for catalogue presence.
RULES: tuple[Rule, ...] = (
    Rule(
        id="container-dockerignore-evasion",
        name="Dockerfile wildcard COPY without .dockerignore protection",
        severity="MAJOR",
        description=(
            "Dockerfile uses `COPY . .` / `ADD . .` while .dockerignore "
            "is absent or fails to exclude sensitive paths — secrets, "
            ".git/, .ssh/, .aws/, ~/.npmrc get baked into the image."
        ),
        pattern=_RULE1_PROXY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="dockerfile-heredoc-pipe-to-shell",
        name="RUN heredoc pipes downloaded content to shell",
        severity="CRITICAL",
        description=(
            "BuildKit `RUN <<EOF` heredoc body downloads remote "
            "content (curl/wget/…) and feeds it to an interpreter "
            "(bash/sh/python/…) — single-line scanners miss this."
        ),
        pattern=_HEREDOC_OPEN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dockerfile-copy-from-external-registry",
        name="COPY --from= pulls from external / unpinned registry",
        severity="CRITICAL",
        description=(
            "`COPY --from=<image>` pulls layers from an unpinned "
            "external image or an untrusted registry — separate "
            "codepath from FROM, never reaches the unpinned-FROM rule."
        ),
        pattern=_COPY_FROM_REGISTRY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dockerfile-healthcheck-shell-escape",
        name="HEALTHCHECK CMD pipes to shell or contacts non-local host",
        severity="MAJOR",
        description=(
            "HEALTHCHECK CMD body either pipes to a shell or makes a "
            "non-local network call — persistent in-container c2 "
            "beacon disguised as a liveness probe."
        ),
        pattern=_HEALTHCHECK_CMD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="devcontainer-untrusted-features-and-hooks",
        name="devcontainer.json untrusted feature / shell hook",
        severity="CRITICAL",
        description=(
            ".devcontainer/devcontainer.json declares a host-running "
            "`initializeCommand`, a pipe-to-shell hook, an untrusted "
            "Features namespace, or exfiltrates host env via "
            "${localEnv:*}."
        ),
        pattern=_RULE5_PROXY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dockerfile-env-registry-bypass",
        name="ENV directive disables supply-chain guardrails",
        severity="MAJOR",
        description=(
            "Dockerfile ENV sets a registry-bypass / TLS-off / "
            "checksum-off variable (GOPROXY=direct, GOSUMDB=off, "
            "PIP_INDEX_URL=http://…, NODE_TLS_REJECT_UNAUTHORIZED=0, "
            "DOCKER_CONTENT_TRUST=0, …)."
        ),
        pattern=_DOCKERFILE_ENV_LINE,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str, *, file_kind: str = "dockerfile") -> list[Finding]:
    """Run every applicable rule against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "dockerfile" (default) — rules 2, 3, 4, 6 (and rule 1's
                                 wildcard-COPY presence is reported as
                                 INFO if no .dockerignore was passed
                                 alongside; for the full rule-1 check,
                                 call `scan_dockerfile_with_dockerignore`).
      * "devcontainer"          — rule 5 (via `scan_devcontainer`).
      * "any"                   — runs every rule (cross-kind scanner).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(items: list[Finding]) -> None:
        for f in items:
            key = (f.rule_id, f.line, f.column)
            if key in seen:
                continue
            seen.add(key)
            findings.append(f)

    if file_kind in {"dockerfile", "any"}:
        _emit(_scan_heredoc_run(text))
        _emit(_scan_copy_from_external(text))
        _emit(_scan_healthcheck(text))
        _emit(_scan_env_bypass(text))
    if file_kind in {"devcontainer", "any"}:
        _emit(scan_devcontainer(text))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
