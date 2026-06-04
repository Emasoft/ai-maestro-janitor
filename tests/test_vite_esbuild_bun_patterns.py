"""Tests for ``scripts/lib/vite_esbuild_bun_patterns.py``.

Wave 30 distillation round 16, angle vite-esbuild-bun — pattern-coverage
tests for the 11 rules (covering 7 distinct vulnerability classes) distilled
from ``reports/distill-round-16/vite-esbuild-bun.md``.

Each rule gets at least two tests: one positive (the documented attack
shape fires) and one negative (a documented carve-out suppresses the hit).
Module-level invariants (unique IDs, compiled patterns, OWASP mapping,
severity enum) are also checked.

Sibling tests:
  * ``tests/test_js_bundler_patterns.py``      (Wave 21 — webpack/Vite/esbuild base)
  * ``tests/test_auth_flow_patterns.py``       (Wave 17 batch A)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

import vite_esbuild_bun_patterns as veb  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, dsn, secret  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[veb.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in veb.scan_text(text) if f.rule_id == rule_id]


# ---- Module-level invariants --------------------------------------------


def test_rules_tuple_is_tuple() -> None:
    """RULES must be a tuple."""
    assert isinstance(veb.RULES, tuple)
    assert len(veb.RULES) >= 7


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in veb.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    for rule in veb.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in veb.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    for rule in veb.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_expected_rule_ids_present() -> None:
    """All 11 rule IDs from the distillation report are present."""
    expected = {
        "veb-01-next-public-secret-in-env-file",
        "veb-02-vite-env-prefix-empty",
        "veb-02-vite-env-prefix-empty-array",
        "veb-03-import-meta-glob-traversal",
        "veb-03-import-meta-glob-dotenv",
        "veb-04-vite-proxy-embedded-credentials",
        "veb-05-esbuild-metafile-public-outdir",
        "veb-05-esbuild-metafile-cli-public",
        "veb-06-bun-registry-token-hardcoded",
        "veb-07-dev-server-dockerfile-cmd",
        "veb-07-dev-server-dockerfile-cmd-shell",
        "veb-07-dev-server-compose-command",
    }
    actual = {r.id for r in veb.RULES}
    assert expected.issubset(actual), expected - actual


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the js_bundler_patterns.Finding shape."""
    f = veb.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_scan_empty_text_returns_no_findings() -> None:
    """Empty input is a fast-path, no findings."""
    assert veb.scan_text("") == []


def test_findings_sorted_by_line() -> None:
    """Output is sorted by (line, column, rule_id)."""
    src = (
        "# .env.production\n"
        f"NEXT_PUBLIC_SECRET_KEY={secret('sk_' + 'live_', 'veb-sk-sorted', 24)}\n"
        "NEXT_PUBLIC_API_TOKEN=some-long-secret-value-here\n"
    )
    findings = veb.scan_text(src)
    for i in range(1, len(findings)):
        prev = findings[i - 1]
        cur = findings[i]
        assert (prev.line, prev.column, prev.rule_id) <= (
            cur.line,
            cur.column,
            cur.rule_id,
        )


# ---- VEB-01 : next-public-secret-in-env-file ----------------------------


def test_veb01_stripe_secret_key_fires_critical() -> None:
    """NEXT_PUBLIC_STRIPE_SECRET_KEY in .env fires CRITICAL."""
    src = f"NEXT_PUBLIC_STRIPE_SECRET_KEY={secret('sk_' + 'live_', 'veb01-stripe', 24)}\n"
    hits = _hits("veb-01-next-public-secret-in-env-file", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-04"


def test_veb01_openai_api_key_fires() -> None:
    """NEXT_PUBLIC_OPENAI_API_KEY with real-shaped value fires."""
    src = "NEXT_PUBLIC_OPENAI_API_KEY=sk-proj-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n"
    assert _hits("veb-01-next-public-secret-in-env-file", src)


def test_veb01_github_token_fires() -> None:
    """NEXT_PUBLIC_GITHUB_TOKEN with real-shaped value fires."""
    src = f"NEXT_PUBLIC_GITHUB_TOKEN={secret('ghp' + '_', 'veb01-ghp', 28)}\n"
    assert _hits("veb-01-next-public-secret-in-env-file", src)


def test_veb01_plain_database_url_no_fire() -> None:
    """DATABASE_URL without NEXT_PUBLIC_ prefix does NOT fire."""
    src = f"DATABASE_URL={dsn('postgres', 'veb-pg-nofire', host='host', port=None, db='db')}\n"
    assert not _hits("veb-01-next-public-secret-in-env-file", src)


def test_veb01_next_public_app_url_no_fire() -> None:
    """NEXT_PUBLIC_APP_URL is not a secret-shaped name — no fire."""
    src = "NEXT_PUBLIC_APP_URL=https://myapp.com\n"
    assert not _hits("veb-01-next-public-secret-in-env-file", src)


def test_veb01_short_value_no_fire() -> None:
    """Values shorter than 8 chars do not fire (likely a placeholder)."""
    src = "NEXT_PUBLIC_SECRET_KEY=tooshrt\n"
    assert not _hits("veb-01-next-public-secret-in-env-file", src)


# ---- VEB-02 : vite-env-prefix-empty -------------------------------------


def test_veb02_scalar_empty_string_double_quote_fires() -> None:
    """envPrefix: \"\" (double-quote scalar) fires HIGH."""
    src = 'envPrefix: "",\n'
    hits = _hits("veb-02-vite-env-prefix-empty", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb02_scalar_empty_string_single_quote_fires() -> None:
    """envPrefix: '' (single-quote scalar) fires HIGH."""
    src = "envPrefix: '',\n"
    assert _hits("veb-02-vite-env-prefix-empty", src)


def test_veb02_array_empty_string_fires() -> None:
    """envPrefix: [''] (array form) fires on the array rule."""
    src = "envPrefix: [''],\n"
    assert _hits("veb-02-vite-env-prefix-empty-array", src)


def test_veb02_array_double_quote_fires() -> None:
    """envPrefix: [\"\"] (double-quote array form) fires."""
    src = 'envPrefix: [""],\n'
    assert _hits("veb-02-vite-env-prefix-empty-array", src)


def test_veb02_normal_prefix_no_fire() -> None:
    """envPrefix: 'VITE_' is correct — no fire on either rule."""
    src = "envPrefix: 'VITE_',\n"
    assert not _hits("veb-02-vite-env-prefix-empty", src)
    assert not _hits("veb-02-vite-env-prefix-empty-array", src)


def test_veb02_non_empty_array_no_fire() -> None:
    """envPrefix: ['VITE_'] is correct — no fire."""
    src = "envPrefix: ['VITE_'],\n"
    assert not _hits("veb-02-vite-env-prefix-empty-array", src)


# ---- VEB-03 : import-meta-glob-traversal --------------------------------


def test_veb03_double_traversal_fires() -> None:
    """Two ../ traversals in import.meta.glob fires HIGH."""
    src = "const mods = import.meta.glob('../../**/*.json')\n"
    hits = _hits("veb-03-import-meta-glob-traversal", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb03_triple_traversal_fires() -> None:
    """Three ../ traversals also fire."""
    src = "const cfg = import.meta.glob('../../../config/**')\n"
    assert _hits("veb-03-import-meta-glob-traversal", src)


def test_veb03_single_traversal_no_fire() -> None:
    """A single ../ traversal is within normal src layout — no fire."""
    src = "const mods = import.meta.glob('../components/*.vue')\n"
    assert not _hits("veb-03-import-meta-glob-traversal", src)


def test_veb03_dotenv_pattern_fires() -> None:
    """import.meta.glob targeting .env files fires the dotenv rule."""
    src = "const envFiles = import.meta.glob('.env*')\n"
    assert _hits("veb-03-import-meta-glob-dotenv", src)


def test_veb03_dotenv_local_pattern_fires() -> None:
    """import.meta.glob('.env.local') fires the dotenv rule."""
    src = "const env = import.meta.glob('.env.local')\n"
    assert _hits("veb-03-import-meta-glob-dotenv", src)


def test_veb03_safe_glob_no_fire() -> None:
    """import.meta.glob('./pages/*.ts') is safe — no fire on either rule."""
    src = "const pages = import.meta.glob('./pages/*.ts')\n"
    assert not _hits("veb-03-import-meta-glob-traversal", src)
    assert not _hits("veb-03-import-meta-glob-dotenv", src)


# ---- VEB-04 : vite-proxy-embedded-credentials ---------------------------


def test_veb04_https_proxy_with_user_password_fires() -> None:
    """target with embedded user:password in https URL fires HIGH."""
    _pw = b62("veb04-proxy-pw", 10)
    src = f"target: 'https://admin:{_pw}@staging.internal.corp/api',\n"
    hits = _hits("veb-04-vite-proxy-embedded-credentials", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb04_http_proxy_with_token_fires() -> None:
    """target with http:// and credentials also fires."""
    src = f"'/graphql': 'http://bot:{secret('ghp' + '_', 'veb04-ghp-proxy', 12)}@internal.corp/graphql',\n"
    assert _hits("veb-04-vite-proxy-embedded-credentials", src)


def test_veb04_proxy_no_credentials_no_fire() -> None:
    """target without credentials does not fire."""
    src = "target: 'https://api.example.com',\n"
    assert not _hits("veb-04-vite-proxy-embedded-credentials", src)


def test_veb04_empty_password_no_fire() -> None:
    """target: 'http://user:@host/' has an empty password (<4 chars) — no fire."""
    src = "target: 'http://user:@localhost:8080/',\n"
    assert not _hits("veb-04-vite-proxy-embedded-credentials", src)


# ---- VEB-05 : esbuild-metafile-public-outdir ----------------------------


def test_veb05_metafile_true_fires() -> None:
    """metafile: true in an esbuild config fires HIGH."""
    src = (
        "const result = await esbuild.build({\n"
        "  entryPoints: ['src/index.ts'],\n"
        "  bundle: true,\n"
        "  outdir: 'dist',\n"
        "  metafile: true,\n"
        "});\n"
    )
    hits = _hits("veb-05-esbuild-metafile-public-outdir", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb05_metafile_cli_dist_fires() -> None:
    """--metafile=dist/meta.json in a build script fires the CLI rule."""
    src = "esbuild src/index.ts --bundle --metafile=dist/meta.json --outdir=dist\n"
    assert _hits("veb-05-esbuild-metafile-cli-public", src)


def test_veb05_metafile_cli_public_dir_fires() -> None:
    """--metafile=public/meta.json also fires the CLI rule."""
    src = "esbuild src/index.ts --bundle --metafile=public/meta.json\n"
    assert _hits("veb-05-esbuild-metafile-cli-public", src)


def test_veb05_metafile_safe_dest_suppresses_api() -> None:
    """writeFileSync to tmp/ path suppresses the API-form finding."""
    src = (
        "const result = await esbuild.build({ metafile: true });\n"
        "fs.writeFileSync('tmp/meta.json', JSON.stringify(result.metafile));\n"
    )
    assert not _hits("veb-05-esbuild-metafile-public-outdir", src)


def test_veb05_metafile_false_no_fire() -> None:
    """metafile: false does not fire."""
    src = "const result = await esbuild.build({ metafile: false });\n"
    assert not _hits("veb-05-esbuild-metafile-public-outdir", src)


# ---- VEB-06 : bun-registry-token-hardcoded ------------------------------


def test_veb06_npm_token_fires_critical() -> None:
    """Literal npm token in bunfig.toml fires CRITICAL."""
    src = (
        '[install.scopes]\n'
        '"@myorg" = { url = "https://npm.internal.corp/", '
        'token = "npm_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" }\n'
    )
    hits = _hits("veb-06-bun-registry-token-hardcoded", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_veb06_github_token_fires() -> None:
    """Hardcoded GitHub PAT in bunfig.toml fires."""
    _tok = secret("ghp" + "_", "veb06-ghp-bun", 28)
    src = f'"@another" = {{ url = "https://jsr.io/", token = "{_tok}" }}\n'
    assert _hits("veb-06-bun-registry-token-hardcoded", src)


def test_veb06_env_var_reference_no_fire() -> None:
    """token = \"$NPM_TOKEN\" (env-var reference starting with $) does NOT fire."""
    src = '"@myorg" = { url = "https://npm.internal.corp/", token = "$NPM_TOKEN" }\n'
    assert not _hits("veb-06-bun-registry-token-hardcoded", src)


def test_veb06_short_token_no_fire() -> None:
    """A token value under 13 chars does not fire (likely a placeholder)."""
    src = '"@org" = { token = "abc123" }\n'
    assert not _hits("veb-06-bun-registry-token-hardcoded", src)


# ---- VEB-07 : dev-server-in-prod-container ------------------------------


def test_veb07_dockerfile_npm_run_dev_fires() -> None:
    """CMD ["npm", "run", "dev"] in Dockerfile fires HIGH."""
    src = 'CMD ["npm", "run", "dev"]\n'
    hits = _hits("veb-07-dev-server-dockerfile-cmd", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb07_dockerfile_npx_vite_fires() -> None:
    """CMD ["npx", "vite"] fires."""
    src = 'CMD ["npx", "vite"]\n'
    assert _hits("veb-07-dev-server-dockerfile-cmd", src)


def test_veb07_dockerfile_next_dev_fires() -> None:
    """CMD including 'next dev' fires."""
    src = 'CMD ["npx", "next", "dev"]\n'
    assert _hits("veb-07-dev-server-dockerfile-cmd", src)


def test_veb07_dockerfile_npm_start_no_fire() -> None:
    """CMD [\"npm\", \"start\"] does NOT fire — 'start' is not a dev-only command."""
    src = 'CMD ["npm", "start"]\n'
    assert not _hits("veb-07-dev-server-dockerfile-cmd", src)


def test_veb07_compose_npm_run_dev_fires() -> None:
    """docker-compose command: npm run dev fires the compose rule."""
    src = "    command: npm run dev\n"
    hits = _hits("veb-07-dev-server-compose-command", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_veb07_compose_vite_fires() -> None:
    """docker-compose command: vite fires."""
    src = "    command: vite\n"
    assert _hits("veb-07-dev-server-compose-command", src)


def test_veb07_compose_next_start_no_fire() -> None:
    """command: next start is production — no fire."""
    src = "    command: next start\n"
    assert not _hits("veb-07-dev-server-compose-command", src)


def test_veb07_dockerfile_production_server_no_fire() -> None:
    """CMD [\"nginx\", \"-g\", \"daemon off;\"] is a production server — no fire."""
    src = 'CMD ["nginx", "-g", "daemon off;"]\n'
    assert not _hits("veb-07-dev-server-dockerfile-cmd", src)
