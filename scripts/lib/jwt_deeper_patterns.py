"""JWT-specific deeper attack patterns (Wave 21 — distill round 7, angle B).

Catalogue source: `reports/distill-round-7/jwt-deeper.md` (15 proposals).

This pack goes DEEPER than Wave 17 (`auth_flow_patterns.py`) and Wave 18
(`crypto_misuse_patterns.py`) which already cover the surface JWT issues:
literal `algorithms=["none"]`, missing `aud`/`iss` claims inside tokens, the
classic alg-confusion list. Those baselines are NOT re-encoded here.

What IS here (15 net-new deeper JWT detectors, regex-only — RE2-safe):

  * jwt.algorithm-from-env-or-config           (HIGH)        — P1
  * jwt.verify-no-algorithms-allowlist         (HIGH)        — P2 / P15
  * jwt.vulnerable-library-version             (HIGH)        — P3 / P12
  * jwt.kid-header-used-as-unsafe-lookup       (CRITICAL)    — P4
  * jwt.jku-header-fetched-unrestricted        (CRITICAL)    — P5
  * jwt.x5u-header-fetched-unrestricted        (CRITICAL)    — P6
  * jwt.x5c-header-chain-trusted-inline        (CRITICAL)    — P7
  * jwt.decode-options-verify-signature-false  (CRITICAL)    — P8
  * jwt.unverified-claims-as-identity          (HIGH)        — P8
  * jwt.decode-missing-audience-or-issuer      (HIGH)        — P9
  * jwt.leeway-excessive-clock-skew            (MEDIUM)      — P10
  * jwt.long-exp-stateless-no-revocation       (HIGH)        — P11
  * jwt.token-in-url-querystring               (HIGH)        — P13
  * jwt.cookie-missing-httponly-secure         (HIGH)        — P14
  * jwt.rsa-key-with-hs-algorithm-allowed      (CRITICAL)    — P15

OWASP ASI mapping:
  ASI-04 — Insecure output / token leak (URL, cookie flags)
  ASI-05 — Supply-chain / cross-tenant pivot (jku, x5u, x5c, kid lookup)
  ASI-07 — Authority / authorisation gaps (alg-confusion, missing aud/iss
                                            verifier-side, leeway, exp,
                                            revocation absence)
  ASI-08 — Cryptographic failures (vulnerable library, verify_signature=False)

Public surface mirrors crypto_misuse_patterns.py and auth_flow_patterns.py:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, file_kind="prose", filename="") -> list[Finding]

Every regex is RE2-safe: no backreferences, no negative lookbehind, no
nested unbounded quantifiers; bounded inline-quantifier windows are used
where context matching is needed.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in crypto_misuse_patterns.py / auth_flow_patterns.py so the
    surface is uniform across rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule P1: jwt.algorithm-from-env-or-config --------------------------


# `jwt.decode(..., algorithms=[<non-literal>])` / `jwt.encode(..., algorithm=<non-literal>)`
# — algorithm comes from a variable, settings.<attr>, os.environ, etc.
# Surface Wave 18 regex (`algorithms=['none']`) never fires while the
# system is still vulnerable to an env flip. We catch the indirection
# explicitly here.
#
# The pattern matches when the algorithms list contains a Python
# identifier / attribute reference (`settings.ALGORITHM`, `cfg.alg`,
# `ALG_ENV`, `os.getenv(...)`) rather than a quoted string literal.
# Bounded inline window (200 chars) keeps the regex RE2-safe.
_JWT_ALG_FROM_ENV_RE = _re(
    # jwt.decode(..., algorithms=[<bare-identifier-or-attr-or-call>])
    r"\bjwt\.decode\s*\([^)\n]{0,200}\balgorithms\s*=\s*\[\s*"
    r"(?:[A-Za-z_][\w\.]*(?:\s*\([^)\n]{0,80}\))?)\s*\]"
    r"|"
    # jwt.encode(..., algorithm=<bare-identifier-or-attr-or-call>)
    r"\bjwt\.encode\s*\([^)\n]{0,200}\balgorithm\s*=\s*"
    r"(?:settings\.|cfg\.|config\.|os\.environ|os\.getenv|getenv|[A-Z_][A-Z0-9_]{2,})"
    r"|"
    # python-jose: jose.jwt.decode(..., algorithms=[<bare-identifier>])
    r"\bjose\.jwt\.decode\s*\([^)\n]{0,200}\balgorithms\s*=\s*\[\s*"
    r"(?:[A-Za-z_][\w\.]*(?:\s*\([^)\n]{0,80}\))?)\s*\]"
)


# ---- Rule P2/P15: jwt.verify-no-algorithms-allowlist --------------------


# `jsonwebtoken.verify(token, key)` / `jwt.verify(token, key)` (Node) with
# NO algorithms option in the call. Pre-9.0 jsonwebtoken silently fell
# back to whatever `alg` the token header advertised — classic RS/HS
# confusion. The detection looks for verify() calls without the
# `algorithms:` option key anywhere inside the call.
#
# We require the second argument to look like a *PEM / public key /
# certificate* source (`publicKey`, `RSA_PUB`, `cert`, `fs.readFileSync(...pem...)`,
# `.pem` literal, etc.) — this elevates the finding to CRITICAL (alg
# confusion vector). Pure secret-string verify() calls are handled by
# Wave 17.
_JWT_VERIFY_NO_ALG_RE = _re(
    # jsonwebtoken.verify(token, publicKey)  — second arg is a "pub key"-shaped name
    r"\b(?:jsonwebtoken|jwt)\.verify\s*\(\s*[A-Za-z_]\w*\s*,\s*"
    r"(?:[A-Za-z_]*(?:public[_-]?key|pubkey|cert|certificate|rsa[_-]?pub)[\w\.]*"
    r"|"
    # ALL_CAPS _PUB / _PUBLIC / _PUB_KEY constants
    r"[A-Z][A-Z0-9_]*_PUB(?:LIC)?(?:_KEY)?[\w\.]*"
    r"|"
    # fs.readFileSync('.../something.pem' ...)
    r"fs\.readFileSync\s*\(\s*[`'\"][^`'\"]{0,200}\.pem"
    r")"
)


# ---- Rule P3/P12: jwt.vulnerable-library-version ------------------------


# Dependency manifests / lockfiles pinning a JWT library at a CVE-affected
# version. Each clause covers ONE library at ONE format. We deliberately
# keep regex bounded — the Stage-B check in scan_text() asserts the
# filename looks like a manifest (requirements.txt, package.json,
# package-lock.json, Pipfile, pyproject.toml, uv.lock, poetry.lock).
_JWT_VULN_LIB_RE = _re(
    # PyPI: python-jose < 3.4.0 (algorithm confusion CVEs)
    r"^\s*python-jose(?:\[[^\]]+\])?\s*[=<~!]+\s*3\.[0-3](?:\.\d+)?\s*$"
    r"|"
    # PyPI: python-jose <3.4 / <3.4.0 explicit upper bound
    r"^\s*python-jose(?:\[[^\]]+\])?\s*<\s*3\.4(?:\.0)?\s*$"
    r"|"
    # PyPI: PyJWT < 2.0 (pre-default-verify era)
    r"^\s*PyJWT\s*[=<~!]+\s*[01]\.\d+(?:\.\d+)?\s*$"
    r"|"
    r"^\s*PyJWT\s*<\s*2(?:\.0(?:\.0)?)?\s*$"
    r"|"
    # npm: "jsonwebtoken": "^8.5.1" / "~8.x" / "<9"
    r'"jsonwebtoken"\s*:\s*"\s*(?:[~^<]?\s*[0-8]\.\d+(?:\.\d+)?'
    r'|<\s*9(?:\.\d+)?)'
    r"|"
    # npm: "jose": "^3.x" / "<4"
    r'"jose"\s*:\s*"\s*(?:[~^<]?\s*[0-3]\.\d+(?:\.\d+)?|<\s*4)'
    r"|"
    # npm jwt-decode used as a verifier — flag any pin (the lib only decodes)
    r'"jwt-decode"\s*:\s*"\s*[~^<>=]*\s*\d'
)


# ---- Rule P4: jwt.kid-header-used-as-unsafe-lookup ----------------------


# `kid` from the token header flows into a filesystem path / SQL query /
# generic dict lookup without an allowlist check. The pattern matches
# common sink shapes within ~200 chars of a `kid` reference. We rely on
# Stage-B file-level guards to suppress when an allowlist clearly exists.
_JWT_KID_PATH_RE = _re(
    # open(f"keys/{kid}.pem") — Python f-string path injection
    r"\bopen\s*\(\s*f?[`'\"][^`'\"\n]{0,80}\{?kid\}?[^`'\"\n]{0,40}\.(?:pem|key|crt|pub|cert|jwk)"
    r"|"
    # Path(...).read_*() with kid in the path
    r"\bPath\s*\(\s*f?[`'\"][^`'\"\n]{0,80}\{?kid\}?"
    r"|"
    # os.path.join(_, kid) / os.path.join(_, header['kid'])
    r"\bos\.path\.join\s*\([^)\n]{0,80}(?:kid|header\s*\[\s*['\"]kid['\"]\s*\]|header\.kid)\b"
    r"|"
    # SQL string formatting with kid
    r"(?:SELECT|select)\s[^;\n]{0,160}WHERE\s[^;\n]{0,80}kid\s*=\s*"
    r"(?:%s|\?|\{kid\}|f?['\"]\s*\+\s*kid)"
    r"|"
    # Redis lookup: redis.get(f"jwt:kid:{kid}") / cache key built from kid
    r"\b(?:redis|cache)\.(?:get|hget|smembers)\s*\(\s*f?['\"][^'\"]{0,40}\{?kid\}?"
    r"|"
    # Node: fs.readFileSync(`keys/${kid}.pem`)
    r"\bfs\.readFileSync\s*\(\s*`[^`\n]{0,80}\$\{kid\}"
    r"|"
    # Node SQL: db.query(`SELECT ... WHERE kid = '${kid}'`)
    r"\bdb\.(?:query|raw)\s*\(\s*`[^`\n]{0,160}\$\{kid\}"
)


# ---- Rule P5: jwt.jku-header-fetched-unrestricted -----------------------


# `jku` extracted from the unverified header and fed to an HTTP fetch
# (requests.get / axios.get / fetch / http.get). The Stage-B guard
# requires the absence of an allowlist marker (a string-literal
# JWKS-host hardcode within 5 lines of the fetch).
_JWT_JKU_FETCH_RE = _re(
    # Python: requests.get(header['jku']) / requests.get(header.get('jku'))
    r"\b(?:requests|httpx|urllib(?:\.request)?|urlopen|aiohttp)"
    r"[^)\n]{0,40}\(\s*"
    r"(?:header\s*\[\s*['\"]jku['\"]\s*\]"
    r"|header\.jku\b"
    r"|header\.get\s*\(\s*['\"]jku['\"]"
    r"|unverified[_-]?header\s*\[\s*['\"]jku['\"]\s*\]"
    r"|get_unverified_header\s*\([^)\n]{0,60}\)\s*\[\s*['\"]jku['\"]\s*\])"
    r"|"
    # Node: axios.get(header.jku) / fetch(header['jku'])
    r"\b(?:axios|fetch|got|superagent|http)\.(?:get|request|fetch)\s*\(\s*"
    r"(?:header\s*\[\s*['\"]jku['\"]\s*\]|header\.jku\b)"
    r"|"
    # Node: const jku = decoded.header.jku; ... fetch(jku)
    r"\bjwksUri\s*[:=]\s*(?:header\.jku|header\s*\[\s*['\"]jku['\"]\s*\])"
)


# ---- Rule P6: jwt.x5u-header-fetched-unrestricted -----------------------


# Same shape as P5 but for `x5u` (X.509 cert URL). The verifier fetches
# the URL, parses the PEM, uses the public key. Attacker controls the
# URL, attacker controls the key.
_JWT_X5U_FETCH_RE = _re(
    # Python: requests.get(header['x5u'])
    r"\b(?:requests|httpx|urllib(?:\.request)?|urlopen|aiohttp)"
    r"[^)\n]{0,40}\(\s*"
    r"(?:header\s*\[\s*['\"]x5u['\"]\s*\]"
    r"|header\.x5u\b"
    r"|header\.get\s*\(\s*['\"]x5u['\"]"
    r"|unverified[_-]?header\s*\[\s*['\"]x5u['\"]\s*\])"
    r"|"
    # Node: axios.get(header.x5u)
    r"\b(?:axios|fetch|got|superagent|http)\.(?:get|request|fetch)\s*\(\s*"
    r"(?:header\s*\[\s*['\"]x5u['\"]\s*\]|header\.x5u\b)"
)


# ---- Rule P7: jwt.x5c-header-chain-trusted-inline -----------------------


# `header["x5c"]` indexed as element [0] and used as a key / cert
# argument. Lazy verifier reads the first element of the chain, extracts
# the public key, verifies the signature, never validates that the chain
# terminates at a trusted CA. Attacker-supplied self-signed cert wins.
#
# Stage-B suppression: file-level presence of a CA-bundle / trust-anchor
# load (`ssl.create_default_context`, `verify_locations`, `x509.load_pem_x509_certificate`
# paired with `verify`) downgrades the severity in user docs (not encoded
# here — surface the hit, let reviewer triage).
_JWT_X5C_INLINE_RE = _re(
    # Python: header['x5c'][0] / header.x5c[0]
    r"\bheader\s*\[\s*['\"]x5c['\"]\s*\]\s*\[\s*0\s*\]"
    r"|"
    r"\bheader\.x5c\s*\[\s*0\s*\]"
    r"|"
    # unverified_header from python-jose / PyJWT
    r"\bunverified[_-]?header\s*\[\s*['\"]x5c['\"]\s*\]\s*\[\s*0\s*\]"
    r"|"
    # Node: decoded.header.x5c[0]
    r"\bdecoded\.header\.x5c\s*\[\s*0\s*\]"
    r"|"
    # Direct use: jwt.verify(token, header.x5c[0], ...)
    r"\bjwt\.verify\s*\([^)\n]{0,80}header\.x5c\s*\[\s*0\s*\]"
)


# ---- Rule P8: jwt.decode-options-verify-signature-false -----------------


# `jwt.decode(..., options={'verify_signature': False, ...})` — PyJWT's
# separate "decode but don't verify" path. Wave 18 catches the `none`
# alg literal; this is the orthogonal disable path.
_JWT_VERIFY_SIG_FALSE_RE = _re(
    # PyJWT: jwt.decode(..., options={'verify_signature': False, ...})
    r"\bjwt\.decode\s*\([^)\n]{0,300}options\s*=\s*"
    r"\{[^}\n]{0,200}"
    r"['\"]verify_signature['\"]\s*:\s*(?:False|false|0)"
    r"|"
    # PyJWT: jwt.decode(..., options={'verify_exp': False, ...})
    r"\bjwt\.decode\s*\([^)\n]{0,300}options\s*=\s*"
    r"\{[^}\n]{0,200}"
    r"['\"]verify_(?:exp|aud|iss|nbf|iat)['\"]\s*:\s*(?:False|false|0)"
    r"|"
    # legacy PyJWT keyword: jwt.decode(..., verify=False)
    r"\bjwt\.decode\s*\([^)\n]{0,200}\bverify\s*=\s*False\b"
    r"|"
    # python-jose: jose.jwt.decode(..., options={'verify_signature': False})
    r"\bjose\.jwt\.decode\s*\([^)\n]{0,300}options\s*=\s*"
    r"\{[^}\n]{0,200}"
    r"['\"]verify_signature['\"]\s*:\s*(?:False|false|0)"
    r"|"
    # Node jsonwebtoken: jwt.verify(..., { ignoreExpiration: true })
    r"\b(?:jsonwebtoken|jwt)\.verify\s*\([^)\n]{0,300}"
    r"\bignoreExpiration\s*:\s*true\b"
)


# ---- Rule P8b: jwt.unverified-claims-as-identity ------------------------


# `get_unverified_claims` / `get_unverified_header` used to extract a
# user-identity field. The pattern flags the call ITSELF as suspect;
# Stage-B in scan_text() suppresses when the file ALSO contains a real
# verifying call (`jwt.decode` without `verify=False`).
_JWT_UNVERIFIED_CLAIMS_RE = _re(
    r"\bjwt\.get_unverified_(?:claims|header)\s*\("
    r"|"
    r"\bjose\.jwt\.get_unverified_(?:claims|header)\s*\("
    r"|"
    r"\bjsonwebtoken\.decode\s*\("
    r"|"
    # Node: jwt-decode library, which only decodes — never verifies
    r"\b(?:from|require)\s*\(?\s*['\"]jwt-decode['\"]"
)


# ---- Rule P9: jwt.decode-missing-audience-or-issuer --------------------


# `jwt.decode(...)` without an `audience=` / `issuer=` kwarg. Wave 18
# catches missing `aud`/`iss` INSIDE the token; this is the verifier-side
# omission. Stage-B in scan_text() suppresses if the SAME FILE contains
# a `jwt.encode(...)` with `aud=` / `iss=` AND the matched decode call's
# call-text already contains `audience=` / `issuer=`.
_JWT_DECODE_TRIGGER_RE = _re(
    r"\bjwt\.decode\s*\("
    r"|"
    r"\bjose\.jwt\.decode\s*\("
    r"|"
    r"\bjsonwebtoken\.verify\s*\("
)


# ---- Rule P10: jwt.leeway-excessive-clock-skew --------------------------


# `leeway=N` where N > 300 (5 minutes). Effectively disables `exp`
# enforcement when the value is hours/days. We match common units:
# integer seconds, `timedelta(...)` calls, and shortcut expressions
# `60 * 60`, `60 * 60 * 24`. The regex covers up to 4-digit integers
# starting from 301; larger numbers via the multi-digit form.
_JWT_LEEWAY_LARGE_RE = _re(
    # leeway=<int>  where int > 300 (we list bounded buckets to keep
    # the regex RE2-safe; 4-5-6+ digit forms catch everything > 999).
    r"\bleeway\s*=\s*"
    r"(?:"
    # 301-999 (3-digit > 300): `[3-9]\d{2}` covers 300-999 but we need
    # >300; explicit ranges keep the floor strict.
    r"(?:3(?:0[1-9]|[1-9]\d)|[4-9]\d{2})"
    r"|"
    # 1000+ (4+ digits)
    r"[1-9]\d{3,}"
    r")"
    r"\b"
    r"|"
    # leeway=timedelta(seconds=<bigger>) / hours=N / minutes>5 / days=N
    r"\bleeway\s*=\s*timedelta\s*\(\s*"
    r"(?:hours\s*=\s*[1-9]\d*"
    r"|days\s*=\s*[1-9]\d*"
    r"|minutes\s*=\s*(?:[6-9]|[1-9]\d+)"
    r"|seconds\s*=\s*(?:3(?:0[1-9]|[1-9]\d)|[4-9]\d{2}|[1-9]\d{3,}))"
    r"|"
    # leeway=60*60 (an hour) / 60*60*24 (a day)
    r"\bleeway\s*=\s*60\s*\*\s*60\b"
    r"|"
    # Node jsonwebtoken: clockTolerance: 600 etc.
    r"\bclockTolerance\s*:\s*"
    r"(?:3(?:0[1-9]|[1-9]\d)|[4-9]\d{2}|[1-9]\d{3,})"
)


# ---- Rule P11: jwt.long-exp-stateless-no-revocation ---------------------


# `jwt.encode(...)` with an `exp` claim set to a long-lived value
# (>3600 seconds = 1 hour). We trigger on:
#  - `expires_delta=timedelta(days=N)` / `hours=N`  with N high
#  - `ACCESS_TOKEN_EXPIRE_MINUTES` / settings.<...> assigned to a value > 60
#  - Node `expiresIn: '24h'` / `'7d'` / `'30d'` literals
_JWT_LONG_EXP_RE = _re(
    # Python pydantic settings: ACCESS_TOKEN_EXPIRE_MINUTES = <big>
    r"\b(?:ACCESS_TOKEN_EXPIRE_MINUTES|JWT_EXPIRE_MINUTES|TOKEN_TTL_MINUTES)"
    r"\s*[:=]\s*(?:int\s*=\s*)?(?:[6-9]\d|[1-9]\d{2,})\b"
    r"|"
    # Python: expires_delta = timedelta(days=N) where N >= 1
    r"\bexpires_delta\s*=\s*timedelta\s*\(\s*days\s*=\s*[1-9]\d*"
    r"|"
    # Python: timedelta(hours=N) where N >= 2 (>1 hour is "long")
    r"\bexpires_delta\s*=\s*timedelta\s*\(\s*hours\s*=\s*(?:[2-9]|[1-9]\d+)"
    r"|"
    # Node jsonwebtoken: expiresIn: '24h' / '7d' / '30d' / '1y'
    r"\bexpiresIn\s*:\s*['\"](?:"
    # >=2h, any 2-digit h
    r"(?:[2-9]|\d{2,})\s*h"
    r"|"
    # any d
    r"\d+\s*d"
    r"|"
    # any y/w
    r"\d+\s*[yw]"
    r")['\"]"
    r"|"
    # Plain `exp = now + N * 3600` style — N >= 24 (1 day)
    r"\bexp\s*=\s*(?:now\s*\(\s*\)|datetime\.\w+\([^)\n]{0,40}\)|time\.\w+\(\s*\))"
    r"\s*\+\s*(?:[2-9]\d|[1-9]\d{2,})\s*\*\s*3600\b"
)


# File-level revocation-presence guards. If any of these appear ANYWHERE
# in the file, presume the developer has a revocation list / token-id
# tracker — drop the finding.
_JWT_REVOCATION_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bjti\b"),
    _re(r"\brevoked[_-]?(?:tokens?|jti|ids?)\b"),
    _re(r"\btoken[_-]?(?:blacklist|denylist|blocklist)\b"),
    _re(r"\bblacklist[_-]?token"),
    _re(r"\bdenylist[_-]?token"),
    _re(r"\.sismember\s*\(\s*['\"]revoked"),
    _re(r"\btoken[_-]?version\b"),
    _re(r"\bis_token_revoked\s*\("),
)


# ---- Rule P13: jwt.token-in-url-querystring -----------------------------


# JWT placed in URL query string — leaks via logs, Referer, history,
# proxies. Wave 17 catches `?access_token=` for OAuth; this rule
# extends to JWT-named fields and to direct JWT-token transport in URL.
_JWT_TOKEN_IN_URL_RE = _re(
    # URL templates: `/path?jwt=...` / `?id_token=`
    r"['\"`][^'\"`\n]{0,160}\?(?:jwt|id_token|access_jwt|bearer_token)="
    r"|"
    # Python: requests.<verb>(...?jwt=) / params={'jwt': ...}
    r"\b(?:requests|httpx|urllib|urlopen|aiohttp)[^)\n]{0,30}\(\s*"
    r"f?['\"][^'\"\n]{0,160}\?(?:jwt|id_token|access_jwt)="
    r"|"
    # urlencode({'jwt': tok})
    r"\burlencode\s*\(\s*\{[^}\n]{0,80}['\"](?:jwt|id_token|access_jwt)['\"]\s*:"
    r"|"
    # Python: requests.get(url, params={'jwt': tok})
    r"\bparams\s*=\s*\{[^}\n]{0,80}['\"](?:jwt|id_token|access_jwt|access_token)['\"]\s*:"
    r"|"
    # JS fetch URL string with ?jwt=
    r"\bfetch\s*\(\s*[`'\"][^`'\"\n]{0,160}\?(?:jwt|id_token|access_jwt)="
)


# ---- Rule P14: jwt.cookie-missing-httponly-secure -----------------------


# Cookie named token / jwt / access_token / session set without the
# critical hardening flags HttpOnly / Secure / SameSite.
_JWT_COOKIE_NAME_RE = _re(
    # res.cookie('token', val, {...})  — Express / Koa
    r"\b(?:res|response|ctx|reply)\.cookie\s*\(\s*"
    r"['\"](?:token|jwt|access_token|id_token|auth_token|session)['\"]\s*,"
    r"[^)\n]{0,300}"
    r"|"
    # Set-Cookie: token=...; (with no HttpOnly / Secure / SameSite)
    r"['\"]Set-Cookie['\"]\s*[:,]\s*[`'\"]"
    r"(?:token|jwt|access_token|id_token|auth_token|session)="
    r"[^\n]{0,300}"
    r"|"
    # Python Flask/FastAPI: response.set_cookie('jwt', value, ...)
    r"\b(?:response|resp|request)\.set_cookie\s*\(\s*"
    r"(?:key\s*=\s*)?['\"](?:token|jwt|access_token|id_token|auth_token|session)['\"]"
    r"[^)\n]{0,300}"
    r"|"
    # Django HttpResponse(...).set_cookie('jwt', ...)
    r"\bHttpResponse\b[^.]*\.set_cookie\s*\(\s*['\"]"
    r"(?:token|jwt|access_token|id_token|auth_token|session)['\"]"
)


# Hardening flag presence (any of these on the same call drops the
# severity); when ALL THREE are missing we fire.
_COOKIE_HTTPONLY_RE = _re(r"\bhttponly\s*[:=]\s*(?:true|True|1)\b")
_COOKIE_SECURE_RE = _re(r"\bsecure\s*[:=]\s*(?:true|True|1)\b")
_COOKIE_SAMESITE_RE = _re(
    r"\bsamesite\s*[:=]\s*['\"]?(?:lax|strict|Lax|Strict)\b"
)


# ---- Cross-rule context helpers ----------------------------------------


# Manifest / lockfile filename hints — Rule P3/P12 only applies to these.
_MANIFEST_FILENAME_HINTS: tuple[str, ...] = (
    "requirements.txt", "requirements-",
    "package.json", "package-lock.json",
    "pipfile", "pyproject.toml", "uv.lock", "poetry.lock",
    "constraints.txt", "yarn.lock", "pnpm-lock.yaml",
)


# Filename hints — test fixtures legitimately exercise weak shapes.
_TEST_FILENAME_HINTS: tuple[str, ...] = (
    "test", "fixture", "scenario", "spec", "example", "sample",
)


# Allowlist presence guards for P5/P6 — JKU / X5U fetches paired with a
# hardcoded JWKS-URI allowlist clearly intend to constrain the fetch.
_JWT_JKU_ALLOWLIST_GUARDS: tuple[re.Pattern, ...] = (
    # A `TRUSTED_JWKS_*` constant / set / list
    _re(r"\bTRUSTED_JWKS(?:_(?:URIS?|HOSTS?|URLS?))?\b"),
    _re(r"\bALLOWED_JWKS\b"),
    _re(r"\bjwks[_-]?allow(?:list|_uris)\b"),
    # Inline check: if jku not in {...}
    _re(r"if\s+jku\s+not\s+in\s+[\{\[]"),
    _re(r"if\s+header\s*\[\s*['\"]jku['\"]\s*\]\s+not\s+in\s+[\{\[]"),
)


# Allowlist presence guards for P4 — kid lookup paired with an allowlist.
_JWT_KID_ALLOWLIST_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bALLOWED_KIDS?\b"),
    _re(r"\bTRUSTED_KIDS?\b"),
    _re(r"\bKID_ALLOW(?:LIST)?\b"),
    _re(r"if\s+kid\s+not\s+in\s+[\{\[]"),
)


# File-level guards for P9 — verifier-side aud/iss kwargs anywhere mean
# the developer DOES validate (but may have missed on the specific call
# site we're flagging — still fire if the SPECIFIC call doesn't carry
# the kwarg).
_JWT_AUD_ISS_KWARG_RE = _re(
    r"\baudience\s*=\s*[A-Za-z_'\"]"
    r"|"
    r"\bissuer\s*=\s*[A-Za-z_'\"]"
)


# File-level: is `jwt.encode` adding `aud=` / `iss=` to tokens?
_JWT_ENCODE_WITH_AUD_ISS_RE = _re(
    r"\bjwt\.encode\s*\([^)\n]{0,400}"
    r"['\"]aud['\"]\s*:"
    r"|"
    r"\bjwt\.encode\s*\([^)\n]{0,400}"
    r"['\"]iss['\"]\s*:"
)


# File-level: is the file a REAL verifier (presence of jwt.decode with
# proper verify) — used to drop P8b unverified-claims-as-identity when
# the file ALSO has a verifying decode call.
_JWT_REAL_VERIFY_RE = _re(
    # jwt.decode(...) without 'verify=False' and without options that
    # disable verify_signature. Hard to express purely in regex, so we
    # match any jwt.decode(...) call that is NOT followed within 200
    # chars by 'verify=False' / 'verify_signature: False'. We use a
    # POSITIVE pattern combined with a Stage-B check in scan_text().
    r"\bjwt\.decode\s*\("
)


# Vulnerable-version manifest line guards — used to constrain P3/P12 to
# manifest files only.
_MANIFEST_LINE_HINT_RE = _re(
    r"\bpython-jose\b|\bPyJWT\b|\bjsonwebtoken\b|\bjwt-decode\b|\bjose\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="jwt.algorithm-from-env-or-config",
        name="JWT algorithm loaded from env / config (not pinned in source)",
        severity="HIGH",
        description=(
            "`jwt.decode(..., algorithms=[<expr>])` or `jwt.encode(..., "
            "algorithm=<expr>)` where the algorithm comes from a variable, "
            "`settings.<attr>`, `os.environ`, etc. instead of a literal "
            "string list. Wave 18 catches the literal `none` form; this "
            "is the deeper variant where an attacker who can write the "
            "`.env` flips `ALGORITHM=none` and the regex never sees it. "
            "Pin the algorithm as a literal in source. Reference: "
            "distill-round-7 P1, CodeSentinel/auth.py:37 evidence."
        ),
        pattern=_JWT_ALG_FROM_ENV_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.verify-no-algorithms-allowlist",
        name="jsonwebtoken/JWT verify() against PEM/public-key with no algorithms list",
        severity="CRITICAL",
        description=(
            "`jsonwebtoken.verify(token, publicKey)` / `jwt.verify(...)` "
            "called with a PEM / public-key / cert second argument and "
            "NO `algorithms:` option. In `jsonwebtoken < 9.0` the default "
            "accepts whatever `alg` the header advertises — attacker "
            "forges `alg=HS256` signed with the PUBLIC KEY as the HMAC "
            "secret (RS/HS algorithm confusion, CVE-2022-23529 family). "
            "Always pass `algorithms: ['RS256']` (or the exact set you "
            "expect). Reference: distill-round-7 P2/P15."
        ),
        pattern=_JWT_VERIFY_NO_ALG_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.vulnerable-library-version",
        name="Known-vulnerable JWT library version pinned in manifest",
        severity="HIGH",
        description=(
            "Dependency manifest / lockfile pins a JWT library at a "
            "version with public CVEs: `python-jose < 3.4.0` (algorithm "
            "confusion CVE-2024-33663 family), `PyJWT < 2.0` "
            "(pre-default-verify era), `jsonwebtoken < 9.0` "
            "(CVE-2022-23529/23539/23540/23541), `jose < 4.0` (npm), or "
            "ANY pin of `jwt-decode` (decode-only library frequently "
            "misused as a verifier). Upgrade to the post-fix version. "
            "Reference: distill-round-7 P3/P12."
        ),
        pattern=_JWT_VULN_LIB_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="jwt.kid-header-used-as-unsafe-lookup",
        name="JWT `kid` header concatenated into filesystem path / SQL / cache key",
        severity="CRITICAL",
        description=(
            "`kid` (Key ID) from the JWT header — attacker-controlled — "
            "flows into a filesystem path (`open(f'keys/{kid}.pem')`), "
            "a SQL query string-format, or a cache lookup key without an "
            "allowlist check. Enables path traversal "
            "(`../../etc/passwd`), SQL injection via the header, or "
            "cache poisoning. The resolver MUST validate `kid` against a "
            "static allowlist BEFORE using it as an identifier. "
            "Reference: distill-round-7 P4."
        ),
        pattern=_JWT_KID_PATH_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jwt.jku-header-fetched-unrestricted",
        name="JWT `jku` header URL HTTP-fetched without allowlist",
        severity="CRITICAL",
        description=(
            "Verifier fetches a JWKS URL extracted from the token "
            "header's `jku` field. Attacker hosts `attacker.example/jwks.json` "
            "with their public key, sets `jku` to that URL, and signs "
            "the token with the matching private key. The verifier "
            "fetches, gets the key, validates the signature, accepts. "
            "Restrict to a static allowlist of trusted JWKS endpoints. "
            "Reference: distill-round-7 P5."
        ),
        pattern=_JWT_JKU_FETCH_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jwt.x5u-header-fetched-unrestricted",
        name="JWT `x5u` header URL HTTP-fetched without allowlist + chain validation",
        severity="CRITICAL",
        description=(
            "Verifier fetches an X.509 cert URL from the token header's "
            "`x5u` field. Same trust-the-attacker dynamic as `jku` "
            "(P5). Restrict to an allowlist AND validate the returned "
            "certificate chain up to a configured trust anchor. "
            "Reference: distill-round-7 P6."
        ),
        pattern=_JWT_X5U_FETCH_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jwt.x5c-header-chain-trusted-inline",
        name="JWT `x5c[0]` cert read inline and used as verification key",
        severity="CRITICAL",
        description=(
            "The token header's `x5c` array carries the cert chain "
            "inline. Lazy verifiers read `header['x5c'][0]`, extract the "
            "public key, verify the signature, and do NOT validate the "
            "chain. Attacker supplies a self-signed cert with any "
            "subject, signs the token, wins. Always chain-validate to a "
            "pinned trust anchor and check Subject/Issuer/notBefore/"
            "notAfter/EKU before trusting the key. "
            "Reference: distill-round-7 P7."
        ),
        pattern=_JWT_X5C_INLINE_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="jwt.decode-options-verify-signature-false",
        name="`jwt.decode(..., options={'verify_signature': False})` disable path",
        severity="CRITICAL",
        description=(
            "PyJWT / python-jose have a separate `options=` dict where "
            "individual checks can be turned OFF. `verify_signature: "
            "False`, `verify_exp: False`, `verify_aud: False`, etc. — "
            "any one converts `jwt.decode` into a TRUSTING parse of "
            "attacker-controlled JSON. Also catches legacy "
            "`jwt.decode(..., verify=False)` and Node "
            "`jwt.verify(..., {ignoreExpiration: true})`. "
            "Reference: distill-round-7 P8."
        ),
        pattern=_JWT_VERIFY_SIG_FALSE_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="jwt.unverified-claims-as-identity",
        name="`get_unverified_claims` / `get_unverified_header` / `jwt-decode` used to identify user",
        severity="HIGH",
        description=(
            "`jwt.get_unverified_claims(...)` / "
            "`jwt.get_unverified_header(...)` / `jsonwebtoken.decode(...)` "
            "/ import of `jwt-decode` — these are DECODE-only "
            "operations. If the result is used to make an authentication "
            "or authorisation decision without a subsequent verify call, "
            "attacker-forged tokens are accepted. The Stage-B file-level "
            "guard suppresses when the file ALSO contains a real "
            "verifying `jwt.decode(...)`. Reference: distill-round-7 P8."
        ),
        pattern=_JWT_UNVERIFIED_CLAIMS_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.decode-missing-audience-or-issuer",
        name="`jwt.decode(...)` without `audience=` / `issuer=` kwarg",
        severity="HIGH",
        description=(
            "Verifier-side omission of `audience=` / `issuer=` on "
            "`jwt.decode` / `jose.jwt.decode` / `jsonwebtoken.verify`. "
            "Even if the token contains valid `aud`/`iss` claims (Wave "
            "18's surface check), an unset verifier kwarg ignores them. "
            "A token issued for service A is accepted by service B "
            "(cross-service confused deputy). Wave 18 catches missing "
            "claims INSIDE tokens; this is the deeper symmetric check. "
            "Reference: distill-round-7 P9."
        ),
        pattern=_JWT_DECODE_TRIGGER_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.leeway-excessive-clock-skew",
        name="JWT `leeway` / `clockTolerance` set > 300 seconds (5 min)",
        severity="MEDIUM",
        description=(
            "`jwt.decode(..., leeway=N)` / Node "
            "`jwt.verify(..., {clockTolerance: N})` where N > 300 "
            "seconds effectively disables expiration enforcement. A "
            "common copy-paste from Stack Overflow answers fixing "
            "\"JWT expired in tests\" — accepts tokens up to N seconds "
            "past their `exp`. Combined with long `exp` (P11) tokens "
            "become effectively immortal. Reference: distill-round-7 P10."
        ),
        pattern=_JWT_LEEWAY_LARGE_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.long-exp-stateless-no-revocation",
        name="Long-lived (>1h) JWT exp with no server-side revocation",
        severity="HIGH",
        description=(
            "Access JWT with `exp > 1 hour` AND the file shows no "
            "revocation list / token-version check / `jti` blacklist. "
            "Password reset, role demotion, session logout = ignored "
            "until exp. Combined with fat payloads (roles + permissions "
            "embedded), one issuance is a 24-hour gap of unrevokable "
            "authority. Reference: distill-round-7 P11, "
            "CodeSentinel/config.py:13 evidence (24h ACCESS_TOKEN)."
        ),
        pattern=_JWT_LONG_EXP_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jwt.token-in-url-querystring",
        name="JWT placed in URL query string (logs / Referer / history leak)",
        severity="HIGH",
        description=(
            "`?jwt=...` / `?id_token=...` / `?access_jwt=...` in a URL "
            "string or in `params={'jwt': ...}` outbound HTTP call. "
            "Tokens leak through web-server access logs, browser "
            "history, Referer headers, intermediate proxies, and HTML "
            "`<a href>` exfiltration. Wave 17 catches OAuth tokens in "
            "the URL; this rule extends to JWT-named fields. Use the "
            "Authorization header or POST body. "
            "Reference: distill-round-7 P13."
        ),
        pattern=_JWT_TOKEN_IN_URL_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="jwt.cookie-missing-httponly-secure",
        name="JWT cookie set without HttpOnly / Secure / SameSite flags",
        severity="HIGH",
        description=(
            "A cookie named `token` / `jwt` / `access_token` / "
            "`id_token` / `auth_token` / `session` is set but the call "
            "omits ALL of HttpOnly, Secure, and SameSite. JS-readable "
            "cookies are XSS-exfiltrable; non-Secure cookies leak over "
            "HTTP downgrades; cookies without SameSite are CSRF-able. "
            "Set `httpOnly: true, secure: true, sameSite: 'lax'` (or "
            "stricter). Reference: distill-round-7 P14."
        ),
        pattern=_JWT_COOKIE_NAME_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="jwt.rsa-key-with-hs-algorithm-allowed",
        name="JWT verifier loads RSA public key but allows HS* algorithm",
        severity="CRITICAL",
        description=(
            "Specific HS/RS algorithm-confusion vector: code loads an "
            "RSA public key (`load_pem_x509_certificate`, "
            "`rsa.PublicKey.load_pkcs1`, `*.pem` file read) AND the "
            "verifier's `algorithms=` list contains an HS* family entry "
            "(or is omitted entirely on a vulnerable library). Attacker "
            "forges a token with `alg=HS256` signed using the PUBLIC "
            "KEY BYTES as the HMAC secret — verifier picks up HS256 "
            "from the header, treats the public key as the HMAC key, "
            "accepts. Reference: distill-round-7 P15."
        ),
        pattern=_re(
            # jwt.decode(..., algorithms=['HS256', 'RS256']) — any HS+RS mix
            # Note: [^)\n] excludes ')' so the bounded window stops on the
            # close-paren before reaching the algorithms list. Use [^\n]
            # to tolerate nested calls (fs.readFileSync('pub.pem')) on the
            # same line. RE2-safe: bounded inline window.
            r"\bjwt\.decode\s*\([^\n]{0,300}\balgorithms\s*=\s*\[[^\]\n]{0,200}"
            r"(?:['\"]HS\d{3}['\"][^\]\n]{0,80}['\"]RS\d{3}['\"]"
            r"|['\"]RS\d{3}['\"][^\]\n]{0,80}['\"]HS\d{3}['\"])"
            r"|"
            # Node: jwt.verify(token, fs.readFileSync(...pem...), {algorithms: ['HS256','RS256']})
            r"\b(?:jsonwebtoken|jwt)\.verify\s*\([^\n]{0,300}algorithms\s*:\s*\["
            r"[^\]\n]{0,200}"
            r"(?:['\"]HS\d{3}['\"][^\]\n]{0,80}['\"]RS\d{3}['\"]"
            r"|['\"]RS\d{3}['\"][^\]\n]{0,80}['\"]HS\d{3}['\"])"
        ),
        owasp_asi="ASI-07",
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _preceding_lines(text: str, line_no: int, window: int = 5) -> str:
    """Return previous `window` lines + the target line itself."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - window)
    end = min(len(lines), line_no)
    return "\n".join(lines[start:end])




def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _filename_matches_any(filename: str, hints: tuple[str, ...]) -> bool:
    """True if the filename (case-insensitive) contains any hint."""
    if not filename:
        return False
    lower = filename.lower()
    return any(h in lower for h in hints)


def _call_text_after(text: str, start_offset: int, max_chars: int = 400) -> str:
    """Return up to `max_chars` of text following the start of a call,
    stopping at the next blank line. Used to inspect the kwargs of a
    function call that may span multiple lines."""
    snippet = text[start_offset:start_offset + max_chars]
    # Stop at a blank line — calls rarely span more than one.
    idx = snippet.find("\n\n")
    if idx > 0:
        snippet = snippet[:idx]
    return snippet


def scan_text(
    text: str,
    *,
    file_kind: str = "prose",
    filename: str = "",
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` is accepted for parity with sibling pattern modules but
    is currently informational only — every rule fires across both
    "prose" and "source" inputs.

    `filename` controls per-rule allowlists:

      Rule jwt.vulnerable-library-version    : ONLY fires inside manifest
                                               files (requirements.txt,
                                               package.json, etc.).
      Rule jwt.kid-header-used-as-unsafe-lookup : suppressed if file
                                               contains a `kid` allowlist
                                               marker.
      Rule jwt.jku-header-fetched-unrestricted  : suppressed if file
                                               contains a JWKS allowlist
                                               marker.
      Rule jwt.unverified-claims-as-identity    : suppressed if file
                                               contains a verifying
                                               `jwt.decode` (no
                                               verify=False).
      Rule jwt.decode-missing-audience-or-issuer:
                                               Stage-B inspects the
                                               SPECIFIC call text — if
                                               the call has audience= or
                                               issuer= already, drop.
      Rule jwt.long-exp-stateless-no-revocation : suppressed if file
                                               contains a revocation /
                                               jti / blacklist marker.
      Rule jwt.cookie-missing-httponly-secure   : suppressed if the
                                               cookie call carries
                                               HttpOnly+Secure+SameSite.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    del file_kind  # accepted for parity with sibling modules; not branched on

    # File-level guard evaluation (one shot per file for cheap rules).
    file_has_revocation = _file_contains_any(text, _JWT_REVOCATION_GUARDS)
    file_has_kid_allowlist = _file_contains_any(text, _JWT_KID_ALLOWLIST_GUARDS)
    file_has_jku_allowlist = _file_contains_any(text, _JWT_JKU_ALLOWLIST_GUARDS)
    # P8b suppression: file contains a verifying decode that does NOT
    # have verify=False on its same line. We approximate by: any
    # jwt.decode(...) call whose call-text does NOT contain
    # "verify=False" or "verify_signature: False".
    file_has_real_verify = False
    for vm in _JWT_REAL_VERIFY_RE.finditer(text):
        call_txt = _call_text_after(text, vm.start(), max_chars=400)
        # Reject the decode if it disables signature verification.
        if (
            re.search(r"\bverify\s*=\s*False\b", call_txt) is None
            and re.search(
                r"['\"]verify_signature['\"]\s*:\s*(?:False|false|0)",
                call_txt,
            ) is None
        ):
            file_has_real_verify = True
            break

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _add(rule: Rule, m: re.Match, ln: int, col: int) -> None:
        key = (rule.id, ln, col)
        if key in seen:
            return
        seen.add(key)
        matched = m.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule.id,
            line=ln,
            column=col,
            matched_text=matched,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            ln_text = _line_text(text, line)
            ctx = _preceding_lines(text, line, window=3)

            # Per-rule Stage-B filters.
            if rule.id == "jwt.vulnerable-library-version":
                # Manifest gate — only fire inside dependency manifests.
                if not _filename_matches_any(filename, _MANIFEST_FILENAME_HINTS):
                    continue
                # And require the line itself to mention a JWT lib name
                # — the pattern is broad enough that a stray version
                # string elsewhere would fire FP.
                if _MANIFEST_LINE_HINT_RE.search(ln_text) is None:
                    continue
            elif rule.id == "jwt.kid-header-used-as-unsafe-lookup":
                if file_has_kid_allowlist:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.jku-header-fetched-unrestricted":
                if file_has_jku_allowlist:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.x5u-header-fetched-unrestricted":
                if file_has_jku_allowlist:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.x5c-header-chain-trusted-inline":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.unverified-claims-as-identity":
                # Suppress when the file ALSO has a real verifying
                # decode call — the developer is using
                # get_unverified_header for routing and a real verify
                # downstream.
                if file_has_real_verify:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.decode-missing-audience-or-issuer":
                # Stage-B: inspect the specific call's text for
                # audience= / issuer= kwargs. If present, drop.
                call_txt = _call_text_after(text, m.start(), max_chars=400)
                if _JWT_AUD_ISS_KWARG_RE.search(call_txt) is not None:
                    continue
                # If the file NEVER calls jwt.encode with aud/iss
                # claims, presume it's a relay-only / decode-only flow
                # and drop. Less noise on logger / debug code.
                if _JWT_ENCODE_WITH_AUD_ISS_RE.search(text) is None:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.long-exp-stateless-no-revocation":
                if file_has_revocation:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.cookie-missing-httponly-secure":
                # The matched call-text is right there — check for
                # the three flags. If ALL three present, drop. We
                # tolerate any two missing flags as a "fire" condition.
                matched_text = m.group(0)
                has_httponly = _COOKIE_HTTPONLY_RE.search(matched_text) is not None
                has_secure = _COOKIE_SECURE_RE.search(matched_text) is not None
                has_samesite = _COOKIE_SAMESITE_RE.search(matched_text) is not None
                if has_httponly and has_secure and has_samesite:
                    continue
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.algorithm-from-env-or-config":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.verify-no-algorithms-allowlist":
                # Already narrowed via PEM/pubkey-shaped second arg.
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
                # If the call-text contains algorithms: anywhere, drop —
                # developer DID provide an allowlist (the broad capture
                # may have included a closing-paren after the list).
                call_txt = _call_text_after(text, m.start(), max_chars=300)
                if re.search(r"\balgorithms\s*:", call_txt) is not None:
                    continue
            elif rule.id == "jwt.leeway-excessive-clock-skew":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.token-in-url-querystring":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
            elif rule.id == "jwt.decode-options-verify-signature-false":
                # Decoding without verifying is legitimate in test
                # fixtures (parsing test vectors). Suppress on test
                # files. Documentation example pragma also OK.
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue
                if re.search(
                    r"(?:#|//)\s*(?:test|fixture|example|documentation)\b",
                    ctx,
                ) is not None:
                    continue
            elif rule.id == "jwt.rsa-key-with-hs-algorithm-allowed":
                if _filename_matches_any(filename, _TEST_FILENAME_HINTS):
                    continue

            _add(rule, m, line, col)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
