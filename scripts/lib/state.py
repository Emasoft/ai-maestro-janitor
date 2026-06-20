# Shared state helpers for ai-maestro-janitor hooks and detectors —
# Python port of scripts/lib/state.sh. Keep the surface AS CLOSE to the
# bash original as possible so a detector can call the same names.
#
# Imported (not invoked as a script) so no PEP 723 metadata block here.
# Stdlib-only — pathlib + os + subprocess + datetime are all that's used.

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

# --- path resolution -------------------------------------------------------

# CPV-skillaudit: avoid reserved-env mutation. A caller (e.g. the PostCompact
# hook, whose environment may lack CLAUDE_PROJECT_DIR) can supply a fallback
# project dir WITHOUT writing the reserved $CLAUDE_PROJECT_DIR into the process
# environment — exporting that harness-set var session-wide would clobber it for
# every other plugin. The override is module-local and is consulted ONLY when
# CLAUDE_PROJECT_DIR is absent, so the env var always wins (guarded fallback,
# identical to the old behaviour where the hook set the env var before the first
# resolution).
_PROJECT_DIR_OVERRIDE: Optional[str] = None


def set_project_dir_override(cwd: Optional[str]) -> None:
    """Record a fallback project dir used only when CLAUDE_PROJECT_DIR is unset.

    Does NOT touch os.environ (the reserved-env mutation CPV flags). Must be
    called BEFORE the first project_root()/state_dir()/... call, since those are
    lru-cached for the process lifetime.
    """
    global _PROJECT_DIR_OVERRIDE
    _PROJECT_DIR_OVERRIDE = (cwd or "").strip() or None


def _resolve_project_root() -> Path:
    """Equivalent to bash's resolve_project_root.

    Priority:
      1. $CLAUDE_PROJECT_DIR
      2. the caller-supplied override (set_project_dir_override) — used only
         when CLAUDE_PROJECT_DIR is absent, so the env var always wins
      3. `git rev-parse --show-toplevel`
      4. cwd
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if explicit:
        return Path(explicit)
    if _PROJECT_DIR_OVERRIDE:
        return Path(_PROJECT_DIR_OVERRIDE)
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(proc.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


# Cached so repeated imports/calls don't re-run git. The cache keys on the
# (single, optional) argument; the normal no-arg call caches under key () so it
# stays an effective module-level singleton — recomputed only if the module is
# re-imported in a fresh process (the lifetime we care about). `.cache_clear()`
# is preserved (tests rely on it).
#
# The optional `cwd_override` is a convenience for the no-env case: passing it
# records the module-level override (so the cached janitor_root()/state_dir()
# resolve from the same fallback) AND returns the resolved root. It is honoured
# only when CLAUDE_PROJECT_DIR is absent. Pass nothing for the normal cached
# call — every existing caller does exactly that and is unaffected.
@lru_cache(maxsize=2)
def project_root(cwd_override: Optional[str] = None) -> Path:
    if cwd_override is not None:
        set_project_dir_override(cwd_override)
    return _resolve_project_root()


@lru_cache(maxsize=1)
def janitor_root() -> Path:
    return project_root() / ".janitor"


@lru_cache(maxsize=1)
def state_dir() -> Path:
    return janitor_root() / "state"


@lru_cache(maxsize=1)
def log_dir() -> Path:
    # The global daemon overrides this via JANITOR_LOG_DIR so its log lands
    # in the deterministic global-state dir instead of whatever project tree
    # happened to spawn it (see daemon.py main()). Per-session detectors leave
    # it unset and keep their project-scoped logs under <project>/.janitor/logs.
    # Set once per process and read here before the lru_cache memoises it.
    override = os.environ.get("JANITOR_LOG_DIR")
    if override:
        return Path(override).expanduser()
    return janitor_root() / "logs"


# --- public API ------------------------------------------------------------

def init_state() -> None:
    """Create state/ and logs/ directories if missing. Idempotent."""
    state_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)


def atomic_write(target: Path, value: str) -> None:
    """Atomic-by-rename write: write to tmp, then os.replace into place.

    `os.replace` is atomic on POSIX and Windows (per Python docs), so a
    concurrent reader sees either the old content or the new — never a
    half-written file.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(value)
    os.replace(tmp, target)


# --- host-level user-presence breadcrumb (TRDD-fb4850b5, janitor#15) --------
#
# A cross-plugin host file the MANAGER's `amama-presence-tracker` reads as a
# *server-unreachable fallback*. It deliberately lives under ~/.aimaestro/state/
# (a shared host path) rather than ${CLAUDE_PLUGIN_DATA} (janitor-private, which
# the MANAGER cannot locate) — a documented exception to the "prefer PLUGIN_DATA"
# principle precisely because this is a shared contract.
#
# The on-disk shape is exactly three fields (byte-agreed with the MANAGER on
# janitor#15 — NO extra fields like source_pid/version, which were never
# confirmed):
#   {"last_user_input_epoch": <int>, "source": "janitor", "written_at_epoch": <int>}
#
# - last_user_input_epoch — bumped ONLY on a genuine user prompt (the hook), NOT
#   on a cron `[janitor-…]` heartbeat prompt.
# - written_at_epoch — refreshed every heartbeat tick (liveness), independent of
#   input recency. The tracker treats the breadcrumb as stale (→ "unknown") once
#   written_at_epoch is older than its threshold.
_PRESENCE_SOURCE = "janitor"


def user_presence_path(home: Path | None = None) -> Path:
    """Path of the cross-plugin user-presence breadcrumb under HOME.

    Defaults to `Path.home()` so a `HOME` override (set by tests or by the
    harness) is honoured naturally; callers may pass an explicit `home` to
    pin it.
    """
    base = Path(home) if home is not None else Path.home()
    return base / ".aimaestro" / "state" / "user-presence.json"


def _write_user_presence(path: Path, last_user_input_epoch: int, written_at_epoch: int) -> None:
    """Atomically write the three-field breadcrumb. Single serialization site."""
    payload = json.dumps(
        {
            "last_user_input_epoch": int(last_user_input_epoch),
            "source": _PRESENCE_SOURCE,
            "written_at_epoch": int(written_at_epoch),
        }
    )
    atomic_write(path, payload)


def bump_user_presence(home: Path | None = None, now: int | None = None) -> None:
    """Record a GENUINE user-input event — stamp BOTH epochs to `now`.

    Called by the UserPromptSubmit hook ONLY for real user prompts (cron
    `[janitor-…]` prompts must be filtered out by the caller first). Best-effort:
    any filesystem error is swallowed so the user's turn is never aborted.
    """
    ts = int(time.time()) if now is None else int(now)
    try:
        _write_user_presence(user_presence_path(home), ts, ts)
    except OSError:
        # Never crash the session on a breadcrumb write failure.
        pass


def refresh_user_presence_written_at(home: Path | None = None, now: int | None = None) -> None:
    """Refresh the breadcrumb's liveness (written_at_epoch) WITHOUT touching input recency.

    Called by the heartbeat each tick. Preserves the existing
    `last_user_input_epoch` when the file exists and parses to a dict with an
    int value; seeds `0` when the file is absent, corrupt, a non-dict, or has a
    non-int `last_user_input_epoch`. Best-effort — never propagates an error so
    a breadcrumb problem cannot break dispatch.
    """
    ts = int(time.time()) if now is None else int(now)
    path = user_presence_path(home)
    last_input = 0
    try:
        existing = json.loads(path.read_text())
        if isinstance(existing, dict):
            value = existing.get("last_user_input_epoch")
            # bool is an int subclass — reject it so a stray `true` doesn't become 1.
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                last_input = value
    except (FileNotFoundError, OSError, ValueError):
        # Absent or unreadable/undecodable → seed 0 (handled below). ValueError
        # covers json.JSONDecodeError (its subclass).
        last_input = 0
    try:
        _write_user_presence(path, last_input, ts)
    except OSError:
        pass


def read_int_state(path: Path | str, default: int = 0) -> int:
    """Read a non-negative int from a state file.

    Falls back to `default` on any read error or non-numeric content.
    Detector arithmetic runs under guard rails — a corrupted state file
    must NOT abort the whole heartbeat. The earlier bash port crashed on
    timestamp subtraction when the stored value was non-numeric; the
    Python rewrite avoids that footgun and degrades gracefully.
    """
    try:
        content = Path(path).read_text().strip()
    except (FileNotFoundError, OSError):
        return default
    if content.isdigit():
        return int(content)
    return default


def is_truthy_env(name: str, default: bool) -> bool:
    """Read a yes/no env var with friendly false-spellings.

    Empty / unset → `default`. Otherwise: `false`/`0`/`no`/`off`
    (case-insensitive) → False; anything else → True.

    Three detectors duplicated this function byte-for-byte; promoting it
    here keeps the spelling-of-false rules in one place so a future
    addition (e.g. `disabled`) doesn't drift between callers.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() not in ("false", "0", "no", "off")


def coerce_int(
    value: Optional[str],
    default: int = 0,
    *,
    detector_name: Optional[str] = None,
    var_name: Optional[str] = None,
) -> int:
    """Coerce a (possibly user-supplied) value to a non-negative int.

    Accepts None, empty string, and non-numeric text — all return
    `default`. Used for `CLAUDE_PLUGIN_OPTION_*` env vars where a typo
    like "900 seconds" should not crash the heartbeat.

    If `detector_name` is provided AND a non-empty value failed to
    coerce, log a one-line note so the user can see in the detector
    log that their config knob is being ignored. The log fires only
    on the "had a value but it wasn't a number" case — empty/unset
    values (the common path) stay silent. `var_name` lets the log
    point at the offending env var.
    """
    if value is None:
        return default
    s = value.strip()
    if not s:
        return default
    if not s.isdigit():
        if detector_name:
            label = var_name or "config value"
            log_line(
                detector_name,
                f"coerce_int: {label}={s!r} is not a non-negative integer — using default {default}",
            )
        return default
    return int(s)


def autofix_mode() -> str:
    """Return the current autofix mode for this project — "on" or "off".

    The sentinel file `.janitor/state/autofix-mode.txt` (one of "on" /
    "off", any case, optional whitespace) is the source of truth. When
    the file is absent OR unreadable OR contains anything else, the
    default `"on"` applies — matching the standing "act, don't ask"
    policy the user set for security/CI/publish hardening.

    Helpers `autofix_enabled()` and `autofix_disabled()` are the
    boolean conveniences callers should reach for; this string variant
    exists for the heartbeat's drift-line text.
    """
    path = state_dir() / "autofix-mode.txt"
    try:
        raw = path.read_text(encoding="utf-8").strip().lower()
    except (FileNotFoundError, OSError):
        return "on"
    return "off" if raw == "off" else "on"


def autofix_enabled() -> bool:
    """True iff the "act, don't ask" autofix policy is active."""
    return autofix_mode() == "on"


def autofix_disabled() -> bool:
    """True iff `/janitor-autofix-off` has been run in this project."""
    return autofix_mode() == "off"


# --- self-scan guard -----------------------------------------------------

# The plugin's own canonical name — read from the source of truth on first
# call to avoid drift if the package is ever renamed. The constant below is
# the fallback used when the lookup itself fails (e.g. corrupted manifest).
_JANITOR_NAME = "ai-maestro-janitor"


@lru_cache(maxsize=1)
def is_self_scan_target() -> bool:
    """True iff the current `CLAUDE_PROJECT_DIR` is the janitor's own repo.

    Detection: the project root has a `.claude-plugin/plugin.json` whose
    top-level `"name"` equals "ai-maestro-janitor". This is the most
    reliable signal — robust to forks (rename the plugin, lose the
    self-scan suppression), worktree paths, sibling clones, and the
    janitor being checked out under any directory name.

    Why this exists:
      * The janitor IS a plugin that scans repos for repo-security
        issues. When the user arms the janitor inside its own source
        repo (the natural case during plugin development), every
        security detector would emit findings against the janitor's
        own CI — confusing self-reports that look like a feedback
        loop and clutter the heartbeat with noise the maintainer
        already audits via `publish.py` and the GitHub Actions CI.

      * Hard rule: a security scanner must not produce findings about
        its own host project. Every security/CI detector calls
        `if state.is_self_scan_target(): return 0` at the top of
        `main()` to enforce this.

    Override (for dev/CI):
      Set `CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1` to force scanning of the
      janitor's own repo. The official CI publish-gate uses this so
      the janitor's own CI keeps catching regressions in its own
      workflow files.
    """
    if os.environ.get("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False
    manifest = project_root() / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return False
    try:
        # Lazy import to avoid pulling json into every script that imports
        # state for the path helpers only.
        import json as _json
        data = _json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("name") == _JANITOR_NAME


# --- ai-maestro context gate (TRDD-db169d9e R1) --------------------------

# The canonical ai-maestro-plugins marketplace member set — the fallback used
# when the live catalog can't be read. The janitor is installed FROM this
# marketplace so the catalog is normally present, but the gate must NEVER depend
# on that. Kept in sync with the marketplace's
# `.claude-plugin/marketplace.json` `plugins` list; the live read below UNIONs
# anything new in, so a member added after this constant was last edited is still
# recognised. Both sources only ever list real members, so the union can never
# wrongly include a non-member.
_AI_MAESTRO_MARKETPLACE = "ai-maestro-plugins"
_AI_MAESTRO_FLEET = frozenset({
    "ai-maestro-plugin",
    "ai-maestro-assistant-manager-agent",
    "ai-maestro-chief-of-staff",
    "ai-maestro-architect-agent",
    "ai-maestro-orchestrator-agent",
    "ai-maestro-integrator-agent",
    "ai-maestro-programmer-agent",
    "ai-maestro-maintainer-agent",
    "ai-maestro-autonomous-agent",
    "ai-maestro-janitor",
    "ai-maestro-visual-communicator-plugin",
})


def _plugins_root() -> Path:
    """The Claude plugins root (`~/.claude/plugins`), env-overridable for tests."""
    override = os.environ.get("JANITOR_PLUGINS_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "plugins"


@lru_cache(maxsize=1)
def ai_maestro_marketplace_members() -> frozenset[str]:
    """Return every plugin name that belongs to the `ai-maestro-plugins` marketplace.

    Source of truth is the installed marketplace catalog at
    `<plugins-root>/marketplaces/ai-maestro-plugins/.claude-plugin/marketplace.json`
    (present on every machine the janitor runs on — the janitor is installed FROM
    that marketplace). The hard-coded `_AI_MAESTRO_FLEET` is unioned in as a
    fallback so the gate never under-recognises a known member when the catalog
    read fails. Cached for the process lifetime; tests call `.cache_clear()`.
    """
    members = set(_AI_MAESTRO_FLEET)
    root = _plugins_root()
    for rel in (
        Path("marketplaces") / _AI_MAESTRO_MARKETPLACE / ".claude-plugin" / "marketplace.json",
        Path("marketplaces") / _AI_MAESTRO_MARKETPLACE / "marketplace.json",
    ):
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("name") != _AI_MAESTRO_MARKETPLACE:
            continue
        for entry in data.get("plugins", []):
            name = entry.get("name") if isinstance(entry, dict) else entry
            if isinstance(name, str) and name:
                members.add(name)
        break
    return frozenset(members)


@lru_cache(maxsize=1)
def project_is_ai_maestro() -> bool:
    """True iff the CURRENT project is a plugin of the `ai-maestro-plugins` marketplace.

    The master context gate (TRDD-db169d9e R1). The janitor is installed at USER
    scope, so it runs in EVERY project — ai-maestro or not. ai-maestro-SPECIFIC
    detectors/skills (TRDD/PRRD/AMP/fleet-coordination) consult this gate and
    self-deactivate when it is False, so the janitor stays silent about ai-maestro
    conventions in unrelated projects. Generic detectors (git hygiene, security,
    cleanup) ignore the gate and run everywhere.

    Detection: the project root has a `.claude-plugin/plugin.json` whose top-level
    `"name"` is a member of the ai-maestro-plugins marketplace (see
    `ai_maestro_marketplace_members`). A project with no plugin manifest — or whose
    plugin name is not a marketplace member — is NOT ai-maestro.

    Override: set `JANITOR_FORCE_AI_MAESTRO` to a truthy value (1/true/yes/on) to
    force the gate ON, or a falsy value (0/false/no/off) to force it OFF — for
    tests, or a project the user wants treated either way.
    """
    forced = os.environ.get("JANITOR_FORCE_AI_MAESTRO", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    manifest = project_root() / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    name = data.get("name")
    return isinstance(name, str) and name in ai_maestro_marketplace_members()


def is_ai_maestro_plugin_id(plugin_id: str) -> bool:
    """True iff `plugin_id` (a `<name>@<marketplace>` id from `claude plugin
    list`) belongs to the ai-maestro-plugins marketplace.

    Used by the daemon to EXCLUDE the ai-maestro fleet from its per-plugin
    auto-update (TRDD-db169d9e R2): fleet versions are owned by each plugin's own
    release pipeline, so auto-bumping them here causes version skew. The janitor's
    OWN self-update path (`task_version_update`) is separate and unaffected — even
    though the janitor's own id is excluded here.

    Detection: the `@ai-maestro-plugins` marketplace suffix is authoritative; a
    bare/odd id falls back to the marketplace-member name check.
    """
    pid = (plugin_id or "").strip()
    if not pid:
        return False
    name, sep, market = pid.rpartition("@")
    if sep and market == _AI_MAESTRO_MARKETPLACE:
        return True
    candidate = name if sep else pid
    return candidate in ai_maestro_marketplace_members()


# --- terminal / runtime-context detection (TRDD-db169d9e R3/R4) -----------

# Terminal-program signatures, matched against an ANCESTOR process's command.
# Order matters: `tmux` is first so a multiplexer ancestor wins over a GUI
# terminal further up the tree (the reliable send inside tmux is `tmux
# send-keys`). The patterns match either a macOS `.app` bundle path or a bare
# Unix executable at a path/word boundary, so they work on macOS and Linux.
_TERMINAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"tmux:? ?server|(?:^|/)tmux(?:\s|$)"), "tmux"),
    (re.compile(r"iTerm\.app|(?:^|/)iTerm2?(?:\s|$)"), "iterm"),
    (re.compile(r"WezTerm\.app|(?:^|/)wezterm(?:-gui)?(?:\s|$)"), "wezterm"),
    (re.compile(r"(?:^|/)kitty(?:\.app|\s|/|$)"), "kitty"),
    (re.compile(r"Ghostty\.app|(?:^|/)ghostty(?:\s|$)"), "ghostty"),
    (re.compile(r"Alacritty\.app|(?:^|/)alacritty(?:\s|$)"), "alacritty"),
    (re.compile(r"Hyper\.app"), "hyper"),
    (re.compile(r"Warp\.app|WarpTerminal"), "warp"),
    (re.compile(r"Code Helper|Visual Studio Code\.app|(?:^|/)code(?:\s|$)"), "vscode"),
    (re.compile(r"Terminal\.app/Contents/MacOS/Terminal"), "apple-terminal"),
)


def _terminal_from_command(cmd: str) -> Optional[str]:
    """Return the terminal kind a process command belongs to, or None. Pure."""
    for pat, kind in _TERMINAL_PATTERNS:
        if pat.search(cmd):
            return kind
    return None


def parse_ps_table(text: str) -> dict[int, tuple[int, str]]:
    """Parse `ps -axo pid=,ppid=,command=` output into `{pid: (ppid, command)}`.

    Tolerates leading whitespace and a header line; skips malformed rows. The
    command (3rd field) keeps its embedded spaces (split with maxsplit=2).
    """
    table: dict[int, tuple[int, str]] = {}
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2])
    return table


def process_ancestry(start_pid: int, table: dict[int, tuple[int, str]]) -> list[str]:
    """Commands of `start_pid`'s ancestors, NEAREST first (excludes itself).

    Walks parent PIDs through `table` (from `parse_ps_table`). Stops at pid <= 1
    (kernel / launchd / init), a cycle, a missing parent, or a 64-deep cap — so
    a corrupted snapshot can never loop forever.
    """
    out: list[str] = []
    seen = {start_pid}
    cur = start_pid
    for _ in range(64):
        entry = table.get(cur)
        if entry is None:
            break
        ppid = entry[0]
        if ppid <= 1 or ppid in seen:
            break
        parent = table.get(ppid)
        if parent is None:
            break
        out.append(parent[1])
        seen.add(ppid)
        cur = ppid
    return out


def terminal_kind(*, ps_text: Optional[str] = None, pid: Optional[int] = None) -> str:
    """Identify the terminal program hosting this process by walking the PROCESS
    ANCESTRY to the launching terminal — NOT by inferring from `$TERM_PROGRAM` &
    friends (those env vars are inherited into subshells, go stale, or are
    missing, so they lie about the real host).

    Walks parent PIDs from this process up toward the session's terminal emulator
    (or multiplexer) and matches each ancestor's command against
    `_TERMINAL_PATTERNS`. Returns one of `iterm`, `apple-terminal`, `tmux`,
    `kitty`, `wezterm`, `vscode`, `ghostty`, `alacritty`, `hyper`, `warp`, or
    `unknown`. The NEAREST matching ancestor wins, so a tmux pane (whose shell's
    parent is the tmux server) resolves to `tmux` even when a GUI terminal sits
    further up the tree.

    `ps_text` / `pid` are injectable for tests (a synthetic
    `pid ppid command`-per-line snapshot and a starting pid).

    Override: `JANITOR_FORCE_TERMINAL_KIND` (e.g. `tmux`, `iterm`) short-circuits
    the ancestry walk — a manual escape hatch if detection ever misfires, and the
    deterministic hook tests use to pin a kind regardless of the host terminal.
    """
    forced = os.environ.get("JANITOR_FORCE_TERMINAL_KIND", "").strip().lower()
    if forced:
        return forced
    if ps_text is None:
        proc = run_subprocess(
            ["ps", "-axo", "pid=,ppid=,command="],
            timeout=5.0,
            capture=True,
            detector_name="terminal_kind",
        )
        ps_text = proc.stdout if proc and proc.stdout else ""
    table = parse_ps_table(ps_text)
    start = os.getpid() if pid is None else pid
    for cmd in process_ancestry(start, table):
        kind = _terminal_from_command(cmd)
        if kind:
            return kind
    return "unknown"


# Env signals that a process is running INSIDE an ai-maestro agent. The explicit
# boolean flags are the PREFERRED, stable contract — ai-maestro sets one on the
# `claude` launch command (or `tmux new-session -e …`) so every descendant
# (the janitor's detector subprocesses, a daemon spawned from a heartbeat)
# inherits it. `AMP_AGENT_ID` / `AID_AUTH` are ai-maestro internals honoured as a
# fallback so detection still works if the explicit flag is ever absent.
_AI_MAESTRO_AGENT_FLAGS = ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO")
_AI_MAESTRO_AGENT_INTERNALS = ("AMP_AGENT_ID", "AID_AUTH")


def in_ai_maestro_agent_env(env: Optional[Mapping[str, str]] = None) -> bool:
    """Cheap pre-check: are we running INSIDE an ai-maestro agent?

    True iff an explicit ai-maestro flag is truthy (`AIMAESTRO_AGENT=1` /
    `THIS_IS_AIMAESTRO=true`) OR an ai-maestro internal id is present
    (`AMP_AGENT_ID` / `AID_AUTH`). This is the FAST signal (TRDD-db169d9e R4);
    the AUTHORITATIVE resolver is a CWD match against the agent list from the
    ai-maestro CLI (`aimaestro-agent.sh list --json`, which also yields the tmux
    session to send to — issue #42, decoupled from the server API), done by the
    trigger scripts when this pre-check passes. Pass `env` to test.
    """
    e = os.environ if env is None else env
    for name in _AI_MAESTRO_AGENT_FLAGS:
        if (e.get(name) or "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return any((e.get(name) or "").strip() for name in _AI_MAESTRO_AGENT_INTERNALS)


def file_mtime(path: Path | str) -> int:
    """Return file mtime in epoch seconds, or 0 on error.

    Cross-platform replacement for the `stat -c %Y` / `stat -f %m`
    dance the bash port had to do.
    """
    try:
        return int(Path(path).stat().st_mtime)
    except (FileNotFoundError, OSError):
        return 0


def log_line(name: str, message: str) -> None:
    """Append one log line with a local-time timestamp + GMT offset.

    Format mirrors the bash port:
        [YYYY-MM-DDTHH:MM:SS±HHMM] [s:<8-char-prefix>] <message>

    The `[s:<prefix>]` block is included only when CLAUDE_CODE_SESSION_ID
    is set (Claude Code 2.1.132+). Without it, the format degrades
    gracefully to the original `[ts] <message>` shape.
    """
    init_state()
    # Local time + GMT offset — never UTC, per the project rule.
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        line = f"[{ts}] [s:{sid[:8]}] {message}\n"
    else:
        line = f"[{ts}] {message}\n"
    log_path = log_dir() / f"{name}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def rotate_log_if_big(name: str, max_bytes: int = 1_048_576) -> None:
    """Rotate <name>.log to <name>.log.1 when it exceeds `max_bytes`.

    Only one rotation level — we don't keep .log.2 / .log.3. The
    log-retention prologue in dispatch.py prunes both .log and .log.1
    after `log_retention_days`.
    """
    log_path = log_dir() / f"{name}.log"
    try:
        if log_path.stat().st_size > max_bytes:
            backup = log_path.with_name(log_path.name + ".1")
            os.replace(log_path, backup)
    except (FileNotFoundError, OSError):
        return


def run_subprocess(
    cmd: list[str],
    *,
    timeout: float = 10.0,
    cwd: Path | str | None = None,
    capture: bool = True,
    detector_name: Optional[str] = None,
) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a subprocess with a default timeout, never propagate exceptions.

    Returns the CompletedProcess on success, None on:
      * `subprocess.TimeoutExpired` — the command ran past `timeout` seconds.
        A network-stuck `gh` call is the canonical case; without a timeout
        the heartbeat would block forever.
      * `FileNotFoundError` — the binary isn't on PATH (e.g. `gh` not
        installed on a CI runner). doctor.py surfaces this upstream as
        WARN/FAIL; detectors can short-circuit on None and continue.
      * `OSError` — any other OS-level failure (permission, ENOMEM, etc.).

    Why None and not raise: detectors run in the cron-fire hot path and
    a single hung subprocess would park the whole heartbeat for 5 minutes.
    Returning None lets each call site decide whether to log + skip the
    branch or log + abort the detector.

    `detector_name` (optional): if provided, a one-line failure log goes
    to `<detector_name>.log` via `log_line`. Pass the detector's own name
    so post-mortem debugging can correlate the timeout to the right detector.

    Always passes `check=False` and `text=True`; never sets `shell=True`.
    Capture defaults on (`capture_output=True`); pass `capture=False` for
    detectors whose stdout must flow through to the cron prompt
    (dispatch.py's detector-invocation path uses that direct form).
    """
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if detector_name:
            cmd_short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
            log_line(detector_name, f"subprocess timed out after {timeout}s: {cmd_short}")
        return None
    except FileNotFoundError:
        if detector_name:
            log_line(detector_name, f"binary not in PATH: {cmd[0]}")
        return None
    except OSError as exc:
        if detector_name:
            cmd_short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
            log_line(detector_name, f"subprocess OSError ({exc}): {cmd_short}")
        return None


def sanitize_for_drift_line(text: str) -> str:
    """Defang `[` `]` and strip control characters from untrusted text.

    Defends against prompt-mimicry where a user-controlled string
    (stash subject, PR title, server name, env var name) tries to
    impersonate a janitor marker like `[janitor-resume]`. Replacements:

      * 0x00–0x1F (except tab + newline) → stripped
      * 0x7F (DEL) → stripped
      * U+202A–U+202E (Unicode bidi-override LRE/RLE/PDF/LRO/RLO) → stripped
      * U+2066–U+2069 (LRI/RLI/FSI/PDI isolate controls) → stripped
      * `[` → `⟦` (U+27E6 MATHEMATICAL LEFT WHITE SQUARE BRACKET)
      * `]` → `⟧` (U+27E7 MATHEMATICAL RIGHT WHITE SQUARE BRACKET)

    Bidi-override and isolate controls let attacker-controlled text
    visually reorder a downstream rendering — a PR title or stash subject
    that embeds them could disguise its real content from a human
    skimming the heartbeat output. Stripping them is safe: drift lines
    are short, single-direction prose; nobody's PR title legitimately
    needs to flip script direction.

    The Unicode lookalikes still read as brackets but are visually
    distinct from anything we emit ourselves (our markers always use
    ASCII `[]`).
    """
    def _keep(c: str) -> bool:
        if c in ("\t", "\n"):
            return True
        cp = ord(c)
        if cp < 0x20:
            return False
        if cp == 0x7F:                  # DEL
            return False
        if 0x202A <= cp <= 0x202E:      # bidi-override LRE/RLE/PDF/LRO/RLO
            return False
        if 0x2066 <= cp <= 0x2069:      # LRI/RLI/FSI/PDI
            return False
        return True

    cleaned = "".join(c for c in text if _keep(c))
    cleaned = cleaned.replace("[", "⟦").replace("]", "⟧")
    return cleaned
