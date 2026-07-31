"""Install plugin-shipped rule files into the active scope's .claude/rules/.

When a plugin ships rules under `<plugin_root>/rules/*.md`, those files
are NOT picked up automatically by Claude Code — the rule loader only
reads `~/.claude/rules/*.md` (user-scope) and
`<project_root>/.claude/rules/*.md` (project-scope and local-scope).
This module copies the plugin's shipped rules into whichever scope's
rules directory matches the plugin's installed scope.

Scope detection mirrors `scripts/detectors/version-update.py`'s
`_detect_install_scopes` — the source of truth lives there. We do NOT
import the detector at runtime (it would couple a hook against a
detector and pull `state` / `dedupe` into the import graph), so the
detection logic is duplicated here. If the version-update detector's
heuristic is ever revised, mirror the change here too.

Idempotency (content-based — issue #37):
  * If the destination file already exists AND its body is byte-identical
    to the plugin's source copy, it is left alone ("already up to date").
  * Otherwise the plugin's copy overwrites it, SUBJECT to the monotonic
    guard below. Rationale: the plugin author ships rule updates by
    editing `<plugin_root>/rules/*.md` and bumping the release; without
    overwrite-on-difference, every user who saw the previous version
    would be stuck on it forever. Byte-exact comparison (NOT size-only)
    closes a silent blind spot: a rule edit that preserves the byte
    count — e.g. a scope-root path swap of equal length — would slip
    past a size check and strand the user on a stale rule whose
    recall silently misses (#37, the quietest failure mode for a
    memory system). Rule files are small, so reading both copies at
    most once per session is cheap.
  * Empty `<plugin_root>/rules/` directory is a silent no-op.
  * No installed scope (e.g. fresh checkout outside a Claude Code
    session) is also a silent no-op — the hook degrades gracefully
    instead of erroring.

MONOTONICITY (issue #141) — why content-exact was not enough:
  Every installed file carries a first-line stamp naming the plugin
  version that wrote it, and an install is REFUSED when that version is
  newer than the one installing. Without it the comparison overwrote in
  EITHER direction, so on a host with several cached versions the
  agent-facing contract converged on whichever session started LAST.
  Measured live: `~/.claude/rules/janitor-heartbeat-protocol.md` was
  0.60.1's copy while 0.66.1 was cached — six versions of contract fixes
  reverted, including the `[janitor-quiet]` marker the dispatcher emits
  but that rule does not list, which under the rule's own security clause
  an agent must refuse. The executable half (the dispatcher stub) always
  rolls FORWARD to the newest cache, so only the contract half could go
  backward; that asymmetry is the whole bug.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

PLUGIN_NAME = "ai-maestro-janitor"

# Provenance marker every shipped rule carries in its guard block (rules/*.md). It is
# the SOLE identifier the cleanup uses to decide a rule file was installed by THIS plugin
# and is therefore safe to remove — a user's own hand-written rule of the same name (no
# marker) is NEVER touched, and NO memory store is ever touched. Keep this string in sync
# with the leading provenance comment prepended to each shipped rule file.
PROVENANCE_MARKER = "ai-maestro-janitor:installed-rule"

# The MONOTONIC stamp (#141). Written as the installed file's FIRST line; the shipped source never
# carries one. It records exactly one thing — WHICH plugin version wrote this file — because that is
# the only datum the guard needs and the only one that was missing when this bug had to be
# diagnosed. It is deliberately not an integrity digest: nothing would verify it, and every byte
# here is re-written into cache by every cold subagent on the machine. (Tamper detection over the
# plugin's own files already exists, properly, in janitor_self_integrity's signed manifest.)
_STAMP_PREFIX = "<!-- ai-maestro-janitor:rule-stamp"
_STAMP_RE = re.compile(r"^<!--\s*ai-maestro-janitor:rule-stamp\s+version=(?P<v>\S+)\s*-->$")


def _plugin_version(plugin_root: Path) -> str:
    """The version of the plugin tree being installed FROM, or "" when unreadable."""
    try:
        data = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    except (OSError, ValueError):
        return ""
    v = data.get("version")
    return v if isinstance(v, str) else ""


# The key an UNPARSEABLE version sorts to. Lower than every real version, so an unknown stamp can
# never win a comparison — see `should_install` for why every unknown must fail toward INSTALLING.
_UNKNOWN_KEY = (-1,)


def _semver_key(version: str) -> tuple[int, ...]:
    """Sortable key for a semver-ish string; `_UNKNOWN_KEY` when it does not parse."""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            return _UNKNOWN_KEY
        parts.append(int(digits))
    return tuple(parts) if parts else _UNKNOWN_KEY


def _stamped_bytes(src_bytes: bytes, version: str) -> bytes:
    """The bytes to install: the stamp line, then the shipped file verbatim."""
    # "unknown" — never "0.0.0". A placeholder that PARSES would outrank a genuinely unknown source
    # on the next install and could freeze the file; `unknown` sorts to _UNKNOWN_KEY and cannot.
    return f"{_STAMP_PREFIX} version={version or 'unknown'} -->\n".encode() + src_bytes


def split_stamp(installed: bytes) -> tuple[str | None, bytes]:
    """`(stamped_version, body)` for an installed file. A `None` version means it carries no stamp,
    and the WHOLE file is the body — so a pre-stamp or hand-placed file still compares exactly as
    the old byte-compare did."""
    head, sep, rest = installed.partition(b"\n")
    if not sep:
        return None, installed
    try:
        line = head.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None, installed
    m = _STAMP_RE.match(line)
    return (m.group("v"), rest) if m else (None, installed)


def should_install(
    installed_version: str | None, body_matches: bool, src_version: str
) -> tuple[bool, str]:
    """PURE. May we overwrite the installed file with this source? Returns `(install, why)`.

    THE DEFECT THIS FIXES (#141). The previous rule was "bytes differ ⇒ overwrite", in EITHER
    direction — so the agent-facing contract converged on whichever session started LAST, not on the
    newest version. Verified live: a host with 0.66.1 cached had 0.60.1's rule installed, six
    versions old, because a session running 0.60.1 skills wrote it last. That rule did not document
    `[janitor-quiet]`, which the dispatcher emits — and the rule's own security clause tells an agent
    to refuse an unlisted marker. So a shipped contract fix could be silently reverted by any older
    session on the machine, which makes every contract change unreliable.

    Now the contract only ever moves FORWARD:

    * no stamp        → INSTALL. First run, a pre-stamp copy, or a hand-placed file. This preserves
                        the one-shot takeover the byte-compare existed for.
    * body identical  → skip. Already exactly this content; nothing to do.
    * installed newer → **SKIP — the guard.** A newer session already wrote a better contract, and
                        an older one must not drag it back. The price is that a NEWER file which was
                        hand-edited is not self-healed here; the newer session heals it.
    * unknown SOURCE  → INSTALL. See below.
    * otherwise       → INSTALL (source is newer, or same version with changed content).

    EVERY unknown fails toward INSTALLING, deliberately. The guard's only job is to stop an OLDER
    version from overwriting a NEWER one; if we cannot tell how old the source is, refusing would
    freeze the destination against every future install — the exact failure this guard exists to
    prevent, inverted and permanent. An unreadable `plugin.json` must degrade to the old behaviour,
    not to a rule nothing can ever replace.
    """
    if installed_version is None:
        return True, "unstamped"
    if body_matches:
        return False, "up-to-date"
    src_key = _semver_key(src_version)
    if src_key == _UNKNOWN_KEY:
        return True, "source version unknown"
    if _semver_key(installed_version) > src_key:
        return False, f"installed {installed_version} is newer than {src_version}"
    return True, "source-newer-or-changed"


def _publish_monotonic(src: Path, dst: Path, version: str) -> bool:
    """Install `src` at `dst`, stamped, unless a NEWER version already wrote it.

    Returns True iff `dst` was written. Never raises: an unreadable source or a failed write is a
    silent no-op, exactly as the plain copy was — SessionStart must degrade, not error.
    """
    try:
        src_bytes = src.read_bytes()
    except OSError:
        return False

    if dst.exists():
        try:
            installed_version, body = split_stamp(dst.read_bytes())
        except OSError:
            # Can't read (race, permission). Bail rather than overwrite on incomplete info.
            return False
        install, _ = should_install(installed_version, body == src_bytes, version)
        if not install:
            return False

    payload = _stamped_bytes(src_bytes, version)
    tmp = None
    try:
        # Atomic publish: write a unique temp in the SAME dir, then os.replace (atomic rename on
        # POSIX) so N concurrent session-start installs writing this user-scope file can't tear it.
        # Rules-install stays per-session (rules must be present at session start), but the write is
        # corruption-free under fan-out — the cheap-idempotent-file analogue of the daemon's
        # single-writer lock for commands.
        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=f".{dst.name}.", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, dst)
        return True
    except OSError:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def _data_dir() -> Path:
    """The janitor's canonical persistent DATA dir. Its ABSENCE is one of the two
    signals that the plugin has been fully uninstalled (Claude Code deletes the data dir
    when the plugin is removed from its last scope, unless `--keep-data`)."""
    return Path.home() / ".claude" / "plugins" / "data" / f"{PLUGIN_NAME}-ai-maestro-plugins"


def _known_rules_dirs() -> list[Path]:
    """Every `.claude/rules/` dir the janitor could have installed into: the USER dir
    always, plus the PROJECT dir when a `$CLAUDE_PROJECT_DIR` is in scope. The daemon
    (no project context) sees only the user dir; a session sees both."""
    dirs = [Path.home() / ".claude" / "rules"]
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        dirs.append(Path(project_dir) / ".claude" / "rules")
    return dirs


def _is_janitor_installed_rule(path: Path) -> bool:
    """True iff `path` is a rule file THIS plugin installed — i.e. it carries the
    provenance marker. Fail-closed: an unreadable file returns False (never removed)."""
    try:
        return PROVENANCE_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _remove_janitor_rules_in(rules_dir: Path) -> list[str]:
    """Remove every provenance-marked janitor rule from `rules_dir` (a `.claude/rules/`
    dir). Returns the removed paths. SAFETY: only `*.md` files carrying the marker are
    removed — a user's own rule (no marker) is left alone — and nothing OUTSIDE
    `rules_dir` is ever touched, so no memory store can be affected."""
    removed: list[str] = []
    if not rules_dir.is_dir():
        return removed
    for p in sorted(rules_dir.glob("*.md")):
        if not _is_janitor_installed_rule(p):
            continue
        try:
            p.unlink()
            removed.append(str(p))
        except OSError:
            continue
    return removed


def _current_target_dirs() -> set[str]:
    """The set of `str(rules_dir)` the janitor SHOULD currently install into, mirroring
    `install_rules`'s scope logic (user-scope wins, dedup by path). Any KNOWN rules dir
    not in this set is one the janitor was uninstalled from → its janitor rules are
    orphans to remove."""
    scopes = _detect_install_scopes()
    if "user" in scopes:
        scopes = ["user"]
    keep: set[str] = set()
    for scope in scopes:
        td = _target_rules_dir(scope)
        if td is not None:
            keep.add(str(td))
    return keep


def remove_orphaned_rules() -> list[str]:
    """Partial-uninstall self-heal: remove janitor-installed rules from every KNOWN rules
    dir that is NOT a current install target — e.g. the PROJECT scope after the janitor
    was uninstalled from it while still user-installed (also the "redundant project mirror
    of a user-scope rule" cleanup, issue #36). Marker-gated; never touches a user's own
    rule or any memory store. Returns removed paths."""
    keep = _current_target_dirs()
    removed: list[str] = []
    for d in _known_rules_dirs():
        if str(d) in keep:
            continue
        removed.extend(_remove_janitor_rules_in(d))
    return removed


def janitor_uninstalled() -> bool:
    """True iff the janitor appears FULLY uninstalled: referenced in NO settings.json
    scope AND its persistent DATA dir is gone. BOTH must hold — requiring the two
    independent signals to agree resists a transient false positive (a momentary
    settings-read miss AND a vanished data dir do not co-occur under normal operation).
    A merely DISABLED plugin still appears in settings.json, so this returns False for
    it (we must not delete rules for a plugin the user only paused)."""
    if _detect_install_scopes():
        return False
    return not _data_dir().exists()


def cleanup_user_orphans_if_uninstalled() -> list[str]:
    """Daemon entry point (TRDD-H9IBY95W): when the janitor is FULLY uninstalled, remove
    its provenance-marked orphaned rules from the USER rules dir (`~/.claude/rules/`).
    Claude Code has NO uninstall hook and does not clean a plugin's `~/.claude/rules/`, so
    the still-running daemon (alive until its orphaned cache is GC'd, ~7 days) is the only
    actor that can remove them. The daemon is global (no project context) → user scope
    only; per-session `remove_orphaned_rules` covers project scope. Returns [] while the
    janitor is still installed. NEVER touches any memory store."""
    if not janitor_uninstalled():
        return []
    return _remove_janitor_rules_in(Path.home() / ".claude" / "rules")


def _detect_install_scopes() -> list[str]:
    """Return every scope where the plugin is referenced in settings.json.

    Order: user → local → project. A plugin can be installed in
    multiple scopes simultaneously, so this returns a list (not a
    single value). String-match against `PLUGIN_NAME` matches both
    `enabledPlugins` and `disabledPlugins` mentions; we accept that
    ambiguity because rule files are harmless when the plugin is
    disabled, and full JSON parsing would couple this module to the
    Claude Code settings schema.
    """
    scopes: list[str] = []

    user_settings = Path.home() / ".claude" / "settings.json"
    if user_settings.is_file():
        try:
            if PLUGIN_NAME in user_settings.read_text(encoding="utf-8"):
                scopes.append("user")
        except OSError:
            pass

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        for scope, rel in (
            ("local", ".claude/settings.local.json"),
            ("project", ".claude/settings.json"),
        ):
            f = Path(project_dir) / rel
            if f.is_file():
                try:
                    if PLUGIN_NAME in f.read_text(encoding="utf-8"):
                        scopes.append(scope)
                except OSError:
                    pass
    return scopes


def _target_rules_dir(scope: str) -> Path | None:
    """Compute the .claude/rules/ directory for a given install scope.

    user-scope          → ~/.claude/rules/
    local + project     → $CLAUDE_PROJECT_DIR/.claude/rules/

    Local and project both live under the project's `.claude/`, so
    they map to the same target — the caller deduplicates by directory
    path, not by scope name.
    """
    if scope == "user":
        return Path.home() / ".claude" / "rules"
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir and scope in ("local", "project"):
        return Path(project_dir) / ".claude" / "rules"
    return None


def references_dir() -> Path:
    """Where the shipped rules' FULL reference docs live: `<DATA>/rules-reference/`.

    Deliberately NOT under any `.claude/rules/` dir. Claude Code loads every
    `~/.claude/rules/*.md` into the context PREFIX of every session AND every subagent,
    machine-wide — so a 35 KB reference doc there is re-written into cache by every cold
    agent that ever starts. The rules themselves must carry only the normative core; the
    bulky reference material (full schemas, transition matrices, grep cheat-sheets,
    migration guides) lives here and is READ ON DEMAND, costing zero tokens until an
    agent actually needs it. The DATA dir is the right home: it is the only path
    guaranteed stable across plugin version updates (TRDD-YRPUSIFY axis B)."""
    return _data_dir() / "rules-reference"


def install_references(plugin_root: Path) -> list[str]:
    """Copy <plugin_root>/rules/references/*.md into `<DATA>/rules-reference/`.

    Same content-exact idempotency as install_rules (byte compare, atomic tmp+replace),
    but the destination is the persistent DATA dir rather than a rules dir, so these
    files are never loaded into any context. Silent no-op when the source dir is absent.
    Returns the paths actually written."""
    src_dir = plugin_root / "rules" / "references"
    if not src_dir.is_dir():
        return []
    src_files = sorted(p for p in src_dir.iterdir() if p.is_file() and p.suffix == ".md")
    if not src_files:
        return []

    dst_dir = references_dir()
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []

    version = _plugin_version(plugin_root)
    written: list[str] = []
    for src in src_files:
        dst = dst_dir / src.name
        # Same monotonic guard as install_rules, and for the same reason: the rules POINT at these
        # docs, so an older session reverting a reference makes the rule cite content that no longer
        # says what the rule promises — a skew that is harder to notice than a stale rule, because
        # nothing surfaces it until an agent reads the reference and acts on it.
        if _publish_monotonic(src, dst, version):
            written.append(str(dst))
    return written


def install_rules(plugin_root: Path) -> list[str]:
    """Copy <plugin_root>/rules/*.md to every active scope's rules dir.

    NOTE: `iterdir()` is deliberately NON-recursive — `rules/references/` holds the
    on-demand full docs and must NEVER be installed as a rule (see install_references).

    Returns a list of `<dst-path>` strings for files that were actually written on this call (so the
    caller can log them). An existing destination is kept when its body is byte-identical to the
    source, and — since #141 — also when it was written by a NEWER plugin version than this one.
    """
    src_dir = plugin_root / "rules"
    if not src_dir.is_dir():
        return []

    rule_files = sorted(
        p for p in src_dir.iterdir() if p.is_file() and p.suffix == ".md"
    )
    if not rule_files:
        return []

    scopes = _detect_install_scopes()
    if not scopes:
        return []

    # USER-SCOPE WINS (issue #36). Claude Code loads `~/.claude/rules/*` for
    # EVERY project, so a user-scope rule already applies everywhere. A
    # project-local copy is therefore a REDUNDANT mirror that adds nothing AND
    # sits untracked in the project tree, tripping the dirty-tree detector on
    # every heartbeat. When the plugin is user-installed (the janitor always is),
    # install ONLY to the user scope. Fall back to the project scope solely when
    # the plugin is NOT at user scope (a project-only install, where the local
    # copy is the only way the rule reaches Claude).
    if "user" in scopes:
        scopes = ["user"]

    # Deduplicate target dirs: local + project both resolve to the
    # same `<project>/.claude/rules/` path, so a plugin installed in
    # both scopes would otherwise be processed twice. dict-by-path
    # keeps a single entry per unique target.
    targets: dict[str, Path] = {}
    for scope in scopes:
        td = _target_rules_dir(scope)
        if td is None:
            continue
        targets[str(td)] = td

    version = _plugin_version(plugin_root)
    copied: list[str] = []
    for td in targets.values():
        try:
            td.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for src in rule_files:
            # CONTENT-exact idempotency (issue #37) + the MONOTONIC guard (#141), both inside
            # `_publish_monotonic`. Content-exact because a size-only check has a silent blind spot:
            # a rule edit that preserves the byte count (swapping one scope-root path for another of
            # equal length) would not refresh the installed copy, stranding the user on a stale rule
            # whose recall silently misses. Monotonic because content-exact alone still overwrites in
            # EITHER direction, which is how the installed contract ended up six versions old.
            if _publish_monotonic(src, td / src.name, version):
                copied.append(str(td / src.name))
    return copied
