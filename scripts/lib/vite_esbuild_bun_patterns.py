"""Vite / esbuild / Bun bundler-specific security patterns.

Wave 30 distillation round 16, angle vite-esbuild-bun.

Catalogue of 7 bundler-specific anti-patterns distilled in
``reports/distill-round-16/vite-esbuild-bun.md``. Targets Vite,
esbuild, Bun, and Turbopack-specific build surfaces that Wave 21
(``js_bundler_patterns.py``) does NOT cover.

What is NOT here (already shipped — DO NOT duplicate):

  * ``build.sourcemap: true`` on Vite config (Wave 21 h3)
  * ``devtool: 'source-map'`` on webpack (Wave 21 h1)
  * ``--sourcemap`` esbuild flag (Wave 21 h5)
  * ``define: { __X__: JSON.stringify(process.env.X) }`` (Wave 21 h7)
  * ``next.config.{js,ts}`` ``env`` block (Wave 21 h8)
  * ``loadEnv('mode', cwd, '')`` with no prefix (Wave 21 h10)
  * ``server.fs.allow: '/'`` (Wave 21 h14)
  * ``build.minify: false`` (Wave 21 h4)

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * veb-01-next-public-secret-in-env-file        (CRITICAL)
  * veb-02-vite-env-prefix-empty                 (HIGH)
  * veb-03-import-meta-glob-traversal            (HIGH)
  * veb-04-vite-proxy-embedded-credentials       (HIGH)
  * veb-05-esbuild-metafile-public-outdir        (HIGH)
  * veb-06-bun-registry-token-hardcoded          (CRITICAL)
  * veb-07-dev-server-in-prod-container          (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            js_bundler_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Insecure Output Handling (internal build metadata served
                                      publicly via metafile)
  ASI-04 — Data Exfiltration (secret inlined into client-side asset,
                               env var broadening, proxy credentials,
                               registry token in VCS)
  ASI-08 — Excessive Agency (dev tooling running in production context)

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
    """A single rule match — same shape as js_bundler_patterns.Finding."""

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
    js_bundler_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- VEB-01 : next-public-secret-in-env-file ----------------------------

# Matches: NEXT_PUBLIC_<anything>SECRET/KEY/TOKEN/PASSWORD/...<anything> = <value>
# The value must be at least 8 non-whitespace, non-comment characters.
# IGNORECASE covers NEXT_PUBLIC_API_KEY, NEXT_PUBLIC_api_key, etc.
_NEXT_PUBLIC_SECRET_ENV = _re(
    r"NEXT_PUBLIC_[A-Z0-9_]*"
    r"(?:SECRET|KEY|TOKEN|PASSWORD|PASS|PRIVATE|AUTH|CREDENTIAL|CLIENT_SECRET)"
    r"[A-Z0-9_]*\s*=\s*[^\s#]{8,}"
)

# ---- VEB-02 : vite-env-prefix-empty -------------------------------------

# Matches envPrefix: '' / "" / `` or envPrefix: [''] / [""] / [`]
# The empty string form broadens ALL env vars into import.meta.env.
_VITE_ENV_PREFIX_EMPTY_SCALAR = _re(
    r"envPrefix\s*:\s*(?:''|\"\")"
)

_VITE_ENV_PREFIX_EMPTY_ARRAY = _re(
    r"envPrefix\s*:\s*\[\s*(?:''|\"\")\s*\]"
)

# ---- VEB-03 : import-meta-glob-traversal --------------------------------

# Fires when import.meta.glob() contains two or more `../` traversals.
# That depth reaches outside the `src/` tree in typical project layouts.
_IMPORT_META_GLOB_TRAVERSAL = _re(
    r"import\.meta\.glob\s*\(\s*['\"`](?:\.\./){2,}"
)

# Second variant: glob pattern explicitly targeting .env files.
_IMPORT_META_GLOB_DOTENV = _re(
    r"import\.meta\.glob\s*\(\s*['\"`][^'\"` ]*\.env[^'\"` ]*['\"`]"
)

# ---- VEB-04 : vite-proxy-embedded-credentials ---------------------------

# Matches: https://user:…@host — whether it appears as the value of
# `target:` key or as a bare string shorthand (e.g. `'/api': 'https://...'`).
# The opening quote anchors the match; password must be at least 4 chars so
# that `http://user:@host/` (empty password) and port-only URLs don't fire.
_VITE_PROXY_CREDENTIALS = _re(
    r"['\"`]https?:[/]{2}[A-Za-z0-9._%-]+:[A-Za-z0-9!#$%&*+/=?^_{|}~.\-]{4,}[@]"
)

# ---- VEB-05 : esbuild-metafile-public-outdir ----------------------------

# API form: metafile: true anywhere in an esbuild config.
_ESBUILD_METAFILE_API = _re(
    r"metafile\s*:\s*true"
)

# CLI flag form: --metafile= pointing to a public output directory.
_ESBUILD_METAFILE_CLI = _re(
    r"--metafile=[^\s\"']*(?:dist|public|out|build)[^\s\"']*"
)

# Guard: if the metafile destination is clearly outside the web root,
# suppress the API-form finding.
_ESBUILD_METAFILE_SAFE_DEST_GUARDS: tuple[re.Pattern, ...] = (
    # writeFileSync / promises.writeFile to a non-public path
    _re(r"writeFile(?:Sync)?\s*\(\s*['\"`](?:tmp|reports|\.cache|artifacts|logs)/"),
    # explicit out path that is NOT dist/public/out/build
    _re(r"--metafile=(?!dist|public|out|build)"),
)

# ---- VEB-06 : bun-registry-token-hardcoded ------------------------------

# Matches: token = "something-that-does-not-start-with-$"
# The value must be at least 9 chars and not start with $ (env-var ref).
# Excludes obvious placeholder patterns containing < or > or REPLACE or EXAMPLE.
_BUN_REGISTRY_TOKEN = _re(
    r"token\s*=\s*\"(?:[^$\"<>])[A-Za-z0-9_\-+/]{12,}\""
)

# ---- VEB-07 : dev-server-in-prod-container ------------------------------

# CMD array form in Dockerfile: CMD ["npm", "run", "dev"], ["npx", "vite"],
# ["npx", "next", "dev"], etc.
# Matches a CMD [...] array that contains one of the dev-server keyword
# strings as a quoted element. The character class [^\]] stops at the
# closing bracket so we never cross into the next line.
_DEV_SERVER_DOCKERFILE_CMD = _re(
    r"""CMD\s+\[[^\]]*['"](?:dev|vite|vite preview|next)['"]\s*\]"""
)

# CMD shell form (no brackets): CMD npm run dev, CMD npx vite, etc.
_DEV_SERVER_DOCKERFILE_CMD_SHELL = _re(
    r"CMD\s+(?:npm run dev|yarn dev|pnpm dev|bun dev|npx vite|vite|next dev)"
)

# docker-compose / systemd command: form.
_DEV_SERVER_COMPOSE_COMMAND = _re(
    r"command\s*:\s*(?:npm run dev|yarn dev|pnpm dev|bun dev|vite|vite preview|next dev)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="veb-01-next-public-secret-in-env-file",
        name="NEXT_PUBLIC_* env-file key with secret-shaped name",
        severity="CRITICAL",
        description=(
            "Next.js inlines every variable whose name starts with "
            "`NEXT_PUBLIC_` into the client bundle at build time. A "
            "variable named `NEXT_PUBLIC_SECRET`, `NEXT_PUBLIC_API_KEY`, "
            "`NEXT_PUBLIC_STRIPE_SECRET_KEY`, etc. will appear as a string "
            "literal in every visitor's browser. Wave 21 rule h8 catches "
            "the same pattern in `next.config.*` `env:` blocks; this rule "
            "catches it in plain `.env`, `.env.local`, `.env.production` "
            "files. Use `NEXT_PUBLIC_` only for genuinely public values "
            "such as publishable API keys or app URLs."
        ),
        pattern=_NEXT_PUBLIC_SECRET_ENV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-02-vite-env-prefix-empty",
        name="Vite envPrefix: '' broadens all env vars to client bundle",
        severity="HIGH",
        description=(
            "Vite only exposes env vars prefixed by `envPrefix` (default "
            "`'VITE_'`) to `import.meta.env`. Setting `envPrefix: ''` "
            "(empty string) or `envPrefix: ['']` makes EVERY env var — "
            "including `DATABASE_URL`, `STRIPE_SECRET_KEY`, "
            "`GITHUB_TOKEN` — available inside the bundle. This is "
            "distinct from Wave 21 rule h10 which fires on the "
            "`loadEnv('mode', cwd, '')` call; this rule fires on the "
            "static `envPrefix` option in the Vite config object."
        ),
        pattern=_VITE_ENV_PREFIX_EMPTY_SCALAR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-02-vite-env-prefix-empty-array",
        name="Vite envPrefix: [''] (array form) broadens all env vars",
        severity="HIGH",
        description=(
            "Same risk as `envPrefix: ''` (scalar form) — the array "
            "form `envPrefix: ['']` also matches every env var including "
            "server-side secrets. See veb-02-vite-env-prefix-empty."
        ),
        pattern=_VITE_ENV_PREFIX_EMPTY_ARRAY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-03-import-meta-glob-traversal",
        name="import.meta.glob with deep ../.. traversal exposes internal files",
        severity="HIGH",
        description=(
            "Vite's `import.meta.glob()` resolves glob patterns at build "
            "time and bundles all matching files into the output. Patterns "
            "with two or more `../` traversals can reach outside the "
            "`src/` tree, accidentally including `.env` files, internal "
            "documentation, `*.pem` keys, or credential files. Restrict "
            "globs to paths under `src/` or use explicit absolute paths "
            "from `import.meta.url`."
        ),
        pattern=_IMPORT_META_GLOB_TRAVERSAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-03-import-meta-glob-dotenv",
        name="import.meta.glob pattern targets .env files",
        severity="HIGH",
        description=(
            "A `import.meta.glob()` call with a pattern containing `.env` "
            "will bundle environment files into the client-side output at "
            "build time, potentially exposing secrets declared in `.env`, "
            "`.env.local`, `.env.production`, etc."
        ),
        pattern=_IMPORT_META_GLOB_DOTENV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-04-vite-proxy-embedded-credentials",
        name="Vite server.proxy target URL contains embedded credentials",
        severity="HIGH",
        description=(
            "Vite dev-server proxy `target` field contains a URL with "
            "`user:password@` embedded credentials. This bakes "
            "authentication secrets directly into the version-controlled "
            "config file. Use `headers: { Authorization: 'Basic ...' }` "
            "with an env-var reference instead, keeping the credential "
            "out of the config."
        ),
        pattern=_VITE_PROXY_CREDENTIALS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-05-esbuild-metafile-public-outdir",
        name="esbuild metafile: true writes module graph to public output",
        severity="HIGH",
        description=(
            "esbuild's `metafile: true` writes a JSON file containing the "
            "complete module dependency graph — every file path, byte "
            "offset, import chain — to the `outdir` location. When "
            "`outdir` is a web-public directory (`dist/`, `public/`, "
            "`out/`, `build/`), the metafile is served alongside JS "
            "chunks, exposing internal module structure and absolute "
            "build-server paths to any visitor."
        ),
        pattern=_ESBUILD_METAFILE_API,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="veb-05-esbuild-metafile-cli-public",
        name="esbuild --metafile= CLI flag points to public output directory",
        severity="HIGH",
        description=(
            "esbuild `--metafile=` CLI flag with a path inside a "
            "web-public directory (`dist/`, `public/`, `out/`, `build/`) "
            "writes the complete module dependency graph where it will be "
            "served to visitors. Move the metafile output outside the "
            "web root (e.g. `--metafile=tmp/meta.json`)."
        ),
        pattern=_ESBUILD_METAFILE_CLI,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="veb-06-bun-registry-token-hardcoded",
        name="bunfig.toml scoped-registry token is a hardcoded literal",
        severity="CRITICAL",
        description=(
            "Bun's `bunfig.toml` `[install.scopes]` section supports a "
            "`token` field for private registry authentication. Setting "
            '`token = "literal-value"` (any string not starting with `$`) '
            "bakes the credential into the committed TOML file, exposing "
            "it to everyone with read access to the repository. Use "
            '`token = "$NPM_TOKEN"` (env-var reference) instead.'
        ),
        pattern=_BUN_REGISTRY_TOKEN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="veb-07-dev-server-dockerfile-cmd",
        name="Dockerfile CMD array runs Vite / Next dev server as production entrypoint",
        severity="HIGH",
        description=(
            "The Dockerfile `CMD` instruction (JSON array form) runs a "
            "development server (`npm run dev`, `vite`, `next dev`, etc.) "
            "as the production container entrypoint. Dev servers expose "
            "HMR websocket endpoints, detailed error overlays with full "
            "source traces, and — in Vite's case — serve files from the "
            "project root without a restrictive CSP. Production containers "
            "must use a production server (nginx, caddy, `next start`, etc.)."
        ),
        pattern=_DEV_SERVER_DOCKERFILE_CMD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="veb-07-dev-server-dockerfile-cmd-shell",
        name="Dockerfile CMD shell form runs Vite / Next dev server as production entrypoint",
        severity="HIGH",
        description=(
            "The Dockerfile `CMD` instruction (shell form) runs a "
            "development server (`npm run dev`, `vite`, `next dev`, etc.) "
            "as the production container entrypoint. Dev servers expose "
            "HMR websocket endpoints, detailed error overlays with full "
            "source traces. Production containers must use a production "
            "server (nginx, caddy, `next start`, etc.)."
        ),
        pattern=_DEV_SERVER_DOCKERFILE_CMD_SHELL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="veb-07-dev-server-compose-command",
        name="docker-compose / systemd command runs dev server in production",
        severity="HIGH",
        description=(
            "A `command:` field in docker-compose or a systemd "
            "`ExecStart=` runs a Vite / Next development server as the "
            "production service command. This exposes HMR endpoints, "
            "source-map-annotated error overlays, and the dev-server "
            "filesystem API to production traffic."
        ),
        pattern=_DEV_SERVER_COMPOSE_COMMAND,
        owasp_asi="ASI-08",
    ),
)


# ---- Helper functions ----------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Two-stage filtering:

    * VEB-05 (metafile-api) — suppress if the file contains a
      ``writeFileSync`` / ``writeFile`` call pointing to a non-public
      path, indicating the metafile is intentionally kept outside
      the web root.

    Findings are deduped by (rule_id, line, col). Output is sorted
    by (line, column, rule_id) for deterministic ordering.
    """
    if not text:
        return []

    # File-level guard evaluation — one shot per file.
    esbuild_metafile_safe = _file_contains_any(text, _ESBUILD_METAFILE_SAFE_DEST_GUARDS)

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

    # ---- VEB-01 : next-public-secret-in-env-file ----
    rule_veb01 = rule_by_id["veb-01-next-public-secret-in-env-file"]
    for m in _NEXT_PUBLIC_SECRET_ENV.finditer(text):
        _emit(rule_veb01, m.start(), m.group(0))

    # ---- VEB-02 : vite-env-prefix-empty (scalar) ----
    rule_veb02_scalar = rule_by_id["veb-02-vite-env-prefix-empty"]
    for m in _VITE_ENV_PREFIX_EMPTY_SCALAR.finditer(text):
        _emit(rule_veb02_scalar, m.start(), m.group(0))

    # ---- VEB-02 : vite-env-prefix-empty (array) ----
    rule_veb02_array = rule_by_id["veb-02-vite-env-prefix-empty-array"]
    for m in _VITE_ENV_PREFIX_EMPTY_ARRAY.finditer(text):
        _emit(rule_veb02_array, m.start(), m.group(0))

    # ---- VEB-03 : import-meta-glob-traversal ----
    rule_veb03_traversal = rule_by_id["veb-03-import-meta-glob-traversal"]
    for m in _IMPORT_META_GLOB_TRAVERSAL.finditer(text):
        _emit(rule_veb03_traversal, m.start(), m.group(0))

    # ---- VEB-03 : import-meta-glob-dotenv ----
    rule_veb03_dotenv = rule_by_id["veb-03-import-meta-glob-dotenv"]
    for m in _IMPORT_META_GLOB_DOTENV.finditer(text):
        _emit(rule_veb03_dotenv, m.start(), m.group(0))

    # ---- VEB-04 : vite-proxy-embedded-credentials ----
    rule_veb04 = rule_by_id["veb-04-vite-proxy-embedded-credentials"]
    for m in _VITE_PROXY_CREDENTIALS.finditer(text):
        _emit(rule_veb04, m.start(), m.group(0))

    # ---- VEB-05 : esbuild-metafile-public-outdir (API form) ----
    rule_veb05_api = rule_by_id["veb-05-esbuild-metafile-public-outdir"]
    if not esbuild_metafile_safe:
        for m in _ESBUILD_METAFILE_API.finditer(text):
            _emit(rule_veb05_api, m.start(), m.group(0))

    # ---- VEB-05 : esbuild-metafile-cli-public (CLI flag form) ----
    rule_veb05_cli = rule_by_id["veb-05-esbuild-metafile-cli-public"]
    for m in _ESBUILD_METAFILE_CLI.finditer(text):
        _emit(rule_veb05_cli, m.start(), m.group(0))

    # ---- VEB-06 : bun-registry-token-hardcoded ----
    rule_veb06 = rule_by_id["veb-06-bun-registry-token-hardcoded"]
    for m in _BUN_REGISTRY_TOKEN.finditer(text):
        _emit(rule_veb06, m.start(), m.group(0))

    # ---- VEB-07 : dev-server-dockerfile-cmd (array form) ----
    rule_veb07_docker = rule_by_id["veb-07-dev-server-dockerfile-cmd"]
    for m in _DEV_SERVER_DOCKERFILE_CMD.finditer(text):
        _emit(rule_veb07_docker, m.start(), m.group(0))

    # ---- VEB-07 : dev-server-dockerfile-cmd-shell (shell form) ----
    rule_veb07_docker_shell = rule_by_id["veb-07-dev-server-dockerfile-cmd-shell"]
    for m in _DEV_SERVER_DOCKERFILE_CMD_SHELL.finditer(text):
        _emit(rule_veb07_docker_shell, m.start(), m.group(0))

    # ---- VEB-07 : dev-server-compose-command ----
    rule_veb07_compose = rule_by_id["veb-07-dev-server-compose-command"]
    for m in _DEV_SERVER_COMPOSE_COMMAND.finditer(text):
        _emit(rule_veb07_compose, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
