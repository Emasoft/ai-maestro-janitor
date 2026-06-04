# Tests — and the synthetic-secret-fixture convention

This is a secret-scanner. Its detectors must be exercised against
**secret-shaped** inputs, so the test suite necessarily contains strings
that *look like* credentials. To keep this repo — a security tool — from
ever tripping a secret scanner (GitHub push-protection, gitleaks,
GitGuardian) on its **own** fixtures, every secret-shaped fixture follows
one rule:

> **No realistic credential value may exist at rest in the source — not even
> a *fragmented* one.** The detector receives the value at runtime; the source
> contains only a generator call. A smart scanner that reconstructs string
> concatenation, evaluates f-strings, or flags a high-entropy tail finds
> nothing.

## How to write a secret fixture

### Primary — generate the value at runtime (`tests/_fake_secrets.py`)

Import the generator and build the value at call time. The realistic body is
sha256-derived (high-entropy → fires the detector, NOT suppressed by the
`*EXAMPLE`/`*TEST*`/`xxxx` placeholder allowlist), deterministic (assertions
are reproducible), and **never written as a literal**. Pass the prefix
fragmented so even it isn't contiguous.

```python
from _fake_secrets import secret, dsn, joinpath, b62, hexs

def test_detects_stripe_key() -> None:
    key = secret("sk_" + "live_", "psk001-stripe", 30)   # value generated here
    src = f"stripe.api_key = '{key}'\n"
    assert scan(src), "detector must fire"
    # reuse the SAME seed in the assertion (determinism), never inline a literal:
    assert secret("sk_" + "live_", "psk001-stripe", 30) in hits[0].matched_text
```

- Connection strings: `dsn("postgres", "seed", host="db", port=5432, db="app")`.
- Token-in-URL (Slack etc.): `joinpath("https://hooks." + "slack.com/services", "seed", (9, 9, 24))`.
- Bespoke (PEM body, base64, hex): `b62(seed, n)` / `hexs(seed, n)`; keep any
  structural marker fragmented (`"-----BEGIN " + "PRIVATE KEY-----"`).

### Fallback — fragment-only (when a test needs a fixed literal value)

If a test genuinely needs a *specific* byte-for-byte value, split the
recognizable prefix with `+` so it isn't contiguous at rest. Prefer the
generator above; this is only for the rare fixed-value case.

```python
_SK_LIVE = "sk_" + "live_"      # "sk_live_" only exists at runtime
src = f"stripe.api_key = '{_SK_LIVE}51Jexample0000000000000000'\n"
```

### PEM private keys — fragment the marker

In a **data** string use `+`:

```python
_PEM_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
src = f"{_PEM_BEGIN}\nMIIexample...\n-----END " + "PRIVATE KEY-----\n"
```

In a **regex pattern** string (detector source, `scripts/lib/*_patterns.py`)
use a one-character class — `[ ]` matches one literal space, identical at
match time:

```python
_re(r"-----BEGIN PRIVATE[ ]KEY-----")   # equivalent to a bare space
```

### Prefix-less high-entropy blobs (fallback) — inline allowlist

When a fixture is a random base64/hex blob with **no** vendor prefix (so
there is nothing to fragment), leave the value and mark the physical line:

```python
key = "ZGVwbG95ZXI6c2VjcmV0"  # gitleaks:allow  pragma: allowlist secret
```

### The one exception you may keep verbatim

`AKIAIOSFODNN7EXAMPLE` — AWS's official documentation example key. It is
universally allowlisted by every scanner and is self-documenting as fake;
use it as-is when you need a recognizable AWS access-key id.

## Enforcement

`test_secret_fixture_hygiene.py` scans the tracked source on every test run
and **fails** if a contiguous, real-format credential literal reappears.
The publish pipeline runs the suite, so a regression cannot ship.

## Running the suite

```bash
uv run python -m pytest tests/ -q
```
