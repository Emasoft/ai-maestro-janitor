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
