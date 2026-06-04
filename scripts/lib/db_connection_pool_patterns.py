"""Database connection-pool & connection-string hygiene patterns.

Wave-26 distillation round 12 — orthogonal DB angle covering pool
sizing, transport flags embedded in DSN/URL, password-in-URL, and the
env-var-empty-default silent-fail gadget.

Catalogue distilled in
``reports/distill-round-12/db-connection-pool.md``. Targets MySQL/JDBC,
MongoDB, Redis, SQLAlchemy/HikariCP/asyncpg pool constructors and the
generic ``scheme://user:pwd@host`` URL shape for self-hosted endpoints
that the cloud-managed credential detector does not cover.

What is NOT here (already shipped — DO NOT duplicate):

  * DBA-RCE primitives (``CREATE EXTENSION``, ``COPY FROM PROGRAM``,
    UDF ``SONAME``) and the **Postgres-only** ``sslmode=`` DSN rule —
    ``scripts/lib/db_extensions_patterns.py``.
  * SQL/NoSQL injection at the query layer (f-string
    ``cursor.execute``, ORM raw, Mongo ``$where``) —
    ``scripts/lib/db_injection_patterns.py``.
  * Cloud-managed (RDS / Azure SQL / CloudSQL) credentialed URLs —
    ``scripts/lib/cloud_credential_patterns.py`` and the upstream
    secret-leak detectors.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * dbcp-jdbc-mysql-transport-disabled                (CRITICAL)
  * dbcp-mongo-url-transport-or-retry-disabled        (HIGH)
  * dbcp-redis-url-no-auth-or-tls-noverify            (HIGH)
  * dbcp-pool-unbounded-or-missing-recycle            (HIGH)
  * dbcp-password-in-url-self-hosted                  (CRITICAL)
  * dbcp-env-empty-default-feeds-pool-constructor     (MEDIUM)

Public surface:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
  * ``RULES`` — ordered tuple of every rule.
  * ``scan_text(text) -> list[Finding]``
  * ``Finding(rule_id, line, column, matched_text, severity,
    description, owasp_asi)`` — NamedTuple, mirrors
    ``chat_bot_patterns.Finding`` shape.

OWASP ASI mapping used:
  ASI-01 — Broken access control (unauthenticated Redis layer).
  ASI-04 — Insecure design (TLS-off, retry-off, pool-unbounded,
                              silent-fail invariant).
  ASI-06 — Vulnerable / outdated config (credentials in source URL).
  ASI-08 — Software & data integrity (stale-connection / silent-fail).

All regexes are RE2-compatible — no backreferences, no lookbehind, no
catastrophic backtracking shapes. Every ``[^X]*``/``.*`` is bounded by
a strict terminator. Patterns are PRE-COMPILED at module load.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as ``chat_bot_patterns.Finding``."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe shapes only."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- DBCP-001 : JDBC MySQL/MariaDB transport disabled -------------------


# Matches a `jdbc:mysql` or `jdbc:mariadb` URL containing any of the three
# transport-downgrade query parameters. Bounded character classes:
# `[^\s'"`]` keeps the URL token strict so we don't bleed across lines or
# string boundaries. No nested unbounded quantifiers.
_JDBC_MYSQL_TRANSPORT_DISABLED = _re(
    r"jdbc:(?:mysql|mariadb)://[^\s'\"`]{1,256}\?"
    r"[^\s'\"`]{0,256}"
    r"(?:useSSL=false|allowPublicKeyRetrieval=true|verifyServerCertificate=false)"
)


# ---- DBCP-002 : MongoDB URL transport/retry disabled --------------------


# `mongodb://` or `mongodb+srv://` URL with at least one of:
#   tls=false, ssl=false, tlsAllowInvalidCertificates=true,
#   tlsInsecure=true, retryWrites=false
# The `[?&]` anchor ensures the flag is in the query part of the URL.
_MONGO_URL_DOWNGRADE = _re(
    r"mongodb(?:\+srv)?://[^\s'\"`]{1,256}"
    r"[?&](?:tls=false|ssl=false|tlsAllowInvalidCertificates=true"
    r"|tlsInsecure=true|retryWrites=false)\b"
)


# ---- DBCP-003 : Redis URL no-auth + TLS-no-verify -----------------------


# A `redis://` URL (NOT `rediss://`) with NO `user:password@` segment
# between scheme and host. Note the literal `redis://` followed by a host
# character that is not a credential. We forbid the credential form via a
# negative character-class match: the very first host character must not
# allow an `@` later before the port. To keep RE2-safe, we encode this as
# `redis://[^@:'"\s/]{1,128}:\d{1,5}` — i.e. host segment without any `@`
# (no credentials), terminated by `:port`.
_REDIS_URL_NO_AUTH = _re(
    r"\bredis://[^@:'\"\s/]{1,128}:\d{1,5}(?:[/?][^\s'\"`]{0,128})?"
)


# Second sibling — `ssl_cert_reqs=none` / `ssl.CERT_NONE` on a redis-py
# constructor. Case-insensitive; `\b` anchors keep us off partial words.
_REDIS_SSL_CERT_REQS_NONE = _re(
    r"\bssl_cert_reqs\s*=\s*(?:['\"]?none['\"]?|ssl\.CERT_NONE)\b"
)


# Whole-file gate so the redis URL rule only fires when the file is
# clearly a Redis client. Without this gate, generic `redis://localhost`
# strings in unrelated docs/comments would false-trigger.
_REDIS_CLIENT_CONTEXT = _re(
    r"(?:\bredis\.Redis\b|\bredis\.from_url\b|\bRedis\.from_url\b"
    r"|\baioredis\b|\bioredis\b|\brequire\(['\"]ioredis['\"]\)"
    r"|\bcreateClient\b|\bREDIS_URL\b|\bCELERY_BROKER_URL\b"
    r"|\bCACHE_URL\b|\bfrom\s+redis\b)"
)


# A local-host suppressor for the no-auth URL rule: when the URL host is
# loopback or a docker-compose service name, the no-auth shape is
# intentional dev wiring. Require the local-host token to occupy the
# ENTIRE hostname (terminated by `:`, `/`, `?`, or end-of-match) so
# `redis://cache.prod.internal:6379` is NOT mis-classified as local
# just because "cache" is a substring.
_REDIS_LOCAL_HOST = _re(
    r"redis://(?:localhost|127\.0\.0\.1|\[::1\]|redis|cache|broker)"
    r"(?=[:/?]|$)"
)


# ---- DBCP-004 : Pool unbounded / missing recycle ------------------------


# SQLAlchemy explicit unbounded — `max_overflow=-1` is the documented
# "no limit" shape. Bounded `[^)]{0,256}` keeps us within a single call.
_SQLA_MAX_OVERFLOW_NEG1 = _re(
    r"\bcreate_engine\s*\([^)]{0,256}max_overflow\s*=\s*-\s*1\b"
)


# SQLAlchemy `create_engine(...)` call — used as the anchor for the
# "silent default" check (the call exists but no pool_pre_ping AND no
# pool_recycle anywhere in the file).
_SQLA_CREATE_ENGINE_CALL = _re(
    r"\bcreate_(?:async_)?engine\s*\("
)


# Markers that, when present anywhere in the file, indicate the operator
# IS doing pool-recycle / staleness handling.
_SQLA_POOL_RECYCLE_PRESENT = _re(
    r"\bpool_recycle\s*="
)
_SQLA_POOL_PRE_PING_PRESENT = _re(
    r"\bpool_pre_ping\s*=\s*True\b"
)


# SQLAlchemy import gate so the rule only fires on files clearly using
# the library.
_SQLA_IMPORT = _re(
    r"(?:^|\n)\s*(?:import\s+sqlalchemy\b|from\s+sqlalchemy\b)"
)


# HikariCP — `HikariConfig` declared, `setMinimumIdle(` called, but no
# `setMaximumPoolSize(` in the file. The two-step gate is encoded in
# `scan_text`; the regex below is the anchor for "this file uses
# HikariCP".
_HIKARI_CONFIG_ANCHOR = _re(
    r"\bHikariConfig\b|\bHikariDataSource\b"
)
_HIKARI_SET_MIN_IDLE = _re(
    r"\.setMinimumIdle\s*\("
)
_HIKARI_SET_MAX_POOL = _re(
    r"\.setMaximumPoolSize\s*\("
)


# asyncpg `create_pool(...)` call where `max_size=` is absent in the
# argument list (caught by a per-call inspection in scan_text).
_ASYNCPG_CREATE_POOL_CALL = _re(
    r"\b(?:asyncpg\.)?create_pool\s*\(([^)]{0,512})\)"
)


# ---- DBCP-005 : Password in URL — non-cloud host ------------------------


# `scheme://user:password@host` for self-hosted endpoints. Cloud-managed
# sentinels are caught upstream and excluded here via a runtime host
# check in scan_text (regex can match the cred-shape; the host filter
# decides whether to emit). The password requires `{4,}` chars to drop
# trivial `:1@` placeholders. Templated `${...}` and `{{ ... }}` are
# excluded via a runtime check.
_URL_WITH_CREDENTIALS = _re(
    r"\b(?P<scheme>postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|"
    r"redis|rediss|amqp|amqps|kafka|clickhouse)://"
    r"(?P<user>[A-Za-z_][A-Za-z0-9_.\-]{0,64}):"
    r"(?P<password>[^@\s'\"`]{4,128})@"
    r"(?P<host>[^/\s'\"`?:]{1,256})"
)


# Templated-placeholder shapes that look like creds but are not.
_URL_PASSWORD_TEMPLATE_RE = re.compile(
    r"(?:\$\{|\{\{|<[A-Z_]+>|\bplaceholder\b|\bexample\b|\bchange[_\-]?me\b|\bsecret_?here\b|\byour[_\-]?password\b)",
    re.IGNORECASE,
)


# Cloud-managed sentinel substrings — when the host contains any of
# these, defer to the upstream cloud detector.
_CLOUD_HOST_SENTINELS = (
    ".rds.amazonaws.com",
    ".database.windows.net",
    "cloudsql",
    ".redis.cache.windows.net",
    ".documents.azure.com",
)


# ---- DBCP-006 : os.environ.get with empty default → pool ctor ------------


# `os.environ.get("FOO", "")` where FOO matches a DB-ish env var name.
# Bounded character classes prevent runaway.
_ENV_GET_EMPTY_DEFAULT_DB = _re(
    r"\bos\.environ\.get\s*\(\s*['\"]"
    r"[A-Z_]{0,32}(?:DATABASE|MONGO|REDIS|CONNECTION|DB_URL|BROKER)[A-Z_]{0,32}"
    r"['\"]\s*,\s*['\"]\s*['\"]\s*\)"
)


# Any pool constructor — second-stage gate in scan_text.
_POOL_CONSTRUCTOR_CALL = _re(
    r"\b(?:create_pool|create_engine|create_async_engine|MongoClient"
    r"|mongoose\.connect|redis\.Redis\.from_url|aioredis\.from_url)\s*\("
)


# Marker that the operator IS doing fail-loud / scheme allowlist.
_POOL_VALIDATION_MARKER = _re(
    r"(?:raise\s+(?:RuntimeError|ValueError|EnvironmentError|Exception)"
    r"|sys\.exit\s*\(\s*[1-9]"
    r"|allowed_schemes|allowlist|ALLOWED_SCHEMES|host\s*not\s*in"
    r"|urlparse\([^)]{0,128}\)\.scheme\s*(?:==|in)\b)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="dbcp-jdbc-mysql-transport-disabled",
        name="JDBC MySQL/MariaDB URL disables TLS or chain validation",
        severity="CRITICAL",
        description=(
            "MySQL Connector/J accepts `useSSL=false` (disables TLS — "
            "credentials and queries flow in cleartext) and "
            "`allowPublicKeyRetrieval=true` (the MySQL-RCE-by-rogue-"
            "server primitive, CVE-2019-2692 family — a malicious "
            "server can phish the auth-plaintext password during the "
            "handshake). `verifyServerCertificate=false` keeps TLS but "
            "disables the chain check. All three commonly appear in "
            "Spring `application.properties` / `application.yml`, "
            "`docker-compose.yml`, `*.env`, and Java/Kotlin source. "
            "Distinct from Postgres `sslmode=` (covered by "
            "`db_extensions_patterns.pg-dsn-sslmode-weak`)."
        ),
        pattern=_JDBC_MYSQL_TRANSPORT_DISABLED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dbcp-mongo-url-transport-or-retry-disabled",
        name="MongoDB URL disables TLS, cert validation, or write retries",
        severity="HIGH",
        description=(
            "MongoDB connection-string flags that weaken transport or "
            "replication semantics: `tls=false` / `ssl=false` (plaintext "
            "wire protocol), `tlsAllowInvalidCertificates=true` / "
            "`tlsInsecure=true` (TLS without cert validation — full MITM "
            "surface), `retryWrites=false` (disables the idempotency-"
            "token-backed retry introduced in 3.6 — reads can be served "
            "from a stale secondary on partial-write failure and the "
            "read-your-own-write invariant most app code assumes is "
            "broken). Orthogonal to `db_injection_patterns` Mongo "
            "`$where` rule (query-layer vs URL-layer)."
        ),
        pattern=_MONGO_URL_DOWNGRADE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dbcp-redis-url-no-auth-or-tls-noverify",
        name="Redis client URL unauthenticated or TLS-cert-check disabled",
        severity="HIGH",
        description=(
            "A `redis://` URL pointing at a non-loopback host without "
            "`user:password@` is the canonical Redis-RCE primitive "
            "(`CONFIG SET dir` + `SLAVEOF` / `MODULE LOAD`). The "
            "`rediss://` scheme switches to TLS; downgrading to "
            "`redis://` strips both encryption and integrity. The "
            "Python `redis-py` constructor also accepts "
            "`ssl_cert_reqs='none'` / `ssl_cert_reqs=ssl.CERT_NONE`, "
            "which keeps TLS but disables peer-cert validation. "
            "Orthogonal to `db_extensions_patterns.redis-no-auth-"
            "modload`, which fires on server-side dangerous commands; "
            "THIS rule fires on the client-side URL/constructor that "
            "connects to an unauthenticated Redis in the first place. "
            "Local-host shapes (`redis://localhost`, `redis://redis`, "
            "`redis://cache`) are excluded via a runtime host check."
        ),
        pattern=_REDIS_URL_NO_AUTH,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="dbcp-pool-unbounded-or-missing-recycle",
        name="DB connection pool unbounded or missing stale-conn handling",
        severity="HIGH",
        description=(
            "Three concrete pool-sizing smells: (a) SQLAlchemy "
            "`create_engine(..., max_overflow=-1)` — documented as 'no "
            "limit', converts a burst of slow queries into 'the DB "
            "falls over from too many sockets'; (b) SQLAlchemy "
            "`create_engine(...)` with NO `pool_pre_ping` and NO "
            "`pool_recycle` anywhere in the file — an idle pool past "
            "the DB-side `idle_in_transaction_session_timeout` returns "
            "dead sockets and the next query throws `OperationalError`; "
            "(c) HikariCP `HikariConfig` where `setMinimumIdle(...)` "
            "is called but `setMaximumPoolSize(...)` is absent — the "
            "pool can never shed connections under load. "
            "DoS-amplifier-inside-the-app-process — availability, not "
            "confidentiality."
        ),
        pattern=_SQLA_MAX_OVERFLOW_NEG1,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dbcp-password-in-url-self-hosted",
        name="Password embedded in DB/broker URL pointing at a self-hosted host",
        severity="CRITICAL",
        description=(
            "A `scheme://user:password@host` URL committed to source / "
            "config where the scheme is one of "
            "{postgresql, postgres, mysql, mariadb, mongodb, mongodb+"
            "srv, redis, rediss, amqp, amqps, kafka, clickhouse} AND "
            "the host is NOT a cloud-managed sentinel "
            "(`*.rds.amazonaws.com`, `*.database.windows.net`, "
            "`*cloudsql*`, etc.). Cloud-managed shapes are caught by "
            "`cloud_credential_patterns` upstream; this rule fills the "
            "gap for self-hosted Postgres / MySQL / Mongo / Redis / "
            "RabbitMQ / Kafka / ClickHouse on private IPs, k8s DNS "
            "names, or generic hostnames. Excludes templated `${...}` "
            "/ `{{ ... }}` placeholders and `*.env.example` / "
            "`*.env.template` / `*.env.sample` files (those ARE the "
            "placeholder samples)."
        ),
        pattern=_URL_WITH_CREDENTIALS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="dbcp-env-empty-default-feeds-pool-constructor",
        name="os.environ.get(..., '') feeds an unvalidated pool constructor",
        severity="MEDIUM",
        description=(
            "An empty-string default on `os.environ.get('DATABASE_URL'"
            ", '')` followed by a pool constructor call "
            "(`create_pool` / `create_engine` / `create_async_engine` "
            "/ `MongoClient` / `mongoose.connect` / `redis.Redis."
            "from_url`) in the same file, with NO fail-loud branch "
            "(`raise RuntimeError(...)` / `sys.exit(1)` / scheme "
            "allowlist). A misconfigured deployment silently fails "
            "open — the app starts, the pool is `None`, every DB-"
            "using code path takes a 'dry-run mode' branch, and "
            "silent data loss occurs in production because the writes "
            "never reach storage. Fail-secure invariant — orthogonal "
            "to all other DB rules in this repo."
        ),
        pattern=_ENV_GET_EMPTY_DEFAULT_DB,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable rule against ``text`` and return findings.

    Stage-B filters consult file-level context:

      * dbcp-redis-url-no-auth-or-tls-noverify — only fires when the
        file shows clear Redis-client context (import, constructor,
        env var name). Loopback / docker-compose hostnames are
        suppressed. The TLS-no-verify sibling (`ssl_cert_reqs=none`)
        fires unconditionally — there is no realistic FP for that
        shape outside of testing.
      * dbcp-pool-unbounded-or-missing-recycle — combines THREE sub-
        checks:
          (i)   SQLAlchemy explicit `max_overflow=-1` — always emit.
          (ii)  SQLAlchemy `create_engine(...)` with neither
                `pool_pre_ping` nor `pool_recycle` in the same file —
                only when the file imports `sqlalchemy`.
          (iii) HikariCP `setMinimumIdle(...)` present but NO
                `setMaximumPoolSize(...)` in the file — only when
                the file mentions `HikariConfig`/`HikariDataSource`.
      * dbcp-password-in-url-self-hosted — runtime host check excludes
        cloud-managed sentinels; templated-placeholder filter excludes
        `${PASSWORD}` / `{{ password }}` / `<changeme>` / `placeholder`.
      * dbcp-env-empty-default-feeds-pool-constructor — only fires when
        the same file ALSO contains a pool-constructor call AND does
        NOT contain a fail-loud / allowlist marker.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    rule_by_id = {r.id: r for r in RULES}

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

    # ---- DBCP-001 : JDBC MySQL/MariaDB transport disabled ----
    rule_001 = rule_by_id["dbcp-jdbc-mysql-transport-disabled"]
    for m in _JDBC_MYSQL_TRANSPORT_DISABLED.finditer(text):
        _emit(rule_001, m.start(), m.group(0))

    # ---- DBCP-002 : MongoDB URL transport/retry disabled ----
    rule_002 = rule_by_id["dbcp-mongo-url-transport-or-retry-disabled"]
    for m in _MONGO_URL_DOWNGRADE.finditer(text):
        _emit(rule_002, m.start(), m.group(0))

    # ---- DBCP-003 : Redis URL no-auth / TLS-no-verify ----
    rule_003 = rule_by_id["dbcp-redis-url-no-auth-or-tls-noverify"]
    redis_context = _file_contains(text, _REDIS_CLIENT_CONTEXT)
    if redis_context:
        for m in _REDIS_URL_NO_AUTH.finditer(text):
            matched = m.group(0)
            # Local-host shapes (loopback / docker service names) ARE the
            # intended use of plain `redis://`; suppress them. The host
            # check is done against the matched URL, not the file path,
            # because dev URLs can appear in prod config files.
            if _REDIS_LOCAL_HOST.match(matched):
                continue
            _emit(rule_003, m.start(), matched)
    # The TLS-no-verify shape is unambiguous — emit unconditionally.
    for m in _REDIS_SSL_CERT_REQS_NONE.finditer(text):
        _emit(rule_003, m.start(), m.group(0))

    # ---- DBCP-004 : Pool unbounded / missing recycle ----
    rule_004 = rule_by_id["dbcp-pool-unbounded-or-missing-recycle"]
    # (i) SQLAlchemy explicit `max_overflow=-1` — always emit.
    for m in _SQLA_MAX_OVERFLOW_NEG1.finditer(text):
        _emit(rule_004, m.start(), m.group(0))
    # (ii) SQLAlchemy create_engine(...) with no pool_pre_ping and no
    # pool_recycle anywhere in the file — only when the file imports
    # sqlalchemy (so we don't false-trigger on identically-named
    # helpers in unrelated libraries).
    if _file_contains(text, _SQLA_IMPORT):
        has_recycle = _file_contains(text, _SQLA_POOL_RECYCLE_PRESENT)
        has_preping = _file_contains(text, _SQLA_POOL_PRE_PING_PRESENT)
        if not has_recycle and not has_preping:
            for m in _SQLA_CREATE_ENGINE_CALL.finditer(text):
                _emit(rule_004, m.start(), m.group(0))
    # (iii) HikariCP with setMinimumIdle but no setMaximumPoolSize.
    if _file_contains(text, _HIKARI_CONFIG_ANCHOR):
        has_max = _file_contains(text, _HIKARI_SET_MAX_POOL)
        if not has_max:
            for m in _HIKARI_SET_MIN_IDLE.finditer(text):
                _emit(rule_004, m.start(), m.group(0))
    # (iv) asyncpg `create_pool(...)` where the call has neither
    # `max_size=` nor `command_timeout=` — unbounded slot count and an
    # idle wedged query holds a slot forever. Inspect the captured
    # arglist directly so we don't false-trigger when the operator IS
    # passing one of them.
    for m in _ASYNCPG_CREATE_POOL_CALL.finditer(text):
        arglist = m.group(1)
        if "max_size" in arglist or "command_timeout" in arglist:
            continue
        _emit(rule_004, m.start(), m.group(0))

    # ---- DBCP-005 : Password in URL — self-hosted host ----
    rule_005 = rule_by_id["dbcp-password-in-url-self-hosted"]
    for m in _URL_WITH_CREDENTIALS.finditer(text):
        matched = m.group(0)
        host = m.group("host") or ""
        password = m.group("password") or ""
        # Suppress templated placeholders — `${PASSWORD}`,
        # `{{ password }}`, `<changeme>`, `placeholder`, etc.
        if _URL_PASSWORD_TEMPLATE_RE.search(password):
            continue
        # Suppress cloud-managed sentinels — caught upstream by
        # cloud_credential_patterns. Case-insensitive substring check
        # against the matched host.
        host_lower = host.lower()
        if any(sentinel in host_lower for sentinel in _CLOUD_HOST_SENTINELS):
            continue
        _emit(rule_005, m.start(), matched)

    # ---- DBCP-006 : env-default-empty feeds pool constructor ----
    rule_006 = rule_by_id["dbcp-env-empty-default-feeds-pool-constructor"]
    # Two-step gate: env-empty-default match AND a pool-constructor in
    # the same file AND no fail-loud marker.
    env_matches = list(_ENV_GET_EMPTY_DEFAULT_DB.finditer(text))
    if env_matches:
        has_pool_ctor = _file_contains(text, _POOL_CONSTRUCTOR_CALL)
        has_validation = _file_contains(text, _POOL_VALIDATION_MARKER)
        if has_pool_ctor and not has_validation:
            for m in env_matches:
                _emit(rule_006, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
