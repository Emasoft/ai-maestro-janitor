# Shared state helpers for ai-maestro-janitor hooks and detectors —
# Python port of scripts/lib/state.sh. Keep the surface AS CLOSE to the
# bash original as possible so a detector can call the same names.
#
# Imported (not invoked as a script) so no PEP 723 metadata block here.
# Stdlib-only — pathlib + os + subprocess + datetime are all that's used.

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

# --- per-project state filenames (cross-module contract) -------------------

# The POSITIVE opt-out. Written by /janitor-disarm, removed by /janitor-arm, and
# read by fleet_scan.diagnose_root (-> session_liveness `unarmed`, sacrosanct) and
# by the SessionStart arm nudge. It is a contract spanning Python AND two shipped
# SKILL.md files, so the name lives here rather than as a literal at each site — it
# once had four readers and no writer at all, and every one of those readers spelled
# it independently (TRDD-EFTQB9RR).
DISARMED_FLAG = "disarmed.flag"

# The RETIRED per-project control sentinels. NOTHING READS THESE — pause, maintenance
# mode and the self-budget throttle are all gone (owner directive 2026-07-31: arm/disarm
# is the only switch). The names survive as the SINGLE source of truth for the two sweeps
# that delete them — dispatch on every fire, arm_prepare on every arm — because real hosts
# carry these files right now and the levers that lifted them went away with the switches.
# Without the sweep an upgraded machine keeps looking quiesced forever, with nothing left
# to un-quiesce it. Retire the names themselves only once no supported version can write
# one. See [[janitor-has-no-off-switch-but-disarm]].
RETIRED_SENTINELS = (
    "paused",
    "maintenance-mode",
    "self-budget-maintenance.flag",
    # The github-issues-watch opt-in, retired by the 2026-08-02 always-on directive. Swept
    # for the same reason as the others: an inert flag on disk makes a healthy host look
    # configured, and the next reader has to prove it means nothing.
    "issues-watch.flag",
    # The `/janitor-keep-going off` sentinel (owner directive 2026-07-31, same ruling that
    # retired the three above). Nothing has read this file since the off-switch it backed was
    # removed — `_phase_keep_going_nudge` is unconditional now — but it was never added HERE,
    # so neither this sweep nor arm_prepare's ever swept it. Measured live (janitor#185): a
    # host carried `keep-going-off` dated 13+ days with every heartbeat firing correctly the
    # whole time — the exact "inert litter looks like live config" trap the comment above
    # names for the other three.
    "keep-going-off",
)

# Written by the StopFailure hook on any turn-ending API error, cleared by
# dispatch.py on the next fire. Read by fleet_scan to diagnose `frozen`.
RATE_LIMITED_FLAG = "rate-limited.flag"

# The rate-limit window START stamp, written by the StopFailure hook alongside
# RATE_LIMITED_FLAG. Used by the daemon's resume-wake dedupe as the per-window key
# (a NEW limit writes a NEW value → a new window → a legitimately-repeated resume is
# not swallowed) — TRDD-X07E7HTN, D1 v1.
RATE_LIMITED_SINCE_FILE = "rate-limited-since.ts"

# Daemon-owned rate-limit RESUME wake (TRDD-X07E7HTN, D1 v1). The name lives HERE
# (SSOT) because it is a CONTRACT spanning two processes: the DAEMON (writer,
# daemon._resume_wake_pass) stamps DAEMON_WAKE_COVERED_FILE = now each beat it is
# covering an injectable, rate-limited pane's resume; dispatch (reader,
# _daemon_wake_covered_fresh) reads it as the MF4 handshake proof that the pane's
# resume is daemon-covered, so the rate-limit window may demote off the FAST cron.
# ABSENT/STALE ⇒ un-injectable / never-scanned / #J / feature-off ⇒ the cron stays the
# trigger (the safe default). DAEMON_RESUME_WAKE_FILE is the daemon's own once-per-window
# inject dedupe (never read by dispatch).
DAEMON_WAKE_COVERED_FILE = "daemon-wake-covered.ts"
DAEMON_RESUME_WAKE_FILE = "daemon-resume-wake.ts"

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
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            env=git_env,
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
    """Create state/ and logs/ directories if missing. Idempotent.

    log_dir() is created FIRST because it is what log_line() actually writes to, and the
    global daemon overrides it to the writable global-state dir via JANITOR_LOG_DIR.

    state_dir() is then best-effort. The OS-keepalive daemon (TRDD-71ABD7V7) runs under
    launchd with NO CLAUDE_PROJECT_DIR and cwd="/", so project_root() resolves to "/" and
    state_dir() becomes "/.janitor/state" — an unwritable read-only-root path whose mkdir
    raised OSError(Errno 30) and CRASH-LOOPED the keepalive daemon on every boot
    (2026-07-09: `state.log_line` -> `init_state` -> `state_dir().mkdir` -> read-only "/").
    The daemon logs via JANITOR_LOG_DIR and never uses state_dir, so a missing project
    state dir must not crash it. Per-session detectors always have a writable project (their
    log_dir is under it and is created just above), so this tolerance never masks a real
    error for them.
    """
    log_dir().mkdir(parents=True, exist_ok=True)
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def atomic_write(target: Path | str, value: str) -> None:
    """Atomic-by-rename write: write to tmp, then os.replace into place.

    `os.replace` is atomic on POSIX and Windows (per Python docs), so a
    concurrent reader sees either the old content or the new — never a
    half-written file.

    `target` is `Path | str` because the body has ALWAYS normalized with
    `Path(target)` and many callers legitimately pass an `os.path.join(...)`
    str. The annotation previously said `Path` alone, which was simply untrue
    of the contract the body implements — and the project's mypy gate could not
    catch the mismatch, because `mypy_path = "scripts"` leaves a bare
    `import state` from a `scripts/lib/` sibling unresolved and
    `ignore_missing_imports` degrades it to `Any` (pyright resolves it and did
    flag it). Widening to match reality is the honest fix; narrowing the callers
    to satisfy a wrong annotation would have been churn. See TRDD-BMDZK4RA.
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


# Per-pane presence works on any terminal that exports a STABLE per-pane id in the env — the ONE
# thing the WRITER (the UserPromptSubmit hook) and the READER (the self-trigger gate) can both
# resolve from the same session env. Ordered by reliability: a multiplexer pane id (tmux) is
# focus-independent and beats a GUI-window id, so it is tried first; then the GUI terminals that
# expose a per-pane/window id. A terminal NOT in this table (Apple Terminal, plain xterm, …) has no
# per-pane addressing → the gate falls back to the machine-global breadcrumb. Each source is a
# distinct NAMESPACE so two terminals' ids can never collide into one presence file.
_PANE_ID_ENV_VARS: tuple[tuple[str, str], ...] = (
    ("tmux", "TMUX_PANE"),          # e.g. %3 — the multiplexer pane, focus-independent
    ("iterm", "ITERM_SESSION_ID"),  # e.g. w0t1p0:UUID — macOS iTerm2
    ("kitty", "KITTY_WINDOW_ID"),   # e.g. 3 — kitty's per-OS-window id
    ("wezterm", "WEZTERM_PANE"),    # e.g. 0 — WezTerm's per-pane id
)


def terminal_pane_key(env: Mapping[str, str] | None = None) -> str | None:
    """A stable, filesystem-safe id for THIS terminal pane, or None if unresolvable.

    Presence is PER-PANE (user directive 2026-07-16): a human typing in pane A must not mark an
    unattended pane B as "present" and block B's self-trigger. The key is `"<source>-<sanitized id>"`
    resolved from the first matching env var in `_PANE_ID_ENV_VARS` — tmux first (focus-independent),
    then the GUI terminals that expose a per-pane id (iTerm, kitty, WezTerm). The `<source>` prefix
    namespaces the key so, e.g., tmux `%3` and kitty window `3` never map to the same file. Any run of
    chars outside `[A-Za-z0-9._]` collapses to a single `-`, trimmed at the ends, so the value is a
    safe filename on every platform. Returns None on a terminal that exports NO per-pane id (Apple
    Terminal, plain xterm) — the caller then falls back to the machine-global breadcrumb.
    """
    e: Mapping[str, str] = os.environ if env is None else env
    for source, var in _PANE_ID_ENV_VARS:
        raw = (e.get(var) or "").strip()
        if not raw:
            continue
        sanitized = re.sub(r"[^A-Za-z0-9._]+", "-", raw).strip("-")[:128]
        if sanitized:
            return f"{source}-{sanitized}"
    return None


def per_pane_presence_path(pane_key: str, home: Path | None = None) -> Path:
    """Path of THIS pane's presence breadcrumb (sibling of the machine-global one).

    Lives under `~/.aimaestro/state/user-presence-panes/<pane_key>.json`. Absence means the
    user has never typed in this pane → unattended here (the reader treats it as "away").
    """
    base = Path(home) if home is not None else Path.home()
    return base / ".aimaestro" / "state" / "user-presence-panes" / f"{pane_key}.json"


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


def bump_user_presence(
    home: Path | None = None, now: int | None = None, env: Mapping[str, str] | None = None
) -> None:
    """Record a GENUINE user-input event — stamp BOTH epochs to `now`.

    Called by the UserPromptSubmit hook ONLY for real user prompts (cron
    `[janitor-…]` prompts must be filtered out by the caller first). Best-effort:
    any filesystem error is swallowed so the user's turn is never aborted.

    Writes TWO breadcrumbs: the machine-global one (kept for cross-plugin consumers that
    read `~/.aimaestro/state/user-presence.json`) AND a PER-PANE one keyed by this pane's
    id (user directive 2026-07-16) so the self-trigger gate can tell "the user is active in
    THIS pane" from "a human typed in some OTHER pane on the machine".
    """
    ts = int(time.time()) if now is None else int(now)
    try:
        _write_user_presence(user_presence_path(home), ts, ts)
    except OSError:
        # Never crash the session on a breadcrumb write failure.
        pass
    pane_key = terminal_pane_key(env)
    if pane_key is not None:
        try:
            _write_user_presence(per_pane_presence_path(pane_key, home), ts, ts)
        except OSError:
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


# The compaction high-water stamp, written by the PostCompact hook via
# `cold_cache_compact.mark_compacted`. It lives HERE rather than beside its writer because both
# that module AND `pre-tool-context-usage.py` need the name, and the hook runs before EVERY tool
# call — importing `cold_cache_compact` there just to reach a filename would put its whole import
# closure on that hot path. One constant, one home, no hot-path cost (TRDD-G043V3V0).
LAST_COMPACT_STAMP = "last-compact.ts"


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


def rollback_marker_ack(filename: str, *, actor: str, why: str) -> bool:
    """Undo a once-per-generation marker ack so the NEXT heartbeat re-emits it (janitor#257).

    A `[janitor-*]` marker whose ack advances at EMISSION time is consumed even when the receiver
    declines — dispatch cannot know whether the action it asked for actually happened, so the
    stamp says "handled" the moment the marker is printed. Rolling the stamp back restores the
    signal; without it a declined reload never happens, never retries, and the session keeps
    running stale code with nothing left to say so.

    Rolls back to 0, not to the previous generation: 0 means "no generation acked", so ANY current
    generation compares as newer and re-emits. A stored previous generation would work only until
    the daemon bumped it, and would then be indistinguishable from a real ack.

    An ABSENT stamp is left absent — creating one would invent an ack that never happened, which
    is this same bug inverted. Returns True iff a stamp existed and was rolled back; never raises,
    because bookkeeping must not break the decline it is recording.
    """

    def _note(message: str) -> None:
        # The LOG is bookkeeping about bookkeeping: on an unwritable .janitor tree it must not be
        # the thing that turns a clean refusal into a traceback for the user.
        try:
            log_line(actor, message)
        except OSError:
            pass

    try:
        path = state_dir() / filename
        if not path.is_file():
            return False
        atomic_write(path, "0")
    except OSError as exc:
        _note(f"could not roll back {filename}: {exc}")
        return False
    _note(f"rolled {filename} back so the next heartbeat re-emits — {why}")
    return True


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


def parse_nonneg_int(s: str) -> Optional[int]:
    """Parse a non-negative integer from a config-value string, or None.

    Accepts the SAME spellings Claude Code's own integer env vars accept as of CC
    2.1.208/2.1.211 (which fixed `1e6` silently becoming `1`, then added digit
    separators) — so a janitor knob and a CC knob read the same string identically:

      * plain digits           — "270000"
      * digit-separator "_"    — "64_000", "270_000"  (Python int-literal underscores)
      * scientific notation    — "1e6", "2.7e5"       (must resolve to a WHOLE number)

    Returns None for anything else — a fractional value ("1.5"), a negative
    ("-1e6"), hex ("0x10"), NaN/inf, or junk — so the caller falls back to its
    default rather than silently using a wrong number. PURE."""
    # Plain / underscore-separated integer (base 10 — never hex/octal for a knob).
    try:
        n = int(s, 10)
    except ValueError:
        # Scientific / float spelling; must be a finite, non-negative WHOLE number,
        # matching CC's "integer env var" contract (2.7e5 == 270000, but 1.5 is not).
        try:
            f = float(s)
        except ValueError:
            return None
        if not math.isfinite(f) or not f.is_integer():
            return None
        n = int(f)
    return n if n >= 0 else None


def coerce_int(
    value: Optional[str],
    default: int = 0,
    *,
    detector_name: Optional[str] = None,
    var_name: Optional[str] = None,
) -> int:
    """Coerce a (possibly user-supplied) value to a non-negative int.

    Accepts None, empty string, and non-numeric text — all return `default`. Used
    for `CLAUDE_PLUGIN_OPTION_*` env vars where a typo like "900 seconds" should not
    crash the heartbeat. Numeric spellings match Claude Code's own int env vars
    (plain, `64_000`, `1e6` — see `parse_nonneg_int`), so a knob set the way CC
    documents is honored rather than silently reverting to the default.

    If `detector_name` is provided AND a non-empty value failed to coerce, log a
    one-line note so the user can see in the detector log that their config knob is
    being ignored. The log fires only on the "had a value but it wasn't a
    non-negative integer" case — empty/unset values (the common path) stay silent.
    `var_name` lets the log point at the offending env var.
    """
    if value is None:
        return default
    s = value.strip()
    if not s:
        return default
    parsed = parse_nonneg_int(s)
    if parsed is None:
        if detector_name:
            label = var_name or "config value"
            log_line(
                detector_name,
                f"coerce_int: {label}={s!r} is not a non-negative integer — using default {default}",
            )
        return default
    return parsed


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
    # S4 (TRDD-7IUTRX29): rotation is STRUCTURAL, not conventional. 10 of the 40
    # log_line writers (hooks especially — stop-failure.log had grown unbounded)
    # never called rotate_log_if_big; folding the amortised check into the append
    # itself bounds every present AND future writer by construction. One stat()
    # per line, a rename only past the cap — the explicit end-of-run rotate calls
    # remain harmless (idempotent under the cap).
    rotate_log_if_big(name)
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


def detached_uv_env() -> dict[str, str]:
    """Environment for a DETACHED child that re-invokes a `uv run --script` shebang.

    Strips `VIRTUAL_ENV`: uv exports it into every `uv run` child, pointing at the
    PARENT script's environment — which can be an EPHEMERAL `builds-v0` temp env that
    uv deletes when the parent exits. A detached worker that starts after that deletion
    finds a dangling "active virtual environment" and uv refuses to run AT ALL
    ("Failed to inspect Python interpreter from active virtual environment"), so the
    worker dies before its first line. The worker must let ITS OWN uv resolve a fresh
    script env instead of inheriting the parent's. Root-caused 2026-07-17: this WAS the
    marketplace-refresh empty-worker-log flake (TRDD-UO93APWN) — worse under suite load
    because load widens the window between parent-uv exit and worker-uv start.
    """
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    return env


def timeout_scale() -> float:
    """Multiplier applied to every `run_subprocess` timeout. **1.0 in production.**

    PUBLIC (was `_timeout_scale`) because `run_subprocess` is not the only place that needs it:
    helpers with their OWN short timeouts outside this seam — `agentlens_probe.probe_json` at
    5.0 s is a measured one — must scale by the SAME number. A second private copy of this env
    read in each of them is exactly the drift that gave TRDD-K3PN7QW2 five spellings of one rule.

    TRDD-7NSRD8OV. Detectors pass deliberately short timeouts (`git rev-parse --git-dir`,
    `timeout=5`) and `run_subprocess` fails OPEN on expiry — returning None so a hung child
    can never park the 5-minute heartbeat. That is correct in production and pathological
    under the TEST SUITE's own load: at loadavg 80+ a `git rev-parse` exceeds 5s, the caller's
    `if x is None: return 0` fires, and the detector exits 0 with EMPTY stdout. The test then
    fails asserting on `''`, with nothing anywhere naming a timeout — so it reads as a logic
    bug in code that is fine. Measured across 5 tests in 4 files; which one fails is decided
    by scheduling, because 52 call sites share this seam.

    Scaling HERE rather than per test because no per-test fix can converge on 52 call sites,
    and raising the production timeouts is forbidden — a real guarantee must not be traded for
    a green suite. Read per-call, not at import, so a test can set it after this module loads.

    Anything unparseable or non-positive falls back to 1.0: a malformed knob must never
    silently shorten a production timeout.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_SUBPROCESS_TIMEOUT_SCALE")
    if not raw:
        return 1.0
    try:
        scale = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return scale if scale > 0 else 1.0


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

    Every child inherits `GIT_OPTIONAL_LOCKS=0` (janitor#245): a read-only
    `git status`/`git diff` still WRITES `.git/index.lock` for its optional
    stat-cache write-back, and the ~5-minute heartbeat overlapping a
    minutes-long `publish.py` commit made that lock collision SCHEDULED,
    not unlucky — it killed real publishes with "Unable to create
    .git/index.lock". `git status` itself fails soft on the collision
    (rc=0, no visible symptom), so the janitor never noticed. This env var
    is git's own documented escape hatch and is inert for non-git children.
    """
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture,
            text=True,
            check=False,
            timeout=timeout * timeout_scale(),
            env=env,
        )
    except subprocess.TimeoutExpired:
        _log_fail_open(detector_name, f"subprocess timed out after {timeout}s", cmd)
        return None
    except FileNotFoundError:
        _log_fail_open(detector_name, "binary not in PATH", cmd)
        return None
    except OSError as exc:
        _log_fail_open(detector_name, f"subprocess OSError ({exc})", cmd)
        return None


def _log_fail_open(detector_name: Optional[str], reason: str, cmd: list[str]) -> None:
    """Record WHY `run_subprocess` returned None. UNCONDITIONAL, and never raises.

    The log used to be gated on the optional `detector_name`, so every caller that omitted it
    failed open in total silence. That silence is the single most expensive property this
    module has had: a caller's `if x is None: return 0` then exits 0 with EMPTY stdout, and the
    test asserting on that output fails with nothing anywhere naming a timeout — so it reads as
    a logic bug in code that is correct. TRDD-7NSRD8OV was misdiagnosed four times against
    exactly that shape, each time by GUESSING at a mechanism no artifact recorded.

    Callers without a name land in a shared `subprocess.log` rather than nowhere. That is worth
    a new file: an unattributed breadcrumb still carries the timestamp, the reason and the argv,
    which is everything the diagnosis needs.

    The `except OSError` is deliberate and narrow, against this repo's fail-fast default:
    `run_subprocess`'s documented contract is that it NEVER propagates, and a read-only
    diagnostic must not be the thing that breaks it on a host whose log dir is unwritable.
    """
    cmd_short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
    try:
        log_line(detector_name or "subprocess", f"{reason}: {cmd_short}")
    except OSError:
        return


_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def sanitize_for_drift_line(text: str) -> str:
    """Defang `[` `]`, strip control characters, and REDACT emails from untrusted text.

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
    # Redact email addresses (owner incident 2026-08-02). The GitHub watchers forward issue
    # titles and comment bodies into the model's context, and an address that arrives there is
    # an address an agent can re-paste into an outbound post — which is exactly how three of
    # the owner's private account identities reached two PUBLIC issues. It is also how a
    # STRANGER gets paged without anyone deciding to: GitHub renders the `@gmail` inside
    # `user@gmail.com` as a mention of the real account `@gmail`.
    #
    # Redacting at the point untrusted text ENTERS context is the cheap fix; the outbound
    # `pre-bash-safety` guard is the backstop for text that arrived some other way. Neither
    # alone is sufficient — this one cannot see a hand-typed address, and that one cannot
    # unsee what is already in the transcript.
    #
    # The local part is kept truncated so a drift line stays diagnostic ("which account?")
    # without carrying the identity.
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)[:2]}…@⟨redacted⟩", cleaned)
