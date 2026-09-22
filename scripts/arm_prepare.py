#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Everything /janitor-arm must do BEFORE it touches the cron (TRDD-DLI76AUC).

The arm used to be six tool calls, and a tool call is not free: every round-trip re-reads the
whole conversation at the 0.1x cache-read rate, so at a ~520k context each one costs ~52k
weighted. Six of them made a re-arm cost about what six quiet heartbeat fires cost — which is
why the dynamic cadence (TRDD-0QQX9H0G) could spend more on switching tiers than the slower
tier ever saved. This script folds four of those calls into one: the scope guard, the stub
install, the cadence resolve, and the prior cron id the skill needs in order to delete the old
heartbeat WITHOUT a CronList.

Output is `key=value` lines for the skill to read:

    scope=ok
    cron=*/15 * * * *
    prior-cron-id=ff020fd5     # empty => the id is unknown; the skill must CronList and sweep
    sweep=no                   # yes => do a full CronList sweep instead of a targeted delete

THE CRASH-SAFETY PROPERTY (the reason the id is cleared HERE and not later):
we print the stored id and then DELETE it, before the caller deletes or creates any cron. So a
turn that dies anywhere in the middle of an arm leaves NO stored id, and the next arm sees
`sweep=yes` and removes every janitor heartbeat before creating one. Clearing it at the END
would instead leave a stale id pointing at an already-deleted cron while the newly-created one
went unrecorded — and the arm after THAT would create a second live heartbeat, silently doubling
the fire cost of the session forever. A half-finished arm must fail toward "sweep everything",
never toward "leak a heartbeat". This mirrors the ordering rationale the skill already applies to
`disarmed.flag`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Mapping
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import global_state as gs  # noqa: E402
import state  # noqa: E402

DEFAULT_CRON = "*/15 * * * *"
CRON_ID_FILE = "heartbeat-cron-id.txt"
DESIRED_CADENCE_FILE = "desired-cadence.cron"

# The janitor's DATA dir is FIXED, but it is resolved at CALL time, never captured at import.
# A module-level `Path.home()` freezes whatever HOME the interpreter started with, which then
# escapes every later attempt to redirect it — the import-time-capture class of bug (TRDD-ZNN0UK5K).
DEFAULT_DATA_SUBPATH = ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins"


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    """The janitor's persistent DATA dir. `CLAUDE_PLUGIN_DATA` is authoritative here (we ARE the
    janitor); the literal fallback keeps the script usable from a bare shell or a test harness."""
    environ: Mapping[str, str] = os.environ if env is None else env
    configured = (environ.get("CLAUDE_PLUGIN_DATA") or "").strip()
    if configured:
        return Path(configured)
    home = environ.get("HOME") or str(Path.home())
    return Path(home) / DEFAULT_DATA_SUBPATH


def resolve_cron(state_dir: Path, env: Mapping[str, str] | None = None) -> str:
    """The cadence to arm: an explicit `desired-cadence.cron` override, else the user's config
    knob, else the fixed default (TRDD-BRHJHWW0 — the dispatcher no longer drives tiers, so this
    file is normally absent; the read stays so a future or manual override still wins).
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    desired = state_dir / DESIRED_CADENCE_FILE
    try:
        cron = desired.read_text(encoding="utf-8").strip()
        if cron:
            return cron
    except OSError:
        pass
    return (environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON") or "").strip() or DEFAULT_CRON


def take_prior_cron_id(state_dir: Path) -> str:
    """Read the stored cron id AND clear it. Returns "" when unknown (⇒ the caller must sweep).

    Consuming the id is the whole point — see the crash-safety note in the module docstring. This
    is a take, not a read.
    """
    path = state_dir / CRON_ID_FILE
    try:
        cron_id = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    try:
        path.unlink()
    except OSError:
        # Could not consume it — so we cannot promise it will be gone after a crash. Report it as
        # unknown and let the caller sweep: a redundant CronList is cheap, a leaked heartbeat is not.
        return ""
    return cron_id


def install_stub(plugin_root: Path, data_dir: Path) -> Path:
    """Copy the dispatcher stub into the persistent DATA dir, atomically (tmp + rename).

    The stub is what the cron actually fires; a torn stub file would break every heartbeat, so it
    is never written in place.
    """
    src = plugin_root / "scripts" / "dispatcher-stub.py"
    if not src.is_file():
        raise SystemExit(f"stub source missing: {src}")
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / "dispatcher-stub.py"
    tmp = dest.with_suffix(f".py.tmp.{os.getpid()}")
    shutil.copyfile(src, tmp)
    tmp.chmod(0o755)
    os.replace(tmp, dest)
    return dest


def restricted_mode_active() -> bool:
    """CC 2.1.248+ `--restricted` (or `CLAUDE_CODE_RESTRICTED=1`) strips Bash and ignores
    settings-file hooks. The cron this would arm fires a dispatcher stub via Bash and every
    guard is a settings-file hook, so an armed heartbeat could never actually run — arming it
    anyway would be a false claim of protection (a guardian silently absent is worse than one
    that says it can't run).

    Thin alias over `state.restricted_mode()`: `doctor` reports the same condition, and a
    second hand-rolled parse here is exactly how two surfaces start disagreeing about whether
    the janitor can run."""
    return state.restricted_mode()


_JEV_PROBE_CACHE_SECONDS = 6 * 60 * 60  # 6h — see jev_probe()'s docstring
_JEV_PROBE_TIMEOUT_SECONDS = 3  # was 20s; only a stamp miss/stale/failure ever pays this now


def _parse_probe_cost(stdout: str) -> float | None:
    """Pull `cost=<f>` out of jev_compact.py probe's one stdout line (`probe ok noul=.. cost=.. ms=..`).

    Best-effort: the stamp is a caching optimization, not the probe's own correctness --
    a line that doesn't parse just leaves `cost` as None rather than failing the probe.
    """
    for token in stdout.split():
        if token.startswith("cost="):
            try:
                return float(token[len("cost=") :])
            except ValueError:
                return None
    return None


def _write_jev_probe_stamp(stamp_path: Path, *, ok: bool, reason: str | None, cost: float | None, provider: str) -> None:
    """Best-effort: a stamp write failure must not turn a successful probe into an arm failure.
    `provider` is stamped alongside the verdict so a later read can tell a genuinely fresh
    "ok" apart from one measured under a DIFFERENT provider — see jev_probe()'s cache-key note.
    """
    body = {"ok": ok, "reason": reason, "ts": time.time(), "cost": cost, "model": None, "provider": provider}
    try:
        state.atomic_write(stamp_path, json.dumps(body))
    except OSError:
        pass


def jev_probe(plugin_root: Path, state_dir: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """Run `jev_compact.py probe` at arm time, off the hot path (TRDD-541CBN36 card 2 follow-ups).

    `arm_prepare.py` runs on every SessionStart of every project on this machine — a network
    round trip there is a session-start stall the WHOLE janitor rests on, not a one-off cost.
    So the probe is CACHED: a `jev-probe.json` stamp under the janitor state dir
    (`{"ok": bool, "reason": str|None, "ts": epoch, "cost": float|None, "model": str|None,
    "provider": str}`) younger than 6h, with `ok: true` AND a `provider` matching the CURRENT
    `CLAUDE_PLUGIN_OPTION_JEV_PROVIDER`, short-circuits the subprocess entirely — zero network,
    zero wait. Only a missing/stale/failed/provider-mismatched stamp pays the (now 3s-bounded,
    was 20s) subprocess cost. 3s, not 20s: a probe that hasn't answered in 3s on a live host is
    not going to save this arm anything over just trying again next arm — 20s was sized for the
    one-shot case, not a check now hit on every arm until it succeeds once and caches.

    The `provider` key (an adversarial review flagged this, TRDD-541CBN36 card 2 follow-ups)
    exists because the cache is otherwise config-oblivious: a stamp keyed only on age would
    keep reporting a stale `jev=ok` for up to 6h after the user switched
    `CLAUDE_PLUGIN_OPTION_JEV_PROVIDER` (openrouter <-> typesafe), silently probing the WRONG
    provider's health. It does NOT cover an API-key rotation under the same provider name --
    that would need hashing the key into the stamp, which is out of scope here; a rotated key
    is caught the same way any other probe failure is, on the next natural cache miss.

    A dedicated `off` value on `CLAUDE_PLUGIN_OPTION_JEV_PROVIDER` (on top of the two the
    provider module itself knows, `openrouter`/`typesafe`) skips this entirely — arming
    must work on a host that never wants Jev compaction, with no network call and no error
    line. A probe FAILURE changes nothing else here (arming proceeds either way); it only
    changes what gets printed, so the skill/human sees `jev=<reason>` instead of `jev=ok`.
    This never changes the arm's own exit code.
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    provider = (environ.get("CLAUDE_PLUGIN_OPTION_JEV_PROVIDER") or "").strip().lower()
    if provider == "off":
        return "jev=off"

    sd = state.state_dir() if state_dir is None else state_dir
    stamp_path = sd / "jev-probe.json"
    now = time.time()
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        age = now - float(stamp["ts"])
        fresh = stamp.get("ok") is True and 0 <= age < _JEV_PROBE_CACHE_SECONDS
        same_provider = stamp.get("provider") == provider
        if fresh and same_provider:
            return f"jev=ok (cached {int(age)}s)"
    except (OSError, ValueError, KeyError, TypeError):
        pass  # no stamp, unreadable, or malformed -- fall through to a live probe

    script = plugin_root / "scripts" / "jev_compact.py"
    if not script.is_file():
        return "jev=script missing"
    proc = state.run_subprocess(
        ["uv", "run", "--script", "--quiet", str(script), "probe"],
        timeout=_JEV_PROBE_TIMEOUT_SECONDS,
        detector_name="arm_prepare",
    )
    if proc is None:
        result = "jev=probe did not run (timeout or uv not on PATH)"
        _write_jev_probe_stamp(stamp_path, ok=False, reason=result, cost=None, provider=provider)
        return result
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        _write_jev_probe_stamp(stamp_path, ok=False, reason=reason, cost=None, provider=provider)
        return f"jev={reason}"

    cost = _parse_probe_cost(proc.stdout)
    _write_jev_probe_stamp(stamp_path, ok=True, reason=None, cost=cost, provider=provider)
    return "jev=ok"


def scope_is_user(plugin_root: Path) -> tuple[bool, str]:
    """The janitor MUST be a user-scope install: it guards OAuth, the machine-global daemon, and
    drift for the WHOLE machine. Arming a project-scope janitor would bind a machine-global
    guardian to one repo. Delegates to the detector so there is ONE definition of the check."""
    detector = plugin_root / "scripts" / "detectors" / "janitor-install-scope.py"
    if not detector.is_file():
        return True, "scope check unavailable (detector missing) — proceeding"
    proc = state.run_subprocess([sys.executable, str(detector), "--check"], timeout=60, detector_name="arm_prepare")
    if proc is None:
        return True, "scope check did not run — proceeding"
    if proc.returncode != 0:
        return False, (proc.stdout or proc.stderr or "").strip()
    return True, (proc.stdout or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(prog="arm_prepare")
    ap.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT", ""))
    ap.add_argument("--data-dir", default="")
    args = ap.parse_args()

    plugin_root = Path(args.plugin_root) if args.plugin_root else _HERE.parent
    data_dir = Path(args.data_dir) if args.data_dir else resolve_data_dir()

    if restricted_mode_active():
        print("scope=refused")
        print(
            "restricted mode active (--restricted / CLAUDE_CODE_RESTRICTED) — Bash is removed "
            "and settings-file hooks are ignored, so the heartbeat cron could never run its "
            "dispatcher stub; arming here would be a false claim of protection"
        )
        return 1

    ok, msg = scope_is_user(plugin_root)
    if not ok:
        print("scope=refused")
        print(msg)
        return 1

    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)

    # Revoke the opt-out FIRST, before anything can fail. A turn that dies after this leaves no
    # cron AND no opt-out, so the fleet guardian reads `cron_dead` and re-arms — the arm self-heals.
    # Clearing it last would leave a cron plus a stale opt-out, and the guardian would file this
    # project under "the user opted out" and never touch it again.
    #
    # `state.DISARMED_FLAG`, never a literal: the flag's name has exactly ONE definition, because
    # its readers and its writer once spelled it independently and drifted apart. The writer is
    # `disarm_guard.py`, the reader is `fleet_scan.py`, and this is the remover — all three name
    # the same constant, and a test binds the chain together.
    try:
        (sd / state.DISARMED_FLAG).unlink()
    except OSError:
        pass

    # Sweep the RETIRED sentinels — pause, maintenance mode, the self-budget's maintenance
    # flag — at BOTH scopes (owner directive 2026-07-31). Nothing reads any of them now, so
    # this cannot undo a live decision; it is the migration that keeps an upgraded host from
    # looking suspended forever. The global flag is swept HERE, breaking the older rule that
    # a project arm never touches machine-wide state, because that rule protected a machine-
    # wide CHOICE and there is no longer a choice to protect: the only lever that used to
    # lift the global flag (/janitor-global-maintenance-off) is gone with the mode, and
    # /janitor-global-arm is reached only after a DISARM, so a host left in maintenance would
    # otherwise never be swept by anything.
    for name in state.RETIRED_SENTINELS:
        try:
            (sd / name).unlink()
        except OSError:
            pass
    gs.clear_maintenance_mode()

    install_stub(plugin_root, data_dir)
    cron = resolve_cron(sd)
    prior = take_prior_cron_id(sd)

    print("scope=ok")
    print(f"cron={cron}")
    print(f"prior-cron-id={prior}")
    print(f"sweep={'no' if prior else 'yes'}")
    print(jev_probe(plugin_root, state_dir=sd))
    # No `maintenance=` line any more — there is no maintenance mode to report. The line
    # existed to make a suppressed host visible, and even in that narrow form it was
    # dangerous: agents read a status line about maintenance, collided it with the
    # heartbeat nudge's "do NOT disable maintenance mode", and RE-ENABLED it globally
    # (owner report 2026-07-21). Nothing suppresses a host now, so nothing needs reporting.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
