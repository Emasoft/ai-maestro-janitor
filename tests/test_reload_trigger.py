"""Tests for the /janitor-reload-plugins backing script (scripts/reload_trigger.py).

SAFETY: every test that exercises main() passes --dry-run and a controlled env, so
the real osascript ESC->/reload-plugins is NEVER fired (it would reload the
developer's own live pane). The pure helper is tested directly; main() is tested
via real subprocess runs with --dry-run.

Unlike the compact trigger, reload records NO resume directive (reloading plugins
does not discard the conversation), so there is no file side effect to assert.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "reload_trigger.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402  # for the per-pane presence key (user directive 2026-07-16)


def _import():
    spec = _u.spec_from_file_location("reload_trigger_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stamp_pane_presence(home: Path, pane_id: str) -> None:
    """Also stamp THIS pane's own breadcrumb — presence is PER-PANE.

    conftest's `present_home` writes only the machine-global breadcrumb. The gate reads the
    per-pane file, so a "present" test built from the global stamp alone reads as UNATTENDED and
    silently exercises the injection path it meant to prove is refused.
    """
    key = state.terminal_pane_key({"ITERM_SESSION_ID": pane_id})
    assert key is not None
    pane_path = state.per_pane_presence_path(key, home)
    pane_path.parent.mkdir(parents=True, exist_ok=True)
    pane_path.write_text(
        (home / ".aimaestro" / "state" / "user-presence.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _run(
    args: list[str],
    *,
    iterm: str | None,
    present: bool = False,
    project: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    import tempfile

    from conftest import away_home, present_home  # type: ignore[import-not-found]

    env = {"PATH": os.environ.get("PATH", "")}
    # Pin the terminal-kind so these tests exercise the iTerm path deterministically
    # regardless of the host terminal (e.g. running the suite inside tmux). The tmux
    # delegation is covered by test_terminal_trigger.py.
    env["JANITOR_FORCE_TERMINAL_KIND"] = "iterm"
    # Pin USER PRESENCE too, for the same reason: the trigger refuses to type into a pane the user is
    # actively using, and `user_is_present` fails CLOSED. Without a pinned HOME these tests inherit the
    # developer's real breadcrumb and pass or fail depending on whether they were typing.
    tmp = Path(tempfile.mkdtemp())
    home = present_home(tmp) if present else away_home(tmp)
    if present and iterm is not None:
        _stamp_pane_presence(home, iterm)
    env["HOME"] = str(home)
    # Pin the project too when a test asserts on state files — otherwise `state.state_dir()`
    # resolves to the DEVELOPER'S OWN repo and the test would write to its live .janitor/state.
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    if iterm is not None:
        env["ITERM_SESSION_ID"] = iterm
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------- pure helper -----------------------------------------------------

def test_build_osascript_targets_uuid_and_sends_esc_then_reload() -> None:
    mod = _import()
    osa = mod._build_osascript("789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0)
    assert '"789D8299-5AA2-48CF-9325-3BC972B9BEAE"' in osa, "must match the specific session id"
    assert osa.count("character id 27") == 2, "a HARD interrupt sends TWO ESCs (tool + turn)"
    # --force always (user directive 2026-07-10): a mid-use plugin can refuse a
    # plain reload and silently stay on the old cached version.
    assert '"/reload-plugins --force"' in osa, "must send /reload-plugins --force"
    assert '"/compact"' not in osa, "must NOT send /compact (this is the reload trigger)"
    assert "delay 2.0" in osa, "must delay before firing so the parent returns first"


def test_build_osascript_soft_omits_esc() -> None:
    """SOFT: no raw ESC byte — /reload-plugins enqueues instead of interrupting the turn."""
    mod = _import()
    osa = mod._build_osascript("789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0, esc_first=False)
    assert "character id 27" not in osa, "soft mode must NOT send an ESC byte"
    assert '"/reload-plugins --force"' in osa, "must still type /reload-plugins --force"


def test_uuid_regex_accepts_real_rejects_injection() -> None:
    mod = _import()
    assert mod._UUID_RE.match("789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    for bad in (
        'x" then do shell script "touch /tmp/pwned" --',
        'abc"; tell app "Finder"',
        "id with spaces",
        "",
        "../../etc",
    ):
        assert not mod._UUID_RE.match(bad), f"{bad!r} must be rejected"


# ---------- main() via subprocess, ALWAYS --dry-run -----------------------

def test_dry_run_reports_plan_and_does_not_fire() -> None:
    """--dry-run + iTerm set: plan printed, NO osascript fired. Bare invocation is
    SOFT (TRDD-0GPQROC1): no ESC — the reload enqueues at the turn boundary."""
    proc = _run(["--dry-run"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0
    assert "DRY_RUN" in proc.stdout and "789D8299-5AA2-48CF-9325-3BC972B9BEAE" in proc.stdout
    assert "reload-plugins --force" in proc.stdout
    assert "ESC->" not in proc.stdout, "SOFT default must not interrupt the in-flight turn"
    assert "RELOAD_FIRED" not in proc.stdout, "dry-run must not fire"


def test_soft_dry_run_omits_esc_from_plan() -> None:
    """--soft (deprecated no-op alias of the default): NO `ESC->` prefix in the plan."""
    proc = _run(["--dry-run", "--soft"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0
    assert "DRY_RUN" in proc.stdout and "/reload-plugins" in proc.stdout
    assert "ESC->" not in proc.stdout, "soft mode must not interrupt with an ESC"
    assert "RELOAD_FIRED" not in proc.stdout


def test_hard_dry_run_has_esc_prefix() -> None:
    """--hard (opt-in since TRDD-0GPQROC1): the plan leads with `ESC->` (interrupt now)."""
    proc = _run(["--dry-run", "--hard"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0
    assert "ESC->" in proc.stdout, "--hard must restore the ESC-interrupt"
    assert "RELOAD_FIRED" not in proc.stdout


def test_soft_and_hard_are_mutually_exclusive() -> None:
    """--soft --hard together is a usage error (argparse mutually-exclusive group)."""
    proc = _run(
        ["--dry-run", "--soft", "--hard"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE"
    )
    assert proc.returncode != 0, "contradictory modes must be rejected"


def test_no_iterm_reports_noop(tmp_path: Path) -> None:
    """No ITERM_SESSION_ID: prints only NO_ITERM, fires nothing.

    `project=` is REQUIRED even though this test asserts only on stdout: the NO_ITERM path now
    rolls the reload ack back, and an unpinned project resolves `state.state_dir()` to the
    DEVELOPER'S OWN repo — the test would silently zero the live `reload-acked.ts`.
    """
    proc = _run([], iterm=None, project=_proj(tmp_path))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM"
    assert "RELOAD_FIRED" not in proc.stdout


def test_malformed_iterm_id_refuses_to_fire(tmp_path: Path) -> None:
    """An injection-shaped ITERM_SESSION_ID is rejected (NO_ITERM), never fired."""
    proc = _run(
        [],
        iterm='x:" then do shell script "touch /tmp/pwned" --',
        project=_proj(tmp_path),
    )
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "RELOAD_FIRED" not in proc.stdout


# ---------- presence DEFERS; only real non-delivery un-consumes the signal (janitor#257) ----
#
# The owner retired the presence CANCEL (2026-08-02, restated 2026-08-13): the only input is the
# last keystroke, each one pushes the send 8 s ahead, and it never stops trying. So "the user is
# present" is no longer an outcome this script can produce, and the tests that pinned it are gone.
#
# The rollback they exercised is NOT gone — it moved to the outcome that actually means the reload
# did not happen. That distinction is the whole of janitor#257: `[janitor-reload]` is emitted once
# per reload generation and `dispatch` advances its ack at EMISSION time, so ANY non-delivery eats
# the only signal that a reload was needed, and "told the human, who never did it" then looks
# exactly like "reloaded".

_PANE = "w0t0p0:11111111-2222-3333-4444-555555555555"


def _proj(tmp_path: Path) -> Path:
    """A pinned project dir with a janitor state dir — so a rollback never touches the real repo."""
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    return proj


def test_a_present_user_no_longer_cancels_the_reload(tmp_path: Path) -> None:
    """The user AT the keyboard must NOT abort the send — presence defers at the pane, it never
    refuses. `PRESENCE_WAIT_S=0` is the sharp form of the assertion: under the OLD gate a zero
    deferral budget meant an immediate `USER_PRESENT` + return, so if any presence check survived
    anywhere in this path, this test fails."""
    proj = _proj(tmp_path)
    acked = proj / ".janitor" / "state" / "reload-acked.ts"
    acked.write_text("1755000000\n", encoding="utf-8")

    proc = _run(
        ["--dry-run"],
        iterm=_PANE,
        present=True,
        project=proj,
        extra_env={"CLAUDE_PLUGIN_OPTION_PRESENCE_WAIT_S": "0"},
    )

    assert proc.returncode == 0
    assert "USER_PRESENT" not in proc.stdout, proc.stdout + proc.stderr
    assert "DRY_RUN" in proc.stdout, "a present user must reach the send, not be turned away"
    assert acked.read_text().strip() == "1755000000", (
        "nothing was un-delivered, so the ack must stand — rolling it back on a successful send "
        "would re-emit the marker forever"
    )


def test_undeliverable_rolls_the_reload_ack_back(tmp_path: Path) -> None:
    """No automatable terminal ⇒ the reload did NOT happen ⇒ the ack must go back so the next
    heartbeat re-emits. This is the guarantee the retired presence branch used to carry, now
    attached to an outcome that genuinely means non-delivery."""
    proj = _proj(tmp_path)
    acked = proj / ".janitor" / "state" / "reload-acked.ts"
    acked.write_text("1755000000\n", encoding="utf-8")

    proc = _run([], iterm=None, project=proj)

    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM", proc.stdout + proc.stderr
    assert acked.read_text().strip() == "0", (
        "the ack must be rolled back to 0 — ANY current generation then compares as newer and "
        "re-emits; storing the PREVIOUS generation would work only until the daemon bumped it"
    )


def test_undeliverable_does_not_invent_an_ack_file(tmp_path: Path) -> None:
    """No ack on disk means no reload was ever acked — creating one would be the exact bug
    inverted (a fabricated ack that a later comparison could read as 'already handled')."""
    proj = _proj(tmp_path)
    acked = proj / ".janitor" / "state" / "reload-acked.ts"

    proc = _run([], iterm=None, project=proj)

    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM"
    assert not acked.exists(), "the rollback must not CREATE an ack that never existed"
