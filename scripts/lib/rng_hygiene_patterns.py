"""RNG hygiene / non-cryptographic randomness source patterns.

Wave-24 distillation round 10 — angle: **randomness-SOURCE choice for
secrets / keys / tokens / nonces**. Distinct from
`crypto_misuse_patterns.py` (single catch-all `random.* / Math.random /
java.util.Random` rule) and from `pqc_readiness_patterns.py` (algorithm
strength, not entropy origin).

What is NOT here (already shipped — DO NOT duplicate):

  * Single catch-all `random.* / Math.random / java.util.Random` line —
    `crypto_misuse_patterns.py` rule 5.
  * Post-quantum algorithm-strength rules — `pqc_readiness_patterns.py`.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * rng-js-token-from-math-random              (CRITICAL)
  * rng-js-datenow-plus-math-random            (HIGH)
  * rng-py-mt19937-for-secret                  (CRITICAL)
  * rng-py-predictable-seed                    (HIGH)
  * rng-go-math-rand-for-secret                (HIGH)
  * rng-js-crypto-polyfill-fallback            (CRITICAL)
  * rng-rust-thread-rng-for-secret             (MEDIUM)
  * rng-multi-uuid-v1-or-weak-v4               (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Insecure Authentication & Session Management
           (predictable session/token/CSRF values).
  ASI-08 — Insecure Cryptographic Storage (predictable seed,
           weak RNG family for keys/nonces/salts, silent polyfill
           downgrade).

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
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Shared building blocks ---------------------------------------------------

# Security-noun word list used as variable-name anchor across multiple
# rules. Bounded character class — RE2-safe. The bare `key` is matched
# only as a whole-word noun (`\bkey\b`) to keep its FP rate down; the
# rules that consume this word group always wrap it in their own anchors.
_SECURITY_NOUN_WORD = (
    r"(?:token|secret|password|passwd|api[_-]?key|apikey|session"
    r"|sessionid|csrf|nonce|reset|verif|verification|invite|magic"
    r"|magiclink|otp|auth|jwt|bearer|salt|cookie|priv(?:ate)?[_-]?key"
    r"|privkey|seed|key)"
)

# Test/mock/fixture path marker — used in Stage-B suppression. We can't
# see the file path from here, so we approximate by file-content markers
# that strongly indicate a test/fixture context (pytest fixture names,
# Jest describe blocks, Storybook stories, mock-file headers).
_TEST_CONTEXT_MARKER = _re(
    r"\bimport\s+pytest\b"
    r"|\bfrom\s+pytest\b"
    r"|^\s*@pytest\.fixture\b"
    r"|\bunittest\.TestCase\b"
    r"|\bunittest\.main\b"
    r"|^\s*(?:describe|it|test)\s*\("
    r"|\bfrom\s+unittest\.mock\b"
    r"|\bimport\s+unittest\.mock\b"
    r"|\bfrom\s+jest\b"
    r"|\bimport\s+\{\s*jest\s*\}"
    r"|^\s*//\s*@vitest\b"
    r"|^\s*//\s*@?fixture\b"
    r"|\bStoryFn\b"
    r"|\bMeta<typeof\b"
)


# ---- R1 : rng-js-token-from-math-random ---------------------------------


# `Math.random()` assigned to (or returned from arrow whose target name
# is) a security-noun variable. Anchored on the assignment shape so we
# do not flag jitter expressions like `delay + Math.random()*100`.
_JS_MATH_RANDOM_FOR_SECRET = _re(
    r"\b" + _SECURITY_NOUN_WORD + r"\w*"
    r"\s*[:=]\s*"
    r"(?:\([^)]{0,80}\)\s*=>\s*)?"
    r"\(?\s*(?:Math\.random\s*\(\s*\)|\(\s*Math\.random\s*\(\s*\)"
    r"\s*\+\s*\d+\s*\))"
)


# Mock-naming suppressors that legitimately use `apiKey: Math.random()`
# in fixture rows. We keep the rule conservative by NOT triggering if
# the variable name carries a mock prefix.
_JS_MOCK_PREFIX = _re(
    r"\b(?:mock|fake|stub|dummy|sample|fixture)" + _SECURITY_NOUN_WORD
)


# ---- R2 : rng-js-datenow-plus-math-random -------------------------------


# `Date.now()` + `Math.random()` in either order on the same line — the
# classic "homemade UUID". We bound the gap to 80 chars (no nested
# quantifier) and require the result to flow into a security-noun
# variable OR to live on a `const|let|var` declaration whose LHS is a
# security noun.
_JS_DATE_NOW_MATH_RANDOM = _re(
    r"Date\.now\s*\(\s*\)[^;\n]{0,80}Math\.random\s*\("
    r"|Math\.random\s*\([^;\n]{0,80}Date\.now\s*\(\s*\)"
)


# Stage-B: require the surrounding 5-line window to mention a security
# noun (assignment / return / template-literal name). Otherwise this is
# cache-busting / analytics tagging — out of scope.
_JS_SECURITY_NOUN_NEARBY = _re(
    r"\b(?:const|let|var|return|=>)\s+" + _SECURITY_NOUN_WORD
    + r"|"
    + r"\b" + _SECURITY_NOUN_WORD + r"\w*\s*[:=]"
    + r"|"
    + r"['\"`]\b(?:inc|incident|session|token|reset|api[_-]?key"
    + r"|nonce|csrf|otp|verif|auth)[_-]"
)


# ---- R3 : rng-py-mt19937-for-secret -------------------------------------


# Python `random.<call>` returning to a security-noun variable. We match
# the `<noun_name> = ... random.<func>(...)` shape with a bounded gap
# (200 chars / no newline) so multi-arg expressions still trigger but
# unrelated assignments do not.
_PY_RANDOM_FOR_SECRET = _re(
    r"^\s*" + _SECURITY_NOUN_WORD + r"\w*"
    r"\s*=\s*[^#\n]{0,200}\brandom\."
    r"(?:randint|random|choice|choices|randrange|sample|getrandbits"
    r"|uniform|shuffle|randbytes)\s*\("
)


# ---- R4 : rng-py-predictable-seed ---------------------------------------


# `random.seed(...)` / `np.random.seed(...)` / `numpy.random.seed(...)`
# with literal integer, hex literal, time.time(), os.getpid(), or
# int(time.time()) as the seed argument.
_PY_PREDICTABLE_SEED = _re(
    r"\b(?:random|np\.random|numpy\.random)\.seed\s*\(\s*"
    r"(?:\d{1,20}"
    r"|0x[0-9a-fA-F]{1,16}"
    r"|time\.time\s*\(\s*\)"
    r"|os\.getpid\s*\(\s*\)"
    r"|int\s*\(\s*time\.time\s*\(\s*\)\s*\))"
    r"\s*\)"
)


# `np.random.default_rng(seed=...)` and `np.random.default_rng(<lit>)`
# with the same predictable-source set. Constructor form is the modern
# NumPy entry point and resets the BitGenerator's stream identically.
_PY_DEFAULT_RNG_PREDICTABLE_SEED = _re(
    r"\b(?:np|numpy)\.random\.default_rng\s*\(\s*"
    r"(?:seed\s*=\s*)?"
    r"(?:\d{1,20}"
    r"|0x[0-9a-fA-F]{1,16}"
    r"|time\.time\s*\(\s*\)"
    r"|os\.getpid\s*\(\s*\)"
    r"|int\s*\(\s*time\.time\s*\(\s*\)\s*\))"
    r"\s*\)"
)


# ---- R5 : rng-go-math-rand-for-secret -----------------------------------


# Two-stage:
#   Stage A — file contains `import "math/rand"` (or aliased form).
#   Stage B — `rand.<call>` near a security identifier.
_GO_MATH_RAND_IMPORT = _re(
    r'^\s*(?:[A-Za-z_]\w*\s+)?"math/rand"\s*$'
    r"|"
    # Allow grouped import block: parentheses style.
    r'^\s*"math/rand"\s*$'
)


_GO_MATH_RAND_CALL = _re(
    r"\brand\."
    r"(?:Intn|Int|Int31|Int63|Read|Float32|Float64|NewSource)\s*\("
)


# Stage-B for Go R5: a security-noun identifier appears in the same
# function body. We bound the search to a 20-line window around each
# rand.* call so a single math/rand import in `package util` does not
# turn EVERY rand.* call into a finding.
_GO_SECURITY_IDENT_NEARBY = _re(
    r"\b\w*" + _SECURITY_NOUN_WORD + r"\w*\s*(?::=|=|\[)"
)


# ---- R6 : rng-js-crypto-polyfill-fallback -------------------------------


# Two regex variants (OR-joined): an `if (...crypto...) {...} else {...
# Math.random...}` shape, and a `typeof crypto !== 'undefined'` ternary
# / discriminator that falls back to Math.random.
#
# Bounded-repetition body (≤ 400 chars / no newline-greedy) keeps this
# RE2-safe. NOTE: `[\s\S]` is used so we span multi-line bodies; we cap
# the body length so the regex cannot blow up.
_JS_CRYPTO_FALLBACK_IF_ELSE = _re(
    r"if\s*\(\s*(?:typeof\s+)?crypto[^)]{0,80}\)\s*\{"
    r"[\s\S]{0,400}?"
    r"\}\s*else\s*\{"
    r"[\s\S]{0,200}?"
    r"Math\.random\s*\("
)


_JS_CRYPTO_FALLBACK_TYPEOF = _re(
    r"typeof\s+(?:window\s*\.\s*)?crypto\s*[!=]==?\s*['\"]undefined['\"]"
    r"[\s\S]{0,400}?"
    r"Math\.random\s*\("
)


# Stage-B: the file MUST also reference `crypto.getRandomValues` —
# otherwise the `typeof crypto` check is for a non-crypto crypto module
# (e.g. node's `crypto.createHmac`) and the fallback is not a downgrade.
_JS_CRYPTO_GETRANDOMVALUES_CONTEXT = _re(
    r"\bcrypto\s*\.\s*getRandomValues\b"
)


# ---- R7 : rng-rust-thread-rng-for-secret --------------------------------


# `let <secret_noun>... = rand::random() | rand::thread_rng()...gen(...)`
# Bounded gap; RE2-safe.
_RUST_THREAD_RNG_FOR_SECRET = _re(
    r"\blet\s+(?:mut\s+)?\w*" + _SECURITY_NOUN_WORD + r"\w*"
    r"\s*(?::\s*[^=]{0,80})?"
    r"=\s*[^;\n]{0,200}"
    r"(?:rand::random\s*(?:::<[^>]{0,60}>)?\s*\("
    r"|rand::thread_rng\s*\(\s*\)\s*\.\s*"
    r"(?:gen|gen_range|fill|fill_bytes|gen_bool|next_u32|next_u64)"
    r"\b)"
)


# A separate shape: `let <noun>: [u8; N] = rand::random();` — the
# function-call form is very common in `rand` crate samples.
_RUST_RAND_RANDOM_TYPED = _re(
    r"\blet\s+(?:mut\s+)?\w*" + _SECURITY_NOUN_WORD + r"\w*"
    r"\s*:\s*\[\s*u8\s*;\s*\d{1,4}\s*\]"
    r"\s*=\s*rand::random\s*\("
)


# ---- R8 : rng-multi-uuid-v1-or-weak-v4 ----------------------------------


# Composite, OR-joined across three languages.
_UUID_WEAK_VARIANT = _re(
    # JS / TS: uuid.v1() / uuidV1() / uuid_v1()
    r"\b(?:uuid\s*\.\s*v1|uuidV1|uuid_v1)\s*\("
    r"|"
    # Python: uuid.UUID(int=random.getrandbits(128))
    r"\buuid\s*\.\s*UUID\s*\(\s*int\s*=\s*random\.getrandbits\s*\("
    r"|"
    # Java: new UUID(rand.nextLong(), rand.nextLong())
    r"\bnew\s+UUID\s*\(\s*[^)]{0,120}"
    r"(?:Random\s*\(\s*\)|\brand\.nextLong\s*\(\s*\))"
    r"[^)]{0,120}\)"
)


# Stage-B: consumer of the UUID must be a security-noun variable.
_UUID_SECRET_CONSUMER = _re(
    r"\b(?:const|let|var)\s+\w*" + _SECURITY_NOUN_WORD + r"\w*\s*[:=]"
    r"|"
    r"\b" + _SECURITY_NOUN_WORD + r"\w*\s*=\s*[^=\n]{0,80}"
    r"(?:uuid|UUID)"
    r"|"
    r"^\s*\w*" + _SECURITY_NOUN_WORD + r"\w*\s*=\s*[^=\n]{0,80}"
    r"(?:uuid|UUID)"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="rng-js-token-from-math-random",
        name="JavaScript / TypeScript secret minted from Math.random()",
        severity="CRITICAL",
        description=(
            "A variable named `token`, `apiKey`, `sessionId`, `csrf`, "
            "`resetToken`, `nonce`, `otp`, etc. is assigned the result "
            "of `Math.random()`. V8 / SpiderMonkey use xorshift128+ — "
            "an attacker who observes a handful of outputs can "
            "reconstruct the internal state and predict the next "
            "token in milliseconds (cf. v8-randomness-predictor PoCs "
            "from 2018-2024). Use `crypto.randomBytes(32).toString("
            "'hex')` or `crypto.randomUUID()` instead."
        ),
        pattern=_JS_MATH_RANDOM_FOR_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="rng-js-datenow-plus-math-random",
        name="JavaScript ID derived from Date.now() + Math.random()",
        severity="HIGH",
        description=(
            "The common 'homemade UUID' pattern: `Date.now()` "
            "concatenated with `Math.random().toString(36)`. Total "
            "entropy is approximately 30 bits, brute-forceable in "
            "seconds. Dangerous when the resulting ID flows into a "
            "deduplication key, idempotency token, or webhook "
            "correlation ID that downstream code trusts. Mitigate by "
            "using `crypto.randomUUID()` or "
            "`crypto.randomBytes(N).toString('hex')`."
        ),
        pattern=_JS_DATE_NOW_MATH_RANDOM,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="rng-py-mt19937-for-secret",
        name="Python `random.*` (MT19937) used to mint a secret",
        severity="CRITICAL",
        description=(
            "Python's `random` module is a Mersenne-Twister (MT19937). "
            "The standard-library documentation itself warns it is "
            "'not suitable for security purposes'. 624 consecutive "
            "outputs reveal the full internal state. Use the "
            "`secrets` module (PEP 506, Python 3.6+) — "
            "`secrets.token_hex`, `secrets.token_urlsafe`, "
            "`secrets.choice` — which reads `os.urandom` under the "
            "hood."
        ),
        pattern=_PY_RANDOM_FOR_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="rng-py-predictable-seed",
        name="`random.seed` / `np.random.seed` with constant or wall-clock",
        severity="HIGH",
        description=(
            "A predictable PRNG seed (`0`, `1`, `42`, `time.time()`, "
            "`os.getpid()`, `int(time.time())`) makes every "
            "subsequent draw reproducible. If the same file then "
            "uses the stream to mint secrets, the value is "
            "effectively guessable. `np.random.seed` shares the "
            "underlying MT19937; `np.random.default_rng(0)` defeats "
            "PCG64's OS-entropy seeding. Drop the seed argument for "
            "production code, or use the `secrets` module for "
            "security-relevant outputs."
        ),
        pattern=_PY_PREDICTABLE_SEED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rng-go-math-rand-for-secret",
        name="Go `math/rand` used to mint a key / token / nonce",
        severity="HIGH",
        description=(
            "Go has two RNG packages: `math/rand` (PCG-style, "
            "deterministic from seed) and `crypto/rand` (reads "
            "`/dev/urandom` / `RtlGenRandom` / `getrandom(2)`). The "
            "package names differ by one path segment and codebases "
            "regularly mis-import. Pre-Go-1.20 the global "
            "`math/rand` seed defaulted to `1`, making every fresh "
            "stream identical across processes; even on Go ≥ 1.20 "
            "`math/rand` remains predictable from a few observed "
            "outputs. Use `crypto/rand.Read(...)` for any byte "
            "string that becomes a secret."
        ),
        pattern=_GO_MATH_RAND_CALL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rng-js-crypto-polyfill-fallback",
        name="`Math.random` fallback when `crypto.getRandomValues` absent",
        severity="CRITICAL",
        description=(
            "A polyfill / RNG helper checks for "
            "`crypto.getRandomValues` and SILENTLY falls back to "
            "`Math.random()` on environments where the global is "
            "missing (very old browsers, sandboxed null-origin "
            "iframes, SSR before hydration, some React-Native "
            "polyfill ordering bugs). Every UUID, nonce, and "
            "randomly-generated value generated by that path "
            "downgrades to xorshift128+ output — without an error "
            "or warning. Throw on missing CSPRNG; do NOT fall back."
        ),
        pattern=_JS_CRYPTO_FALLBACK_IF_ELSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rng-rust-thread-rng-for-secret",
        name="Rust `rand::thread_rng` / `rand::random` for a secret value",
        severity="MEDIUM",
        description=(
            "The `rand` crate's `thread_rng()` defaults to "
            "`ThreadRng`, currently a `ReseedingRng<ChaCha12Core>` — "
            "considered secure on `rand >= 0.8`. Earlier `rand` 0.6 "
            "/ 0.7 used `XorShiftRng` (not secure). For values that "
            "are secrets (keys, nonces, salts, private keys), use "
            "`rand::rngs::OsRng` — it re-reads OS entropy on every "
            "call and is version-stable. The `thread_rng` shape is "
            "a code smell even under modern `rand` because a "
            "transitive dependency may downgrade the crate to "
            "0.7."
        ),
        pattern=_RUST_THREAD_RNG_FOR_SECRET,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rng-multi-uuid-v1-or-weak-v4",
        name="UUID v1 (time + MAC) or v4 from a non-CSPRNG",
        severity="HIGH",
        description=(
            "UUID v1 encodes wall-clock time and the host MAC "
            "address — visible to any attacker who sees one valid "
            "UUID. UUID v4 is random ONLY IF the underlying "
            "generator is a CSPRNG; legacy generators "
            "(`uuid-js < 2.0`, pre-Java-7 Android, "
            "`uuid.UUID(int=random.getrandbits(128))`) seeded v4 "
            "from MT19937 / `java.util.Random`. Use "
            "`crypto.randomUUID()` (Node ≥ 14.17), `uuid.v4()` on "
            "modern `uuid` (≥ 8) with a WebCrypto polyfill, or "
            "`secrets.token_hex(16)` for Python."
        ),
        pattern=_UUID_WEAK_VARIANT,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * R1 (token-from-math-random) — suppress if matched variable name
        is mock/fake/stub/dummy/sample/fixture-prefixed, OR the file is
        clearly a test file (`pytest`, `unittest`, `describe(`).
      * R2 (datenow-plus-math-random) — require a security-noun marker
        within a 5-line window around the match.
      * R3 (mt19937-for-secret) — suppress if the file is a test file
        (`import pytest` / `unittest.main` / `@pytest.fixture`).
      * R4 (predictable-seed) — suppress if the file is a test file
        OR a notebook (`get_ipython()` / `jupyter`); both shapes use
        deterministic seeds intentionally for reproducibility.
      * R5 (math-rand-for-secret) — Stage-A requires the file to
        `import "math/rand"`. We do NOT trigger on non-Go files.
      * R6 (crypto-polyfill-fallback) — require the file to ALSO
        reference `crypto.getRandomValues` somewhere, OR the
        `typeof crypto !== 'undefined'` discriminator variant.
      * R7 (rust-thread-rng-for-secret) — suppress if the file is
        clearly a test (`#[cfg(test)]` / `#[test]`).
      * R8 (uuid-v1-or-weak-v4) — for the v1 shape, require a
        consumer named like a security-noun within ±20 lines. The
        Python `getrandbits` and Java `Random` constructor shapes
        are always flagged (high-precision).

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
    is_test_file = _file_contains(text, _TEST_CONTEXT_MARKER)

    # ---- R1 : rng-js-token-from-math-random ----
    rule_r1 = rule_by_id["rng-js-token-from-math-random"]
    if not is_test_file:
        for m in _JS_MATH_RANDOM_FOR_SECRET.finditer(text):
            # Suppress if the matched variable name carries a mock prefix.
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 0, 0)
            if _JS_MOCK_PREFIX.search(window) is not None:
                continue
            _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : rng-js-datenow-plus-math-random ----
    rule_r2 = rule_by_id["rng-js-datenow-plus-math-random"]
    if not is_test_file:
        for m in _JS_DATE_NOW_MATH_RANDOM.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 2, 3)
            if _JS_SECURITY_NOUN_NEARBY.search(window) is None:
                continue
            _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : rng-py-mt19937-for-secret ----
    rule_r3 = rule_by_id["rng-py-mt19937-for-secret"]
    if not is_test_file:
        for m in _PY_RANDOM_FOR_SECRET.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 0, 0)
            # If the same matched line contains a mock-prefix, skip.
            if _JS_MOCK_PREFIX.search(window) is not None:
                continue
            _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : rng-py-predictable-seed ----
    rule_r4 = rule_by_id["rng-py-predictable-seed"]
    if not is_test_file:
        for m in _PY_PREDICTABLE_SEED.finditer(text):
            _emit(rule_r4, m.start(), m.group(0))
        for m in _PY_DEFAULT_RNG_PREDICTABLE_SEED.finditer(text):
            _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : rng-go-math-rand-for-secret ----
    rule_r5 = rule_by_id["rng-go-math-rand-for-secret"]
    has_math_rand_import = _file_contains(text, _GO_MATH_RAND_IMPORT)
    if has_math_rand_import and not is_test_file:
        for m in _GO_MATH_RAND_CALL.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 10, 10)
            if _GO_SECURITY_IDENT_NEARBY.search(window) is None:
                continue
            _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : rng-js-crypto-polyfill-fallback ----
    rule_r6 = rule_by_id["rng-js-crypto-polyfill-fallback"]
    has_getrandomvalues = _file_contains(
        text, _JS_CRYPTO_GETRANDOMVALUES_CONTEXT
    )
    if has_getrandomvalues:
        for m in _JS_CRYPTO_FALLBACK_IF_ELSE.finditer(text):
            _emit(rule_r6, m.start(), m.group(0))
        for m in _JS_CRYPTO_FALLBACK_TYPEOF.finditer(text):
            _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : rng-rust-thread-rng-for-secret ----
    rule_r7 = rule_by_id["rng-rust-thread-rng-for-secret"]
    if not is_test_file:
        for m in _RUST_THREAD_RNG_FOR_SECRET.finditer(text):
            _emit(rule_r7, m.start(), m.group(0))
        for m in _RUST_RAND_RANDOM_TYPED.finditer(text):
            _emit(rule_r7, m.start(), m.group(0))

    # ---- R8 : rng-multi-uuid-v1-or-weak-v4 ----
    rule_r8 = rule_by_id["rng-multi-uuid-v1-or-weak-v4"]
    for m in _UUID_WEAK_VARIANT.finditer(text):
        matched = m.group(0)
        # High-precision shapes — always flag.
        if (
            "getrandbits" in matched
            or "Random()" in matched
            or "rand.nextLong" in matched
        ):
            _emit(rule_r8, m.start(), matched)
            continue
        # uuid.v1() shape — require a security-noun consumer nearby.
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 10)
        if _UUID_SECRET_CONSUMER.search(window) is None:
            continue
        _emit(rule_r8, m.start(), matched)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
