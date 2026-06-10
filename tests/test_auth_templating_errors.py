import hashlib
import hmac

from agenthook import approval, auth, secrets, templating
from agenthook.errors import ErrorClass, classify_text
from agenthook.instances import Instance, save


def _instance_with(scheme, **kw):
    inst = Instance(name="demo", webhook_auth={"schemes": [scheme], **kw})
    save(inst)
    secrets.generate_key(inst)
    return inst


def test_bearer_auth(monkeypatch):
    inst = _instance_with("bearer")
    secrets.get_backend(inst).set(inst, "AGENTHOOK_WEBHOOK_TOKEN", "tok", True)
    ok, _ = auth.check_auth(inst, {"Authorization": "Bearer tok"}, b"", None)
    assert ok
    bad, _ = auth.check_auth(inst, {"Authorization": "Bearer nope"}, b"", None)
    assert not bad


def test_hmac_auth():
    inst = _instance_with("hmac")
    secrets.get_backend(inst).set(inst, "AGENTHOOK_WEBHOOK_SECRET", "s3cr3t", True)
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    ok, _ = auth.check_auth(inst, {"X-Agenthook-Signature": sig}, body, None)
    assert ok
    bad, _ = auth.check_auth(inst, {"X-Agenthook-Signature": "sha256=bad"}, body, None)
    assert not bad


def test_ip_allow():
    inst = _instance_with("ip-allow", ip_allow=["10.0.0.0/8"])
    assert auth.check_auth(inst, {}, b"", "10.1.2.3")[0]
    assert not auth.check_auth(inst, {}, b"", "192.168.1.1")[0]


def test_no_auth_is_open():
    inst = Instance(name="demo")
    save(inst)
    assert auth.check_auth(inst, {}, b"", None)[0]


def test_prompt_precedence(instance):
    inst = instance
    inst.templates = {"ticket": "T:{{ requester.name }}"}
    inst.default_prompt = "DEFAULT"
    save(inst)
    ctx = templating.build_context({"request_type": "ticket", "requester": {"name": "D"}}, {})
    assert templating.resolve_prompt(inst, {"prompt": "EXPLICIT"}, ctx) == "EXPLICIT"
    assert templating.resolve_prompt(inst, {"request_type": "ticket"}, ctx) == "T:D"
    assert templating.resolve_prompt(inst, {}, ctx) == "DEFAULT"


def test_context_excludes_secrets(instance):
    inst = instance
    inst.context_template = "p={{ env.PUB }} s={{ env.get('SEC','') }}"
    ctx = templating.build_context({}, {"PUB": "ok"})
    rendered = templating.render_context_file(inst, ctx)
    assert "ok" in rendered and "SEC" not in rendered


def test_mcp_interpolation(instance):
    inst = instance
    inst.mcp = {"pg": {"env": {"URL": "{{ env.DB }}"}}}
    out = templating.render_mcp(inst, {"DB": "postgres://x"})
    assert out["mcpServers"]["pg"]["env"]["URL"] == "postgres://x"


def test_error_classification():
    assert classify_text("HTTP 429 rate limit").error_class is ErrorClass.RATE_LIMIT
    assert classify_text("503 overloaded").error_class is ErrorClass.SERVER
    assert classify_text("403 forbidden").error_class is ErrorClass.AUTH
    assert classify_text("boom", exit_code=2).error_class is ErrorClass.ENGINE_CRASH


def test_approval_token_roundtrip_and_tamper():
    secret = "k"
    tok = approval.make_token(secret, "j1", "approve", ttl=60)
    assert approval.verify_token(secret, "j1", "approve", tok)
    assert not approval.verify_token(secret, "j1", "reject", tok)  # action mismatch
    assert not approval.verify_token(secret, "j2", "approve", tok)  # job mismatch
    assert not approval.verify_token(secret, "j1", "approve", "0." + tok.split(".")[1])  # expired
