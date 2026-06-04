"""MessagePack / Cap'n Proto / FlatBuffers / Bencode / Thrift / AMF deserialization patterns.

Wave-33 distillation round 19, angle G.

Catalogue of 9 binary-serialization-format anti-patterns distilled in
`reports/distill-round-19/msgpack-capnp-deserialization.md`. Targets Python,
C++, and Java surfaces that the existing `cross_lang_deserialize_patterns`
module covers only at a higher (Java/Ruby/PHP marshal) level.

What is NOT here (already shipped — DO NOT duplicate):

  * Erlang/Elixir `binary_to_term(Bin)` without `[safe]` —
    `cross_lang_deserialize_patterns.py` rule `cld-erlang-binary-to-term-unsafe`.
  * Hessian `HessianInput.readObject()` —
    `cross_lang_deserialize_patterns.py` rule `cld-hessian-read-object`.
  * Node.js `node-serialize` / `funcster` / `vm2` —
    `js_deserialization_patterns.py`.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * mpc-msgpack-no-strict-map-key             (MEDIUM)
  * mpc-msgpack-ext-hook-unvalidated          (HIGH)
  * mpc-msgpack-no-size-limit                 (MEDIUM)
  * mpc-capnp-no-traversal-limit              (HIGH)
  * mpc-flatbuffers-unverified-buffer         (HIGH)
  * mpc-bencode-unbounded-integer             (MEDIUM)
  * mpc-thrift-no-depth-limit                 (MEDIUM)
  * mpc-amf-pyamf-class-mapping               (HIGH)
  * mpc-thrift-no-max-message-size            (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-06 — Insecure Output / DoS / Memory corruption (hash-collision DoS,
            RCE via deserialization gadget, OOM, stack exhaustion, OOB read)

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
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : mpc-msgpack-no-strict-map-key ---------------------------------


# Match msgpack.unpackb / msgpack.Unpacker calls that lack strict_map_key=True.
# The outer call pattern is intentionally kept simple; the scanner checks for
# the absent guard in a forward window.
_MSGPACK_CALL = _re(
    r"\bmsgpack\.(?:unpackb|Unpacker)\s*\("
)

_MSGPACK_STRICT_MAP_KEY_GUARD = _re(
    r"\bstrict_map_key\s*=\s*True\b"
)


# ---- D2 : mpc-msgpack-ext-hook-unvalidated ------------------------------


# Trigger: ext_hook keyword argument present in a msgpack call.
_MSGPACK_EXT_HOOK_CALL = _re(
    r"\bmsgpack\.(?:unpackb|Unpacker)\s*\([^)]{0,400}ext_hook\s*="
)

# Stage-B: risky delegate inside ext_hook handler body.
_MSGPACK_EXT_HOOK_RISKY_DELEGATE = _re(
    r"\bpickle\.loads\s*\("
    r"|\beval\s*\("
    r"|\bexec\s*\("
    r"\b__import__\s*\("
)


# ---- D3 : mpc-msgpack-no-size-limit -------------------------------------


# Presence of ANY of the size-limit params — used as a guard.
_MSGPACK_SIZE_LIMIT_GUARD = _re(
    r"\bmax_(?:str|bin|array|map|ext)_len\s*="
)


# ---- D4 : mpc-capnp-no-traversal-limit ----------------------------------


# Match C++ assignments that zero out or maximize the traversal limit.
_CAPNP_TRAVERSAL_LIMIT_DISABLED = _re(
    r"\btraversalLimitInWords\s*=\s*(?:0\b|UINT64_MAX\b|0[xX][0-9A-Fa-f]{8,})"
)


# ---- D5 : mpc-flatbuffers-unverified-buffer -----------------------------


# Match C++ GetRoot / GetMutableRoot template calls.
_FLATBUFFERS_GET_ROOT = _re(
    r"\bflatbuffers::(?:GetRoot|GetMutableRoot)\s*<[A-Za-z_:]{1,80}>\s*\("
)

# Stage-B guard: Verifier construction in the same file.
_FLATBUFFERS_VERIFIER_GUARD = _re(
    r"\bflatbuffers::Verifier\b"
)

# Python: GetRootAs calls on potentially attacker-controlled buffer variables.
_FLATBUFFERS_PYTHON_GET_ROOT = _re(
    r"\.GetRootAs\s*\(\s*(?:buf|buffer|data|payload|msg|message|bytes_)[^,)]{0,60}[,)]"
)


# ---- D6 : mpc-bencode-unbounded-integer ---------------------------------


# File-level guard: must import a bencode library.
_BENCODE_IMPORT = _re(
    r"\bimport\s+(?:bencode|bencoder|bencodetools)\b"
    r"|\bfrom\s+(?:bencode|bencoder)\s+import\b"
    r"|\bbdecode\s*\("
)

# Unchecked int() call on a slice — typical bencode integer decoder pattern.
_BENCODE_INT_SLICE = _re(
    r"\bint\s*\(\s*(?:data|buf|token|raw|chunk|payload)\s*\["
)


# ---- D7 : mpc-thrift-no-depth-limit -------------------------------------


# Python: TBinaryProtocolFactory / TCompactProtocolFactory with no arguments.
_THRIFT_PROTOCOL_FACTORY_NO_ARGS = _re(
    r"\bT(?:Binary|Compact)Protocol\.T(?:Binary|Compact)ProtocolFactory\s*\(\s*\)"
)

# Java: new TBinaryProtocol.Factory() or new TCompactProtocol.Factory() with no args.
_THRIFT_JAVA_FACTORY_NO_ARGS = _re(
    r"\bnew\s+T(?:Binary|Compact)Protocol\.Factory\s*\(\s*\)"
)


# ---- D8 : mpc-amf-pyamf-class-mapping -----------------------------------


# File-level guard: pyamf.register_class present.
_PYAMF_REGISTER_CLASS = _re(
    r"\bpyamf\.register_class\s*\("
)

# Call site: pyamf.decode on request body.
_PYAMF_DECODE_CALL = _re(
    r"\bpyamf\.(?:decode|remoting\.decode)\s*\("
)


# ---- D9 : mpc-thrift-no-max-message-size --------------------------------


# Python: TFramedTransport with a single argument (no max frame size).
_THRIFT_FRAMED_TRANSPORT_SINGLE_ARG = _re(
    r"\bTTransport\.TFramedTransport\s*\(\s*\w{1,80}\s*\)"
)

# Java: new TFramedTransport with a single argument.
_THRIFT_JAVA_FRAMED_TRANSPORT_SINGLE_ARG = _re(
    r"\bnew\s+TFramedTransport\s*\(\s*\w{1,80}\s*\)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mpc-msgpack-no-strict-map-key",
        name="msgpack.unpackb / Unpacker called without strict_map_key=True",
        severity="MEDIUM",
        description=(
            "Python `msgpack.unpackb()` or `msgpack.Unpacker()` is called "
            "without `strict_map_key=True`. In msgpack-python < 1.0.4, "
            "the default is `strict_map_key=False`, which allows arbitrary "
            "msgpack objects (dicts, lists, binary blobs) as map keys. An "
            "attacker-controlled payload can pass a map with dict keys, "
            "triggering O(N²) Python dict hashing (hash-collision "
            "amplification) and causing a DoS. With `strict_map_key=True` "
            "only `str` and `bytes` keys are accepted; other types raise "
            "`ValueError` before the object is constructed."
        ),
        pattern=_MSGPACK_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-msgpack-ext-hook-unvalidated",
        name="msgpack ext_hook delegate calls pickle.loads / eval / exec",
        severity="HIGH",
        description=(
            "Python `msgpack.unpackb(data, ext_hook=handler)` where the "
            "handler body delegates to `pickle.loads`, `eval`, or `exec` "
            "without a whitelist of permitted typecodes. MessagePack "
            "Extension Types (typecodes 0–127) allow the serializer "
            "to embed application-level object reconstructors. A crafted "
            "payload can route execution through the `pickle.loads` branch, "
            "achieving RCE via a gadget chain. This is the msgpack "
            "equivalent of Java’s `ObjectInputStream.readObject()`."
        ),
        pattern=_MSGPACK_EXT_HOOK_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-msgpack-no-size-limit",
        name="msgpack.unpackb / Unpacker called without any size-limit parameters",
        severity="MEDIUM",
        description=(
            "`msgpack.unpackb()` or `msgpack.Unpacker()` is called without "
            "`max_str_len`, `max_bin_len`, `max_array_len`, `max_map_len`, "
            "or `max_ext_len`. An attacker-controlled msgpack stream can "
            "encode a map with 2³² entries or a string of several "
            "gigabytes (msgpack length fields are 32-bit unsigned). Without "
            "explicit limits the parser will attempt to allocate all "
            "requested memory before surfacing an error, causing an OOM "
            "DoS."
        ),
        pattern=_MSGPACK_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-capnp-no-traversal-limit",
        name="Cap'n Proto traversalLimitInWords set to 0 or UINT64_MAX",
        severity="HIGH",
        description=(
            "Cap'n Proto C++ code sets `traversalLimitInWords` to `0` or "
            "`UINT64_MAX`, disabling the traversal limit that prevents "
            "amplification attacks. Without a limit, a malformed message "
            "containing cyclic or amplification pointers causes the reader "
            "to traverse O(2^N) nodes before detecting a cycle, resulting "
            "in CPU exhaustion or stack overflow (the amplification attack "
            "documented in capnproto.org/security.html)."
        ),
        pattern=_CAPNP_TRAVERSAL_LIMIT_DISABLED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-flatbuffers-unverified-buffer",
        name="flatbuffers::GetRoot / GetMutableRoot called without prior Verifier",
        severity="HIGH",
        description=(
            "FlatBuffers C++ code calls `flatbuffers::GetRoot<T>(buf)` or "
            "`GetMutableRoot<T>(buf)` without first running "
            "`flatbuffers::Verifier` on the buffer. FlatBuffers uses "
            "offset-based pointer arithmetic inside a raw byte array; "
            "without verification a crafted buffer can encode offsets that "
            "point outside the buffer bounds, causing out-of-bounds reads "
            "(info-leak) or, on mutable root access, out-of-bounds writes "
            "(potential RCE). The `Verifier` validates all offsets, vector "
            "lengths, and string null-terminators before the root object "
            "is accessed."
        ),
        pattern=_FLATBUFFERS_GET_ROOT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-bencode-unbounded-integer",
        name="Bencode integer token parsed without length guard",
        severity="MEDIUM",
        description=(
            "Bencode integer tokens (`i<N>e`) carry no length limit in the "
            "specification. A malformed `.torrent` file or tracker response "
            "can contain a multi-thousand-digit integer token; Python’s "
            "arbitrary-precision `int()` will consume unbounded memory and "
            "CPU when parsing the token. Libraries that call `int(token)` on "
            "the raw slice without a `MAX_INT_DIGITS` check are vulnerable "
            "to DoS via CPU/memory exhaustion."
        ),
        pattern=_BENCODE_INT_SLICE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-thrift-no-depth-limit",
        name="Apache Thrift TBinaryProtocol / TCompactProtocol factory with no depth limit",
        severity="MEDIUM",
        description=(
            "Apache Thrift `TBinaryProtocolFactory()` or "
            "`TCompactProtocolFactory()` (Python) / `new TBinaryProtocol.Factory()` "
            "(Java) constructed without a `TConfiguration` that sets "
            "`maxFieldDepth`. Thrift struct fields can nest other structs to "
            "arbitrary depth; a crafted client message can send a "
            "struct-within-struct chain 10,000 levels deep, consuming stack "
            "space until a `RecursionError` (Python) or "
            "`StackOverflowError` (JVM) crashes the server."
        ),
        pattern=_THRIFT_PROTOCOL_FACTORY_NO_ARGS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-amf-pyamf-class-mapping",
        name="pyamf.decode called when class mappings are registered",
        severity="HIGH",
        description=(
            "`pyamf.decode()` or `pyamf.remoting.decode()` invoked on an "
            "attacker-controlled byte stream in a file that also registers "
            "application classes via `pyamf.register_class()`. AMF typed "
            "objects embed a class-alias string; the deserializer looks up "
            "the alias in the registry and instantiates the corresponding "
            "Python class. If any registered class has side-effecting "
            "`__init__` or `__setattr__` (file I/O, subprocess, network), "
            "an attacker can trigger those effects by sending a crafted "
            "AMF3 typed-object packet — structurally identical to PHP "
            "`unserialize()` with a registered `__wakeup()` gadget."
        ),
        pattern=_PYAMF_DECODE_CALL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mpc-thrift-no-max-message-size",
        name="Thrift TFramedTransport constructed without max-frame-size argument",
        severity="MEDIUM",
        description=(
            "Apache Thrift `TTransport.TFramedTransport(raw_transport)` "
            "(Python) or `new TFramedTransport(raw)` (Java) constructed with "
            "a single argument (no max frame size). The Thrift binary "
            "protocol length-prefixes each message with a 4-byte signed "
            "int32; a client can send `0x7FFFFFFF` (≈2 GB) as the "
            "length prefix. Without a max-size guard the server allocates a "
            "2 GB buffer before reading the body, causing OOM. Python Thrift "
            "does not enforce a default max; Java Thrift added "
            "`TConfiguration.DEFAULT_MAX_MESSAGE_SIZE` (100 MB) only in "
            "0.14."
        ),
        pattern=_THRIFT_FRAMED_TRANSPORT_SINGLE_ARG,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * D1 (msgpack-no-strict-map-key) — anchor on the msgpack call; require
        ABSENCE of `strict_map_key=True` in a 10-line forward window.
      * D2 (msgpack-ext-hook-unvalidated) — anchor on `ext_hook=` in call;
        require presence of `pickle.loads` / `eval` / `exec` anywhere in file.
      * D3 (msgpack-no-size-limit) — anchor on the msgpack call; require
        ABSENCE of any `max_*_len` guard in a 10-line forward window.
      * D4 (capnp-no-traversal-limit) — literal pattern match; always emit.
      * D5 (flatbuffers-unverified-buffer) — anchor on GetRoot; require
        ABSENCE of `flatbuffers::Verifier` anywhere in the file (C++).
        Python GetRootAs calls are always emitted (no verifier API available).
      * D6 (bencode-unbounded-integer) — anchor on `int(slice)` pattern;
        require file-level bencode import marker.
      * D7 (thrift-no-depth-limit) — literal pattern match on no-arg factory;
        always emit. Java variant also emitted from its own pattern.
      * D8 (amf-pyamf-class-mapping) — anchor on `pyamf.decode()`;
        require file-level `pyamf.register_class` marker.
      * D9 (thrift-no-max-message-size) — literal pattern match; always emit.
        Java variant also emitted from its own pattern.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

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

    # ---- D1 : mpc-msgpack-no-strict-map-key ----
    rule_d1 = rule_by_id["mpc-msgpack-no-strict-map-key"]
    for m in _MSGPACK_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 10)
        if _MSGPACK_STRICT_MAP_KEY_GUARD.search(window) is not None:
            continue
        _emit(rule_d1, m.start(), m.group(0))

    # ---- D2 : mpc-msgpack-ext-hook-unvalidated ----
    rule_d2 = rule_by_id["mpc-msgpack-ext-hook-unvalidated"]
    has_risky_delegate = _file_contains(text, _MSGPACK_EXT_HOOK_RISKY_DELEGATE)
    if has_risky_delegate:
        for m in _MSGPACK_EXT_HOOK_CALL.finditer(text):
            _emit(rule_d2, m.start(), m.group(0))

    # ---- D3 : mpc-msgpack-no-size-limit ----
    rule_d3 = rule_by_id["mpc-msgpack-no-size-limit"]
    for m in _MSGPACK_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 10)
        if _MSGPACK_SIZE_LIMIT_GUARD.search(window) is not None:
            continue
        _emit(rule_d3, m.start(), m.group(0))

    # ---- D4 : mpc-capnp-no-traversal-limit ----
    rule_d4 = rule_by_id["mpc-capnp-no-traversal-limit"]
    for m in _CAPNP_TRAVERSAL_LIMIT_DISABLED.finditer(text):
        _emit(rule_d4, m.start(), m.group(0))

    # ---- D5 : mpc-flatbuffers-unverified-buffer ----
    rule_d5 = rule_by_id["mpc-flatbuffers-unverified-buffer"]
    has_verifier = _file_contains(text, _FLATBUFFERS_VERIFIER_GUARD)
    if not has_verifier:
        for m in _FLATBUFFERS_GET_ROOT.finditer(text):
            _emit(rule_d5, m.start(), m.group(0))
    # Python GetRootAs — always flag (no Python verifier API)
    for m in _FLATBUFFERS_PYTHON_GET_ROOT.finditer(text):
        _emit(rule_d5, m.start(), m.group(0))

    # ---- D6 : mpc-bencode-unbounded-integer ----
    rule_d6 = rule_by_id["mpc-bencode-unbounded-integer"]
    has_bencode_import = _file_contains(text, _BENCODE_IMPORT)
    if has_bencode_import:
        for m in _BENCODE_INT_SLICE.finditer(text):
            _emit(rule_d6, m.start(), m.group(0))

    # ---- D7 : mpc-thrift-no-depth-limit (Python + Java) ----
    rule_d7 = rule_by_id["mpc-thrift-no-depth-limit"]
    for m in _THRIFT_PROTOCOL_FACTORY_NO_ARGS.finditer(text):
        _emit(rule_d7, m.start(), m.group(0))
    for m in _THRIFT_JAVA_FACTORY_NO_ARGS.finditer(text):
        _emit(rule_d7, m.start(), m.group(0))

    # ---- D8 : mpc-amf-pyamf-class-mapping ----
    rule_d8 = rule_by_id["mpc-amf-pyamf-class-mapping"]
    has_register_class = _file_contains(text, _PYAMF_REGISTER_CLASS)
    if has_register_class:
        for m in _PYAMF_DECODE_CALL.finditer(text):
            _emit(rule_d8, m.start(), m.group(0))

    # ---- D9 : mpc-thrift-no-max-message-size (Python + Java) ----
    rule_d9 = rule_by_id["mpc-thrift-no-max-message-size"]
    for m in _THRIFT_FRAMED_TRANSPORT_SINGLE_ARG.finditer(text):
        _emit(rule_d9, m.start(), m.group(0))
    for m in _THRIFT_JAVA_FRAMED_TRANSPORT_SINGLE_ARG.finditer(text):
        _emit(rule_d9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
