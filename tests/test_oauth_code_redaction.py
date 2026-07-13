"""The OAuth authorization code must never reach disk or a log (audit finding 2).

Both rotator re-auth paths handle a `<code>#<state>` pair that the consent page renders and
we paste into the CLI. It is credential material: single-use and short-lived, so it is inert
once claude exchanges it — but if the exchange FAILS, a code we persisted stays valid for its
full lifetime (minutes), readable by any same-user process and replayable.

`slot_capture_browser`'s own docstring promises "no token is printed or logged". These pin it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROTATOR_DIR = Path(__file__).resolve().parent.parent / "scripts" / "oauth_rotator"


def _load(name: str):
    """Import a rotator entry-point script by path (they live outside any package)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", _ROTATOR_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reauth = _load("reauth")


def test_pane_dump_redacts_the_authorization_code() -> None:
    """reauth pastes the code with `tmux send-keys`, so it is ON THE PANE — and every pane
    dump we log would carry it. The `<code>#<state>` pair must be masked."""
    code = "aBcD1234efGh5678IjKlMnOpQrStUvWx#Zy9876543210"
    pane = f"Paste code here > {code}\nLogin successful.\n"
    out = reauth._redact(pane)
    assert code not in out
    assert "aBcD1234efGh5678IjKlMnOpQrStUvWx" not in out   # not even the code half
    assert "<code#state redacted>" in out
    assert "Login successful." in out                      # the diagnostic value survives


def test_redaction_leaves_ordinary_pane_text_alone() -> None:
    """Over-redacting a diagnostic dump defeats the reason we print it — only the pair goes."""
    pane = "claude auth login\nIf the browser didn't open, visit: https://claude.ai/oauth/authorize?x=1\n"
    assert reauth._redact(pane) == pane


def test_redaction_is_applied_to_every_pane_dump() -> None:
    """Not just the post-paste ones: the paste can land between our capture and our log, so
    redacting only the sites we think are 'after' the paste would be a race."""
    src = (_ROTATOR_DIR / "reauth.py").read_text(encoding="utf-8")
    dumps = [
        ln for ln in src.splitlines()
        if "log(" in ln and "capture_pane(" in ln and not ln.strip().startswith("#")
    ]
    assert dumps, "no pane dumps found — did the log sites move?"
    assert all("_redact(capture_pane" in ln for ln in dumps), dumps


def test_the_callback_page_is_never_screenshotted() -> None:
    """The /oauth/code/callback page RENDERS the `<code>#<state>` for manual copy, so a PNG of
    it is a live credential sitting on disk under ROOT — overwritten only by the next capture.
    The consent screenshot is the diagnostic one, and that page shows no code."""
    src = (_ROTATOR_DIR / "slot_capture_browser.py").read_text(encoding="utf-8")
    code_lines = [
        ln for ln in src.splitlines()
        if "screenshot(" in ln and not ln.strip().startswith("#")
    ]
    assert code_lines, "no screenshot call found — did the capture flow move?"
    assert all("callback" not in ln for ln in code_lines), code_lines
    assert "capture-callback.png" not in src
