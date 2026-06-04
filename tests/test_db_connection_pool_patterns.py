"""Tests for scripts/lib/db_connection_pool_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 DB connection-
pool / DSN-hygiene catalogue (6 net-new rules covering JDBC/MySQL
transport flags, MongoDB transport-and-retry flags, Redis client-side
no-auth + TLS-noverify, SQLAlchemy/HikariCP pool sizing, self-hosted
password-in-URL, and the env-empty-default → pool-constructor silent-
fail gadget). Each rule has at least one positive and one negative
test — positive proves the canary fires, negative proves the carve-out
or context filter suppresses the false-positive shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from _fake_secrets import b62, dsn  # noqa: E402,I001

import db_connection_pool_patterns as dbcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(dbcp.RULES, tuple)
    rule_ids = {r.id for r in dbcp.RULES}
    expected = {
        "dbcp-jdbc-mysql-transport-disabled",
        "dbcp-mongo-url-transport-or-retry-disabled",
        "dbcp-redis-url-no-auth-or-tls-noverify",
        "dbcp-pool-unbounded-or-missing-recycle",
        "dbcp-password-in-url-self-hosted",
        "dbcp-env-empty-default-feeds-pool-constructor",
    }
    assert expected == rule_ids
    assert len(dbcp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in dbcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = dbcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert dbcp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[dbcp.Finding]:
    return [f for f in dbcp.scan_text(text) if f.rule_id == rule_id]


# ---------- DBCP-001 : dbcp-jdbc-mysql-transport-disabled ----------------


def test_001_jdbc_mysql_use_ssl_false_flags() -> None:
    """JDBC MySQL URL with `useSSL=false` → CRITICAL hit."""
    # Fragment JDBC prefix so no contiguous jdbc: scheme+userinfo literal exists.
    _j = "jdbc" + ":"
    src = (
        f"spring.datasource.url="
        f"{_j}mysql://db.prod:3306/app?useSSL=false&serverTimezone=UTC\n"
    )
    hits = _hits("dbcp-jdbc-mysql-transport-disabled", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_001_jdbc_mariadb_allow_public_key_retrieval_flags() -> None:
    """JDBC MariaDB URL with `allowPublicKeyRetrieval=true` → CRITICAL."""
    _j = "jdbc" + ":"
    src = (
        f'String url = "{_j}mariadb://10.0.0.5:3306/db?'
        'allowPublicKeyRetrieval=true&useSSL=false";\n'
    )
    assert _hits("dbcp-jdbc-mysql-transport-disabled", src)


def test_001_jdbc_postgres_url_not_flagged() -> None:
    """Postgres JDBC URL → NOT flagged (this rule is MySQL/MariaDB only)."""
    _j = "jdbc" + ":"
    src = (
        f'spring.datasource.url='
        f'{_j}postgresql://db:5432/app?sslmode=disable\n'
    )
    assert not _hits("dbcp-jdbc-mysql-transport-disabled", src)


def test_001_jdbc_mysql_tls_enabled_not_flagged() -> None:
    """JDBC MySQL URL without downgrade flags → no hit."""
    _j = "jdbc" + ":"
    src = (
        f'spring.datasource.url='
        f'{_j}mysql://db.prod:3306/app?useSSL=true&serverTimezone=UTC\n'
    )
    assert not _hits("dbcp-jdbc-mysql-transport-disabled", src)


# ---------- DBCP-002 : dbcp-mongo-url-transport-or-retry-disabled --------


def test_002_mongo_tls_false_flags() -> None:
    """MongoDB URL with `tls=false` → HIGH hit."""
    _mongo_srv = dsn("mongodb+srv", "dbcp-mongo-tls-false", host="cluster.mongodb.net", port=None, db="orders")
    src = f"const uri = '{_mongo_srv}?tls=false&retryWrites=false';\n"
    hits = _hits("dbcp-mongo-url-transport-or-retry-disabled", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_002_mongo_tls_allow_invalid_certs_flags() -> None:
    """MongoDB URL with `tlsAllowInvalidCertificates=true` → HIGH hit."""
    _mongo_plain = dsn("mongodb", "dbcp-mongo-invalid-certs", host="db", port=27017, db="orders")
    src = (
        f'MongoClient("{_mongo_plain}?'
        'tlsAllowInvalidCertificates=true&retryWrites=false")\n'
    )
    assert _hits("dbcp-mongo-url-transport-or-retry-disabled", src)


def test_002_mongo_retry_writes_false_alone_flags() -> None:
    """MongoDB URL with only `retryWrites=false` → still flagged."""
    _mongo_root = dsn("mongodb", "dbcp-mongo-retry-false", host="mongo", port=27017, db="", user_prefix="root_")
    src = f'MONGODB_URI: "{_mongo_root}?retryWrites=false"\n'
    assert _hits("dbcp-mongo-url-transport-or-retry-disabled", src)


def test_002_mongo_url_secure_not_flagged() -> None:
    """MongoDB URL with `tls=true` → no hit."""
    _mongo_srv_ok = dsn("mongodb+srv", "dbcp-mongo-tls-true", host="cluster.mongodb.net", port=None, db="orders")
    src = f"const uri = '{_mongo_srv_ok}?tls=true&retryWrites=true';\n"
    assert not _hits("dbcp-mongo-url-transport-or-retry-disabled", src)


# ---------- DBCP-003 : dbcp-redis-url-no-auth-or-tls-noverify ------------


def test_003_redis_url_no_auth_remote_host_flags() -> None:
    """Plain `redis://` against a non-loopback host → HIGH hit."""
    src = (
        "import redis\n"
        "r = redis.Redis.from_url('redis://cache.prod.internal:6379/0')\n"
    )
    hits = _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_003_redis_ssl_cert_reqs_none_flags() -> None:
    """`ssl_cert_reqs='none'` on a redis-py constructor → flagged."""
    src = (
        "import redis\n"
        "r = redis.Redis(host='cache.prod', port=6380, ssl=True, "
        "ssl_cert_reqs='none')\n"
    )
    assert _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


def test_003_redis_ssl_cert_reqs_cert_none_constant_flags() -> None:
    """`ssl_cert_reqs=ssl.CERT_NONE` constant form → flagged."""
    src = (
        "import redis, ssl\n"
        "r = redis.Redis(host='cache.prod', ssl=True, "
        "ssl_cert_reqs=ssl.CERT_NONE)\n"
    )
    assert _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


def test_003_redis_url_localhost_not_flagged() -> None:
    """`redis://localhost:6379` (dev wiring) → no hit."""
    src = (
        "import redis\n"
        "r = redis.Redis.from_url('redis://localhost:6379/0')\n"
    )
    assert not _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


def test_003_redis_url_docker_service_name_not_flagged() -> None:
    """`redis://redis:6379` (docker-compose service name) → no hit."""
    src = (
        "REDIS_URL = 'redis://redis:6379'\n"
        "r = redis.Redis.from_url(REDIS_URL)\n"
    )
    assert not _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


def test_003_redis_url_with_password_not_flagged() -> None:
    """`redis://default:pwd@cache:6379` → no hit (auth present)."""
    src = (
        "import redis\n"
        f"r = redis.from_url('redis://default:{b62('redis-prod', 12)}@cache.prod:6379/0')\n"
    )
    assert not _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


def test_003_redis_url_outside_client_context_not_flagged() -> None:
    """Plain `redis://` URL in a doc string without redis client
    imports → no hit (context gate)."""
    src = (
        "# Example URL shape: redis://cache.prod.internal:6379/0\n"
        "# (this is just documentation)\n"
    )
    assert not _hits("dbcp-redis-url-no-auth-or-tls-noverify", src)


# ---------- DBCP-004 : dbcp-pool-unbounded-or-missing-recycle ------------


def test_004_sqlalchemy_max_overflow_neg1_flags() -> None:
    """`create_engine(..., max_overflow=-1)` → HIGH hit."""
    src = (
        "from sqlalchemy import create_engine\n"
        "engine = create_engine(DATABASE_URL, max_overflow=-1)\n"
    )
    hits = _hits("dbcp-pool-unbounded-or-missing-recycle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_004_sqlalchemy_silent_default_no_recycle_flags() -> None:
    """`create_engine(URL)` with no pool_pre_ping and no pool_recycle
    anywhere in a sqlalchemy-importing file → flagged."""
    src = (
        "from sqlalchemy import create_engine\n"
        "engine = create_engine(DATABASE_URL, echo=False)\n"
    )
    assert _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_sqlalchemy_with_pool_pre_ping_suppressed() -> None:
    """`create_engine(URL, pool_pre_ping=True)` → suppressed."""
    src = (
        "from sqlalchemy import create_engine\n"
        "engine = create_engine(DATABASE_URL, pool_pre_ping=True)\n"
    )
    # The only `create_engine` call is now annotated with pool_pre_ping
    # — both the silent-default check and the explicit max_overflow=-1
    # check should be quiet.
    assert not _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_sqlalchemy_with_pool_recycle_suppressed() -> None:
    """`create_engine(URL, pool_recycle=1800)` → suppressed."""
    src = (
        "from sqlalchemy import create_engine\n"
        "engine = create_engine(DATABASE_URL, pool_recycle=1800)\n"
    )
    assert not _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_hikari_missing_max_pool_size_flags() -> None:
    """`HikariConfig` with `setMinimumIdle` but no `setMaximumPoolSize`
    → flagged."""
    _j = "jdbc" + ":"
    src = (
        "HikariConfig cfg = new HikariConfig();\n"
        f'cfg.setJdbcUrl("{_j}postgresql://db:5432/app");\n'
        "cfg.setMinimumIdle(20);\n"
        "HikariDataSource ds = new HikariDataSource(cfg);\n"
    )
    assert _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_hikari_with_max_pool_size_suppressed() -> None:
    """`HikariConfig` with both `setMinimumIdle` and `setMaximumPoolSize`
    → suppressed."""
    src = (
        "HikariConfig cfg = new HikariConfig();\n"
        "cfg.setMinimumIdle(5);\n"
        "cfg.setMaximumPoolSize(20);\n"
    )
    assert not _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_create_engine_outside_sqlalchemy_not_flagged() -> None:
    """A `create_engine(...)` lookalike in a file with no sqlalchemy
    import is NOT flagged."""
    src = (
        "from myorm import create_engine\n"
        "engine = create_engine(DATABASE_URL)\n"
    )
    assert not _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_asyncpg_no_max_size_no_command_timeout_flags() -> None:
    """`asyncpg.create_pool(URL)` with neither max_size nor
    command_timeout → flagged."""
    src = (
        "import asyncpg\n"
        "pool = await asyncpg.create_pool(DATABASE_URL)\n"
    )
    assert _hits("dbcp-pool-unbounded-or-missing-recycle", src)


def test_004_asyncpg_with_max_size_suppressed() -> None:
    """`asyncpg.create_pool(URL, max_size=5)` → suppressed."""
    src = (
        "import asyncpg\n"
        "pool = await asyncpg.create_pool(DATABASE_URL, max_size=5)\n"
    )
    assert not _hits("dbcp-pool-unbounded-or-missing-recycle", src)


# ---------- DBCP-005 : dbcp-password-in-url-self-hosted ------------------


def test_005_postgres_url_with_password_flags() -> None:
    """DSN with real-looking credentials on a self-hosted host → CRITICAL hit."""
    src = f'DATABASE_URL = "{dsn("postgresql", "dbcp-pg-selfhosted", host="db.internal.corp", port=5432, db="orders")}"\n'
    hits = _hits("dbcp-password-in-url-self-hosted", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_005_mysql_root_root_in_compose_flags() -> None:
    """`mysql://root:root@db:3306/app` in docker-compose → flagged."""
    src = f'      DATABASE_URL: "{dsn("mysql", "dbcp-mysql-root", host="db", port=3306, db="app", user_prefix="root_")}"\n'
    assert _hits("dbcp-password-in-url-self-hosted", src)


def test_005_amqp_kafka_clickhouse_creds_flag() -> None:
    """AMQP / Kafka / ClickHouse credentialed URLs → flagged."""
    src = (
        f'CELERY_BROKER_URL = "{dsn("amqp", "dbcp-amqp-celery", host="rabbitmq", port=5672, db="/")}"\n'
        f'KAFKA_BROKER = "{dsn("kafka", "dbcp-kafka-broker", host="kafka-1", port=9092, db="app")}"\n'
        f'CH = "{dsn("clickhouse", "dbcp-clickhouse", host="ch.analytics.svc", port=9000, db="db")}"\n'
    )
    hits = _hits("dbcp-password-in-url-self-hosted", src)
    assert len(hits) >= 3


def test_005_rds_managed_host_suppressed() -> None:
    """AWS RDS credentialed URL → suppressed (cloud detector covers it)."""
    src = (
        f'DATABASE_URL = "{dsn("postgresql", "dbcp-rds-suppressed", host="prod.rds.amazonaws.com", port=5432, db="orders")}"\n'
    )
    assert not _hits("dbcp-password-in-url-self-hosted", src)


def test_005_azure_sql_host_suppressed() -> None:
    """`*.database.windows.net` credentialed URL → suppressed."""
    src = (
        f'DATABASE_URL = "mssql://app:{b62("mssql-app", 12)}@srv.database.windows.net:1433/db"\n'
    )
    # NB: the scheme `mssql` is not in our list anyway; use postgres + same host.
    assert not _hits("dbcp-password-in-url-self-hosted", src)
    src2 = (
        f'DATABASE_URL = "{dsn("postgresql", "dbcp-azure-suppressed", host="srv.database.windows.net", port=5432, db="db")}"\n'
    )
    assert not _hits("dbcp-password-in-url-self-hosted", src2)


def test_005_templated_placeholder_suppressed() -> None:
    """`${PASSWORD}` / `{{ password }}` / `<changeme>` placeholders →
    suppressed."""
    # Fragment scheme so scanner sees no complete credential-shaped URL literal.
    _pg = "postgresql" + "://"
    _mg = "mongodb" + "://"
    _amqp = "amqp" + "://"
    _ck = "clickhouse" + "://"
    src = (
        f'DATABASE_URL = "{_pg}app:${{DB_PASSWORD}}@db.internal:5432/orders"\n'
        f'OTHER = "{_mg}user:{{{{ password }}}}@mongo:27017/orders"\n'
        f'AMQP = "{_amqp}user:<CHANGE_ME>@rabbit:5672//"\n'
        f'CKH = "{_ck}user:placeholder@ch.svc:9000/d"\n'
    )
    assert not _hits("dbcp-password-in-url-self-hosted", src)


def test_005_short_trivial_password_suppressed() -> None:
    """`:1@` / `:x@` / 3-char passwords → suppressed by `{4,}`."""
    # Fragment scheme so scanner sees no complete credential-shaped URL literal.
    _pg = "postgresql" + "://"
    _my = "mysql" + "://"
    src = (
        f'URL_A = "{_pg}app:1@db:5432/orders"\n'
        f'URL_B = "{_my}root:abc@db:3306/app"\n'
    )
    assert not _hits("dbcp-password-in-url-self-hosted", src)


# ---------- DBCP-006 : dbcp-env-empty-default-feeds-pool-constructor -----


def test_006_env_empty_default_then_create_pool_flags() -> None:
    """`os.environ.get('GHOST_CONNECTION_STRING', '')` + create_pool
    → MEDIUM hit."""
    src = (
        "import os, asyncpg\n"
        "class Ghost:\n"
        "    def __init__(self):\n"
        "        self.cs = os.environ.get('GHOST_CONNECTION_STRING', '')\n"
        "    async def connect(self):\n"
        "        self.pool = await asyncpg.create_pool(self.cs, max_size=5)\n"
    )
    hits = _hits("dbcp-env-empty-default-feeds-pool-constructor", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_006_env_empty_default_then_create_engine_flags() -> None:
    """`os.environ.get('DATABASE_URL', '')` + `create_engine(...)` →
    flagged."""
    src = (
        "import os, sqlalchemy\n"
        "url = os.environ.get('DATABASE_URL', '')\n"
        "engine = sqlalchemy.create_engine(url)\n"
    )
    assert _hits("dbcp-env-empty-default-feeds-pool-constructor", src)


def test_006_env_empty_default_with_fail_loud_suppressed() -> None:
    """`os.environ.get(..., '')` + `raise RuntimeError(...)` →
    suppressed."""
    src = (
        "import os, asyncpg\n"
        "cs = os.environ.get('DATABASE_URL', '')\n"
        "if not cs:\n"
        "    raise RuntimeError('DATABASE_URL is required')\n"
        "pool = await asyncpg.create_pool(cs)\n"
    )
    assert not _hits("dbcp-env-empty-default-feeds-pool-constructor", src)


def test_006_env_no_empty_default_not_flagged() -> None:
    """`os.environ['DATABASE_URL']` (no default) → no hit on this rule."""
    src = (
        "import os, sqlalchemy\n"
        "engine = sqlalchemy.create_engine(os.environ['DATABASE_URL'])\n"
    )
    assert not _hits("dbcp-env-empty-default-feeds-pool-constructor", src)


def test_006_env_empty_default_no_pool_ctor_not_flagged() -> None:
    """`os.environ.get('DATABASE_URL', '')` alone — no pool constructor
    in the file → no hit (CLI / introspection tool case)."""
    src = (
        "import os\n"
        "url = os.environ.get('DATABASE_URL', '')\n"
        "print(url)\n"
    )
    assert not _hits("dbcp-env-empty-default-feeds-pool-constructor", src)
