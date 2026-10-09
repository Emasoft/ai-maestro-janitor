"""R1 (TRDD-JY0OBQZ4): the generated LaunchAgent must not be darwinbg."""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "keepalive_install.sh"


@pytest.mark.real_subprocess("plutil")  # only the optional macOS lint; ProcessType is read portably via plistlib
def test_generated_plist_process_type_is_standard(tmp_path: Path) -> None:
    """Render the plist via the installer into a temp HOME (no launchctl) and check ProcessType."""
    # The sandbox guard only allows running a script that lives in tmp, so run a copy.
    script = tmp_path / "keepalive_install.sh"
    shutil.copy(SCRIPT, script)
    # WHY a `uname` shim: the installer writes the plist only when `uname -s` says Darwin; on the
    # Linux CI runner it writes a systemd unit instead, so no plist existed to read. Forcing Darwin
    # makes the test exercise the plist branch on every platform (nothing is activated).
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    uname = shim_dir / "uname"
    uname.write_text("#!/bin/sh\necho Darwin\n")
    uname.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "KEEPALIVE_SKIP_ACTIVATION": "1", "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}"}
    subprocess.run(["bash", str(script), "install"], env=env, check=True, capture_output=True)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.ai-maestro-janitor.daemon.plist"
    # WHY plistlib: plutil exists only on macOS, so shelling out to it failed on the Linux CI runner;
    # plistlib parses the same file on every platform and yields the same ProcessType fact.
    with plist.open("rb") as fh:
        assert plistlib.load(fh)["ProcessType"] == "Standard"
    if shutil.which("plutil"):
        subprocess.run(["plutil", "-lint", str(plist)], check=True, capture_output=True)


def test_install_over_loaded_job_never_claims_installed_while_unloaded(tmp_path: Path) -> None:
    """TRDD-V13RIZUI: bootout lags, so a naive bootstrap fails; install must end loaded or exit non-zero."""
    script = tmp_path / "keepalive_install.sh"
    shutil.copy(SCRIPT, script)
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    state = tmp_path / "launchd-state"
    state.mkdir()
    (state / "loaded").touch()
    (shim_dir / "uname").write_text("#!/bin/sh\necho Darwin\n")
    # WHY a stateful fake launchctl: after bootout the job still shows in `print` for 3 more polls and
    # `bootstrap` fails (as the real launchd did) until it is gone; `load` always fails.
    (shim_dir / "launchctl").write_text(
        f"""#!/bin/sh
S="{state}"
n=$(cat "$S/pending" 2>/dev/null || echo 0)
case "$1" in
bootout) echo 3 > "$S/pending"; rm -f "$S/loaded"; exit 0 ;;
print) if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$S/pending"; exit 0; fi; [ -e "$S/loaded" ] ;;
bootstrap) if [ "$n" -gt 0 ]; then echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; fi; touch "$S/loaded" ;;
*) exit 1 ;;
esac
"""
    )
    for shim in shim_dir.iterdir():
        shim.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}"}
    env.pop("KEEPALIVE_SKIP_ACTIVATION", None)
    proc = subprocess.run(["bash", str(script), "install"], env=env, capture_output=True, text=True)
    loaded = (state / "loaded").exists()
    assert loaded or proc.returncode != 0, f"claimed install with the job unloaded: {proc.stdout!r}"
    assert not ("installed" in proc.stdout and not loaded)
