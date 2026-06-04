"""Tests for salesforce_apex_patterns — 2 tests per rule (positive + negative)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_secrets import b62  # type: ignore[import-not-found]  # noqa: E402
from salesforce_apex_patterns import RULES, scan_text  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ids(findings):
    """Return a set of rule IDs from a list of findings."""
    return {f.rule_id for f in findings}


def _ids_for(text, rule_id):
    """Return findings matching *rule_id* in *text*."""
    return [f for f in scan_text(text) if f.rule_id == rule_id]


# ---------------------------------------------------------------------------
# sf-soql-inject-concat
# ---------------------------------------------------------------------------

def test_soql_inject_concat_positive():
    """Database.query() with + concat triggers sf-soql-inject-concat."""
    code = """
public List<Account> search(String userInput) {
    String soql = 'SELECT Id FROM Account WHERE Name LIKE \\'%\\'' + userInput + '\\'%\\'';
    return Database.query(soql + ' LIMIT 100');
}
"""
    findings = _ids_for(code, "sf-soql-inject-concat")
    assert findings, "expected at least one sf-soql-inject-concat finding"


def test_soql_inject_concat_negative():
    """Database.query() with no concat does not trigger sf-soql-inject-concat."""
    code = "List<Account> r = Database.query(safeVar);"
    findings = _ids_for(code, "sf-soql-inject-concat")
    assert not findings, "no concat — should not fire sf-soql-inject-concat"


# ---------------------------------------------------------------------------
# sf-soql-inject-bare-var
# ---------------------------------------------------------------------------

def test_soql_inject_bare_var_positive():
    """Database.query(someVar) triggers sf-soql-inject-bare-var."""
    code = "List<sObject> rows = Database.query(soqlString);"
    findings = _ids_for(code, "sf-soql-inject-bare-var")
    assert findings, "bare variable arg should fire sf-soql-inject-bare-var"


def test_soql_inject_bare_var_negative():
    """Database.query() with concat (not bare var) does not fire sf-soql-inject-bare-var."""
    code = "List<sObject> r = Database.query('SELECT Id FROM Account WHERE Id = \\'' + someId + '\\'');"
    findings = _ids_for(code, "sf-soql-inject-bare-var")
    assert not findings, "concat form should not fire sf-soql-inject-bare-var"


# ---------------------------------------------------------------------------
# sf-without-sharing-class
# ---------------------------------------------------------------------------

def test_without_sharing_class_positive():
    """'without sharing class ...' triggers sf-without-sharing-class."""
    code = "public without sharing class AccountController {"
    findings = _ids_for(code, "sf-without-sharing-class")
    assert findings, "expected sf-without-sharing-class finding"


def test_without_sharing_class_negative():
    """'with sharing class ...' does not trigger sf-without-sharing-class."""
    code = "public with sharing class AccountController {"
    findings = _ids_for(code, "sf-without-sharing-class")
    assert not findings, "'with sharing' should not fire sf-without-sharing-class"


# ---------------------------------------------------------------------------
# sf-aura-enabled-method
# ---------------------------------------------------------------------------

def test_aura_enabled_method_positive():
    """@AuraEnabled on a public static method triggers sf-aura-enabled-method."""
    code = """
@AuraEnabled(cacheable=true)
public static List<Contact> getContacts(String accountId) {
    return [SELECT Id FROM Contact];
}
"""
    findings = _ids_for(code, "sf-aura-enabled-method")
    assert findings, "expected sf-aura-enabled-method finding"


def test_aura_enabled_method_negative():
    """@AuraEnabled on a non-static method does not trigger sf-aura-enabled-method."""
    code = """
@AuraEnabled
public List<Contact> getContacts() {
    return [SELECT Id FROM Contact];
}
"""
    findings = _ids_for(code, "sf-aura-enabled-method")
    assert not findings, "non-static @AuraEnabled should not fire sf-aura-enabled-method"


# ---------------------------------------------------------------------------
# sf-callout-non-named-cred
# ---------------------------------------------------------------------------

def test_callout_non_named_cred_positive():
    """setEndpoint(variable) triggers sf-callout-non-named-cred."""
    code = """
HttpRequest req = new HttpRequest();
req.setEndpoint(userProvidedUrl);
req.setMethod('POST');
"""
    findings = _ids_for(code, "sf-callout-non-named-cred")
    assert findings, "expected sf-callout-non-named-cred finding"


def test_callout_non_named_cred_negative():
    """setEndpoint('callout:...') string literal does not match sf-callout-non-named-cred."""
    code = "req.setEndpoint('callout:MyNamedCredential/api/v1');"
    findings = _ids_for(code, "sf-callout-non-named-cred")
    assert not findings, "Named Credential string should not fire sf-callout-non-named-cred"


# ---------------------------------------------------------------------------
# sf-soql-like-wildcard-inject
# ---------------------------------------------------------------------------

def test_soql_like_wildcard_positive():
    """SOQL LIKE '%' + var + '%' triggers sf-soql-like-wildcard-inject."""
    # Use double-quoted percent literals to avoid escaping confusion
    code = 'String q = "SELECT Id FROM Lead WHERE LastName LIKE " + "\'%" + searchTerm + "%\'"'
    # Use the canonical unambiguous form that directly matches the pattern
    code = "WHERE LastName LIKE '%' + searchTerm + '%'"
    findings = _ids_for(code, "sf-soql-like-wildcard-inject")
    assert findings, "expected sf-soql-like-wildcard-inject finding"


def test_soql_like_wildcard_negative():
    """SOQL LIKE with a literal string (no concat) does not trigger sf-soql-like-wildcard-inject."""
    code = "WHERE LastName LIKE '%Smith%'"
    findings = _ids_for(code, "sf-soql-like-wildcard-inject")
    assert not findings, "literal LIKE pattern should not fire sf-soql-like-wildcard-inject"


# ---------------------------------------------------------------------------
# sf-sfdx-access-token
# ---------------------------------------------------------------------------

def test_sfdx_access_token_positive():
    """JSON accessToken starting with 00 triggers sf-sfdx-access-token."""
    code = f'{{"accessToken": "00D{b62("sf-access-tok", 47)}"}}'
    findings = _ids_for(code, "sf-sfdx-access-token")
    assert findings, "expected sf-sfdx-access-token finding"


def test_sfdx_access_token_negative():
    """JSON accessToken with a non-Salesforce value does not trigger sf-sfdx-access-token."""
    code = '{"accessToken": "ya29.a0AfH6SMC_shorttoken"}'
    findings = _ids_for(code, "sf-sfdx-access-token")
    assert not findings, "non-Salesforce token should not fire sf-sfdx-access-token"


# ---------------------------------------------------------------------------
# sf-visualforce-no-https
# ---------------------------------------------------------------------------

def test_visualforce_no_https_positive():
    """<apex:page> without requireSecureRendering triggers sf-visualforce-no-https."""
    code = '<apex:page controller="MyController" action="{!init}">'
    findings = _ids_for(code, "sf-visualforce-no-https")
    assert findings, "expected sf-visualforce-no-https finding"


def test_visualforce_no_https_negative():
    """<apex:page> with requireSecureRendering does not trigger sf-visualforce-no-https."""
    code = '<apex:page controller="MyController" requireSecureRendering="true" action="{!init}">'
    findings = _ids_for(code, "sf-visualforce-no-https")
    assert not findings, "requireSecureRendering present — should not fire sf-visualforce-no-https"


# ---------------------------------------------------------------------------
# sf-connected-app-full-scope
# ---------------------------------------------------------------------------

def test_connected_app_full_scope_positive():
    """<scopes>Full</scopes> in ConnectedApp XML triggers sf-connected-app-full-scope."""
    code = """
<ConnectedApp xmlns="http://soap.sforce.com/2006/04/metadata">
    <oauthConfig>
        <scopes>Full</scopes>
        <scopes>RefreshToken</scopes>
    </oauthConfig>
</ConnectedApp>
"""
    findings = _ids_for(code, "sf-connected-app-full-scope")
    assert findings, "expected sf-connected-app-full-scope finding"


def test_connected_app_full_scope_negative():
    """<scopes>Api</scopes> does not trigger sf-connected-app-full-scope."""
    code = """
<ConnectedApp xmlns="http://soap.sforce.com/2006/04/metadata">
    <oauthConfig>
        <scopes>Api</scopes>
        <scopes>RefreshToken</scopes>
    </oauthConfig>
</ConnectedApp>
"""
    findings = _ids_for(code, "sf-connected-app-full-scope")
    assert not findings, "Api scope should not fire sf-connected-app-full-scope"


# ---------------------------------------------------------------------------
# Meta: RULES tuple sanity
# ---------------------------------------------------------------------------

def test_rules_count():
    """RULES tuple contains exactly 9 rules."""
    assert len(RULES) == 9, f"expected 9 rules, got {len(RULES)}"


def test_rules_ids_unique():
    """All rule IDs in RULES are unique."""
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids)), "duplicate rule IDs detected"


def test_rules_ids_prefixed():
    """All rule IDs start with 'sf-'."""
    for rule in RULES:
        assert rule.id.startswith("sf-"), f"rule {rule.id!r} missing 'sf-' prefix"


def test_scan_text_empty():
    """scan_text('') returns an empty list without errors."""
    assert scan_text("") == []


def test_scan_text_returns_sorted():
    """scan_text output is sorted by (line, column, rule_id)."""
    code = """
public without sharing class Foo {
    @AuraEnabled(cacheable=true)
    public static List<Account> get(String v) {
        return Database.query(v);
    }
}
"""
    findings = scan_text(code)
    keys = [(f.line, f.column, f.rule_id) for f in findings]
    assert keys == sorted(keys), "scan_text output is not sorted"
