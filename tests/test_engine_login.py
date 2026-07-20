"""Parser-level tests for the headless subscription login (engine_login).

The full OAuth round-trip needs a real subscription + browser, so here we only
pin the brittle bits: stripping the TUI's ANSI noise and extracting the authorize
URL and the token from realistic (wrapped, colored) terminal output.
"""

from agenthook import engine_login as el

# A trimmed capture of `claude setup-token` over a PTY: ANSI colors, cursor moves,
# and the URL printed across colored segments.
_URL = (
    "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88"
    "ed-5944d1962f5e&response_type=code&redirect_uri=https%3A%2F%2Fplatform.claude.com"
    "%2Foauth%2Fcode%2Fcallback&scope=user%3Ainference&code_challenge=XCju3JXL"
    "&code_challenge_method=S256&state=joaWXQdIPaIc"
)
_TUI_URL = (
    "\x1b[?25l\x1b[31mWelcome\x1b[9Gto\x1b[12GClaude\x1b[39m\r\n"
    "\x1b[37mBrowser didn't open? Use the url below to sign in (c to copy)\x1b[39m\r\n"
    f"\x1b[37m{_URL}\x1b[39m\r\n"
    "\x1b[2GPaste\x1b[8Gcode\x1b[13Ghere\x1b[18Gif\x1b[21Gprompted\x1b[30G> "
)


def test_strip_ansi_removes_escapes():
    cleaned = el._clean(_TUI_URL)
    assert "\x1b" not in cleaned
    assert "[37m" not in cleaned and "[9G" not in cleaned


def test_url_extracted_from_tui_output():
    m = el._URL_RE.search(el._clean(_TUI_URL))
    assert m and m.group(0) == _URL


def test_token_extracted_and_masked():
    token = "sk-ant-oat01-AbC123_def-XYZ456ghiJKL789mnoPQR"
    out = f"\x1b[32mSuccess!\x1b[39m\r\nYour token:\r\n\x1b[1m{token}\x1b[22m\r\n"
    m = el._TOKEN_RE.search(el._clean(out))
    assert m and m.group(0) == token
    # The masked diagnostic must never leak the token.
    assert token not in el._mask(out)
    assert "sk-ant-***" in el._mask(out)


def test_url_pattern_ignores_unrelated_https():
    assert el._URL_RE.search("see https://docs.example.com/help for more") is None


class _FakeProc:
    """Stand-in for the held setup-token subprocess (never really spawned)."""

    def poll(self):
        return 0

    def send_signal(self, sig):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_submit_code_sends_code_then_bare_cr(monkeypatch):
    """Regression: the setup-token TUI (Ink, raw mode) only submits on a carriage
    return delivered as its OWN write. Two verified failure modes this pins
    against: a line feed ("\\n") is never read as Enter, and a CR glued to the
    pasted code in one write is swallowed as paste text — either way the code
    sits unsubmitted and the flow times out. Contract: write the stripped code
    first, then a bare b"\\r" as a separate write.
    """
    writes: list[bytes] = []
    monkeypatch.setattr(el.os, "write", lambda fd, data: (writes.append(data), len(data))[1])
    monkeypatch.setattr(el, "_SUBMIT_SETTLE_S", 0)  # no real delay in the test
    # Skip real PTY IO: pretend the token appeared right after the submit.
    token = "sk-ant-oat01-RegressionToken_0123456789"
    monkeypatch.setattr(el, "_drain", lambda *a, **k: (f"...{token}...", token))
    monkeypatch.setattr(el, "_kill", lambda sess: None)

    sid = "sess-regression"
    el._SESSIONS[sid] = el._Session(proc=_FakeProc(), master_fd=-1, instance="x", buf="")
    try:
        out = el.submit_code(sid, "  the-code#state  ")
    finally:
        el._SESSIONS.pop(sid, None)

    assert out == token
    # 1) the code is written first, stripped, with NO terminator glued on
    assert writes[0] == b"the-code#state"
    # 2) Enter is a bare carriage return, sent as a SEPARATE write
    assert writes[1] == b"\r"
    # 3) never a line feed anywhere, and never a CR concatenated onto the code
    joined = b"".join(writes)
    assert b"\n" not in joined
    assert not any(w.endswith(b"\r") and len(w) > 1 for w in writes)
