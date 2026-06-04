"""Tests for backstage_patterns.py — 2+ tests per rule, 10 rules.

Wave-37 distillation round 23, angle Backstage SoftwareTemplate + Scaffolder.
Each rule gets at least one positive (realistic vulnerable Backstage YAML /
TS snippet that MUST match) and one negative (the hardened shape that MUST
NOT match).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))  # noqa: E402

import backstage_patterns as bsp  # type: ignore[import-not-found]  # noqa: E402
from backstage_patterns import RULES, Finding, scan_text  # type: ignore[import-not-found]  # noqa: E402


def _has(findings: list[Finding], rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---- Data-model / scanner invariants ------------------------------------


def test_rules_is_tuple_with_expected_ids() -> None:
    """RULES is a tuple covering all 10 advertised Backstage rule ids."""
    assert isinstance(RULES, tuple)
    ids = {r.id for r in RULES}
    expected = {
        "backstage-fetch-template-user-url-ssrf",
        "backstage-publish-github-user-repourl",
        "backstage-fs-rename-user-dest-path",
        "backstage-scaffolder-action-dynamic-code",
        "backstage-prod-config-guest-auth",
        "backstage-catalog-group-privilege-escalation",
        "backstage-ldap-empty-group-filter",
        "backstage-fetch-plain-user-url",
        "backstage-location-http-target-ssrf",
        "backstage-openapi-mock-server-exposed",
    }
    assert expected == ids
    assert len(RULES) == 10


def test_every_rule_has_severity_and_owasp() -> None:
    """Every rule carries a valid severity, an OWASP tag, and a description."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for r in RULES:
        assert r.severity in valid, r.id
        assert r.owasp_asi, r.id
        assert r.description.strip() and r.name.strip(), r.id


def test_patterns_are_re2_safe_no_lookaround() -> None:
    """No compiled rule pattern uses lookahead/lookbehind/backreferences."""
    for r in RULES:
        src = r.pattern.pattern
        assert "(?=" not in src and "(?!" not in src, r.id
        assert "(?<" not in src, r.id
        assert not re.search(r"\\[1-9]", src), r.id


def test_scan_text_empty_returns_empty() -> None:
    """An empty document yields no findings."""
    assert scan_text("") == []


# ---- D1 — backstage-fetch-template-user-url-ssrf ------------------------


def test_fetch_template_user_url_flagged() -> None:
    """A fetch:template url built from parameters must be flagged (SSRF)."""
    src = (
        "steps:\n"
        "  - id: fetch\n"
        "    action: fetch:template\n"
        "    input:\n"
        "      url: ${{ parameters.repoUrl }}\n"
    )
    assert _has(scan_text(src), "backstage-fetch-template-user-url-ssrf")


def test_fetch_template_hardcoded_url_safe() -> None:
    """A hardcoded fetch:template url must not be flagged."""
    src = (
        "steps:\n"
        "  - id: fetch\n"
        "    action: fetch:template\n"
        "    input:\n"
        "      url: ./skeleton\n"
    )
    assert not _has(scan_text(src), "backstage-fetch-template-user-url-ssrf")


# ---- D2 — backstage-publish-github-user-repourl -------------------------


def test_publish_github_user_repourl_flagged() -> None:
    """A repoUrl interpolated from parameters must be flagged."""
    src = (
        "  - id: publish\n"
        "    action: publish:github\n"
        "    input:\n"
        "      repoUrl: ${{ parameters.repoUrl }}\n"
    )
    assert _has(scan_text(src), "backstage-publish-github-user-repourl")


def test_publish_github_hardcoded_repourl_safe() -> None:
    """A hardcoded repoUrl host must not be flagged."""
    src = (
        "  - id: publish\n"
        "    action: publish:github\n"
        "    input:\n"
        "      repoUrl: github.com?owner=acme&repo=service\n"
    )
    assert not _has(scan_text(src), "backstage-publish-github-user-repourl")


# ---- D3 — backstage-fs-rename-user-dest-path ----------------------------


def test_fs_rename_user_dest_flagged() -> None:
    """A fs:rename `to:` built from parameters must be flagged."""
    src = (
        "  - id: rename\n"
        "    action: fs:rename\n"
        "    input:\n"
        "      to: ${{ parameters.destPath }}\n"
    )
    assert _has(scan_text(src), "backstage-fs-rename-user-dest-path")


def test_fs_rename_static_dest_safe() -> None:
    """A fs:rename with a static destination must not be flagged."""
    src = (
        "  - id: rename\n"
        "    action: fs:rename\n"
        "    input:\n"
        "      to: output/result.txt\n"
    )
    assert not _has(scan_text(src), "backstage-fs-rename-user-dest-path")


# ---- D4 — backstage-scaffolder-action-dynamic-code ----------------------


def test_scaffolder_action_eval_flagged() -> None:
    """A scaffolder action using vm.runInNewContext must be flagged."""
    src = (
        "export const customAction = createTemplateAction({\n"
        "  async handler(ctx) {\n"
        "    const result = vm.runInNewContext(ctx.input.script, sandbox);\n"
        "  },\n"
        "});\n"
    )
    assert _has(scan_text(src), "backstage-scaffolder-action-dynamic-code")


def test_scaffolder_action_no_dynamic_code_safe() -> None:
    """A scaffolder action with no eval/vm sink must not be flagged."""
    src = (
        "export const customAction = createTemplateAction({\n"
        "  async handler(ctx) {\n"
        "    await ctx.output('ok', true);\n"
        "  },\n"
        "});\n"
    )
    assert not _has(scan_text(src), "backstage-scaffolder-action-dynamic-code")


# ---- D5 — backstage-prod-config-guest-auth ------------------------------


def test_prod_config_guest_auth_flagged() -> None:
    """A guest provider under auth.providers must be flagged."""
    src = (
        "auth:\n"
        "  providers:\n"
        "    github:\n"
        "      development:\n"
        "        clientId: abc\n"
        "    guest:\n"
    )
    assert _has(scan_text(src), "backstage-prod-config-guest-auth")


def test_prod_config_no_guest_auth_safe() -> None:
    """An auth.providers block without guest must not be flagged."""
    src = (
        "auth:\n"
        "  providers:\n"
        "    github:\n"
        "      production:\n"
        "        clientId: abc\n"
    )
    assert not _has(scan_text(src), "backstage-prod-config-guest-auth")


# ---- D6 — backstage-catalog-group-privilege-escalation ------------------


def test_catalog_group_admin_flagged() -> None:
    """A kind: Group catalog entity with an admin name must be flagged."""
    src = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Group\n"
        "metadata:\n"
        "  name: platform-admins\n"
        "spec:\n"
        "  type: team\n"
        "  members: [attacker]\n"
    )
    assert _has(scan_text(src), "backstage-catalog-group-privilege-escalation")


def test_catalog_component_safe() -> None:
    """A kind: Component entity (not Group) must not be flagged."""
    src = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        "  name: my-service\n"
        "spec:\n"
        "  type: service\n"
    )
    assert not _has(scan_text(src), "backstage-catalog-group-privilege-escalation")


def test_catalog_group_non_sensitive_name_safe() -> None:
    """A kind: Group with a non-sensitive name must not be flagged."""
    src = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Group\n"
        "metadata:\n"
        "  name: frontend-team\n"
        "spec:\n"
        "  type: team\n"
    )
    assert not _has(scan_text(src), "backstage-catalog-group-privilege-escalation")


# ---- D7 — backstage-ldap-empty-group-filter -----------------------------


def test_ldap_empty_group_filter_flagged() -> None:
    """An empty groupSearchFilter must be flagged."""
    src = (
        "ldap:\n"
        "  providers:\n"
        "    - target: ldaps://ds.example.net\n"
        "      groups:\n"
        "        dn: ou=groups,dc=example,dc=net\n"
        "        options:\n"
        "          groupSearchFilter: ''\n"
    )
    assert _has(scan_text(src), "backstage-ldap-empty-group-filter")


def test_ldap_wildcard_group_filter_flagged() -> None:
    """A (objectClass=*) wildcard groupSearchFilter must be flagged."""
    src = "groupSearchFilter: '(objectClass=*)'\n"
    assert _has(scan_text(src), "backstage-ldap-empty-group-filter")


def test_ldap_scoped_group_filter_safe() -> None:
    """A scoped groupSearchFilter must not be flagged."""
    src = "groupSearchFilter: '(&(objectClass=groupOfNames)(cn=eng-*))'\n"
    assert not _has(scan_text(src), "backstage-ldap-empty-group-filter")


# ---- D8 — backstage-fetch-plain-user-url --------------------------------


def test_fetch_plain_action_flagged() -> None:
    """A fetch:plain action must be flagged (archive unpack / SSRF)."""
    src = (
        "  - id: fetch\n"
        "    action: fetch:plain\n"
        "    input:\n"
        "      url: ${{ parameters.archiveUrl }}\n"
    )
    assert _has(scan_text(src), "backstage-fetch-plain-user-url")


def test_fetch_template_action_not_plain_safe() -> None:
    """A fetch:template action (not fetch:plain) must not fire the plain rule."""
    src = (
        "  - id: fetch\n"
        "    action: fetch:template\n"
        "    input:\n"
        "      url: ./skeleton\n"
    )
    assert not _has(scan_text(src), "backstage-fetch-plain-user-url")


# ---- D9 — backstage-location-http-target-ssrf ---------------------------


def test_location_http_target_flagged() -> None:
    """A kind: Location with a plaintext http target must be flagged."""
    src = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Location\n"
        "metadata:\n"
        "  name: external\n"
        "spec:\n"
        "  targets:\n"
        "    - http://10.0.0.5/catalog-info.yaml\n"
    )
    assert _has(scan_text(src), "backstage-location-http-target-ssrf")


def test_location_https_github_target_safe() -> None:
    """A kind: Location with only https GitHub targets must not be flagged."""
    src = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Location\n"
        "metadata:\n"
        "  name: trusted\n"
        "spec:\n"
        "  targets:\n"
        "    - https://github.com/acme/repo/blob/main/catalog-info.yaml\n"
    )
    assert not _has(scan_text(src), "backstage-location-http-target-ssrf")


# ---- D10 — backstage-openapi-mock-server-exposed ------------------------


def test_openapi_mock_server_flagged() -> None:
    """An OpenAPIBackend with mock: true must be flagged."""
    src = (
        "const api = new OpenAPIBackend({\n"
        "  definition: './openapi.yaml',\n"
        "  mock: true,\n"
        "});\n"
        "router.get('/api', (req, res) => api.handleRequest(req));\n"
    )
    assert _has(scan_text(src), "backstage-openapi-mock-server-exposed")


def test_openapi_mock_response_for_operation_flagged() -> None:
    """A mockResponseForOperation call must be flagged."""
    src = "const resp = api.mockResponseForOperation('getUser');\n"
    assert _has(scan_text(src), "backstage-openapi-mock-server-exposed")


def test_openapi_backend_real_mode_safe() -> None:
    """An OpenAPIBackend with mock disabled must not be flagged."""
    src = (
        "const api = new OpenAPIBackend({\n"
        "  definition: './openapi.yaml',\n"
        "  handlers: realHandlers,\n"
        "});\n"
    )
    assert not _has(scan_text(src), "backstage-openapi-mock-server-exposed")


# ---- module-import sanity (keeps `bsp` referenced) ----------------------


def test_module_exposes_scan_text() -> None:
    """The module exports a callable scan_text entry point."""
    assert callable(bsp.scan_text)
