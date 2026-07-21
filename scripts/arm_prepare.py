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
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import global_state as gs  # noqa: E402
import state  # noqa: E402

DEFAULT_CRON = "*/5 * * * *"
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
    """The cadence to arm: the tier the dispatcher ASKED for, else config, else the default.

    Reading `desired-cadence.cron` FIRST is what makes a `[janitor-renew]` re-arm bake the tier
    the dynamic cadence chose (TRDD-0QQX9H0G) rather than silently resetting it to the default.
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

    # Arming means "this session starts in a KNOWN state", so the LOCAL maintenance
    # sentinel is revoked too (owner directive 2026-07-21). A sticky local flag made a
    # session fire cache-refresh-only forever with nothing on screen saying so — you had
    # to inspect every instance to learn which ones were suppressed.
    #
    # The GLOBAL flag is deliberately NOT cleared: /janitor-arm runs AUTOMATICALLY on
    # every SessionStart re-arm, so clearing it here would mean merely opening a new
    # Claude session silently lifts fleet-wide maintenance — the mode could never be
    # kept on. Same rule the arm already applies to the machine-wide kill-switch: a
    # project arm must not undo a deliberate machine-wide decision. Instead we REPORT
    # it, which solves the visibility problem without the override.
    try:
        (sd / state.MAINTENANCE_FLAG).unlink()
    except OSError:
        pass

    install_stub(plugin_root, data_dir)
    cron = resolve_cron(sd)
    prior = take_prior_cron_id(sd)

    print("scope=ok")
    print(f"cron={cron}")
    print(f"prior-cron-id={prior}")
    print(f"sweep={'no' if prior else 'yes'}")
    print(f"maintenance={'global-on' if gs.maintenance_mode_present() else 'off'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
