"""Tests for scripts/lib/distributed_consensus_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 distributed
lock / consensus catalogue (6 anti-patterns covering etcd auth, etcd
v3 RBAC, Consul ACL, ZooKeeper ACL, Raft inter-member RPC mTLS, and
Redlock single-instance / clock-skew). Each rule has at least one
positive test exercising the canary AND at least one negative test
exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import distributed_consensus_patterns as dcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(dcp.RULES, tuple)
    rule_ids = {r.id for r in dcp.RULES}
    expected = {
        "consensus-etcd-auth-disabled",
        "consensus-etcd-role-grant-permissive-prefix",
        "consensus-consul-acl-default-allow",
        "consensus-zookeeper-world-anyone-acl",
        "consensus-raft-rpc-no-mtls",
        "consensus-redlock-single-instance-or-skew",
    }
    assert expected == rule_ids
    assert len(dcp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in dcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = dcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert dcp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "auth-enable: false\n"
        "default_policy = \"allow\"\n"
        "OPEN_ACL_UNSAFE\n"
    )
    findings = dcp.scan_text(src)
    assert len(findings) >= 3
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[dcp.Finding]:
    return [f for f in dcp.scan_text(text) if f.rule_id == rule_id]


# ---------- C1 : consensus-etcd-auth-disabled ----------------------------


def test_c1_etcd_yaml_auth_disabled_flags() -> None:
    """etcd YAML config with `auth-enable: false` → CRITICAL hit."""
    src = (
        "name: 'etcd-node-1'\n"
        "data-dir: '/var/lib/etcd'\n"
        "listen-client-urls: 'http://0.0.0.0:2379'\n"
        "advertise-client-urls: 'http://10.0.1.5:2379'\n"
        "auth-enable: false\n"
        "client-transport-security:\n"
        "  cert-file: ''\n"
        "  key-file: ''\n"
        "  client-cert-auth: false\n"
    )
    hits = _hits("consensus-etcd-auth-disabled", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c1_etcd_systemd_flag_auth_disabled_flags() -> None:
    """systemd ExecStart with `--auth-enable=false` → CRITICAL hit."""
    src = (
        "[Service]\n"
        "ExecStart=/usr/bin/etcd \\\n"
        "  --name=etcd-1 \\\n"
        "  --listen-client-urls=http://0.0.0.0:2379 \\\n"
        "  --auth-enable=false\n"
    )
    assert _hits("consensus-etcd-auth-disabled", src)


def test_c1_loopback_bind_suppresses_finding() -> None:
    """Local-only dev fixture (listen on 127.0.0.1) → suppressed."""
    src = (
        "listen-client-urls: 'http://127.0.0.1:2379'\n"
        "auth-enable: false\n"
    )
    assert not _hits("consensus-etcd-auth-disabled", src)


def test_c1_no_auth_disable_silent() -> None:
    """Auth-enabled config → no hit."""
    src = (
        "auth-enable: true\n"
        "client-cert-auth: true\n"
    )
    assert not _hits("consensus-etcd-auth-disabled", src)


# ---------- C2 : consensus-etcd-role-grant-permissive-prefix -------------


def test_c2_etcdctl_role_grant_empty_prefix_flags() -> None:
    """`etcdctl role grant-permission <r> readwrite --prefix ''` → HIGH."""
    src = (
        "# Bootstrap etcd ACLs (post-cluster-init)\n"
        "etcdctl user add root --new-user-password=hunter2\n"
        "etcdctl auth enable\n"
        "etcdctl role add app-readwrite\n"
        "etcdctl role grant-permission app-readwrite --prefix='' readwrite\n"
    )
    hits = _hits("consensus-etcd-role-grant-permissive-prefix", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c2_etcdctl_role_grant_root_prefix_flags() -> None:
    """`etcdctl role grant-permission <r> readwrite --prefix /` → HIGH."""
    src = (
        "etcdctl role grant-permission web readwrite --prefix=/\n"
    )
    assert _hits("consensus-etcd-role-grant-permissive-prefix", src)


def test_c2_pure_read_grant_not_flagged() -> None:
    """Pure `read` grant on empty prefix → no hit (audit role)."""
    src = (
        "etcdctl role grant-permission audit-role read --prefix=''\n"
    )
    assert not _hits("consensus-etcd-role-grant-permissive-prefix", src)


def test_c2_audit_role_name_suppresses_finding() -> None:
    """`audit` role name on same line suppresses the readwrite grant."""
    src = (
        "etcdctl role grant-permission audit-readwrite "
        "readwrite --prefix=''\n"
    )
    # The line contains the audit token, so the readwrite finding is
    # FP-suppressed.
    assert not _hits("consensus-etcd-role-grant-permissive-prefix", src)


# ---------- C3 : consensus-consul-acl-default-allow ----------------------


def test_c3_consul_hcl_default_allow_flags() -> None:
    """Consul HCL with `default_policy = "allow"` → CRITICAL hit."""
    src = (
        "datacenter = \"dc1\"\n"
        "data_dir = \"/opt/consul\"\n"
        "server = true\n"
        "bootstrap_expect = 3\n"
        "bind_addr = \"10.0.1.5\"\n"
        "acl {\n"
        "  enabled = true\n"
        "  default_policy = \"allow\"\n"
        "  enable_token_persistence = true\n"
        "}\n"
    )
    hits = _hits("consensus-consul-acl-default-allow", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c3_legacy_acl_master_token_literal_flags() -> None:
    """Legacy `acl_master_token = "<uuid>"` plaintext → CRITICAL."""
    src = (
        "bind_addr = \"10.0.1.5\"\n"
        "bootstrap_expect = 3\n"
        "acl_master_token = \"abcdef01-2345-6789-abcd-ef0123456789\"\n"
    )
    assert _hits("consensus-consul-acl-default-allow", src)


def test_c3_single_node_dev_suppresses_finding() -> None:
    """Single-node dev agent (loopback + bootstrap_expect=1) → suppressed."""
    src = (
        "bind_addr = \"127.0.0.1\"\n"
        "bootstrap_expect = 1\n"
        "acl {\n"
        "  default_policy = \"allow\"\n"
        "}\n"
    )
    assert not _hits("consensus-consul-acl-default-allow", src)


def test_c3_default_deny_silent() -> None:
    """`default_policy = "deny"` → no hit."""
    src = (
        "acl {\n"
        "  default_policy = \"deny\"\n"
        "}\n"
    )
    assert not _hits("consensus-consul-acl-default-allow", src)


# ---------- C4 : consensus-zookeeper-world-anyone-acl --------------------


def test_c4_curator_open_acl_unsafe_flags() -> None:
    """Apache Curator `Ids.OPEN_ACL_UNSAFE` → HIGH hit."""
    src = (
        "CuratorFramework client = CuratorFrameworkFactory.newClient(\n"
        "    \"zk-1:2181,zk-2:2181,zk-3:2181\",\n"
        "    new RetryNTimes(5, 1000));\n"
        "client.start();\n"
        "client.create()\n"
        "    .creatingParentsIfNeeded()\n"
        "    .withACL(ZooDefs.Ids.OPEN_ACL_UNSAFE)\n"
        "    .forPath(\"/myapp/leader-election\");\n"
    )
    hits = _hits("consensus-zookeeper-world-anyone-acl", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c4_world_anyone_string_flags() -> None:
    """Raw `world:anyone:cdrwa` ACL string → HIGH hit."""
    src = "acl_provider=world:anyone:cdrwa\n"
    assert _hits("consensus-zookeeper-world-anyone-acl", src)


def test_c4_digest_super_test_default_flags() -> None:
    """ZK default `digest:super:test:` → HIGH hit."""
    src = "authProvider.1=digest:super:test:cdrwa\n"
    assert _hits("consensus-zookeeper-world-anyone-acl", src)


def test_c4_safe_acl_silent() -> None:
    """Properly scoped ACL → no hit."""
    src = (
        "client.create().withACL(specificAcl).forPath(\"/data\");\n"
        "// digest:user:hash:cdrwa with real user\n"
    )
    assert not _hits("consensus-zookeeper-world-anyone-acl", src)


# ---------- C5 : consensus-raft-rpc-no-mtls ------------------------------


def test_c5_etcd_peer_cert_auth_false_flags() -> None:
    """etcd `--peer-client-cert-auth=false` → CRITICAL hit."""
    src = (
        "ExecStart=/usr/bin/etcd \\\n"
        "  --name=etcd-1 \\\n"
        "  --listen-peer-urls=http://0.0.0.0:2380 \\\n"
        "  --peer-client-cert-auth=false\n"
    )
    hits = _hits("consensus-raft-rpc-no-mtls", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_c5_nomad_tls_rpc_false_flags() -> None:
    """Nomad HCL `tls { rpc = false }` → CRITICAL hit."""
    src = (
        "datacenter = \"dc1\"\n"
        "tls { rpc = false verify_server_hostname = false }\n"
    )
    assert _hits("consensus-raft-rpc-no-mtls", src)


def test_c5_raft_newtcptransport_go_flags() -> None:
    """hashicorp/raft `raft.NewTCPTransport(` → CRITICAL hit."""
    src = (
        "package main\n"
        "import \"github.com/hashicorp/raft\"\n"
        "func main() {\n"
        "    transport, _ := raft.NewTCPTransport(addr, nil, 3, 10*time.Second, nil)\n"
        "    _ = transport\n"
        "}\n"
    )
    assert _hits("consensus-raft-rpc-no-mtls", src)


def test_c5_plain_http_peer_url_non_loopback_flags() -> None:
    """Plain HTTP peer URL on non-loopback host → CRITICAL hit."""
    src = (
        "etcd --initial-advertise-peer-urls http://10.0.1.5:2380\n"
    )
    assert _hits("consensus-raft-rpc-no-mtls", src)


def test_c5_safe_raft_config_silent() -> None:
    """mTLS-enabled peer config → no hit."""
    src = (
        "peer-cert-auth: true\n"
        "peer-client-cert-auth: true\n"
        "initial-advertise-peer-urls: https://10.0.1.5:2380\n"
    )
    assert not _hits("consensus-raft-rpc-no-mtls", src)


# ---------- C6 : consensus-redlock-single-instance-or-skew --------------


def test_c6_python_redlock_single_instance_flags() -> None:
    """`Redlock([r])` with one node → HIGH hit."""
    src = (
        "from redlock import Redlock\n"
        "import redis\n"
        "r = redis.Redis(host='redis-primary', port=6379)\n"
        "dlm = Redlock([r], retry_count=3, retry_delay=200)\n"
        "lock = dlm.lock('payment:order-42', 5000)\n"
    )
    hits = _hits("consensus-redlock-single-instance-or-skew", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_c6_drift_factor_zero_flags() -> None:
    """`drift_factor=0` → HIGH hit."""
    src = (
        "from redlock import Redlock\n"
        "import redis\n"
        "dlm = Redlock(\n"
        "    [redis.Redis('a'), redis.Redis('b'), redis.Redis('c')],\n"
        "    drift_factor=0,\n"
        ")\n"
    )
    assert _hits("consensus-redlock-single-instance-or-skew", src)


def test_c6_js_new_redlock_single_instance_flags() -> None:
    """JS `new Redlock([client], ...)` single-element → HIGH hit."""
    src = (
        "const Redlock = require('redlock');\n"
        "const redlock = new Redlock([client], { retryCount: 3 });\n"
    )
    assert _hits("consensus-redlock-single-instance-or-skew", src)


def test_c6_three_node_redlock_silent() -> None:
    """Proper N≥3 Redlock cluster → no hit."""
    src = (
        "from redlock import Redlock\n"
        "import redis\n"
        "dlm = Redlock([redis.Redis('a'), redis.Redis('b'), "
        "redis.Redis('c')], retry_count=3)\n"
    )
    assert not _hits("consensus-redlock-single-instance-or-skew", src)


def test_c6_advisory_marker_suppresses_finding() -> None:
    """Advisory / best-effort marker in file suppresses the finding."""
    src = (
        "# NOT-SAFETY-CRITICAL — advisory lock for cache hint\n"
        "from redlock import Redlock\n"
        "import redis\n"
        "dlm = Redlock([redis.Redis('a')], retry_count=3)\n"
    )
    assert not _hits("consensus-redlock-single-instance-or-skew", src)
