"""L0 OS-keepalive orchestrator + installer contract (TRDD-71ABD7V7, Phase 2b/4).

Two things are proven here:

1. The SHIPPED ``keepalive_install.sh`` heredoc resolves the way CPV's #152 persistence
   discriminator requires — its launchd ProgramArguments[0] / systemd ExecStart is the
   literal ``$HOME/.claude/plugins/data/<slug>/scripts/daemon_keepalive_entry.py`` that
   folds to an EXISTING in-tree file, carries the ``--keepalive`` marker, and injects no
   code-loading env. We re-implement the (tiny) #152 fold + heredoc extraction here so the
   test has ZERO CPV dependency; the real CPV --strict check happens at publish.
2. The Python orchestrator stages the verbatim closure + installer and only ever runs
   ``bash keepalive_install.sh <cmd>`` — and crucially carries NO persistence token (the
   exact property that keeps it off CPV's persistence radar, unlike the old version).

A real, side-effect-free install (``KEEPALIVE_SKIP_ACTIVATION``, sandboxed ``$HOME``)
proves the shell actually expands ``$HOME`` into a valid OS-service config file.
"""

from __future__ import annotations

import configparser
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
INSTALLER = SCRIPTS / "keepalive_install.sh"
sys.path.insert(0, str(SCRIPTS / "lib"))

import launchd_keepalive  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    keepalive test can read or write the real ~/.claude/janitor-global-state/ or the real
    plugin DATA dir. A frozen module constant (launchd_keepalive._DATA_DIR, computed from
    Path.home() at import) let these tests resolve the REAL DATA dir and restage the real
    closure, driving a 39 GB fseventsd runaway (TRDD-ZNN0UK5K). JANITOR_DATA_DIR is the
    lever data_dir()/version_update_lib._data_dir() both honor; the DATA path keeps the
    FIXED suffix so data_dir()'s shape assertion still holds on a tmp tree. Per-test
    overrides (setenv JANITOR_DATA_DIR) win over this default."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


_EXPECTED_ENTRY_LITERAL = (
    "$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py"
)

# The #152 fold + heredoc extraction, re-implemented minimally to match the discriminator
# (cpv_persistence_target.py) WITHOUT importing CPV — so this test pins the contract on its
# own. Kept byte-faithful to the live regexes documented in TRDD-71ABD7V7's STATE.
_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(?:'([A-Za-z_]\w*)'|\"([A-Za-z_]\w*)\"|([A-Za-z_]\w*))")
_PLUGIN_DATA_LITERAL_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})/\.claude/plugins/data/[^/]+/(.+)$")


def _extract_heredoc(content: str, marker: str) -> str | None:
    """Body of the FIRST heredoc whose opener line also mentions ``marker`` — the exact
    rule CPV's ``_extract_heredoc_body`` uses to recover an inline plist/unit."""
    lines = content.split("\n")
    for idx, line in enumerate(lines):
        if marker not in line:
            continue
        mo = _HEREDOC_OPEN_RE.search(line)
        if not mo:
            continue
        delim = mo.group(1) or mo.group(2) or mo.group(3)
        body: list[str] = []
        for nxt in lines[idx + 1 :]:
            if nxt.strip() == delim:
                return "\n".join(body)
            body.append(nxt)
        return None
    return None


def _fold_rest(path: str) -> str | None:
    """The ``<rest>`` the #152 fold maps ``$HOME/.claude/plugins/data/<slug>/<rest>`` to
    (under the plugin root R). ``None`` if the literal is not the sandbox shape."""
    mo = _PLUGIN_DATA_LITERAL_RE.match(path)
    return mo.group(1) if mo is not None else None


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


# ── Pure orchestrator helpers ───────────────────────────────────────────────


def test_current_platform_is_macos_on_darwin() -> None:
    """current_platform() maps this host's sys.platform to macos|linux|other."""
    plat = launchd_keepalive.current_platform()
    assert plat in {"macos", "linux", "other"}
    if sys.platform == "darwin":
        assert plat == "macos"


def test_opted_in_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OS keepalive is opt-OUT: default ON when the env knob is unset."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", raising=False)
    assert launchd_keepalive.opted_in() is True


def test_opted_in_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting the knob to a falsey spelling disables the OS keepalive."""
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", val)
        assert launchd_keepalive.opted_in() is False


def test_data_paths_are_the_fixed_data_dir() -> None:
    """The keepalive targets the FIXED plugin DATA dir, never the ephemeral cache root."""
    assert launchd_keepalive.data_dir().as_posix().endswith(
        ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins"
    )
    assert launchd_keepalive.data_scripts_dir() == launchd_keepalive.data_dir() / "scripts"


# ── The #152 discriminator contract (proves the publish gate will pass) ──────


def test_plist_heredoc_program_is_the_inert_entry() -> None:
    """The launchd plist launches the entry .py directly (argv[0]) with --keepalive."""
    body = _extract_heredoc(_installer_text(), ".plist")
    assert body is not None, "no .plist heredoc found in keepalive_install.sh"
    data = plistlib.loads(body.encode("utf-8"))
    pa = data["ProgramArguments"]
    assert pa[0] == _EXPECTED_ENTRY_LITERAL
    assert pa[1] == "--keepalive"


def test_plist_program_folds_to_existing_in_tree_entry() -> None:
    """#152 folds the plist's program path to an EXISTING in-tree file (C1 passes)."""
    body = _extract_heredoc(_installer_text(), ".plist")
    assert body is not None
    program = plistlib.loads(body.encode("utf-8"))["ProgramArguments"][0]
    rest = _fold_rest(program)
    assert rest == "scripts/daemon_keepalive_entry.py"
    assert (REPO / rest).is_file(), "the #152-folded target must be an existing repo file"


def test_systemd_execstart_folds_to_existing_in_tree_entry() -> None:
    """The systemd unit's ExecStart is the same in-tree entry + --keepalive marker."""
    body = _extract_heredoc(_installer_text(), ".service")
    assert body is not None, "no .service heredoc found in keepalive_install.sh"
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read_string(body)
    toks = shlex.split(cp["Service"]["ExecStart"])
    assert toks[1] == "--keepalive"
    rest = _fold_rest(toks[0])
    assert rest == "scripts/daemon_keepalive_entry.py"
    assert (REPO / rest).is_file()


def test_config_injects_no_code_loading_env() -> None:
    """Neither config sets a code-injecting env key (C3) — in fact none at all."""
    text = _installer_text()
    for key in (
        "BASH_ENV", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
        "LD_LIBRARY_PATH", "NODE_OPTIONS", "PYTHONSTARTUP", "PERL5LIB",
    ):
        assert key not in text, f"code-inject env key {key} present in installer"
    assert "EnvironmentVariables" not in (_extract_heredoc(text, ".plist") or "")
    sbody = _extract_heredoc(text, ".service") or ""
    assert "Environment=" not in sbody and "EnvironmentFile=" not in sbody


def test_heredoc_opener_lines_carry_literal_markers() -> None:
    """Each opener line carries the literal .plist/.service so the discriminator finds it."""
    text = _installer_text()
    assert re.search(r"^\s*cat\s*>.*\.plist\".*<<", text, re.M), "plist opener lacks literal .plist"
    assert re.search(r"^\s*cat\s*>.*\.service\".*<<", text, re.M), "service opener lacks literal .service"


def test_orchestrator_py_carries_no_persistence_token() -> None:
    """The Python orchestrator must contain NO persistence verb/path — the property that
    keeps it off CPV's persistence radar (the old programmatic version's fatal flaw)."""
    src = (SCRIPTS / "lib" / "launchd_keepalive.py").read_text(encoding="utf-8").lower()
    for tok in ("launchctl", "systemctl", "launchagents", "launchdaemons", ".plist", ".service", "@reboot", "crontab"):
        assert tok not in src, f"persistence token {tok!r} leaked into launchd_keepalive.py"


# ── Orchestrator staging + delegation (no real OS side effects) ──────────────


def test_install_stages_closure_and_runs_staged_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install() verbatim-stages the entry+daemon+installer into DATA and runs the STAGED
    installer (the real launchctl/systemctl call is stubbed — no OS side effect)."""
    data = tmp_path / "data"
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    ok, _ = launchd_keepalive.install(SCRIPTS)
    assert ok
    staged = data / "scripts"
    assert (staged / "daemon_keepalive_entry.py").is_file()
    assert (staged / "daemon.py").is_file()
    assert (staged / "keepalive_install.sh").is_file()
    # the staged entry is byte-identical to the shipped one (verbatim-copy invariant)
    assert (staged / "daemon_keepalive_entry.py").read_bytes() == (
        SCRIPTS / "daemon_keepalive_entry.py"
    ).read_bytes()
    assert calls == [["bash", str(staged / "keepalive_install.sh"), "install"]]


def test_install_on_unsupported_platform_stages_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a platform with no OS keepalive, install() fails fast and stages nothing."""
    data = tmp_path / "data"
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setattr(launchd_keepalive, "current_platform", lambda: "other")
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    ok, msg = launchd_keepalive.install(SCRIPTS)
    assert ok is False and "no OS keepalive" in msg
    assert not (data / "scripts").exists()
    assert calls == []


def test_uninstall_without_staged_installer_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uninstalling when nothing was ever installed is a success no-op (never raises)."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    ok, msg = launchd_keepalive.uninstall()
    assert ok is True and "nothing to remove" in msg
    assert calls == []


def test_uninstall_runs_staged_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uninstall delegates to the STAGED installer (so the DATA-run daemon can self-remove)."""
    data = tmp_path / "data"
    scripts = data / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "keepalive_install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    ok, _ = launchd_keepalive.uninstall()
    assert ok
    assert calls == [["bash", str(scripts / "keepalive_install.sh"), "uninstall"]]


def test_is_installed_delegates_to_installer_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_installed() reports the staged installer's `status` rc (names no service path)."""
    data = tmp_path / "data"
    scripts = data / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "keepalive_install.sh").write_text("x", encoding="utf-8")
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(
        launchd_keepalive, "_run", lambda cmd: (seen.__setitem__("cmd", cmd) or (True, "installed"))
    )
    assert launchd_keepalive.is_installed() is True
    assert seen["cmd"] == ["bash", str(scripts / "keepalive_install.sh"), "status"]


def test_is_installed_false_without_staged_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no staged installer, is_installed() is False without shelling out."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))
    assert launchd_keepalive.is_installed() is False


# ── Real shell expansion (sandboxed $HOME, activation skipped) ───────────────


@pytest.mark.real_subprocess("bash")
def test_real_install_writes_expanded_config_without_activation(tmp_path: Path) -> None:
    """Running the installer for real (sandboxed HOME, KEEPALIVE_SKIP_ACTIVATION) writes a
    valid OS-service config whose $HOME is fully expanded — and touches no real OS service.

    Marked `real_subprocess("bash")` because the process sandbox denies real shell scripts by
    default: a shell is the ONE child the sandbox cannot follow into (`sitecustomize` reaches
    every child PYTHON, but this installer's own `launchctl`/`systemctl` calls are its
    children, not ours, and would be invisible). The safety here does not come from the
    sandbox — it comes from `KEEPALIVE_SKIP_ACTIVATION=1`, which is the line that stops the
    installer before it registers anything with the real OS. The marker exists so that fact is
    stated out loud and re-checked in review, instead of being an unexamined default.
    """
    plat = launchd_keepalive.current_platform()
    if plat == "other":
        pytest.skip(f"no OS keepalive on {sys.platform}")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "KEEPALIVE_SKIP_ACTIVATION": "1"}
    env.pop("XDG_CONFIG_HOME", None)  # so linux resolves the unit under fake_home/.config
    proc = subprocess.run(
        ["bash", str(INSTALLER), "install"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    expected_entry = str(
        fake_home / ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py"
    )
    # D-α: the WRITTEN config now carries a baked ABSOLUTE interpreter (the test host has
    # uv + python3, so one always resolves), with the FIXED entry as the launched SCRIPT and
    # --keepalive last. (The SCANNED heredoc still keeps the entry as program[0] — that
    # CPV-#152 contract is pinned by the test_*_folds_to_existing_in_tree_entry tests; this
    # test asserts the RUNTIME file, which is what launchd/systemd actually exec.)
    if plat == "macos":
        cfg = fake_home / "Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist"
        assert cfg.is_file()
        data = plistlib.loads(cfg.read_bytes())
        pa = data["ProgramArguments"]
        # An absolute interpreter was prepended → program[0] is NOT the entry, the entry is
        # present as a later element, and --keepalive is last. $HOME is fully expanded.
        assert pa[0] != expected_entry, "expected a baked interpreter before the entry"
        assert pa[0].startswith("/"), f"interpreter must be an absolute path: {pa[0]!r}"
        assert expected_entry in pa, f"entry missing from ProgramArguments: {pa!r}"
        assert pa[-1] == "--keepalive"
        assert pa.index(expected_entry) == len(pa) - 2  # entry immediately before --keepalive
        assert not any("$" in tok for tok in pa)  # $HOME fully expanded everywhere
    else:  # linux
        cfg = fake_home / ".config/systemd/user/com.ai-maestro-janitor.daemon.service"
        assert cfg.is_file()
        text = cfg.read_text(encoding="utf-8")
        exec_line = next(ln for ln in text.splitlines() if ln.startswith("ExecStart="))
        toks = shlex.split(exec_line[len("ExecStart=") :])
        assert toks[0].startswith("/") and toks[0] != expected_entry, (
            f"expected a baked absolute interpreter before the entry: {exec_line!r}"
        )
        assert expected_entry in toks, f"entry missing from ExecStart: {exec_line!r}"
        assert toks[-1] == "--keepalive"
        assert toks.index(expected_entry) == len(toks) - 2
        assert "$HOME" not in text


def _service_manager_pathdir(tmp_path: Path, *, name: str, loaded: bool) -> Path:
    """A curated PATH dir whose `launchctl`/`systemctl` is a scripted stand-in that
    answers "job loaded" (exit 0) or "job absent" (exit 1).

    WHY a fake and not the host's real service manager: the launchd/systemd job
    LABEL is a machine-global identifier (`gui/<uid>/com.ai-maestro-janitor.daemon`),
    and `$HOME` does not redirect it. A fake HOME moves the plist FILE only, so on a
    host where the janitor's own keepalive is genuinely loaded — the developer's
    machine, and every machine this feature actually runs on — `status` would report
    installed no matter what this test wrote, and the assertion would fail on correct
    code. Scripting the service manager makes the test depend on nothing but itself.
    """
    d = tmp_path / f"sm-{'loaded' if loaded else 'unloaded'}"
    d.mkdir()
    for tool in ("uname", "id", "mkdir", "cat", "awk", "mv", "rm"):
        real = shutil.which(tool)
        assert real is not None, f"host is missing {tool}"
        (d / tool).symlink_to(real)
    fake = d / name
    fake.write_text(f"#!/bin/sh\nexit {0 if loaded else 1}\n", encoding="utf-8")
    fake.chmod(0o755)
    return d


@pytest.mark.real_subprocess("bash")
def test_status_reports_unloaded_job_as_not_installed(tmp_path: Path) -> None:
    """janitor#217: the plist/unit FILE existing on disk must not be enough for
    `status` to report healthy — the job must actually be LOADED with the service
    manager. `install` here uses KEEPALIVE_SKIP_ACTIVATION=1 (never registers
    with real launchd/systemd), so the definition file is written but the job is
    never loaded — exactly the state a `launchctl bootout` leaves behind.

    Both directions are asserted against a SCRIPTED service manager. Asserting only
    the not-loaded direction would also pass for a `status` that always failed; the
    pair pins the actual contract, "status reports what the service manager says".
    A regression to the old `[ -f "$PLIST" ]` check fails the first assertion, since
    install wrote the definition file either way.
    """
    plat = launchd_keepalive.current_platform()
    if plat == "other":
        pytest.skip(f"no OS keepalive on {sys.platform}")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "KEEPALIVE_SKIP_ACTIVATION": "1"}
    env.pop("XDG_CONFIG_HOME", None)
    install = subprocess.run(
        ["bash", str(INSTALLER), "install"], env=env, capture_output=True, text=True, timeout=30,
    )
    assert install.returncode == 0, install.stderr
    # The definition file IS on disk (install wrote it) ...
    if plat == "macos":
        cfg = fake_home / "Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist"
    else:
        cfg = fake_home / ".config/systemd/user/com.ai-maestro-janitor.daemon.service"
    assert cfg.is_file(), "install must still write the definition file"
    # ... but whether `status` calls it installed must come from the SERVICE MANAGER,
    # never from that file. Drive both answers with a scripted stand-in.
    bash = shutil.which("bash")
    assert bash is not None
    sm = "launchctl" if plat == "macos" else "systemctl"

    def _status(*, loaded: bool) -> subprocess.CompletedProcess[str]:
        pathdir = _service_manager_pathdir(tmp_path, name=sm, loaded=loaded)
        return subprocess.run(
            [bash, str(INSTALLER), "status"],
            env={**env, "PATH": str(pathdir)},
            capture_output=True, text=True, timeout=30,
        )

    unloaded = _status(loaded=False)
    assert unloaded.returncode != 0, (
        f"status must report NOT installed when the job isn't loaded, even with "
        f"the definition file present (stdout={unloaded.stdout!r})"
    )
    live = _status(loaded=True)
    assert live.returncode == 0, (
        f"status must report installed when the service manager holds the job "
        f"(stdout={live.stdout!r}, stderr={live.stderr!r})"
    )


# ── Interpreter resolution both ways (TRDD-DB1P25S4) ─────────────────────────
# TCC persists an Automation grant only against a STABLE binary identity, so the
# baked interpreter must be uv's MANAGED CPython when one resolves; the `uv run`
# shim (an ephemeral per-spawn binary no grant can stick to) is the LAST resort.
# Hermetic: a curated PATH (no python*) + a scripted fake `uv` control the outcome.


def _fakebin(tmp_path: Path, uv_body: str) -> Path:
    """A curated PATH dir holding ONLY the tools the installer needs plus a scripted
    fake `uv` — and crucially NO python*, so interpreter resolution is fully
    test-controlled instead of depending on the host."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for tool in ("uname", "mkdir", "cat", "awk", "mv", "rm"):
        real = shutil.which(tool)
        assert real is not None, f"host is missing {tool}"
        (fakebin / tool).symlink_to(real)
    uv = fakebin / "uv"
    uv.write_text(uv_body, encoding="utf-8")
    uv.chmod(0o755)
    return fakebin


def _run_installer_with_path(fake_home: Path, fakebin: Path) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": str(fakebin),
        "KEEPALIVE_SKIP_ACTIVATION": "1",
    }
    env.pop("XDG_CONFIG_HOME", None)
    proc = subprocess.run(
        [bash, str(INSTALLER), "install"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def _baked_interpreter_tokens(fake_home: Path, plat: str) -> list[str]:
    """The interpreter argv the WRITTEN runtime config carries BEFORE the entry token."""
    entry = str(
        fake_home
        / ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py"
    )
    if plat == "macos":
        cfg = fake_home / "Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist"
        toks = list(plistlib.loads(cfg.read_bytes())["ProgramArguments"])
    else:
        cfg = fake_home / ".config/systemd/user/com.ai-maestro-janitor.daemon.service"
        text = cfg.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.startswith("ExecStart="))
        toks = shlex.split(line[len("ExecStart=") :])
    assert entry in toks, f"entry missing from baked config: {toks!r}"
    return toks[: toks.index(entry)]


@pytest.mark.real_subprocess("bash")
def test_config_bakes_managed_python_first(tmp_path: Path) -> None:
    """Rendering, way 1: `uv python find --system --managed-python <pin>` resolves → THAT
    absolute path (the stable, TCC-grantable identity) is the whole baked interpreter —
    never the `uv run` shim. The find must carry both flags: `--system` is load-bearing
    (without it a project's .venv wins), `--managed-python` pins the stable install."""
    plat = launchd_keepalive.current_platform()
    if plat == "other":
        pytest.skip(f"no OS keepalive on {sys.platform}")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    managed = tmp_path / "managed" / "python3.12"
    managed.parent.mkdir()
    managed.write_text("#!/bin/sh\n", encoding="utf-8")
    managed.chmod(0o755)
    arglog = tmp_path / "uv-args.log"
    uv_body = (
        "#!/bin/bash\n"
        f"echo \"$@\" >> '{arglog}'\n"
        'if [ "$1" = python ] && [ "$2" = find ]; then\n'
        f"  echo '{managed}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    fakebin = _fakebin(tmp_path, uv_body)
    _run_installer_with_path(fake_home, fakebin)
    assert _baked_interpreter_tokens(fake_home, plat) == [str(managed)]
    logged = arglog.read_text(encoding="utf-8")
    assert "--system" in logged and "--managed-python" in logged


@pytest.mark.real_subprocess("bash")
def test_config_falls_back_to_uv_run_without_any_stable_python(tmp_path: Path) -> None:
    """Rendering, way 2: no managed CPython and no python3 anywhere on PATH → the
    `uv run --script` shim is baked as the LAST resort (an ungrantable identity, but a
    running daemon beats none)."""
    plat = launchd_keepalive.current_platform()
    if plat == "other":
        pytest.skip(f"no OS keepalive on {sys.platform}")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    uv_body = (
        "#!/bin/bash\n"
        'if [ "$1" = python ] && [ "$2" = find ]; then\n'
        "  exit 1\n"  # no managed python on this host
        "fi\n"
        "exit 1\n"
    )
    fakebin = _fakebin(tmp_path, uv_body)
    _run_installer_with_path(fake_home, fakebin)
    assert _baked_interpreter_tokens(fake_home, plat) == [
        str(fakebin / "uv"), "run", "--script",
    ]


# ── Currency: cache resolution + restage/activate split + self-heal predicate ─


def test_latest_cache_scripts_dir_picks_newest_complete_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """latest_cache_scripts_dir() returns the newest version that actually has BOTH the
    entry and daemon — a numerically-newer but incomplete version is ignored."""
    cache = tmp_path / "cache"
    for ver in ("0.9.0", "0.17.3", "0.18.0", "0.8.0"):
        s = cache / ver / "scripts"
        s.mkdir(parents=True)
        (s / "daemon.py").write_text("x", encoding="utf-8")
        (s / "daemon_keepalive_entry.py").write_text("y", encoding="utf-8")
    incomplete = cache / "0.19.0" / "scripts"  # newer number but NO entry → must be skipped
    incomplete.mkdir(parents=True)
    (incomplete / "daemon.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(launchd_keepalive, "_CACHE_PARENT", cache)
    assert launchd_keepalive.latest_cache_scripts_dir() == cache / "0.18.0" / "scripts"


def test_latest_cache_scripts_dir_none_without_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No cache dir (e.g. an inline/dev install) → None (caller falls back to its own dir)."""
    monkeypatch.setattr(launchd_keepalive, "_CACHE_PARENT", tmp_path / "absent")
    assert launchd_keepalive.latest_cache_scripts_dir() is None


# ── KEEPQRTN Part A: quarantine-aware version selection (mirrors the stub's C3 walk) ──


def _complete_cache(parent: Path, versions: tuple[str, ...]) -> None:
    """Build a cache-parent tree where every version carries the entry + daemon (so all
    are 'complete' keepalive candidates) — the keepalive's selection input."""
    for ver in versions:
        s = parent / ver / "scripts"
        s.mkdir(parents=True)
        (s / "daemon.py").write_text("x", encoding="utf-8")
        (s / "daemon_keepalive_entry.py").write_text("y", encoding="utf-8")


def test_latest_cache_scripts_dir_skips_quarantined_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KEEPQRTN HIGH-1/MEDIUM-1: when the NEWEST cached version is C3-quarantined, the
    keepalive selects the newest NON-quarantined version instead — mirroring the
    dispatcher-stub's C3 skip so launchd restages the GOOD older version, not the bad N."""
    cache = tmp_path / "cache"
    _complete_cache(cache, ("0.20.1", "0.21.0", "0.22.0"))
    data = tmp_path / "data"
    data.mkdir()
    # Real quarantine round-trip (no mock): write the proven-bad newest via version_update_lib,
    # which read_quarantine reads back through the same JANITOR_DATA_DIR.
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setattr(launchd_keepalive, "_CACHE_PARENT", cache)
    assert launchd_keepalive.version_update_lib.add_quarantine("0.22.0", "crash-loop")
    assert launchd_keepalive.latest_cache_scripts_dir() == cache / "0.21.0" / "scripts"


def test_latest_cache_scripts_dir_all_quarantined_picks_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KEEPQRTN fail-open cardinal rule: when EVERY cached version is quarantined, the
    keepalive still selects the NEWEST (a running daemon beats none — the stub's rule). It
    never returns None on account of quarantine."""
    cache = tmp_path / "cache"
    _complete_cache(cache, ("0.20.1", "0.21.0", "0.22.0"))
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setattr(launchd_keepalive, "_CACHE_PARENT", cache)
    for ver in ("0.20.1", "0.21.0", "0.22.0"):
        assert launchd_keepalive.version_update_lib.add_quarantine(ver, "all-bad")
    assert launchd_keepalive.latest_cache_scripts_dir() == cache / "0.22.0" / "scripts"


def test_latest_cache_scripts_dir_quarantine_raises_picks_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KEEPQRTN fail-open: a raising/unreadable quarantine reads as EMPTY → select the
    newest (never worse than today). The keepalive's own `except` backstop catches even an
    unexpected error from read_quarantine, so a quarantine fault can never starve the OS
    keepalive of a version to launch."""
    cache = tmp_path / "cache"
    _complete_cache(cache, ("0.20.1", "0.21.0", "0.22.0"))
    monkeypatch.setattr(launchd_keepalive, "_CACHE_PARENT", cache)

    def _boom() -> set[str]:
        raise RuntimeError("simulated quarantine read failure")

    monkeypatch.setattr(launchd_keepalive.version_update_lib, "read_quarantine", _boom)
    assert launchd_keepalive.latest_cache_scripts_dir() == cache / "0.22.0" / "scripts"


def test_staged_is_current_true_when_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """staged_is_current() is True iff the staged daemon.py byte-matches the source's."""
    data = tmp_path / "data"
    (data / "scripts").mkdir(parents=True)
    src = tmp_path / "src"
    src.mkdir()
    (data / "scripts" / "daemon.py").write_text("SAME", encoding="utf-8")
    (src / "daemon.py").write_text("SAME", encoding="utf-8")
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    assert launchd_keepalive.staged_is_current(src) is True


def test_staged_is_current_false_when_differs_or_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A content difference (a newer version) OR a missing staged file → not current."""
    data = tmp_path / "data"
    (data / "scripts").mkdir(parents=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "daemon.py").write_text("NEW", encoding="utf-8")
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    assert launchd_keepalive.staged_is_current(src) is False  # staged daemon.py missing
    (data / "scripts" / "daemon.py").write_text("OLD", encoding="utf-8")
    assert launchd_keepalive.staged_is_current(src) is False  # content differs


def test_staged_is_current_false_when_closure_lib_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale CLOSURE lib file (with a byte-current daemon.py) → NOT current, so the OS
    daemon restages rather than running a fresh daemon.py against stale libs. The old
    daemon.py-only check reported this as "current" (TRDD-K3WQ7XM9 bug #2, wrong file set)."""
    data = tmp_path / "data"
    (data / "scripts" / "lib").mkdir(parents=True)
    src = tmp_path / "src"
    (src / "lib").mkdir(parents=True)
    # daemon.py imports a sibling lib module → the closure includes lib/foo.py.
    (src / "daemon.py").write_text("import foo\n", encoding="utf-8")
    (src / "lib" / "foo.py").write_text("VERSION = 2\n", encoding="utf-8")
    (data / "scripts" / "daemon.py").write_text("import foo\n", encoding="utf-8")  # daemon.py matches
    (data / "scripts" / "lib" / "foo.py").write_text("VERSION = 1\n", encoding="utf-8")  # but foo.py is STALE
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    assert launchd_keepalive.staged_is_current(src) is False
    (data / "scripts" / "lib" / "foo.py").write_text("VERSION = 2\n", encoding="utf-8")  # now fresh
    assert launchd_keepalive.staged_is_current(src) is True


def test_restage_stages_without_ever_activating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """restage() refreshes the DATA closure + installer but NEVER runs the installer — the
    property that lets the launchd daemon refresh itself on startup without self-bootout."""
    data = tmp_path / "data"
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    launchd_keepalive.restage(SCRIPTS)
    assert (data / "scripts" / "daemon_keepalive_entry.py").is_file()
    assert (data / "scripts" / "keepalive_install.sh").is_file()
    assert calls == [], "restage must never activate the OS service"


def test_activate_runs_staged_installer_or_reports_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """activate() runs the staged installer's `install`; with none staged it fails cleanly."""
    data = tmp_path / "data"
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    ok, msg = launchd_keepalive.activate()
    assert ok is False and "no staged installer" in msg
    (data / "scripts").mkdir(parents=True)
    (data / "scripts" / "keepalive_install.sh").write_text("x", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(launchd_keepalive, "_run", lambda cmd: (calls.append(cmd) or (True, "")))
    ok, _ = launchd_keepalive.activate()
    assert ok
    assert calls == [["bash", str(data / "scripts" / "keepalive_install.sh"), "install"]]
