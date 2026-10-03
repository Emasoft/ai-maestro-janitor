"""R1 (TRDD-JY0OBQZ4): the generated LaunchAgent must not be darwinbg."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "keepalive_install.sh"


@pytest.mark.real_subprocess("plutil")  # read-only plist parser; the task requires the real one
def test_generated_plist_process_type_is_standard(tmp_path: Path) -> None:
    """Render the plist via the installer into a temp HOME (no launchctl) and check ProcessType."""
    # The sandbox guard only allows running a script that lives in tmp, so run a copy.
    script = tmp_path / "keepalive_install.sh"
    shutil.copy(SCRIPT, script)
    env = {**os.environ, "HOME": str(tmp_path), "KEEPALIVE_SKIP_ACTIVATION": "1"}
    subprocess.run(["bash", str(script), "install"], env=env, check=True, capture_output=True)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.ai-maestro-janitor.daemon.plist"
    out = subprocess.run(
        ["plutil", "-extract", "ProcessType", "raw", str(plist)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "Standard"
