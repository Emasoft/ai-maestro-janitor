"""Shared janitor self-update helpers — used by the daemon's
`task_version_update` (the auto-update branch) and the per-session
`version-update` detector (the read-only detection branch).

Per TRDD-be2efa56 §9 follow-up: the auto-update branch moved into the
daemon so every Claude Code session that arms the janitor benefits from
a single global writer. The detector keeps emitting drift lines only —
no `claude plugin update` calls. This module factors the helpers both
surfaces need so we don't duplicate semver / scope-discovery logic.

Functions:
  - `_semver_tuple(s)` — string → (int, …) for ordering
  - `detect_install_scopes()` — every settings file mentioning the
    janitor's PLUGIN_NAME, in user → local → project order
  - `list_installed_versions(parent)` — semver-shaped subdir names
    of the cache parent, sorted ascending
  - `resolve_latest_published(plugin_root)` — GitHub releases/latest
    tag for the repo declared in the plugin's manifest
  - `attempt_auto_update(log_writer)` — best-effort `claude plugin
    marketplace update` + per-scope `claude plugin update`; True iff
    at least one scope finished successfully. Designed so both the
    daemon (logs into ~/.claude/janitor-global-state/daemon.log) and
    the detector (logs into <project>/.janitor/logs/version-update.log)
    can supply their own write-line callable.
  - `do_auto_update_if_needed(plugin_root, log_writer)` — the wrapper
    the daemon task calls: reads cache state, compares to GitHub
    latest, runs `attempt_auto_update` when behind. Returns
    (updated_bool, new_latest_installed_or_empty).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import janitor_integrity  # crash-safe DATA-dir read/write (backup_and_write / read_or_restore)
import janitor_self_integrity  # the DATA-dir HMAC key (load_or_create_key)

PLUGIN_NAME = "ai-maestro-janitor"
MARKETPLACE_NAME = "ai-maestro-plugins"

# C3 (TRDD-T198DT1W) — the janitor's FIXED persistent DATA dir, hard-coded the
# SAME way launchd_keepalive._DATA_DIR and the arm skill resolve it. It is
# resolved by this explicit path, NOT via ${CLAUDE_PLUGIN_DATA} — that env var
# points at whichever plugin owns the running turn (wrong in the detached,
# session-less daemon that writes the pin). Overridable via JANITOR_DATA_DIR for
# tests so no test touches the real ~/.claude tree.
_FIXED_DATA_DIR = (
    Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
)
# Sub-namespace under DATA for the C3 trust-anchor files (outside the cache).
_INTEGRITY_SUBDIR = "integrity"
_LAST_GOOD_NAME = "last-good.json"
_QUARANTINE_NAME = "quarantine.json"
# The version's shipped manifest, relative to its cache dir (the C2 shape).
_MANIFEST_REL = Path(".integrity") / "manifest-sha256.json"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_GH_REPO_RE = re.compile(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$")


def _semver_tuple(s: str) -> tuple[int, ...]:
    """Convert '0.4.0' to (0, 4, 0) for ordering. Returns (-1,) on bad input."""
    if not _SEMVER_RE.match(s):
        return (-1,)
    return tuple(int(p) for p in s.split("."))


def parse_semver(s: str) -> tuple[int, ...]:
    """Public semver-ordering helper: '0.31.0' → (0, 31, 0), or (-1,) on
    non-semver input (which sorts lowest). A thin public alias of the
    module-internal ``_semver_tuple`` so other lib modules (e.g. the
    daemon-recency gate in global_state) reuse ONE semver parser instead of
    hand-rolling their own — keeping a single source of truth for version
    ordering across the janitor."""
    return _semver_tuple(s)


def should_request_prompt_update(
    installed: str, published: str, auto: bool, trigger_enabled: bool,
) -> bool:
    """True iff the version-update detector should RAISE the release-triggered self-update
    request (TRDD-Y9KM5RCJ): auto-update (`auto`) AND the release-trigger opt-in
    (`trigger_enabled`) are BOTH on, AND the plugin cache (`installed`) is strictly behind
    the latest published release (`published`). Pure — no I/O; the detector's single
    testable decision point. When False the detector either shows the manual nudge (auto
    off) or stays silent (already current, or the trigger opt-in is off)."""
    if not (auto and trigger_enabled):
        return False
    if not (installed and published):
        return False
    return _semver_tuple(installed) < _semver_tuple(published)


def registry_path() -> Path:
    """Claude Code's authoritative plugin-install registry."""
    return Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def registry_install_records() -> list[dict]:
    """Every install record the CLI itself obeys, or [] when unreadable.

    `~/.claude/plugins/installed_plugins.json` maps `<name>@<marketplace>` to a
    LIST of `{scope, version, projectPath, installPath}`. This is what
    `claude plugin update --scope X` consults, so it is the only source that can
    answer "where is this plugin actually installed".

    Fail-open to []: the caller then falls back to the settings heuristic, which
    is weaker but not worse than refusing to run at all.
    """
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    recs = plugins.get(f"{PLUGIN_NAME}@{MARKETPLACE_NAME}") if isinstance(plugins, dict) else None
    return [r for r in recs if isinstance(r, dict)] if isinstance(recs, list) else []


def detect_install_scopes() -> list[str]:
    """Return every scope where the plugin is actually INSTALLED.

    Reads the registry first, because that is what the CLI obeys. The old
    settings-only heuristic reported `user` on a host whose four installs were
    all `local`, so every self-update ran `--scope user` and died with
    "not installed at scope user" — silently, for six releases (janitor#147).

    Two things made that inevitable and both are fixed by asking the registry:
      * `enabledPlugins` records ENABLEMENT, not installation. They are
        independent, and a bare substring match over the whole settings file
        would equally match a `false` entry or a hook path that names the plugin.
      * local/project scopes were only discoverable under `CLAUDE_PROJECT_DIR`,
        which the DAEMON — the single writer that owns self-update — never has.
        The one path responsible for updating could not see where the plugin
        lived.

    Order is broadest-first (user → local → project) and deduped, so a plugin
    installed in several scopes is updated in each exactly once.
    """
    records = registry_install_records()
    if records:
        seen: set[str] = {
            s for s in (r.get("scope") for r in records) if isinstance(s, str) and s
        }
        # Annotated: inferred from the literal tuple this becomes
        # list[Literal["user","local","project"]], and the unknown-scope append
        # below is a plain str — which mypy rejects only in an environment
        # without this project's venv (i.e. CI's, and CPV's preflight).
        ordered: list[str] = [s for s in ("user", "local", "project") if s in seen]
        # An unknown scope name is still a real install; keep it rather than
        # silently dropping an install we would then never update.
        ordered += sorted(s for s in seen if s not in ("user", "local", "project"))
        if ordered:
            return ordered

    # Fallback: the pre-registry heuristic, for a host whose registry is absent
    # or unreadable. Kept deliberately — a weaker answer beats no self-update.
    scopes: list[str] = []

    # User scope.
    f = Path.home() / ".claude" / "settings.json"
    if f.is_file():
        try:
            if PLUGIN_NAME in f.read_text():
                scopes.append("user")
        except OSError:
            pass

    # Local + project scopes (project root from CLAUDE_PROJECT_DIR or git).
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        for scope, rel in [
            ("local", ".claude/settings.local.json"),
            ("project", ".claude/settings.json"),
        ]:
            f = Path(project_dir) / rel
            if f.is_file():
                try:
                    if PLUGIN_NAME in f.read_text():
                        scopes.append(scope)
                except OSError:
                    pass
    return scopes


def list_installed_versions(parent: Path) -> list[str]:
    """Semver-shaped subdir names of `parent`, sorted ascending."""
    if not parent.is_dir():
        return []
    versions = [
        d.name for d in parent.iterdir()
        if d.is_dir() and _SEMVER_RE.match(d.name)
    ]
    return sorted(versions, key=_semver_tuple)


def resolve_latest_published(plugin_root: Path) -> str | None:
    """GitHub releases/latest tag for the repo declared in plugin.json.

    Returns the tag stripped of any leading `v`, or None on any failure
    (no manifest, missing repository URL, `gh` unavailable, network
    error, no published releases yet). Silent by design — the caller
    decides whether to log.
    """
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        with plugin_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    repo_url = str(data.get("repository", "") or "")
    m = _GH_REPO_RE.match(repo_url)
    if not m:
        return None
    slug = m.group(1)

    if shutil.which("gh") is None:
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}/releases/latest", "--jq", ".tag_name"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    tag = (proc.stdout or "").strip()
    if not tag:
        return None
    return tag[1:] if tag.startswith("v") else tag


def attempt_auto_update(log_writer: Callable[[str], None],
                        update_log_path: Path | None = None) -> bool:
    """Refresh marketplace + run `claude plugin update` per scope.

    `log_writer(msg)` is the caller's log sink (daemon → daemon.log,
    detector → version-update.log). `update_log_path` is where the
    `claude` subprocess's stdout/stderr is appended; when None, output
    is discarded. Returns True iff at least one scope completed rc=0;
    silent on transient failures so the next cycle can retry.
    """
    if shutil.which("claude") is None:
        log_writer("auto-update: claude CLI not in PATH — falling back to manual nudge")
        return False

    log_writer(f"auto-update: refreshing marketplace '{MARKETPLACE_NAME}'")
    if update_log_path is not None:
        with update_log_path.open("a", encoding="utf-8") as logf:
            proc = subprocess.run(
                ["claude", "plugin", "marketplace", "update", MARKETPLACE_NAME],
                stdout=logf, stderr=subprocess.STDOUT,
                timeout=30, check=False,
            )
    else:
        proc = subprocess.run(
            ["claude", "plugin", "marketplace", "update", MARKETPLACE_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False,
        )
    if proc.returncode != 0:
        log_writer("auto-update: marketplace refresh failed")
        return False

    scopes = detect_install_scopes()
    log_writer(f"auto-update: detected install scopes={scopes or '[none]'}")

    targets: list[list[str]] = []
    base_cmd = ["claude", "plugin", "update", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"]
    if scopes:
        for scope in scopes:
            targets.append(base_cmd + ["--scope", scope])
    else:
        # NEVER run a scope-less `claude plugin update`. Without --scope the CLI
        # INFERS the scope, which can silently MIGRATE the plugin between scopes
        # (e.g. local→user) — the exact accident the scope invariant forbids. If
        # the install scope can't be detected, SKIP the self-update (leave
        # `targets` empty → the `not any_success` guard below returns False)
        # rather than guess; the user updates manually with the exact --scope.
        log_writer(
            f"auto-update: could not detect any install scope for "
            f"{PLUGIN_NAME}@{MARKETPLACE_NAME} — SKIPPING self-update "
            "(refusing a scope-less `claude plugin update`; update manually "
            "with the exact --scope it was installed at)."
        )

    any_success = False
    for cmd in targets:
        log_writer(f"auto-update: {' '.join(cmd)}")
        try:
            if update_log_path is not None:
                with update_log_path.open("a", encoding="utf-8") as logf:
                    proc = subprocess.run(
                        cmd, stdout=logf, stderr=subprocess.STDOUT,
                        timeout=120, check=False,
                    )
            else:
                proc = subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120, check=False,
                )
        except subprocess.TimeoutExpired:
            log_writer(f"auto-update: plugin update timed out ({' '.join(cmd[-2:])})")
            continue
        if proc.returncode != 0:
            log_writer(
                f"auto-update: plugin update failed (rc={proc.returncode}, "
                f"cmd={' '.join(cmd[-2:])})",
            )
            continue
        any_success = True

    if not any_success:
        return False

    log_writer("auto-update: success")
    return True


def do_auto_update_if_needed(plugin_root: Path,
                             log_writer: Callable[[str], None],
                             update_log_path: Path | None = None,
                             ) -> tuple[bool, str]:
    """Run the cache-vs-GitHub check + auto-update in one go.

    `plugin_root` is the current `<plugin>/<version>/` dir; its parent
    is the cache root we list versions from. Returns
    `(updated_bool, latest_installed_after)` — the latest installed
    version on disk AFTER the attempt, so callers can compare against
    pre-state to decide whether to fire reload signals.

    Designed for the daemon: it's safe to call every cadence, silent
    when nothing's behind, conservative on every failure mode.
    """
    cache_parent = plugin_root.parent
    installed = list_installed_versions(cache_parent)
    latest_installed = installed[-1] if installed else ""

    latest_published = resolve_latest_published(plugin_root) or ""
    if not latest_published or not latest_installed:
        return (False, latest_installed)
    if latest_published == latest_installed:
        return (False, latest_installed)
    if _semver_tuple(latest_installed) >= _semver_tuple(latest_published):
        # Cache is at or ahead of GitHub — pre-release / dev cache. Silent.
        return (False, latest_installed)

    if not attempt_auto_update(log_writer, update_log_path):
        return (False, latest_installed)

    # Re-list to confirm the cache actually advanced; if not, treat as
    # failure (the `claude` CLI may have reported success without
    # downloading the new dir).
    refreshed = list_installed_versions(cache_parent)
    new_latest = refreshed[-1] if refreshed else latest_installed
    if new_latest == latest_installed:
        log_writer(
            "auto-update reported success but cache version did not advance — "
            "treating as failure",
        )
        return (False, latest_installed)
    return (True, new_latest)


# ---------------------------------------------------------------------------
# C3 (TRDD-T198DT1W) — pin last-GOOD version + quarantine bad version.
#
# The trust anchor the stub (C2) cross-checks lives HERE, in the persistent
# DATA dir OUTSIDE the version-stamped cache. A malicious cache push can
# rewrite a version's plaintext manifest, but it cannot forge the HMAC of that
# manifest keyed by the DATA-dir `.integrity-key` (it lacks the key) — so the
# pin lets the stub distinguish "this version's manifest is the one the daemon
# certified" from "someone rewrote both the file AND its manifest entry".
#
# The DAEMON (the single global writer) calls `pin_good_version` after a
# self-update lands; it calls `add_quarantine` to mark a proven-bad version.
# The STUB does NOT import these (importing the cache's own verifier to check
# that same cache is circular trust) — it inlines its own stdlib readers and
# recomputes the HMAC independently. These functions are the canonical
# WRITER + the daemon/test-side reader.
#
# CARDINAL RULE — FAIL-OPEN: every reader returns "no opinion" (None / empty
# set) on EVERY uncertainty — no key, no manifest, unreadable / malformed
# state — so the stub's C2-only behavior is preserved whenever C3 cannot PROVE
# anything. Only an explicit, completed mismatch ever diverts the boot path.
# ---------------------------------------------------------------------------


def _data_dir() -> Path | None:
    """The FIXED DATA dir (overridable via JANITOR_DATA_DIR for tests), or None
    only if HOME itself is unresolvable (it never is in practice)."""
    override = os.environ.get("JANITOR_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return _FIXED_DATA_DIR


def _integrity_dir() -> Path | None:
    base = _data_dir()
    return None if base is None else base / _INTEGRITY_SUBDIR


def _load_key() -> bytes | None:
    """The DATA-dir HMAC key, minted on first use by janitor_self_integrity.
    Returns None when no DATA dir is resolvable (→ the pin can't be computed,
    so C3 is a no-op and the stub stays C2-only)."""
    return janitor_self_integrity.load_or_create_key(_data_dir())


def manifest_hmac(version_dir: Path, *, key: bytes | None) -> str | None:
    """HMAC-SHA256(manifest BYTES, key), base64 — the C3 trust anchor for one
    cached version, or None when there is no manifest or no key.

    Hashing the raw manifest BYTES (not a re-parse) means the stub can recompute
    this from the exact on-disk file with stdlib only and `hmac.compare_digest`
    the two, with no JSON-canonicalisation ambiguity. A version that shipped no
    manifest (older releases) yields None — it simply isn't pinnable; the stub
    then treats it as the C2 no-manifest fail-open case."""
    if key is None:
        return None
    manifest_path = version_dir / _MANIFEST_REL
    try:
        raw = manifest_path.read_bytes()
    except OSError:
        return None
    return base64.b64encode(hmac.new(key, raw, hashlib.sha256).digest()).decode("ascii")


def read_last_good() -> dict | None:
    """The pinned last-GOOD record ``{"version": str, "manifest_hmac": str}``,
    crash-recovered from its .bak mirror if the primary is torn, or None on any
    uncertainty (no pin yet / unreadable / malformed / missing fields).

    FAIL-OPEN: a None here means the stub has no pin to cross-check and falls
    back to its C2-only (accidental-corruption) gate — never a block."""
    idir = _integrity_dir()
    if idir is None:
        return None
    raw = janitor_integrity.read_or_restore(idir / _LAST_GOOD_NAME)
    if raw is None:
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    version = obj.get("version")
    mac = obj.get("manifest_hmac")
    if not isinstance(version, str) or not version:
        return None
    if not isinstance(mac, str) or not mac:
        return None
    return {"version": version, "manifest_hmac": mac}


def pin_good_version(version_dir: Path, version: str) -> bool:
    """Certify ``version`` as the last-GOOD version: compute its manifest HMAC
    with the DATA-dir key and persist ``{version, manifest_hmac}`` crash-safely.

    Returns False (a NO-OP, never a partial pin) when the version has no
    manifest or no key is available — there is nothing to anchor, so the pin is
    left untouched and the stub stays C2-only for it. The daemon calls this
    after a self-update lands and the new version has run (its manifest is the
    one we certify)."""
    key = _load_key()
    if key is None:
        return False
    mac = manifest_hmac(version_dir, key=key)
    if mac is None:
        return False  # no manifest → not pinnable; never write a keyless/empty pin
    idir = _integrity_dir()
    if idir is None:
        return False
    blob = json.dumps(
        {"version": version, "manifest_hmac": mac}, sort_keys=True
    ).encode("utf-8")
    try:
        janitor_integrity.backup_and_write(idir / _LAST_GOOD_NAME, blob)
    except OSError:
        return False
    return True


def certify_newest_if_clean(cache_parent: Path) -> str | None:
    """Best-effort C3 self-heal on the PERIODIC path (TRDD-ZM5LZ24Y).

    ROOT CAUSE this closes: `pin_good_version`'s only prior caller lived
    inside `daemon.py`'s `if updated:` branch, so the pin advanced ONLY
    when the daemon itself performed a self-update. A version installed
    by any other route — most importantly a human/agent running
    `claude plugin update <plugin>@<marketplace> --scope user` (which this
    project's own CLAUDE.md now instructs on every CI pass) — was NEVER
    certified, so C3 went silently "no opinion" forever. The daemon's
    `task_version_update` MUST call this unconditionally on every fire
    (not just when `updated` is True) so the newest CACHED version gets
    a chance to be certified regardless of who put it there.

    C2 is NOT weakened or bypassed: this only pins a version whose shipped
    manifest verifies byte-for-byte clean (empty mutated/missing/extra) —
    the exact same `verify_manifest` check the janitor-self-integrity
    detector runs. A version that fails C2 is NEVER pinned.

    FAIL-OPEN throughout: no cached versions, an already-current pin, a
    missing manifest, or any verify exception is a silent no-op — never a
    crash, never a partial/false pin. Mirrors `pin_good_version`'s own
    contract.

    Returns the version string that was newly pinned, or None when there
    was nothing to do (already current / unpinnable / not clean).
    """
    installed = list_installed_versions(cache_parent)
    if not installed:
        return None
    newest = installed[-1]
    pin = read_last_good()
    if pin is not None and pin.get("version") == newest:
        return None  # already certified — nothing to do
    newest_dir = cache_parent / newest
    manifest_path = newest_dir / _MANIFEST_REL
    if not manifest_path.is_file():
        return None  # unpinnable — same fail-open C2 has for a missing manifest
    try:
        mutated, missing, extra = janitor_self_integrity.verify_manifest(
            newest_dir, manifest_path
        )
    except Exception:
        return None  # any verify failure is uncertainty, never a pin
    if mutated or missing or extra:
        return None  # C2 caught a live mismatch — never pin a dirty tree
    return newest if pin_good_version(newest_dir, newest) else None


def read_quarantine() -> set[str]:
    """The set of quarantined (proven-bad) version strings, or an EMPTY set on
    any uncertainty (no file / unreadable / malformed).

    FAIL-OPEN is doubly important here: a corrupt quarantine file must NEVER be
    interpreted as "skip everything" — an empty set means the stub skips
    nothing, exactly as if no quarantine existed."""
    idir = _integrity_dir()
    if idir is None:
        return set()
    raw = janitor_integrity.read_or_restore(idir / _QUARANTINE_NAME)
    if raw is None:
        return set()
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return set()
    if not isinstance(obj, dict):
        return set()
    versions = obj.get("versions")
    if not isinstance(versions, list):
        return set()
    return {v for v in versions if isinstance(v, str) and v}


def add_quarantine(version: str, reason: str = "") -> bool:
    """Record ``version`` as proven-bad so the stub skips it fast on later
    fires. Unions with the existing set (never replaces), idempotent, written
    crash-safely. Returns False only on a DATA-dir / I/O failure."""
    idir = _integrity_dir()
    if idir is None:
        return False
    current = read_quarantine()
    current.add(version)
    blob = json.dumps(
        {"versions": sorted(current), "last_reason": reason}, sort_keys=True
    ).encode("utf-8")
    try:
        janitor_integrity.backup_and_write(idir / _QUARANTINE_NAME, blob)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# C4 (TRDD-T198DT1W) — bad-self-update auto-rollback DECISION (pure).
#
# C3 (above) ships the CONSUMING half: the dispatcher-stub already SKIPS a
# quarantined version and walks down to the next-older runnable one, with a
# fail-open backstop that runs the newest regardless when nothing is
# acceptable. C4 is the PRODUCER of that quarantine entry: when a self-update
# lands a version whose daemon/heartbeat won't STAY alive (it crash-loops),
# quarantine that newest version so the next stub fire falls back to a
# known-good older version — auto-rollback, no new stub change.
#
# These functions are PURE decisions (no I/O beyond a cache `iterdir`/`is_file`
# probe; they NEVER write the quarantine — the caller does). The crash-loop
# SIGNAL is supplied by the caller (global_state.crash_loop_active); decoupling
# it keeps this testable and keeps the live-system read in one place.
#
# CARDINAL RULE — FAIL-OPEN / ZERO-FALSE-ROLLBACK: a rollback is proposed ONLY
# when (a) the daemon is PROVABLY crash-looping AND (b) a strictly-OLDER runnable
# version exists in the cache to fall back to AND (c) the newest is not already
# quarantined. A HEALTHY update never trips (a) — a healthy daemon spawns once
# and stays alive, so the spawn breaker never fires — so a good version is NEVER
# rolled back. With no older fallback, (b) fails and we propose nothing (the
# stub's own fail-open backstop still runs the newest — a bad heartbeat beats a
# dead one). The decision touches NOTHING until all three hold.
# ---------------------------------------------------------------------------


def older_runnable_version(cache_parent: Path, newest: str) -> str | None:
    """The highest installed version STRICTLY OLDER than ``newest`` whose
    ``scripts/dispatch.py`` exists (a real fallback the stub can run), or None
    when there is no such version.

    This is the fallback-exists guard for the rollback decision: quarantining
    the crash-looping newest is only WORTH doing — and only provably safe — when
    an older runnable version is on disk for the stub to walk down to. Pure: a
    cache `iterdir` + per-candidate `is_file` probe, no mutation."""
    newest_t = _semver_tuple(newest)
    if newest_t == (-1,):
        return None
    candidates = [
        v for v in list_installed_versions(cache_parent)
        if _semver_tuple(v) < newest_t
        and (cache_parent / v / "scripts" / "dispatch.py").is_file()
    ]
    if not candidates:
        return None
    # list_installed_versions is sorted ascending → the last strictly-older
    # candidate is the highest (closest) known-good fallback.
    return candidates[-1]


def plan_crash_loop_rollback(cache_parent: Path, *, crash_loop: bool) -> tuple[str, str] | None:
    """Decide whether to auto-rollback a crash-looping self-update. PURE — it
    quarantines NOTHING; the caller passes the result to ``add_quarantine``.

    Returns ``(bad_version, fallback_version)`` — the NEWEST cached version (the
    one the dying daemon is spawned from) and the older runnable version the stub
    would fall back to — ONLY when ALL hold:
      1. ``crash_loop`` is True (the daemon is PROVABLY dying on start);
      2. a strictly-OLDER runnable version exists (``older_runnable_version``);
      3. the newest is not ALREADY quarantined (idempotent — never re-alert).
    Returns None otherwise (fail-open: no proof, no fallback, or already done →
    do nothing). The newest is recomputed from the cache here so the caller never
    has to identify the bad version itself."""
    if not crash_loop:
        return None  # no proof the daemon is dying → never roll back (fail-open)
    installed = list_installed_versions(cache_parent)
    if not installed:
        return None  # nothing installed to reason about
    newest = installed[-1]
    # Only quarantine a version that is actually RUNNABLE-but-bad; a newest dir
    # with no dispatch.py is already unrunnable and the stub skips it on its own.
    if not (cache_parent / newest / "scripts" / "dispatch.py").is_file():
        return None
    if newest in read_quarantine():
        return None  # already quarantined → idempotent, never re-alert
    fallback = older_runnable_version(cache_parent, newest)
    if fallback is None:
        return None  # no known-good older version → leave it to the stub's backstop
    return (newest, fallback)
