"""Tests for the admin sign-in logic (no browser needed)."""
import time

import pytest

from payslip_core import auth, ui


import os

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(auth, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)


def make(totp=False):
    return auth.Credentials("boss", auth.hash_password("Correct-Horse-9!"), auth.new_totp_secret() if totp else "")


def test_hash_roundtrip_and_salt():
    h1, h2 = auth.hash_password("Abc-12345678"), auth.hash_password("Abc-12345678")
    assert h1 != h2 and "Abc-12345678" not in h1
    assert auth.verify_password("Abc-12345678", h1)
    assert not auth.verify_password("abc-12345678", h1)
    assert not auth.verify_password("x", "garbage")


def test_password_rules():
    assert auth.password_problem("short1!A")
    assert auth.password_problem("aaaaaaaaaaaaaaaa")
    assert auth.password_problem("alllowercaseletters")
    assert auth.password_problem("Correct-Horse-9!") is None


def test_login_ok_and_wrong():
    c = make()
    assert auth.check_login("boss", "Correct-Horse-9!", "", c)[0]
    ok, msg = auth.check_login("boss", "nope", "", c)
    assert not ok and "incorrect" in msg
    assert not auth.check_login("other", "Correct-Horse-9!", "", c)[0]   # wrong user, right password


def test_lockout_after_repeated_failures_and_recovery():
    c = make()
    t = 1_000_000.0
    for _ in range(auth.FREE_ATTEMPTS):
        auth.check_login("boss", "bad", "", c, now=t)
    assert auth.lock_remaining(t) > 0
    ok, msg = auth.check_login("boss", "Correct-Horse-9!", "", c, now=t + 1)   # right password is refused while locked
    assert not ok and "Too many" in msg
    assert auth.check_login("boss", "Correct-Horse-9!", "", c, now=t + auth.BASE_LOCK_S + 5)[0]
    assert auth.lock_remaining(t + auth.BASE_LOCK_S + 6) == 0


def test_lockout_grows():
    c = make()
    t = 2_000_000.0
    for _ in range(auth.FREE_ATTEMPTS + 2):
        t_now = t + 10_000 * _          # always past the previous lock
        auth.check_login("boss", "bad", "", c, now=t_now)
    assert auth.lock_remaining(t_now) >= auth.BASE_LOCK_S * 2


def test_totp_required_and_replay_blocked():
    c = make(totp=True)
    now = 1_700_000_000.0
    code = auth._hotp(c.totp_secret, auth.totp_counter(now))
    assert not auth.check_login("boss", "Correct-Horse-9!", "", c, now=now)[0]          # no code
    assert not auth.check_login("boss", "Correct-Horse-9!", "000000", c, now=now)[0]    # wrong code
    assert auth.check_login("boss", "Correct-Horse-9!", code, c, now=now)[0]
    assert not auth.check_login("boss", "Correct-Horse-9!", code, c, now=now)[0]        # same code reused


def test_totp_known_vector():
    # RFC 6238 test secret "12345678901234567890" -> base32 below; T=59s -> 94287082 (8 digits) => last 6 = 287082
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert auth._hotp(secret, 59 // 30) == "287082"


def test_session_timeouts():
    s = auth.new_session(now=1000)
    assert auth.session_state_valid(s, now=1000 + 60)
    assert not auth.session_state_valid(s, now=1000 + auth.IDLE_TIMEOUT_S + 1)
    s["last"] = 1000 + auth.MAX_SESSION_S
    assert not auth.session_state_valid(s, now=1000 + auth.MAX_SESSION_S + 5)
    assert not auth.session_state_valid(None) and not auth.session_state_valid({})


def test_not_configured_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_FILE", tmp_path / "none.json")
    for k in list(os.environ.keys()):
        if any(term in k.upper() for term in ("PAYSLIP_ADMIN", "ENV_USER", "ENV_PASS", "TOTP_SECRET")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(auth, "_secret_from_streamlit", lambda n: "")
    assert auth.load_credentials() is None


def test_environment_credentials_take_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_FILE", tmp_path / "admin.json")
    auth.save_credentials_file(auth.Credentials("file-admin", "file-hash", "file-totp"))
    monkeypatch.setenv("PAYSLIP_ADMIN_USER", "env-admin")
    monkeypatch.setenv("PAYSLIP_ADMIN_HASH", "env-hash")
    monkeypatch.setenv("PAYSLIP_ADMIN_TOTP", "env-totp")
    assert auth.load_credentials() == auth.Credentials("env-admin", "env-hash", "env-totp")


def test_dotenv_credentials_load(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PAYSLIP_ADMIN_USER=dotenv-user\nPAYSLIP_ADMIN_HASH=dotenv-hash\nPAYSLIP_ADMIN_TOTP=dotenv-totp\n")
    monkeypatch.setattr(auth, "ENV_FILE", env_file)
    for k in list(os.environ.keys()):
        if any(term in k.upper() for term in ("PAYSLIP_ADMIN", "ENV_USER", "ENV_PASS", "TOTP_SECRET")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(auth, "_secret_from_streamlit", lambda n: "")
    creds = auth.load_credentials()
    assert creds == auth.Credentials("dotenv-user", "dotenv-hash", "dotenv-totp")


def test_dotenv_aliases_and_quote_cleaning(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'Env_username=custom-user\n'
        'ENV_password_hash=scrypt$custom$hash",\n'
        'totp_secret="MYTOTPKEY"\n'
    )
    monkeypatch.setattr(auth, "ENV_FILE", env_file)
    for k in list(os.environ.keys()):
        if any(term in k.upper() for term in ("PAYSLIP_ADMIN", "ENV_USER", "ENV_PASS", "TOTP_SECRET")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(auth, "_secret_from_streamlit", lambda n: "")
    creds = auth.load_credentials()
    assert creds == auth.Credentials("custom-user", "scrypt$custom$hash", "MYTOTPKEY")


def test_save_credentials_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(auth, "ENV_FILE", env_file)
    p = auth.save_credentials_env(auth.Credentials("saved-user", "saved-hash", "saved-totp"))
    assert p.exists()
    content = p.read_text()
    assert "PAYSLIP_ADMIN_USER=saved-user" in content
    assert "PAYSLIP_ADMIN_HASH=saved-hash" in content
    assert "PAYSLIP_ADMIN_TOTP=saved-totp" in content
    if os.name != "nt":
        assert oct(p.stat().st_mode)[-3:] == "600"


def test_credentials_file_private(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_FILE", tmp_path / "admin.json")
    p = auth.save_credentials_file(make())
    if os.name != "nt":
        assert oct(p.stat().st_mode)[-3:] == "600"
    for k in list(os.environ.keys()):
        if any(term in k.upper() for term in ("PAYSLIP_ADMIN", "ENV_USER", "ENV_PASS", "TOTP_SECRET")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(auth, "_secret_from_streamlit", lambda n: "")
    assert auth.load_credentials().username == "boss"


def test_escaping_helpers():
    assert "<script>" not in ui.esc("<script>alert(1)</script>")
    out = ui.md_esc("[click](http://evil) ![x](y) <b>hi</b> `code`")
    assert "](" not in out.replace("\\]\\(", "") and "<b>" not in out


def test_purge_only_touches_generated_folders(tmp_path):
    from payslip_core.output import purge_outputs
    (tmp_path / "2083-05" / "individual").mkdir(parents=True)
    (tmp_path / "2083-05" / "individual" / "a.pdf").write_bytes(b"x")
    (tmp_path / "2083-05_v2").mkdir()
    (tmp_path / "keep_me").mkdir()
    assert purge_outputs(older_than_hours=1, base=tmp_path) == 0          # too new
    assert purge_outputs(base=tmp_path) == 2
    assert (tmp_path / "keep_me").exists()
