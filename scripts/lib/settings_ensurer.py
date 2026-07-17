"""Ensure a fixed set of recommended Claude Code settings exist in ~/.claude/settings.json.

Run once per session by the SessionStart hook (beside `rules_installer.install_rules`). Two
DISTINCT merge modes, per the user's spec (TRDD-EQ792YPX):

- **Group A — env keys → the top-level `env` block, ADD-IF-MISSING.** A key is "missing" iff it is
  absent from the `env` block (the "env setting values"); an existing value is NEVER overwritten
  (the user's own choice wins).
- **Group B — top-level keys → ENFORCE (set-if-missing-OR-different).** The janitor owns the value:
  if absent or different, it is set/overwritten to the recommended value.

These settings are read at Claude Code STARTUP, so anything added/changed here takes effect on the
NEXT launch, not the current session — the hook's notice says so.

Safety (all load-bearing):
- The settings path is resolved AT CALL TIME (`_settings_path`), NEVER as a module-level constant —
  a frozen `Path.home()` is computed at import, before a test's `monkeypatch.setenv("HOME")`, so a
  module constant would make a test write the USER'S REAL settings.json (the
  `janitor-keepalive-test-isolation-fsevents` class of leak — it once crashed the host).
- A malformed / unreadable / non-object settings.json is LEFT UNTOUCHED (we never clobber a config
  we could not parse). Missing/empty → treated as `{}`.
- We WRITE ONLY WHEN THERE IS A DELTA, so after the first session on a machine every later session
  is a pure read. The write is atomic (`state.atomic_write` = tmp + os.replace, never a torn file)
  and serialised across sessions by `global_state.settings_ensurer_lock` (idempotency already
  prevents key loss; the lock removes the write-write race and guards future non-idempotent change).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Optional

import global_state as gs
import state

# Group A — added to the `env` block only if the key is absent there. Values are strings
# (env vars are always strings). CLAUDE_CODE_FORK_SUBAGENT appeared twice in the user's list;
# a dict naturally dedupes it.
#
# AFK note (per the CC env-vars doc): CLAUDE_AFK_TIMEOUT_MS is the idle time (ms) before an
# unanswered AskUserQuestion auto-continues, and it OVERRIDES the top-level askUserQuestionTimeout
# setting (Group B) when set — so 300000 here (5 min) is the effective timeout regardless of the
# Group-B value. CLAUDE_AFK_COUNTDOWN_MS is the on-screen warning countdown before that fires and
# is CAPPED at the timeout, so it must stay <= CLAUDE_AFK_TIMEOUT_MS (20000 = a 20 s warning).
ENV_ADD_IF_MISSING: dict[str, str] = {
    "ENABLE_BACKGROUND_TASKS": "1",
    "ENABLE_TOOL_SEARCH": "false",
    "CLAUDE_CODE_FORK_SUBAGENT": "1",
    "CLAUDE_AUTO_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_RETRY_WATCHDOG": "1",
    "CLAUDE_AFK_COUNTDOWN_MS": "20000",
    "CLAUDE_AFK_TIMEOUT_MS": "300000",
    "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": "2000000",
}

# Group B — set at the TOP LEVEL, overwriting when absent or different. Stored verbatim as the
# user specified: "60s" — the trailing "s" (seconds) is why the value is a string, not a number.
# This is a SAFE FALLBACK only: CLAUDE_AFK_TIMEOUT_MS (Group A, 300000) overrides it whenever it is
# set, so the effective auto-continue is 5 min; this 60 s applies only if that env var is unset.
TOP_LEVEL_ENFORCE: dict[str, object] = {
    "askUserQuestionTimeout": "60s",
}

# userConfig key `ensure_settings_enabled` → this env var (see .claude-plugin/plugin.json).
_OPTION_ENV = "CLAUDE_PLUGIN_OPTION_ENSURE_SETTINGS_ENABLED"


def enabled() -> bool:
    """Master opt-out. Default ON. Set the userConfig `ensure_settings_enabled` false to disable."""
    return bool(state.is_truthy_env(_OPTION_ENV, True))


def _settings_path(home: Optional[Path] = None) -> Path:
    """The user-scope settings.json, resolved AT CALL TIME so a test's monkeypatched HOME is
    honored. NEVER cache this as a module constant (see module docstring)."""
    base = Path(home) if home is not None else Path.home()
    return base / ".claude" / "settings.json"


def _load_settings(path: Path) -> Optional[dict]:
    """Read settings.json into a dict. Missing/empty → `{}`. Malformed JSON, an unreadable file, or
    a non-object top level → `None` (ABORT — never clobber a config we could not parse)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:  # JSONDecodeError is a ValueError subclass
        return None
    if not isinstance(data, dict):
        return None
    return data


def _env_block_ok(data: dict) -> bool:
    """True unless `env` is present but NOT an object — in which case merging would mean replacing
    the user's value, so we abort rather than clobber."""
    return "env" not in data or isinstance(data["env"], dict)


def _compute_delta(data: dict) -> tuple[list[str], list[str]]:
    """(env keys to add, top-level keys to set) for `data`. Pure — no I/O."""
    env_block = data.get("env")
    env_present = env_block if isinstance(env_block, dict) else {}
    env_add = [k for k in ENV_ADD_IF_MISSING if k not in env_present]
    top_set = [k for k, v in TOP_LEVEL_ENFORCE.items() if data.get(k) != v]
    return env_add, top_set


def _verify_invariants(
    original: dict, result: dict, env_add: list[str], top_set: list[str]
) -> tuple[bool, str]:
    """Prove `result` differs from `original` ONLY by the intended edits — the whole point of the
    supersecure write. Pure. Returns (ok, reason); reason is a short diagnostic when not ok.

    Intended edits: Group-A env keys in `env_add` ADDED to the `env` block with their recommended
    values; Group-B keys in `top_set` SET at top level to their enforced values. Everything else —
    every other top-level key, every pre-existing env key, the presence of every original key — must
    be byte-for-byte the same. Any deviation means the merge (or the on-disk write) corrupted the
    file, so the caller must NOT swap it in.
    """
    enforced = set(TOP_LEVEL_ENFORCE)

    # (a) The intended top-level changes are present and correct.
    for k in top_set:
        if result.get(k) != TOP_LEVEL_ENFORCE[k]:
            return False, f"enforced top-level {k!r} not set to {TOP_LEVEL_ENFORCE[k]!r}"

    # (b) Every ORIGINAL top-level key is unchanged, except an enforced key we intended to overwrite.
    for k, v in original.items():
        if k == "env":
            continue  # the env block is checked below
        if k in enforced and k in top_set:
            continue  # this key's change was intended
        if result.get(k) != v:
            return False, f"unrelated top-level key {k!r} changed"

    # (c) No UNEXPECTED top-level key was added (allowed new keys: enforced keys + a created `env`).
    allowed_new_top = enforced | {"env"}
    for k in result:
        if k not in original and k not in allowed_new_top:
            return False, f"unexpected new top-level key {k!r}"

    # (d) No top-level key was removed.
    for k in original:
        if k not in result:
            return False, f"top-level key {k!r} was removed"

    # (e) env block: additions present+correct, originals unchanged, nothing extra, nothing removed.
    orig_env_raw = original.get("env")
    orig_env = orig_env_raw if isinstance(orig_env_raw, dict) else {}
    res_env = result.get("env")
    if not isinstance(res_env, dict):
        return False, "result 'env' is not an object"
    for k in env_add:
        if res_env.get(k) != ENV_ADD_IF_MISSING[k]:
            return False, f"env key {k!r} not added as {ENV_ADD_IF_MISSING[k]!r}"
    for k, v in orig_env.items():
        if res_env.get(k) != v:
            return False, f"existing env key {k!r} changed"
    allowed_env = set(orig_env) | set(env_add)
    for k in res_env:
        if k not in allowed_env:
            return False, f"unexpected new env key {k!r}"
    for k in orig_env:
        if k not in res_env:
            return False, f"env key {k!r} was removed"

    return True, ""


def _verified_atomic_write(
    path: Path, original: dict, result: dict, env_add: list[str], top_set: list[str]
) -> bool:
    """SUPERSECURE write: serialise `result`, write it to a SAME-DIR tmp, then — before swapping —
    RE-READ the tmp from disk and prove it (1) is valid JSON, (2) round-trips exactly to `result`,
    and (3) differs from `original` ONLY by the intended edits (`_verify_invariants`). ONLY when all
    three pass does it `os.replace` the tmp into place (atomic). On ANY failure the tmp is removed
    and the LIVE FILE IS LEFT UNTOUCHED. Returns True iff the swap happened.

    Re-reading the tmp FROM DISK (not trusting the in-memory string) is deliberate: it catches a
    truncated/short write or an encoding fault in the exact bytes that would become the live file.
    """
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    swapped = False
    try:
        # "Create settings.json if missing" includes its PARENT: on a brand-new HOME
        # ~/.claude does not exist yet and the same-dir tmp write ENOENTs (caught by
        # the harness thin-mode control test). Idempotent on every real machine.
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        # (1) valid JSON on disk + (2) exact round-trip — verify the ACTUAL bytes, not our string.
        reparsed = json.loads(tmp.read_text(encoding="utf-8"))
        if reparsed != result:
            state.log_line("session-start", "settings-ensurer: tmp round-trip mismatch — NOT swapping")
            return False
        # (3) only the intended values changed.
        ok, reason = _verify_invariants(original, reparsed, env_add, top_set)
        if not ok:
            state.log_line("session-start", f"settings-ensurer: invariant check failed ({reason}) — NOT swapping")
            return False
        os.replace(tmp, path)  # atomic swap — reached ONLY after every check passed
        swapped = True
        return True
    except (OSError, ValueError) as exc:
        state.log_line("session-start", f"settings-ensurer: verified write failed ({exc}) — NOT swapping")
        return False
    finally:
        if not swapped:
            try:
                tmp.unlink()
            except OSError:
                pass


def ensure_recommended_settings(*, home: Optional[Path] = None) -> dict[str, list[str]]:
    """Ensure the recommended settings exist in ~/.claude/settings.json.

    Returns `{"env_added": [...], "top_level_set": [...]}` naming what CHANGED (empty when nothing
    needed doing, when disabled, or when the file was left untouched for safety). Never raises for
    an expected condition; the caller still wraps it defensively.
    """
    if not enabled():
        return {"env_added": [], "top_level_set": []}

    path = _settings_path(home)

    # Cheap pre-check WITHOUT the lock: if there is no delta (the common case after the first
    # session applied everything), do nothing — no lock, no write.
    data = _load_settings(path)
    if data is None or not _env_block_ok(data):
        state.log_line("session-start", f"settings-ensurer: {path} unreadable/malformed — left untouched")
        return {"env_added": [], "top_level_set": []}
    env_add, top_set = _compute_delta(data)
    if not env_add and not top_set:
        return {"env_added": [], "top_level_set": []}

    # A delta exists → serialise the read-merge-write against other sessions' ensurers.
    with gs.settings_ensurer_lock() as got:
        if not got:
            # Another session is applying the IDENTICAL settings — skip (idempotent).
            return {"env_added": [], "top_level_set": []}
        # RE-READ under the lock: the file may have changed since the pre-check.
        data = _load_settings(path)
        if data is None or not _env_block_ok(data):
            state.log_line(
                "session-start", f"settings-ensurer: {path} unreadable/malformed under lock — left untouched"
            )
            return {"env_added": [], "top_level_set": []}
        env_add, top_set = _compute_delta(data)
        if not env_add and not top_set:
            return {"env_added": [], "top_level_set": []}
        # Build the RESULT as a deepcopy so `data` stays the untouched ORIGINAL that the supersecure
        # write compares against. json.loads→dumps preserves the user's key ORDER and content; only
        # whitespace is normalised to indent=2, and our new keys append at the end.
        original = data
        result = copy.deepcopy(original)
        env_block = result.setdefault("env", {})
        for k in env_add:
            env_block[k] = ENV_ADD_IF_MISSING[k]
        for k in top_set:
            result[k] = TOP_LEVEL_ENFORCE[k]
        if not _verified_atomic_write(path, original, result, env_add, top_set):
            # Verification refused the swap → the live file was NOT touched; it is exactly as found.
            return {"env_added": [], "top_level_set": []}

    return {"env_added": env_add, "top_level_set": top_set}
