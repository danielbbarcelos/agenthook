"""GitHub App ephemeral tokens: JWT signing, minting (mock API), caching,
revocation, and the runner's host-side git-env injection."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agenthook import github_app


@pytest.fixture(scope="module")
def rsa_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_app_jwt_is_signed_and_verifies(rsa_key):
    key, pem = rsa_key
    tok = github_app._app_jwt("12345", pem, now=1_000_000)
    header_b64, payload_b64, sig_b64 = tok.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload["iss"] == "12345" and payload["exp"] - payload["iat"] == 600

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signing_input = f"{header_b64}.{payload_b64}".encode()
    key.public_key().verify(
        _b64url_decode(sig_b64), signing_input, padding.PKCS1v15(), hashes.SHA256()
    )  # raises if invalid


class _MockGH(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        type(self).calls += 1
        body = json.dumps({"token": "ghs_minted", "expires_at": "2999-01-01T00:00:00Z"}).encode()
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def mock_gh():
    _MockGH.calls = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockGH)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_mint_and_cache(rsa_key, mock_gh):
    github_app._CACHE.clear()
    cfg = github_app.AppConfig("1", "42", rsa_key[1])
    tok, exp = github_app.mint(cfg, api=mock_gh)
    assert tok == "ghs_minted"
    # second call (unscoped) is served from cache — no extra HTTP hit
    tok2, _ = github_app.mint(cfg, api=mock_gh)
    assert tok2 == "ghs_minted"
    assert _MockGH.calls == 1


def test_scoped_mint_bypasses_cache(rsa_key, mock_gh):
    github_app._CACHE.clear()
    cfg = github_app.AppConfig("1", "42", rsa_key[1])
    github_app.mint(cfg, api=mock_gh)  # unscoped -> cached (1 call)
    github_app.mint(cfg, repositories=["repo-a"], api=mock_gh)  # scoped -> fresh (2)
    assert _MockGH.calls == 2


def test_auth_extraheader_format():
    h = github_app.auth_extraheader("ghs_x")
    assert h.startswith("AUTHORIZATION: basic ")
    decoded = base64.b64decode(h.split("basic ", 1)[1]).decode()
    assert decoded == "x-access-token:ghs_x"


def test_app_config_incomplete_returns_none():
    store = {"AGENTHOOK_GH_APP_ID": "1"}  # missing installation + key
    assert github_app.AppConfig.from_secrets(store.get) is None


# --- runner git-env injection ------------------------------------------------


def test_git_env_injects_token(tmp_path, monkeypatch):
    from agenthook.config import Config
    from agenthook.engines import get_engine
    from agenthook.instances import Instance, RepoRef
    from agenthook.models import Deliverable, Job
    from agenthook.runner import RunContext, _git_env

    inst = Instance(name="g", engine="claude", repos=[{"url": "https://github.com/o/r", "name": "r"}])
    ctx = RunContext(
        job=Job(instance="g", deliverable=Deliverable.PR, prompt="x"),
        inst=inst, cfg=Config(use_docker=False), engine=get_engine("claude"),
        env_all={}, env_nonsecret={},
    )
    ctx.repos = [RepoRef(name="r", url="https://github.com/o/r", branch_base="main")]
    monkeypatch.setattr("agenthook.runner._mint_git_token", lambda c: "ghs_tok")
    env = _git_env(ctx)
    assert env["GH_TOKEN"] == "ghs_tok" and env["GITHUB_TOKEN"] == "ghs_tok"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert "github.com/.extraheader" in env["GIT_CONFIG_KEY_0"]
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")


def test_git_env_no_app_is_plain(tmp_path, monkeypatch):
    from agenthook.config import Config
    from agenthook.engines import get_engine
    from agenthook.instances import Instance
    from agenthook.models import Deliverable, Job
    from agenthook.runner import RunContext, _git_env

    ctx = RunContext(
        job=Job(instance="g", deliverable=Deliverable.PR, prompt="x"),
        inst=Instance(name="g", engine="claude"), cfg=Config(use_docker=False),
        engine=get_engine("claude"), env_all={"GH_TOKEN": "static"}, env_nonsecret={},
    )
    monkeypatch.setattr("agenthook.runner._mint_git_token", lambda c: None)
    env = _git_env(ctx)
    assert "GIT_CONFIG_COUNT" not in env
    assert env["GH_TOKEN"] == "static"  # falls back to the instance's static creds
