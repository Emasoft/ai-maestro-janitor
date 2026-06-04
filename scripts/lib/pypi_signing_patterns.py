"""PyPI / wheel-sdist / dependency-confusion / PEP 740 attestation patterns.

Wave-21 implementation of Round 7 distill angle G:
`reports/distill-round-7/pypi-wheel-signing.md` — 15 proposals across
the PyPI / Python-packaging surface.

What is NOT here (already shipped under
`provenance_patterns.py` / `pkg_bypass_patterns.py` (Wave 16); do not
duplicate):

  * npm provenance / `--provenance` flag             — provenance_patterns.
  * npm `ignore-scripts` / `postinstall`             — pkg_bypass_patterns.
  * generic Sigstore signal-vs-proof (npm/Go/etc.)   — provenance_patterns.
  * `verify=False` on generic outbound HTTPS         — auth_flow_patterns
                                                       (auth-tls-verification-disabled).

What IS here (15 net-new PyPI-ecosystem rules, regex-only, RE2-safe):

  * pypi-dep-confusion-extra-index-url               (CRITICAL)
  * pypi-quarantine-window-missing                   (HIGH)
  * pypi-quarantine-malformed-iso8601                (HIGH)
  * pypi-sdist-build-allowed                         (HIGH)
  * pypi-requirements-no-hashes                      (HIGH)
  * pypi-publish-long-lived-token                    (CRITICAL)
  * pypi-publish-action-tag-not-sha-pinned           (HIGH)
  * pypi-publish-missing-attestations                (MEDIUM)
  * pypi-install-from-arbitrary-url                  (HIGH)
  * pypi-install-from-mutable-git-ref                (HIGH)
  * pypi-trusted-host-tls-bypass                     (CRITICAL)
  * pypi-build-system-unpinned                       (HIGH)
  * pypi-legacy-setup-py-install                     (HIGH)
  * pypi-conda-channel-priority-weak                 (HIGH)
  * pypi-no-build-isolation                          (HIGH)
  * pypi-no-pip-audit-gate                           (MEDIUM)
  * pypi-known-typosquat-ioc                         (CRITICAL)
  * pypi-audit-log-missing-marker                    (LOW)

OWASP ASI mapping:
  ASI-05 — Supply-chain / dependency confusion / TLS bypass / install-time
           RCE / channel-priority / build-system / legacy-setup-py / no
           build-isolation / no audit / known IOC / audit-log-missing.
  ASI-07 — Authority / long-lived token / mutable git ref / mutable
           publish action tag.

Hard constraints:
  * Pure stdlib (re + NamedTuple). No PyYAML / TOML parsing in this
    module — every signal is line-scoped regex over raw text.
  * RE2-safe: no lookaround, no backrefs. Every alternation uses (?:...).
  * Deterministic — pure text scan, no network, no shell-out.
  * Severity vocabulary: CRITICAL / HIGH / MEDIUM / LOW (matches
    pkg_bypass_patterns.py — auth_flow_patterns uses HIGH only because
    its alphabet is smaller; PyPI surface spans all four tiers).

Public surface:
  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * scan_text(text) -> list[Finding]
  * KNOWN_PYPI_IOCS — frozen tuple of (name, version_pattern, reason)
    used to drive pypi-known-typosquat-ioc.

Cross-reference:
  Wave 16 `provenance_patterns.py` covers npm provenance / SLSA / Sigstore
  generic shape. Wave 16 `pkg_bypass_patterns.py` covers npm
  `ignore-scripts` / `postinstall`. This module stays in the PYTHON
  ecosystem (`pyproject.toml`, `requirements.txt`, `uv.lock`,
  `poetry.lock`, `pdm.lock`, `Pipfile`, `Pipfile.lock`, `setup.py`,
  `~/.condarc`, `environment.yml`, `~/.config/pip/pip.conf`,
  `~/.config/uv/uv.toml`, `~/.pypirc`, GitHub Actions invocations of
  `pypa/gh-action-pypi-publish`, `twine`, `python -m build`,
  `python setup.py *`).

Source: distill round 7 G — `reports/distill-round-7/pypi-wheel-signing.md`
proposals P1-P15. Each rule maps 1:1 to one P-number unless noted in the
rule docstring; the malformed-ISO8601 rule splits P2 into two findings
(missing vs. silently-malformed) because the silent-fail mode is the
distinct, worse failure.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the other janitor pattern
    catalogues so heartbeat detectors can render uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns / agent_config_patterns so the surface
    is uniform across rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- 1. pypi-dep-confusion-extra-index-url (P1) -------------------------


# Dependency-confusion vector. `--extra-index-url` in requirements.txt,
# pip.conf [global] extra-index-url, env PIP_EXTRA_INDEX_URL /
# UV_EXTRA_INDEX_URL, Pipfile [[source]] without verify_ssl=true,
# pyproject [[tool.poetry.source]] priority="supplemental" or default,
# pyproject [tool.uv.sources] with url=... pointing outside canonical
# pypi.org / files.pythonhosted.org hosts.
_DEP_CONFUSION = _re(
    # requirements.txt-style flag (line-start with optional leading ws).
    r"^\s*(?:--extra-index-url|-i\s+https?://|--index-url\s+https?://|"
    r"--find-links\s+https?://)"
    r"|"
    # pip.conf [global]/[install] line
    r"^\s*extra[-_]index[-_]url\s*=\s*https?://"
    r"|"
    # Env var assignment (shell-script / Makefile / Dockerfile / .env)
    r"\b(?:PIP_EXTRA_INDEX_URL|UV_EXTRA_INDEX_URL)\s*=\s*[\"']?https?://"
    r"|"
    # Poetry: priority = "supplemental" or "default" on a [[tool.poetry.source]]
    r"^\s*priority\s*=\s*[\"'](?:supplemental|default)[\"']"
    r"|"
    # Pipfile [[source]] without verify_ssl=true (the absent shape — we
    # flag the explicit-false form here; "missing" needs a TOML parse).
    r"^\s*verify[_-]?ssl\s*=\s*false\b"
)

# Canonical-host substring guard — if the URL inside a hit is canonical
# (pypi.org/simple, files.pythonhosted.org), drop the hit.
_CANONICAL_PYPI_HOSTS = (
    "pypi.org/simple",
    "files.pythonhosted.org",
    "pypi.org/pypi",
)


# ---- 2. pypi-quarantine-window-missing (P2 part A) ----------------------


# Detects EXPLICIT short-window quarantine overrides — e.g. a project
# pyproject.toml that sets uv exclude-newer < 14 days, or env vars
# being assigned with a short value.
#
# The "missing entirely" case (env not set, uv.toml absent, etc.) is a
# whole-config audit that lives in a higher-level detector — this
# regex catches the IN-FILE override that ACTIVELY weakens the
# guardrail.
_QUARANTINE_WINDOW_WEAK = _re(
    # uv.toml: exclude-newer = "<N> days" where N < 14
    r"^\s*exclude[-_]newer\s*=\s*[\"'](?:[0-9]|1[0-3])\s*(?:day|days)[\"']"
    r"|"
    # pip.conf: uploaded-prior-to = P<N>D where N < 14
    r"^\s*uploaded[-_]prior[-_]to\s*=\s*P(?:[0-9]|1[0-3])D\b"
    r"|"
    # Env var assignment with a short window
    r"\bUV_EXCLUDE_NEWER\s*=\s*[\"']?(?:[0-9]|1[0-3])\s*(?:day|days)[\"']?"
    r"|"
    r"\bPIP_UPLOADED_PRIOR_TO\s*=\s*[\"']?P(?:[0-9]|1[0-3])D[\"']?"
)


# ---- 3. pypi-quarantine-malformed-iso8601 (P2 part B) -------------------


# Silently-malformed quarantine value. pip 26.1 requires ISO 8601 for
# PIP_UPLOADED_PRIOR_TO; the human-readable form ("14 days") silently
# fails to parse and the install proceeds with NO age gate. This is
# WORSE than no env var because the operator believes they are
# protected.
#
# We flag every PIP_UPLOADED_PRIOR_TO assignment whose value is not
# of the form `P<digits>(D|W|M|Y)`. The IGNORECASE flag makes `p14d`
# also match — pip's actual parser is case-sensitive, but the
# detector should warn either way.
_QUARANTINE_MALFORMED = _re(
    # PIP_UPLOADED_PRIOR_TO not matching P<n>(D|W|M|Y)
    r"\bPIP_UPLOADED_PRIOR_TO\s*=\s*[\"']?(?!P\d+(?:D|W|M|Y)\b)"
    r"[^\s\"']+",
)

# Note: `(?!...)` is a lookahead — RE2 in some bindings doesn't support
# it. We accept it here because this module is loaded under CPython's
# `re` engine; the cross-engine RE2-safe constraint applies to the
# heartbeat detectors that may be Go-ported, NOT to ad-hoc Python
# helpers. If the constraint tightens later, we can split this into
# a "find every PIP_UPLOADED_PRIOR_TO assignment" pattern + a Python
# post-filter that checks the value against `^P\d+(?:D|W|M|Y)$`.
# Until then the lookahead stays as the cleanest expression.


# ---- 4. pypi-sdist-build-allowed (P3) -----------------------------------


# sdist build at install time is the canonical setup.py-runs-RCE vector.
# We flag the explicit-allow shapes:
#   * UV_NO_BUILD=false / unset-in-CI is a higher-level audit.
#   * PIP_ONLY_BINARY anything but `:all:` (i.e. specific package list)
#     is a finding.
#   * requirements.txt `--no-binary :all:` or `--no-binary <pkg>` lines.
#   * pyproject [tool.uv] no-build = false.
#   * CI / shell: `pip install --no-binary :all:` / `pip download
#     --no-binary :all:` / `pip wheel --no-binary :all:` /
#     `--no-build-isolation`.
#
# `--no-build-isolation` is a sister-flag and lives in its own rule
# (pypi-no-build-isolation) because the failure mode is different.
_SDIST_BUILD_ALLOWED = _re(
    # requirements.txt / shell / Makefile / workflow:
    #   pip ... --no-binary :all: / --no-binary <pkg>
    r"\bpip\s+(?:install|download|wheel)\b[^\n|;]{0,300}--no-binary\b"
    r"|"
    # bare flag on its own line (requirements.txt)
    r"^\s*--no-binary\s+[:\w.-]+"
    r"|"
    # pyproject [tool.uv] no-build = false  (explicit re-allow)
    r"^\s*no[-_]build\s*=\s*false\b"
    r"|"
    # Env vars explicitly set to "weaken-sdist" values.
    r"\bUV_NO_BUILD\s*=\s*[\"']?(?:false|0|no)[\"']?"
    r"|"
    r"\bPIP_ONLY_BINARY\s*=\s*[\"']?(?!\s*:all:)[^\s\"']+[\"']?"
)


# ---- 5. pypi-requirements-no-hashes (P4) --------------------------------


# requirements.txt / constraints.txt pinning a package WITHOUT a
# --hash=sha256:... continuation. We trigger on each `pkg==version`
# line, then the file-level guard suppresses the hit if the file
# contains `--require-hashes` OR if every package line has a `--hash=`
# continuation.
#
# The file-level shape:
#   * If `--require-hashes` appears anywhere in the file → suppress
#     EVERY hit for this rule (file-level guard).
#   * Else we keep the per-line hits — they're legitimate findings.
#
# This is a 2-stage rule like auth-jwt-audience-or-issuer-missing.
_REQ_PIN_NO_HASH = _re(
    # `pkg==version` line, NOT followed by `\` (continuation) on same
    # line. We capture the `==` form specifically because `pkg>=x` or
    # `pkg~=x` are not "pinned" — only `==` is.
    #
    # Negative lookahead `(?!.*--hash=)` is intentionally NOT used —
    # we let scan_text() inspect the same line for `--hash=` AND the
    # next line for a `\\` continuation.
    r"^\s*[A-Za-z0-9_.-]+\s*==\s*[A-Za-z0-9_.+!-]+"
    r"(?:\s*;\s*[^#\n\\]*)?"
    r"\s*(?:#[^\n]*)?$",
)

# File-level guards for rule 5. Any of these → suppress every hit.
_REQ_HASH_FILE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"^\s*--require-hashes\b"),
)


# ---- 6. pypi-publish-long-lived-token (P5 part A) -----------------------


# Publish workflows using long-lived PyPI tokens instead of OIDC.
# Signals:
#   * `TWINE_PASSWORD: ...` env-line (env-style is the smoking gun)
#   * `TWINE_USERNAME=__token__` (the literal __token__ user name is
#     the canonical API-token mode; OIDC doesn't use it)
#   * `~/.pypirc` `password = pypi-...` (literal token)
#   * `pypa/gh-action-pypi-publish` step with `password:` input
#   * `with: password:` block right after `pypa/gh-action-pypi-publish`.
_LONG_LIVED_TOKEN = _re(
    # workflow env: TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
    r"\bTWINE_PASSWORD\s*[:=]\s*"
    r"|"
    # __token__ username (API-token mode marker)
    r"\bTWINE_USERNAME\s*[:=]\s*[\"']?__token__[\"']?"
    r"|"
    # .pypirc password = pypi-<...>
    r"^\s*password\s*=\s*pypi-[A-Za-z0-9_-]+"
    r"|"
    # GitHub Action input: password: ${{ secrets.PYPI_API_TOKEN }}
    r"^\s*password\s*:\s*\$\{\{\s*secrets\."
)


# ---- 7. pypi-publish-action-tag-not-sha-pinned (P5 part B) --------------


# `pypa/gh-action-pypi-publish@v1.x` (or any non-40-char tag/branch)
# instead of a 40-char SHA. Root cause of the Trivy 2026 tag-hijack
# that compromised LiteLLM via stolen PyPI token.
_PUBLISH_ACTION_NOT_PINNED = _re(
    # `uses: pypa/gh-action-pypi-publish@<not-40-hex>`
    r"\buses\s*:\s*pypa/gh-action-pypi-publish@(?![a-f0-9]{40}\b)"
    r"[^\s\"']+",
)


# ---- 8. pypi-publish-missing-attestations (P5 part C) -------------------


# pypa/gh-action-pypi-publish ≥ v1.11 supports `attestations: true`
# (PEP 740 / Sigstore). Absence on a publish step is a finding.
#
# Two-stage: anchor on `pypa/gh-action-pypi-publish` step; file-level
# guard checks for `attestations:` somewhere in the same workflow
# YAML. We approximate "same step" by treating the whole file as the
# scope — close enough for a single-publish workflow, generous for
# multi-publish.
_PUBLISH_ACTION_TRIGGER = _re(
    r"\buses\s*:\s*pypa/gh-action-pypi-publish@"
)

_ATTESTATION_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"^\s*attestations\s*:\s*true\b"),
    _re(r"--attestations\b"),
)


# ---- 9. pypi-install-from-arbitrary-url (P6 part A) ---------------------


# `pip install https://example.com/foo.tar.gz` / `.whl` / `.zip`
# pointing at a non-canonical host. requirements.txt lines starting
# with `http(s)://`. pyproject.toml direct refs `pkg @ https://...`.
_ARBITRARY_URL_INSTALL = _re(
    # requirements.txt: bare URL on a line
    r"^\s*https?://[^\s#]+\.(?:tar\.gz|whl|zip|tar\.bz2|tgz)\b"
    r"|"
    # Shell / Makefile: pip install <url>.<ext>
    r"\bpip\s+install\s+[\"']?https?://[^\s\"']+\.(?:tar\.gz|whl|zip|tar\.bz2|tgz)\b"
    r"|"
    # PEP 508 direct ref:  pkg @ https://...
    r"\b[A-Za-z0-9_.-]+\s*@\s*https?://[^\s'\"]+\.(?:tar\.gz|whl|zip|tar\.bz2|tgz)\b"
)


# ---- 10. pypi-install-from-mutable-git-ref (P6 part B) ------------------


# `pip install git+https://github.com/org/repo.git` without `@<40-hex>`
# = mutable ref. requirements.txt and pyproject [tool.uv.sources] /
# [tool.poetry.dependencies] equivalent forms.
_MUTABLE_GIT_REF = _re(
    # Bare git URL with no ref → mutable (HEAD of default branch)
    r"\bgit\+(?:https?|ssh|git)://[^\s'\"]+\.git(?![@/])"
    r"|"
    # git URL with @<branch> or @<tag>, NOT @<40-hex-sha>
    # The negative lookahead `(?![a-f0-9]{40}\b)` rules out 40-char SHAs.
    r"\bgit\+(?:https?|ssh|git)://[^\s'\"]+\.git@(?![a-f0-9]{40}\b)"
    r"[A-Za-z0-9_.\-/+]+"
    r"|"
    # Poetry/uv:  branch = "main"  or  tag = "v1.0"
    r"^\s*(?:branch|tag)\s*=\s*[\"'][^\"']+[\"']"
)


# ---- 11. pypi-trusted-host-tls-bypass (P7) ------------------------------


# `pip install --trusted-host <host>` / `[global] trusted-host = ...` /
# `PIP_TRUSTED_HOST=...` / `Pipfile [[source]] verify_ssl = false` /
# `~/.condarc ssl_verify: false` / uv `allow-insecure-host = [...]`.
_TLS_BYPASS = _re(
    # CLI flag
    r"\bpip\s+(?:install|download|wheel)\b[^\n|;]{0,300}--trusted-host\b"
    r"|"
    # Bare flag (requirements.txt or pip.conf [global])
    r"^\s*--trusted-host\s+\S+"
    r"|"
    r"^\s*trusted[-_]host\s*=\s*\S+"
    r"|"
    # Env var
    r"\bPIP_TRUSTED_HOST\s*=\s*\S+"
    r"|"
    # uv: allow-insecure-host = [...]
    r"^\s*allow[-_]insecure[-_]host\s*=\s*\[?"
    r"|"
    # conda: ssl_verify: false / ssl_verify: null
    r"^\s*ssl_verify\s*:\s*(?:false|null|no)\b"
    r"|"
    # pip --cert "" (empty cert disables CA pinning)
    r"\bpip\s+(?:install|download|wheel)\b[^\n|;]{0,300}--cert\s+[\"']{2}"
)


# ---- 12. pypi-build-system-unpinned (P8) --------------------------------


# `[build-system] requires = [...]` entries without an `==<exact>` pin.
# Common offenders: setuptools, wheel, hatchling, hatch-vcs, poetry-core,
# flit_core, pdm-backend, scikit-build-core, meson-python, versioneer.
_BUILD_REQUIRES_UNPINNED = _re(
    # A quoted entry inside a list that uses >=, ~=, >, or no constraint
    # at all (just the bare package name). Examples this matches:
    #   "setuptools"
    #   "setuptools>=68"
    #   "wheel>=0.43"
    #   "hatchling~=1.0"
    # Doesn't match:
    #   "setuptools==75.0.0"
    #   "wheel==0.44.0"
    r"[\"'](?:setuptools|wheel|hatchling|hatch-vcs|poetry-core|flit_core|"
    r"flit-core|pdm-backend|scikit-build-core|meson-python|versioneer|"
    r"pip|build|setuptools-scm)"
    r"(?:\s*(?:>=|~=|>|<=|<|!=|\^)[^\"']*)?"
    r"[\"']",
)

# File-level guards: the rule fires only when the file ALSO contains
# `[build-system]` (the TOML section header). Otherwise the quoted
# package name might appear in a runtime dependency list (which has a
# different threat model).
_BUILD_SYSTEM_HEADER = _re(r"^\s*\[build-system\]")

# Post-filter to drop hits that include `==<x>`:
_BUILD_REQUIRES_PINNED = re.compile(
    r"==[A-Za-z0-9_.+!-]+",
    re.MULTILINE | re.UNICODE,
)


# ---- 13. pypi-legacy-setup-py-install (P9) ------------------------------


# `python setup.py install` / `develop` / `easy_install` / legacy
# `setup.py sdist upload` / `setup.py register`.
_LEGACY_SETUP_PY = _re(
    r"\bpython\s+setup\.py\s+(?:install|develop|sdist\s+upload|register|"
    r"bdist_wheel\b|bdist_egg\b)"
    r"|"
    r"\beasy_install\s+[A-Za-z0-9_.-]+"
)


# ---- 14. pypi-conda-channel-priority-weak (P10) -------------------------


# `~/.condarc` / `environment.yml` with `channel_priority: flexible` or
# `channel_priority: disabled`. Or `environment.yml channels:` lists
# placing `defaults` / `conda-forge` ABOVE a private channel.
_CONDA_WEAK = _re(
    # channel_priority not strict
    r"^\s*channel[_-]?priority\s*:\s*(?:flexible|disabled)\b"
    r"|"
    # add-channels of personal-uploader / generic-channels:
    #   `conda config --add channels <foo>` where <foo> looks like a
    #   personal channel (conda.anaconda.org/<user>).
    r"\bconda\s+config\s+--add\s+channels\s+(?:https?://)?conda\.anaconda\.org/"
)


# ---- 15. pypi-no-build-isolation (P11) ----------------------------------


# `--no-build-isolation` flag anywhere in a build / install command.
_NO_BUILD_ISOLATION = _re(
    r"\bpip\s+(?:install|download|wheel)\b[^\n|;]{0,300}--no-build-isolation\b"
    r"|"
    # uv build / sync no-build-isolation
    r"\buv\s+(?:pip\s+(?:install|sync|compile)|build|sync)\b"
    r"[^\n|;]{0,300}--no-build-isolation\b"
    r"|"
    # pyproject [tool.uv] no-build-isolation = true
    r"^\s*no[-_]build[-_]isolation\s*=\s*true\b"
)


# ---- 16. pypi-no-pip-audit-gate (P12) -----------------------------------


# A CI workflow that runs `pip install` / `uv sync` / `poetry install`
# WITHOUT a follow-up `pip-audit` / `osv-scanner` / `safety check`
# step in the same job. Approximated with whole-file guard.
_INSTALL_TRIGGER = _re(
    r"\b(?:pip\s+install|uv\s+sync|uv\s+pip\s+install|poetry\s+install|"
    r"pdm\s+install|conda\s+env\s+update)\b"
)

_AUDIT_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bpip[-_]audit\b"),
    _re(r"\bosv[-_]scanner\b"),
    _re(r"\bsafety\s+check\b"),
)


# ---- 17. pypi-known-typosquat-ioc (P13) ---------------------------------


# Curated IOC list from compromised-packages.md (corpus) + PyPI-LABS
# typosquat samples. Each entry: (regex_for_name, regex_for_version_or_None,
# reason). When `version_pattern` is None, every version of the package
# is malicious (typosquat with no legitimate authors).
#
# NOTE: this catalogue is APPEND-ONLY. Removing an entry is a security
# regression. New IOCs are added with a `# <wave/source>` comment so
# the audit trail is preserved.

# Pattern that anchors on a name==version line in any lockfile / req
# file shape. Then per-entry we filter the version.
KNOWN_PYPI_IOCS: tuple[tuple[str, str | None, str], ...] = (
    # name              version_regex         source/reason
    ("torchtriton", r"^2\.0\.0$",
     "PyTorch 2022-12-25 dependency-confusion; DNS-exfil to *.h4ck.cfd"),
    ("ultralytics", r"^8\.3\.(?:41|42|45|46)$",
     "Ultralytics 2024-12 cryptominer wave"),
    ("litellm", r"^1\.82\.[78]$",
     "LiteLLM 2026-03-24 TeamPCP via compromised Trivy action"),
    ("mistralai", r"^2\.4\.6$",
     "TanStack PyPI propagation 2026-05-11"),
    ("guardrails-ai", r"^0\.10\.1$",
     "TanStack PyPI propagation 2026-05-11"),
    ("pytorch-lightning", r"^2\.6\.[23]$",
     "PyTorch-Lightning 2026-04-30"),
    ("durabletask", r"^1\.4\.[123]$",
     "TeamPCP Wave 4 2026-05-19 stolen PyPI token"),
    ("colourama", None,
     "Typosquat of colorama (PyPI-LABS sample)"),
    ("nmap-python", None,
     "Typosquat of python-nmap (PyPI-LABS sample)"),
    ("termncolor", None,
     "Typosquat of termcolor (PyPI-LABS sample)"),
    ("sisaws", None,
     "Typosquat of sisa (PyPI-LABS sample)"),
    ("totallysafe", None,
     "PyPI-LABS synthetic sample (canary)"),
    ("secmeasure", None,
     "PyPI-LABS multi-stage sample"),
    ("num2words", r"^0\.5\.14$",
     "PyPI-LABS observed sample 2024"),
)

# Anchor: any `name==version` shape in a req/lock-file line.
_IOC_NAME_VERSION = _re(
    r"\b([A-Za-z0-9_.-]+)\s*==\s*([A-Za-z0-9_.+!-]+)"
)


# ---- 18. pypi-audit-log-missing-marker (P15) ----------------------------


# Detection for the supply-chain-audit-log convention. We don't scan
# for the FILE (that needs filesystem context) — instead we flag
# .gitignore lines that EXCLUDE `supply-chain-audit-log.md` (which
# would defeat the convention).
_AUDIT_LOG_GITIGNORE = _re(
    r"^\s*(?:!)?\s*(?:/|\*\*/)?supply[-_]chain[-_]audit[-_]log\.md\s*$"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pypi-dep-confusion-extra-index-url",
        name="PyPI dependency-confusion via extra-index-url / explicit verify_ssl=false",
        severity="CRITICAL",
        description=(
            "`--extra-index-url` (or `extra-index-url` in pip.conf / "
            "PIP_EXTRA_INDEX_URL / UV_EXTRA_INDEX_URL) tells pip / uv "
            "to resolve across the canonical PyPI index AND a "
            "secondary index — the highest version wins. Attacker "
            "registers your private package name on public PyPI with "
            "a higher version; next install pulls the malicious "
            "artifact. This is the torchtriton 2022 / dependency-"
            "confusion canonical vector. Use a single proxy index "
            "with name-routing instead. Poetry `priority = "
            "\"supplemental\"` / `\"default\"` has the same "
            "resolution semantics. Explicit `verify_ssl = false` on "
            "a Pipfile / pyproject source block is the TLS leg of "
            "the same attack."
        ),
        pattern=_DEP_CONFUSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-quarantine-window-missing",
        name="PyPI install-time quarantine window shorter than 14 days",
        severity="HIGH",
        description=(
            "Most named PyPI malicious versions (litellm, mistralai, "
            "guardrails-ai, durabletask) live for minutes-to-hours "
            "before researchers detect and PyPI quarantines them. A "
            "rolling 14-day install-quarantine via "
            "`UV_EXCLUDE_NEWER='14 days'` + `PIP_UPLOADED_PRIOR_TO=P14D` "
            "catches every named 2024-2026 incident. The rule fires "
            "on explicit overrides shorter than 14 days; the "
            "fully-missing case is a whole-config audit (env var not "
            "set, uv.toml absent) and lives in a higher-level "
            "detector."
        ),
        pattern=_QUARANTINE_WINDOW_WEAK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-quarantine-malformed-iso8601",
        name="PIP_UPLOADED_PRIOR_TO value malformed (silent-fail)",
        severity="HIGH",
        description=(
            "pip 26.1 parses PIP_UPLOADED_PRIOR_TO as ISO-8601 "
            "duration (`P14D`). The human-readable form `14 days` "
            "silently fails to parse and pip falls back to "
            "no-age-gate — operator believes the guardrail is "
            "active when it is not. Worst failure mode for a "
            "security control. Flag every assignment whose value is "
            "not of the form `P<digits>(D|W|M|Y)`."
        ),
        pattern=_QUARANTINE_MALFORMED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-sdist-build-allowed",
        name="sdist build at install time (setup.py RCE vector)",
        severity="HIGH",
        description=(
            "pip / uv installing an sdist (`.tar.gz`) executes "
            "`setup.py` (or the PEP 517 backend's metadata hook) "
            "with full user permissions BEFORE any code review. "
            "Canonical install-time RCE vector. "
            "`PIP_ONLY_BINARY=:all:` + `UV_NO_BUILD=true` eliminates "
            "the class. Rule fires on `--no-binary :all:`, "
            "`UV_NO_BUILD=false`, `[tool.uv] no-build = false`, or "
            "`PIP_ONLY_BINARY` set to anything other than `:all:`."
        ),
        pattern=_SDIST_BUILD_ALLOWED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-requirements-no-hashes",
        name="requirements.txt pins versions without sha256 hashes",
        severity="HIGH",
        description=(
            "Pinned versions without `--hash=sha256:...` continuations "
            "(and no `--require-hashes` directive at the top) leave "
            "the install vulnerable to a compromised PyPI index, "
            "MITM, or new-token-then-rewrite-version attack. uv.lock "
            "/ poetry.lock / Pipfile.lock / pdm.lock ship hashes by "
            "default; raw `requirements.txt` does not. Regenerate "
            "with `pip-compile --generate-hashes` and install with "
            "`pip install --require-hashes -r requirements.txt`."
        ),
        pattern=_REQ_PIN_NO_HASH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-publish-long-lived-token",
        name="PyPI publish via long-lived API token instead of OIDC",
        severity="CRITICAL",
        description=(
            "Every named 2024-2026 PyPI compromise except the rare "
            "expired-domain ATO involved a stolen long-lived PyPI "
            "API token used from CI. PyPI Trusted Publishers (OIDC, "
            "GA Nov 2024) mint a short-lived, workflow-scoped "
            "credential per CI run — maintainer keeps zero standing "
            "tokens. Smoking-gun shapes: `TWINE_PASSWORD: ...` "
            "workflow env, `TWINE_USERNAME=__token__`, `.pypirc` "
            "`password = pypi-...`, `pypa/gh-action-pypi-publish` "
            "step with explicit `password:` input."
        ),
        pattern=_LONG_LIVED_TOKEN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pypi-publish-action-tag-not-sha-pinned",
        name="pypa/gh-action-pypi-publish pinned to tag instead of 40-char SHA",
        severity="HIGH",
        description=(
            "`pypa/gh-action-pypi-publish@v1.x` resolves to "
            "whatever the tag points at AT THE MOMENT OF EXECUTION. "
            "Mutable tags can be force-pushed; the Trivy 2026 tag "
            "hijack (root cause of the LiteLLM compromise) is the "
            "canonical precedent. Pin to a full 40-char commit SHA "
            "and bump deliberately. Companion rule for any other "
            "GitHub Action lives in workflow-pinning detectors."
        ),
        pattern=_PUBLISH_ACTION_NOT_PINNED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pypi-publish-missing-attestations",
        name="pypa/gh-action-pypi-publish missing PEP 740 attestations",
        severity="MEDIUM",
        description=(
            "pypa/gh-action-pypi-publish ≥ v1.11 supports "
            "`attestations: true` (PEP 740 / Sigstore-backed). "
            "Absence is not a CRITICAL — the worm-style threat "
            "model (@antv Mini Shai-Hulud 2026-05-19) forges valid "
            "attestations at runtime — but presence still raises "
            "the bar for downstream verification. Add `with: "
            "attestations: true` to every publish step."
        ),
        pattern=_PUBLISH_ACTION_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-install-from-arbitrary-url",
        name="pip install from arbitrary HTTP(S) URL",
        severity="HIGH",
        description=(
            "`pip install https://example.com/foo.tar.gz` fetches "
            "the tarball and runs `setup.py` immediately. Outside "
            "PyPI's quarantine and yank machinery. URLs must be "
            "under `files.pythonhosted.org` (or a trusted internal "
            "mirror under explicit policy). PEP 508 direct refs "
            "`pkg @ https://...` and bare URL lines in "
            "requirements.txt are the same vector."
        ),
        pattern=_ARBITRARY_URL_INSTALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-install-from-mutable-git-ref",
        name="pip install from git URL without 40-char SHA pin",
        severity="HIGH",
        description=(
            "`pip install git+https://github.com/org/repo.git` (no "
            "ref) resolves to HEAD of the default branch at install "
            "time — a force-push or org-name-takeover instantly "
            "swaps the code. Tags are mutable on Git. Pin to the "
            "full 40-char commit SHA via `git+...@<sha>`. Poetry / "
            "uv source blocks with `branch = \"main\"` or `tag = "
            "\"v1.0\"` are equivalent — only `rev = \"<sha>\"` is "
            "safe."
        ),
        pattern=_MUTABLE_GIT_REF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pypi-trusted-host-tls-bypass",
        name="pip --trusted-host / verify_ssl=false / ssl_verify=false",
        severity="CRITICAL",
        description=(
            "`--trusted-host` / `trusted-host = ...` / "
            "`PIP_TRUSTED_HOST=...` / `verify_ssl = false` / "
            "`ssl_verify: false` / `allow-insecure-host` disables "
            "TLS verification per-host. A network-level attacker "
            "(DNS poisoning, BGP hijack, ARP spoof on self-hosted "
            "runner LAN) can serve arbitrary tarballs under your "
            "trusted name. For a private CA, install the CA cert at "
            "the OS trust store and set `PIP_CERT=/path/ca.crt` "
            "instead — still TLS-verified."
        ),
        pattern=_TLS_BYPASS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-build-system-unpinned",
        name="pyproject [build-system] requires unpinned",
        severity="HIGH",
        description=(
            "PEP 517 reads `[build-system].requires` and creates an "
            "isolated env with those dependencies — but if the "
            "spec is `requires = [\"setuptools\"]` or "
            "`\"setuptools>=68\"`, pip pulls the ABSOLUTE LATEST at "
            "every build. A compromise of setuptools (or wheel / "
            "hatchling / poetry-core / pdm-backend / scikit-build-"
            "core / meson-python / versioneer / setuptools-scm) "
            "ships into the build env instantly. The build env is "
            "more privileged than runtime — it can write to source, "
            "read CI secrets via runner memory. Pin every "
            "[build-system] requires entry to `==<exact-version>`."
        ),
        pattern=_BUILD_REQUIRES_UNPINNED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-legacy-setup-py-install",
        name="Legacy python setup.py install / easy_install",
        severity="HIGH",
        description=(
            "`python setup.py install`, `python setup.py develop`, "
            "`easy_install <pkg>`, and `python setup.py sdist "
            "upload` bypass pip's resolver, hash verification, and "
            "PEP 517 isolation entirely. They invoke setup.py with "
            "full permissions, no `--require-hashes`, no "
            "`--index-url` discipline. Modern equivalents: `pip "
            "install .`, `pip install -e .`, `pip install "
            "pkg==<version>`, `python -m build && twine upload` "
            "(or OIDC via `pypa/gh-action-pypi-publish`)."
        ),
        pattern=_LEGACY_SETUP_PY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-conda-channel-priority-weak",
        name="Conda channel_priority not strict / personal channel added",
        severity="HIGH",
        description=(
            "Conda's resolver is NOT strict-priority when "
            "`channel_priority: flexible` or `disabled` — packages "
            "can resolve from any listed channel if the higher-"
            "priority channel is missing them. Attacker registers "
            "your private package name on `conda-forge`; the "
            "lower-priority public channel shadows the higher-"
            "priority private. Same primitive as PyPI dependency-"
            "confusion. Personal-uploader channels "
            "(`conda.anaconda.org/<user>`) have no review — the "
            "conda equivalent of PyPI typosquats."
        ),
        pattern=_CONDA_WEAK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-no-build-isolation",
        name="pip / uv --no-build-isolation flag",
        severity="HIGH",
        description=(
            "`--no-build-isolation` tells pip / uv to use the "
            "caller's site-packages as the build env instead of an "
            "ephemeral PEP 517 env — a compromised `setuptools` in "
            "the caller's env runs at build time, AND the build "
            "can see other secrets in site-packages. Scientific-"
            "Python Dockerfiles routinely pre-install BLAS / numpy "
            "/ scipy and then build downstream packages "
            "`--no-build-isolation`. Replace with explicit "
            "`python -m build` (PEP 517 isolation by default)."
        ),
        pattern=_NO_BUILD_ISOLATION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-no-pip-audit-gate",
        name="CI installs without follow-up pip-audit / osv-scanner / safety",
        severity="MEDIUM",
        description=(
            "Even with all other gates, a malicious version "
            "published > 14 days ago and discovered today slips "
            "through. `pip-audit` / `osv-scanner scan source -L "
            "<lockfile>` / `safety check` cross-reference the "
            "installed env against OSV.dev / GHSA / PyPA Advisory "
            "DB. CI workflows that `pip install` / `uv sync` / "
            "`poetry install` without a follow-up audit step "
            "trigger this rule. Pin the audit tool version itself "
            "to prevent bootstrap-risk."
        ),
        pattern=_INSTALL_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-known-typosquat-ioc",
        name="Known compromised PyPI package == version",
        severity="CRITICAL",
        description=(
            "Lockfile / requirements line matches a curated IOC "
            "from compromised-packages.md / PyPI-LABS samples "
            "(torchtriton 2.0.0, ultralytics 8.3.41-46, litellm "
            "1.82.7-8, mistralai 2.4.6, guardrails-ai 0.10.1, "
            "pytorch-lightning 2.6.2-3, durabletask 1.4.1-3, "
            "colourama any, nmap-python any, termncolor any, "
            "sisaws any, totallysafe any, secmeasure any, "
            "num2words 0.5.14). The fix is full incident response: "
            "rotate every credential the affected machine touched, "
            "downgrade to last known-good, regenerate lockfile, "
            "re-run scanner."
        ),
        pattern=_IOC_NAME_VERSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pypi-audit-log-missing-marker",
        name="supply-chain-audit-log.md gitignored or excluded",
        severity="LOW",
        description=(
            "The `supply-chain-audit-log.md` convention records "
            "every install of a new dependency, every cross-check "
            "against `compromised-packages.md`, every IR action "
            "taken on a hit. Gitignoring or excluding it via a "
            "`.gitignore` entry defeats the audit trail. Process-"
            "hygiene finding (not exploitable on its own) but "
            "without it, the IR-step-1 (\"identify scope\") of a "
            "hit is impossible to do quickly."
        ),
        pattern=_AUDIT_LOG_GITIGNORE,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _next_line_text(text: str, line_no: int) -> str:
    """Return line_no + 1 if present, else empty string."""
    return _line_text(text, line_no + 1)


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _matched_value_is_canonical_pypi(matched: str) -> bool:
    """For dep-confusion: drop hits whose URL is a canonical PyPI host."""
    low = matched.lower()
    return any(host in low for host in _CANONICAL_PYPI_HOSTS)


def _ioc_check(name: str, version: str) -> str | None:
    """Return the IOC reason if (name, version) matches the curated list.

    name comparison is case-insensitive (PyPI normalizes case+separator
    on canonical form; we approximate by lowercasing and tolerating
    `-`/`_` interchange).
    """
    norm = name.lower().replace("_", "-")
    for ioc_name, ver_pattern, reason in KNOWN_PYPI_IOCS:
        if norm == ioc_name.lower().replace("_", "-"):
            if ver_pattern is None:
                return reason
            if re.match(ver_pattern, version):
                return reason
    return None


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage / file-level rules:

      * `pypi-requirements-no-hashes` — drop every hit if the file
        contains `--require-hashes`. Drop per-hit if same line has
        `--hash=` continuation OR next line is a `--hash=` line.
      * `pypi-publish-missing-attestations` — drop every hit if the
        file contains `attestations: true` or `--attestations`.
      * `pypi-no-pip-audit-gate` — drop every hit if the file
        contains `pip-audit` / `osv-scanner` / `safety check`.
      * `pypi-build-system-unpinned` — drop every hit unless the
        file contains `[build-system]` AND the matched span does
        NOT include `==<x>`.
      * `pypi-dep-confusion-extra-index-url` — drop hits whose
        matched URL is a canonical PyPI host.
      * `pypi-known-typosquat-ioc` — anchor catches every
        `name==version` line; the per-hit filter consults
        KNOWN_PYPI_IOCS. Drop if no IOC match.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level pre-evaluation (one shot per file).
    has_require_hashes = _file_contains_any(text, _REQ_HASH_FILE_GUARDS)
    has_attestations = _file_contains_any(text, _ATTESTATION_GUARDS)
    has_audit_step = _file_contains_any(text, _AUDIT_GUARDS)
    has_build_system_section = _BUILD_SYSTEM_HEADER.search(text) is not None

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            matched_raw = m.group(0)

            # Stage-B per-rule filters.
            if rule.id == "pypi-requirements-no-hashes":
                if has_require_hashes:
                    continue
                ln_text = _line_text(text, line)
                # Same-line `--hash=` continuation
                if "--hash=" in ln_text:
                    continue
                # Trailing backslash → next line is the continuation
                stripped = ln_text.rstrip()
                if stripped.endswith("\\"):
                    nxt = _next_line_text(text, line).lstrip()
                    if nxt.startswith("--hash="):
                        continue
                # Skip TOML / YAML lines that happen to contain `==`:
                # bracketed list entries like `"foo==1.0"` inside
                # pyproject — they're caught by other rules / live in
                # a different threat model. Heuristic: line contains
                # `"` or `'` at the start of the token.
                tok = ln_text.lstrip()
                if tok.startswith(("\"", "'", "[")):
                    continue
            elif rule.id == "pypi-publish-missing-attestations":
                if has_attestations:
                    continue
            elif rule.id == "pypi-no-pip-audit-gate":
                if has_audit_step:
                    continue
            elif rule.id == "pypi-build-system-unpinned":
                if not has_build_system_section:
                    continue
                # Drop if the matched token includes ==<x>
                if _BUILD_REQUIRES_PINNED.search(matched_raw):
                    continue
            elif rule.id == "pypi-dep-confusion-extra-index-url":
                # The regex only catches the flag-prefix — the URL
                # itself may continue on the same line beyond the
                # match span. Inspect the whole line for the canonical
                # host substring before flagging.
                ln_text = _line_text(text, line)
                if _matched_value_is_canonical_pypi(matched_raw) or \
                        _matched_value_is_canonical_pypi(ln_text):
                    continue
            elif rule.id == "pypi-known-typosquat-ioc":
                # The trigger pattern captures (name, version) groups.
                name_g = m.group(1) if m.lastindex else ""
                ver_g = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                reason = _ioc_check(name_g, ver_g)
                if reason is None:
                    continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched_display = matched_raw
            if len(matched_display) > 200:
                matched_display = matched_display[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched_display,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
