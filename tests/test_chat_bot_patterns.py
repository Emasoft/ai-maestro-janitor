"""Tests for scripts/lib/chat_bot_patterns.py.

Pattern-coverage tests for the Wave-22 distill-round-8 angle H
catalogue (15 chat-bot specific anti-patterns covering Slack / Discord /
Microsoft Teams / Telegram). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import chat_bot_patterns as cbp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402


def _slack_hook(seed: str) -> str:
    """Build a Slack webhook URL whose secret body is generated at runtime.

    The T.../B... workspace/channel IDs are non-secret identifiers (not
    credentials); only the trailing path segment is secret-shaped and is
    generated here to avoid any literal in the source.
    """
    body = b62(seed, 24)
    return "https://hooks." + "slack.com/services/T0123ABCDEF/B0456GHIJKL/" + body

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 15 documented rule IDs."""
    assert isinstance(cbp.RULES, tuple)
    rule_ids = {r.id for r in cbp.RULES}
    expected = {
        "chat-bot-webhook-url-literal-committed",
        "chat-bot-teams-workflow-url-literal",
        "chat-bot-slash-command-no-team-allowlist",
        "chat-bot-telegram-no-chat-id-allowlist",
        "chat-bot-telegram-setwebhook-attacker-url",
        "chat-bot-token-type-confused-variable",
        "chat-bot-incoming-webhook-username-spoof",
        "chat-bot-slack-postmessage-as-user-legacy",
        "chat-bot-slack-scope-overreach-users-read-email",
        "chat-bot-slack-admin-scope",
        "chat-bot-oauth-state-predictable-random",
        "chat-bot-discord-message-content-intent-undisclosed",
        "chat-bot-discord-bot-token-in-client-bundle",
        "chat-bot-telegram-token-in-url-path-loglevel",
        "chat-bot-webhook-url-from-untrusted-config",
    }
    assert expected == rule_ids
    assert len(cbp.RULES) == 15


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in cbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = cbp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert cbp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    # Webhook URL secret body generated at runtime — no credential literal in source.
    _slack_url = _slack_hook("sort-slack-url")
    src = (
        # Line 1 — Slack webhook URL literal
        f"const SLACK = '{_slack_url}';\n"
        # Line 2 — Telegram URL literal
        "const TG = 'https://api.telegram.org/bot1234567890:AAHfHs9aBcDe-FgHiJkLmNoPqRsTuVwXyZ12';\n"
    )
    findings = cbp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[cbp.Finding]:
    return [f for f in cbp.scan_text(text) if f.rule_id == rule_id]


# ---------- D1 : chat-bot-webhook-url-literal-committed ------------------


def test_d1_slack_webhook_url_literal_flags() -> None:
    """Live Slack webhook URL committed → CRITICAL hit."""
    src = (
        "const SLACK_URL = "
        "\"https://hooks.slack.com/services/T0123ABCDEF/B0456GHIJKL/"
        "x9a2b8c7d6e5f4g3h2i1jklmnopqrst\";\n"
    )
    hits = _hits("chat-bot-webhook-url-literal-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_d1_discord_webhook_url_literal_flags() -> None:
    """Live Discord webhook URL committed → CRITICAL hit."""
    src = (
        "await fetch('https://discord.com/api/webhooks/812345678901234567/"
        "aLn3K7vM8pQ-r5xY9wZ2tB1cD0eF6gH4jI8kL3mN7oP9qR1sT3uV5wX7yZ', "
        "{ method: 'POST' });\n"
    )
    assert _hits("chat-bot-webhook-url-literal-committed", src)


def test_d1_telegram_bot_url_literal_flags() -> None:
    """Live Telegram bot URL committed → CRITICAL hit."""
    src = (
        "fetch('https://api.telegram.org/bot1234567890:"
        "AAH-Aa1bB2cC3dD4eE5fF6gG7hH8iI9jJ0kK/sendMessage');\n"
    )
    assert _hits("chat-bot-webhook-url-literal-committed", src)


def test_d1_teams_v1_webhook_url_literal_flags() -> None:
    """Teams v1 outlook.office.com webhook URL committed → CRITICAL hit."""
    src = (
        "const TEAMS = 'https://outlook.office.com/webhook/"
        "abc12345-6789-0def-1234-567890abcdef@"
        "9876fedc-ba98-7654-3210-fedcba987654/IncomingWebhook/"
        "abc1234567890def/11112222-3333-4444-5555-666677778888';\n"
    )
    assert _hits("chat-bot-webhook-url-literal-committed", src)


def test_d1_no_webhook_urls_silent() -> None:
    """Non-webhook URLs in source → no hits."""
    src = (
        "const API = 'https://api.example.com/v1/users';\n"
        "const CDN = 'https://cdn.example.com/assets/main.js';\n"
    )
    assert not _hits("chat-bot-webhook-url-literal-committed", src)


def test_d1_short_path_not_flagged() -> None:
    """Slack URL with too-short secret segment → not flagged (FP suppression)."""
    src = "const URL = 'https://hooks.slack.com/services/T1/B1/short';\n"
    assert not _hits("chat-bot-webhook-url-literal-committed", src)


# ---------- D2 : chat-bot-teams-workflow-url-literal ---------------------


def test_d2_teams_v2_workflow_url_flags() -> None:
    """Teams Workflows v2 URL with sig= secret → CRITICAL hit."""
    src = (
        "await axios.post('https://prod-12.westus.logic.azure.com:443/"
        "workflows/abc123def456789012345678/triggers/manual/paths/invoke"
        "?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
        "&sig=AbCdEfGhIjKl_MnOpQrStUvWxYz0123456789', payload);\n"
    )
    hits = _hits("chat-bot-teams-workflow-url-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_d2_teams_v2_no_sig_param_not_flagged() -> None:
    """Logic-azure URL without sig= → no hit (it isn't actionable)."""
    src = (
        "const URL = 'https://prod-12.westus.logic.azure.com:443/"
        "workflows/abc123def456789012345678/triggers/manual/paths/invoke';\n"
    )
    assert not _hits("chat-bot-teams-workflow-url-literal", src)


def test_d2_teams_v2_short_sig_not_flagged() -> None:
    """sig= value too short → no hit (placeholder pattern)."""
    src = (
        "const URL = 'https://prod-12.westus.logic.azure.com:443/"
        "workflows/abc123def456789012345678/triggers/manual/paths/invoke"
        "?sig=PLACEHOLDER';\n"
    )
    assert not _hits("chat-bot-teams-workflow-url-literal", src)


# ---------- D3 : chat-bot-slash-command-no-team-allowlist ----------------


def test_d3_slack_actions_route_no_team_check_flags() -> None:
    """Slack interactivity handler without team_id check → HIGH hit."""
    src = (
        "app.post('/api/chatops/slack/actions', verifySlackSignature, (req, res) => {\n"
        "  const payload = JSON.parse(req.body.payload);\n"
        "  if (payload.type === 'block_actions') {\n"
        "    const action = payload.actions[0];\n"
        "    if (action.action_id === 'approve_recovery') {\n"
        "      runRecovery(action.value);\n"
        "    }\n"
        "  }\n"
        "  res.send();\n"
        "});\n"
    )
    hits = _hits("chat-bot-slash-command-no-team-allowlist", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d3_slack_actions_with_team_id_check_suppressed() -> None:
    """Same handler WITH `payload.team.id` check → no hit."""
    src = (
        "app.post('/slack/actions', verifySlackSignature, (req, res) => {\n"
        "  const payload = JSON.parse(req.body.payload);\n"
        "  if (payload.team.id !== 'T0123ABCDEF') return res.status(403).end();\n"
        "  runRecovery(payload.actions[0].value);\n"
        "});\n"
    )
    assert not _hits("chat-bot-slash-command-no-team-allowlist", src)


def test_d3_python_bolt_action_no_team_check_flags() -> None:
    """Python Bolt @app.action without team_id check → flagged."""
    src = (
        "@app.action(\"approve_recovery\")\n"
        "def approve_recovery(ack, body):\n"
        "    ack()\n"
        "    run_recovery(body[\"actions\"][0][\"value\"])\n"
    )
    assert _hits("chat-bot-slash-command-no-team-allowlist", src)


def test_d3_allowed_teams_constant_suppresses() -> None:
    """Same handler with ALLOWED_TEAMS reference → no hit."""
    src = (
        "const ALLOWED_TEAMS = new Set(['T0123ABCDEF']);\n"
        "app.post('/slack/actions', (req, res) => {\n"
        "  const payload = JSON.parse(req.body.payload);\n"
        "  if (!ALLOWED_TEAMS.has(payload.team.id)) return res.sendStatus(403);\n"
        "  runRecovery(payload.actions[0].value);\n"
        "});\n"
    )
    assert not _hits("chat-bot-slash-command-no-team-allowlist", src)


# ---------- D4 : chat-bot-telegram-no-chat-id-allowlist ------------------


def test_d4_telegram_handler_no_chat_id_check_flags() -> None:
    """Telegram update handler with no chat_id allowlist → HIGH hit."""
    src = (
        "async function handleUpdate(update) {\n"
        "  if (update.message && update.message.text) {\n"
        "    const userText = update.message.text.trim();\n"
        "    if (userText.startsWith('/')) {\n"
        "      await dispatchCommand(userText);\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("chat-bot-telegram-no-chat-id-allowlist", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d4_telegram_handler_with_chat_id_eq_suppresses() -> None:
    """Handler with `if (chatId === TELEGRAM_CHAT_ID)` → no hit."""
    src = (
        "async function handleUpdate(update) {\n"
        "  const chatId = update.message.chat.id;\n"
        "  if (chatId === TELEGRAM_CHAT_ID) {\n"
        "    const userText = update.message.text.trim();\n"
        "    if (userText.startsWith('/')) await dispatchCommand(userText);\n"
        "  }\n"
        "}\n"
    )
    assert not _hits("chat-bot-telegram-no-chat-id-allowlist", src)


def test_d4_telegram_python_handler_no_check_flags() -> None:
    """python-telegram-bot async handler with no chat.id check → flagged."""
    src = (
        "async def handle_message(client, msg):\n"
        "    if msg.text.startswith('/deploy'):\n"
        "        await run_deploy()\n"
    )
    assert _hits("chat-bot-telegram-no-chat-id-allowlist", src)


def test_d4_telegram_broadcast_only_no_user_input_silent() -> None:
    """Broadcast-only bot (no user input read) → silent (FP suppression)."""
    src = (
        "async def handle_update(update):\n"
        "    await bot.send_message(chat_id=ADMIN_CHAT, text='ping')\n"
    )
    assert not _hits("chat-bot-telegram-no-chat-id-allowlist", src)


# ---------- D5 : chat-bot-telegram-setwebhook-attacker-url ---------------


def test_d5_setwebhook_from_req_body_flags() -> None:
    """setWebhook URL from req.body → CRITICAL hit."""
    src = (
        "app.post('/install/telegram', requireAuth, async (req, res) => {\n"
        "  const url = req.body.webhookUrl;\n"
        "  await axios.post(`https://api.telegram.org/bot${BOT_TOKEN}/setWebhook`, { url });\n"
        "  res.send();\n"
        "});\n"
    )
    hits = _hits("chat-bot-telegram-setwebhook-attacker-url", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_d5_setwebhook_from_env_var_flags() -> None:
    """setWebhook URL from env var → flagged (env can be poisoned)."""
    src = (
        "async def install():\n"
        "    url = os.environ['TELEGRAM_WEBHOOK_URL']\n"
        "    await bot.set_webhook(url=url)\n"
    )
    assert _hits("chat-bot-telegram-setwebhook-attacker-url", src)


def test_d5_setwebhook_with_host_allowlist_suppressed() -> None:
    """setWebhook with `new URL(url).host` check → no hit."""
    src = (
        "app.post('/install/telegram', async (req, res) => {\n"
        "  const url = req.body.webhookUrl;\n"
        "  const host = new URL(url).hostname;\n"
        "  if (host !== 'api.example.com') return res.sendStatus(400);\n"
        "  await axios.post(`https://api.telegram.org/bot${BOT_TOKEN}/setWebhook`, { url });\n"
        "});\n"
    )
    assert not _hits("chat-bot-telegram-setwebhook-attacker-url", src)


def test_d5_setwebhook_hardcoded_url_silent() -> None:
    """setWebhook with a hardcoded HTTPS URL → no hit."""
    src = (
        "await axios.post(`https://api.telegram.org/bot${BOT_TOKEN}/setWebhook`, "
        "{ url: 'https://api.production.example.com/tg/webhook' });\n"
    )
    assert not _hits("chat-bot-telegram-setwebhook-attacker-url", src)


# ---------- D6 : chat-bot-token-type-confused-variable -------------------


def test_d6_startswith_http_with_url_and_token_usage_flags() -> None:
    """Variable used as URL AND as token, discriminated by startsWith('http') → HIGH hit."""
    src = (
        "const token = config.slackWebhook || process.env.SLACK_BOT_TOKEN || process.env.SLACK_WEBHOOK_URL;\n"
        "if (token.startsWith('http')) {\n"
        "  await axios.post(token, payload);\n"
        "} else {\n"
        "  const client = new WebClient(token);\n"
        "  await client.chat.postMessage({ channel, text });\n"
        "}\n"
    )
    hits = _hits("chat-bot-token-type-confused-variable", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d6_python_startswith_with_url_and_token_flags() -> None:
    """Python equivalent with .startswith('http') → flagged."""
    src = (
        "token = os.environ['SLACK_TOKEN_OR_URL']\n"
        "if token.startswith('http'):\n"
        "    requests.post(token, json=payload)\n"
        "else:\n"
        "    Bot(token).send_message(text)\n"
    )
    assert _hits("chat-bot-token-type-confused-variable", src)


def test_d6_startswith_http_url_only_no_token_silent() -> None:
    """Variable only used as URL (no WebClient/Bot context) → no hit."""
    src = (
        "const url = process.env.WEBHOOK_URL;\n"
        "if (url.startsWith('http')) {\n"
        "  await axios.post(url, payload);\n"
        "} else {\n"
        "  console.warn('not a URL');\n"
        "}\n"
    )
    assert not _hits("chat-bot-token-type-confused-variable", src)


# ---------- D7 : chat-bot-incoming-webhook-username-spoof ----------------


def test_d7_username_from_req_body_flags() -> None:
    """Slack webhook payload with username: req.body.botName → MEDIUM hit."""
    src = (
        "const SLACK_WEBHOOK_URL = process.env.SLACK_WEBHOOK_URL;\n"
        "await axios.post(SLACK_WEBHOOK_URL, {\n"
        "  text: msg,\n"
        "  username: req.body.botName,\n"
        "  icon_emoji: req.body.icon\n"
        "});\n"
    )
    hits = _hits("chat-bot-incoming-webhook-username-spoof", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d7_username_static_literal_safe() -> None:
    """Static literal username → no hit."""
    src = (
        "const slackWebhook = 'https://hooks.slack.com/services/T1/B1/abc';\n"
        "await axios.post(slackWebhook, {\n"
        "  text: msg,\n"
        "  username: 'opsbot',\n"
        "});\n"
    )
    assert not _hits("chat-bot-incoming-webhook-username-spoof", src)


def test_d7_no_slack_context_in_file_no_hit() -> None:
    """File without Slack webhook context → no FP fire."""
    src = (
        "await axios.post('https://api.example.com/foo', {\n"
        "  text: msg,\n"
        "  username: req.body.name,\n"
        "});\n"
    )
    assert not _hits("chat-bot-incoming-webhook-username-spoof", src)


# ---------- D8 : chat-bot-slack-postmessage-as-user-legacy ---------------


def test_d8_as_user_true_with_postmessage_flags() -> None:
    """`as_user: true` in a chat.postMessage call → LOW hit."""
    src = (
        "await client.chat.postMessage({\n"
        "  channel: 'C0123ABC',\n"
        "  text: msg,\n"
        "  as_user: true\n"
        "});\n"
    )
    hits = _hits("chat-bot-slack-postmessage-as-user-legacy", src)
    assert hits
    assert hits[0].severity == "LOW"


def test_d8_as_user_false_explicit_safe() -> None:
    """`as_user: false` explicit → no hit."""
    src = (
        "await client.chat.postMessage({\n"
        "  channel: 'C0123ABC',\n"
        "  text: msg,\n"
        "  as_user: false\n"
        "});\n"
    )
    assert not _hits("chat-bot-slack-postmessage-as-user-legacy", src)


def test_d8_as_user_true_no_slack_context_silent() -> None:
    """`as_user: true` in unrelated file (no WebClient/chat.postMessage) → silent."""
    src = "const opts = { as_user: true };\n"
    assert not _hits("chat-bot-slack-postmessage-as-user-legacy", src)


# ---------- D9 : chat-bot-slack-scope-overreach-users-read-email ---------


def test_d9_yaml_manifest_chat_write_and_users_email_flags() -> None:
    """YAML manifest with chat:write + users:read.email → MEDIUM hit."""
    src = (
        "oauth_config:\n"
        "  scopes:\n"
        "    bot:\n"
        "      - chat:write\n"
        "      - users:read.email\n"
        "      - users:read\n"
        "      - team:read\n"
    )
    hits = _hits("chat-bot-slack-scope-overreach-users-read-email", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d9_js_array_with_both_scopes_flags() -> None:
    """JS array literal with both scopes → flagged."""
    src = (
        "const installer = new InstallProvider({\n"
        "  scopes: ['chat:write', 'users:read.email', 'team:read'],\n"
        "});\n"
    )
    assert _hits("chat-bot-slack-scope-overreach-users-read-email", src)


def test_d9_chat_write_alone_no_email_silent() -> None:
    """Manifest with chat:write only (no users:read.email) → silent."""
    src = (
        "scopes:\n"
        "  bot:\n"
        "    - chat:write\n"
        "    - users:read\n"
    )
    assert not _hits("chat-bot-slack-scope-overreach-users-read-email", src)


def test_d9_users_email_alone_no_chat_write_silent() -> None:
    """Manifest with users:read.email only (no chat:write) → silent."""
    src = (
        "scopes:\n"
        "  bot:\n"
        "    - users:read.email\n"
        "    - team:read\n"
    )
    assert not _hits("chat-bot-slack-scope-overreach-users-read-email", src)


# ---------- D10 : chat-bot-slack-admin-scope -----------------------------


def test_d10_admin_users_read_flags() -> None:
    """admin.users:read in scope list → HIGH hit."""
    src = (
        "scopes:\n"
        "  bot:\n"
        "    - chat:write\n"
        "    - admin.users:read\n"
        "    - admin.conversations:write\n"
    )
    hits = _hits("chat-bot-slack-admin-scope", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d10_admin_scope_js_array_flags() -> None:
    """JS array literal with admin.conversations:write → flagged."""
    src = "const scopes = ['chat:write', 'admin.conversations:write'];\n"
    assert _hits("chat-bot-slack-admin-scope", src)


def test_d10_no_admin_scope_silent() -> None:
    """Plain scopes without admin.* → no hit."""
    src = (
        "scopes:\n"
        "  bot:\n"
        "    - chat:write\n"
        "    - users:read\n"
    )
    assert not _hits("chat-bot-slack-admin-scope", src)


# ---------- D11 : chat-bot-oauth-state-predictable-random ----------------


def test_d11_math_random_state_near_slack_authorize_flags() -> None:
    """Math.random()-derived state near slack.com/oauth/v2/authorize → MEDIUM hit."""
    src = (
        "app.get('/install/slack', (req, res) => {\n"
        "  const state = Math.random().toString(36).slice(2);\n"
        "  res.redirect(`https://slack.com/oauth/v2/authorize?client_id=X&state=${state}`);\n"
        "});\n"
    )
    hits = _hits("chat-bot-oauth-state-predictable-random", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d11_uuid1_state_near_discord_authorize_flags() -> None:
    """uuid.uuid1()-derived state near discord oauth URL → flagged."""
    src = (
        "state = str(uuid.uuid1())\n"
        "url = f'https://discord.com/oauth2/authorize?client_id=X&state={state}'\n"
    )
    assert _hits("chat-bot-oauth-state-predictable-random", src)


def test_d11_crypto_randombytes_state_safe() -> None:
    """crypto.randomBytes-derived state → no hit (safe shape)."""
    src = (
        "app.get('/install/slack', (req, res) => {\n"
        "  const state = crypto.randomBytes(32).toString('hex');\n"
        "  res.redirect(`https://slack.com/oauth/v2/authorize?state=${state}`);\n"
        "});\n"
    )
    assert not _hits("chat-bot-oauth-state-predictable-random", src)


def test_d11_math_random_state_no_oauth_url_silent() -> None:
    """Math.random() state but no OAuth URL in file → silent."""
    src = "const state = Math.random().toString(36).slice(2);\n"
    assert not _hits("chat-bot-oauth-state-predictable-random", src)


# ---------- D12 : chat-bot-discord-message-content-intent-undisclosed ----


def test_d12_message_content_gateway_intent_flags() -> None:
    """`GatewayIntentBits.MessageContent` → MEDIUM hit."""
    src = (
        "const client = new Client({\n"
        "  intents: [\n"
        "    GatewayIntentBits.Guilds,\n"
        "    GatewayIntentBits.MessageContent,\n"
        "  ]\n"
        "});\n"
    )
    hits = _hits("chat-bot-discord-message-content-intent-undisclosed", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_d12_python_message_content_true_flags() -> None:
    """discord.py `intents.message_content = True` → flagged."""
    src = (
        "intents = discord.Intents.default()\n"
        "intents.message_content = True\n"
    )
    assert _hits("chat-bot-discord-message-content-intent-undisclosed", src)


def test_d12_intents_without_message_content_silent() -> None:
    """Intents without MessageContent → silent."""
    src = (
        "const client = new Client({\n"
        "  intents: [GatewayIntentBits.Guilds]\n"
        "});\n"
    )
    assert not _hits("chat-bot-discord-message-content-intent-undisclosed", src)


# ---------- D13 : chat-bot-discord-bot-token-in-client-bundle ------------


def test_d13_discord_bot_token_literal_flags() -> None:
    """client.login('<JWT-shape token>') → CRITICAL hit."""
    src = (
        "client.login('MzkyNDI0NTM4OTc2MzMyOTI4."
        "X-pGGw.gMqzWZQHy_bX5pFy_AaFXQJ4dCo123');\n"
    )
    hits = _hits("chat-bot-discord-bot-token-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_d13_discord_login_from_env_with_bundler_config_flags() -> None:
    """client.login(process.env.X) in same file as webpack entry config → flagged."""
    src = (
        "module.exports = {\n"
        "  entry: './src/index.js',\n"
        "  mode: 'production'\n"
        "};\n"
        "client.login(process.env.DISCORD_BOT_TOKEN);\n"
    )
    assert _hits("chat-bot-discord-bot-token-in-client-bundle", src)


def test_d13_discord_login_from_env_no_bundle_marker_silent() -> None:
    """client.login(process.env.X) without bundler config → silent."""
    src = "client.login(process.env.DISCORD_BOT_TOKEN);\n"
    assert not _hits("chat-bot-discord-bot-token-in-client-bundle", src)


# ---------- D14 : chat-bot-telegram-token-in-url-path-loglevel -----------


def test_d14_telegram_url_path_with_err_config_log_flags() -> None:
    """Telegram URL construction + err.config log → HIGH hit."""
    src = (
        "axios.post(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, opts)\n"
        "  .catch(err => console.error('Telegram failed:', err.response.config.url, err.message));\n"
    )
    hits = _hits("chat-bot-telegram-token-in-url-path-loglevel", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d14_json_stringify_err_flags() -> None:
    """Telegram URL + JSON.stringify(err) catch → flagged."""
    src = (
        "fetch(`https://api.telegram.org/bot${TOKEN}/sendMessage`)\n"
        "  .catch(err => console.error('Telegram error:', JSON.stringify(err)));\n"
    )
    assert _hits("chat-bot-telegram-token-in-url-path-loglevel", src)


def test_d14_bare_err_message_safe() -> None:
    """Telegram URL + bare err.message log (no .config) → no hit."""
    src = (
        "axios.post(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, opts)\n"
        "  .catch(err => console.error('Telegram failed:', err.message));\n"
    )
    assert not _hits("chat-bot-telegram-token-in-url-path-loglevel", src)


def test_d14_redact_marker_in_file_suppresses() -> None:
    """File with redact marker (replace /bot\\d/) → suppresses entirely."""
    src = (
        "axios.post(`https://api.telegram.org/bot${TOKEN}/sendMessage`, opts)\n"
        "  .catch(err => {\n"
        "    const safe = err.message.replace(/bot\\d+:[A-Za-z0-9_-]+/g, '[REDACTED]');\n"
        "    console.error('Telegram failed:', safe);\n"
        "  });\n"
    )
    assert not _hits("chat-bot-telegram-token-in-url-path-loglevel", src)


# ---------- D15 : chat-bot-webhook-url-from-untrusted-config -------------


def test_d15_settings_endpoint_no_host_validation_flags() -> None:
    """Settings endpoint accepting slackWebhook without host check → HIGH hit."""
    src = (
        "app.post('/api/settings/notifications', requireAuth, (req, res) => {\n"
        "  const { slackWebhook, discordWebhook, teamsWebhook } = req.body;\n"
        "  if (slackWebhook !== undefined && typeof slackWebhook === 'string') {\n"
        "    updates.slackWebhook = slackWebhook;\n"
        "  }\n"
        "  res.send();\n"
        "});\n"
    )
    hits = _hits("chat-bot-webhook-url-from-untrusted-config", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_d15_settings_with_host_validation_suppressed() -> None:
    """Same endpoint WITH `new URL(slackWebhook).hostname` check → no hit."""
    src = (
        "app.post('/api/settings/notifications', (req, res) => {\n"
        "  const { slackWebhook } = req.body;\n"
        "  const host = new URL(slackWebhook).hostname;\n"
        "  if (host !== 'hooks.slack.com') return res.status(400).send();\n"
        "  updates.slackWebhook = slackWebhook;\n"
        "});\n"
    )
    assert not _hits("chat-bot-webhook-url-from-untrusted-config", src)


def test_d15_settings_with_allowed_hosts_constant_suppresses() -> None:
    """Endpoint with ALLOWED_HOSTS constant → no hit."""
    src = (
        "const ALLOWED_HOSTS = new Set(['hooks.slack.com']);\n"
        "app.post('/api/integrations/slack', (req, res) => {\n"
        "  const { slackWebhook } = req.body;\n"
        "  if (!ALLOWED_HOSTS.has(new URL(slackWebhook).hostname)) {\n"
        "    return res.sendStatus(400);\n"
        "  }\n"
        "  storeWebhook(slackWebhook);\n"
        "});\n"
    )
    assert not _hits("chat-bot-webhook-url-from-untrusted-config", src)


def test_d15_unrelated_settings_endpoint_silent() -> None:
    """Settings endpoint NOT accepting a webhook URL → silent."""
    src = (
        "app.post('/api/settings/profile', requireAuth, (req, res) => {\n"
        "  const { displayName } = req.body;\n"
        "  user.displayName = displayName;\n"
        "  res.send();\n"
        "});\n"
    )
    assert not _hits("chat-bot-webhook-url-from-untrusted-config", src)


# ---------- Integration sanity --------------------------------------------


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list (mutable) — same as sibling modules."""
    out = cbp.scan_text("nothing to see here")
    assert isinstance(out, list)


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    # Webhook URL secret body generated at runtime — no credential literal in source.
    _slack_url = _slack_hook("multi-rules-slack-url")
    src = (
        # D1 hit
        f"const SLACK = '{_slack_url}';\n"
        # D10 hit
        "// scopes: admin.users:read\n"
    )
    findings = cbp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "chat-bot-webhook-url-literal-committed" in rule_ids
    assert "chat-bot-slack-admin-scope" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module describes chat-bot integration patterns. It does not\n"
        "contain any live URLs or tokens. The author writes about Slack\n"
        "in prose only, not in code form.\n"
    )
    assert cbp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    # Webhook URL secret body generated at runtime — no credential literal in source.
    _slack_url = _slack_hook("dedup-slack-url")
    src = f"const X = '{_slack_url}';\n"
    findings = cbp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
