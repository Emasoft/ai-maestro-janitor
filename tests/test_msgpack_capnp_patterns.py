"""Tests for scripts/lib/msgpack_capnp_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 catalogue
(9 MessagePack / Cap'n Proto / FlatBuffers / Bencode / Thrift / AMF
deserialization anti-patterns). Each rule has at least two tests:
one positive exercising the canary AND one negative exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import msgpack_capnp_patterns as mcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(mcp.RULES, tuple)
    rule_ids = {r.id for r in mcp.RULES}
    expected = {
        "mpc-msgpack-no-strict-map-key",
        "mpc-msgpack-ext-hook-unvalidated",
        "mpc-msgpack-no-size-limit",
        "mpc-capnp-no-traversal-limit",
        "mpc-flatbuffers-unverified-buffer",
        "mpc-bencode-unbounded-integer",
        "mpc-thrift-no-depth-limit",
        "mpc-amf-pyamf-class-mapping",
        "mpc-thrift-no-max-message-size",
    }
    assert expected == rule_ids
    assert len(mcp.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to ASI-06 and a known severity level."""
    for rule in mcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = mcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mcp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "traversalLimitInWords = 0\n"
        "traversalLimitInWords = UINT64_MAX\n"
    )
    findings = mcp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[mcp.Finding]:
    return [f for f in mcp.scan_text(text) if f.rule_id == rule_id]


# ---------- D1 : mpc-msgpack-no-strict-map-key ---------------------------


def test_d1_msgpack_unpackb_no_strict_map_key_flags() -> None:
    """msgpack.unpackb without strict_map_key=True is MEDIUM."""
    src = "data = msgpack.unpackb(user_bytes, raw=False)\n"
    hits = _hits("mpc-msgpack-no-strict-map-key", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d1_msgpack_unpacker_no_strict_map_key_flags() -> None:
    """msgpack.Unpacker without strict_map_key=True is flagged."""
    src = "unpacker = msgpack.Unpacker(file_like, raw=False)\n"
    assert _hits("mpc-msgpack-no-strict-map-key", src)


def test_d1_msgpack_unpackb_with_strict_map_key_silent() -> None:
    """msgpack.unpackb with strict_map_key=True is safe — no hit."""
    src = "data = msgpack.unpackb(user_bytes, raw=False, strict_map_key=True)\n"
    assert not _hits("mpc-msgpack-no-strict-map-key", src)


def test_d1_msgpack_unpacker_with_strict_map_key_silent() -> None:
    """msgpack.Unpacker with strict_map_key=True is safe — no hit."""
    src = "unpacker = msgpack.Unpacker(file_like, raw=False, strict_map_key=True)\n"
    assert not _hits("mpc-msgpack-no-strict-map-key", src)


# ---------- D2 : mpc-msgpack-ext-hook-unvalidated ------------------------


def test_d2_ext_hook_with_pickle_loads_flags() -> None:
    """ext_hook that delegates to pickle.loads is HIGH."""
    src = (
        "def ext_hook(code, data):\n"
        "    return pickle.loads(data)\n"
        "\n"
        "result = msgpack.unpackb(user_data, ext_hook=ext_hook)\n"
    )
    hits = _hits("mpc-msgpack-ext-hook-unvalidated", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d2_ext_hook_with_eval_flags() -> None:
    """ext_hook that calls eval is flagged."""
    src = (
        "def my_hook(code, data):\n"
        "    return eval(data)\n"
        "\n"
        "r = msgpack.unpackb(payload, ext_hook=my_hook)\n"
    )
    assert _hits("mpc-msgpack-ext-hook-unvalidated", src)


def test_d2_ext_hook_without_risky_delegate_silent() -> None:
    """ext_hook with safe datetime handler — no hit."""
    src = (
        "def ext_hook(code, data):\n"
        "    if code == 1:\n"
        "        return datetime.fromtimestamp(struct.unpack('>d', data)[0])\n"
        "    raise ValueError('unknown')\n"
        "\n"
        "r = msgpack.unpackb(payload, ext_hook=ext_hook)\n"
    )
    assert not _hits("mpc-msgpack-ext-hook-unvalidated", src)


def test_d2_no_ext_hook_argument_silent() -> None:
    """msgpack.unpackb without ext_hook keyword — no D2 hit."""
    src = "data = msgpack.unpackb(user_bytes, raw=False)\n"
    assert not _hits("mpc-msgpack-ext-hook-unvalidated", src)


# ---------- D3 : mpc-msgpack-no-size-limit -------------------------------


def test_d3_msgpack_unpackb_no_size_limits_flags() -> None:
    """msgpack.unpackb with no size limits is MEDIUM."""
    src = "msgpack.unpackb(untrusted_bytes)\n"
    hits = _hits("mpc-msgpack-no-size-limit", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d3_msgpack_unpacker_no_size_limits_flags() -> None:
    """msgpack.Unpacker on a socket without size limits is flagged."""
    src = "unpacker = msgpack.Unpacker(socket_file)\n"
    assert _hits("mpc-msgpack-no-size-limit", src)


def test_d3_msgpack_unpackb_with_max_str_len_silent() -> None:
    """msgpack.unpackb with max_str_len — no D3 hit."""
    src = (
        "msgpack.unpackb(\n"
        "    untrusted_bytes,\n"
        "    max_str_len=1_000_000,\n"
        ")\n"
    )
    assert not _hits("mpc-msgpack-no-size-limit", src)


def test_d3_msgpack_unpackb_with_max_array_len_silent() -> None:
    """msgpack.unpackb with max_array_len — no D3 hit."""
    src = "msgpack.unpackb(data, max_array_len=10000)\n"
    assert not _hits("mpc-msgpack-no-size-limit", src)


# ---------- D4 : mpc-capnp-no-traversal-limit ----------------------------


def test_d4_traversal_limit_zero_flags() -> None:
    """traversalLimitInWords = 0 is HIGH."""
    src = "opts.traversalLimitInWords = 0;\n"
    hits = _hits("mpc-capnp-no-traversal-limit", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d4_traversal_limit_uint64_max_flags() -> None:
    """traversalLimitInWords = UINT64_MAX is flagged."""
    src = "opts.traversalLimitInWords = UINT64_MAX;\n"
    assert _hits("mpc-capnp-no-traversal-limit", src)


def test_d4_traversal_limit_safe_value_silent() -> None:
    """traversalLimitInWords = 1048576 (1 MB) — no hit."""
    src = "opts.traversalLimitInWords = 1048576;\n"
    assert not _hits("mpc-capnp-no-traversal-limit", src)


def test_d4_traversal_limit_variable_silent() -> None:
    """traversalLimitInWords = maxWords (variable) — no hit."""
    src = "opts.traversalLimitInWords = maxWords;\n"
    assert not _hits("mpc-capnp-no-traversal-limit", src)


# ---------- D5 : mpc-flatbuffers-unverified-buffer -----------------------


def test_d5_cpp_get_root_without_verifier_flags() -> None:
    """flatbuffers::GetRoot without Verifier in file is HIGH."""
    src = "auto monster = flatbuffers::GetRoot<Monster>(buf);\n"
    hits = _hits("mpc-flatbuffers-unverified-buffer", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d5_cpp_get_mutable_root_without_verifier_flags() -> None:
    """flatbuffers::GetMutableRoot without Verifier in file is flagged."""
    src = "auto cfg = flatbuffers::GetMutableRoot<Config>(buf);\n"
    assert _hits("mpc-flatbuffers-unverified-buffer", src)


def test_d5_cpp_get_root_with_verifier_silent() -> None:
    """flatbuffers::GetRoot with Verifier present in file — no hit."""
    src = (
        "flatbuffers::Verifier verifier(buf, buf_len);\n"
        "assert(VerifyMonsterBuffer(verifier));\n"
        "auto monster = flatbuffers::GetRoot<Monster>(buf);\n"
    )
    assert not _hits("mpc-flatbuffers-unverified-buffer", src)


def test_d5_python_get_root_as_flags() -> None:
    """Python .GetRootAs on a data variable is flagged (no verifier API)."""
    src = "monster = Monster.GetRootAs(buf, 0)\n"
    assert _hits("mpc-flatbuffers-unverified-buffer", src)


def test_d5_python_get_root_as_on_payload_flags() -> None:
    """Python .GetRootAs on payload variable is flagged."""
    src = "cfg = Config.GetRootAs(payload, 0)\n"
    assert _hits("mpc-flatbuffers-unverified-buffer", src)


# ---------- D6 : mpc-bencode-unbounded-integer ---------------------------


def test_d6_bencode_int_slice_with_import_flags() -> None:
    """int() on a bencode slice in a file with bencode import is MEDIUM."""
    src = (
        "import bencode\n"
        "\n"
        "def decode_int(data, pos):\n"
        "    end = data.index(b'e', pos + 1)\n"
        "    return int(data[pos+1:end]), end + 1\n"
    )
    hits = _hits("mpc-bencode-unbounded-integer", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d6_bencode_int_slice_with_bdecode_import_flags() -> None:
    """int() on a buf slice in a file with bdecode() call is flagged."""
    src = (
        "result = bdecode(raw)\n"
        "\n"
        "def parse_int(buf, pos):\n"
        "    end = buf.index(b'e', pos + 1)\n"
        "    return int(buf[pos+1:end]), end + 1\n"
    )
    assert _hits("mpc-bencode-unbounded-integer", src)


def test_d6_int_slice_without_bencode_import_silent() -> None:
    """int() on a slice in a non-bencode file — no D6 hit."""
    src = (
        "import json\n"
        "\n"
        "def get_offset(data, pos):\n"
        "    return int(data[pos:pos+4])\n"
    )
    assert not _hits("mpc-bencode-unbounded-integer", src)


def test_d6_no_int_slice_with_bencode_import_silent() -> None:
    """bencode import without unchecked int() slice — no D6 hit."""
    src = (
        "import bencode\n"
        "\n"
        "data = bencode.bdecode(raw_bytes)\n"
    )
    assert not _hits("mpc-bencode-unbounded-integer", src)


# ---------- D7 : mpc-thrift-no-depth-limit -------------------------------


def test_d7_python_tbinary_protocol_factory_no_args_flags() -> None:
    """TBinaryProtocolFactory() with no args is MEDIUM."""
    src = (
        "from thrift.protocol import TBinaryProtocol\n"
        "pfactory = TBinaryProtocol.TBinaryProtocolFactory()\n"
    )
    hits = _hits("mpc-thrift-no-depth-limit", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d7_python_tcompact_protocol_factory_no_args_flags() -> None:
    """TCompactProtocolFactory() with no args is flagged."""
    src = (
        "from thrift.protocol import TCompactProtocol\n"
        "pfactory = TCompactProtocol.TCompactProtocolFactory()\n"
    )
    assert _hits("mpc-thrift-no-depth-limit", src)


def test_d7_java_tbinary_protocol_factory_no_args_flags() -> None:
    """Java new TBinaryProtocol.Factory() with no args is flagged."""
    src = (
        "TBinaryProtocol.Factory protoFactory = new TBinaryProtocol.Factory();\n"
    )
    assert _hits("mpc-thrift-no-depth-limit", src)


def test_d7_java_tcompact_protocol_factory_no_args_flags() -> None:
    """Java new TCompactProtocol.Factory() with no args is flagged."""
    src = "TCompactProtocol.Factory pf = new TCompactProtocol.Factory();\n"
    assert _hits("mpc-thrift-no-depth-limit", src)


def test_d7_python_tbinary_factory_with_args_silent() -> None:
    """TBinaryProtocolFactory(config) with an argument — no hit."""
    src = "pfactory = TBinaryProtocol.TBinaryProtocolFactory(config)\n"
    assert not _hits("mpc-thrift-no-depth-limit", src)


# ---------- D8 : mpc-amf-pyamf-class-mapping -----------------------------


def test_d8_pyamf_decode_with_register_class_flags() -> None:
    """pyamf.decode in a file with register_class is HIGH."""
    src = (
        "import pyamf\n"
        "pyamf.register_class(OurModel, 'com.example.OurModel')\n"
        "\n"
        "def handle_request(body):\n"
        "    result = pyamf.decode(body)\n"
        "    return result\n"
    )
    hits = _hits("mpc-amf-pyamf-class-mapping", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d8_pyamf_remoting_decode_with_register_class_flags() -> None:
    """pyamf.remoting.decode in a file with register_class is flagged."""
    src = (
        "import pyamf\n"
        "pyamf.register_class(Item, 'com.example.Item')\n"
        "data = pyamf.remoting.decode(request.body)\n"
    )
    assert _hits("mpc-amf-pyamf-class-mapping", src)


def test_d8_pyamf_decode_without_register_class_silent() -> None:
    """pyamf.decode without register_class in file — no D8 hit."""
    src = (
        "import pyamf\n"
        "data = pyamf.decode(trusted_bytes)\n"
    )
    assert not _hits("mpc-amf-pyamf-class-mapping", src)


def test_d8_register_class_without_decode_silent() -> None:
    """pyamf.register_class without any pyamf.decode call — no D8 hit."""
    src = (
        "import pyamf\n"
        "pyamf.register_class(MyModel, 'com.example.MyModel')\n"
        "# no decode call here\n"
    )
    assert not _hits("mpc-amf-pyamf-class-mapping", src)


# ---------- D9 : mpc-thrift-no-max-message-size --------------------------


def test_d9_python_tframed_transport_single_arg_flags() -> None:
    """TTransport.TFramedTransport(single_arg) is MEDIUM."""
    src = (
        "from thrift.transport import TTransport\n"
        "transport = TTransport.TFramedTransport(raw_transport)\n"
    )
    hits = _hits("mpc-thrift-no-max-message-size", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d9_java_tframed_transport_single_arg_flags() -> None:
    """Java new TFramedTransport(single_arg) is flagged."""
    src = "TFramedTransport transport = new TFramedTransport(raw);\n"
    assert _hits("mpc-thrift-no-max-message-size", src)


def test_d9_java_tframed_transport_with_max_size_silent() -> None:
    """Java new TFramedTransport(raw, 16*1024*1024) — no D9 hit."""
    src = "TFramedTransport transport = new TFramedTransport(raw, 16777216);\n"
    assert not _hits("mpc-thrift-no-max-message-size", src)


def test_d9_python_tframed_transport_two_args_silent() -> None:
    """TTransport.TFramedTransport(raw, max_size) — no D9 hit."""
    src = "transport = TTransport.TFramedTransport(raw_transport, 16777216)\n"
    assert not _hits("mpc-thrift-no-max-message-size", src)
