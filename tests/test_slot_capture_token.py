"""Branch semantics of the setup-token validator.

Every defect in this validator's five-round history was a MISCLASSIFIED HTTP CODE, not a
crash: a 429 read as proof of life (so a wrong User-Agent filed every key unvalidated), a 403
read as death, a 200-with-unparseable-body read as proof. Types and linters pass on all of
them. These assertions are the only thing that can fail when a code changes meaning.
"""
from __future__ import annotations

import email.message
import io
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_ROT = Path(__file__).resolve().parent.parent / "scripts" / "oauth_rotator"
sys.path.insert(0, str(_ROT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import import_oauth_tokens as imp  # type: ignore[import-not-found]  # noqa: E402
import slot_capture_token as sct  # type: ignore[import-not-found]  # noqa: E402


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def _opener(*, code: int = 200, body: bytes = b"{}", exc: BaseException | None = None):
    """Build a fake urlopen returning `code`/`body`, or raising `exc`."""
    def _open(req, timeout=None, context=None):  # noqa: ANN001, ARG001
        if exc is not None:
            raise exc
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "err",
                                         email.message.Message(), io.BytesIO(body))
        return _Resp(body)
    return _open


@pytest.fixture
def fake(monkeypatch):
    """Patch urlopen for one test; yields a setter taking the same kwargs as `_opener`."""
    def _set(**kw):
        monkeypatch.setattr(urllib.request, "urlopen", _opener(**kw))
    return _set


@pytest.mark.parametrize(("code", "want"), [
    (200, "ok"),           # the only proof of life: authentication was required to get it
    (401, "bad"),          # authentication_error — the credential is dead
    (403, "bad"),          # permission refusal — unusable as a slot whatever the cause
    (429, "unverified"),   # a rate limiter answered; the credential was never established
    (500, "unverified"),   # server fault, not a refusal
    (502, "unverified"),
])
def test_inference_status_classifies_http_codes(fake, code, want):
    """count_tokens: 200 proves life, 401/403 refuse, 429 and 5xx prove nothing."""
    fake(code=code)
    assert sct._inference_status("tok")[0] == want


def test_inference_status_survives_a_reset_connection(fake):
    """A mid-stream ConnectionResetError is unverified, never a refusal."""
    fake(exc=ConnectionResetError("peer reset"))
    assert sct._inference_status("tok")[0] == "unverified"


def test_inference_status_403_quotes_the_server_not_a_guess(fake):
    """The 403 message carries the server's own words rather than an invented cause."""
    fake(code=403, body=b'{"error":{"message":"scope thing"}}')
    detail = sct._inference_status("tok")[1]
    assert "scope thing" in detail
    assert sct._MODEL in detail, "the model must be named — a 403 may be about it, not the key"


def test_account_status_200_is_ok_even_with_unknown_quota_fields(fake):
    """A /usage 200 whose JSON lacks the quota shape is ok, via the None path, not an except.

    Asserting the DETAIL matters: an earlier version asserted only the state, which passes
    whichever path runs, and it was written to cover an except clause that could never fire
    (`rotator._util` type-checks every level and returns None). The clause is gone; this
    pins the behaviour to the branch that actually exists.
    """
    fake(body=b'{"totally":"different"}')
    assert sct.account_status("tok") == ("ok", "usage 200")


def test_account_status_200_with_unparseable_body_is_unverified(fake):
    """An unparseable 200 may be an intercepting proxy's, so it proves nothing."""
    fake(body=b"<html>challenge</html>")
    assert sct.account_status("tok")[0] == "unverified"


def test_account_status_401_is_the_only_locally_decided_refusal(fake):
    """/usage 401 is decided here; every other refusal goes through the inference probe."""
    fake(code=401)
    assert sct.account_status("tok")[0] == "bad"


@pytest.mark.parametrize("code", [403, 429, 500])
def test_account_status_delegates_instead_of_trusting_usage(monkeypatch, fake, code):
    """/usage 403, 429 and 5xx all defer to count_tokens rather than deciding alone.

    The 429 row is the regression guard that matters: it returned "ok" until 2026-09-09, so
    any User-Agent drawing a throttle here filed every key having verified nothing.
    """
    fake(code=code)
    called: list[str] = []
    monkeypatch.setattr(sct, "_inference_status",
                        lambda t: (called.append(t), ("ok", "delegated"))[1])
    assert sct.account_status("tok") == ("ok", "delegated")
    assert called == ["tok"]


def test_account_status_network_error_never_leaks_the_exception_repr(monkeypatch, fake):
    """A /usage outage reports the exception TYPE only — a repr can carry proxy credentials."""
    fake(exc=OSError("tunnel to http://user:hunter2@proxy.internal:8080 failed"))
    monkeypatch.setattr(sct, "_inference_status", lambda t: ("ok", "inference ok"))
    state, detail = sct.account_status("tok")
    assert state == "ok"
    assert "hunter2" not in detail and "proxy.internal" not in detail
    assert "OSError" in detail


def test_ua_never_raises_and_normalises_empty_to_none(monkeypatch):
    """A failing or empty User-Agent lookup yields None, never "" and never an exception.

    The empty-string case is the one that matters: a guard written as `is None` beside a
    sibling written as truthiness lets "" through the gap between them.
    """
    saved = list(sct._UA_CACHE)
    try:
        for raiser in (True, False):
            sct._UA_CACHE.clear()
            if raiser:
                def _boom() -> str:
                    raise RuntimeError("no binary")
                monkeypatch.setattr(sct.usage_probe, "user_agent", _boom)
            else:
                monkeypatch.setattr(sct.usage_probe, "user_agent", lambda: "")
            assert sct._ua() is None
            assert "User-Agent" not in sct._hdrs({})
    finally:
        # Restore, or the next test triggers a real user_agent() lookup through an empty cache.
        sct._UA_CACHE.clear()
        sct._UA_CACHE.extend(saved)


def test_setup_token_blob_carries_no_refresh_token():
    """A setup-token slot has refreshToken None by construction — never assert one exists."""
    blob = sct.setup_token_blob("sk-ant-oat01-example")
    assert blob["claudeAiOauth"]["refreshToken"] is None
    assert blob["claudeAiOauth"]["expiresAt"] > 0


def test_import_reports_every_row_it_drops(tmp_path, capsys):
    """A malformed CSV line is announced with its line number, never silently skipped."""
    csv = tmp_path / "keys.csv"
    csv.write_text("email,token\nnot-an-email,%s\nc@d.com,short\ne@f.com,%s\n"
                   % ("x" * 40, "y" * 40), encoding="utf-8")
    rows = imp.read_rows(csv)
    out = capsys.readouterr().out
    assert rows == [("e@f.com", "y" * 40)]
    # Assert per line, not on a total: a count breaks the moment a second diagnostic per row
    # is added, which would look like a regression in the wrong place.
    for line_no in (1, 2, 3):
        assert "IGNORED line %d" % line_no in out


def test_import_never_prints_a_token(tmp_path, capsys):
    """No parse path may echo field 2 — it is the secret."""
    secret = "z" * 40
    csv = tmp_path / "keys.csv"
    csv.write_text("bad-line-no-comma\na@b.com,%s\n" % secret, encoding="utf-8")
    imp.read_rows(csv)
    assert secret not in capsys.readouterr().out


# --------------------------------------------------------------------------
# import_oauth_tokens.main() — the switch decision table.
#
# This is the riskiest logic in the feature: it writes the keychain and installs the
# credential a running session authenticates with. Everything below stubs the three
# side-effecting calls (file_slot, load_state, subprocess.run) so the DECISION is what is
# under test, never the writes.
# --------------------------------------------------------------------------
TOK_A, TOK_B = "a" * 40, "b" * 40


def _fp(tok: str) -> str:
    from rotator import fingerprint  # type: ignore[import-not-found]
    return fingerprint({"claudeAiOauth": {"accessToken": tok}})


@pytest.fixture
def run_import(tmp_path, monkeypatch):
    """Run main() against a temp CSV with every side effect stubbed; report what it decided."""
    def _run(csv_text: str, *, state: dict, statuses: dict[str, str],
             live_expired: bool = False, file_ok: bool = True):
        csv = tmp_path / "keys.csv"
        csv.write_text(csv_text, encoding="utf-8")
        csv.chmod(0o600)
        switched: list[str] = []
        filed: list[str] = []

        monkeypatch.setattr(sys, "argv", ["import_oauth_tokens.py", "--csv", str(csv)])
        # main()'s FIRST action reads gs.global_state_dir() for the ai-maestro server lock.
        # Without this stub these tests read the REAL machine-wide state dir and fail whenever
        # a live rotation tick holds it — a pass that depends on the host. A subdir, not
        # tmp_path itself, so the state dir is never aliased to the dir holding keys.csv.
        #
        # This hard-wires the lock-not-held path, so do NOT add a main()-level lock test on
        # top of it: with no lock the run proceeds, files nothing, and returns 1 — the SAME
        # code the refusal returns, so `rc == 1` would pass for the wrong reason. The six
        # server_tick_holder() tests below cover the lock directly, which is the right level;
        # if a main()-level one is ever really needed, assert on the stdout line, never on rc.
        monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path / "state")
        monkeypatch.setattr(imp.rotator, "load_state", lambda: dict(state))
        monkeypatch.setattr(imp.sct, "account_status",
                            lambda t: (statuses.get(t, "ok"), "stub"))
        monkeypatch.setattr(imp, "_live_credential_is_dead", lambda: live_expired)

        def _file_slot(email, blob, **kw):  # noqa: ANN001, ARG001
            if file_ok:
                filed.append(email)
            return file_ok
        monkeypatch.setattr(imp.rotator, "file_slot", _file_slot)

        class _CP:
            returncode = 0

        def _run_proc(cmd, **kw):  # noqa: ANN001, ARG001
            switched.append(cmd[-1])
            return _CP()
        monkeypatch.setattr(imp.subprocess, "run", _run_proc)

        rc = imp.main()
        return rc, filed, switched
    return _run


def test_import_refuses_a_file_with_two_identical_tokens(run_import, capsys):
    """The same token on two lines means one account was minted twice — file nothing."""
    rc, filed, switched = run_import(
        "a@x.com,%s\nb@x.com,%s\n" % (TOK_A, TOK_A), state={}, statuses={})
    assert (rc, filed, switched) == (1, [], [])
    assert "SAME token" in capsys.readouterr().out


def test_import_switches_the_live_account_when_its_verified_key_changed(run_import):
    """A verified new key for the account already live is installed in place."""
    rc, filed, switched = run_import(
        "a@x.com,%s\n" % TOK_A,
        state={"live_email": "a@x.com", "live_fp": "stale-fp"}, statuses={TOK_A: "ok"})
    assert (rc, filed, switched) == (0, ["a@x.com"], ["a@x.com"])


def test_import_will_not_install_an_unverified_key_over_a_working_one(run_import, capsys):
    """Nobody answered for the key, and the live credential still works — do not swap."""
    rc, filed, switched = run_import(
        "a@x.com,%s\n" % TOK_A,
        state={"live_email": "a@x.com", "live_fp": "stale-fp"},
        statuses={TOK_A: "unverified"}, live_expired=False)
    assert switched == []
    assert filed == ["a@x.com"], "an unverified key is still FILED — only the swap is refused"
    assert rc == 0
    assert "NOT verified" in capsys.readouterr().out


def test_import_installs_an_unverified_key_when_the_live_one_is_already_expired(run_import):
    """Unknown beats known-dead: an expired live credential has nothing left to protect."""
    rc, filed, switched = run_import(
        "a@x.com,%s\n" % TOK_A,
        state={"live_email": "a@x.com", "live_fp": "stale-fp"},
        statuses={TOK_A: "unverified"}, live_expired=True)
    assert switched == ["a@x.com"]
    assert rc == 0


def test_import_skips_the_swap_when_the_live_credential_is_already_that_key(run_import, capsys):
    """Re-running must not rewrite the keychain with the credential already in use."""
    rc, filed, switched = run_import(
        "a@x.com,%s\n" % TOK_A,
        state={"live_email": "a@x.com", "live_fp": _fp(TOK_A)}, statuses={TOK_A: "ok"})
    assert switched == []
    assert "already this key" in capsys.readouterr().out


def test_import_never_switches_to_an_account_that_is_not_live(run_import):
    """Importing a non-live account's key files it and touches the live credential not at all."""
    rc, filed, switched = run_import(
        "b@x.com,%s\n" % TOK_B,
        state={"live_email": "a@x.com", "live_fp": "stale-fp"}, statuses={TOK_B: "ok"})
    assert (rc, filed, switched) == (0, ["b@x.com"], [])


def test_import_partial_success_exits_zero_and_names_what_failed(run_import, capsys):
    """One revoked key among good ones is reported, not turned into a whole-run failure."""
    rc, filed, switched = run_import(
        "a@x.com,%s\nb@x.com,%s\n" % (TOK_A, TOK_B),
        state={}, statuses={TOK_A: "ok", TOK_B: "bad"})
    assert rc == 0, "an agent must not retry the whole import because one key was revoked"
    assert filed == ["a@x.com"]
    assert "not filed: b@x.com" in capsys.readouterr().out


def test_import_exits_one_when_nothing_could_be_filed(run_import):
    """Every key refused means nothing landed — that is the failure the exit code is for."""
    rc, filed, switched = run_import(
        "a@x.com,%s\n" % TOK_A, state={}, statuses={TOK_A: "bad"})
    assert (rc, filed) == (1, [])


def test_import_exits_two_when_the_key_file_is_missing(monkeypatch, tmp_path):
    """A missing file is a usage error, matching rotator.py's own exit vocabulary."""
    monkeypatch.setattr(sys, "argv",
                        ["import_oauth_tokens.py", "--csv", str(tmp_path / "nope.csv")])
    assert imp.main() == 2


def _write_lock(d: Path, pid: int) -> Path:
    p = d / imp.SERVER_TICK_LOCK
    p.write_text("%d\t2026-09-09T12:00:00.000Z\n" % pid, encoding="utf-8")
    return p


def test_server_lock_absent_means_no_holder(tmp_path, monkeypatch):
    """No lockfile at all is the normal case — the import proceeds."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    assert imp.server_tick_holder() is None


def test_server_lock_held_by_a_live_pid_blocks_the_import(tmp_path, monkeypatch):
    """A live holder must stop the import — this is the whole point of the check."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    _write_lock(tmp_path, os.getpid())  # our own pid is definitely alive
    assert imp.server_tick_holder() == os.getpid()


def test_server_lock_held_by_a_dead_pid_is_not_a_holder(tmp_path, monkeypatch):
    """A crashed tick must not block the import forever."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    _write_lock(tmp_path, 999_999_999)  # not a live pid
    assert imp.server_tick_holder() is None


def test_server_lock_older_than_the_stale_window_is_not_a_holder(tmp_path, monkeypatch):
    """Past the server's own five-minute window the lock is abandoned, live pid or not."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    p = _write_lock(tmp_path, os.getpid())
    old = time.time() - (imp.SERVER_STALE_S + 60)
    os.utime(p, (old, old))
    assert imp.server_tick_holder() is None


@pytest.mark.parametrize("body", ["", "not-a-pid\t2026", "\t", "-1\tx"])
def test_server_lock_corrupt_content_is_not_a_holder(tmp_path, monkeypatch, body):
    """A corrupt lockfile is reclaimable to the server, so it must not block us either."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    (tmp_path / imp.SERVER_TICK_LOCK).write_text(body, encoding="utf-8")
    assert imp.server_tick_holder() is None


def test_server_lock_check_never_removes_or_creates_the_lockfile(tmp_path, monkeypatch):
    """OBSERVE ONLY. Deleting a lock a live tick holds is the one way this could do harm."""
    monkeypatch.setattr(imp.gs, "global_state_dir", lambda: tmp_path)
    p = _write_lock(tmp_path, 999_999_999)  # dead pid: the tempting case to "clean up"
    before = p.read_text(encoding="utf-8")
    imp.server_tick_holder()
    assert p.exists(), "the check must never unlink another project's lock"
    assert p.read_text(encoding="utf-8") == before
    imp.server_tick_holder()  # and it must not CREATE one either, when absent
    p.unlink()
    imp.server_tick_holder()
    assert not (tmp_path / imp.SERVER_TICK_LOCK).exists()


def test_import_refuses_while_a_live_tick_holds_the_lock(tmp_path, monkeypatch, capsys):
    """main() stops before touching the CSV or the keychain when a tick is running."""
    csv = tmp_path / "keys.csv"
    csv.write_text("a@x.com,%s\n" % ("a" * 40), encoding="utf-8")
    csv.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["import_oauth_tokens.py", "--csv", str(csv)])
    monkeypatch.setattr(imp, "server_tick_holder", lambda: 4242)
    called: list[str] = []
    monkeypatch.setattr(imp.rotator, "file_slot",
                        lambda *a, **k: called.append("filed") or True)
    assert imp.main() == 1
    assert called == [], "nothing may be written when the import refuses"
    assert "NOT RUNNING" in capsys.readouterr().out


def test_secure_warns_but_does_not_chmod_a_path_the_user_named(tmp_path, capsys):
    """--csv may point at a file that is group-readable on purpose — warn, never mutate it."""
    other = tmp_path / "shared.csv"
    other.write_text("x", encoding="utf-8")
    other.chmod(0o644)
    imp._secure(other)
    assert other.stat().st_mode & 0o777 == 0o644
    assert "Not changing it" in capsys.readouterr().out
