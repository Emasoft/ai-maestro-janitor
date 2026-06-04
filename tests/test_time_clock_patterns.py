"""Tests for scripts/lib/time_clock_patterns.py.

Pattern-coverage tests for the Wave-24 Time/Clock TOCTOU + NTP /
clock-skew catalogue (time.time-as-monotonic, symmetric HMAC-replay
window, wall-clock rate-limit reset, stat-then-act FS TOCTOU, JWT
decode without leeway, refresh-token DB-NOW() only, datetime.utcnow
deprecated). Every rule gets at least one positive + one negative
test (most have two of each).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import time_clock_patterns as tcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_seven_detectors() -> None:
    """RULES must be a tuple and contain every advertised rule id from
    the distill-round-10 / time-clock-toctou proposal."""
    assert isinstance(tcp.RULES, tuple)
    rule_ids = {r.id for r in tcp.RULES}
    expected = {
        "time-time-as-monotonic-for-token-expiry",
        "hmac-timestamp-window-symmetric",
        "rate-limit-window-wall-clock-reset",
        "stat-then-act-toctou",
        "jwt-exp-no-leeway-wall-clock-mint",
        "refresh-token-db-now-only",
        "datetime-utcnow-deprecated-naive",
    }
    assert expected == rule_ids, (
        f"missing: {expected - rule_ids}, extra: {rule_ids - expected}"
    )


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """All time/clock rules map to an OWASP ASI A0X:2021 category;
    severity must be one of CRITICAL/HIGH/MAJOR/MEDIUM/MINOR/LOW."""
    valid_severities = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW"}
    for rule in tcp.RULES:
        assert rule.owasp_asi.startswith("A"), rule.id
        assert ":2021" in rule.owasp_asi, rule.id
        assert rule.severity in valid_severities, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors dos_resource_patterns.Finding so downstream
    renderers handle time/clock + DoS findings uniformly."""
    f = tcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="A02:2021",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "A02:2021"


def _hits(rule_id: str, text: str) -> list[tcp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in tcp.scan_text(text) if f.rule_id == rule_id]


# ---------- T1. time.time() / Date.now() as token-expiry monotonic -------


def test_t1_python_expires_at_time_time_positive() -> None:
    """Python `"expires_at": time.time() + N` — the canonical Auth0
    token-cache shape from `deep-sentinel-main/auth0_client.py:123`."""
    src = 'cache["token"] = {"expires_at": time.time() + 3600, "value": tok}'
    assert _hits("time-time-as-monotonic-for-token-expiry", src)


def test_t1_javascript_date_now_positive() -> None:
    """JS `expires_at: Date.now() + N` — the same bug class on the JS
    side. Token cache write."""
    src = "const cached = { expires_at: Date.now() + 3600000, token: t }"
    assert _hits("time-time-as-monotonic-for-token-expiry", src)


def test_t1_camel_case_expires_at_positive() -> None:
    """JS camelCase variant `expiresAt: Date.now() + N` — common in JS
    codebases that follow Airbnb/Standard style."""
    src = "return { expiresAt: Date.now() + ttlMs, value: result }"
    assert _hits("time-time-as-monotonic-for-token-expiry", src)


def test_t1_unrelated_time_time_no_match() -> None:
    """Plain `time.time()` used for duration measurement (not token
    expiry) must NOT match — no `expires_at` key on the same line."""
    src = 'start = time.time()\nduration = time.time() - start'
    assert not _hits("time-time-as-monotonic-for-token-expiry", src)


def test_t1_logging_only_no_match() -> None:
    """A logging field called `created_at` is not the bug — only
    `expires_at`-style names should match."""
    src = 'log = { "created_at": time.time(), "event": "ping" }'
    assert not _hits("time-time-as-monotonic-for-token-expiry", src)


# ---------- T2. Symmetric clock-skew check on HMAC-replay timestamp ------


def test_t2_javascript_math_abs_slack_positive() -> None:
    """JS Slack-webhook shape `Math.abs(time - slackTimestamp) > 300`
    — accepts future-dated timestamps as valid."""
    src = "if (Math.abs(time - slackTimestamp) > 300) { return reject() }"
    assert _hits("hmac-timestamp-window-symmetric", src)


def test_t2_python_abs_time_time_positive() -> None:
    """Python equivalent: `abs(time.time() - request_ts) > 300`."""
    src = 'if abs(time.time() - int(headers["X-Timestamp"])) > 300: raise'
    assert _hits("hmac-timestamp-window-symmetric", src)


def test_t2_python_abs_datetime_utcnow_timestamp_positive() -> None:
    """Python variant using `datetime.utcnow().timestamp()` — same bug."""
    src = "if abs(datetime.utcnow().timestamp() - claimed - drift) > 60: bail"
    assert _hits("hmac-timestamp-window-symmetric", src)


def test_t2_asymmetric_check_no_match() -> None:
    """Correct asymmetric check `time - sig_ts > 300` (NO Math.abs)
    must NOT match — that's the right shape."""
    src = "if (now - signedTimestamp > 300) { return reject() }"
    assert not _hits("hmac-timestamp-window-symmetric", src)


def test_t2_abs_unrelated_no_match() -> None:
    """`abs(price - last_price) > 0.01` (financial diff, no time/timestamp
    identifier) must NOT match."""
    src = "if abs(price - last_price) > 0.01: trigger_alert()"
    assert not _hits("hmac-timestamp-window-symmetric", src)


# ---------- T3. Wall-clock-driven rate-limit window reset ----------------


def test_t3_javascript_window_start_reset_positive() -> None:
    """JS rate-limiter shape: `windowStart < ... requests = 1` reset."""
    src = (
        "if (recordWindowStart < windowStart) {\n"
        "    record.requests = 1;\n"
        "    record.windowStart = now;\n"
        "}\n"
    )
    assert _hits("rate-limit-window-wall-clock-reset", src)


def test_t3_python_window_start_timedelta_positive() -> None:
    """Python rate-limiter: `record.window_start < (datetime.utcnow() -
    timedelta(seconds=window))` then `record.requests = 1`."""
    src = (
        "if record.window_start < (datetime.utcnow() - timedelta(seconds=60)):\n"
        "    record.requests = 1\n"
        "    record.window_start = datetime.utcnow()\n"
    )
    assert _hits("rate-limit-window-wall-clock-reset", src)


def test_t3_counter_increment_no_match() -> None:
    """`counter += 1` inside a comparison block is NOT a reset — only
    `= 1` (assignment to literal 1) triggers."""
    src = (
        "if window_start_recorded < cutoff:\n"
        "    counter += 1\n"
    )
    assert not _hits("rate-limit-window-wall-clock-reset", src)


def test_t3_no_window_start_identifier_no_match() -> None:
    """Generic comparison without `window_start` keyword must NOT match."""
    src = (
        "if expiry < cutoff:\n"
        "    requests = 1\n"
    )
    assert not _hits("rate-limit-window-wall-clock-reset", src)


# ---------- T4. TOCTOU between path.exists() and open/copy/chmod ---------


def test_t4_path_exists_then_copy2_positive() -> None:
    """Python `if not path.exists(): return ... shutil.copy2(path, backup)`
    — the corpus C8 shape from `narthex-main/install.py:108-119`."""
    src = (
        "if not path.exists():\n"
        "    return None\n"
        "shutil.copy2(path, backup)\n"
    )
    assert _hits("stat-then-act-toctou", src)


def test_t4_os_path_isfile_then_open_positive() -> None:
    """`if os.path.isfile(path):` followed by `open(path)` — TOCTOU
    on the bare open() call. `os.path.isfile` is an additional stat()."""
    src = (
        "if os.path.isfile(target):\n"
        "    log.info('opening')\n"
        "    open(target, 'rb')\n"
    )
    assert _hits("stat-then-act-toctou", src)


def test_t4_is_file_then_chmod_positive() -> None:
    """`Path(p).is_file()` followed by `.chmod(0o600)` — same race."""
    src = (
        "if p.is_file():\n"
        "    p.chmod(0o600)\n"
    )
    assert _hits("stat-then-act-toctou", src)


def test_t4_open_without_stat_no_match() -> None:
    """Bare `open(path)` with NO prior `path.exists()` check must NOT
    match — that's the canonical EAFP Pythonic shape (Try/Except)."""
    src = (
        "try:\n"
        "    f = open(path, 'rb')\n"
        "except FileNotFoundError:\n"
        "    return None\n"
    )
    assert not _hits("stat-then-act-toctou", src)


def test_t4_exists_alone_no_match() -> None:
    """`if path.exists(): log.info(...)` with NO subsequent file
    action must NOT match — pure check, no open/copy/chmod follows."""
    src = (
        "if path.exists():\n"
        "    log.info('found')\n"
        "    return True\n"
    )
    assert not _hits("stat-then-act-toctou", src)


# ---------- T5. JWT decode without explicit clock-skew leeway ------------


def test_t5_python_jwt_decode_no_leeway_positive() -> None:
    """`jwt.decode(token, key, algorithms=[...])` with NO `leeway=`
    — the corpus C7 shape from `CodeSentinel-main/auth.py:36-37`."""
    src = 'payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])'
    assert _hits("jwt-exp-no-leeway-wall-clock-mint", src)


def test_t5_javascript_jwt_verify_no_clock_tolerance_positive() -> None:
    """JS `jwt.verify(token, secret)` with NO `clockTolerance:` option."""
    src = 'const claims = jwt.verify(token, secret)'
    assert _hits("jwt-exp-no-leeway-wall-clock-mint", src)


def test_t5_python_jwt_decode_with_leeway_no_match() -> None:
    """`jwt.decode(token, key, algorithms=["HS256"], leeway=30)` —
    explicit leeway means the engineer made the choice; suppress."""
    src = (
        'payload = jwt.decode(token, key, algorithms=["HS256"], leeway=30)'
    )
    assert not _hits("jwt-exp-no-leeway-wall-clock-mint", src)


def test_t5_javascript_jwt_verify_with_clock_tolerance_no_match() -> None:
    """`jwt.verify(token, secret, { clockTolerance: 30 })` — explicit
    tolerance set; suppress."""
    src = 'const c = jwt.verify(token, secret, { clockTolerance: 30 })'
    assert not _hits("jwt-exp-no-leeway-wall-clock-mint", src)


# ---------- T6. Refresh-token validity bound to DB NOW() only ------------


def test_t6_postgres_now_refresh_token_positive() -> None:
    """SQL `WHERE rt.token_hash = $1 AND rt.expires_at > NOW()` —
    the corpus C9 shape from `AuthService.js:268`."""
    sql = (
        "const result = pool.query("
        "'SELECT * FROM refresh_tokens WHERE token_hash = $1 "
        "AND expires_at > NOW()', [hash])"
    )
    assert _hits("refresh-token-db-now-only", sql)


def test_t6_current_timestamp_session_token_positive() -> None:
    """ANSI-portable `CURRENT_TIMESTAMP` variant + `session_token`
    column — same bug, different dialect."""
    sql = (
        "rows = cursor.execute("
        "'SELECT user_id FROM sessions WHERE session_token = %s "
        "AND expires_at > CURRENT_TIMESTAMP', (st,))"
    )
    assert _hits("refresh-token-db-now-only", sql)


def test_t6_data_table_no_token_keyword_no_match() -> None:
    """`WHERE id = $1 AND expires_at > NOW()` (no token-related
    keyword) must NOT match — that's a generic data-expiry query,
    not an auth check."""
    sql = (
        "pool.query('SELECT * FROM cache_entries "
        "WHERE id = $1 AND expires_at > NOW()', [eid])"
    )
    assert not _hits("refresh-token-db-now-only", sql)


def test_t6_no_now_function_no_match() -> None:
    """`WHERE token_hash = $1 AND expires_at > $2` (parametric, no
    DB-side NOW()) must NOT match — the validator passes the time
    explicitly, which is the recommended fix."""
    sql = (
        "pool.query('SELECT * FROM refresh_tokens "
        "WHERE token_hash = $1 AND expires_at > $2', [h, now_ts])"
    )
    assert not _hits("refresh-token-db-now-only", sql)


# ---------- T7. datetime.utcnow() — deprecated naive UTC -----------------


def test_t7_datetime_utcnow_call_positive() -> None:
    """Bare `datetime.utcnow()` call — deprecated since Python 3.12."""
    src = "expire = datetime.utcnow() + timedelta(minutes=30)"
    assert _hits("datetime-utcnow-deprecated-naive", src)


def test_t7_datetime_utcnow_sqlalchemy_default_positive() -> None:
    """`Column(DateTime, default=datetime.utcnow)` — the no-parens
    callable form. Wait: this is the bare attribute, not a call.
    The detector targets the CALL site, so use the called form
    that produces the same bug in arithmetic."""
    src = "entry.last_used = datetime.utcnow()"
    assert _hits("datetime-utcnow-deprecated-naive", src)


def test_t7_datetime_now_timezone_utc_no_match() -> None:
    """`datetime.now(timezone.utc)` — the modern correct replacement;
    must NOT match."""
    src = "expire = datetime.now(timezone.utc) + timedelta(minutes=30)"
    assert not _hits("datetime-utcnow-deprecated-naive", src)


def test_t7_datetime_now_without_tz_no_match() -> None:
    """`datetime.now()` (naive local) is bad but DIFFERENT bug — not
    flagged by this T7 rule. T7 specifically targets `utcnow()`."""
    src = "ts = datetime.now()"
    assert not _hits("datetime-utcnow-deprecated-naive", src)


# ---------- Composed scan_text behaviour ---------------------------------


def test_scan_text_empty_returns_empty_list() -> None:
    """Empty input is a no-op — must not raise."""
    assert tcp.scan_text("") == []


def test_scan_text_findings_are_sorted_by_position() -> None:
    """Findings sorted by (line, column, rule_id) for stable output."""
    text = (
        'cache = {"expires_at": time.time() + 3600}\n'
        "expire = datetime.utcnow() + timedelta(minutes=30)\n"
    )
    findings = tcp.scan_text(text)
    assert len(findings) >= 2
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_line_column_one_based() -> None:
    """Lines + columns 1-based (matches human traceback convention)."""
    text = (
        "harmless = 1\n"
        "expire = datetime.utcnow()\n"
    )
    findings = _hits("datetime-utcnow-deprecated-naive", text)
    assert findings
    assert findings[0].line == 2
    assert findings[0].column >= 1


def test_scan_text_long_match_is_truncated() -> None:
    """matched_text capped at 200 chars + ellipsis. The TOCTOU match
    spans 5 short noise lines (well under the per-line 200-char
    bound in the regex) so the full match is > 200 chars and gets
    truncated."""
    long_src = (
        "if not path.exists():\n"
        "    # noise line one with a bit of padding text here ok\n"
        "    # noise line two with a bit of padding text here ok\n"
        "    # noise line three with a bit of padding text here\n"
        "    # noise line four with a bit of padding text here ok\n"
        "    return\n"
        "shutil.copy2(path, backup)\n"
    )
    findings = _hits("stat-then-act-toctou", long_src)
    assert findings
    assert len(findings[0].matched_text) <= 201  # 200 + ellipsis
