"""Tests for ``scripts/lib/js_bundler_patterns.py``.

Wave 21 impl angle H — pattern-coverage tests for the 18 rules
distilled from ``reports/distill-round-7/js-bundler-config.md``.

Each rule gets at least one positive test (the documented attack
shape fires) and one negative test (a documented carve-out
suppresses the same line). Module-level invariants (unique IDs,
compiled patterns, OWASP mapping, severity enum) are checked too.

Sibling tests:
  * ``tests/test_auth_flow_patterns.py``       (Wave 17 batch A)
  * ``tests/test_frontend_patterns.py``        (Wave 17 impl-z)
  * ``tests/test_oauth_device_flow_patterns.py`` (Wave 19)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import js_bundler_patterns as jbp  # type: ignore[import-not-found]  # noqa: E402

sys.path.insert(0, str(_REPO_ROOT / "tests"))
from _fake_secrets import secret  # type: ignore[import-not-found]  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[jbp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in jbp.scan_text(text) if f.rule_id == rule_id]


# ---- Module-level invariants -------------------------------------------


def test_rules_tuple_is_frozen() -> None:
    """RULES must be a tuple."""
    assert isinstance(jbp.RULES, tuple)
    assert len(jbp.RULES) >= 15


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in jbp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    for rule in jbp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in jbp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    for rule in jbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_expected_rule_ids_present() -> None:
    """The 15 documented H-N rule ids (H-5 / H-8 / H-15 are split
    into two sub-rules each) are all present."""
    expected = {
        "bundler-h1-webpack-prod-source-map",
        "bundler-h2-webpack-mode-misset",
        "bundler-h3-vite-prod-sourcemap",
        "bundler-h4-vite-prod-no-minify",
        "bundler-h5-esbuild-prod-sourcemap-flag",
        "bundler-h5-esbuild-prod-sourcemap-api",
        "bundler-h6-rollup-prod-sourcemap",
        "bundler-h7-define-secret-inline",
        "bundler-h8-next-env-block-secret",
        "bundler-h8-next-env-block-hardcoded-token",
        "bundler-h9-next-prod-browser-source-maps",
        "bundler-h10-vite-loadenv-no-prefix",
        "bundler-h11-sw-precache-env",
        "bundler-h12-stats-in-public-dir",
        "bundler-h13-public-path-untrusted",
        "bundler-h14-vite-fs-allow-overbroad",
        "bundler-h15-source-mapping-url-drift",
        "bundler-h15-source-map-filename-drift",
    }
    actual = {r.id for r in jbp.RULES}
    assert expected.issubset(actual), expected - actual


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = jbp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_scan_empty_text_returns_no_findings() -> None:
    """Empty input is a fast-path, no findings."""
    assert jbp.scan_text("") == []


def test_findings_sorted_by_line() -> None:
    """Output is sorted by (line, column, rule_id)."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = {\n"
        "  mode: 'development',\n"
        "  devtool: 'source-map',\n"
        "};\n"
    )
    findings = jbp.scan_text(src)
    # Lines must be monotonically non-decreasing.
    for i in range(1, len(findings)):
        prev = findings[i - 1]
        cur = findings[i]
        assert (prev.line, prev.column, prev.rule_id) <= (
            cur.line,
            cur.column,
            cur.rule_id,
        )


# ---- H-1 : webpack-prod-source-map -------------------------------------


def test_h1_webpack_devtool_source_map_flags() -> None:
    """`devtool: 'source-map'` on a webpack config fires CRITICAL."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = {\n"
        "  mode: 'production',\n"
        "  devtool: 'source-map',\n"
        "};\n"
    )
    hits = _hits("bundler-h1-webpack-prod-source-map", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_h1_webpack_devtool_inline_source_map_flags() -> None:
    """`devtool: 'inline-source-map'` also fires."""
    src = "devtool: 'inline-source-map',\n"
    assert _hits("bundler-h1-webpack-prod-source-map", src)


def test_h1_webpack_devtool_eval_source_map_flags() -> None:
    """`devtool: 'eval-source-map'` also fires."""
    src = "devtool: 'eval-source-map',\n"
    assert _hits("bundler-h1-webpack-prod-source-map", src)


def test_h1_dev_gate_suppresses() -> None:
    """`argv.mode === 'development'` anywhere in the file suppresses."""
    src = (
        "module.exports = (env, argv) => {\n"
        "  if (argv.mode === 'development') {\n"
        "    return { devtool: 'source-map' };\n"
        "  }\n"
        "  return { devtool: false };\n"
        "};\n"
    )
    assert not _hits("bundler-h1-webpack-prod-source-map", src)


def test_h1_node_env_dev_gate_suppresses() -> None:
    """`process.env.NODE_ENV !== 'production'` gate suppresses."""
    src = (
        "const devtool = process.env.NODE_ENV !== 'production'\n"
        "  ? 'source-map' : false;\n"
        "module.exports = { devtool };\n"
    )
    assert not _hits("bundler-h1-webpack-prod-source-map", src)


# ---- H-2 : webpack-mode-misset -----------------------------------------


def test_h2_webpack_dev_mode_unconditional_flags() -> None:
    """`mode: 'development'` on an unconditional webpack export fires."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = {\n"
        "  mode: 'development',\n"
        "  entry: './src/index.js',\n"
        "};\n"
    )
    assert _hits("bundler-h2-webpack-mode-misset", src)


def test_h2_paired_config_with_both_modes_suppressed() -> None:
    """File with BOTH `mode: 'development'` and `mode: 'production'`
    is a paired-config — suppress."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = (env, argv) => {\n"
        "  if (argv.mode === 'development') {\n"
        "    return { mode: 'development' };\n"
        "  }\n"
        "  return { mode: 'production' };\n"
        "};\n"
    )
    assert not _hits("bundler-h2-webpack-mode-misset", src)


def test_h2_no_webpack_anchor_suppresses() -> None:
    """`mode: 'development'` outside a webpack-config file (no webpack
    import / require) does not fire — this isn't a webpack config."""
    src = "const config = { mode: 'development' };\n"
    assert not _hits("bundler-h2-webpack-mode-misset", src)


# ---- H-3 : vite-prod-sourcemap -----------------------------------------


def test_h3_vite_sourcemap_true_flags() -> None:
    """`build.sourcemap: true` on a Vite config fires CRITICAL."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  build: { sourcemap: true },\n"
        "});\n"
    )
    hits = _hits("bundler-h3-vite-prod-sourcemap", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h3_vite_sourcemap_inline_flags() -> None:
    """`sourcemap: 'inline'` also fires."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({ build: { sourcemap: 'inline' } });\n"
    )
    assert _hits("bundler-h3-vite-prod-sourcemap", src)


def test_h3_vite_mode_gate_suppresses() -> None:
    """`mode !== 'production'` conditional gates the property."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig(({ mode }) => ({\n"
        "  build: {\n"
        "    sourcemap: mode !== 'production' ? true : false,\n"
        "  },\n"
        "}));\n"
    )
    assert not _hits("bundler-h3-vite-prod-sourcemap", src)


def test_h3_no_vite_anchor_suppresses() -> None:
    """`sourcemap: true` outside a Vite-anchored file doesn't fire."""
    src = "const opts = { sourcemap: true };\n"
    assert not _hits("bundler-h3-vite-prod-sourcemap", src)


# ---- H-4 : vite-prod-no-minify -----------------------------------------


def test_h4_vite_minify_false_flags() -> None:
    """`build.minify: false` on a Vite config fires HIGH."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  build: { minify: false },\n"
        "});\n"
    )
    hits = _hits("bundler-h4-vite-prod-no-minify", src)
    assert hits


def test_h4_library_mode_suppresses() -> None:
    """`build.lib` makes this a library build — minify off is fine."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  build: {\n"
        "    lib: { entry: 'src/index.ts', formats: ['es'] },\n"
        "    minify: false,\n"
        "  },\n"
        "});\n"
    )
    assert not _hits("bundler-h4-vite-prod-no-minify", src)


def test_h4_tauri_target_suppresses() -> None:
    """Tauri / Electron targets are not public — suppress."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "// src-tauri integration\n"
        "export default defineConfig({\n"
        "  build: { minify: false },\n"
        "});\n"
    )
    assert not _hits("bundler-h4-vite-prod-no-minify", src)


# ---- H-5 : esbuild-prod-sourcemap-flag (CLI) ---------------------------


def test_h5_esbuild_cli_sourcemap_flags() -> None:
    """`esbuild ... --sourcemap` in a build script fires CRITICAL."""
    src = (
        '  "scripts": {\n'
        '    "build": "esbuild src/index.ts --bundle --sourcemap"\n'
        "  }\n"
    )
    hits = _hits("bundler-h5-esbuild-prod-sourcemap-flag", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h5_esbuild_cli_sourcemap_external_flags() -> None:
    """`--sourcemap=external` also fires."""
    src = '"build": "esbuild src --sourcemap=external"\n'
    assert _hits("bundler-h5-esbuild-prod-sourcemap-flag", src)


def test_h5_esbuild_sourcemap_hidden_suppresses() -> None:
    """`--sourcemap=hidden` on same line is the safe form — suppress."""
    src = '"build": "esbuild src --bundle --sourcemap=hidden"\n'
    assert not _hits("bundler-h5-esbuild-prod-sourcemap-flag", src)


def test_h5_esbuild_dev_script_name_suppresses() -> None:
    """A script named `dev` with `--sourcemap` is OK (dev workflow)."""
    src = (
        '  "scripts": {\n'
        '    "dev": "esbuild src --sourcemap --watch"\n'
        "  }\n"
    )
    assert not _hits("bundler-h5-esbuild-prod-sourcemap-flag", src)


# ---- H-5 : esbuild-prod-sourcemap-api ----------------------------------


def test_h5_esbuild_api_sourcemap_true_flags() -> None:
    """`esbuild.build({ sourcemap: true })` fires CRITICAL."""
    src = (
        "require('esbuild').build({\n"
        "  entryPoints: ['src/index.ts'],\n"
        "  sourcemap: true,\n"
        "  bundle: true,\n"
        "});\n"
    )
    hits = _hits("bundler-h5-esbuild-prod-sourcemap-api", src)
    assert hits


def test_h5_esbuild_api_sourcemap_inline_flags() -> None:
    """`sourcemap: 'inline'` also fires."""
    src = "esbuild.build({ sourcemap: 'inline' })\n"
    assert _hits("bundler-h5-esbuild-prod-sourcemap-api", src)


def test_h5_esbuild_api_sourcemap_hidden_excluded() -> None:
    """`sourcemap: 'hidden'` is NOT in the regex alternatives — no fire."""
    src = "esbuild.build({ sourcemap: 'hidden' })\n"
    assert not _hits("bundler-h5-esbuild-prod-sourcemap-api", src)


# ---- H-6 : rollup-prod-sourcemap ---------------------------------------


def test_h6_rollup_output_sourcemap_true_flags() -> None:
    """`output.sourcemap: true` in a Rollup app config fires HIGH."""
    src = (
        "export default {\n"
        "  input: 'src/main.js',\n"
        "  output: { file: 'dist/bundle.js', format: 'iife', sourcemap: true },\n"
        "};\n"
    )
    assert _hits("bundler-h6-rollup-prod-sourcemap", src)


def test_h6_library_format_es_suppresses() -> None:
    """`format: 'es'` is a library build — source maps are conventional."""
    src = (
        "export default {\n"
        "  input: 'src/main.js',\n"
        "  output: {\n"
        "    file: 'dist/bundle.mjs',\n"
        "    format: 'es',\n"
        "    sourcemap: true,\n"
        "  },\n"
        "};\n"
    )
    assert not _hits("bundler-h6-rollup-prod-sourcemap", src)


# ---- H-7 : define-secret-inline ----------------------------------------


def test_h7_define_anthropic_secret_inline_flags() -> None:
    """`define: { __ANTHROPIC_API_KEY__: ... }` fires CRITICAL."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  define: {\n"
        "    __ANTHROPIC_API_KEY__: JSON.stringify(process.env.ANTHROPIC_API_KEY),\n"
        "  },\n"
        "});\n"
    )
    hits = _hits("bundler-h7-define-secret-inline", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h7_webpack_defineplugin_secret_flags() -> None:
    """`new webpack.DefinePlugin({ ... SECRET: ... })` fires."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = {\n"
        "  plugins: [\n"
        "    new webpack.DefinePlugin({\n"
        "      'process.env.AUTH_SECRET': JSON.stringify(process.env.AUTH_SECRET),\n"
        "    }),\n"
        "  ],\n"
        "};\n"
    )
    assert _hits("bundler-h7-define-secret-inline", src)


def test_h7_raw_process_env_token_in_define_flags() -> None:
    """Raw `process.env.X_TOKEN` (no JSON.stringify) in define fires."""
    src = (
        "export default defineConfig({\n"
        "  define: {\n"
        "    __GH_TOKEN__: process.env.GITHUB_TOKEN,\n"
        "  },\n"
        "});\n"
    )
    assert _hits("bundler-h7-define-secret-inline", src)


def test_h7_build_metadata_keys_not_flagged() -> None:
    """`__BUILD_TIME__`, `__VERSION__`, `__COMMIT_SHA__` are harmless."""
    src = (
        "export default defineConfig({\n"
        "  define: {\n"
        "    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),\n"
        "    __VERSION__: JSON.stringify('1.2.3'),\n"
        "    __COMMIT_SHA__: JSON.stringify(process.env.GIT_SHA),\n"
        "  },\n"
        "});\n"
    )
    # No hit for these keys.
    assert not _hits("bundler-h7-define-secret-inline", src)


def test_h7_no_define_block_anchor_suppresses() -> None:
    """`process.env.X_SECRET` outside a `define`/DefinePlugin context
    is the responsibility of other rules, not H-7."""
    src = "const x = process.env.AUTH_SECRET;\n"
    assert not _hits("bundler-h7-define-secret-inline", src)


# ---- H-8 : next-env-block-secret ---------------------------------------


def test_h8_next_env_secret_key_flags() -> None:
    """`next.config.env: { ANTHROPIC_API_KEY: ... }` fires CRITICAL."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  env: {\n"
        "    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,\n"
        "  },\n"
        "};\n"
        "module.exports = nextConfig;\n"
    )
    hits = _hits("bundler-h8-next-env-block-secret", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_h8_next_public_runtime_config_secret_flags() -> None:
    """`publicRuntimeConfig: { ...SECRET... }` also fires."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "module.exports = {\n"
        "  publicRuntimeConfig: { SLACK_BOT_TOKEN: process.env.SLACK_BOT_TOKEN },\n"
        "};\n"
    )
    assert _hits("bundler-h8-next-env-block-secret", src)


def test_h8_next_public_url_key_not_flagged() -> None:
    """`NEXT_PUBLIC_*_URL` is an explicit-public marker — suppress."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  env: {\n"
        "    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,\n"
        "  },\n"
        "};\n"
        "module.exports = nextConfig;\n"
    )
    assert not _hits("bundler-h8-next-env-block-secret", src)


def test_h8_next_hardcoded_anthropic_token_flags() -> None:
    """Hard-coded `sk-ant-...` token value in env block fires."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "module.exports = {\n"
        "  env: {\n"
        "    ANTHROPIC_KEY: 'sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890',\n"
        "  },\n"
        "};\n"
    )
    assert _hits("bundler-h8-next-env-block-hardcoded-token", src)


def test_h8_next_hardcoded_github_pat_flags() -> None:
    """`github_pat_...` value fires."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "module.exports = {\n"
        f"  env: {{ GH_TOKEN: '{secret('github' + '_pat_', 'jbp-h8-gh-pat', 25)}' }},\n"
        "};\n"
    )
    assert _hits("bundler-h8-next-env-block-hardcoded-token", src)


# ---- H-9 : next-prod-browser-source-maps -------------------------------


def test_h9_next_prod_browser_sourcemaps_true_flags() -> None:
    """`productionBrowserSourceMaps: true` fires HIGH."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  productionBrowserSourceMaps: true,\n"
        "};\n"
        "module.exports = nextConfig;\n"
    )
    hits = _hits("bundler-h9-next-prod-browser-source-maps", src)
    assert hits


def test_h9_sentry_plugin_present_suppresses() -> None:
    """`@sentry/nextjs` import means Sentry's plugin handles the
    upload-and-strip — suppress the hit."""
    src = (
        "const { withSentryConfig } = require('@sentry/nextjs');\n"
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  productionBrowserSourceMaps: true,\n"
        "};\n"
        "module.exports = withSentryConfig(nextConfig, {});\n"
    )
    assert not _hits("bundler-h9-next-prod-browser-source-maps", src)


# ---- H-10 : vite-loadenv-no-prefix -------------------------------------


def test_h10_vite_loadenv_empty_string_flags() -> None:
    """`loadEnv(mode, process.cwd(), '')` fires HIGH."""
    src = (
        "import { defineConfig, loadEnv } from 'vite';\n"
        "export default defineConfig(({ mode }) => {\n"
        "  const env = loadEnv(mode, process.cwd(), '');\n"
        "  return { define: { ...env } };\n"
        "});\n"
    )
    hits = _hits("bundler-h10-vite-loadenv-no-prefix", src)
    assert hits


def test_h10_vite_loadenv_empty_array_flags() -> None:
    """`loadEnv(mode, cwd, [''])` also fires."""
    src = "const env = loadEnv('production', process.cwd(), [''])\n"
    assert _hits("bundler-h10-vite-loadenv-no-prefix", src)


def test_h10_vite_loadenv_explicit_prefix_suppresses() -> None:
    """`loadEnv(mode, cwd, 'VITE_')` is the safe form."""
    src = (
        "const env = loadEnv(mode, process.cwd(), 'VITE_');\n"
    )
    assert not _hits("bundler-h10-vite-loadenv-no-prefix", src)


def test_h10_vite_loadenv_default_prefix_suppresses() -> None:
    """`loadEnv(mode, cwd)` defaults to `'VITE_'` — safe."""
    src = "const env = loadEnv(mode, process.cwd());\n"
    assert not _hits("bundler-h10-vite-loadenv-no-prefix", src)


# ---- H-11 : sw-precache-env --------------------------------------------


def test_h11_sw_globpatterns_catchall_flags() -> None:
    """Catch-all `globPatterns: ['**/*.*']` fires HIGH."""
    src = (
        "module.exports = {\n"
        "  globPatterns: ['**/*.*'],\n"
        "  swDest: 'dist/sw.js',\n"
        "};\n"
    )
    assert _hits("bundler-h11-sw-precache-env", src)


def test_h11_sw_runtime_caching_catchall_flags() -> None:
    """`urlPattern: /.*/` with CacheFirst is a bug."""
    src = (
        "module.exports = {\n"
        "  runtimeCaching: [\n"
        "    { urlPattern: /.*/, handler: 'CacheFirst' },\n"
        "  ],\n"
        "};\n"
    )
    assert _hits("bundler-h11-sw-precache-env", src)


def test_h11_globignores_env_suppresses() -> None:
    """`globIgnores` with `.env*` excludes the sensitive files."""
    src = (
        "module.exports = {\n"
        "  globPatterns: ['**/*.*'],\n"
        "  globIgnores: ['**/.env*', '**/*.map'],\n"
        "  swDest: 'dist/sw.js',\n"
        "};\n"
    )
    assert not _hits("bundler-h11-sw-precache-env", src)


# ---- H-12 : stats-in-public-dir ----------------------------------------


def test_h12_bundle_analyzer_default_flags() -> None:
    """Bare `new BundleAnalyzerPlugin()` writes report.html into
    output.path — fires HIGH."""
    src = (
        "const { BundleAnalyzerPlugin } = require('webpack-bundle-analyzer');\n"
        "module.exports = {\n"
        "  plugins: [new BundleAnalyzerPlugin()],\n"
        "};\n"
    )
    assert _hits("bundler-h12-stats-in-public-dir", src)


def test_h12_visualizer_dist_filename_flags() -> None:
    """`visualizer({ filename: 'dist/report.html' })` fires."""
    src = (
        "import { visualizer } from 'rollup-plugin-visualizer';\n"
        "export default {\n"
        "  plugins: [visualizer({ filename: 'dist/report.html' })],\n"
        "};\n"
    )
    assert _hits("bundler-h12-stats-in-public-dir", src)


def test_h12_analyze_env_gate_suppresses() -> None:
    """`process.env.ANALYZE` gate suppresses the hit."""
    src = (
        "const { BundleAnalyzerPlugin } = require('webpack-bundle-analyzer');\n"
        "module.exports = {\n"
        "  plugins: process.env.ANALYZE ? [new BundleAnalyzerPlugin()] : [],\n"
        "};\n"
    )
    assert not _hits("bundler-h12-stats-in-public-dir", src)


# ---- H-13 : public-path-untrusted --------------------------------------


def test_h13_public_path_from_location_search_flags() -> None:
    """`__webpack_public_path__ = window.location.search` fires HIGH."""
    src = (
        "// entry script\n"
        "__webpack_public_path__ = window.location.search;\n"
    )
    assert _hits("bundler-h13-public-path-untrusted", src)


def test_h13_public_path_from_referrer_flags() -> None:
    """`__webpack_public_path__ = document.referrer` fires."""
    src = "__webpack_public_path__ = document.referrer;\n"
    assert _hits("bundler-h13-public-path-untrusted", src)


def test_h13_public_path_from_runtime_env_flags() -> None:
    """`output.publicPath: (file) => process.env.CDN_URL` fires."""
    src = (
        "module.exports = {\n"
        "  output: {\n"
        "    path: '/dist',\n"
        "    publicPath: (file) => process.env.PUBLIC_CDN_URL || '/',\n"
        "  },\n"
        "};\n"
    )
    assert _hits("bundler-h13-public-path-untrusted", src)


def test_h13_strict_csp_self_suppresses() -> None:
    """A strict CSP `script-src 'self'` declaration suppresses."""
    src = (
        "// CSP header: \"script-src 'self'\";\n"
        "__webpack_public_path__ = document.referrer;\n"
    )
    assert not _hits("bundler-h13-public-path-untrusted", src)


# ---- H-14 : vite-fs-allow-overbroad ------------------------------------


def test_h14_vite_fs_allow_root_flags() -> None:
    """`server.fs.allow: ['/']` fires HIGH."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  server: { fs: { allow: ['/'] } },\n"
        "});\n"
    )
    assert _hits("bundler-h14-vite-fs-allow-overbroad", src)


def test_h14_vite_fs_strict_false_flags() -> None:
    """`server.fs.strict: false` also fires (deprecated alias)."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  server: { fs: { strict: false } },\n"
        "});\n"
    )
    assert _hits("bundler-h14-vite-fs-allow-overbroad", src)


def test_h14_vite_fs_allow_dotdot_flags() -> None:
    """`allow: ['..']` is the same broadening — fires."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  server: { fs: { allow: ['..'] } },\n"
        "});\n"
    )
    assert _hits("bundler-h14-vite-fs-allow-overbroad", src)


def test_h14_loopback_bind_with_strict_port_suppresses() -> None:
    """`host: '127.0.0.1', strictPort: true` mitigates — suppress."""
    src = (
        "import { defineConfig } from 'vite';\n"
        "export default defineConfig({\n"
        "  server: { host: '127.0.0.1', strictPort: true, fs: { allow: ['/'] } },\n"
        "});\n"
    )
    assert not _hits("bundler-h14-vite-fs-allow-overbroad", src)


# ---- H-15 : source-mapping-url-drift -----------------------------------


def test_h15_external_https_source_mapping_url_flags() -> None:
    """`//# sourceMappingURL=https://attacker.example/leak.map` fires."""
    src = "//# sourceMappingURL=https://attacker.example.com/leak.map\n"
    assert _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_protocol_relative_source_mapping_url_flags() -> None:
    """Protocol-relative URL also fires."""
    src = "//# sourceMappingURL=//evil.example.com/foo.map\n"
    assert _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_data_url_source_mapping_not_flagged() -> None:
    """`data:` URL is inline and safe."""
    src = "//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozfQ==\n"
    assert not _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_relative_source_mapping_not_flagged() -> None:
    """Relative path (`foo.js.map`) is same-origin."""
    src = "//# sourceMappingURL=bundle.js.map\n"
    assert not _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_loopback_localhost_not_flagged() -> None:
    """`http://localhost:...` is a dev URL — safe."""
    src = "//# sourceMappingURL=http://localhost:3000/bundle.js.map\n"
    assert not _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_loopback_127_not_flagged() -> None:
    """`http://127.0.0.1:...` is a dev URL — safe."""
    src = "//# sourceMappingURL=http://127.0.0.1:3000/bundle.js.map\n"
    assert not _hits("bundler-h15-source-mapping-url-drift", src)


def test_h15_source_map_filename_external_https_flags() -> None:
    """`sourceMapFilename: 'https://cdn.bad/...'` fires."""
    src = (
        "module.exports = {\n"
        "  output: {\n"
        "    sourceMapFilename: 'https://old-cdn.example.com/[name].js.map',\n"
        "  },\n"
        "};\n"
    )
    assert _hits("bundler-h15-source-map-filename-drift", src)


def test_h15_source_map_filename_relative_not_flagged() -> None:
    """Relative `sourceMapFilename` is the safe form."""
    src = (
        "module.exports = {\n"
        "  output: { sourceMapFilename: '[name].js.map' },\n"
        "};\n"
    )
    assert not _hits("bundler-h15-source-map-filename-drift", src)


# ---- Integration: representative real-world configs --------------------


def test_full_vite_config_with_multiple_leaks() -> None:
    """A Vite config that trips H-3 + H-4 + H-7 + H-10 + H-14
    simultaneously. Exercises the dedupe + sort path."""
    src = (
        "import { defineConfig, loadEnv } from 'vite';\n"
        "export default defineConfig(({ mode }) => {\n"
        "  const env = loadEnv(mode, process.cwd(), '');\n"
        "  return {\n"
        "    server: { fs: { allow: ['/'] } },\n"
        "    build: { sourcemap: true, minify: false },\n"
        "    define: {\n"
        "      __OPENAI_API_KEY__: JSON.stringify(process.env.OPENAI_API_KEY),\n"
        "    },\n"
        "  };\n"
        "});\n"
    )
    findings = jbp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "bundler-h3-vite-prod-sourcemap" in rule_ids
    assert "bundler-h4-vite-prod-no-minify" in rule_ids
    assert "bundler-h7-define-secret-inline" in rule_ids
    assert "bundler-h10-vite-loadenv-no-prefix" in rule_ids
    assert "bundler-h14-vite-fs-allow-overbroad" in rule_ids


def test_safe_next_config_no_findings() -> None:
    """A correctly-authored next.config produces zero bundler-config
    findings."""
    src = (
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  reactStrictMode: true,\n"
        "  serverExternalPackages: ['pg'],\n"
        "  productionBrowserSourceMaps: false,\n"
        "};\n"
        "module.exports = nextConfig;\n"
    )
    assert jbp.scan_text(src) == []


def test_safe_webpack_config_no_findings() -> None:
    """A correctly-authored webpack config produces zero findings."""
    src = (
        "const webpack = require('webpack');\n"
        "module.exports = (env, argv) => ({\n"
        "  mode: argv.mode || 'production',\n"
        "  devtool: argv.mode === 'development' ? 'source-map' : false,\n"
        "});\n"
    )
    findings = jbp.scan_text(src)
    # The dev-mode gate guard fires AND prod literal is also
    # present — both H-1 and H-2 should be suppressed.
    bundler_findings = [
        f for f in findings if f.rule_id.startswith("bundler-")
    ]
    assert bundler_findings == [], bundler_findings


# ---- RE2-safety smoke test ---------------------------------------------


def test_no_catastrophic_backtracking_on_long_inputs() -> None:
    """Run every rule against a pathological-shape input — should
    return in milliseconds, not hang."""
    # 50 KB of mostly-benign text with a few trigger fragments.
    pathological = (
        ("a" * 1000 + "process.env.X" + "b" * 1000) * 25
        + "\n//# sourceMappingURL=https://evil.example/leak.map\n"
        + "\nconst x = { sourcemap: true };\n"
    )
    import time
    t0 = time.time()
    findings = jbp.scan_text(pathological)
    elapsed = time.time() - t0
    # Should be well under 1 second on any modern machine.
    assert elapsed < 2.0, f"scan_text too slow: {elapsed:.3f}s"
    # H-15 should still fire on the pragma.
    assert any(
        f.rule_id == "bundler-h15-source-mapping-url-drift"
        for f in findings
    )


# ---- Matched-text truncation -------------------------------------------


def test_long_match_truncated_to_200_chars() -> None:
    """Matches longer than 200 characters are suffixed with '…'."""
    # H-7 matches `process.env.X_SECRET` (short) — synthesise an
    # H-15 hit with a deliberately long URL to exercise truncation.
    src = "//# sourceMappingURL=https://evil.example.com/" + "a" * 300 + ".map\n"
    findings = [
        f for f in jbp.scan_text(src)
        if f.rule_id == "bundler-h15-source-mapping-url-drift"
    ]
    assert findings
    # Match is truncated to 200 chars + …
    assert findings[0].matched_text.endswith("…")
    assert len(findings[0].matched_text) <= 201  # 200 + ellipsis
