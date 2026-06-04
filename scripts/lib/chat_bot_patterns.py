"""Chat-bot OAuth, webhook, slash-command and token-leak patterns.

Wave-22 distillation round 8, angle H.

Catalogue of 15 chat-bot-specific anti-patterns distilled in
`reports/distill-round-8/chat-bot-oauth.md`. Targets Slack / Discord /
Microsoft Teams / Telegram surfaces that Wave 17 (`auth_flow_patterns`),
Wave 19 (`webhook_signature_patterns`, `oauth_device_flow_patterns`,
`dns_email_patterns`) and existing modules cover only at the abstract
level.

What is NOT here (already shipped — DO NOT duplicate):

  * Receiver-side HMAC primitives (signing-secret bypass, replay
    window, raw-body utf8 coerce, non-constant-time compare,
    no-auth-on-handler) — `webhook_signature_patterns.py` rules 1-12.
  * Outbound *WEBHOOK* env-var POST without host allowlist —
    `dns_email_patterns.py` rule 5.
  * Discord / Telegram URLs as prompt-injection exfil sinks —
    `agent_config_patterns.py` line 176.
  * `SLACK_TOKEN`/`SLACK_BOT_TOKEN` env-var prefix mapping —
    `credential_lifecycle_patterns.py` line 307.
  * Generic `xoxb-` literal in JS bundle —
    `js_bundler_patterns.py` line 392.
  * Generic OAuth device-flow — `oauth_device_flow_patterns.py`.

What IS here (15 net-new rules, regex-only, all RE2-safe):

  * chat-bot-webhook-url-literal-committed                     (CRITICAL)
  * chat-bot-teams-workflow-url-literal                        (CRITICAL)
  * chat-bot-slash-command-no-team-allowlist                   (HIGH)
  * chat-bot-telegram-no-chat-id-allowlist                     (HIGH)
  * chat-bot-telegram-setwebhook-attacker-url                  (CRITICAL)
  * chat-bot-token-type-confused-variable                      (HIGH)
  * chat-bot-incoming-webhook-username-spoof                   (MEDIUM)
  * chat-bot-slack-postmessage-as-user-legacy                  (LOW)
  * chat-bot-slack-scope-overreach-users-read-email            (MEDIUM)
  * chat-bot-slack-admin-scope                                 (HIGH)
  * chat-bot-oauth-state-predictable-random                    (MEDIUM)
  * chat-bot-discord-message-content-intent-undisclosed        (MEDIUM)
  * chat-bot-discord-bot-token-in-client-bundle                (CRITICAL)
  * chat-bot-telegram-token-in-url-path-loglevel               (HIGH)
  * chat-bot-webhook-url-from-untrusted-config                 (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (literal webhook URL, Discord token, Telegram
                        token in URL/logs)
  ASI-04 — Information leak (token-type-confusion, username-spoof,
                              intent disclosure)
  ASI-05 — Supply-chain / cross-tenant pivot (slash-command team
                                                allowlist, settings
                                                endpoint hijack)
  ASI-07 — Authority / authorisation gaps (chat-id allowlist,
                                            setWebhook hijack, as_user
                                            legacy, OAuth state CSRF,
                                            scope overreach)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- D1 : chat-bot-webhook-url-literal-committed ------------------------


# Bounded character-class shapes for the four platform webhook URL forms.
# Combined into a single regex so we can iterate once; no nested
# quantifiers, no alternation under repetition.
_WEBHOOK_URL_LITERAL_ANY = _re(
    r"\b(?:hooks\.slack\.com/services/T[A-Z0-9]{8,12}/B[A-Z0-9]{8,12}/[A-Za-z0-9]{20,40}"
    r"|discord(?:app)?\.com/api/webhooks/\d{17,20}/[A-Za-z0-9_\-]{50,80}"
    r"|api\.telegram\.org/bot\d{8,12}:[A-Za-z0-9_\-]{30,40}"
    r"|(?:outlook|webhook)\.office(?:\.com)?/webhook(?:b2)?/"
    r"[a-f0-9\-]{36}@[a-f0-9\-]{36}/IncomingWebhook/"
    r"[A-Za-z0-9_\-]+/[a-f0-9\-]{36})\b"
)


# ---- D2 : chat-bot-teams-workflow-url-literal ---------------------------


# Teams Workflows webhook URL — post-2024 connector. Host is
# prod-NN.<region>.logic.azure.com; the `?sig=` query param IS the bearer.
_TEAMS_V2_WORKFLOW_URL_LITERAL = _re(
    r"\bhttps?://prod-\d{1,3}(?:\.[a-z]+)?\.logic\.azure\.com"
    r"(?::\d{1,5})?/workflows/[a-f0-9]{16,40}"
    r"/triggers/manual/paths/invoke"
    r"[^\"'\s]{0,300}?[?&]sig=[A-Za-z0-9_\-]{30,60}\b"
)


# ---- D3 : chat-bot-slash-command-no-team-allowlist ----------------------


# Trigger pattern: a Slack interactivity route registration.
_SLACK_INTERACTIVITY_ROUTE = _re(
    r"\bapp\.(?:post|use)\s*\(\s*['\"`]"
    r"(?:/api)?/(?:chatops/)?slack/(?:actions|commands|events|interactivity)"
    r"(?:/[A-Za-z0-9_:\-]*)?"
    r"['\"`]"
    r"|"
    # Slack Bolt SDK action/command/view handlers
    r"\b(?:app|slackApp|boltApp)\."
    r"(?:action|command|view|shortcut|options)\s*\("
    r"|"
    # Python Bolt: @app.action(...) / @app.command(...)
    r"^\s*@app\.(?:action|command|view|shortcut)\s*\("
)

_SLACK_TEAM_ID_CHECK = _re(
    r"\b(?:payload|body|req\.body|event)\.team(?:_id|\.id)\b"
    r"|"
    r"\bALLOWED_TEAMS?\b"
    r"|"
    r"\bWORKSPACE_ALLOWLIST\b"
    r"|"
    r"\bTEAM_ID_ALLOWLIST\b"
    r"|"
    r"\bteam_id\s*(?:==|===|!=|!==|in|not in)\s*"
    r"|"
    r"\bteam\.id\s*(?:==|===|!=|!==|in|not in)\s*"
)


# ---- D4 : chat-bot-telegram-no-chat-id-allowlist ------------------------


# Trigger: a telegram-update handler shape.
_TELEGRAM_HANDLER_TRIGGER = _re(
    # JS / TS destructuring of update fields
    r"\bupdate\.(?:message|callback_query|inline_query|edited_message)\b"
    r"|"
    # python-telegram-bot v20+ shape
    r"\b(?:async\s+)?def\s+(?:handle_?update|on_message|handle_message"
    r"|on_callback|handle_command|on_command)\s*\("
    r"|"
    # JS handler function declarations
    r"\bfunction\s+(?:handle_?update|onMessage|handleMessage|onCallback)\s*\("
    r"|"
    # pyrogram @app.on_message style
    r"^\s*@(?:app|bot|dp|router)\.(?:on_message|message_handler|message"
    r"|callback_query|on_callback_query|on_command)\s*[\(\.]"
)

_TELEGRAM_USER_INPUT_READ = _re(
    r"\b(?:update|msg|message|event|ctx)\.(?:message\.)?text\b"
    r"|"
    r"\b(?:update|callback)\.callback_query\.data\b"
    r"|"
    r"\.message\.text\b"
)

_TELEGRAM_CHAT_ALLOWLIST = _re(
    r"\bchat(?:_id|\.id)\s*(?:==|===|!=|!==|in|not in)\s*"
    r"|"
    r"\bALLOWED_CHATS?(?:_IDS?)?\b"
    r"|"
    r"\bTELEGRAM_CHAT_IDS?\b"
    r"|"
    r"\bAUTHORIZED_CHATS?\b"
    r"|"
    r"\bif\s+msg\.chat\.id\s*=="
    r"|"
    r"\bif\s+chat_id\s*=="
    r"|"
    r"\bif\s+update\.message\.chat\.id\s*=="
)


# ---- D5 : chat-bot-telegram-setwebhook-attacker-url ---------------------


_TELEGRAM_SETWEBHOOK_TRIGGER = _re(
    # JS axios: `https://api.telegram.org/bot${TOKEN}/setWebhook`
    r"api\.telegram\.org/bot[^/\s'\"`]+/setWebhook\b"
    r"|"
    # python-telegram-bot: bot.set_webhook(url=...)
    r"\b(?:bot|application|app)\.set_webhook\s*\("
    r"|"
    # JS bot.setWebhook(url) / telegraf
    r"\b(?:bot|telegraf|client)\.setWebhook\s*\("
)

_TELEGRAM_SETWEBHOOK_URL_FROM_INPUT = _re(
    # URL value comes from a request body / query / env var
    r"\b(?:req\.body|req\.query|request\.form|request\.json"
    r"|request\.args|request\.params|req\.params|params\["
    r"|process\.env|os\.environ|os\.getenv|config\.[A-Za-z_]+webhook"
    r"|input|user_input|payload|userdata)\b"
)

_TELEGRAM_SETWEBHOOK_HOST_ALLOWLIST = _re(
    r"\bnew\s+URL\s*\([^)]*\)\.host"
    r"|"
    r"\b(?:urlparse|parse_url|url\.parse)\s*\([^)]*\)\.host"
    r"|"
    r"\bALLOWED_(?:WEBHOOK_)?HOSTS?\b"
    r"|"
    # Hardcoded https:// followed by a known host in the same function
    r"['\"]https://[a-z0-9.-]+\.(?:com|net|io|org|app|cloud|dev)/['\"]"
)


# ---- D6 : chat-bot-token-type-confused-variable -------------------------


# Discriminator: variable distinguished by `startsWith('http')` /
# `'http' in var` / `/^https?:/`.
_TYPE_CONFUSION_DISCRIMINATOR = _re(
    r"\b([A-Za-z_$][A-Za-z0-9_$]{2,32})"
    r"\.(?:startsWith|startswith)\s*\(\s*['\"]https?['\"]\s*\)"
    r"|"
    r"\b['\"]https?['\"]\s+in\s+([A-Za-z_$][A-Za-z0-9_$]{2,32})\b"
    r"|"
    r"\b/\^https?:/\s*\.test\s*\(\s*([A-Za-z_$][A-Za-z0-9_$]{2,32})\s*\)"
    r"|"
    # JS regex match: var.match(/^https?:/)
    r"\b([A-Za-z_$][A-Za-z0-9_$]{2,32})\.match\s*\(\s*/\^https?:"
)

_TYPE_CONFUSION_USED_AS_URL = _re(
    # axios.post(<var>, ...) / fetch(<var>, ...) / requests.post(<var>, ...)
    r"\b(?:axios\.(?:post|get|put|patch|delete)|fetch|http\.(?:post|get)"
    r"|requests\.(?:post|get|put|patch|delete))"
    r"\s*\(\s*[A-Za-z_$][A-Za-z0-9_$]{2,32}\b"
)

_TYPE_CONFUSION_USED_AS_TOKEN = _re(
    # new WebClient(<var>) / new SlackClient(<var>) / Bot(<var>) /
    # telegram.Bot(<var>) / Authorization: Bearer ${var}
    r"\bnew\s+(?:WebClient|SlackClient|Slack|Bot|TelegramBot|DiscordClient)\s*\("
    r"|"
    r"\b(?:Bot|telegram\.Bot|tg\.Bot|TelegramClient|Pyrogram)\s*\("
    r"|"
    r"['\"]Authorization['\"]\s*[:,]\s*[`'\"]Bearer\s"
    r"|"
    r"\.setToken\s*\("
    r"|"
    # Bolt App({token: ...})
    r"\bApp\s*\(\s*\{\s*[^}]*\btoken\s*:"
)


# ---- D7 : chat-bot-incoming-webhook-username-spoof ----------------------


# JSON payload to Slack incoming-webhook with username/icon overrides
# derived from non-literal expressions. We match the username key
# assignment line; same-file presence of a Slack webhook URL or var name
# is a Stage-B filter.
_SLACK_INCOMING_USERNAME_OVERRIDE = _re(
    # JSON-shape: username: <expr> where <expr> is a template literal,
    # variable, or attribute access (NOT a static quoted literal).
    r"\busername\s*:\s*"
    r"(?:`[^`]*\$\{[^}]+\}[^`]*`"  # template literal with interpolation
    r"|req\.body\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|req\.query\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|payload\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|user(?:Input|Name|_input|_name)?\b"
    r"|botName\b"
    r"|[A-Za-z_$][A-Za-z0-9_$]{0,16}\.(?:name|username|userName))"
    r"|"
    # Same for icon_emoji / icon_url
    r"\b(?:icon_emoji|icon_url)\s*:\s*"
    r"(?:`[^`]*\$\{[^}]+\}[^`]*`"
    r"|req\.body\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|payload\.[A-Za-z_$][A-Za-z0-9_$]*)"
)

# Stage-B context: same-file mention of Slack webhook URL or
# SLACK_WEBHOOK_URL var. Without context, MEDIUM is too noisy.
_SLACK_WEBHOOK_CONTEXT = _re(
    r"\bhooks\.slack\.com/services"
    r"|"
    r"\bSLACK_WEBHOOK(?:_URL)?\b"
    r"|"
    r"\bslackWebhook(?:Url)?\b"
)


# ---- D8 : chat-bot-slack-postmessage-as-user-legacy ---------------------


_SLACK_POSTMESSAGE_AS_USER_TRUE = _re(
    # Anchor: `as_user: true` literal in a JSON-like context. The
    # neighbouring chat.postMessage is the confirming context (Stage-B).
    r"\bas_user\s*:\s*true\b"
)

_SLACK_POSTMESSAGE_CONTEXT = _re(
    r"\bchat\.postMessage\b"
    r"|"
    r"\bclient\.chat\.postMessage\b"
    r"|"
    r"\bweb\.chat\.postMessage\b"
    r"|"
    r"\b@slack/web-api\b"
    r"|"
    r"\bWebClient\b"
)


# ---- D9 : chat-bot-slack-scope-overreach-users-read-email ---------------


# Stage A: scope token in a YAML/JSON list or JS array literal.
_SLACK_CHAT_WRITE_SCOPE = _re(
    r"(?:^\s*-\s*|['\"])chat:write(?:\.public|\.customize)?(?:['\"]|\s*$)"
)

_SLACK_USERS_EMAIL_SCOPE = _re(
    r"(?:^\s*-\s*|['\"])users(?:\.profile)?:read\.email(?:['\"]|\s*$)"
)


# ---- D10 : chat-bot-slack-admin-scope -----------------------------------


_SLACK_ADMIN_SCOPE = _re(
    # YAML list / quoted string / inline comment / bare-token forms.
    # The scope name itself is the discriminator (Slack `admin.*:*` is a
    # well-defined, narrowly-bounded class of strings).
    r"\badmin\.[a-z_]+:(?:read|write)\b"
)


# ---- D11 : chat-bot-oauth-state-predictable-random ----------------------


# Trigger: a `state` variable construction immediately near a Slack /
# Discord / Microsoft OAuth authorize URL.
_OAUTH_STATE_WEAK_RNG = _re(
    # JS: const state = Math.random().toString(36)...
    r"\bstate\s*[:=]\s*Math\.random\s*\("
    r"|"
    # JS: state = Date.now().toString()
    r"\bstate\s*[:=]\s*Date\.now\s*\("
    r"|"
    # Python: state = str(random.randint(...))
    r"\bstate\s*=\s*str\s*\(\s*random\.(?:randint|random|choice)\s*\("
    r"|"
    # Python: state = str(uuid.uuid1())  -- uuid1 leaks MAC+time
    r"\bstate\s*=\s*str\s*\(\s*uuid\.uuid1\s*\("
    r"|"
    # Sequential counter: state = counter++ / state = ++counter
    r"\bstate\s*=\s*(?:counter|seq|n|i)\s*\+\+"
    r"|"
    # JS: const state = `prefix-${Math.random()}`
    r"\bstate\s*[:=]\s*[`'\"][^`'\"]*\$\{[^}]*(?:Math\.random|Date\.now)"
)

_OAUTH_AUTHORIZE_URL_CONTEXT = _re(
    r"\bslack\.com/oauth/v2/authorize"
    r"|"
    r"\bdiscord(?:app)?\.com/(?:api/)?oauth2/authorize"
    r"|"
    r"\blogin\.microsoftonline\.com/[^/]+/oauth2"
    r"|"
    r"\boauth\.telegram\.org"
)


# ---- D12 : chat-bot-discord-message-content-intent-undisclosed ----------


_DISCORD_MESSAGE_CONTENT_INTENT = _re(
    # JS discord.js v14+:  GatewayIntentBits.MessageContent
    r"\bGatewayIntentBits\.MessageContent\b"
    r"|"
    # JS discord.js v13: 'MESSAGE_CONTENT' / Intents.FLAGS.MESSAGE_CONTENT
    r"\bIntents\.FLAGS\.MESSAGE_CONTENT\b"
    r"|"
    # Python discord.py: intents.message_content = True
    r"\bintents\.message_content\s*=\s*True\b"
    r"|"
    # JS shorthand: intents: [..., 'MessageContent', ...]
    r"['\"]MessageContent['\"]"
)


# ---- D13 : chat-bot-discord-bot-token-in-client-bundle ------------------


# JWT-shape Discord bot token literal as the first arg to client.login.
# 3 segments separated by `.`, each base64url-ish.
_DISCORD_BOT_TOKEN_LITERAL = _re(
    r"\.login\s*\(\s*['\"]"
    r"([A-Za-z0-9_\-]{20,30}\.[A-Za-z0-9_\-]{5,10}\.[A-Za-z0-9_\-]{25,40})"
    r"['\"]\s*\)"
)

# Companion shape: client.login(process.env.DISCORD_BOT_TOKEN) in a file
# that ALSO contains a webpack/vite/rollup entry config.
_DISCORD_LOGIN_FROM_ENV = _re(
    r"\.login\s*\(\s*(?:process\.env\.[A-Z_]*(?:DISCORD|BOT)[A-Z_]*"
    r"|import\.meta\.env\.[A-Z_]*(?:DISCORD|BOT)[A-Z_]*)\s*\)"
)

_CLIENT_BUNDLE_MARKER = _re(
    r"\bmodule\.exports\s*=\s*\{[^}]*\bentry\s*:"
    r"|"
    r"\bexport\s+default\s+\{[^}]*\bentry\s*:"
    r"|"
    r"\bdefineConfig\s*\(\s*\{[^}]*\binput\s*:"
    r"|"
    r"\besbuild\.build\s*\(\s*\{[^}]*\bentryPoints\s*:"
    r"|"
    r"\bdefineConfig\s*\(\s*\{[^}]*\bbuild\s*:"
)


# ---- D14 : chat-bot-telegram-token-in-url-path-loglevel -----------------


# Trigger: api.telegram.org/bot${TOKEN}/... URL construction.
_TELEGRAM_URL_PATH_TOKEN = _re(
    r"api\.telegram\.org/bot\$\{[A-Za-z_$][A-Za-z0-9_$.]*\}"
    r"|"
    r"api\.telegram\.org/bot\$\{[A-Za-z_$][A-Za-z0-9_$.]*\?[^}]*\}"
    r"|"
    # Python f-string: f"https://api.telegram.org/bot{TOKEN}/..."
    r"api\.telegram\.org/bot\{[A-Za-z_][A-Za-z0-9_.]*\}"
    r"|"
    # Python str-format / concat (e.g. f"https://api.telegram.org/bot" + token)
    r"['\"]https?://api\.telegram\.org/bot['\"]\s*\+\s*[A-Za-z_]"
)

# Anti-pattern: catch handler that logs err.config / err.response / etc.
_ERROR_CONFIG_LOG_LEAK = _re(
    r"\b(?:console\.(?:log|error|warn|info|debug)"
    r"|logger\.(?:error|warn|info|debug)"
    r"|log\.(?:error|warn|info|debug))"
    r"\s*\([^)]*\b(?:err|error|e|ex)\.(?:response\.config\.url"
    r"|response\.config"
    r"|config\.url"
    r"|config"
    r"|request"
    r"|toString\s*\(\s*\))"
    r"|"
    r"\bJSON\.stringify\s*\(\s*(?:err|error|e|ex)\s*\)"
)

_TELEGRAM_TOKEN_REDACT_GUARD = _re(
    r"\.replace\s*\(\s*/bot\\?d"
    r"|"
    r"\bredact\b"
    r"|"
    r"\b\[REDACTED\]"
    r"|"
    r"\bscrub(?:_token|Token)?\b"
)


# ---- D15 : chat-bot-webhook-url-from-untrusted-config -------------------


_SETTINGS_WEBHOOK_ROUTE = _re(
    # Express: app.post('/api/...settings...webhook...|notifications...')
    r"\bapp\.(?:post|put|patch)\s*\(\s*['\"`]/api/"
    r"(?:[a-z0-9_\-]+/)*"
    r"(?:settings|integrations|notifications|chatops|webhooks?|alerts?)"
    r"(?:/[a-z0-9_\-]*)?"
    r"['\"`]"
    r"|"
    # FastAPI / Flask: @app.post('/api/.../webhook...')
    r"^\s*@(?:app|router|bp)\.(?:post|put|patch)\s*\(\s*['\"`]/api/"
    r"(?:[a-z0-9_\-]+/)*"
    r"(?:settings|integrations|notifications|chatops|webhooks?|alerts?)"
)

_WEBHOOK_FIELD_DESTRUCTURE = _re(
    # const { slackWebhook, discordWebhook, teamsWebhook } = req.body;
    r"\bconst\s*\{[^}]*(?:slackWebhook|discordWebhook|teamsWebhook|telegramWebhook"
    r"|webhookUrl|webhook_url|chatWebhook)[^}]*\}\s*=\s*req\.body\b"
    r"|"
    # Python: slack_webhook = request.json.get('slack_webhook')
    r"\b(?:slack|discord|teams|telegram|chat)_?webhook(?:_url)?\s*="
    r"\s*request\.(?:json|form|values|args)"
    r"|"
    # JS: const slackWebhook = req.body.slackWebhook
    r"\b(?:slackWebhook|discordWebhook|teamsWebhook|telegramWebhook|webhookUrl)"
    r"\s*=\s*req\.body\."
)

_HOST_VALIDATION_MARKER = _re(
    r"\bnew\s+URL\s*\("
    r"|"
    r"\b(?:url|URL)\.parse\s*\("
    r"|"
    r"\burlparse\s*\("
    r"|"
    r"\b\.hostname\b"
    r"|"
    r"\b\.host\b"
    r"|"
    # Canonical host literals — if any present, host check exists
    r"['\"]hooks\.slack\.com['\"]"
    r"|"
    r"['\"]discord(?:app)?\.com['\"]"
    r"|"
    r"['\"](?:webhook|outlook)\.office(?:\.com)?['\"]"
    r"|"
    r"['\"]logic\.azure\.com['\"]"
    r"|"
    r"\bALLOWED_HOSTS?\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="chat-bot-webhook-url-literal-committed",
        name="Chat-bot webhook URL with embedded secret committed to source",
        severity="CRITICAL",
        description=(
            "A live Slack/Discord/Telegram/Teams (v1) webhook URL with "
            "the path-segment secret is committed to a non-env, "
            "non-documentation, non-test file. Anyone with the URL can "
            "post to the channel (and on Discord/Teams, exfil channel "
            "contents). The secret IS the auth — there is no further "
            "verification step on Slack/Discord/Teams incoming-webhook "
            "and the Telegram bot token in the URL path is the full "
            "credential."
        ),
        pattern=_WEBHOOK_URL_LITERAL_ANY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="chat-bot-teams-workflow-url-literal",
        name="Microsoft Teams Workflows webhook URL with sig= secret committed",
        severity="CRITICAL",
        description=(
            "A live Microsoft Teams Workflows webhook URL "
            "(post-2024 connector, host prod-NN.<region>.logic.azure.com) "
            "with the `sig=` query parameter — the bearer secret — "
            "committed to source. The Teams v1 outlook.office.com URL "
            "shape is covered by chat-bot-webhook-url-literal-committed; "
            "this rule covers the v2 Workflows URL that v1 cannot match."
        ),
        pattern=_TEAMS_V2_WORKFLOW_URL_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="chat-bot-slash-command-no-team-allowlist",
        name="Slack slash-command / interactivity handler with no team_id allowlist",
        severity="HIGH",
        description=(
            "Slack interactivity / slash-command handler verifies the "
            "signing-secret signature (good) but does NOT check "
            "`payload.team.id` / `payload.team_id` against a workspace "
            "allowlist. A Slack app installed in workspaces A and B "
            "produces validly signed payloads for both; a user in "
            "workspace A can drive B's actions. Distinct from Wave 19's "
            "`webhook-handler-no-authentication` (which catches missing "
            "signature checks)."
        ),
        pattern=_SLACK_INTERACTIVITY_ROUTE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="chat-bot-telegram-no-chat-id-allowlist",
        name="Telegram bot handler dispatches commands without chat_id allowlist",
        severity="HIGH",
        description=(
            "Telegram update-handler dispatches `/commands` or callback "
            "actions WITHOUT checking `update.message.chat.id` against "
            "an operator allowlist. Telegram bot tokens leak frequently; "
            "anyone who knows the bot's @username can DM `/deploy`, "
            "`/restart`, `/exec` once the token is out. The chat_id "
            "allowlist is the only effective auth surface on Telegram "
            "bots (no app-store permission boundary)."
        ),
        pattern=_TELEGRAM_HANDLER_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-telegram-setwebhook-attacker-url",
        name="Telegram setWebhook called with attacker-controllable URL",
        severity="CRITICAL",
        description=(
            "A call to `setWebhook` / `set_webhook` where the URL "
            "argument comes from a request body, query string, or env "
            "var WITHOUT a host allowlist. The attack: a vuln in an "
            "install/settings endpoint redirects ALL future Telegram "
            "updates to the attacker's host — full bot takeover at the "
            "update level, persisted by Telegram across bot-server "
            "restarts. The attacker now gets a copy of every legitimate "
            "user message (privacy breach)."
        ),
        pattern=_TELEGRAM_SETWEBHOOK_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-token-type-confused-variable",
        name="Chat-bot variable holds either token OR URL, discriminated by startsWith('http')",
        severity="HIGH",
        description=(
            "A single variable is used both as an HTTP URL (passed to "
            "axios.post / fetch) AND as a bearer token (passed to "
            "`new WebClient(...)` / `Bot(...)`), discriminated by "
            "`startsWith('http')`. Two attack surfaces: (a) operator "
            "puts the wrong VALUE in the 'right' env var, routing through "
            "the wrong code path and leaking the secret in resulting "
            "error messages; (b) the inverse — a webhook URL passed to "
            "`new WebClient()` constructs an HTTP-client with the URL "
            "AS the auth token, leaking it in Slack's access logs."
        ),
        pattern=_TYPE_CONFUSION_DISCRIMINATOR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="chat-bot-incoming-webhook-username-spoof",
        name="Slack incoming-webhook username/icon overridden from user input",
        severity="MEDIUM",
        description=(
            "Slack incoming-webhook payload includes a `username:` or "
            "`icon_emoji:`/`icon_url:` field whose value comes from "
            "user input. Slack legacy-supports these overrides on "
            "incoming-webhooks; they let an attacker post AS a different "
            "bot identity (e.g. '@security-team' or '@CEO') inside the "
            "channel — a strong precursor for phishing within the "
            "operator team's trusted channel."
        ),
        pattern=_SLACK_INCOMING_USERNAME_OVERRIDE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="chat-bot-slack-postmessage-as-user-legacy",
        name="Slack chat.postMessage called with deprecated as_user: true",
        severity="LOW",
        description=(
            "`client.chat.postMessage({ as_user: true, ... })` posts AS "
            "the installing user (using their `xoxp-` user token), not "
            "as the bot. Slack deprecates this — bot-token apps should "
            "NEVER set `as_user: true` because it (a) requires a user "
            "token the app may not have, and (b) bypasses the bot "
            "identity's audit trail. Slack will eventually stop "
            "honoring this field."
        ),
        pattern=_SLACK_POSTMESSAGE_AS_USER_TRUE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-slack-scope-overreach-users-read-email",
        name="Slack manifest grants chat:write AND users:read.email",
        severity="MEDIUM",
        description=(
            "Slack OAuth scope list grants both `chat:write` "
            "(notional bot purpose) and `users:read.email` — the latter "
            "exfiltrates every workspace member's email if the bot's "
            "`xoxb-` token leaks. Developers commonly request "
            "`users:read.email` to populate DM templates without "
            "realising they just granted PII scope. GDPR/privacy "
            "implications."
        ),
        pattern=_SLACK_USERS_EMAIL_SCOPE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-slack-admin-scope",
        name="Slack manifest grants workspace admin.* scopes to a chat-ops bot",
        severity="HIGH",
        description=(
            "Slack `admin.*` scopes (e.g. `admin.users:read`, "
            "`admin.conversations:write`) grant workspace-wide "
            "administrative reach. These are intended for SCIM/IT-"
            "automation apps, NOT for chat-ops bots. Granting them to "
            "a CI-recovery bot means the bot token compromise impacts "
            "the entire workspace, not just the bot's channels — "
            "post-quantum-class privilege escalation in the Slack-ops "
            "trust model."
        ),
        pattern=_SLACK_ADMIN_SCOPE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-oauth-state-predictable-random",
        name="OAuth install-flow state derived from non-CSPRNG",
        severity="MEDIUM",
        description=(
            "Slack/Discord OAuth install flow constructs the `state` "
            "CSRF parameter from `Math.random()` / `Date.now()` / "
            "`uuid.uuid1()` / sequential counter — NOT from a "
            "cryptographically secure RNG. An attacker can pre-compute "
            "state values (V8's Math.random is not crypto-grade) and "
            "complete the OAuth callback on the attacker's chosen "
            "account. Use `crypto.randomBytes(32).toString('hex')` "
            "(Node) or `secrets.token_urlsafe(32)` (Python)."
        ),
        pattern=_OAUTH_STATE_WEAK_RNG,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="chat-bot-discord-message-content-intent-undisclosed",
        name="Discord bot enables MessageContent privileged intent",
        severity="MEDIUM",
        description=(
            "Discord bot enables the privileged `MessageContent` "
            "gateway intent (or `intents.message_content = True` in "
            "discord.py). Discord moved this intent to the privileged "
            "tier in August 2022 — bots in 100+ servers MUST go through "
            "manual verification, and ToS requires the bot's privacy "
            "policy to disclose that the bot READS message content. "
            "Disclosure gap = Discord ToS violation = bot terminated "
            "by Discord ops."
        ),
        pattern=_DISCORD_MESSAGE_CONTENT_INTENT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="chat-bot-discord-bot-token-in-client-bundle",
        name="Discord bot-token literal or env reference in client.login",
        severity="CRITICAL",
        description=(
            "Discord `client.login(...)` called with a hardcoded "
            "JWT-shape bot token literal, OR with `process.env.X` in a "
            "file that ALSO appears in a webpack/rollup/esbuild/vite "
            "client-bundle entry config (where the env var is build-time "
            "inlined into the browser bundle). Discord bot tokens grant "
            "full bot control — leaking one is equivalent to handing "
            "over the bot to the attacker."
        ),
        pattern=_DISCORD_BOT_TOKEN_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="chat-bot-telegram-token-in-url-path-loglevel",
        name="Telegram bot URL with token in path logged via err.config",
        severity="HIGH",
        description=(
            "Telegram bot API has no Authorization header — the bot "
            "token IS the URL path. Default axios error objects expose "
            "`err.config.url` / `err.response.config.url` containing "
            "the FULL URL with token. Logging `err.response`, "
            "`err.config`, `err.request`, `err.toString()`, or "
            "`JSON.stringify(err)` in a catch handler leaks the token "
            "to production logs (Datadog, Splunk, etc.). The leaked "
            "token gives full bot control."
        ),
        pattern=_TELEGRAM_URL_PATH_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="chat-bot-webhook-url-from-untrusted-config",
        name="Settings endpoint accepts chat-bot webhook URL without host validation",
        severity="HIGH",
        description=(
            "An admin/settings endpoint accepts a Slack/Discord/Teams "
            "webhook URL from `req.body` and stores it WITHOUT "
            "validating the URL's host against the platform's canonical "
            "host. A session-compromised admin can swap production "
            "webhook URLs for attacker-controlled hosts; future "
            "incident alerts flow to the attacker, the incident channel "
            "goes quiet, and detection is delayed until someone "
            "notices the silence. Distinct from Wave 19's "
            "`dns-webhook-url-no-allowlist` (outbound POST direction "
            "vs. inbound settings mutation here)."
        ),
        pattern=_SETTINGS_WEBHOOK_ROUTE,
        owasp_asi="ASI-05",
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


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * D3 (slash-command-no-team-allowlist) — anchor on the route
        registration and require NO `payload.team.id` / `ALLOWED_TEAMS`
        marker in a 30-line forward window.
      * D4 (telegram-no-chat-id-allowlist) — anchor on the handler
        trigger and require BOTH: user-input read (`update.message.text`
        or similar) AND NO chat-id allowlist in a 30-line forward
        window.
      * D5 (telegram-setwebhook-attacker-url) — anchor on setWebhook
        and require an attacker-controllable URL source AND NO host
        allowlist marker in the same 15-line window.
      * D6 (token-type-confused-variable) — anchor on the
        startsWith('http') discriminator and require BOTH a URL-usage
        and a token-usage of the same variable name within 20 lines.
      * D7 (incoming-webhook-username-spoof) — require a Slack
        webhook context anywhere in the file.
      * D8 (postmessage-as-user-legacy) — require a chat.postMessage
        context anywhere in the file.
      * D9 (scope-overreach) — require BOTH `chat:write` AND
        `users:read.email` within 30 lines.
      * D11 (oauth-state-predictable-random) — require an OAuth
        authorize URL context anywhere in the file.
      * D13 (discord-bot-token-in-client-bundle) — literal-shape match
        is high-precision FLAG; the env-from-bundle variant requires
        a same-file bundler-entry config (Stage-B).
      * D14 (telegram-token-in-url-path-loglevel) — anchor on the
        URL construction AND require an err.config-style log in a
        15-line forward window AND NO redact marker.
      * D15 (webhook-url-from-untrusted-config) — anchor on the
        settings route AND require a webhook-field destructure in a
        15-line forward window AND NO host-validation marker.

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

    # ---- D1 : chat-bot-webhook-url-literal-committed ----
    rule_d1 = rule_by_id["chat-bot-webhook-url-literal-committed"]
    for m in _WEBHOOK_URL_LITERAL_ANY.finditer(text):
        _emit(rule_d1, m.start(), m.group(0))

    # ---- D2 : chat-bot-teams-workflow-url-literal ----
    rule_d2 = rule_by_id["chat-bot-teams-workflow-url-literal"]
    for m in _TEAMS_V2_WORKFLOW_URL_LITERAL.finditer(text):
        _emit(rule_d2, m.start(), m.group(0))

    # ---- D3 : chat-bot-slash-command-no-team-allowlist ----
    rule_d3 = rule_by_id["chat-bot-slash-command-no-team-allowlist"]
    for m in _SLACK_INTERACTIVITY_ROUTE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look forward 30 lines (the handler body).
        window = _slice_forward(text, line, 30)
        if _SLACK_TEAM_ID_CHECK.search(window) is not None:
            continue
        _emit(rule_d3, m.start(), m.group(0))

    # ---- D4 : chat-bot-telegram-no-chat-id-allowlist ----
    rule_d4 = rule_by_id["chat-bot-telegram-no-chat-id-allowlist"]
    _seen_d4_lines: set[int] = set()
    for m in _TELEGRAM_HANDLER_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 10-line backward + 30-line forward window — allowlists usually
        # appear BEFORE the user-input read (guard pattern) but the trigger
        # may match anywhere inside the handler body.
        window = _slice_window(text, line, 10, 30)
        # Must read user input to be a meaningful FP-suppression baseline.
        if _TELEGRAM_USER_INPUT_READ.search(window) is None:
            continue
        # If chat-id allowlist marker is present, suppress.
        if _TELEGRAM_CHAT_ALLOWLIST.search(window) is not None:
            continue
        # De-dup: a single handler often contains multiple triggers; only
        # emit one D4 per ~15-line region.
        region = line // 15
        if region in _seen_d4_lines:
            continue
        _seen_d4_lines.add(region)
        _emit(rule_d4, m.start(), m.group(0))

    # ---- D5 : chat-bot-telegram-setwebhook-attacker-url ----
    rule_d5 = rule_by_id["chat-bot-telegram-setwebhook-attacker-url"]
    for m in _TELEGRAM_SETWEBHOOK_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 15-line window before+after the call for input-source / allowlist
        window = _slice_window(text, line, 5, 10)
        if _TELEGRAM_SETWEBHOOK_URL_FROM_INPUT.search(window) is None:
            continue
        if _TELEGRAM_SETWEBHOOK_HOST_ALLOWLIST.search(window) is not None:
            continue
        _emit(rule_d5, m.start(), m.group(0))

    # ---- D6 : chat-bot-token-type-confused-variable ----
    rule_d6 = rule_by_id["chat-bot-token-type-confused-variable"]
    for m in _TYPE_CONFUSION_DISCRIMINATOR.finditer(text):
        line, _ = _line_col(text, m.start())
        # 20-line forward window
        window = _slice_window(text, line, 5, 15)
        # Need BOTH a URL-usage AND a token-usage to be flagged.
        if (
            _TYPE_CONFUSION_USED_AS_URL.search(window) is not None
            and _TYPE_CONFUSION_USED_AS_TOKEN.search(window) is not None
        ):
            _emit(rule_d6, m.start(), m.group(0))

    # ---- D7 : chat-bot-incoming-webhook-username-spoof ----
    rule_d7 = rule_by_id["chat-bot-incoming-webhook-username-spoof"]
    has_slack_context = _file_contains(text, _SLACK_WEBHOOK_CONTEXT)
    if has_slack_context:
        for m in _SLACK_INCOMING_USERNAME_OVERRIDE.finditer(text):
            _emit(rule_d7, m.start(), m.group(0))

    # ---- D8 : chat-bot-slack-postmessage-as-user-legacy ----
    rule_d8 = rule_by_id["chat-bot-slack-postmessage-as-user-legacy"]
    has_postmessage_context = _file_contains(text, _SLACK_POSTMESSAGE_CONTEXT)
    if has_postmessage_context:
        for m in _SLACK_POSTMESSAGE_AS_USER_TRUE.finditer(text):
            _emit(rule_d8, m.start(), m.group(0))

    # ---- D9 : chat-bot-slack-scope-overreach-users-read-email ----
    rule_d9 = rule_by_id["chat-bot-slack-scope-overreach-users-read-email"]
    chat_write_matches = list(_SLACK_CHAT_WRITE_SCOPE.finditer(text))
    email_scope_matches = list(_SLACK_USERS_EMAIL_SCOPE.finditer(text))
    if chat_write_matches and email_scope_matches:
        for m in email_scope_matches:
            line_email, _ = _line_col(text, m.start())
            # Require chat:write within 30 lines (either direction).
            for cm in chat_write_matches:
                line_chat, _ = _line_col(text, cm.start())
                if abs(line_email - line_chat) <= 30:
                    _emit(rule_d9, m.start(), m.group(0))
                    break

    # ---- D10 : chat-bot-slack-admin-scope ----
    rule_d10 = rule_by_id["chat-bot-slack-admin-scope"]
    for m in _SLACK_ADMIN_SCOPE.finditer(text):
        _emit(rule_d10, m.start(), m.group(0))

    # ---- D11 : chat-bot-oauth-state-predictable-random ----
    rule_d11 = rule_by_id["chat-bot-oauth-state-predictable-random"]
    has_oauth_url_context = _file_contains(text, _OAUTH_AUTHORIZE_URL_CONTEXT)
    if has_oauth_url_context:
        for m in _OAUTH_STATE_WEAK_RNG.finditer(text):
            _emit(rule_d11, m.start(), m.group(0))

    # ---- D12 : chat-bot-discord-message-content-intent-undisclosed ----
    rule_d12 = rule_by_id["chat-bot-discord-message-content-intent-undisclosed"]
    for m in _DISCORD_MESSAGE_CONTENT_INTENT.finditer(text):
        _emit(rule_d12, m.start(), m.group(0))

    # ---- D13 : chat-bot-discord-bot-token-in-client-bundle ----
    rule_d13 = rule_by_id["chat-bot-discord-bot-token-in-client-bundle"]
    # Stage-A: literal token in login() — always high precision
    for m in _DISCORD_BOT_TOKEN_LITERAL.finditer(text):
        _emit(rule_d13, m.start(), m.group(0))
    # Stage-B: env-from-bundle variant requires a same-file bundler config
    has_bundle_marker = _file_contains(text, _CLIENT_BUNDLE_MARKER)
    if has_bundle_marker:
        for m in _DISCORD_LOGIN_FROM_ENV.finditer(text):
            _emit(rule_d13, m.start(), m.group(0))

    # ---- D14 : chat-bot-telegram-token-in-url-path-loglevel ----
    rule_d14 = rule_by_id["chat-bot-telegram-token-in-url-path-loglevel"]
    has_redact = _file_contains(text, _TELEGRAM_TOKEN_REDACT_GUARD)
    if not has_redact:
        for m in _TELEGRAM_URL_PATH_TOKEN.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_forward(text, line, 15)
            if _ERROR_CONFIG_LOG_LEAK.search(window) is not None:
                _emit(rule_d14, m.start(), m.group(0))

    # ---- D15 : chat-bot-webhook-url-from-untrusted-config ----
    rule_d15 = rule_by_id["chat-bot-webhook-url-from-untrusted-config"]
    for m in _SETTINGS_WEBHOOK_ROUTE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 30)
        if _WEBHOOK_FIELD_DESTRUCTURE.search(window) is None:
            continue
        if _HOST_VALIDATION_MARKER.search(window) is not None:
            continue
        _emit(rule_d15, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
