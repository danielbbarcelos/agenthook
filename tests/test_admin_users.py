"""Native-UI admin accounts: scrypt password hashing, stdlib TOTP, user store."""

import time

import pytest

from agenthook import admin_users as au


# --- password (scrypt) ------------------------------------------------------


def test_password_hash_roundtrip():
    h = au.hash_password("s3cret-pw")
    assert h.startswith("scrypt$")
    assert au.verify_password("s3cret-pw", h)
    assert not au.verify_password("wrong-pw", h)


def test_password_hash_is_salted():
    assert au.hash_password("same") != au.hash_password("same")  # random salt each time


def test_verify_rejects_garbage():
    assert not au.verify_password("x", "not-a-hash")
    assert not au.verify_password("x", "")


# --- TOTP (RFC 6238) --------------------------------------------------------


def _wrong_code(secret, now):
    valid = {au._totp(secret, int(now // 30) + w) for w in (-1, 0, 1)}
    return next(f"{i:06d}" for i in range(10) if f"{i:06d}" not in valid)


def test_totp_roundtrip_and_skew():
    secret = au.generate_totp_secret()
    now = 1_700_000_000
    code = au._totp(secret, int(now // 30))
    assert au.verify_totp(secret, code, now=now)
    assert au.verify_totp(secret, code, now=now + 29)       # same step
    assert au.verify_totp(secret, code, now=now + 30)       # +/-1 window tolerated
    assert not au.verify_totp(secret, code, now=now + 300)  # far out of window
    assert not au.verify_totp(secret, _wrong_code(secret, now), now=now)


# --- user store -------------------------------------------------------------


def test_user_crud():
    au.create_user("admin", "pw1")
    assert au.count_users() == 1
    with pytest.raises(ValueError):
        au.create_user("admin", "pw2")  # duplicate rejected
    u = au.get_user("admin")
    assert u and u.username == "admin" and not u.totp_enabled
    au.set_password("admin", "pw2")
    assert au.authenticate("admin", "pw2")
    assert not au.authenticate("admin", "pw1")
    au.delete_user("admin")
    assert au.get_user("admin") is None
    assert au.count_users() == 0


def test_set_password_missing_user_raises():
    with pytest.raises(ValueError):
        au.set_password("ghost", "x")


def test_authenticate_with_totp_required():
    au.create_user("a", "pw")
    secret = au.generate_totp_secret()
    au.set_totp_secret("a", secret)
    now = time.time()
    # once TOTP is enrolled, password alone (or a wrong code) is not enough
    assert not au.authenticate("a", "pw")
    assert not au.authenticate("a", "pw", _wrong_code(secret, now))
    good = au._totp(secret, int(now // 30))
    assert au.authenticate("a", "pw", good)


def test_authenticate_unknown_user():
    assert not au.authenticate("nobody", "pw")
