"""Tests for scripts/lib/rng_hygiene_patterns.py.

Two tests per rule (positive + negative / FP-suppression) plus
data-model sanity checks. Mirrors the test layout used in
test_chat_bot_patterns.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import rng_hygiene_patterns as rhp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(rhp.RULES, tuple)
    rule_ids = {r.id for r in rhp.RULES}
    expected = {
        "rng-js-token-from-math-random",
        "rng-js-datenow-plus-math-random",
        "rng-py-mt19937-for-secret",
        "rng-py-predictable-seed",
        "rng-go-math-rand-for-secret",
        "rng-js-crypto-polyfill-fallback",
        "rng-rust-thread-rng-for-secret",
        "rng-multi-uuid-v1-or-weak-v4",
    }
    assert expected == rule_ids
    assert len(rhp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in rhp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = rhp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
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
    assert rhp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[rhp.Finding]:
    return [f for f in rhp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : rng-js-token-from-math-random ---------------------------


def test_r1_session_token_from_math_random_flags() -> None:
    """`const sessionToken = Math.random().toString(36)` → CRITICAL hit."""
    src = "const sessionToken = Math.random().toString(36).slice(2);\n"
    hits = _hits("rng-js-token-from-math-random", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_mock_apikey_in_fixture_does_not_flag() -> None:
    """`mockApiKey: Math.random()` in fixture data must NOT flag."""
    src = "const row = { mockApiKey: Math.random().toString() };\n"
    assert not _hits("rng-js-token-from-math-random", src)


# ---------- R2 : rng-js-datenow-plus-math-random -------------------------


def test_r2_incidentid_template_literal_flags() -> None:
    """`const incidentId = `inc-${Date.now()}-${Math.floor(Math.random()*1000)}`` → HIGH."""
    src = (
        "const incidentId = `inc-${Date.now()}-"
        "${Math.floor(Math.random()*1000)}`;\n"
    )
    hits = _hits("rng-js-datenow-plus-math-random", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_cache_buster_query_param_does_not_flag() -> None:
    """`?v=${Date.now()}-${Math.random()}` in a non-security context must NOT flag."""
    src = (
        "const url = `https://cdn.example.com/asset.js"
        "?v=${Date.now()}-${Math.random()}`;\n"
        "fetch(url).then(r => r.text());\n"
    )
    assert not _hits("rng-js-datenow-plus-math-random", src)


# ---------- R3 : rng-py-mt19937-for-secret -------------------------------


def test_r3_password_from_random_choices_flags() -> None:
    """`password = ''.join(random.choices(...))` → CRITICAL."""
    src = (
        "import random, string\n"
        "password = ''.join(random.choices("
        "string.ascii_letters + string.digits, k=16))\n"
    )
    hits = _hits("rng-py-mt19937-for-secret", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r3_test_file_pytest_does_not_flag() -> None:
    """A pytest test file using `random.choice` for fixtures must NOT flag."""
    src = (
        "import pytest\n"
        "import random\n"
        "@pytest.fixture\n"
        "def sample():\n"
        "    token = random.choice(['a', 'b', 'c'])\n"
        "    return token\n"
    )
    assert not _hits("rng-py-mt19937-for-secret", src)


# ---------- R4 : rng-py-predictable-seed ---------------------------------


def test_r4_constant_int_seed_flags() -> None:
    """`random.seed(42)` → HIGH."""
    src = "import random\nrandom.seed(42)\n"
    hits = _hits("rng-py-predictable-seed", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_np_default_rng_zero_seed_flags() -> None:
    """`np.random.default_rng(0)` → HIGH (defeats PCG64's OS reseed)."""
    src = (
        "import numpy as np\n"
        "rng = np.random.default_rng(0)\n"
    )
    assert _hits("rng-py-predictable-seed", src)


# ---------- R5 : rng-go-math-rand-for-secret -----------------------------


def test_r5_math_rand_with_token_assignment_flags() -> None:
    """`token := byte(rand.Intn(256))` in a file importing math/rand → HIGH."""
    src = (
        "package main\n"
        "import (\n"
        '\t"encoding/hex"\n'
        '\t"math/rand"\n'
        ")\n"
        "func newToken() string {\n"
        "\ttoken := make([]byte, 32)\n"
        "\tfor i := range token { token[i] = byte(rand.Intn(256)) }\n"
        "\treturn hex.EncodeToString(token)\n"
        "}\n"
    )
    hits = _hits("rng-go-math-rand-for-secret", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_no_math_rand_import_no_flag() -> None:
    """A file using `rand.Intn` with NO `math/rand` import (only crypto/rand) must NOT flag."""
    src = (
        "package main\n"
        "import (\n"
        '\t"crypto/rand"\n'
        '\t"encoding/hex"\n'
        ")\n"
        "func newToken() string {\n"
        "\tkey := make([]byte, 32)\n"
        "\t_, _ = rand.Read(key)\n"
        "\treturn hex.EncodeToString(key)\n"
        "}\n"
    )
    assert not _hits("rng-go-math-rand-for-secret", src)


# ---------- R6 : rng-js-crypto-polyfill-fallback -------------------------


def test_r6_if_else_polyfill_fallback_flags() -> None:
    """`if (crypto.getRandomValues) {...} else { ...Math.random()... }` → CRITICAL."""
    src = (
        "function rng(len) {\n"
        "  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {\n"
        "    const a = new Uint8Array(len);\n"
        "    crypto.getRandomValues(a);\n"
        "    return a;\n"
        "  } else {\n"
        "    const a = new Uint8Array(len);\n"
        "    for (let i = 0; i < len; i++) a[i] = "
        "Math.floor(Math.random() * 256);\n"
        "    return a;\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("rng-js-crypto-polyfill-fallback", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r6_throwing_helper_does_not_flag() -> None:
    """Helper that THROWS on missing CSPRNG must NOT flag."""
    src = (
        "function rng(len) {\n"
        "  if (!(typeof crypto !== 'undefined' && "
        "crypto.getRandomValues)) {\n"
        "    throw new Error('No secure RNG available');\n"
        "  }\n"
        "  const a = new Uint8Array(len);\n"
        "  crypto.getRandomValues(a);\n"
        "  return a;\n"
        "}\n"
    )
    assert not _hits("rng-js-crypto-polyfill-fallback", src)


# ---------- R7 : rng-rust-thread-rng-for-secret --------------------------


def test_r7_let_key_from_rand_random_flags() -> None:
    """`let key: [u8; 32] = rand::random();` → MEDIUM."""
    src = (
        "use rand::Rng;\n"
        "fn make_key() {\n"
        "    let key: [u8; 32] = rand::random();\n"
        "    println!(\"{:?}\", key);\n"
        "}\n"
    )
    hits = _hits("rng-rust-thread-rng-for-secret", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r7_game_dice_does_not_flag() -> None:
    """A `let dice = rand::thread_rng().gen_range(1..=6)` is non-security and must NOT flag."""
    src = (
        "use rand::Rng;\n"
        "fn roll() -> u32 {\n"
        "    let dice: u32 = rand::thread_rng().gen_range(1..=6);\n"
        "    dice\n"
        "}\n"
    )
    assert not _hits("rng-rust-thread-rng-for-secret", src)


# ---------- R8 : rng-multi-uuid-v1-or-weak-v4 ----------------------------


def test_r8_uuid_v1_for_session_flags() -> None:
    """`const sessionId = uuid.v1();` → HIGH (timestamp + MAC leak)."""
    src = (
        "const uuid = require('uuid');\n"
        "const sessionId = uuid.v1();\n"
    )
    hits = _hits("rng-multi-uuid-v1-or-weak-v4", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r8_python_random_getrandbits_uuid_flags() -> None:
    """`uuid.UUID(int=random.getrandbits(128))` → HIGH (MT19937-seeded v4)."""
    src = (
        "import uuid, random\n"
        "session_id = uuid.UUID(int=random.getrandbits(128))\n"
    )
    hits = _hits("rng-multi-uuid-v1-or-weak-v4", src)
    assert hits
    assert hits[0].severity == "HIGH"
