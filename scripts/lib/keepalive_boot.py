"""Pre-launch integrity gate for the L0 OS-keepalive (TRDD-DGROUPAB, D-β).

The OS keepalive launches ``daemon_keepalive_entry.py`` from the persistent DATA
dir, and that entry does a static ``import daemon`` — so the daemon AND its whole
~16-file import closure must be present and uncorrupted BESIDE the entry at the DATA
path. ``launchd_keepalive.staged_is_current`` byte-compares the whole closure vs the
cache (a CURRENCY check the daemon self-heal loop runs), but that runs only when a live
daemon is executing — nothing detects a *corrupt/truncated/incomplete* stage
(interrupted copy, disk-full, bit-rot, partial relocation) at LAUNCH, before any daemon
runs. A torn stage makes
``import daemon`` raise → the OS service crash-loops with NO re-stage trigger, because
the only thing that re-stages is a live session firing ``_setup_os_keepalive()`` — and
an all-sessions-down host (the exact scenario the OS keepalive exists for) cannot
provide one.

This module is the missing self-heal: the launched entry calls
``verify_or_restage(<its own dir>)`` BEFORE ``import daemon``. It verifies every staged
closure file's sha256 against the trusted CACHE baseline (the cache is already
C2/C3-verified by the dispatcher stub) and, on any mismatch / missing file, RE-STAGES
the whole closure from ``latest_cache_scripts_dir()`` so the next ``import daemon``
resolves clean code.

It lives in a SEPARATE lib module (not inlined in the entry) on purpose: the entry is
re-scanned by CPV's persistence discriminator and must stay provably inert (no
``open``/``hashlib``/``subprocess``/``shutil`` calls, no dynamic load). The discriminator
scans the launched file plus its exec/source chain but does NOT follow ``import`` — so
the heavy I/O is legal here, exactly as it is in the ``import daemon`` the entry already
performs. This module is covered by CPV's GENERAL validators, like every other lib.

Two hard invariants for the DEEPEST immortality layer:
  * FAIL-OPEN — a verify/restage fault must NEVER leave the daemon un-launchable when a
    runnable stage exists. If the cache is gone (can't verify), we PROCEED with whatever
    is staged rather than blocking — the daemon's own import then either works or fails
    visibly, and the crash-loop breaker bounds a die-on-start daemon. Every step is
    wrapped so an exception here can never abort the launch.
  * FAIL-LOUD — when the stage is broken AND there is no runnable cache to restage from
    (nothing runnable anywhere), we LOG LOUDLY to the keepalive log + stderr so the
    operator sees the cause, then let ``import daemon`` proceed and fail visibly — never
    a silent crash-loop.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import keepalive_stage  # sibling: computes the daemon's verbatim import closure
import launchd_keepalive  # sibling: latest_cache_scripts_dir() + restage()

try:
    # Sibling in the daemon closure. Its global_state_dir() honors
    # JANITOR_GLOBAL_STATE_DIR, resolved at CALL time — so the keepalive's log + restage
    # stamp land in the SAME test-overridable dir every other janitor global-state writer
    # uses, instead of a frozen real Path.home() that made the keepalive tests pollute
    # production state (TRDD-ZNN0UK5K).
    import global_state  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - defensive; the lib is part of the closure
    global_state = None  # type: ignore[assignment]

try:
    # _file_sha256 is the same streaming hasher the self-integrity manifest uses; reuse
    # it so closure verification hashes files exactly as the rest of the plugin does.
    from janitor_self_integrity import _file_sha256  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - defensive; the lib is part of the closure
    _file_sha256 = None  # type: ignore[assignment]

# The keepalive's log lives in the janitor global-state dir (same place launchd/systemd
# capture stdout/stderr to, and where the daemon pins its logs). A loud line here is
# visible next to the crash output.
_LOG_NAME = "daemon-keepalive.boot.log"
_LOG_MAX_BYTES = 256 * 1024  # rotate at 256 KB so the boot log can never grow unbounded
_RESTAGE_STAMP = "daemon-keepalive.restage-stamp"


def _state_dir() -> Path:
    """The keepalive log/stamp dir, resolved AT CALL TIME so JANITOR_GLOBAL_STATE_DIR (the
    isolation override every janitor global-state writer honors) is respected. A frozen
    module-level ``Path.home()`` constant made the keepalive tests write into production
    state and corrupt the real staged closure → the fseventsd runaway (TRDD-ZNN0UK5K).

    The import-failure fallback falls FORWARD to the DATA dir, never back to the retired
    era-1 ``~/.claude/janitor-global-state/`` (TRDD-ULEGRT01). A backward fallback would
    have this one code path recreate the very directory the retirement asks the user to
    delete — and it would do so precisely on the hosts where the import broke, i.e. the
    ones nobody is watching. It still honors the env override for test isolation, which
    is the whole reason this function resolves at call time."""
    if global_state is not None:
        try:
            return global_state.global_state_dir()
        except Exception:
            pass
    override = os.environ.get("JANITOR_GLOBAL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path.home()
        / ".claude"
        / "plugins"
        / "data"
        / "ai-maestro-janitor-ai-maestro-plugins"
        / "global-state"
    )


def _loud(msg: str) -> None:
    """Emit ``msg`` to BOTH stderr (launchd/systemd capture it) and a keepalive log file,
    each best-effort so a logging failure never propagates into the launch path. The log is
    size-rotated (``<name>`` → ``<name>.1``) so a persistent boot fault can't grow it
    without bound."""
    line = f"keepalive-boot: {msg}"
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        d = _state_dir()
        d.mkdir(parents=True, exist_ok=True)
        log = d / _LOG_NAME
        try:
            if log.stat().st_size > _LOG_MAX_BYTES:
                os.replace(log, log.with_name(_LOG_NAME + ".1"))
        except OSError:
            pass  # no log yet, or a concurrent rotate raced — the append below still works
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # A log we cannot write must not block the daemon — stderr already carried it.
        pass


def _restage_cooldown_s() -> int:
    """Seconds an identical repeated restage is suppressed. A closure that never converges
    (an un-stageable file, or a cache version that keeps flipping) otherwise re-copies the
    whole ~16-file closure on EVERY keepalive boot — the fsevents-churn half of the
    fseventsd runaway (TRDD-ZNN0UK5K). Env-tunable; 0 disables the suppression."""
    try:
        return max(0, int(os.environ.get("CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S", "300")))
    except (TypeError, ValueError):
        return 300


def _restage_recently_tried(signature: str, now: int) -> bool:
    """True iff the SAME mismatch ``signature`` was restaged within the cooldown and is
    STILL mismatched now — i.e. the prior restage did NOT make it converge, so copying the
    closure again is futile churn. Reads ``<state>/daemon-keepalive.restage-stamp``
    (``<ts>\\t<sig>``). Never raises. A cooldown of 0 always returns False (feature off)."""
    cooldown = _restage_cooldown_s()
    if cooldown <= 0:
        return False
    try:
        raw = (_state_dir() / _RESTAGE_STAMP).read_text(encoding="utf-8").strip()
        last_ts_s, _, last_sig = raw.partition("\t")
        return last_sig == signature and (now - int(last_ts_s)) < cooldown
    except (OSError, ValueError):
        return False


def _record_restage(signature: str, now: int) -> None:
    """Stamp ``(now, signature)`` atomically so an identical mismatch on the next boot is
    suppressed for the cooldown. Never raises."""
    try:
        d = _state_dir()
        d.mkdir(parents=True, exist_ok=True)
        stamp = d / _RESTAGE_STAMP
        tmp = stamp.with_name(f"{_RESTAGE_STAMP}.tmp.{os.getpid()}")
        tmp.write_text(f"{now}\t{signature}", encoding="utf-8")
        os.replace(tmp, stamp)
    except OSError:
        pass


def stage_mismatches(staged_scripts_dir: Path, cache_scripts_dir: Path) -> list[str]:
    """Return the relative names of closure files that are MISSING or whose sha256 differs
    between the staged DATA copy and the trusted ``cache_scripts_dir`` baseline. The closure
    is computed from the CACHE (the source of truth for what *should* be staged), so a file
    the stage dropped entirely is reported as a mismatch. Empty ⇒ the stage is complete +
    byte-faithful to the cache. Pure-ish (only reads + hashes); never raises — an
    unreadable/unhashable file is conservatively reported as a mismatch so it gets restaged."""
    mismatches: list[str] = []
    try:
        closure = keepalive_stage.daemon_closure(cache_scripts_dir)
    except Exception as exc:  # cache unreadable/unparseable → caller treats as "can't verify"
        raise RuntimeError(f"could not compute cache closure: {exc}") from exc
    for src in closure:
        rel = src.relative_to(cache_scripts_dir)
        staged = staged_scripts_dir / rel
        try:
            if not staged.is_file():
                mismatches.append(rel.as_posix())
                continue
            if _file_sha256 is None:
                # No hasher available → fall back to a size+exists check (still catches a
                # truncated/missing file, the dominant corruption modes) rather than skip.
                if staged.stat().st_size != src.stat().st_size:
                    mismatches.append(rel.as_posix())
                continue
            if _file_sha256(staged) != _file_sha256(src):
                mismatches.append(rel.as_posix())
        except OSError:
            # Unreadable staged or source file → restage it to be safe.
            mismatches.append(rel.as_posix())
    return mismatches


def _repair(staged: Path, cache: Path) -> None:
    """Re-stage the daemon closure from ``cache`` into the EXACT dir that was verified
    (``staged``). When ``staged`` is the canonical DATA scripts dir (the production case —
    the entry runs from there), delegate to ``launchd_keepalive.restage`` so the shell
    installer is refreshed alongside the closure; otherwise stage the closure straight into
    ``staged`` (keeps the gate self-consistent if ever invoked from a non-DATA dir). Raises
    on I/O failure (the caller treats it as a failed restage)."""
    try:
        is_data = staged.resolve() == launchd_keepalive.data_scripts_dir().resolve()
    except OSError:
        is_data = False
    if is_data:
        launchd_keepalive.restage(cache)  # closure + installer, into DATA
    else:
        keepalive_stage.stage_closure(cache, staged)  # repair exactly what we verified


def verify_or_restage(staged_scripts_dir: object) -> bool:
    """Pre-launch gate the OS-keepalive entry calls BEFORE ``import daemon``.

    Verifies the staged closure at ``staged_scripts_dir`` against the trusted cache and
    restages from ``latest_cache_scripts_dir()`` on any mismatch. Returns True iff, after
    this call, the stage is believed clean (verified-clean, or restaged-clean). Returns
    False when the stage is broken and could NOT be repaired (no runnable cache) — in which
    case it has already logged LOUDLY; the entry still proceeds to ``import daemon`` so the
    failure is visible, never silent.

    NEVER raises: every branch is guarded so a fault in this gate cannot abort the launch
    (fail-OPEN). ``staged_scripts_dir`` is typed ``object`` because the entry passes a bare
    string from ``os.path`` — we coerce to ``Path`` here so the entry needs no pathlib."""
    try:
        staged = Path(str(staged_scripts_dir))
        cache = launchd_keepalive.latest_cache_scripts_dir()
        if cache is None:
            # No cache to verify against (inline/dev install, or a relocated/GC'd cache).
            # Cannot prove the stage good — but blocking would be worse than trusting it.
            # FAIL-OPEN: proceed with whatever is staged; the import will reveal any break.
            return True

        try:
            missing = stage_mismatches(staged, cache)
        except RuntimeError as exc:
            # Cache present but unreadable → can't verify. Fail-OPEN (don't block).
            _loud(f"could not verify staged closure ({exc}); proceeding with current stage")
            return True

        if not missing:
            return True  # stage is complete + byte-faithful to the cache

        signature = ",".join(sorted(missing))
        now = int(time.time())
        if _restage_recently_tried(signature, now):
            # The SAME closure files were restaged within the cooldown and are STILL
            # mismatched → the restage does not converge, so re-copying the whole closure is
            # pure fsevents churn (TRDD-ZNN0UK5K). Skip the copy; the first attempt already
            # logged the cause, and the import below still fails VISIBLY.
            return False

        _loud(
            f"staged closure is corrupt/incomplete ({len(missing)} file(s): "
            f"{', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}); "
            f"restaging from {cache}"
        )
        _record_restage(signature, now)
        try:
            _repair(staged, cache)
        except Exception as exc:
            # Restage itself failed (disk-full again, perms). Re-verify: if the stage is
            # somehow runnable anyway, proceed; else this is the nothing-runnable case.
            _loud(f"restage FAILED: {exc}")
            try:
                still_bad = stage_mismatches(staged, cache)
            except RuntimeError:
                still_bad = missing
            if still_bad:
                _loud(
                    "stage still broken after restage and no runnable copy available — "
                    "the daemon import will fail VISIBLY (not silently); operator action needed"
                )
                return False
            return True

        # Restage reported success — confirm it actually fixed the closure.
        try:
            remaining = stage_mismatches(staged, cache)
        except RuntimeError:
            return True  # can't re-verify; trust the successful restage (fail-open)
        if remaining:
            _loud(
                f"restage left {len(remaining)} file(s) still mismatched — proceeding so the "
                "import surfaces the fault visibly"
            )
            return False
        return True
    except Exception as exc:  # absolute backstop — this gate can never abort the launch
        _loud(f"verify-or-restage gate errored ({exc}); proceeding to import (fail-open)")
        return True
