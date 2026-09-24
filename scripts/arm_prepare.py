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
import hashlib
import os
import re
import shutil
import sys
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


# Matches ONLY a plain `*/N * * * *` minute-step cron — the shape this janitor ever arms
# (DEFAULT_CRON, the tier knob, or a manually-written desired-cadence.cron). Anything else
# (a list, a range, a non-`*` hour/day field) is a cron this janitor did not construct and must
# not rewrite — see `_stagger` below.
_STEP_CRON_RE = re.compile(r"^\*/(\d+) \* \* \* \*$")


def _stagger_offset(project_dir: Path, step: int) -> int:
    """A per-project minute offset in [0, step), stable across re-arms of the SAME project and
    (with high probability) different across projects — report:
    reports/hook-timeout/20260924_175736+0200-startup-timing.md, proposal 2.

    `hashlib.sha256`, never `hash()`: `hash(str)` is salted per-PROCESS (PYTHONHASHSEED), so the
    offset would differ on every re-arm of the same project and undo the whole point — two arms
    of the same project must land in the same minute-bucket, or the burst this exists to avoid
    just reappears one hop later.

    STABILITY DEPENDS ON `project_dir` BEING THE SAME STRING ACROSS ARMS. `resolve_cron`'s
    default (`state.project_root()`) uses `$CLAUDE_PROJECT_DIR` when set, which every real
    Claude Code invocation sets — so in practice every arm of one session sees the identical
    string. The offset would only drift if a re-arm ran with that env var absent AND the
    `git rev-parse --show-toplevel` fallback resolved a differently-spelled path (a symlinked
    checkout, say) than a prior arm — an existing edge case of `project_root()` itself, not
    introduced here, and one this function has no way to normalize away.
    """
    digest = hashlib.sha256(str(project_dir).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % step


def _stagger(cron: str, project_dir: Path) -> str:
    """Spread a plain `*/N` minute-step cron onto a stable per-project offset:
    `{offset}-59/{N} * * * *`. Every armed session otherwise shares the IDENTICAL cron grid, so
    all of a host's heartbeat prompts — and every hook they fire — start in the same minute; at
    load the report measured that burst pushing 30-60 concurrent hook launches to 1.4-2.0s of CPU
    run-queue wait, the very timeouts proposal 1 widened. A cron this janitor did not itself
    construct (anything not matching `_STEP_CRON_RE`) is returned UNCHANGED — staggering only
    the shape we know is safe to rewrite.

    Step must be in [1, 60]: a step > 60 (e.g. a hand-edited `*/90` desired-cadence.cron) would
    produce `{offset}-59/90 * * * *` with `offset` in [0, 90) — an offset above 59 gives an
    invalid range (start > end), which CronCreate would reject, and an offset of 59 or less
    gives a range that fires once an hour instead of every 90 minutes; either is worse than
    leaving the original cron unstaggered (review finding, TRDD-D7RLXAN1 follow-up).
    """
    m = _STEP_CRON_RE.match(cron)
    if not m:
        return cron
    step = int(m.group(1))
    if not 1 <= step <= 60:
        return cron
    offset = _stagger_offset(project_dir, step)
    return f"{offset}-59/{step} * * * *"


def resolve_cron(state_dir: Path, env: Mapping[str, str] | None = None, project_dir: Path | None = None) -> str:
    """The cadence to arm: an explicit `desired-cadence.cron` override, else the user's config
    knob, else the fixed default (TRDD-BRHJHWW0 — the dispatcher no longer drives tiers, so this
    file is normally absent; the read stays so a future or manual override still wins), then
    STAGGERED onto a stable per-project offset (see `_stagger`) so this project's heartbeat does
    not land in the same minute as every other armed session's.
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    desired = state_dir / DESIRED_CADENCE_FILE
    cron: str | None = None
    try:
        candidate = desired.read_text(encoding="utf-8").strip()
        if candidate:
            cron = candidate
    except OSError:
        pass
    if cron is None:
        cron = (environ.get("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON") or "").strip() or DEFAULT_CRON
    root = project_dir if project_dir is not None else state.project_root()
    return _stagger(cron, root)


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
    # No `maintenance=` line any more — there is no maintenance mode to report. The line
    # existed to make a suppressed host visible, and even in that narrow form it was
    # dangerous: agents read a status line about maintenance, collided it with the
    # heartbeat nudge's "do NOT disable maintenance mode", and RE-ENABLED it globally
    # (owner report 2026-07-21). Nothing suppresses a host now, so nothing needs reporting.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
