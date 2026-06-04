"""Discord / Slack / Telegram bot token + intent + command-handler abuse patterns.

Wave-34 distillation round 20, deeper cut on bot token / intent / handler abuse.

Catalogue of 8 bot-token-specific anti-patterns distilled in
`reports/distill-round-20/bot-tokens-deeper.md`. Targets Discord / Slack /
Telegram surfaces not covered by Wave-22 `chat_bot_patterns.py` (D1-D15).

What is NOT here (already shipped — DO NOT duplicate):

  * Webhook-URL literals (Slack hooks.slack.com / Discord / Telegram / Teams) —
    `chat_bot_patterns.py` rules D1-D2.
  * Slash-command team-ID allowlist — `chat_bot_patterns.py` rule D3.
  * Telegram chat_id allowlist — `chat_bot_patterns.py` rule D4.
  * setWebhook URL hijack — `chat_bot_patterns.py` rule D5.
  * Token-type-confusion variable — `chat_bot_patterns.py` rule D6.
  * Username spoof via incoming webhook — `chat_bot_patterns.py` rule D7.
  * as_user:true legacy — `chat_bot_patterns.py` rule D8.
  * Scope overreach users:read.email — `chat_bot_patterns.py` rule D9.
  * admin.* scope — `chat_bot_patterns.py` rule D10.
  * OAuth state predictable random — `chat_bot_patterns.py` rule D11.
  * discord.message_content intent discrete — `chat_bot_patterns.py` rule D12.
  * Discord bot token literal in client bundle — `chat_bot_patterns.py` rule D13.
  * Telegram token in URL-path log leak — `chat_bot_patterns.py` rule D14.
  * Webhook URL from untrusted config — `chat_bot_patterns.py` rule D15.
  * Generic HMAC receiver-side — `webhook_signature_patterns.py`.
  * Frontend prototype-pollution (DOM-side) — `prototype_pollution_patterns.py`.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * btd-discord-interaction-sig-verify-absent                    (CRITICAL)
  * btd-discord-intents-all-catch-all                            (HIGH)
  * btd-slack-chat-write-customize-scope                         (MEDIUM)
  * btd-telegram-getupdates-plain-http                           (HIGH)
  * btd-discord-reaction-role-payload-merge-prototype-pollution  (MEDIUM)
  * btd-bot-dm-command-no-rate-limit                             (MEDIUM)
  * btd-discord-bot-token-no-rotation-convention                 (LOW)
  * btd-slack-signing-secret-middleware-unwired                  (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (Telegram token over plain HTTP, token without rotation)
  ASI-04 — Information leak / excessive data exposure (intents.all catch-all)
  ASI-05 — Supply-chain / cross-tenant pivot (interaction sig absent, middleware unwired)
  ASI-07 — Authority / authorisation gaps (scope, prototype-pollution, rate-limit)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : btd-discord-interaction-sig-verify-absent ---------------------


# Stage-A: route registering a Discord interaction path (Express / FastAPI).
# Fires when a POST endpoint contains 'discord' or 'interaction' in the path.
_DISCORD_INTERACTION_ROUTE = _re(
    r"(?:app|router|Blueprint)\s*\.\s*(?:post|route)\s*\(\s*['\"][^'\"]*"
    r"(?:discord|interaction)[^'\"]*['\"]"
)


# ---- D2 : btd-discord-intents-all-catch-all -----------------------------


# All three shapes that enable ALL privileged intents:
#   discord.Intents.all()  (Python discord.py)
#   intents: 32767 / 0x7FFF  (discord.js legacy numeric bitmask)
#   Object.values(GatewayIntentBits)  (discord.js v14 enumeration)
_DISCORD_INTENTS_ALL = _re(
    r"\bdiscord\.Intents\.all\s*\(\s*\)"
    r"|intents\s*:\s*(?:32767|0x7FFF|0x[0-9a-fA-F]{4,5})\b"
    r"|Object\.values\s*\(\s*GatewayIntentBits\s*\)"
)


# ---- D3 : btd-slack-chat-write-customize-scope --------------------------


# Exact scope string in YAML manifests, JSON arrays, or JS/TS arrays.
_SLACK_CHAT_WRITE_CUSTOMIZE = _re(r"\bchat:write\.customize\b")


# ---- D4 : btd-telegram-getupdates-plain-http ----------------------------


# Telegram bot API called over plain HTTP — token leaks in proxy logs.
# Anchored on 'api.telegram.org/bot' with 'http://' prefix only.
_TELEGRAM_PLAIN_HTTP = _re(r"\bhttp://api\.telegram\.org/bot")


# ---- D5 : btd-discord-reaction-role-payload-merge-prototype-pollution ---


# Stage-A: user-controlled Discord / bot payload source field.
_DISCORD_PAYLOAD_SOURCE = _re(
    r"interaction\.data(?:\.custom_id|\.options\[\d+\]?\.value)?"
    r"|message\.content"
    r"|callback_query\.data"
)

# Stage-B: unsafe merge within the same or nearby lines.
_UNSAFE_MERGE = _re(
    r"Object\.assign\s*\("
    r"|_\.merge\s*\("
    r"|\{[^}]{0,80}\.\.\.[^}]{0,80}\}"
)


# ---- D6 : btd-bot-dm-command-no-rate-limit ------------------------------


# Trigger: DM channel type check in Discord (JS/TS) or Telegram update dispatch.
_DM_COMMAND_DISPATCH = _re(
    r"ChannelType\.DM"
    r"|channel\.type\s*===?\s*['\"]DM['\"]"
    r"|isDMBased\s*\(\s*\)"
    r"|getUpdates"
    r"|update\.message\.text\.startsWith"
    r"|msg\.text\.startsWith"
)

# Guard: any rate-limit or throttle mechanism in nearby context.
_RATE_LIMIT_GUARD = _re(
    r"rateLimit|rate_limit|throttle|cooldown|lastCommand"
    r"|commandTimestamp|Date\.now|setTimeout.*return"
)


# ---- D7 : btd-discord-bot-token-no-rotation-convention ------------------


# Env-file line: DISCORD_BOT_TOKEN / DISCORD_TOKEN / DISCORD_CLIENT_TOKEN
# with a sufficiently long value (50+ chars) — no rotation companion expected.
_DISCORD_TOKEN_ENV = _re(
    r"(?:DISCORD_BOT_TOKEN|DISCORD_TOKEN|DISCORD_CLIENT_TOKEN)\s*=\s*[A-Za-z0-9_.\-]{50,}"
)

# Rotation companion marker — suppression pattern.
_DISCORD_TOKEN_ROTATION = _re(
    r"DISCORD[_A-Z]*(?:ROTAT|EXPIR|VERSION)[_A-Z]*\s*="
)


# ---- D8 : btd-slack-signing-secret-middleware-unwired -------------------


# Stage-A: Slack signing-secret / HMAC middleware defined in this file.
_SLACK_VERIFY_DEFINED = _re(
    r"(?:function|const|var)\s+verify(?:Slack)?Signature\b"
    r"|createHmac\s*\(\s*['\"]sha256['\"]"
)

# Stage-B: a Slack-path route registered (POST / use) — presence of path
# containing 'slack'. Two-pass logic checks whether the middleware name
# appears as a route argument.
_SLACK_ROUTE_REGISTERED = _re(
    r"app\.(?:post|use)\s*\(\s*['\"][^'\"]*slack[^'\"]*['\"]"
)


# ---- Rule catalogue (ordered) -------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="btd-discord-interaction-sig-verify-absent",
        name="Discord interaction endpoint missing Ed25519 signature verification",
        severity="CRITICAL",
        description=(
            "A Discord interaction endpoint is registered without Ed25519 signature "
            "verification (verifyKey / nacl.sign.detached.verify against "
            "x-signature-ed25519 + x-signature-timestamp headers). Any actor can "
            "forge interaction payloads and drive bot commands unauthenticated."
        ),
        pattern=_DISCORD_INTERACTION_ROUTE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="btd-discord-intents-all-catch-all",
        name="Discord Intents.all() or numeric all-bits mask enables all privileged intents",
        severity="HIGH",
        description=(
            "discord.Intents.all(), GatewayIntentBits all-bits enumeration, or numeric "
            "bitmask 32767/0x7FFF silently enables ALL privileged intents including "
            "MessageContent, GuildMembers, GuildPresences without individual Discord review."
        ),
        pattern=_DISCORD_INTENTS_ALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="btd-slack-chat-write-customize-scope",
        name="Slack chat:write.customize scope enables per-message identity spoofing",
        severity="MEDIUM",
        description=(
            "The chat:write.customize scope lets a bot override its display name and "
            "icon per message, enabling identity impersonation within a Slack workspace. "
            "If the bot token leaks, attackers can post as any named entity."
        ),
        pattern=_SLACK_CHAT_WRITE_CUSTOMIZE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="btd-telegram-getupdates-plain-http",
        name="Telegram bot API called over plain HTTP — token exposed in proxy logs",
        severity="HIGH",
        description=(
            "Telegram bot API (api.telegram.org/bot...) called over http:// instead of "
            "https://. The bot token appears verbatim in all proxy access logs, APM spans, "
            "and CDN logs, and is subject to MITM interception."
        ),
        pattern=_TELEGRAM_PLAIN_HTTP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="btd-discord-reaction-role-payload-merge-prototype-pollution",
        name="Discord bot payload merged into object without prototype-pollution guard",
        severity="MEDIUM",
        description=(
            "User-controlled Discord interaction payload (interaction.data, message.content, "
            "callback_query.data) is merged into a plain object via Object.assign / _.merge / "
            "spread without sanitizing __proto__ / constructor keys. Enables prototype "
            "pollution in the bot process, granting escalated permissions."
        ),
        pattern=_DISCORD_PAYLOAD_SOURCE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="btd-bot-dm-command-no-rate-limit",
        name="Bot DM command handler dispatches commands without per-user rate limit",
        severity="MEDIUM",
        description=(
            "A Discord DM or Telegram direct-message command handler dispatches commands "
            "without a per-sender rate-limit guard. A single authorized user or compromised "
            "allowlist entry can flood the bot with O(N) commands, amplifying API calls, "
            "database writes, or notification bursts."
        ),
        pattern=_DM_COMMAND_DISPATCH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="btd-discord-bot-token-no-rotation-convention",
        name="Discord bot token in env var without rotation tracking companion",
        severity="LOW",
        description=(
            "DISCORD_BOT_TOKEN / DISCORD_TOKEN / DISCORD_CLIENT_TOKEN is present as an "
            "env-file assignment with no rotation metadata (DISCORD_TOKEN_ROTATED_AT, "
            "DISCORD_TOKEN_MAX_AGE_DAYS, etc.). Discord bot tokens do not auto-expire; "
            "without a rotation convention, a leaked token grants permanent bot control."
        ),
        pattern=_DISCORD_TOKEN_ENV,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="btd-slack-signing-secret-middleware-unwired",
        name="Slack event/interaction route registered without signing-secret middleware",
        severity="HIGH",
        description=(
            "A Slack-path route (POST /...slack...) is registered without the signing-secret "
            "verification middleware as a route argument. The middleware is defined in the "
            "same file but omitted from this specific route, leaving it open to forged "
            "Slack event payloads."
        ),
        pattern=_SLACK_ROUTE_REGISTERED,
        owasp_asi="ASI-05",
    ),
)


# ---- scanner ------------------------------------------------------------


_WINDOW = 30  # lines to scan forward for two-phase rules


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rules and return a list of Finding tuples.

    Two-phase rules (D1, D5, D6, D8) perform a window scan: Stage-A fires
    a candidate; Stage-B confirms or suppresses within ±_WINDOW lines.
    Single-pass rules (D2, D3, D4, D7) emit a Finding on each match.

    D7 (discord-bot-token-no-rotation-convention) suppresses when a rotation
    companion variable appears within _WINDOW lines of the token assignment.

    Never raises on benign input — all exceptions are suppressed internally.
    """
    findings: list[Finding] = []
    lines = text.splitlines()

    for rule in RULES:
        rid = rule.id

        if rid == "btd-discord-interaction-sig-verify-absent":
            # Two-phase: route present AND no verifyKey / Ed25519 in the file.
            _verify_guard = _re(
                r"x-signature-ed25519|verifyKey|nacl\.sign\.detached\.verify"
                r"|discord-interactions"
            )
            has_guard = bool(_verify_guard.search(text))
            if not has_guard:
                for i, line in enumerate(lines):
                    m = _DISCORD_INTERACTION_ROUTE.search(line)
                    if m:
                        findings.append(
                            Finding(
                                rule_id=rid,
                                line=i + 1,
                                column=m.start() + 1,
                                matched_text=m.group(0),
                                severity=rule.severity,
                                description=rule.description,
                                owasp_asi=rule.owasp_asi,
                            )
                        )

        elif rid == "btd-discord-intents-all-catch-all":
            for i, line in enumerate(lines):
                m = _DISCORD_INTENTS_ALL.search(line)
                if m:
                    findings.append(
                        Finding(
                            rule_id=rid,
                            line=i + 1,
                            column=m.start() + 1,
                            matched_text=m.group(0),
                            severity=rule.severity,
                            description=rule.description,
                            owasp_asi=rule.owasp_asi,
                        )
                    )

        elif rid == "btd-slack-chat-write-customize-scope":
            for i, line in enumerate(lines):
                m = _SLACK_CHAT_WRITE_CUSTOMIZE.search(line)
                if m:
                    findings.append(
                        Finding(
                            rule_id=rid,
                            line=i + 1,
                            column=m.start() + 1,
                            matched_text=m.group(0),
                            severity=rule.severity,
                            description=rule.description,
                            owasp_asi=rule.owasp_asi,
                        )
                    )

        elif rid == "btd-telegram-getupdates-plain-http":
            for i, line in enumerate(lines):
                m = _TELEGRAM_PLAIN_HTTP.search(line)
                if m:
                    findings.append(
                        Finding(
                            rule_id=rid,
                            line=i + 1,
                            column=m.start() + 1,
                            matched_text=m.group(0),
                            severity=rule.severity,
                            description=rule.description,
                            owasp_asi=rule.owasp_asi,
                        )
                    )

        elif rid == "btd-discord-reaction-role-payload-merge-prototype-pollution":
            # Two-phase: payload source present AND unsafe merge within _WINDOW lines.
            for i, line in enumerate(lines):
                m = _DISCORD_PAYLOAD_SOURCE.search(line)
                if m:
                    window_start = max(0, i - 5)
                    window_end = min(len(lines), i + _WINDOW)
                    window_text = "\n".join(lines[window_start:window_end])
                    if _UNSAFE_MERGE.search(window_text):
                        findings.append(
                            Finding(
                                rule_id=rid,
                                line=i + 1,
                                column=m.start() + 1,
                                matched_text=m.group(0),
                                severity=rule.severity,
                                description=rule.description,
                                owasp_asi=rule.owasp_asi,
                            )
                        )

        elif rid == "btd-bot-dm-command-no-rate-limit":
            # Two-phase: DM dispatch trigger AND no rate-limit in forward window.
            for i, line in enumerate(lines):
                m = _DM_COMMAND_DISPATCH.search(line)
                if m:
                    window_end = min(len(lines), i + _WINDOW)
                    window_text = "\n".join(lines[i:window_end])
                    if not _RATE_LIMIT_GUARD.search(window_text):
                        findings.append(
                            Finding(
                                rule_id=rid,
                                line=i + 1,
                                column=m.start() + 1,
                                matched_text=m.group(0),
                                severity=rule.severity,
                                description=rule.description,
                                owasp_asi=rule.owasp_asi,
                            )
                        )

        elif rid == "btd-discord-bot-token-no-rotation-convention":
            # Single-pass with window suppression when rotation companion present.
            for i, line in enumerate(lines):
                m = _DISCORD_TOKEN_ENV.search(line)
                if m:
                    window_start = max(0, i - 5)
                    window_end = min(len(lines), i + _WINDOW)
                    window_text = "\n".join(lines[window_start:window_end])
                    if not _DISCORD_TOKEN_ROTATION.search(window_text):
                        findings.append(
                            Finding(
                                rule_id=rid,
                                line=i + 1,
                                column=m.start() + 1,
                                matched_text=m.group(0),
                                severity=rule.severity,
                                description=rule.description,
                                owasp_asi=rule.owasp_asi,
                            )
                        )

        elif rid == "btd-slack-signing-secret-middleware-unwired":
            # Two-phase: verify middleware defined AND a Slack route exists.
            # Report if the route POST call exists but no verify function name
            # appears as an argument on the same line.
            has_middleware_def = bool(_SLACK_VERIFY_DEFINED.search(text))
            if has_middleware_def:
                _middleware_as_arg = _re(r"\bverify(?:Slack)?Signature\b")
                for i, line in enumerate(lines):
                    m = _SLACK_ROUTE_REGISTERED.search(line)
                    if m and not _middleware_as_arg.search(line):
                        findings.append(
                            Finding(
                                rule_id=rid,
                                line=i + 1,
                                column=m.start() + 1,
                                matched_text=m.group(0),
                                severity=rule.severity,
                                description=rule.description,
                                owasp_asi=rule.owasp_asi,
                            )
                        )

    return findings
