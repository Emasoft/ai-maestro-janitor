"""Tests for scripts/lib/grpc_reflection_exposure_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 gRPC reflection
and health-check exposure catalogue (10 rules). Each rule has at least
two tests: one positive exercising the canary pattern AND one negative
exercising the suppression logic or a clearly non-matching snippet.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import grpc_reflection_exposure_patterns as grp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_ten_rules() -> None:
    """RULES must expose all 10 documented rule IDs."""
    assert isinstance(grp.RULES, tuple)
    rule_ids = {r.id for r in grp.RULES}
    expected = {
        "grpc-refl-py-health-service-no-auth",
        "grpc-refl-go-health-service-no-auth",
        "grpc-refl-java-insecure-channel-credentials",
        "grpc-refl-java-managed-channel-plaintext",
        "grpc-refl-node-create-insecure-credentials",
        "grpc-refl-envoy-yaml-reflection-filter",
        "grpc-refl-spring-grpc-web-filter",
        "grpc-refl-py-streaming-no-deadline",
        "grpc-refl-client-proto-reflection-db",
        "grpc-refl-client-go-reflection-stub",
    }
    assert expected == rule_ids
    assert len(grp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must map to a valid ASI- prefix and a known severity tier."""
    for rule in grp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror webhook_signature_patterns.Finding field layout."""
    f = grp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert grp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """scan_text output must be sorted by (line, column, rule_id)."""
    src = (
        "grpc_health_v1.RegisterHealthServer(s, hs)\n"
        "add_HealthServicer_to_server(health_servicer, server)\n"
    )
    results = grp.scan_text(src)
    lines = [f.line for f in results]
    assert lines == sorted(lines)


# ---------- R1 : grpc-refl-py-health-service-no-auth --------------------


def test_r1_py_health_servicer_register_detected() -> None:
    """add_HealthServicer_to_server( must trigger grpc-refl-py-health-service-no-auth."""
    src = (
        "from grpc_health.v1 import health_pb2_grpc, health\n"
        "health_servicer = health.HealthServicer()\n"
        "health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)\n"
        'server.add_insecure_port("[::]:50051")\n'
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-health-service-no-auth" in ids


def test_r1_py_health_servicer_no_false_positive_on_unrelated_add_call() -> None:
    """add_SomeOtherServicer_to_server must NOT trigger the Python health rule."""
    src = (
        "from myapp import pb2_grpc\n"
        "pb2_grpc.add_MyServiceServicer_to_server(servicer, server)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-health-service-no-auth" not in ids


# ---------- R2 : grpc-refl-go-health-service-no-auth --------------------


def test_r2_go_health_register_server_detected() -> None:
    """grpc_health_v1.RegisterHealthServer( must trigger grpc-refl-go-health-service-no-auth."""
    src = (
        'import "google.golang.org/grpc/health/grpc_health_v1"\n'
        "hs := health.NewServer()\n"
        "grpc_health_v1.RegisterHealthServer(s, hs)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-go-health-service-no-auth" in ids


def test_r2_go_health_no_false_positive_on_plain_register_call() -> None:
    """grpc_health_v1.SomethingElse( must NOT trigger the Go health rule."""
    src = (
        "grpc_health_v1.HealthCheckResponse_SERVING\n"
        "grpc_health_v1.NewServer()\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-go-health-service-no-auth" not in ids


# ---------- R3 : grpc-refl-java-insecure-channel-credentials ------------


def test_r3_java_insecure_channel_credentials_detected() -> None:
    """InsecureChannelCredentials.create() must trigger grpc-refl-java-insecure-channel-credentials."""
    src = (
        "import io.grpc.InsecureChannelCredentials;\n"
        "import io.grpc.Grpc;\n"
        "ManagedChannel channel = Grpc.newChannelBuilder(\n"
        '    "api.internal.example.com:443",\n'
        "    InsecureChannelCredentials.create()\n"
        ").build();\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-java-insecure-channel-credentials" in ids


def test_r3_java_insecure_channel_credentials_no_fp_on_different_factory() -> None:
    """TlsChannelCredentials.create() must NOT trigger the Java insecure credentials rule."""
    src = (
        "import io.grpc.TlsChannelCredentials;\n"
        "ManagedChannel channel = Grpc.newChannelBuilder(\n"
        '    "api.example.com:443",\n'
        "    TlsChannelCredentials.create()\n"
        ").build();\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-java-insecure-channel-credentials" not in ids


# ---------- R4 : grpc-refl-java-managed-channel-plaintext ---------------


def test_r4_java_managed_channel_plaintext_detected() -> None:
    """ManagedChannelBuilder...usePlaintext() must trigger grpc-refl-java-managed-channel-plaintext."""
    src = (
        "ManagedChannel channel = ManagedChannelBuilder\n"
        '    .forAddress("api.internal.example.com", 443)\n'
        "    .usePlaintext()\n"
        "    .build();\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-java-managed-channel-plaintext" in ids


def test_r4_java_managed_channel_plaintext_no_fp_on_use_tls() -> None:
    """ManagedChannelBuilder...useTransportSecurity() must NOT trigger the plaintext rule."""
    src = (
        "ManagedChannel channel = ManagedChannelBuilder\n"
        '    .forAddress("api.example.com", 443)\n'
        "    .useTransportSecurity()\n"
        "    .build();\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-java-managed-channel-plaintext" not in ids


# ---------- R5 : grpc-refl-node-create-insecure-credentials -------------


def test_r5_node_create_insecure_credentials_detected() -> None:
    """grpc.credentials.createInsecure() must trigger grpc-refl-node-create-insecure-credentials."""
    src = (
        "const grpc = require('@grpc/grpc-js');\n"
        "const client = new MyServiceClient(\n"
        "    'api.prod.example.com:50051',\n"
        "    grpc.credentials.createInsecure()\n"
        ");\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-node-create-insecure-credentials" in ids


def test_r5_node_create_insecure_no_fp_on_create_ssl() -> None:
    """grpc.credentials.createSsl() must NOT trigger the Node insecure credentials rule."""
    src = (
        "const grpc = require('@grpc/grpc-js');\n"
        "const client = new MyServiceClient(\n"
        "    'api.prod.example.com:50051',\n"
        "    grpc.credentials.createSsl()\n"
        ");\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-node-create-insecure-credentials" not in ids


# ---------- R6 : grpc-refl-envoy-yaml-reflection-filter -----------------


def test_r6_envoy_yaml_reflection_filter_detected() -> None:
    """envoy.filters.http.grpc_server_reflection must trigger grpc-refl-envoy-yaml-reflection-filter."""
    src = (
        "http_filters:\n"
        "  - name: envoy.filters.http.grpc_server_reflection\n"
        "    typed_config: {}\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-envoy-yaml-reflection-filter" in ids


def test_r6_envoy_yaml_no_fp_on_router_filter() -> None:
    """envoy.filters.http.router must NOT trigger the Envoy reflection rule."""
    src = (
        "http_filters:\n"
        "  - name: envoy.filters.http.router\n"
        "    typed_config:\n"
        '      "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router\n'
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-envoy-yaml-reflection-filter" not in ids


# ---------- R7 : grpc-refl-spring-grpc-web-filter -----------------------


def test_r7_spring_grpc_web_filter_detected() -> None:
    """new GrpcWebFilter() must trigger grpc-refl-spring-grpc-web-filter."""
    src = (
        "@Bean\n"
        "public GrpcWebFilter grpcWebFilter() {\n"
        "    return new GrpcWebFilter();\n"
        "}\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-spring-grpc-web-filter" in ids


def test_r7_spring_grpc_web_filter_no_fp_on_other_filter() -> None:
    """new CorsWebFilter() must NOT trigger the Spring gRPC-Web filter rule."""
    src = (
        "@Bean\n"
        "public CorsWebFilter corsWebFilter() {\n"
        "    return new CorsWebFilter(source);\n"
        "}\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-spring-grpc-web-filter" not in ids


# ---------- R8 : grpc-refl-py-streaming-no-deadline ---------------------


def test_r8_py_streaming_no_deadline_detected() -> None:
    """Streaming servicer with yield but no context check must trigger grpc-refl-py-streaming-no-deadline."""
    src = (
        "class MyServiceServicer(my_pb2_grpc.MyServiceServicer):\n"
        "    def StreamData(self, request, context):\n"
        "        for item in large_dataset_generator(request.query):\n"
        "            yield my_pb2.DataResponse(item=item)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-streaming-no-deadline" in ids


def test_r8_py_streaming_with_deadline_check_suppressed() -> None:
    """Streaming servicer that checks context.is_active() must NOT trigger grpc-refl-py-streaming-no-deadline."""
    src = (
        "class MyServiceServicer(my_pb2_grpc.MyServiceServicer):\n"
        "    def StreamData(self, request, context):\n"
        "        for item in large_dataset_generator(request.query):\n"
        "            if not context.is_active():\n"
        "                return\n"
        "            yield my_pb2.DataResponse(item=item)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-streaming-no-deadline" not in ids


def test_r8_py_streaming_time_remaining_check_suppressed() -> None:
    """Streaming servicer that checks context.time_remaining() must NOT trigger the deadline rule."""
    src = (
        "class DataServiceServicer(data_pb2_grpc.DataServiceServicer):\n"
        "    def FetchStream(self, request, context):\n"
        "        for row in db.stream(request.query):\n"
        "            if context.time_remaining() <= 0:\n"
        "                break\n"
        "            yield data_pb2.Row(data=row)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-streaming-no-deadline" not in ids


def test_r8_py_non_streaming_servicer_not_flagged() -> None:
    """Unary servicer (no yield) must NOT trigger the streaming deadline rule."""
    src = (
        "class MyServiceServicer(my_pb2_grpc.MyServiceServicer):\n"
        "    def GetData(self, request, context):\n"
        "        return my_pb2.DataResponse(item=request.query)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-streaming-no-deadline" not in ids


# ---------- R9 : grpc-refl-client-proto-reflection-db -------------------


def test_r9_proto_reflection_descriptor_db_detected() -> None:
    """ProtoReflectionDescriptorDatabase( must trigger grpc-refl-client-proto-reflection-db."""
    src = (
        "from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (\n"
        "    ProtoReflectionDescriptorDatabase,\n"
        ")\n"
        'channel = grpc.insecure_channel("internal-service:50051")\n'
        "desc_db = ProtoReflectionDescriptorDatabase(channel)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-client-proto-reflection-db" in ids


def test_r9_proto_reflection_no_fp_on_descriptor_pool_only() -> None:
    """descriptor_pool.DescriptorPool without ProtoReflectionDescriptorDatabase must NOT trigger."""
    src = (
        "from google.protobuf import descriptor_pool\n"
        "pool = descriptor_pool.DescriptorPool()\n"
        "service_desc = pool.FindServiceByName('myapp.v1.MyService')\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-client-proto-reflection-db" not in ids


# ---------- R10 : grpc-refl-client-go-reflection-stub -------------------


def test_r10_go_reflection_client_stub_detected() -> None:
    """grpc_reflection_v1alpha.NewServerReflectionClient( must trigger grpc-refl-client-go-reflection-stub."""
    src = (
        'import "google.golang.org/grpc/reflection/grpc_reflection_v1alpha"\n'
        "\n"
        "stub := grpc_reflection_v1alpha.NewServerReflectionClient(conn)\n"
        "stream, _ := stub.ServerReflectionInfo(ctx)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-client-go-reflection-stub" in ids


def test_r10_go_reflection_no_fp_on_server_side_registration() -> None:
    """reflection.Register(s) (server side) must NOT trigger the Go reflection client rule."""
    src = (
        'import "google.golang.org/grpc/reflection"\n'
        "\n"
        "// Register reflection service on gRPC server.\n"
        "reflection.Register(s)\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-client-go-reflection-stub" not in ids


# ---------- Integration / multi-rule scenarios ---------------------------


def test_multiple_rules_fire_on_combined_snippet() -> None:
    """A file with both Python health registration and Node insecure credentials triggers both rules."""
    src = (
        "# server.py\n"
        "health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)\n"
        "# client.js\n"
        "const client = new MyClient('host:50051', grpc.credentials.createInsecure());\n"
    )
    findings = grp.scan_text(src)
    ids = {f.rule_id for f in findings}
    assert "grpc-refl-py-health-service-no-auth" in ids
    assert "grpc-refl-node-create-insecure-credentials" in ids


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text must return a list of Finding namedtuples on a hit."""
    src = "grpc_health_v1.RegisterHealthServer(s, hs)\n"
    results = grp.scan_text(src)
    assert isinstance(results, list)
    assert len(results) >= 1
    f = results[0]
    assert isinstance(f, grp.Finding)
    assert f.severity == "HIGH"
    assert f.owasp_asi.startswith("ASI-")


def test_deduplication_prevents_duplicate_findings() -> None:
    """The same pattern at the exact same (rule_id, line, col) must only appear once."""
    # A single occurrence on a single line — must produce exactly one finding.
    src = "add_HealthServicer_to_server(health_servicer, server)\n"
    findings = grp.scan_text(src)
    rule_findings = [f for f in findings if f.rule_id == "grpc-refl-py-health-service-no-auth"]
    # Exactly one finding for one match at one position.
    assert len(rule_findings) == 1
    # Re-running on the same text must yield the same count (idempotent).
    findings2 = grp.scan_text(src)
    rule_findings2 = [f for f in findings2 if f.rule_id == "grpc-refl-py-health-service-no-auth"]
    assert len(rule_findings2) == 1
