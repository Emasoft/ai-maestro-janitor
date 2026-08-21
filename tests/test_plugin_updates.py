"""Tests for the plugin-updates detector's enabled-gate (#34).

`claude plugin list --json` keeps listing a plugin — with its install scope and
projectPath — even after it is DISABLED in that project (`enabled: false`). The
detector used to treat such an entry as an auto-update candidate, run
`claude plugin update <id> --scope <scope>` on it (which has nothing to update),
mis-classify the output as an "unexpected output" failure, and nag every
heartbeat. The fix skips any entry not explicitly `enabled: true` at the
candidate stage — so a disabled plugin never triggers a marketplace refresh,
an update call, or a nag.

Real I/O, no mocks: a stub `claude` on PATH returns a parameterized plugin
list and logs every invocation, so the test asserts on the actual call trace.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "plugin-updates.py"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import state  # noqa: E402  # for the shared subprocess-timeout scale (TRDD-7NSRD8OV)

_CLAUDE_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ.get("CLAUDE_STUB_LOG", "")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(a) + "\\n")
if a[:3] == ["plugin", "list", "--json"]:
    sys.stdout.write(os.environ.get("CLAUDE_STUB_LIST", "[]"))
    raise SystemExit(0)
if a[:3] == ["plugin", "marketplace", "update"]:
    sys.stdout.write("Updated 1 marketplace.\\n")
    raise SystemExit(0)
if a[:2] == ["plugin", "update"]:
    sys.stdout.write("weird unexpected output\\n")  # the shape that nagged
    raise SystemExit(0)
raise SystemExit(0)
'''


def _run(project: Path, plugin_list: list) -> tuple[str, list[str]]:
    """Run the detector with a stub claude; return (stdout, stub-call-lines)."""
    bin_dir = project / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(_CLAUDE_STUB, encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    stub_log = project / "claude.log"

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "sess"
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["CLAUDE_STUB_LOG"] = str(stub_log)
    env["CLAUDE_STUB_LIST"] = json.dumps(plugin_list)
    # Isolate the marketplace cross-process lock so the refresh is acquirable
    # and never touches the real global-state dir.
    env["JANITOR_GLOBAL_STATE_DIR"] = str(project / "gstate")
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env,
        # The TEST'S OWN ceiling, scaled by the shared knob (TRDD-7NSRD8OV, category D). The
        # child DOES inherit the knob (`dict(os.environ)` above), so the detector's own
        # `run_subprocess` calls were already covered — this 60 s was the last uncovered
        # category-D site on the card. Safe to stretch: this test's subject is whether an
        # enabled plugin becomes a CANDIDATE (asserted against the stub's call log), never how
        # fast the detector reaches that verdict.
        timeout=60 * state.timeout_scale(),
    )
    calls = stub_log.read_text(encoding="utf-8").splitlines() if stub_log.is_file() else []
    return res.stdout, calls


class TestPluginUpdatesEnabledGate(unittest.TestCase):
    def test_disabled_plugin_is_not_a_candidate(self):
        """A disabled local plugin triggers no refresh, no update, no nag (#34)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, calls = _run(root, [
                {"id": "foo@mp", "scope": "local", "projectPath": str(root),
                 "enabled": False, "version": "1.0.0"},
            ])
            self.assertNotIn("[plugin-updates]", out)
            self.assertFalse(
                any("marketplace update" in c for c in calls),
                f"disabled plugin must not trigger a marketplace refresh; calls={calls}",
            )
            self.assertFalse(
                any(c.startswith("plugin update") for c in calls),
                f"disabled plugin must not be update-attempted; calls={calls}",
            )

    def test_enabled_plugin_is_a_candidate(self):
        """An enabled local plugin for this project IS treated as a candidate."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _out, calls = _run(root, [
                {"id": "foo@mp", "scope": "local", "projectPath": str(root),
                 "enabled": True, "version": "1.0.0"},
            ])
            # Becoming a candidate triggers a marketplace refresh for its mp.
            self.assertTrue(
                any("plugin marketplace update mp" in c for c in calls),
                f"enabled plugin should trigger a refresh of its marketplace; calls={calls}",
            )


if __name__ == "__main__":
    unittest.main()
