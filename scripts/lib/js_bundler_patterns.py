"""JS bundler / build-tool config attack-surface patterns.

Wave 21 impl angle H — distillation of the 15 proposals from
``reports/distill-round-7/js-bundler-config.md`` into deterministic
regex rules.

Scope: bundler/build-tool *configuration* files
(``webpack.config.{js,ts}``, ``vite.config.{js,ts}``,
``rollup.config.{js,ts}``, ``next.config.{js,ts}``,
``esbuild.config.{js,ts}``, ``tsup.config.{js,ts}``,
``workbox-config.{js,ts}``) and a smaller set of built-artefact
shapes (``sourceMappingURL`` pragma drift in shipped JS).

Targets four convergent failure modes:

  * Source-map leakage in production bundles
    (``devtool: 'source-map'``, ``build.sourcemap: true``,
    ``--sourcemap`` esbuild flag, ``productionBrowserSourceMaps``,
    third-party-host ``sourceMappingURL`` pragmas).
  * Build-time env-var inlining of server secrets
    (``define: { __SECRET__: JSON.stringify(process.env.X) }``,
    ``next.config.env`` containing secret-named keys,
    ``loadEnv('mode', cwd, '')`` with no prefix).
  * Dev-mode artefacts shipped to prod
    (``mode: 'development'`` or missing mode on unconditional
    export, ``build.minify: false``, ``server.fs.allow: '/'``).
  * Public recon surfaces shipped to CDN
    (``BundleAnalyzerPlugin`` writing into ``output.path``,
    ``__webpack_public_path__`` derived from untrusted source).

Cross-reference:

  * ``frontend_patterns.py`` (Wave 17) — React/Vue/Svelte DOM XSS
    sinks. No overlap: that ruleset fires on application source,
    this one fires on bundler config.
  * ``oauth_device_flow_patterns.py`` (Wave 19) —
    ``VITE_*_SECRET`` / ``NEXT_PUBLIC_*_SECRET`` identifier shape in
    source code. No overlap: that ruleset fires on the identifier;
    this one fires on the **substitution mechanism** (``define``,
    ``next.config.env``, ``loadEnv``) that lets the identifier be
    authored. A repo can trip Wave 19 without tripping this module
    (env file declares the leaked var but config never inlines it)
    and vice-versa.

Architecture mirrors ``scripts/lib/auth_flow_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
  * ``RULES`` — ordered tuple of every catalogued rule.
  * ``scan_text(text) -> list[Finding]`` — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)`` — single finding record.

Pure-stdlib (re, NamedTuple). All regex patterns are RE2-safe — no
backreferences, no possessive quantifiers, no nested-quantifier
catastrophic backtracking surfaces. Tested by the companion
``tests/test_js_bundler_patterns.py``.

OWASP ASI mapping:
  ASI-02 — Insecure Output Handling (source-map leak, public dir
           recon files, ``sourceMappingURL`` drift).
  ASI-04 — Data Exfiltration (define / env-block secret inline,
           loadEnv-no-prefix, SW precache of .env).
  ASI-05 — Supply-chain / lazy-chunk hijack
           (``__webpack_public_path__`` from untrusted source,
           dev FS-allow exposing prod).
  ASI-08 — Excessive Agency (dev-mode artefacts in prod build —
           unminified, eval-source-map, dev FS-allow).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/auth_flow_patterns.Finding`` so heartbeat detectors
    and SARIF emitters render either kind uniformly."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper
    used by ``auth_flow_patterns.py`` and ``frontend_patterns.py``.

    Bundler-config property names are case-sensitive in real JS
    (``DefinePlugin`` vs ``defineplugin``), but the IGNORECASE flag
    matches the pattern used across the other Wave-N rulesets and
    keeps a single helper. Patterns that NEED case-sensitivity
    (e.g. ``SECRET`` discriminator on a key) are written so that
    the literal alpha part is the structural anchor and the rest
    is an explicit charset — IGNORECASE doesn't change the truth
    of the match in those cases.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- H-1 : webpack-prod-source-map --------------------------------------


# webpack `devtool: 'source-map'` (any variant containing 'source-map')
# in a config that ALSO sets `mode: 'production'` or has no mode
# (defaults to production). The two-stage rule is: trigger on the
# devtool literal, then in scan_text inspect a 30-line surrounding
# window for the `mode: 'production'` literal OR an unconditional
# top-level shape (no mode-gating function wrapper).
_WEBPACK_PROD_SOURCE_MAP = _re(
    r"\bdevtool\s*:\s*['\"](?:eval-)?(?:cheap(?:-module)?-)?(?:inline-)?source-map['\"]"
)

# File-level negative guards — if any of these appears anywhere in
# the file, we trust the author has gated the devtool.
_WEBPACK_DEV_SOURCE_MAP_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bargv\.mode\s*===\s*['\"]development['\"]"),
    _re(r"\benv\.NODE_ENV\s*!==\s*['\"]production['\"]"),
    _re(r"\bprocess\.env\.NODE_ENV\s*!==\s*['\"]production['\"]"),
    _re(r"#\s*webpack-devtool-gated\b"),
    _re(r"//\s*webpack-devtool-gated\b"),
)


# ---- H-2 : webpack-mode-misset ------------------------------------------


# webpack config exporting an object that has `mode: 'development'`
# OR is missing the mode property entirely. The latter is detected
# by requiring a `module.exports = {` / `export default {` shape that
# DOESN'T set mode anywhere in the file.
_WEBPACK_MODE_DEVELOPMENT_LITERAL = _re(
    r"\bmode\s*:\s*['\"]development['\"]"
)

# Trigger for the "missing mode" sub-case — we anchor on the
# require/import of webpack itself (idiomatic in a webpack.config.*).
_WEBPACK_CONFIG_ANCHOR = _re(
    r"\brequire\s*\(\s*['\"]webpack['\"]\s*\)"
    r"|"
    r"\bfrom\s+['\"]webpack['\"]"
)

# Negative guard: any `mode: 'production'` literal anywhere in the
# file means the author has set mode somewhere.
_WEBPACK_MODE_PRODUCTION = _re(
    r"\bmode\s*:\s*['\"]production['\"]"
)


# ---- H-3 : vite-prod-sourcemap ------------------------------------------


# Vite `build.sourcemap: true | 'inline' | 'both'` in an unconditional
# export. Acceptable: `false`, `'hidden'`. Two-stage — if file has a
# `mode === 'development'` conditional that gates the property, the
# scan_text helper will check the immediate surrounding window for it.
_VITE_PROD_SOURCEMAP = _re(
    r"\bsourcemap\s*:\s*(?:true|['\"](?:inline|both)['\"])"
)

# File-level guard — if the source explicitly mentions mode-gating,
# the dev is doing the right thing and we suppress hits.
_VITE_MODE_GATE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bmode\s*===\s*['\"]development['\"]"),
    _re(r"\bmode\s*!==\s*['\"]production['\"]"),
    _re(r"#\s*vite-sourcemap-gated\b"),
    _re(r"//\s*vite-sourcemap-gated\b"),
)

# Vite-config file anchor — we only flag if the file looks like a
# Vite config.
_VITE_CONFIG_ANCHOR = _re(
    r"\bdefineConfig\s*\("
    r"|"
    r"\bfrom\s+['\"]vite['\"]"
    r"|"
    r"\brequire\s*\(\s*['\"]vite['\"]\s*\)"
)


# ---- H-4 : vite-prod-no-minify ------------------------------------------


# `build.minify: false` literal in a Vite config (or compatible
# shape). The Vite-config file anchor and library-mode guard apply.
_VITE_MINIFY_FALSE = _re(
    r"\bminify\s*:\s*false\b"
)

_VITE_LIB_MODE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bbuild\s*:\s*\{[^}]{0,400}\blib\s*:"),
    _re(r"\blib\s*:\s*\{"),
    _re(r"#\s*vite-library-build\b"),
    _re(r"//\s*vite-library-build\b"),
)

# Electron / Tauri / VSCode-extension markers — non-public targets
# where minify-off is conventional.
_VITE_NON_PUBLIC_TARGET_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsrc-tauri\b"),
    _re(r"\belectron-builder\b"),
    _re(r"['\"]electron['\"]"),
    _re(r"\bvsce\b"),
    _re(r"#\s*vite-non-public-target\b"),
)


# ---- H-5 : esbuild-prod-sourcemap-flag ----------------------------------


# esbuild CLI invocation in a package.json script or build script
# that includes `--sourcemap` WITHOUT `=hidden`. RE2-safe: the
# negative-lookahead is on a fixed-length tail, no backtracking risk.
_ESBUILD_PROD_SOURCEMAP_FLAG = _re(
    # Either bare `--sourcemap` (without `=hidden`) or `--sourcemap=`
    # with one of inline|external|both|linked|true.
    r"\besbuild\b[^\n]{0,200}--sourcemap(?:=(?:inline|external|both|linked|true))?\b"
)

# esbuild API form: `require('esbuild').build({ sourcemap: ... })` or
# `esbuild.build({ sourcemap: ... })` with a truthy value. The leading
# alternative covers both shapes (bare module call and require chain).
# Note: [\s\S] is required (not [^)]) since the body of build() can
# contain parens — e.g. `process.cwd()` — that would otherwise
# break the {0,400} window. Non-greedy minimises catastrophic-backtrack
# risk on long inputs (RE2-safe shape).
_ESBUILD_API_SOURCEMAP = _re(
    r"(?:\besbuild|require\s*\(\s*['\"]esbuild['\"]\s*\))"
    r"\.build\s*\(\s*\{[\s\S]{0,400}?"
    r"\bsourcemap\s*:\s*"
    r"(?:true|['\"](?:inline|external|both|linked)['\"])"
)

# Negative-script guard: if the surrounding script name contains
# dev/watch/debug/start, suppress.
_ESBUILD_DEV_SCRIPT_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"['\"](?:dev|watch|start|serve|debug)['\"]\s*:"),
    _re(r"NODE_ENV=development\b"),
    _re(r"#\s*esbuild-sourcemap-gated\b"),
)

# Hidden flag — the safe form. If `--sourcemap=hidden` appears on
# the same line, suppress the hit.
_ESBUILD_SOURCEMAP_HIDDEN = _re(
    r"--sourcemap=hidden\b"
)


# ---- H-6 : rollup-prod-sourcemap ----------------------------------------


# Rollup `output.sourcemap: true` or `'inline'`. Library mode is the
# legitimate use-case (consumers benefit from source maps), so we
# guard on `package.json.main` / `module` / `exports` / `publishConfig`
# signatures present in the same file.
_ROLLUP_OUTPUT_SOURCEMAP = _re(
    r"\boutput\s*:\s*\{[^}]{0,400}\bsourcemap\s*:\s*(?:true|['\"]inline['\"])"
    r"|"
    r"\bsourcemap\s*:\s*(?:true|['\"]inline['\"])\s*,[^\n]{0,200}\bformat\s*:\s*['\"](?:iife|umd|cjs)['\"]"
)

# Library-mode guard. If the rollup config also imports/declares a
# library export shape, it's a library build and source-maps are
# conventional.
_ROLLUP_LIBRARY_GUARDS: tuple[re.Pattern, ...] = (
    # `format: 'es'` — trailing \b would expect a word char after `'`,
    # which never happens (the quote is the boundary). Drop \b.
    _re(r"\bformat\s*:\s*['\"]es['\"]"),
    _re(r"#\s*rollup-library-build\b"),
    _re(r"\bpublishConfig\s*:"),
    _re(r"//\s*rollup-library-build\b"),
)


# ---- H-7 : define-secret-inline -----------------------------------------


# A `define` ObjectExpression substitution that bakes a secret into
# the bundle. Three sub-shapes:
#   (a) The KEY of the define matches `*SECRET*` / `*TOKEN*` /
#       `*PASSWORD*` / `*PRIVATE_KEY*` / `*API_KEY*` (case-insens).
#   (b) The VALUE is `JSON.stringify(process.env.X)` where X is in
#       the same set.
#   (c) The VALUE is a bare `process.env.X` (no JSON.stringify) for
#       any of the secret-named keys — the worst form (syntax-break /
#       quote-injection / shell-injection-style substitution).
_DEFINE_SECRET_INLINE = _re(
    # (a) KEY shape: `__ANTHROPIC_API_KEY__: ...` or
    # `__SECRET__: ...` — the value side starts with `:` and any
    # characters up to a comma or closing brace.
    r"\b__[A-Z0-9_]*(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))[A-Z0-9_]*__\s*:"
    r"|"
    # (a') Bare `SECRET: ...` / `API_KEY: ...` inside a `define`
    # block. The `define` anchor is checked in the scan-text helper.
    r"['\"]?(?:[A-Z][A-Z0-9_]{0,40}_)?(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))['\"]?\s*:\s*"
    r"(?:JSON\.stringify\s*\(\s*)?process\.env\."
    r"|"
    # (b) `JSON.stringify(process.env.*SECRET*)` etc. — the secret
    # name on the right side of the substitution.
    r"JSON\.stringify\s*\(\s*process\.env\.[A-Z_]*"
    r"(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))[A-Z_]*\s*\)"
    r"|"
    # (c) Raw `process.env.*SECRET*` — no JSON.stringify wrapper.
    r"\bprocess\.env\.[A-Z_]*"
    r"(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))[A-Z_]*\b"
)

# Define-block anchor — only fire H-7 in a file that uses a
# `define` / `DefinePlugin` / `replace-plugin` shape.
_DEFINE_BLOCK_ANCHOR = _re(
    r"\bdefine\s*:\s*\{"
    r"|"
    r"\bnew\s+webpack\.DefinePlugin\s*\("
    r"|"
    r"\bnew\s+DefinePlugin\s*\("
    r"|"
    r"\brollup-plugin-replace\b"
    r"|"
    r"\bfrom\s+['\"]@rollup/plugin-replace['\"]"
)

# False-positive guards: well-known harmless build metadata keys.
_DEFINE_HARMLESS_KEY_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\b__BUILD_TIME__\b"),
    _re(r"\b__BUILD_DATE__\b"),
    _re(r"\b__VERSION__\b"),
    _re(r"\b__COMMIT_SHA__\b"),
    _re(r"\b__COMMIT_HASH__\b"),
    _re(r"\b__APP_NAME__\b"),
    _re(r"\b__DEV__\b"),
    _re(r"\b__PROD__\b"),
)


# ---- H-8 : next-env-block-secret ----------------------------------------


# Next.js `next.config.{js,ts}` env block containing a secret-named
# key. The two-step rule: anchor on `env:` block; THEN trigger if
# the inner object has a key matching the secret pattern.
_NEXT_ENV_BLOCK_SECRET = _re(
    # `env: { *SECRET*: ... }` or `env: { *_PRIVATE_KEY*: ... }`.
    # Negative lookahead drops `*_TOKEN_PUBLIC` and `*_API_KEY_PUBLIC`
    # since those are explicit public-marker keys.
    r"\benv\s*:\s*\{[^}]{0,400}"
    r"['\"]?[A-Z][A-Z0-9_]*"
    r"(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))"
    r"[A-Z0-9_]*['\"]?\s*:"
    r"|"
    # `publicRuntimeConfig` shape — same surface, same risk.
    r"\bpublicRuntimeConfig\s*:\s*\{[^}]{0,400}"
    r"['\"]?[A-Z][A-Z0-9_]*"
    r"(?:SECRET|TOKEN(?!_PUBLIC)|PRIVATE_KEY|PASSWORD|API_KEY(?!_PUBLIC))"
    r"[A-Z0-9_]*['\"]?\s*:"
)

# Anchor for Next-config files — `next.config.*` shape detection.
_NEXT_CONFIG_ANCHOR = _re(
    r"\bnext\.config\b"
    r"|"
    r"\bNextConfig\b"
    r"|"
    r"\bmodule\.exports\s*=\s*\{[^}]{0,400}\b(?:experimental|env|publicRuntimeConfig|serverRuntimeConfig|images|i18n)\b"
)

# Hard-coded token-shape recognisers — if the value next to the key
# is a literal token, that's also a leak.
_NEXT_HARDCODED_TOKEN_VALUE = _re(
    r":\s*['\"](?:sk-(?:ant-|proj-|live-)?[A-Za-z0-9_-]{16,}"
    r"|ghp_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xoxb-[A-Za-z0-9-]{20,}"
    r"|AKIA[A-Z0-9]{16}"
    r"|AIza[A-Za-z0-9_-]{30,})['\"]"
)


# ---- H-9 : next-prod-browser-source-maps --------------------------------


_NEXT_PROD_BROWSER_SOURCE_MAPS = _re(
    r"\bproductionBrowserSourceMaps\s*:\s*true\b"
)

# Sentry-webpack-plugin guard — the legitimate way to ship maps with
# automated stripping.
_NEXT_SENTRY_PLUGIN_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bfrom\s+['\"]@sentry/nextjs['\"]"),
    _re(r"\brequire\s*\(\s*['\"]@sentry/nextjs['\"]\s*\)"),
    _re(r"\bwithSentryConfig\s*\("),
    _re(r"#\s*sentry-handles-sourcemaps\b"),
    _re(r"//\s*sentry-handles-sourcemaps\b"),
)


# ---- H-10 : vite-loadenv-no-prefix --------------------------------------


# `loadEnv(mode, cwd, '')` or `loadEnv(mode, cwd, [''])` — only the
# EXPLICIT empty-string prefix forms are dangerous. `loadEnv(mode,
# cwd)` defaults to `'VITE_'` and is safe. Use [\s\S] non-greedy
# because the arg list usually contains `process.cwd()` whose parens
# would defeat a `[^)]` char-class.
_VITE_LOADENV_NO_PREFIX = _re(
    r"\bloadEnv\s*\([\s\S]{0,200}?,\s*['\"]['\"]\s*\)"
    r"|"
    r"\bloadEnv\s*\([\s\S]{0,200}?,\s*\[\s*['\"]['\"]\s*\]\s*\)"
)


# ---- H-11 : sw-precache-env ---------------------------------------------


# Service-worker / workbox config with a catch-all glob OR a runtime
# cache route that matches everything with CacheFirst.
_SW_PRECACHE_OVERBROAD = _re(
    # `globPatterns: ['**/*.*']` or `globPatterns: ['**/*']` —
    # catch-all extensions.
    r"\bglobPatterns\s*:\s*\[[^\]]*['\"](?:\*\*/\*\.\*|\*\*/\*)['\"]"
    r"|"
    # `urlPattern: /.*/` or `urlPattern: () => true` AND
    # CacheFirst.
    r"\burlPattern\s*:\s*/\.\*/"
    r"|"
    r"\burlPattern\s*:\s*\([^)]*\)\s*=>\s*true\b"
)

# Negative guard — if the same file also lists `globIgnores` with
# `.env*` or `.map`, the author is doing the right thing.
_SW_GLOB_IGNORE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bglobIgnores\s*:\s*\[[^\]]{0,400}['\"][^'\"]*\.env"),
    _re(r"\bglobIgnores\s*:\s*\[[^\]]{0,400}['\"][^'\"]*\.map['\"]"),
    _re(r"#\s*sw-globignores-verified\b"),
)


# ---- H-12 : stats-in-public-dir -----------------------------------------


# BundleAnalyzerPlugin / rollup-plugin-visualizer / similar emitting
# a `report.html` / `stats.json` into the public output dir.
_BUNDLE_ANALYZER_PUBLIC_OUTPUT = _re(
    # `new BundleAnalyzerPlugin({ analyzerMode: 'static' })` —
    # default report.html lands in output.path.
    r"\bnew\s+BundleAnalyzerPlugin\s*\([^)]{0,300}analyzerMode\s*:\s*['\"]static['\"]"
    r"|"
    # `visualizer({ filename: 'dist/...html' })`
    r"\bvisualizer\s*\(\s*\{[^}]{0,300}filename\s*:\s*['\"](?:dist|build|out|public|\.next)/[^'\"]*\.html['\"]"
    r"|"
    # `reportFilename: 'dist/...html'` / 'report.html' (relative,
    # which resolves into output.path)
    r"\breportFilename\s*:\s*['\"](?!\.\.)(?!/)[^'\"]*\.html['\"]"
    r"|"
    # Plain `new BundleAnalyzerPlugin()` with no opts — default
    # `report.html` in output.path.
    r"\bnew\s+BundleAnalyzerPlugin\s*\(\s*\)"
)

# Negative guards — gated under ANALYZE env var.
_BUNDLE_ANALYZER_GATE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bprocess\.env\.ANALYZE\b"),
    _re(r"\benv\.ANALYZE\b"),
    _re(r"#\s*bundle-analyzer-gated\b"),
    _re(r"//\s*bundle-analyzer-gated\b"),
)


# ---- H-13 : public-path-untrusted ---------------------------------------


# `__webpack_public_path__` derived from a runtime source we can
# observe, OR `output.publicPath` set to a callable returning a
# runtime env var.
_WEBPACK_PUBLIC_PATH_UNTRUSTED = _re(
    # Assignment from window.location.search / referrer / data-*
    # attribute / query-string parse.
    r"\b__webpack_public_path__\s*=\s*"
    r"(?:window\.location\.(?:search|hash|href|origin)"
    r"|document\.referrer"
    r"|document\.currentScript\.dataset\b"
    r"|getAttribute\s*\(\s*['\"]data-)"
    r"|"
    # `output.publicPath: (file) => process.env.PUBLIC_CDN_URL`
    r"\bpublicPath\s*:\s*\([^)]*\)\s*=>\s*[^,;\n]{0,200}process\.env\."
)

# CSP guard — if the project has a strict CSP `script-src 'self'`
# rule somewhere in the same file or a sibling config, suppress.
_CSP_STRICT_SELF_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"['\"]script-src\b[^'\"]*['\"]self['\"]"),
    _re(r"#\s*csp-script-src-self-verified\b"),
    _re(r"//\s*csp-script-src-self-verified\b"),
)


# ---- H-14 : vite-fs-allow-overbroad -------------------------------------


# `server.fs.allow: ['/']` or `server.fs.strict: false` — broadens
# the dev FS-exposure surface to root.
_VITE_FS_ALLOW_ROOT = _re(
    r"\bfs\s*:\s*\{[^}]{0,200}\ballow\s*:\s*\[[^\]]{0,200}['\"]\/['\"]"
    r"|"
    r"\bfs\s*:\s*\{[^}]{0,200}\bstrict\s*:\s*false\b"
    r"|"
    # Standalone allow: ['/'] form (top-level under server.fs).
    r"\ballow\s*:\s*\[\s*['\"]\/['\"]\s*\]"
    r"|"
    # Allow contains '..' / '../' / 'process.cwd() + .. ' etc.
    r"\ballow\s*:\s*\[[^\]]{0,200}['\"]\.\.['\"]"
)

# Loopback-bind guard — if the dev server is bound to 127.0.0.1
# and strictPort is true, the leak surface is at least contained
# to the local box (still flag, but the rule wants a guard).
_VITE_LOOPBACK_BIND_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bhost\s*:\s*['\"]127\.0\.0\.1['\"]\s*,[^}]{0,200}strictPort\s*:\s*true"),
    _re(r"#\s*vite-fs-loopback-verified\b"),
)


# ---- H-15 : source-mapping-url-drift ------------------------------------


# `//# sourceMappingURL=` pragma in a built artefact pointing at a
# non-loopback, non-relative HTTPS/HTTP URL. Loopback and data:
# URLs are fine. Same-origin relative paths are fine.
# RE2-safe: only fixed-length negative-lookaheads, no nested quantifier
# multiplication that could trigger ReDoS.
_SOURCE_MAPPING_URL_DRIFT = _re(
    r"//[#@]\s*sourceMappingURL\s*=\s*"
    r"(?!data:)"
    r"(?!/[^/])"
    r"(?:https?:)?//"
    r"(?!localhost\b)(?!127\.0\.0\.1\b)(?!\[::1\])"
    r"[A-Za-z0-9.-]{1,200}"
    r"/[^\s\n]{1,200}"
)

# Bundler-config `sourceMapFilename` / `sourcemapFileNames` with a
# hard-coded non-relative external URL.
_SOURCE_MAP_FILENAME_DRIFT = _re(
    r"\b(?:sourceMapFilename|sourcemapFileNames)\s*:\s*['\"]https?://[^'\"]+['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bundler-h1-webpack-prod-source-map",
        name="webpack production build emits original-source map",
        severity="CRITICAL",
        description=(
            "webpack `devtool` is set to a `*source-map*` value in a "
            "config that lacks dev-mode gating. The emitted `.map` "
            "file contains the FULL original source — including "
            "`process.env.*` references, server-only helpers, and "
            "inline secrets — and the bundle's `sourceMappingURL` "
            "pragma fetches it from the public CDN. Production builds "
            "must use `devtool: false` or `'hidden-source-map'` (the "
            "latter omits the URL pragma; the map only ships if "
            "uploaded out-of-band to Sentry / Datadog)."
        ),
        pattern=_WEBPACK_PROD_SOURCE_MAP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h2-webpack-mode-misset",
        name="webpack config exports with mode=development or missing mode",
        severity="HIGH",
        description=(
            "webpack config exports an object with `mode: 'development'` "
            "on an unconditional export. Dev mode disables TerserPlugin "
            "minification, skips DefinePlugin's `NODE_ENV='production'` "
            "substitution, and ships unminified source + dev-only "
            "warnings. Production builds must export "
            "`mode: 'production'` (or use the function form gated by "
            "`argv.mode`)."
        ),
        pattern=_WEBPACK_MODE_DEVELOPMENT_LITERAL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="bundler-h3-vite-prod-sourcemap",
        name="Vite build.sourcemap exposes original source in prod",
        severity="CRITICAL",
        description=(
            "Vite `build.sourcemap` is `true`, `'inline'`, or `'both'` "
            "on an unconditional export. Default is `false`. `true` "
            "ships a sibling `.map` for every chunk; `'inline'` "
            "embeds the map inside the JS, doubling bundle size. "
            "Either form exposes server-import-resolution traces, "
            "`define` substitutions, and original module paths. Use "
            "`'hidden'` when a map is uploaded out-of-band."
        ),
        pattern=_VITE_PROD_SOURCEMAP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h4-vite-prod-no-minify",
        name="Vite build.minify: false ships unmangled identifiers",
        severity="HIGH",
        description=(
            "Vite `build.minify: false` ships every server-only "
            "helper name, every `if (process.env.X)` branch, and "
            "every internal API path in plain text. Combined with "
            "`define` substitutions, server-imported constants land "
            "in the bundle unobfuscated. Default is `'esbuild'`; "
            "explicit `false` is usually a forgotten debug toggle."
        ),
        pattern=_VITE_MINIFY_FALSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="bundler-h5-esbuild-prod-sourcemap-flag",
        name="esbuild production script ships --sourcemap flag",
        severity="CRITICAL",
        description=(
            "esbuild invocation includes `--sourcemap` (without "
            "`=hidden`) or sets `sourcemap: true` in the build API. "
            "esbuild has no `mode` concept — the same config runs "
            "dev and prod unless the developer branches manually. "
            "`--sourcemap` without value is `external` (writes "
            "`.map` next to output); `inline` doubles bundle size; "
            "`both` does both. Only `--sourcemap=hidden` is safe "
            "for prod."
        ),
        pattern=_ESBUILD_PROD_SOURCEMAP_FLAG,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h5-esbuild-prod-sourcemap-api",
        name="esbuild build() API call sets sourcemap: true / inline / external / both",
        severity="CRITICAL",
        description=(
            "esbuild's JS build API is invoked with `sourcemap: "
            "true` / `'inline'` / `'external'` / `'both'`. Same risk "
            "surface as the CLI flag — emits a `.map` containing "
            "original source. Use `sourcemap: 'hidden'` (no URL "
            "pragma) or omit entirely for production."
        ),
        pattern=_ESBUILD_API_SOURCEMAP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h6-rollup-prod-sourcemap",
        name="Rollup output.sourcemap true on application bundle",
        severity="HIGH",
        description=(
            "Rollup `output.sourcemap: true` writes a sibling `.map` "
            "and adds `//# sourceMappingURL=` to the JS. For "
            "application bundles shipped to end users via CDN this "
            "is a leak. For published NPM libraries source maps are "
            "often intentional — but a private lib that gets "
            "`npm publish`-ed accidentally with `sourcemap: "
            "'inline'` doubles size and ships full source."
        ),
        pattern=_ROLLUP_OUTPUT_SOURCEMAP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h7-define-secret-inline",
        name="Bundler define block inlines a server secret into the bundle",
        severity="CRITICAL",
        description=(
            "A `define` substitution (`vite.config.define`, "
            "`webpack.DefinePlugin`, `esbuild.build({define})`, "
            "`rollup-plugin-replace`) bakes a secret-named env var "
            "(`*_SECRET`, `*_API_KEY`, `*_TOKEN`, `*_PRIVATE_KEY`, "
            "`*_PASSWORD`) into every chunk that references it. The "
            "bundle is then served from a public CDN. `define` is "
            "for build metadata (build time, version, commit SHA) — "
            "server secrets stay server-only; client-side calls go "
            "through an authenticated same-origin API route."
        ),
        pattern=_DEFINE_SECRET_INLINE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bundler-h8-next-env-block-secret",
        name="Next.js next.config.env contains server-only secret name",
        severity="CRITICAL",
        description=(
            "Next.js `next.config.{js,ts}` `env` (or "
            "`publicRuntimeConfig`) block declares a key whose name "
            "ends in `_SECRET` / `_TOKEN` / `_PRIVATE_KEY` / "
            "`_PASSWORD` / `_API_KEY`. Next's `env` block is the "
            "canonical client-bundle env-inlining mechanism: anything "
            "listed there ships to every browser via "
            "`process.env.<KEY>`. Server secrets belong in "
            "`serverRuntimeConfig` or raw `process.env.X` reads "
            "from Server Components / Route Handlers."
        ),
        pattern=_NEXT_ENV_BLOCK_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bundler-h8-next-env-block-hardcoded-token",
        name="Next.js next.config.env contains a hard-coded token literal",
        severity="CRITICAL",
        description=(
            "Next.js `env` block declares a key whose value is a "
            "literal token (`sk-...`, `ghp_...`, `github_pat_...`, "
            "`xoxb-...`, `AKIA...`, `AIza...`). The literal ships to "
            "every browser through `process.env.<KEY>` substitution. "
            "Remove and replace with a server-only secret read."
        ),
        pattern=_NEXT_HARDCODED_TOKEN_VALUE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bundler-h9-next-prod-browser-source-maps",
        name="Next.js productionBrowserSourceMaps: true ships maps to public CDN",
        severity="HIGH",
        description=(
            "Next.js `productionBrowserSourceMaps: true` ships a "
            "`.map` per chunk to `/_next/static/chunks/*.js.map`. "
            "Source maps reveal React-Server-Component boundaries, "
            "server-action serialization fingerprints, and `define`d "
            "build-time constants. Production deploys should keep "
            "this `false` and upload maps to Sentry / Datadog out "
            "of band (the Sentry Next plugin strips them from the "
            "public output)."
        ),
        pattern=_NEXT_PROD_BROWSER_SOURCE_MAPS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h10-vite-loadenv-no-prefix",
        name="Vite loadEnv called with empty prefix returns ALL env vars",
        severity="HIGH",
        description=(
            "Vite's `loadEnv` second-arg default is `'VITE_'`. "
            "Passing `''` (or `['']`) loads EVERY env var the build "
            "process can see — `AWS_SECRET_ACCESS_KEY`, "
            "`GITHUB_TOKEN`, `OPENAI_API_KEY`, anything the CI "
            "runner has in scope. Combined with `define: { "
            "...env }` (a common pattern) the entire process "
            "environment lands inside the client bundle. Always pass "
            "an explicit non-empty prefix (`'VITE_'`, `'PUBLIC_'`, "
            "`'NEXT_PUBLIC_'`)."
        ),
        pattern=_VITE_LOADENV_NO_PREFIX,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bundler-h11-sw-precache-env",
        name="Service-worker config precache catches .env / .map / API responses",
        severity="HIGH",
        description=(
            "Workbox / vite-plugin-pwa / next-pwa config uses a "
            "catch-all `globPatterns` (`**/*.*` or `**/*`) without "
            "a matching `globIgnores` excluding `.env*` / `*.map` / "
            "`*.server.*`, OR a `runtimeCaching` route with "
            "`urlPattern: /.*/` and `CacheFirst`. The first pulls "
            "any output file into the SW's IndexedDB cache; the "
            "second caches authenticated `/api/me` responses with "
            "session cookies — the next user on the same browser "
            "sees them."
        ),
        pattern=_SW_PRECACHE_OVERBROAD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bundler-h12-stats-in-public-dir",
        name="Bundle-analyzer writes report.html / stats.json into public output dir",
        severity="HIGH",
        description=(
            "`webpack-bundle-analyzer`'s static `report.html` or "
            "`rollup-plugin-visualizer`'s output map the entire "
            "module graph: every `node_modules/` package, every "
            "server-only file accidentally imported, every relative "
            "path. Shipped to a public CDN it becomes a one-click "
            "recon tool — `https://app.example.com/report.html` "
            "lists every dependency-version combo for known-CVE "
            "lookup. Generate the report in a separate CI step that "
            "doesn't run on the deploy build, or gate it under "
            "`process.env.ANALYZE`."
        ),
        pattern=_BUNDLE_ANALYZER_PUBLIC_OUTPUT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h13-public-path-untrusted",
        name="webpack public-path derived from untrusted runtime source",
        severity="HIGH",
        description=(
            "`__webpack_public_path__` (or `output.publicPath` "
            "function) is derived from `window.location.search` / "
            "`document.referrer` / a `data-*` attribute / a runtime "
            "env var. An attacker who can influence any of those — "
            "via an open redirect, a postMessage handler, or an XSS "
            "in a wrapping page — gets remote-code-execution: their "
            "origin serves the next lazy chunk webpack loads, which "
            "executes inside the victim's origin. The classic "
            "'webpack lazy-chunk hijack' (CVE-2022-21824-class). "
            "Use a frozen literal or an allowlist match."
        ),
        pattern=_WEBPACK_PUBLIC_PATH_UNTRUSTED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bundler-h14-vite-fs-allow-overbroad",
        name="Vite server.fs.allow broadens dev FS exposure to root",
        severity="HIGH",
        description=(
            "Vite `server.fs.allow` contains `'/'`, `'..'`, or an "
            "unbounded path, OR `server.fs.strict: false` is set. "
            "Vite's dev server (and `vite preview`, which is "
            "sometimes used as a quick prod server) refuses to "
            "serve files outside the project root by default. "
            "`allow: ['/']` re-enables full-filesystem read. "
            "Anyone reaching the dev port (typo, leaked tunnel, "
            "`0.0.0.0` binding) can `curl "
            "http://host:1420/@fs/etc/passwd`."
        ),
        pattern=_VITE_FS_ALLOW_ROOT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bundler-h15-source-mapping-url-drift",
        name="sourceMappingURL pragma points at non-loopback external host",
        severity="HIGH",
        description=(
            "A built JS asset contains a `//# sourceMappingURL=` "
            "pragma pointing at an http(s) or protocol-relative URL "
            "on a non-loopback host. Lets that host's owner serve "
            "arbitrary content into devtools' source view — and, in "
            "some Chromium versions, into the page's runtime via "
            "`chrome://devtools` extension surfaces. Drift typically "
            "happens when a team migrates CDNs and forgets to "
            "update `sourcemapFileNames`. Use a `data:` URL, a "
            "relative path, or a same-origin absolute path."
        ),
        pattern=_SOURCE_MAPPING_URL_DRIFT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bundler-h15-source-map-filename-drift",
        name="Bundler sourceMapFilename hard-coded to external host",
        severity="HIGH",
        description=(
            "`output.sourceMapFilename` / "
            "`build.rollupOptions.output.sourcemapFileNames` is a "
            "hard-coded `https://` URL pointing to a host that "
            "isn't the deploy origin. Each chunk's pragma will "
            "fetch from that host — the bundler-config equivalent "
            "of the `sourceMappingURL` drift above."
        ),
        pattern=_SOURCE_MAP_FILENAME_DRIFT,
        owasp_asi="ASI-02",
    ),
)


# ---- The composed scanner -----------------------------------------------


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


def _surrounding_lines(text: str, line_no: int, before: int, after: int) -> str:
    """Return the concatenation of N lines before + the target line +
    M lines after."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no + after)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return
    findings.

    Two-stage rules consult file-level guards:

    * H-1 — suppress webpack source-map hit if file has a dev-mode
      gate (`argv.mode === 'development'`, `NODE_ENV !== 'production'`,
      or explicit pragma).
    * H-2 — suppress webpack `mode: 'development'` hit if the same
      file also sets `mode: 'production'` later (paired-config
      convention).
    * H-3 — suppress Vite sourcemap hit if file has a mode-gating
      conditional.
    * H-4 — suppress Vite minify hit if the file is a library build
      (`build.lib`) or a non-public target (Tauri / Electron / VSCode
      extension).
    * H-5 — suppress esbuild flag hit if the surrounding script name
      is `dev` / `watch` / `start` / `debug`, OR the same line uses
      `--sourcemap=hidden`.
    * H-6 — suppress rollup hit if the same file flags itself as a
      library build (`format: 'es'`, `publishConfig`, or the
      rollup-library-build pragma).
    * H-7 — anchor on `define:` / `DefinePlugin` block; suppress if
      the matched key is a known harmless build-metadata key.
    * H-9 — suppress Next-source-maps hit if the same file wires the
      Sentry plugin.
    * H-11 — suppress SW-precache hit if same file declares
      `globIgnores` with `.env` or `.map`.
    * H-12 — suppress analyzer hit if the surrounding 10-line window
      gates the plugin under `process.env.ANALYZE`.
    * H-13 — suppress webpack-public-path hit if the file has a
      strict-CSP `script-src 'self'` declaration.
    * H-14 — suppress Vite FS-allow hit if the dev server is bound
      to loopback with strictPort.

    Findings are deduped by (rule_id, line, column). Output is sorted
    by (line, column, rule_id) for deterministic ordering.
    """
    if not text:
        return []

    # File-level guard evaluation — one shot per file.
    webpack_devtool_gated = _file_contains_any(text, _WEBPACK_DEV_SOURCE_MAP_GUARDS)
    webpack_mode_prod_present = _WEBPACK_MODE_PRODUCTION.search(text) is not None
    webpack_anchor = _WEBPACK_CONFIG_ANCHOR.search(text) is not None
    vite_mode_gated = _file_contains_any(text, _VITE_MODE_GATE_GUARDS)
    vite_anchor = _VITE_CONFIG_ANCHOR.search(text) is not None
    vite_is_library = _file_contains_any(text, _VITE_LIB_MODE_GUARDS)
    vite_non_public_target = _file_contains_any(text, _VITE_NON_PUBLIC_TARGET_GUARDS)
    esbuild_dev_script_context = _file_contains_any(text, _ESBUILD_DEV_SCRIPT_GUARDS)
    rollup_is_library = _file_contains_any(text, _ROLLUP_LIBRARY_GUARDS)
    define_block_present = _DEFINE_BLOCK_ANCHOR.search(text) is not None
    next_config_anchor = _NEXT_CONFIG_ANCHOR.search(text) is not None
    next_sentry_present = _file_contains_any(text, _NEXT_SENTRY_PLUGIN_GUARDS)
    sw_globignore_present = _file_contains_any(text, _SW_GLOB_IGNORE_GUARDS)
    analyzer_gated = _file_contains_any(text, _BUNDLE_ANALYZER_GATE_GUARDS)
    csp_strict_self = _file_contains_any(text, _CSP_STRICT_SELF_GUARDS)
    vite_loopback = _file_contains_any(text, _VITE_LOOPBACK_BIND_GUARDS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            matched = m.group(0)

            # ---- Per-rule Stage-B filtering -----------------------

            if rule.id == "bundler-h1-webpack-prod-source-map":
                if webpack_devtool_gated:
                    continue
                # `devtool: 'hidden-source-map'` is safe — the regex
                # does not match the `hidden-` prefix, but be
                # defensive in case a future regex tweak adds it.
                if "hidden-source-map" in matched:
                    continue
                # If the same-line text says `devtool: false`,
                # something else matched. Skip defensively.
                ln_text = _line_text(text, line)
                if re.search(r"\bdevtool\s*:\s*false\b", ln_text):
                    continue

            elif rule.id == "bundler-h2-webpack-mode-misset":
                # Only fire in a file that imports/requires webpack.
                if not webpack_anchor:
                    continue
                # And only when production-mode literal is NOT
                # ALSO present (paired-config convention).
                if webpack_mode_prod_present:
                    # Same file has both — fire only if the dev
                    # literal is on the path actually being exported.
                    # Without AST, the cheap heuristic: if the dev
                    # literal lives in the same line as `mode:` and
                    # the prod literal is on a different line, treat
                    # as paired-config and suppress.
                    continue
                # Skip dev-paired-config filenames.
                # Filename detection is the caller's job (this is a
                # text-level scanner); we leave the filename guard
                # to the doctor. Here we ONLY suppress when the
                # comment pragma `// webpack-mode-prod-gated` is
                # present.
                if re.search(r"//\s*webpack-mode-prod-gated\b", text):
                    continue

            elif rule.id == "bundler-h3-vite-prod-sourcemap":
                if not vite_anchor:
                    continue
                if vite_mode_gated:
                    continue
                # `sourcemap: 'hidden'` is safe; regex doesn't
                # match it but be defensive.
                if "'hidden'" in matched or '"hidden"' in matched:
                    continue

            elif rule.id == "bundler-h4-vite-prod-no-minify":
                if not vite_anchor:
                    continue
                if vite_is_library or vite_non_public_target:
                    continue

            elif rule.id == "bundler-h5-esbuild-prod-sourcemap-flag":
                # Skip if the line has `--sourcemap=hidden`.
                ln_text = _line_text(text, line)
                if _ESBUILD_SOURCEMAP_HIDDEN.search(ln_text):
                    continue
                # Skip if a dev-script context guard fires AT FILE
                # SCOPE (same `package.json`/script file).
                if esbuild_dev_script_context:
                    # But only if the *line itself* looks like a dev
                    # script — i.e. the line contains `dev` /
                    # `watch` token. Otherwise we'd suppress a real
                    # `scripts.build` hit just because the file also
                    # has a `scripts.dev`.
                    if re.search(
                        r"\b(?:dev|watch|start|debug)\b",
                        ln_text,
                        re.IGNORECASE,
                    ):
                        continue

            elif rule.id == "bundler-h5-esbuild-prod-sourcemap-api":
                # Same guard — line-local `--sourcemap=hidden` is
                # impossible here (API form), but a `sourcemap:
                # 'hidden'` IS safe. The regex doesn't include
                # 'hidden' in its alternatives — defensive check.
                if "'hidden'" in matched or '"hidden"' in matched:
                    continue

            elif rule.id == "bundler-h6-rollup-prod-sourcemap":
                if rollup_is_library:
                    continue

            elif rule.id == "bundler-h7-define-secret-inline":
                if not define_block_present:
                    continue
                # Skip if the match overlaps with a harmless build-
                # metadata key.
                if _file_contains_any(matched, _DEFINE_HARMLESS_KEY_GUARDS):
                    # The match itself is a harmless key. Skip.
                    if any(
                        g.search(matched)
                        for g in _DEFINE_HARMLESS_KEY_GUARDS
                    ):
                        continue

            elif rule.id in (
                "bundler-h8-next-env-block-secret",
                "bundler-h8-next-env-block-hardcoded-token",
            ):
                if not next_config_anchor:
                    continue
                # For the secret-named-key rule, also skip if the
                # KEY contains `_PUBLIC_` (NEXT_PUBLIC_*_URL, etc.)
                # — explicit-public marker. The regex already drops
                # `_TOKEN_PUBLIC` / `_API_KEY_PUBLIC` via negative
                # lookahead, but `NEXT_PUBLIC_*_URL` could still
                # be in scope; here we double-check.
                if rule.id == "bundler-h8-next-env-block-secret":
                    if re.search(
                        r"\bNEXT_PUBLIC_\w+_(?:URL|ENDPOINT|NAME|ID)\b",
                        matched,
                        re.IGNORECASE,
                    ):
                        continue

            elif rule.id == "bundler-h9-next-prod-browser-source-maps":
                if next_sentry_present:
                    continue

            elif rule.id == "bundler-h11-sw-precache-env":
                if sw_globignore_present:
                    continue

            elif rule.id == "bundler-h12-stats-in-public-dir":
                # 10-line surrounding window for the ANALYZE gate.
                window = _surrounding_lines(text, line, before=10, after=2)
                if _file_contains_any(window, _BUNDLE_ANALYZER_GATE_GUARDS):
                    continue
                if analyzer_gated:
                    # File-level gate also applies — if anywhere in
                    # the file we see `process.env.ANALYZE`, the
                    # author has likely scoped this.
                    continue

            elif rule.id == "bundler-h13-public-path-untrusted":
                if csp_strict_self:
                    continue

            elif rule.id == "bundler-h14-vite-fs-allow-overbroad":
                if not vite_anchor:
                    continue
                if vite_loopback:
                    continue

            # H-15 has no Stage-B carve-outs — the regex already
            # excludes loopback / data: / relative URLs.

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
